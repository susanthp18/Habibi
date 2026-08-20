"""Temporal adapter — not promoted.

``TEMPORAL_ENABLED`` is the go/no-go switch. Until a cluster exists this module
fails closed so a mis-set flag cannot silently fall back to a cron SMS blast.
"""

from __future__ import annotations

from typing import Any


def start_workflow(**_kwargs: Any) -> dict[str, Any]:
    raise RuntimeError("temporal_adapter_not_promoted")


def signal(_job_id: str, _name: str, _payload: dict[str, Any]) -> dict[str, Any]:
    raise RuntimeError("temporal_adapter_not_promoted")


def query(_job_id: str) -> dict[str, Any] | None:
    raise RuntimeError("temporal_adapter_not_promoted")
