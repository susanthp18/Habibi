"""F9 protected attributes — evaluation role only. Never row-level on API."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import text

from bank_boundary import schema_ready


class EvaluationRoleRequired(PermissionError):
    """F9 writes are refused unless the evaluation role is active."""


def evaluation_role_active(conn: Any) -> bool:
    """Return whether this connection has the segregated F9 write grant."""
    try:
        return (
            conn.execute(
                text(
                    """
                    SELECT has_table_privilege(
                      current_user,
                      'evaluation.protected_attributes',
                      'INSERT'
                    )
                    """
                )
            ).scalar()
            is True
        )
    except Exception:
        return False


def ingest(
    conn: Any,
    *,
    tenant_id: str,
    customer_id: str,
    attribute_name: str,
    attribute_value: str,
    source_ref: str | None = None,
) -> str:
    if not evaluation_role_active(conn):
        raise EvaluationRoleRequired("f9_requires_evaluation_role")
    if not schema_ready.evaluation_ready(conn):
        raise EvaluationRoleRequired("f9_schema_missing")
    owned = conn.execute(
        text(
            """
            SELECT 1 FROM public.customers
             WHERE id = :cid AND tenant_id = :tid
            """
        ),
        {"cid": customer_id, "tid": tenant_id},
    ).first()
    if owned is None:
        raise EvaluationRoleRequired("f9_tenant_ownership")
    digest = hashlib.sha256(attribute_value.encode("utf-8")).hexdigest()
    row_id = f"F9-{uuid.uuid4().hex[:12].upper()}"
    conn.execute(
        text(
            """
            INSERT INTO evaluation.protected_attributes (
              id, tenant_id, customer_id, attribute_name, attribute_value_hash,
              source_ref
            ) VALUES (
              :id, :tid, :cid, :name, :hash, :src
            )
            ON CONFLICT (tenant_id, customer_id, attribute_name) DO UPDATE SET
              attribute_value_hash = EXCLUDED.attribute_value_hash,
              source_ref = EXCLUDED.source_ref
            """
        ),
        {
            "id": row_id,
            "tid": tenant_id,
            "cid": customer_id,
            "name": attribute_name,
            "hash": digest,
            "src": source_ref,
        },
    )
    n = conn.execute(
        text(
            """
            SELECT count(*) FROM evaluation.protected_attributes
             WHERE tenant_id = :tid
            """
        ),
        {"tid": tenant_id},
    ).scalar()
    conn.execute(
        text(
            """
            INSERT INTO evaluation.fairness_readiness (
              tenant_id, portfolio_id, covered, n_subjects
            ) VALUES (
              :tid, '', true, :n
            )
            ON CONFLICT (tenant_id, portfolio_id) DO UPDATE SET
              covered = true,
              n_subjects = EXCLUDED.n_subjects,
              updated_at = now()
            """
        ),
        {"tid": tenant_id, "n": int(n or 0)},
    )
    return row_id


def fairness_readiness(conn: Any, *, tenant_id: str, portfolio_id: str = "") -> dict[str, Any]:
    """Aggregate only. Never returns attribute values or hashes."""
    if not schema_ready.evaluation_ready(conn):
        return {"covered": False, "n_subjects": 0, "ready": False}
    row = conn.execute(
        text(
            """
            SELECT covered, n_subjects FROM evaluation.fairness_readiness
             WHERE tenant_id = :tid AND portfolio_id = :pid
            """
        ),
        {"tid": tenant_id, "pid": portfolio_id},
    ).mappings().first()
    if row is None:
        return {"covered": False, "n_subjects": 0, "ready": False}
    return {
        "covered": bool(row["covered"]),
        "n_subjects": int(row["n_subjects"] or 0),
        "ready": bool(row["covered"]) and int(row["n_subjects"] or 0) > 0,
    }
