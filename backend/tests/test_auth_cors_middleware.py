"""Regression tests for auth/CORS middleware, actor binding, and breakers.

Locks shut: ApiKeyMiddleware must NOT reject CORS preflight OPTIONS when
API_KEY is set, and CORS must be outermost so 401s carry Access-Control-*.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = "test-api-key-regression-lock"
    monkeypatch.setenv("API_KEY", key)
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    monkeypatch.setenv("ACTOR_USER_ID", "priya-nair")
    return key


@pytest.fixture()
def client() -> TestClient:
    import main as app_main

    return TestClient(app_main.app)


def test_middleware_order_cors_outermost(client: TestClient) -> None:
    import main as app_main

    names = [m.cls.__name__ for m in app_main.app.user_middleware]
    assert names[0] == "CORSMiddleware", names
    assert "ApiKeyMiddleware" in names
    assert names.index("ApiKeyMiddleware") > names.index("CORSMiddleware")


def test_options_preflight_ok_with_api_key(client: TestClient, api_key: str) -> None:
    res = client.options(
        "/conversations",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-api-key,content-type,x-actor-user-id",
        },
    )
    assert res.status_code in {200, 204}, res.text
    assert res.headers.get("access-control-allow-origin")
    assert res.status_code != 401


def test_missing_api_key_401_with_cors(client: TestClient, api_key: str) -> None:
    res = client.get(
        "/conversations",
        headers={"Origin": "http://localhost:5173"},
    )
    assert res.status_code == 401
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "unauthorized" in res.text.lower()


def test_wrong_api_key_401(client: TestClient, api_key: str) -> None:
    res = client.get(
        "/conversations",
        headers={"X-API-Key": "definitely-wrong", "Origin": "http://localhost:5173"},
    )
    assert res.status_code == 401
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_non_ascii_api_key_compare_is_safe(client: TestClient, api_key: str) -> None:
    """A non-ASCII key must 401 through the real middleware, not 500.

    ``secrets.compare_digest`` raises TypeError on non-ASCII ``str`` input, so
    this exercises ApiKeyMiddleware end-to-end rather than re-asserting its
    predicate — an inline copy would keep passing after the middleware
    regressed to the str comparison.
    """
    # httpx encodes str header values as ASCII, so send raw bytes — that is
    # what a real client puts on the wire anyway.
    res = client.get(
        "/conversations", headers={"X-API-Key": "café-key".encode("utf-8")}
    )
    assert res.status_code == 401, res.text


def test_correct_api_key_passes(client: TestClient, api_key: str) -> None:
    res = client.get("/me", headers={"X-API-Key": api_key})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == "priya-nair"


def test_actor_header_binds_identity(
    client: TestClient, api_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Prefer a second seeded user if present; otherwise skip.
    import db

    candidates = ["rahul-sharma", "anita-desai", "vikram-rao"]
    other = next((u for u in candidates if db.user_exists(u)), None)
    if other is None:
        pytest.skip("no alternate seeded user for actor-header test")

    res = client.get(
        "/me",
        headers={"X-API-Key": api_key, "X-Actor-User-Id": other},
    )
    assert res.status_code == 200, res.text
    assert res.json()["id"] == other


def test_api_key_map_binds_actor(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    import actor_context
    import db

    if not db.user_exists("priya-nair"):
        pytest.skip("priya-nair not seeded")

    secret = "map-secret-priya"
    monkeypatch.setenv("API_KEY_MAP", json.dumps({secret: "priya-nair"}))
    monkeypatch.delenv("API_KEY", raising=False)
    actor_context.reload_api_key_map()

    res = client.get("/me", headers={"X-API-Key": secret})
    assert res.status_code == 200, res.text
    assert res.json()["id"] == "priya-nair"
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    actor_context.reload_api_key_map()


def test_health_exempt_without_key(client: TestClient, api_key: str) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json().get("status") == "ok"


def test_ready_shape(client: TestClient, api_key: str) -> None:
    res = client.get("/ready")
    body = res.json()
    if res.status_code == 503:
        detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
        assert "pool" in detail or "ok" in detail
    else:
        assert res.status_code == 200
        assert "pool" in body or "ok" in body
        assert "circuits" in body


def test_azure_busy_maps_to_503(client: TestClient, api_key: str) -> None:
    import asyncio

    import azure_openai
    import main as app_main

    resp = asyncio.run(
        app_main._azure_busy_handler(
            None,  # type: ignore[arg-type]
            azure_openai.AzureBusyError("azure_concurrency_saturated"),
        )
    )
    assert resp.status_code == 503
    assert b"azure_concurrency_saturated" in resp.body


def test_circuit_open_maps_to_503(client: TestClient, api_key: str) -> None:
    import asyncio

    import circuit_breaker
    import main as app_main

    resp = asyncio.run(
        app_main._circuit_open_handler(
            None,  # type: ignore[arg-type]
            circuit_breaker.CircuitOpenError("circuit_open:azure_openai"),
        )
    )
    assert resp.status_code == 503
    assert b"circuit_open" in resp.body


def test_prod_boot_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production startup must refuse to boot with no credentials configured.

    Drives main's real lifespan validation. The previous version re-implemented
    the condition and raised its own RuntimeError, so it passed even if the
    production check were deleted outright.
    """
    import asyncio

    import actor_context
    import main as app_main

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setattr(app_main, "_IS_PROD", True)
    # Deferred-hardening gate would fire first — acknowledge it so this test
    # exercises the credential check specifically.
    monkeypatch.setenv("ALLOW_UNHARDENED_PRODUCTION", "1")
    actor_context.reload_api_key_map()

    async def _boot() -> None:
        async with app_main.lifespan(app_main.app):
            pass

    try:
        with pytest.raises(RuntimeError, match="API_KEY"):
            asyncio.run(_boot())
    finally:
        # Undo the env changes BEFORE rebuilding the cache, and do it even when
        # the assertion fails: reloading first cached the map for the test's
        # own stripped environment, so every later test in the process ran
        # against no API keys.
        monkeypatch.undo()
        actor_context.reload_api_key_map()


def test_semaphore_acquire_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import azure_openai

    monkeypatch.setenv("AZURE_OPENAI_MAX_CONCURRENT", "1")
    monkeypatch.setenv("AZURE_OPENAI_ACQUIRE_TIMEOUT_S", "1")
    azure_openai._azure_sem = None

    with azure_openai._azure_slot():
        with pytest.raises(azure_openai.AzureBusyError):
            with azure_openai._azure_slot():
                pass

    azure_openai._azure_sem = None


def test_circuit_breaker_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    import circuit_breaker

    monkeypatch.setenv("CIRCUIT_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("CIRCUIT_RESET_TIMEOUT_S", "60")
    # Fresh breaker instance
    with circuit_breaker._breakers_lock:
        circuit_breaker._breakers.pop("test_breaker", None)
    b = circuit_breaker.CircuitBreaker("test_breaker", failure_threshold=3, reset_timeout_s=60)

    def _fail():
        raise RuntimeError("boom")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            b.call(_fail)

    with pytest.raises(circuit_breaker.CircuitOpenError):
        b.call(lambda: "ok")
