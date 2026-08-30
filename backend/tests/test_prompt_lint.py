"""Prompt lint disclosure regex — avoid false positives on unrelated 'record' words."""

from __future__ import annotations

from prompt_lint import lint_prompt


NO_DISCLOSURE = "You are a collections agent. Help the customer pay."
DISCLOSES = "This call is being recorded for quality. Help with EMI."
#: "record" as a noun. The regex must not read this as a disclosure.
UNRELATED_RECORD = "Update the customer's account record after the payment posts."


def test_the_guardrail_covers_the_disclosure_so_the_prompt_need_not() -> None:
    """No finding when the guardrail is on, however silent the prompt is.

    This assertion is the inverse of the one it replaces, deliberately. Every
    render path appends ``agent_core.guardrail_rules`` to the shipped system
    message, so with the guardrail on the disclosure is already guaranteed —
    reporting it "missing" told the author a compliant card was broken, and the
    remedy it implied (write "Always disclose that the call is recorded")
    is the phrasing that made a live call disclose three times over.
    """
    codes = {f["code"] for f in lint_prompt(NO_DISCLOSURE, {"alwaysDiscloseRecording": True})}
    assert not any(c.startswith("recording_disclosure") for c in codes)
    assert "missing_recording_disclosure" not in codes


def test_saying_it_as_well_as_the_guardrail_is_reported_as_duplication() -> None:
    findings = lint_prompt(DISCLOSES, {"alwaysDiscloseRecording": True})
    dup = [f for f in findings if f["code"] == "recording_disclosure_duplicated"]
    assert len(dup) == 1
    # Advisory. A second copy of a rule the platform enforces is untidy and
    # drift-prone, not a reason to stop a publish.
    assert dup[0]["severity"] == "info"


def test_recording_disclosure_ignores_unrelated_record() -> None:
    """An account *record* is not a disclosure — the original false positive.

    Asserted through the duplication finding now, because that is the branch
    the detector drives: a prompt the regex misread would be reported as
    already disclosing and told to delete a line it never had.
    """
    codes = {f["code"] for f in lint_prompt(UNRELATED_RECORD, {"alwaysDiscloseRecording": True})}
    assert "recording_disclosure_duplicated" not in codes


def test_nothing_discloses_when_the_guardrail_is_off_and_the_prompt_is_silent() -> None:
    """The case the old rule was blind to, and the only one that is a real gap."""
    findings = lint_prompt(NO_DISCLOSURE, {"alwaysDiscloseRecording": False})
    gap = [f for f in findings if f["code"] == "recording_disclosure_unenforced"]
    assert len(gap) == 1
    assert gap[0]["severity"] == "warn"


def test_an_author_who_writes_it_themselves_with_the_guardrail_off_is_left_alone() -> None:
    codes = {f["code"] for f in lint_prompt(DISCLOSES, {"alwaysDiscloseRecording": False})}
    assert not any(c.startswith("recording_disclosure") for c in codes)


def test_an_absent_guardrails_key_is_treated_as_off() -> None:
    codes = {f["code"] for f in lint_prompt(NO_DISCLOSURE, {})}
    assert "recording_disclosure_unenforced" in codes


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


# --- Flow syntax typed into a prompt ---------------------------------------
#
# The Flow tab renders `{{ customer_name }}` and the CRM value appears. A prompt
# renders `{customer_name}` and the whole line is deleted. The two syntaxes look
# alike, sit two tabs apart in one studio, and behave oppositely.
#
# A double-brace token in a prompt matched neither `TOKEN_RE` nor the CRM
# stripper, so it was not substituted, not dropped, and not reported — it
# survived verbatim into the system message and the model read the braces aloud.


def test_flow_syntax_in_a_prompt_is_an_error_not_silence() -> None:
    import prompt_lint

    findings = prompt_lint.lint_prompt("Greet {{ customer_name }} warmly.", {})
    codes = [f["code"] for f in findings]
    assert "flow_syntax_in_prompt" in codes
    assert next(f for f in findings if f["code"] == "flow_syntax_in_prompt")["severity"] == "error"


def test_flow_syntax_is_reported_separately_from_a_crm_single_brace() -> None:
    """Different failures — one is spoken aloud, the other deletes its line."""
    import prompt_lint

    findings = prompt_lint.lint_prompt(
        "Greet {{ customer_name }}. Reference {account_no}.", {}
    )
    codes = {f["code"] for f in findings}
    assert {"flow_syntax_in_prompt", "crm_variable_in_system_prompt"} <= codes


def test_a_flow_token_is_not_also_reported_as_an_unknown_variable() -> None:
    """One finding per defect; the editor renders each finding it is given."""
    import prompt_lint

    findings = prompt_lint.lint_prompt("Greet {{ customer_name }} warmly.", {})
    assert [f["code"] for f in findings].count("unknown_variable") == 0


def test_the_flow_token_span_covers_both_braces() -> None:
    """The editor highlights the span; half a token is worse than none."""
    import prompt_lint

    text = "Greet {{ customer_name }} warmly."
    finding = next(
        f for f in prompt_lint.lint_prompt(text, {}) if f["code"] == "flow_syntax_in_prompt"
    )
    span = finding["span"]
    assert text[span["start"] : span["end"]] == "{{ customer_name }}"


def test_an_ordinary_prompt_reports_no_flow_syntax() -> None:
    import prompt_lint

    findings = prompt_lint.lint_prompt("You are {agent_name} for {bank_name}.", {})
    assert not [f for f in findings if f["code"] == "flow_syntax_in_prompt"]


def test_a_spaceless_flow_token_is_reported_once_not_twice() -> None:
    """`{{customer_name}}` literally contains `{customer_name}`.

    An unmasked single-brace scan reported the same characters under two codes
    with two different remedies, so the editor showed contradictory advice about
    one token.
    """
    import prompt_lint

    findings = prompt_lint.lint_prompt("Greet {{customer_name}} now.", {})
    # Scoped to the two codes this is about. It used to assert the whole list,
    # which quietly made it a test of every unrelated rule as well: passing `{}`
    # guardrails means nothing discloses recording, and the day that grew a
    # finding of its own this failed for a reason having nothing to do with
    # brace masking.
    token_codes = [
        f["code"]
        for f in findings
        if f["code"] in {"flow_syntax_in_prompt", "crm_variable_in_system_prompt"}
    ]
    assert token_codes == ["flow_syntax_in_prompt"]


def test_spans_still_index_the_original_text_after_masking() -> None:
    import prompt_lint

    text = "Greet {{customer_name}} and quote {account_no}."
    for finding in prompt_lint.lint_prompt(text, {}):
        span = finding["span"]
        if span:
            assert text[span["start"] : span["end"]].startswith("{")


# -----------------------------------------------------------------------------
# The AI review (include_llm). Advisory, costed, and — until this change — it
# spent all five of its bullets restating guardrails the platform appends to
# every call anyway. A real reply, reproduced from the live endpoint:
#
#     alwaysDiscloseRecording: Not explicitly required (document doesn't
#         mention recording disclosure).
#     refusePoliticsReligion: Not explicitly required.
#     escalateAbuse: Not explicitly required.
#     escalateLegal: Not explicitly required.
#     neverQuoteRate / neverPromiseWaiver: Not explicitly required.
#
# Every one of those rules is in the shipped system message, put there by
# build_voice_system_prompt. Acting on the advice means keeping a second copy of
# policy in the authored prompt, where it drifts from the toggle that governs it
# and no longer shows up on the Guardrails tab.
# -----------------------------------------------------------------------------


def test_a_bullet_restating_an_enforced_guardrail_is_dropped() -> None:
    import prompt_lint

    for line in (
        "alwaysDiscloseRecording: Not explicitly required.",
        "refusePoliticsReligion: not explicitly required",
        "escalateAbuse: Not explicitly required (document doesn't mention it).",
        "neverQuoteRate / neverPromiseWaiver: Not explicitly required.",
        "The document is missing escalateLegal.",
        "Should also add refusePoliticsReligion.",
    ):
        assert prompt_lint._restates_enforced_guardrail(line), line


def test_a_real_finding_that_merely_touches_a_guardrail_subject_survives() -> None:
    """The filter matches the toggle's NAME plus an absence claim, not its topic.

    "The prompt never states why the agent is calling" is a genuine finding that
    happens to contain the word "state"; "it promises a waiver no tool can
    grant" is a genuine finding about neverPromiseWaiver's subject matter. A
    filter that reached for prose would delete both.
    """
    import prompt_lint

    for line in (
        "The prompt never states the purpose of the call.",
        "It promises a waiver the agent has no tool to grant.",
        "Step-by-step script here belongs in the conversation flow.",
        "Line 2 contradicts line 5 about who may be quoted a figure.",
        "The escalation path is described but no escalation tool is listed.",
    ):
        assert not prompt_lint._restates_enforced_guardrail(line), line


def test_the_review_hands_the_model_the_enforced_rules_and_keeps_what_is_left(
    monkeypatch,
) -> None:
    """The enforced block reaches the model, and surviving bullets come back."""
    import prompt_lint

    seen: dict[str, str] = {}

    def _fake_chat(messages, **_kwargs):
        seen["system"] = messages[0]["content"]
        seen["user"] = messages[1]["content"]
        return (
            "- alwaysDiscloseRecording: Not explicitly required.\n"
            "- The prompt never states the purpose of the call.\n"
        )

    monkeypatch.setattr("azure_openai.chat_complete", _fake_chat)

    findings = prompt_lint.lint_prompt(
        "You are an agent.",
        {"alwaysDiscloseRecording": True, "escalateAbuse": True},
        include_llm=True,
    )
    messages = [f["message"] for f in findings if f["code"] == "llm_checklist"]
    assert messages == ["The prompt never states the purpose of the call."]

    # The rules are handed over as settled, in the platform's own wording.
    assert "ALREADY ENFORCED" in seen["user"]
    assert "recorded for quality and compliance" in seen["user"]
    assert "escalate to a human agent" in seen["user"].lower()
    assert "never report one of them as missing" in seen["system"]


def test_no_issues_found_is_not_rendered_as_a_finding(monkeypatch) -> None:
    import prompt_lint

    monkeypatch.setattr(
        "azure_openai.chat_complete",
        lambda *_a, **_k: "No issues found in the authored text.",
    )
    findings = prompt_lint.lint_prompt("You are an agent.", {}, include_llm=True)
    assert [f for f in findings if f["code"] == "llm_checklist"] == []
