"""Fail-closed mapping catalogues. Unknown values never become permission."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

from bank_boundary import schema_ready

RAIL = "rail_return_codes"
LMS = "lms_account_status"
DLT = "dlt_templates"


class UnknownMapping(ValueError):
    """A source value has no approved map entry."""

    def __init__(self, catalogue: str, raw: str) -> None:
        super().__init__(f"unknown_map:{catalogue}:{raw}")
        self.catalogue = catalogue
        self.raw = raw


def lookup_rail(conn: Any, *, namespace: str, code: str) -> str:
    return _lookup(conn, RAIL, namespace, code, column="normalised")


def lookup_lms_status(conn: Any, *, namespace: str, code: str) -> dict[str, Any]:
    if not schema_ready.w5_ready(conn):
        raise UnknownMapping(LMS, code)
    row = conn.execute(
        text(
            """
            SELECT normalised, contacting_permitted
              FROM lms_account_status
             WHERE namespace = :ns AND code = :code
            """
        ),
        {"ns": namespace, "code": code},
    ).mappings().first()
    if row is None:
        raise UnknownMapping(LMS, code)
    return dict(row)


def require_dlt(
    conn: Any, *, tenant_id: str, template_id: str, channel: str
) -> dict[str, Any]:
    if not schema_ready.w5_ready(conn):
        raise UnknownMapping(DLT, template_id)
    row = conn.execute(
        text(
            """
            SELECT id, body_hash, required_assertions, state,
                   submitted_by_user_id, approved_by_user_id, approved_at
              FROM dlt_templates
             WHERE tenant_id = :tid AND template_id = :tidt AND channel = :ch
            """
        ),
        {"tid": tenant_id, "tidt": template_id, "ch": channel},
    ).mappings().first()
    if (
        row is None
        or row["state"] != "approved"
        or row["approved_at"] is None
        or not row["required_assertions"]
    ):
        raise UnknownMapping(DLT, template_id)
    if row["approved_by_user_id"] == row["submitted_by_user_id"]:
        raise UnknownMapping(DLT, template_id)
    return dict(row)


def open_review(
    conn: Any,
    *,
    tenant_id: str,
    catalogue: str,
    raw_value: str,
    contract_code: str | None = None,
    manifest_id: str | None = None,
) -> str:
    review_id = f"BMR-{uuid.uuid4().hex[:12].upper()}"
    conn.execute(
        text(
            """
            INSERT INTO bank_mapping_reviews (
              id, tenant_id, catalogue, raw_value, contract_code, manifest_id
            ) VALUES (
              :id, :tid, :cat, :raw, :code, :mid
            )
            """
        ),
        {
            "id": review_id,
            "tid": tenant_id,
            "cat": catalogue,
            "raw": raw_value,
            "code": contract_code,
            "mid": manifest_id,
        },
    )
    return review_id


def _lookup(conn: Any, table: str, namespace: str, code: str, *, column: str) -> str:
    if table not in {RAIL, LMS}:
        raise UnknownMapping(table, code)
    if not schema_ready.w5_ready(conn):
        raise UnknownMapping(table, code)
    row = conn.execute(
        text(f"SELECT {column} FROM {table} WHERE namespace = :ns AND code = :code"),  # noqa: S608
        {"ns": namespace, "code": code},
    ).scalar()
    if row is None:
        raise UnknownMapping(table, code)
    return str(row)
