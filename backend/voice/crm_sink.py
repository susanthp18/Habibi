"""CrmSink — off-audio-path persistence for voice turns + metrics.

Turn text comes from aggregator event handlers (plan §5).
MetricsFrame is observed via BaseObserver when available.
A background asyncio.Queue drain never blocks the speech path.

Live tripwires (flow_improve §4): loop / abuse / legal / sentiment collapse
enqueue alerts and optionally invoke an escalate callback on the audio path.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agent_core import classify_intent
from agent_core import turn_critic
from agent_core.guardrails import mentions_recording_disclosure
from voice import persist
from voice.safety import (
    SENTIMENT_WINDOW,
    detect_abuse,
    detect_bot_loop,
    detect_hold_request,
    detect_legal,
    resolve_language_action,
    rolling_sentiment_collapsed,
)
from voice.session import VoiceSession
from voice.usage import VoiceUsageMeter

logger = logging.getLogger(__name__)

#: Disposition filed on the minimal interaction row written for a call whose
#: CRM bind failed at connect. Deliberately not one of
#: ``capture.disposition_from_flags``'s values: "we did not record this call
#: properly" must never be readable as an outcome the bot achieved.
CRM_DEGRADED_DISPOSITION = "crm_degraded"
#: Passed alongside it because ``complete_voice_call`` forwards
#: ``force_summary=not summary`` into ``capture.rollup_interaction``, and a
#: forced rollup overwrites the disposition we just wrote.
CRM_DEGRADED_SUMMARY = (
    "CRM persistence was unavailable when this call connected. "
    "The call is recorded but its transcript, tool calls and alerts are not."
)

#: Logged verbatim when a call loses its CRM bind. A stable prefix on purpose —
#: it is what an alert rule matches on, and the one line that says a live call is
#: running without a record.
CRM_DEGRADED_LOG = (
    "crm_persistence_degraded · session=%s · call continues; a minimal "
    "interaction row will be filed at teardown"
)


def mark_crm_degraded(session: VoiceSession, exc: BaseException | None = None) -> None:
    """Flag a call whose CRM bind failed, loudly.

    The connect path used to catch the bind failure, log it and carry on with
    ``interaction_id`` still None: every CRM job for the rest of the call was
    then discarded by the ``interaction_id`` guards below, and a collections
    call completed with no record that it had ever happened.

    Degrade, do not abort — hanging up on a borrower mid-disclosure to protect a
    database is not a trade this call gets to make. Setting the flag here rather
    than in ``bot.py`` keeps the one thing teardown depends on next to the code
    that reads it, and gives it a seam a test can hold.
    """
    session.crm_degraded = True
    logger.error(CRM_DEGRADED_LOG, session.session_id, exc_info=exc)


EscalateHandler = Callable[[str, str], Awaitable[None]]
HoldHandler = Callable[[], Awaitable[None]]
LanguageHandler = Callable[[dict[str, Any]], Awaitable[None]]
#: Receives one agent_core.turn_critic.Correction to inject into the live
#: context as a developer message for the *next* turn.
CorrectionHandler = Callable[[Any], Awaitable[None]]
#: Receives one per-turn analysis payload for the live Inspector. Shape matches
#: the ``interaction_transcript`` columns so the live view and the persisted
#: export agree field for field.
TurnHandler = Callable[[dict[str, Any]], Awaitable[None]]


def _camel(snake: str) -> str:
    """``stt_ttfb_ms`` → ``sttTtfbMs``. RTVI payloads are camelCase throughout."""
    head, *rest = snake.split("_")
    return head + "".join(p.title() for p in rest)


@dataclass
class _Job:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


class CrmSink:
    """Queue-backed CRM writer bound to one VoiceSession."""

    def __init__(
        self,
        session: VoiceSession,
        *,
        guardrails: dict[str, Any] | None = None,
        direction: str = "inbound",
        simulated: bool = False,
    ) -> None:
        self.session = session
        self.guardrails = guardrails or {}
        # What kind of contact this is, for the rules that only govern contact
        # attempts. Voice defaults to "inbound" because that is what this
        # transport is — a caller dialled in. Outbound campaigns set it
        # explicitly, which is the direction that owes a calling window.
        self.call_direction = direction
        self.simulated_call = bool(simulated)
        #: Corrections already spent, per kind, and the guardrail rules already
        #: steered on. Both exist so one detector cannot monopolise the budget
        #: or repeat itself.
        self._corrections_by_kind: dict[str, int] = {}
        self._corrected_flags: set[str] = set()
        # Whether ANY bot turn in this call has stated the recording
        # disclosure. The guardrail evaluator sees one turn at a time and
        # cannot answer that on its own; without it a compliant greeting is
        # followed by a false "missing-recording-disclosure" on the next turn.
        self._recording_disclosed = False
        # Billable consumption for this call. Fed by the metrics observer and
        # finalised in stop(); see voice/usage.py for why STT is derived.
        self.usage = VoiceUsageMeter(session)
        self._queue: asyncio.Queue[_Job | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        # Turn understanding runs on its OWN queue and drain task, not the main
        # one. Two reasons, both load-bearing:
        #
        #  * the main drain is a single FIFO, so an Azure call parked in it
        #    head-of-line-blocks `live_alert` (compliance escalations the Inbox
        #    renders) and `complete` (call closure);
        #  * stop() gives the main drain 15s before cancelling it, and an
        #    analysis backlog inside that budget would cost real CRM writes.
        #
        # This queue's backlog is *discarded* at teardown instead. Those turns
        # keep their keyword classification, which is exactly the intended
        # degradation.
        self._analysis_queue: asyncio.Queue[_Job | None] = asyncio.Queue()
        self._analysis_task: asyncio.Task[None] | None = None
        # Captured in start(). Bot-turn guardrail flags are computed inside
        # _handle_sync, which runs in a worker thread via to_thread — and
        # asyncio.Queue is not thread-safe, so the critique job has to be handed
        # back across the boundary rather than put_nowait'd directly.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_correction: CorrectionHandler | None = None
        # Per-turn analysis, pushed to the live UI as it is produced. The
        # Inspector's Intent, Sentiment and Metrics tabs were rendering their
        # empty states for entire live calls because the browser built its turns
        # from the RTVI transcript alone, which carries no classification and no
        # timings — while the backend was computing both and writing them
        # straight to Postgres. This is the missing wire, not a second
        # classifier.
        self._on_turn: TurnHandler | None = None
        self._corrections_sent = 0
        self._last_customer_text = ""
        self._customer_exchanges = 0
        self._sentiment_scores: list[float] = []
        self._recent_bot_texts: list[str] = []
        # Interleaved run-up, oldest first, fed by both speakers. The turn
        # analyser needs the conversation to tell an ordinary question from the
        # third unanswered one; judged on a single sentence, a caller who has
        # asked the same thing three times looks perfectly calm.
        self._recent_turns: list[tuple[str, str]] = []
        self._ttfb_samples_ms: list[float] = []
        self._pending_ttfb_ms: float | None = None
        self._pending_ttfa_ms: float | None = None
        self._pending_tokens: int | None = None
        # Per-service latency for the next bot turn (UserBotLatencyObserver).
        self._pending_breakdown: dict[str, int] = {}
        self._user_bot_latency_ms: list[float] = []
        # CRM work discarded because the session never got an interaction_id,
        # counted by job kind. These guards used to be a bare `return`: an
        # entire call's transcript turns, tool-call audit rows, live alerts and
        # guardrail violations could go missing without one line in the log.
        # Counted here and reported once per session — a line per lost turn
        # would be the loudest thing in the log on exactly the call that already
        # went wrong, and ops would filter it out.
        #
        # Written from the drain thread and the audio path both, hence the lock.
        self._dropped_jobs: dict[str, int] = {}
        self._drop_logged = False
        self._drop_lock = threading.Lock()
        self._closed = False
        self._completed = False
        self._escalated_live = False
        self._on_escalate: EscalateHandler | None = None
        self._on_hold: HoldHandler | None = None
        self._on_language: LanguageHandler | None = None
        self._stt_language = "en-IN"
        self._fallback_languages: list[str] = ["hi-IN", "en-IN"]

    def configure_live_handlers(
        self,
        *,
        on_escalate: EscalateHandler | None = None,
        on_hold: HoldHandler | None = None,
        on_language: LanguageHandler | None = None,
        on_correction: CorrectionHandler | None = None,
        on_turn: TurnHandler | None = None,
        stt_language: str = "en-IN",
        fallback_languages: list[str] | None = None,
    ) -> None:
        self._on_escalate = on_escalate
        self._on_hold = on_hold
        self._on_language = on_language
        self._on_correction = on_correction
        self._on_turn = on_turn
        self._stt_language = stt_language or "en-IN"
        if fallback_languages is not None:
            self._fallback_languages = list(fallback_languages)

    def _note_dropped(self, kind: str) -> None:
        """Record one CRM job lost to a missing ``interaction_id``.

        The first loss on a session logs at ERROR and names the kind — this is
        persistence failing, not a debug detail. Every later loss only
        increments the counter; the per-kind totals go out once at teardown.
        Keeping the drop itself is deliberate: there is no id to write against,
        so the choice is between losing the row loudly and losing it silently.
        """
        with self._drop_lock:
            self._dropped_jobs[kind] = self._dropped_jobs.get(kind, 0) + 1
            already_logged = self._drop_logged
            self._drop_logged = True
            count = self._dropped_jobs[kind]
        if already_logged:
            return
        logger.error(
            "crm job dropped, interaction_id unset · kind=%s · dropped=%d · session=%s · "
            "further drops on this session are counted, not logged",
            kind,
            count,
            self.session.session_id,
        )

    def _report_dropped(self) -> None:
        """Per-kind totals, once, at teardown. Nothing to report is the norm."""
        with self._drop_lock:
            dropped = dict(self._dropped_jobs)
        if not dropped:
            return
        logger.warning(
            "crm jobs dropped this session · session=%s · %s · total=%d",
            self.session.session_id,
            " · ".join(f"{kind}={n}" for kind, n in sorted(dropped.items())),
            sum(dropped.values()),
        )

    def _file_degraded_interaction(self) -> None:
        """File the minimal interaction row for a call the bind never covered.

        Reuses ``start_voice_call`` rather than a bespoke INSERT so the row
        carries the same tenant, bot, direction and account resolution every
        other call gets — a reviewer opens it in the same screen. ``started_at``
        is the moment the borrower answered, so the duration ``complete`` then
        computes is the real one and not a teardown artefact.

        ``bot_id`` and the direction come from ``session.extra``, where the
        connect path leaves whatever the failed bind resolved: this row is thin
        by necessity and must not also be wrong about who answered.

        Failing here leaves the call genuinely unrecorded, so it says exactly
        that rather than another quiet ``return``.
        """
        extra = self.session.extra or {}
        try:
            row = persist.start_voice_call(
                session_id=self.session.session_id,
                deployment_id=self.session.deployment_id,
                transport=self.session.transport,
                provider_call_id=(
                    self.session.provider_call_id
                    or (str(extra.get("call_sid") or "").strip() or None)
                ),
                customer_id=self.session.customer_id,
                account_id=self.session.account_id,
                bot_id=str(extra.get("bot_id") or "").strip() or None,
                direction=str(extra.get("call_direction") or self.call_direction),
                started_at=self.session.call_started_at,
            )
        except Exception:
            logger.exception(
                "crm_persistence_degraded · minimal interaction could NOT be filed · "
                "session=%s · this call is unrecorded",
                self.session.session_id,
            )
            return
        self.session.interaction_id = row["interactionId"]
        self.session.customer_id = row["customerId"]
        self.session.account_id = row.get("accountId")
        logger.error(
            "crm_persistence_degraded · minimal interaction filed · session=%s · interaction=%s",
            self.session.session_id,
            row["interactionId"],
        )

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._task is None:
            self._task = asyncio.create_task(self._drain(), name=f"crm-sink-{self.session.session_id}")
        if self._analysis_task is None:
            self._analysis_task = asyncio.create_task(
                self._drain_analysis(), name=f"crm-analysis-{self.session.session_id}"
            )

    async def stop(self, *, final_status: str = "completed") -> None:
        if self._closed:
            return
        self._closed = True
        # A call whose bind failed at connect has no interaction row, so every
        # job above was dropped and `complete` would be dropped too — the call
        # would end with nothing written anywhere. File the minimal row first:
        # it makes the call auditable, and anything still queued drains against
        # a real id instead of into the void.
        #
        # A bind that succeeded and only tripped afterwards is deliberately NOT
        # this case: its interaction row exists and the queue drains into it, so
        # labelling the call ``crm_degraded`` would misreport a call that was in
        # fact recorded.
        unrecorded = bool(self.session.crm_degraded and not self.session.interaction_id)
        if unrecorded:
            await asyncio.to_thread(self._file_degraded_interaction)
        avg = (
            sum(self._sentiment_scores) / len(self._sentiment_scores)
            if self._sentiment_scores
            else None
        )
        latency = None
        if self._ttfb_samples_ms:
            sorted_s = sorted(self._ttfb_samples_ms)
            latency = int(sorted_s[len(sorted_s) // 2])

        # Bill the recognised audio now that the call's length is known, then log
        # what this call consumed. Buffered in-memory like every other metering
        # call, so it adds nothing to teardown latency.
        self.usage.finalize_stt(seconds=self.session.at_sec())
        logger.info("voice call usage · %s", self.usage.summary())
        complete_job = _Job(
            "complete",
            {
                "status": final_status,
                "avg_sentiment": avg,
                "latency_ms": latency,
                "rag_hits": self.session.rag_hits,
            },
        )
        if unrecorded:
            complete_job.payload["disposition"] = CRM_DEGRADED_DISPOSITION
            complete_job.payload["summary"] = CRM_DEGRADED_SUMMARY
        # Give the analysis queue a short, separate budget BEFORE the CRM drain,
        # so a slow classifier eats its own deadline rather than the 15 seconds
        # the interaction's completion depends on. Anything still queued is
        # abandoned: those turns keep their keyword classification, which is
        # already persisted and already correct enough.
        await self._stop_analysis()

        self._queue.put_nowait(complete_job)
        self._queue.put_nowait(None)
        if self._task is None:
            # start() never ran — drain synchronously so interaction completes.
            await self._drain()
            self._report_dropped()
            return
        try:
            try:
                await asyncio.wait_for(self._task, timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "crm sink drain timed out · session=%s", self.session.session_id
                )
                await self._finish_drain_task(complete_job)
            except Exception:
                # Not only TimeoutError: _drain raising propagated out of stop()
                # and skipped the cleanup entirely, leaving the interaction
                # unfinalised and self._task pointing at a dead task.
                logger.exception(
                    "crm sink drain failed · session=%s", self.session.session_id
                )
                await self._finish_drain_task(complete_job)
        finally:
            self._task = None
            self._report_dropped()

    # Short on purpose. At teardown the call is over: nobody is waiting on a
    # refined intent, and the only thing a longer wait buys is a marginally
    # better analytics row at the cost of delaying the interaction's completion.
    _ANALYSIS_STOP_TIMEOUT_S = 3.0

    async def _stop_analysis(self) -> None:
        """Drain what is already in flight, discard the rest."""
        task = self._analysis_task
        self._analysis_task = None
        if task is None:
            return
        self._analysis_queue.put_nowait(None)
        try:
            await asyncio.wait_for(task, timeout=self._ANALYSIS_STOP_TIMEOUT_S)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            logger.info(
                "turn understanding backlog abandoned at teardown · session=%s",
                self.session.session_id,
            )
        except Exception:
            logger.debug("analysis drain failed at teardown", exc_info=True)

    async def _finish_drain_task(self, complete_job: _Job) -> None:
        """Cancel a stuck/failed drain and finalise the interaction directly."""
        if self._task is not None:
            self._task.cancel()
            # Await the cancellation so it is actually observed: without this,
            # stop() returned while the drain task was still unwinding, so
            # in-flight CRM writes raced the interaction's completion.
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("crm sink drain failed during cancellation")
            # The queue is FIFO, so a slow backlog means the drain never reached
            # the "complete" job we just appended — the interaction would stay
            # in-progress forever and the call would never close in the CRM.
            # Finalise directly; _handle_complete is idempotent-safe because the
            # drain that would have run it has been cancelled.
            if not self._completed:
                try:
                    await asyncio.to_thread(self._handle_sync, complete_job)
                except Exception:
                    logger.exception(
                        "crm sink direct finalisation failed · session=%s",
                        self.session.session_id,
                    )

    def set_stt_language(self, language: str) -> None:
        self._stt_language = language or self._stt_language

    def enqueue(self, kind: str, **payload: Any) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(_Job(kind, payload))
        except Exception:
            logger.exception("crm sink enqueue failed")

    # Depth at which the oldest queued analysis is dropped. A backlog means
    # Azure is slower than the caller is talking, and a classification four
    # turns stale is worth less than the keyword one already in hand.
    _ANALYSIS_MAX_DEPTH = 4

    # How much run-up is kept for the analyser. Bounded because this is a live
    # call: an unbounded transcript buffer grows for the whole session and only
    # the last few exchanges carry the "asked again" signal.
    _RECENT_TURNS_KEPT = 8

    def _remember_turn(self, speaker: str, text: str) -> None:
        line = (text or "").strip()
        if not line:
            return
        # Both callers of this method are the only two places a turn is
        # recorded, which makes it the one honest place to answer "who spoke
        # last?" — a question the flow compiler asks before deciding whether a
        # listen-first step is patience or dead air.
        self.session.last_speaker = speaker
        self._recent_turns.append((speaker, line))
        if len(self._recent_turns) > self._RECENT_TURNS_KEPT:
            del self._recent_turns[: -self._RECENT_TURNS_KEPT]

    def enqueue_understanding(
        self,
        *,
        turn_index: int,
        text: str,
        prior_intent: str | None,
        recent: list[tuple[str, str]] | None = None,
    ) -> None:
        """Schedule the LLM refinement for one customer turn.

        Called from ``_on_user_turn_stopped``, which Pipecat awaits on the
        pipeline task — so this must stay non-blocking and cheap. It queues; it
        never awaits, never touches Azure, and never raises into the caller.
        """
        if self._closed:
            return
        while self._analysis_queue.qsize() >= self._ANALYSIS_MAX_DEPTH:
            try:
                dropped = self._analysis_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if dropped is not None:
                logger.info(
                    "turn understanding dropped (backlog) · session=%s · turn=%s",
                    self.session.session_id,
                    dropped.payload.get("turn_index"),
                )
        try:
            self._analysis_queue.put_nowait(
                _Job(
                    "understanding",
                    {
                        "turn_index": turn_index,
                        "text": text,
                        "prior_intent": prior_intent,
                        "recent": recent or [],
                    },
                )
            )
        except Exception:
            logger.debug("understanding enqueue failed", exc_info=True)

    def enqueue_critique(
        self,
        *,
        bot_text: str,
        user_text: str,
        guardrail_flags: list[str] | None,
        recent_bot_turns: list[str] | None,
    ) -> None:
        """Schedule self-review of one bot turn. Safe to call from any thread.

        The audio for this turn has already been spoken; a correction steers the
        turn *after* it. Runs on the analysis queue rather than the main FIFO so
        an Azure call can never sit in front of a compliance escalation.
        """
        if self._closed or self._on_correction is None:
            return
        if self._corrections_sent >= turn_critic.MAX_CORRECTIONS_PER_CALL:
            return
        if not turn_critic.enabled():
            return
        job = _Job(
            "critique",
            {
                "bot_text": bot_text,
                "user_text": user_text,
                "guardrail_flags": list(guardrail_flags or []),
                "recent_bot_turns": list(recent_bot_turns or []),
            },
        )
        loop = self._loop
        try:
            if loop is not None and loop.is_running():
                # _handle_sync calls this from a to_thread worker; asyncio.Queue
                # is not thread-safe, so hop back onto the loop to enqueue.
                loop.call_soon_threadsafe(self._enqueue_analysis_job, job)
            else:
                self._enqueue_analysis_job(job)
        except RuntimeError:
            # Loop already closed at teardown — the call is over, drop it.
            logger.debug("critique enqueue after loop close", exc_info=True)

    def _enqueue_analysis_job(self, job: _Job) -> None:
        """Bounded put. Runs on the event loop thread."""
        while self._analysis_queue.qsize() >= self._ANALYSIS_MAX_DEPTH:
            try:
                dropped = self._analysis_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if dropped is not None:
                logger.info(
                    "analysis job dropped (backlog) · session=%s · kind=%s",
                    self.session.session_id,
                    dropped.kind,
                )
        try:
            self._analysis_queue.put_nowait(job)
        except Exception:
            logger.debug("analysis enqueue failed", exc_info=True)

    async def _drain_analysis(self) -> None:
        while True:
            job = await self._analysis_queue.get()
            if job is None:
                break
            try:
                if job.kind == "whisper":
                    await self._handle_whisper(job)
                elif job.kind == "critique":
                    await self._handle_critique(job)
                else:
                    await asyncio.to_thread(self._handle_understanding, job)
            except Exception:
                logger.exception(
                    "turn analysis failed · session=%s · kind=%s",
                    self.session.session_id,
                    job.kind,
                )

    async def _handle_critique(self, job: _Job) -> None:
        """Review one bot turn and, if warranted, inject one directive.

        The budget is re-checked here as well as at enqueue time: several turns
        can be queued before any of them resolves, and four corrections in
        flight would all pass an enqueue-time check.
        """
        if self._on_correction is None or self._closed:
            return
        if self._corrections_sent >= turn_critic.MAX_CORRECTIONS_PER_CALL:
            return
        p = job.payload
        correction = await asyncio.to_thread(
            lambda: turn_critic.critique_turn(
                bot_text=str(p.get("bot_text") or ""),
                user_text=str(p.get("user_text") or ""),
                understanding=self.session.understanding,
                guardrail_flags=p.get("guardrail_flags"),
                recent_bot_turns=list(p.get("recent_bot_turns") or []),
                already_corrected=self._corrected_flags,
            )
        )
        if correction is None:
            return
        # Per-kind ceiling as well as the call total. One noisy detector used to
        # be able to spend the entire budget — a compliance burst in the first
        # minute left nothing to catch the repetition that filled the next four.
        kind_cap = turn_critic.MAX_CORRECTIONS_PER_KIND.get(
            correction.kind, turn_critic.MAX_CORRECTIONS_PER_CALL
        )
        if self._corrections_by_kind.get(correction.kind, 0) >= kind_cap:
            return
        self._corrections_by_kind[correction.kind] = (
            self._corrections_by_kind.get(correction.kind, 0) + 1
        )
        # Remember the rules already steered on, so the same one is not raised
        # twice in a call.
        self._corrected_flags.update(f.lower() for f in correction.flags)
        self._corrections_sent += 1
        logger.info(
            "self-correction · session=%s · kind=%s · severity=%s · %s/%s",
            self.session.session_id,
            correction.kind,
            correction.severity,
            self._corrections_sent,
            turn_critic.MAX_CORRECTIONS_PER_CALL,
        )
        try:
            await self._on_correction(correction)
        except Exception:
            logger.debug("correction injection failed", exc_info=True)

    async def _handle_whisper(self, job: _Job) -> None:
        """Inject floor supervisor whispers. Not counted against the critic budget."""
        if self._on_correction is None or self._closed:
            return
        from agent_core.live_qa.enact import whisper_correction

        for note in job.payload.get("notes") or []:
            correction = whisper_correction(str(note or ""))
            if correction is None:
                continue
            try:
                await self._on_correction(correction)
            except Exception:
                logger.debug("whisper injection failed", exc_info=True)

    def _drain_whispers(self) -> None:
        if self._closed or self._on_correction is None:
            return
        from agent_core.live_qa.enact import consume_whispers

        notes = consume_whispers(self.session.interaction_id or "")
        if not notes:
            return
        job = _Job("whisper", {"notes": notes})
        loop = self._loop
        try:
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(self._enqueue_analysis_job, job)
            else:
                self._enqueue_analysis_job(job)
        except RuntimeError:
            logger.debug("whisper enqueue after loop close", exc_info=True)

    def _handle_understanding(self, job: _Job) -> None:
        """Classify one turn and publish the result. Runs in a worker thread."""
        from agent_core.understanding import analyze_turn

        p = job.payload
        turn_index = int(p.get("turn_index") or 0)
        result = analyze_turn(
            str(p.get("text") or ""),
            prior_intent=p.get("prior_intent"),
            channel="voice",
            recent=list(p.get("recent") or []),
        )
        # Publish even when the LLM was skipped or shed: a keyword result on the
        # session is what the offer engine and lead capture read, and it is
        # strictly better than each of them re-deriving their own.
        #
        # Guard against a late arrival overwriting a newer turn — the queue is
        # FIFO but a slow call can still land after a faster later one was
        # dropped, and a stale intent on the session is worse than none.
        if turn_index >= self.session.understanding_turn_index:
            self.session.understanding = result
            self.session.understanding_turn_index = turn_index

        # Upgrade the call goal's intent from the keyword baseline captured at
        # capture_call_goal time. Matched on the goal's own turn — by now
        # `understanding` describes a later turn (usually the digits the caller
        # read out), whose intent says nothing about why they called.
        if (
            result.source == "llm"
            and self.session.call_goal_turn_index is not None
            and turn_index == self.session.call_goal_turn_index
        ):
            self.session.call_goal_intent = result.intent

        if result.source != "llm":
            return

        # Same correction the DB gets, sent to the live UI. Without it the
        # Inspector keeps showing the keyword baseline for the rest of the call
        # while the persisted row says something better.
        #
        # This method runs in a worker thread (to_thread), so the emit has to be
        # handed back to the loop rather than awaited here — same boundary the
        # critique job crosses.
        self._emit_turn_threadsafe(
            turnIndex=turn_index,
            speaker="customer",
            intent=result.intent,
            intentScores=getattr(result, "intent_scores", None),
            sentiment=result.sentiment,
            source="llm",
        )

        # Correct what the keyword pass already persisted for this turn.
        ix = self.session.interaction_id
        if not ix:
            self._note_dropped("turn_understanding")
            return
        try:
            persist.update_turn_understanding(
                interaction_id=ix,
                turn_index=turn_index,
                intent=result.intent,
                intent_score=result.intent_score,
                sentiment=result.sentiment,
            )
        except Exception:
            logger.debug("turn understanding persist failed", exc_info=True)

    def enqueue_tool_call(
        self,
        *,
        tool_name: str,
        turn_index: int,
        result_ok: bool,
        error: str | None,
        latency_ms: int,
        args: dict[str, Any] | None = None,
    ) -> None:
        """Audit one voice tool call. Queued — the caller is mid-turn.

        ``args`` are filtered by ``persist._audit_args`` on the way to the row,
        not here: this runs on the turn and must stay a dict copy and an enqueue.
        """
        self.enqueue(
            "tool_call",
            tool_name=tool_name,
            turn_index=turn_index,
            result_ok=result_ok,
            error=error,
            latency_ms=latency_ms,
            args=dict(args) if isinstance(args, dict) else None,
        )

    def enqueue_kb_gap(self, payload: dict[str, Any]) -> None:
        """Queue an unanswerable question for the KB-gap table.

        Synchronous and fire-and-forget so it can be handed to
        ``agent_core.tools.kb.search_knowledge_base`` as its ``gap_sink``. That
        handler runs in a worker thread but still inside the turn's latency
        budget — the model waits for the tool result before speaking — so the
        write is deferred rather than done inline.

        Unlike the transcript jobs this does not need ``interaction_id`` on the
        session: the payload already carries the one the tool call used.
        """
        self.enqueue("kb_gap", **payload)

    async def enqueue_alert(self, kind: str, reason: str) -> None:
        """Used by bot idle ladder / other live paths.

        Queued, not awaited: this is called from live audio-path handlers, and
        a to_thread() database write there adds an unbounded stall to the
        customer's turn whenever Postgres is slow.
        """
        if not self.session.interaction_id:
            self._note_dropped("live_alert")
            return
        self.enqueue("live_alert", alert_kind=kind, reason=reason)

    async def _trigger_escalate(self, reason: str, detail: str) -> None:
        if self._escalated_live:
            return
        self._escalated_live = True
        ix = self.session.interaction_id
        if ix:
            try:
                kind = (
                    "sentiment_drop"
                    if reason == "sentiment_drop"
                    else ("loop_detected" if reason == "loop_detected" else "escalation")
                )
                self.enqueue("live_alert", alert_kind=kind, reason=detail or reason)
            except Exception:
                logger.exception("live escalate alert failed")
        else:
            # The escalation still runs below — a caller who needs a human gets
            # one — but the alert that would have told the floor console why is
            # gone. Say so; this is the loss that used to be invisible.
            self._note_dropped("live_alert_escalation")
        if self._on_escalate is not None:
            try:
                await self._on_escalate(reason, detail)
            except Exception:
                logger.exception("on_escalate handler failed")

    def attach_aggregators(self, user_aggregator: Any, assistant_aggregator: Any) -> None:
        """Install the customer-turn handler.

        ``assistant_aggregator`` is accepted but no longer subscribed to: bot
        turns are read at the LLM→TTS boundary instead, via
        :meth:`record_bot_turn`. See that method for why.
        """

        @user_aggregator.event_handler("on_user_turn_stopped")
        async def _on_user_turn_stopped(aggregator, strategy, message):
            content = getattr(message, "content", None) or ""
            if not str(content).strip():
                return
            text = str(content).strip()
            self._last_customer_text = text
            self._customer_exchanges += 1
            turn_index = self.session.next_turn_index()
            score, label = persist.score_customer_text(text)
            intent, intent_scores = classify_intent(text)
            top_score = float(intent_scores.get(intent) or 0.0) if intent_scores else None
            self._sentiment_scores.append(score)
            self.enqueue(
                "customer_turn",
                turn_index=turn_index,
                text=text,
                at_sec=self.session.at_sec(),
                score=score,
                label=label,
                intent=intent,
                intent_score=top_score,
            )
            # Schedule the LLM refinement on the separate analysis queue. The
            # keyword classification above is unchanged and still what gets
            # persisted first: this handler is awaited by Pipecat on the
            # pipeline task, so nothing here may wait on Azure. The refinement
            # lands a moment later and corrects the row.
            #
            # Snapshot the run-up *before* appending this turn — the analyser
            # takes the turn under test separately, and passing it twice makes
            # the caller look like they are repeating themselves.
            self.enqueue_understanding(
                turn_index=turn_index,
                text=text,
                prior_intent=getattr(self.session.understanding, "intent", None),
                recent=list(self._recent_turns),
            )
            self._remember_turn("customer", text)
            await self._emit_turn(
                turnIndex=turn_index,
                speaker="customer",
                text=text,
                atSec=self.session.at_sec(),
                sentiment=score,
                sentimentLabel=label,
                intent=intent,
                intentScores=intent_scores or None,
                source="keyword",
            )

            # Live tripwires (edges 13/14/17/16/22) — never block the audio path
            # long. Independently guarded: a shared try meant a failure in the
            # hold or language handler skipped the abuse, legal and
            # sentiment-collapse checks for that turn, which are the compliance
            # ones and must run regardless.
            try:
                if detect_hold_request(text) and self._on_hold is not None:
                    await self._on_hold()
            except Exception:
                logger.exception("hold-request tripwire failed")

            try:
                lang = resolve_language_action(
                    text,
                    current_language=self._stt_language,
                    fallback_languages=self._fallback_languages,
                )
                if lang and self._on_language is not None:
                    await self._on_language(lang)
            except Exception:
                logger.exception("language tripwire failed")

            try:
                if detect_abuse(text):
                    await self._trigger_escalate("compliance", "abuse_detected")
                elif detect_legal(text):
                    await self._trigger_escalate("compliance", "legal_mention")
                elif rolling_sentiment_collapsed(self._sentiment_scores):
                    # Same window the detector used. A hardcoded slice here was
                    # free to drift from SENTIMENT_WINDOW, so the average an
                    # agent reads in the escalation detail would stop matching
                    # the threshold that actually fired.
                    window = self._sentiment_scores[-SENTIMENT_WINDOW:]
                    avg_window = sum(window) / len(window) if window else 0.0
                    await self._trigger_escalate(
                        "sentiment_drop",
                        f"rolling_sentiment<={avg_window:.2f}",
                    )
            except Exception:
                logger.exception("customer-turn tripwire failed")

    async def _emit_turn(self, **payload: Any) -> None:
        """Hand one turn's analysis to the live UI. Never raises, never blocks."""
        if self._on_turn is None:
            return
        try:
            await self._on_turn({k: v for k, v in payload.items() if v is not None})
        except Exception:
            logger.exception("live turn handler failed")

    def _emit_turn_threadsafe(self, **payload: Any) -> None:
        """:meth:`_emit_turn` from a worker thread. Fire-and-forget."""
        loop = self._loop
        if self._on_turn is None or loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._emit_turn(**payload), loop)
        except Exception:
            logger.debug("threadsafe turn emit failed", exc_info=True)

    async def record_bot_turn(self, text: str, interrupted: bool = False) -> None:
        """Persist one bot turn. Called from the LLM→TTS probe.

        Deliberately **not** driven off ``on_assistant_turn_stopped`` any more.
        That handler runs downstream of the output transport, which meant bot
        turns were stamped 10-20s after they were produced while customer turns
        were stamped immediately — two clocks for one conversation — and any
        turn the caller barged in on was dropped outright, because
        ``TTSService`` clears its pending ``LLMFullResponseEndFrame`` map on
        interruption. See voice/turn_probe.py for the full derivation.
        """
        text = (text or "").strip()
        if not text:
            return
        turn_index = self.session.next_turn_index()
        # Both halves of the exchange, so the analyser can see that the
        # caller's next turn repeats a request this reply did not satisfy.
        self._remember_turn("bot", text)
        # This drives the guardrail evaluator. Reuse the classification the
        # analysis queue already produced for the customer turn this reply
        # answers, rather than re-deriving one — free, and on a Hindi turn
        # the keyword re-derivation returns out_of_scope every time. Falls
        # back to the keyword path when the refinement has not landed yet;
        # no Azure call is possible here, this handler is on the pipeline.
        cached = self.session.understanding
        if cached is not None:
            intent = cached.intent
        else:
            intent, _ = classify_intent(self._last_customer_text or text)
        # Consume the most recent LLM metrics for this bot turn.
        ttfb = self._pending_ttfb_ms
        ttfa = self._pending_ttfa_ms
        tokens = self._pending_tokens
        # The breakdown fires on BotStartedSpeakingFrame, i.e. earlier in
        # this same turn — so it has the same lifecycle as _pending_ttfb_ms
        # and drains here rather than through a job kind of its own. A
        # separate job would have to UPDATE this row, racing the
        # ON CONFLICT DO NOTHING insert below.
        breakdown = self._pending_breakdown
        self._pending_ttfb_ms = None
        self._pending_ttfa_ms = None
        self._pending_tokens = None
        self._pending_breakdown = {}
        self.enqueue(
            "bot_turn",
            turn_index=turn_index,
            text=text,
            at_sec=self.session.at_sec(),
            interrupted=interrupted,
            intent=intent,
            customer_text=self._last_customer_text,
            customer_bot_exchanges=self._customer_exchanges,
            # Snapshot taken BEFORE this turn is appended below. The drain
            # runs later, by which point _recent_bot_texts already contains
            # this turn — comparing it against itself would score 1.0 and
            # report every single turn as a repetition.
            prior_bot_turns=list(self._recent_bot_texts),
            # Snapshot of the calls-so-far disclosure state, taken before this
            # turn is folded in below — the evaluator adds "or this turn says
            # it" itself, and passing the post-fold value would make every turn
            # look retroactively compliant.
            recording_disclosed=self._recording_disclosed,
            ttfb_ms=int(ttfb) if ttfb is not None else None,
            ttfa_ms=int(ttfa) if ttfa is not None else None,
            tokens=int(tokens) if tokens is not None else None,
            **breakdown,
        )
        await self._emit_turn(
            turnIndex=turn_index,
            speaker="bot",
            text=text,
            atSec=self.session.at_sec(),
            interrupted=interrupted,
            intent=intent,
            ttfbMs=int(ttfb) if ttfb is not None else None,
            ttfaMs=int(ttfa) if ttfa is not None else None,
            tokens=int(tokens) if tokens is not None else None,
            **{_camel(k): v for k, v in breakdown.items()},
        )
        # Same predicate the guardrail uses (agent_core.guardrails). A bare
        # "record" substring also matched "let me record your promise to
        # pay", which would mark an undisclosed call compliant.
        if not self._recording_disclosed and mentions_recording_disclosure(text):
            self._recording_disclosed = True
        self._recent_bot_texts.append(text)
        if len(self._recent_bot_texts) > 8:
            self._recent_bot_texts = self._recent_bot_texts[-8:]
        try:
            if detect_bot_loop(self._recent_bot_texts):
                await self._trigger_escalate("loop_detected", "near_identical_bot_turns")
        except Exception:
            logger.exception("bot-loop tripwire failed")

    def record_ttfb_ms(self, ms: float) -> None:
        if ms and ms > 0:
            self._ttfb_samples_ms.append(float(ms))
            self._pending_ttfb_ms = float(ms)

    def current_avg_sentiment(self) -> float | None:
        """On-demand rolling average for mid-call routing (before stop())."""
        if not self._sentiment_scores:
            return None
        return sum(self._sentiment_scores) / len(self._sentiment_scores)

    def current_sentiment(self) -> float:
        """Latest reading, not the average.

        The offer gate cares whether the caller is receptive *now*. An average
        drags a call that has just turned sour back over the threshold, which is
        precisely when we must not pitch.
        """
        return float(self._sentiment_scores[-1]) if self._sentiment_scores else 0.0

    def sentiment_trend(self) -> float:
        """Slope across the last three readings. Warming up and cooling down can
        sit at the same absolute score."""
        recent = self._sentiment_scores[-3:]
        return float(recent[-1] - recent[0]) if len(recent) >= 2 else 0.0

    def last_customer_text(self) -> str:
        """The caller's most recent utterance.

        capture_lead needs it: the transcript snippet on the lead is the only
        context the follow-up specialist gets, and it was being written as a
        generic "Interest in <product>" because this was never exposed.
        """
        return str(self._last_customer_text or "")

    def customer_turns(self) -> int:
        return int(self._customer_exchanges)

    def record_ttfa_ms(self, ms: float) -> None:
        if ms and ms > 0:
            self._pending_ttfa_ms = float(ms)

    def record_tokens(self, tokens: int) -> None:
        if tokens and tokens > 0:
            self._pending_tokens = int(tokens)

    def _auto_barge(self, interaction_id: str, reason: str) -> None:
        from agent_core.live_qa import decisions as live_decisions
        from agent_core.live_qa.enact import barge_audio

        audio = barge_audio(interaction_id, reason=reason)
        try:
            persist.record_handoff(
                interaction_id=interaction_id,
                reason="compliance",
            )
        except Exception:
            logger.exception("live_qa auto-barge handoff failed for %s", interaction_id)
        pending = live_decisions.pending_auto_barge(interaction_id)
        if pending:
            live_decisions.mark_enacted(
                pending.get("id"),
                ref=str(audio.get("conference") or audio.get("reason") or ""),
            )
        logger.info(
            "live_qa auto-barge · ix=%s · audio=%s · reason=%s",
            interaction_id,
            audio.get("audio"),
            reason,
        )

    def _write_customer_memory(self, interaction_id: str, payload: dict[str, Any]) -> None:
        """Persist what the *next* call should already know. Never fatal.

        Gated on identity_verified as well as the flag: an unverified call has no
        trustworthy customer binding, and writing memory against a guessed
        customer_id would poison the next caller's context.
        """
        try:
            from voice import config as voice_config
            from voice import memory

            if not voice_config.voice_memory():
                return
            customer_id = self.session.customer_id
            if not customer_id or not self.session.identity_verified:
                return
            if customer_id == persist.UNKNOWN_CALLER_ID:
                return

            commitments = memory.open_commitments(customer_id)
            summary = memory.summarize_call(
                interaction_id=interaction_id, customer_id=customer_id
            )
            memory.upsert_memory(
                customer_id=customer_id,
                summary=summary,
                open_commitments=commitments,
                last_sentiment=payload.get("avg_sentiment"),
                last_interaction_id=interaction_id,
                last_channel=self.session.transport,
            )
            logger.info(
                "customer_memory written · customer=%s · commitments=%s · summary=%s",
                customer_id,
                len(commitments),
                "yes" if summary else "none",
            )
        except Exception:
            logger.exception(
                "customer_memory upsert failed (non-fatal) · interaction=%s", interaction_id
            )

    def record_user_bot_latency_ms(self, ms: float) -> None:
        """User-stopped-speaking → bot-started-speaking, the number a caller feels."""
        if ms and ms > 0:
            self._user_bot_latency_ms.append(float(ms))

    def record_latency_breakdown(self, breakdown: Any) -> None:
        """Stash Pipecat's per-service LatencyBreakdown for the next bot turn.

        Maps ``breakdown.ttfb`` onto stt/llm/tts by substring on the reporting
        processor's name (they look like ``AzureSTTService#0`` /
        ``KeepAliveAzureLLMService#0``), because the observer reports whichever
        services are in the pipeline rather than named slots. An unrecognised
        processor is dropped rather than guessed at.

        Durations are seconds throughout Pipecat — see _as_ms in build_observer
        for why that is asserted rather than sniffed.
        """
        try:
            out: dict[str, int] = {}
            for item in getattr(breakdown, "ttfb", None) or []:
                secs = getattr(item, "duration_secs", None)
                if not secs or secs <= 0:
                    continue
                name = str(getattr(item, "processor", "") or "").lower()
                if "stt" in name:
                    key = "stt_ttfb_ms"
                elif "tts" in name:
                    key = "tts_ttfb_ms"
                elif "llm" in name:
                    key = "llm_ttfb_ms"
                else:
                    continue
                # First report wins: a retried service would otherwise overwrite
                # the measurement that actually delayed this turn.
                out.setdefault(key, int(float(secs) * 1000.0))

            turn_secs = getattr(breakdown, "user_turn_secs", None)
            if turn_secs:
                out["user_turn_ms"] = int(float(turn_secs) * 1000.0)

            aggregation = getattr(breakdown, "text_aggregation", None)
            agg_secs = getattr(aggregation, "duration_secs", None) if aggregation else None
            if agg_secs:
                out["aggregation_ms"] = int(float(agg_secs) * 1000.0)

            calls = getattr(breakdown, "function_calls", None) or []
            tool_secs = sum(float(getattr(c, "duration_secs", 0) or 0) for c in calls)
            if tool_secs > 0:
                out["tool_ms"] = int(tool_secs * 1000.0)

            if out:
                self._pending_breakdown = out
        except Exception:
            logger.exception("latency breakdown mapping failed")

    def latency_breakdown_payload(self, breakdown: Any) -> dict[str, Any]:
        """RTVI-shaped view of a breakdown, for the Sandbox Inspector."""
        mapped = dict(self._pending_breakdown)
        events: list[str] = []
        try:
            chronological = getattr(breakdown, "chronological_events", None)
            if callable(chronological):
                events = list(chronological())
        except Exception:
            logger.debug("chronological_events failed", exc_info=True)
        return {
            "sttTtfbMs": mapped.get("stt_ttfb_ms"),
            "llmTtfbMs": mapped.get("llm_ttfb_ms"),
            "ttsTtfbMs": mapped.get("tts_ttfb_ms"),
            "userTurnMs": mapped.get("user_turn_ms"),
            "toolMs": mapped.get("tool_ms"),
            "aggregationMs": mapped.get("aggregation_ms"),
            "toolNames": [
                str(getattr(c, "function_name", "") or "")
                for c in (getattr(breakdown, "function_calls", None) or [])
            ],
            "events": events,
        }

    def build_observer(self) -> Any | None:
        """Optional MetricsFrame observer — returns None if Pipecat API unavailable."""
        try:
            from pipecat.observers.base_observer import BaseObserver
            from pipecat.frames.frames import MetricsFrame
        except Exception:
            try:
                from pipecat.utils.base_object import BaseObject as BaseObserver  # type: ignore

                MetricsFrame = None  # type: ignore
            except Exception:
                return None

        # The usage classes carry their payload in `.value`, not as attributes on
        # the item, so they are matched by type rather than duck-typed. Optional
        # so an older/newer Pipecat that lacks them degrades to latency-only
        # observation instead of failing to build the observer at all.
        try:
            from pipecat.metrics.metrics import LLMUsageMetricsData, TTSUsageMetricsData
        except Exception:  # pragma: no cover - depends on pipecat version
            LLMUsageMetricsData = None  # type: ignore
            TTSUsageMetricsData = None  # type: ignore

        sink = self

        def _as_ms(value: Any) -> float | None:
            """Pipecat latency metrics are seconds — convert, don't guess.

            Every shape read below is documented and implemented in seconds:
            ``TTFBMetricsData.value`` is ``end_time - start_time``, and
            ``TTFAMetricsData.ttfa`` / ``.ttfb`` mirror it. The old magnitude
            test ("< 50 means seconds") happened to be right for realistic
            values but silently stopped converting above 50 s and would have
            multiplied a genuinely millisecond-valued field by a thousand.
            """
            try:
                v = float(value)
            except (TypeError, ValueError):
                return None
            if v <= 0:
                return None
            return v * 1000.0

        class _MetricsObserver(BaseObserver):  # type: ignore[misc,valid-type]
            async def on_push_frame(self, data):  # noqa: ANN001
                try:
                    frame = getattr(data, "frame", None) or data
                    if MetricsFrame is not None and isinstance(frame, MetricsFrame):
                        for item in getattr(frame, "data", None) or []:
                            name = str(getattr(item, "name", "") or "").lower()
                            cls = type(item).__name__.lower()

                            ttfb = getattr(item, "ttfb", None)
                            if ttfb is None and hasattr(item, "value") and "ttfb" in (name + cls):
                                ttfb = getattr(item, "value", None)
                            ms = _as_ms(ttfb)
                            if ms is not None:
                                sink.record_ttfb_ms(ms)

                            ttfa = getattr(item, "ttfa", None)
                            if ttfa is None and hasattr(item, "value") and "ttfa" in (name + cls):
                                ttfa = getattr(item, "value", None)
                            ms_a = _as_ms(ttfa)
                            if ms_a is not None:
                                sink.record_ttfa_ms(ms_a)

                            # leading_silence (new on TTFAMetricsData in 1.6.0)
                            # separates real TTS latency from padding at the
                            # head of the audio. Logged, deliberately not a
                            # column — it tunes the voice, it isn't a per-turn
                            # business metric.
                            lead = _as_ms(getattr(item, "leading_silence", None))
                            if lead is not None:
                                logger.debug(
                                    "tts leading silence %.0fms · session=%s",
                                    lead,
                                    sink.session.session_id,
                                )

                            # Token usage. This previously read `item.tokens` /
                            # `item.total_tokens` / `item.prompt_tokens` straight
                            # off the metrics item — none of which exist on
                            # LLMUsageMetricsData, whose fields are
                            # (processor, model, value: LLMTokenUsage). Every
                            # getattr returned None, so record_tokens() was never
                            # called and interaction_transcript.tokens was NULL on
                            # every live call ever recorded.
                            if LLMUsageMetricsData is not None and isinstance(
                                item, LLMUsageMetricsData
                            ):
                                usage = getattr(item, "value", None)
                                if usage is not None:
                                    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
                                    completion = int(
                                        getattr(usage, "completion_tokens", 0) or 0
                                    )
                                    # total_tokens is authoritative when present:
                                    # some providers report a total that exceeds
                                    # prompt+completion (audio/reasoning tokens).
                                    total = int(getattr(usage, "total_tokens", 0) or 0)
                                    if total > 0:
                                        sink.record_tokens(total)
                                    elif prompt or completion:
                                        sink.record_tokens(prompt + completion)
                                    sink.usage.record_llm(
                                        prompt_tokens=prompt,
                                        completion_tokens=completion,
                                        model=getattr(item, "model", None),
                                        cached_input_tokens=getattr(
                                            usage, "cache_read_input_tokens", None
                                        ),
                                        reasoning_tokens=getattr(
                                            usage, "reasoning_tokens", None
                                        ),
                                    )

                            # Characters synthesised, the unit Azure TTS bills.
                            if TTSUsageMetricsData is not None and isinstance(
                                item, TTSUsageMetricsData
                            ):
                                try:
                                    chars = int(getattr(item, "value", 0) or 0)
                                except (TypeError, ValueError):
                                    chars = 0
                                if chars > 0:
                                    sink.usage.record_tts(
                                        chars=chars, model=getattr(item, "model", None)
                                    )
                except Exception:
                    logger.exception("metrics observer failed")

        try:
            return _MetricsObserver()
        except Exception:
            logger.exception("could not construct metrics observer")
            return None

    async def _drain(self) -> None:
        while True:
            job = await self._queue.get()
            if job is None:
                break
            try:
                await asyncio.to_thread(self._handle_sync, job)
            except Exception:
                logger.exception(
                    "crm sink job failed · kind=%s · session=%s",
                    job.kind,
                    self.session.session_id,
                )

    def _handle_sync(self, job: _Job) -> None:
        p = job.payload
        if job.kind == "kb_gap":
            # Handled before the interaction_id guard below: the payload carries
            # the id the tool call actually used, and a gap is worth recording
            # even on a session whose interaction row never materialised.
            import db

            try:
                db.record_kb_gap(
                    question=str(p.get("question") or ""),
                    intent=p.get("intent"),
                    channel=p.get("channel") or "voice",
                    interaction_id=p.get("interaction_id"),
                )
            except Exception:
                logger.warning("kb gap write failed", exc_info=True)
            return

        ix = self.session.interaction_id
        if not ix:
            self._note_dropped(job.kind)
            return
        if job.kind == "tool_call":
            persist.record_voice_tool_call(
                interaction_id=ix,
                turn_index=int(p.get("turn_index") or 0),
                tool_name=str(p.get("tool_name") or ""),
                result_ok=bool(p.get("result_ok")),
                error=p.get("error"),
                latency_ms=p.get("latency_ms"),
                args=p.get("args") if isinstance(p.get("args"), dict) else None,
            )
            return
        if job.kind == "live_alert":
            persist.append_live_alert(
                interaction_id=ix,
                kind=str(p.get("alert_kind") or "escalation"),
                reason=str(p.get("reason") or ""),
            )
            return
        if job.kind == "live_qa_barge":
            self._auto_barge(ix, str(p.get("reason") or "live_qa"))
            return
        if job.kind == "customer_turn":
            persist.append_transcript_turn(
                interaction_id=ix,
                turn_index=int(p["turn_index"]),
                speaker="customer",
                text_content=p["text"],
                at_sec=float(p["at_sec"]),
                sentiment_delta=float(p["score"]),
                intent=p.get("intent"),
                intent_score=p.get("intent_score"),
            )
            persist.append_sentiment_point(
                interaction_id=ix,
                at_sec=float(p["at_sec"]),
                score=float(p["score"]),
                label=p.get("label"),
            )
            if p.get("intent"):
                try:
                    import capture
                    import db as _db

                    with _db.engine.begin() as conn:
                        capture.touch_primary_intent(conn, ix, str(p["intent"]))
                        if str(p["intent"]) in capture.PRODUCT_INTENTS:
                            capture.record_product_interest(
                                conn,
                                interaction_id=ix,
                                intent=str(p["intent"]),
                                snippet=str(p.get("text") or "")[:240],
                            )
                except Exception:
                    logger.exception("touch_primary_intent failed")
            persist.heartbeat(self.session.session_id)
        elif job.kind == "bot_turn":
            persist.append_transcript_turn(
                interaction_id=ix,
                turn_index=int(p["turn_index"]),
                speaker="bot",
                text_content=p["text"],
                at_sec=float(p["at_sec"]),
                ttfb_ms=p.get("ttfb_ms"),
                ttfa_ms=p.get("ttfa_ms"),
                tokens=p.get("tokens"),
                stt_ttfb_ms=p.get("stt_ttfb_ms"),
                llm_ttfb_ms=p.get("llm_ttfb_ms"),
                tts_ttfb_ms=p.get("tts_ttfb_ms"),
                user_turn_ms=p.get("user_turn_ms"),
                tool_ms=p.get("tool_ms"),
                aggregation_ms=p.get("aggregation_ms"),
            )
            if p.get("interrupted"):
                persist.append_interaction_flag(
                    interaction_id=ix,
                    flag="barge_in",
                    severity="low",
                )
            flags = persist.evaluate_and_flag_bot_turn(
                interaction_id=ix,
                customer_text=p.get("customer_text") or "",
                bot_text=p["text"],
                intent=p.get("intent") or "out_of_scope",
                guardrails=self.guardrails,
                turn_index=int(p["turn_index"]),
                elapsed_seconds=float(p.get("at_sec") or 0),
                customer_bot_exchanges=int(p.get("customer_bot_exchanges") or 0),
                identity_verified=bool(self.session.identity_verified),
                third_party=bool((self.session.extra or {}).get("third_party")),
                channel="voice",
                customer_id=self.session.customer_id,
                account_id=self.session.account_id,
                max_waiver_inr=_session_waiver_cap(self.session),
                # A rehearsal reaches no customer, and an inbound caller chose
                # the hour themselves. Without these the RBI calling-window
                # check fired on turn 1 of a 20:43 sandbox call and spent a
                # high-severity self-correction before anyone had spoken.
                direction=self.call_direction,
                simulated=self.simulated_call,
                recording_disclosed=bool(p.get("recording_disclosed")),
            )
            self._drain_whispers()
            if "live-qa-auto-barge" in flags:
                self.enqueue("live_qa_barge", reason=next(
                    (f for f in flags if f in {
                        "hours-breach",
                        "third-party-leak",
                        "identity-before-verify",
                        "authority-cap-exceeded",
                        "auto-escalate",
                        "opt-out-ignored",
                    }),
                    "live_qa",
                ))
            # The flags used to stop here, in a database row nobody reads until
            # the QA review. Hand them to the critic so the next turn can
            # actually change.
            #
            # This is deliberately a lighter trigger than the `detect_bot_loop`
            # tripwire on the enqueue side: that one needs three near-identical
            # turns at 0.92 similarity and escalates the call to a human. The
            # critic fires on two at 0.82 and merely nudges — the intent being
            # to break the loop before it earns an escalation.
            self.enqueue_critique(
                bot_text=p["text"],
                user_text=p.get("customer_text") or "",
                guardrail_flags=flags,
                recent_bot_turns=list(p.get("prior_bot_turns") or []),
            )
            persist.heartbeat(self.session.session_id)
        elif job.kind == "complete":
            if self._completed:
                return
            self._completed = True
            persist.complete_voice_call(
                session_id=self.session.session_id,
                interaction_id=ix,
                status=str(p.get("status") or "completed"),
                latency_ms=p.get("latency_ms"),
                rag_hits=int(p.get("rag_hits") or 0),
                avg_sentiment=p.get("avg_sentiment"),
                summary=p.get("summary"),
                disposition=p.get("disposition"),
            )
            # Off audio path — serialize turns after CRM close.
            try:
                exported = persist.export_transcript_json(
                    interaction_id=ix,
                    session_id=self.session.session_id,
                )
                if exported:
                    logger.info(
                        "transcript export · interaction=%s · media=%s · turns=%s",
                        ix,
                        exported.get("mediaId"),
                        exported.get("turnCount"),
                    )
            except Exception:
                logger.exception("transcript export failed · interaction=%s", ix)

            # Cross-call memory. Deliberately AFTER complete_voice_call, in its
            # own try/except, so a slow or failing summariser can never block
            # call closure. This whole handler already runs in asyncio.to_thread
            # off the audio path, and azure_openai.chat_complete is synchronous,
            # so there is nothing to await here.
            self._write_customer_memory(ix, p)
        elif job.kind == "heartbeat":
            persist.heartbeat(self.session.session_id)


def bind_session_start(
    session: VoiceSession,
    *,
    deployment_id: str | None,
    transport: str = "smallwebrtc",
    provider_call_id: str | None = None,
    customer_id: str | None = None,
    bot_id: str | None = None,
    direction: str = "inbound",
) -> dict[str, Any]:
    """Synchronous start — call from on_client_connected via to_thread.

    ``direction`` is forwarded rather than left to ``start_voice_call``'s
    default: an outbound dial recorded as ``inbound`` is not a cosmetic error,
    it inverts every contact-attempt and answer-rate report built on the column.
    """
    row = persist.start_voice_call(
        session_id=session.session_id,
        deployment_id=deployment_id,
        transport=transport,
        provider_call_id=provider_call_id,
        customer_id=customer_id,
        bot_id=bot_id,
        direction=direction,
    )
    session.interaction_id = row["interactionId"]
    session.customer_id = row["customerId"]
    session.account_id = row.get("accountId")
    session.deployment_id = deployment_id
    if row.get("startedAt"):
        session.call_started_at = row["startedAt"]
    return row


def _session_waiver_cap(session: Any) -> float | None:
    extra = getattr(session, "extra", None) or {}
    raw = extra.get("max_waiver_inr")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
