"""Conversation & bot analytics accessors.

Peeled from ``db.py`` (WP-036 peel 6). Call sites stay ``db.*`` via a
bottom-of-file re-export. Reach the engine through :func:`_db`, never
``from db_core import engine``: the ``db_tx`` fixture wraps ``db.engine``,
and a name bound from ``db_core`` bypasses that proxy.
"""

from __future__ import annotations

from typing import Any
from dataclasses import dataclass, field

from sqlalchemy import text
from db_core import _one, _rows, _tenant


def _db():
    """The ``db`` module object, resolved at call time.

    Carved modules must use ``_db().engine``, never ``from db_core import
    engine``. See ``db_core._db``.
    """
    import db as d

    return d


# ---------------------------------------------------------------------------
# Bot Analytics — live aggregates from interactions (+ children).
# Do NOT read intent_aggregates / analytics_daily / escalation_reasons stubs.
# ---------------------------------------------------------------------------

_BOT_ANALYTICS_RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90}

# The unanswered-questions table used to be hand-seeded at ~10 rows, so this
# read was unbounded. Runtime gap capture makes it grow with traffic, and the
# screen only renders a top-N table.
_BOT_ANALYTICS_GAP_LIMIT = 50

_BOT_ANALYTICS_CHANNELS = frozenset({"voice", "whatsapp", "sms"})

_HANDOFF_REASON_LABELS = {
    "sentiment_drop": "Sentiment drop (negative)",
    "verification_failed": "Verification failed",
    "compliance": "Compliance flag",
    "customer_requested": "User asked for human",
    "hardship": "Hardship / sensitive",
    "dispute": "Sensitive topic (dispute/legal)",
    "high_value": "High-value account",
    "routing_rule": "Routing rule / queue",
}

_INTENT_LABELS = {
    "balance": "Balance / Dues query",
    "emi": "EMI schedule",
    "payment-confirm": "Payment confirmation",
    "statement": "Statement request",
    "late-fee": "Late fee / waiver",
    "dispute": "Dispute raise",
    "callback": "Callback / reschedule",
    "topup": "Top-up / upsell interest",
    "dnd": "DND / opt-out",
    "language": "Language switch",
    "escalate-human": "Ask for human",
    "other": "Other / unrecognised",
    "upi": "UPI payment",
    "PTP": "Promise to pay",
    "QA-review": "QA review",
    "empathy-coach": "Empathy coach",
}

_TURN_BUCKETS: list[tuple[str, int, int]] = [
    ("1–2", 1, 2),
    ("3–4", 3, 4),
    ("5–7", 5, 7),
    ("8–12", 8, 12),
    ("13+", 13, 99),
]

# Escalated = handed to a *human*. ``interaction_handoffs`` also carries
# specialist hops (``to_kind='bot'``, reason ``specialist_route``), which are the
# fleet routing itself and not a failure to contain. Without the ``to_kind``
# filter the first hop would inflate every escalation and containment figure a
# grievance MIS report is built on.
_ESCALATED_PRED = """EXISTS (
  SELECT 1 FROM interaction_handoffs h
   WHERE h.interaction_id = i.id AND h.to_kind = 'human'
)"""

# Abandoned = explicit status or contact-failure dispositions (seed has no status='abandoned').
_ABANDONED_PRED = """(
  i.status = 'abandoned'
  OR lower(coalesce(i.disposition, '')) ~ '(no answer|voicemail|dnd|abandon|not contacted)'
)"""

_RESOLVED_DISP_PRED = """(
  lower(coalesce(i.disposition, '')) ~ '(resolved|payment made|ptp)'
)"""


#: Voice Studio stamps the published version it ran on every call it handles.
_VOICE_STUDIO_VERSION = "(i.source_payload -> 'voiceStudio' ->> 'versionNumber')"

#: A deflected session is one the customer did not come back about within this.
_REPEAT_CONTACT_DAYS = 7


def _bot_analytics_window(
    range_key: str,
    channel: str,
    bot_id: str | None = None,
    version: str | None = None,
) -> tuple[int, str, dict[str, Any], str]:
    """(days, where_sql, params, filter_sql).

    ``filter_sql`` is the non-time part (" AND ..."), for queries with their own
    time window: the prior-period escalations and the agent picker, which drops
    the agent filters so the picker still lists every agent.
    """
    days = _BOT_ANALYTICS_RANGE_DAYS.get(range_key, 30)
    params: dict[str, Any] = {"days": days}
    filters: list[str] = []
    if channel and channel != "all":
        if channel not in _BOT_ANALYTICS_CHANNELS:
            raise ValueError(f"invalid_channel: {channel}")
        filters.append("i.channel = :channel")
        params["channel"] = channel
    if bot_id:
        filters.append("i.handler_bot_id = :bot_id")
        params["bot_id"] = bot_id
    if version:
        filters.append(f"{_VOICE_STUDIO_VERSION} = :version")
        params["version"] = version
    filter_sql = "".join(f" AND {f}" for f in filters)
    where_sql = "i.started_at >= (now() - make_interval(days => :days))" + filter_sql
    return days, where_sql, params, filter_sql


def _intent_label(intent_id: str) -> str:
    if intent_id in _INTENT_LABELS:
        return _INTENT_LABELS[intent_id]
    return intent_id.replace("-", " ").replace("_", " ").strip().title() or "Other / unrecognised"


def _suggested_fix_screen(raw: str | None) -> str:
    v = (raw or "kb").strip().lower()
    if v in {"prompt"}:
        return "prompt"
    if v in {"both"}:
        return "both"
    # faq / kb / doc / anything else → kb work
    return "kb"


def _trend_delta(current: int, prior: int) -> float:
    if prior <= 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - prior) / prior) * 100.0, 1)


@dataclass
class BotAnalyticsBuild:
    """One analytics build: the window, the rows ``_bot_analytics_reads`` fetches in
    one connection, and what ``_bot_analytics_shape`` makes of them. The bodies
    are what ``bot_analytics`` was; ``tests/snapshots/reader_shapes.json`` pins
    the key tree.
    """

    _one: Any
    _rows: Any
    _tenant: Any
    days: int
    engine: Any
    params: dict[str, Any]
    where_sql: str
    filter_sql: str = ""
    by_card_rows: list[dict[str, Any]] = field(default_factory=list)
    daily_rows: list[dict[str, Any]] = field(default_factory=list)
    esc_current: dict[str, int] = field(default_factory=dict)
    esc_prior: dict[str, int] = field(default_factory=dict)
    funnel: dict[str, Any] = field(default_factory=dict)
    intent_rows: list[dict[str, Any]] = field(default_factory=list)
    skill_rows: list[dict[str, Any]] = field(default_factory=list)
    turn_rows: list[dict[str, Any]] = field(default_factory=list)
    unanswered_rows: list[dict[str, Any]] = field(default_factory=list)
    summary_row: dict[str, Any] = field(default_factory=dict)
    lift_row: dict[str, Any] = field(default_factory=dict)
    agent_rows: list[dict[str, Any]] = field(default_factory=list)


def _bot_analytics_reads(st: BotAnalyticsBuild) -> None:
    """Every query the screen needs, in one connection: daily volume, intents,
    escalation reasons for both windows, unanswered questions, turn counts,
    per-card and per-skill rows, and the funnel."""
    _one = st._one
    _rows = st._rows
    _tenant = st._tenant
    days = st.days
    engine = st.engine
    params = st.params
    where_sql = st.where_sql

    with engine.connect() as conn:
        daily_rows = _rows(
            conn.execute(
                text(
                    f"""
                    WITH base AS (
                      SELECT
                        i.id,
                        (i.started_at AT TIME ZONE 'UTC')::date AS d,
                        i.handler_kind,
                        i.query_resolved,
                        i.latency_ms,
                        i.avg_sentiment,
                        coalesce(i.upsell_presented, false) AS upsell_presented,
                        coalesce(i.ptp_captured, false) AS ptp_captured,
                        {_ESCALATED_PRED} AS escalated,
                        {_ABANDONED_PRED} AS abandoned,
                        (
                          SELECT count(*)::int
                          FROM interaction_transcript t
                          WHERE t.interaction_id = i.id
                        ) AS turns
                      FROM interactions i
                      WHERE {where_sql}
                    )
                    SELECT
                      to_char(d, 'YYYY-MM-DD') AS date,
                      count(*)::int AS sessions,
                      count(*) FILTER (
                        WHERE handler_kind = 'bot' AND query_resolved
                      )::int AS contained,
                      count(*) FILTER (WHERE escalated)::int AS escalated,
                      count(*) FILTER (WHERE abandoned)::int AS abandoned,
                      count(*) FILTER (WHERE upsell_presented)::int AS upsell_presented,
                      count(*) FILTER (WHERE ptp_captured)::int AS ptp_captured,
                      count(*) FILTER (WHERE handler_kind = 'bot')::int AS bot_sessions,
                      count(*) FILTER (
                        WHERE handler_kind = 'bot' AND NOT escalated
                      )::int AS bot_contained,
                      coalesce(avg(turns), 0)::float AS avg_turns,
                      coalesce(
                        percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms),
                        0
                      )::float AS latency_p50,
                      coalesce(
                        percentile_cont(0.9) WITHIN GROUP (ORDER BY latency_ms),
                        0
                      )::float AS latency_p90,
                      coalesce(
                        percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms),
                        0
                      )::float AS latency_p99,
                      coalesce(avg(avg_sentiment), 0)::float AS sentiment
                    FROM base
                    GROUP BY d
                    ORDER BY d
                    """
                ),
                params,
            )
        )

        intent_rows = _rows(
            conn.execute(
                text(
                    f"""
                    WITH base AS (
                      SELECT
                        i.id,
                        coalesce(nullif(trim(i.primary_intent), ''), 'other') AS intent_id,
                        i.handler_kind,
                        i.query_resolved,
                        i.latency_ms,
                        i.sentiment_label,
                        {_ESCALATED_PRED} AS escalated,
                        {_ABANDONED_PRED} AS abandoned,
                        (
                          SELECT count(*)::int
                          FROM interaction_transcript t
                          WHERE t.interaction_id = i.id
                        ) AS turns
                      FROM interactions i
                      WHERE {where_sql}
                    )
                    SELECT
                      intent_id,
                      count(*)::int AS sessions,
                      count(*) FILTER (
                        WHERE handler_kind = 'bot' AND query_resolved
                      )::int AS contained,
                      count(*) FILTER (WHERE escalated)::int AS escalated,
                      count(*) FILTER (WHERE abandoned)::int AS abandoned,
                      coalesce(avg(turns), 0)::float AS avg_turns,
                      coalesce(avg(latency_ms), 0)::float AS avg_latency_ms,
                      count(*) FILTER (WHERE sentiment_label = 'positive')::int AS positive,
                      count(*) FILTER (
                        WHERE sentiment_label = 'neutral' OR sentiment_label IS NULL
                      )::int AS neutral,
                      count(*) FILTER (WHERE sentiment_label = 'negative')::int AS negative
                    FROM base
                    GROUP BY intent_id
                    ORDER BY sessions DESC, intent_id
                    """
                ),
                params,
            )
        )

        esc_current = {
            r["reason"]: int(r["count"])
            for r in _rows(
                conn.execute(
                    text(
                        f"""
                        SELECT h.reason, count(*)::int AS count
                        FROM interaction_handoffs h
                        JOIN interactions i ON i.id = h.interaction_id
                        WHERE {where_sql} AND h.to_kind = 'human'
                        GROUP BY h.reason
                        """
                    ),
                    params,
                )
            )
        }
        prior_params = {**params, "prior_days": days * 2}
        esc_prior = {
            r["reason"]: int(r["count"])
            for r in _rows(
                conn.execute(
                    text(
                        f"""
                        SELECT h.reason, count(*)::int AS count
                        FROM interaction_handoffs h
                        JOIN interactions i ON i.id = h.interaction_id
                        WHERE i.started_at >= (now() - make_interval(days => :prior_days))
                          AND i.started_at < (now() - make_interval(days => :days))
                          AND h.to_kind = 'human'
                          {st.filter_sql}
                        GROUP BY h.reason
                        """
                    ),
                    prior_params,
                )
            )
        }

        unanswered_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT
                      uq.id,
                      uq.question,
                      uq.hit_count,
                      uq.last_seen_at,
                      coalesce(uq.top_intent, 'other') AS top_intent,
                      uq.suggested_fix_type,
                      EXISTS (
                        SELECT 1
                        FROM analytics_kb_gap_links g
                        WHERE g.unanswered_question_id = uq.id
                          AND g.kb_document_id IS NOT NULL
                      ) AS has_kb_doc
                    FROM unanswered_questions uq
                    WHERE uq.tenant_id = :tenant_id
                    ORDER BY uq.hit_count DESC, uq.id
                    LIMIT :gap_lim
                    """
                ),
                {"tenant_id": _tenant(), "gap_lim": _BOT_ANALYTICS_GAP_LIMIT},
            )
        )

        turn_rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT
                      (
                        SELECT count(*)::int
                        FROM interaction_transcript t
                        WHERE t.interaction_id = i.id
                      ) AS turns
                    FROM interactions i
                    WHERE {where_sql}
                    """
                ),
                params,
            )
        )

        by_card_rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT
                      coalesce(nullif(trim(i.handler_bot_id), ''), 'unknown') AS bot_id,
                      count(*)::int AS sessions,
                      count(*) FILTER (
                        WHERE i.handler_kind = 'bot' AND i.query_resolved
                      )::int AS contained,
                      count(*) FILTER (WHERE {_ESCALATED_PRED})::int AS escalated,
                      coalesce(
                        percentile_cont(0.99) WITHIN GROUP (ORDER BY i.latency_ms),
                        0
                      )::float AS latency_p99
                    FROM interactions i
                    WHERE {where_sql}
                    GROUP BY 1
                    ORDER BY sessions DESC, bot_id
                    """
                ),
                params,
            )
        )

        skill_rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT
                      coalesce(nullif(trim(c.skill_id), ''), 'none') AS skill_id,
                      count(*)::int AS activations
                    FROM bot_tool_calls c
                    JOIN interactions i ON i.id = c.interaction_id
                    WHERE {where_sql}
                      AND c.skill_id IS NOT NULL
                      AND trim(c.skill_id) <> ''
                    GROUP BY 1
                    ORDER BY activations DESC, skill_id
                    LIMIT 24
                    """
                ),
                params,
            )
        )

        # Funnel stages are cumulative subsets (landed ⊇ verified ⊇ intent ⊇
        # answered ⊇ confirmed), so counts decrease monotonically. Each stage
        # ANDs all prior predicates; "answered" is the union of the two resolve
        # signals so "confirmed" (disposition-resolved) is always a subset of it.
        _v_pred = (
            "EXISTS (SELECT 1 FROM identity_verifications v "
            "WHERE v.interaction_id = i.id AND v.status = 'verified')"
        )
        _intent_pred = "i.primary_intent IS NOT NULL AND trim(i.primary_intent) <> ''"
        _answered_pred = f"(i.query_resolved OR {_RESOLVED_DISP_PRED})"
        funnel = _one(
            conn.execute(
                text(
                    f"""
                    SELECT
                      count(*)::int AS landed,
                      count(*) FILTER (WHERE {_v_pred})::int AS verified,
                      count(*) FILTER (
                        WHERE {_v_pred} AND {_intent_pred}
                      )::int AS intent_captured,
                      count(*) FILTER (
                        WHERE {_v_pred} AND {_intent_pred} AND {_answered_pred}
                      )::int AS answered,
                      count(*) FILTER (
                        WHERE {_v_pred} AND {_intent_pred} AND {_answered_pred}
                          AND {_RESOLVED_DISP_PRED}
                      )::int AS confirmed
                    FROM interactions i
                    WHERE {where_sql}
                    """
                ),
                params,
            )
        ) or {}

        # The headline figures, over calls rather than averaged across days.
        # Containment: bot sessions never handed to a human. Deflection:
        # inbound bot sessions resolved without a human AND without the
        # customer contacting again within 7 days -- only sessions old enough
        # for that week to have passed count, or the newest calls would read
        # as deflected merely because the customer has not called back yet.
        st.summary_row = _one(
            conn.execute(
                text(
                    f"""
                    WITH base AS (
                      SELECT
                        i.handler_kind,
                        i.direction,
                        i.latency_ms,
                        i.started_at <= now() - make_interval(days => :repeat_days) AS matured,
                        {_ESCALATED_PRED} AS escalated,
                        (i.query_resolved OR {_RESOLVED_DISP_PRED}) AS resolved,
                        EXISTS (
                          SELECT 1 FROM interactions r
                          WHERE r.customer_id = i.customer_id
                            AND r.id <> i.id
                            AND r.direction IS DISTINCT FROM 'outbound'
                            AND r.started_at > i.started_at
                            AND r.started_at <= i.started_at + make_interval(days => :repeat_days)
                        ) AS repeat_contact
                      FROM interactions i
                      WHERE {where_sql}
                    )
                    SELECT
                      count(*) FILTER (WHERE handler_kind = 'bot')::int AS bot_sessions,
                      count(*) FILTER (
                        WHERE handler_kind = 'bot' AND NOT escalated
                      )::int AS bot_contained,
                      count(*) FILTER (
                        WHERE handler_kind = 'bot' AND direction = 'inbound' AND matured
                      )::int AS deflection_eligible,
                      count(*) FILTER (
                        WHERE handler_kind = 'bot' AND direction = 'inbound' AND matured
                          AND resolved AND NOT escalated AND NOT repeat_contact
                      )::int AS deflected,
                      percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)::float
                        AS latency_p50,
                      percentile_cont(0.9) WITHIN GROUP (ORDER BY latency_ms)::float
                        AS latency_p90
                    FROM base
                    """
                ),
                {**params, "repeat_days": _REPEAT_CONTACT_DAYS},
            )
        ) or {}

        # Sentiment lift: per call, the customer's last sentiment minus their
        # first. Per-turn signals (customer turns, in turn order) where the
        # call-intelligence pass produced them, else the call's sentiment
        # timeline (at_sec order). A call needs two points to have a direction.
        st.lift_row = _one(
            conn.execute(
                text(
                    f"""
                    WITH win AS (SELECT i.id FROM interactions i WHERE {where_sql}),
                    turn_points AS (
                      SELECT s.interaction_id AS id, s.score::float AS score,
                             t.turn_index AS ord
                      FROM interaction_turn_signals s
                      JOIN interaction_transcript t ON t.id = s.transcript_turn_id
                      WHERE s.kind = 'sentiment' AND t.speaker = 'customer'
                        AND s.interaction_id IN (SELECT id FROM win)
                    ),
                    points AS (
                      SELECT id, score, ord FROM turn_points
                      UNION ALL
                      SELECT e.interaction_id, e.score::float, e.at_sec
                      FROM interaction_sentiment e
                      WHERE e.interaction_id IN (SELECT id FROM win)
                        AND NOT EXISTS (SELECT 1 FROM turn_points tp WHERE tp.id = e.interaction_id)
                    ),
                    per_call AS (
                      SELECT (array_agg(score ORDER BY ord DESC))[1]
                             - (array_agg(score ORDER BY ord ASC))[1] AS lift
                      FROM points
                      GROUP BY id
                      HAVING count(*) >= 2
                    )
                    SELECT avg(lift)::float AS lift, count(*)::int AS calls FROM per_call
                    """
                ),
                params,
            )
        ) or {}

        # The agent picker: every bot (and Voice Studio version) with calls
        # in the range and channel, whatever agent is currently selected.
        agent_filter = "AND i.channel = :channel" if "channel" in params else ""
        st.agent_rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT i.handler_bot_id AS bot_id,
                           coalesce(b.name, i.handler_bot_id) AS name,
                           array_remove(array_agg(DISTINCT {_VOICE_STUDIO_VERSION}), NULL)
                             AS versions
                    FROM interactions i
                    LEFT JOIN bots b ON b.id = i.handler_bot_id
                    WHERE i.started_at >= (now() - make_interval(days => :days))
                      AND i.handler_bot_id IS NOT NULL
                      {agent_filter}
                    GROUP BY 1, 2
                    ORDER BY 2, 1
                    """
                ),
                {k: v for k, v in params.items() if k not in ("bot_id", "version")},
            )
        )

    st.by_card_rows = by_card_rows
    st.daily_rows = daily_rows
    st.esc_current = esc_current
    st.esc_prior = esc_prior
    st.funnel = funnel
    st.intent_rows = intent_rows
    st.skill_rows = skill_rows
    st.turn_rows = turn_rows
    st.unanswered_rows = unanswered_rows


def _bot_analytics_shape(st: BotAnalyticsBuild) -> dict[str, Any]:
    """The series, the histograms, the funnel stages and the response the screen renders."""
    by_card_rows = st.by_card_rows
    daily_rows = st.daily_rows
    esc_current = st.esc_current
    esc_prior = st.esc_prior
    funnel = st.funnel
    intent_rows = st.intent_rows
    skill_rows = st.skill_rows
    turn_rows = st.turn_rows
    unanswered_rows = st.unanswered_rows

    daily_series = [
        {
            "date": r["date"],
            "sessions": int(r["sessions"] or 0),
            "contained": int(r["contained"] or 0),
            "escalated": int(r["escalated"] or 0),
            "abandoned": int(r["abandoned"] or 0),
            "avgTurns": round(float(r["avg_turns"] or 0), 2),
            "latencyP50": round(float(r["latency_p50"] or 0), 1),
            "latencyP90": round(float(r["latency_p90"] or 0), 1),
            "latencyP99": round(float(r["latency_p99"] or 0), 1),
            "sentiment": round(float(r["sentiment"] or 0), 3),
            "upsellPresented": int(r["upsell_presented"] or 0),
            "ptpCaptured": int(r["ptp_captured"] or 0),
            "botSessions": int(r["bot_sessions"] or 0),
            "botContained": int(r["bot_contained"] or 0),
        }
        for r in daily_rows
    ]

    intent_aggs = [
        {
            "id": r["intent_id"],
            "label": _intent_label(r["intent_id"]),
            "sessions": int(r["sessions"] or 0),
            "contained": int(r["contained"] or 0),
            "escalated": int(r["escalated"] or 0),
            "abandoned": int(r["abandoned"] or 0),
            "avgTurns": round(float(r["avg_turns"] or 0), 2),
            "avgLatencyMs": round(float(r["avg_latency_ms"] or 0), 1),
            "sentiment": {
                "positive": int(r["positive"] or 0),
                "neutral": int(r["neutral"] or 0),
                "negative": int(r["negative"] or 0),
            },
        }
        for r in intent_rows
    ]

    reasons = sorted(set(esc_current) | set(esc_prior), key=lambda k: (-esc_current.get(k, 0), k))
    escalation_reasons = [
        {
            "id": reason,
            "label": _HANDOFF_REASON_LABELS.get(reason, reason.replace("_", " ").title()),
            "count": esc_current.get(reason, 0),
            "trendDelta": _trend_delta(esc_current.get(reason, 0), esc_prior.get(reason, 0)),
        }
        for reason in reasons
        if esc_current.get(reason, 0) > 0 or esc_prior.get(reason, 0) > 0
    ]
    # Prefer current-period reasons first; drop pure-prior zeros already filtered.
    escalation_reasons = [r for r in escalation_reasons if r["count"] > 0]

    unanswered = []
    for r in unanswered_rows:
        last = r["last_seen_at"]
        if hasattr(last, "date"):
            last_seen = last.date().isoformat()
        elif last:
            last_seen = str(last)[:10]
        else:
            last_seen = ""
        unanswered.append(
            {
                "id": r["id"],
                "text": r["question"],
                "hits": int(r["hit_count"] or 0),
                "lastSeen": last_seen,
                "topIntent": r["top_intent"] or "other",
                "hasKbDoc": bool(r["has_kb_doc"]),
                "suggestedFix": _suggested_fix_screen(r["suggested_fix_type"]),
            }
        )

    bucket_counts = {label: 0 for label, _mn, _mx in _TURN_BUCKETS}
    for r in turn_rows:
        turns = int(r["turns"] or 0)
        if turns <= 0:
            continue
        for label, mn, mx in _TURN_BUCKETS:
            if mn <= turns <= mx:
                bucket_counts[label] += 1
                break
    turns_histogram = [
        {"label": label, "min": mn, "max": mx, "count": bucket_counts[label]}
        for label, mn, mx in _TURN_BUCKETS
    ]

    funnel_stages = [
        {"id": "landed", "label": "Session landed", "count": int(funnel.get("landed") or 0)},
        {"id": "verified", "label": "Verified identity", "count": int(funnel.get("verified") or 0)},
        {"id": "intent", "label": "Intent captured", "count": int(funnel.get("intent_captured") or 0)},
        {"id": "answered", "label": "Answer delivered", "count": int(funnel.get("answered") or 0)},
        {"id": "confirmed", "label": "Confirmed resolution", "count": int(funnel.get("confirmed") or 0)},
    ]

    by_card = [
        {
            "botId": r["bot_id"],
            "sessions": int(r["sessions"] or 0),
            "contained": int(r["contained"] or 0),
            "escalated": int(r["escalated"] or 0),
            "containment": round(
                (int(r["contained"] or 0) / int(r["sessions"] or 1)) * 100.0, 1
            )
            if int(r["sessions"] or 0)
            else 0.0,
            "handoffRate": round(
                (int(r["escalated"] or 0) / int(r["sessions"] or 1)) * 100.0, 1
            )
            if int(r["sessions"] or 0)
            else 0.0,
            "latencyP99": round(float(r["latency_p99"] or 0), 1),
            "sloMs": 800,
        }
        for r in by_card_rows
    ]
    skill_histogram = [
        {"skillId": r["skill_id"], "activations": int(r["activations"] or 0)}
        for r in skill_rows
    ]

    return {
        "dailySeries": daily_series,
        "intentAggs": intent_aggs,
        "escalationReasons": escalation_reasons,
        "unansweredQuestions": unanswered,
        "turnsHistogram": turns_histogram,
        "funnelStages": funnel_stages,
        "byCard": by_card,
        "skillHistogram": skill_histogram,
        "summary": _summary(st.summary_row, st.lift_row),
        "agents": [
            {
                "botId": r["bot_id"],
                "name": r["name"],
                "versions": sorted(
                    r["versions"] or [], key=lambda v: (not v.isdigit(), int(v) if v.isdigit() else 0, v)
                ),
            }
            for r in st.agent_rows
        ],
    }


def _pct(part: int, whole: int) -> float | None:
    return round(part / whole * 100.0, 1) if whole else None


def _summary(row: dict[str, Any], lift: dict[str, Any]) -> dict[str, Any]:
    """Headline KPIs; None where there is nothing to measure (the UI shows "—")."""
    bot_sessions = int(row.get("bot_sessions") or 0)
    eligible = int(row.get("deflection_eligible") or 0)
    p50, p90 = row.get("latency_p50"), row.get("latency_p90")
    lift_calls = int(lift.get("calls") or 0)
    return {
        "botSessions": bot_sessions,
        "containment": _pct(int(row.get("bot_contained") or 0), bot_sessions),
        "deflection": _pct(int(row.get("deflected") or 0), eligible),
        "deflectionEligible": eligible,
        "repeatContactDays": _REPEAT_CONTACT_DAYS,
        "latencyP50": round(float(p50), 1) if p50 is not None else None,
        "latencyP90": round(float(p90), 1) if p90 is not None else None,
        "sentimentLift": round(float(lift["lift"]), 3) if lift_calls else None,
        "sentimentLiftCalls": lift_calls,
    }


def bot_analytics(
    range_key: str = "30d",
    channel: str = "all",
    bot_id: str | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Conversation & Bot Analytics — screen shape, aggregated live from interactions.

    ``bot_id`` narrows to one agent (``handler_bot_id``; Voice Studio agents are
    ``voice-studio-{workflowId}``), ``version`` to one Voice Studio published
    version (``source_payload.voiceStudio.versionNumber``).
    """
    if range_key not in _BOT_ANALYTICS_RANGE_DAYS:
        raise ValueError(f"invalid_range: {range_key}")
    days, where_sql, params, filter_sql = _bot_analytics_window(
        range_key, channel, bot_id, version
    )

    engine = _db().engine
    st = BotAnalyticsBuild(
        _one=_one,
        _rows=_rows,
        _tenant=_tenant,
        days=days,
        engine=engine,
        params=params,
        where_sql=where_sql,
        filter_sql=filter_sql,
    )
    _bot_analytics_reads(st)
    return _bot_analytics_shape(st)


