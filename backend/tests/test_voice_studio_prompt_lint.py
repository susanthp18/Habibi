"""Voice Studio prompt lint: what the engine renders, not the old runtime's syntax."""

import voice_studio_prompt_lint as vlint

RULES = {"prohibited": ["legal action"], "alwaysDiscloseRecording": True}


def codes(prompt, **kw):
    return [f["code"] for f in vlint.lint(prompt, RULES, **kw)]


def test_engine_template_syntax_is_valid_and_known_keys_pass():
    assert codes("Hello {{initial_context.first_name}}, you owe {{initial_context.outstanding_amount}}.") == []


def test_unsupplied_context_key_is_flagged_unless_it_has_a_fallback():
    assert codes("Hi {{initial_context.first_nme}}") == ["unsupplied_context"]
    assert codes("Hi {{initial_context.first_nme | fallback:there}}") == []


def test_old_single_brace_variables_are_errors():
    assert codes("Hello {customer_name}") == ["single_brace_variable"]


def test_prohibited_phrase_is_flagged_but_a_prohibition_is_not():
    assert codes("We will take legal action.") == ["prohibited_phrase"]
    assert codes("Never threaten legal action.") == []


def test_opening_must_disclose_recording_when_the_guardrail_requires_it():
    assert codes("Hello, I am calling from the bank.", is_opening=True) == ["recording_disclosure_missing"]
    assert codes("Hello, this call is recorded.", is_opening=True) == []
    assert codes("Hello, I am calling from the bank.") == []
    assert codes("How can I help?", is_opening=True, spoken_first="Hi, this call is recorded for quality.") == []


def test_estimate_reports_tokens_and_cost():
    out = vlint.lint_with_estimate("Hello there, this call is recorded.", RULES)
    assert out["tokens"] > 0 and out["usdPerTurn"] >= 0
