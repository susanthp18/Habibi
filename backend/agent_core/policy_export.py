"""OPA (Rego) and Cedar *export* of live Python policy. Never imported.

GRC diffs this bundle. Authority / DND / calling hours still veto in-process.
"""

from __future__ import annotations

from typing import Any

from agent_core.authority import config as authority_config
from agent_core.platform_flags import policy_export_enabled
from contact_policy import RBI_VOICE_END, RBI_VOICE_START


def bundle(*, fmt: str = "opa") -> dict[str, Any]:
    if not policy_export_enabled():
        raise PermissionError("policy_export_disabled")
    kind = (fmt or "opa").strip().lower()
    if kind not in {"opa", "rego", "cedar"}:
        raise ValueError("policy_export_format")
    facts = {
        "callingHours": {"startHour": RBI_VOICE_START, "endHour": RBI_VOICE_END, "tz": "Asia/Kolkata"},
        "authority": {
            "lateFeeCapInr": authority_config.late_fee_cap(),
            "lateFeeMidCapInr": authority_config.late_fee_mid_cap(),
            "maxOutstandingInr": authority_config.late_fee_max_outstanding(),
            "maxDpd": authority_config.late_fee_max_dpd(),
            "minTenureMonths": authority_config.min_tenure_months(),
        },
        "dnd": {"contactWhenDnd": False},
        "source": "python",
        "note": "Projection only. Live veto remains in-process Python.",
    }
    if kind == "cedar":
        return {"format": "cedar", "facts": facts, "text": _cedar(facts)}
    return {"format": "opa", "facts": facts, "text": _rego(facts)}


def _rego(facts: dict[str, Any]) -> str:
    hours = facts["callingHours"]
    auth = facts["authority"]
    return (
        "package bigbound.policy\n\n"
        "default allow := false\n\n"
        f"calling_hours_start := {hours['startHour']}\n"
        f"calling_hours_end := {hours['endHour']}\n"
        f"authority_late_fee_cap := {auth['lateFeeCapInr']}\n"
        f"authority_late_fee_mid_cap := {auth['lateFeeMidCapInr']}\n"
        f"authority_max_outstanding := {auth['maxOutstandingInr']}\n"
        f"authority_max_dpd := {auth['maxDpd']}\n"
        f"authority_min_tenure_months := {auth['minTenureMonths']}\n\n"
        "dnd if input.customer.dnd == true\n\n"
        "inside_calling_hours if {\n"
        "  input.hour >= calling_hours_start\n"
        "  input.hour < calling_hours_end\n"
        "}\n\n"
        "allow if {\n"
        "  not dnd\n"
        "  inside_calling_hours\n"
        "}\n"
    )


def _cedar(facts: dict[str, Any]) -> str:
    hours = facts["callingHours"]
    auth = facts["authority"]
    return (
        f"// Generated from Python engines. Do not hot-load.\n"
        f"permit(principal, action, resource)\n"
        f"when {{\n"
        f"  resource.dnd == false &&\n"
        f"  context.hour >= {hours['startHour']} &&\n"
        f"  context.hour < {hours['endHour']} &&\n"
        f"  context.goodwill_inr <= {auth['lateFeeCapInr']}\n"
        f"}};\n"
    )
