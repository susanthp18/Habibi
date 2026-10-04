"""Handoff queue, session, claim, disclosure and suggestions (WP-036 peel).

Peeled from ``db.py``. Call sites stay ``db.*`` via a bottom-of-file
re-export. Reach the engine through :func:`_db`, never ``from db_core import
engine``: the ``db_tx`` fixture wraps ``db.engine``, and a name bound from
``db_core`` bypasses that proxy.
"""

from __future__ import annotations

import logging
import visibility
from datetime import date, datetime, timezone
from schemas import HandoffQueueItem, HandoffQueueResponse, HandoffSessionResponse
from sqlalchemy import text
from typing import Any
from agent_core.clock import utc_now
from db_core import (
    _activity,
    _actor_user_id,
    _assert_tenant_owns,
    _dump,
    _id,
    _one,
    _rows,
    _tenant,
)

logger = logging.getLogger(__name__)


def _db():
    """The ``db`` module object, resolved at call time."""
    import db as d

    return d


#: A wrap-up outcome and the evidence it must carry: the record it files
#: ("promise", "callback", "dispute") or the agent's own words ("notes"). An
#: outcome nothing backs is not offered -- "PTP captured" used to save with no
#: promise, and "Escalated to supervisor" escalated nothing.
HANDOFF_OUTCOMES: dict[str, str] = {
    "PTP captured": "promise",
    "Callback scheduled": "callback",
    "Dispute - under review": "dispute",
    "Customer says they paid": "notes",
    "Info provided": "notes",
    "Unresolved - retry": "notes",
}


def require_outcome_evidence(payload: dict[str, Any]) -> None:
    """Refuse a wrap-up whose outcome lacks what it claims happened."""
    need = HANDOFF_OUTCOMES.get(payload.get("disposition") or "")
    if need is None:
        raise ValueError("unknown_disposition")
    has = (payload.get("notes") or "").strip() if need == "notes" else payload.get(need)
    if not has:
        raise ValueError(f"disposition_needs:{need}")


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

def _handoff_status(completed: bool, claimed: bool) -> str:
    """The case's state, not the call's: an escalation outlives the bot leg."""
    if completed:
        return "completed"
    if claimed:
        return "active"
    return "pending_claim"

def _actor_team_id(conn: Any) -> str | None:
    row = _one(
        conn.execute(
            text("SELECT team_id FROM users WHERE id = :id"),
            {"id": _actor_user_id()},
        )
    )
    return row["team_id"] if row else None

def _handoff_queue_visible(conn: Any, to_team_id: str | None) -> bool:
    """Whether this unclaimed handoff belongs on the actor's queue."""
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

#: The case on an interaction: its escalation, ahead of a supervisor's
#: temporary call takeover (a 'Supervisor barge' row, closed with the call),
#: which must never stand in for the case.
_CASE_ORDER = (
    "ORDER BY queue IS NOT DISTINCT FROM 'Supervisor barge', "
    "requested_at DESC NULLS LAST, created_at DESC"
)

#: The queue shows the oldest escalations first, this many unless the page asks
#: for more, and says how many are waiting.
HANDOFF_QUEUE_LIMIT = 50

_QUEUE_COLUMNS = """
  i.id AS interaction_id,
  h.id AS handoff_id,
  i.customer_id,
  c.name AS customer_name,
  COALESCE(i.account_id, '') AS account_id,
  h.reason,
  h.queue,
  COALESCE(c.risk, 'medium') AS risk,
  h.requested_at,
  h.transfer_outcome,
  EXTRACT(EPOCH FROM (now() - COALESCE(h.requested_at, h.created_at)))::int AS wait_sec
"""


def _queue_item(r: dict[str, Any]) -> dict[str, Any]:
    return _dump(
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
            transferOutcome=r["transfer_outcome"],
        )
    )


def _like(term: str) -> str:
    """A substring pattern for ILIKE ... ESCAPE '\\', the term taken literally."""
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def list_handoff_queue(
    *,
    customer_id: str | None = None,
    search: str | None = None,
    limit: int = HANDOFF_QUEUE_LIMIT,
) -> dict[str, Any]:
    """The cases waiting for someone, oldest first, and the actor's own open
    cases. ``search`` matches the customer's name or id, or the loan account."""
    engine = _db().engine
    actor = _actor_user_id()
    vis = visibility.resolve(actor)
    with engine.connect() as conn:
        actor_team = _actor_team_id(conn)
        params: dict[str, Any] = {
            "tenant_id": _tenant(),
            "limit": max(1, min(int(limit), 500)),
            "actor": actor,
            "actor_team": actor_team,
            "vis_all": vis.is_unrestricted,
            "vis_team": vis.scope == visibility.TEAM,
            "vis_actor": actor,
        }
        filters = ""
        if customer_id:
            filters += " AND i.customer_id = :customer_id"
            params["customer_id"] = customer_id
        term = (search or "").strip()
        if term:
            filters += (
                " AND (c.name ILIKE :term ESCAPE '\\' OR i.customer_id ILIKE :term ESCAPE '\\'"
                " OR i.account_id ILIKE :term ESCAPE '\\')"
            )
            params["term"] = _like(term)
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT {_QUEUE_COLUMNS}, count(*) OVER ()::int AS total
                    FROM interaction_handoffs h
                    JOIN interactions i ON i.id = h.interaction_id
                    JOIN customers c ON c.id = i.customer_id
                    WHERE i.tenant_id = :tenant_id
                      AND h.to_kind = 'human'
                      AND h.to_user_id IS NULL
                      AND h.accepted_at IS NULL
                      AND h.completed_at IS NULL
                      {filters}
                      {_handoff_queue_sql_filter()}
                    ORDER BY h.requested_at ASC NULLS LAST, h.created_at ASC
                    LIMIT :limit
                    """
                ),
                params,
            )
        )
        # The caseload: every open case the actor holds, not only the newest.
        mine = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT {_QUEUE_COLUMNS}
                    FROM interaction_handoffs h
                    JOIN interactions i ON i.id = h.interaction_id
                    JOIN customers c ON c.id = i.customer_id
                    WHERE i.tenant_id = :tenant_id
                      AND h.to_kind = 'human'
                      AND h.to_user_id = :actor
                      AND h.completed_at IS NULL
                      AND h.queue IS DISTINCT FROM 'Supervisor barge'
                    ORDER BY h.requested_at ASC NULLS LAST, h.created_at ASC
                    """
                ),
                {"tenant_id": _tenant(), "actor": actor},
            )
        )
    return _dump(
        HandoffQueueResponse.model_validate(
            {
                "items": [_queue_item(r) for r in rows],
                "total": rows[0]["total"] if rows else 0,
                "mine": [_queue_item(r) for r in mine],
            }
        )
    )


def _assert_handoff_readable(conn: Any, row: dict[str, Any]) -> tuple[bool, bool]:
    """Who may open a case: its holder, a supervisor, or -- while unclaimed --
    anyone whose queue it is on. Returns (is_mine, is_supervisor)."""
    import authz

    actor = _actor_user_id()
    claimed = bool(row["accepted_at"] and row["to_user_id"])
    is_mine = claimed and row["to_user_id"] == actor
    is_supervisor = authz.has_permission(actor, authz.SUPERVISOR_READ)
    if claimed and not is_mine and not is_supervisor:
        raise PermissionError("handoff_not_assigned")
    if not claimed and not _handoff_queue_visible(conn, row.get("to_team_id")) and not is_supervisor:
        raise PermissionError("handoff_not_assigned")
    return is_mine, is_supervisor


def assert_handoff_readable(interaction_id: str) -> None:
    """The session's own access rule, for what the Hub reads beside it (the copilot)."""
    with _db().engine.connect() as conn:
        _assert_tenant_owns(conn, "interactions", interaction_id)
        row = _one(
            conn.execute(
                text(
                    f"""
                    SELECT h.to_user_id, h.accepted_at, h.to_team_id
                    FROM interactions i
                    JOIN LATERAL (
                      SELECT to_user_id, accepted_at, to_team_id FROM interaction_handoffs
                      WHERE interaction_id = i.id AND to_kind = 'human'
                      {_CASE_ORDER}
                      LIMIT 1
                    ) h ON true
                    WHERE i.id = :id
                    """
                ),
                {"id": interaction_id},
            )
        )
        if row is None:
            raise KeyError("handoff_not_found")
        _assert_handoff_readable(conn, row)


def get_handoff_session(interaction_id: str) -> dict[str, Any]:
    engine = _db().engine
    with engine.connect() as conn:
        _assert_tenant_owns(conn, "interactions", interaction_id)
        row = _one(
            conn.execute(
                text(
                    f"""
                    SELECT
                      i.id,
                      i.customer_id,
                      c.name AS customer_name,
                      i.account_id,
                      i.channel,
                      i.status,
                      i.started_at,
                      i.transferred_from_bot_id,
                      i.disposition,
                      COALESCE(u.name, '') AS handler_name,
                      COALESCE(tb.name, fb.name, '') AS transferred_from,
                      c.risk,
                      c.phone_primary,
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
                      h.requested_at,
                      h.transfer_outcome,
                      h.wrap_up_notes,
                      i.ended_at,
                      conv.id AS conversation_id
                    FROM interactions i
                    JOIN customers c ON c.id = i.customer_id
                    LEFT JOIN LATERAL (
                      SELECT id, reason, to_user_id, accepted_at, completed_at, to_team_id,
                             requested_at, transfer_outcome, wrap_up_notes
                      FROM interaction_handoffs
                      WHERE interaction_id = i.id AND to_kind = 'human'
                      {_CASE_ORDER}
                      LIMIT 1
                    ) h ON true
                    LEFT JOIN users u ON u.id = h.to_user_id
                    LEFT JOIN bots tb ON tb.id = i.transferred_from_bot_id
                    LEFT JOIN bots fb ON fb.id = i.handler_bot_id
                    LEFT JOIN accounts a ON a.id = i.account_id
                    LEFT JOIN products p ON p.id = a.product_id
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

        is_mine, is_supervisor = _assert_handoff_readable(conn, row)

        claimed_flag = bool(row["accepted_at"] and row["to_user_id"])
        status = _handoff_status(row["completed_at"] is not None, claimed_flag)
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
        # A thread's passages answer one customer message; found for an
        # earlier one (or for none) they are stale, as the Inbox says. The
        # latest message is the Inbox's (db_inbox_rag._latest_customer_turns).
        suggestions = _rows(
            conn.execute(
                text(
                    """
                    SELECT s.id, s.suggestion_text AS body, s.source, s.accepted,
                           s.conversation_id IS NOT NULL
                             AND s.answers_message_id IS DISTINCT FROM latest.id AS stale
                    FROM ai_response_suggestions s
                    LEFT JOIN LATERAL (
                      SELECT m.id FROM messages m
                      WHERE m.conversation_id = s.conversation_id AND m.sender = 'customer'
                        AND btrim(m.body) <> ''
                      ORDER BY COALESCE(m.sent_at, m.created_at) DESC, m.id COLLATE "C" DESC
                      LIMIT 1
                    ) latest ON true
                    WHERE s.interaction_id = :interaction_id
                       OR (CAST(:conversation_id AS text) IS NOT NULL AND s.conversation_id = :conversation_id)
                    ORDER BY s.created_at
                    """
                ),
                {"interaction_id": interaction_id, "conversation_id": row.get("conversation_id")},
            )
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
        bot_name = row["transferred_from"]  # the agent that handed over; unnamed reads as "Bot"
        speakers = {
            "customer": row["customer_name"],
            "agent": "You" if is_mine else (row["handler_name"] or "Agent"),
            "bot": f"Bot · {bot_name}" if bot_name else "Bot",
            "system": "System",
        }
        channel = row["channel"] or "voice"
        channel_label = channel.replace("_", " ").title()
        reason = row["reason"] or "routing_rule"
        started_at = _epoch_ms(row["started_at"])
        outstanding = row["account_outstanding"]
        context["outstanding"] = float(outstanding) if outstanding is not None else None
        import voice_studio_supervision

        call_live = voice_studio_supervision.live_run(conn, interaction_id) is not None
        # What the wrap-up filed, not every record on the interaction: the
        # wrap-up writes its records in the transaction that closes the case,
        # and now() is that transaction's start, so they carry its instant.
        filed = _rows(
            conn.execute(
                text(
                    """
                    SELECT 'promise' AS kind, id FROM promises WHERE interaction_id = :ix AND created_at = :done
                    UNION ALL
                    SELECT 'dispute', id FROM disputes WHERE interaction_id = :ix AND created_at = :done
                    UNION ALL
                    SELECT 'callback', id FROM callbacks WHERE interaction_id = :ix AND created_at = :done
                    """
                ),
                {"ix": interaction_id, "done": row["completed_at"]},
            )
        ) if row["completed_at"] is not None else []
    wrap_up = None
    if row["completed_at"] is not None:
        wrap_up = {
            "outcome": row["disposition"],
            "notes": row["wrap_up_notes"],
            "at": _iso_ts(row["completed_at"]),
            "byUserId": row["to_user_id"],
        }

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
            # The case's holder, whom a takeover expects to replace.
            "handlerUserId": row["to_user_id"] if claimed_flag else None,
            "requestedAt": _iso_ts(row["requested_at"]),
            "callState": "live" if call_live else "ended",
            "callEndedAt": None if call_live else _iso_ts(row["ended_at"]),
            "transferOutcome": row["transfer_outcome"],
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
                "accepted": bool(s["accepted"]),
                "stale": bool(s["stale"]),
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
        outcomes=[{"label": label, "needs": needs} for label, needs in HANDOFF_OUTCOMES.items()],
        speakers=speakers,
        wrapUp=wrap_up,
        filed=[{"kind": f["kind"], "id": f["id"]} for f in filed],
        copilotEvidence=_copilot_evidence(row, transcript, context, call_live),
    ))
    return _dump(session)

def _copilot_evidence(
    row: dict[str, Any], transcript: list[dict[str, Any]], context: dict[str, Any], call_live: bool
) -> str:
    """A version of what the copilot drafts from: the conversation, the two
    policy decisions and the approvals waiting on the customer. The page
    redrafts when it changes, and only then."""
    import hashlib
    import json

    try:
        from work_runtime import list_jobs

        approvals = sorted(
            str(j.get("id"))
            for j in list_jobs(status="input_required", customer_id=row["customer_id"], limit=20)
        )
    except Exception:
        logger.exception("approvals lookup failed for handoff %s", row.get("id"))
        approvals = ["unavailable"]
    basis = [
        len(transcript),
        transcript[-1]["id"] if transcript else None,
        call_live,
        context.get("offerPolicy"),
        context.get("authorityPolicy"),
        approvals,
    ]
    return hashlib.sha1(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()[:16]


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
    customer_id = row["customer_id"]
    account_id = row.get("account_id")
    last_promise = _one(
        conn.execute(
            text(
                """
                SELECT amount, promised_at, status
                FROM promises
                WHERE customer_id = :cid
                ORDER BY created_at DESC
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
            # A part-paid instalment past its date is overdue too.
            "daysOverdue": days if next_emi["status"] in ("overdue", "partial") else 0,
        }
    return {
        "risk": str(row.get("risk") or "medium").title(),
        "currency": "₹",
        "lastPromise": last,
        "nextEmi": emi,
        "openDisputes": int((open_disputes or {}).get("n") or 0),
        "tenureMonths": tenure,
        "product": row.get("product") or "",
        "offerPolicy": _handoff_offer_policy(conn, row),
        "authorityPolicy": _handoff_authority_policy(conn, row),
    }

def _handoff_offer_policy(conn: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    """None when the policy could not be read: the panel says so instead of
    showing an empty decision as if nothing applied."""
    from agent_core.reco import policy

    try:
        with conn.begin_nested():
            return policy.snapshot(
                conn,
                customer_id=row["customer_id"],
                tenant_id=_tenant(),
                interaction_id=row.get("id"),
            )
    except Exception:
        logger.exception("offer policy snapshot failed for handoff %s", row.get("id"))
        return None


def _handoff_authority_policy(conn: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    from agent_core.authority import policy

    try:
        with conn.begin_nested():
            return policy.snapshot(
                conn,
                customer_id=row["customer_id"],
                tenant_id=_tenant(),
                interaction_id=row.get("id"),
            )
    except Exception:
        logger.exception("authority policy snapshot failed for handoff %s", row.get("id"))
        return None


def _handoff_compliance_items(conn: Any, interaction_id: str) -> list[dict[str, Any]]:
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

def claim_handoff(interaction_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make the case the caller's: from the queue, or from a colleague.

    Claiming a waiting case is an agent's ordinary work. Taking one a colleague
    holds is a reassignment -- the Inbox's rule (db_inbox.takeover_conversation):
    it needs supervisor rights and ``expectedAssigneeId``, whom the caller saw
    holding it, and is refused if that changed meanwhile. Either way the case,
    the interaction and its text thread move together.
    """
    import authz
    import db_inbox

    expected = (payload or {}).get("expectedAssigneeId", db_inbox._UNSTATED)
    engine = _db().engine
    actor = _actor_user_id()
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "interactions", interaction_id)
        # Lock order: conversation, interaction, handoff (db_inbox.lock_interaction_thread).
        thread = db_inbox.lock_interaction_thread(conn, interaction_id)
        conn.execute(text("SELECT 1 FROM interactions WHERE id = :id FOR UPDATE"), {"id": interaction_id})
        ho = _one(
            conn.execute(
                text(
                    f"""
                    SELECT id, to_user_id, accepted_at, completed_at, to_team_id
                    FROM interaction_handoffs
                    WHERE interaction_id = :iid AND to_kind = 'human'
                    {_CASE_ORDER}
                    LIMIT 1
                    FOR UPDATE
                    """
                ),
                {"iid": interaction_id},
            )
        )
        if ho is None:
            raise KeyError("handoff_not_found")
        if ho["completed_at"] is not None:
            raise ValueError("handoff_already_completed")
        holder = ho["to_user_id"] if ho["accepted_at"] else None
        reassign = holder is not None and holder != actor
        if holder != actor:
            if expected is not db_inbox._UNSTATED and holder != expected:
                raise ValueError("handoff_owner_changed")
            if reassign:
                if expected is db_inbox._UNSTATED:
                    raise ValueError("handoff_already_claimed")
                if not authz.has_permission(actor, authz.SUPERVISOR_WRITE):
                    raise PermissionError("reassign_requires_supervisor")
            elif not _handoff_queue_visible(conn, ho.get("to_team_id")):
                raise PermissionError("handoff_not_assigned")
            conn.execute(
                text(
                    """
                    UPDATE interaction_handoffs
                    SET to_user_id = :uid, accepted_at = COALESCE(accepted_at, now())
                    WHERE id = :id
                    """
                ),
                {"id": ho["id"], "uid": actor},
            )
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
        if reassign:
            if thread is not None and thread["assigned_user_id"] != actor:
                db_inbox._assign_conversation(conn, thread, actor, "Took over from the Handoff Hub")
        else:
            db_inbox.claim_interaction_thread(conn, thread, actor)
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
        if holder != actor:
            _activity(
                conn,
                "interaction",
                interaction_id,
                "handoff_taken_over" if reassign else "handoff_claimed",
                "Case taken over" if reassign else "Handoff claimed",
                None,
            )
    return get_handoff_session(interaction_id)

def record_handoff_disclosure(interaction_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    engine = _db().engine
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
                    SET read = :read,
                        read_at_sec = COALESCE(read_at_sec, (SELECT GREATEST(0, EXTRACT(EPOCH FROM (now() - started_at)))::int
                       FROM interactions WHERE id = :iid)),
                        read_by_kind = 'human', read_by_user_id = :uid, read_by_bot_id = NULL
                    WHERE id = :id
                    """
                ),
                {"id": existing["id"], "iid": interaction_id, "read": read, "uid": actor},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO interaction_disclosures (
                      id, interaction_id, rule_id, label, read, read_at_sec,
                      read_by_kind, read_by_user_id
                    ) VALUES (
                      :id, :iid, :rule_id, :label, :read,
                      (SELECT GREATEST(0, EXTRACT(EPOCH FROM (now() - started_at)))::int
                       FROM interactions WHERE id = :iid),
                      'human', :uid
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
    engine = _db().engine
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

def _assert_handoff_assignee(
    conn: Any, interaction_id: str, actor: str, *, open_only: bool = True
) -> dict[str, Any]:
    """The actor holds this interaction's case; and, unless ``open_only`` is
    off, the case is still open -- a wrapped-up case takes no more writes.
    Returns the case row."""
    row = _one(
        conn.execute(
            text(
                f"""
                SELECT id, to_user_id, accepted_at, completed_at
                FROM interaction_handoffs
                WHERE interaction_id = :id AND to_kind = 'human'
                {_CASE_ORDER}
                LIMIT 1
                """
            ),
            {"id": interaction_id},
        )
    )
    if row is None:
        raise KeyError("handoff_not_found")
    if not row["accepted_at"] or row["to_user_id"] != actor:
        raise PermissionError("handoff_not_assigned")
    if open_only and row["completed_at"] is not None:
        raise ValueError("handoff_closed")
    return row
