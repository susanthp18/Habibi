# One owner for the tool grant, and it is the enforcement point

---
Status: accepted
---

Six different formulas across eight call sites computed some version of "which tools may this agent call", and they had already diverged: the publish gate's copy omitted connectors, so a skill pack legitimately naming an external tool failed a gate the runtime would have passed. We are collapsing all of them into one module that owns the **Tool Grant** and the **Offer** derived from it.

The module *is* the gate rather than a helper returning a set. Returning a set is what produced six formulas in the first place — every caller that receives one is free to union something onto it, and several did, including a hardcoded keep-set in the voice runtime and a hand-maintained tool list on the text path.

## Considered options

**A helper returning a set, with callers applying it.** This is what exists. It cannot prevent a seventh formula, because nothing stops a caller adjusting the set after receiving it.

**Two modules, one for publish and one for runtime.** Rejected: the publish gate's question is definitionally the union of every runtime answer, so two modules means two chances to disagree — which is the bug we are fixing. One module exposes both, and the relationship between them is asserted by a test.

## Consequences

The grant is recomputed when the **card** changes, not per turn and not per session. Nothing within a turn can alter it, so per-turn recomputation is waste; per-session caching is correct only while one conversation involves one card. That stops being true when handoff is real — a mid-call handoff changes the card and must change the grant with it. The current voice runtime filters its tool registry once at session start and would keep the handing-off agent's tools after the transfer. This decision is therefore a prerequisite for handoff, not merely an improvement alongside it.

Narrowing an Offer is explicitly not a safety mechanism. Loading a skill changes what the model is shown, never what it is permitted to run; the permission boundary is pack *attachment*, decided when the card is published. Any future change that tries to make activation a control must change the grant, not the offer.
