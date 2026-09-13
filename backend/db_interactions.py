"""Interactions: the calls list, the 360's interaction contracts, and the writes (a logged interaction, its wrap-up). Carved out of db.py."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from agent_core.clock import utc_now
from db_prompt_studio.deployments import DEFAULT_BOT_ID
from env_utils import env_int
from db_core import (
    _activity,
    _actor_user_id,
    _assert_tenant_owns,
    _dump,
    _duration,
    _ensure_customer,
    _ensure_interaction,
    _first_account_id,
    _id,
    _idempotent_response,
    _one,
    _rows,
    _sql,
    _store_idempotent_response,
    _tenant,
    _vis_params,
    clamp_list_limit,
    clamp_offset,
)


# Calls carry their whole transcript inline, so a call row is orders of
# magnitude larger than a customer row and gets its own, tighter default.
DEFAULT_CALLS_LIMIT = max(1, env_int("DEFAULT_CALLS_LIMIT", 100))


def _db():
    """The ``db`` module object, resolved at call time: tests route
    ``db.engine`` through a savepoint proxy, and the proxy must be the one
    the writes below open their transactions on."""
    import db as d

    return d


def _sentiment_delta(score: float | None) -> str:
    if score is None:
        return "flat"
    if score > 0.15:
        return "up"
    if score < -0.15:
        return "down"
    return "flat"


def _interaction_contracts(conn: Any, customer_id: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    # Tenant-scoped unconditionally. Filtering on customer_id alone was safe
    # only because every live caller passes one and customers are themselves
    # tenant-scoped; the customer_id=None path selected across tenants, and
    # neither the limit nor the tenant were required by the signature.
    where = "WHERE i.tenant_id = :tenant_id"
    params: dict[str, Any] = {"tenant_id": _tenant()}
    if customer_id:
        where += " AND i.customer_id = :customer_id"
        params["customer_id"] = customer_id
    # No unbounded branch: this loads full transcripts per interaction.
    params["limit"] = clamp_list_limit(limit, DEFAULT_CALLS_LIMIT)
    limit_sql = "LIMIT :limit"
    interactions = _rows(
        conn.execute(
            text(
                f"""
                SELECT
                  i.id,
                  i.channel,
                  i.handler_kind,
                  COALESCE(u.name, b.name) AS handler_name,
                  i.started_at,
                  i.duration_sec,
                  i.disposition,
                  i.sentiment_label,
                  i.avg_sentiment,
                  i.summary,
                  i.query_resolved,
                  i.upsell_presented,
                  i.ptp_captured
                FROM interactions i
                LEFT JOIN users u ON u.id = i.handler_user_id
                LEFT JOIN bots b ON b.id = i.handler_bot_id
                {where}
                ORDER BY i.started_at DESC NULLS LAST, i.id
                {limit_sql}
                """
            ),
            params,
        )
    )
    # Batch transcripts — avoid N+1 (one query per interaction).
    transcripts_by_id: dict[str, list[str]] = {row["id"]: [] for row in interactions}
    interaction_ids = list(transcripts_by_id)
    if interaction_ids:
        for trow in _rows(
            conn.execute(
                text(
                    """
                    SELECT interaction_id, text
                    FROM interaction_transcript
                    WHERE interaction_id = ANY(:ids)
                    ORDER BY interaction_id, turn_index
                    """
                ),
                {"ids": interaction_ids},
            )
        ):
            transcripts_by_id.setdefault(trow["interaction_id"], []).append(trow["text"])

    output = []
    for interaction in interactions:
        output.append(
            {
                "id": interaction["id"],
                "channel": interaction["channel"],
                "handler": {"kind": interaction["handler_kind"], "name": interaction["handler_name"] or "Unknown"},
                "startedAt": interaction["started_at"],
                "duration": _duration(interaction["duration_sec"]),
                "disposition": interaction["disposition"] or "Unknown",
                "sentiment": interaction["sentiment_label"] or "neutral",
                "sentimentDelta": _sentiment_delta(interaction["avg_sentiment"]),
                "summary": interaction["summary"] or "",
                "intents": {
                    "queryResolved": bool(interaction["query_resolved"]),
                    "upsellPresented": bool(interaction["upsell_presented"]),
                    "ptpCaptured": bool(interaction["ptp_captured"]),
                },
                "transcript": transcripts_by_id.get(interaction["id"], []),
            }
        )
    return output


def list_calls(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Audit-screen call list, newest first.

    Bounded and tenant-scoped. Both were missing: the outer query selected every
    interaction the deployment had ever recorded, and the four child queries
    below then loaded *every transcript turn of every one of them* into memory
    to assemble the response. That is fine against a demo seed and is a
    guaranteed outage against a real portfolio.
    """

    from schemas import CallResponse
    page = clamp_list_limit(limit, DEFAULT_CALLS_LIMIT)
    skip = clamp_offset(offset)
    with _db().engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    """
                    SELECT
                      i.id,
                      i.started_at,
                      i.duration_sec,
                      i.channel,
                      i.direction,
                      i.handler_kind,
                      COALESCE(u.name, b.name) AS handled_by,
                      i.customer_id,
                      c.name AS customer_name,
                      c.phone_primary,
                      i.account_id,
                      i.disposition,
                      i.summary,
                      i.avg_sentiment,
                      i.sentiment_label,
                      i.redaction_applied,
                      i.hash,
                      i.rag_hits,
                      i.latency_ms
                    FROM interactions i
                    JOIN customers c ON c.id = i.customer_id
                    LEFT JOIN users u ON u.id = i.handler_user_id
                    LEFT JOIN bots b ON b.id = i.handler_bot_id
                    WHERE i.tenant_id = :tenant_id
                      /*VISIBILITY*/
                    ORDER BY i.started_at DESC NULLS LAST, i.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"tenant_id": _tenant(), "limit": page, "offset": skip, **_vis_params()},
            )
        )
        # Four child tables, one query each — not four per interaction. The
        # per-row version issued 4N round trips against an unbounded outer
        # query, so the Calls screen got slower in direct proportion to how
        # long the deployment had been running.
        interaction_ids = [row["id"] for row in rows]

        def _grouped(sql: str) -> dict[str, list[dict[str, Any]]]:
            grouped: dict[str, list[dict[str, Any]]] = {}
            if not interaction_ids:
                return grouped
            for r in _rows(conn.execute(text(sql), {"interaction_ids": interaction_ids})):
                grouped.setdefault(r.pop("interaction_id"), []).append(r)
            return grouped

        transcripts_by = _grouped(
            """
            SELECT interaction_id, id, at_sec AS t, speaker, text
            FROM interaction_transcript
            WHERE interaction_id = ANY(:interaction_ids)
            ORDER BY interaction_id, turn_index
            """
        )
        flags_by = _grouped(
            """
            SELECT interaction_id, flag, severity
            FROM interaction_flags
            WHERE interaction_id = ANY(:interaction_ids)
            ORDER BY interaction_id, created_at
            """
        )
        sentiment_by = _grouped(
            """
            SELECT interaction_id, at_sec AS t, score AS v
            FROM interaction_sentiment
            WHERE interaction_id = ANY(:interaction_ids)
            ORDER BY interaction_id, at_sec
            """
        )
        disclosures_by = _grouped(
            """
            SELECT interaction_id, id, label, read, read_at_sec AS "atSec"
            FROM interaction_disclosures
            WHERE interaction_id = ANY(:interaction_ids)
            ORDER BY interaction_id, id
            """
        )

        calls = []
        for row in rows:
            transcript = transcripts_by.get(row["id"], [])
            flags = flags_by.get(row["id"], [])
            sentiment_series = sentiment_by.get(row["id"], [])
            disclosures = disclosures_by.get(row["id"], [])
            handled_by = {"kind": row["handler_kind"]}
            if row["handler_kind"] == "bot":
                handled_by["bot"] = row["handled_by"] or "Bot"
            else:
                handled_by["agent"] = row["handled_by"] or "Agent"
            calls.append(
                _dump(
                    CallResponse(
                        id=row["id"],
                        startedAt=row["started_at"],
                        duration=row["duration_sec"] or 0,
                        channel=row["channel"],
                        direction=row["direction"],
                        handledBy=handled_by,
                        customerId=row["customer_id"],
                        customerName=row["customer_name"],
                        accountId=row["account_id"],
                        disposition=row["disposition"],
                        summary=row["summary"],
                        avgSentiment=row["avg_sentiment"],
                        sentiment=row["sentiment_label"] or "neutral",
                        redactionApplied=bool(row["redaction_applied"]),
                        hash=row["hash"],
                        ragHits=row["rag_hits"] or 0,
                        latencyMs=row["latency_ms"],
                        transcript=transcript,
                        flags=flags,
                        phoneMasked=row["phone_primary"] or "",
                        tags=[row["disposition"]] if row["disposition"] else [],
                        sentimentSeries=sentiment_series,
                        disclosures=disclosures,
                        routing=["Postgres", "API"],
                    )
                )
            )
    return calls


def create_interaction(payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    from schemas import CallResponse

    endpoint = "POST /interactions"
    with _db().engine.begin() as conn:
        cached = _idempotent_response(conn, idempotency_key, endpoint)
        if cached:
            return cached
        customer_id = payload["customerId"]
        _ensure_customer(conn, customer_id)
        interaction_id = _id("CL")
        handler_kind = payload.get("handlerKind") or "human"
        # Attribution is the acting user, never a value the client chose.
        handler_user_id = _actor_user_id() if handler_kind == "human" else None
        handler_bot_id = payload.get("handlerBotId") or (DEFAULT_BOT_ID if handler_kind == "bot" else None)
        conn.execute(
            text(
                """
                INSERT INTO interactions
                  (id, tenant_id, customer_id, account_id, handler_kind, handler_user_id, handler_bot_id,
                   channel, direction, status, disposition, summary, started_at, source_payload)
                VALUES
                  (:id, :tenant_id, :customer_id, :account_id, :handler_kind, :handler_user_id, :handler_bot_id,
                   :channel, :direction, 'completed', :disposition, :summary, now(), '{}'::jsonb)
                """
            ),
            {"id": interaction_id, "tenant_id": _tenant(), "customer_id": customer_id, "account_id": payload.get("accountId") or _first_account_id(conn, customer_id), "handler_kind": handler_kind, "handler_user_id": handler_user_id, "handler_bot_id": handler_bot_id, "channel": payload.get("channel") or "voice", "direction": payload.get("direction") or "outbound", "disposition": payload.get("disposition"), "summary": payload.get("summary")},
        )
        import capture_events

        for idx, turn in enumerate(payload.get("transcript") or []):
            # The one transcript writer: a manually logged call is masked at
            # rest like a recorded one. An empty line is not a turn.
            if not (turn.get("text") or "").strip():
                continue
            capture_events.insert_transcript_turn(
                conn,
                interaction_id=interaction_id,
                turn_index=idx,
                speaker=turn.get("speaker") or "human",
                text_content=turn["text"],
                at_sec=turn.get("atSec") or 0,
            )
        _activity(conn, "interaction", interaction_id, "interaction_created", "Manual interaction logged", payload.get("summary"), customer_id)
        customer = _one(conn.execute(text("SELECT name, phone_primary FROM customers WHERE id = :id"), {"id": customer_id})) or {}
        response = _dump(
            CallResponse(
                id=interaction_id,
                startedAt=utc_now().isoformat(),
                duration=0,
                channel=payload.get("channel") or "voice",
                direction=payload.get("direction") or "outbound",
                handledBy={"kind": handler_kind, "agent" if handler_kind == "human" else "bot": handler_user_id or handler_bot_id or "unknown"},
                customerId=customer_id,
                customerName=customer.get("name") or customer_id,
                accountId=payload.get("accountId") or _first_account_id(conn, customer_id),
                disposition=payload.get("disposition"),
                summary=payload.get("summary"),
                phoneMasked=customer.get("phone_primary") or "",
                transcript=payload.get("transcript") or [],
            )
        )
        _store_idempotent_response(conn, idempotency_key, endpoint, response)
        return response


def wrap_up_interaction(interaction_id: str, payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    endpoint = f"POST /interactions/{interaction_id}/wrap-up"
    with _db().engine.begin() as conn:
        _assert_tenant_owns(conn, "interactions", interaction_id)
        cached = _idempotent_response(conn, idempotency_key, endpoint)
        if cached:
            return cached
        interaction = _ensure_interaction(conn, interaction_id)
        conn.execute(
            text(
                """
                UPDATE interactions
                SET disposition = :disposition,
                    summary = COALESCE(:notes, summary),
                    status = 'completed',
                    ended_at = COALESCE(ended_at, now()),
                    ptp_captured = ptp_captured OR :ptp,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": interaction_id,
                "disposition": payload["disposition"],
                "notes": payload.get("notes"),
                "ptp": bool(payload.get("promise")),
            },
        )
        conn.execute(
            text(
                """
                UPDATE interaction_handoffs
                SET completed_at = now()
                WHERE interaction_id = :id AND completed_at IS NULL
                """
            ),
            {"id": interaction_id},
        )
        for flag in payload.get("flags") or []:
            conn.execute(text("INSERT INTO interaction_flags (id, interaction_id, flag, severity) VALUES (:id, :interaction_id, :flag, 'medium')"), {"id": _id("FLAG"), "interaction_id": interaction_id, "flag": flag})
        spawned: dict[str, Any] = {}
        # Connection-scoped: a wrap-up spawning a promise, a dispute and a
        # callback is one atomic outcome. The public create_* entrypoints open
        # their own transaction, so a failure after the second spawn used to
        # leave the first two committed while the wrap-up itself rolled back —
        # and the idempotent replay then spawned them a second time.
        from db_callbacks import _create_callback
        from db_disputes import _create_dispute
        from db_promises import _create_promise

        if payload.get("promise"):
            promise_payload = {**payload["promise"], "customerId": interaction["customer_id"], "accountId": interaction["account_id"], "interactionId": interaction_id}
            spawned["promise"] = _create_promise(conn, promise_payload, None, "POST /promises")
        if payload.get("dispute"):
            dispute_payload = {**payload["dispute"], "customerId": interaction["customer_id"], "accountId": interaction["account_id"], "interactionId": interaction_id}
            spawned["dispute"] = _create_dispute(conn, dispute_payload, None, "POST /disputes")
        if payload.get("callback"):
            callback_payload = {**payload["callback"], "customerId": interaction["customer_id"], "accountId": interaction["account_id"], "interactionId": interaction_id}
            spawned["callback"] = _create_callback(conn, callback_payload)
        _activity(conn, "interaction", interaction_id, "interaction_wrapped_up", "Interaction wrapped up", payload.get("notes"), interaction["customer_id"])
        response = {"id": interaction_id, "spawned": spawned}
        _store_idempotent_response(conn, idempotency_key, endpoint, response)
        return response
