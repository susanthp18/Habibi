"""PSTN control-plane seam. Every call is placed and carried by PayInt Voice
Studio (the engine dials with its own telephony and runs the conversation, see
``voice_studio``).

``outbound.place``, warm transfer and the dial endpoints call here rather than
``voice_studio`` directly, so the dialler reads the same whatever carries the
call. The Twilio media-stream runner and the Asterisk adapter that used to sit
behind it were retired with the legacy voice runtime.
"""

from __future__ import annotations

from typing import Any

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
    return "studio"


def _adapter() -> Any:
    import voice_studio

    return voice_studio


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
    """Whether Voice Studio has what it needs to place a call."""
    return bool(_adapter().configured())


def preflight() -> list[str]:
    """Problems that would make a dial silently useless, for operator tooling."""
    return list(_adapter().preflight())
