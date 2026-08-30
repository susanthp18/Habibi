"""Floor / Webhooks / Integrations screen-shaped accessors.

Kept out of db.py on purpose — these are ops-admin surfaces, not CRM core.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text

import db

logger = logging.getLogger(__name__)


def _floor_agent_card(row: dict[str, Any], fallback_name: str) -> dict[str, str] | None:
    bot_id = row.get("handler_bot_id")
    if not bot_id:
        return None
    display = fallback_name
    try:
        from agent_core.cards.defaults import card_for

        display = card_for(str(bot_id)).identity.display_name
    except KeyError:
        pass
    return {"botId": str(bot_id), "displayName": display}

def _tenant() -> str:
    """Read tenant dynamically so tests/env overrides apply.

    Delegates rather than re-deriving. The previous fallback chain ended in
    ``"tenant-hdfc"``, a tenant id that exists nowhere — had it ever been
    reached, these screens would have queried a tenant with no rows instead of
    failing.
    """
    return db.current_tenant()


def _validate_webhook_url(url: str) -> str:
    """HTTPS-only public webhook targets — reject loopback / RFC1918 / link-local."""
    raw = (url or "").strip()
    if not raw:
        raise ValueError("webhook_url_required")
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise ValueError("webhook_url_https_required")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("webhook_url_host_required")
    blocked = {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "metadata.google.internal",
    }
    if host in blocked or host.endswith(".local"):
        raise ValueError("webhook_url_private_forbidden")
    # Literal private / loopback / link-local addresses.
    #
    # NOTE: hostnames are deliberately *not* resolved here — DNS at validation
    # time is both a rebinding hazard (the name can resolve differently at send
    # time) and a blocking network call inside a request handler. Before real
    # webhook egress ships, the delivery worker must re-check the resolved
    # address immediately before connecting and pin it for the request.
    if _is_private_host_ip(host):
        raise ValueError("webhook_url_private_forbidden")
    return raw


def _is_private_host_ip(host: str) -> bool:
    """True when `host` is a literal address in a non-public range."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


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


# ── Floor ────────────────────────────────────────────────────────────────────


def get_floor_snapshot() -> dict[str, Any]:
    tenant = _tenant()
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
                      RIGHT(COALESCE(a.id, ''), 4) AS account_tail,
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
                "accountTail": (r["account_tail"] or "----")[-4:],
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


def create_supervisor_action(payload: dict[str, Any]) -> dict[str, Any]:
    interaction_id = (payload.get("interactionId") or "").strip()
    action = (payload.get("action") or "").strip()
    if not interaction_id or not action:
        raise ValueError("interactionId_and_action_required")
    note = (payload.get("note") or "").strip() or None
    tenant = _tenant()
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
                        "id": _sid("ho"),
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
    tenant = _tenant()
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
            "sample": {"event": e["key"], "tenant": _tenant(), "at": datetime.now(timezone.utc).isoformat()},
        }
        for e in EVENT_CATALOG
    ]


def _endpoint_contract(conn: Any, endpoint_id: str) -> dict[str, Any] | None:
    row = db._one(
        conn.execute(
            text(
                """
                SELECT id, target_system, url, status, signing_algorithm, secret_ref,
                       secret_hash, created_at, name
                FROM webhook_endpoints
                WHERE id = :id AND tenant_id = :tenant
                """
            ),
            {"id": endpoint_id, "tenant": _tenant()},
        )
    )
    if row is None:
        return None

    headers = db._rows(
        conn.execute(
            text(
                """
                SELECT header_key AS key, header_value AS value
                FROM webhook_endpoint_headers
                WHERE endpoint_id = :id
                  -- Case-insensitive and including Authorization, matching the
                  -- write-side exclusion in _upsert_endpoint_children. The
                  -- exact-case list let a legacy row stored as
                  -- 'x-webhook-secret' (or any bearer token) be read back.
                  AND lower(header_key) NOT IN (
                        'x-webhook-secret-sha256', 'x-webhook-secret', 'authorization'
                      )
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
    has_secret = bool(secret_ref or row.get("secret_hash"))
    return {
        "id": row["id"],
        "name": name,
        "url": row["url"],
        "target": row["target_system"],
        "status": row["status"],
        "events": events,
        "algo": row.get("signing_algorithm") or "HMAC-SHA256",
        "secret": _mask_secret(has_secret),
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
    # No blanket try/except: swallowing a database error here rendered the
    # Webhooks screen as "no endpoints configured", which reads as a
    # deliberate empty state. Let it surface as a 5xx instead.
    with db.engine.connect() as conn:
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
                    {"tenant": _tenant()},
                )
            )
        ]
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
        # Never persist signing secrets as outbound headers.
        if key.lower() in {"x-webhook-secret-sha256", "x-webhook-secret", "authorization"}:
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
    secret_hash = hashlib.sha256(secret_plain.encode()).hexdigest()
    url = _validate_webhook_url(str(payload.get("url") or ""))
    tenant = _tenant()
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
            {"id": tenant, "name": tenant},
        )
        conn.execute(
            text(
                """
                INSERT INTO webhook_endpoints (
                  id, tenant_id, target_system, url, status, signing_algorithm,
                  secret_ref, secret_hash, name, created_at, updated_at
                ) VALUES (
                  :id, :tenant, :target, :url, 'active', :algo,
                  :secret_ref, :secret_hash, :name, now(), now()
                )
                """
            ),
            {
                "id": eid,
                "tenant": tenant,
                "target": payload.get("target") or "Custom",
                "url": url,
                "algo": payload.get("algo") or "HMAC-SHA256",
                "secret_ref": secret_ref,
                "secret_hash": secret_hash,
                "name": payload.get("name") or payload.get("target") or eid,
            },
        )
        _upsert_endpoint_children(
            conn,
            eid,
            events=list(payload.get("events") or []),
            headers=list(payload.get("headers") or []),
            retry=dict(payload.get("retry") or {}),
        )
        ep = _endpoint_contract(conn, eid)
    assert ep is not None
    ep["secretOnce"] = secret_plain
    ep["secret"] = _mask_secret(True)
    return ep


def patch_webhook_endpoint(endpoint_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with db.engine.begin() as conn:
        sets: list[str] = []
        params: dict[str, Any] = {"id": endpoint_id, "tenant": _tenant()}
        for col, key in [
            ("url", "url"),
            ("target_system", "target"),
            ("status", "status"),
            ("signing_algorithm", "algo"),
            ("name", "name"),
        ]:
            if key in payload and payload[key] is not None:
                sets.append(f"{col} = :{key}")
                val = payload[key]
                if key == "url":
                    val = _validate_webhook_url(str(val))
                params[key] = val
        if sets:
            sets.append("updated_at = now()")
            conn.execute(
                text(
                    f"UPDATE webhook_endpoints SET {', '.join(sets)} "
                    "WHERE id = :id AND tenant_id = :tenant"
                ),
                params,
            )
        cur = _endpoint_contract(conn, endpoint_id)
        if cur is None:
            raise KeyError("endpoint_not_found")
        if any(k in payload for k in ("events", "headers", "retry")):
            _upsert_endpoint_children(
                conn,
                endpoint_id,
                events=list(payload["events"]) if "events" in payload else list(cur.get("events") or []),
                headers=list(payload["headers"]) if "headers" in payload else list(cur.get("headers") or []),
                retry=dict(payload["retry"]) if "retry" in payload else dict(cur.get("retry") or {}),
            )
        ep = _endpoint_contract(conn, endpoint_id)
    if ep is None:
        raise KeyError("endpoint_not_found")
    return ep


def delete_webhook_endpoint(endpoint_id: str) -> None:
    with db.engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM webhook_endpoints WHERE id = :id AND tenant_id = :tenant"),
            {"id": endpoint_id, "tenant": _tenant()},
        )
        if not result.rowcount:
            raise KeyError("endpoint_not_found")


def rotate_webhook_secret(endpoint_id: str) -> dict[str, Any]:
    secret_plain = secrets.token_urlsafe(24)
    secret_ref = f"vault://local/{endpoint_id}"
    secret_hash = hashlib.sha256(secret_plain.encode()).hexdigest()
    with db.engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE webhook_endpoints
                SET secret_ref = :ref, secret_hash = :hash, updated_at = now()
                WHERE id = :id AND tenant_id = :tenant
                """
            ),
            {
                "id": endpoint_id,
                "tenant": _tenant(),
                "ref": secret_ref,
                "hash": secret_hash,
            },
        )
        if not result.rowcount:
            raise KeyError("endpoint_not_found")
        conn.execute(
            text(
                """
                DELETE FROM webhook_endpoint_headers
                WHERE endpoint_id = :id
                  -- Case-insensitive and including Authorization, matching the
                  -- read-side filter in _endpoint_contract. Exact-case matching
                  -- let a legacy row stored as 'x-webhook-secret' survive a
                  -- rotation that is supposed to invalidate the old secret.
                  AND lower(header_key) IN (
                        'x-webhook-secret-sha256', 'x-webhook-secret', 'authorization'
                      )
                """
            ),
            {"id": endpoint_id},
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
        # 'live' or 'simulated'. The test-fire button does no egress, and a row
        # it produced must never be mistaken for a delivery that happened.
        "mode": row.get("delivery_mode") or "live",
    }


def list_webhook_deliveries(endpoint_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    with db.engine.connect() as conn:
        params: dict[str, Any] = {"limit": limit, "tenant": _tenant()}
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
    """The Integrations test-fire button. Simulated on purpose — no egress.

    This exists so the screen can be demonstrated without a receiver, and it is
    the ONLY path that still simulates. Real events go through
    ``webhooks_dispatch.dispatch``, and the row this writes is stamped
    ``delivery_mode='simulated'`` so the log distinguishes the two. It used to
    be the only producer of deliveries at all, which is how a system that had
    never sent a webhook came to have a delivery log full of 200s.
    """
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
        # Deterministic digest, not hash(): PYTHONHASHSEED randomises str
        # hashing per process, so the same endpoint produced a different
        # persisted latency on every worker and every restart.
        latency = 40 + (
            int.from_bytes(hashlib.sha256(endpoint_id.encode()).digest()[:4], "big") % 180
        )
        did = _sid("dlv")
        payload = {
            "event": key,
            "endpointId": endpoint_id,
            "tenant": _tenant(),
            "test": True,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        conn.execute(
            text(
                """
                INSERT INTO webhook_deliveries (
                  id, endpoint_id, event_type_id, payload, response_body,
                  http_status, attempt_number, latency_ms, status,
                  delivery_mode, created_at, updated_at
                ) VALUES (
                  :id, :eid, :et, CAST(:payload AS jsonb), :body,
                  :http, 1, :lat, :status,
                  'simulated', now(), now()
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
            "delivery_mode": "simulated",
            "created_at": datetime.now(timezone.utc),
        }
    return _delivery_contract(row, ep["retry"]["attempts"])


def retry_webhook_delivery(delivery_id: str) -> dict[str, Any]:
    """Re-queue the ORIGINAL payload for real delivery.

    This used to select ``d.payload`` and then throw it away, calling the
    simulator instead — so "retry" re-simulated a different, synthetic event and
    reported success for something that had never been sent. The receiver that
    missed the payment notification still had not received it.

    One click, one attempt. ``attempt_number`` carries forward from the row
    being retried rather than resetting, so a delivery that already burned its
    automatic ladder does not silently start a fresh one: the worker settles it
    terminally and the operator decides whether to click again.
    """
    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text(
                    """
                    SELECT d.endpoint_id, d.event_type_id, d.payload,
                           d.attempt_number, d.delivery_mode,
                           et.name AS event_name, e.status AS endpoint_status
                    FROM webhook_deliveries d
                    JOIN webhook_endpoints e ON e.id = d.endpoint_id
                    LEFT JOIN event_types et ON et.id = d.event_type_id
                    WHERE d.id = :id AND e.tenant_id = :tenant
                    """
                ),
                {"id": delivery_id, "tenant": _tenant()},
            )
        )
    if row is None:
        raise KeyError("delivery_not_found")
    if row.get("endpoint_status") == "paused":
        raise ValueError("endpoint_paused")
    # A simulated row has no real payload behind it, so retrying one can only
    # mean firing the simulator again. Say so by staying on that path.
    if (row.get("delivery_mode") or "live") == "simulated":
        return test_fire_webhook(row["endpoint_id"], row.get("event_name"))

    payload = row.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    did = _sid("dlv")
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO webhook_deliveries (
                  id, endpoint_id, event_type_id, payload, attempt_number,
                  status, delivery_mode, created_at, updated_at
                ) VALUES (
                  :id, :eid, :et, CAST(:payload AS jsonb), :attempt,
                  'pending', 'live', now(), now()
                )
                """
            ),
            {
                "id": did,
                "eid": row["endpoint_id"],
                "et": row["event_type_id"],
                "payload": json.dumps(payload),
                "attempt": int(row.get("attempt_number") or 1),
            },
        )
        fresh = db._one(
            conn.execute(
                text(
                    """
                    SELECT d.*, et.name AS event_name, rp.max_attempts
                    FROM webhook_deliveries d
                    LEFT JOIN event_types et ON et.id = d.event_type_id
                    LEFT JOIN webhook_retry_policies rp ON rp.endpoint_id = d.endpoint_id
                    WHERE d.id = :id
                    """
                ),
                {"id": did},
            )
        )
    assert fresh is not None
    return _delivery_contract(fresh, int(fresh.get("max_attempts") or 3))


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


def _provider_config_id(provider_id: str, environment: str) -> str:
    """Surrogate id for a new provider_configs row.

    Includes the tenant so ids stay unique across tenants; the durable identity
    (and upsert conflict target) is (provider_id, tenant_id, environment).
    """
    return f"pcfg-{_tenant()}-{provider_id}-{environment}"


def _provider_config_rows(environment: str) -> dict[str, dict[str, Any]]:
    """All provider_configs rows for this tenant/env, keyed by provider_id.

    One query for the whole screen — the per-provider variant opened a
    connection per provider on every Integrations page load.
    """
    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT provider_id, enabled, health, latency_ms
                    FROM provider_configs
                    WHERE tenant_id = :tenant AND environment = :env
                    """
                ),
                {"tenant": _tenant(), "env": environment},
            )
        )
    return {str(r["provider_id"]): dict(r) for r in rows}


# Distinguishes "caller supplied no config data" from "the batched lookup found
# no row for this provider". Without it, every unconfigured provider in
# list_providers re-ran _provider_config_rows(), defeating the batching.
_CONFIG_ROW_UNSET: Any = object()


def _provider_health(
    provider_id: str,
    environment: str = "sandbox",
    *,
    config_row: dict[str, Any] | None = _CONFIG_ROW_UNSET,
) -> tuple[str, int, bool]:
    meta = _PROVIDER_META[provider_id]
    env = environment if environment in {"sandbox", "production"} else "sandbox"
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
    row = (
        _provider_config_rows(env).get(provider_id)
        if config_row is _CONFIG_ROW_UNSET
        else config_row
    )
    if row and row.get("enabled") is not None:
        enabled_default = bool(row["enabled"]) and configured
    if not configured:
        return "unconfigured", 0, False
    health = (row or {}).get("health") or "healthy"
    latency = int((row or {}).get("latency_ms") or 0)
    return health if enabled_default else "unconfigured", latency, enabled_default


def list_providers(environment: str = "sandbox") -> list[dict[str, Any]]:
    # Both environments up front. `enabled`, `health` and `latency_ms` live in
    # provider_configs keyed by (tenant, environment) and patch_provider_enabled
    # writes one environment at a time — copying the requested env's status into
    # both perEnv entries made a sandbox toggle read back as a production one.
    rows_by_env = {
        "sandbox": _provider_config_rows("sandbox"),
        "production": _provider_config_rows("production"),
    }
    out: list[dict[str, Any]] = []
    for pid in LIVE_PROVIDER_IDS:
        meta = _PROVIDER_META[pid]
        values = _env_values(pid)

        def _per(for_env: str, pid: str = pid, values: dict[str, Any] = values) -> dict[str, Any]:
            health, latency, enabled = _provider_health(
                pid, for_env, config_row=rows_by_env[for_env].get(pid)
            )
            return {
                "values": values,
                # Credentials are process-wide env vars, so `values` is shared;
                # only the DB-backed status is per-environment.
                "region": values.get("region")
                or ("centralindia" if for_env == "production" else "eastus"),
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
                    "sandbox": _per("sandbox"),
                    "production": _per("production"),
                },
            }
        )
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
            {"id": _tenant(), "name": _tenant()},
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
        tenant = _tenant()
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
                ON CONFLICT (provider_id, tenant_id, environment) DO UPDATE SET
                  enabled = EXCLUDED.enabled,
                  health = EXCLUDED.health,
                  updated_at = now()
                """
            ),
            {
                "id": _provider_config_id(provider_id, env),
                "pid": provider_id,
                "tenant": tenant,
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
        tenant = _tenant()
        # Tenant-scoped read: keying by the surrogate id alone read (and then
        # overwrote) whichever tenant happened to own that row.
        existing_enabled = conn.execute(
            text(
                """
                SELECT enabled FROM provider_configs
                WHERE provider_id = :pid AND tenant_id = :tenant AND environment = :env
                """
            ),
            {"pid": provider_id, "tenant": tenant, "env": env},
        ).scalar()
        enabled_val = bool(existing_enabled) if existing_enabled is not None else False
        # RETURNING id: an existing row may still carry the legacy
        # (tenant-less) surrogate id, and integration_test_logs FKs to it.
        cid = conn.execute(
            text(
                """
                INSERT INTO provider_configs (
                  id, provider_id, tenant_id, environment, values, health,
                  latency_ms, enabled, credential_ref, created_at, updated_at
                ) VALUES (
                  :id, :pid, :tenant, :env, '{}'::jsonb, :health,
                  :lat, :enabled, :cref, now(), now()
                )
                ON CONFLICT (provider_id, tenant_id, environment) DO UPDATE SET
                  health = EXCLUDED.health,
                  latency_ms = EXCLUDED.latency_ms,
                  updated_at = now()
                RETURNING id
                """
            ),
            {
                "id": _provider_config_id(provider_id, env),
                "pid": provider_id,
                "tenant": tenant,
                "env": env,
                "health": "healthy" if ok else "degraded",
                "lat": latency,
                "enabled": enabled_val,
                "cref": f"env://{provider_id}",
            },
        ).scalar()
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
                {"pid": provider_id, "tenant": _tenant(), "limit": limit},
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
