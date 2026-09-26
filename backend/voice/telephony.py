"""PSTN control-plane seam: Twilio or Asterisk behind one set of functions.

``outbound.place``, warm transfer and the dial endpoints call here. Unset
``TELEPHONY_PROVIDER`` keeps Twilio; the telephony compose overlay sets
``asterisk``; ``studio`` hands the call to PayInt Voice Studio (the engine
places it with its own telephony and runs the conversation, see
``voice_studio``). Nothing outside the adapters should import ``twilio_ops`` or
``asterisk_ops`` to decide whether a call can be placed.
"""

from __future__ import annotations

from typing import Any

from env_loader import env_str, load_env
from voice.twilio_ops import OutboundDisabled

__all__ = [
    "OutboundDisabled",
    "configured",
    "default_from_number",
    "hangup",
    "originate",
    "preflight",
    "provider_name",
    "warm_transfer",
]


def provider_name() -> str:
    load_env()
    raw = (env_str("TELEPHONY_PROVIDER") or "twilio").lower()
    if raw in {"studio", "voice-studio", "agentstudio"}:
        return "studio"
    return "asterisk" if raw in {"asterisk", "sip"} else "twilio"


def _adapter() -> Any:
    if provider_name() == "studio":
        import voice_studio

        return voice_studio
    if provider_name() == "asterisk":
        from voice import asterisk_ops

        return asterisk_ops
    from voice import twilio_ops

    return twilio_ops


def originate(
    *,
    to: str,
    custom: dict[str, str] | None = None,
    machine_detection: bool = False,
    from_number: str | None = None,
) -> dict[str, Any]:
    return _adapter().originate(
        to=to,
        custom=custom,
        machine_detection=machine_detection,
        from_number=from_number,
    )


def warm_transfer(channel_id: str, *, reason: str = "customer_requested") -> dict[str, Any]:
    return _adapter().warm_transfer(channel_id, reason=reason)


def hangup(channel_id: str) -> None:
    _adapter().hangup(channel_id)


def default_from_number() -> str:
    return (_adapter().default_from_number() or "").strip()


def configured() -> bool:
    """Whether the selected provider has what it needs to place a call."""
    return bool(_adapter().configured())


def preflight() -> list[str]:
    """Problems that would make a dial silently useless, for operator tooling."""
    return list(_adapter().preflight())
