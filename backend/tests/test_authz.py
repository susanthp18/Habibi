"""Per-route authorization.

The load-bearing test here is :func:`test_registry_covers_every_route`. Before
authz existed, exactly one of ~180 routes was gated; the failure mode being
locked shut is not "this route is wrong" but "somebody added a route and nobody
noticed it was ungated".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import authz


# ---------------------------------------------------------------------------
# Registry integrity — no database, no app boot
# ---------------------------------------------------------------------------


def _app_routes() -> list[tuple[str, str]]:
    from fastapi.routing import APIRoute, APIWebSocketRoute

    import main as app_main

    out: list[tuple[str, str]] = []
    for route in app_main.app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                out.append((method, route.path))
        elif isinstance(route, APIWebSocketRoute):
            out.append(("WS", route.path))
    return out


def test_registry_covers_every_route() -> None:
    """Every route is classified. A new endpoint must not ship ungated."""
    authz.assert_registry_covers(_app_routes())


def test_registry_has_no_entries_for_routes_that_do_not_exist() -> None:
    """A stale registry row is a policy that silently protects nothing."""
    live = {(m.upper(), p) for m, p in _app_routes()}
    # The embedded voice host registers /api/offer only when enabled, and the
    # WhatsApp/Twilio callbacks are always present; anything else in the
    # registry that is not routable is dead policy.
    optional = {
        ("POST", "/api/offer"),
        ("PATCH", "/api/offer"),
        ("POST", "/voice-rtc/api/offer"),
        ("PATCH", "/voice-rtc/api/offer"),
    }
    stale = sorted(
        f"{m} {p}"
        for m, p in (set(authz.ROUTE_PERMISSIONS) | authz.PUBLIC_ROUTES)
        if (m, p) not in live and (m, p) not in optional
    )
    assert not stale, f"authz registry references routes that do not exist: {stale}"


def test_every_registered_permission_is_in_the_catalog() -> None:
    """Guards against a typo'd constant silently denying a whole screen."""
    unknown = sorted(set(authz.ROUTE_PERMISSIONS.values()) - authz.ALL_PERMISSIONS)
    assert not unknown, f"permissions not in PERMISSION_CATALOG: {unknown}"


def test_role_defaults_only_reference_catalog_permissions() -> None:
    for role, perms in authz.ROLE_DEFAULTS.items():
        unknown = sorted(perms - authz.ALL_PERMISSIONS)
        assert not unknown, f"role {role} defaults reference unknown perms: {unknown}"


def test_permission_ids_are_unique() -> None:
    ids = [p[0] for p in authz.PERMISSION_CATALOG]
    assert len(ids) == len(set(ids))


def test_admin_default_is_every_permission() -> None:
    assert authz.ROLE_DEFAULTS["admin"] == authz.ALL_PERMISSIONS


def test_no_role_default_grants_admin_write_except_admin() -> None:
    """Superuser must not leak into an ordinary role's fallback grants."""
    for role, perms in authz.ROLE_DEFAULTS.items():
        if role == "admin":
            continue
        assert authz.ADMIN_WRITE not in perms, role


# ---------------------------------------------------------------------------
# Enforcement switch
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_authz_cache():
    authz.invalidate_permission_cache()
    yield
    authz.invalidate_permission_cache()


def test_enforcement_off_when_no_credentials_configured(monkeypatch) -> None:
    """Local dev with auth unset keeps working exactly as before."""
    import actor_context

    monkeypatch.delenv("AUTHZ_ENFORCE", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    actor_context.reload_api_key_map()
    assert authz.enforcement_enabled() is False
    # ...and check() is therefore a no-op even for a user with no grants.
    authz.check("POST", "/webhook-endpoints", "nobody-at-all")


def test_enforcement_on_when_api_key_configured(monkeypatch) -> None:
    import actor_context

    monkeypatch.delenv("AUTHZ_ENFORCE", raising=False)
    monkeypatch.setenv("API_KEY", "some-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    actor_context.reload_api_key_map()
    assert authz.enforcement_enabled() is True


def test_enforce_env_overrides_in_both_directions(monkeypatch) -> None:
    import actor_context

    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    actor_context.reload_api_key_map()
    monkeypatch.setenv("AUTHZ_ENFORCE", "1")
    assert authz.enforcement_enabled() is True
    monkeypatch.setenv("API_KEY", "some-key")
    monkeypatch.setenv("AUTHZ_ENFORCE", "0")
    assert authz.enforcement_enabled() is False


def test_unregistered_route_is_denied_not_allowed(monkeypatch) -> None:
    """Fail closed: a route nobody classified must not be reachable."""
    monkeypatch.setenv("AUTHZ_ENFORCE", "1")
    with pytest.raises(authz.PermissionDenied) as exc:
        authz.check("POST", "/some/route/nobody/registered", "priya-nair")
    assert exc.value.permission == "unregistered_route"


def test_public_route_needs_no_actor(monkeypatch) -> None:
    monkeypatch.setenv("AUTHZ_ENFORCE", "1")
    authz.check("GET", "/health", None)
    authz.check("POST", "/webhooks/whatsapp", None)


# ---------------------------------------------------------------------------
# Grant resolution against the seeded roles
# ---------------------------------------------------------------------------


def test_admin_actor_resolves_to_every_permission() -> None:
    """priya-nair holds role-admin, whose only explicit grant is admin-write."""
    perms = authz.actor_permissions("priya-nair")
    assert perms == authz.ALL_PERMISSIONS


def test_agent_actor_is_limited_to_its_explicit_grants() -> None:
    """role-agent has explicit rows, so the database is authoritative for it."""
    perms = authz.actor_permissions("arjun-mehta")
    assert authz.CUSTOMERS_READ in perms
    assert authz.INTERACTIONS_READ in perms
    assert authz.ADMIN_WRITE not in perms
    assert authz.INTEGRATIONS_WRITE not in perms


def test_actor_with_no_roles_has_no_permissions() -> None:
    assert authz.actor_permissions("anita-rao") == frozenset()


def test_unknown_actor_has_no_permissions() -> None:
    assert authz.actor_permissions("no-such-user-at-all") == frozenset()


def test_blank_actor_has_no_permissions() -> None:
    assert authz.actor_permissions("") == frozenset()
    assert authz.actor_permissions(None) == frozenset()  # type: ignore[arg-type]


def test_role_with_no_explicit_grants_falls_back_to_defaults(db_tx) -> None:
    """A fresh database with roles but no role_permissions is still usable."""
    db_tx.execute(
        text("INSERT INTO roles (id, tenant_id, name) VALUES ('role-tmp-qa', :t, 'QA Reviewer')"),
        {"t": __import__("db").TENANT_ID},
    )
    db_tx.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES ('anita-rao', 'role-tmp-qa')")
    )
    authz.invalidate_permission_cache("anita-rao")

    perms = authz.actor_permissions("anita-rao")
    assert perms == authz.ROLE_DEFAULTS["qa_reviewer"]
    assert authz.ADMIN_WRITE not in perms


def test_explicit_grant_beats_default_so_revocation_works(db_tx) -> None:
    """Once a role has any explicit row, the default set no longer applies."""
    tenant = __import__("db").TENANT_ID
    db_tx.execute(
        text("INSERT INTO roles (id, tenant_id, name) VALUES ('role-tmp-qa2', :t, 'QA Reviewer')"),
        {"t": tenant},
    )
    db_tx.execute(
        text(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "VALUES ('role-tmp-qa2', :p)"
        ),
        {"p": authz.QA_REVIEW},
    )
    db_tx.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES ('anita-rao', 'role-tmp-qa2')")
    )
    authz.invalidate_permission_cache("anita-rao")

    perms = authz.actor_permissions("anita-rao")
    assert perms == frozenset({authz.QA_REVIEW})
    # QA_WRITE is in the qa_reviewer default set but was not granted — the
    # database's opinion wins, which is what makes revocation possible.
    assert authz.QA_WRITE not in perms


def test_permission_cache_is_invalidatable(db_tx) -> None:
    assert authz.actor_permissions("anita-rao") == frozenset()
    tenant = __import__("db").TENANT_ID
    db_tx.execute(
        text("INSERT INTO roles (id, tenant_id, name) VALUES ('role-tmp-adm', :t, 'Admin')"),
        {"t": tenant},
    )
    db_tx.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES ('anita-rao', 'role-tmp-adm')")
    )
    # Still cached as empty until invalidated.
    assert authz.actor_permissions("anita-rao") == frozenset()
    authz.invalidate_permission_cache("anita-rao")
    assert authz.actor_permissions("anita-rao") == authz.ALL_PERMISSIONS


# ---------------------------------------------------------------------------
# Catalog bootstrap
# ---------------------------------------------------------------------------


def test_ensure_permission_catalog_is_idempotent(db_tx) -> None:
    import db

    authz.ensure_permission_catalog(db.engine)
    authz.ensure_permission_catalog(db.engine)
    rows = db_tx.execute(
        text("SELECT id FROM permissions WHERE id = ANY(:ids)"),
        {"ids": list(authz.ALL_PERMISSIONS)},
    ).fetchall()
    assert {r[0] for r in rows} == authz.ALL_PERMISSIONS


def test_ensure_permission_catalog_grants_nothing(db_tx) -> None:
    """Catalog seeding must never re-add a grant an operator revoked."""
    import db

    before = db_tx.execute(text("SELECT count(*) FROM role_permissions")).scalar()
    authz.ensure_permission_catalog(db.engine)
    after = db_tx.execute(text("SELECT count(*) FROM role_permissions")).scalar()
    assert before == after


# ---------------------------------------------------------------------------
# End-to-end through the real app
# ---------------------------------------------------------------------------


@pytest.fixture()
def gated_client(monkeypatch) -> TestClient:
    import actor_context
    import main as app_main

    monkeypatch.setenv("API_KEY", "authz-test-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    monkeypatch.delenv("AUTHZ_ENFORCE", raising=False)
    actor_context.reload_api_key_map()
    return TestClient(app_main.app)


def _hdr(actor: str) -> dict[str, str]:
    return {"X-API-Key": "authz-test-key", "X-Actor-User-Id": actor}


def test_agent_is_denied_an_integrations_route(gated_client: TestClient) -> None:
    res = gated_client.get("/webhook-endpoints", headers=_hdr("arjun-mehta"))
    assert res.status_code == 403, res.text
    assert authz.INTEGRATIONS_READ in res.text


def test_agent_is_denied_the_admin_route(gated_client: TestClient) -> None:
    res = gated_client.post("/tts-voices/catalog/sync", headers=_hdr("arjun-mehta"))
    assert res.status_code == 403, res.text


def test_agent_is_allowed_a_customers_route(gated_client: TestClient) -> None:
    res = gated_client.get("/staff", headers=_hdr("arjun-mehta"))
    assert res.status_code == 200, res.text


def test_roleless_actor_is_denied_everything_gated(gated_client: TestClient) -> None:
    res = gated_client.get("/staff", headers=_hdr("anita-rao"))
    assert res.status_code == 403, res.text


def test_admin_actor_passes(gated_client: TestClient) -> None:
    res = gated_client.get("/webhook-endpoints", headers=_hdr("priya-nair"))
    assert res.status_code == 200, res.text


def test_health_stays_public_under_enforcement(gated_client: TestClient) -> None:
    assert gated_client.get("/health").status_code == 200


def test_unauthenticated_still_401_not_403(gated_client: TestClient) -> None:
    """Authn runs before authz — a missing key must not surface as forbidden."""
    res = gated_client.get("/staff")
    assert res.status_code == 401, res.text


# ---------------------------------------------------------------------------
# Can each role actually do its job?
# ---------------------------------------------------------------------------
#
# Every test above this line asks whether the *mechanism* works: is the registry
# complete, does an unregistered route deny, does an explicit grant beat a
# default. All of them passed while the shipped configuration locked every
# non-admin user out of the product.
#
# The demo seed wrote six token grants across four roles. `authz` treats a
# role's explicit grants as authoritative — that is what makes revoking work —
# so those six were not a partial seed, they were a complete policy, and they
# replaced the built-in defaults. With enforcement on, a Supervisor could reach
# two things. Nothing caught it because the existing tests sampled one allowed
# route per role, and the ones they sampled happened to be covered.
#
# So: assert what each role is *for*, not that the resolver is sound.

#: The screens a role must be able to open to be useful. Not exhaustive — one
#: representative route per area of the job, chosen so that a regression in
#: grants shows up as a failure naming the role and the screen.
_ROLE_CORE_SCREENS = {
    "arjun-mehta": ("agent", ["/customers", "/promises", "/callbacks", "/calls", "/work-items"]),
    "david-chen": (
        "supervisor",
        ["/customers", "/promises", "/callbacks", "/calls", "/work-items", "/dashboard"],
    ),
    "priya-nair": ("admin", ["/customers", "/webhook-endpoints", "/dashboard"]),
}


@pytest.mark.parametrize("actor", sorted(_ROLE_CORE_SCREENS))
def test_role_can_open_its_own_screens(gated_client: TestClient, actor: str) -> None:
    role, paths = _ROLE_CORE_SCREENS[actor]
    denied = [
        path
        for path in paths
        if gated_client.get(path, headers=_hdr(actor)).status_code == 403
    ]
    assert not denied, (
        f"the {role} role is forbidden from {denied} — these are its own "
        "screens. Check role_permissions: an incomplete set of explicit grants "
        "silently replaces the built-in defaults rather than extending them."
    )


@pytest.mark.parametrize(
    "role_id,role_key",
    [
        ("role-agent", "agent"),
        ("role-supervisor", "supervisor"),
        ("role-admin", "admin"),
        ("role-qa", "qa_reviewer"),
    ],
)
def test_stock_role_grants_cover_the_built_in_defaults(db_tx, role_id, role_key) -> None:
    """The shipped grants must be at least the defaults they stand in for.

    Backfilled by migration 20260812_0064 and seeded from `authz.ROLE_DEFAULTS`
    thereafter, so the seeder and the resolver can no longer disagree about what
    a stock role means.
    """
    granted = {
        row[0]
        for row in db_tx.execute(
            text("SELECT permission_id FROM role_permissions WHERE role_id = :r"),
            {"r": role_id},
        )
    }
    if not granted:
        pytest.skip(f"{role_id} not present in this database")
    missing = set(authz.ROLE_DEFAULTS[role_key]) - granted
    assert not missing, f"{role_id} is missing {sorted(missing)}"


def test_reading_the_work_queue_does_not_require_a_write_permission() -> None:
    """`GET /work-items` required WORKQUEUE_WRITE.

    Wrong in both directions: an oversight role could not open the screen it
    oversees, and anyone who could open it could also claim from it.
    """
    assert authz.ROUTE_PERMISSIONS[("GET", "/work-items")] == authz.COLLECTIONS_READ


def test_no_read_route_requires_a_write_permission() -> None:
    """The general form of the bug above."""
    offenders = [
        (method, path)
        for (method, path), permission in authz.ROUTE_PERMISSIONS.items()
        if method == "GET" and permission.endswith("-write")
    ]
    assert not offenders, (
        f"GET routes gated on a write permission: {sorted(offenders)}. A read "
        "should not require the right to mutate."
    )


def test_agent_cannot_publish_an_agent_card(gated_client: TestClient) -> None:
    """agent.publish is not on the floor-agent role — 403, not a silent publish."""
    res = gated_client.post(
        "/prompt-versions/v1_4/publish",
        headers=_hdr("arjun-mehta"),
        json={"summary": "should not ship"},
    )
    assert res.status_code == 403, res.text
    assert authz.AGENT_PUBLISH in res.text
