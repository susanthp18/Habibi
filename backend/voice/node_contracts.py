"""What each node needs in order to still be leaveable.

``voice/flows_dynamic`` offers a node only the tools the grant allows, which
stops a narrowed card raising KeyError mid-call. It introduces a quieter failure
in its place: a node whose every exit was dropped. The model is then holding a
turn with nothing to call, on a node whose whole job is to move somewhere else,
and the call goes round until the idle ladder hangs up on a borrower who did
nothing wrong.

So each node names the verbs that are its exits. Every one of them is in the
voice floor (``agent_core.tools.grant.VOICE_ALWAYS``), which is what makes the
contract satisfiable rather than aspirational -- the floor is part of every
grant, so these cannot be dropped by any card.
``tests/test_flows_survive_a_narrow_grant.py`` asserts that containment, so
adding a requirement here that a card *can* exclude fails the suite rather
than the call.

This is deliberately a plain dict with no imports. ``flow_graph`` runs in the API
process and must not pull in Pipecat; anything that wants to reason about node
exits statically can read this without importing ``voice.tools``.
"""

from __future__ import annotations

#: node key -> the verbs that can leave it.
#:
#: Read as: "if none of these survived the grant filter, this node is a dead
#: end." Nodes absent from this map either end the call themselves
#: (``call_ended``) or are reached only to terminate (``terminate_politely``).
NODE_REQUIRED: dict[str, frozenset[str]] = {
    # Says the disclosure, then moves on. Its exit is the disclosure verb.
    "greet_disclose": frozenset({"disclose_recording"}),
    # Listens for why they rang. Without this it cannot record the goal or move.
    "discover_intent": frozenset({"capture_call_goal"}),
    # Verification, inbound. Three outcomes: verified, refused, wrong person.
    "verify_identity": frozenset(
        {"verify_identity", "refuse_verification", "not_account_holder"}
    ),
    # Verification, outbound. Same three, different opening line.
    "confirm_identity": frozenset(
        {"verify_identity", "refuse_verification", "not_account_holder"}
    ),
    # The hub. Everything money-shaped is skill-gated and may legitimately be
    # absent; what may not be absent is the ability to leave.
    "state_position": frozenset({"begin_negotiate", "begin_dispute", "begin_wrap_up"}),
    "negotiate_ptp": frozenset({"begin_wrap_up", "return_to_position"}),
    "handle_dispute": frozenset({"return_to_position"}),
    "gated_upsell": frozenset({"return_to_position", "begin_wrap_up"}),
    "pre_close": frozenset({"return_to_position", "end_call"}),
    "escalate_close": frozenset({"end_call"}),
}


#: Developer directives the runtime attaches to a node *by key*, whatever the
#: author wrote in its instructions. These are the last runtime special-cases
#: of a node name, and they are declared here so the editor can say "this key
#: carries a built-in directive" instead of the author discovering it on a
#: call. ``flows_dynamic`` appends them; ``GET /flow/reserved-keys`` surfaces
#: them beside the transition targets.
#: Prefixed onto each node's developer block so a hop can evict the previous
#: node's instructions instead of stacking them (Flows APPEND).
NODE_INSTRUCTIONS_PREFIX = "CURRENT NODE:"

NODE_DIRECTIVES: dict[str, str] = {
    "confirm_identity": (
        "Do not call any tool until the caller has spoken and confirmed they are "
        "the account holder. Your first utterance is the greeting, your name, "
        "the bank, that the call is recorded for quality and compliance, and the "
        "confirmation question. Never mention a balance, overdue, or collections "
        "before they confirm. Do not put the recording notice in parentheses. "
        "Never open with a tool acknowledgement such as 'Sure, I can set that up.'"
    ),
    "escalate_close": (
        "If they ask a product or policy question, call search_knowledge_base. "
        "If they then name a specific product or policy facet after a catalog or "
        "names-only result, search_knowledge_base again before escalating. When "
        "the result is confident with passages, answer in at most two sentences "
        "from those passages. When it is not confident after that second search, "
        "say a specialist will follow up. Do not call request_callback after the "
        "caller refused a callback. Never ask which insurer or policy type they "
        "have. Speak the close, then call end_call. Do not ask further questions."
    ),
}
NODE_DIRECTIVES["pre_close"] = NODE_DIRECTIVES["escalate_close"]
