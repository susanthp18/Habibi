"""IVR navigation — outbound partner-IVR traversal + inbound DTMF capture.

Two independent capabilities, both telephony-only (voice plan §2.10):

**Outbound** (``VOICE_IVR_ENABLED=true`` + ``call_type=outbound``)
    Some collections numbers on file are a workplace or partner switchboard, not
    the customer's handset. Pipecat's :class:`IVRNavigator` wraps our LLM: it
    classifies the far end as menu-vs-human, drives DTMF until it reaches a
    person, then hands control back so the normal Flows conversation begins on a
    live human. Without it those dials burn a retry against a robot.

**Inbound** (``VOICE_DTMF_INPUT_ENABLED=true``, any telephony leg)
    ``DTMFAggregator`` folds keypad digits into the transcript stream, so a
    caller who *types* an account tail instead of speaking it is understood.
    Digits are aggregated to a terminator/timeout rather than one frame each,
    which is what makes "1-2-3-4#" arrive as one turn.

Sandbox Live never enables either — a browser peer has no keypad and is always
a human.

The navigator is only ever placed where the plain ``llm`` stage would sit, so
the rest of the pipeline (Flows, RTVI, CrmSink, recording) is unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# Reaching a human is the only goal that makes sense for collections: we cannot
# authenticate against a third party's IVR, and we must never key an account
# number into someone else's menu tree.
DEFAULT_IVR_GOAL = (
    "Reach a live human agent in customer service or the operator. "
    "Do NOT enter any account number, card number, PIN, date of birth or other "
    "personal identifier into this menu — you are calling on behalf of a "
    "customer and must not disclose their data to an automated system. "
    "Prefer options such as 'speak to an agent', 'customer service', "
    "'operator', or 'all other enquiries'. If the menu demands an account "
    "number or PIN before continuing, respond that you are stuck."
)


def should_enable_ivr(session_extra: dict[str, Any] | None, *, is_twilio: bool) -> bool:
    """Outbound Twilio leg with the feature flag on."""
    if not is_twilio:
        return False
    from voice import config as voice_config

    if not voice_config.voice_ivr_enabled():
        return False
    extra = session_extra or {}
    params = extra.get("twilio_params") if isinstance(extra.get("twilio_params"), dict) else {}
    call_type = str(params.get("call_type") or extra.get("call_type") or "").lower()
    if call_type != "outbound":
        return False
    # The card has the final say. Traversing somebody's employer switchboard is
    # a decision about how far we are willing to chase a borrower through a
    # third party's phone system, and that belongs to whoever publishes the
    # agent rather than to a deployment-wide environment variable. The env flag
    # stays as the kill switch above; this is the per-agent opt-in.
    mission = extra.get("mission") if isinstance(extra.get("mission"), dict) else None
    if mission is not None and "ivrTraversal" in mission:
        return bool(mission.get("ivrTraversal"))
    return True


def ivr_budget_sec(session_extra: dict[str, Any] | None) -> int:
    """How long the navigator may spend in a menu tree.

    Unbudgeted, a traversal can consume the mission's whole time budget before
    a human ever answers — and the borrower then gets a rushed conversation
    because a phone menu was slow.
    """
    extra = session_extra or {}
    mission = extra.get("mission") if isinstance(extra.get("mission"), dict) else {}
    try:
        return max(15, min(300, int(mission.get("ivrMaxSec") or 90)))
    except (TypeError, ValueError):
        return 90


def should_enable_dtmf_input(*, is_twilio: bool) -> bool:
    """Inbound keypad capture — telephony only, behind its own flag."""
    if not is_twilio:
        return False
    from voice import config as voice_config

    return voice_config.voice_dtmf_input_enabled()


def build_dtmf_aggregator() -> Any | None:
    """``DTMFAggregator`` if this Pipecat build ships one, else ``None``.

    Optional rather than required: the aggregator moved modules across Pipecat
    releases, and a missing keypad path must not stop a call from connecting.
    """
    try:
        from pipecat.processors.aggregators.dtmf_aggregator import DTMFAggregator
    except ImportError:
        logger.warning("DTMFAggregator unavailable in this Pipecat build — keypad input off")
        return None
    # Prefix labels the digits in the transcript so the model can tell "the
    # caller typed 1234" from "the caller said 1234".
    return DTMFAggregator(prefix="Caller keypad input: ")


def ivr_goal(session_extra: dict[str, Any] | None) -> str:
    """Per-call override via ``twilio_params.ivr_goal``, else the safe default."""
    extra = session_extra or {}
    params = extra.get("twilio_params") if isinstance(extra.get("twilio_params"), dict) else {}
    goal = str(params.get("ivr_goal") or extra.get("ivr_goal") or "").strip()
    return goal or DEFAULT_IVR_GOAL


def build_ivr_navigator(*, llm: Any, session_extra: dict[str, Any] | None) -> Any | None:
    """Wrap ``llm`` in an :class:`IVRNavigator`; ``None`` if unavailable."""
    try:
        from pipecat.extensions.ivr.ivr_navigator import IVRNavigator
    except ImportError:
        logger.warning("IVRNavigator unavailable in this Pipecat build — IVR nav off")
        return None
    try:
        return IVRNavigator(llm=llm, ivr_prompt=ivr_goal(session_extra))
    except Exception:
        logger.exception("IVRNavigator construction failed")
        return None


async def attach_ivr_handlers(
    *,
    navigator: Any,
    session: Any,
    sink: Any,
    worker: Any,
    emitter: Any | None = None,
    on_human_reached: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Register navigation-status handlers: CRM disposition + RTVI lifecycle.

    ``on_ivr_status_changed`` is advisory except for ``STUCK``, which is
    terminal: the menu wants data we are not permitted to give it, so the leg is
    ended and dispositioned for a human to redial. Leaving it running would sit
    in a loop until the worker idle timeout.
    """
    from pipecat.extensions.ivr.ivr_navigator import IVRStatus

    async def _lifecycle(phase: str, reason: str) -> None:
        if emitter is None:
            return
        try:
            await emitter.lifecycle(phase=phase, reason=reason)
        except Exception:
            logger.debug("ivr lifecycle emit failed", exc_info=True)

    async def _alert(kind: str, reason: str) -> None:
        if not hasattr(sink, "enqueue_alert"):
            return
        try:
            await sink.enqueue_alert(kind, reason)
        except Exception:
            logger.warning("ivr %s alert failed", reason, exc_info=True)

    @navigator.event_handler("on_conversation_detected")
    async def _on_human(_processor, _conversation_history) -> None:
        logger.info("IVR: human reached · session=%s", session.session_id)
        session.extra["ivr"] = "human"
        await _lifecycle("ivr", "human_reached")
        if on_human_reached:
            try:
                await on_human_reached()
            except Exception:
                logger.exception("ivr on_human_reached failed")

    @navigator.event_handler("on_ivr_status_changed")
    async def _on_status(_processor, status) -> None:
        name = getattr(status, "value", str(status))
        logger.info("IVR status=%s · session=%s", name, session.session_id)
        session.extra["ivr_status"] = name
        await _lifecycle("ivr", name)

        if status == IVRStatus.DETECTED:
            await _flag(session, "ivr_detected", "low")
        elif status == IVRStatus.STUCK:
            session.extra["disposition"] = "ivr_stuck"
            await _flag(session, "ivr_stuck", "high")
            await _alert("compliance", "ivr_stuck")
            await _end_call(worker)


async def _flag(session: Any, flag: str, severity: str) -> None:
    """Best-effort interaction flag so a redial queue can see how the dial went."""
    ix = getattr(session, "interaction_id", None)
    if not ix:
        return
    try:
        from voice import persist

        await asyncio.to_thread(
            partial(
                persist.append_interaction_flag,
                interaction_id=ix,
                flag=flag,
                severity=severity,
            )
        )
    except Exception:
        logger.exception("ivr flag %s failed", flag)


async def _end_call(worker: Any) -> None:
    try:
        from pipecat.frames.frames import EndWorkerFrame

        await worker.queue_frame(EndWorkerFrame())
    except Exception:
        logger.exception("ivr EndWorkerFrame failed")
