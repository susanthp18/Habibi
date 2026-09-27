"""Evidence exports, built by the ml_worker from the redacted record.

Three formats, one source of truth:

* **pdf** -- a watermarked transcript bundle for a regulator: a cover page,
  then per call its metadata and the masked transcript. Every page carries the
  watermark diagonally and in the footer with the job id. Text is shaped
  (HarfBuzz) with Noto fallbacks, so Hindi, Tamil and Arabic render correctly.
* **csv** -- one metadata row per call, the watermark as a column.
* **audio-zip** -- the *redacted* recordings (every finding beeped), the masked
  transcripts when asked, and a manifest with each file's sha256.

Nothing here reads raw PII: transcripts are the masked store, audio is the
redacted copy. A call whose redacted recording is not ready fails the job
with that reason rather than shipping the original.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from env_utils import env_str

logger = logging.getLogger(__name__)

STALE_MINUTES = 30


class NotReady(RuntimeError):
    """A record in the export is not fully redacted yet."""


def claim() -> dict[str, Any] | None:
    import db

    with db.engine.begin() as conn:
        row = conn.execute(
            text(
                f"""
                UPDATE export_jobs j SET status = 'running', locked_at = now(), updated_at = now()
                WHERE j.id = (
                  SELECT id FROM export_jobs
                  WHERE COALESCE(scope->>'kind', 'redaction') = 'redaction' AND (status = 'queued'
                     OR (status = 'running' AND locked_at < now() - interval '{STALE_MINUTES} minutes'))
                  ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
                )
                RETURNING j.id, j.format, j.scope, j.watermark, j.created_at, j.actor_user_id
                """
            )
        ).mappings().first()
    return dict(row) if row else None


def _records(conn: Any, job_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        text(
            """
            SELECT r.id AS redaction_id, r.interaction_id, r.reviewed, r.reviewed_at,
                   ru.name AS reviewer, i.customer_id, i.channel, i.direction, i.started_at,
                   i.ended_at, i.duration_sec, i.disposition, i.hash AS log_hash,
                   i.source_payload->'voiceStudio' AS studio, b.name AS agent,
                   (SELECT jsonb_object_agg(type, n) FROM (SELECT type, count(*) n FROM pii_findings
                      WHERE redaction_id = r.id AND accepted GROUP BY type) t) AS masked_by_type
            FROM export_job_records e
            JOIN redaction_records r ON r.id = e.redaction_id
            JOIN interactions i ON i.id = r.interaction_id
            LEFT JOIN bots b ON b.id = i.handler_bot_id
            LEFT JOIN users ru ON ru.id = r.reviewed_by_user_id
            WHERE e.export_job_id = :id
            ORDER BY i.started_at
            """
        ),
        {"id": job_id},
    ).mappings()]


def _turns(conn: Any, interaction_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        text("SELECT turn_index, speaker, at_sec, text FROM interaction_transcript "
             "WHERE interaction_id = :ix ORDER BY turn_index"),
        {"ix": interaction_id},
    ).mappings()]


def _metadata(rec: dict[str, Any]) -> dict[str, Any]:
    studio = rec.get("studio") or {}
    return {
        "interactionId": rec["interaction_id"],
        "redactionId": rec["redaction_id"],
        "customerId": rec["customer_id"],
        "channel": rec["channel"],
        "direction": rec["direction"],
        "startedAt": rec["started_at"].isoformat() if rec["started_at"] else "",
        "endedAt": rec["ended_at"].isoformat() if rec["ended_at"] else "",
        "durationSec": rec["duration_sec"],
        "agent": rec["agent"] or "",
        "agentVersion": studio.get("versionNumber"),
        "disposition": rec["disposition"] or "",
        "reviewed": bool(rec["reviewed"]),
        "reviewedBy": rec["reviewer"] or "",
        "reviewedAt": rec["reviewed_at"].isoformat() if rec["reviewed_at"] else "",
        "maskedByType": rec["masked_by_type"] or {},
        "logHash": rec["log_hash"] or "",
    }


def _redacted_audio(interaction_id: str) -> tuple[bytes, str]:
    from voice.recordings import _load_bytes, media_for_interaction

    media = media_for_interaction(interaction_id, variant="redacted")
    if media is None:
        raise NotReady(f"{interaction_id}: the redacted recording is not ready yet")
    data = _load_bytes(str(media["storage_ref"]))
    return data, hashlib.sha256(data).hexdigest()


def build_csv(job: dict[str, Any], records: list[dict[str, Any]]) -> bytes:
    rows = [_metadata(r) for r in records]
    buf = io.StringIO()
    fields = [*rows[0].keys(), "watermark", "exportJob"] if rows else ["watermark", "exportJob"]
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({**row, "maskedByType": json.dumps(row["maskedByType"]),
                         "watermark": job["watermark"], "exportJob": job["id"]})
    return buf.getvalue().encode("utf-8-sig")  # BOM: Excel opens Devanagari correctly


def build_zip(job: dict[str, Any], records: list[dict[str, Any]], parts: list[str], conn: Any) -> bytes:
    buf = io.BytesIO()
    manifest: dict[str, Any] = {"job": job["id"], "watermark": job["watermark"],
                                "createdAt": _now(), "files": []}
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rec in records:
            base = rec["interaction_id"]
            if "audio" in parts:
                audio, digest = _redacted_audio(rec["interaction_id"])
                zf.writestr(f"{base}/recording-redacted.wav", audio)
                manifest["files"].append({"path": f"{base}/recording-redacted.wav", "sha256": digest})
            if "transcript" in parts:
                lines = [f"[{_clock(t['at_sec'])}] {t['speaker']}: {t['text']}" for t in _turns(conn, base)]
                body = ("\n".join([f"# {job['watermark']} -- export {job['id']}", *lines]) + "\n").encode()
                zf.writestr(f"{base}/transcript-masked.txt", body)
                manifest["files"].append({"path": f"{base}/transcript-masked.txt",
                                          "sha256": hashlib.sha256(body).hexdigest()})
            if "metadata" in parts:
                body = json.dumps(_metadata(rec), indent=2, ensure_ascii=False).encode()
                zf.writestr(f"{base}/metadata.json", body)
                manifest["files"].append({"path": f"{base}/metadata.json",
                                          "sha256": hashlib.sha256(body).hexdigest()})
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    return buf.getvalue()


def _font_dir() -> Path:
    return Path(env_str("ML_FONT_DIR", "/opt/fonts"))


def build_pdf(job: dict[str, Any], records: list[dict[str, Any]], parts: list[str], conn: Any) -> bytes:
    from fpdf import FPDF

    watermark = job["watermark"] or "CONFIDENTIAL"

    class Evidence(FPDF):
        def header(self) -> None:
            with self.local_context(fill_opacity=0.08, text_color=(120, 120, 120)):
                self.set_font("Noto", size=46)
                with self.rotation(35, x=self.w / 2, y=self.h / 2):
                    self.text(x=self.w / 2 - self.get_string_width(watermark) / 2, y=self.h / 2, text=watermark)

        def footer(self) -> None:
            self.set_y(-12)
            self.set_font("Noto", size=7)
            self.set_text_color(110, 110, 110)
            self.cell(0, 5, f"{watermark}  ·  export {job['id']}  ·  page {self.page_no()}/{{nb}}", align="C")

    pdf = Evidence(format="A4")
    fonts = _font_dir()
    pdf.add_font("Noto", fname=str(fonts / "NotoSans-Regular.ttf"))
    pdf.add_font("NotoDeva", fname=str(fonts / "NotoSansDevanagari-Regular.ttf"))
    pdf.add_font("NotoTamil", fname=str(fonts / "NotoSansTamil-Regular.ttf"))
    pdf.add_font("NotoArabic", fname=str(fonts / "NotoSansArabic-Regular.ttf"))
    pdf.set_fallback_fonts(["NotoDeva", "NotoTamil", "NotoArabic"])
    pdf.set_text_shaping(True)
    pdf.set_auto_page_break(True, margin=16)

    pdf.add_page()
    pdf.set_font("Noto", size=16)
    pdf.cell(0, 10, "Call evidence export", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Noto", size=10)
    for label, value in (("Export", job["id"]), ("Created", _now()), ("Calls", str(len(records))),
                         ("Watermark", watermark),
                         ("Masking", "Personal data is masked: transcripts show [TYPE] in place of each "
                                     "finding; card numbers keep their last four digits.")):
        pdf.multi_cell(0, 6, f"{label}: {value}", align="L", new_x="LMARGIN", new_y="NEXT")

    for rec in records:
        pdf.add_page()
        meta = _metadata(rec)
        pdf.set_font("Noto", size=13)
        pdf.cell(0, 8, f"Call {meta['interactionId']}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Noto", size=9)
        if "metadata" in parts:
            masked = ", ".join(f"{k} {v}" for k, v in sorted(meta["maskedByType"].items())) or "none"
            for label, value in (
                ("Started", meta["startedAt"]), ("Duration", f"{meta['durationSec'] or 0}s"),
                ("Agent", f"{meta['agent']} v{meta['agentVersion']}" if meta["agentVersion"] else meta["agent"]),
                ("Channel", f"{meta['channel']} / {meta['direction']}"), ("Disposition", meta["disposition"]),
                ("Customer id", meta["customerId"]), ("Masked", masked),
                ("Review", f"reviewed by {meta['reviewedBy']} at {meta['reviewedAt']}" if meta["reviewed"]
                 else "not yet reviewed"),
            ):
                pdf.multi_cell(0, 5, f"{label}: {value}", align="L", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
        if "transcript" in parts:
            for t in _turns(conn, rec["interaction_id"]):
                pdf.set_font("Noto", size=8)
                pdf.set_text_color(110, 110, 110)
                pdf.cell(0, 5, f"{_clock(t['at_sec'])}  {t['speaker']}", new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.set_font("Noto", size=10)
                pdf.multi_cell(0, 5, t["text"] or "", align="L", new_x="LMARGIN", new_y="NEXT")
                pdf.ln(1)
    return bytes(pdf.output())


def _clock(sec: Any) -> str:
    s = int(sec or 0)
    return f"{s // 60}:{s % 60:02d}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(job: dict[str, Any]) -> None:
    """Build one export and file it (ready), or record why it could not be built (failed)."""
    import db
    import storage

    scope = job["scope"] if isinstance(job["scope"], dict) else json.loads(job["scope"] or "{}")
    parts = [p for p in scope.get("parts") or [] if p in ("transcript", "audio", "metadata")] or ["transcript"]
    fmt = job["format"]
    records: list[dict[str, Any]] = []
    try:
        with db.engine.connect() as conn:
            records = _records(conn, job["id"])
            if fmt == "csv":
                blob, ext, mime = build_csv(job, records), "csv", "text/csv"
            elif fmt == "pdf":
                blob, ext, mime = build_pdf(job, records, parts, conn), "pdf", "application/pdf"
            else:
                blob, ext, mime = build_zip(job, records, [*parts, "audio"], conn), "zip", "application/zip"
        ref = storage.put_bytes(f"export-bundles/{db.current_tenant()}/{job['id']}.{ext}", blob, mime,
                                bucket=storage.RECORDINGS_BUCKET)
        scope["sha256"] = hashlib.sha256(blob).hexdigest()
        scope["sizeBytes"] = len(blob)
        status, error = "ready", None
    except NotReady as exc:
        ref, status, error = None, "failed", str(exc)
    except Exception as exc:
        logger.exception("export %s failed", job["id"])
        ref, status, error = None, "failed", f"{type(exc).__name__}: {exc}"[:500]
    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE export_jobs SET status = :s, storage_ref = :ref, error = :err, locked_at = NULL, "
                 "scope = CAST(:scope AS jsonb), updated_at = now() WHERE id = :id"),
            {"s": status, "ref": ref, "err": error, "scope": json.dumps(scope), "id": job["id"]},
        )
    logger.info("export %s (%s, %s records): %s%s", job["id"], fmt, len(records) if status == "ready" else "?",
                status, f" -- {error}" if error else "")
