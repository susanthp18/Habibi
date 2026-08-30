"""Publish compiler — gates G0–G15. First red stops mutating steps; the report
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

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_core.cards.schema import (
    LOCKED_MOUTH_TOOLS,
    LOCKED_POLICY_ENGINES,
    REQUIRED_POLICY_KEYS,
    ROLLBACK_TRIGGERS,
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

logger = logging.getLogger(__name__)

GateStatus = Literal["pass", "fail", "warn", "skipped"]

#: Issue key raised when G10 could not *read* the connector registry, so the
#: per-connector checks (approved, https, dataClass, health) never ran. Same
#: shape and same reasoning as ``intersect.CONNECTOR_BIND_FAILED``: a registry
#: outage is not an authoring error, so it must not fail the gate, but it must
#: not be indistinguishable from a clean pass either.
CONNECTOR_LOOKUP_UNAVAILABLE = "connector_lookup_unavailable"


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
    #: objective -> entry node key, as the *graph* declares it. The Outbound tab
    #: renders this beside what the card claims, because the two disagreeing is
    #: the failure G-OB2 exists to catch and an author needs to see both halves.
    mission_entries: dict[str, str] = {}
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



# ---------------------------------------------------------------------------
# Outbound gate vocabulary
# ---------------------------------------------------------------------------

#: Business outcome codes the Closer can write. Restated here rather than
#: imported so the compiler does not pull the post-call module (and its Azure
#: client) into every publish; the pair is pinned by a test.
OUTCOME_CODES: frozenset[str] = frozenset(
    {
        "ptp_captured",
        "ptp_recommitted",
        "paid_in_call",
        "part_payment_agreed",
        "plan_agreed",
        "dispute_raised",
        "hardship_declared",
        "refused",
        "callback_requested",
        "wrong_number",
        "deceased",
        "opt_out_requested",
        "escalated",
        "no_resolution",
        "abandoned_by_customer",
    }
)

#: Post-call verbs the Closer knows how to carry out. An authored rule may also
#: name any tool on the card, which is what lets a client add an action without
#: a code change.
POST_CALL_ACTIONS: frozenset[str] = frozenset(
    {
        "confirm_written",
        "schedule_due_reminder",
        "close_case",
        "place_hold",
        "create_followup",
        "suppress_upsell",
        "flag_dispute",
        "notify",
        "schedule_mission",
        "mark_phone_dead",
        "promote_alternate",
        "requeue",
        "record_optout",
        "stop_cadence",
        "advance_ladder",
    }
)

_OUTBOUND_GATE_NAMES: dict[str, str] = {
    "G-OB1": "missions_declared",
    "G-OB2": "entry_nodes",
    "G-OB3": "cadence_budget",
    "G-OB4": "offer_on_service_number",
    "G-OB5": "voicemail_disclosure",
    "G-OB6": "post_call_actions",
    "G-OB7": "escalation_target",
    "G-OB8": "cadence_defined",
}


def _gate(gate: str, name: str, status: GateStatus, detail: str = "", issues: list | None = None) -> GateResult:
    return GateResult(gate=gate, name=name, status=status, detail=detail, issues=issues or [])


def _primary_subtag(tag: str) -> str:
    """``en-IN`` and ``en`` are the same language to this gate.

    Only Azure publishes region-qualified locales. Every other provider the
    registry syncs carries a bare language code — Fish's Arabic rows are ``ar``,
    not ``ar-EG`` — so comparing whole tags would warn on every non-Azure voice
    a card legitimately uses, which is the fastest way to teach an operator to
    ignore the warning.
    """
    return (tag or "").strip().replace("_", "-").split("-")[0].casefold()


def _voice_locale_gate(
    short_name: str | None,
    voice_locale: str | None,
    card_locales: list[str] | None,
) -> GateResult:
    """G15 — the voice speaks a language the card does not claim.

    A warning, never a block. Shipping a voice from outside the card's language
    set is a legitimate localisation override, and a gate that refused it would
    be wrong more often than right. Silence was the defect: a kaia draft carried
    an Arabic Fish voice on an en-IN collections card, cleared G0-G14, and left
    Publish enabled — one click from an English collections bot speaking Arabic.
    """
    sn = (short_name or "").strip()
    wanted = [t for t in (card_locales or []) if t]
    if not sn or not wanted:
        return _gate("G15", "voice_locale", "skipped", "no voice or no card language")
    spoken = (voice_locale or "").strip()
    if not spoken:
        # Not this gate's story to tell. An id the catalog cannot resolve is
        # already reported by get_tts_voice_warning, and what the runtime then
        # speaks is the fallback voice, whose locale is not the stored id's.
        return _gate("G15", "voice_locale", "skipped", f"{sn} is not in the voice catalog")
    if _primary_subtag(spoken) in {_primary_subtag(t) for t in wanted}:
        return _gate("G15", "voice_locale", "pass", f"{spoken} within {', '.join(wanted)}")
    return _gate(
        "G15",
        "voice_locale",
        "warn",
        f"voice speaks {spoken}, card speaks {', '.join(wanted)}",
        [{"voice": sn, "voiceLocale": spoken, "cardLocales": wanted}],
    )


def _mission_entries(flow: Any) -> dict[str, str]:
    """objective -> node key from the graph. Empty on an unauthored flow."""
    import flow_graph as fg

    if not fg.is_authored(flow):
        return {}
    try:
        return fg.parse_graph(flow).entry_objectives()
    except Exception:
        return {}


def _outbound_gates(
    card: "AgentCard | None",
    flow: Any,
    *,
    catalog_names: set[str],
    effective: list[str],
    known_bot_ids: set[str],
    eval_report: dict[str, Any] | None,
) -> list[GateResult]:
    # `eval_report` here is the *outbound* suite's latest report, not the
    # regression one — the caller resolves it by kind.
    """G-OB1..8 — an agent that cannot dial correctly must not be publishable.

    Outbound has a property inbound does not: its failures are invisible until
    they are at scale. An inbound bug annoys the one caller who rang us; an
    outbound bug rings ten thousand phones. So these gates are errors, not
    warnings, and several of them exist to catch a configuration that is
    *arithmetically* doomed rather than merely unwise.
    """
    import flow_graph as fg
    from agent_core.cards.schema import PoolKind  # noqa: F401  (documents the vocabulary)

    out: list[GateResult] = []
    if card is None:
        out.append(_gate("G-OB1", "outbound", "skipped", "no card"))
        return out
    ob = card.outbound
    if not ob.dials:
        out.append(_gate("G-OB1", "outbound", "skipped", "inbound-only card"))
        return out

    issues: list[dict[str, Any]] = []

    # G-OB1 — declaring a direction without a mission is a card that dials with
    # no reason to. The runtime would have to invent one.
    if not ob.objectives:
        issues.append({"gate": "G-OB1", "problem": "direction is outbound but no objective is defined"})

    # G-OB2 — the entry node has to exist, and the graph has to agree that it is
    # the entry. Two places can disagree, so both directions are checked: a card
    # naming a node that does not claim the mission is as broken as a card
    # naming a node that does not exist.
    graph = None
    if fg.is_authored(flow):
        try:
            graph = fg.parse_graph(flow)
        except Exception:
            graph = None
    if graph is None:
        # An outbound card with no authored door is not "N/A" — it is a card
        # that will dial and then guess. VS-4D8667B522 ran confirm_identity
        # because the runtime fell back; the compiler must refuse that.
        problem = (
            "flow could not be parsed — no entry door exists"
            if fg.is_authored(flow)
            else "flow is unauthored — no entry door exists"
        )
        for objective in ob.objectives:
            issues.append(
                {"gate": "G-OB2", "objective": objective.key, "problem": problem}
            )
    if graph is not None:
        keys = {n.key for n in graph.nodes}
        claims = graph.entry_objectives()
        for objective in ob.objectives:
            if not objective.entry_node:
                issues.append(
                    {"gate": "G-OB2", "objective": objective.key, "problem": "no entry step chosen"}
                )
                continue
            if objective.entry_node not in keys:
                issues.append(
                    {
                        "gate": "G-OB2",
                        "objective": objective.key,
                        "problem": f"entry step {objective.entry_node!r} is not in the flow",
                    }
                )
            elif claims.get(objective.key) != objective.entry_node:
                issues.append(
                    {
                        "gate": "G-OB2",
                        "objective": objective.key,
                        "problem": (
                            f"the flow says {objective.key!r} starts at "
                            f"{claims.get(objective.key) or 'nothing'}, the card says "
                            f"{objective.entry_node!r}"
                        ),
                    }
                )

    # G-OB3 — a cadence that cannot legally run.
    #
    # The check is per cadence, not the sum across missions, and the difference
    # matters. A borrower is on one case at a time: a bounce cure and a
    # broken-promise chase are different reasons and the same person is rarely
    # both. Summing four missions at one call a day each and calling that four
    # calls a day assumes every borrower is on every mission simultaneously,
    # which is never true — and it blocks a perfectly sane card.
    #
    # What *is* arithmetically guaranteed to be vetoed is a single cadence that
    # plans more contacts in a day than the borrower's cap allows. That case
    # fails every day, for every borrower on it, forever.
    try:
        import contact_policy

        cap = contact_policy.daily_cap()
    except Exception:
        cap = 3
    for cadence in ob.cadences:
        if cadence.per_day > cap:
            issues.append(
                {
                    "gate": "G-OB3",
                    "problem": (
                        f"cadence {cadence.name!r} plans {cadence.per_day} contacts/day "
                        f"against a borrower cap of {cap}"
                    ),
                }
            )

    # G-OB4 — promotional content on a service-only number. TRAI's 1600 series
    # carries service and transactional calls; a product pitch is neither. The
    # honest engineering position is that this is the client's compliance call,
    # so it is configurable — and default-off, which is what this gate enforces.
    if ob.pool_kind == "service_1600":
        for objective in ob.objectives:
            if objective.allowed_offers:
                issues.append(
                    {
                        "gate": "G-OB4",
                        "objective": objective.key,
                        "problem": "offers are not permitted from a 1600-series service pool",
                    }
                )

    # G-OB5 — a voicemail script that omits the grievance contact is a recovery
    # communication made without a disclosure that was owed (RBI para 100AA).
    for objective in ob.objectives:
        vm = objective.voicemail
        if vm.leave != "never" and not vm.include_grievance_contact:
            issues.append(
                {
                    "gate": "G-OB5",
                    "objective": objective.key,
                    "problem": "voicemail without the grievance contact is a recovery "
                    "communication missing a required disclosure",
                }
            )

    # G-OB6 — a post-call rule that names an action nobody implements is a rule
    # that silently does nothing, which is worse than no rule at all.
    known_actions = POST_CALL_ACTIONS | set(effective)
    for rule in ob.post_call.on_outcome:
        if rule.when not in OUTCOME_CODES:
            issues.append(
                {"gate": "G-OB6", "problem": f"unknown outcome code {rule.when!r}"}
            )
        for action in rule.do:
            verb = action.split("(", 1)[0].strip()
            if verb not in known_actions:
                issues.append(
                    {
                        "gate": "G-OB6",
                        "problem": f"post-call action {verb!r} is not a known action "
                        "and is not a tool this card includes",
                    }
                )

    # G-OB7 — escalation has to have somewhere to go, and that somewhere has to
    # be reachable. A cadence pointing at a bot the card cannot hand off to is a
    # ladder with a missing top rung.
    allowlist = card.handoff_targets()
    for cadence in ob.cadences:
        target = (cadence.escalate_to or "").strip()
        if not target or target == "human":
            continue
        if target not in known_bot_ids:
            issues.append(
                {"gate": "G-OB7", "problem": f"escalation target {target!r} is not a known agent"}
            )
        elif target not in allowlist:
            issues.append(
                {
                    "gate": "G-OB7",
                    "problem": f"escalation target {target!r} is not on this card's handoff allowlist",
                }
            )

    # G-OB8 — a named cadence that does not exist silently becomes the default,
    # which is a different retry policy than the author wrote down.
    defined = {c.name for c in ob.cadences}
    for objective in ob.objectives:
        if objective.cadence not in defined and objective.cadence != "default":
            issues.append(
                {
                    "gate": "G-OB8",
                    "objective": objective.key,
                    "problem": f"cadence {objective.cadence!r} is not defined on this card",
                }
            )

    by_gate: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        by_gate.setdefault(str(issue["gate"]), []).append(issue)

    for gate, name in _OUTBOUND_GATE_NAMES.items():
        found = by_gate.get(gate)
        if found:
            out.append(_gate(gate, name, "fail", found[0]["problem"], found))
        else:
            out.append(_gate(gate, name, "pass"))

    # G-OB9 — the eval gate, on exactly the same terms as G7/G8: the flag off
    # skips, the suite not being required skips, and a missing or failing report
    # fails. Restating that logic here rather than reusing `_eval_gate` would be
    # a fourth opinion about what "required" means.
    #
    # `status == "pass"` is the report's own vocabulary. It was written as
    # "passed" here first, which would have failed every genuinely green report
    # — the kind of mistake a gate that nobody can satisfy hides very well.
    from agent_core.platform_flags import outbound_eval_gate_enabled

    out.append(
        _eval_gate("G-OB9", "outbound", outbound_eval_gate_enabled(), eval_report, card)
    )
    return out


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
    issues: list[dict[str, Any]] | None = None,
) -> list[str]:
    """include ∩ catalog ∩ channel ∪ locked, with skill-gated writes filtered."""
    packs, _ = _resolve_attached(card, attached_skills)
    return skill_effective_tools(
        card,
        catalog_names=catalog_names,
        channel_tools=channel_tools,
        attached_skills=packs if (card.skills or attached_skills is not None) else None,
        issues=issues,
    )


# G12's accepted set is the card's own vocabulary. Restating it here meant a
# canary naming only the outbound triggers filtered to empty and failed the
# gate with "canary split requires auto_rollback".
_ROLLBACK_TRIGGERS = ROLLBACK_TRIGGERS


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
    outbound_report: dict[str, Any] | None = None,
    attached_skills: list[SkillPack] | None = None,
    traffic_pct: int | None = None,
    auto_rollback: list[str] | None = None,
    has_publish: bool | None = None,
    a2a_cert_ok: bool | None = None,
    voice_short_name: str | None = None,
    voice_locale: str | None = None,
    card_locales: list[str] | None = None,
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
    #: Filled by the tool intersection at G4, reported by G10.
    connector_bind_issues: list[dict[str, Any]] = []

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
        # Connector binding happens inside the tool intersection. When it fails
        # the compile continues without the ext.* names, and G10 below reports
        # why instead of leaving the author a card that looks connector-less.
        tools = effective_tools(
            card,
            catalog_names=catalog_names,
            channel_tools=channel_tools,
            attached_skills=packs if (card.skills or attached_skills is not None) else None,
            issues=connector_bind_issues,
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
        #: Registry-outage issues, kept apart from ``g10_issues``: they are not
        #: authoring errors and must not fail the gate on their own.
        lookup_issues: list[dict[str, Any]] = []
        card_ident = card.identity.bot_id or card.identity.slug or bot_id

        def _lookup_unavailable(connector_ids: list[str], exc: BaseException) -> None:
            """Record a registry read that did not happen. Loudly.

            The call below used to sit outside any ``try``, so a DB error while
            reading the registry propagated out of ``compile_card`` entirely —
            the studio got a 500 on a card that is perfectly well authored, and
            an outage in one connector registry took out every publish and every
            dry-run compile. Degrade the way ``bound_tool_names`` was made to:
            log with the card, tell the author in the report, and finish the
            compile with the ext.* checks declared unrun rather than faked.
            """
            logger.error(
                "connector registry lookup failed for card %s (connectors=%s) — "
                "compiling with ext.* gates skipped: %s",
                card_ident,
                connector_ids,
                exc,
                exc_info=True,
            )
            lookup_issues.append(
                {
                    "problem": CONNECTOR_LOOKUP_UNAVAILABLE,
                    "connectors": connector_ids,
                    "detail": str(exc) or exc.__class__.__name__,
                }
            )

        try:
            from agent_core.connectors.persist import get_connector
        except Exception as exc:
            # An import failure is the same class of problem as a failed read,
            # and it affects every ref at once. It used to be reported as each
            # connector being "unresolved" — i.e. as the author having named
            # connectors that do not exist, which is a blocking authoring error
            # and the wrong story entirely.
            get_connector = None  # type: ignore[assignment]
            _lookup_unavailable([c.connector_id for c in card.connectors], exc)
        for ref in card.connectors:
            prefixes = ref.allow_prefixes or []
            # Pure card validation: it needs no registry, so it still runs (and
            # still blocks) when the lookup is unavailable.
            if any(not p.startswith("ext.") for p in prefixes):
                g10_issues.append({"bad_prefix": ref.connector_id})
            if get_connector is None:
                continue
            try:
                conn = get_connector(ref.connector_id)
            except Exception as exc:
                _lookup_unavailable([ref.connector_id], exc)
                continue
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
            gates.append(
                _gate(
                    "G10",
                    "connectors",
                    "fail",
                    "connector bind failed",
                    g10_issues + lookup_issues + connector_bind_issues,
                )
            )
        elif connector_bind_issues or lookup_issues:
            # The registry read threw — either the one that binds ext.* names or
            # the one G10's own checks need. Nothing about the card is wrong, so
            # this does not block a publish; but the compiled tool set is missing
            # every connector tool and/or the ext.* checks never ran, and the
            # author has to be told rather than left to infer it.
            detail = "; ".join(
                part
                for part in (
                    "connector tools unavailable during compile" if connector_bind_issues else "",
                    "connector lookup unavailable — ext.* gates skipped" if lookup_issues else "",
                )
                if part
            )
            gates.append(
                _gate(
                    "G10",
                    "connectors",
                    "warn",
                    detail,
                    connector_bind_issues + lookup_issues,
                )
            )
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

    # G-OB1..9 outbound. Skipped entirely on an inbound-only card, so every
    # card that exists today compiles exactly as it did.
    gates.extend(
        _outbound_gates(
            card,
            flow,
            catalog_names=catalog_names,
            effective=tools,
            known_bot_ids=known_bot_ids,
            eval_report=outbound_report,
        )
    )

    # G14 agent.publish — dry-run with no actor skips so four-card unit compile stays green.
    if has_publish is None:
        gates.append(_gate("G14", "agent_publish", "skipped", "no actor — dry-run"))
    elif has_publish:
        gates.append(_gate("G14", "agent_publish", "pass"))
    else:
        gates.append(_gate("G14", "agent_publish", "fail", "actor lacks agent.publish"))

    # G15 voice locale. Last because it is the only gate that reads the mouth
    # columns rather than the card, and the only one that can warn.
    gates.append(_voice_locale_gate(voice_short_name, voice_locale, card_locales))

    return CompileReport(
        bot_id=bot_id,
        gates=gates,
        effective_tools=tools,
        idle_tools=idle,
        idle_voice_tools=idle_count,
        voice_tool_cap=tool_cap,
        skill_description_tokens=skill_tokens,
        mission_entries=_mission_entries(flow),
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
