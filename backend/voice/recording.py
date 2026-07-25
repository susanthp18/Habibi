"""AudioBufferProcessor → MinIO (or local fallback) → interaction_media.

Recording starts ONLY after disclosure proof is written (plan §9.5).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import wave
from pathlib import Path
from typing import Any, Callable

import numpy as np

from voice import persist
from voice.session import VoiceSession

logger = logging.getLogger(__name__)

_LOCAL_DIR = Path(__file__).resolve().parent.parent / ".cache" / "recordings"


def _wav_bytes(pcm: bytes, *, sample_rate: int, num_channels: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(max(1, int(num_channels)))
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm)
    return buf.getvalue()


def _interleave_stereo(user_pcm: bytes, bot_pcm: bytes) -> bytes:
    """Pack mono user + mono bot into interleaved stereo (user L / bot R)."""
    n = max(len(user_pcm), len(bot_pcm))
    n -= n % 2
    u = user_pcm.ljust(n, b"\x00")
    b = bot_pcm.ljust(n, b"\x00")
    ua = np.frombuffer(u, dtype="<i2")
    ba = np.frombuffer(b, dtype="<i2")
    stereo = np.empty(ua.size * 2, dtype="<i2")
    stereo[0::2] = ua
    stereo[1::2] = ba
    return stereo.tobytes()


def upload_recording(
    *,
    interaction_id: str,
    pcm: bytes,
    sample_rate: int,
    num_channels: int,
) -> dict[str, Any] | None:
    if not pcm:
        return None
    wav = _wav_bytes(pcm, sample_rate=sample_rate, num_channels=num_channels)
    duration_sec = int(len(pcm) / (2 * max(1, num_channels) * max(1, sample_rate)))
    digest = hashlib.sha256(wav).hexdigest()
    filename = f"{interaction_id}.wav"
    import db as _db

    key = f"recordings/{_db.TENANT_ID}/{filename}"

    storage_ref: str | None = None
    try:
        import storage

        if storage.is_configured():
            try:
                storage_ref = storage.put_bytes(
                    key,
                    wav,
                    "audio/wav",
                    bucket="recordings",
                )
            except Exception:
                storage_ref = storage.put_bytes(key, wav, "audio/wav")
    except Exception:
        logger.exception("minio upload failed — falling back to local disk")

    if not storage_ref:
        _LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        path = _LOCAL_DIR / filename
        path.write_bytes(wav)
        storage_ref = f"local://recordings/{filename}"
        logger.info("recording saved locally path=%s", path)

    media_id = persist.record_media(
        interaction_id=interaction_id,
        kind="audio",
        storage_ref=storage_ref,
        duration_sec=duration_sec,
        mime_type="audio/wav",
        size_bytes=len(wav),
        content_hash=digest,
    )
    return {
        "mediaId": media_id,
        "storageRef": storage_ref,
        "durationSec": duration_sec,
        "sizeBytes": len(wav),
    }


def attach_recording_handlers(
    audiobuffer: Any,
    session: VoiceSession,
    *,
    on_uploaded: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Wire on_audio_data / on_track_audio_data → persist. Never blocks speech path."""

    @audiobuffer.event_handler("on_track_audio_data")
    async def _on_track(buffer, user_audio, bot_audio, sample_rate, num_channels):  # noqa: ANN001
        ix = session.interaction_id
        if not ix or (not user_audio and not bot_audio):
            return
        # One audio row per call: the buffer emits the full track once at stop, so
        # guard against a duplicate row if the callback ever fires again (restart /
        # non-zero buffer_size). The fixed {interaction_id}.wav key is overwritten
        # in place; only the DB insert would otherwise duplicate.
        if session.extra.get("audio_media_id"):
            return
        try:
            stereo = _interleave_stereo(user_audio or b"", bot_audio or b"")
            result = await asyncio.to_thread(
                upload_recording,
                interaction_id=ix,
                pcm=stereo,
                sample_rate=int(sample_rate or 16000),
                num_channels=2,
            )
            if result:
                session.extra["audio_media_id"] = result.get("mediaId")
                if on_uploaded:
                    on_uploaded(result)
            logger.info(
                "track audio uploaded · interaction=%s · ref=%s",
                ix,
                (result or {}).get("storageRef"),
            )
        except Exception:
            logger.exception("track audio upload failed")

    @audiobuffer.event_handler("on_audio_data")
    async def _on_audio(buffer, audio, sample_rate, num_channels):  # noqa: ANN001
        # Prefer track handler (cleaner L/R). Composite is a fallback when tracks empty.
        ix = session.interaction_id
        if not ix or not audio:
            return
        if session.extra.get("audio_media_id"):
            return
        try:
            result = await asyncio.to_thread(
                upload_recording,
                interaction_id=ix,
                pcm=audio,
                sample_rate=int(sample_rate or 16000),
                num_channels=int(num_channels or 1),
            )
            if result:
                session.extra["audio_media_id"] = result.get("mediaId")
                if on_uploaded:
                    on_uploaded(result)
            logger.info(
                "composite audio uploaded · interaction=%s · ref=%s",
                ix,
                (result or {}).get("storageRef"),
            )
        except Exception:
            logger.exception("composite audio upload failed")
