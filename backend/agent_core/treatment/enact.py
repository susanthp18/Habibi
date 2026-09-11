"""Carrying out a plan — the only part of this package that touches a borrower.

Two rules, and everything else follows from them.

**Live mode only.** A shadow decision is never enacted, no matter how it got
here. The check is at the top of :func:`enact_one` rather than left to the
caller, because "the worker was pointed at the wrong environment" is exactly the
mistake that shadow mode exists to survive.

**The gate runs again at send time, not at plan time.** A plan made at 09:00 for
19:30 is a plan made against a contact budget that has since been spent, a
consent that may have been withdrawn, and a borrower who may have paid. So
every enactment calls ``contact_policy.admit`` — the reserving, fail-closed
version — immediately before the send. That is also the call that books the
touch, so the treatment engine cannot spend budget it did not account for.

Field visits and statutory notices have no executor here, and that is the
roadmap's sequencing rather than an omission: dispatch is P8 and the legal
clocks are P9. The engine still *recommends* them, which is what makes the
shadow log tell a collections head how much field work the ladder would
generate before anybody builds the dispatcher. Until then they are recorded as
cancelled with the executor named, so they show up in the scoreboard rather
than silently retrying forever.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from agent_core.clock import as_utc
from agent_core.treatment import actions as A, attempts, cancel, config, decisions, reservations

logger = logging.getLogger(__name__)

#: Actions whose executor is a later roadmap item.
DEFERRED: frozenset[str] = frozenset({A.FIELD_VISIT, A.LEGAL_NOTICE})

#: Enqueued rather than sent inside the claim transaction. Queuing is not
#: enactment: ``enacted`` stays false until a provider reference exists.
QUEUED_ACTIONS: frozenset[str] = frozenset({A.WHATSAPP})

#: A plan this stale is about a situation that has moved on. Re-deciding is
#: cheaper and safer than dialling on yesterday's reasoning.
MAX_PLAN_AGE = timedelta(hours=12)


class NoExecutor(RuntimeError):
    """The action is understood and deliberately not carried out yet."""


def _enqueue_work(
    conn: Any,
    *,
    workflow_type: str,
    customer_id: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> str:
    """Idempotent enqueue onto the work-runtime port. One work item per key."""
    from work_runtime import start_workflow

    job = start_workflow(
        workflow_type=workflow_type,
        payload=payload,
        customer_id=customer_id,
        idempotency_key=idempotency_key,
        conn=conn,
    )
    return f"work:{job['id']}"


def enact_one(
    conn: Any, decision: dict[str, Any], *, enacted_by: str = "treatment_executor"
) -> tuple[bool, str]:
    """Carry out one claimed plan. Returns (acted, note). Never raises."""
    decision_id = decision["id"]
    action = str(decision.get("chosen_action") or A.WAIT)

    if config.mode() != config.MODE_LIVE:
        # Belt and braces: claim_due should not have returned this, but a
        # shadow decision must not become a real contact through any path.
        return False, "not_live"

    scheduled = decision.get("scheduled_at")
    if isinstance(scheduled, datetime):
        at = scheduled if scheduled.tzinfo else scheduled.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - at > MAX_PLAN_AGE:
            decisions.record_outcome(
                decision_id, "cancelled", conn=conn, cancel_reason=cancel.PLAN_EXPIRED
            )
            return False, "plan_expired"

    if action in DEFERRED:
        decisions.record_outcome(
            decision_id, "cancelled", conn=conn, cancel_reason=cancel.NO_EXECUTOR
        )
        logger.info(
            "treatment %s recommended %s — no executor yet (roadmap P8/P9)",
            decision_id,
            action,
        )
        return False, f"no_executor:{action}"

    handler = _HANDLERS.get(action)
    if handler is None:
        decisions.record_outcome(
            decision_id, "cancelled", conn=conn, cancel_reason=cancel.UNKNOWN_ACTION
        )
        return False, f"unknown_action:{action}"

    customer = _customer(conn, decision["customer_id"])
    if customer is None:
        decisions.record_outcome(
            decision_id, "cancelled", conn=conn, cancel_reason=cancel.CUSTOMER_ROW_MISSING
        )
        return False, "customer_gone"

    # Still worth doing? A borrower who paid between planning and sending must
    # not be dunned for it.
    if _paid_since_decision(conn, decision):
        decisions.record_outcome(
            decision_id, "cancelled", conn=conn, cancel_reason=cancel.PAID_SINCE_DECISION
        )
        return False, "paid_since_decision"
    if _resolved_since(conn, decision):
        decisions.record_outcome(decision_id, "superseded", conn=conn)
        return False, "already_resolved"

    import contact_policy

    spec = A.spec(action)
    admitted = None
    # A voice plan is gated by `outbound.gate` inside `_dial_bot`, on the
    # attempt row itself, so the refusal is a suppressed attempt. Gating it
    # here as well would count the same touch twice against the budget.
    if spec.channel and action != A.VOICE_BOT:
        admitted = contact_policy.admit(
            conn,
            customer_id=decision["customer_id"],
            channel=spec.channel,
            purpose="outreach",
            session_key=decision_id,
            source="treatment",
            related_id=decision_id,
            actor_kind=spec.actor_kind if spec.actor_kind in {"bot", "human", "system", "agency"} else "system",
            account_id=decision.get("account_id"),
            endpoint=contact_policy.chosen_phone(customer),
            product_id=decision.get("product_id"),
        )
        if not admitted.allowed:
            decisions.record_outcome(
                decision_id, "cancelled", conn=conn, cancel_reason=cancel.CONTACT_GATE_REFUSED
            )
            return False, f"contact:{admitted.reason}"

    try:
        from agent_core.treatment import contract as action_contract
        from bank_boundary.snapshots import ContractError

        envelope = action_contract.require_for_enactment(conn, decision, customer)
        decision["_action_contract"] = envelope
        _consume_contract(envelope, decision)
        ref = handler(conn, decision=decision, customer=customer, contract=envelope)
    except ContractError as exc:
        decisions.record_outcome(
            decision_id, "cancelled", conn=conn, cancel_reason=cancel.CONTACT_GATE_REFUSED
        )
        return False, f"contract:{exc}"
    except NoExecutor as exc:
        reason = cancel.from_note(str(exc))
        decisions.record_outcome(
            decision_id, "cancelled", conn=conn, cancel_reason=reason
        )
        return False, str(exc)
    except Exception:
        logger.exception("treatment enactment failed for %s", decision_id)
        decisions.record_outcome(
            decision_id, "cancelled", conn=conn, cancel_reason=cancel.HANDLER_EXCEPTION
        )
        return False, "enactment_failed"

    if str(ref or "").startswith("queued:"):
        # Queued is not sent. The drain marks enacted once a provider reference
        # exists. A stubbed handler that returns a send-shaped ref still marks.
        return True, ref

    decisions.mark_enacted(decision_id, ref=ref, conn=conn, enacted_by=enacted_by)
    return True, ref or action


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _consume_contract(contract: dict[str, Any] | None, decision: dict[str, Any]) -> None:
    """Handlers refuse missing, stale, tampered, or unsupported snapshots."""
    from bank_boundary import ACTION_CONTRACT_VERSION
    from bank_boundary import snapshots
    from bank_boundary.snapshots import ContractError

    if not contract:
        raise NoExecutor("missing_action_contract")
    decision_id = str(decision.get("id") or "")
    got = str(contract.get("decision_id") or contract.get("decisionId") or "")
    if got != decision_id:
        raise NoExecutor("stale_action_contract")
    if contract.get("version") != ACTION_CONTRACT_VERSION:
        raise NoExecutor("unsupported_contract_version")
    try:
        snapshots.validate(contract)
    except ContractError as exc:
        raise NoExecutor(f"invalid_action_contract:{exc}") from exc
    expected = {
        "action": decision.get("chosen_action"),
        "channel": decision.get("chosen_channel"),
        "tenant_id": decision.get("tenant_id"),
        "policy_binding_hash": decision.get("policy_binding_hash"),
    }
    if any(
        value is not None and contract.get(key) != value
        for key, value in expected.items()
    ):
        raise NoExecutor("stale_action_contract")


def _customer(conn: Any, customer_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id, tenant_id, name, phone_primary, phone_alt, language,
                   assigned_user_id
            FROM customers WHERE id = :id
            """
        ),
        {"id": customer_id},
    ).mappings().first()
    return dict(row) if row else None


def _resolved_since(conn: Any, decision: dict[str, Any]) -> bool:
    """Has the reason for contacting them gone away?"""
    ref = decision.get("trigger_ref")
    kind = decision.get("trigger_kind")
    if kind == "bounce" and ref:
        status = conn.execute(
            text("SELECT status FROM payment_events WHERE id = :id"), {"id": ref}
        ).scalar()
        return status in {"cured", "suppressed"} or status is None
    if kind == "broken_ptp" and ref:
        status = conn.execute(
            text("SELECT status FROM promises WHERE id = :id"), {"id": ref}
        ).scalar()
        return status in {"kept", "partial"} or status is None
    if kind == "dpd_tick":
        dpd = conn.execute(
            text("SELECT dpd FROM accounts WHERE id = :id"),
            {"id": decision.get("account_id")},
        ).scalar()
        return dpd is None or int(dpd) <= 0
    return False


def _paid_since_decision(conn: Any, decision: dict[str, Any]) -> bool:
    """A payment posted after this plan was written. Distinct from trigger cure."""
    account_id = decision.get("account_id")
    created = decision.get("created_at")
    known = decision.get("features_known_ts") or created
    if not account_id or created is None:
        return False
    from agent_core.treatment import schema_ready

    if schema_ready.w6_ready(conn):
        statement = """
            SELECT 1
              FROM fct_payment
             WHERE account_id = :aid
               AND known_from > :since
             LIMIT 1
        """
    else:
        statement = """
            SELECT 1 FROM ledger_entries
             WHERE account_id = :aid
               AND type = 'payment'
               AND posted_at > :since
             LIMIT 1
        """
    found = conn.execute(
        text(statement), {"aid": account_id, "since": known if schema_ready.w6_ready(conn) else created}
    ).fetchone()
    return found is not None


def _open_pay_url(conn: Any, decision: dict[str, Any]) -> tuple[str | None, Any]:
    """The live pay-link for this account, if one exists.

    Deliberately does not mint a new one. A payment intent is a money object
    with an expiry and a public token; the treatment engine's job is to pick
    the moment, not to issue instruments. Where a bounce or a PTP already
    created one, the nudge carries it; where none exists the nudge is a
    reminder without a link.
    """
    row = conn.execute(
        text(
            """
            SELECT id, pay_url, amount FROM payment_intents
            WHERE customer_id = :cid
              AND (CAST(:aid AS TEXT) IS NULL OR account_id = :aid)
              AND status IN ('created','sent','opened')
              AND (expires_at IS NULL OR expires_at > now())
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"cid": decision["customer_id"], "aid": decision.get("account_id")},
    ).mappings().first()
    if row is None:
        return None, None
    return row["pay_url"], row["amount"]


def _copy(conn: Any, decision: dict[str, Any], *, tenant_id: str | None = None) -> str:
    """The message body. Statutory disclosure first, then the ask.

    RBI's Digital Lending Guidelines require the regulated entity, the loan
    reference and a grievance route to be identifiable on any collections
    communication. Composing that here rather than in a template means a channel
    added later cannot ship without it.

    That was the intent and, until now, not the behaviour: the body ended
    ``"Queries: reply to this message."``, which is a reply-to and not a
    grievance route. ¶100AA wants the officer's name, telephone number and
    email in every recovery communication, and this is one. The footer now comes
    from :mod:`compliance_copy`, the same renderer the voicemail path uses, and
    a tenant with no officer on file raises rather than sends — the identical
    call made for voicemail, made once.

    On SMS the footer usually costs a second segment. That is the price of the
    disclosure and not an argument against carrying it; a cheaper message that
    omits it is not cheaper, it is non-compliant.
    """
    import compliance_copy
    import db as dbmod

    # The borrower's own tenant where the caller knows it. This worker drains a
    # queue that spans tenants and never binds one, so `current_tenant()` here
    # is the process default rather than the bank whose borrower is about to be
    # messaged - which would eventually put one bank's grievance officer, and
    # one bank's brand, into another bank's dunning message.
    footer = compliance_copy.written_footer(compliance_copy.tenant_contacts(tenant_id))
    if footer is None:
        raise NoExecutor(compliance_copy.NO_GRIEVANCE_CONTACT)

    pay_url, amount = _open_pay_url(conn, decision)
    account_ref = decision.get("account_id") or "your account"
    tail = str(account_ref)[-4:]
    money = ""
    if amount is not None:
        import promise_fulfillment as pf

        money = f" of ₹{pf._fmt_inr(amount)}"
    brand = (tenant_id or dbmod.current_tenant()).split(".")[0].upper()
    ask = (
        f"Pay securely here: {pay_url}. Do not share this link."
        if pay_url
        else "Please call us on the number on your statement to arrange payment."
    )
    return (
        f"{brand}: your instalment{money} on the account ending {tail} is overdue. "
        f"{ask} {footer}"
    )


def _send_whatsapp(
    conn: Any,
    *,
    decision: dict[str, Any],
    customer: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> str:
    import promise_fulfillment as pf

    phone = customer.get("phone_primary")
    if not phone:
        raise NoExecutor("no_phone_on_file")
    pay_url, amount = _open_pay_url(conn, decision)
    body = _copy(conn, decision, tenant_id=customer.get("tenant_id"))
    intent = {"amount": amount or 0, "pay_url": pay_url or ""}
    conversation_id = _conversation(conn, customer["id"])
    inside = pf._inside_service_window(conn, conversation_id)
    template_name = pf.resolve_template(
        "WHATSAPP_TREATMENT_TEMPLATE_NAME", "WHATSAPP_TREATMENT_TEMPLATE_LANG"
    )[0]
    if not inside and not template_name:
        # Outside Meta's 24-hour service window a freeform message is not
        # deliverable, and pretending otherwise burns the plan for nothing.
        raise NoExecutor("outside_service_window_no_template")
    outbound = _outbox_send(conn, customer, decision, contract, "O1")
    if not outbound.get("submitted"):
        return f"queued:reference:{outbound['id']}"
    pf.enqueue_whatsapp_paylink(
        conn,
        customer_id=customer["id"],
        intent=intent,
        to_phone=phone,
        body=body,
        use_template=not inside,
        purpose="outreach",
        source="treatment",
        template_env_name="WHATSAPP_TREATMENT_TEMPLATE_NAME",
        template_env_lang="WHATSAPP_TREATMENT_TEMPLATE_LANG",
        template_params=[str(customer.get("name") or ""), pay_url or ""] if not inside else None,
        decision_id=decision["id"],
    )
    return f"queued:whatsapp:{conversation_id}"


def _conversation(conn: Any, customer_id: str) -> str:
    import db as dbmod

    return dbmod._open_whatsapp_conversation(conn, customer_id)


def _send_sms(
    conn: Any,
    *,
    decision: dict[str, Any],
    customer: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> str:
    import twilio_sms

    phone = customer.get("phone_primary")
    if not phone:
        raise NoExecutor("no_phone_on_file")
    body = _copy(conn, decision, tenant_id=customer.get("tenant_id"))
    outbound = _outbox_send(conn, customer, decision, contract, "O1")
    if not outbound.get("submitted"):
        return f"queued:reference:{outbound['id']}"
    if not twilio_sms.configured():
        raise NoExecutor("sms_not_configured")
    # The decision id is the ``related_id`` on the contact event too, so the
    # receipt, the attempt and the decision that caused it all key together
    # without a join table.
    result = twilio_sms.send(
        to_phone=phone,
        body=body,
        customer_id=customer["id"],
        tenant_id=customer.get("tenant_id"),
        related_id=decision["id"],
    )
    return f"sms:{result.get('sid') or 'sent'}"


def _dial_bot(
    conn: Any,
    *,
    decision: dict[str, Any],
    customer: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> str:
    """Place the engine's call, through the attempt ledger.

    The attempt is reserved on its **own** short transaction rather than on
    ``conn``. The executor's transaction is still open at this point, so a row
    written on it would be invisible to :func:`outbound.place`, which opens its
    own connections — the fleet-gate count would miss it and the post-dial
    UPDATE would match nothing. Committing first also means a crash mid-dial
    leaves evidence rather than a spent contact budget with no cause; the
    orphan is reaped by ``outbound.sweep_stale``.
    """
    import db as dbmod
    import mission as mission_mod
    import outbound

    phone = customer.get("phone_primary")
    if not phone:
        raise NoExecutor("no_phone_on_file")
    slot = "primary" if customer.get("phone_primary") else "alt"
    objective = _objective_for(decision)

    with dbmod.engine.begin() as own:
        # The agent that will run this mission, and the envelope it may work
        # inside. Resolved here rather than in the voice worker because the card
        # is what decides whether this agent is even allowed on this mission —
        # and a dial placed against a card that forbids it should not happen at
        # all, rather than be discovered once the borrower has answered.
        bot_id = mission_mod.resolve_outbound_bot_id(
            decision=decision, objective=objective
        )
        card = mission_mod.card_for_bot(bot_id)
        # Two refusals, widest first. The old order asked "does this card claim
        # this mission" only when `dials` was already true, so the one setting
        # that says *never call anybody* was the one setting that skipped the
        # check — an inbound-only card dialled out, and did it unguarded.
        if card is not None and not card.outbound.dials:
            raise NoExecutor("card_forbids_outbound")
        if card is not None and card.outbound.objectives:
            if card.outbound.objective(objective) is None:
                raise NoExecutor(f"card_forbids_mission:{objective}")
        built = mission_mod.build(
            own,
            customer_id=customer["id"],
            objective=objective,
            account_id=decision.get("account_id"),
            card=card,
            bot_id=bot_id,
            decision=decision,
        )
        built["actionContract"] = contract
        # The contact gate for a voice plan runs *here*, on the row it gates —
        # not in `enact_one` — so a refusal is a suppressed attempt rather
        # than a decision cancelled with no attempt to show for it. One
        # reservation per decision: a decision re-claimed after a crash finds
        # the attempt it already made.
        gated = outbound.gate(
            own,
            idempotency_key=f"decision:{decision['id']}",
            admit={
                "source": "treatment",
                "actor_kind": "bot",
                "product_id": decision.get("product_id"),
            },
            customer_id=customer["id"],
            to_phone=phone,
            objective=objective,
            account_id=decision.get("account_id"),
            decision_id=decision["id"],
            phone_slot=slot,
            policy_version=decision.get("policy_version"),
            tenant_id=customer.get("tenant_id"),
            bot_id=bot_id,
            context={
                "trigger": decision.get("trigger_kind"),
                "expectedValueInr": float(decision["expected_value"])
                if decision.get("expected_value") is not None
                else None,
                "propensity": decision.get("propensity"),
                "variant": decision.get("variant"),
                "mission": built,
            },
        )
    attempt = gated.attempt
    if attempt is None:
        raise NoExecutor("customer_gone")
    if gated.existing:
        return f"voice:{attempt['id']}"
    if not gated.allowed:
        raise NoExecutor(f"contact:{gated.reason}")

    result = outbound.place(dbmod.engine, attempt, to_phone=phone)
    if not result.get("placed"):
        # Not an error the executor should retry into: the plan stays claimed
        # and the reason is on the attempt row. `fleet_busy` in particular is a
        # capacity fact, not a fact about this borrower.
        raise NoExecutor(str(result.get("reason") or "dial_refused"))
    return f"voice:{result.get('callSid') or attempt['id']}"


def _objective_for(decision: dict[str, Any]) -> str:
    """Trigger kind → the mission this call is on.

    Delegates to ``mission.objective_for_trigger`` rather than keeping a second
    copy: two maps of the same relationship is two answers to one question, and
    the one that drifts is always the one nobody is looking at.
    """
    import mission as mission_mod

    return mission_mod.objective_for_trigger(decision.get("trigger_kind"))


def _queue_human(
    conn: Any,
    *,
    decision: dict[str, Any],
    customer: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> str:
    """Put it in front of a person, with the reasoning attached.

    A follow-up rather than a callback: a callback is something the borrower
    asked for at a time they chose, and mislabelling an engine-initiated dial as
    one would corrupt the callback SLA the workspace reports on.
    """
    import db as dbmod

    followup_id = dbmod._id("FUP")
    at = decision.get("scheduled_at") or datetime.now(timezone.utc)
    conn.execute(
        text(
            """
            INSERT INTO followups (
              id, promise_id, lead_id, customer_id, assignee_user_id,
              status, priority, due_at, note, channel
            ) VALUES (
              :id, :promise_id, NULL, :customer_id, :assignee,
              'open', :priority, :due_at, :note, 'voice'
            )
            """
        ),
        {
            "id": followup_id,
            # followups requires exactly one of promise_id / lead_id. A broken
            # PTP has one; a bounce does not, which is why bounce-triggered
            # human work is queued against the promise when there is one and
            # refused rather than faked when there is not.
            "promise_id": _promise_ref(conn, decision),
            "customer_id": customer["id"],
            "assignee": customer.get("assigned_user_id"),
            "priority": "high" if (decision.get("trigger_kind") == "broken_ptp") else "normal",
            "due_at": at,
            "note": (decision.get("rationale") or "Treatment engine: agent call")[:500],
        },
    )
    return f"followup:{followup_id}"


def _promise_ref(conn: Any, decision: dict[str, Any]) -> str:
    ref = decision.get("trigger_ref")
    if decision.get("trigger_kind") == "broken_ptp" and ref:
        return str(ref)
    row = conn.execute(
        text(
            """
            SELECT id FROM promises
            WHERE customer_id = :cid
            ORDER BY promised_at DESC
            LIMIT 1
            """
        ),
        {"cid": decision["customer_id"]},
    ).scalar()
    if not row:
        # The table's CHECK requires a promise or a lead. Rather than inventing
        # a promise to satisfy it, refuse: an agent-call recommendation for a
        # borrower with no promise history belongs in the queue as a bounce
        # work item, which the work_items view already projects.
        raise NoExecutor("no_promise_to_attach_followup_to")
    return str(row)


def _represent_mandate(
    conn: Any,
    *,
    decision: dict[str, Any],
    customer: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> str:
    """Submit the standing instruction again for the unpaid cycle.

    **The mandate state is re-read here, not trusted from the plan.** This is
    the same discipline the contact gate gets in :func:`enact_one` and it exists
    for a sharper reason: a plan made at 09:00 for a presentment at 15:00 was
    made against a mandate the borrower may since have cancelled, and presenting
    a debit against a withdrawn authority is not a missed collection — it is an
    unauthorised debit. There is no version of that which is recoverable by
    apologising.

    Both executors write the same row. What differs is who submits it: with
    ``rail`` we do, and the row is born ``submitted``; with ``lms`` the lender
    does, and the row is ``scheduled`` until their webhook settles it. The
    ``decision_id`` on that row is what lets either outcome be attributed back
    to the decision that asked for it.
    """
    import db as dbmod

    prepared_id = decision.get("_prepared_presentation_id")
    prepared_outbox_id = decision.get("_prepared_outbox_id")
    if prepared_id and prepared_outbox_id:
        prepared = conn.execute(
            text(
                """
                SELECT p.id, p.tenant_id, p.mandate_id, p.account_id,
                       p.amount, p.presented_for, p.status, p.decision_id,
                       m.status AS mandate_status, m.rail
                  FROM mandate_presentations p
                  JOIN mandates m ON m.id = p.mandate_id
                 WHERE p.id = :id AND p.decision_id = :did
                 FOR UPDATE OF p, m
                """
            ),
            {"id": prepared_id, "did": decision["id"]},
        ).mappings().first()
        if prepared is None:
            raise NoExecutor("prepared_presentation_missing")
        if str(prepared["mandate_status"]).lower() != "active":
            raise NoExecutor(f"mandate_{prepared['mandate_status']}")
        from bank_boundary import adapters

        envelope = {
            **(contract or decision.get("_action_contract") or {}),
            "presentation_id": str(prepared["id"]),
            "mandate_id": str(prepared["mandate_id"]),
            "account_id": str(prepared["account_id"]),
            "amount_paise": int(round(float(prepared["amount"]) * 100)),
            "presented_for": str(prepared["presented_for"]),
            "rail": str(prepared["rail"]),
        }
        ack = adapters.send_with_outbox(
            conn,
            tenant_id=str(prepared["tenant_id"]),
            contract_code="O2",
            action_contract=envelope,
            idempotency_key=str(prepared["id"]),
            prepared_outbox_id=str(prepared_outbox_id),
        )
        conn.execute(
            text(
                """
                UPDATE mandate_presentations
                   SET status = 'awaiting_settlement',
                       presented_at = CASE
                         WHEN :submitted THEN now()
                         ELSE presented_at
                       END,
                       updated_at = now()
                 WHERE id = :id
                """
            ),
            {"id": prepared["id"], "submitted": bool(ack.get("submitted"))},
        )
        return (
            f"rail:{ack.get('ack', {}).get('provider_ref')}"
            if ack.get("submitted")
            else f"queued:reference:{ack['id']}"
        )

    account_id = decision.get("account_id")
    if not account_id:
        raise NoExecutor("no_account_on_decision")

    state = conn.execute(
        text(
            """
            SELECT m.id, m.status, m.max_amount, m.rail,
                   e.id  AS emi_id,
                   e.due_date::date AS cycle,
                   GREATEST(e.amount - COALESCE(e.paid_amount, 0), 0) AS due_amount
            FROM mandates m
            LEFT JOIN LATERAL (
              SELECT id, due_date, amount, paid_amount
              FROM emi_installments
              WHERE account_id = m.account_id
                AND status IN ('overdue','partial','upcoming')
              ORDER BY due_date ASC, installment_index ASC
              LIMIT 1
            ) e ON TRUE
            WHERE m.account_id = :aid
            ORDER BY (m.status = 'active') DESC, m.registered_at DESC NULLS LAST, m.id
            LIMIT 1
            FOR UPDATE OF m
            """
        ),
        {"aid": account_id},
    ).mappings().first()

    if state is None:
        raise NoExecutor("no_mandate_on_file")
    if str(state["status"]).lower() != "active":
        raise NoExecutor(f"mandate_{state['status']}")
    if state["cycle"] is None:
        raise NoExecutor("no_unpaid_cycle_to_present")

    amount = float(state["due_amount"] or 0.0)
    if amount <= 0:
        raise NoExecutor("nothing_due_on_this_cycle")
    ceiling = state["max_amount"]
    if ceiling is not None:
        # Present what the mandate authorises, not what is owed. A request
        # above the ceiling is refused by the rail and still earns the borrower
        # a return, so collecting part of the instalment strictly beats
        # collecting none of it and charging them for the attempt.
        amount = min(amount, float(ceiling))

    attempt_no = int(
        conn.execute(
            text(
                """
                SELECT COALESCE(max(attempt_no), 0) + 1
                FROM mandate_presentations
                WHERE mandate_id = :mid AND presented_for = :cycle
                """
            ),
            {"mid": state["id"], "cycle": state["cycle"]},
        ).scalar()
        or 1
    )

    executor = config.mandate_executor()
    presentation_id = dbmod._id("MP")
    scheduled = decision.get("scheduled_at") or datetime.now(timezone.utc)

    conn.execute(
        text(
            """
            INSERT INTO mandate_presentations (
              id, tenant_id, mandate_id, account_id, emi_installment_id,
              amount, presented_for, attempt_no, scheduled_at, presented_at,
              status, executor, decision_id
            ) VALUES (
              :id, :tenant_id, :mandate_id, :account_id, :emi_id,
              :amount, :cycle, :attempt_no, :scheduled_at, :presented_at,
              :status, :executor, :decision_id
            )
            """
        ),
        {
            "id": presentation_id,
            "tenant_id": customer["tenant_id"],
            "mandate_id": state["id"],
            "account_id": account_id,
            "emi_id": state["emi_id"],
            "amount": amount,
            "cycle": state["cycle"],
            "attempt_no": attempt_no,
            "scheduled_at": scheduled,
            "presented_at": None,
            "status": "scheduled",
            "executor": executor,
            "decision_id": decision["id"],
        },
    )

    if executor == config.MANDATE_EXECUTOR_RAIL:
        from bank_boundary import outbox

        envelope = {
            **(contract or decision.get("_action_contract") or {}),
            "presentation_id": presentation_id,
            "mandate_id": str(state["id"]),
            "account_id": str(account_id),
            "amount_paise": int(round(amount * 100)),
            "presented_for": str(state["cycle"]),
            "rail": str(state["rail"]),
        }
        outbox_id = outbox.enqueue(
            conn,
            tenant_id=str(customer["tenant_id"]),
            contract_code="O2",
            idempotency_key=presentation_id,
            payload=envelope,
            action_contract_id=envelope.get("contract_id"),
            decision_id=str(decision["id"]),
        )
        decision["_prepared_presentation_id"] = presentation_id
        decision["_prepared_outbox_id"] = outbox_id
        return f"queued:prepared:{outbox_id}"

    ref = _hand_to_lms(
        conn,
        decision=decision,
        customer=customer,
        presentation_id=presentation_id,
        amount=amount,
        cycle=state["cycle"],
        contract=contract,
    )
    conn.execute(
        text(
            """
            UPDATE mandate_presentations
               SET status = 'awaiting_settlement', updated_at = now()
             WHERE id = :id
            """
        ),
        {"id": presentation_id},
    )
    return ref


def _submit_to_rail(
    *, presentation_id: str, mandate_id: str, rail: str, amount: float, cycle: Any
) -> str:
    """Hand the debit to the payment rail through a configured adapter.

    There is no adapter in this repository, and this refuses rather than
    pretending — the same choice ``_promise_ref`` makes when there is no
    promise to attach a follow-up to. Writing a ``submitted`` row for a debit
    nothing submitted would put a presentation in the ledger that the rail has
    never heard of, and the settlement poller would wait for a return that
    cannot arrive.

    ``TREATMENT_MANDATE_RAIL_MODULE`` names a module exposing
    ``present(presentation_id, mandate_id, rail, amount, cycle) -> str``.
    """
    import importlib

    module_name = (os.getenv("TREATMENT_MANDATE_RAIL_MODULE") or "").strip()
    if not module_name:
        raise NoExecutor("no_mandate_rail_adapter_configured")
    try:
        adapter = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - configuration error
        raise NoExecutor(f"mandate_rail_adapter_unimportable:{exc}") from exc
    present = getattr(adapter, "present", None)
    if present is None:
        raise NoExecutor(f"mandate_rail_adapter_has_no_present:{module_name}")
    return str(
        present(
            presentation_id=presentation_id,
            mandate_id=mandate_id,
            rail=rail,
            amount=amount,
            cycle=cycle,
        )
    )


def _hand_to_lms(
    conn: Any,
    *,
    decision: dict[str, Any],
    customer: dict[str, Any],
    presentation_id: str,
    amount: float,
    cycle: Any,
    contract: dict[str, Any] | None = None,
) -> str:
    """Ask the lender's own system to present, and record that we asked.

    The default path, because it is the safe half of the authority question:
    recommending a presentment the lender declines costs a missed collection,
    and presenting a debit we were never authorised to present costs
    considerably more.

    The work item is keyed on the presentation id, so a retried executor asks
    once. The outcome comes back through the ordinary ``payment_events``
    webhook, which is why the presentation row carries ``payment_event_id``.
    """
    outbound = _outbox_send(conn, customer, decision, contract, "O6")
    if not outbound.get("submitted"):
        return f"queued:reference:{outbound['id']}"
    return _enqueue_work(
        conn,
        workflow_type="o6_lms_workitem",
        customer_id=customer["id"],
        payload={
            "presentationId": presentation_id,
            "decisionId": decision["id"],
            "accountId": decision.get("account_id"),
            "amount": round(amount, 2),
            "presentedFor": str(cycle),
            "rationale": (decision.get("rationale") or "")[:500],
            "contractVersion": contract.get("version") if contract else None,
            "actionContractId": contract.get("contract_id") if contract else None,
            "actionContractDigest": contract.get("digest") if contract else None,
        },
        idempotency_key=f"mandate-representment:{presentation_id}",
    )


def _change_emi_date(
    conn: Any,
    *,
    decision: dict[str, Any],
    customer: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> str:
    """Ask for the instalment date to be moved behind the salary credit.

    Never applied directly. Moving a due date changes the borrower's repayment
    contract and the lender's own accrual — it is an amendment, not a setting,
    and the engine's job is to notice that the calendar is the problem and say
    so. The work runtime carries it to whoever is allowed to agree.

    The proposed day is derived rather than asked for, and clamped to the 28th:
    a mandate set for the 30th silently skips February on some rails, and a
    schedule that is right eleven months a year is a bug with an alibi.
    """
    row = conn.execute(
        text(
            """
            SELECT next_credit_at
            FROM payment_events
            WHERE customer_id = :cid
              AND (CAST(:aid AS TEXT) IS NULL OR account_id = :aid)
              AND next_credit_at IS NOT NULL
            ORDER BY occurred_at DESC
            LIMIT 1
            """
        ),
        {"cid": decision["customer_id"], "aid": decision.get("account_id")},
    ).mappings().first()
    if row is None:
        raise NoExecutor("no_salary_credit_signal")

    credit_day = (as_utc(row["next_credit_at"]) or datetime.now(timezone.utc)).day
    proposed = min(28, credit_day + EMI_DATE_BUFFER_DAYS)

    outbound = _outbox_send(conn, customer, decision, contract, "O6")
    if not outbound.get("submitted"):
        return f"queued:reference:{outbound['id']}"
    return _enqueue_work(
        conn,
        workflow_type="emi_date_change",
        customer_id=customer["id"],
        payload={
            "decisionId": decision["id"],
            "accountId": decision.get("account_id"),
            "proposedDueDay": proposed,
            "salaryCreditDay": credit_day,
            "rationale": (decision.get("rationale") or "")[:500],
            "contractVersion": contract.get("version") if contract else None,
            "actionContractId": contract.get("contract_id") if contract else None,
            "actionContractDigest": contract.get("digest") if contract else None,
        },
        idempotency_key=f"emi-date-change:{decision['id']}",
    )


def _open_self_service_plan(
    conn: Any,
    *,
    decision: Any,
    customer: Any,
    contract: dict[str, Any] | None = None,
) -> str:
    """Enable a borrower-initiated repayment path. Nothing is sent.

    Same shape as the date change and for the same reason: the platform holds
    the decision, the LMS holds the schedule. What lands here is a work item
    the servicing system picks up, and the borrower meets the result where they
    already are -- the app, the portal, the next statement.

    The idempotency key is the decision id, so a retried enactment opens one
    plan rather than two. That matters more here than on a message: two plans
    on one account is a borrower with two schedules and a dispute about which
    one they agreed to.
    """
    row = conn.execute(
        text(
            """
            SELECT a.outstanding,
                   (SELECT e.amount FROM emi_installments e
                     WHERE e.account_id = a.id ORDER BY e.due_date DESC LIMIT 1)
                     AS instalment
            FROM accounts a WHERE a.id = :aid
            """
        ),
        {"aid": decision.get("account_id")},
    ).mappings().first()
    if row is None:
        raise NoExecutor("no_account_to_plan_against")

    outstanding = float(row["outstanding"] or 0.0)
    instalment = float(row["instalment"] or 0.0)
    if outstanding <= 0 or instalment <= 0:
        raise NoExecutor("no_arrears_to_plan")

    # Instalments, rounded up, capped. The cap is not arithmetic: beyond six
    # this stops being a catch-up plan and becomes a restructure, which needs
    # the authority matrix rather than a self-service toggle.
    tenor = min(6, max(2, int(-(-outstanding // instalment))))

    outbound = _outbox_send(conn, customer, decision, contract, "O6")
    if not outbound.get("submitted"):
        return f"queued:reference:{outbound['id']}"
    return _enqueue_work(
        conn,
        workflow_type="self_service_plan",
        customer_id=customer["id"],
        payload={
            "decisionId": decision["id"],
            "accountId": decision.get("account_id"),
            "arrearsInr": round(outstanding, 2),
            "instalmentInr": round(instalment, 2),
            "proposedTenor": tenor,
            "rationale": (decision.get("rationale") or "")[:500],
            "contractVersion": contract.get("version") if contract else None,
            "actionContractId": contract.get("contract_id") if contract else None,
            "actionContractDigest": contract.get("digest") if contract else None,
        },
        idempotency_key=f"self-service-plan:{decision['id']}",
    )


#: Days after the salary credit to put the new due date. Two, not zero: a
#: credit posted on payday is not always cleared on payday, and an instalment
#: that debits the same morning is the mismatch again with a smaller gap.
EMI_DATE_BUFFER_DAYS = 2


def _outbox_send(
    conn: Any,
    customer: dict[str, Any],
    decision: dict[str, Any],
    contract: dict[str, Any] | None,
    code: str,
) -> dict[str, Any]:
    from bank_boundary import adapters

    envelope = contract or decision.get("_action_contract") or {}
    try:
        return adapters.send_with_outbox(
            conn,
            tenant_id=str(customer.get("tenant_id") or ""),
            contract_code=code,
            action_contract=envelope,
            idempotency_key=f"{code}:{decision['id']}",
        )
    except Exception as exc:
        logger.exception("outbox %s failed for %s", code, decision.get("id"))
        raise NoExecutor(f"outbox_failed:{code}") from exc


_HANDLERS = {
    A.WHATSAPP: _send_whatsapp,
    A.SMS: _send_sms,
    A.VOICE_BOT: _dial_bot,
    A.HUMAN_CALL: _queue_human,
    A.REPRESENT_MANDATE: _represent_mandate,
    A.EMI_DATE_CHANGE: _change_emi_date,
    A.SELF_SERVICE_PLAN: _open_self_service_plan,
}


def process_one(engine: Engine) -> bool:
    """Claim, commit intent, perform provider I/O outside the claim transaction."""
    if config.mode() != config.MODE_LIVE:
        return False
    from agent_core.treatment import kill_switch

    if not kill_switch.enact_allowed():
        return False

    prepared_rail = False
    prepare_failed_note: str | None = None
    with engine.begin() as conn:
        claimed = decisions.claim_due(conn, limit=1)
        if not claimed:
            reservations.reap_abandoned(conn)
            return False
        decision = claimed[0]
        spec = A.spec(str(decision.get("chosen_action") or A.WAIT))
        channel = spec.channel or "system"
        attempt_id = attempts.write_intent(
            conn,
            tenant_id=str(decision.get("tenant_id") or ""),
            decision_id=decision["id"],
            channel=channel,
            action=str(decision.get("chosen_action") or A.WAIT),
        )
        reservation_id = None
        if spec.channel:
            reservation_id = reservations.reserve(
                conn,
                tenant_id=str(decision.get("tenant_id") or ""),
                customer_id=decision["customer_id"],
                decision_id=decision["id"],
                channel=spec.channel,
            )
        attempts.set_state(conn, attempt_id, attempts.STATE_COMMITTED)
        decision["_attempt_id"] = attempt_id
        decision["_reservation_id"] = reservation_id
        if (
            str(decision.get("chosen_action") or "") == A.REPRESENT_MANDATE
            and config.mandate_executor() == config.MANDATE_EXECUTOR_RAIL
        ):
            acted, note = enact_one(conn, decision)
            prepared_rail = bool(
                acted and str(note or "").startswith("queued:prepared:")
            )
            if not prepared_rail:
                prepare_failed_note = str(note or "rail_prepare_failed")
                attempts.set_state(
                    conn,
                    attempt_id,
                    attempts.STATE_FAILED,
                    error=prepare_failed_note,
                )

    if prepare_failed_note is not None:
        logger.info(
            "treatment plan %s rail preparation failed note=%s",
            decision["id"],
            prepare_failed_note,
        )
        return True

    # Provider I/O on a fresh connection so a voice FK insert cannot wait
    # on the claim lock, and an ambiguous result can park rather than retry.
    with engine.begin() as conn:
        import usage_meter

        with usage_meter.attribute_to(
            decision.get("interaction_id"), decision_id=str(decision["id"])
        ):
            acted, note = enact_one(conn, decision)
        attempt_id = decision.get("_attempt_id")
        reservation_id = decision.get("_reservation_id")
        envelope = decision.get("_action_contract") or {}
        if attempt_id and envelope.get("contract_id"):
            from agent_core.treatment import schema_ready as _sr

            if _sr.has_column(conn, "enactment_attempts", "action_contract_id"):
                conn.execute(
                    text(
                        """
                        UPDATE enactment_attempts
                           SET action_contract_id = :cid,
                               action_contract_digest = :dig,
                               updated_at = now()
                         WHERE id = :id
                        """
                    ),
                    {
                        "cid": envelope.get("contract_id"),
                        "dig": envelope.get("digest"),
                        "id": attempt_id,
                    },
                )
        queued = str(note or "").startswith("queued:")
        if acted and queued:
            attempts.set_state(conn, attempt_id, attempts.STATE_QUEUED, provider_ref=note)
        elif acted:
            attempts.set_state(conn, attempt_id, attempts.STATE_SENT, provider_ref=note)
            reservations.commit(conn, reservation_id, provider_ref=note)
        elif note in {"not_live"}:
            reservations.release(conn, reservation_id)
        else:
            if prepared_rail:
                from bank_boundary import outbox

                conn.execute(
                    text(
                        """
                        UPDATE mandate_presentations
                           SET status = 'cancelled', updated_at = now()
                         WHERE id = :id AND status = 'scheduled'
                        """
                    ),
                    {"id": decision.get("_prepared_presentation_id")},
                )
                outbox.mark(
                    conn,
                    str(decision.get("_prepared_outbox_id") or ""),
                    outbox.REJECTED,
                )
            ambiguous = note in {"dial_failed", "timeout", "unknown"} or "ambiguous" in note
            if ambiguous:
                attempts.set_state(conn, attempt_id, attempts.STATE_PARKED, error=note)
            else:
                attempts.set_state(conn, attempt_id, attempts.STATE_FAILED, error=note)
                reservations.release(conn, reservation_id)
        logger.info(
            "treatment plan %s action=%s acted=%s note=%s",
            decision["id"],
            decision.get("chosen_action"),
            acted,
            note,
        )
        return True
