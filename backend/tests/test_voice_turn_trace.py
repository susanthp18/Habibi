"""The turn.e2e measurement spine (Phase 0 of the latency plan).

Five independent reviews each asked for the same missing number: one line per
turn, in the caller's clock, carrying which end-of-turn signal bound and what
each stage cost. Most of the values already existed and were discarded; these
tests pin that they now reach the trace, and that the clock is the right one.
"""

from __future__ import annotations


def test_tool_trace_names_cannot_include_arguments_or_borrower_text():
    from voice.call_trace import safe_tool_name

    assert safe_tool_name("create_promise_to_pay") == "create_promise_to_pay"
    assert safe_tool_name("create_promise_to_pay(amount=500)") is None
    assert safe_tool_name("borrower said yes") is None
    assert safe_tool_name("x" * 65) is None
