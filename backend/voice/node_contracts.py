"""What each node needs in order to still be leaveable.

``_fns`` in ``voice/flows.py`` drops any tool the card did not grant, which stops
a narrowed card raising KeyError mid-call. It introduces a quieter failure in its
place: a node whose every exit was dropped. The model is then holding a turn with
nothing to call, on a node whose whole job is to move somewhere else, and the
call goes round until the idle ladder hangs up on a borrower who did nothing
wrong.

So each node names the verbs that are its exits. Every one of them is in
``voice.tools.ALWAYS_ON``, which is what makes the contract satisfiable rather
than aspirational -- the grant filter unions that set back in, so these cannot be
dropped by any card. ``tests/test_flows_survive_a_narrow_grant.py`` asserts that
containment, so adding a requirement here that a card *can* exclude fails the
suite rather than the call.

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
    "collections_hub": frozenset({"begin_dispute", "begin_wrap_up"}),
    "negotiate_ptp": frozenset({"begin_wrap_up", "return_to_position"}),
    "handle_dispute": frozenset({"return_to_position"}),
    "gated_upsell": frozenset({"return_to_position", "begin_wrap_up"}),
    "pre_close": frozenset({"return_to_position", "end_call"}),
    "escalate_close": frozenset({"end_call"}),
}
