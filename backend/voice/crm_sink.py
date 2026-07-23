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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agent_core import classify_intent
from voice import persist
from voice.safety import (
    detect_abuse,
    detect_bot_loop,
    detect_hold_request,
    detect_legal,
    resolve_language_action,
    rolling_sentiment_collapsed,
)
from voice.session import VoiceSession

logger = logging.getLogger(__name__)

EscalateHandler = Callable[[str, str], Awaitable[None]]
HoldHandler = Callable[[], Awaitable[None]]
LanguageHandler = Callable[[dict[str, Any]], Awaitable[None]]


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
    ) -> None:
        self.session = session
        self.guardrails = guardrails or {}
        self._queue: asyncio.Queue[_Job | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._last_customer_text = ""
        self._customer_exchanges = 0
        self._sentiment_scores: list[float] = []
        self._recent_bot_texts: list[str] = []
        self._ttfb_samples_ms: list[float] = []
        self._closed = False
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
        stt_language: str = "en-IN",
        fallback_languages: list[str] | None = None,
    ) -> None:
        self._on_escalate = on_escalate
        self._on_hold = on_hold
        self._on_language = on_language
        self._stt_language = stt_language or "en-IN"
        if fallback_languages is not None:
            self._fallback_languages = list(fallback_languages)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._drain(), name=f"crm-sink-{self.session.session_id}")

    async def stop(self, *, final_status: str = "completed") -> None:
        if self._closed:
            return
        self._closed = True
        avg = (
            sum(self._sentiment_scores) / len(self._sentiment_scores)
            if self._sentiment_scores
            else None
        )
        latency = None
        if self._ttfb_samples_ms:
            sorted_s = sorted(self._ttfb_samples_ms)
            latency = int(sorted_s[len(sorted_s) // 2])
        self._queue.put_nowait(
            _Job(
                "complete",
                {
                    "status": final_status,
                    "avg_sentiment": avg,
                    "latency_ms": latency,
                    "rag_hits": self.session.rag_hits,
                },
            )
        )
        self._queue.put_nowait(None)
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning("crm sink drain timed out · session=%s", self.session.session_id)
                self._task.cancel()
            self._task = None

    def enqueue(self, kind: str, **payload: Any) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(_Job(kind, payload))
        except Exception:
            logger.exception("crm sink enqueue failed")

    async def enqueue_alert(self, kind: str, reason: str) -> None:
        """Used by bot idle ladder / other live paths."""
        ix = self.session.interaction_id
        if not ix:
            return
        try:
            await asyncio.to_thread(
                persist.append_live_alert,
                interaction_id=ix,
                kind=kind,
                reason=reason,
            )
        except Exception:
            logger.exception("enqueue_alert failed")

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
                await asyncio.to_thread(
                    persist.append_live_alert,
                    interaction_id=ix,
                    kind=kind,
                    reason=detail or reason,
                )
            except Exception:
                logger.exception("live escalate alert failed")
        if self._on_escalate is not None:
            try:
                await self._on_escalate(reason, detail)
            except Exception:
                logger.exception("on_escalate handler failed")

    def attach_aggregators(self, user_aggregator: Any, assistant_aggregator: Any) -> None:
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

            # Live tripwires (edges 13/14/17/16/22) — never block the audio path long.
            try:
                if detect_hold_request(text) and self._on_hold is not None:
                    await self._on_hold()
                lang = resolve_language_action(
                    text,
                    current_language=self._stt_language,
                    fallback_languages=self._fallback_languages,
                )
                if lang and self._on_language is not None:
                    await self._on_language(lang)
                if detect_abuse(text):
                    await self._trigger_escalate("compliance", "abuse_detected")
                elif detect_legal(text):
                    await self._trigger_escalate("compliance", "legal_mention")
                elif rolling_sentiment_collapsed(self._sentiment_scores):
                    await self._trigger_escalate(
                        "sentiment_drop",
                        f"rolling_sentiment<={sum(self._sentiment_scores[-4:]) / 4:.2f}",
                    )
            except Exception:
                logger.exception("customer-turn tripwire failed")

        @user_aggregator.event_handler("on_user_turn_message_added")
        async def _on_user_turn_message_added(aggregator, message):
            content = getattr(message, "content", None) or getattr(message, "text", None) or ""
            if not str(content).strip():
                return
            if str(content).strip() == self._last_customer_text:
                return

        @assistant_aggregator.event_handler("on_assistant_turn_stopped")
        async def _on_assistant_turn_stopped(aggregator, message):
            content = getattr(message, "content", None) or ""
            if not str(content).strip():
                return
            text = str(content).strip()
            interrupted = bool(getattr(message, "interrupted", False))
            turn_index = self.session.next_turn_index()
            intent, _ = classify_intent(self._last_customer_text or text)
            self.enqueue(
                "bot_turn",
                turn_index=turn_index,
                text=text,
                at_sec=self.session.at_sec(),
                interrupted=interrupted,
                intent=intent,
                customer_text=self._last_customer_text,
                customer_bot_exchanges=self._customer_exchanges,
            )
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

        sink = self

        class _MetricsObserver(BaseObserver):  # type: ignore[misc,valid-type]
            async def on_push_frame(self, data):  # noqa: ANN001
                try:
                    frame = getattr(data, "frame", None) or data
                    if MetricsFrame is not None and isinstance(frame, MetricsFrame):
                        for item in getattr(frame, "data", None) or []:
                            ttfb = getattr(item, "ttfb", None)
                            if ttfb is None and hasattr(item, "value"):
                                name = str(getattr(item, "name", "") or "").lower()
                                if "ttfb" in name:
                                    ttfb = getattr(item, "value", None)
                            if ttfb is not None:
                                ms = float(ttfb) * 1000.0 if float(ttfb) < 50 else float(ttfb)
                                sink.record_ttfb_ms(ms)
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
        ix = self.session.interaction_id
        if not ix:
            return
        p = job.payload
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
            )
            if p.get("interrupted"):
                persist.append_interaction_flag(
                    interaction_id=ix,
                    flag="barge_in",
                    severity="low",
                )
            persist.evaluate_and_flag_bot_turn(
                interaction_id=ix,
                customer_text=p.get("customer_text") or "",
                bot_text=p["text"],
                intent=p.get("intent") or "out_of_scope",
                guardrails=self.guardrails,
                turn_index=int(p["turn_index"]),
                elapsed_seconds=float(p.get("at_sec") or 0),
                customer_bot_exchanges=int(p.get("customer_bot_exchanges") or 0),
            )
            persist.heartbeat(self.session.session_id)
        elif job.kind == "complete":
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
) -> dict[str, Any]:
    """Synchronous start — call from on_client_connected via to_thread."""
    row = persist.start_voice_call(
        session_id=session.session_id,
        deployment_id=deployment_id,
        transport=transport,
        provider_call_id=provider_call_id,
        customer_id=customer_id,
        bot_id=bot_id,
    )
    session.interaction_id = row["interactionId"]
    session.customer_id = row["customerId"]
    session.account_id = row.get("accountId")
    session.deployment_id = deployment_id
    if row.get("startedAt"):
        session.call_started_at = row["startedAt"]
    return row
