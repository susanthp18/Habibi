"""Supervisor floor: the live snapshot (calls, alerts, agents), supervisor actions and alert acks.

Carved from ops_screens.py; the shape is pinned by tests/snapshots/reader_shapes.json.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import text
import db
from agent_core.clock import utc_now
from db_core import _id

logger = logging.getLogger(__name__)


def _floor_agent_card(row: dict[str, Any], fallback_name: str) -> dict[str, str] | None:
    bot_id = row.get("handler_bot_id")
    if not bot_id:
        return None
    # `handler_name` is already COALESCE(u.name, b.name, ...) from the bots
    # row -- not the Python constant, which a renamed or cloned card never
    # told about its name.
    return {"botId": str(bot_id), "displayName": fallback_name}


def _rel_age(ts: datetime | str | None) -> str:
    if ts is None:
        return "—"
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return ts
    if not isinstance(ts, datetime):
        return "—"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    secs = max(0, int((utc_now() - ts).total_seconds()))
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _severity_num(raw: str | None) -> int:
    v = (raw or "medium").strip().lower()
    if v in {"critical", "high", "3"}:
        return 3
    if v in {"medium", "warn", "2"}:
        return 2
    return 1


_THREAT_MARKERS = (
    "ombudsman",
    "threat",
    "lawyer",
    "rbi",
    "abuse",
    "police",
    "harass",
)


_HIGH_FLAGS = frozenset(
    {
        "auto-escalate",
        "abuse-detected",
        "compliance-miss",
        "missing-recording-disclosure",
        "waiver-blocked",
        "authority-cap-exceeded",
        "hours-breach",
        "identity-before-verify",
        "third-party-leak",
        "opt-out-ignored",
        "missing-mini-miranda",
    }
)


def _recommended_action(
    *,
    channel: str,
    handler_kind: str,
    alert_kind: str | None,
    severity: int,
    reason: str | None,
    pending_handoff: bool,
) -> str:
    if channel in {"whatsapp", "sms"}:
        return "inbox"
    reason_l = (reason or "").lower()
    threat = any(w in reason_l for w in _THREAT_MARKERS)
    if pending_handoff or alert_kind in {"escalation", "silence", "loop_detected"}:
        return "barge"
    if alert_kind == "compliance" or threat:
        return "barge"
    if alert_kind == "sentiment_drop" and (severity >= 3 or handler_kind == "bot"):
        return "barge" if handler_kind == "bot" or threat else "whisper"
    if alert_kind == "sentiment_drop" and handler_kind == "human":
        return "whisper"
    if alert_kind == "long_hold":
        return "listen"
    return "listen"


def _composite_risk(
    *,
    sentiment: float,
    trend: float,
    flags: list[str],
    alert_max_sev: int,
    duration_sec: int,
    customer_risk: str | None,
    pending_handoff: bool,
    dnd: bool,
) -> str:
    score = 0
    if sentiment <= -0.35:
        score += 3
    elif sentiment <= -0.1:
        score += 1
    if trend <= -0.15:
        score += 2
    if alert_max_sev >= 3:
        score += 3
    elif alert_max_sev >= 2:
        score += 1
    if any(f in _HIGH_FLAGS for f in flags):
        score += 3
    if pending_handoff:
        score += 2
    if duration_sec >= 480:
        score += 1
    if (customer_risk or "").lower() in {"critical", "high"}:
        score += 1
    if dnd:
        score += 1
    if score >= 5:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def _initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _channel(raw: str | None) -> str:
    c = (raw or "voice").lower()
    if c in {"voice", "whatsapp", "sms"}:
        return c
    if c in {"chat", "email"}:
        return "whatsapp"
    return "voice"


@dataclass
class FloorBuild:
    """One floor snapshot: the rows ``_floor_reads`` fetches in one connection and
    what ``_floor_shape`` makes of them. The bodies are what
    ``get_floor_snapshot`` was; ``tests/snapshots/reader_shapes.json`` pins the
    key tree.
    """

    tenant: str
    alert_sev_by: dict[str, int] = field(default_factory=dict)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    alerts_by_call: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    audio_by: dict[str, bool] = field(default_factory=dict)
    authority_by: dict[str, dict[str, Any]] = field(default_factory=dict)
    flags_by: dict[str, list[str]] = field(default_factory=dict)
    inbox_waiting: Any = None
    last_line_by: dict[str, str] = field(default_factory=dict)
    live_qa_by: dict[str, dict[str, Any]] = field(default_factory=dict)
    offer_by: dict[str, dict[str, Any]] = field(default_factory=dict)
    presence_rows: list[dict[str, Any]] = field(default_factory=list)
    queue_row: Any = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    trend_by: dict[str, float] = field(default_factory=dict)
    turns_by: dict[str, list[dict[str, str]]] = field(default_factory=dict)


def _floor_reads(st: FloorBuild) -> None:
    """Every query the floor needs, in one connection: live calls, their flags,
    trends, turns, offers, authority and live-QA state, alerts, the queue,
    the inbox backlog and agent presence."""
    tenant = st.tenant

    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT
                      i.id,
                      i.customer_id,
                      i.account_id,
                      i.channel,
                      i.handler_kind,
                      i.handler_user_id,
                      i.handler_bot_id,
                      COALESCE(u.name, b.name, 'Unassigned') AS handler_name,
                      c.name AS customer_name,
                      c.risk AS customer_risk,
                      c.dnd,
                      c.language,
                      a.id AS account_id,
                      a.outstanding,
                      COALESCE(i.primary_intent, i.disposition, i.summary, 'Live session') AS topic,
                      COALESCE(i.avg_sentiment, 0) AS avg_sentiment,
                      COALESCE(
                        EXTRACT(EPOCH FROM (now() - i.started_at))::int,
                        i.duration_sec,
                        0
                      ) AS duration_sec,
                      conv.id AS conversation_id,
                      conv.status AS conversation_status,
                      h.id AS pending_handoff_id,
                      EXTRACT(EPOCH FROM (now() - COALESCE(h.requested_at, h.created_at)))::int
                        AS handoff_wait_sec
                    FROM interactions i
                    JOIN customers c ON c.id = i.customer_id
                    LEFT JOIN accounts a ON a.id = i.account_id
                    LEFT JOIN users u ON u.id = i.handler_user_id
                    LEFT JOIN bots b ON b.id = i.handler_bot_id
                    LEFT JOIN LATERAL (
                      SELECT id, status FROM conversations
                      WHERE interaction_id = i.id
                      ORDER BY created_at DESC LIMIT 1
                    ) conv ON true
                    LEFT JOIN LATERAL (
                      SELECT id, requested_at, created_at FROM interaction_handoffs
                      WHERE interaction_id = i.id
                        AND completed_at IS NULL
                        AND accepted_at IS NULL
                      ORDER BY requested_at DESC NULLS LAST, created_at DESC
                      LIMIT 1
                    ) h ON true
                    WHERE i.tenant_id = :tenant AND i.status = 'active'
                    ORDER BY i.started_at ASC NULLS LAST
                    """
                ),
                {"tenant": tenant},
            )
        )
        ids = [r["id"] for r in rows]
        flags_by: dict[str, list[str]] = {i: [] for i in ids}
        trend_by: dict[str, float] = {i: 0.0 for i in ids}
        turns_by: dict[str, list[dict[str, str]]] = {i: [] for i in ids}
        last_line_by: dict[str, str] = {}
        if ids:
            for fr in db._rows(
                conn.execute(
                    text(
                        """
                        SELECT interaction_id, flag
                        FROM interaction_flags
                        WHERE interaction_id = ANY(:ids)
                        ORDER BY created_at DESC
                        """
                    ),
                    {"ids": ids},
                )
            ):
                bucket = flags_by.setdefault(fr["interaction_id"], [])
                if len(bucket) < 8:
                    bucket.append(fr["flag"])

            scores: dict[str, list[float]] = {}
            for sr in db._rows(
                conn.execute(
                    text(
                        """
                        SELECT interaction_id, score FROM (
                          SELECT interaction_id, score,
                                 ROW_NUMBER() OVER (
                                   PARTITION BY interaction_id
                                   ORDER BY at_sec DESC, created_at DESC
                                 ) AS rn
                          FROM interaction_sentiment
                          WHERE interaction_id = ANY(:ids)
                        ) x WHERE rn <= 2
                        """
                    ),
                    {"ids": ids},
                )
            ):
                scores.setdefault(sr["interaction_id"], []).append(float(sr["score"] or 0))
            for iid, vals in scores.items():
                if len(vals) >= 2:
                    trend_by[iid] = round(vals[0] - vals[1], 3)

            turn_rows = db._rows(
                conn.execute(
                    text(
                        """
                        SELECT interaction_id, speaker, text FROM (
                          SELECT interaction_id, speaker, text, turn_index,
                                 ROW_NUMBER() OVER (
                                   PARTITION BY interaction_id ORDER BY turn_index DESC
                                 ) AS rn
                          FROM interaction_transcript
                          WHERE interaction_id = ANY(:ids)
                        ) x WHERE rn <= 4
                        ORDER BY interaction_id, turn_index
                        """
                    ),
                    {"ids": ids},
                )
            )
            for tr in turn_rows:
                iid = tr["interaction_id"]
                turns_by.setdefault(iid, []).append(
                    {"speaker": tr["speaker"] or "system", "text": (tr["text"] or "")[:240]}
                )
                last_line_by[iid] = (tr["text"] or "—")[:160]

        offer_by: dict[str, dict[str, Any]] = {}
        authority_by: dict[str, dict[str, Any]] = {}
        live_qa_by: dict[str, dict[str, Any]] = {}
        audio_by: dict[str, bool] = {}
        if ids:
            try:
                from agent_core.reco import policy as offer_policy

                offer_by = offer_policy.snapshots_for_interactions(
                    conn, tenant_id=tenant, interaction_ids=ids
                )
            except Exception:
                logger.exception("floor offer policy snapshots failed")
            try:
                from agent_core.authority import policy as authority_policy

                authority_by = authority_policy.snapshots_for_interactions(
                    conn, tenant_id=tenant, interaction_ids=ids
                )
            except Exception:
                logger.exception("floor authority policy snapshots failed")
            try:
                from agent_core.live_qa import policy as live_qa_policy

                live_qa_by = live_qa_policy.snapshots_for_interactions(
                    conn, tenant_id=tenant, interaction_ids=ids
                )
                audio_by = live_qa_policy.audio_capable_map(conn, ids)
            except Exception:
                logger.exception("floor live_qa snapshots failed")

        alerts = db._rows(
            conn.execute(
                text(
                    """
                    SELECT la.id, la.interaction_id, la.kind, la.severity, la.reason, la.created_at
                    FROM live_alerts la
                    JOIN interactions i ON i.id = la.interaction_id
                    WHERE i.tenant_id = :tenant
                      AND la.acknowledged_at IS NULL
                    ORDER BY la.created_at DESC
                    LIMIT 40
                    """
                ),
                {"tenant": tenant},
            )
        )
        alert_sev_by: dict[str, int] = {}
        alerts_by_call: dict[str, list[dict[str, Any]]] = {}
        for a in alerts:
            sev = _severity_num(a["severity"])
            iid = a["interaction_id"]
            alert_sev_by[iid] = max(alert_sev_by.get(iid, 0), sev)
            alerts_by_call.setdefault(iid, []).append(a)

        queue_row = conn.execute(
            text(
                """
                SELECT
                  count(*)::int AS depth,
                  COALESCE(
                    max(EXTRACT(EPOCH FROM (now() - COALESCE(h.requested_at, h.created_at))))::int,
                    0
                  ) AS longest_wait
                FROM interaction_handoffs h
                JOIN interactions i ON i.id = h.interaction_id
                WHERE i.tenant_id = :tenant
                  AND h.accepted_at IS NULL
                  AND h.completed_at IS NULL
                """
            ),
            {"tenant": tenant},
        ).mappings().one()
        inbox_waiting = conn.execute(
            text(
                """
                SELECT count(*) FROM conversations conv
                JOIN interactions i ON i.id = conv.interaction_id
                WHERE i.tenant_id = :tenant AND conv.status = 'needs_human'
                """
            ),
            {"tenant": tenant},
        ).scalar() or 0

        presence_rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT
                      ap.user_id,
                      u.name,
                      ap.status,
                      ap.since_at,
                      ap.interaction_id,
                      c.name AS customer_name
                    FROM agent_presence ap
                    JOIN users u ON u.id = ap.user_id
                    LEFT JOIN interactions i ON i.id = ap.interaction_id
                    LEFT JOIN customers c ON c.id = i.customer_id
                    WHERE u.tenant_id = :tenant AND u.status = 'active'
                    ORDER BY u.name
                    """
                ),
                {"tenant": tenant},
            )
        )

    st.alert_sev_by = alert_sev_by
    st.alerts = alerts
    st.alerts_by_call = alerts_by_call
    st.audio_by = audio_by
    st.authority_by = authority_by
    st.flags_by = flags_by
    st.inbox_waiting = inbox_waiting
    st.last_line_by = last_line_by
    st.live_qa_by = live_qa_by
    st.offer_by = offer_by
    st.presence_rows = presence_rows
    st.queue_row = queue_row
    st.rows = rows
    st.trend_by = trend_by
    st.turns_by = turns_by


def _floor_shape(st: FloorBuild) -> dict[str, Any]:
    """The call cards, the alerts, the agents, the stats, and the response the floor renders."""
    alert_sev_by = st.alert_sev_by
    alerts = st.alerts
    alerts_by_call = st.alerts_by_call
    audio_by = st.audio_by
    authority_by = st.authority_by
    flags_by = st.flags_by
    inbox_waiting = st.inbox_waiting
    last_line_by = st.last_line_by
    live_qa_by = st.live_qa_by
    offer_by = st.offer_by
    presence_rows = st.presence_rows
    queue_row = st.queue_row
    rows = st.rows
    trend_by = st.trend_by
    turns_by = st.turns_by

    on_call_users = {
        r["handler_user_id"]: r for r in rows if r.get("handler_user_id") and r.get("handler_kind") == "human"
    }

    calls: list[dict[str, Any]] = []
    for r in rows:
        iid = r["id"]
        name = r["handler_name"] or "Unassigned"
        sent = float(r["avg_sentiment"] or 0)
        trend = trend_by.get(iid, 0.0)
        flags = flags_by.get(iid, [])
        pending = bool(r.get("pending_handoff_id"))
        channel = _channel(r["channel"])
        handler_kind = r["handler_kind"] if r["handler_kind"] in {"bot", "human"} else "human"
        duration = max(0, int(r["duration_sec"] or 0))
        top_alert = (alerts_by_call.get(iid) or [None])[0]
        action = _recommended_action(
            channel=channel,
            handler_kind=handler_kind,
            alert_kind=(top_alert or {}).get("kind") if top_alert else None,
            severity=_severity_num((top_alert or {}).get("severity")) if top_alert else 0,
            reason=(top_alert or {}).get("reason") if top_alert else None,
            pending_handoff=pending,
        )
        turns = turns_by.get(iid, [])
        last_line = last_line_by.get(iid) or "—"
        calls.append(
            {
                "id": iid,
                "customerId": r["customer_id"],
                "accountId": r["account_id"] or "",
                "conversationId": r.get("conversation_id"),
                "handlerUserId": r.get("handler_user_id"),
                "handlerBotId": r.get("handler_bot_id"),
                "agentCard": _floor_agent_card(r, name) if handler_kind == "bot" else None,
                "handler": {
                    "kind": handler_kind,
                    "name": name,
                    "initials": _initials(name),
                },
                "customer": r["customer_name"] or "Unknown",
                "accountTail": db._account_tail(r["account_id"]) or "----",
                "channel": channel,
                "topic": (r["topic"] or "Live session").strip()[:48],
                "durationSec": duration,
                "sentiment": round(sent, 3),
                "sentimentTrend": trend,
                "risk": _composite_risk(
                    sentiment=sent,
                    trend=trend,
                    flags=flags,
                    alert_max_sev=alert_sev_by.get(iid, 0),
                    duration_sec=duration,
                    customer_risk=r.get("customer_risk"),
                    pending_handoff=pending,
                    dnd=bool(r.get("dnd")),
                ),
                "lastLine": last_line,
                "language": (r["language"] or "EN-IN"),
                "flags": flags,
                "pendingHandoff": pending,
                "outstanding": float(r["outstanding"] or 0),
                "customerRisk": (r.get("customer_risk") or "medium"),
                "dnd": bool(r.get("dnd")),
                "recentTurns": turns,
                "recommendedAction": action,
                "offerPolicy": offer_by.get(iid),
                "authorityPolicy": authority_by.get(iid),
                "liveQa": {**(live_qa_by.get(iid) or {}), "audioCapable": bool(audio_by.get(iid))},
            }
        )

    call_by_id = {c["id"]: c for c in calls}
    floor_alerts = []
    for a in alerts:
        call = call_by_id.get(a["interaction_id"])
        sev = _severity_num(a["severity"])
        kind = a["kind"] or "escalation"
        action = _recommended_action(
            channel=call["channel"] if call else "voice",
            handler_kind=call["handler"]["kind"] if call else "bot",
            alert_kind=kind,
            severity=sev,
            reason=a["reason"],
            pending_handoff=bool(call and call["pendingHandoff"]),
        )
        floor_alerts.append(
            {
                "id": a["id"],
                "callId": a["interaction_id"],
                "kind": kind,
                "severity": sev,
                "reason": a["reason"] or kind,
                "at": _rel_age(a["created_at"]),
                "recommendedAction": action,
            }
        )

    agents = []
    available = on_call = 0
    for p in presence_rows:
        uid = p["user_id"]
        live = on_call_users.get(uid)
        derived = "on_call" if live else (p["status"] or "offline")
        if derived == "on_call":
            on_call += 1
        elif derived == "available":
            available += 1
        agents.append(
            {
                "userId": uid,
                "name": p["name"] or uid,
                "initials": _initials(p["name"] or uid),
                "status": derived,
                "sinceAt": p["since_at"].isoformat() if hasattr(p["since_at"], "isoformat") else str(p["since_at"] or ""),
                "interactionId": (live["id"] if live else p.get("interaction_id")),
                "customer": (live["customer_name"] if live else p.get("customer_name")),
            }
        )

    n = len(calls)
    avg = sum(c["sentiment"] for c in calls) / n if n else 0.0
    critical = sum(1 for a in floor_alerts if a["severity"] >= 3)
    bot_at_risk = sum(1 for c in calls if c["handler"]["kind"] == "bot" and c["risk"] != "low")
    stats = {
        "callsInProgress": n,
        "avgSentiment": round(avg, 2),
        "criticalAlerts": critical,
        "queueDepth": int(queue_row["depth"] or 0) + int(inbox_waiting),
        "agentsAvailable": available,
        "agentsOnCall": on_call,
        "botAtRisk": bot_at_risk,
        "longestWaitSec": int(queue_row["longest_wait"] or 0),
    }
    return {"calls": calls, "alerts": floor_alerts, "stats": stats, "agents": agents}


def get_floor_snapshot() -> dict[str, Any]:
    tenant = db.current_tenant()

    st = FloorBuild(
        tenant=tenant,
    )
    _floor_reads(st)
    return _floor_shape(st)


def create_supervisor_action(payload: dict[str, Any]) -> dict[str, Any]:
    interaction_id = (payload.get("interactionId") or "").strip()
    action = (payload.get("action") or "").strip()
    if not interaction_id or not action:
        raise ValueError("interactionId_and_action_required")
    note = (payload.get("note") or "").strip() or None
    tenant = db.current_tenant()
    with db.engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, handler_user_id, handler_bot_id
                FROM interactions
                WHERE id = :id AND tenant_id = :tenant
                """
            ),
            {"id": interaction_id, "tenant": tenant},
        ).fetchone()
        if row is None:
            raise KeyError("interaction_not_found")
        aid = _id("sup")
        conn.execute(
            text(
                """
                INSERT INTO supervisor_actions (
                  id, interaction_id, supervisor_user_id, action,
                  target_user_id, target_bot_id, note, created_at
                ) VALUES (
                  :id, :iid, :sup, :action, :tuid, :tbid, :note, now()
                )
                """
            ),
            {
                "id": aid,
                "iid": interaction_id,
                "sup": db._actor_user_id(),
                "action": action,
                "tuid": row._mapping["handler_user_id"],
                "tbid": row._mapping["handler_bot_id"],
                "note": note,
            },
        )
        # Audit-only for listen/whisper. Barge / force_handoff reassigns handler
        # and ensures a handoff row exists so /handoff/{id} can open.
        if action in {"barge", "force_handoff"}:
            uid = db._actor_user_id()
            mapping = row._mapping
            conn.execute(
                text(
                    """
                    UPDATE interactions
                    SET handler_kind = 'human',
                        handler_user_id = :uid,
                        handler_bot_id = NULL,
                        updated_at = now()
                    WHERE id = :id AND tenant_id = :tenant
                    """
                ),
                {"id": interaction_id, "uid": uid, "tenant": tenant},
            )
            open_ho = conn.execute(
                text(
                    """
                    SELECT id FROM interaction_handoffs
                    WHERE interaction_id = :iid AND completed_at IS NULL
                    ORDER BY requested_at DESC NULLS LAST, created_at DESC
                    LIMIT 1
                    """
                ),
                {"iid": interaction_id},
            ).fetchone()
            if open_ho is not None:
                conn.execute(
                    text(
                        """
                        UPDATE interaction_handoffs
                        SET to_user_id = :uid,
                            accepted_at = COALESCE(accepted_at, now())
                        WHERE id = :id
                        """
                    ),
                    {"uid": uid, "id": open_ho._mapping["id"]},
                )
            else:
                from_kind = "bot" if mapping["handler_bot_id"] else "human"
                conn.execute(
                    text(
                        """
                        INSERT INTO interaction_handoffs (
                          id, interaction_id, from_kind, from_user_id, from_bot_id,
                          to_kind, to_user_id, reason, queue,
                          requested_at, accepted_at, created_at
                        ) VALUES (
                          :id, :iid, :from_kind, :from_user, :from_bot,
                          'human', :uid, 'routing_rule', 'Supervisor barge',
                          now(), now(), now()
                        )
                        """
                    ),
                    {
                        "id": _id("ho"),
                        "iid": interaction_id,
                        "from_kind": from_kind,
                        "from_user": mapping["handler_user_id"] if from_kind == "human" else None,
                        "from_bot": mapping["handler_bot_id"],
                        "uid": uid,
                    },
                )
    audio_joined = False
    if action in {"barge", "force_handoff"}:
        try:
            from agent_core.live_qa.enact import barge_audio

            result = barge_audio(interaction_id, reason=action)
            audio_joined = bool(result.get("audio"))
        except Exception:
            logger.exception("supervisor barge audio failed for %s", interaction_id)
        try:
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE supervisor_actions
                        SET audio_joined = :joined
                        WHERE id = :id
                        """
                    ),
                    {"id": aid, "joined": audio_joined},
                )
        except Exception:
            logger.exception("supervisor audio_joined update failed for %s", aid)
        try:
            from agent_core.live_qa import decisions as live_decisions

            pending = live_decisions.pending_auto_barge(interaction_id)
            if pending:
                live_decisions.mark_enacted(pending.get("id"), ref=aid)
        except Exception:
            logger.exception("live_qa mark_enacted from supervisor failed")
    return {
        "id": aid,
        "ok": True,
        "action": action,
        "interactionId": interaction_id,
        "audioJoined": audio_joined,
    }


def ack_floor_alert(alert_id: str) -> dict[str, Any]:
    tenant = db.current_tenant()
    with db.engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE live_alerts la
                SET acknowledged_by_user_id = :uid, acknowledged_at = now()
                FROM interactions i
                WHERE la.id = :id
                  AND la.acknowledged_at IS NULL
                  AND la.interaction_id = i.id
                  AND i.tenant_id = :tenant
                """
            ),
            {"id": alert_id, "uid": db._actor_user_id(), "tenant": tenant},
        )
        if not result.rowcount:
            raise KeyError("alert_not_found")
    return {"id": alert_id, "ok": True}
