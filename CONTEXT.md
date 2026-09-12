# Habibi

A regulated collections platform. Autonomous agents speak to borrowers by voice and WhatsApp, while policy engines — not the language model — own every decision about money, contact and consent.

## Language

### Agents

**Mouth**:
The speaking surface of one agent: its prompt, persona, voice, guardrails and flow, published together as a single version.
_Avoid_: bot (the legacy spelling, still used for identifiers and table names)

**Agent Card**:
The contract for one mouth, checked at publish time. It names the agent's identity, the tools it may call, the agents it may hand off to, the skills it pins, the missions it may be sent on, and the engines it cannot unbind.
_Avoid_: config, manifest, profile

**Skill Pack**:
Procedural knowledge attached to a card — how to do one thing, plus the tools doing it requires. Passive: a pack never decides when it applies.
_Avoid_: playbook, prompt fragment, macro

**Locked Engine**:
A decision engine an author may not detach from a card. The model proposes; a locked engine disposes, and no card may publish without them.
_Avoid_: policy service, guardrail

**Deployment**:
The one version of a mouth that is live in a given environment.

### Permission

**Tool Grant**:
Everything an agent may execute, derived from its card, its attached packs and the channel it is speaking on. Fixed for as long as the card is fixed.
_Avoid_: allowlist, permissions, scope

**Offer**:
The subset of the grant placed in front of the model on a given turn. Narrowing an offer is a cost decision, never a safety one — an offer may only ever be smaller than the grant.
_Avoid_: exposed tools, available tools

**Gate**:
One publish-time check with four honest outcomes: pass, fail, warn, or skipped. A gate never reports green for a check it did not run. A gate that fails says what would let it pass.

**Assurance**:
How much a channel has proved about who it is talking to, as one of three levels. `endpoint` — the channel proved control of the endpoint (a WhatsApp sender matched to a CRM row; caller ID does not qualify). `challenge` — the customer supplied something only they know. Tools name the level they need; reads and reversible writes take `endpoint`, money and regulated acts take `challenge`.
_Avoid_: verified (a boolean, and the thing this replaced)

### Conversation

**Flow**:
The authored graph of conversation steps for a mouth. Steps the model chooses between are distinct from steps taken deterministically.
_Avoid_: script, workflow, journey

**Handoff**:
Transfer of a live conversation from one agent to another named on the first agent's card. The receiving agent brings its own card, and therefore its own grant — the hop moves the flow cursor onto a node that agent owns, and the offer is narrowed by whoever owns the node. All three mouths do this: voice through the node it lands on, text and the sandbox through the walker's cursor. A hop into a member with no compiled entry is still recorded and announced; what it does not do is swap the tools.
_Avoid_: transfer (reserved for reaching a human), routing

**Reachability**:
Whether traffic can arrive at a card at all — as the entry agent, through a handoff, by direct address, or not at all.

**Run-up**:
The turns before the one being judged, oldest first, excluding that turn itself. Built once per turn and passed to every per-turn judgment — intent, sentiment, retrieval planning — so none of them decides on a single sentence.
_Avoid_: history (the whole thread, and what the prompt carries), context (overloaded)

### Outbound

**Mission**:
One reason to place a call, with its own entry step, its own definition of success, and its own time budget. On the card it is the `objectives[]` entry; `objective` is the field name, not a synonym.
_Avoid_: campaign, intent

**Cadence**:
When to attempt a mission again. Mechanical only: a cadence may repeat an action, never change it.
_Avoid_: retry policy, schedule

**Deferral**:
A refusal that expires. Contact policy says *not yet* — cooling-off, a cap, a closed window — and names the instant it stops saying so, and the queued message waits for it rather than failing. Distinct from a refusal about the customer (DND, withdrawn consent, a settled account), which never expires and cancels.
_Avoid_: retry, backoff (both mean a transport failure here)

**Outcome**:
What a conversation settled, as one code from a closed vocabulary. The outcome is what post-call obligations and cadence both read.
_Avoid_: result, disposition, status
