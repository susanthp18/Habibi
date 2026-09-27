"""The pass's stages. Each reads what it needs, writes its rows, and is safe to re-run."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from call_intel import audio, models, pii
from call_intel.inputs import Call

logger = logging.getLogger(__name__)

#: What the PII model looks for, and the finding type each label files as.
MODEL_LABELS = {
    "person name": "name",
    "street address": "address",
    "date of birth": "dob",
    "email address": "email",
    "phone number": "phone",
    "bank account number": "account",
    "credit card number": "card",
    "passport number": "passport",
}
#: Below this the model's span is not a finding. Tuned with call_intel.eval.
MODEL_THRESHOLD = 0.5


def _model_spans(call: Call, extra_labels: list[str]) -> tuple[dict[int, list[tuple[int, int, str, float]]], str | None]:
    labels = [*MODEL_LABELS, *extra_labels]
    try:
        per_turn = models.pii_spans([t.text for t in call.turns], labels, threshold=MODEL_THRESHOLD)
    except Exception:
        # Identifiers are still caught by patterns, context and the CRM; prose
        # names and addresses are not. Logged loudly: recall has dropped.
        logger.exception("call_intel: PII model unavailable for %s; patterns only", call.interaction_id)
        return {}, None
    out: dict[int, list[tuple[int, int, str, float]]] = {}
    for turn, entities in zip(call.turns, per_turn):
        out[turn.index] = [(e["start"], e["end"], MODEL_LABELS.get(e["label"], "custom"), e["score"])
                           for e in entities]
    return out, models.version(models.PII)


def run_pii(call: Call, rules: dict[str, Any]) -> dict[str, str]:
    """File the redaction record and its findings; re-mask the stored transcript."""
    import db

    spans, version = _model_spans(call, rules["labels"])
    findings = pii.detect(
        call.turns, crm=call.crm, disabled=rules["disabled"], custom=rules["custom"],
        model_spans=spans, model_version=version, allow_names=call.allow_names,
    )
    with db.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO redaction_records (id, interaction_id, customer_id) VALUES (:id, :ix, :c) "
                 "ON CONFLICT (interaction_id) DO NOTHING"),
            {"id": db._id("RR"), "ix": call.interaction_id, "c": call.customer_id},
        )
        rid = conn.execute(
            text("SELECT id FROM redaction_records WHERE interaction_id = :ix"), {"ix": call.interaction_id}
        ).scalar()
        # A reviewer's "not PII" survives a re-run over the same span.
        kept = {
            (r.transcript_turn_id, r.start_offset, r.end_offset): r.accepted
            for r in conn.execute(
                text("SELECT transcript_turn_id, start_offset, end_offset, accepted FROM pii_findings "
                     "WHERE redaction_id = :r AND detector IS NOT NULL"), {"r": rid})
        }
        conn.execute(text("DELETE FROM pii_findings WHERE redaction_id = :r"), {"r": rid})
        texts = {t.index: t.text for t in call.turns}
        for f in findings:
            turn_id = call.turn_ids.get(f.turn_index)
            accepted = kept.get((turn_id, f.start, f.end), True)
            conn.execute(
                text(
                    """
                    INSERT INTO pii_findings (id, redaction_id, type, masked, confidence, accepted,
                      transcript_turn_id, start_offset, end_offset, detector, model_version, needs_review)
                    VALUES (:id, :r, :type, :masked, :conf, :acc, :tid, :s, :e, :det, :mv, :nr)
                    """
                ),
                {"id": db._id("PF"), "r": rid, "type": f.type,
                 "masked": pii.mask_for(f.type, texts[f.turn_index][f.start:f.end]),
                 "conf": round(f.confidence, 3), "acc": accepted, "tid": turn_id, "s": f.start, "e": f.end,
                 "det": f.detector, "mv": f.model_version, "nr": f.needs_review},
            )
    remask_transcript(call)
    logger.info("call_intel %s: %s PII findings (%s for review)", call.interaction_id, len(findings),
                sum(f.needs_review for f in findings))
    return {"pii": version or "patterns-only"}


def remask_transcript(call: Call) -> None:
    """Store each turn masked by its accepted findings (and the at-rest regex).

    Only when the words came unmasked from the engine: the stored text then
    becomes the best-masked version of what was said. A reviewer's decision
    re-runs this at once; it needs no model.
    """
    import db
    import pii_redact

    if not call.raw:
        return
    with db.engine.begin() as conn:
        _, found = _accepted_findings(conn, call)
        by_turn: dict[int, list[pii.Finding]] = {}
        for _, f in found:
            by_turn.setdefault(f.turn_index, []).append(f)
        for turn in call.turns:
            masked = pii_redact.redact_text(pii.masked_text(turn.text, by_turn.get(turn.index, [])))
            conn.execute(
                text("UPDATE interaction_transcript SET text = :t WHERE id = :id AND text <> :t"),
                {"t": masked, "id": call.turn_ids[turn.index]},
            )
        # Audit's "Redaction: PII masked" reads this.
        conn.execute(text("UPDATE interactions SET redaction_applied = true WHERE id = :ix"),
                     {"ix": call.interaction_id})


def _accepted_findings(conn: Any, call: Call) -> tuple[str | None, list[tuple[str, pii.Finding]]]:
    index_of = {v: k for k, v in call.turn_ids.items()}
    rid = conn.execute(
        text("SELECT id FROM redaction_records WHERE interaction_id = :ix"), {"ix": call.interaction_id}
    ).scalar()
    rows = conn.execute(
        text("SELECT id, type, transcript_turn_id, start_offset, end_offset, confidence, detector "
             "FROM pii_findings WHERE redaction_id = :r AND accepted AND start_offset IS NOT NULL"),
        {"r": rid},
    ).mappings().all()
    return rid, [
        (r["id"], pii.Finding(index_of[r["transcript_turn_id"]], r["type"], r["start_offset"], r["end_offset"],
                              float(r["confidence"] or 0), r["detector"] or "pattern"))
        for r in rows if r["transcript_turn_id"] in index_of
    ]


def run_audio(call: Call) -> dict[str, str]:
    """Time every accepted finding on the recording and render the redacted copy."""
    import db
    from call_intel.inputs import recording
    from voice.redaction_export import write_redacted_wav

    media = recording(call.interaction_id)
    with db.engine.connect() as conn:
        rid, found = _accepted_findings(conn, call)
    if rid is None or media is None:
        return {}
    media_id, wav = media
    segments = audio.plan([f for _, f in found], call.turns, wav) if found else []
    ids = {id(f): fid for fid, f in found}
    with db.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM redaction_audio_segments WHERE redaction_id = :r AND COALESCE(source, '') <> 'manual'"),
            {"r": rid},
        )
        for s in segments:
            conn.execute(
                text(
                    """
                    INSERT INTO redaction_audio_segments (id, redaction_id, media_id, finding_id, at_sec,
                      duration_sec, muted, start_ms, end_ms, channel, source)
                    VALUES (:id, :r, :m, :f, :at, :dur, true, :s, :e, :ch, :src)
                    """
                ),
                {"id": db._id("RAS"), "r": rid, "m": media_id, "f": ids.get(id(s.finding)),
                 "at": s.start_ms // 1000, "dur": max(1, -(-(s.end_ms - s.start_ms) // 1000)),
                 "s": s.start_ms, "e": s.end_ms, "ch": s.channel, "src": s.source},
            )
    result = write_redacted_wav(call.interaction_id, rid)
    logger.info("call_intel %s: %s beeps (%s word-aligned)", call.interaction_id, len(segments),
                sum(s.source == "aligned" for s in segments))
    return {"audio": models.version(models.ASR) if segments else "none", "redacted": str(bool(result))}
