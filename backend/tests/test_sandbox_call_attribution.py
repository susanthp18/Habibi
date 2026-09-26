"""A Sandbox Live rehearsal is filed as one, not as an anonymous caller."""

from db_core import unknown_caller_id
from db_interactions import _caller_label
from voice.persist import _voice_source_payload


def test_rehearsal_payload_names_the_operator_and_the_run():
    payload = _voice_source_payload(
        transport="websocket",
        bot_id="kaia-v2-4",
        accountable_user_id="priya-nair",
        sandbox={"runId": "SBX-1", "scenarioId": "late-emi", "personaName": None},
    )
    assert payload["environment"] == "sandbox"
    assert payload["accountableUserId"] == "priya-nair"
    assert payload["runId"] == "SBX-1" and payload["scenarioId"] == "late-emi"
    assert "personaName" not in payload


def test_a_live_call_payload_is_unchanged():
    payload = _voice_source_payload(transport="twilio", bot_id="kaia-v2-4", accountable_user_id=None)
    assert "environment" not in payload


def test_unverified_rehearsal_is_labelled_not_unknown():
    row = {"customer_id": unknown_caller_id(), "customer_name": "Unknown caller"}
    assert _caller_label({**row, "environment": "sandbox", "persona_name": "Rahul"}) == "Sandbox rehearsal · Rahul"
    assert _caller_label({**row, "environment": "sandbox", "persona_name": None}) == "Sandbox rehearsal"
    assert _caller_label({**row, "environment": None, "persona_name": None}) == "Unknown caller"
    # A rehearsal bound to a real customer keeps that customer's name.
    assert _caller_label({"customer_id": "cust-1", "customer_name": "Asha", "environment": "sandbox"}) == "Asha"
