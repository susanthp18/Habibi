"""Per-route authorization.

The load-bearing test here is :func:`test_registry_covers_every_route`. Before
authz existed, exactly one of ~180 routes was gated; the failure mode being
locked shut is not "this route is wrong" but "somebody added a route and nobody
noticed it was ungated".
"""

from __future__ import annotations

import re

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


# Authenticated, not API-key-exempt: any actor may read their own row.
_SELF_SCOPED_PUBLIC = frozenset(
    {
        ("GET", "/me"),
        ("GET", "/me/presence"),
        ("PATCH", "/me/presence"),
    }
)
# ApiKeyMiddleware special-cases POST /a2a before the prefix list.
_MIDDLEWARE_SPECIAL_CASED = frozenset({("POST", "/a2a")})
# Only present in _AUTH_EXEMPT_PREFIXES when the embedded voice host is on.
_CONDITIONAL_ON_EMBEDDED_HOST = frozenset(
    {
        ("POST", "/api/offer"),
        ("PATCH", "/api/offer"),
        ("POST", "/voice-rtc/api/offer"),
        ("PATCH", "/voice-rtc/api/offer"),
    }
)


def _instantiate_path_template(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def _matches_exempt_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    concrete = _instantiate_path_template(path)
    return any(concrete == p or concrete.startswith(p + "/") for p in prefixes)


def test_public_signature_routes_are_api_key_exempt() -> None:
    """``PUBLIC_ROUTES`` and ``_AUTH_EXEMPT_PREFIXES`` are one policy.

    They used to disagree on ``POST /twilio/sms/status`` and
    ``POST /webhooks/collections/payment-events``: the handler HMAC never
    ran because ApiKeyMiddleware 401'd first.
    """
    import main as app_main

    prefixes = app_main._AUTH_EXEMPT_PREFIXES
    missing: list[str] = []
    leaked: list[str] = []
    for method, path in sorted(authz.PUBLIC_ROUTES):
        key = (method, path)
        exempt = _matches_exempt_prefix(path, prefixes)
        if key in _SELF_SCOPED_PUBLIC:
            if exempt:
                leaked.append(f"{method} {path}")
            continue
        if key in _MIDDLEWARE_SPECIAL_CASED:
            continue
        if key in _CONDITIONAL_ON_EMBEDDED_HOST and not app_main._EMBEDDED_VOICE_HOST:
            continue
        if not exempt:
            missing.append(f"{method} {path}")
    assert missing == [], f"PUBLIC_ROUTES not API-key exempt: {missing}"
    assert leaked == [], f"self-scoped /me routes must still require a key: {leaked}"


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


def test_viewer_can_read_the_demo_book_but_cannot_write() -> None:
    perms = authz.ROLE_DEFAULTS["viewer"]
    for needed in (
        authz.CUSTOMERS_READ,
        authz.CUSTOMERS_READ_ALL,
        authz.INTERACTIONS_READ,
        authz.COLLECTIONS_READ,
        authz.ANALYTICS_READ,
        authz.BOT_READ,
        authz.SUPERVISOR_READ,
    ):
        assert needed in perms, needed
    for forbidden in (
        authz.COLLECTIONS_WRITE,
        authz.CUSTOMERS_WRITE,
        authz.BOT_WRITE,
        authz.VOICE_OPERATE,
        authz.ADMIN_WRITE,
    ):
        assert forbidden not in perms, forbidden


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
    monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
    monkeypatch.delenv("ENTRA_API_AUDIENCE", raising=False)
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
    monkeypatch.setenv("AUTHZ_ENFORCE", "on")
    assert authz.enforcement_enabled() is True
    monkeypatch.setenv("API_KEY", "some-key")
    monkeypatch.setenv("AUTHZ_ENFORCE", "0")
    assert authz.enforcement_enabled() is False
    monkeypatch.setenv("AUTHZ_ENFORCE", "off")
    assert authz.enforcement_enabled() is False


def test_unrecognised_enforce_follows_credentials(monkeypatch) -> None:
    """A typo must not disable the gate the way omitting ``on`` disabled TLS.

    Unset, blank, and unrecognised all use the credential default. Treating a
    set-but-unknown value as false would leave a production boot with
    ``API_KEY`` ungated.
    """
    import actor_context

    monkeypatch.setenv("API_KEY", "some-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
    monkeypatch.delenv("ENTRA_API_AUDIENCE", raising=False)
    actor_context.reload_api_key_map()
    monkeypatch.setenv("AUTHZ_ENFORCE", "banana")
    assert authz.enforcement_enabled() is True
    monkeypatch.delenv("API_KEY")
    actor_context.reload_api_key_map()
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


def test_resolve_role_grants_empty_unconfigured_falls_back_to_defaults() -> None:
    assert authz.resolve_role_grants(
        "Supervisor", [], configured=False
    ) == authz.ROLE_DEFAULTS["supervisor"]
    assert authz.VOICE_OPERATE in authz.resolve_role_grants(
        "Supervisor", [], configured=False
    )


def test_resolve_role_grants_empty_configured_is_empty() -> None:
    """The case ``test_explicit_grant_beats_default_so_revocation_works`` missed."""
    assert authz.resolve_role_grants("Supervisor", [], configured=True) == frozenset()
    assert authz.VOICE_OPERATE not in authz.resolve_role_grants(
        "Supervisor", [], configured=True
    )


def test_resolve_role_grants_admin_by_name_is_still_superuser() -> None:
    assert authz.resolve_role_grants("Admin", [], configured=True) == authz.ALL_PERMISSIONS


def test_revoking_every_grant_leaves_the_role_empty(db_tx) -> None:
    """Total revocation is not 'never configured' — the role stays empty.

    The previous test granted one permission and asserted a second was absent.
    An operator who unticks the last box sends ``[]``, and that path used to
    restore the full default set.
    """
    import db

    tenant = db.TENANT_ID
    db_tx.execute(
        text(
            "INSERT INTO roles (id, tenant_id, name) "
            "VALUES ('role-tmp-sup-empty', :t, 'Supervisor')"
        ),
        {"t": tenant},
    )
    db_tx.execute(
        text(
            "INSERT INTO user_roles (user_id, role_id) "
            "VALUES ('anita-rao', 'role-tmp-sup-empty')"
        )
    )
    authz.invalidate_permission_cache("anita-rao")
    assert authz.VOICE_OPERATE in authz.actor_permissions("anita-rao")

    result = db.replace_role_permissions("role-tmp-sup-empty", [])
    assert result["permissionIds"] == []
    configured_at = db_tx.execute(
        text("SELECT configured_at FROM roles WHERE id = 'role-tmp-sup-empty'")
    ).scalar()
    assert configured_at is not None
    remaining = db_tx.execute(
        text("SELECT count(*) FROM role_permissions WHERE role_id = 'role-tmp-sup-empty'")
    ).scalar()
    assert remaining == 0
    # No extra invalidate — replace_role_permissions must have dropped the cache
    # or this would still see the default set for up to AUTHZ_CACHE_TTL_S.
    perms = authz.actor_permissions("anita-rao")
    assert perms == frozenset()
    assert authz.VOICE_OPERATE not in perms


def test_total_revocation_of_supervisor_denies_voice_operate_on_the_next_request(
    db_tx,
) -> None:
    """Acceptance: strip role-supervisor; a holder loses VOICE_OPERATE immediately."""
    import db

    if db_tx.execute(text("SELECT 1 FROM roles WHERE id = 'role-supervisor'")).scalar() is None:
        pytest.skip("role-supervisor not present in this database")
    if db_tx.execute(text("SELECT 1 FROM users WHERE id = 'david-chen'")).scalar() is None:
        pytest.skip("david-chen not present in this database")

    assert authz.has_permission("david-chen", authz.VOICE_OPERATE)
    db.replace_role_permissions("role-supervisor", [])
    assert not authz.has_permission("david-chen", authz.VOICE_OPERATE)


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

    # The first run may *remove* grants on a retired permission; it never adds.
    authz.ensure_permission_catalog(db.engine)
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
        ("role-compliance-officer", "compliance_officer"),
        ("role-dpo", "dpo"),
        ("role-viewer", "viewer"),
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
    # Listing operators is an admin action. There is no perm-admin-read, so
    # the same grant that may change people is the one that may see them.
    admin_gets = {("GET", "/users"), ("GET", "/roles"), ("GET", "/invites")}
    offenders = [
        (method, path)
        for (method, path), permission in authz.ROUTE_PERMISSIONS.items()
        if method == "GET"
        and permission.endswith("-write")
        and (method, path) not in admin_gets
    ]
    assert not offenders, (
        f"GET routes gated on a write permission: {sorted(offenders)}. A read "
        "should not require the right to mutate."
    )
    assert authz.ROUTE_PERMISSIONS[("GET", "/users")] == authz.ADMIN_WRITE
    assert authz.ROUTE_PERMISSIONS[("GET", "/roles")] == authz.ADMIN_WRITE
    assert authz.ROUTE_PERMISSIONS[("GET", "/invites")] == authz.ADMIN_WRITE


def test_deployment_rollback_requires_agent_publish() -> None:
    assert authz.ROUTE_PERMISSIONS[("POST", "/bot-deployments/{deployment_id}/rollback")] == authz.AGENT_PUBLISH
    assert (
        authz.ROUTE_PERMISSIONS[("POST", "/bot-deployments/experiments/{experiment_id}/rollback")]
        == authz.AGENT_PUBLISH
    )


@pytest.mark.parametrize(
    "route",
    [
        ("POST", "/prompt-versions/{version_id}/publish"),
        ("POST", "/agent-studio/cards/{bot_id}/publish"),
        # Archive retires the live production deployment: the inverse of
        # publishing. It used to sit on AGENT_EDIT, so an editor could take a
        # shipped agent off the air.
        ("POST", "/agent-studio/cards/{bot_id}/archive"),
        # Entry bindings decide which card answers the phone.
        ("PUT", "/agent-studio/entry-bindings"),
        ("DELETE", "/agent-studio/entry-bindings/{binding_id}"),
    ],
)
def test_every_route_that_changes_what_ships_requires_agent_publish(route) -> None:
    assert authz.ROUTE_PERMISSIONS[route] == authz.AGENT_PUBLISH, route


def test_restore_is_an_edit_because_it_does_not_redeploy() -> None:
    assert authz.ROUTE_PERMISSIONS[("POST", "/agent-studio/cards/{bot_id}/restore")] == authz.AGENT_EDIT


def test_agent_cannot_publish_an_agent_card(gated_client: TestClient) -> None:
    """agent.publish is not on the floor-agent role — 403, not a silent publish."""
    res = gated_client.post(
        "/prompt-versions/v1_4/publish",
        headers=_hdr("arjun-mehta"),
        json={"summary": "should not ship"},
    )
    assert res.status_code == 403, res.text
    assert authz.AGENT_PUBLISH in res.text


def test_get_roles_reports_resolved_grants_not_raw_rows(
    db_tx, gated_client: TestClient
) -> None:
    """The Roles screen and the enforcer cannot disagree about an empty role."""
    import db

    tenant = db.TENANT_ID
    db_tx.execute(
        text(
            "INSERT INTO roles (id, tenant_id, name) "
            "VALUES ('role-tmp-unconf', :t, 'QA Reviewer')"
        ),
        {"t": tenant},
    )
    catalog = gated_client.get("/roles", headers=_hdr("priya-nair")).json()
    unconf = next(r for r in catalog["roles"] if r["id"] == "role-tmp-unconf")
    assert set(unconf["permissionIds"]) == set(authz.ROLE_DEFAULTS["qa_reviewer"])

    if db_tx.execute(text("SELECT 1 FROM roles WHERE id = 'role-supervisor'")).scalar() is None:
        pytest.skip("role-supervisor not present in this database")

    db.replace_role_permissions("role-supervisor", [])
    catalog = gated_client.get("/roles", headers=_hdr("priya-nair")).json()
    supervisor = next(r for r in catalog["roles"] if r["id"] == "role-supervisor")
    assert supervisor["permissionIds"] == []
    assert [
        g["permission_id"] for g in catalog["grants"] if g["role_id"] == "role-supervisor"
    ] == []

    denied = gated_client.post(
        "/voice/sandbox/start",
        headers=_hdr("david-chen"),
        json={},
    )
    assert denied.status_code == 403, denied.text
    assert authz.VOICE_OPERATE in denied.text


def test_actor_is_admin_is_the_route_guards_reading(db_tx, monkeypatch) -> None:
    """db.actor_is_admin used to restate superuser-ness with its own SQL (an
    admin-named role OR perm-admin-write), so the Redaction Hub and the route
    guard could disagree about who is admin. One reading now: authz."""
    import db

    monkeypatch.setattr(authz, "has_permission", lambda uid, perm: perm == authz.ADMIN_WRITE and uid == "u-1")
    assert db.actor_is_admin("u-1") is True
    assert db.actor_is_admin("u-2") is False
    assert db.actor_is_admin("") is False


# ---------------------------------------------------------------------------
# Every gated route refuses an actor without its permission (P5-34)
# ---------------------------------------------------------------------------
#
# The five spot checks above prove the gate on five routes. This walks the
# registry: every (method, path) it names, called as the seeded actor who holds
# no role at all, is 403 and the body names the permission that was missing.
# The gate runs on the route template before the handler, so the path
# parameters are placeholders and no row is read.


@pytest.mark.parametrize(
    "method,path", sorted(authz.ROUTE_PERMISSIONS), ids=lambda v: v if isinstance(v, str) else str(v)
)
def test_every_gated_route_refuses_a_roleless_actor(
    gated_client: TestClient, method: str, path: str
) -> None:
    concrete = re.sub(r"\{[^}]+\}", "placeholder", path)
    res = gated_client.request(method, concrete, headers=_hdr("anita-rao"))
    assert res.status_code == 403, f"{method} {path}: {res.status_code} {res.text[:200]}"
    assert authz.ROUTE_PERMISSIONS[(method, path)] in res.text


def test_a_logged_interaction_is_attributed_to_the_actor_not_the_body(gated_client) -> None:
    """`POST /interactions` accepted `handlerUserId` from the body, so any
    caller could log an interaction as somebody else. The handler is the
    acting user; a body that names one is refused as an unknown field."""
    res = gated_client.post(
        "/interactions",
        json={"customerId": "CL-100023", "handlerUserId": "arjun-mehta", "summary": "x"},
        headers=_hdr("priya-nair"),
    )
    assert res.status_code == 422, res.text
    assert "handlerUserId" in res.text


def test_provider_bindings_are_read_by_bot_read_and_written_by_admin(
    gated_client: TestClient, db_tx
) -> None:
    """The three /providers/bindings routes had no HTTP test at all (BINDINGS-13):
    an agent is refused the list (BOT_READ), a supervisor may read it, only an
    admin may write, and a write round-trips."""
    from sqlalchemy import text

    assert gated_client.get("/providers/bindings", headers=_hdr("arjun-mehta")).status_code == 403
    res = gated_client.get("/providers/bindings", headers=_hdr("david-chen"))
    assert res.status_code == 200, res.text
    model = db_tx.execute(text("SELECT id FROM provider_models WHERE kind = 'stt' LIMIT 1")).scalar()
    if model is None:
        pytest.skip("no provider model seeded")
    body = {"slot": "stt", "providerModelId": model, "locale": "hi-IN", "priority": 900}
    denied = gated_client.post("/providers/bindings", json=body, headers=_hdr("david-chen"))
    assert denied.status_code == 403, denied.text
    created = gated_client.post("/providers/bindings", json=body, headers=_hdr("priya-nair"))
    assert created.status_code == 200, created.text
    binding_id = created.json()["id"]
    try:
        listed = gated_client.get("/providers/bindings", headers=_hdr("david-chen")).json()
        assert any(b["id"] == binding_id for b in listed)
    finally:
        gone = gated_client.delete(f"/providers/bindings/{binding_id}", headers=_hdr("priya-nair"))
        assert gone.status_code == 200, gone.text
