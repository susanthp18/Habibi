"""OPA (Rego) and Cedar *export* of live Python policy. Never imported.

GRC diffs this bundle. Authority / DND / calling hours still veto in-process.
"""

from __future__ import annotations

import json
from typing import Any

import db
import policy_rules
from agent_core.authority import config as authority_config
from agent_core.clock import timezone_name
from agent_core.platform_flags import policy_export_enabled


#: The channels a tenant can publish a calling window for.
_CHANNELS = ("voice", "whatsapp", "sms")


def bundle(*, fmt: str = "opa", bot_id: str | None = None) -> dict[str, Any]:
    if not policy_export_enabled():
        raise PermissionError("policy_export_disabled")
    kind = (fmt or "opa").strip().lower()
    if kind not in {"opa", "rego", "cedar"}:
        raise ValueError("policy_export_format")
    tenant = db.current_tenant()
    # The rules the tenant actually runs under, not platform constants: GRC
    # diffs this bundle against what was published. DND used to be a literal
    # `contactWhenDnd: False` with the scrub lists and suppression kinds the
    # gate reads left out, and the card's gates were not in the bundle at all.
    with db.engine.connect() as conn:
        rules = policy_rules.resolve(conn, tenant_id=tenant)
        windows = {
            ch: policy_rules.calling_window(conn, ch, tenant_id=tenant) for ch in _CHANNELS
        }
    start_hour, end_hour = windows["voice"]
    facts: dict[str, Any] = {
        "callingHours": {"startHour": start_hour, "endHour": end_hour, "tz": timezone_name()},
        "callingWindows": {
            ch: {"startHour": w[0], "endHour": w[1]} for ch, w in windows.items()
        },
        "authority": {
            "lateFeeCapInr": authority_config.late_fee_cap(),
            "lateFeeMidCapInr": authority_config.late_fee_mid_cap(),
            "maxOutstandingInr": authority_config.late_fee_max_outstanding(),
            "maxDpd": authority_config.late_fee_max_dpd(),
            "minTenureMonths": authority_config.min_tenure_months(),
        },
        # `contact_policy` refuses a customer flagged dnd / dnd_registry
        # unconditionally; the published rule set adds the scrub lists and the
        # suppression states that veto on top.
        "dnd": {
            "contactWhenDnd": False,
            "scrubLists": list(rules.channel_scrub_lists()),
            "suppressionKinds": sorted(rules.suppression_kinds()),
            "ruleSetVersion": rules.version,
        },
        "card": _card_facts(bot_id),
        "source": "python",
        "note": "Projection only. Live veto remains in-process Python.",
    }
    if kind == "cedar":
        return {"format": "cedar", "facts": facts, "text": _cedar(facts)}
    return {"format": "opa", "facts": facts, "text": _rego(facts)}


def _card_facts(bot_id: str | None) -> dict[str, Any] | None:
    """The published card's human gates and mouth guardrails, or None when the
    bot has no published version — absent, not an empty card that reads as
    "no gates"."""
    published = db.get_published_prompt_version(bot_id)
    if not published:
        return None
    card = published.get("agentCard") or {}
    return {
        "botId": published["botId"],
        "versionId": published["id"],
        "humanGates": list(card.get("human_gates") or []),
        "guardrails": dict(published.get("guardrails") or {}),
    }


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
        f"authority_min_tenure_months := {auth['minTenureMonths']}\n"
        + _rego_card(facts)
        + "\n"
        + "".join(
            f'calling_window["{ch}"] := [{w["startHour"]}, {w["endHour"]}]\n'
            for ch, w in facts["callingWindows"].items()
        )
        + f"dnd_scrub_lists := {json.dumps(facts['dnd']['scrubLists'])}\n"
        f"dnd_suppression_kinds := {json.dumps(facts['dnd']['suppressionKinds'])}\n\n"
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


def _rego_card(facts: dict[str, Any]) -> str:
    card = facts.get("card")
    if not card:
        return ""
    gates = {str(g.get("tool_name")): str(g.get("require") or "identity") for g in card["humanGates"]}
    return (
        f"card_bot_id := {json.dumps(card['botId'])}\n"
        f"human_gate_require := {json.dumps(gates)}\n"
        f"guardrails := {json.dumps(card['guardrails'])}\n"
    )


def _cedar(facts: dict[str, Any]) -> str:
    hours = facts["callingHours"]
    auth = facts["authority"]
    return (
        f"// Generated from Python engines. Do not hot-load.\n"
        f"// dnd: scrub lists {facts['dnd']['scrubLists']}, suppression {facts['dnd']['suppressionKinds']}\n"
        + "".join(
            f"// calling window {ch}: {w['startHour']}-{w['endHour']}\n"
            for ch, w in facts["callingWindows"].items()
        )
        + (
            f"// card {facts['card']['botId']}: human gates {json.dumps(facts['card']['humanGates'])}\n"
            if facts.get("card")
            else ""
        )
        + f"permit(principal, action, resource)\n"
        f"when {{\n"
        f"  resource.dnd == false &&\n"
        f"  context.hour >= {hours['startHour']} &&\n"
        f"  context.hour < {hours['endHour']} &&\n"
        f"  context.goodwill_inr <= {auth['lateFeeCapInr']}\n"
        f"}};\n"
    )
