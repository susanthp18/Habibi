"""Deterministic reference adapters. No external side effects."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import text

from bank_boundary import mappings, outbox


class BankAdapter(Protocol):
    code: str
    idempotency_horizon_hours: int
    receipt_horizon_hours: int

    def send(self, contract: dict[str, Any]) -> dict[str, Any]:
        ...

    def reconcile(self, idempotency_key: str) -> dict[str, Any]:
        ...

    def receipts(self, since: datetime) -> list[dict[str, Any]]:
        ...


class ReferenceAdapter:
    """Writes deterministic acknowledgements only."""

    idempotency_horizon_hours = 24
    receipt_horizon_hours = 72

    def __init__(self, code: str) -> None:
        self.code = code
        self._receipts: list[dict[str, Any]] = []

    def send(self, contract: dict[str, Any]) -> dict[str, Any]:
        key = str(
            contract.get("idempotency_key")
            or f"{self.code}:{contract.get('decision_id')}"
        )
        ack = {
            "code": self.code,
            "idempotency_key": key,
            "provider_ref": f"ref:{self.code}:{key}",
            "status": "acked",
            "submitted": False,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        if self.code == "O2":
            ack["submitted"] = False
            ack["rail"] = "reference"
            ack["status"] = "awaiting_settlement"
        self._receipts.append(ack)
        return ack

    def reconcile(self, idempotency_key: str) -> dict[str, Any]:
        for row in reversed(self._receipts):
            if row["idempotency_key"] == idempotency_key:
                return {**row, "reconciled": True}
        return {
            "idempotency_key": idempotency_key,
            "status": "unknown",
            "reconciled": False,
        }

    def receipts(self, since: datetime) -> list[dict[str, Any]]:
        stamp = since.isoformat()
        return [r for r in self._receipts if str(r.get("at") or "") >= stamp]


REGISTRY: dict[str, ReferenceAdapter] = {
    code: ReferenceAdapter(code) for code in ("O1", "O2", "O3", "O4", "O5", "O6")
}


def dispatch(code: str) -> ReferenceAdapter:
    adapter = REGISTRY.get(code)
    if adapter is None:
        raise KeyError(f"unknown_outbound:{code}")
    return adapter


def send_with_outbox(
    conn: Any,
    *,
    tenant_id: str,
    contract_code: str,
    action_contract: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    binding = conn.execute(
        text(
            """
            SELECT adapter, state FROM bank_contract_bindings
             WHERE tenant_id = :tid AND contract_code = :code
               AND portfolio_id = :pid
            """
        ),
        {
            "tid": tenant_id,
            "code": contract_code,
            "pid": str(action_contract.get("portfolio_id") or ""),
        },
    ).mappings().first()
    if binding is None or binding["state"] == "blocked":
        raise RuntimeError(f"outbound_binding_unready:{contract_code}")
    if binding["adapter"] != "reference":
        raise RuntimeError(f"real_adapter_unavailable:{binding['adapter']}")
    channel = str(action_contract.get("channel") or "")
    if contract_code == "O1" and channel in {"sms", "whatsapp"}:
        template_id = str(action_contract.get("template_id") or "")
        try:
            approved = mappings.require_dlt(
                conn,
                tenant_id=tenant_id,
                template_id=template_id,
                channel=channel,
            )
        except mappings.UnknownMapping:
            mappings.open_review(
                conn,
                tenant_id=tenant_id,
                catalogue=mappings.DLT,
                raw_value=template_id or "<missing>",
                contract_code=contract_code,
            )
            raise
        required = set(action_contract.get("required_assertions") or [])
        certified = set(approved.get("required_assertions") or [])
        if not required.issubset(certified):
            mappings.open_review(
                conn,
                tenant_id=tenant_id,
                catalogue=mappings.DLT,
                raw_value=template_id,
                contract_code=contract_code,
            )
            raise mappings.UnknownMapping(mappings.DLT, template_id)
    adapter = dispatch(contract_code)
    existing = outbox.get(
        conn, tenant_id=tenant_id, idempotency_key=idempotency_key
    )
    terminal = {
        outbox.ACKED,
        outbox.RECONCILED,
        outbox.AWAITING_SETTLEMENT,
        outbox.PARKED,
        outbox.REJECTED,
    }
    if existing and existing["state"] in terminal:
        return {"replayed": True, "state": existing["state"], "id": existing["id"]}
    if existing:
        reconciled = adapter.reconcile(idempotency_key)
        if not reconciled.get("reconciled"):
            created = existing.get("created_at")
            age_hours = 0.0
            if isinstance(created, datetime):
                aware = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
                age_hours = (datetime.now(timezone.utc) - aware).total_seconds() / 3600
            reason = (
                "provider_idempotency_expired"
                if age_hours > adapter.idempotency_horizon_hours
                else "provider_state_unknown"
            )
            outbox.park(conn, str(existing["id"]), reason)
            return {
                "replayed": True,
                "state": outbox.PARKED,
                "id": existing["id"],
                "reason": reason,
            }
        state = (
            outbox.AWAITING_SETTLEMENT
            if reconciled.get("status") == outbox.AWAITING_SETTLEMENT
            else outbox.RECONCILED
        )
        outbox.mark(
            conn,
            str(existing["id"]),
            state,
            provider_ref=str(reconciled.get("provider_ref") or ""),
            payload=reconciled,
        )
        return {"replayed": True, "state": state, "id": existing["id"]}
    oid = outbox.enqueue(
        conn,
        tenant_id=tenant_id,
        contract_code=contract_code,
        idempotency_key=idempotency_key,
        payload=action_contract,
        action_contract_id=action_contract.get("contract_id"),
        decision_id=action_contract.get("decision_id"),
    )
    ack = adapter.send({**action_contract, "idempotency_key": idempotency_key})
    if ack.get("status") in outbox.AMBIGUOUS:
        outbox.park(conn, oid, "provider_ambiguous")
        return {"id": oid, "state": outbox.PARKED, "ack": ack}
    state = (
        outbox.AWAITING_SETTLEMENT
        if ack.get("status") == outbox.AWAITING_SETTLEMENT
        else outbox.ACKED
    )
    outbox.mark(
        conn,
        oid,
        state,
        provider_ref=str(ack.get("provider_ref")),
        payload=ack,
    )
    return {
        "id": oid,
        "state": state,
        "ack": ack,
        "submitted": bool(ack.get("submitted")),
    }
