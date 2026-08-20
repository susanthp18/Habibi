"""A WhatsApp turn that took 51 seconds and announced a call that never happened.

Session log, conversation CV-SUSANTH-WA1::

    08:49:44  bot_turn start
    08:50:37  azure_chat latency_ms=24972
    08:50:37  turn understanding refined · 51452ms
    08:50:39  azure_chat latency_ms=1822      <- the actual reply
    08:50:42  bot_turn succeeded

and the reply it produced began "Thanks for confirming. This call is recorded
for quality and compliance."

Two unrelated defects, both pinned here.

**It thought it was on a call.** ``build_system_prompt`` serves the messaging
channels and opened its reply rules with "Speak as the voice collections agent
… short spoken sentences" for every one of them, while ``guardrail_rules``
rendered the recording disclosure into the same prompt. Neither is true on
WhatsApp: nobody speaks and nothing is recorded.

**The enrichment outran the work it was enriching.** The reply took 1.8s. The
optional intent/sentiment call took 51.4s, on the critical path, because the
analysis profile advertises an 8s timeout and no retries but silently inherited
the main client's 20s and ``max_retries=2`` whenever no separate analysis
endpoint is configured — which is the default.
"""

from __future__ import annotations

import inspect

import pytest

from agent_core.prompt import build_system_prompt, guardrail_rules

_GUARDRAILS = {"alwaysDiscloseRecording": True, "neverQuoteRate": True}
_TEXT = ("whatsapp", "sms", "email", "chat", "text")


def _prompt(channel: str, authored: str = "") -> str:
    return build_system_prompt(
        rendered_prompt=authored,
        persona={},
        guardrails=_GUARDRAILS,
        context_blocks=[],
        channel=channel,
    )


# --- the recording disclosure is a telephony obligation ---------------------


@pytest.mark.parametrize("channel", _TEXT)
def test_text_channels_get_no_recording_disclosure_rule(channel: str) -> None:
    assert not any("recorded" in r for r in guardrail_rules(_GUARDRAILS, channel=channel))


def test_voice_still_gets_it() -> None:
    assert any("recorded" in r for r in guardrail_rules(_GUARDRAILS, channel="voice"))


def test_unknown_channels_keep_the_stricter_behaviour() -> None:
    """An unaware caller must not silently lose a compliance rule."""
    assert any("recorded" in r for r in guardrail_rules(_GUARDRAILS, channel="carrier-pigeon"))


@pytest.mark.parametrize("channel", (*_TEXT, "voice"))
def test_the_other_guardrails_survive_every_channel(channel: str) -> None:
    assert any("APR" in r or "interest rate" in r for r in guardrail_rules(_GUARDRAILS, channel=channel))


# --- and the model has to be told which medium it is in ---------------------


@pytest.mark.parametrize("channel", _TEXT)
def test_a_text_prompt_never_calls_itself_a_voice_agent(channel: str) -> None:
    """The line that convinced the WhatsApp bot it was speaking."""
    assert "Speak as the voice collections agent" not in _prompt(channel)


def test_a_voice_prompt_still_does() -> None:
    assert "Speak as the voice collections agent" in _prompt("voice")


@pytest.mark.parametrize("channel", _TEXT)
def test_a_text_prompt_says_it_is_not_a_call(channel: str) -> None:
    body = _prompt(channel)
    assert "NOT a phone call" in body
    assert "nothing is being recorded" in body


def test_the_framing_overrides_an_authored_disclosure_instruction() -> None:
    """The operator's own prompt says to always disclose. It is theirs to keep.

    This module does not get to rewrite it, so the fix is to name the medium
    and let the model see that the instruction is about voice calls.
    """
    body = _prompt(
        "whatsapp",
        authored="Always disclose that the call is recorded for quality and compliance.",
    )
    assert "Always disclose that the call is recorded" in body, "authored text is preserved"
    assert "does not apply here" in body


def test_only_one_channel_heading_reaches_the_model() -> None:
    """Two sections with the same title is how contradictory rules get filed."""
    assert _prompt("whatsapp").count("## Channel\n") == 1


def test_bot_runtime_declares_its_channel() -> None:
    import bot_runtime

    src = inspect.getsource(bot_runtime)
    assert 'channel="whatsapp",' in src
    assert "## WhatsApp behaviour" in src


# --- the analysis lane must honour its own budget ---------------------------


def test_analysis_client_does_not_inherit_the_main_timeout() -> None:
    """The default configuration is the broken one: no analysis endpoint set."""
    import azure_openai

    azure_openai.load_env()
    analysis = azure_openai.get_analysis_client()
    main = azure_openai.get_client()

    assert analysis.timeout == azure_openai._analysis_timeout_s()
    assert analysis.timeout < main.timeout
    assert analysis.max_retries == 0, "a retry spends a live caller's time"
    assert main.max_retries == 2, "the main lane keeps its retries"


def test_reusing_the_main_endpoint_does_not_open_a_second_pool() -> None:
    """The reason it returned the main client in the first place still holds."""
    import azure_openai

    azure_openai.load_env()
    analysis = azure_openai.get_analysis_client()
    main = azure_openai.get_client()
    assert analysis._client is main._client


def test_worst_case_analysis_wall_clock_is_bounded() -> None:
    """20s x (1 + 2 retries) is how one turn reached 51 seconds."""
    import azure_openai

    azure_openai.load_env()
    c = azure_openai.get_analysis_client()
    assert float(c.timeout) * (1 + c.max_retries) <= 10.0


# --- optional enrichment degrades on time, not just on error ----------------


def test_understanding_sends_a_per_request_budget() -> None:
    from agent_core import understanding

    assert "timeout=_timeout_s()" in inspect.getsource(understanding._ask_llm)


def test_the_budget_fits_inside_a_live_turn() -> None:
    from agent_core.understanding import _timeout_s

    assert 1.0 <= _timeout_s() <= 8.0


def test_a_bad_budget_setting_falls_back_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_core import understanding

    monkeypatch.setenv("UNDERSTANDING_LLM_TIMEOUT_S", "not-a-number")
    assert understanding._timeout_s() == understanding._DEFAULT_TIMEOUT_S


def test_the_keyword_baseline_is_what_a_timeout_degrades_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole justification for a budget: there is already an answer."""
    from agent_core import understanding

    monkeypatch.setattr(understanding, "_ask_llm", lambda *_a, **_k: (None, None))
    out = understanding.analyze_turn("i want to pay my emi next week", channel="text")
    assert out.intent
    assert out.sentiment_label
