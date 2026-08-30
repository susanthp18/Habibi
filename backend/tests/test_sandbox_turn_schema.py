"""The sandbox turn request body must accept what the studio actually posts.

``POST /sandbox/runs/{run_id}/turns`` returned 422 for *every* customer turn:

    {"type":"extra_forbidden","loc":["body","skillSlug"],
     "msg":"Extra inputs are not permitted"}

Three layers disagreed. ``appendSandboxTurn`` in Habibi/src/api/sandbox.ts
always posts ``skillSlug`` (``input.skillSlug ?? null``); ``sandbox_runtime``
reads it and pins the active skill from it; ``SandboxTurnCreateRequest``
declared only text/history/context/topK under ``extra="forbid"``, so the
request was rejected before the handler ran and the rehearsal conversation was
dead at turn one.

Nothing caught it because no test posted the body the browser posts — the
runtime was tested directly, with a dict it built itself. The tests below go
through the app, so the request model is on the path.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
SANDBOX_TS = BACKEND_ROOT.parent / "Habibi" / "src" / "api" / "sandbox.ts"

RUN_ID = "sbx-run-turn-schema"
HEADERS = {"X-API-Key": "sandbox-turn-test-key", "X-Actor-User-Id": "priya-nair"}


def _turn_response(run_id: str) -> dict:
    """A minimal SandboxTurnResponse — enough to serialise, no LLM involved."""
    return {
        "runId": run_id,
        "promptVersionId": "v1_4",
        "customerTurn": {
            "id": "c-1",
            "role": "customer",
            "text": "Yes this is Rahul speaking",
            "intent": "identity_confirm",
            "intentScores": {"identity_confirm": 1.0},
            "sentiment": 0.0,
            "sentimentLabel": "neutral",
        },
        "botTurn": {
            "id": "b-1",
            "role": "bot",
            "text": "Thank you for confirming.",
            "chunkIds": [],
            "chunks": [],
            "latencyMs": 12,
            "tokens": 34,
            "guardrailFlags": [],
            "intent": "identity_confirm",
            "sentiment": 0.0,
            "sentimentLabel": "neutral",
        },
    }


@pytest.fixture()
def captured(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Stand in for the runtime and record the payload the handler forwards.

    ``main`` calls ``sandbox_runtime.append_sandbox_turn`` through the module,
    so patching the attribute is enough. The real one calls Azure and writes
    turn rows; what is under test here is the request model in front of it.
    """
    import sandbox_runtime

    seen: list[dict] = []

    def _fake_append(run_id: str, payload: dict) -> dict:
        seen.append(payload)
        return _turn_response(run_id)

    monkeypatch.setattr(sandbox_runtime, "append_sandbox_turn", _fake_append)
    return seen


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import actor_context
    import main as app_main

    monkeypatch.setenv("API_KEY", HEADERS["X-API-Key"])
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    actor_context.reload_api_key_map()
    return TestClient(app_main.app)


def _post(client: TestClient, body: dict):
    return client.post(f"/sandbox/runs/{RUN_ID}/turns", json=body, headers=HEADERS)


# ---------------------------------------------------------------------------
# The body the studio posts
# ---------------------------------------------------------------------------


def test_turn_without_skill_slug_is_accepted(client, captured) -> None:
    """The field is optional — an older client that omits it still works."""
    res = _post(
        client,
        {"text": "Yes this is Rahul speaking", "history": [], "context": None, "topK": 3},
    )

    assert res.status_code == 200, res.text
    assert res.json()["runId"] == RUN_ID
    assert len(captured) == 1
    assert captured[0]["skillSlug"] is None


def test_turn_with_skill_slug_is_accepted_and_reaches_the_runtime(client, captured) -> None:
    """The regression itself: this is the exact body appendSandboxTurn sends.

    Accepting it is only half the fix — the value has to survive
    ``model_dump()`` and arrive in the dict ``sandbox_runtime`` reads
    ``payload.get("skillSlug")`` out of, or the active skill silently resets to
    None on every turn.
    """
    res = _post(
        client,
        {
            "text": "Yes this is Rahul speaking",
            "history": [{"role": "bot", "text": "Am I speaking with Rahul?"}],
            "context": None,
            "topK": 3,
            "skillSlug": "waiver_negotiation",
        },
    )

    assert res.status_code == 200, res.text
    assert len(captured) == 1
    assert captured[0]["skillSlug"] == "waiver_negotiation"
    assert captured[0]["text"] == "Yes this is Rahul speaking"
    assert captured[0]["topK"] == 3


def test_explicit_null_skill_slug_is_accepted(client, captured) -> None:
    """``input.skillSlug ?? null`` — the studio posts null when no skill is pinned."""
    res = _post(
        client,
        {"text": "hello", "history": [], "context": None, "topK": 3, "skillSlug": None},
    )

    assert res.status_code == 200, res.text
    assert captured[0]["skillSlug"] is None


# ---------------------------------------------------------------------------
# extra="forbid" stays
# ---------------------------------------------------------------------------


def test_an_unknown_field_is_still_rejected(client, captured) -> None:
    """Widening the model to one known field must not open it to anything."""
    res = _post(
        client,
        {
            "text": "hello",
            "history": [],
            "context": None,
            "topK": 3,
            "skillSlug": None,
            "totallyNotAField": "junk",
        },
    )

    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert any(
        d.get("type") == "extra_forbidden" and d.get("loc")[-1] == "totallyNotAField"
        for d in detail
    ), detail
    assert not captured, "a rejected body must not reach the runtime"


def test_the_model_still_forbids_extras() -> None:
    import schemas

    assert schemas.SandboxTurnCreateRequest.model_config.get("extra") == "forbid"
    assert "skillSlug" in schemas.SandboxTurnCreateRequest.model_fields
    assert schemas.SandboxTurnCreateRequest.model_fields["skillSlug"].default is None


# ---------------------------------------------------------------------------
# Contract drift — the check that would have caught this in the first place
# ---------------------------------------------------------------------------


def test_every_key_the_studio_posts_is_a_field_on_the_request_model() -> None:
    """``extra="forbid"`` makes the studio's POST body part of the contract.

    A key added on the TypeScript side without a matching field here is not a
    lenient no-op, it is a 422 on every turn. Reading the literal keeps the two
    sides pinned to each other instead of to a comment.
    """
    import schemas

    source = SANDBOX_TS.read_text(encoding="utf-8")
    match = re.search(
        r"apiPost<SandboxTurnResult>\(\s*`[^`]*/turns`\s*,\s*\{(?P<body>.*?)\n\s*\}\s*\)",
        source,
        re.S,
    )
    assert match, f"could not locate the turns POST body in {SANDBOX_TS}"

    posted = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*):", match.group("body"), re.M))
    assert "skillSlug" in posted, "the literal changed — this test is no longer guarding it"

    unknown = sorted(posted - set(schemas.SandboxTurnCreateRequest.model_fields))
    assert not unknown, (
        f"Habibi/src/api/sandbox.ts posts {unknown}, which SandboxTurnCreateRequest "
        "rejects under extra='forbid' — every sandbox turn would 422"
    )
