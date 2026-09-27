"""The signal sweep: every finished conversation, judged once per extractor version.

Runs from the worker every few minutes. Per interaction it:

1. **claims** it in ``signal_scans`` (a short transaction; two workers never
   judge the same call);
2. **gates** it on consent before reading a word: promotional consent opted in
   on some channel, no promotional withdrawal, not on DND, and nothing said in
   the last 30 days that makes selling wrong (hardship, dispute, legal, stop
   contacting me). A skip is recorded with its reason;
3. waits, for a Voice Studio call, until call intelligence has re-masked its
   transcript (the PII stage), when that pipeline is installed;
4. **extracts** outside any transaction (the LLM call is slow), then writes
   the checked signals and closes the ledger row.

Only the masked ``interaction_transcript`` is read. The raw engine words and
unmasked WhatsApp ``messages`` are never read here.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import text

from agent_core.signals.extract import EXTRACTOR_VERSION, extract

logger = logging.getLogger(__name__)

MIN_CUSTOMER_TURNS = 3
LOOKBACK_DAYS = 30

_CANDIDATES = """
SELECT i.id, i.tenant_id, i.customer_id, i.channel
  FROM interactions i
  LEFT JOIN signal_scans s ON s.interaction_id = i.id
 WHERE i.status IN ('completed', 'abandoned')
   AND i.customer_id IS NOT NULL AND i.customer_id <> 'UNKNOWN-CALLER'
   AND COALESCE(i.ended_at, i.started_at) > now() - make_interval(days => :days)
   AND (s.interaction_id IS NULL OR (s.extractor_version < :ver AND s.status <> 'claimed'))
   AND (SELECT count(*) FROM interaction_transcript t
         WHERE t.interaction_id = i.id AND t.speaker = 'customer') >= :min_turns
 ORDER BY COALESCE(i.ended_at, i.started_at) DESC
 LIMIT :lim
"""


def _claim(conn: Any, row: dict[str, Any]) -> bool:
    got = conn.execute(
        text(
            """
            INSERT INTO signal_scans (interaction_id, tenant_id, customer_id, extractor_version, status)
            VALUES (:i, :t, :c, :v, 'claimed')
            ON CONFLICT (interaction_id) DO UPDATE
               SET extractor_version = EXCLUDED.extractor_version, status = 'claimed',
                   skip_reason = NULL, scanned_at = now()
             WHERE signal_scans.status <> 'claimed' AND signal_scans.extractor_version < EXCLUDED.extractor_version
            RETURNING interaction_id
            """
        ),
        {"i": row["id"], "t": row["tenant_id"], "c": row["customer_id"], "v": EXTRACTOR_VERSION},
    ).first()
    return got is not None


def _close(conn: Any, interaction_id: str, status: str, *, reason: str | None = None, n: int = 0) -> None:
    conn.execute(
        text(
            """
            UPDATE signal_scans SET status = :s, skip_reason = :r, signals = :n, scanned_at = now()
             WHERE interaction_id = :i
            """
        ),
        {"i": interaction_id, "s": status, "r": reason, "n": n},
    )


def consent_block(conn: Any, customer_id: str) -> str | None:
    """Why this customer's conversations may not be read for sales, or None."""
    import capture

    dnd = conn.execute(text("SELECT dnd FROM customers WHERE id = :c"), {"c": customer_id}).scalar()
    if dnd:
        return "on_dnd"
    if not any(
        capture.promotional_consent(conn, customer_id, ch) == "opted_in"
        for ch in ("whatsapp", "voice", "sms", "email")
    ):
        return "no_promotional_consent"
    withdrawn = conn.execute(
        text(
            """
            SELECT 1 FROM consent_events
             WHERE customer_id = :c AND purpose IN ('promotional', 'all')
               AND verb IN ('withdraw', 'opt_out', 'restrict')
               AND captured_at > now() - interval '365 days'
             LIMIT 1
            """
        ),
        {"c": customer_id},
    ).first()
    if withdrawn:
        return "promotional_consent_withdrawn"
    try:
        with conn.begin_nested():
            said = conn.execute(
                text(
                    """
                    SELECT 1 FROM perception_facts
                     WHERE customer_id = :c AND provenance = 'borrower_utterance'
                       AND fact_key IN ('hardship_claimed','dispute_claimed','consent_withdrawal','legal_threat')
                       AND superseded_at IS NULL AND abstained IS FALSE
                       AND observed_at > now() - interval '30 days'
                     LIMIT 1
                    """
                ),
                {"c": customer_id},
            ).first()
    except Exception:
        said = None
    if said:
        return "said_something_that_rules_out_selling"
    return None


def _pii_pending(conn: Any, interaction_id: str) -> bool:
    """A Voice Studio call whose transcript call intelligence has not re-masked yet."""
    from agent_core.treatment import schema_ready

    if not schema_ready.has_table(conn, "call_intelligence_jobs"):
        return False
    row = conn.execute(
        text("SELECT stages_done FROM call_intelligence_jobs WHERE interaction_id = :i"),
        {"i": interaction_id},
    ).first()
    return row is not None and "pii" not in (row[0] or [])


def scan_one(row: dict[str, Any]) -> dict[str, Any]:
    """Claim, gate, extract, write. Never raises."""
    import db
    import tenant_context

    interaction_id = row["id"]
    with tenant_context.bind(row["tenant_id"]):
        with db.engine.begin() as conn:
            if not _claim(conn, row):
                return {"interactionId": interaction_id, "status": "taken"}
            if _pii_pending(conn, interaction_id):
                # Not judged yet; released so the next sweep tries again.
                conn.execute(text("DELETE FROM signal_scans WHERE interaction_id = :i"), {"i": interaction_id})
                return {"interactionId": interaction_id, "status": "waiting_for_masking"}
            block = consent_block(conn, row["customer_id"])
            if block:
                _close(conn, interaction_id, "skipped", reason=block)
                return {"interactionId": interaction_id, "status": "skipped", "reason": block}
            turns = [
                dict(r)
                for r in conn.execute(
                    text(
                        """
                        SELECT id, turn_index, speaker, text FROM interaction_transcript
                         WHERE interaction_id = :i ORDER BY turn_index LIMIT 80
                        """
                    ),
                    {"i": interaction_id},
                ).mappings()
            ]
            products = [
                str(p)
                for p in conn.execute(
                    text("SELECT id FROM products WHERE tenant_id = :t AND is_active"), {"t": row["tenant_id"]}
                ).scalars()
            ]
        try:
            found = extract(turns, products=products)
        except Exception as exc:
            logger.exception("signal extraction failed for %s", interaction_id)
            with db.engine.begin() as conn:
                _close(conn, interaction_id, "failed", reason=type(exc).__name__)
            return {"interactionId": interaction_id, "status": "failed"}
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE customer_signals SET superseded_at = now()
                     WHERE interaction_id = :i AND superseded_at IS NULL
                    """
                ),
                {"i": interaction_id},
            )
            for s in found:
                conn.execute(
                    text(
                        """
                        INSERT INTO customer_signals
                          (id, tenant_id, customer_id, interaction_id, transcript_turn_id, channel,
                           signal_code, product_hint, horizon, confidence, extractor_version)
                        VALUES (:id, :t, :c, :i, :turn, :ch, :code, :hint, :h, :conf, :v)
                        """
                    ),
                    {
                        "id": f"SIG-{uuid.uuid4().hex[:12].upper()}", "t": row["tenant_id"],
                        "c": row["customer_id"], "i": interaction_id, "turn": s.turn_id,
                        "ch": row["channel"], "code": s.code, "hint": s.product_hint,
                        "h": s.horizon, "conf": round(s.confidence, 3), "v": EXTRACTOR_VERSION,
                    },
                )
            _close(conn, interaction_id, "done", n=len(found))
    return {"interactionId": interaction_id, "status": "done", "signals": len(found)}


def sweep(limit: int = 10) -> dict[str, Any]:
    """Judge up to ``limit`` unjudged conversations."""
    import db
    from agent_core.treatment import schema_ready

    with db.engine.begin() as conn:
        if not schema_ready.has_table(conn, "signal_scans"):
            return {"skipped": "signal_tables_absent"}
        # A worker that died mid-extraction leaves a claim nobody will close.
        conn.execute(
            text("DELETE FROM signal_scans WHERE status = 'claimed' AND scanned_at < now() - interval '1 hour'")
        )
        rows = [
            dict(r)
            for r in conn.execute(
                text(_CANDIDATES),
                {"days": LOOKBACK_DAYS, "ver": EXTRACTOR_VERSION, "min_turns": MIN_CUSTOMER_TURNS, "lim": limit},
            ).mappings()
        ]
    results = [scan_one(r) for r in rows]
    return {
        "judged": sum(1 for r in results if r["status"] in {"done", "skipped"}),
        "signals": sum(r.get("signals", 0) for r in results),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
    }
