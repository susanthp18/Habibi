"""Four first-party Agent Cards. Tenants do not create a fifth until Phase 5."""

from __future__ import annotations

import re

from agent_core.cards.schema import (
    LOCKED_POLICY_ENGINES,
    AgentCard,
    CardCadence,
    CardConnector,
    CardEval,
    CardHandoff,
    CardIdentity,
    CardObjective,
    CardOutbound,
    CardPostCall,
    CardSkillRef,
    CardTools,
    HumanGate,
    PostCallRule,
)
from agent_core.skills.defaults import (
    COLLECTIONS_SKILLS,
    INTAKE_SKILLS,
    INSURANCE_SKILLS,
    SUPERVISOR_SKILLS,
    skill_refs,
)

COLLECTIONS_BOT_ID = "kaia-v2-4"
INTAKE_BOT_ID = "intake-v1"
INSURANCE_BOT_ID = "insurance-v1"
SUPERVISOR_BOT_ID = "supervisor-brief"

FIRST_PARTY_BOTS: tuple[tuple[str, str, str], ...] = (
    (INTAKE_BOT_ID, "Intake", "1.0"),
    (COLLECTIONS_BOT_ID, "Collections", "2.4"),
    (INSURANCE_BOT_ID, "Insurance", "1.0"),
    (SUPERVISOR_BOT_ID, "Supervisor brief", "1.0"),
)

FIRST_PARTY_BOT_IDS: frozenset[str] = frozenset(b[0] for b in FIRST_PARTY_BOTS)

# Mesh role name the voice worker still keys on. Card identity.slug matches.
BOT_TO_MESH_ROLE: dict[str, str] = {
    COLLECTIONS_BOT_ID: "collections",
    INTAKE_BOT_ID: "intake",
    INSURANCE_BOT_ID: "insurance",
    SUPERVISOR_BOT_ID: "supervisor_brief",
}

_LOCKED = list(LOCKED_POLICY_ENGINES)

_COLLECTIONS_TOOLS = [
    "verify_identity",
    "get_customer_context",
    "get_account_position",
    "get_payment_history",
    "get_emi_schedule",
    "create_promise_to_pay",
    "flag_dispute",
    "evaluate_authority",
    "apply_goodwill",
    "request_callback",
    "escalate_to_human",
    "handoff_to_agent",
    "search_knowledge_base",
    "recommend_next_offer",
    "request_documents",
    "add_customer_note",
    # Why the borrower has not paid, as a code. On the collections card only:
    # an intake or insurance agent asking a servicing caller why they are behind
    # would be a question nobody asked them to answer.
    "capture_nonpayment_reason",
    # Unlike the reason code above, this one is on every customer-facing card.
    # "Don't ring me before ten" is conduct rather than collections: an
    # insurance servicing caller who says it is owed the same window, and the
    # dialler reads one column regardless of which agent heard the sentence.
    "set_contact_preference",
    "check_product_eligibility",
    "capture_lead",
    "decline_offer",
    "load_skill",
    "run_skill_script",
]

_INTAKE_TOOLS = [
    "verify_identity",
    "get_customer_context",
    "handoff_to_agent",
    "escalate_to_human",
    "search_knowledge_base",
    "add_customer_note",
    "set_contact_preference",
    "load_skill",
]

_INSURANCE_TOOLS = [
    "verify_identity",
    "get_customer_context",
    "get_account_position",
    "get_payment_history",
    "get_emi_schedule",
    "add_customer_note",
    "set_contact_preference",
    "check_product_eligibility",
    "capture_lead",
    "recommend_next_offer",
    "request_documents",
    "search_knowledge_base",
    "escalate_to_human",
    "handoff_to_agent",
    "load_skill",
    "run_skill_script",
]

_SUPERVISOR_TOOLS: list[str] = ["add_customer_note"]


def _card(
    *,
    bot_id: str,
    slug: str,
    display_name: str,
    purpose: str,
    channels: list,
    include: list[str],
    handoffs: list[CardHandoff],
    data_class: list,
    human_gates: list[HumanGate] | None = None,
    suite_id: str | None = None,
    skills: list[CardSkillRef] | None = None,
    connectors: list[CardConnector] | None = None,
    outbound: CardOutbound | None = None,
) -> AgentCard:
    return AgentCard(
        identity=CardIdentity(
            bot_id=bot_id,
            slug=slug,
            display_name=display_name,
            purpose=purpose,
            channels=channels,
            data_class=data_class,
            regulator_tags=["rbi-fair-practices", "dpdp"],
        ),
        skills=skills or [],
        tools=CardTools(include=include, locked=_LOCKED),
        handoffs=handoffs,
        human_gates=human_gates
        or [HumanGate(tool_name="create_promise_to_pay", require="identity")],
        eval=CardEval(suite_id=suite_id, require=["regression", "redteam"]),
        connectors=connectors or [],
        outbound=outbound or CardOutbound(),
    )


def intake_card() -> AgentCard:
    return _card(
        bot_id=INTAKE_BOT_ID,
        slug="intake",
        display_name="Intake",
        purpose="Identify the caller, disclose recording, route to a specialist.",
        channels=["voice", "whatsapp"],
        include=_INTAKE_TOOLS,
        handoffs=[
            CardHandoff(to_bot_id=COLLECTIONS_BOT_ID, when="collections intent"),
            CardHandoff(to_bot_id=INSURANCE_BOT_ID, when="product / insurance intent"),
        ],
        data_class=["pii"],
        human_gates=[HumanGate(tool_name="handoff_to_agent", require="identity")],
        suite_id="eval-regression-intake",
        skills=skill_refs(*INTAKE_SKILLS),
    )


#: The collections agent's outbound configuration.
#:
#: Written down here rather than left to an operator's first publish because a
#: default that dials nothing is not a safe default — it is an agent that
#: silently does not work, and the first person to notice is whoever wonders
#: why the campaign finished with zero calls. Four missions, one cadence, and
#: no offers on any of them.
#:
#: Every entry node is ``confirm_identity``: the built-in script has one
#: outbound door, and the mission briefing in the system prompt is what makes a
#: bounce cure sound different from a broken-promise chase. An *authored* graph
#: can give each mission its own door — that is the whole point of ``entryFor``
#: — and the compiler checks the two agree (G-OB2).
def _collections_outbound() -> CardOutbound:
    def objective(key: str, *, success: list[str], minutes: int = 4) -> CardObjective:
        return CardObjective(
            key=key,
            entry_node="confirm_identity",
            success=success,
            max_duration_sec=minutes * 60,
            # Empty, deliberately. A servicing call is not a sales call, and a
            # borrower who is behind on an instalment did not ask to be sold a
            # top-up. Turning this on is a decision somebody makes on purpose.
            allowed_offers=[],
            cadence="collections",
        )

    return CardOutbound(
        # `both`: the same agent answers the phone and places calls. One card,
        # one persona, one authority envelope, one compliance surface — the
        # conversation differs at the door and converges immediately after.
        direction="both",
        objectives=[
            objective(
                "pre_due_reminder",
                success=["ptp_captured", "paid_in_call"],
                minutes=3,
            ),
            objective(
                "bounce_cure",
                success=["ptp_captured", "paid_in_call", "part_payment_agreed"],
            ),
            objective(
                "dpd_reminder",
                success=[
                    "ptp_captured",
                    "paid_in_call",
                    "part_payment_agreed",
                    "plan_agreed",
                ],
            ),
            objective(
                "broken_ptp_chase",
                success=["ptp_recommitted", "paid_in_call", "part_payment_agreed"],
                minutes=5,
            ),
        ],
        cadences=[
            CardCadence(
                name="collections",
                max_attempts=3,
                per_day=1,
                # Four hours, then a day, then three. The first gap is short
                # enough to catch somebody who was simply driving; the later
                # ones are long enough that three attempts do not read as
                # pursuit.
                backoff_hours=[4, 24, 72],
                escalate_to="human",
            )
        ],
        post_call=CardPostCall(
            on_outcome=[
                PostCallRule(when="ptp_captured", do=["confirm_written", "schedule_due_reminder"]),
                PostCallRule(when="ptp_recommitted", do=["confirm_written", "schedule_due_reminder"]),
                # `confirm_written` comes last in each of these because the verb
                # before it is what produces the fact the message states — the
                # hold's end date, the dispute's reference. Reversed, the message
                # would have nothing to quote and would decline to send.
                PostCallRule(
                    when="hardship_declared",
                    do=["place_hold", "suppress_upsell", "confirm_written"],
                ),
                PostCallRule(
                    when="dispute_raised", do=["flag_dispute", "place_hold", "confirm_written"]
                ),
                PostCallRule(
                    when="callback_requested", do=["schedule_mission", "confirm_written"]
                ),
                PostCallRule(when="opt_out_requested", do=["record_optout", "stop_cadence"]),
                PostCallRule(when="wrong_number", do=["mark_phone_dead", "promote_alternate"]),
                PostCallRule(when="no_resolution", do=["advance_ladder"]),
            ]
        ),
        # No pool configured: the deployment's single TWILIO_PHONE_NUMBER, which
        # is what every dial used before pools existed. A tenant on the 1600
        # series names one here and G-OB4 starts enforcing the offer ban.
        pool_kind="general",
        carrier_amd=False,
        ivr_traversal=False,
    )


def collections_card() -> AgentCard:
    return _card(
        bot_id=COLLECTIONS_BOT_ID,
        slug="collections",
        display_name="Collections",
        purpose="Recover overdue balances: PTP, dispute, callback, escalate.",
        channels=["voice", "whatsapp"],
        include=_COLLECTIONS_TOOLS,
        handoffs=[
            CardHandoff(to_bot_id=INSURANCE_BOT_ID, when="in-policy upsell after PTP"),
            CardHandoff(to_bot_id=SUPERVISOR_BOT_ID, when="warm transfer brief"),
        ],
        data_class=["pii", "money"],
        suite_id="eval-regression-collections",
        skills=skill_refs(*COLLECTIONS_SKILLS),
        connectors=[CardConnector(connector_id="paylink", allow_prefixes=["ext.paylink."])],
        outbound=_collections_outbound(),
    )


def insurance_card() -> AgentCard:
    return _card(
        bot_id=INSURANCE_BOT_ID,
        slug="insurance",
        display_name="Insurance",
        purpose="Product eligibility, lead capture, insurance FAQ.",
        channels=["voice", "whatsapp"],
        include=_INSURANCE_TOOLS,
        handoffs=[
            CardHandoff(to_bot_id=COLLECTIONS_BOT_ID, when="caller returns to dues"),
            CardHandoff(to_bot_id=SUPERVISOR_BOT_ID, when="warm transfer brief"),
        ],
        data_class=["pii", "marketing"],
        human_gates=[HumanGate(tool_name="capture_lead", require="identity")],
        suite_id="eval-regression-insurance",
        skills=skill_refs(*INSURANCE_SKILLS),
    )


def supervisor_brief_card() -> AgentCard:
    return _card(
        bot_id=SUPERVISOR_BOT_ID,
        slug="supervisor_brief",
        display_name="Supervisor brief",
        purpose="Compact handoff brief for a warm-transfer human agent.",
        channels=["internal"],
        include=_SUPERVISOR_TOOLS,
        handoffs=[],
        data_class=["pii", "internal"],
        human_gates=[],
        suite_id="eval-regression-supervisor",
        skills=skill_refs(*SUPERVISOR_SKILLS),
    )


_BUILDERS = {
    INTAKE_BOT_ID: intake_card,
    COLLECTIONS_BOT_ID: collections_card,
    INSURANCE_BOT_ID: insurance_card,
    SUPERVISOR_BOT_ID: supervisor_brief_card,
}


def card_for(bot_id: str) -> AgentCard:
    builder = _BUILDERS.get(bot_id)
    if builder is None:
        raise KeyError(f"unknown_first_party_bot:{bot_id}")
    return builder()


def card_dump(bot_id: str) -> dict:
    return card_for(bot_id).model_dump(mode="json")


def scaffold_card(bot_id: str, display_name: str | None = None) -> dict:
    """A minimal *valid* card for a bot that has none yet.

    A bot row with no prompt version resolved to ``{}``, and an empty card is
    not authorable: ``is_authored`` is false, so the Tools/Skills/Connectors
    tabs had nothing to edit and the compiler treated it as legacy. This gives
    such a bot a real identity plus the locked policy engines — the floor every
    card has to stand on — so it can be edited and published like any other.
    """
    from agent_core.cards.schema import AgentCard, CardIdentity, CardTools, LOCKED_POLICY_ENGINES

    bid = (bot_id or "").strip()
    name = (display_name or "").strip() or bid
    slug = re.sub(r"[^a-z0-9]+", "-", bid.lower()).strip("-") or bid
    return AgentCard(
        identity=CardIdentity(bot_id=bid, slug=slug, display_name=name, purpose=""),
        tools=CardTools(include=[], locked=list(LOCKED_POLICY_ENGINES)),
    ).model_dump(mode="json")
