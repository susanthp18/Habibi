"""The token counter must describe the call, not the textarea.

The editor's footer read "100 tokens · $0.0003" for a card whose system message
is 878 tokens. The endpoint counted ``payload.prompt`` and nothing else, but the
message the model receives is the authored prompt *plus* generated guardrail
rules, persona directions, tenant-local time and — on voice — a ~650-token
naturalness overlay. It is re-sent on every LLM call, two or three times a turn
through Flows.

So the one number in the Studio that exists to answer "what does this cost"
understated the answer by roughly 8x, in the safe direction for a demo and the
expensive direction for a tenant.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main

GUARDRAILS = {
    "prohibited": [],
    "escalateAbuse": True,
    "escalateLegal": True,
    "neverQuoteRate": True,
    "neverPromiseWaiver": True,
    "alwaysDiscloseRecording": True,
    "refusePoliticsReligion": False,
    "maxTurns": 30,
    "maxSeconds": 600,
}
PERSONA = {
    "traits": {"empathy": 82, "firmness": 40, "formality": 55, "verbosity": 60, "upsell": 20},
    "language": "English",
    "fallbackLanguages": ["Hindi"],
}
PROMPT = "You are {agent_name}, a collections agent for {bank_name}. Speak in {language}."


@pytest.fixture(scope="module")
def client(api_headers: dict[str, str]) -> TestClient:
    # api_headers is empty when nothing is enforcing, so this is a no-op on a
    # dev machine and the difference that made these eight tests 401 in CI.
    return TestClient(main.app, headers=api_headers)


def _estimate(client: TestClient, **body: object) -> dict:
    res = client.post("/prompt-versions/estimate-tokens", json={"prompt": PROMPT, **body})
    assert res.status_code == 200, res.text
    return res.json()


def test_the_authored_count_is_unchanged(client: TestClient) -> None:
    """The existing contract still holds — this adds a figure, it does not move one."""
    plain = _estimate(client)
    withctx = _estimate(client, guardrails=GUARDRAILS, persona=PERSONA)
    assert plain["tokens"] == withctx["tokens"]
    assert plain["costUsd"] == withctx["costUsd"]


def test_without_guardrails_no_assembled_figure_is_invented(client: TestClient) -> None:
    """A guess presented as a measurement is worse than no measurement."""
    body = _estimate(client)
    assert body["assembledTokens"] is None
    assert body["assembledCostUsd"] is None


def test_the_assembled_message_is_several_times_the_authored_text(client: TestClient) -> None:
    body = _estimate(client, guardrails=GUARDRAILS, persona=PERSONA)
    assert body["assembledTokens"] > body["tokens"] * 3


def test_the_assembled_cost_uses_the_same_rate(client: TestClient) -> None:
    body = _estimate(client, guardrails=GUARDRAILS, persona=PERSONA)
    expected = round(body["assembledTokens"] * body["usdPer1M"] / 1_000_000.0, 6)
    assert body["assembledCostUsd"] == expected


def test_voice_costs_more_than_text(client: TestClient) -> None:
    """The naturalness overlay is the difference, and it is most of the message."""
    voice = _estimate(client, guardrails=GUARDRAILS, persona=PERSONA, channel="voice")
    text = _estimate(client, guardrails=GUARDRAILS, persona=PERSONA, channel="text")
    assert voice["assembledTokens"] > text["assembledTokens"]


def test_turning_a_guardrail_on_costs_tokens(client: TestClient) -> None:
    """The figure has to respond to the control, or it is decoration."""
    off = _estimate(
        client, guardrails={**GUARDRAILS, "refusePoliticsReligion": False}, persona=PERSONA
    )
    on = _estimate(
        client, guardrails={**GUARDRAILS, "refusePoliticsReligion": True}, persona=PERSONA
    )
    assert on["assembledTokens"] > off["assembledTokens"]


def test_a_crm_line_that_gets_deleted_is_not_billed(client: TestClient) -> None:
    """The assembled count runs the real render, deletions included."""
    kept = _estimate(client, guardrails=GUARDRAILS, persona=PERSONA)
    res = client.post(
        "/prompt-versions/estimate-tokens",
        json={
            "prompt": PROMPT + "\nReference their account {account_no} in full.",
            "guardrails": GUARDRAILS,
            "persona": PERSONA,
        },
    )
    assert res.status_code == 200, res.text
    doomed = res.json()
    # strip_unrendered_crm_tokens deletes the extra line before assembly, so it
    # raises the authored count and leaves the assembled one exactly where it was.
    assert doomed["tokens"] > kept["tokens"]
    assert doomed["assembledTokens"] == kept["assembledTokens"]


def test_persona_is_optional(client: TestClient) -> None:
    body = _estimate(client, guardrails=GUARDRAILS)
    assert body["assembledTokens"] > body["tokens"]
