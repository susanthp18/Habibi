# The authoring unit is many cards; the runtime unit is one bundle

---
Status: accepted
---

An operator should be able to author as many specialist agents as they have real
boundaries — a door, collections, insurance, hardship, a document verifier — each
with its own persona, tool grant, skills, subgraph and eval fixtures, wired to
each other as typed edges. That is the product ask, and it is the right one: a
single card carrying every conversation is how a prompt grows until nobody can
say what it will do.

It does not follow that each specialist should be a separately deployed agent.

## Decision

**Many cards are authored. One bundle is deployed.** Publishing compiles every
member reachable from a card's handoff allowlist into a single artefact — one
namespaced graph, one grant per member, one hash — carried on one
`bot_deployments` row. A hop between specialists is a move within that graph, in
one process, on one deployment id.

## Considered options

**A deployment per specialist.** Rejected on three counts, each verified in this
tree rather than argued:

1. `db_prompt_studio.publish_prompt_version` inserts a `bot_deployments` row and
   records a canary experiment in the same transaction. If every specialist
   publishes itself, every specialist gets its own release id and its own
   canary, and a regulator's *"which version said this"* resolves to a set. One
   accountable version per call is not a nicety here; it is the thing the audit
   trail is for.
2. A hop that changes the system prefix costs a prompt-cache miss on the one
   channel where sub-second turns bind. Keeping the prefix constant and swapping
   a developer block is the mechanism the skill runtime already survives a
   thirty-turn call with.
3. `audit-reports/TARGET-ARCHITECTURE.md` refuses microservices and an event bus
   outright. The bus that a per-worker fleet would need was publish-only, its
   `start()` never called, and its bridge processor absent. Building the headline
   capability on it would have been a bet on unbuilt machinery.

**A single card with more prompt.** Rejected. It is where this started, and the
audit that prompted this work counted 22 card fields with no runtime reader —
the surface grows past the substance precisely because there is one place to put
everything.

## Consequences

**A specialist cannot be shipped alone.** Publishing a member promotes its
`prompt_versions` row; deploying is a fleet act. That is the price of one release
id, paid deliberately.

**The namespace is a bot id, written in exactly one place.** `fleet/compile.py`
is the only code in the tree that ever writes one, because everything a hop
touches — `target_bot_id`, the handoff allowlist, `CardHandoff.to_bot_id` — is
already a bot id, and a second vocabulary would be a lookup that can be wrong.
Authors never type a namespace; the roster is the card's own handoff allowlist.

**The merged graph is a separate field from the authored one.**
`CompiledBundle.fleet_flow` holds the merge; `flow` and `hashes.flow` stay the
author's own graph, so the canvas and the parity check keep describing what was
authored rather than what was compiled from it.

**A member's global tools become node tools.** `flows_dynamic` builds global
functions once per graph with no per-member filter, so a merged graph that kept a
union of every member's globals would hand the receiving specialist the sending
one's tools — the exact leak the hop exists to close, one level up.

**What a hop is, mechanically.** The cursor moves onto a node the receiving
member owns, and the offer is narrowed by whoever owns the node. Nothing else has
to change for the grant to follow, which is why there is no second mechanism: the
narrowing was already correct, and what was missing was the move. The invariant
is testable and tested — `split_key(current_node)[0] == active_specialist`.

**What is still refused.** Parallel specialists on a live call; mid-call voice
switching; free-text negotiation between agents on the audio path; and a blank
canvas. Agent-to-agent communication is typed edges with a fact-only carry
packet, and — when it lands — consultation off the audio path through the queue
that already exists.
