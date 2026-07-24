"""Floor / Webhooks / Integrations screen-shaped accessors.

Kept out of db.py on purpose — these are ops-admin surfaces, not CRM core.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text

import db

TENANT_ID = db.TENANT_ID

# UI event catalog → persisted event_types.name (same strings; seed may differ).
EVENT_CATALOG: list[dict[str, str]] = [
    {"key": "call.started", "category": "Calls", "description": "Caller connected to the voice bot."},
    {"key": "call.completed", "category": "Calls", "description": "Hangup with duration and disposition."},
    {"key": "call.summary.ready", "category": "Calls", "description": "Structured summary ready for CRM writeback."},
    {"key": "call.escalated", "category": "Calls", "description": "Bot triggered a human handoff."},
    {"key": "promise.created", "category": "Promises", "description": "Promise-to-pay captured."},
    {"key": "promise.kept", "category": "Promises", "description": "Promise marked kept."},
    {"key": "promise.broken", "category": "Promises", "description": "Promise marked broken."},
    {"key": "dispute.raised", "category": "Disputes", "description": "Dispute opened."},
    {"key": "dispute.resolved", "category": "Disputes", "description": "Dispute resolved or rejected."},
    {"key": "payment.updated", "category": "Payments", "description": "Payment status changed."},
    {"key": "payment.reversed", "category": "Payments", "description": "Payment reversed."},
    {"key": "consent.dnd.updated", "category": "Consent", "description": "DND / contact window changed."},
    {"key": "consent.opted_out", "category": "Consent", "description": "Customer opted out of a channel."},
    {"key": "bot.handoff", "category": "Bot", "description": "Bot→human handoff event."},
    {"key": "bot.compliance.flag", "category": "Bot", "description": "Compliance flag raised on a turn."},
]

# Live-stack providers only (env-backed). CBS / Pipecat-as-connector stay mock-only.
LIVE_PROVIDER_IDS = (
    "azure_openai",
    "azure_speech_stt",
    "azure_speech_tts",
    "twilio",
    "whatsapp",
)

_PROVIDER_META: dict[str, dict[str, Any]] = {
    "azure_openai": {
        "name": "Azure OpenAI",
        "vendor": "Microsoft Azure",
        "category": "Voice AI",
        "capability": "LLM — reasoning core",
        "description": "GPT deployment powering reasoning, RAG synthesis, and tool-calling.",
        "docsUrl": "https://learn.microsoft.com/azure/ai-services/openai/",
        "brandInitial": "Az",
        "brandColor": "bg-blue-100 text-blue-700",
        "capabilities": ["streaming", "tool-calling", "JSON mode"],
        "fields": [
            {"key": "endpoint", "label": "Endpoint", "secret": False},
            {"key": "apiKey", "label": "API key", "secret": True},
            {"key": "deployment", "label": "Deployment name", "secret": False},
            {"key": "apiVersion", "label": "API version", "secret": False},
        ],
        "env_map": {
            "endpoint": "AZURE_OPENAI_ENDPOINT",
            "apiKey": "AZURE_OPENAI_API_KEY",
            "deployment": "AZURE_OPENAI_CHAT_DEPLOYMENT",
            "apiVersion": "AZURE_OPENAI_API_VERSION",
        },
    },
    "azure_speech_stt": {
        "name": "Azure Speech STT",
        "vendor": "Microsoft Azure",
        "category": "Voice AI",
        "capability": "Speech-to-text",
        "description": "Realtime transcription for voice calls.",
        "docsUrl": "https://learn.microsoft.com/azure/ai-services/speech-service/",
        "brandInitial": "ST",
        "brandColor": "bg-sky-100 text-sky-700",
        "capabilities": ["streaming", "multi-language"],
        "fields": [
            {"key": "speechKey", "label": "Speech key", "secret": True},
            {"key": "region", "label": "Region", "secret": False},
            {"key": "language", "label": "Default language", "secret": False},
        ],
        "env_map": {
            "speechKey": "AZURE_SPEECH_KEY",
            "region": "AZURE_SPEECH_REGION",
            "language": "AZURE_SPEECH_LANGUAGE",
        },
    },
    "azure_speech_tts": {
        "name": "Azure Speech TTS",
        "vendor": "Microsoft Azure",
        "category": "Voice AI",
        "capability": "Text-to-speech",
        "description": "Neural voices for bot replies.",
        "docsUrl": "https://learn.microsoft.com/azure/ai-services/speech-service/",
        "brandInitial": "TT",
        "brandColor": "bg-indigo-100 text-indigo-700",
        "capabilities": ["neural voices", "SSML"],
        "fields": [
            {"key": "speechKey", "label": "Speech key", "secret": True},
            {"key": "region", "label": "Region", "secret": False},
            {"key": "defaultVoice", "label": "Default voice", "secret": False},
        ],
        "env_map": {
            "speechKey": "AZURE_SPEECH_KEY",
            "region": "AZURE_SPEECH_REGION",
            "defaultVoice": "AZURE_SPEECH_TTS_VOICE_DEFAULT",
        },
    },
    "twilio": {
        "name": "Twilio",
        "vendor": "Twilio",
        "category": "Telephony",
        "capability": "PSTN / Media Streams",
        "description": "Inbound/outbound voice transport for the collections line.",
        "docsUrl": "https://www.twilio.com/docs",
        "brandInitial": "Tw",
        "brandColor": "bg-rose-100 text-rose-700",
        "capabilities": ["media streams", "PSTN"],
        "fields": [
            {"key": "accountSid", "label": "Account SID", "secret": False},
            {"key": "authToken", "label": "Auth token", "secret": True},
        ],
        "env_map": {
            "accountSid": "TWILIO_ACCOUNT_SID",
            "authToken": "TWILIO_AUTH_TOKEN",
        },
    },
    "whatsapp": {
        "name": "WhatsApp Cloud API",
        "vendor": "Meta",
        "category": "Messaging",
        "capability": "WhatsApp business messaging",
        "description": "Inbound webhook + outbound agent/bot messages.",
        "docsUrl": "https://developers.facebook.com/docs/whatsapp/",
        "brandInitial": "WA",
        "brandColor": "bg-emerald-100 text-emerald-700",
        "capabilities": ["webhooks", "templates"],
        "fields": [
            {"key": "phoneNumberId", "label": "Phone number ID", "secret": False},
            {"key": "wabaId", "label": "WABA ID", "secret": False},
            {"key": "accessToken", "label": "System-user token", "secret": True},
        ],
        "env_map": {
            "phoneNumberId": "WHATSAPP_PHONE_NUMBER_ID",
            "wabaId": "WHATSAPP_WABA_ID",
            "accessToken": "WHATSAPP_TOKEN",
        },
    },
}


def _sid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _mask_secret(present: bool) -> str:
    return "••••••••••••" if present else ""


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
    secs = max(0, int((datetime.now(timezone.utc) - ts).total_seconds()))
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


def _risk_from_sentiment(avg: float | None) -> str:
    s = float(avg or 0)
    if s <= -0.35:
        return "high"
    if s <= -0.1:
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


# ── Floor ────────────────────────────────────────────────────────────────────


def get_floor_snapshot() -> dict[str, Any]:
    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT
                      i.id,
                      i.channel,
                      i.handler_kind,
                      COALESCE(u.name, b.name, 'Unassigned') AS handler_name,
                      c.name AS customer_name,
                      RIGHT(COALESCE(a.id, ''), 4) AS account_tail,
                      COALESCE(i.primary_intent, i.disposition, i.summary, 'Live session') AS topic,
                      COALESCE(i.avg_sentiment, 0) AS avg_sentiment,
                      i.started_at,
                      COALESCE(
                        EXTRACT(EPOCH FROM (now() - i.started_at))::int,
                        i.duration_sec,
                        0
                      ) AS duration_sec,
                      c.language,
                      (
                        SELECT t.text FROM interaction_transcript t
                        WHERE t.interaction_id = i.id
                        ORDER BY t.turn_index DESC LIMIT 1
                      ) AS last_line
                    FROM interactions i
                    JOIN customers c ON c.id = i.customer_id
                    LEFT JOIN accounts a ON a.id = i.account_id
                    LEFT JOIN users u ON u.id = i.handler_user_id
                    LEFT JOIN bots b ON b.id = i.handler_bot_id
                    WHERE i.tenant_id = :tenant AND i.status = 'active'
                    ORDER BY i.started_at ASC NULLS LAST
                    """
                ),
                {"tenant": TENANT_ID},
            )
        )
        alerts = db._rows(
            conn.execute(
                text(
                    """
                    SELECT la.id, la.interaction_id, la.kind, la.severity, la.reason, la.created_at
                    FROM live_alerts la
                    JOIN interactions i ON i.id = la.interaction_id
                    WHERE i.tenant_id = :tenant
                      AND la.acknowledged_at IS NULL
                      AND la.kind IN ('sentiment_drop','compliance','long_hold','escalation')
                    ORDER BY la.created_at DESC
                    LIMIT 40
                    """
                ),
                {"tenant": TENANT_ID},
            )
        )
        queue_depth = conn.execute(
            text(
                """
                SELECT count(*) FROM interactions
                WHERE tenant_id = :tenant AND status = 'active' AND handler_kind = 'human'
                """
            ),
            {"tenant": TENANT_ID},
        ).scalar() or 0

    calls: list[dict[str, Any]] = []
    for r in rows:
        name = r["handler_name"] or "Unassigned"
        sent = float(r["avg_sentiment"] or 0)
        topic = (r["topic"] or "Live session").strip()[:48]
        calls.append(
            {
                "id": r["id"],
                "handler": {
                    "kind": r["handler_kind"] if r["handler_kind"] in {"bot", "human"} else "human",
                    "name": name,
                    "initials": _initials(name),
                },
                "customer": r["customer_name"] or "Unknown",
                "accountTail": (r["account_tail"] or "----")[-4:],
                "channel": _channel(r["channel"]),
                "topic": topic,
                "durationSec": max(0, int(r["duration_sec"] or 0)),
                "sentiment": round(sent, 3),
                "sentimentTrend": 0.0,
                "risk": _risk_from_sentiment(sent),
                "lastLine": (r["last_line"] or "—")[:160],
                "language": (r["language"] or "EN-IN"),
            }
        )

    floor_alerts = [
        {
            "id": a["id"],
            "callId": a["interaction_id"],
            "kind": a["kind"],
            "severity": _severity_num(a["severity"]),
            "reason": a["reason"] or a["kind"],
            "at": _rel_age(a["created_at"]),
        }
        for a in alerts
    ]

    n = len(calls)
    avg = sum(c["sentiment"] for c in calls) / n if n else 0.0
    humans = sum(1 for c in calls if c["handler"]["kind"] == "human")
    bots = n - humans
    stats = {
        "callsInProgress": n,
        "avgSentiment": round(avg, 2),
        "escalationRate": round(humans / n, 2) if n else 0.0,
        "queueDepth": int(queue_depth),
        "botContainment": round(bots / n, 2) if n else 0.0,
        "longestWaitSec": max((c["durationSec"] for c in calls), default=0),
    }
    return {"calls": calls, "alerts": floor_alerts, "stats": stats}


def create_supervisor_action(payload: dict[str, Any]) -> dict[str, Any]:
    interaction_id = payload["interactionId"]
    action = payload["action"]
    note = (payload.get("note") or "").strip() or None
    with db.engine.begin() as conn:
        row = conn.execute(
            text("SELECT id, handler_user_id, handler_bot_id FROM interactions WHERE id = :id"),
            {"id": interaction_id},
        ).fetchone()
        if row is None:
            raise KeyError("interaction_not_found")
        aid = _sid("sup")
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
        # Audit-only for listen/whisper. Barge / force_handoff reassigns handler when possible.
        if action in {"barge", "force_handoff"}:
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
                {"id": interaction_id, "uid": db._actor_user_id()},
            )
    return {"id": aid, "ok": True, "action": action, "interactionId": interaction_id}


def ack_floor_alert(alert_id: str) -> dict[str, Any]:
    with db.engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE live_alerts
                SET acknowledged_by_user_id = :uid, acknowledged_at = now()
                WHERE id = :id AND acknowledged_at IS NULL
                """
            ),
            {"id": alert_id, "uid": db._actor_user_id()},
        )
        if not result.rowcount:
            raise KeyError("alert_not_found")
    return {"id": alert_id, "ok": True}


# ── Webhooks ─────────────────────────────────────────────────────────────────


def _ensure_event_type(conn: Any, key: str) -> str:
    eid = f"evt-{key.replace('.', '-')}"
    conn.execute(
        text(
            """
            INSERT INTO event_types (id, name, description, created_at, updated_at)
            VALUES (:id, :name, :desc, now(), now())
            ON CONFLICT (name) DO NOTHING
            """
        ),
        {"id": eid, "name": key, "desc": next((e["description"] for e in EVENT_CATALOG if e["key"] == key), key)},
    )
    row = conn.execute(text("SELECT id FROM event_types WHERE name = :n"), {"n": key}).fetchone()
    if row is None:
        raise RuntimeError(f"event_type_missing:{key}")
    return row[0]


def list_event_types() -> list[dict[str, Any]]:
    return [
        {
            "key": e["key"],
            "category": e["category"],
            "description": e["description"],
            "sample": {"event": e["key"], "tenant": TENANT_ID, "at": datetime.now(timezone.utc).isoformat()},
        }
        for e in EVENT_CATALOG
    ]


def _endpoint_contract(conn: Any, endpoint_id: str) -> dict[str, Any] | None:
    row = db._one(
        conn.execute(
            text(
                """
                SELECT id, target_system, url, status, signing_algorithm, secret_ref,
                       created_at, name
                FROM webhook_endpoints
                WHERE id = :id AND tenant_id = :tenant
                """
            ),
            {"id": endpoint_id, "tenant": TENANT_ID},
        )
    )
    if row is None:
        # name column may not exist yet on older DBs — fall back.
        try:
            row = db._one(
                conn.execute(
                    text(
                        """
                        SELECT id, target_system, url, status, signing_algorithm, secret_ref, created_at
                        FROM webhook_endpoints
                        WHERE id = :id AND tenant_id = :tenant
                        """
                    ),
                    {"id": endpoint_id, "tenant": TENANT_ID},
                )
            )
        except Exception:
            row = None
    if row is None:
        return None

    headers = db._rows(
        conn.execute(
            text(
                """
                SELECT header_key AS key, header_value AS value
                FROM webhook_endpoint_headers WHERE endpoint_id = :id
                ORDER BY header_key
                """
            ),
            {"id": endpoint_id},
        )
    )
    retry = db._one(
        conn.execute(
            text(
                """
                SELECT max_attempts, backoff_strategy, max_event_age_sec
                FROM webhook_retry_policies WHERE endpoint_id = :id
                """
            ),
            {"id": endpoint_id},
        )
    )
    events = [
        r["name"]
        for r in db._rows(
            conn.execute(
                text(
                    """
                    SELECT et.name
                    FROM webhook_subscriptions ws
                    JOIN event_types et ON et.id = ws.event_type_id
                    WHERE ws.endpoint_id = :id
                    ORDER BY et.name
                    """
                ),
                {"id": endpoint_id},
            )
        )
    ]
    created = row.get("created_at")
    created_ms = int(created.timestamp() * 1000) if isinstance(created, datetime) else int(time.time() * 1000)
    name = row.get("name") or row["target_system"] or endpoint_id
    secret_ref = row.get("secret_ref") or ""
    return {
        "id": row["id"],
        "name": name,
        "url": row["url"],
        "target": row["target_system"],
        "status": row["status"],
        "events": events,
        "algo": row.get("signing_algorithm") or "HMAC-SHA256",
        "secret": _mask_secret(bool(secret_ref)),
        "secretRef": secret_ref,
        "retry": {
            "attempts": int((retry or {}).get("max_attempts") or 3),
            "backoff": (retry or {}).get("backoff_strategy") or "exponential",
            "maxAgeHours": int(((retry or {}).get("max_event_age_sec") or 86400) // 3600),
        },
        "headers": headers,
        "createdAt": created_ms,
    }


def list_webhook_endpoints() -> list[dict[str, Any]]:
    with db.engine.connect() as conn:
        try:
            ids = [
                r["id"]
                for r in db._rows(
                    conn.execute(
                        text(
                            """
                            SELECT id FROM webhook_endpoints
                            WHERE tenant_id = :tenant
                            ORDER BY created_at DESC
                            """
                        ),
                        {"tenant": TENANT_ID},
                    )
                )
            ]
        except Exception:
            return []
        return [ep for eid in ids if (ep := _endpoint_contract(conn, eid))]


def _upsert_endpoint_children(
    conn: Any,
    endpoint_id: str,
    *,
    events: list[str],
    headers: list[dict[str, str]],
    retry: dict[str, Any],
) -> None:
    conn.execute(text("DELETE FROM webhook_subscriptions WHERE endpoint_id = :id"), {"id": endpoint_id})
    for key in events:
        et_id = _ensure_event_type(conn, key)
        conn.execute(
            text(
                """
                INSERT INTO webhook_subscriptions (endpoint_id, event_type_id, created_at)
                VALUES (:eid, :et, now())
                ON CONFLICT DO NOTHING
                """
            ),
            {"eid": endpoint_id, "et": et_id},
        )
    conn.execute(text("DELETE FROM webhook_endpoint_headers WHERE endpoint_id = :id"), {"id": endpoint_id})
    for h in headers:
        key = (h.get("key") or "").strip()
        val = (h.get("value") or "").strip()
        if not key:
            continue
        conn.execute(
            text(
                """
                INSERT INTO webhook_endpoint_headers (id, endpoint_id, header_key, header_value, created_at)
                VALUES (:id, :eid, :k, :v, now())
                """
            ),
            {"id": _sid("whh"), "eid": endpoint_id, "k": key, "v": val},
        )
    attempts = int(retry.get("attempts") or 3)
    backoff = retry.get("backoff") or "exponential"
    max_age = int(retry.get("maxAgeHours") or 24) * 3600
    conn.execute(text("DELETE FROM webhook_retry_policies WHERE endpoint_id = :id"), {"id": endpoint_id})
    conn.execute(
        text(
            """
            INSERT INTO webhook_retry_policies (
              id, endpoint_id, max_attempts, backoff_strategy, max_event_age_sec, created_at, updated_at
            ) VALUES (:id, :eid, :a, :b, :age, now(), now())
            """
        ),
        {"id": _sid("whr"), "eid": endpoint_id, "a": attempts, "b": backoff, "age": max_age},
    )


def create_webhook_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    eid = payload.get("id") or f"wh_{uuid.uuid4().hex[:8]}"
    secret_plain = secrets.token_urlsafe(24)
    secret_ref = f"vault://local/{eid}"
    with db.engine.begin() as conn:
        # Ensure tenant exists for FK
        conn.execute(
            text(
                """
                INSERT INTO tenants (id, name, created_at, updated_at)
                VALUES (:id, :name, now(), now())
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": TENANT_ID, "name": TENANT_ID},
        )
        try:
            conn.execute(
                text(
                    """
                    INSERT INTO webhook_endpoints (
                      id, tenant_id, target_system, url, status, signing_algorithm,
                      secret_ref, name, created_at, updated_at
                    ) VALUES (
                      :id, :tenant, :target, :url, 'active', :algo,
                      :secret_ref, :name, now(), now()
                    )
                    """
                ),
                {
                    "id": eid,
                    "tenant": TENANT_ID,
                    "target": payload.get("target") or "Custom",
                    "url": payload["url"],
                    "algo": payload.get("algo") or "HMAC-SHA256",
                    "secret_ref": secret_ref,
                    "name": payload.get("name") or payload.get("target") or eid,
                },
            )
        except Exception:
            conn.execute(
                text(
                    """
                    INSERT INTO webhook_endpoints (
                      id, tenant_id, target_system, url, status, signing_algorithm,
                      secret_ref, created_at, updated_at
                    ) VALUES (
                      :id, :tenant, :target, :url, 'active', :algo,
                      :secret_ref, now(), now()
                    )
                    """
                ),
                {
                    "id": eid,
                    "tenant": TENANT_ID,
                    "target": payload.get("target") or "Custom",
                    "url": payload["url"],
                    "algo": payload.get("algo") or "HMAC-SHA256",
                    "secret_ref": secret_ref,
                },
            )
        _upsert_endpoint_children(
            conn,
            eid,
            events=list(payload.get("events") or []),
            headers=list(payload.get("headers") or []),
            retry=dict(payload.get("retry") or {}),
        )
        # Store hashed secret material in a header reserved for local demos only —
        # never return raw after create except once via `secretOnce`.
        conn.execute(
            text(
                """
                INSERT INTO webhook_endpoint_headers (id, endpoint_id, header_key, header_value, created_at)
                VALUES (:id, :eid, :k, :v, now())
                """
            ),
            {
                "id": _sid("whh"),
                "eid": eid,
                "k": "X-Webhook-Secret-SHA256",
                "v": hashlib.sha256(secret_plain.encode()).hexdigest(),
            },
        )
        ep = _endpoint_contract(conn, eid)
    assert ep is not None
    ep["secretOnce"] = secret_plain
    ep["secret"] = _mask_secret(True)
    return ep


def patch_webhook_endpoint(endpoint_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with db.engine.begin() as conn:
        sets: list[str] = []
        params: dict[str, Any] = {"id": endpoint_id, "tenant": TENANT_ID}
        for col, key in [
            ("url", "url"),
            ("target_system", "target"),
            ("status", "status"),
            ("signing_algorithm", "algo"),
            ("name", "name"),
        ]:
            if key in payload and payload[key] is not None:
                sets.append(f"{col} = :{key}")
                params[key] = payload[key]
        if sets:
            sets.append("updated_at = now()")
            try:
                conn.execute(
                    text(
                        f"UPDATE webhook_endpoints SET {', '.join(sets)} "
                        "WHERE id = :id AND tenant_id = :tenant"
                    ),
                    params,
                )
            except Exception:
                # name column may be missing
                sets = [s for s in sets if not s.startswith("name")]
                if sets:
                    conn.execute(
                        text(
                            f"UPDATE webhook_endpoints SET {', '.join(sets)} "
                            "WHERE id = :id AND tenant_id = :tenant"
                        ),
                        params,
                    )
        if any(k in payload for k in ("events", "headers", "retry")):
            cur = _endpoint_contract(conn, endpoint_id)
            if cur is None:
                raise KeyError("endpoint_not_found")
            _upsert_endpoint_children(
                conn,
                endpoint_id,
                events=list(payload.get("events") if "events" in payload else cur["events"]),
                headers=list(payload.get("headers") if "headers" in payload else cur["headers"]),
                retry=dict(payload.get("retry") if "retry" in payload else cur["retry"]),
            )
        ep = _endpoint_contract(conn, endpoint_id)
    if ep is None:
        raise KeyError("endpoint_not_found")
    return ep


def delete_webhook_endpoint(endpoint_id: str) -> None:
    with db.engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM webhook_endpoints WHERE id = :id AND tenant_id = :tenant"),
            {"id": endpoint_id, "tenant": TENANT_ID},
        )
        if not result.rowcount:
            raise KeyError("endpoint_not_found")


def rotate_webhook_secret(endpoint_id: str) -> dict[str, Any]:
    secret_plain = secrets.token_urlsafe(24)
    secret_ref = f"vault://local/{endpoint_id}"
    with db.engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE webhook_endpoints
                SET secret_ref = :ref, updated_at = now()
                WHERE id = :id AND tenant_id = :tenant
                """
            ),
            {"id": endpoint_id, "tenant": TENANT_ID, "ref": secret_ref},
        )
        if not result.rowcount:
            raise KeyError("endpoint_not_found")
        conn.execute(
            text("DELETE FROM webhook_endpoint_headers WHERE endpoint_id = :id AND header_key = :k"),
            {"id": endpoint_id, "k": "X-Webhook-Secret-SHA256"},
        )
        conn.execute(
            text(
                """
                INSERT INTO webhook_endpoint_headers (id, endpoint_id, header_key, header_value, created_at)
                VALUES (:id, :eid, :k, :v, now())
                """
            ),
            {
                "id": _sid("whh"),
                "eid": endpoint_id,
                "k": "X-Webhook-Secret-SHA256",
                "v": hashlib.sha256(secret_plain.encode()).hexdigest(),
            },
        )
        ep = _endpoint_contract(conn, endpoint_id)
    assert ep is not None
    ep["secretOnce"] = secret_plain
    ep["secret"] = _mask_secret(True)
    return ep


def _delivery_contract(row: dict[str, Any], max_attempts: int = 3) -> dict[str, Any]:
    created = row.get("created_at")
    at_ms = int(created.timestamp() * 1000) if isinstance(created, datetime) else int(time.time() * 1000)
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    return {
        "id": row["id"],
        "endpointId": row["endpoint_id"],
        "event": row.get("event_name") or "call.completed",
        "status": row["status"],
        "httpStatus": int(row.get("http_status") or 0),
        "latencyMs": int(row.get("latency_ms") or 0),
        "attempt": int(row.get("attempt_number") or 1),
        "maxAttempts": max_attempts,
        "at": at_ms,
        "payload": payload,
        "responseBody": row.get("response_body"),
    }


def list_webhook_deliveries(endpoint_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    with db.engine.connect() as conn:
        params: dict[str, Any] = {"limit": limit, "tenant": TENANT_ID}
        where = "WHERE e.tenant_id = :tenant"
        if endpoint_id:
            where += " AND d.endpoint_id = :eid"
            params["eid"] = endpoint_id
        rows = db._rows(
            conn.execute(
                text(
                    f"""
                    SELECT d.*, et.name AS event_name, rp.max_attempts
                    FROM webhook_deliveries d
                    JOIN webhook_endpoints e ON e.id = d.endpoint_id
                    LEFT JOIN event_types et ON et.id = d.event_type_id
                    LEFT JOIN webhook_retry_policies rp ON rp.endpoint_id = d.endpoint_id
                    {where}
                    ORDER BY d.created_at DESC
                    LIMIT :limit
                    """
                ),
                params,
            )
        )
    return [_delivery_contract(r, int(r.get("max_attempts") or 3)) for r in rows]


def test_fire_webhook(endpoint_id: str, event_key: str | None = None) -> dict[str, Any]:
    with db.engine.begin() as conn:
        ep = _endpoint_contract(conn, endpoint_id)
        if ep is None:
            raise KeyError("endpoint_not_found")
        if ep["status"] == "paused":
            raise ValueError("endpoint_paused")
        key = event_key or (ep["events"][0] if ep["events"] else "call.completed")
        et_id = _ensure_event_type(conn, key)
        host = urlparse(ep["url"]).hostname or ""
        # Simulated delivery — no real egress from this process (safe for demo/prod UI).
        ok = bool(host) and ep["status"] == "active"
        http_status = 200 if ok else 502
        status = "success" if ok else "server_err"
        latency = 40 + (hash(endpoint_id) % 180)
        did = _sid("dlv")
        payload = {
            "event": key,
            "endpointId": endpoint_id,
            "tenant": TENANT_ID,
            "test": True,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        conn.execute(
            text(
                """
                INSERT INTO webhook_deliveries (
                  id, endpoint_id, event_type_id, payload, response_body,
                  http_status, attempt_number, latency_ms, status, created_at, updated_at
                ) VALUES (
                  :id, :eid, :et, CAST(:payload AS jsonb), :body,
                  :http, 1, :lat, :status, now(), now()
                )
                """
            ),
            {
                "id": did,
                "eid": endpoint_id,
                "et": et_id,
                "payload": json.dumps(payload),
                "body": '{"ok":true,"mode":"simulated"}' if ok else '{"ok":false}',
                "http": http_status,
                "lat": latency,
                "status": status,
            },
        )
        row = {
            "id": did,
            "endpoint_id": endpoint_id,
            "event_name": key,
            "payload": payload,
            "response_body": '{"ok":true,"mode":"simulated"}' if ok else '{"ok":false}',
            "http_status": http_status,
            "attempt_number": 1,
            "latency_ms": latency,
            "status": status,
            "created_at": datetime.now(timezone.utc),
        }
    return _delivery_contract(row, ep["retry"]["attempts"])


def retry_webhook_delivery(delivery_id: str) -> dict[str, Any]:
    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text(
                    """
                    SELECT d.endpoint_id, et.name AS event_name, d.payload
                    FROM webhook_deliveries d
                    LEFT JOIN event_types et ON et.id = d.event_type_id
                    WHERE d.id = :id
                    """
                ),
                {"id": delivery_id},
            )
        )
    if row is None:
        raise KeyError("delivery_not_found")
    return test_fire_webhook(row["endpoint_id"], row.get("event_name"))


# ── Integrations ─────────────────────────────────────────────────────────────


def _env_values(provider_id: str) -> dict[str, str]:
    meta = _PROVIDER_META[provider_id]
    out: dict[str, str] = {}
    for field_key, env_name in meta["env_map"].items():
        raw = (os.getenv(env_name) or "").strip()
        field = next((f for f in meta["fields"] if f["key"] == field_key), None)
        if field and field.get("secret"):
            out[field_key] = _mask_secret(bool(raw))
        else:
            out[field_key] = raw
    return out


def _provider_health(provider_id: str) -> tuple[str, int, bool]:
    meta = _PROVIDER_META[provider_id]
    configured = all(
        (os.getenv(env_name) or "").strip()
        for field in meta["fields"]
        if field.get("secret")
        for env_name in [meta["env_map"].get(field["key"])]
        if env_name
    )
    # Non-secret-only providers (unlikely) — any mapped env counts.
    if not any(f.get("secret") for f in meta["fields"]):
        configured = any((os.getenv(v) or "").strip() for v in meta["env_map"].values())
    enabled_default = configured
    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text(
                    """
                    SELECT enabled, health, latency_ms
                    FROM provider_configs
                    WHERE provider_id = :pid AND tenant_id = :tenant
                    ORDER BY environment DESC
                    LIMIT 1
                    """
                ),
                {"pid": provider_id, "tenant": TENANT_ID},
            )
        )
    if row and row.get("enabled") is not None:
        enabled_default = bool(row["enabled"]) and configured
    if not configured:
        return "unconfigured", 0, False
    health = (row or {}).get("health") or "healthy"
    latency = int((row or {}).get("latency_ms") or 0)
    return health if enabled_default else "unconfigured", latency, enabled_default


def list_providers(environment: str = "sandbox") -> list[dict[str, Any]]:
    env = environment if environment in {"sandbox", "production"} else "sandbox"
    out: list[dict[str, Any]] = []
    for pid in LIVE_PROVIDER_IDS:
        meta = _PROVIDER_META[pid]
        health, latency, enabled = _provider_health(pid)
        values = _env_values(pid)
        region = values.get("region") or ("centralindia" if env == "production" else "eastus")
        per = {
            "values": values,
            "region": region,
            "health": health,
            "latencyMs": latency,
            "enabled": enabled,
            "usageStats": [
                {"label": "Source", "value": "env"},
                {"label": "Secrets", "value": "ops vault"},
                {"label": "Editable", "value": "no"},
            ],
            "costMonth": "—",
            "unitLabel": "ops",
            "credentialsLocked": True,
        }
        out.append(
            {
                "id": pid,
                "name": meta["name"],
                "vendor": meta["vendor"],
                "category": meta["category"],
                "capability": meta["capability"],
                "description": meta["description"],
                "docsUrl": meta["docsUrl"],
                "brandInitial": meta["brandInitial"],
                "brandColor": meta["brandColor"],
                "capabilities": meta["capabilities"],
                "fields": meta["fields"],
                "perEnv": {
                    "sandbox": per if env == "sandbox" else {**per, "enabled": False, "health": "unconfigured"},
                    "production": per if env == "production" else {**per, "enabled": False, "health": "unconfigured"},
                },
            }
        )
        # Mirror same status into both envs for simplicity (env vars are process-wide).
        out[-1]["perEnv"]["sandbox"] = {**per}
        out[-1]["perEnv"]["production"] = {**per}
    return out


def patch_provider_enabled(provider_id: str, environment: str, enabled: bool) -> dict[str, Any]:
    if provider_id not in LIVE_PROVIDER_IDS:
        raise KeyError("provider_not_found")
    env = environment if environment in {"sandbox", "production"} else "sandbox"
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO tenants (id, name, created_at, updated_at)
                VALUES (:id, :name, now(), now())
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": TENANT_ID, "name": TENANT_ID},
        )
        conn.execute(
            text(
                """
                INSERT INTO providers (id, name, category, created_at, updated_at)
                VALUES (:id, :name, :cat, now(), now())
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, updated_at = now()
                """
            ),
            {
                "id": provider_id,
                "name": _PROVIDER_META[provider_id]["name"],
                "cat": _PROVIDER_META[provider_id]["category"],
            },
        )
        cid = f"pcfg-{provider_id}-{env}"
        conn.execute(
            text(
                """
                INSERT INTO provider_configs (
                  id, provider_id, tenant_id, environment, values, health,
                  latency_ms, enabled, credential_ref, created_at, updated_at
                ) VALUES (
                  :id, :pid, :tenant, :env, '{}'::jsonb, :health,
                  0, :enabled, :cref, now(), now()
                )
                ON CONFLICT (id) DO UPDATE SET
                  enabled = EXCLUDED.enabled,
                  updated_at = now()
                """
            ),
            {
                "id": cid,
                "pid": provider_id,
                "tenant": TENANT_ID,
                "env": env,
                "health": "healthy" if enabled else "unconfigured",
                "enabled": enabled,
                "cref": f"env://{provider_id}",
            },
        )
    providers = list_providers(env)
    return next(p for p in providers if p["id"] == provider_id)


def test_provider(provider_id: str, environment: str = "sandbox") -> dict[str, Any]:
    if provider_id not in LIVE_PROVIDER_IDS:
        raise KeyError("provider_not_found")
    env = environment if environment in {"sandbox", "production"} else "sandbox"
    meta = _PROVIDER_META[provider_id]
    t0 = time.perf_counter()
    missing = [
        env_name
        for field in meta["fields"]
        if field.get("secret")
        for env_name in [meta["env_map"].get(field["key"])]
        if env_name and not (os.getenv(env_name) or "").strip()
    ]
    ok = not missing
    latency = int((time.perf_counter() - t0) * 1000) + (12 if ok else 3)
    message = "Connection config present" if ok else f"Missing env: {', '.join(missing)}"
    entry = {
        "id": _sid("itest"),
        "at": datetime.now(timezone.utc).isoformat(),
        "providerId": provider_id,
        "env": env,
        "ok": ok,
        "latencyMs": latency,
        "message": message,
        "payload": None,
    }
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO providers (id, name, category, created_at, updated_at)
                VALUES (:id, :name, :cat, now(), now())
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": provider_id,
                "name": meta["name"],
                "cat": meta["category"],
            },
        )
        cid = f"pcfg-{provider_id}-{env}"
        conn.execute(
            text(
                """
                INSERT INTO provider_configs (
                  id, provider_id, tenant_id, environment, values, health,
                  latency_ms, enabled, credential_ref, created_at, updated_at
                ) VALUES (
                  :id, :pid, :tenant, :env, '{}'::jsonb, :health,
                  :lat, true, :cref, now(), now()
                )
                ON CONFLICT (id) DO UPDATE SET
                  health = EXCLUDED.health,
                  latency_ms = EXCLUDED.latency_ms,
                  updated_at = now()
                """
            ),
            {
                "id": cid,
                "pid": provider_id,
                "tenant": TENANT_ID,
                "env": env,
                "health": "healthy" if ok else "degraded",
                "lat": latency,
                "cref": f"env://{provider_id}",
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO integration_test_logs (
                  id, config_id, status, latency_ms, payload_summary, error, created_at
                ) VALUES (
                  :id, :cid, :status, :lat, CAST(:payload AS jsonb), :err, now()
                )
                """
            ),
            {
                "id": entry["id"],
                "cid": cid,
                "status": "ok" if ok else "error",
                "lat": latency,
                "payload": json.dumps({"message": message}),
                "err": None if ok else message,
            },
        )
    return entry


def list_provider_test_logs(provider_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT l.id, l.status, l.latency_ms, l.error, l.created_at, l.payload_summary,
                           c.environment, c.provider_id
                    FROM integration_test_logs l
                    JOIN provider_configs c ON c.id = l.config_id
                    WHERE c.provider_id = :pid AND c.tenant_id = :tenant
                    ORDER BY l.created_at DESC
                    LIMIT :limit
                    """
                ),
                {"pid": provider_id, "tenant": TENANT_ID, "limit": limit},
            )
        )
    out = []
    for r in rows:
        at = r["created_at"]
        out.append(
            {
                "id": r["id"],
                "at": at.isoformat() if isinstance(at, datetime) else str(at),
                "providerId": r["provider_id"],
                "env": r["environment"],
                "ok": r["status"] == "ok",
                "latencyMs": int(r["latency_ms"] or 0),
                "message": r["error"] or "ok",
                "payload": None,
            }
        )
    return out
