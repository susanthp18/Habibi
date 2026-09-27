"""AgentStudio: engine-started dials are admitted by PayInt's contact policy."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from api.services.telephony import payint_admission


class _Client:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.sent = response, error, None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json, headers):
        self.sent = json
        if self.error:
            raise self.error
        return httpx.Response(200, json=self.response, request=httpx.Request("POST", url))


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setenv("PAYINT_ADMIT_URL", "http://api/voice-studio/hooks/admit")
    def with_context(ctx):
        monkeypatch.setattr(payint_admission.db_client, "get_workflow_run",
                            AsyncMock(return_value=SimpleNamespace(initial_context=ctx)))
    return with_context


@pytest.mark.asyncio
async def test_payint_dialled_calls_are_not_asked_again(run, monkeypatch):
    run({"attempt_id": "AT-1"})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **k: pytest.fail("PayInt was asked"))
    await payint_admission.admit("+919800000000", 5)


@pytest.mark.asyncio
async def test_a_refusal_stops_the_dial(run, monkeypatch):
    run({})
    client = _Client({"admitted": False, "reason": "dnd"})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **k: client)
    with pytest.raises(payint_admission.DialRefused, match="dnd"):
        await payint_admission.admit("+919800000000", 5)
    assert client.sent["to_number"] == "+919800000000"


@pytest.mark.asyncio
async def test_payint_unreachable_fails_closed(run, monkeypatch):
    run({})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **k: _Client(error=httpx.ConnectError("down")))
    with pytest.raises(payint_admission.DialRefused):
        await payint_admission.admit("+919800000000", 5)
