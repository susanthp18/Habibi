"""The scope every handler section shares.

The constants and helpers that used to sit at the top of voice/bot_handlers.py,
``HandlerState`` (the six scalars the closures shared through ``nonlocal``),
and ``HandlerScope`` -- ``register_handlers``' closure scope as an object.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from dataclasses import dataclass
from types import SimpleNamespace

_TUNE_MSG_TYPES = frozenset({"tune", "agent_tuning", "tuning", "tuning_delta"})


def _delta_from_payload(data) -> dict | None:
    """Normalize a tune payload into an AgentTuning delta dict."""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("tuning"), dict):
        return data["tuning"]
    return data


def _extract_tune_delta(message) -> dict | None:
    """Accept Studio deltas from transport app-message or RTVI client-message shapes.

    Wire formats handled:
    - Bare AgentTuning / ``{tuning: {...}}``
    - ``{type: "tuning_delta"|"tune"|..., data|payload: {...}}``
    - RTVI client-message: ``{type: "client-message", data: {t: "tuning_delta", d: {...}}}``
    - ``RTVIClientMessageFrame`` / ClientMessage objects (``.type`` + ``.data``)
    """
    if message is None:
        return None
    if isinstance(message, dict):
        if isinstance(message.get("tuning"), dict):
            return message["tuning"]

        outer = message.get("type")
        data = message.get("data") if "data" in message else message.get("payload")

        # RTVI wire: sendClientMessage("tuning_delta", delta) →
        # {type: "client-message", data: {t: "tuning_delta", d: delta}}
        if outer == "client-message" and isinstance(data, dict):
            inner_t = data.get("t") or data.get("type")
            inner_d = data["d"] if "d" in data else data.get("data")
            if inner_t in _TUNE_MSG_TYPES:
                return _delta_from_payload(inner_d)
            return None

        if outer in _TUNE_MSG_TYPES:
            return _delta_from_payload(data if isinstance(data, dict) else {})

        # Bare AgentTuning sections
        if any(k in message for k in ("llm", "tts", "vad", "turn", "interaction", "stt")):
            return message
        return None

    # RTVI ClientMessage / RTVIClientMessageFrame
    msg_type = getattr(message, "type", None) or getattr(message, "msg_type", None)
    data = getattr(message, "data", None)
    if msg_type in _TUNE_MSG_TYPES:
        return _delta_from_payload(data)
    return None


# Collections voice calls: hard cap then spoken sign-off (docs: pipeline-termination).
_MAX_CALL_DURATION_SECS = 10 * 60

#: How long end-of-call bookkeeping may take before teardown proceeds without
#: it. Generous — a healthy finalize is well under a second, and the slowest
#: real one observed was six — but finite, which is the point: past this, the
#: records lose and the worker gets cancelled. The alternative is what actually
#: happened, which is that one drain that never returned kept a whole session
#: alive and made every later call on the process fail.
_FINALIZE_BUDGET_SECS = 20.0

#: Above this, the caller has been holding a silent line long enough that the
#: call is at risk. Healthy setup on a warm process is well under a second; the
#: run that started this investigation took 16.5s and Twilio hung up at 0.5s
#: past ready. Warned rather than enforced — refusing the call outright would
#: turn a degraded call into no call.
_SLOW_SETUP_WARN_SECS = 4.0

#: Conversation + classifier LLM starts before the callee has said a real
#: word. VS-4D8667B522 burned 46 turns on one "Hello." Six is already a loop.
_LOOP_LLM_BUDGET = 6

# Dead-air watchdog.
#
# Pipecat's UserIdleController starts its timer on BotStoppedSpeakingFrame and
# re-arms nowhere else. Every silence that follows a bot turn is therefore
# covered — and every silence that does NOT is invisible to it. A transition
# into a listen-first node, a tool call that resolves without a reply, or a
# chain of transition tools that never reaches speech all leave no timer
# running at all: on VS-92CDE3F088 the line was mute for 24 seconds with the
# ladder configured and not one strike logged.
#
# This watchdog measures silence itself, from frames, and feeds the same ladder.
# The poll interval is deliberately coarse — it is a backstop, not a turn timer.
_DEADAIR_POLL_SECS = 1.0
#: Added to the configured idle timeout before the watchdog acts, so the
#: aggregator's own timer always wins when it is armed and the watchdog only
#: speaks for the silences nothing else can see.
_DEADAIR_GRACE_SECS = 2.0
#: Floor for the watchdog, independent of tuning. A 2s idle_timeout is a
#: turn-taking preference; hanging on it as a dead-air threshold would nudge
#: over ordinary thinking pauses.
_DEADAIR_MIN_SECS = 6.0
#: One quiet stretch must not burn two rungs of the ladder just because two
#: timers noticed it.
_IDLE_REFIRE_GUARD_SECS = 4.0


async def _drain_tasks(tasks: set[asyncio.Task], *, label: str, timeout: float = 2.0) -> None:
    """Settle a call's fire-and-forget tasks, then cancel whatever is left.

    Mirrors voice.tools.drain_background_tasks. Best-effort work must not hold
    up the hangup path, but it also must not be abandoned pending — that is
    what logs "Task was destroyed but it is pending!" at interpreter exit.
    """
    pending = [t for t in tasks if not t.done()]
    if not pending:
        return
    done, still_pending = await asyncio.wait(pending, timeout=timeout)
    for task in still_pending:
        task.cancel()
    if still_pending:
        await asyncio.gather(*still_pending, return_exceptions=True)
    for task in done:
        if not task.cancelled() and task.exception() is not None:
            logger.debug("{} task failed: {}", label, task.exception())


@dataclass
class HandlerState:
    """What the handlers used to share through ``nonlocal``: single-flight end,
    the silence ladder's strike count and last fire, the two watchdog tasks,
    and the finalize-once flag."""

    idle_strikes: int = 0
    last_idle_fired: float = 0.0
    ending: bool = False
    duration_task: asyncio.Task | None = None
    deadair_task: asyncio.Task | None = None
    finalized: bool = False


class HandlerScope(SimpleNamespace):
    """``register_handlers``' closure scope: the call's objects, the tuning, the
    injectors, and ``hs``. Each section unpacks what it reads; a section that
    defines a coroutine a later one needs attaches it here."""

