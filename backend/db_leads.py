"""Leads: pipeline reads, routing, stage machine and follow-ups (WP-036 peel).

Peeled from ``db.py``. Call sites stay ``db.*`` via a bottom-of-file
re-export. Reach the engine through :func:`_db`, never ``from db_core import
engine``: the ``db_tx`` fixture wraps ``db.engine``, and a name bound from
``db_core`` bypasses that proxy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from schemas import LeadResponse
from sqlalchemy import text
from typing import Any


def _db():
    """The ``db`` module object, resolved at call time."""
    import db as d

    return d


# Filters the pipeline screen actually offers, resolved server-side. They used
# to be applied only in the browser, over whatever the first page happened to
# contain — so "All owners" on a 5,000-lead book filtered 200 rows and said
# nothing about it.
#
# Every parameter is CAST to text before the NULL test. Postgres cannot infer a
# type for a bare placeholder in `$1 IS NULL` and rejects the statement with
# AmbiguousParameter; the cast is what tells it what an absent filter is.
_LEAD_FILTER_SQL = """
              AND (CAST(:stage      AS text) IS NULL OR l.stage = :stage)
              AND (CAST(:owner      AS text) IS NULL OR u.name = :owner)
              AND (CAST(:team       AS text) IS NULL OR t.name = :team)
              AND (CAST(:product_id AS text) IS NULL OR l.product_id = :product_id)
              AND (CAST(:source     AS text) IS NULL OR l.source = :source)
              -- Comma-separated, because the screen's priority and sentiment
              -- controls are multi-select. A single-value filter here would
              -- have forced those two to stay client-side, and then the KPI
              -- strip and the board would be describing different sets.
              AND (
                CAST(:priority AS text) IS NULL
                OR l.priority = ANY(string_to_array(:priority, ','))
              )
              AND (
                CAST(:sentiment AS text) IS NULL
                OR l.sentiment_at_capture = ANY(string_to_array(:sentiment, ','))
              )
              AND (
                CAST(:q AS text) IS NULL
                OR l.id ILIKE '%%' || :q || '%%'
                OR c.name ILIKE '%%' || :q || '%%'
                OR COALESCE(l.account_id, '') ILIKE '%%' || :q || '%%'
                OR COALESCE(p.name, '') ILIKE '%%' || :q || '%%'
                OR COALESCE(l.transcript_snippet, '') ILIKE '%%' || :q || '%%'
              )
"""

def _lead_filter_params(filters: dict[str, Any] | None) -> dict[str, Any]:
    """Normalise the screen's filter vocabulary. "all" and "" both mean unset."""
    f = filters or {}

    def pick(key: str) -> str | None:
        raw = str(f.get(key) or "").strip()
        return None if not raw or raw == "all" else raw

    return {
        "stage": pick("stage"),
        "owner": pick("owner"),
        "team": pick("team"),
        "product_id": pick("productId"),
        "source": pick("source"),
        "priority": pick("priority"),
        "sentiment": pick("sentiment"),
        "q": pick("q"),
    }

def list_leads(
    *,
    limit: int | None = None,
    offset: int | None = None,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    _mod = _db()
    _account_tail = _mod._account_tail
    _dump = _mod._dump
    _rows = _mod._rows
    _sql = _mod._sql
    _tenant = _mod._tenant
    _vis_params = _mod._vis_params
    clamp_list_limit = _mod.clamp_list_limit
    clamp_offset = _mod.clamp_offset
    engine = _mod.engine
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    """
                    SELECT
                      l.id,
                      l.customer_id,
                      c.name AS customer_name,
                      l.account_id,
                      l.product_id,
                      p.name AS product,
                      l.stage,
                      l.source,
                      l.sentiment_at_capture,
                      l.sentiment_score,
                      l.estimated_value,
                      l.offer_amount,
                      l.offer_roi,
                      l.priority,
                      l.captured_at,
                      l.closed_at,
                      l.won_amount,
                      l.loss_reason,
                      l.interaction_id,
                      l.transcript_snippet,
                      u.name AS owner,
                      t.name AS team
                    FROM leads l
                    JOIN customers c ON c.id = l.customer_id
                     AND c.tenant_id = :tenant_id
                     /*VISIBILITY*/
                    LEFT JOIN products p ON p.id = l.product_id
                    LEFT JOIN users u ON u.id = l.owner_user_id
                    LEFT JOIN teams t ON t.id = l.team_id
                    WHERE TRUE
                    """
                    + _LEAD_FILTER_SQL
                    + """
                    ORDER BY l.captured_at DESC NULLS LAST, l.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {
                    "limit": page,
                    "offset": skip,
                    "tenant_id": _tenant(),
                    **_vis_params(),
                    **_lead_filter_params(filters),
                },
            )
        )
        # Three bulk queries rather than 3N. The list endpoint is the ONLY
        # source the Upsell screen reads — the detail drawer re-uses the row
        # from this array rather than fetching — so everything the drawer
        # renders has to be here. Returning [] for follow-ups meant one
        # scheduled a second ago showed as "No follow-ups yet".
        lead_ids = [r["id"] for r in rows]
        eligibility_by_lead: dict[str, list[dict[str, Any]]] = {}
        for elig in _rows(
            conn.execute(
                text(
                    "SELECT lead_id, label, passed AS ok, reason AS detail"
                    " FROM lead_eligibility WHERE lead_id = ANY(:ids) ORDER BY lead_id, id"
                ),
                {"ids": lead_ids},
            )
        ):
            eligibility_by_lead.setdefault(elig.pop("lead_id"), []).append(elig)
        followups_by_lead = _lead_followups_bulk(conn, lead_ids)
        events_by_lead = _lead_events_bulk(conn, lead_ids)

        leads = []
        for row in rows:
            eligibility = eligibility_by_lead.get(row["id"], [])
            followups = followups_by_lead.get(row["id"], [])
            leads.append(
                _dump(
                    LeadResponse(
                        id=row["id"],
                        customerId=row["customer_id"],
                        customerName=row["customer_name"],
                        accountId=row["account_id"],
                        accountTail=_account_tail(row["account_id"]),
                        offer={
                            "productId": row["product_id"],
                            "label": row["product"] or row["product_id"],
                            "indicativeAmount": row["offer_amount"],
                            "indicativeROI": row["offer_roi"],
                        },
                        stage=row["stage"],
                        capturedAt=row["captured_at"],
                        sourceCallId=row["interaction_id"],
                        source=row["source"],
                        sentimentAtCapture=row["sentiment_at_capture"],
                        sentimentScore=row["sentiment_score"],
                        transcriptSnippet=row["transcript_snippet"],
                        eligibilityFlags=eligibility,
                        owner=row["owner"],
                        team=row["team"],
                        priority=row["priority"],
                        estimatedValue=row["estimated_value"],
                        nextFollowUpAt=_next_followup_at(followups),
                        followUps=followups,
                        events=events_by_lead.get(row["id"], []),
                        closedAt=row["closed_at"],
                        wonAmount=row["won_amount"],
                        lossReason=row["loss_reason"],
                    )
                )
            )
    return leads

def lead_metrics(filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """The pipeline KPI strip, computed over the whole book.

    These numbers were derived in the browser from whatever ``GET /leads``
    returned, and that endpoint pages at 200. Below the page size the answer
    happened to be right; above it "Conversion (30d)" quietly described the 200
    most recently captured leads while the header claimed to be showing
    everything. A summary statistic computed from a page is not a summary
    statistic.

    Definitions match the client-side ones they replace, deliberately: a lead's
    value is its won amount once won and its estimate before that; conversion
    is won-over-captured within the last 30 days, by capture date; and
    time-to-close spans every closed lead, not just recent ones.
    """
    _mod = _db()
    _one = _mod._one
    _rows = _mod._rows
    _sql = _mod._sql
    _tenant = _mod._tenant
    _vis_params = _mod._vis_params
    engine = _mod.engine
    params = {"tenant_id": _tenant(), **_vis_params(), **_lead_filter_params(filters)}
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                _sql(
                    """
                    WITH scoped AS (
                      SELECT
                        l.stage,
                        l.captured_at,
                        l.closed_at,
                        COALESCE(
                          CASE WHEN l.stage = 'won'
                               THEN COALESCE(l.won_amount, l.estimated_value)
                               ELSE l.estimated_value END,
                          0
                        ) AS value
                      FROM leads l
                      JOIN customers c ON c.id = l.customer_id
                       AND c.tenant_id = :tenant_id
                       /*VISIBILITY*/
                      LEFT JOIN products p ON p.id = l.product_id
                      LEFT JOIN users u ON u.id = l.owner_user_id
                      LEFT JOIN teams t ON t.id = l.team_id
                      WHERE TRUE
                    """
                    + _LEAD_FILTER_SQL
                    + """
                    )
                    SELECT
                      COUNT(*)::int                                              AS total,
                      COUNT(*) FILTER (
                        WHERE stage IN ('interested','contacted','qualified')
                      )::int                                                     AS open_leads,
                      COALESCE(SUM(value) FILTER (
                        WHERE stage IN ('interested','contacted','qualified')
                      ), 0)::float                                               AS pipeline_value,
                      COUNT(*) FILTER (
                        WHERE stage = 'won' AND closed_at > now() - interval '7 days'
                      )::int                                                     AS won_week,
                      COALESCE(SUM(value) FILTER (
                        WHERE stage = 'won' AND closed_at > now() - interval '7 days'
                      ), 0)::float                                               AS won_week_amount,
                      COUNT(*) FILTER (
                        WHERE captured_at > now() - interval '30 days'
                      )::int                                                     AS captured_30d,
                      COUNT(*) FILTER (
                        WHERE captured_at > now() - interval '30 days' AND stage = 'won'
                      )::int                                                     AS won_30d,
                      AVG(
                        EXTRACT(EPOCH FROM (closed_at - captured_at)) / 86400.0
                      ) FILTER (WHERE closed_at IS NOT NULL)                     AS avg_days_to_close
                    FROM scoped
                    """
                ),
                params,
            )
        ) or {}

        by_stage = {
            r["stage"]: {"count": r["n"], "amount": float(r["amount"] or 0)}
            for r in _rows(
                conn.execute(
                    _sql(
                        """
                        SELECT
                          l.stage,
                          COUNT(*)::int AS n,
                          COALESCE(SUM(
                            COALESCE(
                              CASE WHEN l.stage = 'won'
                                   THEN COALESCE(l.won_amount, l.estimated_value)
                                   ELSE l.estimated_value END,
                              0
                            )
                          ), 0)::float AS amount
                        FROM leads l
                        JOIN customers c ON c.id = l.customer_id
                         AND c.tenant_id = :tenant_id
                         /*VISIBILITY*/
                        LEFT JOIN products p ON p.id = l.product_id
                        LEFT JOIN users u ON u.id = l.owner_user_id
                        LEFT JOIN teams t ON t.id = l.team_id
                        WHERE TRUE
                        """
                        + _LEAD_FILTER_SQL
                        + """
                        GROUP BY 1
                        """
                    ),
                    params,
                )
            )
        }

    captured_30d = int(row.get("captured_30d") or 0)
    won_30d = int(row.get("won_30d") or 0)
    avg_days = row.get("avg_days_to_close")
    return {
        "total": int(row.get("total") or 0),
        "openLeads": int(row.get("open_leads") or 0),
        "pipelineValue": float(row.get("pipeline_value") or 0),
        "wonWeek": int(row.get("won_week") or 0),
        "wonWeekAmount": float(row.get("won_week_amount") or 0),
        # None, not 0, when nothing was captured in the window. "no leads to
        # convert" and "converted none of them" are different facts and the
        # strip renders them differently.
        "conversionRate": (
            round(won_30d / captured_30d * 100) if captured_30d else None
        ),
        "captured30d": captured_30d,
        "won30d": won_30d,
        "avgDaysToClose": None if avg_days is None else round(float(avg_days)),
        "perStage": {
            stage: by_stage.get(stage, {"count": 0, "amount": 0.0})
            for stage in ("interested", "contacted", "qualified", "won", "lost")
        },
    }

# activity_events.kind → the LeadEventKind the UI timeline renders. Anything
# not listed is still shown, with its raw kind, rather than dropped: an
# unmapped event is a labelling gap, not a reason to hide history.
_LEAD_EVENT_KINDS: dict[str, str] = {
    "lead_created": "created",
    "lead_updated": "stage_moved",
    "lead_stage_moved": "stage_moved",
    "lead_assigned": "assigned",
    "lead_team_changed": "team_changed",
    "lead_offer_edited": "offer_edited",
    "lead_followup_created": "followup_scheduled",
    # Rendered as a scheduling event rather than a new timeline vocabulary
    # word: the note carries "Follow-up overdue" and the channel and time, so
    # the reader loses nothing, and the UI's LeadEventKind union stays closed.
    "lead_followup_overdue": "followup_scheduled",
    "followup_updated": "followup_done",
    "lead_won": "won",
    "lead_lost": "lost",
    "lead_eligibility_revalidated": "eligibility_revalidated",
}

def _lead_events(conn: Any, lead_id: str) -> list[dict[str, Any]]:
    """Real audit trail for a lead, from activity_events.

    The list and detail endpoints both used to synthesise a single "created"
    entry from the lead row, so the Timeline tab — an audit surface — never
    showed a stage move, a reassignment or an offer edit. Every one of those
    mutations has been writing an activity_events row all along.
    """
    _mod = _db()
    _rows = _mod._rows
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT ae.at, ae.kind, ae.label, ae.note, ae.actor_kind,
                       u.name AS user_name, b.name AS bot_name
                FROM activity_events ae
                LEFT JOIN users u ON u.id = ae.actor_user_id
                LEFT JOIN bots b ON b.id = ae.actor_bot_id
                WHERE ae.entity_type = 'lead' AND ae.entity_id = :id
                  -- See _lead_events_bulk: lead_captured duplicates the fact
                  -- lead_created already records on this timeline.
                  AND ae.kind <> 'lead_captured'
                ORDER BY ae.at DESC, ae.id DESC
                LIMIT 100
                """
            ),
            {"id": lead_id},
        )
    )
    return [_lead_event(row) for row in rows]

def _lead_followups(conn: Any, lead_id: str) -> list[dict[str, Any]]:
    _mod = _db()
    _rows = _mod._rows
    return _rows(
        conn.execute(
            text(
                """
                SELECT id, due_at AS at, COALESCE(channel, 'voice') AS channel, note, status = 'done' AS done
                FROM followups
                WHERE lead_id = :lead_id
                ORDER BY due_at
                """
            ),
            {"lead_id": lead_id},
        )
    )

def _lead_followups_bulk(conn: Any, lead_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Follow-ups for many leads in one round trip.

    The list endpoint renders every lead on the board; per-lead queries here
    would be 2N round trips on a screen that already loads the whole pipeline.
    """
    _mod = _db()
    _rows = _mod._rows
    if not lead_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT lead_id, id, due_at AS at, COALESCE(channel, 'voice') AS channel, note,
                       status = 'done' AS done
                FROM followups
                WHERE lead_id = ANY(:ids)
                ORDER BY lead_id, due_at
                """
            ),
            {"ids": lead_ids},
        )
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(row.pop("lead_id"), []).append(row)
    return out

def _lead_events_bulk(conn: Any, lead_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Audit trail for many leads in one round trip."""
    _mod = _db()
    _rows = _mod._rows
    if not lead_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT ae.entity_id, ae.at, ae.kind, ae.label, ae.note, ae.actor_kind,
                       u.name AS user_name, b.name AS bot_name
                FROM activity_events ae
                LEFT JOIN users u ON u.id = ae.actor_user_id
                LEFT JOIN bots b ON b.id = ae.actor_bot_id
                WHERE ae.entity_type = 'lead' AND ae.entity_id = ANY(:ids)
                  -- lead_captured is the offer funnel's numerator, written for
                  -- the same act that writes lead_created. Both belong in the
                  -- table; showing both in the drawer would put "Lead created"
                  -- on the timeline twice.
                  AND ae.kind <> 'lead_captured'
                ORDER BY ae.entity_id, ae.at DESC, ae.id DESC
                """
            ),
            {"ids": lead_ids},
        )
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        bucket = out.setdefault(row["entity_id"], [])
        # Cap per lead: the board only ever renders a preview, and one
        # pathologically-edited lead must not dominate the response.
        if len(bucket) >= 50:
            continue
        bucket.append(_lead_event(row))
    return out

def _lead_event(row: dict[str, Any]) -> dict[str, Any]:
    by = row["user_name"] or row["bot_name"]
    if not by:
        by = "System"
    return {
        "at": row["at"],
        "kind": _LEAD_EVENT_KINDS.get(row["kind"], row["kind"]),
        "by": by,
        "note": row["note"] or row["label"],
    }

def _next_followup_at(followups: list[dict[str, Any]]) -> Any:
    """First OPEN follow-up. followups[0] was wrong: a completed one still
    sorts first by due_at, so the UI advertised a past, already-done call as
    the next action."""
    for f in followups:
        if not f.get("done"):
            return f.get("at")
    return None

def _lead_by_id(conn: Any, lead_id: str) -> dict[str, Any]:
    _mod = _db()
    _account_tail = _mod._account_tail
    _dump = _mod._dump
    _one = _mod._one
    _rows = _mod._rows
    row = _one(
        conn.execute(
            text(
                """
                SELECT l.id, l.customer_id, c.name AS customer_name, l.account_id, l.product_id,
                       p.name AS product, l.stage, l.source, l.sentiment_at_capture,
                       l.sentiment_score, l.estimated_value, l.offer_amount, l.offer_roi,
                       l.priority, l.captured_at, l.closed_at, l.interaction_id,
                       l.transcript_snippet,
                       u.name AS owner, t.name AS team, l.won_amount, l.loss_reason
                FROM leads l
                JOIN customers c ON c.id = l.customer_id
                LEFT JOIN products p ON p.id = l.product_id
                LEFT JOIN users u ON u.id = l.owner_user_id
                LEFT JOIN teams t ON t.id = l.team_id
                WHERE l.id = :id
                """
            ),
            {"id": lead_id},
        )
    )
    if row is None:
        raise KeyError("lead_not_found")
    eligibility = _rows(
        conn.execute(text("SELECT label, passed AS ok, reason AS detail FROM lead_eligibility WHERE lead_id = :lead_id ORDER BY id"), {"lead_id": lead_id})
    )
    followups = _lead_followups(conn, lead_id)
    return _dump(
        LeadResponse(
            id=row["id"],
            customerId=row["customer_id"],
            customerName=row["customer_name"],
            accountId=row["account_id"],
            accountTail=_account_tail(row["account_id"]),
            offer={
                "productId": row["product_id"],
                "label": row["product"] or row["product_id"],
                "indicativeAmount": row["offer_amount"] or row["estimated_value"] or row["won_amount"] or 0,
                "indicativeROI": row["offer_roi"] or "",
            },
            stage=row["stage"],
            capturedAt=row["captured_at"],
            sourceCallId=row["interaction_id"],
            source=row["source"],
            sentimentAtCapture=row["sentiment_at_capture"],
            sentimentScore=row["sentiment_score"],
            transcriptSnippet=row["transcript_snippet"],
            eligibilityFlags=eligibility,
            owner=row["owner"],
            team=row["team"],
            priority=row["priority"],
            estimatedValue=row["estimated_value"],
            nextFollowUpAt=_next_followup_at(followups),
            followUps=followups,
            events=_lead_events(conn, lead_id),
            closedAt=row["closed_at"],
            wonAmount=row["won_amount"],
            lossReason=row["loss_reason"],
        )
    )

# Product category → sales team. A lead for a policy must not land in the
# retail-loan queue simply because "retail-sales" was the hardcoded default on
# every bot-captured row.
_TEAM_BY_CATEGORY: dict[str, str] = {
    "insurance": "insurance",
    "card": "cards-sales",
    "loan": "retail-sales",
    "deposit": "retail-sales",
}

_DEFAULT_LEAD_TEAM = "retail-sales"

# Stages in which a lead is still being worked. A second lead for the same
# product while one of these is open is a duplicate, not a new opportunity.
OPEN_LEAD_STAGES = ("interested", "contacted", "qualified")

def find_open_lead(conn: Any, customer_id: str, product_id: str) -> dict[str, Any] | None:
    """An existing in-flight lead for this customer/product, if any."""
    _mod = _db()
    _one = _mod._one
    return _one(
        conn.execute(
            text(
                """
                SELECT id, stage, captured_at
                FROM leads
                WHERE customer_id = :cid AND product_id = :pid
                  AND stage = ANY(:stages)
                ORDER BY captured_at DESC NULLS LAST, id DESC
                LIMIT 1
                """
            ),
            {"cid": customer_id, "pid": product_id, "stages": list(OPEN_LEAD_STAGES)},
        )
    )

def _route_team_id(conn: Any, product_id: str, explicit: str | None) -> str | None:
    """Team that should own this lead. Explicit wins; otherwise route by
    product category, and fall back to NULL rather than an id that does not
    exist — a bad team_id is an IntegrityError, i.e. an HTTP 500 on a write
    that had nothing wrong with it."""
    _mod = _db()
    _one = _mod._one
    logger = _mod.logger
    candidate = explicit
    if not candidate:
        row = _one(
            conn.execute(
                text("SELECT category, type FROM products WHERE id = :id"), {"id": product_id}
            )
        )
        key = ((row or {}).get("category") or (row or {}).get("type") or "").strip().lower()
        candidate = _TEAM_BY_CATEGORY.get(key, _DEFAULT_LEAD_TEAM)
    exists = _one(
        conn.execute(text("SELECT id FROM teams WHERE id = :id"), {"id": candidate})
    )
    if exists:
        return candidate
    if candidate != _DEFAULT_LEAD_TEAM:
        fallback = _one(
            conn.execute(
                text("SELECT id FROM teams WHERE id = :id"), {"id": _DEFAULT_LEAD_TEAM}
            )
        )
        if fallback:
            return _DEFAULT_LEAD_TEAM
    logger.warning("lead routing: no team row for %r — leaving unassigned", candidate)
    return None

def create_lead(
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    *,
    allow_duplicate: bool = False,
    emitted: list[str] | None = None,
) -> dict[str, Any]:
    """Capture a lead. ``emitted`` is an out-parameter: the names of the
    analytics events that actually landed.

    The bot tool reports those names back to the model, and it must not claim
    an event whose row was never written — so the fact has to travel out of
    here rather than being assumed by the caller. It is not part of the API
    response because it is not part of the lead.
    """
    _mod = _db()
    _activity = _mod._activity
    _actor_user_id = _mod._actor_user_id
    _ensure_customer = _mod._ensure_customer
    _first_account_id = _mod._first_account_id
    _id = _mod._id
    _idempotent_response = _mod._idempotent_response
    _one = _mod._one
    _store_idempotent_response = _mod._store_idempotent_response
    _tenant = _mod._tenant
    engine = _mod.engine
    logger = _mod.logger
    endpoint = "POST /leads"
    with engine.begin() as conn:
        # Same contract as create_promise / create_dispute / create_callback.
        # capture_lead was the one CRM write with no replay protection, so a
        # retried tool call — the single most common thing an LLM does — put two
        # identical leads in the pipeline and two reps on the phone.
        cached = _idempotent_response(conn, idempotency_key, endpoint)
        if cached:
            return cached

        customer_id = payload["customerId"]
        _ensure_customer(conn, customer_id)
        lead_id = _id("LD")
        product_id = payload.get("productId")
        if not product_id:
            raise ValueError("productId_required")

        # Validate before INSERT: a bad product id would otherwise surface as an
        # unhandled IntegrityError (HTTP 500) instead of a 409 the caller can act on.
        product = _one(
            conn.execute(
                text("SELECT id, name, category, ticket_min, ticket_max, roi FROM products WHERE id = :id"),
                {"id": product_id},
            )
        )
        if product is None:
            raise ValueError("product_not_found")

        if not allow_duplicate:
            # Serialise concurrent capture of the same (customer, product): the
            # voice tool and the WhatsApp worker are genuinely concurrent
            # writers, so a plain SELECT-then-INSERT races. Transaction-scoped,
            # released on commit — same pattern as _idempotent_response.
            conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('lead'), hashtext(:k))"),
                {"k": f"{customer_id}:{product_id}"},
            )
            existing = find_open_lead(conn, customer_id, product_id)
            if existing:
                raise ValueError(f"duplicate_open_lead:{existing['id']}")

        conn.execute(
            text(
                """
                INSERT INTO leads
                  (id, customer_id, account_id, interaction_id, product_id, owner_user_id, team_id,
                   stage, source, sentiment_at_capture, sentiment_score, estimated_value,
                   offer_amount, offer_roi, priority, captured_at, transcript_snippet)
                VALUES
                  (:id, :customer_id, :account_id, :interaction_id, :product_id, :owner_user_id, :team_id,
                   :stage, :source, :sentiment_at_capture, :sentiment_score, :estimated_value,
                   :offer_amount, :offer_roi, :priority, now(), :transcript_snippet)
                """
            ),
            {
                "id": lead_id,
                "customer_id": customer_id,
                "account_id": payload.get("accountId") or _first_account_id(conn, customer_id),
                "interaction_id": payload.get("interactionId"),
                "product_id": product_id,
                # A bot has no user identity; falling back to the API actor made
                # every bot-captured lead look like it was raised by whichever
                # service account happened to be configured.
                "owner_user_id": payload.get("ownerUserId"),
                "team_id": _route_team_id(conn, product_id, payload.get("teamId")),
                "stage": payload.get("stage") or "interested",
                "source": payload.get("source") or "agent",
                "sentiment_at_capture": payload.get("sentimentAtCapture") or "neutral",
                "sentiment_score": payload.get("sentimentScore"),
                # estimated_value drives every money figure on the board. A NULL
                # here rendered as ₹NaN column subtotals and crashed the lead
                # card outright, so it falls back to the offer amount and then to
                # the product's ticket floor rather than staying empty.
                "estimated_value": (
                    payload.get("estimatedValue")
                    if payload.get("estimatedValue") is not None
                    else payload.get("offerAmount")
                    if payload.get("offerAmount") is not None
                    else product.get("ticket_min")
                ),
                "offer_amount": payload.get("offerAmount"),
                "offer_roi": payload.get("offerRoi") or product.get("roi"),
                "priority": payload.get("priority") or "normal",
                "transcript_snippet": payload.get("transcriptSnippet"),
            },
        )
        # Phase 2-lite: persist evaluated eligibility (honest unknown for bureau/KYC).
        # Savepoint: a capture failure must not abort the lead write + trailing activity.
        try:
            import capture

            with conn.begin_nested():
                flags = payload.get("eligibilityFlags")
                if not isinstance(flags, list):
                    flags = capture.evaluate_product_eligibility(
                        conn,
                        customer_id=customer_id,
                        product_id=product_id,
                        channel=payload.get("channel"),
                    )
                capture.insert_lead_eligibility(conn, lead_id=lead_id, flags=flags)
                if payload.get("interactionId"):
                    # A captured lead genuinely IS a presented offer, so the
                    # flag belongs here. What it must NOT be tied to is a bare
                    # eligibility probe — see voice/tools.py.
                    capture.mark_upsell_presented(conn, payload.get("interactionId"))
                    capture.touch_primary_intent(conn, payload.get("interactionId"), "upsell_opportunity")
        except Exception:
            logger.exception("lead eligibility capture failed for %s", lead_id)
        # The offer funnel's numerator. This lives here, in the one function
        # every capture path goes through, rather than in the bot tool that
        # used to own it: a lead captured from the UI — including the "Capture
        # lead" button on a decision the engine itself recommended — emitted
        # only `lead_created`, which nothing counts. The funnel's denominator
        # (close_probe_presented) came from the call and its numerator came
        # from one caller of three, so close-probe conversion was structurally
        # understated and no arithmetic on it meant anything.
        #
        # Its own savepoint: an eligibility failure above must not swallow the
        # funnel event, and a funnel-event failure must not lose the lead.
        try:
            import capture

            with conn.begin_nested():
                bot_id = payload.get("actorBotId")
                capture.record_lead_captured(
                    conn,
                    interaction_id=payload.get("interactionId"),
                    lead_id=lead_id,
                    product_id=product_id,
                    actor_bot_id=bot_id,
                    actor_user_id=None if bot_id else _actor_user_id(),
                )
            if emitted is not None:
                emitted.append("lead_captured")
        except Exception:
            logger.exception("lead_captured event failed for %s", lead_id)
        _activity(conn, "lead", lead_id, "lead_created", "Lead created", None, customer_id)
        decision_id = payload.get("decisionId")
        if decision_id:
            try:
                conn.execute(
                    text(
                        """
                        UPDATE offer_decisions
                        SET lead_id = :lead_id,
                            response = COALESCE(response, 'interested'),
                            responded_at = COALESCE(responded_at, now()),
                            presented = true,
                            presented_at = COALESCE(presented_at, now())
                        WHERE id = :id AND tenant_id = :tenant
                        """
                    ),
                    {"id": decision_id, "lead_id": lead_id, "tenant": _tenant()},
                )
                # W12: the same label into the absorbed log. This is the third
                # writer of an offer response and the one most easily missed --
                # it is not in `agent_core/reco/` at all.
                from agent_core.reco import decisions as reco_decisions

                reco_decisions.mirror_update(
                    conn,
                    "lead_id = :lead_id,"
                    " offer_response = COALESCE(offer_response, 'interested'),"
                    " responded_at = COALESCE(responded_at, now()),"
                    " presented = true,"
                    " presented_at = COALESCE(presented_at, now())",
                    {"id": decision_id, "lead_id": lead_id},
                )
            except Exception:
                logger.exception("attach_lead failed for decision %s", decision_id)
        response = _lead_by_id(conn, lead_id)
        _store_idempotent_response(conn, idempotency_key, endpoint, response)
        return response

# A lead's stage is a state machine, not a free-text column. Without this any
# stage could be written over any other — including straight from 'interested'
# to 'won' with no amount, or back out of a closed stage silently.
_LEAD_STAGE_TRANSITIONS: dict[str, frozenset[str]] = {
    "interested": frozenset({"contacted", "qualified", "won", "lost"}),
    "contacted": frozenset({"interested", "qualified", "won", "lost"}),
    "qualified": frozenset({"interested", "contacted", "won", "lost"}),
    # Closed stages reopen only deliberately: won↔lost corrects a mis-click,
    # and either can be pulled back into the pipeline for re-engagement.
    "won": frozenset({"lost", "interested"}),
    "lost": frozenset({"won", "interested"}),
}

_CLOSED_LEAD_STAGES = frozenset({"won", "lost"})

def offer_decision_exists(decision_id: str) -> bool:
    """Whether this tenant has an offer decision with that id.

    Tenant-scoped, so an id guessed or leaked from another tenant reads as
    absent rather than as labellable. The route above returns 404 on False:
    without it a caller could POST a response for an hour and silently label
    nothing, which is exactly the failure mode that left `offer_decisions` with
    zero responses in the first place.
    """
    _mod = _db()
    _tenant = _mod._tenant
    engine = _mod.engine
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    "SELECT 1 FROM offer_decisions"
                    " WHERE id = :id AND tenant_id = :tenant"
                ),
                {"id": decision_id, "tenant": _tenant()},
            ).first()
        )

def patch_lead(lead_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    _activity = _mod._activity
    _assert_tenant_owns = _mod._assert_tenant_owns
    _one = _mod._one
    engine = _mod.engine
    logger = _mod.logger
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "leads", lead_id)
        row = _one(
            conn.execute(
                text(
                    "SELECT customer_id, product_id, stage, estimated_value, offer_amount"
                    " FROM leads WHERE id = :id"
                ),
                {"id": lead_id},
            )
        )
        if row is None:
            raise KeyError("lead_not_found")

        current_stage = row["stage"]
        next_stage = payload.get("stage")
        updates: list[str] = []
        params: dict[str, Any] = {"id": lead_id}
        events: list[tuple[str, str, str | None]] = []  # (kind, label, note)

        if next_stage and next_stage != current_stage:
            allowed = _LEAD_STAGE_TRANSITIONS.get(current_stage, frozenset())
            if next_stage not in allowed:
                raise ValueError(f"invalid_stage_transition:{current_stage}->{next_stage}")

            if next_stage == "lost" and not (payload.get("lossReason") or "").strip():
                # A loss with no reason is a data point that teaches nobody
                # anything, and it is what the loss-reason breakdown reports on.
                raise ValueError("loss_reason_required")

            updates.append("stage = :stage")
            params["stage"] = next_stage

            if next_stage in _CLOSED_LEAD_STAGES:
                updates.append("closed_at = now()")
                if next_stage == "won" and payload.get("wonAmount") is None:
                    # Fall back to the pipeline value we have been reporting all
                    # along rather than closing a win worth NULL.
                    fallback = row["estimated_value"] or row["offer_amount"]
                    if fallback is not None:
                        updates.append("won_amount = :won_amount_default")
                        params["won_amount_default"] = fallback
            else:
                # Reopening: the close date is no longer true.
                updates.append("closed_at = NULL")

            events.append(
                (
                    "lead_won" if next_stage == "won" else "lead_lost" if next_stage == "lost" else "lead_stage_moved",
                    f"Lead moved to {next_stage}",
                    payload.get("lossReason") if next_stage == "lost" else next_stage,
                )
            )

        # Explicit-None means "clear this field". `is not None` made lossReason
        # and wonAmount permanently sticky once set.
        clearable = {"lossReason": "loss_reason", "wonAmount": "won_amount"}
        settable = {
            "productId": "product_id",
            "ownerUserId": "owner_user_id",
            "teamId": "team_id",
            "offerAmount": "offer_amount",
            "offerRoi": "offer_roi",
        }
        for key, column in {**settable, **clearable}.items():
            if key not in payload:
                continue
            value = payload[key]
            if value is None and key not in clearable:
                continue
            updates.append(f"{column} = :{column}")
            params[column] = value

        product_changed = bool(payload.get("productId")) and payload["productId"] != row["product_id"]
        if product_changed:
            product = _one(
                conn.execute(
                    text("SELECT id FROM products WHERE id = :id"), {"id": payload["productId"]}
                )
            )
            if product is None:
                raise ValueError("product_not_found")
            events.append(("lead_offer_edited", "Offer product changed", payload["productId"]))

        if payload.get("ownerUserId"):
            events.append(("lead_assigned", "Lead reassigned", payload["ownerUserId"]))
        if payload.get("teamId"):
            events.append(("lead_team_changed", "Lead routed to another team", payload["teamId"]))
        if payload.get("offerAmount") is not None and not product_changed:
            events.append(("lead_offer_edited", "Offer amount updated", str(payload["offerAmount"])))

        if updates:
            conn.execute(text(f"UPDATE leads SET {', '.join(updates)} WHERE id = :id"), params)

        # Switching the product invalidates every stored eligibility flag: they
        # describe the OLD product. Leaving them made the drawer show a green
        # "all checks passed" for a product that was never evaluated.
        if product_changed:
            try:
                import capture

                with conn.begin_nested():
                    flags = capture.evaluate_product_eligibility(
                        conn,
                        customer_id=row["customer_id"],
                        product_id=payload["productId"],
                        channel=payload.get("channel"),
                    )
                    capture.insert_lead_eligibility(conn, lead_id=lead_id, flags=flags)
            except Exception:
                logger.exception("lead eligibility re-evaluation failed for %s", lead_id)

        if not events:
            events.append(("lead_updated", "Lead updated", None))
        for kind, label, note in events:
            _activity(conn, "lead", lead_id, kind, label, note, row["customer_id"])
        return _lead_by_id(conn, lead_id)

def revalidate_lead_eligibility(lead_id: str, channel: str | None = None) -> dict[str, Any]:
    """Re-evaluate a lead's eligibility against today's facts.

    Eligibility was evaluated once, at capture, and never again — so a customer
    who opted out afterwards kept an actionable lead with a green badge on it.
    Called by the nightly sweep and by the drawer's refresh action.
    """
    _mod = _db()
    _activity = _mod._activity
    _one = _mod._one
    engine = _mod.engine
    import capture

    with engine.begin() as conn:
        row = _one(
            conn.execute(
                text("SELECT customer_id, product_id, stage FROM leads WHERE id = :id"),
                {"id": lead_id},
            )
        )
        if row is None:
            raise KeyError("lead_not_found")
        if not row["product_id"]:
            raise ValueError("lead_has_no_product")

        flags = capture.evaluate_product_eligibility(
            conn,
            customer_id=row["customer_id"],
            product_id=row["product_id"],
            channel=channel,
        )
        capture.insert_lead_eligibility(conn, lead_id=lead_id, flags=flags)
        blocked = capture.eligibility_blocks_capture(flags)
        _activity(
            conn,
            "lead",
            lead_id,
            "lead_eligibility_revalidated",
            "Eligibility re-checked" + (f" — blocked: {blocked}" if blocked else " — still eligible"),
            blocked,
            row["customer_id"],
        )
        return {"leadId": lead_id, "eligible": blocked is None, "blockReason": blocked, "flags": flags}

def revalidate_open_leads(limit: int = 500) -> dict[str, Any]:
    """Nightly sweep over open leads. Returns a compact report."""
    _mod = _db()
    _rows = _mod._rows
    engine = _mod.engine
    logger = _mod.logger
    with engine.connect() as conn:
        ids = [
            r["id"]
            for r in _rows(
                conn.execute(
                    text(
                        "SELECT id FROM leads WHERE stage = ANY(:stages)"
                        " AND product_id IS NOT NULL ORDER BY captured_at DESC NULLS LAST LIMIT :lim"
                    ),
                    {"stages": list(OPEN_LEAD_STAGES), "lim": max(1, int(limit))},
                )
            )
        ]
    checked = 0
    blocked: list[str] = []
    reasons: dict[str, str] = {}
    for lead_id in ids:
        try:
            result = revalidate_lead_eligibility(lead_id)
        except Exception:
            logger.exception("revalidate failed for %s", lead_id)
            continue
        checked += 1
        if not result["eligible"]:
            blocked.append(lead_id)
            # Carry the reason, not just the id. On a collections book most
            # cross-sell leads are blocked by delinquency and always were —
            # "13 of 14 leads no longer eligible" reads like an incident until
            # you learn the reason is "worst account DPD is 74 (over 30)", at
            # which point it reads like the policy working.
            reasons[lead_id] = str(result.get("blockReason") or "unspecified")
    return {
        "checked": checked,
        "blocked": blocked,
        "blockedCount": len(blocked),
        "reasons": reasons,
    }

def sweep_due_followups(limit: int = 500) -> dict[str, Any]:
    """Escalate lead follow-ups whose moment has passed.

    Nothing acted on a due follow-up. An agent scheduled a callback for Tuesday
    at 11:00, Tuesday came and went, and the row sat at ``normal`` priority
    among every other open item — the entire pipeline was a passive record that
    depended on a human noticing. This is the smallest honest fix: the system
    now notices.

    It deliberately does **not** contact anyone. Sending on a customer's behalf
    is a contact-policy decision with consent, calling hours and frequency caps
    attached to it, and a background sweep is the wrong place to make one
    silently. What it does is raise the work where a human will see it.

    Idempotent by construction: the only rows it touches are those not already
    at ``high``, so a second pass over the same follow-up is a no-op and no
    "already escalated" bookkeeping column is needed.
    """
    _mod = _db()
    _activity = _mod._activity
    _rows = _mod._rows
    engine = _mod.engine
    escalated: list[dict[str, Any]] = []
    with engine.begin() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT f.id, f.lead_id, f.customer_id, f.due_at, f.channel
                    FROM followups f
                    JOIN leads l ON l.id = f.lead_id
                    WHERE f.status IN ('open', 'in_progress')
                      AND f.priority <> 'high'
                      AND f.due_at <= now()
                      AND l.stage = ANY(:stages)
                    ORDER BY f.due_at
                    LIMIT :lim
                    FOR UPDATE OF f SKIP LOCKED
                    """
                ),
                {"stages": list(OPEN_LEAD_STAGES), "lim": max(1, int(limit))},
            )
        )
        for row in rows:
            conn.execute(
                text("UPDATE followups SET priority = 'high', updated_at = now() WHERE id = :id"),
                {"id": row["id"]},
            )
            # The lead carries the priority the board sorts and colours by, so
            # escalating only the follow-up would raise the work in the queue
            # and leave it looking routine on the pipeline.
            conn.execute(
                text(
                    "UPDATE leads SET priority = 'high', updated_at = now()"
                    " WHERE id = :id AND priority IN ('low', 'normal')"
                ),
                {"id": row["lead_id"]},
            )
            _activity(
                conn,
                "lead",
                row["lead_id"],
                "lead_followup_overdue",
                "Follow-up overdue",
                # _rows already serialises timestamps to ISO strings — do not
                # reach for strftime here.
                f"{row['channel']} follow-up was due {row['due_at']}",
                row["customer_id"],
            )
            escalated.append({"followupId": row["id"], "leadId": row["lead_id"]})
    return {"escalated": len(escalated), "leads": [e["leadId"] for e in escalated]}

def _lead_followup_channel(channel: str | None) -> str:
    if channel in {"voice", "whatsapp", "email", "sms"}:
        return channel
    return "voice"

def _parse_followup_due(scheduled_at: Any) -> datetime:
    """Resolve the requested slot to an aware UTC instant.

    Parsed rather than passed through as a string because the contact-policy
    check needs an actual moment to convert into the customer's local time —
    "is 03:00 inside the calling window" is not a question you can ask of text.
    A missing or unparseable value means now, which is what the previous
    ``or datetime.now()`` fallback meant too.
    """
    if isinstance(scheduled_at, datetime):
        parsed = scheduled_at
    else:
        raw = str(scheduled_at or "").strip()
        if not raw:
            return datetime.now(timezone.utc)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

def add_lead_followup(lead_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    _activity = _mod._activity
    _actor_user_id = _mod._actor_user_id
    _assert_tenant_owns = _mod._assert_tenant_owns
    _id = _mod._id
    _one = _mod._one
    engine = _mod.engine
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "leads", lead_id)
        row = _one(conn.execute(text("SELECT customer_id, owner_user_id FROM leads WHERE id = :id"), {"id": lead_id}))
        if row is None:
            raise KeyError("lead_not_found")
        followup_id = _id("FU")
        channel = _lead_followup_channel(payload.get("channel"))
        due_at = _parse_followup_due(payload.get("scheduledAt"))

        # The sales side used to book touches the collections side would never
        # have been allowed to make. Nothing here consulted consent, DND or the
        # RBI 08:00–19:00 calling window, so a voice follow-up could be diaried
        # for 03:00 on an opted-out customer and the first person to find out
        # was the rep who dialled it.
        import contact_policy

        blocked = contact_policy.blocks_scheduling(
            conn, customer_id=row["customer_id"], channel=channel, at=due_at
        )
        if blocked:
            raise ValueError(f"contact_policy:{blocked}")

        conn.execute(
            text(
                """
                INSERT INTO followups (id, lead_id, customer_id, assignee_user_id, status, priority, due_at, note, channel)
                VALUES (:id, :lead_id, :customer_id, :assignee_user_id, 'open', 'normal', :due_at, :note, :channel)
                """
            ),
            {
                "id": followup_id,
                "lead_id": lead_id,
                "customer_id": row["customer_id"],
                "assignee_user_id": row["owner_user_id"] or _actor_user_id(),
                "due_at": due_at,
                "note": payload.get("note") or "Lead follow-up",
                "channel": channel,
            },
        )
        _activity(conn, "lead", lead_id, "lead_followup_created", "Lead follow-up scheduled", None, row["customer_id"])
        return {"id": followup_id, "status": "open"}

def patch_followup(followup_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    _activity = _mod._activity
    _one = _mod._one
    engine = _mod.engine
    with engine.begin() as conn:
        row = _one(conn.execute(text("SELECT customer_id, lead_id, promise_id FROM followups WHERE id = :id"), {"id": followup_id}))
        if row is None:
            raise KeyError("followup_not_found")
        if payload.get("status"):
            conn.execute(text("UPDATE followups SET status = :status WHERE id = :id"), {"id": followup_id, "status": payload["status"]})
        entity_type = "lead" if row["lead_id"] else "promise"
        entity_id = row["lead_id"] or row["promise_id"] or followup_id
        _activity(conn, entity_type, entity_id, "followup_updated", "Follow-up updated", payload.get("status"), row["customer_id"])
        return {"id": followup_id, "status": payload.get("status")}

