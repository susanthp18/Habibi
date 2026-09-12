"""Handoff queue, session, claim, disclosure and suggestions (WP-036 peel).

Peeled from ``db.py``. Call sites stay ``db.*`` via a bottom-of-file
re-export. Reach the engine through :func:`_db`, never ``from db_core import
engine``: the ``db_tx`` fixture wraps ``db.engine``, and a name bound from
``db_core`` bypasses that proxy.
"""

from __future__ import annotations

import visibility
from datetime import date, datetime, timezone
from schemas import HandoffQueueItem, HandoffQueueResponse, HandoffSessionResponse
from sqlalchemy import text
from typing import Any
from agent_core.clock import utc_now


def _db():
    """The ``db`` module object, resolved at call time."""
    import db as d

    return d


HANDOFF_DISPOSITIONS = [
    "PTP captured",
    "Payment taken",
    "Dispute - under review",
    "Info provided",
    "Callback scheduled",
    "Escalated to supervisor",
    "Unresolved - retry",
]

# Checklist catalog for the hub — disclosure rules, not the full violation taxonomy.
_HANDOFF_DISCLOSURE_RULES = (
    ("rule-recording", "Recording disclosure read"),
    ("rule-identity", "Identity verified"),
    ("rule-mini-miranda", "Mini-Miranda / debt-collection notice"),
    ("rule-payment", "Payment terms / data-use consent"),
)

def _epoch_ms(value: Any) -> int:
    if value is None:
        return int(utc_now().timestamp() * 1000)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)):
        return int(value)
    return int(utc_now().timestamp() * 1000)

def _iso_ts(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)

def _handoff_status(ix_status: str | None, claimed: bool) -> str:
    if ix_status == "completed":
        return "completed"
    if claimed:
        return "active"
    return "pending_claim"

def _actor_team_id(conn: Any) -> str | None:
    _mod = _db()
    _actor_user_id = _mod._actor_user_id
    _one = _mod._one
    row = _one(
        conn.execute(
            text("SELECT team_id FROM users WHERE id = :id"),
            {"id": _actor_user_id()},
        )
    )
    return row["team_id"] if row else None

def _handoff_queue_visible(conn: Any, to_team_id: str | None) -> bool:
    """Whether this unclaimed handoff belongs on the actor's queue."""
    _mod = _db()
    _actor_user_id = _mod._actor_user_id
    _one = _mod._one
    vis = visibility.resolve(_actor_user_id())
    if vis.is_unrestricted:
        return True
    if not to_team_id:
        return True
    actor_team = _actor_team_id(conn)
    if vis.scope == visibility.TEAM:
        supervised = _one(
            conn.execute(
                text(
                    """
                    SELECT 1 FROM teams
                    WHERE id = :tid AND supervisor_user_id = :uid
                    """
                ),
                {"tid": to_team_id, "uid": _actor_user_id()},
            )
        )
        return bool(supervised) or to_team_id == actor_team
    return to_team_id == actor_team

def _handoff_queue_sql_filter() -> str:
    """Bind-parameterised team filter for the unclaimed queue."""
    return """
      AND (
        :vis_all
        OR h.to_team_id IS NULL
        OR h.to_team_id = :actor_team
        OR (:vis_team AND h.to_team_id IN (
              SELECT t.id FROM teams t WHERE t.supervisor_user_id = :vis_actor
            ))
      )
    """

def list_handoff_queue(*, customer_id: str | None = None) -> dict[str, Any]:
    _mod = _db()
    _actor_user_id = _mod._actor_user_id
    _dump = _mod._dump
    _one = _mod._one
    _rows = _mod._rows
    _tenant = _mod._tenant
    engine = _mod.engine
    actor = _actor_user_id()
    vis = visibility.resolve(actor)
    with engine.connect() as conn:
        actor_team = _actor_team_id(conn)
        params: dict[str, Any] = {
            "tenant_id": _tenant(),
            "actor": actor,
            "actor_team": actor_team,
            "vis_all": vis.is_unrestricted,
            "vis_team": vis.scope == visibility.TEAM,
            "vis_actor": actor,
        }
        customer_sql = ""
        if customer_id:
            customer_sql = "AND i.customer_id = :customer_id"
            params["customer_id"] = customer_id
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT
                      i.id AS interaction_id,
                      h.id AS handoff_id,
                      i.customer_id,
                      c.name AS customer_name,
                      COALESCE(i.account_id, '') AS account_id,
                      h.reason,
                      h.queue,
                      COALESCE(c.risk, 'medium') AS risk,
                      h.requested_at,
                      EXTRACT(EPOCH FROM (now() - COALESCE(h.requested_at, h.created_at)))::int AS wait_sec
                    FROM interaction_handoffs h
                    JOIN interactions i ON i.id = h.interaction_id
                    JOIN customers c ON c.id = i.customer_id
                    WHERE i.tenant_id = :tenant_id
                      AND i.status = 'active'
                      AND h.to_user_id IS NULL
                      AND h.accepted_at IS NULL
                      AND h.completed_at IS NULL
                      {customer_sql}
                      {_handoff_queue_sql_filter()}
                    ORDER BY h.requested_at ASC NULLS LAST, h.created_at ASC
                    LIMIT 50
                    """
                ),
                params,
            )
        )
        mine = _one(
            conn.execute(
                text(
                    """
                    SELECT i.id
                    FROM interaction_handoffs h
                    JOIN interactions i ON i.id = h.interaction_id
                    WHERE i.tenant_id = :tenant_id
                      AND i.status = 'active'
                      AND h.completed_at IS NULL
                      AND h.accepted_at IS NOT NULL
                      AND (
                        h.to_user_id = :actor
                        OR i.handler_user_id = :actor
                      )
                    ORDER BY h.accepted_at DESC
                    LIMIT 1
                    """
                ),
                {"tenant_id": _tenant(), "actor": actor},
            )
        )
    items = [
        _dump(
            HandoffQueueItem(
                interactionId=r["interaction_id"],
                handoffId=r["handoff_id"],
                customerId=r["customer_id"],
                customerName=r["customer_name"],
                accountId=r["account_id"] or "",
                reason=r["reason"],
                queue=r["queue"],
                risk=str(r["risk"] or "medium"),
                waitSec=max(0, int(r["wait_sec"] or 0)),
                requestedAt=_iso_ts(r["requested_at"]),
            )
        )
        for r in rows
    ]
    return _dump(
        HandoffQueueResponse.model_validate(
            {"items": items, "activeInteractionId": mine["id"] if mine else None}
        )
    )

def get_active_handoff_session() -> dict[str, Any] | None:
    _mod = _db()
    _actor_user_id = _mod._actor_user_id
    _one = _mod._one
    _tenant = _mod._tenant
    engine = _mod.engine
    actor = _actor_user_id()
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT i.id
                    FROM interaction_handoffs h
                    JOIN interactions i ON i.id = h.interaction_id
                    WHERE i.tenant_id = :tenant_id
                      AND i.status = 'active'
                      AND h.completed_at IS NULL
                      AND h.accepted_at IS NOT NULL
                      AND (
                        h.to_user_id = :actor
                        OR i.handler_user_id = :actor
                      )
                    ORDER BY h.accepted_at DESC
                    LIMIT 1
                    """
                ),
                {"tenant_id": _tenant(), "actor": actor},
            )
        )
    if row is None:
        return None
    return get_handoff_session(row["id"])

def get_handoff_session(interaction_id: str) -> dict[str, Any]:
    _mod = _db()
    _actor_user_id = _mod._actor_user_id
    _assert_tenant_owns = _mod._assert_tenant_owns
    _dump = _mod._dump
    _one = _mod._one
    _rows = _mod._rows
    engine = _mod.engine
    with engine.connect() as conn:
        _assert_tenant_owns(conn, "interactions", interaction_id)
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT
                      i.id,
                      i.customer_id,
                      c.name AS customer_name,
                      i.account_id,
                      i.channel,
                      i.status,
                      i.started_at,
                      i.handler_user_id,
                      i.transferred_from_bot_id,
                      COALESCE(u.name, '') AS handler_name,
                      COALESCE(tb.name, fb.name, '') AS transferred_from,
                      c.risk,
                      c.phone_primary,
                      c.preferred_window,
                      c.dnd,
                      a.product_id,
                      p.name AS product,
                      a.opened_on,
                      a.outstanding AS account_outstanding,
                      h.id AS handoff_id,
                      h.reason,
                      h.to_user_id,
                      h.accepted_at,
                      h.completed_at,
                      h.to_team_id,
                      conv.id AS conversation_id
                    FROM interactions i
                    JOIN customers c ON c.id = i.customer_id
                    LEFT JOIN users u ON u.id = i.handler_user_id
                    LEFT JOIN bots tb ON tb.id = i.transferred_from_bot_id
                    LEFT JOIN bots fb ON fb.id = i.handler_bot_id
                    LEFT JOIN accounts a ON a.id = i.account_id
                    LEFT JOIN products p ON p.id = a.product_id
                    LEFT JOIN LATERAL (
                      SELECT id, reason, to_user_id, accepted_at, completed_at, to_team_id
                      FROM interaction_handoffs
                      WHERE interaction_id = i.id
                      ORDER BY requested_at DESC NULLS LAST, created_at DESC
                      LIMIT 1
                    ) h ON true
                    LEFT JOIN LATERAL (
                      SELECT id FROM conversations
                      WHERE interaction_id = i.id
                      ORDER BY created_at DESC
                      LIMIT 1
                    ) conv ON true
                    WHERE i.id = :id
                    """
                ),
                {"id": interaction_id},
            )
        )
        if row is None or not row.get("handoff_id"):
            raise KeyError("handoff_not_found")

        actor = _actor_user_id()
        claimed = bool(row["accepted_at"] and (row["to_user_id"] or row["handler_user_id"]))
        is_mine = row["to_user_id"] == actor or row["handler_user_id"] == actor
        import authz

        is_supervisor = authz.has_permission(actor, authz.SUPERVISOR_READ)
        if claimed and not is_mine and not is_supervisor:
            raise PermissionError("handoff_not_assigned")
        if not claimed and not _handoff_queue_visible(conn, row.get("to_team_id")) and not is_supervisor:
            raise PermissionError("handoff_not_assigned")

        status = _handoff_status(row["status"], bool(row["accepted_at"] or is_mine))
        claimed_flag = bool(row["accepted_at"] or is_mine)
        monitor = bool(is_supervisor and not is_mine)

        transcript = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, speaker, at_sec AS at, text, sentiment_delta AS "sentimentDelta"
                    FROM interaction_transcript
                    WHERE interaction_id = :interaction_id
                    ORDER BY turn_index
                    """
                ),
                {"interaction_id": interaction_id},
            )
        )
        sentiment_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT score
                    FROM interaction_sentiment
                    WHERE interaction_id = :interaction_id
                    ORDER BY at_sec, created_at
                    """
                ),
                {"interaction_id": interaction_id},
            )
        )
        suggestion_sql = """
                    SELECT id, suggestion_text AS body, source, accepted
                    FROM ai_response_suggestions
                    WHERE interaction_id = :interaction_id
                    ORDER BY created_at
                    """
        suggestion_params: dict[str, Any] = {"interaction_id": interaction_id}
        if row.get("conversation_id"):
            suggestion_sql = """
                    SELECT id, suggestion_text AS body, source, accepted
                    FROM ai_response_suggestions
                    WHERE interaction_id = :interaction_id
                       OR conversation_id = :conversation_id
                    ORDER BY created_at
                    """
            suggestion_params["conversation_id"] = row["conversation_id"]
        suggestions = _rows(
            conn.execute(text(suggestion_sql), suggestion_params)
        )
        alerts = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, kind, severity, reason
                    FROM live_alerts
                    WHERE interaction_id = :interaction_id
                      AND acknowledged_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT 8
                    """
                ),
                {"interaction_id": interaction_id},
            )
        )
        context = _handoff_customer_context(conn, row)
        compliance = _handoff_compliance_items(conn, interaction_id)
        bot_name = row["transferred_from"] or "Bot"
        speakers = {
            "customer": row["customer_name"],
            "agent": "You" if is_mine else (row["handler_name"] or "Agent"),
            "bot": f"Bot · {bot_name}",
            "system": "System",
        }
        channel = row["channel"] or "voice"
        channel_label = channel.replace("_", " ").title()
        reason = row["reason"] or "routing_rule"
        started_at = _epoch_ms(row["started_at"])
        outstanding = float(row["account_outstanding"] or 0)
        context["outstanding"] = outstanding
        context["risk"] = str(row["risk"] or "medium").title()
        context["product"] = row["product"] or context.get("product") or ""

    # The builders assemble dicts; the response model validates them into shape.
    session = HandoffSessionResponse.model_validate(dict(
        interactionId=interaction_id,
        handoffId=row["handoff_id"],
        customerId=row["customer_id"],
        conversationId=row.get("conversation_id"),
        status=status,
        claimed=claimed_flag,
        monitor=monitor,
        activeCall={
            "interactionId": interaction_id,
            "handoffId": row["handoff_id"],
            "customerId": row["customer_id"],
            "conversationId": row.get("conversation_id"),
            "customerName": row["customer_name"],
            "accountId": row["account_id"] or "",
            "phone": row["phone_primary"] or "",
            "channel": channel_label,
            "agentName": "You" if is_mine else (row["handler_name"] or "Unassigned"),
            "transferredFrom": f"Bot · {bot_name}" if bot_name else "",
            "escalationReason": reason.replace("_", " "),
            "startedAt": started_at,
            "status": status,
            "claimed": claimed_flag,
            "risk": str(row["risk"] or "medium"),
            "handlerUserId": row["handler_user_id"],
        },
        customerContext=context,
        transcriptScript=transcript,
        sentimentSeries=_handoff_sentiment_series(sentiment_rows, transcript),
        suggestions=[
            {
                "id": s["id"],
                "title": "Suggested response",
                "body": s["body"],
                "source": s["source"] or "",
                "showAfter": 0,
                "accepted": bool(s["accepted"]),
            }
            for s in suggestions
        ],
        complianceItems=compliance,
        alerts=[
            {
                "id": a["id"],
                "kind": a["kind"],
                "severity": a["severity"] or "medium",
                "reason": a["reason"],
            }
            for a in alerts
        ],
        dispositions=list(HANDOFF_DISPOSITIONS),
        speakers=speakers,
    ))
    return _dump(session)

def _handoff_sentiment_series(
    sentiment_rows: list[dict[str, Any]],
    transcript: list[dict[str, Any]],
) -> list[float]:
    if sentiment_rows:
        return [float(r["score"] or 0) for r in sentiment_rows]
    running = 0.0
    series: list[float] = []
    for turn in transcript:
        delta = turn.get("sentimentDelta")
        if delta is not None:
            running = max(-1.0, min(1.0, running + float(delta)))
            series.append(running)
    return series

def _handoff_customer_context(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    _one = _mod._one
    _rows = _mod._rows
    customer_id = row["customer_id"]
    account_id = row.get("account_id")
    last_promise = _one(
        conn.execute(
            text(
                """
                SELECT amount, promised_at, status
                FROM promises
                WHERE customer_id = :cid
                ORDER BY promised_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                """
            ),
            {"cid": customer_id},
        )
    )
    next_emi = None
    if account_id:
        next_emi = _one(
            conn.execute(
                text(
                    """
                    SELECT amount, due_date, status
                    FROM emi_installments
                    WHERE account_id = :aid
                      AND status IN ('overdue', 'upcoming', 'partial')
                    ORDER BY
                      CASE status WHEN 'overdue' THEN 0 WHEN 'partial' THEN 1 ELSE 2 END,
                      due_date ASC
                    LIMIT 1
                    """
                ),
                {"aid": account_id},
            )
        )
    open_disputes = _one(
        conn.execute(
            text(
                """
                SELECT count(*)::int AS n
                FROM disputes
                WHERE customer_id = :cid
                  AND status IN ('new', 'under_review', 'awaiting_customer')
                """
            ),
            {"cid": customer_id},
        )
    )
    consents = _rows(
        conn.execute(
            text(
                """
                SELECT cc.channel, cc.status
                FROM consent_records cr
                JOIN channel_consents cc ON cc.consent_id = cr.id
                WHERE cr.customer_id = :cid
                """
            ),
            {"cid": customer_id},
        )
    )
    allowed_channels = [
        (c["channel"] or "").replace("_", " ").title()
        for c in consents
        if c["status"] == "opted_in"
    ]
    if not allowed_channels:
        allowed_channels = ["Voice", "WhatsApp"]
    tenure = 0
    opened = row.get("opened_on")
    if isinstance(opened, datetime):
        opened = opened.date()
    if isinstance(opened, date):
        tenure = max(0, (date.today() - opened).days // 30)
    last = None
    if last_promise:
        last = {
            "amount": float(last_promise["amount"] or 0),
            "date": _iso_ts(last_promise["promised_at"]) or "",
            "status": last_promise["status"] or "upcoming",
        }
    emi = None
    if next_emi:
        due = next_emi["due_date"]
        due_d = due.date() if isinstance(due, datetime) else due
        days = 0
        if isinstance(due_d, date):
            days = max(0, (date.today() - due_d).days)
        emi = {
            "amount": float(next_emi["amount"] or 0),
            "dueDate": _iso_ts(due) or "",
            "daysOverdue": days if (next_emi["status"] == "overdue") else 0,
        }
    return {
        "risk": str(row.get("risk") or "medium").title(),
        "outstanding": 0,
        "currency": "₹",
        "lastPromise": last,
        "nextEmi": emi,
        "openDisputes": int((open_disputes or {}).get("n") or 0),
        "dnd": {
            "allowed": not bool(row.get("dnd")),
            "window": row.get("preferred_window") or "",
            "channels": allowed_channels,
        },
        "tenureMonths": tenure,
        "product": row.get("product") or "",
        "offerPolicy": _handoff_offer_policy(conn, row),
        "authorityPolicy": _handoff_authority_policy(conn, row),
        "liveQa": _handoff_live_qa(conn, row),
    }

def _handoff_offer_policy(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    _tenant = _mod._tenant
    logger = _mod.logger
    from agent_core.reco import policy

    try:
        return policy.snapshot(
            conn,
            customer_id=row["customer_id"],
            tenant_id=_tenant(),
            interaction_id=row.get("id"),
        )
    except Exception:
        logger.exception("offer policy snapshot failed for handoff %s", row.get("id"))
        return policy.empty()

def _handoff_authority_policy(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    _tenant = _mod._tenant
    logger = _mod.logger
    from agent_core.authority import policy

    try:
        return policy.snapshot(
            conn,
            customer_id=row["customer_id"],
            tenant_id=_tenant(),
            interaction_id=row.get("id"),
        )
    except Exception:
        logger.exception("authority policy snapshot failed for handoff %s", row.get("id"))
        return policy.empty()

def _handoff_live_qa(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    _tenant = _mod._tenant
    logger = _mod.logger
    from agent_core.live_qa import policy

    try:
        snap = policy.snapshot(
            conn,
            tenant_id=_tenant(),
            interaction_id=row.get("id"),
        )
        capable = policy.audio_capable_map(conn, [row.get("id") or ""])
        snap["audioCapable"] = bool(capable.get(row.get("id") or ""))
        return snap
    except Exception:
        logger.exception("live_qa snapshot failed for handoff %s", row.get("id"))
        return policy.empty()

def _handoff_compliance_items(conn: Any, interaction_id: str) -> list[dict[str, Any]]:
    _mod = _db()
    _one = _mod._one
    _rows = _mod._rows
    disclosures = _rows(
        conn.execute(
            text(
                """
                SELECT id, rule_id, label, read
                FROM interaction_disclosures
                WHERE interaction_id = :iid
                ORDER BY created_at
                """
            ),
            {"iid": interaction_id},
        )
    )
    by_rule: dict[str, dict[str, Any]] = {}
    by_label: dict[str, dict[str, Any]] = {}
    for d in disclosures:
        if d.get("rule_id"):
            by_rule[d["rule_id"]] = d
        by_label[(d.get("label") or "").lower()] = d
    identity = _one(
        conn.execute(
            text(
                """
                SELECT id, status, method
                FROM identity_verifications
                WHERE interaction_id = :iid
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"iid": interaction_id},
        )
    )
    items: list[dict[str, Any]] = []
    for rule_id, label in _HANDOFF_DISCLOSURE_RULES:
        row = by_rule.get(rule_id) or by_label.get(label.lower())
        checked = bool(row and row.get("read"))
        locked = False
        item_id = row["id"] if row else rule_id
        if rule_id == "rule-identity":
            verified = bool(identity and identity.get("status") == "verified")
            checked = checked or verified
            locked = verified
            item_id = "identity" if not row else row["id"]
        items.append(
            {
                "id": item_id,
                "label": label,
                "required": rule_id != "rule-payment",
                "checked": checked,
                "locked": locked,
                "ruleId": rule_id,
            }
        )
    dnd_row = by_label.get("dnd & consent window checked")
    items.append(
        {
            "id": dnd_row["id"] if dnd_row else "dnd-consent",
            "label": "DND & consent window checked",
            "required": True,
            "checked": bool(dnd_row and dnd_row.get("read")),
            "locked": False,
            "ruleId": None,
        }
    )
    return items

def claim_handoff(interaction_id: str) -> dict[str, Any]:
    _mod = _db()
    _activity = _mod._activity
    _actor_user_id = _mod._actor_user_id
    _assert_tenant_owns = _mod._assert_tenant_owns
    _id = _mod._id
    _one = _mod._one
    engine = _mod.engine
    actor = _actor_user_id()
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "interactions", interaction_id)
        ho = _one(
            conn.execute(
                text(
                    """
                    SELECT h.id, h.to_user_id, h.accepted_at, h.completed_at, h.to_team_id,
                           i.status, i.handler_user_id
                    FROM interaction_handoffs h
                    JOIN interactions i ON i.id = h.interaction_id
                    WHERE h.interaction_id = :iid
                    ORDER BY h.requested_at DESC NULLS LAST, h.created_at DESC
                    LIMIT 1
                    FOR UPDATE OF h
                    """
                ),
                {"iid": interaction_id},
            )
        )
        if ho is None:
            raise KeyError("handoff_not_found")
        if ho["completed_at"] is not None or ho["status"] == "completed":
            raise ValueError("handoff_already_completed")
        if ho["to_user_id"] and ho["to_user_id"] != actor:
            raise ValueError("handoff_already_claimed")
        if ho["accepted_at"] and ho["to_user_id"] == actor:
            pass  # idempotent re-claim
        else:
            if not _handoff_queue_visible(conn, ho.get("to_team_id")):
                raise PermissionError("handoff_not_assigned")
            updated = conn.execute(
                text(
                    """
                    UPDATE interaction_handoffs
                    SET to_user_id = :uid, accepted_at = COALESCE(accepted_at, now())
                    WHERE id = :id
                      AND (to_user_id IS NULL OR to_user_id = :uid)
                      AND completed_at IS NULL
                    RETURNING id
                    """
                ),
                {"id": ho["id"], "uid": actor},
            ).fetchone()
            if updated is None:
                raise ValueError("handoff_already_claimed")
        conn.execute(
            text(
                """
                UPDATE interactions
                SET handler_kind = 'human',
                    handler_user_id = :uid,
                    handler_bot_id = NULL,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": interaction_id, "uid": actor},
        )
        existing = _one(
            conn.execute(
                text(
                    """
                    SELECT id FROM interaction_participants
                    WHERE interaction_id = :iid
                      AND participant_kind = 'human'
                      AND user_id = :uid
                      AND left_at IS NULL
                    LIMIT 1
                    """
                ),
                {"iid": interaction_id, "uid": actor},
            )
        )
        if existing is None:
            conn.execute(
                text(
                    """
                    INSERT INTO interaction_participants (
                      id, interaction_id, participant_kind, user_id, role, joined_at
                    ) VALUES (
                      :id, :iid, 'human', :uid, 'primary', now()
                    )
                    """
                ),
                {"id": _id("IP"), "iid": interaction_id, "uid": actor},
            )
        _activity(
            conn,
            "interaction",
            interaction_id,
            "handoff_claimed",
            "Handoff claimed",
            None,
        )
    return get_handoff_session(interaction_id)

def record_handoff_disclosure(interaction_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    _actor_user_id = _mod._actor_user_id
    _assert_tenant_owns = _mod._assert_tenant_owns
    _id = _mod._id
    _one = _mod._one
    engine = _mod.engine
    actor = _actor_user_id()
    item_id = (payload.get("itemId") or "").strip()
    rule_id = (payload.get("ruleId") or "").strip() or None
    label = (payload.get("label") or "").strip()
    read = bool(payload.get("read", True))
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "interactions", interaction_id)
        _assert_handoff_assignee(conn, interaction_id, actor)
        if item_id == "identity" or rule_id == "rule-identity":
            ident = _one(
                conn.execute(
                    text(
                        """
                        SELECT id, status FROM identity_verifications
                        WHERE interaction_id = :iid
                        ORDER BY created_at DESC LIMIT 1
                        """
                    ),
                    {"iid": interaction_id},
                )
            )
            if ident and ident["status"] == "verified":
                raise ValueError("identity_locked")
            if read:
                cust = _one(
                    conn.execute(
                        text("SELECT customer_id FROM interactions WHERE id = :id"),
                        {"id": interaction_id},
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO identity_verifications (
                          id, interaction_id, customer_id, method, status,
                          attempt_count, verified_at
                        ) VALUES (
                          :id, :iid, :cid, 'manual', 'verified', 1, now()
                        )
                        """
                    ),
                    {
                        "id": _id("IV"),
                        "iid": interaction_id,
                        "cid": cust["customer_id"] if cust else None,
                    },
                )
            rule_id = rule_id or "rule-identity"
            label = label or "Identity verified"
        if not label:
            for rid, lbl in _HANDOFF_DISCLOSURE_RULES:
                if rid == rule_id or rid == item_id:
                    label = lbl
                    rule_id = rid
                    break
            if item_id == "dnd-consent":
                label = "DND & consent window checked"
        if not label:
            raise ValueError("disclosure_label_required")
        existing = None
        if item_id and not item_id.startswith("rule-") and item_id not in {"identity", "dnd-consent"}:
            existing = _one(
                conn.execute(
                    text(
                        """
                        SELECT id FROM interaction_disclosures
                        WHERE id = :id AND interaction_id = :iid
                        """
                    ),
                    {"id": item_id, "iid": interaction_id},
                )
            )
        if existing:
            conn.execute(
                text(
                    """
                    UPDATE interaction_disclosures
                    SET read = :read, read_at_sec = COALESCE(read_at_sec, 0),
                        read_by_kind = 'human', read_by_user_id = :uid, read_by_bot_id = NULL
                    WHERE id = :id
                    """
                ),
                {"id": existing["id"], "read": read, "uid": actor},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO interaction_disclosures (
                      id, interaction_id, rule_id, label, read, read_at_sec,
                      read_by_kind, read_by_user_id
                    ) VALUES (
                      :id, :iid, :rule_id, :label, :read, 0, 'human', :uid
                    )
                    """
                ),
                {
                    "id": _id("DISC"),
                    "iid": interaction_id,
                    "rule_id": rule_id,
                    "label": label,
                    "read": read,
                    "uid": actor,
                },
            )
    return get_handoff_session(interaction_id)

def accept_handoff_suggestion(interaction_id: str, suggestion_id: str) -> dict[str, Any]:
    _mod = _db()
    _actor_user_id = _mod._actor_user_id
    _assert_tenant_owns = _mod._assert_tenant_owns
    _one = _mod._one
    engine = _mod.engine
    actor = _actor_user_id()
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "interactions", interaction_id)
        _assert_handoff_assignee(conn, interaction_id, actor)
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT id FROM ai_response_suggestions
                    WHERE id = :sid
                      AND (interaction_id = :iid OR conversation_id IN (
                            SELECT id FROM conversations WHERE interaction_id = :iid
                          ))
                    """
                ),
                {"sid": suggestion_id, "iid": interaction_id},
            )
        )
        if row is None:
            raise KeyError("suggestion_not_found")
        conn.execute(
            text(
                """
                UPDATE ai_response_suggestions
                SET accepted = true,
                    accepted_by_user_id = :uid,
                    accepted_at = now()
                WHERE id = :id
                """
            ),
            {"id": suggestion_id, "uid": actor},
        )
    return get_handoff_session(interaction_id)

def _assert_handoff_assignee(conn: Any, interaction_id: str, actor: str) -> None:
    _mod = _db()
    _one = _mod._one
    row = _one(
        conn.execute(
            text(
                """
                SELECT i.handler_user_id, h.to_user_id
                FROM interactions i
                LEFT JOIN LATERAL (
                  SELECT to_user_id FROM interaction_handoffs
                  WHERE interaction_id = i.id
                  ORDER BY requested_at DESC NULLS LAST, created_at DESC
                  LIMIT 1
                ) h ON true
                WHERE i.id = :id
                """
            ),
            {"id": interaction_id},
        )
    )
    if row is None:
        raise KeyError("interaction_not_found")
    if row["handler_user_id"] != actor and row["to_user_id"] != actor:
        raise PermissionError("handoff_not_assigned")

