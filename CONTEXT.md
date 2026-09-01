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
One publish-time check with three honest outcomes: pass, block, or skip. A gate never reports green for a check it did not run.

### Conversation

**Flow**:
The authored graph of conversation steps for a mouth. Steps the model chooses between are distinct from steps taken deterministically.
_Avoid_: script, workflow, journey

**Handoff**:
Transfer of a live conversation from one agent to another named on the first agent's card. The receiving agent brings its own card, and therefore its own grant.
_Avoid_: transfer (reserved for reaching a human), routing

**Reachability**:
Whether traffic can arrive at a card at all — as the entry agent, through a handoff, by direct address, or not at all.

### Outbound

**Mission**:
One reason to place a call, with its own entry step, its own definition of success, and its own time budget.
_Avoid_: campaign, objective, intent

**Cadence**:
When to attempt a mission again. Mechanical only: a cadence may repeat an action, never change it.
_Avoid_: retry policy, schedule

**Outcome**:
What a conversation settled, as one code from a closed vocabulary. The outcome is what post-call obligations and cadence both read.
_Avoid_: result, disposition, status
