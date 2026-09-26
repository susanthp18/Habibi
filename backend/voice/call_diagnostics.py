"""Every step of a call, numbered, for reading one test call end to end.

The trace spine (``voice.trace dial.* / ws.* / setup.* / turn.* / tool.*``) says
*when* things happened. It does not say what the caller was heard to say, what
the model was actually given, what it wrote, whether all of that was spoken,
or whether the reply was any good -- and analysing VS-7956F27B36 meant
rebuilding each of those from pipecat's DEBUG context dumps, one 30k-token
line at a time. This observer writes them down as they happen:

    diag.stt        what speech recognition heard, how late, how many partials
    diag.llm_in     what one model request carried: messages, size, the
                    injected blocks (KB, CRM card, node rules), tools offered
    diag.llm_out    what the model wrote: time to first token, length, tool
                    calls, and the quality checks below
    diag.say        text spoken without the model (fillers, phrase cache)
    diag.spoken     what reached the caller's ear, against what was written --
                    the input/output mismatch check
    diag.interrupt  a barge-in: how far into the bot's speech, what was cut
    diag.error      any ErrorFrame, from any processor
    diag.scorecard  the whole call in one line, at hang-up

Quality checks on every reply (``flags=``): ``long`` (over 45 words, the voice
overlay's cap), ``multi_q`` (more than one question), ``digits`` (a run of
three or more digits read aloud), ``format`` (INR / Rs / ISO dates spoken),
``name`` (the caller's name more than once, or in consecutive replies),
``repeat`` (mostly the same words as a recent reply), ``same_opener``,
``apology``, ``markup`` (list or markdown syntax), ``template`` (braces or a
placeholder), ``deflect`` ("I'm not able to..."), ``no_q`` (ended on a statement
while the call is open).

Every line carries ``step=`` (monotonic within the call) and ``t=`` (seconds
since the call connected), plus the call's ids, so the whole call reads in
order with ``grep "diag\\."``. Spoken text goes through
:func:`voice.call_trace.preview`, which strips digit runs: a verification
answer never reaches the log.

Read-only: an observer sees frames, it cannot hold or alter them, and every
handler is wrapped so a bug here can never touch the call.
"""

from __future__ import annotations

import logging
import re
import statistics
import time
from collections import Counter, deque
from typing import Any, Callable

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    ErrorFrame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver

from voice.call_trace import event, preview, session_fields

logger = logging.getLogger(__name__)

_WATCHED = (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    ErrorFrame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)

#: The voice overlay caps a reply at 45 spoken words.
LONG_REPLY_WORDS = 45
#: Word-trigram overlap with a recent reply above which it counts as a repeat.
REPEAT_JACCARD = 0.5

_WORD = re.compile(r"[a-z0-9']+")
_DIGIT_RUN = re.compile(r"\d[\d ,.-]{1,}\d")
_FORMAT_LEAK = re.compile(r"\bINR\b|\bRs\.?(?=\s|\d)|\b\d{4}-\d{2}-\d{2}\b")
_MARKUP = re.compile(r"(^|\n)\s*([-*•]|\d+\.)\s|\*\*|__|#{1,3}\s")
_TEMPLATE = re.compile(r"\{\{?\s*\w+|\[\s*[A-Z_]{3,}\s*\]|\bTODO\b|<[a-z_]+>")
_DEFLECT = re.compile(
    r"\b(i('m| am) (not able|unable)|i (can't|cannot) (help|answer|access)|"
    r"i don't have (that|access|the)|a specialist will)\b",
    re.I,
)
_APOLOGY = re.compile(r"\b(sorry|apolog)", re.I)
_CLOSING = re.compile(r"\b(goodbye|bye|take care|have a (good|great|nice))\b", re.I)


def _words(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def _trigrams(words: list[str]) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + 3]) for i in range(len(words) - 2)}


def _pct(values: list[float], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return int(ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))])


def _proc(obj: Any) -> str | None:
    return type(obj).__name__ if obj is not None else None


def reply_flags(
    text: str,
    *,
    name: str | None,
    previous: list[str],
    name_in_last: bool,
) -> tuple[list[str], dict[str, Any]]:
    """Quality checks on one reply. Pure, so it is tested without a pipeline."""
    words = _words(text)
    flags: list[str] = []
    facts: dict[str, Any] = {"words": len(words), "q": text.count("?")}
    if len(words) > LONG_REPLY_WORDS:
        flags.append("long")
    if facts["q"] > 1:
        flags.append("multi_q")
    if _DIGIT_RUN.search(text):
        flags.append("digits")
    if _FORMAT_LEAK.search(text):
        flags.append("format")
    if _MARKUP.search(text):
        flags.append("markup")
    if _TEMPLATE.search(text):
        flags.append("template")
    if _DEFLECT.search(text):
        flags.append("deflect")
    if _APOLOGY.search(text):
        flags.append("apology")
    if words and facts["q"] == 0 and not _CLOSING.search(text):
        flags.append("no_q")
    first = (name or "").strip().split(" ")[0].lower()
    uses = words.count(first) if len(first) >= 2 else 0
    facts["name_uses"] = uses or None
    if uses > 1 or (uses and name_in_last):
        flags.append("name")
    grams = _trigrams(words)
    for back, earlier in enumerate(reversed(previous), start=1):
        other = _trigrams(_words(earlier))
        if grams and other and len(grams & other) / len(grams | other) >= REPEAT_JACCARD:
            flags.append("repeat")
            facts["repeat_of"] = back
            break
    if previous and words[:3] and words[:3] == _words(previous[-1])[:3]:
        flags.append("same_opener")
    return flags, facts


def spoken_coverage(written: str, spoken: str) -> tuple[float | None, float | None]:
    """Share of the written words that were spoken, and of spoken words never written."""
    w, s = _words(written), _words(spoken)
    if not w and not s:
        return None, None
    wc, sc = Counter(w), Counter(s)
    common = sum((wc & sc).values())
    covered = round(common / len(w), 2) if w else None
    extra = round((len(s) - common) / len(s), 2) if s else None
    return covered, extra


class CallDiagnosticsObserver(BaseObserver):
    """Numbered, joinable trace of one call's content and quality."""

    def __init__(
        self,
        *,
        session: Any,
        name_getter: Callable[[], str | None] | None = None,
        node_getter: Callable[[], str | None] | None = None,
    ) -> None:
        super().__init__()
        self._session = session
        self._name_getter = name_getter
        self._node_getter = node_getter
        self._t0 = time.monotonic()
        self._step = 0
        self._seen_ids: set[Any] = set()
        self._seen_order: deque[Any] = deque()

        # Caller side.
        self._caller_stopped_at = 0.0
        self._caller_started_at = 0.0
        self._interims = 0
        # Model side.
        self._llm_in_at = 0.0
        self._response_started_at = 0.0
        self._first_token_at = 0.0
        self._text: list[str] = []
        self._tools_this_response: list[str] = []
        self._responses = 0
        self._started_tool_ids: set[str] = set()
        self._result_tool_ids: set[str] = set()
        # Ear side.
        self._written_unspoken: list[str] = []
        self._spoken: list[str] = []
        #: Words the output transport replayed -- i.e. played to the caller.
        self._heard: list[str] = []
        self._heard_seen = False
        self._maybe_empty = 0
        self._direct: list[str] = []
        self._bot_speaking_since = 0.0
        self._previous_replies: deque[str] = deque(maxlen=6)
        self._name_in_last = False

        # Scorecard.
        self._reply_latency_ms: list[float] = []
        self._stt_lag_ms: list[float] = []
        self._ttft_ms: list[float] = []
        self._flag_counts: Counter[str] = Counter()
        self._caller_turns = 0
        self._interruptions = 0
        self._errors = 0
        self._tool_calls = 0
        self._tool_errors = 0
        self._unspoken = 0
        self._unscripted = 0
        self._empty_replies = 0
        self._bot_words = 0
        self._caller_words = 0
        self._scored = False

    # -- plumbing -------------------------------------------------------------

    def _emit(self, name: str, **fields: Any) -> None:
        self._step += 1
        node = None
        if self._node_getter is not None:
            try:
                node = self._node_getter()
            except Exception:
                node = None
        try:
            event(
                name,
                step=self._step,
                t=round(time.monotonic() - self._t0, 2),
                node=node,
                **session_fields(self._session),
                **fields,
            )
        except Exception as exc:
            logger.warning("diag trace failed event=%s error_type=%s", name, type(exc).__name__)

    def _first_sighting(self, key: Any) -> bool:
        if key in self._seen_ids:
            return False
        self._seen_ids.add(key)
        self._seen_order.append(key)
        if len(self._seen_order) > 4096:
            self._seen_ids.discard(self._seen_order.popleft())
        return True

    def _caller_name(self) -> str | None:
        if self._name_getter is None:
            return None
        try:
            return self._name_getter()
        except Exception:
            return None

    async def on_push_frame(self, data: Any) -> None:
        frame = data.frame
        if not isinstance(frame, _WATCHED):
            return
        try:
            self._on_frame(frame, data)
        except Exception as exc:
            logger.warning(
                "diag observer failed frame=%s error_type=%s: %s",
                type(frame).__name__,
                type(exc).__name__,
                str(exc)[:120],
            )

    # -- frames ---------------------------------------------------------------

    def _on_frame(self, frame: Any, data: Any) -> None:
        # A context is logged where it enters the model, after every processor
        # upstream (the KB enricher, the CRM card refresher) has edited it.
        if isinstance(frame, LLMContextFrame):
            from pipecat.services.llm_service import LLMService

            if isinstance(getattr(data, "destination", None), LLMService) and self._first_sighting(
                ("llm_in", frame.id)
            ):
                self._llm_in(frame)
            return
        # Hang-up is scored where the frame *leaves* the pipeline. Its first
        # sighting is where it was queued, and the closing reply is generated
        # and spoken after that: both calls' scorecards missed their last turn.
        if isinstance(frame, (EndFrame, CancelFrame)):
            if str(getattr(getattr(data, "destination", None), "name", "")).endswith("::Sink"):
                self._settle_empty()
                self.scorecard(reason=type(frame).__name__)
            return
        # Words reach the ear when the output transport replays them at their
        # timestamps; the TTS service pushes the same frame earlier, when it
        # synthesises. On VS-58097BA530 a barge-in 1s into a 16-word question
        # was logged as all 16 words spoken.
        if isinstance(frame, TTSTextFrame) and "OutputTransport" in (_proc(getattr(data, "source", None)) or ""):
            if self._first_sighting(("heard", frame.id)):
                self._heard.append(str(getattr(frame, "text", "") or ""))
            return
        if not self._first_sighting(frame.id):
            return
        now = time.monotonic()

        if isinstance(frame, UserStartedSpeakingFrame):
            self._caller_started_at = now
            self._interims = 0
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._caller_stopped_at = now
        elif isinstance(frame, InterimTranscriptionFrame):
            self._interims += 1
        elif isinstance(frame, TranscriptionFrame):
            self._stt(frame, now)
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._settle_empty()
            self._response_started_at = now
            self._first_token_at = 0.0
            self._text = []
            self._tools_this_response = []
        elif isinstance(frame, LLMTextFrame):
            if not self._first_token_at:
                self._first_token_at = now
            self._text.append(str(getattr(frame, "text", "") or ""))
        elif isinstance(frame, FunctionCallInProgressFrame):
            tool_id = str(getattr(frame, "tool_call_id", "") or "")
            if tool_id and tool_id in self._started_tool_ids:
                return
            if tool_id:
                self._started_tool_ids.add(tool_id)
            # Tool frames follow LLMFullResponseEndFrame, so a tool-only reply
            # is only known not to be empty once they arrive.
            self._maybe_empty = 0
            self._tool_calls += 1
            self._tools_this_response.append(str(getattr(frame, "function_name", "") or "?"))
        elif isinstance(frame, FunctionCallResultFrame):
            tool_id = str(getattr(frame, "tool_call_id", "") or "")
            if tool_id and tool_id in self._result_tool_ids:
                return
            if tool_id:
                self._result_tool_ids.add(tool_id)
            result = getattr(frame, "result", None)
            if isinstance(result, dict) and (result.get("ok") is False or result.get("error")):
                self._tool_errors += 1
        elif isinstance(frame, LLMFullResponseEndFrame):
            self._llm_out(now)
        elif isinstance(frame, TTSSpeakFrame):
            text = str(getattr(frame, "text", "") or "")
            self._direct.append(text)
            self._emit("diag.say", preview=preview(text, limit=120), source=_proc(data.source))
        elif isinstance(frame, TTSTextFrame):
            self._spoken.append(str(getattr(frame, "text", "") or ""))
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking_since = now
            if self._caller_stopped_at and now >= self._caller_stopped_at:
                self._reply_latency_ms.append((now - self._caller_stopped_at) * 1000)
                self._caller_stopped_at = 0.0
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._flush_spoken(interrupted=False, now=now)
        elif isinstance(frame, InterruptionFrame):
            if self._bot_speaking_since:
                self._interruptions += 1
                self._emit(
                    "diag.interrupt",
                    into_bot_ms=int((now - self._bot_speaking_since) * 1000),
                    spoken_so_far=preview(" ".join(self._spoken), limit=100),
                )
                self._flush_spoken(interrupted=True, now=now)
        elif isinstance(frame, ErrorFrame):
            self._errors += 1
            self._emit(
                "diag.error",
                source=_proc(data.source),
                fatal=1 if getattr(frame, "fatal", False) else 0,
                error=preview(str(getattr(frame, "error", "") or ""), limit=240),
            )

    def _stt(self, frame: Any, now: float) -> None:
        text = str(getattr(frame, "text", "") or "")
        words = _words(text)
        self._caller_turns += 1
        self._caller_words += len(words)
        lag = None
        if self._caller_stopped_at and now >= self._caller_stopped_at:
            lag = int((now - self._caller_stopped_at) * 1000)
            self._stt_lag_ms.append(lag)
        flags = []
        if len(words) < 2:
            flags.append("short")
        if any(ch.isdigit() for ch in text):
            flags.append("digits")
        if any(ord(ch) > 127 for ch in text):
            flags.append("non_ascii")
        self._emit(
            "diag.stt",
            preview=preview(text, limit=160),
            words=len(words),
            lag_ms=lag,
            spoke_ms=(
                int((self._caller_stopped_at - self._caller_started_at) * 1000)
                if self._caller_stopped_at >= self._caller_started_at > 0
                else None
            ),
            interims=self._interims,
            lang=getattr(frame, "language", None),
            flags=",".join(flags) or None,
        )
        self._interims = 0

    def _llm_in(self, frame: Any) -> None:
        context = getattr(frame, "context", None)
        get = getattr(context, "get_messages", None)
        messages = list(get() or []) if callable(get) else list(getattr(context, "messages", []) or [])
        roles: Counter[str] = Counter()
        chars = 0
        blocks: list[str] = []
        last_user = None
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "?")
            roles[role] += 1
            content = message.get("content")
            if isinstance(content, list):
                content = " ".join(
                    str(part.get("text") or "") for part in content if isinstance(part, dict)
                )
            body = str(content or "")
            chars += len(body)
            if role in {"developer", "system"} and body:
                head = " ".join(body.split())[:48]
                blocks.append(head)
            if role == "user" and body:
                last_user = body
        tools = getattr(context, "tools", None)
        standard = getattr(tools, "standard_tools", None)
        tool_count = len(standard) if standard is not None else (len(tools) if isinstance(tools, list) else None)
        self._llm_in_at = time.monotonic()
        self._emit(
            "diag.llm_in",
            messages=len(messages),
            roles=",".join(f"{k}:{v}" for k, v in sorted(roles.items())),
            chars=chars,
            est_tokens=chars // 4,
            tools=tool_count,
            # The first words of each instruction block: which node rules, KB
            # grounding and CRM cards the model actually had on this turn.
            blocks=" | ".join(preview(b, limit=48) or "" for b in blocks[-8:]) or None,
            last_user=preview(last_user, limit=100),
        )

    def _llm_out(self, now: float) -> None:
        self._responses += 1
        text = "".join(self._text).strip()
        ttft = (
            int((self._first_token_at - self._response_started_at) * 1000)
            if self._first_token_at and self._response_started_at
            else None
        )
        if ttft is not None:
            self._ttft_ms.append(ttft)
        since_request = int((now - self._llm_in_at) * 1000) if self._llm_in_at else None
        flags: list[str] = []
        facts: dict[str, Any] = {}
        if text:
            flags, facts = reply_flags(
                text,
                name=self._caller_name(),
                previous=list(self._previous_replies),
                name_in_last=self._name_in_last,
            )
            self._name_in_last = bool(facts.get("name_uses"))
            self._previous_replies.append(text)
            self._written_unspoken.append(text)
            self._bot_words += facts.get("words", 0)
            self._flag_counts.update(flags)
        elif not self._tools_this_response:
            # No words yet no tool frame either -- but tool frames arrive after
            # this one. Decided at the next response or hang-up (_settle_empty);
            # flagging it here marked every tool call "empty".
            self._maybe_empty = self._responses
        self._emit(
            "diag.llm_out",
            response=self._responses,
            ttft_ms=ttft,
            gen_ms=int((now - self._response_started_at) * 1000) if self._response_started_at else None,
            since_request_ms=since_request,
            tools=",".join(self._tools_this_response) or None,
            preview=preview(text, limit=200),
            flags=",".join(flags) or None,
            **facts,
        )
        self._text = []
        self._response_started_at = 0.0

    def _settle_empty(self) -> None:
        """A reply with neither words nor a tool call: the caller heard nothing."""
        if not self._maybe_empty:
            return
        self._empty_replies += 1
        self._flag_counts.update(["empty"])
        self._emit("diag.empty_reply", response=self._maybe_empty)
        self._maybe_empty = 0

    def _flush_spoken(self, *, interrupted: bool, now: float) -> None:
        # What the caller heard when the transport reports it; what was
        # synthesised only on a transport that replays no word timestamps.
        source = self._heard if self._heard_seen or self._heard else self._spoken
        self._heard_seen = self._heard_seen or bool(self._heard)
        spoken = " ".join(t.strip() for t in source if t.strip())
        written = " ".join(self._written_unspoken)
        direct = " ".join(self._direct)
        if not (spoken or written):
            self._bot_speaking_since = 0.0
            return
        covered, extra = spoken_coverage(written + " " + direct, spoken)
        flags = []
        if not interrupted and covered is not None and covered < 0.8 and written:
            flags.append("unspoken")
            self._unspoken += 1
        if extra is not None and extra > 0.3 and spoken:
            flags.append("unscripted")
            self._unscripted += 1
        self._emit(
            "diag.spoken",
            interrupted=1 if interrupted else None,
            speech_ms=int((now - self._bot_speaking_since) * 1000) if self._bot_speaking_since else None,
            written_words=len(_words(written)) or None,
            spoken_words=len(_words(spoken)) or None,
            covered=covered,
            extra=extra,
            spoken=preview(spoken, limit=200),
            flags=",".join(flags) or None,
        )
        self._spoken, self._written_unspoken, self._direct = [], [], []
        self._heard = []
        self._bot_speaking_since = 0.0

    # -- the call in one line -------------------------------------------------

    def scorecard(self, *, reason: str) -> None:
        """Emit once per call, at the first EndFrame/CancelFrame or at cleanup."""
        if self._scored:
            return
        self._scored = True
        lat = self._reply_latency_ms
        top = ",".join(f"{k}:{v}" for k, v in self._flag_counts.most_common())
        self._emit(
            "diag.scorecard",
            reason=reason,
            duration_s=round(time.monotonic() - self._t0, 1),
            caller_turns=self._caller_turns,
            bot_responses=self._responses,
            caller_words=self._caller_words,
            bot_words=self._bot_words,
            talk_ratio=round(self._bot_words / self._caller_words, 1) if self._caller_words else None,
            reply_p50_ms=_pct(lat, 0.5),
            reply_p90_ms=_pct(lat, 0.9),
            reply_max_ms=int(max(lat)) if lat else None,
            reply_over_2s=sum(1 for v in lat if v > 2000) or None,
            stt_lag_p50_ms=_pct(self._stt_lag_ms, 0.5),
            ttft_p50_ms=_pct(self._ttft_ms, 0.5),
            ttft_mean_ms=int(statistics.fmean(self._ttft_ms)) if self._ttft_ms else None,
            interruptions=self._interruptions,
            tool_calls=self._tool_calls,
            tool_errors=self._tool_errors or None,
            errors=self._errors or None,
            empty_replies=self._empty_replies or None,
            unspoken=self._unspoken or None,
            unscripted=self._unscripted or None,
            flags=top or None,
        )

    async def cleanup(self) -> None:  # pragma: no cover - pipecat lifecycle
        try:
            self.scorecard(reason="cleanup")
        finally:
            parent = getattr(super(), "cleanup", None)
            if callable(parent):
                await parent()
