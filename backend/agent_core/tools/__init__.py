"""Shared agent tool spine — one catalog, one set of domain handlers.

``catalog`` owns the wire contract (names, args, aliases, deep-links).
``domain`` owns the CRM logic that both channels execute identically.
``kb`` owns retrieval policy (gate, steering, confidence) for both channels.
Channel modules (``voice/tools.py``, ``bot_tools.py``) are thin adapters.
"""

from agent_core.tools.catalog import (
    CALLBACK_REASONS,
    CATALOG,
    DISPUTE_TYPES,
    DOCUMENT_CHANNELS,
    DOCUMENT_TYPES,
    ESCALATION_REASONS,
    LEAD_PRIORITIES,
    VERIFY_METHODS,
    normalize,
    openai_tools,
    spec,
)
from agent_core.tools.domain import (
    ToolResult,
    capture_lead,
    check_product_eligibility,
    create_promise_to_pay,
    flag_dispute,
    mark_upsell_presented,
    request_callback,
    request_documents,
)
from agent_core.tools.kb import (
    KB_ALLOWED_INTENTS,
    KB_CONFIDENCE_THRESHOLD,
    search_knowledge_base,
)
from agent_core.tools.schema import ArgSpec, ToolCatalog, ToolSpec

__all__ = [
    "ArgSpec",
    "CALLBACK_REASONS",
    "CATALOG",
    "DISPUTE_TYPES",
    "DOCUMENT_CHANNELS",
    "DOCUMENT_TYPES",
    "ESCALATION_REASONS",
    "KB_ALLOWED_INTENTS",
    "KB_CONFIDENCE_THRESHOLD",
    "LEAD_PRIORITIES",
    "ToolCatalog",
    "ToolResult",
    "ToolSpec",
    "VERIFY_METHODS",
    "capture_lead",
    "check_product_eligibility",
    "create_promise_to_pay",
    "flag_dispute",
    "mark_upsell_presented",
    "normalize",
    "openai_tools",
    "request_callback",
    "request_documents",
    "search_knowledge_base",
    "spec",
]
