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

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from agent_core.treatment import actions as A, config, decisions

logger = logging.getLogger(__name__)

#: Actions whose executor is a later roadmap item.
DEFERRED: frozenset[str] = frozenset({A.FIELD_VISIT, A.LEGAL_NOTICE})

#: A plan this stale is about a situation that has moved on. Re-deciding is
#: cheaper and safer than dialling on yesterday's reasoning.
MAX_PLAN_AGE = timedelta(hours=12)


class NoExecutor(RuntimeError):
    """The action is understood and deliberately not carried out yet."""


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
            decisions.record_outcome(decision_id, "cancelled", conn=conn)
            return False, "plan_expired"

    if action in DEFERRED:
        decisions.record_outcome(decision_id, "cancelled", conn=conn)
        logger.info(
            "treatment %s recommended %s — no executor yet (roadmap P8/P9)",
            decision_id,
            action,
        )
        return False, f"no_executor:{action}"

    handler = _HANDLERS.get(action)
    if handler is None:
        decisions.record_outcome(decision_id, "cancelled", conn=conn)
        return False, f"unknown_action:{action}"

    customer = _customer(conn, decision["customer_id"])
    if customer is None:
        decisions.record_outcome(decision_id, "cancelled", conn=conn)
        return False, "customer_gone"

    # Still worth doing? A borrower who paid between planning and sending must
    # not be dunned for it.
    if _resolved_since(conn, decision):
        decisions.record_outcome(decision_id, "superseded", conn=conn)
        return False, "already_resolved"

    import contact_policy

    spec = A.spec(action)
    admitted = None
    if spec.channel:
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
        )
        if not admitted.allowed:
            # A voice plan the gate refused is still evidence. Recording it as a
            # suppressed attempt is what makes the denial rate a query over one
            # table rather than a join between a log file and an intention —
            # and it is the row that answers "why did nobody call this borrower
            # on Tuesday" with a reason instead of a shrug.
            if action == A.VOICE_BOT:
                _record_suppressed_dial(decision, customer, admitted.reason)
            decisions.record_outcome(decision_id, "cancelled", conn=conn)
            return False, f"contact:{admitted.reason}"

    try:
        ref = handler(conn, decision=decision, customer=customer)
    except NoExecutor as exc:
        decisions.record_outcome(decision_id, "cancelled", conn=conn)
        return False, str(exc)
    except Exception:
        logger.exception("treatment enactment failed for %s", decision_id)
        # Left un-enacted with an outcome so the executor does not spin on it.
        decisions.record_outcome(decision_id, "cancelled", conn=conn)
        return False, "enactment_failed"

    decisions.mark_enacted(decision_id, ref=ref, conn=conn, enacted_by=enacted_by)
    return True, ref or action


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


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
    return False


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


def _send_whatsapp(conn: Any, *, decision: dict[str, Any], customer: dict[str, Any]) -> str:
    import promise_fulfillment as pf

    phone = customer.get("phone_primary") or customer.get("phone_alt")
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
    )
    return f"whatsapp:{conversation_id}"


def _conversation(conn: Any, customer_id: str) -> str:
    import db as dbmod

    return dbmod._open_whatsapp_conversation(conn, customer_id)


def _send_sms(conn: Any, *, decision: dict[str, Any], customer: dict[str, Any]) -> str:
    import twilio_sms

    phone = customer.get("phone_primary") or customer.get("phone_alt")
    if not phone:
        raise NoExecutor("no_phone_on_file")
    body = _copy(conn, decision, tenant_id=customer.get("tenant_id"))
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


def _dial_bot(conn: Any, *, decision: dict[str, Any], customer: dict[str, Any]) -> str:
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

    phone = customer.get("phone_primary") or customer.get("phone_alt")
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
        if card is not None and card.outbound.dials and card.outbound.objectives:
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
        attempt = outbound.reserve(
            own,
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
    if attempt is None:
        raise NoExecutor("customer_gone")

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


def _record_suppressed_dial(
    decision: dict[str, Any], customer: dict[str, Any], reason: str | None
) -> None:
    """Log a refused voice plan as a suppressed attempt. Never raises.

    On its own transaction, and swallowing failures, because this is
    bookkeeping: an attempt ledger that can abort an enactment would be a
    measurement that changes what it measures.
    """
    import db as dbmod
    import outbound

    phone = customer.get("phone_primary") or customer.get("phone_alt")
    if not phone:
        return
    try:
        with dbmod.engine.begin() as own:
            attempt = outbound.reserve(
                own,
                customer_id=customer["id"],
                to_phone=phone,
                objective=_objective_for(decision),
                account_id=decision.get("account_id"),
                decision_id=decision["id"],
                policy_version=decision.get("policy_version"),
                tenant_id=customer.get("tenant_id"),
                context={"trigger": decision.get("trigger_kind")},
            )
            if attempt:
                outbound.suppress(own, attempt["id"], reason or "contact_policy")
    except Exception:
        logger.exception("could not log suppressed dial for %s", decision.get("id"))


def _queue_human(conn: Any, *, decision: dict[str, Any], customer: dict[str, Any]) -> str:
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
    conn: Any, *, decision: dict[str, Any], customer: dict[str, Any]
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

    if executor == config.MANDATE_EXECUTOR_RAIL:
        ref = _submit_to_rail(
            presentation_id=presentation_id,
            mandate_id=str(state["id"]),
            rail=str(state["rail"]),
            amount=amount,
            cycle=state["cycle"],
        )
        status, presented_at = "submitted", datetime.now(timezone.utc)
    else:
        ref = _hand_to_lms(
            conn,
            decision=decision,
            customer=customer,
            presentation_id=presentation_id,
            amount=amount,
            cycle=state["cycle"],
        )
        status, presented_at = "scheduled", None

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
            "presented_at": presented_at,
            "status": status,
            "executor": executor,
            "decision_id": decision["id"],
        },
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
    import os

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
    import db as dbmod

    job_id = dbmod._id("WRJ")
    conn.execute(
        text(
            """
            INSERT INTO work_runtime_jobs (
              id, tenant_id, workflow_type, status, customer_id,
              payload, idempotency_key
            ) VALUES (
              :id, :tenant_id, 'mandate_representment', 'submitted', :customer_id,
              CAST(:payload AS jsonb), :idem
            )
            ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
            """
        ),
        {
            "id": job_id,
            "tenant_id": customer["tenant_id"],
            "customer_id": customer["id"],
            "payload": json.dumps(
                {
                    "presentationId": presentation_id,
                    "decisionId": decision["id"],
                    "accountId": decision.get("account_id"),
                    "amount": round(amount, 2),
                    "presentedFor": str(cycle),
                    "rationale": (decision.get("rationale") or "")[:500],
                }
            ),
            "idem": f"mandate-representment:{presentation_id}",
        },
    )
    return f"work:{job_id}"


def _change_emi_date(
    conn: Any, *, decision: dict[str, Any], customer: dict[str, Any]
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
    import db as dbmod

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

    credit_day = _aware(row["next_credit_at"]).day
    proposed = min(28, credit_day + EMI_DATE_BUFFER_DAYS)

    job_id = dbmod._id("WRJ")
    conn.execute(
        text(
            """
            INSERT INTO work_runtime_jobs (
              id, tenant_id, workflow_type, status, customer_id,
              payload, idempotency_key
            ) VALUES (
              :id, :tenant_id, 'emi_date_change', 'submitted', :customer_id,
              CAST(:payload AS jsonb), :idem
            )
            ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
            """
        ),
        {
            "id": job_id,
            "tenant_id": customer["tenant_id"],
            "customer_id": customer["id"],
            "payload": json.dumps(
                {
                    "decisionId": decision["id"],
                    "accountId": decision.get("account_id"),
                    "proposedDueDay": proposed,
                    "salaryCreditDay": credit_day,
                    "rationale": (decision.get("rationale") or "")[:500],
                }
            ),
            "idem": f"emi-date-change:{decision['id']}",
        },
    )
    return f"work:{job_id}"


def _open_self_service_plan(
    conn: Any, *, decision: Any, customer: Any, **_: Any
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
    import db as dbmod

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

    job_id = dbmod._id("WRJ")
    conn.execute(
        text(
            """
            INSERT INTO work_runtime_jobs (
              id, tenant_id, workflow_type, status, customer_id,
              payload, idempotency_key
            ) VALUES (
              :id, :tenant_id, 'self_service_plan', 'submitted', :customer_id,
              CAST(:payload AS jsonb), :idem
            )
            ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
            """
        ),
        {
            "id": job_id,
            "tenant_id": customer["tenant_id"],
            "customer_id": customer["id"],
            "payload": json.dumps(
                {
                    "decisionId": decision["id"],
                    "accountId": decision.get("account_id"),
                    "arrearsInr": round(outstanding, 2),
                    "instalmentInr": round(instalment, 2),
                    "proposedTenor": tenor,
                    "rationale": (decision.get("rationale") or "")[:500],
                }
            ),
            "idem": f"self-service-plan:{decision['id']}",
        },
    )
    return f"work:{job_id}"


#: Days after the salary credit to put the new due date. Two, not zero: a
#: credit posted on payday is not always cleared on payday, and an instalment
#: that debits the same morning is the mismatch again with a smaller gap.
EMI_DATE_BUFFER_DAYS = 2


def _aware(value: Any) -> datetime:
    if not isinstance(value, datetime):
        return datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


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
    """Drain one due plan. Returns True if a row was claimed at all."""
    if config.mode() != config.MODE_LIVE:
        return False
    with engine.begin() as conn:
        claimed = decisions.claim_due(conn, limit=1)
        if not claimed:
            return False
        acted, note = enact_one(conn, claimed[0])
        logger.info(
            "treatment plan %s action=%s acted=%s note=%s",
            claimed[0]["id"],
            claimed[0].get("chosen_action"),
            acted,
            note,
        )
        return True
