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
