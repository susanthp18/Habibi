"""One traceable story per call, across four processes and a tunnel.

Why this exists
---------------
A call that answered and played silence took most of a day to narrow down, and
the reason was not difficulty -- it was that every hop logged in a different
vocabulary, or not at all:

* the dial logged a Twilio SID and nothing about the TwiML it sent, so "what did
  we actually ask Twilio to do" had no answer;
* the media socket logged only when uvicorn happened to accept it, so a socket
  that never arrived and a socket that was rejected looked identical -- both
  were silence in the log;
* ``voice.bot`` logged a ``VS-`` session id that appears nowhere near the
  ``CA-`` attempt id or the Twilio ``CAxxxx`` SID, so joining them was manual;
* and the pipeline's readiness -- the thing that decides whether a carrier waits
  or hangs up -- was not measured anywhere.

So the rule here is: **every hop of a call logs the same three ids and its own
timing**, at a level that reaches the log by default. A trace you have to enable
is a trace you do not have when it matters, which is the first time.

What a complete story looks like
--------------------------------
    voice.trace dial.requested   attempt=CA-… to=***2324 objective=dpd_reminder
    voice.trace dial.placed      attempt=CA-… sid=CAxxxx stream=wss://…/ws/*** twiml_bytes=612
    voice.trace ws.arrived       secret=path peer=52.23.156.9
    voice.trace ws.authorized    secret=path
    voice.trace ws.upstream_open upstream=ws://127.0.0.1:7860/ws in=0.04s
    voice.trace pipeline.ready   session=VS-… waited=1.8s
    voice.trace ws.closed        first=caller→bot in=1315 out=372

A gap in that sequence names the broken hop without any further digging.

Redaction
---------
Phone numbers keep their last four digits, the proxy secret is never printed,
and the TwiML is summarised by size and stream host rather than dumped -- it
carries the secret in a query-free path segment.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger("voice.trace")

#: The media-stream path carries ``VOICE_WS_PROXY_SECRET`` as a path segment
#: (Twilio rejects query strings, error 31920), so any URL logged from this
#: module has to lose that segment first.
_WS_SECRET = re.compile(r"(/ws/)[^\s\"'<>?]+")


def redact_url(url: str | None) -> str:
    """A media-stream URL safe to print: host and path, never the secret."""
    if not url:
        return "-"
    return _WS_SECRET.sub(r"\1***", str(url))


def redact_phone(number: str | None) -> str:
    """Last four digits only. Enough to match a call, not enough to dial one."""
    digits = "".join(ch for ch in str(number or "") if ch.isdigit())
    return f"***{digits[-4:]}" if len(digits) >= 4 else "***"


_DIGITS = re.compile(r"\d{2,}")


def preview(text: str | None, *, limit: int = 80) -> str | None:
    """A short log-safe snippet of spoken text.

    Digit runs of two or more are stripped so a last-four or an account tail
    cannot leak at WARNING. The remaining words are enough to reconstruct
    what was said without opening a 30k-token context dump.
    """
    raw = " ".join(str(text or "").split())
    if not raw:
        return None
    scrubbed = _DIGITS.sub("***", raw)
    if len(scrubbed) <= limit:
        return scrubbed
    return scrubbed[: limit - 1] + "…"


def session_fields(session: Any | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """The ids that join every hop of one call.

    A line without these is a line that cannot be grepped back to the dial
    that caused it. Callers still pass hop-specific fields; this fills the
    ones that must appear on all of them.
    """
    extra = extra if extra is not None else (getattr(session, "extra", None) or {})
    if not isinstance(extra, dict):
        extra = {}
    params = extra.get("twilio_params") if isinstance(extra.get("twilio_params"), dict) else {}
    demo_raw = params.get("demo") if params.get("demo") is not None else extra.get("demo")
    demo = str(demo_raw or "").strip().lower()
    return {
        "session": getattr(session, "session_id", None),
        "attempt": extra.get("attempt_id") or params.get("attempt_id"),
        "sid": extra.get("call_sid") or params.get("call_id") or params.get("CallSid"),
        "interaction": getattr(session, "interaction_id", None) or extra.get("interaction_id"),
        "objective": extra.get("objective") or params.get("objective"),
        "demo": 1 if demo in {"1", "true", "yes"} else None,
    }


def event(name: str, **fields: Any) -> None:
    """Emit one trace line.

    WARNING rather than INFO on purpose. This module's records exist to be read
    after something went wrong, and on this deployment the root logger sits at
    WARNING -- an INFO trace is a trace that is not there. The volume is a
    handful of lines per call, which is the correct price for being able to
    answer "what happened to that call" without a reproduction.
    """
    parts = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    logger.warning("voice.trace %s %s", name, parts)


class Stopwatch:
    """Elapsed seconds since construction, for the timings that decide calls."""

    __slots__ = ("_t0",)

    def __init__(self) -> None:
        self._t0 = time.monotonic()

    def s(self) -> float:
        return round(time.monotonic() - self._t0, 2)
