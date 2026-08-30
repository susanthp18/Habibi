"""Two reads in the connector subtree that were wrong in different ways.

The first is a cost: ``bound_tool_names`` ran ``SELECT * FROM mcp_connectors``
twice back to back — once to index by id, once to index by slug — on the card
compile path, which is called per compile and per dry-run.

The second is a leak. ``first_party.paylink_status`` filtered on
``customer_id`` alone. RLS is opt-in and the app connects as BYPASSRLS, so a
customer id belonging to another tenant returned that tenant's payment status,
while every neighbouring read (``lms_balance`` via ``db.get_customer``) is
tenant-scoped.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db
import tenant_context
from agent_core.connectors import persist as connectors_persist
from agent_core.connectors.first_party import paylink_status

APPROVED_PAYLINK = {
    "id": "conn-t1-paylink",
    "slug": "paylink",
    "status": "approved",
    "kind": "first_party",
    "allowPrefixes": ["ext.paylink."],
    "toolsCache": [],
}


def test_bound_tool_names_reads_the_registry_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both indexes are built from one read."""
    monkeypatch.setenv("MCP_CLIENT_ENABLED", "true")
    calls: list[int] = []

    def _counted() -> list[dict]:
        calls.append(1)
        return [dict(APPROVED_PAYLINK)]

    monkeypatch.setattr(connectors_persist, "list_connectors", _counted)

    names = connectors_persist.bound_tool_names([{"connector_id": "conn-t1-paylink"}])

    assert names == ["ext.paylink.get_status"]
    assert len(calls) == 1, f"registry read {len(calls)} times for one bind"


def test_bound_tool_names_still_resolves_a_connector_by_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The slug index is not collateral damage of dropping the second query."""
    monkeypatch.setenv("MCP_CLIENT_ENABLED", "true")
    monkeypatch.setattr(
        connectors_persist, "list_connectors", lambda: [dict(APPROVED_PAYLINK)]
    )

    assert connectors_persist.bound_tool_names([{"connector_id": "paylink"}]) == [
        "ext.paylink.get_status"
    ]


# ---------------------------------------------------------------------------
# paylink_status is tenant-scoped
# ---------------------------------------------------------------------------


def _product(db_tx) -> str:
    product = db_tx.execute(text("SELECT id FROM products LIMIT 1")).scalar()
    if not product:
        pytest.skip("no products seeded")
    return str(product)


def _customer_with_paid_intent(db_tx, tenant_id: str) -> str:
    """A customer, an account and one paid pay-link, all under ``tenant_id``."""
    suffix = uuid.uuid4().hex[:10]
    customer_id = f"CUST-XT-{suffix}"
    account_id = f"ACC-XT-{suffix}"
    db_tx.execute(
        text("INSERT INTO tenants (id, name) VALUES (:t, :t) ON CONFLICT DO NOTHING"),
        {"t": tenant_id},
    )
    db_tx.execute(
        text(
            """
            INSERT INTO customers (id, tenant_id, name, risk)
            VALUES (:id, :t, 'Cross Tenant Probe', 'low')
            """
        ),
        {"id": customer_id, "t": tenant_id},
    )
    db_tx.execute(
        text(
            """
            INSERT INTO accounts (id, customer_id, product_id, outstanding)
            VALUES (:id, :cid, :pid, 1000.00)
            """
        ),
        {"id": account_id, "cid": customer_id, "pid": _product(db_tx)},
    )
    db_tx.execute(
        text(
            """
            INSERT INTO payment_intents (
              id, tenant_id, customer_id, account_id, amount, public_token,
              status, paid_at, provider_ref
            ) VALUES (
              :id, :t, :cid, :aid, 250.00, :tok, 'paid', now(), 'upi-ok'
            )
            """
        ),
        {
            "id": f"pi-xt-{suffix}",
            "t": tenant_id,
            "cid": customer_id,
            "aid": account_id,
            "tok": f"tok-{uuid.uuid4().hex}",
        },
    )
    return customer_id


def test_paylink_status_hides_another_tenants_customer(db_tx) -> None:
    """The leak: a cross-tenant customer id answered with real payment status."""
    other = f"xt-{uuid.uuid4().hex[:8]}"
    foreign_customer = _customer_with_paid_intent(db_tx, other)

    unknown = paylink_status(f"CUST-NOPE-{uuid.uuid4().hex[:8]}")
    leaked = paylink_status(foreign_customer)

    assert unknown == {"ok": True, "status": "none"}
    assert leaked == unknown, "another tenant's payment status crossed the boundary"


def test_paylink_status_still_answers_for_the_owning_tenant(db_tx) -> None:
    """The other half — a predicate that hides everything would pass the test above."""
    other = f"xt-{uuid.uuid4().hex[:8]}"
    foreign_customer = _customer_with_paid_intent(db_tx, other)

    with tenant_context.bind(other):
        mine = paylink_status(foreign_customer)

    assert mine["ok"] is True
    assert mine["status"] == "paid"
    assert mine["providerRef"] == "upi-ok"


def test_paylink_status_reads_the_callers_own_tenant(db_tx) -> None:
    """Same-tenant read, from the default tenant the suite runs as."""
    own_customer = _customer_with_paid_intent(db_tx, db.current_tenant())

    out = paylink_status(own_customer)

    assert out["status"] == "paid"
    assert out["say"] == "We see the UPI success."
