"""Prompt lint disclosure regex — avoid false positives on unrelated 'record' words."""

from __future__ import annotations

from prompt_lint import lint_prompt


def test_recording_disclosure_required_when_missing() -> None:
    findings = lint_prompt(
        "You are a collections agent. Help the customer pay.",
        {"alwaysDiscloseRecording": True},
    )
    codes = {f["code"] for f in findings}
    assert "missing_recording_disclosure" in codes


def test_recording_disclosure_accepts_call_is_recorded() -> None:
    findings = lint_prompt(
        "This call is being recorded for quality. Help with EMI.",
        {"alwaysDiscloseRecording": True},
    )
    codes = {f["code"] for f in findings}
    assert "missing_recording_disclosure" not in codes


def test_recording_disclosure_ignores_unrelated_record() -> None:
    findings = lint_prompt(
        "Update the customer's account record after the payment posts.",
        {"alwaysDiscloseRecording": True},
    )
    codes = {f["code"] for f in findings}
    assert "missing_recording_disclosure" in codes


def test_a_forbidden_phrase_inside_a_prohibition_is_not_a_violation() -> None:
    """The first-party collections prompt says "Never threaten legal action", so
    the rule reported an error on the prompt the product ships — and on every
    card cloned from it. Writing a guardrail is not breaking one."""
    guardrails = {"prohibited": ["threaten"], "alwaysDiscloseRecording": True}
    prompt = (
        "Never threaten legal action. Offer Promise-to-Pay options instead. "
        "This call is recorded for quality and compliance."
    )

    findings = lint_prompt(prompt, guardrails)

    assert [f for f in findings if f["code"] == "prohibited_word_in_prompt"] == []


def test_a_negation_does_not_excuse_the_next_sentence() -> None:
    """The scan stops at the clause boundary. Otherwise one early "never" would
    clear every later use in the prompt."""
    guardrails = {"prohibited": ["threaten"], "alwaysDiscloseRecording": True}
    prompt = (
        "Never threaten legal action. Threaten escalation if they stall. "
        "This call is recorded for quality and compliance."
    )

    findings = [f for f in lint_prompt(prompt, guardrails) if f["code"] == "prohibited_word_in_prompt"]

    assert len(findings) == 1
    # Points at the real use, not the prohibition that precedes it.
    assert prompt[findings[0]["span"]["start"] :].startswith("Threaten escalation")


def test_a_crm_variable_in_a_system_prompt_says_the_line_is_dropped() -> None:
    """The editor offers nine variables; only four survive a system prompt. The
    other five cost the whole line — `strip_unrendered_crm_tokens` deletes it —
    and a message that said merely "is not substituted" led authors to expect a
    stray brace token rather than a missing sentence.

    Pinned rather than left to prose drift: this string is the only place the
    consequence is stated, and the frontend palette now mirrors it.
    """
    findings = lint_prompt(
        "Reference their account {account_no} and the amount {overdue_amount}.",
        {},
    )
    crm = [f for f in findings if f["code"] == "crm_variable_in_system_prompt"]

    assert {f["message"].split("}")[0] + "}" for f in crm} == {
        "{account_no}",
        "{overdue_amount}",
    }
    for finding in crm:
        assert "whole line" in finding["message"]
        assert finding["severity"] == "warn"


def test_the_system_safe_variables_are_not_flagged() -> None:
    """The counterpart — the four the palette still offers plainly must lint
    clean, or the split in the editor is advertising the wrong set."""
    findings = lint_prompt(
        "You are {agent_name} for {bank_name}. Speak {language}. It is {time_of_day}.",
        {},
    )

    assert [
        f for f in findings if f["code"] in {"crm_variable_in_system_prompt", "unknown_variable"}
    ] == []
