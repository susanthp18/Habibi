"""The four small routes whose transactions moved out of the router still
answer: roles catalog, platform switches, one eval report, hourly reach."""

from __future__ import annotations

import pytest


@pytest.fixture()
def client(monkeypatch, db_tx):
    from fastapi.testclient import TestClient

    import actor_context
    import main as app_main

    monkeypatch.setenv("API_KEY", "peeled-routes-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    actor_context.reload_api_key_map()
    return TestClient(app_main.app)


HEADERS = {"X-API-Key": "peeled-routes-key", "X-Actor-User-Id": "priya-nair"}


def test_roles_catalog_resolves_grants(client) -> None:
    body = client.get("/roles", headers=HEADERS).json()
    assert {"permissions", "agentPublishRoles", "grants", "roles"} <= set(body)
    admin = next((r for r in body["roles"] if r["name"].lower() == "admin"), None)
    assert admin is not None and "perm-admin-write" in admin["permissionIds"]


def test_platform_switches_list_and_flip(client, db_tx) -> None:
    import platform_switches

    listed = client.get("/platform/switches", headers=HEADERS).json()["switches"]
    keys = {s["key"] for s in listed}
    assert platform_switches.OUTBOUND_ENABLED in keys
    res = client.patch(
        f"/platform/switches/{platform_switches.DEMO_IGNORES_WINDOW}",
        headers=HEADERS,
        json={"enabled": True, "note": "http test"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["enabled"] is True
    assert client.patch("/platform/switches/no-such-switch", headers=HEADERS, json={"enabled": True}).status_code == 404
    platform_switches.invalidate()


def test_eval_report_read_is_tenant_scoped(client, db_tx) -> None:
    import db
    from sqlalchemy import text

    assert client.get("/eval/reports/no-such-report", headers=HEADERS).status_code == 404
    suite = db_tx.execute(text("SELECT id FROM eval_suites LIMIT 1")).scalar()
    if suite is None:
        pytest.skip("no eval suites seeded")
    saved = db.save_eval_report(suite_id=suite, bot_id=None, status="pass", summary={"failed": 0, "total": 1})
    res = client.get(f"/eval/reports/{saved['id']}", headers=HEADERS)
    assert res.status_code == 200, res.text
    assert res.json()["id"] == saved["id"]


def test_hourly_reach_answers_for_a_customer(client, db_tx) -> None:
    import db
    from sqlalchemy import text

    cid = db_tx.execute(
        text("SELECT id FROM customers WHERE tenant_id = :t AND id <> 'UNKNOWN-CALLER' LIMIT 1"),
        {"t": db.current_tenant()},
    ).scalar()
    if cid is None:
        pytest.skip("no customers seeded")
    res = client.get(f"/customers/{cid}/outbound/hours", headers=HEADERS)
    assert res.status_code == 200, res.text
    assert isinstance(res.json(), list)
