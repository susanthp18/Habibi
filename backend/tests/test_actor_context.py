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
    # Restore the environment *before* reloading: monkeypatch's own teardown
    # runs after this fixture, so reloading first re-caches the test's mapping
    # and leaks it into every later module.
    monkeypatch.undo()
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


def test_staging_without_credentials_is_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    """APP_ENV=staging is production for identity: missing keys refuse, not spoof."""
    import actor_context

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.delenv("ALLOW_ACTOR_HEADER", raising=False)
    actor_context.reload_api_key_map()

    ok, actor, err = actor_context.resolve_authenticated_actor(
        provided_key="", actor_header="priya-nair"
    )
    assert not ok
    assert actor is None
    assert err == "unauthorized"


def test_actor_header_off_for_an_unrecognised_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset ALLOW_ACTOR_HEADER is off — in staging as in every other name.

    Before WP-013 ``staging`` was treated as non-production and could spoof
    the actor behind a shared API key; since WP-070 no environment defaults
    to on (the laptop compose overlay sets it explicitly).
    """
    import actor_context
    import db

    if not db.user_exists("priya-nair"):
        pytest.skip("priya-nair not seeded")

    monkeypatch.setenv("API_KEY", "shared-dev-key")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ACTOR_USER_ID", "priya-nair")
    monkeypatch.delenv("ALLOW_ACTOR_HEADER", raising=False)
    actor_context.reload_api_key_map()

    # A header that would 400 if honoured (see test_unknown_actor_header_rejected)
    # must be ignored: staging is production for this purpose.
    ok, actor, err = actor_context.resolve_authenticated_actor(
        provided_key="shared-dev-key",
        actor_header="definitely-not-a-real-user-id",
    )
    assert ok and err is None
    assert actor == "priya-nair"

    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    ok, actor, err = actor_context.resolve_authenticated_actor(
        provided_key="shared-dev-key",
        actor_header="definitely-not-a-real-user-id",
    )
    assert not ok
    assert actor is None
    assert err == "actor_not_found"


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


def test_actor_header_is_off_unless_set_even_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """WP-070: a shared API_KEY never impersonates by default; dev opts in
    through docker-compose.dev.yml, not through the environment name."""
    import actor_context
    import db

    if not db.user_exists("priya-nair"):
        pytest.skip("priya-nair not seeded")

    monkeypatch.setenv("API_KEY", "shared-dev-key")
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ACTOR_USER_ID", "priya-nair")
    monkeypatch.delenv("ALLOW_ACTOR_HEADER", raising=False)
    actor_context.reload_api_key_map()

    assert actor_context._allow_actor_header() is False
    ok, actor, err = actor_context.resolve_authenticated_actor(
        provided_key="shared-dev-key", actor_header="definitely-not-a-real-user-id"
    )
    assert ok and err is None
    assert actor == "priya-nair"


def test_an_ignored_actor_header_is_said_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The console always sends X-Actor-User-Id. When the flag is off the
    server drops it and every action attributes to ACTOR_USER_ID -- once per
    process that is said out loud; with the flag on, dev and the console agree
    on who acted."""
    import actor_context
    import db

    if not db.user_exists("priya-nair"):
        pytest.skip("priya-nair not seeded")
    other = next((u["id"] for u in db.list_staff() if u["id"] != "priya-nair"), None)
    if other is None:
        pytest.skip("needs a second seeded user")

    monkeypatch.setenv("API_KEY", "shared-dev-key")
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ACTOR_USER_ID", "priya-nair")
    monkeypatch.delenv("ALLOW_ACTOR_HEADER", raising=False)
    monkeypatch.setattr(actor_context, "_ignored_header_warned", False)
    actor_context.reload_api_key_map()

    with caplog.at_level("WARNING", logger="actor_context"):
        ok, actor, _ = actor_context.resolve_authenticated_actor(
            provided_key="shared-dev-key", actor_header=other
        )
        actor_context.resolve_authenticated_actor(provided_key="shared-dev-key", actor_header=other)
    assert ok and actor == "priya-nair"
    assert sum("X-Actor-User-Id ignored" in r.message for r in caplog.records) == 1

    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    ok, actor, _ = actor_context.resolve_authenticated_actor(
        provided_key="shared-dev-key", actor_header=other
    )
    assert ok and actor == other


def test_a_deactivated_operator_stops_resolving(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    """A per-user key or an actor header naming an inactive user is refused;
    deactivation is recorded on users.status and nowhere else."""
    import actor_context
    import db

    other = next((u["id"] for u in db.list_staff() if u["id"] != "priya-nair"), None)
    if other is None:
        pytest.skip("needs a second seeded user")
    from sqlalchemy import text

    db_tx.execute(text("UPDATE users SET status = 'inactive' WHERE id = :id"), {"id": other})
    actor_context._user_exists_cache.clear()

    monkeypatch.setenv("API_KEY_MAP", json.dumps({"k-other": other}))
    monkeypatch.setenv("APP_ENV", "dev")
    actor_context.reload_api_key_map()
    ok, actor, err = actor_context.resolve_authenticated_actor(provided_key="k-other", actor_header=None)
    assert (ok, actor, err) == (False, None, "actor_not_found")
