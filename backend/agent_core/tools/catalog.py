"""The one tool catalog. Voice and WhatsApp/text are adapters over these specs.

Canonical arg names are snake_case. The camelCase names the WhatsApp catalog
used to publish live on as :attr:`ArgSpec.aliases`, so in-flight conversations
and models that emit the old shape keep resolving — see
:meth:`ToolSpec.normalize_args`.
"""

from __future__ import annotations

from agent_core.tools.schema import (
    CHANNEL_TEXT,
    CHANNEL_VOICE,
    ArgSpec,
    ToolCatalog,
    ToolSpec,
)

BOTH = frozenset({CHANNEL_VOICE, CHANNEL_TEXT})
VOICE_ONLY = frozenset({CHANNEL_VOICE})
TEXT_ONLY = frozenset({CHANNEL_TEXT})

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

LEAD_PRIORITIES = ("low", "normal", "high")

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
        channels=BOTH,
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
        channels=BOTH,
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
        channels=BOTH,
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
        description="Record the customer's promise to pay an amount by a date. Does not collect payment.",
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

# --------------------------------------------------------------------------
# Upsell
# --------------------------------------------------------------------------

CHECK_PRODUCT_ELIGIBILITY = _r(
    ToolSpec(
        name="check_product_eligibility",
        description=(
            "Evaluate eligibility for an upsell/cross-sell product using live account "
            "DPD, consent/DND, and product rules. Bureau/KYC/income return unknown "
            "(not fake passes). Call before capture_lead."
        ),
        args=(
            ArgSpec(
                name="product_id",
                type="string",
                description=(
                    "Product id, e.g. topup-loan, debt-consolidation, cc-limit-upgrade, "
                    "bundled-insurance, personal-loan, gold-loan."
                ),
                required=True,
                aliases=("productId",),
            ),
        ),
        channels=BOTH,
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
                description="Product the customer is interested in.",
                required=True,
                aliases=("productId",),
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
                description="Short snippet of what the customer said about their interest.",
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
        channels=BOTH,
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
