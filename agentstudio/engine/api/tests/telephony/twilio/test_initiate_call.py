"""The dial carries its TwiML, so Twilio need not fetch it after the answer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.telephony.providers.twilio.provider import TwilioProvider

MODULE = "api.services.telephony.providers.twilio.provider"


def _provider() -> TwilioProvider:
    return TwilioProvider(
        {"account_sid": "AC123", "auth_token": "t", "from_numbers": ["+15551230002"]}
    )


async def _dial(**kwargs) -> dict:
    """Run initiate_call and return the form Twilio was sent."""
    response = MagicMock(status=201)
    response.json = AsyncMock(return_value={"sid": "CA1", "status": "queued"})
    post = MagicMock()
    post.return_value.__aenter__ = AsyncMock(return_value=response)
    post.return_value.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock(post=post)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    endpoints = AsyncMock(return_value=("https://api.example", "wss://api.example"))
    with (
        patch(f"{MODULE}.aiohttp.ClientSession", return_value=session),
        patch(f"{MODULE}.get_backend_endpoints", endpoints),
    ):
        await _provider().initiate_call(
            "+15551230001", "https://api.example/api/v1/telephony/twiml?x=1", **kwargs
        )
    return post.call_args.kwargs["data"]


@pytest.mark.asyncio
async def test_twiml_rides_with_the_dial():
    data = await _dial(workflow_run_id=73, workflow_id=4, organization_id=1)
    assert "Url" not in data
    assert "/api/v1/telephony/ws/4/1/73" in data["Twiml"]
    assert "<Connect>" in data["Twiml"]
    # Engine ids are ours, not Twilio parameters.
    assert "workflow_id" not in data and "organization_id" not in data
    assert data["StatusCallback"].endswith("/status-callback/73")


@pytest.mark.asyncio
async def test_without_the_ids_twilio_fetches_the_url():
    data = await _dial(workflow_run_id=73)
    assert data["Url"].endswith("/twiml?x=1")
    assert "Twiml" not in data
