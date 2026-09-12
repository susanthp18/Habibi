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

import dataclasses
import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_core.cards.gates_voice import voice_locale_gate, voice_provider_gate
from agent_core.cards.schema import (
    LOCKED_MOUTH_TOOLS,
    LOCKED_POLICY_ENGINES,
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
    #: Phase-1 compiled artefact. Empty on a dry compile that did not wrap
    #: through ``fleet.compile_bundle``; persistable JSON when it did.
    bundle: dict[str, Any] = {}
    #: Published doors whose bundle merges this card: publishing it refreshes
    #: each of theirs. Empty for a card nothing merges.
    doors_merging: list[str] = []

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

#: Every gate id and the one name it goes by.
#:
#: The ids lived only as string literals at ~40 call sites, and two things went
#: wrong that a registry makes impossible. ``G-OB1`` was emitted as
#: ``missions_declared`` from the loop below and as ``outbound`` on its two skip
#: paths — one id, two names, in the same function. And two designs each
#: independently specified a ``G-F12``, because nothing said which ids were
#: taken.
#:
#: The ``G-F`` prefix is a separate space from ``G``: G4 (``tools``) and G-F4
#: (``handoff_is_an_edge``) coexist deliberately. The fleet gates that need the
#: merged graph -- G-F1, G-F2, G-F3, G-F6, G-F12, G-F15 -- are emitted from
#: ``agent_core.fleet.compile.fleet_gates`` and registered here, because the id
#: space is one space wherever the gate runs. Reserved but not yet built: G-F16
#: ``gate_monotonicity``.
_GATE_NAMES: dict[str, str] = {
    "G0": "schema",
    "G1": "flowValid",
    "G2": "flow_persisted",
    "G3": "policy_bindings",
    "G4": "tools",
    "G5": "handoffs",
    "G6": "latency",
    "G7": "regression",
    "G8": "redteam",
    "G9": "signed_skills",
    "G10": "connectors",
    "G11": "twin",
    "G12": "canary",
    "G13": "a2a_mtls",
    "G14": "agent_publish",
    "G15": "voice_locale",
    "G16": "flow_grant",
    "G17": "voice_provider_bound",
    "G18": "connector_is_offerable",
    "G-LINT": "prompt_lint",
    "G-OB9": "outbound",
    "G-F1": "closure",
    "G-F2": "door_and_terminals",
    "G-F3": "identity_before_writes",
    "G-F4": "handoff_is_an_edge",
    "G-F6": "door_readonly",
    "G-F7": "carry_is_fact_only",
    "G-F11": "text_walkability",
    "G-F12": "publish_scope",
    "G-F15": "fleet_hop",
    "G-F14": "eval_provenance",
    **_OUTBOUND_GATE_NAMES,
}


def _gate(gate: str, name: str, status: GateStatus, detail: str = "", issues: list | None = None) -> GateResult:
    registered = _GATE_NAMES.get(gate)
    assert registered is not None, f"unregistered gate id {gate!r} — add it to _GATE_NAMES"
    assert registered == name, f"{gate} is {registered!r} everywhere else, not {name!r}"
    return GateResult(gate=gate, name=name, status=status, detail=detail, issues=issues or [])


def _connector_offer_gate(card: AgentCard | None, packs: list[SkillPack]) -> GateResult:
    """G18 — a bound connector whose tools nothing on this card can offer.

    ``ext.*`` names reach the Grant and are stripped from the idle offer
    (``skills/intersect.py``), returning only for tools an *active* skill pack
    names. So a card can bind a connector, pass G10, and never be able to call
    it — the Bind control looks like it granted a capability and granted none.

    Warn, not fail: `kaia-v2-4`'s live published card is exactly this shape
    (binds `paylink`, and no skill version in the tenant names an
    `ext.paylink.*` tool), and a gate that refuses the shipping card on day one
    is one people switch off instead of adopting.

    A connector with no ``allow_prefixes`` is skipped rather than guessed at:
    there is nothing to match its tools against, and silence beats a wrong
    accusation on an authoring surface.
    """
    if card is None or not card.connectors:
        return _gate("G18", "connector_is_offerable", "skipped", "no connectors bound")
    skill_tools = {n for p in packs for n in (p.allowed_tools or [])}
    inert: list[dict[str, Any]] = []
    for conn in card.connectors:
        prefixes = tuple(p for p in (conn.allow_prefixes or []) if p)
        if not prefixes:
            continue
        if not any(name.startswith(prefixes) for name in skill_tools):
            inert.append(
                {"connector": conn.connector_id, "prefixes": list(prefixes)}
            )
    if not inert:
        return _gate("G18", "connector_is_offerable", "pass", "every binding is reachable")
    names = ", ".join(str(i["connector"]) for i in inert)
    return _gate(
        "G18",
        "connector_is_offerable",
        "warn",
        f"bound but offered by nothing: {names} — attach a skill that names its tools",
        inert,
    )


def node_offers(flow: Any, grant: set[str] | frozenset[str]) -> list[dict[str, Any]]:
    """Per node: the tools it names, split into what the runtime will offer and
    what it will silently drop.

    The flow tool picker, ``/flow/validate`` and G1 all check a node's tools
    against the *whole* voice catalog. Nothing checked them against the card's
    Tool Grant — so a node could name a tool the card cannot grant, compile
    green through every gate, and lose it at ``flows_dynamic``'s
    ``logger.warning``. The canvas still drew the tool's hop as an exit, so a
    step whose only way out the runtime would drop looked like a step with a
    way out.

    ``VOICE_ALWAYS`` is not a drop: the nine flow-control verbs are not catalog
    specs at all, and ``capture_call_goal``/``verify_identity`` are on the floor
    the FlowManager keeps regardless of the grant.

    Shared by the G16 gate and the compiled bundle, so the certificate and the
    artefact cannot disagree about what a step can call.
    """
    import flow_graph as fg
    from agent_core.tools.grant import VOICE_ALWAYS

    try:
        graph = fg.parse_graph(flow)
    except Exception:
        return []
    if graph is None:
        return []

    reachable = set(grant) | VOICE_ALWAYS
    out: list[dict[str, Any]] = []

    def _row(key: str, names: list[str]) -> dict[str, Any]:
        used = [n for n in dict.fromkeys(names) if n]
        return {
            "key": key,
            "offered": [n for n in used if n in reachable],
            "dropped": [n for n in used if n not in reachable],
        }

    global_tools = list(getattr(graph, "globalTools", None) or [])
    if global_tools:
        # Named for the field an author edits, not for a node, because that is
        # what they would go and change.
        out.append(_row("globalTools", global_tools))
    for node in graph.nodes:
        data = getattr(node, "data", None)
        out.append(_row(node.key, list(getattr(data, "tools", None) or [])))
    return out


def _flow_grant_gate(flow: Any, grant: set[str] | frozenset[str]) -> GateResult:
    """G16 — every tool the graph calls is one the card can grant.

    A warning, not a block, for now. The gate found a real defect on the live
    built-in script the day it was written (``handle_dispute`` offers
    ``apply_goodwill``, which no attached pack granted), and a blocking gate
    that fires on the shipping card is a gate nobody can adopt. It is promoted
    once the fleet compiles clean.
    """
    import flow_graph as fg

    if not fg.is_authored(flow):
        return _gate("G16", "flow_grant", "skipped", "empty flow — built-in script")
    rows = node_offers(flow, grant)
    if not rows:
        return _gate("G16", "flow_grant", "skipped", "flow could not be parsed")
    issues = [
        {"node": r["key"], "dropped": r["dropped"]} for r in rows if r["dropped"]
    ]
    # A granted CRM read on ``globalTools`` is still never offered: the runtime
    # strips it before the first turn. Within the grant, and silently gone.
    graph = fg.parse_graph(flow)  # already parsed once by node_offers, so it parses
    stripped = sorted(set(graph.globalTools) & fg.GLOBAL_TOOLS_STRIPPED_AT_RUNTIME)
    if stripped:
        issues.append({"node": "globalTools", "stripped_at_runtime": stripped})
    if not issues:
        return _gate("G16", "flow_grant", "pass", f"{len(rows)} steps within the grant")
    dropped = [i for i in issues if i.get("dropped")]
    names = sorted({n for i in dropped for n in i["dropped"]})
    detail = ""
    if names:
        detail = (
            f"{len(dropped)} step(s) call {len(names)} tool(s) this card cannot grant: "
            + ", ".join(names)
        )
    if stripped:
        detail += ("; " if detail else "") + (
            "globalTools carries CRM reads the runtime strips before the first turn — "
            "put them on the step that may use them: " + ", ".join(stripped)
        )
    return _gate("G16", "flow_grant", "warn", detail, issues)


def _text_walkability_gate(flow: Any, grant: Any, card: Any) -> GateResult:
    """G-F11 — a card with a text mouth can actually be walked on text.

    Until ``flow_walk`` existed this could not be asserted at all: the graph ran
    only under Pipecat, so "does this script work on WhatsApp" had no answer
    short of sending a customer a message. The walker answers it in-process, and
    this gate is that answer at publish time.

    A step is unwalkable when nothing can move the conversation off it on the
    text channel — no granted tool that transitions, no authored edge, and not
    an ``end`` node. On voice such a step is usually still fine, because the
    caller keeps talking and the model keeps choosing; on text it is where the
    thread stops answering.

    Warn-level, on the G16 precedent: a new graph gate that blocks the shipping
    card is a gate nobody can adopt. Promote once the fleet compiles clean.
    """
    import flow_graph as fg

    channels = {str(c).strip().lower() for c in (card.identity.channels or ())}
    if not channels & {"whatsapp", "text", "internal"}:
        return _gate("G-F11", "text_walkability", "skipped", "no text mouth on this card")
    if not fg.is_authored(flow):
        return _gate("G-F11", "text_walkability", "skipped", "empty flow — built-in script")
    try:
        from flow_vars import FlowVariables
        from flow_walk import FlowWalker

        graph = fg.parse_graph(flow)
        walker = FlowWalker(graph, FlowVariables({}))
    except Exception:
        return _gate("G-F11", "text_walkability", "skipped", "flow could not be parsed")

    # The walker owns the text-channel rules -- what counts as an exit, which
    # steps a text mouth passes straight through, and which it can reach at
    # all -- so the gate and the runtime cannot disagree. A step nobody can
    # reach on text (`third_party`, entered only by a voice verb on the
    # outbound leg) is not a text problem; a step that ends the conversation
    # is not stuck; a granted handoff is an exit that leaves the graph.
    granted = set(grant or ())
    reachable, stuck_keys = walker.text_reachable(
        granted=granted, handoffs=bool(getattr(card, "handoffs", None))
    )
    stuck = [{"node": key} for key in stuck_keys]
    if not stuck:
        return _gate(
            "G-F11",
            "text_walkability",
            "pass",
            f"{len(reachable)} of {len(graph.nodes)} steps reachable on text, all walkable",
        )
    return _gate(
        "G-F11",
        "text_walkability",
        "warn",
        f"{len(stuck)} step(s) have no exit on the text channel: "
        + ", ".join(s["node"] for s in stuck),
        stuck,
    )


#: Words in a handoff ``payload_schema`` that name a decision rather than a fact.
#:
#: A hop may carry what happened; it may not carry what an engine decided. If a
#: sending specialist could put ``waiver_amount`` in the packet, the receiving
#: one would quote a rupee figure that ``evaluate_authority`` never approved on
#: its grant — which is laundering, whatever the author meant by it. The
#: receiver calls the engine again and gets its own answer.
_DECISION_WORDS: frozenset[str] = frozenset(
    {
        "amount",
        "waiver",
        "offer",
        "discount",
        "settlement",
        "rupees",
        "inr",
        "callback_at",
        "contact_at",
        "call_at",
        "next_contact",
    }
)


def _carry_gate(card: Any) -> GateResult:
    """G-F7 — a handoff carries facts, never decisions.

    Reads ``card.handoffs[].payload_schema``, which is the only per-edge shape
    an author controls: the fact packet itself is a fixed field list in
    ``agent_core.context.PACKET_FIELDS`` and is not authorable at all. So this
    gate guards the one door left open.

    Warn-level on the G16/G-F11 precedent, and for the same reason: promoting a
    new gate to blocking on the day it lands is how a gate gets disabled instead
    of adopted.
    """
    if not card.handoffs:
        return _gate("G-F7", "carry_is_fact_only", "skipped", "no handoffs on this card")
    findings: list[dict[str, Any]] = []
    for handoff in card.handoffs:
        for field in (handoff.payload_schema or {}):
            lowered = str(field).lower()
            hit = next((w for w in _DECISION_WORDS if w in lowered), None)
            if hit:
                findings.append(
                    {"to": handoff.to_bot_id, "field": str(field), "word": hit}
                )
    if not findings:
        return _gate(
            "G-F7",
            "carry_is_fact_only",
            "pass",
            f"{len(card.handoffs)} handoff(s) carry facts only",
        )
    return _gate(
        "G-F7",
        "carry_is_fact_only",
        "warn",
        f"{len(findings)} handoff field(s) name a decision an engine must make: "
        + ", ".join(f"{f['to']}.{f['field']}" for f in findings),
        findings,
    )


def _handoff_edge_gate(flow: Any, card: Any, grant: Any) -> GateResult:
    """G-F4 — if a step can transfer, the card says where to.

    ``handoff_allowlist`` builds the enforcement set from ``card.handoffs``, so
    a card that grants ``handoff_to_agent`` and declares no handoffs offers the
    model a tool whose every call is refused — a dead end the author cannot see,
    because the Tools tab shows the grant and the canvas shows the step, and
    neither shows the empty allowlist between them.

    Blocking, unlike G-F7: this is not a new judgement about authoring style, it
    is a tool that cannot succeed. The fix is one line on the card.
    """
    import flow_graph as fg

    if "handoff_to_agent" not in set(grant or ()):
        return _gate("G-F4", "handoff_is_an_edge", "skipped", "handoff not granted")
    if card.handoffs:
        return _gate(
            "G-F4",
            "handoff_is_an_edge",
            "pass",
            f"{len(card.handoffs)} authored target(s)",
        )
    if not fg.is_authored(flow):
        # No graph to point at, but the tool is still granted and still dead.
        return _gate(
            "G-F4",
            "handoff_is_an_edge",
            "fail",
            "handoff_to_agent is granted and the card declares no handoff targets",
        )
    try:
        graph = fg.parse_graph(flow)
    except Exception:
        return _gate("G-F4", "handoff_is_an_edge", "skipped", "flow could not be parsed")
    if "handoff_to_agent" in (graph.globalTools or []):
        # Offered everywhere, so naming the nodes would be noise.
        return _gate(
            "G-F4",
            "handoff_is_an_edge",
            "fail",
            "handoff_to_agent is a global tool and the card declares no targets, "
            "so every call is refused",
            [{"node": "globalTools"}],
        )
    steps = sorted(n.key for n in graph.nodes if "handoff_to_agent" in (n.data.tools or []))
    if not steps:
        return _gate("G-F4", "handoff_is_an_edge", "pass", "no step offers a transfer")
    return _gate(
        "G-F4",
        "handoff_is_an_edge",
        "fail",
        f"{len(steps)} step(s) offer handoff_to_agent and the card declares no "
        "targets, so every call is refused: " + ", ".join(steps),
        [{"node": key} for key in steps],
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
    skip_eval: bool = False,
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
        out.append(_gate("G-OB1", "missions_declared", "skipped", "no card"))
        out.append(_gate("G-OB9", "outbound", "skipped", "no card"))
        return out
    ob = card.outbound
    if not ob.dials:
        # G-OB9 too: a card requiring the outbound suite while dialling nothing
        # produced no gate at all, not even a skipped one, so the requirement
        # looked satisfied.
        out.append(_gate("G-OB1", "missions_declared", "skipped", "inbound-only card"))
        out.append(_gate("G-OB9", "outbound", "skipped", "inbound-only card"))
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

        cap = contact_policy.tenant_daily_cap()
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
    # that silently does nothing, which is worse than no rule at all. The
    # objective's success/partial lists and each cadence's stop_on are outcome
    # codes too, and the editor's copy said this gate checked them; it did not.
    for objective in ob.objectives:
        for field in ("success", "partial"):
            for code in getattr(objective, field) or []:
                if code not in OUTCOME_CODES:
                    issues.append(
                        {
                            "gate": "G-OB6",
                            "objective": objective.key,
                            "problem": f"{field} names unknown outcome code {code!r}",
                        }
                    )
    for cadence in ob.cadences:
        for code in cadence.stop_on or []:
            if code not in OUTCOME_CODES:
                issues.append(
                    {"gate": "G-OB6", "problem": f"cadence {cadence.name!r} stops on unknown outcome code {code!r}"}
                )
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
        # No exemption for "default": a card that defines no ladder by that
        # name falls back to the built-in one, which is a different retry
        # policy from anything the author wrote down.
        if objective.cadence not in defined:
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
        _eval_gate(
            "G-OB9",
            "outbound",
            outbound_eval_gate_enabled(),
            eval_report,
            card,
            skip=skip_eval,
        )
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


# G12's accepted set is the card's own vocabulary. Restating it here meant a
# canary naming only the outbound triggers filtered to empty and failed the
# gate with "canary split requires auto_rollback".
_ROLLBACK_TRIGGERS = ROLLBACK_TRIGGERS


@dataclasses.dataclass
class _Compile:
    """What the gate phases share: the compile inputs every phase reads and
    the locals the earlier phases produce for the later ones."""

    bot_id: str
    flow: Any
    catalog_names: set[str]
    known_bot_ids: set[str]
    skip_eval_gates: bool
    dump: dict[str, Any]
    gates: list[GateResult] = dataclasses.field(default_factory=list)
    card: AgentCard | None = None
    tools: list[str] = dataclasses.field(default_factory=list)
    idle: list[str] = dataclasses.field(default_factory=list)
    skill_tokens: int = 0
    idle_count: int = 0
    tool_cap: int = 0
    packs: list[SkillPack] = dataclasses.field(default_factory=list)
    unresolved: list[str] = dataclasses.field(default_factory=list)
    #: Filled by the tool intersection at G4, reported by G10.
    connector_bind_issues: list[dict[str, Any]] = dataclasses.field(default_factory=list)


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
    content_key: str | None = None,
    attached_skills: list[SkillPack] | None = None,
    traffic_pct: int | None = None,
    auto_rollback: list[str] | None = None,
    has_publish: bool | None = None,
    a2a_cert_ok: bool | None = None,
    voice_short_name: str | None = None,
    voice_locale: str | None = None,
    card_locales: list[str] | None = None,
    voice_provider: str | None = None,
    bound_tts_providers: set[str] | frozenset[str] | None = None,
    prompt: str | None = None,
    prompt_guardrails: dict[str, Any] | None = None,
    skip_eval_gates: bool = False,
) -> CompileReport:
    """Static gates always run. Eval gates honour their flags. Phases run in
    the order the report lists their gates -- the Ship tab renders it."""
    st = _Compile(
        bot_id=bot_id,
        flow=flow,
        catalog_names=catalog_names,
        known_bot_ids=known_bot_ids,
        skip_eval_gates=skip_eval_gates,
        dump=card_raw if isinstance(card_raw, dict) else {},
    )
    _identity_gates(st, card_raw=card_raw)
    _tool_gates(st, channel_tools=channel_tools, attached_skills=attached_skills)
    _eval_gates(
        st,
        eval_report=eval_report,
        redteam_report=redteam_report,
        twin_report=twin_report,
        outbound_report=outbound_report,
        content_key=content_key,
    )
    _ship_gates(
        st,
        traffic_pct=traffic_pct,
        auto_rollback=auto_rollback,
        a2a_cert_ok=a2a_cert_ok,
    )
    _flow_gates(
        st,
        outbound_report=outbound_report,
        prompt=prompt,
        prompt_guardrails=prompt_guardrails,
        has_publish=has_publish,
        voice_short_name=voice_short_name,
        voice_locale=voice_locale,
        card_locales=card_locales,
        voice_provider=voice_provider,
        bound_tts_providers=bound_tts_providers,
    )
    return CompileReport(
        bot_id=bot_id,
        gates=st.gates,
        effective_tools=st.tools,
        idle_tools=st.idle,
        idle_voice_tools=st.idle_count,
        voice_tool_cap=st.tool_cap,
        skill_description_tokens=st.skill_tokens,
        mission_entries=_mission_entries(flow),
        card=st.dump,
    )


def _identity_gates(st: _Compile, *, card_raw: Any) -> None:
    """G0 schema, G1 flowValid, G2 flow included, G3 policy engines."""
    gates, card, flow = st.gates, st.card, st.flow

    # G0 schema
    if not is_authored(card_raw):
        gates.append(_gate("G0", "schema", "skipped", "empty agent_card — legacy mouth"))
    else:
        try:
            card = st.card = AgentCard.model_validate(card_raw)
            st.dump = card.model_dump(mode="json")
            from agent_core.cards.schema import retired_gate_requires

            retired = retired_gate_requires(card_raw)
            if retired:
                gates.append(
                    _gate(
                        "G0",
                        "schema",
                        "warn",
                        "human_gates.require 'floor'/'both' is retired (no floor ledger exists); "
                        "read as 'identity' for: " + ", ".join(retired),
                    )
                )
            else:
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
        issues: list[Any] = []
        detail = str(exc)
        if isinstance(exc, fg.FlowInvalidError):
            payload = exc.http_detail()
            issues = list(payload.get("issues") or [])
            detail = str(payload.get("code") or detail)
        gates.append(_gate("G1", "flowValid", "fail", detail, issues))

    # G2 flow included (authored graphs must not have been dropped)
    import flow_graph as fg

    if fg.is_authored(flow):
        gates.append(_gate("G2", "flow_persisted", "pass"))
    else:
        gates.append(
            _gate("G2", "flow_persisted", "pass", "empty flow — built-in script")
        )

    # G3 -- the policy engines stay on the card's locked list. That is the
    # whole gate: the "binding" half compared six `Literal["required"]` fields
    # against "required" and could not fail.
    if card is None:
        gates.append(_gate("G3", "policy_bindings", "skipped", "no card"))
    else:
        locked_set = set(card.tools.locked)
        missing_locked = [n for n in LOCKED_POLICY_ENGINES if n not in locked_set]
        if missing_locked:
            gates.append(
                _gate(
                    "G3",
                    "policy_bindings",
                    "fail",
                    "engines cannot be unbound",
                    [{"missing_locked": missing_locked}],
                )
            )
        else:
            gates.append(_gate("G3", "policy_bindings", "pass"))


def _tool_gates(
    st: _Compile,
    *,
    channel_tools: set[str] | None,
    attached_skills: list[SkillPack] | None,
) -> None:
    """G4 effective tools, G5 handoffs, G6 latency."""
    gates, card, bot_id = st.gates, st.card, st.bot_id
    catalog_names, known_bot_ids = st.catalog_names, st.known_bot_ids

    # G4 effective tools ⊆ catalog; locked mouth tools included
    if card is None:
        gates.append(_gate("G4", "tools", "skipped", "no card"))
    else:
        st.packs, st.unresolved = _resolve_attached(card, attached_skills)
        packs = st.packs
        unknown = [n for n in card.tools.include if n not in catalog_names]
        # Connector binding happens inside the tool intersection. When it fails
        # the compile continues without the ext.* names, and G10 below reports
        # why instead of leaving the author a card that looks connector-less.
        # The one grant formula (ADR-0001): ToolGrant.for_card calls this same
        # function with the same inputs; the gate passes `issues` so a failed
        # connector bind reaches the author through G10.
        tools = st.tools = skill_effective_tools(
            card,
            catalog_names=catalog_names,
            channel_tools=channel_tools,
            attached_skills=packs if (card.skills or attached_skills is not None) else None,
            issues=st.connector_bind_issues,
        )
        idle = st.idle = idle_offered_tools(
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
        skill_tokens = st.skill_tokens = description_prefix_tokens(packs)
        # `max_voice_tools` caps what a *call* carries, so the count is of what
        # a call renders. No caller passes `channel_tools`, deliberately — a
        # publish gate reasons about every channel at once — so the text-only
        # specs are in `idle` and were being charged against a voice latency
        # budget they never spend. A catalog name the catalog says does not
        # render on voice is not idle voice weight.
        #
        # Only catalog names are filtered: an ext.* connector tool is not a
        # spec, and whether those belong in this count is a separate question
        # this line does not answer either way.
        from agent_core.tools.catalog import CATALOG
        from agent_core.tools.schema import CHANNEL_VOICE

        voice_renderable = {s.name for s in CATALOG.for_channel(CHANNEL_VOICE)}
        catalog_specs = set(CATALOG.specs)
        idle_count = st.idle_count = len(
            [
                n
                for n in idle
                if n not in PLATFORM_SKILL_TOOLS
                and not (n in catalog_specs and n not in voice_renderable)
            ]
        )
        cap = card.tools.max_voice_tools
        st.tool_cap = cap
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


def _eval_gates(
    st: _Compile,
    *,
    eval_report: dict[str, Any] | None,
    redteam_report: dict[str, Any] | None,
    twin_report: dict[str, Any] | None,
    outbound_report: dict[str, Any] | None,
    content_key: str | None,
) -> None:
    """G7 regression, G8 red-team, G-F14 provenance, G11 twin."""
    gates, card, skip_eval_gates = st.gates, st.card, st.skip_eval_gates

    # G7 regression
    gates.append(
        _eval_gate(
            "G7",
            "regression",
            eval_gate_enabled(),
            eval_report,
            card,
            skip=skip_eval_gates,
        )
    )
    # G8 red-team
    gates.append(
        _eval_gate(
            "G8",
            "redteam",
            redteam_gate_enabled(),
            redteam_report,
            card,
            skip=skip_eval_gates,
        )
    )
    # G-F14 -- which content those verdicts are about.
    gates.append(
        _provenance_gate(
            card,
            {"regression": eval_report, "redteam": redteam_report, "outbound": outbound_report},
            content_key,
        )
    )
    # G11 twin — blocking in Phase 4 when twin is in card.eval.require.
    # Default cards require regression+redteam only; skip honestly, never fake-green.
    twin_required = bool(card and "twin" in (card.eval.require or []))
    gates.append(
        _eval_gate(
            "G11",
            "twin",
            twin_required,
            twin_report,
            card,
            skip=skip_eval_gates,
            where=" — run it from the Sandbox inspector's Twin tab",
        )
    )


def _ship_gates(
    st: _Compile,
    *,
    traffic_pct: int | None,
    auto_rollback: list[str] | None,
    a2a_cert_ok: bool | None,
) -> None:
    """G9 signed skills, G10 connectors, G12 canary, G13 A2A."""
    gates, card, bot_id, catalog_names = st.gates, st.card, st.bot_id, st.catalog_names
    packs, unresolved, skip_eval_gates = st.packs, st.unresolved, st.skip_eval_gates
    connector_bind_issues = st.connector_bind_issues

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
        # The author's declared scope, deliberately not the grant: a pack that
        # names a tool the card never included is an authoring error to report,
        # and the grant would already have dropped it in silence.
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
            # Publish is production: a sandbox-only connector fails here, not
            # on the first live call.
            if str(conn.get("allowedEnv") or "sandbox") not in ("both", "production"):
                g10_issues.append({"env_not_allowed": ref.connector_id})
            outside = [p for p in prefixes if not any(p.startswith(r) for r in conn.get("allowPrefixes") or [])]
            if outside:
                g10_issues.append({"prefix_outside_registry": ref.connector_id, "prefixes": outside})
            if conn["kind"] == "remote_mcp":
                url = str(conn.get("url") or "")
                if not url.startswith("https://"):
                    g10_issues.append({"url_not_https": ref.connector_id})
            if not conn.get("dataClass"):
                g10_issues.append({"data_class_missing": ref.connector_id})
            if conn.get("health") in {"down", "blocked"}:
                g10_issues.append({"unhealthy": ref.connector_id, "health": conn.get("health")})
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
    if skip_eval_gates:
        gates.append(
            _gate("G12", "canary", "skipped", "rollback of a previously published version")
        )
    elif pct == 100:
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


def _flow_gates(
    st: _Compile,
    *,
    outbound_report: dict[str, Any] | None,
    prompt: str | None,
    prompt_guardrails: dict[str, Any] | None,
    has_publish: bool | None,
    voice_short_name: str | None,
    voice_locale: str | None,
    card_locales: list[str] | None,
    voice_provider: str | None,
    bound_tts_providers: set[str] | frozenset[str] | None,
) -> None:
    """G-OB1..9 outbound, G-LINT, G14 publish, G15/G17 voice, G18 connector
    offer, G16/G-F11/G-F4/G-F7 the graph against the grant."""
    gates, card, flow, tools, packs = st.gates, st.card, st.flow, st.tools, st.packs
    catalog_names, known_bot_ids = st.catalog_names, st.known_bot_ids
    skip_eval_gates = st.skip_eval_gates

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
            skip_eval=skip_eval_gates,
        )
    )

    # G-LINT — deterministic prompt lint errors block publish. Warns stay
    # visible in the editor; they do not fail this gate.
    if skip_eval_gates:
        gates.append(
            _gate("G-LINT", "prompt_lint", "skipped", "rollback of a previously published version")
        )
    elif prompt is None:
        gates.append(_gate("G-LINT", "prompt_lint", "skipped", "no prompt supplied"))
    else:
        from prompt_lint import lint_prompt

        findings = lint_prompt(prompt, prompt_guardrails or {}, include_llm=False)
        errors = [f for f in findings if f.get("severity") == "error"]
        if errors:
            gates.append(
                _gate(
                    "G-LINT",
                    "prompt_lint",
                    "fail",
                    f"{len(errors)} lint error(s)",
                    errors,
                )
            )
        else:
            gates.append(_gate("G-LINT", "prompt_lint", "pass"))

    # G14 agent.publish — dry-run with no actor skips so four-card unit compile stays green.
    if has_publish is None:
        gates.append(_gate("G14", "agent_publish", "skipped", "no actor — dry-run"))
    elif has_publish:
        gates.append(_gate("G14", "agent_publish", "pass"))
    else:
        gates.append(_gate("G14", "agent_publish", "fail", "actor lacks agent.publish"))

    # G15 voice locale. Reads the mouth columns rather than the card.
    gates.append(voice_locale_gate(voice_short_name, voice_locale, card_locales, gate=_gate))

    # G17 the voice's vendor against what this bot can speak through. Beside
    # G15 because they read the same mouth columns; separate from it because a
    # wrong language is a warning and an unspeakable voice is a dropped call.
    gates.append(
        voice_provider_gate(voice_short_name, voice_provider, bound_tts_providers, gate=_gate)
    )

    # G18 the other half of a connector binding: G10 says it is allowed, this
    # says whether anything can actually call it.
    gates.append(_connector_offer_gate(card, packs))

    # G16 the graph and the grant. Last because it is the only gate that reads
    # both, and the second that can warn.
    if card is None:
        gates.append(_gate("G16", "flow_grant", "skipped", "no card"))
        gates.append(_gate("G-F11", "text_walkability", "skipped", "no card"))
        gates.append(_gate("G-F4", "handoff_is_an_edge", "skipped", "no card"))
        gates.append(_gate("G-F7", "carry_is_fact_only", "skipped", "no card"))
    else:
        gates.append(_flow_grant_gate(flow, set(tools)))
        gates.append(_text_walkability_gate(flow, tools, card))
        gates.append(_handoff_edge_gate(flow, card, tools))
        gates.append(_carry_gate(card))


def _eval_gate(
    gate: str,
    name: str,
    flag_on: bool,
    report: dict[str, Any] | None,
    card: AgentCard | None,
    *,
    skip: bool = False,
    where: str = "",
) -> GateResult:
    """``where`` names the screen that can satisfy this gate, when it is not the
    Evals tab. Only the Twin needs it: the tab's suites write ``eval_reports``
    and G11 reads ``twin_runs``, so an operator who ticks Twin and then runs
    everything in front of them never moves this gate.
    """
    if skip:
        return _gate(gate, name, "skipped", "rollback of a previously published version")
    if not flag_on:
        return _gate(gate, name, "skipped", f"{name} gate flag is off")
    required = (card.eval.require if card else []) or []
    if name not in required and card is not None:
        return _gate(gate, name, "skipped", f"{name} not in card.eval.require")
    if report is None:
        return _gate(gate, name, "fail", f"{name} suite has not been run{where}")
    status = str(report.get("status") or "")
    if status == "pass":
        # A pass carried over by content: the same words, judged on another
        # row. Said so, never "skipped".
        if report.get("cached"):
            since = str(report.get("created_at") or "")[:19]
            return _gate(gate, name, "pass", f"cached {report.get('id')} (unchanged since {since})")
        return _gate(gate, name, "pass", report.get("id") or "")
    return _gate(gate, name, "fail", status or "eval_fail", [report])


def _provenance_gate(
    card: AgentCard | None,
    reports: dict[str, dict[str, Any] | None],
    candidate_key: str | None,
) -> GateResult:
    """G-F14 -- every required report says what it was run against, and it is
    this. Informational beside G7/G8: those block on the verdict, this one
    names whether the verdict is about this content at all."""
    if card is None or not candidate_key:
        return _gate("G-F14", "eval_provenance", "skipped", "no card or no content key")
    # Only the reports that exist: a required kind with no report is G7/G8's
    # finding, not a provenance one.
    present = {k: r for k, r in reports.items() if k in (card.eval.require or []) and r is not None}
    if not any(k in reports for k in (card.eval.require or [])):
        return _gate("G-F14", "eval_provenance", "skipped", "no suite required")
    unkeyed = [k for k, r in present.items() if not r.get("content_key")]
    other = [k for k, r in present.items() if r.get("content_key") and r["content_key"] != candidate_key]
    if other:
        return _gate(
            "G-F14",
            "eval_provenance",
            "fail",
            f"{', '.join(other)} report(s) were run against different content",
            [{"kind": k, "report": present[k].get("id")} for k in other],
        )
    if unkeyed:
        return _gate(
            "G-F14",
            "eval_provenance",
            "warn",
            f"{', '.join(unkeyed)} report(s) predate content keys -- re-run to record what they judged",
            [{"kind": k, "report": present[k].get("id")} for k in unkeyed],
        )
    return _gate("G-F14", "eval_provenance", "pass", f"content {candidate_key[:12]}")


def assert_publishable(report: CompileReport) -> CompileReport:
    if not report.ok:
        raise CompileError(report)
    return report
