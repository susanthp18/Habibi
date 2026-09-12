"""Routing-builder reads and the voice-escalation write.

Peeled from ``db.py`` (WP-036 peel 7). Call sites stay ``db.*`` via a
bottom-of-file re-export. Reach the engine through :func:`_db`, never
``from db_core import engine``: the ``db_tx`` fixture wraps ``db.engine``,
and a name bound from ``db_core`` bypasses that proxy.

``DEFAULT_BOT_ID`` stays on ``db.py`` (Prompt Studio writes). This module
reaches it through ``_db()`` rather than copying the env default.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from agent_core.clock import utc_now


def _db():
    """The ``db`` module object, resolved at call time.

    Carved modules must use ``_db().engine``, never ``from db_core import
    engine``. See ``db_core._db``.
    """
    import db as d

    return d


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routing & Logic Builder — reads (writes stay Phase 3A / optimistic UI)
# ---------------------------------------------------------------------------

_ROUTING_CATEGORIES = {"Escalation", "Handoff", "Throttle", "Compliance", "Routing"}

_ROUTING_ACTION_KEYS = {
    "route_tier2",
    "route_specialist",
    "handoff_human",
    "play_disclosure",
    "send_sms",
    "log_flag",
    "stop_upsell",
    "slow_tts",
    "escalate_supervisor",
}

# Legacy action_key → screen ActionKey (pre-builder seed used "handoff").
_ROUTING_ACTION_ALIASES = {
    "handoff": "handoff_human",
    "escalate": "escalate_supervisor",
    "tier2": "route_tier2",
}


def _routing_action_key(raw: str | None) -> str:
    key = (raw or "").strip()
    key = _ROUTING_ACTION_ALIASES.get(key, key)
    if key in _ROUTING_ACTION_KEYS:
        return key
    return "log_flag"


def _routing_when(conditions: Any) -> list[Any]:
    """Normalize DB conditions jsonb into Habibi ConditionNode[]."""
    if conditions is None:
        return []
    if isinstance(conditions, list):
        return conditions
    if isinstance(conditions, dict):
        # Legacy shape e.g. {"avgSentimentLt": -0.35} → approximate screen node.
        if "avgSentimentLt" in conditions:
            return [
                {
                    "id": "legacy-sentiment",
                    "field": "sentiment",
                    "op": "=",
                    "value": "angry",
                }
            ]
        # Already a single condition node?
        if "field" in conditions or "or" in conditions:
            return [conditions]
    return []


def _routing_action_params(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[str, str] = {}
    for k, v in raw.items():
        if v is None:
            continue
        out[str(k)] = str(v)
    return out or None


def _routing_category(raw: str | None) -> str:
    if raw in _ROUTING_CATEGORIES:
        return raw
    return "Routing"


_ROUTING_RULE_SELECT = """
    SELECT
      r.id,
      r.priority,
      r.enabled,
      COALESCE(NULLIF(r.name, ''), r.id) AS name,
      COALESCE(r.description, '') AS description,
      r.category,
      r.conditions,
      r.action_key,
      r.action_params,
      COALESCE(agg.execution_count, 0) AS execution_count,
      agg.last_fired_at,
      COALESCE(agg.triggers_last_24h, 0) AS triggers_last_24h
    FROM routing_rules r
    LEFT JOIN LATERAL (
      SELECT
        count(*) FILTER (WHERE e.result = 'matched') AS execution_count,
        max(e.evaluated_at) FILTER (WHERE e.result = 'matched') AS last_fired_at,
        count(*) FILTER (
          WHERE e.result = 'matched'
            AND e.evaluated_at >= now() - interval '24 hours'
        ) AS triggers_last_24h
      FROM routing_rule_executions e
      WHERE e.rule_id = r.id
    ) agg ON true
    WHERE r.tenant_id = :tenant_id
"""


def _map_routing_rule(r: dict[str, Any]) -> dict[str, Any]:
    params = _routing_action_params(r["action_params"])
    then: dict[str, Any] = {"key": _routing_action_key(r["action_key"])}
    if params is not None:
        then["params"] = params
    last = r["last_fired_at"]
    return {
        "id": r["id"],
        "name": r["name"] or r["id"],
        "description": r["description"] or "",
        "category": _routing_category(r["category"]),
        "enabled": bool(r["enabled"]),
        "priority": int(r["priority"] or 0),
        "when": _routing_when(r["conditions"]),
        "then": then,
        "executionCount": int(r["execution_count"] or 0),
        "lastFiredAt": last if last else None,
        "triggersLast24h": int(r["triggers_last_24h"] or 0),
    }


def get_routing_rule(rule_id: str) -> dict[str, Any] | None:
    """Single tenant-scoped rule — used by write paths instead of re-listing."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(_ROUTING_RULE_SELECT + " AND r.id = :rule_id"),
                {"tenant_id": _tenant(), "rule_id": rule_id},
            )
        )
    return _map_routing_rule(row) if row else None


def list_routing_rules() -> list[dict[str, Any]]:
    """Priority-ordered routing rules with execution aggregates. Tenant-scoped."""
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _tenant = _mod._tenant
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(_ROUTING_RULE_SELECT + " ORDER BY r.priority ASC, r.id"),
                {"tenant_id": _tenant()},
            )
        )
    return [_map_routing_rule(r) for r in rows]


_TEAM_NAME_ALIASES = {
    "hardship desk": "card-collections",
    "hardship": "card-collections",
    "dispute desk": "card-collections",
    "dispute": "card-collections",
    "supervisors": "supervisors",
    "supervisor": "supervisors",
    "tier 2": "retail-collections",
    "tier2": "retail-collections",
    "card collections": "card-collections",
    "retail collections": "retail-collections",
}

_ACTION_DEFAULT_TEAM = {
    "escalate_supervisor": "supervisors",
    "route_tier2": "card-collections",
    "route_specialist": "card-collections",
    "handoff_human": "card-collections",
}


def _routing_coerce(a: Any, b: Any) -> tuple[Any, Any]:
    if isinstance(b, bool) or isinstance(a, bool):
        def _b(v: Any) -> bool:
            if isinstance(v, bool):
                return v
            return str(v).strip().lower() in {"1", "true", "yes", "y"}

        return _b(a), _b(b)
    try:
        return float(a), float(b)
    except (TypeError, ValueError):
        return str(a).strip().lower() if a is not None else "", str(b).strip().lower() if b is not None else ""


def _routing_eval_condition(cond: dict[str, Any], context: dict[str, Any]) -> bool:
    field = str(cond.get("field") or "")
    op = str(cond.get("op") or "=")
    raw = context.get(field)
    if op in {">", "<", ">=", "<="}:
        try:
            av = float(raw) if raw is not None else None
            bv = float(cond.get("value"))
        except (TypeError, ValueError):
            return False
        if av is None:
            return False
        if op == ">":
            return av > bv
        if op == "<":
            return av < bv
        if op == ">=":
            return av >= bv
        return av <= bv
    av, bv = _routing_coerce(raw, cond.get("value"))
    if op == "=":
        return av == bv
    if op == "!=":
        return av != bv
    if op == "in":
        if isinstance(cond.get("value"), list):
            return str(raw) in {str(x) for x in cond["value"]}
        return str(raw) in {s.strip() for s in str(cond.get("value") or "").split(",")}
    if op == "contains":
        return str(bv) in str(av)
    return False


def _routing_eval_node(node: Any, context: dict[str, Any]) -> bool:
    if not isinstance(node, dict):
        return False
    if "or" in node and isinstance(node["or"], list):
        return any(
            _routing_eval_condition(c, context)
            for c in node["or"]
            if isinstance(c, dict)
        )
    return _routing_eval_condition(node, context)


def _resolve_team_id(conn: Any, action_key: str, params: dict[str, str] | None) -> str | None:
    _mod = _db()
    _one = _mod._one
    _tenant = _mod._tenant
    params = params or {}
    hint = (params.get("team") or params.get("teamId") or params.get("queue") or "").strip()
    if hint:
        by_id = _one(
            conn.execute(
                text("SELECT id FROM teams WHERE id = :id AND tenant_id = :t"),
                {"id": hint, "t": _tenant()},
            )
        )
        if by_id:
            return by_id["id"]
        alias = _TEAM_NAME_ALIASES.get(hint.lower())
        if alias:
            return alias
        by_name = _one(
            conn.execute(
                text(
                    """
                    SELECT id FROM teams
                    WHERE tenant_id = :t AND lower(name) = lower(:name)
                    LIMIT 1
                    """
                ),
                {"t": _tenant(), "name": hint},
            )
        )
        if by_name:
            return by_name["id"]
    return _ACTION_DEFAULT_TEAM.get(action_key)


def _resolve_assignee_for_team(conn: Any, team_id: str | None) -> tuple[str | None, str | None, str | None]:
    """Return (assignee_user_id, assignee_name, team_name)."""
    _mod = _db()
    _one = _mod._one
    _tenant = _mod._tenant
    _user_name = _mod._user_name
    if not team_id:
        team_id = "card-collections"
    team = _one(
        conn.execute(
            text(
                """
                SELECT id, name, supervisor_user_id
                FROM teams WHERE id = :id AND tenant_id = :t
                """
            ),
            {"id": team_id, "t": _tenant()},
        )
    )
    if not team:
        # Last-resort: any seeded team with a supervisor.
        team = _one(
            conn.execute(
                text(
                    """
                    SELECT id, name, supervisor_user_id
                    FROM teams
                    WHERE tenant_id = :t AND supervisor_user_id IS NOT NULL
                    ORDER BY id
                    LIMIT 1
                    """
                ),
                {"t": _tenant()},
            )
        )
    if not team:
        return None, None, None
    uid = team.get("supervisor_user_id")
    if not uid:
        member = _one(
            conn.execute(
                text(
                    """
                    SELECT u.id
                    FROM users u
                    WHERE u.team_id = :team
                    ORDER BY u.name
                    LIMIT 1
                    """
                ),
                {"team": team["id"]},
            )
        )
        uid = member["id"] if member else None
    if not uid:
        # Empty team (e.g. retail-collections with no members) — borrow Card Collections.
        fallback = _one(
            conn.execute(
                text(
                    """
                    SELECT id, name, supervisor_user_id
                    FROM teams
                    WHERE id = 'card-collections' AND tenant_id = :t
                    """
                ),
                {"t": _tenant()},
            )
        )
        if fallback and fallback.get("supervisor_user_id"):
            team = fallback
            uid = fallback["supervisor_user_id"]
    name = _user_name(conn, uid) if uid else None
    return uid, name, team.get("name")


def _match_routing_rule(
    conn: Any,
    rules: list[dict[str, Any]],
    ctx: dict[str, Any],
    *,
    interaction_id: str | None = None,
    sandbox_run_id: str | None = None,
) -> dict[str, Any]:
    """First matching enabled rule → decision dict, logging the execution.

    Connection-scoped on purpose — the escalation path is already inside a
    transaction and must not open a nested one.
    """
    _mod = _db()
    _id = _mod._id
    for rule in rules:
        if not rule.get("enabled"):
            continue
        when = rule.get("when") or []
        if not when:
            continue
        if not all(_routing_eval_node(node, ctx) for node in when):
            continue
        action = rule.get("then") or {}
        action_key = _routing_action_key(action.get("key"))
        params = action.get("params") if isinstance(action.get("params"), dict) else None
        team_id = _resolve_team_id(conn, action_key, params)
        assignee_id, assignee_name, team_name = _resolve_assignee_for_team(conn, team_id)
        action_taken = f"{action_key}:{team_id or 'none'}:{assignee_id or 'unassigned'}"
        exec_id = _id("RRE")
        conn.execute(
            text(
                """
                INSERT INTO routing_rule_executions (
                  id, rule_id, interaction_id, sandbox_run_id, context,
                  result, action_taken, evaluated_at, created_at
                ) VALUES (
                  :id, :rule_id, :interaction_id, :sandbox_run_id,
                  CAST(:context AS jsonb), 'matched', :action_taken, now(), now()
                )
                """
            ),
            {
                "id": exec_id,
                "rule_id": rule["id"],
                "interaction_id": interaction_id,
                "sandbox_run_id": sandbox_run_id,
                "context": json.dumps(ctx),
                "action_taken": action_taken[:240],
            },
        )
        return {
            "matched": True,
            "ruleId": rule["id"],
            "ruleName": rule.get("name"),
            "actionKey": action_key,
            "actionParams": params,
            "teamId": team_id,
            "teamName": team_name,
            "assigneeUserId": assignee_id,
            "assigneeName": assignee_name,
            "executionId": exec_id,
        }

    return {
        "matched": False,
        "ruleId": None,
        "ruleName": None,
        "actionKey": None,
        "actionParams": None,
        "teamId": _ACTION_DEFAULT_TEAM.get("handoff_human"),
        "teamName": None,
        "assigneeUserId": None,
        "assigneeName": None,
        "executionId": None,
    }


#: Escalation reasons that should also stop outbound collections. Warm-
#: transferring a borrower who has just described losing their job, and then
#: dialling them again tomorrow morning because the campaign says so, is the
#: single most complained-about thing a collections floor does. Until now
#: "hardship" was a routing label that expired with the call.
_ESCALATION_HOLDS = {"hardship": "hardship", "dispute": "dispute"}

#: Hours a specialist has to pick the case up. Matches the roadmap's "hardship
#: as a first-class object with specialist SLA"; the hold itself does not
#: expire on it — an unattended hardship case must stay held, not quietly
#: resume dunning.
_HOLD_SLA_HOURS = 24


def _hold_on_escalation(
    conn: Any, *, customer_id: str | None, reason: str, interaction_id: str | None
) -> None:
    """Place a treatment hold when an escalation says to stop collecting.

    ``ON CONFLICT DO NOTHING`` against the partial unique index, so a second
    escalation on the same call is a no-op rather than an error. Failures are
    swallowed: an escalation must complete even if the hold cannot be written,
    because a customer stuck mid-transfer is a worse outcome than a hold that
    has to be placed by hand.
    """
    _mod = _db()
    _tenant = _mod._tenant
    _id = _mod._id
    kind = _ESCALATION_HOLDS.get(reason)
    if not kind or not customer_id:
        return
    try:
        nested = conn.begin_nested()
        try:
            conn.execute(
                text(
                    """
                    INSERT INTO treatment_holds (
                      id, tenant_id, customer_id, kind, reason, source,
                      interaction_id, placed_by_user_id, sla_due_at
                    ) VALUES (
                      :id, :tenant_id, :customer_id, :kind, :reason, 'bot',
                      :interaction_id, NULL, now() + make_interval(hours => :sla)
                    )
                    ON CONFLICT (customer_id, COALESCE(account_id, ''), kind)
                    WHERE released_at IS NULL
                    DO NOTHING
                    """
                ),
                {
                    "id": _id("THD"),
                    "tenant_id": _tenant(),
                    "customer_id": customer_id,
                    "kind": kind,
                    "reason": f"Escalated from a call: {reason}",
                    "interaction_id": interaction_id,
                    "sla": _HOLD_SLA_HOURS,
                },
            )
            nested.commit()
        except Exception:
            nested.rollback()
            raise
    except Exception:
        logger.exception("treatment hold on escalation failed for %s", customer_id)


def escalate_voice_interaction(
    *,
    interaction_id: str,
    reason: str,
    bot_id: str | None = None,
    customer_id: str | None = None,
    note_text: str | None = None,
    route_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Single-transaction escalate: handoff + note + routing + inbox conversation.

    Collapses the four sequential pool round-trips previously done from
    ``voice.tools.escalate_to_human`` so PSTN calls spend one connection slot.
    """
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _id = _mod._id
    _activity = _mod._activity
    _actor_user_id = _mod._actor_user_id
    DEFAULT_BOT_ID = _mod.DEFAULT_BOT_ID
    ix = (interaction_id or "").strip()
    if not ix:
        raise ValueError("interaction_id_required")

    reasons = {
        "sentiment_drop",
        "verification_failed",
        "compliance",
        "customer_requested",
        "hardship",
        "dispute",
        "high_value",
        "routing_rule",
    }
    r = reason if reason in reasons else "customer_requested"
    ctx = {str(k): v for k, v in (route_context or {}).items()}
    # Read rules outside the write txn (stable catalog).
    rules = list_routing_rules()

    with engine.begin() as conn:
        interaction = _one(
            conn.execute(
                text(
                    """
                    SELECT id, customer_id, channel, status
                    FROM interactions WHERE id = :id
                    """
                ),
                {"id": ix},
            )
        )
        if interaction is None:
            raise KeyError("interaction_not_found")

        cid = customer_id or interaction.get("customer_id")
        hid = _id("HO")
        conn.execute(
            text(
                """
                INSERT INTO interaction_handoffs (
                  id, interaction_id, from_kind, from_user_id, from_bot_id,
                  to_kind, to_user_id, to_bot_id, to_team_id, reason, queue,
                  requested_at, created_at
                ) VALUES (
                  :id, :interaction_id, 'bot', NULL, :bot_id,
                  'human', NULL, NULL, 'retail-collections', :reason, 'Retail Collections',
                  now(), now()
                )
                """
            ),
            {
                "id": hid,
                "interaction_id": ix,
                "bot_id": bot_id or DEFAULT_BOT_ID,
                "reason": r,
            },
        )
        conn.execute(
            text(
                """
                UPDATE interactions
                SET disposition = COALESCE(disposition, 'escalated'),
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": ix},
        )

        _hold_on_escalation(conn, customer_id=cid, reason=r, interaction_id=ix)

        note_id = None
        if note_text and cid:
            note_id = _id("NOTE")
            conn.execute(
                text(
                    """
                    INSERT INTO customer_notes (id, customer_id, author_user_id, text, pinned)
                    VALUES (:id, :customer_id, :author_user_id, :text, false)
                    """
                ),
                {
                    "id": note_id,
                    "customer_id": cid,
                    "author_user_id": _actor_user_id(),
                    "text": note_text[:2000],
                },
            )
            _activity(
                conn,
                "customer",
                cid,
                "note_created",
                "Customer note added",
                note_text[:240],
                cid,
            )

        # Routing match — connection-scoped so it joins this transaction
        # instead of opening a nested one.
        decision = _match_routing_rule(conn, rules, ctx, interaction_id=ix)

        assignee_user_id = decision.get("assigneeUserId")
        team_id = decision.get("teamId")

        existing = _one(
            conn.execute(
                text(
                    """
                    SELECT id FROM conversations
                    WHERE interaction_id = :ix
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"ix": ix},
            )
        )
        now = utc_now()
        if existing:
            conversation_id = existing["id"]
        else:
            channel = interaction.get("channel") or "voice"
            if channel not in {"whatsapp", "sms", "email", "chat", "voice"}:
                channel = "chat"
            conversation_id = _id("CV")
            # Savepoint: a failed INSERT aborts the enclosing transaction in
            # Postgres, so the voice->chat fallback below would itself fail with
            # 25P02 and the whole escalation would be lost.
            nested = conn.begin_nested()
            try:
                conn.execute(
                    text(
                        """
                        INSERT INTO conversations
                          (id, interaction_id, customer_id, assigned_user_id,
                           status, channel, created_at, updated_at)
                        VALUES
                          (:id, :interaction_id, :customer_id, :assignee,
                           'needs_human', :channel, :now, :now)
                        """
                    ),
                    {
                        "id": conversation_id,
                        "interaction_id": ix,
                        "customer_id": interaction["customer_id"],
                        "assignee": assignee_user_id,
                        "channel": channel,
                        "now": now,
                    },
                )
                nested.commit()
            except Exception as exc:
                nested.rollback()
                from sqlalchemy.exc import IntegrityError

                msg = str(getattr(exc, "orig", exc)).lower()
                # Only the schema's channel CHECK is recoverable here; anything
                # else (FK violation, deadlock) must surface.
                if (
                    isinstance(exc, IntegrityError)
                    and channel == "voice"
                    and ("channel" in msg or "check" in msg)
                ):
                    conn.execute(
                        text(
                            """
                            INSERT INTO conversations
                              (id, interaction_id, customer_id, assigned_user_id,
                               status, channel, created_at, updated_at)
                            VALUES
                              (:id, :interaction_id, :customer_id, :assignee,
                               'needs_human', 'chat', :now, :now)
                            """
                        ),
                        {
                            "id": conversation_id,
                            "interaction_id": ix,
                            "customer_id": interaction["customer_id"],
                            "assignee": assignee_user_id,
                            "now": now,
                        },
                    )
                else:
                    raise
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, sender, body, sent_at, created_at)
                    VALUES (:id, :cid, 'system', :body, :now, :now)
                    """
                ),
                {
                    "id": _id("MSG"),
                    "cid": conversation_id,
                    "body": f"Escalated from voice · {r}"[:500],
                    "now": now,
                },
            )

        sets = ["status = 'needs_human'", "updated_at = now()"]
        params: dict[str, Any] = {"id": conversation_id}
        if assignee_user_id:
            sets.append("assigned_user_id = :assignee")
            params["assignee"] = assignee_user_id
        conn.execute(
            text(f"UPDATE conversations SET {', '.join(sets)} WHERE id = :id"),
            params,
        )
        _activity(
            conn,
            "conversation",
            conversation_id,
            "conversation_escalated",
            "Escalated to human",
            r[:240],
            interaction["customer_id"],
        )

        # Live alert inside the same txn (was a second begin() via persist).
        conn.execute(
            text(
                """
                INSERT INTO live_alerts (
                  id, interaction_id, kind, severity, reason, created_at
                ) VALUES (
                  :id, :interaction_id, 'escalation', 'high', :reason, now()
                )
                """
            ),
            {"id": _id("ALERT"), "interaction_id": ix, "reason": r},
        )

        # Snapshot conversation fields without a post-txn get_conversation() round-trip.
        conv_row = _one(
            conn.execute(
                text(
                    """
                    SELECT c.id, c.assigned_user_id, u.name AS assigned_user_name
                    FROM conversations c
                    LEFT JOIN users u ON u.id = c.assigned_user_id
                    WHERE c.id = :id
                    """
                ),
                {"id": conversation_id},
            )
        )

    return {
        "handoffId": hid,
        "noteId": note_id,
        "conversationId": conversation_id,
        "assigneeUserId": (conv_row or {}).get("assigned_user_id") or assignee_user_id,
        "assigneeName": decision.get("assigneeName")
        or (conv_row or {}).get("assigned_user_name"),
        "teamId": team_id,
        "teamName": decision.get("teamName"),
        "routing": decision,
        "reason": r,
    }


def list_routing_rule_executions(rule_id: str) -> list[dict[str, Any]]:
    """Firing log for one rule — tenant-scoped via the parent rule."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _rows = _mod._rows
    _tenant = _mod._tenant
    with engine.connect() as conn:
        parent = _one(
            conn.execute(
                text(
                    """
                    SELECT id FROM routing_rules
                    WHERE id = :id AND tenant_id = :tenant_id
                    """
                ),
                {"id": rule_id, "tenant_id": _tenant()},
            )
        )
        if parent is None:
            raise KeyError("routing_rule_not_found")
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, rule_id, interaction_id, result, action_taken,
                           evaluated_at, context
                    FROM routing_rule_executions
                    WHERE rule_id = :id
                    ORDER BY evaluated_at DESC, id
                    LIMIT 100
                    """
                ),
                {"id": rule_id},
            )
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            at = r["evaluated_at"]
            ctx = r["context"] if isinstance(r["context"], dict) else {}
            out.append(
                {
                    "id": r["id"],
                    "ruleId": r["rule_id"],
                    "interactionId": r["interaction_id"],
                    "result": r["result"],
                    "actionTaken": r["action_taken"],
                    "evaluatedAt": at or "",
                    "context": ctx,
                }
            )
        return out


# ---------------------------------------------------------------------------
# Routing writes + audit
# ---------------------------------------------------------------------------

_AUDIT_ACTIONS = frozenset(
    {"created", "edited", "reordered", "toggled", "deleted", "duplicated"}
)


def _routing_priority_next(conn: Any) -> int:
    d = _db()
    n = conn.execute(
        text(
            "SELECT coalesce(max(priority), 0) + 10 FROM routing_rules WHERE tenant_id = :t"
        ),
        {"t": d.current_tenant()},
    ).scalar()
    return int(n or 10)


def create_routing_rule(payload: dict[str, Any]) -> dict[str, Any]:
    d = _db()
    with d.engine.begin() as conn:
        name = (payload.get("name") or "Untitled rule").strip()
        category = d._routing_category(payload.get("category"))
        then = payload.get("then") or {}
        action_key = d._routing_action_key(
            then.get("key") if isinstance(then, dict) else None
        )
        params = then.get("params") if isinstance(then, dict) else None
        when = payload.get("when") if isinstance(payload.get("when"), list) else []
        rule_id = payload.get("id") or d._id("RULE")
        # If client sent an id that already exists, mint a new one
        exists = d._one(
            conn.execute(
                text("SELECT id FROM routing_rules WHERE id = :id"), {"id": rule_id}
            )
        )
        if exists:
            rule_id = d._id("RULE")
        priority = payload.get("priority")
        if priority is None:
            priority = _routing_priority_next(conn)
        enabled = bool(payload.get("enabled", True))
        conn.execute(
            text(
                """
                INSERT INTO routing_rules (
                  id, tenant_id, priority, enabled, conditions,
                  action_key, action_params, name, description, category
                ) VALUES (
                  :id, :tenant, :priority, :enabled, CAST(:cond AS jsonb),
                  :akey, CAST(:aparams AS jsonb), :name, :desc, :cat
                )
                """
            ),
            {
                "id": rule_id,
                "tenant": d.current_tenant(),
                "priority": int(priority),
                "enabled": enabled,
                "cond": json.dumps(when),
                "akey": action_key,
                "aparams": json.dumps(params if params else {}),
                "name": name,
                "desc": payload.get("description") or "",
                "cat": category,
            },
        )
        d._activity(
            conn,
            "routing_rule",
            rule_id,
            "created",
            "Routing rule created",
            note=name,
        )
        _append_routing_audit(conn, rule_id, name, "created", "Rule created")
        created_id = rule_id
    created = d.get_routing_rule(created_id)
    if created is None:
        raise KeyError("routing_rule_not_found")
    return created


def patch_routing_rule(rule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    d = _db()
    with d.engine.begin() as conn:
        existing = d._one(
            conn.execute(
                text(
                    """
                    SELECT id, name, enabled FROM routing_rules
                    WHERE id = :id AND tenant_id = :tenant
                    """
                ),
                {"id": rule_id, "tenant": d.current_tenant()},
            )
        )
        if existing is None:
            raise KeyError("routing_rule_not_found")
        sets: list[str] = []
        params: dict[str, Any] = {"id": rule_id}
        audit_action = "edited"
        summary_bits: list[str] = []
        if "name" in payload and payload["name"] is not None:
            sets.append("name = :name")
            params["name"] = str(payload["name"]).strip() or existing["name"]
            summary_bits.append("name")
        if "description" in payload and payload["description"] is not None:
            sets.append("description = :description")
            params["description"] = str(payload["description"])
        if "category" in payload and payload["category"] is not None:
            sets.append("category = :category")
            params["category"] = d._routing_category(payload["category"])
        if "enabled" in payload and payload["enabled"] is not None:
            sets.append("enabled = :enabled")
            params["enabled"] = bool(payload["enabled"])
            audit_action = "toggled"
            summary_bits.append(f"enabled={params['enabled']}")
        if "priority" in payload and payload["priority"] is not None:
            sets.append("priority = :priority")
            params["priority"] = int(payload["priority"])
            audit_action = "reordered"
            summary_bits.append(f"priority={params['priority']}")
        if "when" in payload and payload["when"] is not None:
            if not isinstance(payload["when"], list):
                raise ValueError("when_must_be_list")
            sets.append("conditions = CAST(:cond AS jsonb)")
            params["cond"] = json.dumps(payload["when"])
            summary_bits.append(f"{len(payload['when'])} conditions")
        if "then" in payload and payload["then"] is not None:
            then = payload["then"]
            if not isinstance(then, dict):
                raise ValueError("then_must_be_object")
            sets.append("action_key = :akey")
            params["akey"] = d._routing_action_key(then.get("key"))
            aparams = then.get("params")
            sets.append("action_params = CAST(:aparams AS jsonb)")
            params["aparams"] = json.dumps(aparams if aparams else {})
            summary_bits.append(f"action {params['akey']}")
        if not sets:
            raise ValueError("no_fields")
        sets.append("updated_at = now()")
        conn.execute(
            text(f"UPDATE routing_rules SET {', '.join(sets)} WHERE id = :id"),
            params,
        )
        name = params.get("name") or existing["name"]
        _append_routing_audit(
            conn,
            rule_id,
            name,
            audit_action,
            " · ".join(summary_bits) or "Updated",
        )
        patched_id = rule_id
    patched = d.get_routing_rule(patched_id)
    if patched is None:
        raise KeyError("routing_rule_not_found")
    return patched


def reorder_routing_rules(ordered_ids: list[str]) -> list[dict[str, Any]]:
    d = _db()
    with d.engine.begin() as conn:
        # Count matched rows, not submitted ids: the UPDATE is tenant-scoped, so
        # an id from another tenant (or a deleted rule) updates nothing. The
        # audit trail must record what actually changed.
        updated = 0
        for i, rid in enumerate(ordered_ids):
            result = conn.execute(
                text(
                    """
                    UPDATE routing_rules
                    SET priority = :p, updated_at = now()
                    WHERE id = :id AND tenant_id = :tenant
                    """
                ),
                {"id": rid, "p": (i + 1) * 10, "tenant": d.current_tenant()},
            )
            updated += int(result.rowcount or 0)
        if updated:
            _append_routing_audit(
                conn,
                ordered_ids[0],
                "library",
                "reordered",
                f"Reordered {updated} rules",
            )
    return d.list_routing_rules()


def delete_routing_rule(rule_id: str) -> None:
    d = _db()
    with d.engine.begin() as conn:
        existing = d._one(
            conn.execute(
                text(
                    """
                    SELECT id, name FROM routing_rules
                    WHERE id = :id AND tenant_id = :tenant
                    """
                ),
                {"id": rule_id, "tenant": d.current_tenant()},
            )
        )
        if existing is None:
            raise KeyError("routing_rule_not_found")
        _append_routing_audit(
            conn, rule_id, existing["name"], "deleted", "Rule deleted"
        )
        conn.execute(
            text("DELETE FROM routing_rules WHERE id = :id AND tenant_id = :tenant"),
            {"id": rule_id, "tenant": d.current_tenant()},
        )


def _append_routing_audit(
    conn: Any, rule_id: str, rule_name: str, action: str, summary: str
) -> None:
    d = _db()
    # activity_events note stores JSON for the audit feed
    payload = json.dumps(
        {
            "ruleId": rule_id,
            "ruleName": rule_name,
            "action": action if action in _AUDIT_ACTIONS else "edited",
            "summary": summary,
        }
    )
    d._activity(
        conn,
        "routing_rule",
        rule_id,
        f"rule_{action}",
        f"Rule {action}",
        note=payload,
    )


def list_routing_audit(limit: int = 100) -> list[dict[str, Any]]:
    d = _db()
    with d.engine.connect() as conn:
        rows = d._rows(
            conn.execute(
                text(
                    """
                    SELECT ae.id, ae.created_at, ae.note, ae.entity_id,
                           coalesce(u.name, 'System') AS author
                    FROM activity_events ae
                    LEFT JOIN users u ON u.id = ae.actor_user_id
                    WHERE ae.tenant_id = :tenant
                      AND ae.entity_type = 'routing_rule'
                      AND ae.kind LIKE 'rule_%'
                    ORDER BY ae.created_at DESC
                    LIMIT :lim
                    """
                ),
                {"tenant": d.current_tenant(), "lim": limit},
            )
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            meta: dict[str, Any] = {}
            note = r.get("note") or ""
            try:
                meta = json.loads(note) if note.startswith("{") else {}
            except json.JSONDecodeError:
                meta = {}
            action = meta.get("action") or "edited"
            if action not in _AUDIT_ACTIONS:
                action = "edited"
            at = r["created_at"]
            out.append(
                {
                    "id": r["id"],
                    "at": at.isoformat() if hasattr(at, "isoformat") else str(at),
                    "author": r["author"],
                    "ruleId": meta.get("ruleId") or r["entity_id"],
                    "ruleName": meta.get("ruleName") or r["entity_id"],
                    "action": action,
                    "summary": meta.get("summary") or note,
                }
            )
        return out
