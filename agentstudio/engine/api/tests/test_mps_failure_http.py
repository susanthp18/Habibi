import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from api.errors.mps import MPS_UNAVAILABLE_PUBLIC_MESSAGE, MPSUnavailableError
from api.routes import user as user_routes


@pytest.mark.asyncio
async def test_voice_catalog_does_not_duplicate_mps_failure(monkeypatch):
    # AgentStudio lists voices from the provider itself; its own HTTP errors
    # (no key saved, provider refused) reach the caller unchanged and unlogged.
    route_log_failure = Mock()
    list_voices = AsyncMock(side_effect=HTTPException(status_code=400, detail="no key"))
    monkeypatch.setattr(user_routes.voice_catalog_local, "list_voices", list_voices)
    monkeypatch.setattr(user_routes, "log_failure", route_log_failure)

    with pytest.raises(HTTPException) as exc:
        await user_routes.get_voices(
            provider="cartesia",
            user=SimpleNamespace(
                selected_organization_id=42,
                provider_id="provider-123",
            ),
        )

    assert exc.value.status_code == 400
    route_log_failure.assert_not_called()


@pytest.mark.asyncio
async def test_mps_unavailable_handler_returns_customer_safe_503():
    from api.app import app, handle_mps_unavailable_error

    assert app.exception_handlers[MPSUnavailableError] is handle_mps_unavailable_error

    response = await handle_mps_unavailable_error(
        None,
        MPSUnavailableError("validate_service_key", status_code=503),
    )

    assert response.status_code == 503
    assert json.loads(response.body) == {"detail": MPS_UNAVAILABLE_PUBLIC_MESSAGE}
