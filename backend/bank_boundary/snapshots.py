"""Immutable Action Contract snapshots, persisted at send time."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import text

from bank_boundary import ACTION_CONTRACT_VERSION, schema_ready


class ContractError(ValueError):
    """Missing, stale, tampered, or unsupported contract."""


REQUIRED_FIELDS = frozenset(
    {
        "version",
        "decision_id",
        "tenant_id",
        "policy_binding",
        "policy_binding_hash",
        "engine_image_digest",
        "config_version",
        "veto_stack_version",
        "arm_propensity",
        "action_propensity",
        "action",
        "channel",
        "scheduled_at",
        "expected_value_paise",
        "ev_lcb_paise",
        "objective",
        "strategy",
        "prohibitions",
        "required_assertions",
        "retention_class",
        "allowed_offers",
    }
)


def digest_of(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def persist(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    if not schema_ready.w5_ready(conn):
        raise ContractError("w5_schema_missing")
    validate(payload, require_digest=False)
    body = _digest_body(payload)
    digest = digest_of(body)
    contract_id = f"AC-{uuid.uuid4().hex[:12].upper()}"
    stored = {**payload, "contract_id": contract_id, "digest": digest}
    conn.execute(
        text(
            """
            INSERT INTO action_contracts (
              id, tenant_id, decision_id, version, digest, payload
            ) VALUES (
              :id, :tid, :did, :ver, :digest, CAST(:payload AS jsonb)
            )
            ON CONFLICT (decision_id) DO NOTHING
            """
        ),
        {
            "id": contract_id,
            "tid": payload["tenant_id"],
            "did": payload["decision_id"],
            "ver": payload.get("version") or ACTION_CONTRACT_VERSION,
            "digest": digest,
            "payload": json.dumps(stored, default=str),
        },
    )
    row = conn.execute(
        text("SELECT id, digest, payload FROM action_contracts WHERE decision_id = :did"),
        {"did": payload["decision_id"]},
    ).mappings().first()
    if row is None:
        raise ContractError("persist_failed")
    persisted = dict(row["payload"] or {})
    persisted["contract_id"] = row["id"]
    persisted["digest"] = row["digest"]
    validate(persisted)
    return persisted


def load(conn: Any, decision_id: str) -> dict[str, Any]:
    if not schema_ready.w5_ready(conn):
        raise ContractError("missing")
    row = conn.execute(
        text("SELECT id, version, digest, payload FROM action_contracts WHERE decision_id = :did"),
        {"did": decision_id},
    ).mappings().first()
    if row is None:
        raise ContractError("missing")
    payload = dict(row["payload"] or {})
    if row["version"] != ACTION_CONTRACT_VERSION or payload.get("version") != ACTION_CONTRACT_VERSION:
        raise ContractError("unsupported_version")
    payload["contract_id"] = row["id"]
    payload["digest"] = row["digest"]
    validate(payload)
    return payload


def validate(payload: dict[str, Any], *, require_digest: bool = True) -> None:
    """Validate the closed V1 envelope and its canonical digest."""
    if payload.get("version") != ACTION_CONTRACT_VERSION:
        raise ContractError("unsupported_version")
    missing = sorted(
        key
        for key in REQUIRED_FIELDS
        if key not in payload or payload[key] is None
    )
    if missing:
        raise ContractError(f"missing_fields:{','.join(missing)}")
    for key in ("arm_propensity", "action_propensity"):
        value = float(payload[key])
        if not 0.0 <= value <= 1.0:
            raise ContractError(f"invalid_{key}")
    if payload.get("allowed_offers") != []:
        raise ContractError("collections_offers_not_empty")
    if not payload.get("prohibitions") or not payload.get("required_assertions"):
        raise ContractError("missing_safety_bounds")
    digest = payload.get("digest")
    if require_digest:
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise ContractError("missing_digest")
        if digest_of(_digest_body(payload)) != digest:
            raise ContractError("tampered")


def _digest_body(payload: dict[str, Any]) -> dict[str, Any]:
    skip = {"digest", "contract_id"}
    return {k: payload[k] for k in sorted(payload) if k not in skip}
