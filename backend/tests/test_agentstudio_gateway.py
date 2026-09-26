"""The AgentStudio gateway: RBAC per engine path, identity injection, tickets."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import HTTPException

import authz
from routers import agentstudio_gateway as gw


@pytest.mark.parametrize(
    ("method", "path", "needs"),
    [
        ("GET", "/workflow/fetch", authz.BOT_READ),
        ("PUT", "/workflow/12", authz.AGENT_EDIT),
        ("POST", "/workflow/12/runs", authz.VOICE_OPERATE),
        ("POST", "/campaign/create", authz.VOICE_OPERATE),
        ("GET", "/knowledge-base/documents", authz.KB_READ),
        ("POST", "/knowledge-base/search", authz.KB_READ),
        ("DELETE", "/knowledge-base/documents/abc", authz.KB_WRITE),
        ("POST", "/tools", authz.INTEGRATIONS_WRITE),
        ("PUT", "/organizations/model-configurations/v2", authz.INTEGRATIONS_WRITE),
        ("GET", "/organizations/telephony-configs", authz.INTEGRATIONS_READ),
        ("GET", "/organizations/usage/runs", authz.ANALYTICS_READ),
        ("POST", "/user/api-keys", authz.ADMIN_WRITE),
        ("POST", "/user/configurations/voices/azure_speech/preview", authz.AGENT_EDIT),
        ("PUT", "/user/configurations/user", authz.INTEGRATIONS_WRITE),
        ("GET", "/ws/signaling/1/2", authz.VOICE_OPERATE),
        ("POST", "/something-new", authz.ADMIN_WRITE),
    ],
)
def test_each_engine_path_needs_the_matching_permission(method, path, needs):
    assert needs in gw.required_permissions(method, path)


@pytest.mark.parametrize("path", ["/auth/login", "/superuser/workflow-runs", "/public/agent/x", "/agent-stream/twilio/u", "/mcp/"])
def test_engine_logins_and_public_surfaces_are_not_reachable_through_the_gateway(monkeypatch, path):
    monkeypatch.setattr(authz, "enforcement_enabled", lambda: True)
    with pytest.raises(HTTPException) as exc:
        gw._authorise("POST", path, "u-admin")
    assert exc.value.status_code == 404


def test_a_viewer_cannot_write(monkeypatch):
    monkeypatch.setattr(authz, "enforcement_enabled", lambda: True)
    monkeypatch.setattr(authz, "has_permission", lambda uid, perm: perm == authz.BOT_READ)
    gw._authorise("GET", "/workflow/fetch", "u-viewer")
    with pytest.raises(HTTPException) as exc:
        gw._authorise("PUT", "/workflow/12", "u-viewer")
    assert exc.value.status_code == 403


def test_tickets_are_one_use_and_bound_to_their_path():
    tickets = gw._Tickets()
    t = tickets.mint("u-1", "/ws/signaling/1/2")
    assert tickets.redeem(t, "/ws/signaling/9/9") is None  # wrong path burns it
    t = tickets.mint("u-1", "/ws/signaling/1/2")
    assert tickets.redeem(t, "/ws/signaling/1/2") == "u-1"
    assert tickets.redeem(t, "/ws/signaling/1/2") is None


def test_expired_tickets_are_refused(monkeypatch):
    tickets = gw._Tickets()
    t = tickets.mint("u-1", "/ws/x")
    monkeypatch.setattr(gw.time, "monotonic", lambda: 10**12)
    assert tickets.redeem(t, "/ws/x") is None


def test_the_browser_credential_is_replaced_by_the_signed_identity(monkeypatch):
    seen = {}

    def engine(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(gw, "_client", httpx.AsyncClient(transport=httpx.MockTransport(engine)))
    monkeypatch.setattr(gw, "_engine_url", lambda: "http://engine")
    monkeypatch.setattr(authz, "enforcement_enabled", lambda: True)
    monkeypatch.setattr(authz, "has_permission", lambda uid, perm: True)
    monkeypatch.setattr(
        gw, "_identity", lambda actor: {"X-Internal-Secret": "s", "X-User-Id": actor, "X-Org-Id": "t"}
    )

    from starlette.requests import Request

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/studio-api/workflow/fetch",
        "query_string": b"status=active",
        "headers": [(b"authorization", b"Bearer entra"), (b"x-api-key", b"dgr_x"), (b"accept", b"application/json")],
        "state": {"actor_user_id": "u-7"},
    }
    response = asyncio.run(gw._proxy(Request(scope, receive), "workflow/fetch"))

    assert response.status_code == 200
    assert seen["url"] == "http://engine/api/v1/workflow/fetch?status=active"
    assert seen["headers"]["x-user-id"] == "u-7"
    assert "authorization" not in seen["headers"] and "x-api-key" not in seen["headers"]


def test_generated_client_paths_address_the_same_engine_route():
    assert gw._engine_path("api/v1/workflow/fetch") == "/workflow/fetch"
    assert gw._engine_path("/workflow/fetch") == "/workflow/fetch"
    assert gw.required_permissions("POST", gw._engine_path("/api/v1/auth/login")) == ()


def _write_request(path: str, body: bytes, method: str = "PUT"):
    from starlette.requests import Request

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "method": method, "path": f"/studio-api{path}", "query_string": b"",
                    "headers": [(b"content-type", b"application/json")],
                    "state": {"actor_user_id": "u-admin"}}, receive)


@pytest.fixture
def engine_seen(monkeypatch):
    seen: dict = {}

    def engine(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read()
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(gw, "_client", httpx.AsyncClient(transport=httpx.MockTransport(engine)))
    monkeypatch.setattr(gw, "_engine_url", lambda: "http://engine")
    monkeypatch.setattr(authz, "enforcement_enabled", lambda: True)
    monkeypatch.setattr(authz, "has_permission", lambda uid, perm: True)
    monkeypatch.setattr(gw, "_identity", lambda actor: {"X-Internal-Secret": "s", "X-User-Id": actor})
    return seen


@pytest.mark.parametrize("body", [b'{"inbound_workflow_id": 4}', b'{"label": "x", "clear_inbound_workflow": true}'])
def test_inbound_routing_cannot_bypass_the_routing_page(engine_seen, body):
    path = "/organizations/telephony-configs/1/phone-numbers/2"
    with pytest.raises(HTTPException) as exc:
        asyncio.run(gw._proxy(_write_request(path, body), path))
    assert exc.value.status_code == 409 and "body" not in engine_seen


def test_other_phone_number_edits_still_reach_the_engine(engine_seen):
    path = "/organizations/telephony-configs/1/phone-numbers/2"
    response = asyncio.run(gw._proxy(_write_request(path, b'{"label": "Main line"}'), path))
    assert response.status_code == 200 and engine_seen["body"] == b'{"label": "Main line"}'


def test_direct_publish_is_refused_so_every_release_has_a_note(engine_seen):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(gw._proxy(_write_request("/workflow/12/publish", b"", "POST"), "workflow/12/publish"))
    assert exc.value.status_code == 404 and "body" not in engine_seen
