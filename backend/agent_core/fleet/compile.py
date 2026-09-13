"""Deterministic wrapper around ``compile_card``.

Does not replace the publish compiler. Builds the persisted artefact from
the same inputs the live grant uses, so a one-member fleet is byte-identical
to today's prompt, tools, flow and attribution.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from typing import Any, Iterable

import flow_graph as fg
from agent_core.cards.compile import CompileReport, GateResult, _gate, node_offers
from agent_core.cards.schema import AgentCard, is_authored, parse_card
from agent_core.fleet.schema import (
    ChannelGrant,
    CompiledBundle,
    CompiledHashes,
    FrozenConnector,
    NodeOffer,
    PinnedSkill,
)
from agent_core.skills.pack import SkillPack
from agent_core.tools.grant import TEXT, VOICE, ToolGrant

logger = logging.getLogger(__name__)


def canonical_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical_dumps(obj).encode("utf-8")).hexdigest()


def bundle_hash_valid(bundle: CompiledBundle) -> bool:
    payload = bundle.model_dump(mode="json")
    claimed = str(payload.pop("bundle_hash", "") or "")
    return bool(claimed) and claimed == digest(payload)


def _member_grant(card_raw: Any) -> set[str]:
    """One member's voice grant, from its own published card.

    Its *own*: the whole point of the hop is that the receiving specialist
    brings its own tools. Signed packs are deliberately not folded in yet — no
    member attaches one, and a grant that quietly widened from a pack the fleet
    compiler never read would be the same bug in a new place.
    """
    # ponytail: card ∪ locked only. Add packs when a member actually attaches one.
    try:
        card = parse_card(card_raw) if is_authored(card_raw) else None
    except Exception:
        card = None
    if card is None:
        return set()
    return set(ToolGrant.for_card(card, (), channel=VOICE).allowed)


def _merge_members(
    *,
    primary_bot_id: str,
    primary_flow: dict[str, Any],
    primary_grant: set[str],
    members: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, str], dict[str, list[str]]]:
    """Fold each member's graph into one namespaced graph.

    Returns ``(fleet_flow, entry_by_specialist, grant_by_specialist)``. With no
    members the first is empty and the other two describe the primary alone, so
    a one-member fleet compiles to today's behaviour and the runtime falls back
    to the authored flow.

    The namespace is the **bot id**, and this is the only place in the tree that
    writes one. Everything a hop touches — ``target_bot_id``, the handoff
    allowlist, ``CardHandoff.to_bot_id`` — is already a bot id, so a second
    vocabulary would be a lookup that can be wrong.
    """
    if not members or not primary_flow.get("nodes"):
        return {}, {}, {}

    def entry_of(graph: dict[str, Any], bot_id: str) -> str:
        # The primary keeps its start node. A member's start is its greeting,
        # which is exactly where a hop must not land, so a member's default
        # entry is where its business begins (an authored ``entry_node`` on
        # the handoff overrides this in ``compile_bundle``).
        nodes = graph.get("nodes") or []
        start = next(
            (n for n in nodes if isinstance(n, dict) and (n.get("data") or {}).get("isStart")),
            None,
        )
        if start is not None:
            return str(start.get("key") or "")
        return fg.business_entry(graph)

    merged_nodes: list[dict[str, Any]] = []
    merged_edges: list[dict[str, Any]] = []
    entries: dict[str, str] = {}
    grants: dict[str, list[str]] = {primary_bot_id: sorted(primary_grant)}

    for bot_id, graph, grant, is_primary in [
        (primary_bot_id, primary_flow, primary_grant, True),
        *(
            (str(m.get("bot_id") or ""), m.get("flow") or {}, _member_grant(m.get("card")), False)
            for m in sorted(members, key=lambda m: str(m.get("bot_id") or ""))
        ),
    ]:
        if not bot_id or not (graph.get("nodes") or []):
            continue
        scoped = fg.namespaced(graph, bot_id, keep_start=is_primary)
        merged_nodes.extend(scoped.get("nodes") or [])
        merged_edges.extend(scoped.get("edges") or [])
        entries[bot_id] = entry_of(scoped, bot_id)
        grants[bot_id] = sorted(grant)

    if len(entries) < 2:  # nothing actually merged
        return {}, {}, {}
    return (
        {"version": 1, "globalTools": [], "nodes": merged_nodes, "edges": merged_edges},
        entries,
        grants,
    )


def compile_bundle(
    *,
    report: CompileReport,
    prompt: str = "",
    persona: dict[str, Any] | None = None,
    guardrails: dict[str, Any] | None = None,
    flow: Any = None,
    prompt_version_id: str | None = None,
    attached_skills: list[SkillPack] | None = None,
    source_ids: dict[str, str] | None = None,
    members: Sequence[dict[str, Any]] | None = None,
) -> CompiledBundle:
    """Fold a ``CompileReport`` plus mouth columns into one hashed artefact."""
    card_dump = report.card if isinstance(report.card, dict) else {}
    persona = persona if isinstance(persona, dict) else {}
    guardrails = guardrails if isinstance(guardrails, dict) else {}
    flow_obj = flow if isinstance(flow, dict) else {}
    packs = tuple(attached_skills or ())
    card: AgentCard | None = None
    if is_authored(card_dump):
        try:
            card = parse_card(card_dump)
        except Exception:
            card = None

    skills = [
        PinnedSkill(
            skill_id=p.slug,
            version=p.version,
            pin="exact",
            content_hash=p.content_hash,
            signed=bool(p.signed),
            mouth=list(p.mouth or []),
        )
        for p in packs
    ]
    connectors: list[FrozenConnector] = []
    if card is not None:
        for conn in card.connectors:
            dumped = conn.model_dump(mode="json")
            registry: dict[str, Any] = {}
            try:
                from agent_core.connectors.persist import get_connector

                registry = get_connector(conn.connector_id) or {}
            except Exception:
                logger.exception(
                    "connector registry unavailable while freezing %s",
                    conn.connector_id,
                )
            prefixes = list(conn.allow_prefixes or registry.get("allowPrefixes") or [])
            frozen_names = sorted(
                name
                for name in report.effective_tools
                if name.startswith("ext.")
                and (not prefixes or any(name.startswith(prefix) for prefix in prefixes))
            )
            registry_contract = {
                key: registry.get(key)
                for key in (
                    "id",
                    "slug",
                    "kind",
                    "url",
                    "allowPrefixes",
                    "dataClass",
                    "toolsCache",
                    "status",
                )
            }
            connectors.append(
                FrozenConnector(
                    connector_id=conn.connector_id,
                    allow_prefixes=prefixes,
                    tool_names=frozen_names,
                    digest=digest(
                        {"binding": dumped, "registry": registry_contract}
                    ),
                    voice_supported=False,
                )
            )

    frozen_connector_tools = sorted(
        {name for connector in connectors for name in connector.tool_names}
    )
    grants: list[ChannelGrant] = []
    for channel in (VOICE, TEXT):
        grant = ToolGrant.for_card(
            card,
            packs,
            channel=channel,
            frozen_connector_tools=frozen_connector_tools,
        )
        grants.append(
            ChannelGrant(
                channel=channel,
                allowed=sorted(grant.allowed),
                offered=list(grant.offer()),
            )
        )

    # The same intersection G16 reports, from the same helper, so the gate that
    # certified the publish and the artefact the runtime reads cannot disagree
    # about what a step can call. Voice, because a flow node is a voice node.
    voice_grant = next(
        (set(g.allowed) for g in grants if g.channel == VOICE), set(report.effective_tools)
    )
    # The merged fleet graph, and the per-member grants that go with it. Empty
    # for a one-member fleet, which is every card today: the runtime then reads
    # `flow` and the channel grant exactly as before.
    fleet_flow, entry_by_specialist, by_specialist = _merge_members(
        primary_bot_id=report.bot_id,
        primary_flow=flow_obj,
        primary_grant=voice_grant,
        members=members or (),
    )
    # The authored landing wins. `_merge_members` names each member's first
    # node; both mouths read the card's `entry_node` first and fall back to
    # this map, so the map used to carry the fallback (`greet_disclose`) even
    # when the hop was authored to land elsewhere -- a truthful map and the
    # fallback agree.
    if card is not None and entry_by_specialist:
        keys = {str(n.get("key")) for n in (fleet_flow.get("nodes") or []) if isinstance(n, dict)}
        for hop in card.handoffs:
            if hop.to_bot_id in entry_by_specialist and hop.entry_node:
                scoped = fg.resolve_key(keys, hop.entry_node, namespace=hop.to_bot_id)
                if scoped:
                    entry_by_specialist[hop.to_bot_id] = scoped
    # Offers are reported for whatever graph the runtime will actually walk.
    offers = [NodeOffer(**row) for row in node_offers(fleet_flow or flow_obj, voice_grant)]

    human_gates = []
    if card is not None:
        human_gates = [g.model_dump(mode="json") for g in card.human_gates]

    hashes = CompiledHashes(
        prompt=digest(prompt or ""),
        persona=digest(persona),
        guardrails=digest(guardrails),
        flow=digest(flow_obj),
        card=digest(card_dump),
    )
    draft = CompiledBundle(
        bot_id=report.bot_id,
        prompt_version_id=prompt_version_id,
        source_ids=dict(source_ids or {}),
        skills=skills,
        connectors=connectors,
        grants=grants,
        node_offers=offers,
        grant_by_specialist=by_specialist,
        human_gates=human_gates,
        hashes=hashes,
        gates=[g.model_dump(mode="json") for g in report.gates],
        prompt=prompt or "",
        persona=persona,
        guardrails=guardrails,
        flow=flow_obj,
        fleet_flow=fleet_flow,
        entry_by_specialist=entry_by_specialist,
        member_versions={
            str(m.get("bot_id")): str(m.get("prompt_version_id"))
            for m in (members or ())
            if m.get("bot_id") and m.get("prompt_version_id")
        },
        agent_card=card_dump,
        bundle_hash="",
    )
    hashed = draft.model_dump(mode="json")
    hashed.pop("bundle_hash", None)
    return draft.model_copy(update={"bundle_hash": digest(hashed)})


def parity_report(
    *,
    live_prompt: str,
    live_flow: dict[str, Any] | None,
    live_tools: Iterable[str],
    bundle: CompiledBundle,
    live_persona: dict[str, Any] | None = None,
    live_guardrails: dict[str, Any] | None = None,
    channel: str = "voice",
    bot_id: str | None = None,
    prompt_version_id: str | None = None,
) -> dict[str, Any]:
    """Compare a live mouth against the persisted bundle. No traffic change."""
    grant = bundle.grant_for(channel)
    live_set = set(live_tools)
    bundle_set = set(grant.allowed) if grant else set()
    mismatches: list[str] = []
    if (live_prompt or "") != (bundle.prompt or ""):
        mismatches.append("prompt")
    if digest(live_persona or {}) != bundle.hashes.persona:
        mismatches.append("persona")
    if digest(live_guardrails or {}) != bundle.hashes.guardrails:
        mismatches.append("guardrails")
    if digest(live_flow or {}) != bundle.hashes.flow:
        mismatches.append("flow")
    if live_set != bundle_set:
        mismatches.append("tools")
    if bot_id is not None and bot_id != bundle.bot_id:
        mismatches.append("bot_id")
    if (
        prompt_version_id is not None
        and prompt_version_id != bundle.prompt_version_id
    ):
        mismatches.append("prompt_version_id")
    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "bundle_hash": bundle.bundle_hash,
        "live_only": sorted(live_set - bundle_set),
        "bundle_only": sorted(bundle_set - live_set),
    }


# ---------------------------------------------------------------------------
# Fleet gates
#
# These need the *merged* graph, which is why they live here and not in
# cards/compile.py. Their ids are registered in that module's `_GATE_NAMES`
# all the same: the id space is one space wherever the gate runs, and `_gate`
# asserts against it.
# ---------------------------------------------------------------------------

#: Nodes every member must be able to reach, whoever is speaking.
#:
#: `resolve_key` tries the speaking member's namespace first, so a duplicated
#: terminal is safe *if every namespace has one* and fatal if only some do: a
#: member without its own `call_ended` resolves through the third tier into a
#: sibling's, or -- once two siblings own one -- resolves to nothing at all,
#: because `resolve_key` calls that ambiguous and returns None. A caller whose
#: `end_call` returns None is a caller nobody can hang up on.
_TERMINAL_KEYS: frozenset[str] = frozenset(
    {"call_ended", "pre_close", "terminate_politely", "escalate_close"}
)

#: Tools that change a record about the borrower. A path that reaches one
#: of these before ``verify_identity`` is the thing G-F3 refuses. The catalog's
#: ``entity`` marks the six that create a CRM row; the rest are writes the
#: skill layer already gates for the same reason (``SKILL_GATED_TOOLS``).
_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "apply_goodwill",
        "set_contact_preference",
        "capture_nonpayment_reason",
        "decline_offer",
        "opt_out",
    }
)
_VERIFY_TOOLS: frozenset[str] = frozenset({"verify_identity", "identify_customer"})


def _write_tool_names() -> frozenset[str]:
    from agent_core.tools import CATALOG

    return _WRITE_TOOLS | {name for name, spec in CATALOG.specs.items() if getattr(spec, "entity", None)}


def _closure_gate(
    *,
    primary_bot_id: str,
    card: AgentCard | None,
    members: Sequence[dict[str, Any]],
    entries: dict[str, str],
) -> GateResult:
    """G-F1: every declared hop lands in a member that has a graph, and every
    member the merge produced is reachable from the primary over handoffs."""
    graphs_by_bot = {str(m.get("bot_id") or ""): m for m in members}
    handoffs_of: dict[str, list[str]] = {
        primary_bot_id: [h.to_bot_id for h in (card.handoffs if card else [])],
    }
    for bot_id, member in graphs_by_bot.items():
        raw_card = member.get("card")
        raw = raw_card if isinstance(raw_card, dict) else {}
        handoffs_of[bot_id] = [
            str(h.get("to_bot_id") or "") for h in (raw.get("handoffs") or []) if isinstance(h, dict)
        ]
    problems: list[dict[str, Any]] = []
    for target in handoffs_of[primary_bot_id]:
        if target and target not in entries:
            problems.append({"member": target, "why": "handoff target has no published graph to land in"})
    seen = {primary_bot_id}
    frontier = [primary_bot_id]
    while frontier:
        bot = frontier.pop()
        for target in handoffs_of.get(bot, []):
            if target in entries and target not in seen:
                seen.add(target)
                frontier.append(target)
    for namespace in sorted(entries):
        if namespace not in seen:
            problems.append({"member": namespace, "why": "in the bundle but no handoff reaches it"})
    return _gate(
        "G-F1",
        "closure",
        "fail" if problems else "pass",
        (
            f"{len(problems)} member(s) unreachable or graphless"
            if problems
            else f"{len(entries)} member(s) reachable, each with a graph"
        ),
        problems,
    )


def _identity_gate(*, fleet_flow: dict[str, Any], entries: dict[str, str]) -> GateResult:
    """G-F3: no path from the door's start reaches a write before verification.

    Walks the merged graph over authored edges, the built-in tool transitions
    (``flow_graph.TRANSITIONS``, resolved in the speaking namespace) and the
    hops (``handoff_to_agent`` lands on each member's entry). A node that
    offers ``verify_identity`` marks the paths through it verified; a node
    offering a write on an unverified path is the finding.
    """
    nodes = {str(n.get("key")): n for n in fleet_flow.get("nodes") or [] if isinstance(n, dict)}
    by_id = {str(n.get("id")): str(n.get("key")) for n in nodes.values()}
    writes = _write_tool_names()
    edges: dict[str, set[str]] = {k: set() for k in nodes}
    for edge in fleet_flow.get("edges") or []:
        src, dst = by_id.get(str(edge.get("source"))), by_id.get(str(edge.get("target")))
        if src in edges and dst:
            edges[src].add(dst)
    for key, node in nodes.items():
        namespace = fg.split_key(key)[0]
        tools = list((node.get("data") or {}).get("tools") or [])
        for tool in tools:
            for target in fg.TRANSITIONS.get(tool, ()):
                resolved = fg.resolve_key(nodes, target, namespace=namespace)
                if resolved:
                    edges[key].add(resolved)
                    break
            if tool == "handoff_to_agent":
                for member, entry in entries.items():
                    if member != namespace and entry in nodes:
                        edges[key].add(entry)

    start = next(
        (k for k, n in nodes.items() if (n.get("data") or {}).get("isStart")),
        None,
    )
    if start is None:
        return _gate("G-F3", "identity_before_writes", "skipped", "the merged graph has no start node")

    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, bool]] = set()
    frontier: list[tuple[str, bool]] = [(start, False)]
    while frontier:
        key, verified = frontier.pop()
        if (key, verified) in seen:
            continue
        seen.add((key, verified))
        tools = set((nodes[key].get("data") or {}).get("tools") or [])
        if not verified and tools & writes:
            findings.append({"node": key, "writes": sorted(tools & writes)})
        now_verified = verified or bool(tools & _VERIFY_TOOLS)
        for nxt in edges.get(key, ()):
            frontier.append((nxt, now_verified))
    return _gate(
        "G-F3",
        "identity_before_writes",
        "fail" if findings else "pass",
        (
            f"{len(findings)} step(s) offer a write on a path with no verification"
            if findings
            else "every write sits behind verify_identity on every path from the door"
        ),
        findings,
    )


#: What a door may hold.
#:
#: An allowlist, not a deny-list, because a deny-list fails open on the next
#: tool anyone adds to the catalog. `ToolSpec.entity` was the tempting derived
#: signal -- "this tool creates a CRM record" -- but it marks only six tools and
#: misses `apply_goodwill`, which moves money. A gate that would let a door
#: write off a balance is worse than one with a list in it.
#:
#: The rule the list encodes: a door may identify the caller, read what it needs
#: to route, answer a general question, record what happened, and leave. It may
#: not change the borrower's record, and it may not widen its own tool surface
#: at runtime -- which is why `load_skill` and `run_skill_script` are absent.
_DOOR_TOOLS: frozenset[str] = frozenset(
    {
        "verify_identity",
        "identify_customer",
        "capture_call_goal",
        "get_customer_context",
        "search_knowledge_base",
        "add_customer_note",
        "handoff_to_agent",
        "escalate_to_human",
        # The one write a door may make. A borrower's calling window is said
        # to whoever picks up, and the dialler reads it from the consent
        # record -- a handoff brief is not that record. Conduct, not business.
        "set_contact_preference",
    }
)


def _namespace_locals(fleet_flow: dict[str, Any]) -> dict[str, set[str]]:
    """namespace -> the local node keys it owns."""
    out: dict[str, set[str]] = {}
    for node in fleet_flow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        namespace, local = fg.split_key(str(node.get("key") or ""))
        if namespace:
            out.setdefault(namespace, set()).add(local)
    return out


def _bound_as_entry(bot_id: str) -> bool:
    """Is an enabled entry binding authored for this card?

    The binding is the authorship; ``DOOR_ENABLED`` is the rollout. A card
    bound as the door is held to the door's rule before the flag flips, which
    is when the compile has to say so.
    """
    try:
        from agent_core.cards.routing import list_entry_bindings

        return any(
            str(b.get("bot_id")) == bot_id and b.get("enabled") for b in list_entry_bindings()
        )
    except Exception:
        logger.exception("entry binding scan failed · bot=%s", bot_id)
        return False


def fleet_gates(
    *,
    primary_bot_id: str,
    card_raw: dict[str, Any] | None,
    flow: dict[str, Any],
    members: Sequence[dict[str, Any]],
    door_keys: frozenset[str] | None = None,
    is_door: bool | None = None,
) -> list[GateResult]:
    """G-F2, G-F6, G-F12 and G-F15 over the merged fleet graph.

    ``is_door`` says whether the primary answers the phone -- an enabled
    entry binding names it. G-F6 (a door may not do business) applies only
    then: every specialist with handoffs also merges a fleet, and holding the
    door's read-only rule against the collections card would refuse the one
    card whose business tools are the point. ``None`` asks the bindings.

    G-F15, G-F2 and G-F6 block. The first two describe a call that breaks --
    a hop replaying the greeting and recording disclosure at an already-verified
    caller, and a member that cannot reach a terminal. G-F6 describes a door
    that can do business: it stayed warn while the shipped intake card carried
    `load_skill`, and went red once the door's include was authored down to
    the read set. All three pass on every card that emits them, which is the
    condition for a gate to block here.

    G-F12 stays warn, and not out of caution: it is informational by
    construction -- it reports that publishing a door deploys its members,
    which is the design, not a defect.

    Returns ``[]`` when there is no fleet: a single-member card has no hop to
    check, no sibling to share a terminal with, and no door.
    """
    card: AgentCard | None = None
    if isinstance(card_raw, dict) and is_authored(card_raw):
        try:
            card = parse_card(card_raw)
        except Exception:
            # G0 already reports an unparseable card. Emitting a second failure
            # for the same cause would double-count it.
            card = None

    if door_keys is None:
        door_keys = fg.DOOR_KEYS

    fleet_flow, entries, _grants = _merge_members(
        primary_bot_id=primary_bot_id,
        primary_flow=flow if isinstance(flow, dict) else {},
        # Grants are not read by any gate here; `_merge_members` needs the
        # argument to build `grant_by_specialist`, which is discarded.
        primary_grant=set(),
        members=members,
    )
    if not entries:
        return []

    gates: list[GateResult] = []
    owned = _namespace_locals(fleet_flow)

    if is_door is None:
        is_door = _bound_as_entry(primary_bot_id)
    gates.append(
        _closure_gate(primary_bot_id=primary_bot_id, card=card, members=members, entries=entries)
    )
    if is_door:
        gates.append(_identity_gate(fleet_flow=fleet_flow, entries=entries))
    else:
        # A specialist's own start is not where a caller enters; the hop into
        # it arrives verified, and the walk from the door covers every member
        # the door can reach. Judged when the door compiles.
        gates.append(
            _gate(
                "G-F3",
                "identity_before_writes",
                "skipped",
                f"{primary_bot_id} is not the door; the walk starts at the door's compile",
            )
        )

    # G-F15 -- where a hop lands.
    #
    # `CardHandoff.entry_node` defaults to "", which `_merge_members` resolves
    # to the member's first business node (`flow_graph.business_entry`). What
    # this still catches: an authored entry_node that names a door node, and a
    # member whose graph is all door nodes. A hop landing there would greet the
    # caller and read the recording disclosure a second time, mid-call.
    landings: list[dict[str, Any]] = []
    declared = {h.to_bot_id: (h.entry_node or "") for h in (card.handoffs if card else [])}
    for namespace, entry in sorted(entries.items()):
        if namespace == primary_bot_id:
            continue
        local = fg.local_key(entry)
        authored = declared.get(namespace, "")
        effective = authored or local
        if effective in door_keys:
            landings.append(
                {
                    "member": namespace,
                    "entry_node": effective,
                    "authored": bool(authored),
                    "why": "a hop lands on a door node and replays greeting/disclosure",
                }
            )
    gates.append(
        _gate(
            "G-F15",
            "fleet_hop",
            "fail" if landings else "pass",
            (
                f"{len(landings)} hop(s) land on a door node — "
                "author entry_node on the handoff edge"
            )
            if landings
            else f"{len(entries) - 1} hop(s) land on a business node",
            landings,
        )
    )

    # G-F2 -- complete residency, not exclusive ownership.
    partial: list[dict[str, Any]] = []
    for key in sorted(_TERMINAL_KEYS):
        owners = {ns for ns, locals_ in owned.items() if key in locals_}
        if owners and owners != set(owned):
            partial.append(
                {"terminal": key, "owned_by": sorted(owners), "missing": sorted(set(owned) - owners)}
            )
    gates.append(
        _gate(
            "G-F2",
            "door_and_terminals",
            "fail" if partial else "pass",
            (
                f"{len(partial)} terminal(s) exist in some members and not others"
                if partial
                else f"{len(owned)} namespace(s) agree on the terminals"
            ),
            partial,
        )
    )

    # G-F6 -- a door that can do business is not a door. Only the door.
    if not is_door:
        gates.append(
            _gate(
                "G-F6",
                "door_readonly",
                "skipped",
                f"{primary_bot_id} is not bound as an entry; the read-only rule is the door's",
            )
        )
    else:
        extra = sorted(set((card.tools.include if card else []) or []) - _DOOR_TOOLS)
        gates.append(
            _gate(
                "G-F6",
                "door_readonly",
                "fail" if extra else "pass",
                (
                    f"the door holds {len(extra)} tool(s) beyond routing: {', '.join(extra)}"
                    if extra
                    else "the door can identify, read, route and leave, and nothing else"
                ),
                [{"beyond_routing": extra}] if extra else [],
            )
        )

    # G-F12 -- informational until publish is split into member and fleet scope.
    gates.append(
        _gate(
            "G-F12",
            "publish_scope",
            "warn",
            (
                f"publishing {primary_bot_id} deploys {len(entries)} member(s) as one "
                "bundle; a member cannot ship alone"
            ),
            [{"members": sorted(entries)}],
        )
    )
    return gates
