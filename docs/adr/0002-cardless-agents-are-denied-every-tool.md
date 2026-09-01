# A cardless agent is denied every tool

---
Status: accepted
---

An agent whose card is absent or empty previously ran **ungated** — no tool filtering at all, falling back to a hand-maintained list that contained every skill-gated write. We are inverting this: no card now means no tools.

The old behaviour existed to keep an unmigrated mouth working, and it is why the gating code carried a sentinel distinguishing "no packs, deny" from "legacy, allow everything". That sentinel is the mechanism by which the gate could invert: a card with an empty skill list plus a database fault produced the "legacy" sentinel and disabled gating entirely, on exactly the population the fallback was written to protect. A comment at the site asserted the opposite.

## Considered options

**Keep the legacy state and fix the sentinel.** Rejected. Every prompt version in the database is authored — 5 published, 2 draft, 11 archived, none null or empty — and no authored card has an empty skill list. The state being preserved has no instances, and preserving it keeps the branch that can invert.

**Deny-all, with a scaffold card for genuinely new agents.** Chosen. The scaffolding path already exists and produces a minimal valid card carrying the locked engines, so a new agent has somewhere to start that is authorable and publishable rather than silently permissive.

## Consequences

Fail-open becomes structurally unreachable rather than defended by a fix: there is no branch in which an absent card grants a tool. The hand-maintained fallback tool list is deleted along with its only consumer.

An agent created outside the scaffolding path will speak but call nothing, which is a visible failure. That is intended — the alternative is an agent that quietly has more authority than its author granted it.
