"""Agent Studio MINOR cluster 1: the authz, tenant and audit holes.

Each test names the hole it closes. They were MINOR because none was a route
missing its guard -- the guard was there and the thing behind it was not:
a revoke that said done for a key it never touched, a sweep bound to one
tenant, a split that served 59% on a 50% canary, a `/me` with no permissions
for the shell to read.
"""

from __future__ import annotations

from collections import Counter

import pytest
from sqlalchemy import text

import authz
import db

OTHER = "rival.bank"


def test_revoking_a_key_that_is_not_there_is_not_success(db_tx) -> None:
    """AUTHZ-12: `revoke_key` ran an UPDATE and returned. A typo'd id was
    200 -- the leaked key kept working and the operator was told otherwise."""
    from agent_core.mcp_http.auth import revoke_key

    with pytest.raises(KeyError):
        revoke_key("mcpk-no-such-key")


def test_me_carries_the_permissions_the_routes_enforce(db_tx) -> None:
    """AUTHZ-8: the shell had to guess what the actor may do; it now reads
    the same set `authz.require` checks."""
    me = db.get_current_user()
    assert set(me["permissions"]) == authz.actor_permissions(me["id"])
    from schemas import MeResponse

    assert MeResponse(**me).permissions == sorted(authz.actor_permissions(me["id"]))


def test_the_orphan_permission_is_gone(db_tx) -> None:
    """AUTHZ-14: `perm-redteam-run` guarded no route. A permission nothing
    checks is a grant screen lying about what it grants."""
    assert not hasattr(authz, "REDTEAM_RUN")
    assert "perm-redteam-run" not in authz.ALL_PERMISSIONS
    authz.ensure_permission_catalog(db.engine)
    left = db_tx.execute(
        text("SELECT count(*) FROM permissions WHERE id = 'perm-redteam-run'")
    ).scalar()
    assert left == 0


def test_a_shared_api_key_with_no_map_does_not_boot_in_prod(monkeypatch) -> None:
    """AUTHZ-13: one API_KEY and no API_KEY_MAP audits every caller as
    ACTOR_USER_ID. Fine on a laptop; in production it is a forged trail."""
    import actor_context

    monkeypatch.setattr(actor_context, "_user_exists", lambda _uid: True)
    monkeypatch.setattr(actor_context, "_api_key_map_cache", {})
    monkeypatch.setenv("API_KEY", "one-key-for-everyone")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.delenv("ALLOW_ACTOR_HEADER", raising=False)
    monkeypatch.setenv("APP_ENV", "prod")
    with pytest.raises(RuntimeError, match="API_KEY_MAP"):
        actor_context.validate_configured_actors()
    monkeypatch.setenv("APP_ENV", "dev")
    actor_context.validate_configured_actors()


