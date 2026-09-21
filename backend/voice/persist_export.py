"""Transcript export and the PTP capture stamp.

Peeled out of persist.py so that module stays under the 1,500-line ceiling.
Callers keep importing these names from ``voice.persist``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text

import db

logger = logging.getLogger(__name__)


def list_transcript_turns(interaction_id: str) -> list[dict[str, Any]]:
    """Ordered turns for export / post-call review."""
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT turn_index, speaker, at_sec, text,
                       sentiment_delta, intent, intent_score,
                       ttfb_ms, ttfa_ms, tokens
                FROM interaction_transcript
                WHERE interaction_id = :id
                ORDER BY turn_index ASC
                """
            ),
            {"id": interaction_id},
        ).mappings().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "turnIndex": int(r["turn_index"]),
                "speaker": r["speaker"],
                "atSec": int(r["at_sec"] or 0),
                "text": r["text"],
                "sentimentDelta": float(r["sentiment_delta"]) if r["sentiment_delta"] is not None else None,
                "intent": r["intent"],
                "intentScore": float(r["intent_score"]) if r["intent_score"] is not None else None,
                "ttfbMs": int(r["ttfb_ms"]) if r["ttfb_ms"] is not None else None,
                "ttfaMs": int(r["ttfa_ms"]) if r["ttfa_ms"] is not None else None,
                "tokens": int(r["tokens"]) if r["tokens"] is not None else None,
            }
        )
    return out


def transcript_export_payload(
    interaction_id: str, session_id: str | None, turns: list[dict[str, Any]]
) -> dict[str, Any]:
    """What the export file holds. Rows are masked at write with
    ``transcript_view.redact_line``; this re-applies the same rule so a row
    written before that was the rule leaves the system the same way."""
    from transcript_view import scrub_identifiers

    return {
        "interactionId": interaction_id,
        "sessionId": session_id,
        "turnCount": len(turns),
        "turns": [{**t, "text": scrub_identifiers(str(t.get("text") or ""))} for t in turns],
    }


def export_transcript_json(
    *,
    interaction_id: str,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """Serialize turns → MinIO (or local) → interaction_media kind=transcript_export.

    Safe to call from CrmSink worker threads. Returns media row summary or None.
    """
    from voice.persist import record_media

    turns = list_transcript_turns(interaction_id)
    if not turns:
        return None

    payload = transcript_export_payload(interaction_id, session_id, turns)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    filename = f"{interaction_id}.transcript.json"
    key = f"transcripts/{db.current_tenant()}/{filename}"

    storage_ref: str | None = None
    try:
        import storage

        if storage.is_configured():
            storage_ref = storage.put_bytes(
                key,
                raw,
                "application/json",
                bucket=storage.RECORDINGS_BUCKET,
            )
    except Exception:
        logger.exception("transcript export minio upload failed — falling back to local")

    if not storage_ref:
        local_dir = Path(__file__).resolve().parent.parent / ".cache" / "transcripts"
        local_dir.mkdir(parents=True, exist_ok=True)
        path = local_dir / filename
        path.write_bytes(raw)
        storage_ref = f"local://transcripts/{filename}"
        logger.info("transcript export saved locally path=%s", path)

    media_id = record_media(
        interaction_id=interaction_id,
        kind="transcript_export",
        storage_ref=storage_ref,
        duration_sec=None,
        mime_type="application/json",
        size_bytes=len(raw),
        content_hash=digest,
    )
    return {
        "mediaId": media_id,
        "storageRef": storage_ref,
        "sizeBytes": len(raw),
        "turnCount": len(turns),
    }


def mark_ptp_captured(interaction_id: str) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE interactions
                SET ptp_captured = true, updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": interaction_id},
        )
