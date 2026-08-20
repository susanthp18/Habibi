"""Four first-party Agent Cards. Tenants do not create a fifth until Phase 5."""

from __future__ import annotations

import re

from agent_core.cards.schema import (
    LOCKED_POLICY_ENGINES,
    AgentCard,
    CardConnector,
    CardEval,
    CardHandoff,
    CardIdentity,
    CardSkillRef,
    CardTools,
    HumanGate,
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
    "load_skill",
]

_INSURANCE_TOOLS = [
    "verify_identity",
    "get_customer_context",
    "get_account_position",
    "get_payment_history",
    "get_emi_schedule",
    "add_customer_note",
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
