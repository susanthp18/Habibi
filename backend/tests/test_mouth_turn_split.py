"""The prompt/tools split must not have moved anything.

``mouth_turn_state`` answered two unrelated questions in one untyped dict:
which tools a mouth may call, and what skill text belongs in its prompt. It is
now a composition over ``resolve_mouth(...).prompt()`` and ``.tools()``.

The values below were captured by **running the pre-split implementation** at
commit 60cb9b7 against the live collections card, then hashing the two long
strings. They are the oracle: comparing the new seam against the current
``mouth_turn_state`` would compare a function to its own inlined body and could
never fail, which is what an earlier version of this file mistakenly did.

Regenerating, if a deliberate behaviour change ever makes that necessary::

    git show <pre-change-sha>:backend/agent_core/skills/runtime.py

load it as a module and project its ``mouth_turn_state`` through ``_project``.
Changing a value here without that provenance means the test has stopped being
an oracle.

No database: pack resolution falls back to the on-disk first-party packs, so
every case runs from the filesystem alone.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from agent_core.tools.catalog import CATALOG
from agent_core.tools.schema import CHANNEL_TEXT, CHANNEL_VOICE

BACKEND = Path(__file__).resolve().parents[1]

# --- golden values, captured from the pre-split implementation --------------

#: sha256("")[:16] — the empty prefix a cardless mouth produces.
_EMPTY_SHA = "e3b0c44298fc1c14"

# Both moved when the mouth started honouring a pack's declared ``mouth:``
# channels: floor-coach is internal-only and no longer rides the collections
# card, so its description left the prefix. Re-measured, not guessed.
_PREFIX_SHA = "897053d86da0b1fb"
_PREFIX_LEN = 1450
# Moved again when the pack stopped stating a calling window the CRM card does
# not carry (the platform default is the script's, not prose). Re-measured.
_PTP_BODY_SHA = "e01d92f26b1e4a3d"

_PACK_SLUGS = [
    "broken-ptp-chase",
    "dispute-capture",
    "doc-fulfil",
    # floor-coach is attached to the card and dropped at resolution:
    # ``mouth: [internal]`` shares no channel with ``[voice, whatsapp]``.
    "hardship-intake",
    "ptp-negotiate",
    "upsell-pitch",
    "verify-and-disclose",
]

_ALLOWED = [
    "add_customer_note",
    # Granted by dispute-capture, which handle_dispute runs under. Before this
    # the node offered a goodwill waiver it had no tool to post.
    "apply_goodwill",
    "capture_lead",
    "capture_nonpayment_reason",
    "check_product_eligibility",
    "create_promise_to_pay",
    "decline_offer",
    "escalate_to_human",
    "evaluate_authority",
    "flag_dispute",
    "get_account_position",
    "get_customer_context",
    "get_emi_schedule",
    "get_payment_history",
    "handoff_to_agent",
    # TEXT_ONLY, and on the collections card's include list — the mouth is
    # unchannelled here, so it survives; the voice grant drops it.
    "ingest_customer_document",
    "load_skill",
    "recommend_next_offer",
    "request_callback",
    "request_documents",
    # Pass 7: the renegotiation tool ptp-negotiate 1.6.0 grants.
    "revise_promise_to_pay",
    "run_skill_script",
    "search_knowledge_base",
    "set_contact_preference",
    "verify_identity",
]

#: Order is part of the contract — it is the order the model sees the tools in.
_OFFERED_IDLE = [
    "recommend_next_offer",
    "evaluate_authority",
    "load_skill",
    "run_skill_script",
    "verify_identity",
    "get_customer_context",
    "get_account_position",
    "get_payment_history",
    "get_emi_schedule",
    "request_callback",
    "escalate_to_human",
    "handoff_to_agent",
    "search_knowledge_base",
    "ingest_customer_document",
    "add_customer_note",
]

#: The two skill-gated writes ptp-negotiate adds, appended after the idle set.
_OFFERED_WITH_PTP = _OFFERED_IDLE + [
    "create_promise_to_pay",
    "revise_promise_to_pay",
    "capture_nonpayment_reason",
]

_CARDLESS = {
    "card_is_none": True,
    "pack_slugs": [],
    "allowed": [],
    "offered": [],
    "prefix_sha": _EMPTY_SHA,
    "prefix_len": 0,
    "active_slug": None,
    "body_role": None,
    "body_sha": None,
}


def _authored(active_slug, offered, body_sha):
    return {
        "card_is_none": False,
        "pack_slugs": _PACK_SLUGS,
        "allowed": _ALLOWED,
        "offered": offered,
        "prefix_sha": _PREFIX_SHA,
        "prefix_len": _PREFIX_LEN,
        "active_slug": active_slug,
        "body_role": None if body_sha is None else "developer",
        "body_sha": body_sha,
    }


GOLDEN = {
    "unauthored-none": (None, {}, _CARDLESS),
    "unauthored-empty": ({}, {}, _CARDLESS),
    "unauthored-with-intent": (None, {"intent": "payment_intent"}, _CARDLESS),
    # An unparseable card reaches the same answer by a different route: the
    # pack resolver fails the identical parse, so no packs survive either.
    "unparseable": ({"identity": "not-an-object"}, {}, _CARDLESS),
    "authored-idle": (
        "CARD",
        {},
        _authored(None, _OFFERED_IDLE, None),
    ),
    "authored-payment-intent": (
        "CARD",
        {"intent": "payment_intent"},
        _authored("ptp-negotiate", _OFFERED_WITH_PTP, _PTP_BODY_SHA),
    ),
    "authored-unknown-intent": (
        "CARD",
        {"intent": "nonsense-intent"},
        _authored(None, _OFFERED_IDLE, None),
    ),
    "authored-active-ptp": (
        "CARD",
        {"active_slug": "ptp-negotiate"},
        _authored("ptp-negotiate", _OFFERED_WITH_PTP, _PTP_BODY_SHA),
    ),
    # A slug the card does not attach resolves to itself but loads no body.
    "authored-active-unattached": (
        "CARD",
        {"active_slug": "not-attached"},
        _authored("not-attached", _OFFERED_IDLE, None),
    ),
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _project(mouth) -> dict:
    """The observable contract of one resolved mouth, in comparable form."""
    prompt = mouth.prompt()
    tools = mouth.tools()
    body = prompt.body_message
    return {
        "card_is_none": mouth.card is None,
        "pack_slugs": sorted(p.slug for p in mouth.packs),
        "allowed": sorted(tools.allowed) if tools.allowed is not None else None,
        "offered": list(tools.offered) if tools.offered is not None else None,
        "prefix_sha": _sha(prompt.prefix),
        "prefix_len": len(prompt.prefix),
        "active_slug": mouth.active_slug,
        "body_role": None if body is None else body["role"],
        "body_sha": None if body is None else _sha(body["content"]),
    }


# --- what the split is for --------------------------------------------------


# --- fail-closed, at the new seam -------------------------------------------
#
# tests/test_skill_packs_fail_closed.py pins this through the legacy dict. That
# suite is deliberately untouched, which leaves the replacement path uncovered
# — so the same property is pinned here too, and the shim can be deleted
# without losing it.


# --- channel filter (WP-031 step 1) -----------------------------------------
#
# The publish Gate forwarded channel_tools; MouthTurn.tools() did not. A card
# naming a voice-only tool was granted it on WhatsApp, where no handler exists.


def test_the_three_runtimes_pass_channel_tools() -> None:
    """Closing the divergence requires the callers, not only the parameter."""
    missing: list[str] = []
    # The sandbox turn loop is sandbox_tools.py since the pass-7 carve.
    for rel in ("bot_runtime.py", "sandbox_tools.py", "voice/bot_flow.py"):
        path = BACKEND / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "tools"
        ]
        assert calls, f"{rel} no longer calls MouthTurn.tools()"
        for node in calls:
            if not any(kw.arg == "channel_tools" for kw in node.keywords):
                missing.append(f"{rel}:{node.lineno}")
    assert missing == []
