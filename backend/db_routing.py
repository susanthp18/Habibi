"""Legacy voice escalation and treatment holds.

The retired Routing / Logic builder is not part of Voice Studio. This module
keeps the transactional human handoff used by the legacy voice runner.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from agent_core.clock import utc_now
from db_core import DEFAULT_BOT_ID, _activity, _actor_user_id, _id, _one, _tenant


def _db():
    import db

    return db


logger = logging.getLogger(__name__)

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
) -> dict[str, Any]:
    """Single-transaction escalate: handoff + note + inbox conversation.

    Collapses the four sequential pool round-trips previously done from
    ``voice.tools.escalate_to_human`` so PSTN calls spend one connection slot.
    """
    _mod = _db()
    engine = _db().engine
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

        # The retired rule builder no longer assigns handoffs. Keep the
        # existing default queue; human operators can reassign in the Inbox.
        assignee_user_id = None
        team_id = "card-collections"

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
        "assigneeName": (conv_row or {}).get("assigned_user_name"),
        "teamId": team_id,
        "teamName": None,
        "routing": {"matched": False, "teamId": team_id},
        "reason": r,
    }
