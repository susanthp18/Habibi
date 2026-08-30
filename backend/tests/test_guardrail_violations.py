"""Guardrail breach -> compliance violation.

Two halves. The mapping is pure and is where the risk lives: a flag filed
against the wrong rule misleads a reviewer and corrupts per-rule breach rates,
so the tests below pin *both* what maps and what deliberately does not. The
round-trip covers the SQL — the INSERT ... SELECT has to satisfy the table's
actor CHECK constraint and the per-(interaction, rule) idempotency guard.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from voice import persist


# --------------------------------------------------------------------------
# Mapping
# --------------------------------------------------------------------------


def test_missing_recording_disclosure_maps_to_the_recording_rule() -> None:
    assert persist.rule_for_flag("missing-recording-disclosure") == "r-rec"


def test_blocked_waiver_maps_to_the_guarantee_rule() -> None:
    """The bot promised an outcome it has no authority to promise."""
    assert persist.rule_for_flag("waiver-blocked") == "r-guarantee"


def test_quoting_above_the_authority_cap_maps_to_the_guarantee_rule() -> None:
    assert persist.rule_for_flag("authority-cap-exceeded") == "r-guarantee"


def test_hours_breach_maps_to_the_dnd_window_rule() -> None:
    assert persist.rule_for_flag("hours-breach") == "r-dnd-win"


def test_identity_before_verify_maps_to_the_verify_rule() -> None:
    assert persist.rule_for_flag("identity-before-verify") == "r-verify"


def test_missing_mini_miranda_maps_to_the_disclosure_rule() -> None:
    assert persist.rule_for_flag("missing-mini-miranda") == "r-mm"


def test_third_party_leak_maps_to_the_disclosure_rule() -> None:
    assert persist.rule_for_flag("third-party-leak") == "r-third"


def test_opt_out_ignored_maps_to_the_dnd_disclosure_rule() -> None:
    assert persist.rule_for_flag("opt-out-ignored") == "r-dnd-disc"


def test_rate_quoted_maps_to_the_false_claim_rule() -> None:
    assert persist.rule_for_flag("rate-quoted") == "r-false"


def test_a_prohibited_legal_threat_maps_to_the_threat_rule() -> None:
    assert persist.rule_for_flag("prohibited:court") == "r-threat"


def test_a_prohibited_abusive_term_maps_to_the_abuse_rule() -> None:
    from agent_core import lexicon

    term = "stupid" if lexicon.is_abusive("stupid") else "idiot"
    if not lexicon.is_abusive(term):
        pytest.skip("lexicon carries no plain abusive term to assert against")
    assert persist.rule_for_flag(f"prohibited:{term}") == "r-abuse"


def test_an_unclassifiable_prohibited_term_files_nothing() -> None:
    """PROH-LANG-03/04 cannot be inferred from a bare word, so we decline to
    guess rather than file against a rule the reviewer will have to overturn."""
    assert persist.rule_for_flag("prohibited:refinance") is None


def test_an_empty_prohibited_term_files_nothing() -> None:
    assert persist.rule_for_flag("prohibited:") is None


@pytest.mark.parametrize(
    "flag", ["auto-escalate", "max-turns", "max-seconds", "politics-religion"]
)
def test_caller_conduct_and_session_limits_are_not_bot_violations(flag: str) -> None:
    """These describe the caller or the session, not bot misconduct. Filing
    them against the bot would blame it for the caller swearing."""
    assert persist.rule_for_flag(flag) is None


def test_an_unknown_flag_files_nothing() -> None:
    assert persist.rule_for_flag("some-future-flag") is None


# --------------------------------------------------------------------------
# Round-trip
# --------------------------------------------------------------------------


def _bot_handled_interaction(conn) -> str:
    row = conn.execute(
        text(
            "SELECT id FROM interactions"
            " WHERE handler_bot_id IS NOT NULL AND customer_id IS NOT NULL"
            " LIMIT 1"
        )
    ).first()
    if row is None:
        pytest.skip("no bot-handled interaction seeded")
    return row[0]


def _violations_for(conn, interaction_id: str, rule_id: str) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT id, actor_kind, actor_bot_id, actor_user_id, status,"
            "       description, at_sec, customer_id"
            "  FROM violations"
            " WHERE interaction_id = :ix AND rule_id = :rule"
        ),
        {"ix": interaction_id, "rule": rule_id},
    ).mappings()
    return [dict(r) for r in rows]


def test_a_breach_files_an_open_violation_against_the_bot(db_tx) -> None:
    conn = db_tx
    ix = _bot_handled_interaction(conn)
    conn.execute(
        text("DELETE FROM violations WHERE interaction_id = :ix AND rule_id = 'r-rec'"),
        {"ix": ix},
    )

    persist.append_violation(
        interaction_id=ix,
        rule_id="r-rec",
        description="Auto-detected on turn 1: missing-recording-disclosure",
        at_sec=12,
    )

    found = _violations_for(conn, ix, "r-rec")
    assert len(found) == 1
    v = found[0]
    # The table's CHECK requires exactly one actor ref for the declared kind.
    assert v["actor_kind"] == "bot"
    assert v["actor_bot_id"] is not None
    assert v["actor_user_id"] is None
    assert v["status"] == "open"
    assert v["at_sec"] == 12
    assert v["customer_id"]


def test_repeating_the_same_breach_does_not_file_a_second_row(db_tx) -> None:
    """Six turns of the same banned word is one rule broken once; six rows
    would bury every other breach on the call."""
    conn = db_tx
    ix = _bot_handled_interaction(conn)
    conn.execute(
        text("DELETE FROM violations WHERE interaction_id = :ix AND rule_id = 'r-rec'"),
        {"ix": ix},
    )

    for turn in range(6):
        persist.append_violation(
            interaction_id=ix, rule_id="r-rec", description=f"turn {turn}", at_sec=turn
        )

    found = _violations_for(conn, ix, "r-rec")
    assert len(found) == 1
    assert found[0]["description"] == "turn 0", "the first breach is the one on record"


def test_distinct_rules_on_one_call_each_file_their_own_row(db_tx) -> None:
    conn = db_tx
    ix = _bot_handled_interaction(conn)
    conn.execute(
        text(
            "DELETE FROM violations WHERE interaction_id = :ix"
            " AND rule_id IN ('r-rec','r-guarantee')"
        ),
        {"ix": ix},
    )

    persist.append_violation(interaction_id=ix, rule_id="r-rec", description="a")
    persist.append_violation(interaction_id=ix, rule_id="r-guarantee", description="b")

    assert len(_violations_for(conn, ix, "r-rec")) == 1
    assert len(_violations_for(conn, ix, "r-guarantee")) == 1


def test_an_unknown_interaction_files_nothing_and_does_not_raise(db_tx) -> None:
    """The INSERT ... SELECT finds no row rather than violating a FK."""
    persist.append_violation(
        interaction_id="IX-DOES-NOT-EXIST", rule_id="r-rec", description="x"
    )
    found = _violations_for(db_tx, "IX-DOES-NOT-EXIST", "r-rec")
    assert found == []


# --------------------------------------------------------------------------
# waiver-blocked: promising a waiver vs. refusing one
#
# SBX-E8A282E083 (scenario angry-waiver, card kaia-v2-4 v1_4) halted a live run
# on a *compliant refusal*: the detector was a bare mention match on
# waive/waiver/waived, so declining the waiver in words that contain the word
# scored identically to granting it. The customer was dropped mid-flow with no
# resolution path. These pin the distinction in both directions -- a mention is
# not a promise, and a promise still halts.
# --------------------------------------------------------------------------

_WAIVER_GUARDRAILS = {"neverPromiseWaiver": True}


def _waiver_flags(bot_text: str, *, intent: str = "waiver_request") -> list[str]:
    from agent_core.guardrails import evaluate_guardrails

    return evaluate_guardrails(
        customer_text="Yes speaking. I paid on the 5th - waive this late fee now.",
        bot_text=bot_text,
        intent=intent,
        guardrails=_WAIVER_GUARDRAILS,
        turn_index=1,
        elapsed_seconds=12,
        customer_bot_exchanges=1,
    )


#: Verbatim bot turn from run SBX-E8A282E083 -- the behaviour we want.
_LIVE_REFUSAL = (
    "Thank you. I understand you've paid on the 5th and you're requesting a "
    "late fee waiver. Late fee waivers can't be approved on this chat without "
    "a supervisor review, but I can log your request for escalation and a "
    "specialist to check whether any waiver is possible."
)


def test_the_live_compliant_refusal_is_not_a_blocked_waiver() -> None:
    assert "waiver-blocked" not in _waiver_flags(_LIVE_REFUSAL)


@pytest.mark.parametrize(
    "bot_text",
    [
        "Waivers require supervisor approval.",
        "We cannot waive the late fee on this channel.",
        "I'm unable to waive that, but I can raise it internally.",
        "I won't be able to waive the fee myself.",
        "A waiver isn't something I can approve here.",
        "That can't be waived without approval from a supervisor.",
    ],
)
def test_refusal_phrasings_do_not_flag(bot_text: str) -> None:
    """Saying the word while declining is the correct answer, not a breach."""
    assert "waiver-blocked" not in _waiver_flags(bot_text)


@pytest.mark.parametrize(
    "bot_text",
    [
        "I will waive the late fee for you.",
        "Sure, I can waive it.",
        "Consider it waived.",
        "We'll waive the late fee of 500 rupees today.",
        "Let me waive that charge right now.",
        "Done, I've waived the late fee.",
        "Your late fee has been waived.",
    ],
)
def test_real_promises_still_flag_and_halt(bot_text: str) -> None:
    from agent_core.guardrails import should_halt

    flags = _waiver_flags(bot_text)
    assert "waiver-blocked" in flags
    assert should_halt(flags) is True


def test_the_goodwill_escape_hatch_still_applies() -> None:
    """Pre-existing behaviour, kept: 'goodwill' framing is not the breach."""
    assert "waiver-blocked" not in _waiver_flags(
        "As a goodwill adjustment I can have it reviewed and waived by my supervisor."
    )


@pytest.mark.parametrize("intent", ["payment_promise", "dispute", "general"])
def test_other_intents_are_untouched_even_when_a_waiver_is_promised(
    intent: str,
) -> None:
    """The gate is intent-scoped; widening it here would be a separate rule."""
    assert "waiver-blocked" not in _waiver_flags(
        "I will waive the late fee for you.", intent=intent
    )


def test_the_gate_is_off_when_the_card_does_not_forbid_waiver_promises() -> None:
    from agent_core.guardrails import evaluate_guardrails

    flags = evaluate_guardrails(
        customer_text="waive this fee",
        bot_text="I will waive the late fee for you.",
        intent="waiver_request",
        guardrails={},
        turn_index=1,
        elapsed_seconds=12,
        customer_bot_exchanges=1,
    )
    assert "waiver-blocked" not in flags


def test_a_promise_is_not_excused_by_a_refusal_in_a_later_sentence() -> None:
    """Refusal cues suppress only within the clause carrying the commitment."""
    assert "waiver-blocked" in _waiver_flags(
        "I'll waive the late fee. I can't do anything about the interest."
    )
