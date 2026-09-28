"""Wave 3: outbound last-4 prefer, CTX fail-closed, embedded admission, AMD skip."""

from __future__ import annotations


def test_lookup_prefers_bound_customer_when_tail_collides(monkeypatch) -> None:
    from voice import persist

    preferred = {
        "customer_id": "C-BOUND",
        "name": "Asha",
        "phone_primary": "9876543210",
        "account_id": "AC-1",
        "outstanding": 100,
        "minimum_due": 10,
        "dpd": 5,
    }
    captured: list[dict] = []

    class _Maps:
        def __init__(self, row):
            self._row = row

        def first(self):
            return self._row

        def all(self):
            return [self._row, {**self._row, "customer_id": "C-OTHER"}]

    class _Result:
        def __init__(self, row):
            self._row = row

        def mappings(self):
            return _Maps(self._row)

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, _sql, params):
            captured.append(dict(params))
            if params.get("prefer") == "C-BOUND":
                return _Result(preferred)
            return _Result(None)

    monkeypatch.setattr("db.engine.connect", lambda: _Conn())
    monkeypatch.setattr("db.current_tenant", lambda: "hdfc.retail")
    monkeypatch.setattr("db._find_customer_by_phone", lambda *_a, **_k: None)
    found = persist.lookup_customer_for_verify(
        method="phone_match",
        value="3210",
        prefer_customer_id="C-BOUND",
    )
    assert found is not None
    assert found["customerId"] == "C-BOUND"
    assert any(p.get("prefer") == "C-BOUND" for p in captured)


def test_inbound_last4_collision_still_refuses(monkeypatch) -> None:
    from voice import persist

    row = {
        "customer_id": "C1",
        "name": "A",
        "phone_primary": "11113210",
        "account_id": "AC-1",
        "outstanding": 1,
        "minimum_due": 1,
        "dpd": 1,
    }

    class _Maps:
        def first(self):
            return None

        def all(self):
            return [row, {**row, "customer_id": "C2"}]

    class _Result:
        def mappings(self):
            return _Maps()

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *_a, **_k):
            return _Result()

    monkeypatch.setattr("db.engine.connect", lambda: _Conn())
    monkeypatch.setattr("db.current_tenant", lambda: "hdfc.retail")
    monkeypatch.setattr("db._find_customer_by_phone", lambda *_a, **_k: None)
    found = persist.lookup_customer_for_verify(method="phone_match", value="3210")
    assert found is None
