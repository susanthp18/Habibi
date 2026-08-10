"""Outbound AMD — Pipecat VoicemailDetector wiring + CRM disposition.

Only enabled for Twilio outbound legs (``call_type=outbound``). Sandbox Live and
inbound dial-in skip this path — the browser/human is never a voicemail box.
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
VOICEMAIL_SCRIPT = (
    f"Hello, this is {_DEFAULT_AGENT_NAME} calling from {_DEFAULT_ISSUER} collections "
    "regarding your account. Please call us back at your earliest convenience. Thank you."
)


def voicemail_script(
    persona: dict[str, Any] | None = None,
    tuning: dict[str, Any] | None = None,
) -> str:
    """Render the voicemail message for this deployment.

    Agent name and issuer come from the deployment's persona/tuning bundle so a
    second tenant does not leave messages claiming to be HDFC's Priya.
    """
    p = persona or {}
    t = tuning or {}
    persona_block = t.get("persona") if isinstance(t.get("persona"), dict) else {}
    agent = str(
        p.get("agentName") or p.get("name") or persona_block.get("agentName") or ""
    ).strip() or _DEFAULT_AGENT_NAME
    issuer = str(
        p.get("issuer") or p.get("brand") or persona_block.get("issuer") or ""
    ).strip() or _DEFAULT_ISSUER
    return (
        f"Hello, this is {agent} calling from {issuer} collections regarding your "
        "account. Please call us back at your earliest convenience. Thank you."
    )


def should_enable_amd(session_extra: dict[str, Any] | None, *, is_twilio: bool) -> bool:
    if not is_twilio:
        return False
    extra = session_extra or {}
    params = extra.get("twilio_params") if isinstance(extra.get("twilio_params"), dict) else {}
    call_type = str(params.get("call_type") or extra.get("call_type") or "").lower()
    return call_type == "outbound"


async def attach_voicemail_handlers(
    *,
    voicemail_detector: Any,
    session: Any,
    sink: Any,
    worker: Any,
    on_left_message: Callable[[], Awaitable[None]] | None = None,
    persona: dict[str, Any] | None = None,
    tuning: dict[str, Any] | None = None,
) -> None:
    """Register conversation / voicemail event handlers on the detector."""
    from pipecat.frames.frames import EndWorkerFrame, TTSSpeakFrame
    from pipecat.processors.frame_processor import FrameDirection

    @voicemail_detector.event_handler("on_conversation_detected")
    async def _on_human(_detector) -> None:
        logger.info("AMD: live conversation · session=%s", session.session_id)
        session.extra["amd"] = "human"
        if hasattr(sink, "enqueue_alert"):
            try:
                await sink.enqueue_alert("compliance", "amd_human")
            except Exception:
                # Alerting is best-effort on the audio path, but a persistent
                # failure must be visible rather than swallowed silently.
                logger.warning("amd_human alert failed", exc_info=True)

    @voicemail_detector.event_handler("on_voicemail_detected")
    async def _on_voicemail(processor) -> None:
        logger.info("AMD: voicemail · session=%s — leaving message", session.session_id)
        session.extra["amd"] = "voicemail"
        session.extra["disposition"] = "voicemail"
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

        script = voicemail_script(persona, tuning)
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
