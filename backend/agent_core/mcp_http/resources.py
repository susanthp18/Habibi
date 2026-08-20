"""MCP resources — read-only CRM/KB/policy URIs."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

RESOURCE_CATALOG = [
    {"uri": "customer://{id}", "name": "Customer", "description": "CRM customer card (PII). Requires crm.read."},
    {"uri": "account://{id}/ledger", "name": "Account ledger", "description": "Ledger lines for an account. Requires crm.read."},
    {"uri": "kb://snapshot/{id}", "name": "KB snapshot", "description": "Published knowledge snapshot metadata. Requires kb.search."},
    {"uri": "interaction://{id}/trace", "name": "Turn trace", "description": "Tool I/O for one interaction. Requires crm.read."},
    {"uri": "policy://authority-matrix", "name": "Authority matrix", "description": "Live authority policy export. Requires policy.read."},
]


def list_resources() -> list[dict[str, str]]:
    return list(RESOURCE_CATALOG)


def read_resource(uri: str) -> dict[str, Any]:
    parsed = urlparse(uri)
    scheme = parsed.scheme
    path = (parsed.netloc + parsed.path).strip("/")
    if scheme == "customer":
        return _customer(path)
    if scheme == "account":
        account_id = path.split("/")[0]
        return _ledger(account_id)
    if scheme == "kb":
        parts = path.split("/")
        snap_id = parts[-1] if parts else ""
        return _kb_snapshot(snap_id)
    if scheme == "interaction":
        iid = path.split("/")[0]
        return _trace(iid)
    if scheme == "policy" and path.startswith("authority"):
        return _authority()
    raise KeyError("resource_not_found")


def _customer(customer_id: str) -> dict[str, Any]:
    import db

    row = db.get_customer(customer_id)
    if not row:
        raise KeyError("customer_not_found")
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "accountId": row.get("accountId"),
        "outstanding": row.get("outstanding"),
        "dpd": (row.get("account") or {}).get("dpd"),
    }


def _ledger(account_id: str) -> dict[str, Any]:
    import db
    from sqlalchemy import text

    with db.engine.connect() as conn:
        customer = db._one(
            conn.execute(
                text("SELECT customer_id FROM accounts WHERE id = :a AND tenant_id = :t LIMIT 1"),
                {"a": account_id, "t": db._tenant()},
            )
        )
    if not customer:
        raise KeyError("account_not_found")
    row = db.get_customer(customer["customer_id"])
    return {"accountId": account_id, "entries": (row or {}).get("ledger") or []}


def _kb_snapshot(snap_id: str) -> dict[str, Any]:
    import db
    from sqlalchemy import text

    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text("SELECT id, label, created_at FROM kb_snapshots WHERE id = :id AND tenant_id = :t"),
                {"id": snap_id, "t": db._tenant()},
            )
        )
    if not row:
        raise KeyError("snapshot_not_found")
    return {"id": row["id"], "label": row.get("label"), "createdAt": str(row.get("created_at"))}


def _trace(interaction_id: str) -> dict[str, Any]:
    import db

    if hasattr(db, "get_turn_trace"):
        return {"interactionId": interaction_id, "turns": db.get_turn_trace(interaction_id)}
    return {"interactionId": interaction_id, "turns": []}


def _authority() -> dict[str, Any]:
    try:
        from agent_core.authority.matrix import export_matrix

        return export_matrix()
    except Exception:
        return {"engine": "authority", "note": "matrix export unavailable"}


def as_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str)
