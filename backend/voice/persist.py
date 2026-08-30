"""Voice persistence — interactions + voice_sessions + transcript/sentiment.

Keeps writes out of the contested main.py / large mutation surface of db.py.
Uses db.engine / TENANT_ID / DEFAULT_BOT_ID only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

import db
from agent_core import estimate_sentiment, evaluate_guardrails, sentiment_label
from agent_core import lexicon

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
            {"id": UNKNOWN_CALLER_ID, "tenant": db.current_tenant()},
        )


def resolve_known_customer(customer_id: str | None) -> str | None:
    """Return ``customer_id`` if a row exists, else None. Never raises.

    The outbound dialler puts the borrower's id into the Twilio stream
    parameters so the call knows who it rang. Those parameters come back to us
    over a WebSocket, and ``start_voice_call`` would fail its foreign key on a
    stale or wrong id — taking down call setup for a value that is only ever an
    optimisation. Checking first degrades to the unknown-caller path instead.
    """
    cid = (customer_id or "").strip()
    if not cid or cid == UNKNOWN_CALLER_ID:
        return None
    try:
        with db.engine.connect() as conn:
            found = conn.execute(
                text("SELECT id FROM customers WHERE id = :id"), {"id": cid}
            ).scalar()
        return str(found) if found else None
    except Exception:
        logger.exception("customer lookup failed for %s", cid)
        return None


def customer_id_for_bind(
    *,
    direction: str,
    twilio_params: dict[str, Any] | None = None,
    pstn_customer: dict[str, Any] | None = None,
) -> str | None:
    """The customer this call already knows, before verify_identity runs.

    Outbound: we dialled them, so the stream parameter is the source of truth.
    Inbound: ANI lookup (`pstn_customer`) is the same fact — a matched caller
    must bind to that row rather than sit as UNKNOWN-CALLER. Verification still
    gates account facts; this only joins the interaction to the right person.
    """
    if str(direction or "").strip().lower() == "outbound" and isinstance(twilio_params, dict):
        return str(twilio_params.get("customer_id") or "").strip() or None
    if str(direction or "").strip().lower() == "inbound" and isinstance(pstn_customer, dict):
        return (
            str(pstn_customer.get("customerId") or pstn_customer.get("customer_id") or "").strip()
            or None
        )
    return None


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
    started_at: datetime | None = None,
) -> dict[str, Any]:
    """INSERT active interaction + voice_sessions row. Returns ids.

    ``started_at`` defaults to now, which is right on the connect path. The
    degraded-call recovery in ``CrmSink`` passes the moment the borrower
    actually answered instead, so a row filed at teardown does not report a
    zero-second call.

    Interaction is committed first so CRM tools still work if the
    ``voice_sessions`` registry row fails (missing table / constraint). A prior
    single-transaction design rolled back both when ``voice_sessions`` was
    absent, leaving Live sandbox with ``interaction_id=None`` and every tool
    returning ``no_interaction``.
    """
    ensure_unknown_caller()
    cid = customer_id or UNKNOWN_CALLER_ID
    bid = (bot_id or db.DEFAULT_BOT_ID).strip() or db.DEFAULT_BOT_ID
    interaction_id = _sid("CL")
    host = socket.gethostname()
    started = started_at or _now()
    transport_n = transport if transport in ("smallwebrtc", "twilio", "daily") else "smallwebrtc"
    direction_n = direction if direction in ("inbound", "outbound") else "inbound"

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
                "tenant": db.current_tenant(),
                "customer_id": cid,
                "account_id": acct,
                "bot_id": bid,
                "direction": direction_n,
                "deployment_id": deployment_id,
                "started": started,
                "payload": json.dumps({"source": "voice", "transport": transport_n}),
            },
        )
        try:
            db._activity(
                conn,
                "interaction",
                interaction_id,
                "voice_session_started",
                "Voice session started",
                f"transport={transport_n}",
                cid,
            )
        except Exception:
            logger.exception("activity_events write failed (non-fatal)")

    try:
        with db.engine.begin() as conn:
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
                    "transport": transport_n,
                    "provider_call_id": provider_call_id,
                    "host": host,
                    "started": started,
                },
            )
    except Exception:
        logger.exception(
            "voice_sessions insert failed session=%s interaction=%s — CRM tools still bound",
            session_id,
            interaction_id,
        )

    return {
        "sessionId": session_id,
        "interactionId": interaction_id,
        "customerId": cid,
        "accountId": acct,
        "botId": bid,
        "startedAt": started,
    }


#: A run of seven or more consecutive digits in caller speech is an identifier,
#: not an amount — a mobile number, an account number, a card read out loud.
#: ``pii_redact.redact_text`` only matches *formatted* PII (a ``+91`` prefix, a
#: spaced 16-digit card), and digits reach the transcript bare: ``voice/ivr.py``
#: folds keypad presses in as ``"Caller keypad input: 9876543210"``, and STT
#: renders spoken digits the same way. Nothing in the shared detector set
#: matches that shape, so the transcript is exactly where those digits survive.
#: Two are kept for the same reason ``_mask_phone`` keeps two — enough to tell
#: two turns apart, not enough to re-identify, and short of the last four that
#: verification itself asks for.
_BARE_DIGIT_RUN = re.compile(r"\d{7,}")


def _redact_transcript_text(content: str) -> str:
    """Mask PII in a transcript turn before it is stored.

    Same redactor the tool-call audit rows use (``_audit_args``), so a card
    number spoken into a dispute summary and the same number spoken into the
    turn that preceded it are masked identically. The RTVI layer already keeps
    ``verify_identity`` arguments out of the browser (``voice/bot.py``); without
    this the transcript undid that at rest.
    """
    import pii_redact

    out = pii_redact.redact_text(content)
    return _BARE_DIGIT_RUN.sub(lambda m: "•" * 6 + m.group(0)[-2:], out)


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
    stt_ttfb_ms: int | None = None,
    llm_ttfb_ms: int | None = None,
    tts_ttfb_ms: int | None = None,
    user_turn_ms: int | None = None,
    tool_ms: int | None = None,
    aggregation_ms: int | None = None,
) -> None:
    """Idempotent turn write — UNIQUE(interaction_id, turn_index).

    The ``*_ttfb_ms`` / ``user_turn_ms`` / ``tool_ms`` / ``aggregation_ms``
    breakdown comes from Pipecat's UserBotLatencyObserver and is written on the
    same INSERT as ``ttfb_ms`` rather than a follow-up UPDATE — an UPDATE would
    race the ON CONFLICT DO NOTHING above.
    """
    content = (text_content or "").strip()
    if not content:
        return
    content = _redact_transcript_text(content)

    def _int(value: Any) -> int | None:
        return int(value) if value is not None else None

    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO interaction_transcript (
                  id, interaction_id, turn_index, speaker, at_sec, text,
                  sentiment_delta, intent, intent_score,
                  ttfb_ms, ttfa_ms, tokens,
                  stt_ttfb_ms, llm_ttfb_ms, tts_ttfb_ms,
                  user_turn_ms, tool_ms, aggregation_ms, created_at
                ) VALUES (
                  :id, :interaction_id, :turn_index, :speaker, :at_sec, :text,
                  :sentiment_delta, :intent, :intent_score,
                  :ttfb_ms, :ttfa_ms, :tokens,
                  :stt_ttfb_ms, :llm_ttfb_ms, :tts_ttfb_ms,
                  :user_turn_ms, :tool_ms, :aggregation_ms, now()
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
                "ttfb_ms": _int(ttfb_ms),
                "ttfa_ms": _int(ttfa_ms),
                "tokens": _int(tokens),
                "stt_ttfb_ms": _int(stt_ttfb_ms),
                "llm_ttfb_ms": _int(llm_ttfb_ms),
                "tts_ttfb_ms": _int(tts_ttfb_ms),
                "user_turn_ms": _int(user_turn_ms),
                "tool_ms": _int(tool_ms),
                "aggregation_ms": _int(aggregation_ms),
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


#: Tools whose arguments are never stored. Both exist to receive digits the
#: caller spoke — a mobile tail, an account tail — and an audit row is not a
#: place to keep them. The *fact* that verification ran is the auditable thing;
#: the digits are what the verification was protecting.
_ARGS_WITHHELD: frozenset[str] = frozenset({"verify_identity", "identify_customer"})

#: Argument names that carry free-form caller speech. Kept, but through the same
#: redactor the transcript uses, so a spoken card number in a dispute summary
#: does not survive in a column nobody thinks of as a transcript.
_ARGS_REDACTED: frozenset[str] = frozenset(
    {"summary", "text", "note", "reason", "verbatim", "context", "question", "detail"}
)

#: Arguments never exceed this once serialised. A model that emits a wall of
#: text into a tool argument should not be able to grow this table without
#: bound, and nothing downstream reads past the useful fields.
_MAX_ARGS_CHARS = 4000


def _audit_args(tool_name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """What of a tool's arguments is safe to keep on the audit row.

    The voice path recorded no arguments at all, which is why the Closer could
    see *that* ``capture_nonpayment_reason`` ran and not *what* it captured —
    the structured field and the row that proves it were on opposite sides of a
    gap. Keeping them is the fix; keeping them unfiltered would have traded one
    defect for a worse one.
    """
    if not isinstance(args, dict) or not args:
        return {}
    if tool_name in _ARGS_WITHHELD:
        return {"_withheld": True}
    import pii_redact

    out: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            cleaned = pii_redact.redact_text(value) if key in _ARGS_REDACTED else value
            out[key] = cleaned[:1000]
        elif isinstance(value, (int, float, bool)) or value is None:
            out[key] = value
        else:
            out[key] = str(value)[:500]
    serialised = json.dumps(out, default=str)
    if len(serialised) > _MAX_ARGS_CHARS:
        return {"_truncated": True}
    return out


def record_voice_tool_call(
    *,
    interaction_id: str,
    turn_index: int,
    tool_name: str,
    result_ok: bool,
    error: str | None = None,
    latency_ms: int | None = None,
    args: dict[str, Any] | None = None,
) -> None:
    """Audit one voice tool call into ``bot_tool_calls``.

    The turn id is **read back**, never constructed. ``capture`` normalises
    transcript ids to ``{interaction_id}-T{index}`` inside a savepoint that is
    allowed to fail (it logs "transcript turn id normalisation skipped"), so a
    row can permanently keep an id of the form ``{ix}-T-next-{uuid}``. Building
    the FK by string would dangle exactly on those rows.

    A missing transcript row is normal, not an error: the analysis queue and the
    CRM queue drain independently, so a tool call can be recorded before the
    turn it belongs to is written. ``interaction_id`` alone still places it on
    the timeline.
    """
    import bot_jobs

    with db.engine.begin() as conn:
        turn_id = conn.execute(
            text(
                "SELECT id FROM interaction_transcript "
                "WHERE interaction_id = :ix AND turn_index = :ti"
            ),
            {"ix": interaction_id, "ti": int(turn_index)},
        ).scalar()
        bot_jobs.record_tool_call(
            conn,
            interaction_id=interaction_id,
            transcript_turn_id=turn_id,
            channel="voice",
            tool_name=tool_name,
            # Was `{}` with the note "voice args are bound server-side from
            # VoiceSession". True of the *identity* arguments and false of
            # everything else: the reason code, the promise terms and the
            # callback slot all come from the model and were being dropped, so
            # post-call processing could see that a tool ran and never what it
            # recorded. `_audit_args` is what makes keeping them safe.
            args=_audit_args(tool_name, args),
            result_ok=result_ok,
            error=error,
            latency_ms=latency_ms,
        )


def update_turn_understanding(
    *,
    interaction_id: str,
    turn_index: int,
    intent: str,
    intent_score: float,
    sentiment: float,
) -> bool:
    """Correct a persisted customer turn with the LLM classification.

    The keyword pass writes the row immediately from the audio path so the
    transcript is never missing a turn; this lands a moment later and replaces
    intent/sentiment with what the caller actually meant. Returns False when the
    row is not there — which is legitimate, not an error: the analysis queue and
    the CRM queue drain independently, so the refinement can win the race.

    Also corrects the matching ``interaction_sentiment`` point, otherwise the
    Inbox sentiment sparkline keeps showing the English-lexicon 0.00 for every
    Hindi turn while the transcript shows the real value.
    """
    updated = False
    with db.engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE interaction_transcript
                   SET intent = :intent,
                       intent_score = :intent_score,
                       sentiment_delta = :sentiment
                 WHERE interaction_id = :interaction_id
                   AND turn_index = :turn_index
                """
            ),
            {
                "interaction_id": interaction_id,
                "turn_index": int(turn_index),
                "intent": intent,
                "intent_score": round(float(intent_score), 3),
                "sentiment": round(float(sentiment), 3),
            },
        )
        updated = bool(result.rowcount)
        if updated:
            # Match on the row this turn wrote rather than by at_sec, which the
            # sink computes independently and is not a key.
            conn.execute(
                text(
                    """
                    UPDATE interaction_sentiment
                       SET score = :score, label = :label
                     WHERE id = (
                       SELECT id FROM interaction_sentiment
                        WHERE interaction_id = :interaction_id
                        ORDER BY at_sec DESC, created_at DESC
                        LIMIT 1
                     )
                    """
                ),
                {
                    "interaction_id": interaction_id,
                    "score": round(float(sentiment), 3),
                    "label": sentiment_label(sentiment),
                },
            )
    if not updated:
        logger.debug(
            "turn understanding update matched no row · ix=%s · turn=%s",
            interaction_id,
            turn_index,
        )
    return updated


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


# --------------------------------------------------------------------------
# Guardrail breach -> compliance violation
# --------------------------------------------------------------------------
#
# evaluate_and_flag_bot_turn already knows the bot broke a rule; until now that
# knowledge reached interaction_flags and live_alerts and stopped. live_alerts
# are ephemeral floor-console signals — nobody reviews them after the call, so
# a breach was only ever caught if a human happened to QA-sample that call
# (industry norm: 1-2% of volume). A violations row is the reviewable artefact:
# it carries a rule, a status workflow and an assignee, and the Compliance
# screen is already built on it.
#
# Mapping is deliberately explicit and partial. An unmapped flag writes NO
# violation. A row filed against the wrong rule is worse than no row: it
# misleads the reviewer, corrupts per-rule breach rates, and is the kind of
# error that surfaces in an audit rather than in testing.
_FLAG_RULE_MAP = {
    # The bot's opening turns never mentioned recording. Exact semantic match
    # for RBI-DISC-01.
    "missing-recording-disclosure": "r-rec",
    # The bot said "waive"/"waiver" on a waiver_request turn despite
    # neverPromiseWaiver — an outcome the bot has no authority to promise.
    "waiver-blocked": "r-guarantee",
    # Quoted a rupee figure above the authority-matrix ceiling.
    "authority-cap-exceeded": "r-guarantee",
    "missing-mini-miranda": "r-mm",
    "identity-before-verify": "r-verify",
    "hours-breach": "r-dnd-win",
    "opt-out-ignored": "r-dnd-disc",
    "third-party-leak": "r-third",
    "rate-quoted": "r-false",
}

#: Flags that describe the *caller's* conduct or a session limit, not bot
#: misconduct. Listed so a reader can see they were considered and rejected
#: rather than overlooked.
_NON_BOT_FLAGS = frozenset(
    {"auto-escalate", "max-turns", "max-seconds", "politics-religion"}
)


def rule_for_flag(flag: str) -> str | None:
    """Map one guardrail flag to a compliance_rules id, or None to skip.

    ``prohibited:<term>`` is deployment-configured free text, so the term is
    classified through the same lexicon the escalation path uses. A term that
    is neither a legal threat nor abusive is left unmapped on purpose: the
    remaining PROH-LANG rules (false legal claim, guarantee of outcome) cannot
    be inferred from the word alone.
    """
    if flag in _FLAG_RULE_MAP:
        return _FLAG_RULE_MAP[flag]
    if flag.startswith("prohibited:"):
        term = flag.split(":", 1)[1].strip()
        if not term:
            return None
        if lexicon.is_legal_threat(term):
            return "r-threat"
        if lexicon.is_abusive(term):
            return "r-abuse"
    return None


def append_violation(
    *,
    interaction_id: str,
    rule_id: str,
    description: str,
    at_sec: int = 0,
) -> None:
    """File one open violation against the bot that handled ``interaction_id``.

    Idempotent per (interaction, rule): a bot that repeats a banned word on six
    turns has broken one rule once as far as a reviewer is concerned, and six
    rows would bury the other breaches on the call.

    Silently does nothing when the interaction has no bot handler — the table's
    CHECK constraint requires actor_bot_id for actor_kind='bot', and a
    human-handled turn is not this function's business.
    """
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO violations (
                  id, interaction_id, customer_id, rule_id,
                  actor_kind, actor_bot_id, status, description, at_sec,
                  created_at, updated_at
                )
                SELECT
                  :id, i.id, i.customer_id, :rule_id,
                  'bot', i.handler_bot_id, 'open', :description, :at_sec,
                  now(), now()
                FROM interactions i
                WHERE i.id = :interaction_id
                  AND i.handler_bot_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM violations v
                    WHERE v.interaction_id = i.id AND v.rule_id = :rule_id
                  )
                """
            ),
            {
                "id": _sid("VIO"),
                "interaction_id": interaction_id,
                "rule_id": rule_id,
                "description": description,
                "at_sec": max(int(at_sec), 0),
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

    try:
        from agent_core.live_qa.scorecard import score_completed_interaction

        score_completed_interaction(interaction_id)
    except Exception:
        logger.exception("live_qa scorecard-on-complete failed for %s", interaction_id)


_LIVE_ALERT_FLAGS = frozenset(
    {
        "waiver-blocked",
        "authority-cap-exceeded",
        "missing-recording-disclosure",
        "missing-mini-miranda",
        "identity-before-verify",
        "hours-breach",
        "opt-out-ignored",
        "third-party-leak",
        "rate-quoted",
    }
)
_BARGE_ALERT_FLAGS = frozenset(
    {
        "auto-escalate",
        "hours-breach",
        "third-party-leak",
        "identity-before-verify",
        "authority-cap-exceeded",
        "opt-out-ignored",
    }
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
    identity_verified: bool = False,
    third_party: bool = False,
    channel: str = "voice",
    customer_id: str | None = None,
    account_id: str | None = None,
    max_waiver_inr: float | None = None,
    now_hour: int | None = None,
    direction: str = "outbound",
    simulated: bool = False,
    recording_disclosed: bool = False,
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
        max_waiver_inr=max_waiver_inr,
        # Whether an EARLIER turn already disclosed. Without it the check is
        # per-turn and a compliant opening turn is followed by a false
        # "missing-recording-disclosure" on the next one.
        recording_disclosed=recording_disclosed,
    )
    live_result = None
    try:
        from agent_core.clock import now_local
        from agent_core.live_qa import TurnFacts, evaluate_live_qa

        hour = now_hour if now_hour is not None else now_local().hour
        live_result = evaluate_live_qa(
            TurnFacts(
                channel=channel or "voice",
                bot_text=bot_text,
                customer_text=customer_text,
                turn_index=turn_index,
                elapsed_seconds=elapsed_seconds,
                identity_verified=identity_verified,
                third_party=third_party,
                now_hour=hour,
                direction=direction,
                simulated=simulated,
                recording_disclosed=recording_disclosed
                or "missing-recording-disclosure" not in flags,
                miranda_disclosed=False,
                guardrail_flags=tuple(flags),
            ),
            customer_id=customer_id,
            account_id=account_id,
            interaction_id=interaction_id,
        )
        for extra in live_result.flags:
            if extra not in flags:
                flags.append(extra)
    except Exception:
        logger.exception("live_qa turn failed for %s", interaction_id)

    for f in flags:
        try:
            append_interaction_flag(interaction_id=interaction_id, flag=f)
            if f.startswith("prohibited:") or f in _LIVE_ALERT_FLAGS:
                append_live_alert(
                    interaction_id=interaction_id,
                    kind="compliance",
                    reason=f,
                    severity="high" if f in _BARGE_ALERT_FLAGS else "medium",
                )
            if f in _BARGE_ALERT_FLAGS:
                append_live_alert(
                    interaction_id=interaction_id,
                    kind="escalation",
                    reason=f,
                    severity="high",
                )
            rule_id = rule_for_flag(f)
            if rule_id:
                append_violation(
                    interaction_id=interaction_id,
                    rule_id=rule_id,
                    description=f"Auto-detected on turn {turn_index}: {f}",
                    at_sec=int(elapsed_seconds),
                )
        except Exception:
            logger.exception("flag/alert write failed for %s", f)
    if live_result is not None and live_result.auto_barge:
        flags.append("live-qa-auto-barge")
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

    # Every branch is tenant-scoped: identity verification must never resolve a
    # caller to another tenant's customer, and accounts inherits its tenant
    # through customers, so the predicate lives on `c`.
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
                        WHERE c.id = :cid AND c.tenant_id = :tenant
                        LIMIT 1
                        """
                    ),
                    {"cid": found["id"], "tenant": db.current_tenant()},
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
                      AND c.tenant_id = :tenant
                      AND (
                        RIGHT(regexp_replace(COALESCE(c.phone_primary, ''), '[^0-9]', '', 'g'), 4) = :tail4
                        OR RIGHT(regexp_replace(COALESCE(c.phone_alt, ''), '[^0-9]', '', 'g'), 4) = :tail4
                      )
                    LIMIT 2
                    """
                ),
                {
                    "tail4": digits[-4:],
                    "unknown": UNKNOWN_CALLER_ID,
                    "tenant": db.current_tenant(),
                },
            ).mappings().all()
            if len(matches) != 1:
                return None
            return _pack(matches[0])

        if method_n == "account_tail":
            digits = "".join(ch for ch in raw if ch.isdigit())
            tail = digits[-4:] if len(digits) >= 4 else ""
            if len(tail) != 4:
                return None
            matches = conn.execute(
                text(
                    """
                    SELECT c.id AS customer_id, c.name, c.phone_primary,
                           a.id AS account_id, a.outstanding, a.minimum_due, a.dpd
                    FROM accounts a
                    JOIN customers c ON c.id = a.customer_id
                    WHERE c.id <> :unknown
                      AND c.tenant_id = :tenant
                      AND RIGHT(regexp_replace(a.id, '[^0-9]', '', 'g'), 4) = :tail
                    ORDER BY a.outstanding DESC NULLS LAST
                    LIMIT 2
                    """
                ),
                {"tail": tail, "unknown": UNKNOWN_CALLER_ID, "tenant": db.current_tenant()},
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
                    WHERE c.id = :cid AND c.id <> :unknown AND c.tenant_id = :tenant
                    LIMIT 1
                    """
                ),
                {"cid": raw, "unknown": UNKNOWN_CALLER_ID, "tenant": db.current_tenant()},
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
    # Best-effort, like the alert writes in evaluate_and_flag_bot_turn and
    # start_voice_call: the handoff is already committed, so raising here would
    # report a failure for work that succeeded and invite a retry that writes a
    # second handoff row.
    try:
        append_live_alert(
            interaction_id=interaction_id,
            kind="escalation",
            reason=r,
            severity="high",
        )
    except Exception:
        logger.exception("live alert for handoff %s failed (handoff persisted)", hid)
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
    key = f"transcripts/{db.current_tenant()}/{filename}"

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
