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


def test_a_fifty_percent_canary_serves_half(monkeypatch) -> None:
    """SHIP-08: `digest[0] % 100` put 256 values into 100 buckets, so 0-55
    held three each and 56-99 two: a 50% split routed ~59% to the canary."""
    from agent_core.canary import pick_deployment_id

    monkeypatch.setattr(db, "get_active_deployment", lambda **_k: {"id": "DEP-ACTIVE"})
    monkeypatch.setattr(
        "agent_core.canary.running_experiment",
        lambda *_a, **_k: {
            "id": "EXP-1",
            "canary_deployment_id": "DEP-CANARY",
            "baseline_deployment_id": "DEP-BASE",
            "traffic_pct": 50,
            "shadow": False,
        },
    )
    picks = Counter(pick_deployment_id("kaia-v2-4", customer_id=f"cust-{i}") for i in range(4000))
    share = picks["DEP-CANARY"] / 4000
    assert 0.47 < share < 0.53, share


def test_the_rollback_sweep_reaches_every_tenant(db_tx, monkeypatch) -> None:
    """AUTHZ-17: `sweep_rollbacks` read `deployment_experiments` under the
    worker's own tenant, so a canary another tenant was running rolled back
    never."""
    from agent_core import canary

    db_tx.execute(
        text("INSERT INTO tenants (id, name) VALUES (:t, 'Rival') ON CONFLICT (id) DO NOTHING"),
        {"t": OTHER},
    )
    seen: list[str] = []

    def _per_tenant() -> bool:
        seen.append(db.current_tenant())
        return False

    monkeypatch.setattr(canary, "_sweep_tenant_rollbacks", _per_tenant)
    canary.sweep_rollbacks()
    assert OTHER in seen
    assert db.current_tenant() in seen


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


def test_tenant_wide_reports_are_a_server_side_filter(db_tx) -> None:
    """EVALS-19: the Evals tab found the scheduler's bot-less runs by filtering
    a shared page of fifty client-side, so fifty newer card-scoped reports
    hid them. `botId=__none__` asks for exactly those rows."""
    import db_inbox

    suite = db_tx.execute(text("SELECT id FROM eval_suites LIMIT 1")).scalar()
    if suite is None:
        pytest.skip("no eval suites seeded")
    db.save_eval_report(suite_id=suite, bot_id=None, status="pass", summary={"failed": 0, "total": 1})
    db.save_eval_report(suite_id=suite, bot_id="kaia-v2-4", status="pass", summary={"failed": 0, "total": 1})
    rows = db.list_eval_reports(bot_id=db_inbox.TENANT_WIDE_REPORTS, limit=5)
    assert rows and all(r.get("botId") is None for r in rows)
