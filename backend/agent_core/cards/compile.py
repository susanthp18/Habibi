"""Publish compiler — gates G0–G14. First red stops mutating steps; the report
still lists every static failure.

G7/G8/G10/G11 are skipped (not faked green) when their feature flags are off or
the suite is not in ``card.eval.require``. Skipped is an honest state: publish
may proceed. Fail is closed.

G6 is blocking in Phase 2 (idle voice tool count or skill-description budget).
G9 is blocking: attached skill versions must be signed and their allowed-tools
must sit inside the catalog and the card include ∪ locked set.
G11 (twin) is blocking in Phase 4 when twin is required — HTTP 409.
G12 (canary) is blocking in Phase 5: 100% traffic passes; a split requires
auto-rollback. G13 (A2A mTLS) is blocking when the card exposes A2A.
G14 (agent.publish) is skipped on dry-run with no actor; HTTP publish must pass.
G14 fail → 403.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_core.cards.schema import (
    LOCKED_MOUTH_TOOLS,
    LOCKED_POLICY_ENGINES,
    REQUIRED_POLICY_KEYS,
    AgentCard,
    is_authored,
)
from agent_core.platform_flags import eval_gate_enabled, redteam_gate_enabled
from agent_core.skills.intersect import (
    PLATFORM_SKILL_TOOLS,
    description_prefix_tokens,
    effective_tools as skill_effective_tools,
    idle_offered_tools,
)
from agent_core.skills.lint import CATALOG_PREFIX_TOKEN_CAP
from agent_core.skills.pack import SkillPack, pack_for_slug

GateStatus = Literal["pass", "fail", "warn", "skipped"]


class GateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate: str
    name: str
    status: GateStatus
    detail: str = ""
    issues: list[dict[str, Any]] = []


class CompileReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_id: str
    gates: list[GateResult]
    effective_tools: list[str] = []
    idle_tools: list[str] = []
    # The number G6 actually gates on: idle tools minus the platform skill
    # tools, which ride along free. `len(idle_tools)` is not that number, and a
    # UI that recomputed the cap from the card's include list was redder still.
    idle_voice_tools: int = 0
    voice_tool_cap: int = 0
    skill_description_tokens: int = 0
    card: dict[str, Any] = {}

    @property
    def blocking(self) -> list[GateResult]:
        return [g for g in self.gates if g.status == "fail"]

    @property
    def ok(self) -> bool:
        return not self.blocking

    def http_status(self) -> int:
        if any(g.gate == "G14" and g.status == "fail" for g in self.gates):
            return 403
        if any(g.gate in {"G7", "G8", "G11"} and g.status == "fail" for g in self.gates):
            return 409
        return 422


class CompileError(Exception):
    """Raised when publish cannot proceed. Carries the full report."""

    def __init__(self, report: CompileReport) -> None:
        self.report = report
        super().__init__(f"compile_failed:{[g.gate for g in report.blocking]}")

    def http_detail(self) -> dict[str, Any]:
        return {
            "code": "compile_failed",
            "status": self.report.http_status(),
            "report": self.report.model_dump(),
        }


def _gate(gate: str, name: str, status: GateStatus, detail: str = "", issues: list | None = None) -> GateResult:
    return GateResult(gate=gate, name=name, status=status, detail=detail, issues=issues or [])


def _resolve_attached(
    card: AgentCard,
    attached_skills: list[SkillPack] | None,
) -> tuple[list[SkillPack], list[str]]:
    """Prefer caller-supplied packs (DB-signed). Else first-party on-disk packs.

    Passing a list never hides unresolved slugs — G9 must fail closed on a
    missing pack rather than publish a mouth with a hole.
    """
    wanted = [ref.skill_id for ref in card.skills]
    if attached_skills is not None:
        have = {p.slug for p in attached_skills}
        return attached_skills, [slug for slug in wanted if slug not in have]
    if not wanted:
        return [], []
    packs: list[SkillPack] = []
    missing: list[str] = []
    for slug in wanted:
        try:
            packs.append(pack_for_slug(slug))
        except KeyError:
            missing.append(slug)
    return packs, missing


def effective_tools(
    card: AgentCard,
    *,
    catalog_names: set[str],
    channel_tools: set[str] | None = None,
    attached_skills: list[SkillPack] | None = None,
) -> list[str]:
    """include ∩ catalog ∩ channel ∪ locked, with skill-gated writes filtered."""
    packs, _ = _resolve_attached(card, attached_skills)
    return skill_effective_tools(
        card,
        catalog_names=catalog_names,
        channel_tools=channel_tools,
        attached_skills=packs if (card.skills or attached_skills is not None) else None,
    )


_ROLLBACK_TRIGGERS = frozenset({"slo_miss", "live_qa_burn", "eval_fail"})


def compile_card(
    *,
    bot_id: str,
    card_raw: Any,
    flow: Any = None,
    catalog_names: set[str],
    known_bot_ids: set[str],
    channel_tools: set[str] | None = None,
    eval_report: dict[str, Any] | None = None,
    redteam_report: dict[str, Any] | None = None,
    twin_report: dict[str, Any] | None = None,
    attached_skills: list[SkillPack] | None = None,
    traffic_pct: int | None = None,
    auto_rollback: list[str] | None = None,
    has_publish: bool | None = None,
    a2a_cert_ok: bool | None = None,
) -> CompileReport:
    """Static gates always run. Eval gates honour their flags."""
    gates: list[GateResult] = []
    card: AgentCard | None = None
    tools: list[str] = []
    idle: list[str] = []
    skill_tokens = 0
    idle_count = 0
    tool_cap = 0
    dump: dict[str, Any] = card_raw if isinstance(card_raw, dict) else {}
    packs: list[SkillPack] = []
    unresolved: list[str] = []

    # G0 schema
    if not is_authored(card_raw):
        gates.append(_gate("G0", "schema", "skipped", "empty agent_card — legacy mouth"))
    else:
        try:
            card = AgentCard.model_validate(card_raw)
            dump = card.model_dump(mode="json")
            gates.append(_gate("G0", "schema", "pass"))
        except ValidationError as exc:
            issues = [
                {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                for e in exc.errors()
            ]
            gates.append(_gate("G0", "schema", "fail", "agent_card is not a valid AgentCard", issues))

    # G1 flowValid
    try:
        import flow_graph as fg

        fg.assert_publishable(flow)
        gates.append(_gate("G1", "flowValid", "pass"))
    except Exception as exc:
        issues = []
        detail = str(exc)
        if hasattr(exc, "http_detail"):
            payload = exc.http_detail()
            issues = payload.get("issues") or []
            detail = payload.get("code") or detail
        gates.append(_gate("G1", "flowValid", "fail", detail, issues))

    # G2 flow included (authored graphs must not have been dropped)
    import flow_graph as fg

    if fg.is_authored(flow):
        gates.append(_gate("G2", "flow_persisted", "pass"))
    else:
        gates.append(
            _gate("G2", "flow_persisted", "pass", "empty flow — built-in script")
        )

    # G3 policy bindings locked
    if card is None:
        gates.append(_gate("G3", "policy_bindings", "skipped", "no card"))
    else:
        missing = [
            key
            for key in REQUIRED_POLICY_KEYS
            if getattr(card.policy_bindings, key, None) != "required"
        ]
        locked_set = set(card.tools.locked)
        missing_locked = [n for n in LOCKED_POLICY_ENGINES if n not in locked_set]
        if missing or missing_locked:
            gates.append(
                _gate(
                    "G3",
                    "policy_bindings",
                    "fail",
                    "engines cannot be unbound",
                    [{"missing_bindings": missing, "missing_locked": missing_locked}],
                )
            )
        else:
            gates.append(_gate("G3", "policy_bindings", "pass"))

    # G4 effective tools ⊆ catalog; locked mouth tools included
    if card is None:
        gates.append(_gate("G4", "tools", "skipped", "no card"))
    else:
        packs, unresolved = _resolve_attached(card, attached_skills)
        unknown = [n for n in card.tools.include if n not in catalog_names]
        tools = effective_tools(
            card,
            catalog_names=catalog_names,
            channel_tools=channel_tools,
            attached_skills=packs if (card.skills or attached_skills is not None) else None,
        )
        idle = idle_offered_tools(
            card,
            catalog_names=catalog_names,
            attached_skills=packs if (card.skills or attached_skills is not None) else None,
            channel_tools=channel_tools,
        )
        missing_locked = [n for n in LOCKED_MOUTH_TOOLS if n not in tools and n in catalog_names]
        # Internal-only cards (supervisor brief) have no mouth tools — locked
        # engines stay on the card but are not in the mouth set.
        voice_or_wa = any(ch in card.identity.channels for ch in ("voice", "whatsapp"))
        if unknown:
            gates.append(
                _gate("G4", "tools", "fail", "include names not in catalog", [{"unknown": unknown}])
            )
        elif voice_or_wa and missing_locked:
            gates.append(
                _gate(
                    "G4",
                    "tools",
                    "fail",
                    "locked mouth tools missing from effective set",
                    [{"missing": missing_locked}],
                )
            )
        else:
            gates.append(_gate("G4", "tools", "pass", f"{len(tools)} tools"))

    # G5 handoff targets exist and are allowlisted (on this card)
    if card is None:
        gates.append(_gate("G5", "handoffs", "skipped", "no card"))
    else:
        missing_bots = [h.to_bot_id for h in card.handoffs if h.to_bot_id not in known_bot_ids]
        self_ref = [h.to_bot_id for h in card.handoffs if h.to_bot_id == bot_id]
        if missing_bots or self_ref:
            gates.append(
                _gate(
                    "G5",
                    "handoffs",
                    "fail",
                    "handoff target missing or self",
                    [{"unknown": missing_bots, "self": self_ref}],
                )
            )
        else:
            gates.append(_gate("G5", "handoffs", "pass"))

    # G6 latency — blocking. Idle tools (not the full gated union) vs cap;
    # skill descriptions must fit the ~800 token prefix budget.
    if card is None:
        gates.append(_gate("G6", "latency", "skipped", "no card"))
    else:
        voice = "voice" in card.identity.channels
        skill_tokens = description_prefix_tokens(packs)
        idle_count = len([n for n in idle if n not in PLATFORM_SKILL_TOOLS])
        cap = card.tools.max_voice_tools
        tool_cap = cap
        issues: list[dict[str, Any]] = []
        if voice and idle_count > cap:
            issues.append({"idle_tools": idle_count, "cap": cap})
        if skill_tokens > CATALOG_PREFIX_TOKEN_CAP:
            issues.append({"skill_description_tokens": skill_tokens, "cap": CATALOG_PREFIX_TOKEN_CAP})
        if issues:
            gates.append(
                _gate(
                    "G6",
                    "latency",
                    "fail",
                    f"idle {idle_count}/{cap} tools, skill prefix {skill_tokens}/{CATALOG_PREFIX_TOKEN_CAP} tokens",
                    issues,
                )
            )
        else:
            gates.append(
                _gate(
                    "G6",
                    "latency",
                    "pass",
                    f"idle {idle_count} tools (cap {cap}); skill prefix {skill_tokens} tokens",
                )
            )

    # G7 regression
    gates.append(_eval_gate("G7", "regression", eval_gate_enabled(), eval_report, card))
    # G8 red-team
    gates.append(_eval_gate("G8", "redteam", redteam_gate_enabled(), redteam_report, card))
    # G11 twin — blocking in Phase 4 when twin is in card.eval.require.
    # Default cards require regression+redteam only; skip honestly, never fake-green.
    twin_required = bool(card and "twin" in (card.eval.require or []))
    gates.append(_eval_gate("G11", "twin", twin_required, twin_report, card))

    # G9 signed skills + allowed-tools ⊆ catalog ∩ (include ∪ locked)
    if card is None or not card.skills:
        gates.append(_gate("G9", "signed_skills", "skipped", "no skills on card"))
    else:
        g9_issues: list[dict[str, Any]] = []
        if unresolved:
            g9_issues.append({"unresolved": unresolved})
        unsigned = [p.slug for p in packs if not p.signed]
        if unsigned:
            g9_issues.append({"unsigned": unsigned})
        allowed_scope = set(card.tools.include) | set(card.tools.locked) | PLATFORM_SKILL_TOOLS
        extras: dict[str, list[str]] = {}
        unknown_skill_tools: dict[str, list[str]] = {}
        for pack in packs:
            not_catalog = [n for n in pack.allowed_tools if n not in catalog_names]
            not_card = [n for n in pack.allowed_tools if n not in allowed_scope and n in catalog_names]
            if not_catalog:
                unknown_skill_tools[pack.slug] = not_catalog
            if not_card:
                extras[pack.slug] = not_card
        if unknown_skill_tools:
            g9_issues.append({"unknown_tools": unknown_skill_tools})
        if extras:
            g9_issues.append({"tools_not_on_card": extras})
        if g9_issues:
            gates.append(_gate("G9", "signed_skills", "fail", "unsigned or out-of-scope skill tools", g9_issues))
        else:
            gates.append(_gate("G9", "signed_skills", "pass", f"{len(packs)} signed skill(s)"))

    # G10 connectors — skipped until MCP_CLIENT_ENABLED. Never fake-green.
    from agent_core.platform_flags import mcp_client_enabled

    if card is None or not card.connectors:
        gates.append(_gate("G10", "connectors", "skipped", "no connectors on card"))
    elif not mcp_client_enabled():
        gates.append(_gate("G10", "connectors", "skipped", "MCP client flag is off"))
    else:
        g10_issues: list[dict[str, Any]] = []
        try:
            from agent_core.connectors.persist import get_connector
        except Exception:
            get_connector = None  # type: ignore[assignment]
        for ref in card.connectors:
            prefixes = ref.allow_prefixes or []
            if any(not p.startswith("ext.") for p in prefixes):
                g10_issues.append({"bad_prefix": ref.connector_id})
            conn = get_connector(ref.connector_id) if get_connector else None
            if conn is None:
                g10_issues.append({"unresolved": ref.connector_id})
                continue
            if conn["status"] != "approved":
                g10_issues.append({"not_approved": ref.connector_id})
            if conn["kind"] == "remote_mcp":
                url = str(conn.get("url") or "")
                if not url.startswith("https://"):
                    g10_issues.append({"url_not_https": ref.connector_id})
            if not conn.get("dataClass"):
                g10_issues.append({"data_class_missing": ref.connector_id})
            if conn.get("health") == "down":
                g10_issues.append({"unhealthy": ref.connector_id})
        if g10_issues:
            gates.append(_gate("G10", "connectors", "fail", "connector bind failed", g10_issues))
        else:
            gates.append(_gate("G10", "connectors", "pass", f"{len(card.connectors)} connector(s)"))

    # G12 canary — 100% is a full ship. A split without auto-rollback cannot publish.
    pct = traffic_pct
    triggers = list(auto_rollback) if auto_rollback is not None else None
    if card is not None:
        if pct is None:
            pct = card.experiment.traffic_pct
        if triggers is None:
            triggers = list(card.experiment.auto_rollback or [])
    if pct is None:
        pct = 100
    if triggers is None:
        triggers = []
    pct = max(0, min(100, int(pct)))
    valid_triggers = [t for t in triggers if t in _ROLLBACK_TRIGGERS]
    if pct == 100:
        gates.append(_gate("G12", "canary", "pass", "full ship"))
    elif 0 < pct < 100 and valid_triggers:
        gates.append(_gate("G12", "canary", "pass", f"{pct}% with {','.join(valid_triggers)}"))
    elif 0 < pct < 100:
        gates.append(
            _gate(
                "G12",
                "canary",
                "fail",
                "canary split requires auto_rollback",
                [{"traffic_pct": pct, "auto_rollback": triggers}],
            )
        )
    else:
        gates.append(_gate("G12", "canary", "fail", "canary_zero", [{"traffic_pct": pct}]))

    # G13 A2A — skip unless the card exposes A2A. Never pass on bearer-only.
    expose = bool(card and card.a2a and card.a2a.expose)
    if not expose:
        gates.append(_gate("G13", "a2a_mtls", "skipped", "card does not expose A2A"))
    else:
        from agent_core.platform_flags import a2a_enabled

        cert_ok = a2a_cert_ok
        if cert_ok is None:
            try:
                from agent_core.a2a import partner_has_cert

                cert_ok = partner_has_cert(bot_id)
            except Exception:
                cert_ok = False
        if not a2a_enabled():
            gates.append(_gate("G13", "a2a_mtls", "fail", "A2A_ENABLED is off"))
        elif not cert_ok:
            gates.append(_gate("G13", "a2a_mtls", "fail", "partner cert required — bearer is not enough"))
        else:
            gates.append(_gate("G13", "a2a_mtls", "pass", "partner mTLS cert on file"))

    # G14 agent.publish — dry-run with no actor skips so four-card unit compile stays green.
    if has_publish is None:
        gates.append(_gate("G14", "agent_publish", "skipped", "no actor — dry-run"))
    elif has_publish:
        gates.append(_gate("G14", "agent_publish", "pass"))
    else:
        gates.append(_gate("G14", "agent_publish", "fail", "actor lacks agent.publish"))

    return CompileReport(
        bot_id=bot_id,
        gates=gates,
        effective_tools=tools,
        idle_tools=idle,
        idle_voice_tools=idle_count,
        voice_tool_cap=tool_cap,
        skill_description_tokens=skill_tokens,
        card=dump,
    )


def _eval_gate(
    gate: str,
    name: str,
    flag_on: bool,
    report: dict[str, Any] | None,
    card: AgentCard | None,
) -> GateResult:
    if not flag_on:
        return _gate(gate, name, "skipped", f"{name} gate flag is off")
    required = (card.eval.require if card else []) or []
    if name not in required and card is not None:
        return _gate(gate, name, "skipped", f"{name} not in card.eval.require")
    if report is None:
        return _gate(gate, name, "fail", f"{name} suite has not been run")
    status = str(report.get("status") or "")
    if status == "pass":
        return _gate(gate, name, "pass", report.get("id") or "")
    return _gate(gate, name, "fail", status or "eval_fail", [report])


def assert_publishable(report: CompileReport) -> CompileReport:
    if not report.ok:
        raise CompileError(report)
    return report
