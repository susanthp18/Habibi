"""The one tool catalog. Voice and WhatsApp/text are adapters over these specs.

Canonical arg names are snake_case. The camelCase names the WhatsApp catalog
used to publish live on as :attr:`ArgSpec.aliases`, so in-flight conversations
and models that emit the old shape keep resolving — see
:meth:`ToolSpec.normalize_args`.
"""

from __future__ import annotations

from agent_core.tools.schema import (
    CHANNEL_MCP,
    CHANNEL_TEXT,
    CHANNEL_VOICE,
    ArgSpec,
    ToolCatalog,
    ToolSpec,
)

BOTH = frozenset({CHANNEL_VOICE, CHANNEL_TEXT})
VOICE_ONLY = frozenset({CHANNEL_VOICE})
TEXT_ONLY = frozenset({CHANNEL_TEXT})

# Readable by an external agent over MCP, in addition to the bot's own channels.
#
# Read-only tools ONLY. Every mutating tool in this catalog writes to a bank's
# CRM — promises, disputes, leads, notes, escalations — and on voice and text
# those writes sit behind CallContext.identity_verified, which is what stops an
# unverified caller moving money-adjacent state. An MCP client has no
# verification ceremony, so that gate has no analogue and the write tools stay
# off until one exists.
#
# Opt-in per spec rather than a default so adding a tool never silently exposes
# it, and so this comment is the thing someone has to argue with.
BOTH_AND_MCP = frozenset({CHANNEL_VOICE, CHANNEL_TEXT, CHANNEL_MCP})

DISPUTE_TYPES = (
    "paid_already",
    "wrong_amount",
    "not_my_account",
    "fee_waiver",
    "duplicate_charge",
    "fraud",
)

CALLBACK_REASONS = (
    "payment_discussion",
    "dispute_followup",
    "document_query",
    "hardship_review",
    "upsell_interest",
    "general",
)

ESCALATION_REASONS = (
    "sentiment_drop",
    "verification_failed",
    "compliance",
    "customer_requested",
    "hardship",
    "dispute",
    "high_value",
)

VERIFY_METHODS = ("phone_match", "account_tail")

DOCUMENT_TYPES = (
    "account_statement",
    "no_dues_certificate",
    "interest_certificate",
    "foreclosure_letter",
    "loan_schedule",
    "payment_receipt",
    "kyc_letter",
)

DOCUMENT_CHANNELS = ("whatsapp", "email", "sms")

# Matches the leads.priority CHECK constraint. Stopping at "high" made the
# 'urgent' the database allows unreachable from every channel.
LEAD_PRIORITIES = ("low", "normal", "high", "urgent")

CATALOG = ToolCatalog()
_r = CATALOG.register

# --------------------------------------------------------------------------
# CRM reads
# --------------------------------------------------------------------------

GET_CUSTOMER_CONTEXT = _r(
    ToolSpec(
        name="get_customer_context",
        description=(
            "Authoritative customer/account snapshot: name, outstanding, DPD, DND, "
            "consent, open promises/disputes. Use for any money question."
        ),
        channels=BOTH_AND_MCP,
    )
)

GET_PAYMENT_HISTORY = _r(
    ToolSpec(
        name="get_payment_history",
        description="Recent ledger entries for the customer's primary account.",
        args=(
            ArgSpec(
                name="limit",
                type="integer",
                description="How many entries to return.",
                minimum=1,
                maximum=20,
                default=8,
            ),
        ),
        channels=BOTH_AND_MCP,
    )
)

GET_EMI_SCHEDULE = _r(
    ToolSpec(
        name="get_emi_schedule",
        description="EMI installment schedule for the customer's primary account.",
        args=(
            ArgSpec(
                name="limit",
                type="integer",
                description="How many installments to return.",
                minimum=1,
                maximum=24,
                default=6,
            ),
        ),
        channels=BOTH_AND_MCP,
    )
)

# Voice hub reads the already-loaded CallContext rather than re-querying.
GET_ACCOUNT_POSITION = _r(
    ToolSpec(
        name="get_account_position",
        description=(
            "Return the verified caller's outstanding balance and amounts due. "
            "Must not be called before identity verification succeeds."
        ),
        channels=VOICE_ONLY,
        cancel_on_interruption=True,
    )
)

# --------------------------------------------------------------------------
# Call intake
# --------------------------------------------------------------------------

# The bot asks what the caller needs BEFORE the verification ceremony, so that
# verification can be framed as the means to the caller's goal rather than a
# checkpoint they are marched through. Nothing account-specific is disclosed
# here — this records an intention, it reads no CRM data.
CAPTURE_CALL_GOAL = _r(
    ToolSpec(
        name="capture_call_goal",
        description=(
            "Record why the caller says they called, in their own words, and move "
            "on to identity verification. Call this as soon as the caller has "
            "stated what they want — never before they have spoken, and never "
            "with a guess."
        ),
        args=(
            ArgSpec(
                name="goal_summary",
                type="string",
                description=(
                    "One short phrase in the caller's own terms, e.g. 'dispute a "
                    "late fee', 'pay the EMI today', 'ask about insurance "
                    "coverage'. Never placeholder text."
                ),
                required=True,
                aliases=("goalSummary",),
            ),
        ),
        channels=VOICE_ONLY,
    )
)

# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------

VERIFY_IDENTITY = _r(
    ToolSpec(
        name="verify_identity",
        description=(
            "Verify caller identity before any account details are shared. "
            "Call only after the caller has spoken digits — never with placeholder text."
        ),
        args=(
            ArgSpec(
                name="method",
                type="string",
                description="phone_match (mobile digits) or account_tail (last 4 of account).",
                required=True,
                enum=VERIFY_METHODS,
            ),
            ArgSpec(
                name="value",
                type="string",
                description="Digits the caller spoke (not instruction text).",
                required=True,
            ),
        ),
        channels=VOICE_ONLY,
    )
)

IDENTIFY_CUSTOMER = _r(
    ToolSpec(
        name="identify_customer",
        description=(
            "Verify/rebind the conversation to a customer by phone digits or account "
            "last-4 (writes identity_verifications). Use when identity is unclear or "
            "the session started as an unknown caller."
        ),
        args=(
            ArgSpec(name="phone", type="string", description="Customer phone digits."),
            ArgSpec(
                name="account_tail",
                type="string",
                description="Last 4 digits of the account id.",
                aliases=("accountTail",),
            ),
        ),
        channels=TEXT_ONLY,
    )
)

# --------------------------------------------------------------------------
# CRM writes
# --------------------------------------------------------------------------

CREATE_PROMISE_TO_PAY = _r(
    ToolSpec(
        name="create_promise_to_pay",
        description="Record the customer's promise to pay an amount by a date. Records the promise and sends a written confirm with a pay link.",
        args=(
            ArgSpec(
                name="amount",
                type="number",
                description="Amount in INR the customer commits to pay.",
                required=True,
                minimum=0.01,
            ),
            ArgSpec(
                name="promise_date",
                type="string",
                description="ISO date YYYY-MM-DD the customer will pay by.",
                required=True,
                aliases=("promisedDate", "promised_date"),
            ),
        ),
        channels=BOTH,
        entity="promise",
        deep_link="/promises?id={id}",
    )
)

FLAG_DISPUTE = _r(
    ToolSpec(
        name="flag_dispute",
        description="Flag a payment/charge dispute for human review (capture only).",
        args=(
            ArgSpec(
                name="dispute_type",
                type="string",
                description="Dispute classification.",
                required=True,
                enum=DISPUTE_TYPES,
                aliases=("type",),
            ),
            ArgSpec(name="amount", type="number", description="Optional disputed amount in INR."),
            ArgSpec(
                name="summary",
                type="string",
                description="Brief transcript snippet of the customer's claim.",
                aliases=("transcriptSnippet", "transcript_snippet"),
            ),
        ),
        channels=BOTH,
        entity="dispute",
        deep_link="/disputes?id={id}",
    )
)

EVALUATE_AUTHORITY = _r(
    ToolSpec(
        name="evaluate_authority",
        description=(
            "Ask the authority matrix what — if anything — may close on this call "
            "for a fee waiver, bounce-charge reversal, settlement or restructuring. "
            "Returns a verdict (auto_approve, cap_inr, or escalate) and an approved "
            "rupee amount that is already inside policy. Never invent a figure this "
            "tool did not return. Call it before quoting any waiver or settlement "
            "amount, and before apply_goodwill."
        ),
        args=(
            ArgSpec(
                name="fee_type",
                type="string",
                description="What they asked to reverse or settle.",
                enum=("late_fee", "bounce_charge", "settlement", "restructuring"),
                aliases=("feeType", "type"),
            ),
            ArgSpec(
                name="asked_amount",
                type="number",
                description="Rupee amount they asked for, if they named one.",
                aliases=("askedAmount", "amount"),
            ),
        ),
        channels=BOTH,
    )
)

APPLY_GOODWILL = _r(
    ToolSpec(
        name="apply_goodwill",
        description=(
            "Post an in-policy late-fee goodwill waiver that evaluate_authority "
            "already approved. Amount must be at or below the approved amount. "
            "Do not call this for settlement, restructuring, or bounce charges."
        ),
        args=(
            ArgSpec(
                name="decision_id",
                type="string",
                description="The decisionId evaluate_authority returned.",
                required=True,
                aliases=("decisionId",),
            ),
            ArgSpec(
                name="amount",
                type="number",
                description="Rupees to reverse. Must be ≤ the approved amount.",
            ),
        ),
        channels=BOTH,
    )
)

REQUEST_CALLBACK = _r(
    ToolSpec(
        name="request_callback",
        description="Schedule a human callback for the verified customer. Respects DND windows.",
        args=(
            ArgSpec(
                name="scheduled_at",
                type="string",
                description="ISO datetime when the customer wants to be called back.",
                required=True,
                aliases=("scheduledAt",),
            ),
            ArgSpec(
                name="reason",
                type="string",
                description="Why the callback is needed.",
                enum=CALLBACK_REASONS,
            ),
            ArgSpec(
                name="window_mins",
                type="integer",
                description="Acceptable window around the slot, in minutes.",
                minimum=15,
                maximum=120,
                aliases=("windowMins",),
            ),
        ),
        channels=BOTH,
        entity="callback",
        deep_link="/callbacks?id={id}",
    )
)

ADD_CUSTOMER_NOTE = _r(
    ToolSpec(
        name="add_customer_note",
        description="Add an internal CRM note on the customer (agent-facing; never spoken).",
        args=(
            ArgSpec(
                name="text",
                type="string",
                description="Note body.",
                required=True,
            ),
            ArgSpec(name="pinned", type="boolean", description="Pin the note to the top."),
        ),
        channels=BOTH,
    )
)

ESCALATE_TO_HUMAN = _r(
    ToolSpec(
        name="escalate_to_human",
        description=(
            "Hand the conversation to a human agent. Use for legal threats, abuse, "
            "identity confusion, or when tools fail. This QUEUES a human callback — "
            "it does not transfer the caller live."
        ),
        args=(
            ArgSpec(
                name="reason",
                type="string",
                description="Escalation reason.",
                required=True,
                enum=ESCALATION_REASONS,
            ),
            ArgSpec(
                name="detail",
                type="string",
                description="Optional free-text context for the supervisor.",
            ),
        ),
        channels=BOTH,
    )
)

HANDOFF_TO_AGENT = _r(
    ToolSpec(
        name="handoff_to_agent",
        description=(
            "Transfer this conversation to another first-party agent card. "
            "Only call this tool — never announce a transfer in prose. The target "
            "must be on this card's handoff allowlist."
        ),
        args=(
            ArgSpec(
                name="target_bot_id",
                type="string",
                description="Destination bot id (e.g. kaia-v2-4, insurance-v1).",
                required=True,
            ),
            ArgSpec(
                name="reason",
                type="string",
                description="Why this specialist should take the call.",
                required=True,
            ),
            ArgSpec(
                name="payload",
                type="string",
                description="Compact JSON context for the receiving card.",
            ),
        ),
        channels=BOTH,
    )
)

LOAD_SKILL = _r(
    ToolSpec(
        name="load_skill",
        description=(
            "Load a signed skill's instructions into this turn. Pass the slug from "
            "the Skills list. Replaces any previously loaded skill body. Does not "
            "grant extra tools beyond that skill's allowlist."
        ),
        args=(
            ArgSpec(
                name="slug",
                type="string",
                description="Skill slug (e.g. ptp-negotiate, hardship-intake).",
                required=True,
            ),
            ArgSpec(
                name="include_references",
                type="boolean",
                description="If true, also load references/ text. Still grants no extra tools.",
            ),
        ),
        channels=BOTH,
    )
)

RUN_SKILL_SCRIPT = _r(
    ToolSpec(
        name="run_skill_script",
        description=(
            "Run an allowlisted pure function (JSON in, JSON out). No shell, no "
            "network, no ledger writes. Scripts: emi_remaining, promise_date_in_window."
        ),
        args=(
            ArgSpec(
                name="name",
                type="string",
                description="Script name.",
                required=True,
                enum=("emi_remaining", "promise_date_in_window"),
            ),
            ArgSpec(
                name="payload",
                type="string",
                description="JSON object of script arguments.",
            ),
        ),
        channels=BOTH,
    )
)

REQUEST_DOCUMENTS = _r(
    ToolSpec(
        name="request_documents",
        description=(
            "Raise a document request for the verified customer (statement, no-dues "
            "certificate, interest certificate, foreclosure letter, schedule, receipt, "
            "KYC letter). Operations fulfils and delivers it."
        ),
        args=(
            ArgSpec(
                name="document_type",
                type="string",
                description="Which document the customer asked for.",
                required=True,
                enum=DOCUMENT_TYPES,
                aliases=("docType", "doc_type"),
            ),
            ArgSpec(
                name="delivery_channel",
                type="string",
                description="How to deliver it. Defaults to email.",
                enum=DOCUMENT_CHANNELS,
                aliases=("deliveryChannel",),
            ),
            ArgSpec(
                name="period",
                type="string",
                description="Optional period the document should cover, e.g. 'FY2025-26' or 'last 6 months'.",
            ),
        ),
        channels=BOTH,
        entity="document_request",
        deep_link="/documents?id={id}",
    )
)

INGEST_CUSTOMER_DOCUMENT = _r(
    ToolSpec(
        name="ingest_customer_document",
        description=(
            "File a customer-sent receipt or KYC photo as a document request "
            "(source=vision). Text/WhatsApp only — never on a live voice turn."
        ),
        args=(
            ArgSpec(
                name="filename",
                type="string",
                description="Original filename of the image.",
                required=True,
            ),
            ArgSpec(
                name="mime_type",
                type="string",
                description="Image MIME type, e.g. image/jpeg.",
                required=True,
                aliases=("mimeType",),
            ),
        ),
        channels=TEXT_ONLY,
        entity="document_request",
        deep_link="/documents?id={id}",
    )
)

# --------------------------------------------------------------------------
# Upsell
# --------------------------------------------------------------------------

# The recommender, not the model, chooses the product. This tool is the only
# supported way to find out what may be offered: it returns a shortlist that has
# already passed candidate generation, the compliance veto, ranking and every
# policy gate. Deliberately no product-id list in any description below — a
# model that knows ids a priori will eventually name one nobody approved.
RECOMMEND_NEXT_OFFER = _r(
    ToolSpec(
        name="recommend_next_offer",
        description=(
            "Ask the offer engine what — if anything — is worth mentioning to this "
            "customer right now. Returns at most a couple of pre-approved offers, "
            "each with a product id and an indicative amount, or suppressed=true "
            "meaning say nothing about products at all. Never invent a product id "
            "and never pitch anything this tool did not return. Call it before "
            "mentioning any product, and before closing the call."
        ),
        args=(),
        channels=BOTH,
    )
)

DECLINE_OFFER = _r(
    ToolSpec(
        name="decline_offer",
        description=(
            "Record that the customer said no to the product you just mentioned. "
            "Call it as soon as they decline, then move on without pressing. This "
            "is what stops us raising the same product with them again."
        ),
        args=(
            ArgSpec(
                name="reason",
                type="string",
                description="Short paraphrase of why they declined, if they gave one.",
            ),
        ),
        channels=BOTH,
    )
)

CHECK_PRODUCT_ELIGIBILITY = _r(
    ToolSpec(
        name="check_product_eligibility",
        description=(
            "Re-confirm eligibility for a product recommend_next_offer already "
            "returned, using live account DPD, consent/DND and product rules. "
            "Bureau/KYC/income return unknown (not fake passes)."
        ),
        args=(
            ArgSpec(
                name="product_id",
                type="string",
                description="Product id, exactly as returned by recommend_next_offer.",
                required=True,
                aliases=("productId",),
            ),
        ),
        channels=BOTH_AND_MCP,
    )
)

CAPTURE_LEAD = _r(
    ToolSpec(
        name="capture_lead",
        description=(
            "Capture an upsell/cross-sell lead into the CRM pipeline (Interested). "
            "Runs eligibility first; hard-blocks on DND/consent fail or DPD rule fail. "
            "Unknown bureau/KYC does not block. Only after the customer shows interest."
        ),
        args=(
            ArgSpec(
                name="product_id",
                type="string",
                description=(
                    "Product the customer is interested in — must be one "
                    "recommend_next_offer returned."
                ),
                required=True,
                aliases=("productId",),
            ),
            ArgSpec(
                name="offer_id",
                type="string",
                description=(
                    "The offerId from recommend_next_offer. Pass it whenever you "
                    "have one so the captured lead is tied to the offer that was "
                    "actually pitched."
                ),
                aliases=("offerId",),
            ),
            ArgSpec(
                name="offer_amount",
                type="number",
                description="Optional offer amount in INR.",
                minimum=1,
                aliases=("offerAmount",),
            ),
            ArgSpec(
                name="summary",
                type="string",
                description=(
                    "What the customer actually said about their interest, in their "
                    "own words where possible — this is the only context the "
                    "follow-up specialist gets."
                ),
                aliases=("transcriptSnippet", "transcript_snippet"),
            ),
            ArgSpec(
                name="priority",
                type="string",
                description="Lead priority.",
                enum=LEAD_PRIORITIES,
            ),
        ),
        channels=BOTH,
        entity="lead",
        deep_link="/upsell?id={id}",
    )
)

# --------------------------------------------------------------------------
# Knowledge base
# --------------------------------------------------------------------------

SEARCH_KNOWLEDGE_BASE = _r(
    ToolSpec(
        name="search_knowledge_base",
        description=(
            "Search the knowledge base for policy or FAQ answers. NEVER for balance, "
            "dues, EMI, or fees — CRM tools are authoritative for money. Honor "
            "answer_policy in the result: if confident is false, do not answer from "
            "the snippets."
        ),
        args=(
            ArgSpec(
                name="query",
                type="string",
                description="Customer's question in plain language.",
                required=True,
            ),
        ),
        channels=BOTH_AND_MCP,
        cancel_on_interruption=True,
        timeout_secs=20,
    )
)


def openai_tools(names: list[str] | None = None) -> list[dict]:
    """OpenAI tool dicts for the text channel."""
    return CATALOG.openai_tools(names)


def normalize(name: str, raw: dict | None) -> dict:
    """Canonicalize tool args for ``name`` (accepts legacy camelCase)."""
    return CATALOG.normalize(name, raw)


def spec(name: str) -> ToolSpec | None:
    return CATALOG.get(name)
