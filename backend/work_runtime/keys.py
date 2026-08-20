"""Idempotency keys for work-runtime workflows. Never a free-form SMS blast key."""

from __future__ import annotations


def idempotency_key(*, workflow_type: str, trigger_ref: str, tenant_id: str | None = None) -> str:
    tenant = (tenant_id or "").strip() or "tenant"
    kind = (workflow_type or "").strip() or "job"
    ref = (trigger_ref or "").strip() or "none"
    return f"{tenant}:{kind}:{ref}"
