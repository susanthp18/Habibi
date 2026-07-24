"""Voice persistence — interactions + voice_sessions + transcript/sentiment.

Keeps writes out of the contested main.py / large mutation surface of db.py.
Uses db.engine / TENANT_ID / DEFAULT_BOT_ID only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

import db
from agent_core import estimate_sentiment, evaluate_guardrails, sentiment_label

logger = logging.getLogger(__name__)

UNKNOWN_CALLER_ID = "UNKNOWN-CALLER"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def ensure_unknown_caller() -> None:
    """Idempotent sentinel customer for unbound voice calls (runtime, not Alembic)."""
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO customers (
                  id, tenant_id, name, segment, risk, dnd, created_at, updated_at
                ) VALUES (
                  :id, :tenant, 'Unknown caller', 'sentinel', 'medium', false, now(), now()
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": UNKNOWN_CALLER_ID, "tenant": db.TENANT_ID},
        )


def start_voice_call(
    *,
    session_id: str,
    deployment_id: str | None,
    transport: str = "smallwebrtc",
    provider_call_id: str | None = None,
    customer_id: str | None = None,
    account_id: str | None = None,
    bot_id: str | None = None,
    direction: str = "inbound",
) -> dict[str, Any]:
    """INSERT active interaction + voice_sessions row. Returns ids."""
    ensure_unknown_caller()
    cid = customer_id or UNKNOWN_CALLER_ID
    bid = (bot_id or db.DEFAULT_BOT_ID).strip() or db.DEFAULT_BOT_ID
    interaction_id = _sid("CL")
    host = socket.gethostname()
    started = _now()

    with db.engine.begin() as conn:
        # Resolve account only for known customers.
        acct = account_id
        if not acct and cid != UNKNOWN_CALLER_ID:
            acct = db._first_account_id(conn, cid)

        conn.execute(
            text(
                """
                INSERT INTO interactions (
                  id, tenant_id, customer_id, account_id,
                  handler_kind, handler_user_id, handler_bot_id,
                  channel, direction, status, deployment_id,
                  started_at, source_payload, created_at, updated_at
                ) VALUES (
                  :id, :tenant, :customer_id, :account_id,
                  'bot', NULL, :bot_id,
                  'voice', :direction, 'active', :deployment_id,
                  :started, CAST(:payload AS jsonb), now(), now()
                )
                """
            ),
            {
                "id": interaction_id,
                "tenant": db.TENANT_ID,
                "customer_id": cid,
                "account_id": acct,
                "bot_id": bid,
                "direction": direction if direction in ("inbound", "outbound") else "inbound",
                "deployment_id": deployment_id,
                "started": started,
                "payload": json.dumps({"source": "voice", "transport": transport}),
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO voice_sessions (
                  id, interaction_id, deployment_id, transport, provider_call_id,
                  worker_host, status, started_at, last_heartbeat_at,
                  created_at, updated_at
                ) VALUES (
                  :id, :interaction_id, :deployment_id, :transport, :provider_call_id,
                  :host, 'live', :started, :started, now(), now()
                )
                """
            ),
            {
                "id": session_id,
                "interaction_id": interaction_id,
                "deployment_id": deployment_id,
                "transport": transport if transport in ("smallwebrtc", "twilio", "daily") else "smallwebrtc",
                "provider_call_id": provider_call_id,
                "host": host,
                "started": started,
            },
        )
        try:
            db._activity(
                conn,
                "interaction",
                interaction_id,
                "voice_session_started",
                "Voice session started",
                f"transport={transport}",
                cid,
            )
        except Exception:
            logger.exception("activity_events write failed (non-fatal)")

    return {
        "sessionId": session_id,
        "interactionId": interaction_id,
        "customerId": cid,
        "accountId": acct,
        "botId": bid,
        "startedAt": started,
    }


def append_transcript_turn(
    *,
    interaction_id: str,
    turn_index: int,
    speaker: str,
    text_content: str,
    at_sec: float,
    sentiment_delta: float | None = None,
    intent: str | None = None,
    intent_score: float | None = None,
    ttfb_ms: int | None = None,
    ttfa_ms: int | None = None,
    tokens: int | None = None,
) -> None:
    """Idempotent turn write — UNIQUE(interaction_id, turn_index)."""
    content = (text_content or "").strip()
    if not content:
        return
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO interaction_transcript (
                  id, interaction_id, turn_index, speaker, at_sec, text,
                  sentiment_delta, intent, intent_score,
                  ttfb_ms, ttfa_ms, tokens, created_at
                ) VALUES (
                  :id, :interaction_id, :turn_index, :speaker, :at_sec, :text,
                  :sentiment_delta, :intent, :intent_score,
                  :ttfb_ms, :ttfa_ms, :tokens, now()
                )
                ON CONFLICT (interaction_id, turn_index) DO NOTHING
                """
            ),
            {
                "id": f"{interaction_id}-T{turn_index}",
                "interaction_id": interaction_id,
                "turn_index": turn_index,
                "speaker": speaker,
                "at_sec": int(max(0, round(at_sec))),
                "text": content,
                "sentiment_delta": sentiment_delta,
                "intent": (intent or None),
                "intent_score": round(float(intent_score), 3) if intent_score is not None else None,
                "ttfb_ms": int(ttfb_ms) if ttfb_ms is not None else None,
                "ttfa_ms": int(ttfa_ms) if ttfa_ms is not None else None,
                "tokens": int(tokens) if tokens is not None else None,
            },
        )


def append_sentiment_point(
    *,
    interaction_id: str,
    at_sec: float,
    score: float,
    label: str | None = None,
) -> None:
    lbl = label or sentiment_label(score)
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO interaction_sentiment (
                  id, interaction_id, at_sec, score, label, created_at
                ) VALUES (
                  :id, :interaction_id, :at_sec, :score, :label, now()
                )
                """
            ),
            {
                "id": _sid("SENT"),
                "interaction_id": interaction_id,
                "at_sec": int(max(0, round(at_sec))),
                "score": round(float(score), 3),
                "label": lbl if lbl in ("positive", "neutral", "negative") else "neutral",
            },
        )


def append_interaction_flag(
    *,
    interaction_id: str,
    flag: str,
    severity: str = "medium",
) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO interaction_flags (id, interaction_id, flag, severity, created_at)
                VALUES (:id, :interaction_id, :flag, :severity, now())
                """
            ),
            {
                "id": _sid("FLAG"),
                "interaction_id": interaction_id,
                "flag": flag,
                "severity": severity,
            },
        )


def append_live_alert(
    *,
    interaction_id: str,
    kind: str,
    reason: str | None = None,
    severity: str = "medium",
) -> None:
    schema_kinds = {
        "sentiment_drop",
        "compliance",
        "long_hold",
        "escalation",
        "silence",
        "loop_detected",
    }
    k = kind if kind in schema_kinds else None
    if not k:
        return
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO live_alerts (
                  id, interaction_id, kind, severity, reason, created_at
                ) VALUES (
                  :id, :interaction_id, :kind, :severity, :reason, now()
                )
                """
            ),
            {
                "id": _sid("ALERT"),
                "interaction_id": interaction_id,
                "kind": k,
                "severity": severity,
                "reason": reason or kind,
            },
        )


def heartbeat(session_id: str) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE voice_sessions
                SET last_heartbeat_at = now(), updated_at = now()
                WHERE id = :id AND status = 'live'
                """
            ),
            {"id": session_id},
        )


def complete_voice_call(
    *,
    session_id: str,
    interaction_id: str,
    status: str = "completed",
    latency_ms: int | None = None,
    rag_hits: int = 0,
    summary: str | None = None,
    disposition: str | None = None,
    avg_sentiment: float | None = None,
) -> None:
    ended = _now()
    st = status if status in ("completed", "abandoned", "failed") else "completed"
    sent_label = sentiment_label(avg_sentiment) if avg_sentiment is not None else None

    with db.engine.begin() as conn:
        row = conn.execute(
            text("SELECT started_at FROM interactions WHERE id = :id"),
            {"id": interaction_id},
        ).mappings().first()
        duration = None
        if row and row.get("started_at"):
            started = row["started_at"]
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            duration = max(0, int((ended - started).total_seconds()))

        conn.execute(
            text(
                """
                UPDATE interactions
                SET status = :status,
                    ended_at = :ended,
                    duration_sec = COALESCE(:duration, duration_sec),
                    latency_ms = COALESCE(:latency_ms, latency_ms),
                    rag_hits = GREATEST(COALESCE(rag_hits, 0), :rag_hits),
                    summary = COALESCE(:summary, summary),
                    disposition = COALESCE(:disposition, disposition),
                    avg_sentiment = COALESCE(:avg_sentiment, avg_sentiment),
                    sentiment_label = COALESCE(:sentiment_label, sentiment_label),
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": interaction_id,
                "status": st,
                "ended": ended,
                "duration": duration,
                "latency_ms": latency_ms,
                "rag_hits": int(rag_hits or 0),
                "summary": summary,
                "disposition": disposition,
                "avg_sentiment": round(avg_sentiment, 3) if avg_sentiment is not None else None,
                "sentiment_label": sent_label,
            },
        )
        # Phase 0 capture: roll primary_intent + outcome flags from transcript (non-Azure).
        try:
            import capture

            capture.rollup_interaction(
                conn,
                interaction_id,
                channel_hint="voice",
                force_summary=not bool(summary),
            )
        except Exception:
            logger.exception("capture rollup failed for %s", interaction_id)

        vs_status = "ended" if st != "failed" else "failed"
        conn.execute(
            text(
                """
                UPDATE voice_sessions
                SET status = :status,
                    ended_at = :ended,
                    last_heartbeat_at = :ended,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": session_id, "status": vs_status, "ended": ended},
        )


def evaluate_and_flag_bot_turn(
    *,
    interaction_id: str,
    customer_text: str,
    bot_text: str,
    intent: str,
    guardrails: dict[str, Any],
    turn_index: int,
    elapsed_seconds: float,
    customer_bot_exchanges: int,
) -> list[str]:
    flags = evaluate_guardrails(
        customer_text=customer_text,
        bot_text=bot_text,
        intent=intent,
        guardrails=guardrails,
        turn_index=turn_index,
        elapsed_seconds=elapsed_seconds,
        customer_bot_exchanges=customer_bot_exchanges,
        hard_max_turns=50,  # voice calls are longer than sandbox
    )
    for f in flags:
        try:
            append_interaction_flag(interaction_id=interaction_id, flag=f)
            if f.startswith("prohibited:") or f in ("waiver-blocked", "missing-recording-disclosure"):
                append_live_alert(
                    interaction_id=interaction_id,
                    kind="compliance",
                    reason=f,
                )
            if f == "auto-escalate":
                append_live_alert(
                    interaction_id=interaction_id,
                    kind="escalation",
                    reason=f,
                )
        except Exception:
            logger.exception("flag/alert write failed for %s", f)
    return flags


def score_customer_text(text_content: str) -> tuple[float, str]:
    score = estimate_sentiment(text_content)
    return score, sentiment_label(score)


# ── V3 compliance / identity / handoff / media ──────────────────────────────


def _digits_only(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def lookup_customer_for_verify(
    *,
    method: str,
    value: str,
) -> dict[str, Any] | None:
    """Resolve a customer for identity verification (phone last-4 / account tail).

    Returns {customerId, accountId, name, outstanding, minimumDue, dpd, phoneTail, accountTail}
    or None when no unique match.
    """
    method_n = (method or "").strip().lower()
    raw = (value or "").strip()
    if not raw:
        return None

    def _pack(row: Any) -> dict[str, Any]:
        phone = row.get("phone_primary") or ""
        acct = row.get("account_id")
        return {
            "customerId": row["customer_id"],
            "accountId": acct,
            "name": row["name"],
            "outstanding": float(row["outstanding"] or 0),
            "minimumDue": float(row["minimum_due"] or 0) if row.get("minimum_due") is not None else None,
            "dpd": int(row["dpd"] or 0) if row.get("dpd") is not None else None,
            "phoneTail": _digits_only(phone)[-4:] if phone else None,
            # Last 4 DIGITS, not chars — "AC-SUSANTH"[-4:] would be "ANTH".
            "accountTail": (_digits_only(acct)[-4:] or None) if acct and len(_digits_only(acct)) >= 4 else None,
        }

    with db.engine.connect() as conn:
        if method_n == "phone_match":
            digits = _digits_only(raw)
            if len(digits) < 4:
                return None
            # Exact / 10-digit match first (unique).
            found = db._find_customer_by_phone(conn, digits)
            if found:
                row = conn.execute(
                    text(
                        """
                        SELECT c.id AS customer_id, c.name, c.phone_primary,
                               a.id AS account_id, a.outstanding, a.minimum_due, a.dpd
                        FROM customers c
                        LEFT JOIN LATERAL (
                          SELECT id, outstanding, minimum_due, dpd
                          FROM accounts
                          WHERE customer_id = c.id
                          ORDER BY outstanding DESC NULLS LAST
                          LIMIT 1
                        ) a ON true
                        WHERE c.id = :cid
                        LIMIT 1
                        """
                    ),
                    {"cid": found["id"]},
                ).mappings().first()
                return _pack(row) if row else None

            # Last-4 only when unambiguous.
            matches = conn.execute(
                text(
                    """
                    SELECT c.id AS customer_id, c.name, c.phone_primary,
                           a.id AS account_id, a.outstanding, a.minimum_due, a.dpd
                    FROM customers c
                    LEFT JOIN LATERAL (
                      SELECT id, outstanding, minimum_due, dpd
                      FROM accounts
                      WHERE customer_id = c.id
                      ORDER BY outstanding DESC NULLS LAST
                      LIMIT 1
                    ) a ON true
                    WHERE c.id <> :unknown
                      AND (
                        RIGHT(regexp_replace(COALESCE(c.phone_primary, ''), '[^0-9]', '', 'g'), 4) = :tail4
                        OR RIGHT(regexp_replace(COALESCE(c.phone_alt, ''), '[^0-9]', '', 'g'), 4) = :tail4
                      )
                    LIMIT 2
                    """
                ),
                {"tail4": digits[-4:], "unknown": UNKNOWN_CALLER_ID},
            ).mappings().all()
            if len(matches) != 1:
                return None
            return _pack(matches[0])

        if method_n == "account_tail":
            tail = raw[-4:].upper()
            matches = conn.execute(
                text(
                    """
                    SELECT c.id AS customer_id, c.name, c.phone_primary,
                           a.id AS account_id, a.outstanding, a.minimum_due, a.dpd
                    FROM accounts a
                    JOIN customers c ON c.id = a.customer_id
                    WHERE c.id <> :unknown
                      AND UPPER(RIGHT(a.id, 4)) = :tail
                    ORDER BY a.outstanding DESC NULLS LAST
                    LIMIT 2
                    """
                ),
                {"tail": tail, "unknown": UNKNOWN_CALLER_ID},
            ).mappings().all()
            if len(matches) != 1:
                return None
            return _pack(matches[0])

        if method_n == "manual":
            row = conn.execute(
                text(
                    """
                    SELECT c.id AS customer_id, c.name, c.phone_primary,
                           a.id AS account_id, a.outstanding, a.minimum_due, a.dpd
                    FROM customers c
                    LEFT JOIN LATERAL (
                      SELECT id, outstanding, minimum_due, dpd
                      FROM accounts
                      WHERE customer_id = c.id
                      ORDER BY outstanding DESC NULLS LAST
                      LIMIT 1
                    ) a ON true
                    WHERE c.id = :cid AND c.id <> :unknown
                    LIMIT 1
                    """
                ),
                {"cid": raw, "unknown": UNKNOWN_CALLER_ID},
            ).mappings().first()
            return _pack(row) if row else None

        # dob / otp not backed by customer columns yet.
        return None


def bind_customer_to_interaction(
    *,
    interaction_id: str,
    customer_id: str,
    account_id: str | None,
) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE interactions
                SET customer_id = :customer_id,
                    account_id = COALESCE(:account_id, account_id),
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": interaction_id,
                "customer_id": customer_id,
                "account_id": account_id,
            },
        )


def record_disclosure(
    *,
    interaction_id: str,
    label: str,
    rule_id: str | None,
    read_at_sec: float,
    bot_id: str | None = None,
) -> str:
    disc_id = _sid("DISC")
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO interaction_disclosures (
                  id, interaction_id, rule_id, label, read_at_sec,
                  read_by_kind, read_by_user_id, read_by_bot_id, read, created_at
                ) VALUES (
                  :id, :interaction_id, :rule_id, :label, :read_at_sec,
                  'bot', NULL, :bot_id, true, now()
                )
                """
            ),
            {
                "id": disc_id,
                "interaction_id": interaction_id,
                "rule_id": rule_id,
                "label": label,
                "read_at_sec": int(max(0, round(read_at_sec))),
                "bot_id": bot_id or db.DEFAULT_BOT_ID,
            },
        )
    return disc_id


def record_identity_verification(
    *,
    interaction_id: str,
    customer_id: str,
    method: str,
    status: str,
    attempt_count: int,
    failure_reason: str | None = None,
) -> str:
    method_n = method if method in ("phone_match", "dob", "otp", "account_tail", "manual") else "manual"
    status_n = status if status in ("pending", "verified", "failed") else "failed"
    vid = _sid("IDV")
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO identity_verifications (
                  id, interaction_id, customer_id, method, status,
                  attempt_count, verified_at, failure_reason, created_at, updated_at
                ) VALUES (
                  :id, :interaction_id, :customer_id, :method, :status,
                  :attempt_count,
                  CASE WHEN :status = 'verified' THEN now() ELSE NULL END,
                  :failure_reason, now(), now()
                )
                """
            ),
            {
                "id": vid,
                "interaction_id": interaction_id,
                "customer_id": customer_id,
                "method": method_n,
                "status": status_n,
                "attempt_count": max(1, int(attempt_count)),
                "failure_reason": failure_reason,
            },
        )
    return vid


def record_handoff(
    *,
    interaction_id: str,
    reason: str,
    bot_id: str | None = None,
    to_team_id: str | None = "retail-collections",
    queue: str | None = "Retail Collections",
) -> str:
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
    hid = _sid("HO")
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO interaction_handoffs (
                  id, interaction_id, from_kind, from_user_id, from_bot_id,
                  to_kind, to_user_id, to_bot_id, to_team_id, reason, queue,
                  requested_at, created_at
                ) VALUES (
                  :id, :interaction_id, 'bot', NULL, :bot_id,
                  'human', NULL, NULL, :to_team_id, :reason, :queue,
                  now(), now()
                )
                """
            ),
            {
                "id": hid,
                "interaction_id": interaction_id,
                "bot_id": bot_id or db.DEFAULT_BOT_ID,
                "to_team_id": to_team_id,
                "reason": r,
                "queue": queue,
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
            {"id": interaction_id},
        )
    append_live_alert(
        interaction_id=interaction_id,
        kind="escalation",
        reason=r,
        severity="high",
    )
    return hid


def record_media(
    *,
    interaction_id: str,
    kind: str,
    storage_ref: str,
    duration_sec: int | None,
    mime_type: str,
    size_bytes: int | None,
    content_hash: str | None = None,
) -> str:
    kind_n = kind if kind in ("audio", "voicemail", "transcript_export", "redacted_audio", "waveform") else "audio"
    mid = _sid("MED")
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO interaction_media (
                  id, interaction_id, kind, storage_ref, duration_sec,
                  mime_type, size_bytes, hash, created_at, updated_at
                ) VALUES (
                  :id, :interaction_id, :kind, :storage_ref, :duration_sec,
                  :mime_type, :size_bytes, :hash, now(), now()
                )
                """
            ),
            {
                "id": mid,
                "interaction_id": interaction_id,
                "kind": kind_n,
                "storage_ref": storage_ref,
                "duration_sec": duration_sec,
                "mime_type": mime_type,
                "size_bytes": size_bytes,
                "hash": content_hash,
            },
        )
    return mid


def list_transcript_turns(interaction_id: str) -> list[dict[str, Any]]:
    """Ordered turns for export / post-call review."""
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT turn_index, speaker, at_sec, text,
                       sentiment_delta, intent, intent_score,
                       ttfb_ms, ttfa_ms, tokens
                FROM interaction_transcript
                WHERE interaction_id = :id
                ORDER BY turn_index ASC
                """
            ),
            {"id": interaction_id},
        ).mappings().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "turnIndex": int(r["turn_index"]),
                "speaker": r["speaker"],
                "atSec": int(r["at_sec"] or 0),
                "text": r["text"],
                "sentimentDelta": float(r["sentiment_delta"]) if r["sentiment_delta"] is not None else None,
                "intent": r["intent"],
                "intentScore": float(r["intent_score"]) if r["intent_score"] is not None else None,
                "ttfbMs": int(r["ttfb_ms"]) if r["ttfb_ms"] is not None else None,
                "ttfaMs": int(r["ttfa_ms"]) if r["ttfa_ms"] is not None else None,
                "tokens": int(r["tokens"]) if r["tokens"] is not None else None,
            }
        )
    return out


def export_transcript_json(
    *,
    interaction_id: str,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """Serialize turns → MinIO (or local) → interaction_media kind=transcript_export.

    Safe to call from CrmSink worker threads. Returns media row summary or None.
    """
    turns = list_transcript_turns(interaction_id)
    if not turns:
        return None

    payload = {
        "interactionId": interaction_id,
        "sessionId": session_id,
        "turnCount": len(turns),
        "turns": turns,
    }
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    filename = f"{interaction_id}.transcript.json"
    key = f"transcripts/{db.TENANT_ID}/{filename}"

    storage_ref: str | None = None
    try:
        import storage

        if storage.is_configured():
            try:
                storage_ref = storage.put_bytes(
                    key,
                    raw,
                    "application/json",
                    bucket="recordings",
                )
            except Exception:
                storage_ref = storage.put_bytes(key, raw, "application/json")
    except Exception:
        logger.exception("transcript export minio upload failed — falling back to local")

    if not storage_ref:
        local_dir = Path(__file__).resolve().parent.parent / ".cache" / "transcripts"
        local_dir.mkdir(parents=True, exist_ok=True)
        path = local_dir / filename
        path.write_bytes(raw)
        storage_ref = f"local://transcripts/{filename}"
        logger.info("transcript export saved locally path=%s", path)

    media_id = record_media(
        interaction_id=interaction_id,
        kind="transcript_export",
        storage_ref=storage_ref,
        duration_sec=None,
        mime_type="application/json",
        size_bytes=len(raw),
        content_hash=digest,
    )
    return {
        "mediaId": media_id,
        "storageRef": storage_ref,
        "sizeBytes": len(raw),
        "turnCount": len(turns),
    }


def mark_ptp_captured(interaction_id: str) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE interactions
                SET ptp_captured = true, updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": interaction_id},
        )


def rebind_customer(
    *,
    interaction_id: str,
    customer_id: str,
    method: str = "phone_match",
    account_id: str | None = None,
    bot_id: str | None = None,
) -> dict[str, Any]:
    """Rebind a live voice/chat interaction to a verified customer (Phase 3 lite)."""
    import capture

    with db.engine.begin() as conn:
        return capture.rebind_interaction_customer(
            conn,
            interaction_id=interaction_id,
            customer_id=customer_id,
            method=method,
            account_id=account_id,
            actor_bot_id=bot_id or db.DEFAULT_BOT_ID,
        )
