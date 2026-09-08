"""The published card steers every dial, not just the first one.

Three defects, one shape: the outbound card was read where it was convenient
and ignored where it was not.

* **The ladder forgot the card.** ``cadence.process_one`` hard-coded
  ``DEFAULT_BOT_ID``, so attempt 1 ran the agent an operator authored and
  attempts 2 and 3 ran the tenant default — a different prompt, a different
  tool grant and a different voice, to the same borrower about the same case.
* **``direction`` was not a kill switch.** The objective guard was nested
  inside ``card.outbound.dials``, so the one setting that says *never call
  anybody* was the one setting that skipped the check.
* **The caller ID was campaign-only.** Campaigns passed ``number_pool``; the
  treatment engine and the cadence did not. The same card rang from a TRAI
  1600 service number on a campaign and from the deployment's default number
  on a retry.

Findings OUTBOUND-02/03/04 and RUNTIME-13/14.
"""

from __future__ import annotations

import inspect
import uuid

import pytest
from sqlalchemy import text

import cadence
import campaigns
import outbound
from agent_core.cards.schema import AgentCard

TENANT = "hdfc.retail"


def _card(direction: str, *, number_pool: str | None = None) -> AgentCard:
    return AgentCard.model_validate(
        {
            "identity": {"bot_id": "dial-probe", "slug": "dial-probe", "display_name": "Probe"},
            "outbound": {"direction": direction, "number_pool": number_pool},
        }
    )


def _needs_bot_column(conn) -> None:
    """Migration 20260906_0112 is applied by the orchestrator, not by this
    package. Until it lands the ladder simply cannot remember the card, which
    is the pre-existing behaviour rather than a regression to assert against."""
    from agent_core.treatment.schema_ready import has_column

    if not has_column(conn, "call_cadence_state", "bot_id"):
        pytest.skip("call_cadence_state.bot_id not applied yet (20260906_0112)")


def _a_real_bot(conn) -> str:
    """``call_attempts.bot_id`` is a foreign key, so the probe has to be a bot
    that exists. The card is monkeypatched; only the id has to be real."""
    import db as dbmod

    return conn.execute(text("SELECT id FROM bots LIMIT 1")).scalar() or dbmod.DEFAULT_BOT_ID


def _customer(conn) -> str:
    cid = f"cust-dial-{uuid.uuid4().hex[:8]}"
    conn.execute(
        text(
            "INSERT INTO customers (id, tenant_id, name, risk, phone_primary) "
            "VALUES (:id, :tenant, 'Dial Test', 'low', '+919000000001')"
        ),
        {"id": cid, "tenant": TENANT},
    )
    return cid


# ---------------------------------------------------------------------------
# The ladder carries the card
# ---------------------------------------------------------------------------


def test_the_retry_resolves_the_bot_instead_of_hard_coding_the_default() -> None:
    """``DEFAULT_BOT_ID`` at this call site is the whole of OUTBOUND-02."""
    src = inspect.getsource(cadence.process_one)
    assert "resolve_outbound_bot_id" in src
    # The prose above the call names the old constant; the code must not.
    assert "dbmod.DEFAULT_BOT_ID" not in src
    assert "db.DEFAULT_BOT_ID" not in src


def test_ensure_case_records_the_bot_that_opened_the_ladder(db_tx) -> None:
    _needs_bot_column(db_tx)
    cid = _customer(db_tx)
    case = cadence.ensure_case(
        db_tx,
        tenant_id=TENANT,
        customer_id=cid,
        objective="ptp_capture",
        case_ref="TD-steers-1",
        bot_id="authored-card",
    )
    assert case["bot_id"] == "authored-card"


def test_a_later_outcome_never_clears_the_bot(db_tx) -> None:
    """``ensure_case`` is idempotent and is called again on every outcome. A
    caller that does not know the bot must not erase the one that did."""
    _needs_bot_column(db_tx)
    cid = _customer(db_tx)
    kwargs = dict(
        tenant_id=TENANT,
        customer_id=cid,
        objective="ptp_capture",
        case_ref="TD-steers-2",
    )
    cadence.ensure_case(db_tx, bot_id="authored-card", **kwargs)
    again = cadence.ensure_case(db_tx, bot_id=None, **kwargs)
    assert again["bot_id"] == "authored-card"


def test_claim_due_falls_back_to_the_previous_rungs_bot(db_tx) -> None:
    """Ladders opened before the column existed still ran a real agent. The
    attempt that agent placed is the same answer the column would hold."""
    _needs_bot_column(db_tx)
    cid = _customer(db_tx)
    bot = _a_real_bot(db_tx)
    attempt = outbound.reserve(
        db_tx,
        customer_id=cid,
        to_phone="+919000000001",
        objective="ptp_capture",
        bot_id=bot,
        tenant_id=TENANT,
    )
    assert attempt is not None
    case = cadence.ensure_case(
        db_tx,
        tenant_id=TENANT,
        customer_id=cid,
        objective="ptp_capture",
        case_ref="TD-steers-3",
    )
    db_tx.execute(
        text(
            "UPDATE call_cadence_state SET bot_id = NULL, last_attempt_id = :a, "
            "next_attempt_at = now() - interval '1 minute' WHERE id = :id"
        ),
        {"id": case["id"], "a": attempt["id"]},
    )
    due = cadence.claim_due(db_tx)
    assert due is not None and due["id"] == case["id"]
    assert due["bot_id"] is None
    assert due["last_attempt_bot_id"] == bot


# ---------------------------------------------------------------------------
# direction is a kill switch
# ---------------------------------------------------------------------------


def test_an_inbound_only_card_is_refused_before_the_dial(monkeypatch) -> None:
    """The refusal is wider than the mission check and runs first: an
    inbound-only card must not reach ``outbound.reserve`` at all."""
    import mission as mission_mod
    from agent_core.treatment import enact

    monkeypatch.setattr(mission_mod, "resolve_outbound_bot_id", lambda **_: "dial-probe")
    monkeypatch.setattr(mission_mod, "card_for_bot", lambda *_a, **_k: _card("inbound"))

    def _explode(*_a, **_k):  # pragma: no cover - the point is that it is not called
        raise AssertionError("reserve was reached for a card that forbids dialling")

    monkeypatch.setattr(outbound, "reserve", _explode)

    with pytest.raises(enact.NoExecutor) as excinfo:
        enact._dial_bot(
            None,
            decision={"id": "TD-x", "objective": "ptp_capture"},
            customer={"id": "cust-x", "phone_primary": "+919000000001"},
        )
    assert "card_forbids_outbound" in str(excinfo.value)


def test_the_mission_guard_is_no_longer_nested_inside_dials() -> None:
    """RUNTIME-13's mechanism: ``and card.outbound.dials and`` on the objective
    check made the forbidding case the unguarded one."""
    from agent_core.treatment import enact

    src = inspect.getsource(enact._dial_bot)
    assert "if card is not None and not card.outbound.dials" in src
    assert "card.outbound.dials and card.outbound.objectives" not in src


def test_a_campaign_marks_the_target_instead_of_dialling_it() -> None:
    src = inspect.getsource(campaigns)
    assert 'note="card_forbids_outbound"' in src


def test_the_ladder_stops_when_the_card_stops_dialling() -> None:
    src = inspect.getsource(cadence.process_one)
    assert "card_forbids_outbound" in src


# ---------------------------------------------------------------------------
# The caller ID follows the card
# ---------------------------------------------------------------------------


def test_reserve_derives_the_caller_id_pool_from_the_bot(db_tx, monkeypatch) -> None:
    import mission as mission_mod

    monkeypatch.setattr(
        mission_mod, "card_for_bot", lambda *_a, **_k: _card("outbound", number_pool="service-1600")
    )
    cid = _customer(db_tx)
    attempt = outbound.reserve(
        db_tx,
        customer_id=cid,
        to_phone="+919000000001",
        objective="ptp_capture",
        bot_id=_a_real_bot(db_tx),
        tenant_id=TENANT,
    )
    assert attempt is not None
    assert attempt["numberPool"] == "service-1600"


def test_an_explicit_pool_still_wins(db_tx, monkeypatch) -> None:
    import mission as mission_mod

    monkeypatch.setattr(
        mission_mod, "card_for_bot", lambda *_a, **_k: _card("outbound", number_pool="from-card")
    )
    cid = _customer(db_tx)
    attempt = outbound.reserve(
        db_tx,
        customer_id=cid,
        to_phone="+919000000001",
        objective="ptp_capture",
        bot_id=_a_real_bot(db_tx),
        tenant_id=TENANT,
        number_pool="from-caller",
    )
    assert attempt is not None and attempt["numberPool"] == "from-caller"


def test_an_unreadable_card_falls_back_to_the_deployment_number(db_tx, monkeypatch) -> None:
    """A caller ID we could not resolve is not a reason to refuse a dial."""
    import mission as mission_mod

    def _boom(*_a, **_k):
        raise RuntimeError("card store down")

    monkeypatch.setattr(mission_mod, "card_for_bot", _boom)
    cid = _customer(db_tx)
    attempt = outbound.reserve(
        db_tx,
        customer_id=cid,
        to_phone="+919000000001",
        objective="ptp_capture",
        bot_id=_a_real_bot(db_tx),
        tenant_id=TENANT,
    )
    assert attempt is not None and attempt["numberPool"] is None


def test_no_dial_path_passes_its_own_pool() -> None:
    """One owner. ``reserve`` derives it, so a new dial site cannot opt out by
    forgetting a keyword argument."""
    assert "number_pool=" not in inspect.getsource(campaigns)
