"""Asterisk ARI client -- originate, transfer, hangup, and the calls the controller makes.

Every call enters the ``habibi`` Stasis application, so the controller
(``voice/asterisk_controller.py``) owns it end to end: answer, media, recording,
status. This module is the REST half; the controller holds the event socket.

Ids: an outbound SIP leg is created with ``channelId = att-<attempt>``, so
``call_attempts.provider_call_id``, the transfer target and the recording all
use one id. The call's bridge is ``br-<sip id>`` and its media leg ``<sip id>-m``,
derived rather than looked up.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from env_loader import env_str, load_env
from voice.twilio_ops import OutboundDisabled

logger = logging.getLogger(__name__)

APP = "habibi"
#: One JSON channel variable carries who the call is about (attempt, customer,
#: numbers). Defined here, not in the serializer, because dialling runs in the api
#: and bot_worker images, which do not have Pipecat.
CTX_VARIABLE = "HABIBI_CTX"
#: Set on the SIP leg just before a transfer moves it out of the app.
TRANSFER_VARIABLE = "HABIBI_TRANSFER"
#: Dialplan the media leg runs: Dial(WebSocket/habibi_bot). ARI cannot bridge a
#: chan_websocket channel directly -- it is not in the bridgeable channel
#: registry -- so the bot is reached through a Local channel into this extension.
MEDIA_ENDPOINT = "Local/bot@to-bot/n"
#: Pre-recorded apology+callback played when the bot's media leg never comes up.
#: Not TTS: the caller must hear a human recording, then the line drops.
UNREACHABLE_SOUND = "sound:habibi/bot-unreachable"
#: The pjsip endpoint render_config.py writes for the carrier leg.
TRUNK_ENDPOINT = "trunk"
#: Outbound SIP legs get this prefix plus the attempt id, so the controller can
#: tell a leg this product dialled from any other channel on the PBX.
OUTBOUND_ID_PREFIX = "att-"
#: Longest dial string treated as an internal extension rather than a phone number.
MAX_EXTENSION_DIGITS = 6

_DIGITS = re.compile(r"\D+")
_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")

__all__ = [
    "APP",
    "AriError",
    "CTX_VARIABLE",
    "OutboundDisabled",
    "MEDIA_ENDPOINT",
    "OUTBOUND_ID_PREFIX",
    "UNREACHABLE_SOUND",
    "bridge_id",
    "configured",
    "default_from_number",
    "hangup",
    "media_channel_id",
    "originate",
    "preflight",
    "warm_transfer",
]


class AriError(RuntimeError):
    """ARI answered with an error, or could not be reached.

    ``definitive`` is True when ARI replied at all: originate is synchronous, so a
    reply of any status means the channel was not created and a retry cannot
    double-dial. A timeout is not definitive.
    """

    def __init__(self, status: int | None, message: str, *, definitive: bool = True) -> None:
        super().__init__(f"ari {status or 'unreachable'}: {message}")
        self.status = status
        self.message = message
        self.definitive = definitive


def default_from_number() -> str:
    load_env()
    return env_str("ASTERISK_FROM_NUMBER") or ""


def bridge_id(sip_channel_id: str) -> str:
    return f"br-{sip_channel_id}"


def media_channel_id(sip_channel_id: str) -> str:
    return f"{sip_channel_id}-m"


def _ari_root() -> str:
    load_env()
    base = (env_str("ASTERISK_ARI_URL") or "http://asterisk:8088").rstrip("/")
    return base if base.endswith("/ari") else base + "/ari"


def _ari_auth_header() -> str:
    load_env()
    user, password = env_str("ASTERISK_ARI_USER"), env_str("ASTERISK_ARI_PASSWORD")
    if not (user and password):
        raise AriError(None, "ASTERISK_ARI_USER / ASTERISK_ARI_PASSWORD not configured")
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def configured() -> bool:
    load_env()
    return bool(env_str("ASTERISK_ARI_USER") and env_str("ASTERISK_ARI_PASSWORD"))


def ari(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    raw: bool = False,
    timeout: float = 10,
) -> Any:
    """One ARI request. Returns parsed JSON (``{}`` when empty), or bytes with ``raw``."""
    url = _ari_root() + path
    if query:
        # doseq: ARI list parameters (bridges addChannel) repeat the key.
        url += "?" + urllib.parse.urlencode(
            {k: v for k, v in query.items() if v is not None}, doseq=True
        )
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method.upper())
    req.add_header("Authorization", _ari_auth_header())
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            message = str(json.loads(detail).get("message") or json.loads(detail).get("error") or detail)
        except (ValueError, AttributeError):
            message = detail
        raise AriError(exc.code, message.strip()[:200]) from exc
    except TimeoutError as exc:
        raise AriError(None, "timed out", definitive=False) from exc
    except urllib.error.URLError as exc:
        # Refused or unresolvable: the request never reached Asterisk.
        raise AriError(None, str(exc.reason)[:200]) from exc
    if raw:
        return payload
    return json.loads(payload) if payload else {}


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _endpoint_for(to: str) -> str:
    digits = _DIGITS.sub("", to)
    if not digits:
        raise AriError(None, f"not a dialable number: {to!r}")
    if len(digits) <= MAX_EXTENSION_DIGITS:
        return f"PJSIP/{digits}"
    load_env()
    if not env_str("ASTERISK_TRUNK_HOST"):
        raise AriError(None, "no trunk configured for external numbers (ASTERISK_TRUNK_HOST)")
    number = "+" + digits if to.strip().startswith("+") else digits
    return f"PJSIP/{number}@{TRUNK_ENDPOINT}"


def originate(
    *,
    to: str,
    custom: dict[str, str] | None = None,
    machine_detection: bool = False,
    from_number: str | None = None,
) -> dict[str, Any]:
    """Dial ``to``; when answered the call enters the ``habibi`` Stasis app.

    ``custom`` is the attempt context ``outbound.place`` assembles. It rides on
    the SIP leg as one JSON variable, ``HABIBI_CTX``, which the controller copies
    onto the media leg so the bot knows which borrower it is calling.
    ``machine_detection`` is ignored: in-band AMD (``voice/amd.py``) is the detector.
    """
    import platform_switches

    if not platform_switches.outbound_enabled():
        logger.warning("outbound dial to %s refused -- outbound switch is OFF", to)
        raise OutboundDisabled("outbound_disabled: turn on outbound calling in Roles & access first")

    from voice.call_trace import event, redact_phone

    ctx = {k: str(v) for k, v in (custom or {}).items() if v not in (None, "")}
    attempt_id = ctx.get("attempt_id")
    channel_id = (
        _ID_UNSAFE.sub("-", f"{OUTBOUND_ID_PREFIX}{attempt_id}")
        if attempt_id
        else f"{OUTBOUND_ID_PREFIX}{uuid.uuid4().hex[:16]}"
    )
    from_number = (from_number or "").strip() or default_from_number()
    ctx.update(call_type="outbound", sip_channel_id=channel_id, to=to, **({"from": from_number} if from_number else {}))
    endpoint = _endpoint_for(to)
    load_env()
    ring_timeout = env_str("ASTERISK_RING_TIMEOUT") or "45"

    event("dial.requested", to=redact_phone(to), endpoint=endpoint, attempt=attempt_id, provider="asterisk")
    channel = ari(
        "POST",
        "/channels",
        query={
            "endpoint": endpoint,
            "app": APP,
            "appArgs": "outbound",
            "channelId": channel_id,
            "callerId": from_number or None,
            "timeout": ring_timeout,
        },
        body={"variables": {CTX_VARIABLE: json.dumps(ctx)}},
    )
    state = str(channel.get("state") or "Down")
    event("dial.placed", sid=channel_id, status=state, attempt=attempt_id, provider="asterisk")
    return {
        "callSid": channel_id,
        "provider_call_id": channel_id,
        "to": to,
        "status": state,
        "from": from_number or None,
        "provider": "asterisk",
    }


def warm_transfer(channel_id: str, *, reason: str = "customer_requested") -> dict[str, Any]:
    """Move the caller from the bot's bridge into the collectors queue.

    ``continue`` only works on a channel inside a Stasis application, which every
    Habibi call now is. The controller sees the SIP leg leave Stasis alive, hangs
    up the bot's media leg and records the attempt as transferred.
    """
    if not channel_id:
        raise AriError(None, "channel id required for warm transfer")
    # Tells the controller the SIP leg is leaving the app alive, not hanging up.
    ari(
        "POST",
        f"/channels/{_quote(channel_id)}/variable",
        query={"variable": TRANSFER_VARIABLE, "value": reason or "1"},
    )
    try:
        ari("POST", f"/bridges/{_quote(bridge_id(channel_id))}/removeChannel", query={"channel": channel_id})
    except AriError as exc:
        if exc.status not in (400, 404, 422):
            raise
    ari(
        "POST",
        f"/channels/{_quote(channel_id)}/continue",
        query={"context": "agents", "extension": "collectors", "priority": 1},
    )
    logger.info("Asterisk warm transfer channel=%s reason=%s", channel_id, reason)
    return {"ok": True, "mode": "warm", "channelId": channel_id, "reason": reason}


def hangup(channel_id: str, *, reason: str = "normal") -> None:
    if not channel_id:
        return
    try:
        ari("DELETE", f"/channels/{_quote(channel_id)}", query={"reason": reason})
    except AriError as exc:
        if exc.status != 404:
            logger.warning("Asterisk hangup failed channel=%s: %s", channel_id, exc)


def preflight() -> list[str]:
    """What stops a dial from working, as operator-readable problems."""
    if not configured():
        return ["ASTERISK_ARI_USER / ASTERISK_ARI_PASSWORD missing"]
    try:
        ari("GET", f"/applications/{APP}")
    except AriError as exc:
        if exc.status == 404:
            return ["the asterisk_controller is not connected (ARI app 'habibi' not registered)"]
        return [f"ARI unreachable: {exc}"]
    return []
