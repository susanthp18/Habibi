"""Allowlisted skill scripts — JSON in, JSON out. No subprocess, no network, no ledger writes."""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_WINDOW = "10:00-19:00 IST"

ScriptFn = Callable[[dict[str, Any]], dict[str, Any]]


def _outside_preferred_window(scheduled_at: str, preferred_window: str | None) -> bool:
    """Same rule as db._outside_preferred_window — kept here so code-mode has no DB import."""
    try:
        at = datetime.fromisoformat(scheduled_at)
    except ValueError:
        return False
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    local = at.astimezone(IST)
    hour = local.hour
    window = preferred_window or DEFAULT_WINDOW
    match = re.search(r"(\d{1,2}):(\d{2}).*?(\d{1,2}):(\d{2})", window)
    if not match:
        return hour < 9 or hour >= 20
    start_h, end_h = int(match.group(1)), int(match.group(3))
    return hour < start_h or hour >= end_h


def emi_remaining(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        outstanding = float(payload.get("outstanding") or 0)
        installment = float(payload.get("installment_amount") or payload.get("emi_amount") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "numeric_required"}
    if installment <= 0:
        return {"ok": False, "error": "installment_required"}
    if outstanding <= 0:
        return {"ok": True, "remaining_emis": 0, "outstanding": outstanding}
    remaining = int(math.ceil(outstanding / installment))
    return {
        "ok": True,
        "remaining_emis": remaining,
        "outstanding": outstanding,
        "installment_amount": installment,
    }


def promise_date_in_window(payload: dict[str, Any]) -> dict[str, Any]:
    date = str(payload.get("promise_date") or payload.get("scheduled_at") or "").strip()
    if not date:
        return {"ok": False, "error": "promise_date_required"}
    window = payload.get("preferred_window") or DEFAULT_WINDOW
    outside = _outside_preferred_window(date, str(window))
    return {
        "ok": True,
        "in_window": not outside,
        "outside": outside,
        "promise_date": date,
        "preferred_window": window,
    }


SCRIPTS: dict[str, ScriptFn] = {
    "emi_remaining": emi_remaining,
    "promise_date_in_window": promise_date_in_window,
}

SCRIPT_NAMES: tuple[str, ...] = tuple(sorted(SCRIPTS))


def run_script(name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    fn = SCRIPTS.get(name)
    if fn is None:
        return {"ok": False, "error": "unknown_script", "name": name, "allowed": list(SCRIPT_NAMES)}
    args = payload if isinstance(payload, dict) else {}
    return fn(args)
