"""Score a finished bot call against the QA rubric, automatically.

``qa_scorecard_entries.ai_suggested_score`` has existed since the QA screens
shipped and nothing has ever populated it — ``qa_scorecards.status`` even
allows ``ai_draft``. The socket was built and left empty, so QA is a human
screen over demo data: a reviewer can score a call, but nobody scores the other
several hundred.

This fills it. The model proposes, a human disposes: rows land as ``ai_draft``
with ``accepted`` unset, which is exactly the state the existing UI renders as
"needs review".

Three things here are load-bearing and easy to get wrong:

**Both score columns are written.** ``db._qa_section_total`` reads
``final_score`` (mapped from the ``score`` key), *not* ``ai_suggested_score``.
Writing only the AI column would compute a total of 0, band ``red``, and trip
the critical-fail cap at 40 on every single call.

**Coverage is gated.** ``_qa_compute_total`` iterates every rubric criterion and
scores a missing one as 0 against its full weight. A truncated or partial model
response would therefore produce a confident-looking red band that the model
never asserted. Below the threshold we write nothing at all.

**It runs on the analysis Azure profile.** QA is the lowest-value Azure caller
in the system; it must never compete with a live conversation turn for a slot.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

_TOOL_NAME = "submit_qa_scores"

# Below this share of the rubric's criteria, write nothing. A partial response
# is not a partial score — see the module docstring.
MIN_COVERAGE = 0.8

# Enough for a full collections call; the summariser's 40 is tuned for a short
# handover note, not for scoring the whole conversation.
TRANSCRIPT_TURNS = 80

_SYSTEM_PROMPT = """You are a quality analyst reviewing one completed collections call
for an Indian retail bank. Score the agent against the rubric below.

Each criterion is scored 0 to 5:
  5  fully met
  3  partially met
  0  not met at all, or the agent did the opposite

Score ONLY what the transcript shows. If a criterion had no opportunity to apply
(no dispute was raised, so dispute handling never came up), score 3 — a neutral
score, not a penalty. Do not infer intent the words do not support.

Calls are in English, Hindi, or a mix. Judge what was communicated, not which
language it was communicated in.

Add a short note (under 20 words) only where the score is not 5, explaining what
was missing. Never quote account numbers, amounts or phone digits in a note.

Call submit_qa_scores exactly once with a score for EVERY criterion listed."""


def enabled() -> bool:
    return (os.getenv("QA_AUTOSCORE_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _tool_schema(criteria: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": _TOOL_NAME,
            "description": "Submit one score per rubric criterion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scores": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "criterionId": {
                                    "type": "string",
                                    "enum": [c["id"] for c in criteria],
                                },
                                "score": {"type": "number"},
                                "note": {"type": "string"},
                            },
                            "required": ["criterionId", "score"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["scores"],
                "additionalProperties": False,
            },
        },
    }


def _render_rubric(rubric: dict[str, Any]) -> str:
    lines: list[str] = []
    for section in rubric.get("sections") or []:
        lines.append(f"\n## {section.get('label') or section.get('name')}")
        for c in section.get("criteria") or []:
            flag = " [CRITICAL — scoring 0 caps the whole call]" if c.get("critical") else ""
            desc = f" — {c['description']}" if c.get("description") else ""
            lines.append(f"- id={c['id']}: {c['label']}{desc}{flag}")
    return "\n".join(lines)


def _flat_criteria(rubric: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for s in (rubric.get("sections") or []) for c in (s.get("criteria") or [])]


def _clamp_score(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN
        return None
    return max(0.0, min(5.0, round(value, 2)))


def score_interaction(
    interaction_id: str,
    *,
    rubric_id: str | None = None,
) -> dict[str, Any] | None:
    """Score one interaction. Returns the scorecard, or None if nothing was written.

    Returns None — rather than raising — for every expected miss: too little
    transcript, Azure unavailable, a malformed response, insufficient coverage,
    or a scorecard that already exists. The caller is a background sweep, and an
    unscored call is an honest state.
    """
    import azure_openai
    import db
    import transcript_view

    if not rubric_id:
        rubric_id = db.rubric_id_for_interaction(interaction_id)
        if not rubric_id:
            logger.info("qa autoscore: no channel-appropriate rubric for %s", interaction_id)
            return None

    rubric = db.load_rubric_tree(rubric_id)
    if not rubric:
        logger.warning("qa autoscore: no rubric available")
        return None
    criteria = _flat_criteria(rubric)
    if not criteria:
        return None

    if _has_final_scorecard(interaction_id):
        return None

    transcript = transcript_view.fenced_transcript(interaction_id, limit=TRANSCRIPT_TURNS)
    if not transcript:
        return None

    try:
        result = azure_openai.chat_with_tools(
            [
                {"role": "system", "content": _SYSTEM_PROMPT + "\n" + _render_rubric(rubric)},
                {"role": "user", "content": transcript},
            ],
            tools=[_tool_schema(criteria)],
            tool_choice={"type": "function", "function": {"name": _TOOL_NAME}},
            temperature=0.0,
            max_completion_tokens=1200,
            profile=azure_openai.PROFILE_ANALYSIS,
        )
    except azure_openai.AzureBusyError:
        # Signalled to the caller so it abandons the whole tick: if analysis is
        # saturated, the next nine interactions will be too.
        raise
    except Exception:
        logger.debug("qa autoscore call failed · ix=%s", interaction_id, exc_info=True)
        return None

    payload = _parse(result)
    if payload is None:
        return None

    valid = _validate(payload, criteria)
    if valid is None:
        return None

    locked = _live_locked_criteria(interaction_id)
    if locked:
        valid = {cid: pair for cid, pair in valid.items() if cid not in locked}
        if not valid:
            return None

    entries = [
        {
            "criterionId": cid,
            # BOTH columns. _qa_section_total reads `score`; `aiSuggested`
            # preserves what the model actually said so a reviewer can see how
            # far they moved it.
            "aiSuggested": score,
            "score": score,
            "note": note or None,
            # Left unset: `ai_draft` + accepted IS NULL is the "needs review"
            # state the QA screen already understands.
        }
        for cid, (score, note) in valid.items()
    ]

    existing_id = _existing_scorecard_id(interaction_id)
    try:
        if existing_id:
            return db.patch_scorecard(existing_id, {"entries": entries, "status": "ai_draft"})
        return db.create_scorecard(
            {
                "interactionId": interaction_id,
                "rubricId": rubric["id"],
                "status": "ai_draft",
                "entries": entries,
            }
        )
    except Exception as exc:
        # qa_scorecards.interaction_id is UNIQUE and create_scorecard does not
        # handle that violation — it only guards against an id collision. A
        # human scoring the call between our SELECT and this INSERT is a normal
        # race, not an error, and their scorecard wins.
        import pg_errors

        if pg_errors.is_unique_violation(exc):
            logger.debug("qa autoscore: scorecard already exists · ix=%s", interaction_id)
            return None
        logger.warning("qa autoscore persist failed · ix=%s", interaction_id, exc_info=True)
        return None


def _parse(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    for call in result.get("toolCalls") or []:
        if call.get("name") != _TOOL_NAME:
            continue
        try:
            payload = json.loads(call.get("arguments") or "{}")
        except (TypeError, ValueError):
            logger.debug("qa autoscore: unparseable tool arguments", exc_info=True)
            continue
        if isinstance(payload, dict):
            return payload
    logger.debug("qa autoscore: no usable tool call in response")
    return None


def _validate(
    payload: dict[str, Any], criteria: list[dict[str, Any]]
) -> dict[str, tuple[float, str | None]]:
    """Drop what we cannot trust, then require most of the rubric to survive."""
    known = {c["id"] for c in criteria}
    out: dict[str, tuple[float, str | None]] = {}

    for row in payload.get("scores") or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("criterionId") or "").strip()
        if cid not in known:
            logger.warning("qa autoscore: unknown criterion %r — dropped", cid)
            continue
        score = _clamp_score(row.get("score"))
        if score is None:
            logger.warning("qa autoscore: unusable score for %s — dropped", cid)
            continue
        note = str(row.get("note") or "").strip()[:280] or None
        out[cid] = (score, note)

    coverage = len(out) / len(known) if known else 0.0
    if coverage < MIN_COVERAGE:
        # Not a partial score. _qa_compute_total treats a missing criterion as
        # 0 against full weight, so writing this would publish a red band the
        # model never asserted.
        logger.info(
            "qa autoscore: coverage %.0f%% below %.0f%% — writing nothing",
            coverage * 100,
            MIN_COVERAGE * 100,
        )
        return None
    return out


def _existing_scorecard_id(interaction_id: str) -> str | None:
    import db

    with db.engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id FROM qa_scorecards
                WHERE interaction_id = :id AND status = 'ai_draft'
                LIMIT 1
                """
            ),
            {"id": interaction_id},
        ).mappings().first()
    return str(row["id"]) if row else None


def _has_final_scorecard(interaction_id: str) -> bool:
    import db

    with db.engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    """
                    SELECT 1 FROM qa_scorecards
                    WHERE interaction_id = :id AND status = 'final'
                    LIMIT 1
                    """
                ),
                {"id": interaction_id},
            ).fetchone()
        )


def _live_locked_criteria(interaction_id: str) -> set[str]:
    """Criterion ids whose score came from live evidence — the LLM must not clobber them."""
    import db

    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT e.criterion_id
                    FROM qa_scorecard_entries e
                    JOIN qa_scorecards s ON s.id = e.scorecard_id
                    WHERE s.interaction_id = :id
                      AND e.note LIKE '[live]%'
                    """
                ),
                {"id": interaction_id},
            )
        )
    return {r["criterion_id"] for r in rows}


# ---------------------------------------------------------------------------
# Batch selection
# ---------------------------------------------------------------------------

_SELECT_SQL = """
    SELECT i.id
      FROM interactions i
     WHERE i.tenant_id = :tenant_id
       AND i.status = 'completed'
       AND i.handler_kind = 'bot'
       AND i.ended_at BETWEEN now() - CAST(:max_age AS interval)
                          AND now() - CAST(:min_age AS interval)
       AND (
             NOT EXISTS (
               SELECT 1 FROM qa_scorecards q WHERE q.interaction_id = i.id
             )
          OR EXISTS (
               SELECT 1 FROM qa_scorecards q
               JOIN qa_scorecard_entries e ON e.scorecard_id = q.id
              WHERE q.interaction_id = i.id
                AND q.status = 'ai_draft'
                AND (e.note IS NULL OR e.note NOT LIKE '[live]%')
             )
           )
       AND (
             SELECT count(*) FROM interaction_transcript t
              WHERE t.interaction_id = i.id
           ) >= :min_turns
     ORDER BY i.ended_at DESC
     LIMIT :lim
"""


def pending_interactions(*, limit: int = 10) -> list[str]:
    """Completed bot calls with no scorecard yet.

    The five-minute floor lets the CrmSink's ``complete`` job and the transcript
    export finish first — scoring a call whose last two turns have not landed
    would score a truncated conversation. The 24-hour ceiling bounds retries: an
    interaction that cannot be scored ages out instead of being retried forever.

    Bot-only is deliberate. Auto-scoring a human agent is a people-management
    decision, not an engineering one.
    """
    import db

    with db.engine.connect() as conn:
        return [
            r["id"]
            for r in db._rows(
                conn.execute(
                    text(_SELECT_SQL),
                    {
                        "tenant_id": db.current_tenant(),
                        "min_age": "5 minutes",
                        "max_age": "24 hours",
                        "min_turns": 4,
                        "lim": int(limit),
                    },
                )
            )
        ]


def score_pending(*, limit: int = 10) -> int:
    """Score one batch. Returns how many scorecards were written."""
    import azure_openai

    if not enabled():
        return 0

    written = 0
    for interaction_id in pending_interactions(limit=limit):
        try:
            if score_interaction(interaction_id):
                written += 1
        except azure_openai.AzureBusyError:
            # Abandon the whole tick — a live call outranks QA for every slot.
            logger.info("qa autoscore batch abandoned — azure analysis saturated")
            break
        except Exception:
            logger.warning("qa autoscore failed · ix=%s", interaction_id, exc_info=True)
    return written
