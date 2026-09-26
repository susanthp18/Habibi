"""AgentStudio: identity asserted by the host gateway (AUTH_PROVIDER=internal)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.services import organization_bootstrap
from api.services.auth import depends as auth_depends

SECRET = "s3cret"


def _headers(**extra):
    return {"x-internal-secret": SECRET, "x-user-id": "42", "x-org-id": "hdfc.retail", **extra}


@pytest.fixture
def internal(monkeypatch):
    monkeypatch.setattr(auth_depends, "AUTH_PROVIDER", "internal")
    monkeypatch.setattr(auth_depends, "AGENTSTUDIO_INTERNAL_SECRET", SECRET)
    user = SimpleNamespace(id=7, email=None, provider_id="host:42", selected_organization_id=None)
    org = SimpleNamespace(id=3)
    db = auth_depends.db_client
    calls = SimpleNamespace(
        get_user=AsyncMock(return_value=(user, True)),
        get_org=AsyncMock(return_value=(org, True)),
        add=AsyncMock(),
        select=AsyncMock(),
        email=AsyncMock(),
        bootstrap=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(db, "get_or_create_user_by_provider_id", calls.get_user)
    monkeypatch.setattr(db, "get_or_create_organization_by_provider_id", calls.get_org)
    monkeypatch.setattr(db, "add_user_to_organization", calls.add)
    monkeypatch.setattr(db, "update_user_selected_organization", calls.select)
    monkeypatch.setattr(db, "update_user_email", calls.email)
    monkeypatch.setattr(auth_depends, "ensure_organization_bootstrapped", calls.bootstrap)
    return user, org, calls


@pytest.mark.asyncio
async def test_gateway_identity_maps_to_one_user_and_one_tenant_org(internal):
    user, org, calls = internal
    request = SimpleNamespace(headers=_headers(**{"x-user-email": "Ops@Bank.example"}))

    result = await auth_depends.get_user(None, None, request)

    assert result is user and user.selected_organization_id == org.id
    calls.get_user.assert_awaited_once_with("host:42")
    assert calls.get_org.await_args.kwargs["org_provider_id"] == "tenant:hdfc.retail"
    calls.add.assert_awaited_once_with(7, 3)
    calls.email.assert_awaited_once_with(7, "ops@bank.example")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"x-internal-secret": "wrong", "x-user-id": "42", "x-org-id": "t"},
        {"x-internal-secret": SECRET, "x-org-id": "t"},
        {"x-internal-secret": SECRET, "x-user-id": "42"},
    ],
)
async def test_anything_but_the_gateway_is_rejected(internal, headers):
    with pytest.raises(HTTPException) as exc:
        await auth_depends.get_user("Bearer forged", None, SimpleNamespace(headers=headers))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_no_secret_configured_rejects_everything(internal, monkeypatch):
    monkeypatch.setattr(auth_depends, "AGENTSTUDIO_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException):
        await auth_depends.get_user(None, None, SimpleNamespace(headers=_headers()))


@pytest.mark.asyncio
async def test_websocket_reads_identity_from_headers(internal):
    user, _, _ = internal
    ws = SimpleNamespace(headers=_headers(), close=AsyncMock())
    assert await auth_depends.get_user_ws(ws, token=None, api_key=None) is user
    ws.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_vendor_service_endpoints_are_hidden(internal):
    with pytest.raises(HTTPException) as exc:
        await auth_depends.require_vendor_services()
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_bootstrap_never_reaches_the_vendor(monkeypatch):
    monkeypatch.setattr(organization_bootstrap, "AUTH_PROVIDER", "internal")
    minted = AsyncMock()
    monkeypatch.setattr(
        organization_bootstrap.mps_service_key_client, "create_service_key", minted
    )
    monkeypatch.setattr(
        organization_bootstrap, "_is_bootstrap_complete", AsyncMock(return_value=False)
    )
    assert await organization_bootstrap.ensure_organization_bootstrapped(3, created_by="host:42")
    minted.assert_not_awaited()
