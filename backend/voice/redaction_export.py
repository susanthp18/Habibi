"""Post-call redaction records and the redacted recording (beeps over each finding).

Export bundles are built by the ml_worker: ``call_intel/exports.py``.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import wave
import zipfile
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _findings_in_text(text_value: str) -> list[dict[str, Any]]:
    from pii_redact import PII_DETECTORS

    out: list[dict[str, Any]] = []
    if not text_value:
        return out
    for kind, pattern, mask in PII_DETECTORS:
        for match in pattern.finditer(text_value):
            raw = match.group(0)
            out.append(
                {
                    "type": kind,
                    "start": match.start(),
                    "end": match.end(),
                    "masked": mask(raw),
                    "confidence": 0.9,
                }
            )
    return out


def ensure_redaction_record(interaction_id: str) -> str | None:
    """Upsert ``redaction_records`` + ``pii_findings`` from the transcript."""
    import db as d

    with d.engine.begin() as conn:
        row = d._one(
            conn.execute(
                text(
                    """
                    SELECT i.id, i.customer_id
                    FROM interactions i
                    WHERE i.id = :id AND i.tenant_id = :tenant
                    """
                ),
                {"id": interaction_id, "tenant": d.current_tenant()},
            )
        )
        if row is None:
            return None
        existing = conn.execute(
            text("SELECT id FROM redaction_records WHERE interaction_id = :id"),
            {"id": interaction_id},
        ).scalar()
        rid = str(existing) if existing else d._id("RR")
        if not existing:
            conn.execute(
                text(
                    """
                    INSERT INTO redaction_records (
                      id, interaction_id, customer_id, reviewed, created_at, updated_at
                    ) VALUES (
                      :id, :ix, :cid, false, now(), now()
                    )
                    """
                ),
                {"id": rid, "ix": interaction_id, "cid": row["customer_id"]},
            )
        already = conn.execute(
            text("SELECT count(*) FROM pii_findings WHERE redaction_id = :id"),
            {"id": rid},
        ).scalar()
        if int(already or 0) > 0:
            return rid
        # Turn ids: list_transcript_turns does not return the PK. Load them.
        turn_rows = d._rows(
            conn.execute(
                text(
                    """
                    SELECT id, turn_index, text
                    FROM interaction_transcript
                    WHERE interaction_id = :id
                    ORDER BY turn_index
                    """
                ),
                {"id": interaction_id},
            )
        )
        for turn in turn_rows:
            for finding in _findings_in_text(str(turn.get("text") or "")):
                fid = d._id("PF")
                conn.execute(
                    text(
                        """
                        INSERT INTO pii_findings (
                          id, redaction_id, type, masked, confidence, accepted,
                          transcript_turn_id, start_offset, end_offset, created_at
                        ) VALUES (
                          :id, :rid, :type, :masked, :conf, false,
                          :tid, :start, :end, now()
                        )
                        """
                    ),
                    {
                        "id": fid,
                        "rid": rid,
                        "type": finding["type"],
                        "masked": finding["masked"],
                        "conf": finding["confidence"],
                        "tid": turn["id"],
                        "start": finding["start"],
                        "end": finding["end"],
                    },
                )
    return rid


#: A beep, not silence: a listener must hear that something was removed.
BEEP_HZ = 1000
BEEP_LEVEL = 0.25  # -12 dBFS


def _mute_ranges(conn: Any, redaction_id: str) -> list[tuple[int, int, str | None]]:
    """(start_ms, end_ms, channel) of every muted segment; channel None = all."""
    import db as d

    rows = d._rows(
        conn.execute(
            text(
                """
                SELECT at_sec, duration_sec, start_ms, end_ms, channel
                FROM redaction_audio_segments
                WHERE redaction_id = :id AND muted = true
                ORDER BY COALESCE(start_ms, at_sec * 1000)
                """
            ),
            {"id": redaction_id},
        )
    )
    out = []
    for r in rows:
        start = r["start_ms"] if r["start_ms"] is not None else int(r["at_sec"] or 0) * 1000
        end = r["end_ms"] if r["end_ms"] is not None else start + int(r["duration_sec"] or 0) * 1000
        out.append((int(start), int(end), r["channel"]))
    return out


def beep_ranges(wav_bytes: bytes, ranges: list[tuple[int, int, str | None]]) -> bytes:
    """``wav_bytes`` with a tone over each range, on that speaker's channel.

    Stereo recordings are customer left, agent right; a mono recording, or a
    range with no channel, is beeped on every channel.
    """
    import numpy as np

    with wave.open(io.BytesIO(wav_bytes), "rb") as src:
        channels, sampwidth, rate = src.getnchannels(), src.getsampwidth(), src.getframerate()
        frames = src.readframes(src.getnframes())
    if sampwidth != 2:
        raise ValueError(f"cannot redact {8 * sampwidth}-bit audio")
    pcm = np.frombuffer(frames, dtype="<i2").reshape(-1, channels).copy()
    column = {"customer": 0, "agent": 1}
    for start_ms, end_ms, channel in ranges:
        a = max(0, int(start_ms * rate / 1000))
        b = min(len(pcm), int(end_ms * rate / 1000))
        if b <= a:
            continue
        t = np.arange(b - a) / rate
        tone = (BEEP_LEVEL * 32767 * np.sin(2 * np.pi * BEEP_HZ * t)).astype("<i2")
        cols = [column[channel]] if channels == 2 and channel in column else range(channels)
        for c in cols:
            pcm[a:b, c] = tone
    out = io.BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setnchannels(channels)
        dst.setsampwidth(2)
        dst.setframerate(rate)
        dst.writeframes(pcm.tobytes())
    return out.getvalue()


def write_redacted_wav(interaction_id: str, redaction_id: str) -> dict[str, Any] | None:
    """Build ``kind=redacted_audio``: the original with every muted segment beeped.

    Replaces any earlier redacted copy, so toggling a segment re-renders it. A
    call with nothing to beep still gets one, identical to the original: the
    redacted variant then always exists once the call has been processed, and
    playback without raw-PII permission never has to fall back to the original.
    """
    import db as d
    import storage
    from voice import persist
    from voice.recordings import media_for_interaction, _load_bytes

    original = media_for_interaction(interaction_id, variant="original")
    if original is None:
        return None
    with d.engine.connect() as conn:
        ranges = _mute_ranges(conn, redaction_id)
    source = _load_bytes(str(original["storage_ref"]))
    wav = beep_ranges(source, ranges) if ranges else source
    digest = hashlib.sha256(wav).hexdigest()
    if ranges:
        filename = f"{interaction_id}-redacted.wav"
        key = f"recordings/{d.current_tenant()}/{filename}"
        storage_ref: str | None = None
        try:
            if storage.is_configured():
                storage_ref = storage.put_bytes(
                    key, wav, "audio/wav", bucket=storage.RECORDINGS_BUCKET
                )
        except Exception:
            logger.exception("redacted wav minio upload failed")
        if not storage_ref:
            from pathlib import Path

            local_dir = Path(__file__).resolve().parent.parent / ".cache" / "recordings"
            local_dir.mkdir(parents=True, exist_ok=True)
            (local_dir / filename).write_bytes(wav)
            storage_ref = f"local://recordings/{filename}"
    else:
        storage_ref = str(original["storage_ref"])
    with d.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM interaction_media WHERE interaction_id = :ix AND kind = 'redacted_audio'"),
            {"ix": interaction_id},
        )
    media_id = persist.record_media(
        interaction_id=interaction_id,
        kind="redacted_audio",
        storage_ref=storage_ref,
        duration_sec=original.get("duration_sec"),
        mime_type="audio/wav",
        size_bytes=len(wav),
        content_hash=digest,
    )
    return {"mediaId": media_id, "storageRef": storage_ref, "sizeBytes": len(wav), "beeps": len(ranges)}
