"""Callback factory helpers for :pyclass:`~api.services.workflow.pipecat_engine.PipecatEngine`.

Each helper takes a :class:`PipecatEngine` instance and returns an async
callback function suitable for passing to the various pipeline processors.
Separating these helpers into their own module keeps
``pipecat_engine.py`` focused on high-level engine orchestration logic while
encapsulating the callback implementations here for easier maintenance and
unit-testing.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from loguru import logger
from pipecat.frames.frames import (
    LLMMessagesAppendFrame,
)
from pipecat.utils.enums import EndTaskReason

if TYPE_CHECKING:
    from api.services.workflow.pipecat_engine import PipecatEngine


# ---------------------------------------------------------------------------
# User-idle handling
# ---------------------------------------------------------------------------


class UserIdleHandler:
    """Helper class to manage user idle retry logic with state."""

    def __init__(self, engine: "PipecatEngine"):
        self._engine = engine
        self._retry_count = 0

    def reset(self):
        """Reset the retry count when user becomes active."""
        self._retry_count = 0

    async def handle_idle(self, aggregator):
        """Handle user idle event with escalating prompts."""
        supervisor = getattr(self._engine, "answer_supervisor", None)
        if supervisor is not None and supervisor.blocks_workflow:
            return
        if getattr(self._engine, "generation_on_hold", False):
            # The caller is listening to a hold ringer while the next agent is
            # prepared, or talking to a supervisor who took the call over.
            # Prompting them to speak, and eventually hanging up on them for
            # not speaking, is exactly wrong here.
            logger.debug("Suppressing user-idle prompt while the agent is on hold")
            return
        self._retry_count += 1
        logger.debug(f"Handling user_idle, attempt: {self._retry_count}")

        if self._retry_count == 1:
            message = self._engine.engine_note(
                "The user has been quiet. Politely and briefly ask if they're still there in the language that the user has been speaking so far."
            )
            await aggregator.push_frame(LLMMessagesAppendFrame([message], run_llm=True))
            return

        message = self._engine.engine_note(
            "The user has been quiet. We will be disconnecting the call now. Wish them a good day in the language that the user has been speaking so far."
        )
        await aggregator.push_frame(LLMMessagesAppendFrame([message], run_llm=True))
        await self._engine.end_call_with_reason(
            EndTaskReason.USER_IDLE_MAX_DURATION_EXCEEDED.value
        )


def create_user_idle_handler(engine: "PipecatEngine") -> UserIdleHandler:
    """Return a UserIdleHandler that manages user-idle timeouts with state."""
    return UserIdleHandler(engine)


# ---------------------------------------------------------------------------
# Max-duration handling
# ---------------------------------------------------------------------------


#: At the time limit the agent says goodbye; the call ends when it has, or
#: after this long if the goodbye never starts (a tool call, a failed TTS).
LIMIT_GOODBYE_START_SECONDS = 8.0
LIMIT_GOODBYE_PLAYBACK_SECONDS = 20.0

_LIMIT_GOODBYE_NOTE = (
    "The call has reached its time limit and must end now. In one or two short sentences, in the "
    "language the caller is speaking: thank them, say the bank can call them back if they need "
    "anything more, and say goodbye. Do not ask a question, and do not call any tool or take any path."
)


def create_max_duration_callback(engine: "PipecatEngine"):
    """Return a callback that closes the call once its time limit has passed.

    It used to cancel the pipeline on the spot: run 88 was cut mid-conversation
    at 300 s, the caller's question unheard and no goodbye. The agent now says
    goodbye first, then the call ends normally. The closing runs in its own
    task: the clock awaits this callback on its frame path, and waiting there
    for the goodbye (or the final extraction) held the call pipeline.
    """

    async def handle_max_duration():
        if getattr(engine, "generation_on_hold", False) is True:
            # AgentStudio: a supervisor has the call; the limit applies once
            # they hand it back. False tells the clock to ask again later.
            # ponytail: no hard cap during a takeover; add one if it is abused.
            return False
        if engine.__dict__.get("_limit_close_task") is None:
            logger.debug("Max call duration exceeded. Saying goodbye, then ending the call")
            engine._limit_close_task = asyncio.create_task(
                close_at_time_limit(engine), name="call-time-limit"
            )

    return handle_max_duration


async def close_at_time_limit(engine: "PipecatEngine") -> None:
    """Have the agent say goodbye, then end the call gracefully."""
    try:
        agent = engine.active_agent
        if engine.agent_can_act(agent):
            # As an end node closes: the goodbye is the last thing said.
            engine.arm_speech_playback()
            engine._mute_pipeline = True
            await agent.queue_frame(
                LLMMessagesAppendFrame([engine.engine_note(_LIMIT_GOODBYE_NOTE)], run_llm=True)
            )
            await engine.wait_for_speech_playback(
                start_timeout=LIMIT_GOODBYE_START_SECONDS,
                playback_timeout=LIMIT_GOODBYE_PLAYBACK_SECONDS,
            )
    except Exception:
        logger.exception("Time-limit goodbye failed; ending the call without it")
    await engine.end_call_with_reason(EndTaskReason.CALL_DURATION_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Generation-started handling
# ---------------------------------------------------------------------------


def create_generation_started_callback(
    engine: "PipecatEngine", *, visit_id: str | None = None
):
    """Return a callback that resets flags at the start of each LLM generation.

    Args:
        engine: The call's engine.
        visit_id: The agent visit whose generation stage fires this. A
            generation starting in an agent that has already handed the call
            over is ignored, so it cannot clear the reference text the new
            agent is mid-way through building.
    """

    async def handle_generation_started():
        if not engine.owns_generation(visit_id):
            logger.debug(f"Ignoring generation start from retired visit {visit_id}")
            return
        logger.debug("LLM generation started in callback processor")
        # Clear reference text from previous generation
        engine._current_llm_generation_reference_text = ""

    return handle_generation_started


def create_aggregation_correction_callback(engine: "PipecatEngine"):
    """Create a callback that uses engine's reference text to correct corrupted aggregation."""

    def correct_corrupted_aggregation(ref: str, corrupted: str) -> str:
        """Correct corrupted text by aligning it with reference text.

        This is a pure function that doesn't depend on engine instance.
        """
        # 1) Safety check: if ref (minus spaces) is shorter than corrupted, bail out
        # also if corrupted is less than 10 characters, lets also return that since most likely
        # Elevenlabs returned the right alignment
        alnum_corr = "".join(ch for ch in corrupted if ch.isalnum())
        alnum_ref = "".join(ch for ch in ref if ch.isalnum())

        if corrupted in ref or len(alnum_ref) < len(alnum_corr) or len(alnum_corr) < 10:
            return corrupted

        logger.debug(
            f"In correct_corrupted_aggregation: ref: {ref} corrupted: {corrupted}"
        )

        # 2) Find where in `ref` we should start aligning.
        #    We take the first N (N=10) characters of `corrupted`
        #    and look for all their occurrences in `ref`.
        #    We pick the *last* one
        prefix = corrupted[:10]

        # find all start‐indices of that prefix in ref
        starts = [m.start() for m in re.finditer(re.escape(prefix), ref)]
        start_idx = starts[-1] if starts else 0

        # 3) Now run the same two‑pointer scan from start_idx
        i, j = start_idx, 0
        out_chars = []
        while i < len(ref) and j < len(corrupted):
            r_ch, c_ch = ref[i], corrupted[j]
            if r_ch == c_ch:
                out_chars.append(r_ch)
                i += 1
                j += 1

            elif c_ch == " ":
                # extra space in corrupted → skip it
                j += 1

            elif r_ch == " " or r_ch in ".,;:!?":
                # missing structural char in corrupted → emit from ref
                out_chars.append(r_ch)
                i += 1

            else:
                # letter mismatch → best‑effort copy from ref
                out_chars.append(r_ch)
                i += 1
                j += 1

        # 4) A final check - the final created output should be exactly
        # as corrupted sentence sans whitespace.
        alnum_out = "".join([ch for ch in out_chars if ch.isalnum()])
        if alnum_out != alnum_corr:
            return corrupted

        # 5) Join and return exactly what we built
        return "".join(out_chars)

    def correct_aggregation(corrupted: str) -> str:
        reference = engine._current_llm_generation_reference_text

        if not reference:
            return corrupted

        # Apply the correction algorithm
        corrected = correct_corrupted_aggregation(reference, corrupted)
        return corrected

    return correct_aggregation
