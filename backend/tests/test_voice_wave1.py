"""Wave-1 compliance floor: direction, redaction, holds, identity, inbox label."""

from __future__ import annotations

from unittest.mock import MagicMock


def test_suppress_upsell_inserts_no_upsell_kind() -> None:
    import post_call_actions

    captured: dict = {}

    class _Conn:
        def execute(self, sql, params):
            captured["sql"] = str(sql)
            captured["params"] = params
            return MagicMock()

    ctx = {
        "conn": _Conn(),
        "attempt": {"tenant_id": "t", "customer_id": "c", "interaction_id": None},
        "business": "hardship_declared",
    }
    post_call_actions._suppress_upsell(ctx, "90d")
    assert captured["params"]["kind"] == "no_upsell"
    assert captured["params"]["reason"] == "hardship_declared"


def test_media_for_interaction_keeps_newest_audio(monkeypatch) -> None:
    from voice import recordings

    rows = [
        {"id": "new", "kind": "audio", "storage_ref": "new.wav", "created_at": 2},
        {"id": "old", "kind": "audio", "storage_ref": "old.wav", "created_at": 1},
    ]

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *_a, **_k):
            return rows

    monkeypatch.setattr("db.engine.connect", lambda: _Conn())
    monkeypatch.setattr("db._rows", lambda result: result)
    monkeypatch.setattr("db.current_tenant", lambda: "hdfc.retail")
    picked = recordings.media_for_interaction("CL-1", variant="original")
    assert picked is not None
    assert picked["id"] == "new"


def test_resolve_known_customer_is_tenant_scoped(monkeypatch) -> None:
    from voice import persist

    captured: list[dict] = []

    class _Result:
        def scalar(self):
            return None

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, _sql, params):
            captured.append(dict(params))
            return _Result()

    monkeypatch.setattr("db.engine.connect", lambda: _Conn())
    monkeypatch.setattr("db.current_tenant", lambda: "hdfc.retail")
    assert persist.resolve_known_customer("C-1") is None
    assert captured == [{"id": "C-1", "tenant": "hdfc.retail"}]
