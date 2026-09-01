"""Deterministic scorecard on hangup. Coverage is evidence, not Azure.

Critical FPC criteria are filled from flags / disclosures / clocks. Soft
criteria land as a neutral 3 (no opportunity) so ``_qa_compute_total`` does
not treat them as a 0 against full weight. The gated LLM autoscore may later
overwrite empty soft cells; it must not clobber a ``[live]`` note.
"""

from __future__ import annotations

import logging
from datetime import timezone
from typing import Any

from sqlalchemy import text

from contact_policy import RBI_VOICE_END, RBI_VOICE_START
from agent_core.clock import to_local

logger = logging.getLogger(__name__)

LIVE_NOTE_PREFIX = "[live]"
NEUTRAL_SCORE = 3.0

# Criterion → (flag that fails it, rule_id, fail note)
_FLAG_CRITERIA: dict[str, tuple[str, str | None, str]] = {
    "cmp-recording": (
        "missing-recording-disclosure",
        "r-rec",
        "[live] Recording notice missing",
    ),
    "cmp-miranda": (
        "missing-mini-miranda",
        "r-mm",
        "[live] Mini-Miranda missing before dues",
    ),
    "scr-verify": (
        "identity-before-verify",
        "r-verify",
        "[live] Account figures before identity verification",
    ),
}

_LANGUAGE_FAIL_FLAGS = (
    "third-party-leak",
    "authority-cap-exceeded",
    "waiver-blocked",
    "rate-quoted",
)
_DND_FAIL_FLAGS = ("hours-breach", "opt-out-ignored")


def score_completed_interaction(interaction_id: str) -> dict[str, Any] | None:
    """Write an ``ai_draft`` scorecard from live evidence. Never raises.

    Returns the scorecard, or None when there is nothing to write (no
    interaction, a card already exists, too little transcript).
    """
    try:
        return _score(interaction_id)
    except Exception:
        logger.exception("live_qa scorecard failed for %s", interaction_id)
        return None


def score_pending(*, limit: int = 20) -> int:
    """Deterministic coverage sweep. Returns how many scorecards were written."""
    written = 0
    try:
        ids = _pending_ids(limit=limit)
    except Exception:
        logger.exception("live_qa pending selection failed")
        return 0
    for iid in ids:
        if score_completed_interaction(iid):
            written += 1
    return written


def _pending_ids(*, limit: int) -> list[str]:
    import db

    sql = """
        SELECT i.id
          FROM interactions i
         WHERE i.tenant_id = :tenant_id
           AND i.status IN ('completed', 'abandoned')
           AND i.ended_at IS NOT NULL
           AND i.ended_at <= now() - interval '1 minute'
           AND i.ended_at >= now() - interval '7 days'
           AND NOT EXISTS (
                 SELECT 1 FROM qa_scorecards q WHERE q.interaction_id = i.id
               )
           AND (
                 (SELECT count(*) FROM interaction_transcript t
                   WHERE t.interaction_id = i.id) >= 2
              OR (SELECT count(*) FROM conversations c
                    JOIN messages m ON m.conversation_id = c.id
                   WHERE c.interaction_id = i.id) >= 2
               )
         ORDER BY i.ended_at DESC
         LIMIT :lim
    """
    with db.engine.connect() as conn:
        return [
            r["id"]
            for r in db._rows(
                conn.execute(
                    text(sql),
                    {"tenant_id": db.current_tenant(), "lim": int(limit)},
                )
            )
        ]


def _score(interaction_id: str) -> dict[str, Any] | None:
    import db

    with db.engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT i.id, i.customer_id, i.account_id, i.channel, i.handler_kind,
                       i.handler_user_id, i.handler_bot_id, i.ptp_captured,
                       i.upsell_presented, i.started_at, i.ended_at, i.status,
                       c.timezone
                FROM interactions i
                LEFT JOIN customers c ON c.id = i.customer_id
                WHERE i.id = :id
                """
            ),
            {"id": interaction_id},
        ).mappings().first()
        if row is None:
            return None
        existing = conn.execute(
            text("SELECT 1 FROM qa_scorecards WHERE interaction_id = :id"),
            {"id": interaction_id},
        ).fetchone()
        if existing:
            return None

        flags = [
            r["flag"]
            for r in db._rows(
                conn.execute(
                    text(
                        """
                        SELECT DISTINCT flag FROM interaction_flags
                        WHERE interaction_id = :id
                        """
                    ),
                    {"id": interaction_id},
                )
            )
        ]
        disclosures = {
            (r["rule_id"] or "").strip()
            for r in db._rows(
                conn.execute(
                    text(
                        """
                        SELECT rule_id FROM interaction_disclosures
                        WHERE interaction_id = :id AND read IS TRUE
                        """
                    ),
                    {"id": interaction_id},
                )
            )
            if r.get("rule_id")
        }
        verified = bool(
            conn.execute(
                text(
                    """
                    SELECT 1 FROM identity_verifications
                    WHERE interaction_id = :id AND status = 'verified'
                    LIMIT 1
                    """
                ),
                {"id": interaction_id},
            ).fetchone()
        )
        hold_kinds = {
            r["kind"]
            for r in db._rows(
                conn.execute(
                    text(
                        """
                        SELECT kind FROM treatment_holds
                        WHERE customer_id = :cid
                          AND released_at IS NULL
                          AND (account_id IS NULL OR account_id = :aid)
                        """
                    ),
                    {
                        "cid": row["customer_id"],
                        "aid": row["account_id"],
                    },
                )
            )
            if row["customer_id"]
        }
        ptp_written = bool(
            conn.execute(
                text(
                    """
                    SELECT 1 FROM promises p
                    JOIN payment_intents pi ON pi.promise_id = p.id
                    WHERE p.interaction_id = :id
                      AND pi.confirm_channel IS NOT NULL
                    LIMIT 1
                    """
                ),
                {"id": interaction_id},
            ).fetchone()
        ) if row["ptp_captured"] else False
        offer_suppressed = bool(
            conn.execute(
                text(
                    """
                    SELECT 1 FROM offer_decisions
                    WHERE interaction_id = :id
                      AND suppression_reason IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"id": interaction_id},
            ).fetchone()
        )

        rubric = db._load_rubric_tree(conn)
        if not rubric:
            return None
        criteria = [c for s in rubric["sections"] for c in s["criteria"]]
        if not criteria:
            return None

    hours_fail = _hours_fail(row)
    if hours_fail and "hours-breach" not in flags:
        flags.append("hours-breach")

    entries = [
        _entry_for(
            cid=c["id"],
            flags=flags,
            disclosures=disclosures,
            verified=verified,
            hold_kinds=hold_kinds,
            ptp_captured=bool(row["ptp_captured"]),
            ptp_written=ptp_written,
            upsell_presented=bool(row["upsell_presented"]),
            offer_suppressed=offer_suppressed,
        )
        for c in criteria
    ]

    try:
        return db.create_scorecard(
            {
                "interactionId": interaction_id,
                "rubricId": rubric["id"],
                "status": "ai_draft",
                "subjectBotId": row["handler_bot_id"]
                if row["handler_kind"] == "bot"
                else None,
                "subjectUserId": row["handler_user_id"]
                if row["handler_kind"] == "human"
                else None,
                "entries": entries,
            }
        )
    except Exception as exc:
        import pg_errors

        if pg_errors.is_unique_violation(exc):
            return None
        raise


def _hours_fail(row: Any) -> bool:
    channel = (row.get("channel") or "voice").lower()
    if channel != "voice":
        return False
    started = row.get("started_at")
    if started is None:
        return False
    if getattr(started, "tzinfo", None) is None:
        started = started.replace(tzinfo=timezone.utc)
    local = to_local(started)
    return local.hour < RBI_VOICE_START or local.hour >= RBI_VOICE_END


def _entry_for(
    *,
    cid: str,
    flags: list[str],
    disclosures: set[str],
    verified: bool,
    hold_kinds: set[str],
    ptp_captured: bool,
    ptp_written: bool,
    upsell_presented: bool,
    offer_suppressed: bool,
) -> dict[str, Any]:
    flag_hit = _FLAG_CRITERIA.get(cid)
    if flag_hit:
        flag, _rule, note = flag_hit
        if flag in flags:
            return _cell(cid, 0.0, note)
        if cid == "cmp-recording" and ("r-rec" in disclosures or "rule-recording" in disclosures):
            return _cell(cid, 5.0, "[live] Recording notice given")
        if cid == "cmp-miranda" and ("r-mm" in disclosures or "rule-mini-miranda" in disclosures):
            return _cell(cid, 5.0, "[live] Mini-Miranda given")
        if cid == "scr-verify" and verified:
            return _cell(cid, 5.0, "[live] Identity verified")
        if cid == "cmp-miranda" and "missing-mini-miranda" not in flags:
            # No dues discussion captured — no opportunity.
            return _cell(cid, NEUTRAL_SCORE, None)
        if cid == "scr-verify" and not verified and "identity-before-verify" not in flags:
            return _cell(cid, NEUTRAL_SCORE, None)
        return _cell(cid, 5.0, f"[live] {cid} clear")

    if cid == "cmp-language":
        hit = next((f for f in _LANGUAGE_FAIL_FLAGS if f in flags), None)
        if hit:
            return _cell(cid, 0.0, f"[live] {hit}")
        if any(f.startswith("prohibited:") for f in flags):
            return _cell(cid, 0.0, "[live] prohibited language")
        return _cell(cid, 5.0, "[live] No prohibited language")

    if cid == "cmp-dnd":
        hit = next((f for f in _DND_FAIL_FLAGS if f in flags), None)
        if hit:
            return _cell(cid, 0.0, f"[live] {hit}")
        return _cell(cid, 5.0, "[live] Calling window / opt-out honoured")

    if cid == "res-close":
        if hold_kinds & {"hardship", "legal", "bereavement", "complaint"}:
            return _cell(cid, NEUTRAL_SCORE, "[live] Hold on account — collection close N/A")
        if ptp_captured and ptp_written:
            return _cell(cid, 5.0, "[live] Written PTP confirm on file")
        if ptp_captured and not ptp_written:
            return _cell(cid, 0.0, "[live] PTP captured without written confirm")
        return _cell(cid, NEUTRAL_SCORE, None)

    if cid == "ups-eligibility":
        if upsell_presented and offer_suppressed:
            return _cell(cid, 0.0, "[live] Pitch while offer engine suppressed")
        if not upsell_presented:
            return _cell(cid, NEUTRAL_SCORE, None)
        return _cell(cid, 5.0, "[live] Pitch after eligibility")

    # Soft cells: neutral until the LLM autoscore fills them.
    return _cell(cid, NEUTRAL_SCORE, None)


def _cell(criterion_id: str, score: float, note: str | None) -> dict[str, Any]:
    return {
        "criterionId": criterion_id,
        "aiSuggested": score,
        "score": score,
        "note": note,
    }


def is_live_locked(note: str | None) -> bool:
    return bool(note) and str(note).startswith(LIVE_NOTE_PREFIX)
