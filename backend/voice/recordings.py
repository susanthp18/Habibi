"""Read path for call recordings (stereo operator WAV, Asterisk bridge recording copy)."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

def _load_bytes(storage_ref: str) -> bytes:
    if storage_ref.startswith("local://"):
        rel = storage_ref[len("local://") :]
        path = Path(__file__).resolve().parent.parent / ".cache" / rel
        return path.read_bytes()
    import storage

    return storage.get_bytes(storage_ref)


def media_for_interaction(
    interaction_id: str, *, variant: str = "original"
) -> dict[str, Any] | None:
    """Pick the WAV to stream. Stereo ``audio`` wins; ``sip_audio`` is fallback."""
    import db as d

    wanted = "redacted_audio" if variant == "redacted" else None
    with d.engine.connect() as conn:
        rows = d._rows(
            conn.execute(
                text(
                    """
                    SELECT m.id, m.kind, m.storage_ref, m.duration_sec, m.mime_type, m.size_bytes
                    FROM interaction_media m
                    JOIN interactions i ON i.id = m.interaction_id
                    WHERE m.interaction_id = :id AND i.tenant_id = :tenant
                    ORDER BY m.created_at DESC
                    """
                ),
                {"id": interaction_id, "tenant": d.current_tenant()},
            )
        )
    if not rows:
        return None
    if wanted:
        for row in rows:
            if row["kind"] == wanted:
                return row
        return None
    by_kind: dict[str, Any] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], r)
    for kind in ("audio", "sip_audio"):
        if kind in by_kind:
            return by_kind[kind]
    return None


def stream_recording(interaction_id: str, *, variant: str = "original") -> dict[str, Any]:
    row = media_for_interaction(interaction_id, variant=variant)
    if row is None:
        raise KeyError("recording_not_found")
    data = _load_bytes(str(row["storage_ref"]))
    return {
        "bytes": data,
        "mimeType": row.get("mime_type") or "audio/wav",
        "mediaId": row["id"],
        "kind": row["kind"],
        "durationSec": row.get("duration_sec"),
    }


@lru_cache(maxsize=256)
def recording_peaks(media_id: str, storage_ref: str, bins: int) -> dict[str, Any]:
    """Peak amplitude (0..1) per bucket for each channel. Cached per media row:
    a filed recording never changes, a re-filed one gets a new id."""
    import io
    import wave

    import numpy as np

    with wave.open(io.BytesIO(_load_bytes(storage_ref))) as wf:
        channels, rate = wf.getnchannels(), wf.getframerate()
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").reshape(-1, channels)
    names = ["customer", "agent"] if channels == 2 else ["mixed"]
    out: dict[str, list[float]] = {}
    for c, name in enumerate(names):
        chunks = np.array_split(np.abs(pcm[:, c].astype(np.int32)), bins)
        out[name] = [round(float(ch.max()) / 32768, 3) if ch.size else 0.0 for ch in chunks]
    return {"durationSec": round(len(pcm) / rate, 3), "channels": out}


def log_recording_download(
    interaction_id: str, *, variant: str, media_id: str | None
) -> None:
    import db as d

    try:
        with d.engine.begin() as conn:
            d._activity(
                conn,
                "interaction",
                interaction_id,
                "recording_downloaded",
                "Recording downloaded",
                note=f"variant={variant} media={media_id or ''}",
            )
    except Exception:
        logger.exception("recording download audit failed interaction=%s", interaction_id)
        raise
