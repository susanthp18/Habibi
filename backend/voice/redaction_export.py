"""Post-call redaction records, redacted WAV, and real export zip bundles."""

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


def _mute_ranges(conn: Any, redaction_id: str) -> list[tuple[float, float]]:
    import db as d

    rows = d._rows(
        conn.execute(
            text(
                """
                SELECT at_sec, duration_sec
                FROM redaction_audio_segments
                WHERE redaction_id = :id AND muted = true
                ORDER BY at_sec
                """
            ),
            {"id": redaction_id},
        )
    )
    return [(float(r["at_sec"] or 0), float(r["duration_sec"] or 0)) for r in rows]


def _silence_ranges(wav_bytes: bytes, ranges: list[tuple[float, float]]) -> bytes:
    if not ranges:
        return wav_bytes
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as src:
        channels = src.getnchannels()
        sampwidth = src.getsampwidth()
        rate = src.getframerate()
        frames = src.readframes(src.getnframes())
    import array

    if sampwidth == 2:
        pcm = array.array("h")
        pcm.frombytes(frames)
        for start, dur in ranges:
            a = max(0, int(start * rate) * channels)
            b = min(len(pcm), int((start + dur) * rate) * channels)
            for i in range(a, b):
                pcm[i] = 0
        out_frames = pcm.tobytes()
    else:
        out_frames = frames
    out = io.BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setnchannels(channels)
        dst.setsampwidth(sampwidth)
        dst.setframerate(rate)
        dst.writeframes(out_frames)
    return out.getvalue()


def write_redacted_wav(interaction_id: str, redaction_id: str) -> dict[str, Any] | None:
    """Build ``kind=redacted_audio`` by zeroing muted ranges on the original WAV."""
    import db as d
    import storage
    from voice import persist
    from voice.recordings import media_for_interaction, _load_bytes

    original = media_for_interaction(interaction_id, variant="original")
    if original is None:
        return None
    with d.engine.connect() as conn:
        ranges = _mute_ranges(conn, redaction_id)
    if not ranges:
        logger.warning(
            "no mute ranges for %s; refusing to write a redacted wav that equals the original",
            redaction_id,
        )
        return None
    wav = _silence_ranges(_load_bytes(str(original["storage_ref"])), ranges)
    digest = hashlib.sha256(wav).hexdigest()
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
    media_id = persist.record_media(
        interaction_id=interaction_id,
        kind="redacted_audio",
        storage_ref=storage_ref,
        duration_sec=original.get("duration_sec"),
        mime_type="audio/wav",
        size_bytes=len(wav),
        content_hash=digest,
    )
    return {"mediaId": media_id, "storageRef": storage_ref, "sizeBytes": len(wav)}


def build_export_zip(job_id: str, record_ids: list[str], scope: list[str]) -> bytes:
    """Zip transcript + original/redacted WAV + CDR/metadata for the job."""
    import db as d
    from voice import persist
    from voice.recordings import media_for_interaction, _load_bytes

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        with d.engine.connect() as conn:
            for rid in record_ids:
                rec = d._one(
                    conn.execute(
                        text(
                            """
                            SELECT r.id, r.interaction_id, i.customer_id, i.started_at,
                                   i.ended_at, i.direction, i.channel, i.handler_bot_id,
                                   i.source_payload
                            FROM redaction_records r
                            JOIN interactions i ON i.id = r.interaction_id
                            WHERE r.id = :id AND i.tenant_id = :tenant
                            """
                        ),
                        {"id": rid, "tenant": d.current_tenant()},
                    )
                )
                if rec is None:
                    continue
                ix = rec["interaction_id"]
                prefix = f"{rid}/"
                if "transcript" in scope:
                    payload = persist.transcript_export_payload(
                        ix, None, persist.list_transcript_turns(ix)
                    )
                    zf.writestr(
                        prefix + "transcript.json",
                        json.dumps(payload, ensure_ascii=False, indent=2),
                    )
                if "audio" in scope or "redacted_audio" in scope:
                    variant = "redacted" if "redacted_audio" in scope else "original"
                    if variant == "redacted":
                        write_redacted_wav(ix, rid)
                    media = media_for_interaction(ix, variant=variant)
                    if media is not None:
                        name = "redacted.wav" if variant == "redacted" else "original.wav"
                        zf.writestr(prefix + name, _load_bytes(str(media["storage_ref"])))
                if "metadata" in scope:
                    attempt = d._one(
                        conn.execute(
                            text(
                                """
                                SELECT id, state, provider, provider_call_id, from_number,
                                       placed_at, answered_at, ended_at, ring_sec, talk_sec
                                FROM call_attempts
                                WHERE interaction_id = :ix
                                ORDER BY placed_at DESC NULLS LAST
                                LIMIT 1
                                """
                            ),
                            {"ix": ix},
                        )
                    )
                    meta = {
                        "interactionId": ix,
                        "redactionId": rid,
                        "customerId": rec["customer_id"],
                        "startedAt": str(rec["started_at"] or ""),
                        "endedAt": str(rec["ended_at"] or ""),
                        "direction": rec["direction"],
                        "channel": rec["channel"],
                        "botId": rec["handler_bot_id"],
                        "sourcePayload": rec["source_payload"],
                        "attempt": dict(attempt) if attempt else None,
                    }
                    zf.writestr(
                        prefix + "metadata.json",
                        json.dumps(meta, ensure_ascii=False, indent=2, default=str),
                    )
        zf.writestr("job.json", json.dumps({"id": job_id, "records": record_ids}))
    return buf.getvalue()
