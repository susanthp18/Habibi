"""Outbound AMD — Pipecat VoicemailDetector wiring + CRM disposition.

Only enabled for Twilio outbound legs (``call_type=outbound``). Sandbox Live and
inbound dial-in skip this path — the browser/human is never a voicemail box.

What a voicemail may say
------------------------
Almost nothing, and this module used to say considerably more than that. The
shipped script was:

    "Hello, this is Priya calling from HDFC Bank collections regarding your
     account. Please call us back at your earliest convenience."

Two defects in one sentence, and both are the kind that end a pilot:

* **It discloses the debt.** A voicemail plays to whoever opens the inbox — a
  spouse, a flatmate, a colleague with the handset. "Collections regarding your
  account" tells them the borrower owes money, which is the borrower's
  information and not ours to share (RBI para 100O).
* **It omits a required disclosure.** A voicemail *is* a recovery
  communication, and para 100AA requires the grievance officer's name, email and
  telephone number in all of them.

So the message now identifies the caller, asks for a call back on a number that
will still be answered tomorrow, names the grievance officer, and says nothing
about why. If the tenant has not recorded a grievance contact, no message is
left at all — an attempt with no voicemail is a lesser failure than a
non-compliant communication, and the attempt records `voicemail_skipped` with
the reason so the gap is visible rather than silent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# Fallback wording when no deployment/persona config is available. Every
# deployment should render its own agent name and brand via voicemail_script().
_DEFAULT_AGENT_NAME = "Priya"
_DEFAULT_ISSUER = "HDFC Bank"

#: Kept as the module's advertised constant because tests and callers import it,
#: but it is now what it always should have been: an identification, not a
#: disclosure. It carries no grievance contact, so it is only ever the shape of
#: a message — :func:`voicemail_script` is what produces one fit to leave.
VOICEMAIL_SCRIPT = (
    f"Hello, this is {_DEFAULT_AGENT_NAME} calling from {_DEFAULT_ISSUER}. "
    "Please give us a call back when you have a moment. Thank you."
)


def tenant_contacts(tenant_id: str | None = None) -> dict[str, Any]:
    """Issuer, grievance officer and callback number for a tenant.

    Kept as a name on this module because callers import it from here, but the
    body now lives in :mod:`compliance_copy` — the disclosure this feeds is owed
    by the SMS and WhatsApp senders too, and two copies of it would have drifted
    exactly the way the docstring in ``treatment/enact._copy`` drifted from what
    that function actually returned.
    """
    import compliance_copy

    return compliance_copy.tenant_contacts(tenant_id)


def _spoken_number(raw: str | None) -> str:
    import compliance_copy

    return compliance_copy.spoken_number(raw)


def voicemail_script(
    persona: dict[str, Any] | None = None,
    tuning: dict[str, Any] | None = None,
    *,
    contacts: dict[str, Any] | None = None,
    include_grievance: bool = True,
) -> str | None:
    """Render the message, or None when it cannot be left compliantly.

    Returning None rather than a partial message is the load-bearing part: the
    duty is not "mention the grievance officer if you happen to know them", and
    a message that identifies the bank and asks for a call back while omitting
    the disclosure is still a recovery communication that owed one.
    """
    import compliance_copy

    p = persona or {}
    t = tuning or {}
    persona_block = t.get("persona") if isinstance(t.get("persona"), dict) else {}
    agent = str(
        p.get("agentName") or p.get("name") or persona_block.get("agentName") or ""
    ).strip() or _DEFAULT_AGENT_NAME

    resolved = contacts if contacts is not None else tenant_contacts()
    issuer = str(
        p.get("issuer")
        or p.get("brand")
        or persona_block.get("issuer")
        or resolved.get("issuer")
        or ""
    ).strip() or _DEFAULT_ISSUER

    parts = [f"Hello, this is {agent} calling from {issuer}."]

    callback = compliance_copy.spoken_number(resolved.get("contactNumber"))
    if callback:
        parts.append(f"Please call us back on {callback} when you have a moment.")
    else:
        parts.append("Please give us a call back when you have a moment.")

    if include_grievance:
        footer = compliance_copy.spoken_footer(resolved)
        if footer is None:
            return None
        parts.append(footer)

    parts.append("Thank you.")
    # Nothing here says why we called, and that is the point — see the module
    # docstring. Any change to this wording should be checked against the
    # `voicemail_discloses_nothing` grader.
    return " ".join(parts)


def _twilio_params(session_extra: dict[str, Any] | None) -> dict[str, Any]:
    extra = session_extra or {}
    params = extra.get("twilio_params") if isinstance(extra.get("twilio_params"), dict) else {}
    return params


def is_demo_call(session_extra: dict[str, Any] | None) -> bool:
    """The demo button stamps ``demo=1`` on the stream. That handset is never a mailbox."""
    extra = session_extra or {}
    params = _twilio_params(extra)
    raw = params.get("demo") if params.get("demo") is not None else extra.get("demo")
    return str(raw or "").strip().lower() in {"1", "true", "yes"}


def should_enable_amd(session_extra: dict[str, Any] | None, *, is_twilio: bool) -> bool:
    if not is_twilio:
        return False
    if is_demo_call(session_extra):
        return False
    extra = session_extra or {}
    params = _twilio_params(extra)
    call_type = str(params.get("call_type") or extra.get("call_type") or "").lower()
    return call_type == "outbound"


def voicemail_policy(session_extra: dict[str, Any] | None) -> dict[str, Any]:
    """The card's voicemail policy for this mission, or the conservative default.

    ``first_attempt_only`` is the default because a second message rarely adds
    anything a first one did not, and every one of them spends a contact touch.
    """
    extra = session_extra or {}
    mission = extra.get("mission") if isinstance(extra.get("mission"), dict) else {}
    policy = mission.get("voicemail") if isinstance(mission.get("voicemail"), dict) else {}
    return {
        "leave": str(policy.get("leave") or "first_attempt_only"),
        "maxSec": int(policy.get("maxSec") or 25),
        "includeGrievance": bool(policy.get("includeGrievanceContact", True)),
        "attemptNo": int(mission.get("attemptNo") or 1),
    }


def should_leave_message(policy: dict[str, Any]) -> bool:
    leave = policy.get("leave")
    if leave == "never":
        return False
    if leave == "first_attempt_only":
        return int(policy.get("attemptNo") or 1) <= 1
    # "engine" means the decision engine will eventually score it; until it
    # does, behave like first_attempt_only rather than like "always".
    if leave == "engine":
        return int(policy.get("attemptNo") or 1) <= 1
    return True


def voicemail_action_allowed(
    session: Any,
    *,
    bot_speaking: bool = False,
    bot_has_spoken: bool = False,
    guard: Any = None,
) -> str | None:
    """Why a VOICEMAIL verdict must not speak or hang up, or None if it may.

    VS-4D8667B522 classified silence as voicemail, then left a grievance
    message over a live greeting. The classifier is allowed to guess; acting
    on that guess before the callee has spoken, or while the bot is already
    talking, is the defect.
    """
    extra = getattr(session, "extra", None) or {}
    if extra.get("amd") == "human" or extra.get("amd_verdict") == "conversation":
        return "already_decided"
    if extra.get("amd_closed"):
        return "already_decided"
    seen = bool(getattr(guard, "seen_speech", False) or extra.get("amd_callee_speech"))
    if not seen:
        return "no_callee_speech"
    if bot_speaking:
        return "bot_already_speaking"
    if not bot_has_spoken:
        return "greeting_incomplete"
    return None


def _close_classifier(session: Any, detector: Any, *, verdict: str) -> None:
    extra = getattr(session, "extra", None)
    if isinstance(extra, dict):
        extra["amd_verdict"] = verdict
        extra["amd_closed"] = True
    guard = getattr(detector, "_habibi_guard", None)
    if guard is not None:
        guard.closed = True


def _trace(name: str, session: Any, **fields: Any) -> None:
    try:
        from voice.call_trace import event, session_fields

        event(name, **session_fields(session), **fields)
    except Exception:
        logger.debug("amd trace failed", exc_info=True)


async def attach_voicemail_handlers(
    *,
    voicemail_detector: Any,
    session: Any,
    sink: Any,
    worker: Any,
    on_left_message: Callable[[], Awaitable[None]] | None = None,
    persona: dict[str, Any] | None = None,
    tuning: dict[str, Any] | None = None,
    bot_turn_state: Any = None,
) -> None:
    """Register conversation / voicemail event handlers on the detector."""
    from pipecat.frames.frames import EndWorkerFrame, TTSSpeakFrame
    from pipecat.processors.frame_processor import FrameDirection

    @voicemail_detector.event_handler("on_conversation_detected")
    async def _on_human(_detector) -> None:
        logger.info("AMD: live conversation · session=%s", session.session_id)
        session.extra["amd"] = "human"
        _close_classifier(session, voicemail_detector, verdict="conversation")
        _trace("amd.classify", session, verdict="CONVERSATION", acted=True)
        await _mark_attempt(session, answered_by="human")
        if hasattr(sink, "enqueue_alert"):
            try:
                await sink.enqueue_alert("compliance", "amd_human")
            except Exception:
                # Alerting is best-effort on the audio path, but a persistent
                # failure must be visible rather than swallowed silently.
                logger.warning("amd_human alert failed", exc_info=True)

    @voicemail_detector.event_handler("on_voicemail_detected")
    async def _on_voicemail(processor) -> None:
        speaking = bool(
            bot_turn_state is not None
            and (
                getattr(bot_turn_state, "speaking", lambda: False)()
                or getattr(bot_turn_state, "busy", lambda: False)()
            )
        )
        has_spoken = bool(
            (bot_turn_state is not None and getattr(bot_turn_state, "has_spoken", lambda: False)())
            or (session.extra or {}).get("first_bot_speech_done")
        )
        skip = voicemail_action_allowed(
            session,
            bot_speaking=speaking,
            bot_has_spoken=has_spoken,
            guard=getattr(voicemail_detector, "_habibi_guard", None),
        )
        if skip:
            logger.info(
                "AMD: voicemail verdict ignored · session=%s · %s",
                session.session_id,
                skip,
            )
            _trace("amd.voicemail_skipped", session, reason=skip, verdict="VOICEMAIL", acted=False)
            return

        session.extra["amd"] = "voicemail"
        session.extra["disposition"] = "voicemail"
        _close_classifier(session, voicemail_detector, verdict="voicemail")
        await _mark_attempt(session, answered_by="machine")

        policy = voicemail_policy(session.extra)
        script = None
        skip_reason = None
        if not should_leave_message(policy):
            skip_reason = f"policy:{policy['leave']}"
        else:
            script = voicemail_script(
                persona,
                tuning,
                include_grievance=policy["includeGrievance"],
            )
            if script is None:
                skip_reason = "no_grievance_contact"

        logger.info(
            "AMD: voicemail · session=%s · %s",
            session.session_id,
            "leaving message" if script else f"no message ({skip_reason})",
        )
        _trace(
            "amd.classify",
            session,
            verdict="VOICEMAIL",
            acted=bool(script),
            reason=skip_reason,
        )
        await _record_voicemail_state(session, left=bool(script), reason=skip_reason)

        try:
            from voice import persist

            ix = session.interaction_id
            if ix:
                # Placeholder media row — actual audio still flows through audiobuffer
                # if disclosure already started; kind marks the disposition for QA.
                await asyncio.to_thread(
                    persist.record_media,
                    interaction_id=ix,
                    kind="voicemail",
                    storage_ref=f"voicemail://{session.session_id}",
                    duration_sec=None,
                    mime_type="audio/wav",
                    size_bytes=0,
                )
        except Exception:
            logger.exception("voicemail media row failed")

        if script:
            try:
                await processor.push_frame(TTSSpeakFrame(script, append_to_context=False))
            except TypeError:
                # Older Pipecat without append_to_context — retry, but the retry
                # needs its own guard or a real TTS failure escapes this handler.
                try:
                    await processor.push_frame(TTSSpeakFrame(script))
                except Exception:
                    logger.exception("voicemail TTS failed (legacy frame signature)")
            except Exception:
                logger.exception("voicemail TTS failed")

            if on_left_message:
                try:
                    await on_left_message()
                except Exception:
                    logger.exception("voicemail on_left_message failed")

        try:
            await processor.push_frame(EndWorkerFrame(), FrameDirection.UPSTREAM)
        except Exception:
            try:
                await worker.queue_frame(EndWorkerFrame())
            except Exception:
                logger.exception("voicemail EndWorkerFrame failed")


async def _mark_attempt(session: Any, *, answered_by: str) -> None:
    """Tell the attempt ledger who picked up. Fire-and-forget."""
    attempt_id = (session.extra or {}).get("attempt_id")
    if not attempt_id:
        return

    def _write() -> None:
        import db as dbmod
        import outbound

        with dbmod.engine.begin() as conn:
            outbound.mark(conn, str(attempt_id), answered_by=answered_by)

    try:
        await asyncio.to_thread(_write)
    except Exception:
        logger.debug("attempt answered_by mark failed", exc_info=True)


async def _record_voicemail_state(session: Any, *, left: bool, reason: str | None) -> None:
    """``voicemail_left`` vs ``voicemail_skipped`` — the pair the engine learns from.

    Leaving a message costs a contact touch and has a callback lift that varies
    by segment. The two states have to be distinguishable in the log or the
    question "is a voicemail worth leaving for borrowers like this one" has no
    denominator.
    """
    attempt_id = (session.extra or {}).get("attempt_id")
    if not attempt_id:
        return

    def _write() -> None:
        import db as dbmod
        import outbound
        from sqlalchemy import text

        state = outbound.STATE_VOICEMAIL_LEFT if left else outbound.STATE_VOICEMAIL_SKIPPED
        with dbmod.engine.begin() as conn:
            outbound.mark(conn, str(attempt_id), state=state)
            if reason:
                conn.execute(
                    text(
                        "UPDATE call_attempts SET context = context || CAST(:patch AS jsonb), "
                        "updated_at = now() WHERE id = :id"
                    ),
                    {"id": str(attempt_id), "patch": '{"voicemailSkipped": "%s"}' % reason},
                )

    try:
        await asyncio.to_thread(_write)
    except Exception:
        logger.debug("voicemail state write failed", exc_info=True)


# ---------------------------------------------------------------------------
# Flow-safe voicemail detection
# ---------------------------------------------------------------------------


class _ClassifierContextGuard:
    """Keeps the voicemail classifier reading the callee, and only the callee.

    ``VoicemailDetector`` is a ``ParallelPipeline``: every frame entering it is
    copied into *both* branches. One branch is the conversation, the other is a
    small LLM whose entire job is to read what the callee said and answer
    CONVERSATION or VOICEMAIL. Two different things reached it that should not
    have, and each produced the same wrong verdict on a live human.

    **The conversation's own script.** ``pipecat-flows`` pushes
    ``LLMMessagesAppendFrame`` down the pipeline when it enters a node, and the
    classifier's aggregator appended it to the *classifier's* context. It then
    read the collections agent's instructions --

        "You placed this call. Open by greeting them ... call me back ..."

    -- which are dense with the exact phrases its own rules list as voicemail
    evidence. A human who had not yet spoken was classified VOICEMAIL 1.1s after
    connect, and heard the greeting twice followed by a voicemail message.

    **Nothing at all.** With the script filtered out, the classifier still ran --
    on an empty context, because a VAD blip on answer (the connect tone, a
    breath) closes a user turn with no transcription and the aggregator pushes a
    context frame anyway. Asked to classify silence, the model guesses, and it
    guessed VOICEMAIL again. Removing the wrong evidence exposed that there was
    no evidence.

    So the rule is the obvious one, stated once: **no speech, no
    classification.** The context frame is held until a transcription with
    actual text has passed. Stateful per call, which is why this is an instance
    rather than a module-level predicate -- two concurrent calls must not share
    the "has anyone spoken yet" answer.
    """

    #: Frames that change what the classifier *is* rather than report what it
    #: heard. These never belong in the classifier branch.
    #:
    #: ``LLMUpdateSettingsFrame`` is the one VS-4D8667B522 leaked: the flow
    #: pushed the conversation's system instruction onto the classifier LLM,
    #: which then classified its own greeting script as VOICEMAIL.
    #: Function-call frames are the conversation's tools, not the callee.
    _CONTEXT_MUTATING = (
        "LLMMessagesAppendFrame",
        "LLMMessagesUpdateFrame",
        "LLMSetToolsFrame",
        "LLMUpdateSettingsFrame",
        "FunctionCallsStartedFrame",
        "FunctionCallInProgressFrame",
        "FunctionCallResultFrame",
        "FunctionCallCancelFrame",
    )

    #: The frame that makes the classifier LLM run. Held until there is speech.
    _TRIGGERS_INFERENCE = ("LLMContextFrame", "OpenAILLMContextFrame")

    #: A ringtone or VAD blip often transcribes as punctuation. Two letters
    #: is "Hi"; one character is not a person answering.
    _MIN_SPEECH_LETTERS = 2

    def __init__(self) -> None:
        self.seen_speech = False
        self.closed = False
        self.last_blocked: str | None = None

    @classmethod
    def is_callee_speech(cls, text: str) -> bool:
        letters = sum(1 for ch in str(text or "") if ch.isalpha())
        return letters >= cls._MIN_SPEECH_LETTERS

    @classmethod
    def blocks(cls, frame: Any) -> bool:
        """Context-mutating frames, independent of call state."""
        return type(frame).__name__ in cls._CONTEXT_MUTATING

    def allow(self, frame: Any) -> bool:
        """False for frames that must not reach the classifier branch."""
        name = type(frame).__name__
        if name in self._CONTEXT_MUTATING:
            self.last_blocked = name
            return False
        if name == "TranscriptionFrame" and self.is_callee_speech(
            str(getattr(frame, "text", "") or "")
        ):
            # Real words from the callee. From here the classifier has something
            # to read, and inference is allowed to run.
            self.seen_speech = True
            return True
        if name in self._TRIGGERS_INFERENCE and (not self.seen_speech or self.closed):
            self.last_blocked = name
            return False
        if self.closed and name not in ("TranscriptionFrame",):
            self.last_blocked = name
            return name not in self._TRIGGERS_INFERENCE
        return True


def build_voicemail_detector(*, llm: Any, session: Any = None, **kwargs: Any) -> Any:
    """A :class:`VoicemailDetector` whose classifier cannot read the flow's prompts.

    Rebuilds the parallel branches with a guard in front of the classifier's
    context aggregator. Rebuilding is safe here and nowhere else: the detector
    has only just been constructed, ``setup()`` has not run, no tasks exist, and
    ``ParallelPipeline.__init__`` does nothing but assemble branch objects.
    """
    from pipecat.extensions.voicemail.voicemail_detector import VoicemailDetector
    from pipecat.pipeline.parallel_pipeline import ParallelPipeline
    from pipecat.processors.filters.function_filter import FunctionFilter

    detector = VoicemailDetector(llm=llm, **kwargs)

    # One guard per detector, so its "has anyone spoken yet" state belongs to
    # this call alone.
    guard = _ClassifierContextGuard()
    detector._habibi_guard = guard
    traced_blocks: set[str] = set()

    async def _allow(frame: Any) -> bool:
        allowed = guard.allow(frame)
        blocked = guard.last_blocked
        if not allowed and blocked and blocked not in traced_blocks:
            traced_blocks.add(blocked)
            if session is not None:
                _trace("amd.guard", session, blocked=blocked)
            else:
                try:
                    from voice.call_trace import event

                    event("amd.guard", blocked=blocked)
                except Exception:
                    pass
        return allowed

    # Rebuild the branches once with the guard in the classifier path.
    # VoicemailDetector.__init__ already assembled an unguarded ParallelPipeline
    # (#0). Re-init replaces it — we do not leave that first pipeline linked,
    # which is what produced VoicemailDetector#0 then #1 on VS-4D8667B522 and
    # paid the link cost twice on a silent line.
    ParallelPipeline.__init__(
        detector,
        # Conversation branch: unchanged. The real LLM still needs flow updates.
        [detector._conversation_gate],
        # Classifier branch: the guard sits after the gate, so the gate's own
        # open/closed bookkeeping is untouched and only the aggregator is
        # protected.
        [
            detector._classifier_gate,
            FunctionFilter(_allow),
            detector._context_aggregator.user(),
            detector._classifier_llm,
            detector._classification_processor,
            detector._context_aggregator.assistant(),
        ],
    )
    return detector
