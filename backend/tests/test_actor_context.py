"""Actor identity resolution — spoofing + map caching."""

from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _reload_map(monkeypatch: pytest.MonkeyPatch):
    """Clear cached API_KEY_MAP between tests after env changes."""
    import actor_context

    monkeypatch.delenv("API_KEY_MAP", raising=False)
    actor_context.reload_api_key_map()
    yield
    actor_context.reload_api_key_map()


def test_api_key_map_binds_configured_user(monkeypatch: pytest.MonkeyPatch) -> None:
    import actor_context
    import db

    if not db.user_exists("priya-nair"):
        pytest.skip("priya-nair not seeded")

    secret = "actor-map-secret-priya"
    monkeypatch.setenv("API_KEY_MAP", json.dumps({secret: "priya-nair"}))
    monkeypatch.delenv("API_KEY", raising=False)
    actor_context.reload_api_key_map()

    ok, actor, err = actor_context.resolve_authenticated_actor(
        provided_key=secret, actor_header=None
    )
    assert ok and err is None
    assert actor == "priya-nair"


def test_unknown_actor_header_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import actor_context

    monkeypatch.setenv("API_KEY", "shared-dev-key")
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    actor_context.reload_api_key_map()

    ok, actor, err = actor_context.resolve_authenticated_actor(
        provided_key="shared-dev-key",
        actor_header="definitely-not-a-real-user-id",
    )
    assert not ok
    assert actor is None
    assert err == "actor_not_found"


def test_actor_header_ignored_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    import actor_context
    import db

    if not db.user_exists("priya-nair"):
        pytest.skip("priya-nair not seeded")

    monkeypatch.setenv("API_KEY", "shared-prod-key")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ACTOR_USER_ID", "priya-nair")
    monkeypatch.delenv("ALLOW_ACTOR_HEADER", raising=False)
    actor_context.reload_api_key_map()

    # Even if another user exists, header must not override in prod default.
    other = "rahul-sharma" if db.user_exists("rahul-sharma") else None
    ok, actor, err = actor_context.resolve_authenticated_actor(
        provided_key="shared-prod-key",
        actor_header=other or "spoof-attempt",
    )
    assert ok and err is None
    assert actor == "priya-nair"


def test_parse_api_key_map_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    import actor_context

    monkeypatch.setenv("API_KEY_MAP", json.dumps({"k1": "priya-nair"}))
    actor_context.reload_api_key_map()
    first = actor_context.parse_api_key_map()
    monkeypatch.setenv("API_KEY_MAP", json.dumps({"k2": "priya-nair"}))
    # Without reload, cache must still return k1.
    second = actor_context.parse_api_key_map()
    assert first == second == {"k1": "priya-nair"}
    actor_context.reload_api_key_map()
    assert actor_context.parse_api_key_map() == {"k2": "priya-nair"}
