"""Outbound AMD — Pipecat VoicemailDetector wiring + CRM disposition.

Only enabled for Twilio outbound legs (``call_type=outbound``). Sandbox Live and
inbound dial-in skip this path — the browser/human is never a voicemail box.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

VOICMAIL_SCRIPT = (
    "Hello, this is Priya calling from HDFC Bank collections regarding your account. "
    "Please call us back at your earliest convenience. Thank you."
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
) -> None:
    """Register conversation / voicemail event handlers on the detector."""
    from pipecat.frames.frames import EndWorkerFrame, TTSSpeakFrame
    from pipecat.processors.frame_processor import FrameDirection

    @voicemail_detector.event_handler("on_conversation_detected")
    async def _on_human(_detector) -> None:
        logger.info("AMD: live conversation · session=%s", session.session_id)
        session.extra["amd"] = "human"
        try:
            await sink.enqueue_alert("compliance", "amd_human") if hasattr(sink, "enqueue_alert") else None
        except Exception:
            pass

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
                persist.record_media(
                    interaction_id=ix,
                    kind="voicemail",
                    storage_ref=f"voicemail://{session.session_id}",
                    duration_sec=None,
                    mime_type="audio/wav",
                    size_bytes=0,
                )
        except Exception:
            logger.exception("voicemail media row failed")

        try:
            await processor.push_frame(TTSSpeakFrame(VOICMAIL_SCRIPT, append_to_context=False))
        except TypeError:
            await processor.push_frame(TTSSpeakFrame(VOICMAIL_SCRIPT))
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
