"""G-OB1..9: an agent that cannot dial correctly must not be publishable.

``gate`` and ``eval_gate`` are the compiler's registered constructors, passed
in so this module does not import the compiler (the ``gates_voice`` shape).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from agent_core.cards.schema import AgentCard


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
        "no_upsell",
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


def mission_entries(flow: Any) -> dict[str, str]:
    """objective -> node key from the graph. Empty on an unauthored flow."""
    import flow_graph as fg

    if not fg.is_authored(flow):
        return {}
    try:
        return fg.parse_graph(flow).entry_objectives()
    except Exception:
        return {}


def outbound_gates(
    card: "AgentCard | None",
    flow: Any,
    *,
    catalog_names: set[str],
    effective: list[str],
    known_bot_ids: set[str],
    eval_report: dict[str, Any] | None,
    skip_eval: bool = False,
    gate: Callable[..., Any],
    eval_gate: Callable[..., Any],
) -> list[Any]:
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
    import outbound
    from agent_core.cards.schema import PoolKind  # noqa: F401  (documents the vocabulary)

    out: list[Any] = []
    if card is None:
        out.append(gate("G-OB1", "missions_declared", "skipped", "no card"))
        out.append(gate("G-OB9", "outbound", "skipped", "no card"))
        return out
    ob = card.outbound
    if not ob.dials:
        # G-OB9 too: a card requiring the outbound suite while dialling nothing
        # produced no gate at all, not even a skipped one, so the requirement
        # looked satisfied.
        out.append(gate("G-OB1", "missions_declared", "skipped", "inbound-only card"))
        out.append(gate("G-OB9", "outbound", "skipped", "inbound-only card"))
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
        # retry_on is matched against the attempt's state; a state the dialler
        # never writes is a retry that never fires, and a state that is also
        # in stop_on is a ladder arguing with itself.
        for code in cadence.retry_on or []:
            if code not in outbound.RETRYABLE:
                issues.append(
                    {"gate": "G-OB6", "problem": f"cadence {cadence.name!r} retries on {code!r}, which is not a retryable state"}
                )
            elif code in set(cadence.stop_on or []):
                issues.append(
                    {"gate": "G-OB6", "problem": f"cadence {cadence.name!r} both retries and stops on {code!r}"}
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

    for gate_id, name in _OUTBOUND_GATE_NAMES.items():
        found = by_gate.get(gate_id)
        if found:
            out.append(gate(gate_id, name, "fail", found[0]["problem"], found))
        else:
            out.append(gate(gate_id, name, "pass"))

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
        eval_gate(
            "G-OB9",
            "outbound",
            outbound_eval_gate_enabled(),
            eval_report,
            card,
            skip=skip_eval,
        )
    )
    return out
