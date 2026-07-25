"""CallContext + KB corpus routing.

The corpus rules matter more than they look: sending ``["collections"]`` on the
upsell node makes every product question retrieve nothing, and sending ``None``
on a collections node lets insurance policy text answer a money question.
"""

from __future__ import annotations

from agent_core.context import (
    CallContext,
    account_tail,
    product_keys_for_intent,
    product_keys_for_node,
)


# --------------------------------------------------------------------------
# Corpus routing
# --------------------------------------------------------------------------


def test_collections_nodes_hard_filter_to_collections():
    for node in ("greet_disclose", "verify_identity", "state_position", "negotiate_ptp", None):
        assert product_keys_for_node(node) == ["collections"]


def test_upsell_node_uses_soft_product_steering():
    """None means 'no hard filter' — kb_retrieve then steers by query tokens.

    A hard-coded product key list would silently exclude every corpus added
    after it was written.
    """
    assert product_keys_for_node("gated_upsell") is None


def test_product_intents_use_soft_steering():
    assert product_keys_for_intent("product_faq") is None
    assert product_keys_for_intent("upsell_opportunity") is None
    assert product_keys_for_intent("balance_query") == ["collections"]
    assert product_keys_for_intent(None) == ["collections"]


# --------------------------------------------------------------------------
# account_tail — the "AC-SUSANTH" bug
# --------------------------------------------------------------------------


def test_account_tail_returns_digits_only():
    assert account_tail("AC-77410") == "7410"
    assert account_tail("AC-1234") == "1234"


def test_account_tail_refuses_letters():
    """Vanity ids have no trailing digits; the bot must omit the phrase entirely
    rather than read 'ANTH' aloud."""
    assert account_tail("AC-SUSANTH") is None
    assert account_tail("AC-12") is None
    assert account_tail(None) is None
    assert account_tail("") is None


# --------------------------------------------------------------------------
# Developer-message injection
# --------------------------------------------------------------------------


def _ctx(**kw) -> CallContext:
    ctx = CallContext(channel="sandbox_live", **kw)
    ctx.customer_card = {
        "name": "Ravi Kumar",
        "accountTail": "7410",
        "outstanding": 48200,
        "minimumDue": 4820,
        "dpd": 34,
        "product": "Personal Loan",
        "dnd": False,
    }
    return ctx


def test_crm_card_states_facts_as_authoritative():
    card = _ctx().crm_card()
    assert "Ravi Kumar" in card
    assert "7410" in card
    assert "48,200" in card  # formatted INR, not a raw float
    assert "34" in card
    assert "authoritative" in card.lower()


def test_crm_card_message_is_a_developer_message():
    msg = _ctx().crm_card_message()
    assert msg["role"] == "developer"
    assert msg["content"]


def test_crm_card_omits_missing_fields():
    """A partial CRM read must not emit 'Outstanding: None'."""
    ctx = CallContext(channel="voice")
    ctx.customer_card = {"name": "Asha"}
    card = ctx.crm_card()
    assert "Asha" in card
    assert "None" not in card
    assert "Outstanding" not in card


def test_dnd_is_surfaced_when_set():
    ctx = _ctx()
    ctx.customer_card["dnd"] = True
    assert "DND" in ctx.crm_card()


def test_open_work_is_summarised_into_the_card():
    ctx = _ctx()
    ctx.open_work = {"promises": [{"id": "PR-9", "promisedDate": "2026-08-01"}]}
    card = ctx.crm_card()
    assert "Open promises" in card
    assert "PR-9" in card


def test_persona_message_only_when_persona_present():
    assert CallContext(channel="sandbox_live").persona_message() is None
    assert CallContext(channel="sandbox_live", persona={}).persona_message() is None


def test_persona_message_describes_the_simulated_caller():
    msg = CallContext(
        channel="sandbox_live",
        persona={"name": "Ravi", "language": "Hindi", "mood": "frustrated"},
    ).persona_message()
    assert msg is not None
    assert msg["role"] == "developer"
    content = msg["content"]
    assert "Ravi" in content and "Hindi" in content and "frustrated" in content
    # The tester must not be able to convince the bot the CRM writes are fake.
    assert "CRM writes are real" in content


def test_delta_message_is_short_and_tagged():
    msg = CallContext(channel="voice").delta_message("promise PR-1 created")
    assert msg["role"] == "developer"
    assert msg["content"].startswith("CRM UPDATE:")
