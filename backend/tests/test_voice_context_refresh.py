"""In-call CRM context refresh after a write (voice/tools.py).

The bug: ``CallContext`` was loaded exactly once, at verify_identity, and
``refresh_from_crm()`` was never called anywhere in the voice path. After
booking a PTP the bot's own context still said the account had no open
promises, so "what did I just agree to" could not be answered from context.

Only tools that change something the CRM card actually renders schedule a
refresh — see the table in the plan. request_callback deliberately does not:
CallContext.open_work omits callbacks, so a refresh would re-read the CRM and
change nothing.
"""

from __future__ import annotations


# Tools whose writes appear in CallContext.open_work / customer_card.
CARD_AFFECTING = {
    "create_promise_to_pay",
    "revise_promise_to_pay",
    "flag_dispute",
    "request_documents",
    "evaluate_authority",
    "apply_goodwill",
}
# Written by voice, but invisible to the card.
NOT_CARD_AFFECTING = {"request_callback", "capture_lead", "add_customer_note"}


def test_card_affecting_and_other_tools_are_disjoint() -> None:
    assert CARD_AFFECTING.isdisjoint(NOT_CARD_AFFECTING)


