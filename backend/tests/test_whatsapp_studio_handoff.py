"""A WhatsApp thread goes to the Inbox only on a transfer the engine carried out."""

import whatsapp_studio


def _turn(*events):
    return {"events": [{"type": t, "payload": {"function_name": "transfer_to_human", **p}} for t, p in events]}


def test_refused_transfer_is_not_a_handoff():
    turns = [_turn(("tool_call_started", {}),
                   ("tool_call_result", {"result": {"status": "error", "error": "customer_did_not_ask"}}))]
    assert whatsapp_studio._asked_for_person(turns) is False


def test_transfer_attempt_is_a_handoff():
    turns = [_turn(("tool_call_started", {}),
                   ("tool_call_result", {"result": {"status": "transfer_failed", "reason": "textchat_not_supported"}}))]
    assert whatsapp_studio._asked_for_person(turns) is True
