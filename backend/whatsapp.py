"""Meta WhatsApp Cloud API helpers (inbound verify + outbound send).

Inbound Meta webhooks are separate from outbound CRM webhook_endpoints.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from typing import Any

from env_loader import load_env


def _read_env(key: str, default: str | None = None) -> str | None:
    load_env()
    value = os.getenv(key)
    if value is not None and value != "":
        return value
    return default


def config() -> dict[str, str | None]:
    return {
        "app_id": _read_env("META_APP_ID"),
        "app_secret": _read_env("WHATSAPP_APP_SECRET"),
        "token": _read_env("WHATSAPP_TOKEN"),
        "phone_number_id": _read_env("WHATSAPP_PHONE_NUMBER_ID"),
        "waba_id": _read_env("WHATSAPP_WABA_ID"),
        "display_number": _read_env("WHATSAPP_DISPLAY_NUMBER"),
        "api_version": _read_env("WHATSAPP_API_VERSION", "v25.0"),
        "verify_token": _read_env("WHATSAPP_VERIFY_TOKEN"),
        "public_base_url": _read_env("PUBLIC_BASE_URL"),
    }


def normalize_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits


def verify_signature(app_secret: str | None, raw_body: bytes, header: str | None) -> bool:
    """Validate X-Hub-Signature-256 = sha256=<hex>."""
    if not app_secret or not header:
        return False
    prefix = "sha256="
    if not header.startswith(prefix):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = header[len(prefix) :].strip()
    return hmac.compare_digest(expected, provided)


def send_text_message(*, to_phone: str, body: str, preview_url: bool = False) -> dict[str, Any]:
    """Send a free-form WhatsApp text message. Raises ValueError on API/config errors."""
    import circuit_breaker

    return circuit_breaker.get_breaker("whatsapp_meta").call(
        _send_text_message_uncircuited,
        to_phone=to_phone,
        body=body,
        preview_url=preview_url,
    )


def _send_text_message_uncircuited(
    *, to_phone: str, body: str, preview_url: bool = False
) -> dict[str, Any]:
    """Send a free-form WhatsApp text message. Raises ValueError on API/config errors."""
    cfg = config()
    token = cfg["token"]
    phone_number_id = cfg["phone_number_id"]
    version = cfg["api_version"] or "v25.0"
    if not token or not phone_number_id:
        raise ValueError("whatsapp_not_configured")
    to = normalize_phone(to_phone)
    if not to:
        raise ValueError("whatsapp_missing_recipient")
    url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": bool(preview_url), "body": body},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(_classify_send_error(exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"whatsapp_send_failed:network:{exc.reason}") from exc


def send_template_message(
    *,
    to_phone: str,
    template_name: str,
    template_lang: str = "en_US",
    body_params: list[str] | None = None,
) -> dict[str, Any]:
    """Send a WhatsApp utility template. Raises ValueError on API/config errors."""
    import circuit_breaker

    return circuit_breaker.get_breaker("whatsapp_meta").call(
        _send_template_message_uncircuited,
        to_phone=to_phone,
        template_name=template_name,
        template_lang=template_lang,
        body_params=body_params,
    )


def _send_template_message_uncircuited(
    *,
    to_phone: str,
    template_name: str,
    template_lang: str = "en_US",
    body_params: list[str] | None = None,
) -> dict[str, Any]:
    cfg = config()
    token = cfg["token"]
    phone_number_id = cfg["phone_number_id"]
    version = cfg["api_version"] or "v25.0"
    if not token or not phone_number_id:
        raise ValueError("whatsapp_not_configured")
    to = normalize_phone(to_phone)
    if not to:
        raise ValueError("whatsapp_missing_recipient")
    if not (template_name or "").strip():
        raise ValueError("whatsapp_template_missing")
    url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"
    components: list[dict[str, Any]] = []
    if body_params:
        components.append(
            {
                "type": "body",
                "parameters": [{"type": "text", "text": str(p)} for p in body_params],
            }
        )
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name.strip(),
            "language": {"code": (template_lang or "en_US").strip() or "en_US"},
        },
    }
    if components:
        payload["template"]["components"] = components
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(_classify_send_error(exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"whatsapp_send_failed:network:{exc.reason}") from exc


def is_definite_client_error(err: str) -> bool:
    """True for config/token/4xx failures where a retry cannot succeed."""
    s = (err or "").strip().lower()
    if not s:
        return False
    if s in {
        "whatsapp_not_configured",
        "whatsapp_missing_recipient",
        "whatsapp_token_expired",
        "whatsapp_token_invalid",
    }:
        return True
    if "whatsapp_send_failed:network:" in s:
        return False
    if s.startswith("whatsapp_send_failed:"):
        parts = s.split(":", 2)
        if len(parts) >= 2:
            try:
                status = int(parts[1])
            except ValueError:
                return False
            if status in {408, 429, 500, 502, 503, 504}:
                return False
            if 400 <= status < 500:
                return True
            if status >= 500:
                return False
    return False


def is_ambiguous_transport_error(err: str) -> bool:
    """True when Meta may have accepted the message despite the client error."""
    s = (err or "").strip().lower()
    if "whatsapp_send_failed:network:" in s:
        return True
    if s.startswith("whatsapp_send_failed:"):
        parts = s.split(":", 2)
        if len(parts) >= 2:
            try:
                status = int(parts[1])
            except ValueError:
                return False
            return status in {408, 429, 500, 502, 503, 504}
    return False


def _classify_send_error(status: int, detail: str) -> str:
    """Map Meta Graph errors to stable machine codes the inbox UI can friendlify.

    Only the parsed diagnostic fields (code / error_subcode / error_user_msg)
    are carried forward. The raw Graph body echoes request context — recipient
    number, message text, access-token fragments in `error_data`, `fbtrace_id`
    — and this string is persisted to bot_turn_jobs.error /
    whatsapp_outbound_jobs.error and written to the application log.
    """
    code = None
    subcode = None
    message = ""
    user_msg = ""
    try:
        payload = json.loads(detail) if detail else {}
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict):
            code = err.get("code")
            subcode = err.get("error_subcode")
            message = str(err.get("message") or "")
            user_msg = str(err.get("error_user_msg") or "")
    except json.JSONDecodeError:
        pass

    # OAuthException 190 = invalid/expired token; 463 = session expired.
    if status == 401 or code == 190:
        if subcode == 463 or "expired" in message.lower():
            return "whatsapp_token_expired"
        return "whatsapp_token_invalid"

    bits = []
    if code is not None:
        bits.append(f"code={code}")
    if subcode is not None:
        bits.append(f"subcode={subcode}")
    if user_msg:
        bits.append(f"user_msg={user_msg[:200]}")
    summary = " ".join(bits) or "unparsed_graph_error"
    return f"whatsapp_send_failed:{status}:{summary}"


def extract_wamid(send_response: dict[str, Any]) -> str | None:
    messages = send_response.get("messages") or []
    if not messages:
        return None
    return messages[0].get("id")
