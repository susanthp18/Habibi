"""The connector registry is the only door — including for first-party tools.

Two defects live here, and they share a cause: something reached past the
registry.

The first is a read. ``get_customer_context`` called
``first_party.paylink_status`` directly behind nothing but the
``MCP_CLIENT_ENABLED`` flag, while the sanctioned path
(``bot_tools.execute_tool`` -> ``connectors.persist.dispatch``) checks that the
connector is ``approved`` and that its circuit is closed. A connector left in
draft, or disabled after an incident, therefore kept feeding payment status
into every context card the bot built. Routing the read through ``dispatch``
only helps if ``dispatch`` actually gates first-party tools, which it did not —
it answered them above the status check — so both halves are asserted below.

The second is a write. ``mcp_connectors.id`` is the PRIMARY KEY but the
registry's real uniqueness is ``(tenant_id, slug)``, and the default id was
``conn-{slug}``. The second tenant to register "paylink" collided on the PK,
which ``ON CONFLICT (tenant_id, slug)`` cannot absorb, so the POST 500'd.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db
import tenant_context

PAYLINK_TOOL = "ext.paylink.get_status"


def _customer(db_tx) -> tuple[str, str | None]:
    row = db_tx.execute(
        text(
            """
            SELECT c.id, a.id AS account_id
              FROM customers c
              LEFT JOIN accounts a ON a.customer_id = c.id
             WHERE c.id <> 'UNKNOWN-CALLER' AND c.tenant_id = :t
             ORDER BY c.id
             LIMIT 1
            """
        ),
        {"t": db.current_tenant()},
    ).mappings().first()
    if not row:
        pytest.skip("no customers seeded")
    return row["id"], row["account_id"]


def _paid_intent(db_tx, customer_id: str, account_id: str) -> None:
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
            "id": f"pi-gov-{uuid.uuid4().hex[:10]}",
            "t": db.current_tenant(),
            "cid": customer_id,
            "aid": account_id,
            "tok": f"tok-{uuid.uuid4().hex}",
        },
    )


def _paylink_connector(db_tx, *, status: str, circuit_opened: bool = False) -> str:
    """A first-party paylink connector for this tenant, in ``status``."""
    connector_id = f"conn-{db.current_tenant()}-paylink"
    db_tx.execute(
        text("DELETE FROM mcp_connectors WHERE tenant_id = :t AND slug = 'paylink'"),
        {"t": db.current_tenant()},
    )
    db_tx.execute(
        text(
            """
            INSERT INTO mcp_connectors (
              id, tenant_id, slug, display_name, kind, allow_prefixes,
              data_class, status, circuit_opened_at
            ) VALUES (
              :id, :t, 'paylink', 'Pay Link', 'first_party',
              CAST('{ext.paylink.}' AS text[]), CAST('{pii}' AS text[]),
              :status, CASE WHEN :open THEN now() ELSE NULL END
            )
            """
        ),
        {"id": connector_id, "t": db.current_tenant(), "status": status, "open": circuit_opened},
    )
    return connector_id


def _require_connectors(db_tx) -> None:
    row = db_tx.execute(text("SELECT to_regclass('public.mcp_connectors') AS t")).mappings().first()
    if not row or not row["t"]:
        pytest.skip("mcp_connectors missing")


def _context(customer_id: str) -> dict:
    import bot_tools

    ctx = bot_tools.ToolContext(
        job_id="job-gov",
        conversation_id="conv-gov",
        customer_id=customer_id,
        interaction_id=None,
        bot_id=None,
        customer_text="",
        intent="balance_query",
    )
    return bot_tools._tool_get_customer_context(ctx, {})


# ---------------------------------------------------------------------------
# Fix 1 — the paylink read answers to the registry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["draft", "disabled"])
def test_context_omits_paylink_when_connector_is_not_approved(
    db_tx, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    """The leak: payment status reached the card through an ungoverned read."""
    _require_connectors(db_tx)
    monkeypatch.setenv("MCP_CLIENT_ENABLED", "true")
    customer_id, account_id = _customer(db_tx)
    if not account_id:
        pytest.skip("no account")
    _paid_intent(db_tx, customer_id, account_id)
    _paylink_connector(db_tx, status=status)

    out = _context(customer_id)
    assert "payLink" not in out
    # Degraded, not broken: the rest of the card is still built.
    assert out.get("accountId") or out.get("name") or out.get("outstanding") is not None


def test_context_omits_paylink_when_the_circuit_is_open(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_connectors(db_tx)
    monkeypatch.setenv("MCP_CLIENT_ENABLED", "true")
    customer_id, account_id = _customer(db_tx)
    if not account_id:
        pytest.skip("no account")
    _paid_intent(db_tx, customer_id, account_id)
    _paylink_connector(db_tx, status="approved", circuit_opened=True)

    assert "payLink" not in _context(customer_id)


def test_context_includes_paylink_for_an_approved_healthy_connector(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half — a gate that refuses everything would pass the tests above."""
    _require_connectors(db_tx)
    monkeypatch.setenv("MCP_CLIENT_ENABLED", "true")
    customer_id, account_id = _customer(db_tx)
    if not account_id:
        pytest.skip("no account")
    _paid_intent(db_tx, customer_id, account_id)
    _paylink_connector(db_tx, status="approved")

    out = _context(customer_id)
    assert out["payLink"]["status"] == "paid"
    assert out["payLink"]["say"] == "We see the UPI success."


def test_context_omits_paylink_when_mcp_client_is_off(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unchanged behaviour: the flag still short-circuits before any DB read."""
    _require_connectors(db_tx)
    monkeypatch.delenv("MCP_CLIENT_ENABLED", raising=False)
    customer_id, account_id = _customer(db_tx)
    if not account_id:
        pytest.skip("no account")
    _paid_intent(db_tx, customer_id, account_id)
    _paylink_connector(db_tx, status="approved")

    assert "payLink" not in _context(customer_id)


def test_dispatch_gates_first_party_tools_on_status(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``dispatch`` used to answer first-party tools above the status check."""
    _require_connectors(db_tx)
    monkeypatch.setenv("MCP_CLIENT_ENABLED", "true")
    from agent_core.connectors.persist import dispatch

    customer_id, _ = _customer(db_tx)
    _paylink_connector(db_tx, status="draft")
    assert dispatch(PAYLINK_TOOL, customer_id=customer_id) == {
        "ok": False,
        "error": "connector_not_bound",
    }

    _paylink_connector(db_tx, status="approved", circuit_opened=True)
    assert dispatch(PAYLINK_TOOL, customer_id=customer_id) == {
        "ok": False,
        "error": "connector_circuit_open",
    }

    _paylink_connector(db_tx, status="approved")
    assert dispatch(PAYLINK_TOOL, customer_id=customer_id)["ok"] is True


def test_dispatch_refuses_an_unregistered_first_party_connector(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No row at all is not an implicit grant."""
    _require_connectors(db_tx)
    monkeypatch.setenv("MCP_CLIENT_ENABLED", "true")
    from agent_core.connectors.persist import dispatch

    customer_id, _ = _customer(db_tx)
    db_tx.execute(
        text("DELETE FROM mcp_connectors WHERE tenant_id = :t AND slug = 'paylink'"),
        {"t": db.current_tenant()},
    )
    assert dispatch(PAYLINK_TOOL, customer_id=customer_id)["error"] == "connector_not_bound"


# ---------------------------------------------------------------------------
# Fix 2 — the default connector id is tenant-scoped
# ---------------------------------------------------------------------------


def _foreign_tenant(conn, tenant_id: str = "other.bank") -> str:
    conn.execute(
        text("INSERT INTO tenants (id, name) VALUES (:t, 'Other Bank') ON CONFLICT DO NOTHING"),
        {"t": tenant_id},
    )
    return tenant_id


def _payload(slug: str) -> dict:
    return {"slug": slug, "kind": "first_party", "displayName": "Pay Link"}


def _row_count(db_tx, slug: str, tenant_id: str) -> int:
    return db_tx.execute(
        text("SELECT count(*) FROM mcp_connectors WHERE slug = :s AND tenant_id = :t"),
        {"s": slug, "t": tenant_id},
    ).scalar()


def test_two_tenants_can_register_the_same_slug(db_tx) -> None:
    """Previously the second INSERT raised on the id PRIMARY KEY."""
    _require_connectors(db_tx)
    from agent_core.connectors.persist import upsert_connector

    slug = f"paylink{uuid.uuid4().hex[:6]}"
    other = _foreign_tenant(db_tx)
    ours = upsert_connector(_payload(slug))
    with tenant_context.bind(other):
        theirs = upsert_connector(_payload(slug))

    assert ours["id"] != theirs["id"], "both tenants were handed the same primary key"
    assert db.current_tenant() in ours["id"]
    assert other in theirs["id"]
    assert _row_count(db_tx, slug, db.current_tenant()) == 1
    assert _row_count(db_tx, slug, other) == 1


def test_repeat_upsert_updates_the_same_row(db_tx) -> None:
    """Tenant-scoping the id must not turn the upsert into an insert-per-call."""
    _require_connectors(db_tx)
    from agent_core.connectors.persist import upsert_connector

    slug = f"paylink{uuid.uuid4().hex[:6]}"
    first = upsert_connector(_payload(slug))
    second = upsert_connector({**_payload(slug), "displayName": "Pay Link v2"})

    assert first["id"] == second["id"]
    assert second["displayName"] == "Pay Link v2"
    assert _row_count(db_tx, slug, db.current_tenant()) == 1


def test_an_explicit_id_is_still_honoured(db_tx) -> None:
    """Only the default is scoped — callers that supply an id keep it."""
    _require_connectors(db_tx)
    from agent_core.connectors.persist import upsert_connector

    slug = f"paylink{uuid.uuid4().hex[:6]}"
    row = upsert_connector({**_payload(slug), "id": f"conn-explicit-{slug}"})
    assert row["id"] == f"conn-explicit-{slug}"


def test_each_tenant_reads_back_only_its_own_connector(db_tx) -> None:
    _require_connectors(db_tx)
    from agent_core.connectors.persist import get_connector, upsert_connector

    slug = f"paylink{uuid.uuid4().hex[:6]}"
    other = _foreign_tenant(db_tx)
    ours = upsert_connector(_payload(slug))
    with tenant_context.bind(other):
        theirs = upsert_connector({**_payload(slug), "displayName": "Their Pay Link"})
        assert get_connector(slug)["id"] == theirs["id"]
        assert get_connector(ours["id"]) is None

    assert get_connector(slug)["id"] == ours["id"]
    assert get_connector(theirs["id"]) is None
