"""/ready pool headroom → 503 when exhausted."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    import main as app_main

    return TestClient(app_main.app)


def test_ready_503_when_pool_exhausted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import db

    monkeypatch.setattr(
        db,
        "pool_snapshot",
        lambda: {
            "poolSize": 5,
            "maxOverflow": 10,
            "capacity": 15,
            "checkedOut": 15,
            "overflow": 10,
            "available": 0,
            "statementTimeoutMs": 15000,
            "poolRecycle": 1800,
        },
    )
    # readiness reads pool_snapshot — also stub MinIO ping to stay green.
    import storage

    monkeypatch.setattr(
        storage, "ping", lambda: {"configured": False, "ok": True}
    )

    res = client.get("/ready")
    assert res.status_code == 503, res.text
    body = res.json()
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
    assert detail.get("detail") == "pool_exhausted" or detail.get("ok") is False
    assert detail.get("pool", {}).get("available") == 0


def test_ready_200_when_pool_has_headroom(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import db
    import storage

    monkeypatch.setattr(
        db,
        "pool_snapshot",
        lambda: {
            "poolSize": 5,
            "maxOverflow": 10,
            "capacity": 15,
            "checkedOut": 2,
            "overflow": 0,
            "available": 13,
            "statementTimeoutMs": 15000,
            "poolRecycle": 1800,
        },
    )
    monkeypatch.setattr(
        storage, "ping", lambda: {"configured": False, "ok": True}
    )
    # readiness still pings DB — leave real SELECT 1.

    res = client.get("/ready")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("ok") is True
    assert body["pool"]["available"] == 13
    assert "circuits" in body
