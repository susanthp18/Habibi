# 38 — Architecture boundaries

**Repo:** [susanthp18/Habibi](https://github.com/susanthp18/Habibi) at `D:\Hackathon`
**Product:** Habibi CRM (`Habibi/`) + collections backend (`backend/`)
**Date:** 2026-09-03
**Mode:** read-only. No source, lockfile, migration or config was changed except this file. No install, no server, no build, no migration was run.
**Companions:** `03-frontend-architecture.md`, `04-backend-architecture.md`, `05-dependency-graph.md`, `11-api-contracts.md`

Domain terms follow `CONTEXT.md`: Mouth, Agent Card, Skill Pack, Locked Engine, Tool Grant, Offer, Gate, Flow, Handoff, Mission, Cadence, Outcome.

This report asks one question: **do dependencies flow in a direction that serves this system?** Not whether they match a layer diagram. Habibi does not attempt Clean Architecture and should not be graded against it.

---

## Verdict

**Habibi has an explicit architecture, it is not a layer cake, and it is largely holding. The boundary that is failing is the one nobody named: `db.py`.**

The system's stated architecture is written down and applied — a **gated decision pipeline**, `features → candidates → veto → score → arbitrate → log → [enact]`, implemented four times over (`treatment`, `reco`, `authority`, `live_qa`), each behind a package façade that exports the decision function and deliberately withholds `enact`. Its architectural rule is about **ordering of gates, not layering of abstractions** — `agent_core/treatment/README.md:33` states it outright: *"Exploration is last, and that is the architectural boundary."* Graded against its own design, that structure is intact: **49 of 56 intra-engine import edges respect stage order, and the 7 that do not are type and copy-string imports, not control inversions.**

Three boundaries are enforced better than in most codebases of this size:

| Boundary | Measurement |
|---|---|
| **HTTP does not leak inward** | `fastapi`/`starlette` in **3 of 267** modules. `HTTPException` in **1** file (`main.py`, 202 uses). **Nothing imports `main.py`** — zero edges. |
| **Wire schemas do not leak inward** | `schemas.py` has exactly **2 importers**: `db` and `main`. |
| **Provider SDKs are contained** | `openai` 3 modules, `twilio` 3, `psycopg` 0 outside seed scripts, `pipecat` 19 — all but one inside `voice/`. In the frontend: **zero** provider SDKs outside one dynamically-imported hook. |
| **Authorization is total and provable** | A global `Depends(_authz_guard)` on the `FastAPI(...)` constructor, two reviewable tables, unregistered routes denied. Statically matched against every route: **314 of 314 covered.** |

What fails is orthogonal to all of that, and it comes in two shapes.

**The first is one file.** `db.py` is **18,088 lines with fan-in 101 and fan-out 46** — imported by 38% of the backend, and importing the domain back: the Locked Engines, `contact_policy`, the channel adapters, the job queue. Cutting *either* direction of its edges collapses the runtime strongly-connected component from **76 modules to 19**; trimming subsets barely moves it (76 → 71/73/75). The coupling is not diffuse. It is one file, and it has to be cut whole. Underneath it sits the version with regulatory teeth: the engines accept an injected connection and **fall back to opening their own** from the `db.engine` global — 64 modules, 262 references — so a decision and the row recording it can land in different transactions. `agent_core/treatment/engine.py:259` says so in its own comment: *"One connection for the whole read phase, then the log writes on its own."* A caller's rollback cannot retract the audit row.

**The second shape is the one the import graph cannot see, and it is the more important finding.** Five analysts working on different questions converged on the same pattern: **this system's regulated decisions are restated at call sites rather than imported.** Not badly-directed dependencies — *absent* ones.

| Regulated decision | Canonical owner | Independent restatements |
|---|---|---|
| Which tools an agent may run | `agent_core/tools/grant.py` (ADR-0001) | **4 live formulas**, with a verified divergence: the publish gate filters by channel, both runtimes do not |
| The outbound contact gate sequence | nobody | **7 sites**, two of them HTTP handlers ~320 lines apart |
| The RBI 08:00–19:00 calling window | `policy_rules.calling_window()` | **9 decision sites; 2 consult it.** `compliance/detectors.py:297-298` restates `8` and `19` sixteen lines above a comment reading *"one definition of the timezone fallback"* |
| The DPDP blocking-consent set | `contact_policy.BLOCKING_CONSENT` | **5 copies**, two in modules that already import `contact_policy` for other reasons |
| Indian rupee formatting | `money_inr.py` | **2 stragglers** — and they are the SMS the borrower reads and the sentence the agent speaks |
| Tenant isolation | `rls.py` (built, inert) | **248 hand-written SQL predicates across 44 modules** |
| The wire contract | `schemas.py` / `response_model` | **178 of 314 routes declare none**; the shape is assembled by hand inside `db.py` |

`agent_core/tools/grant.py` is the emblem: 247 lines, an accepted ADR behind it, characterised by two test files, and **zero production importers.** The boundary exists as a document and a module. Nothing imports it.

The same failure reaches the frontend. `src/types/` holds **zero** domain types; `src/data/*-seed.ts` — mock fixtures — hold **261**. `api/customers.ts:29` returns `apiGet<Customer[]>("/customers")` where `Customer` is declared in `data/customer360-seed.ts`. **229 unchecked casts, 0 runtime validations.** The schema of record for a regulated backend is a mock file only the frontend has ever agreed to.

**The honest summary: dependencies here mostly flow in sensible directions. What is missing is not a layer — it is an owner.** So almost every fix below is a subtraction or an import, not an abstraction: delete a connection fallback, import a constant that already exists, call the module the ADR already wrote, move a switch back one directory. The one genuinely structural job is `db.py`, and even that starts by naming five helpers.

The mechanism to enforce all of it is already in this repo and already proven at 314/314 — `authz.ROUTE_PERMISSIONS`. One table, applied by construction, unregistered entries denied, coverage provable by a test. Every boundary this report says is missing has that shape.

---

## 1. Scope and method

**In scope.** `backend/` production Python — 267 modules (top-level, `agent_core/**`, `voice/**`, `work_runtime/**`, `llm_gateway/**`), excluding `tests/`, `alembic/`, `scripts/`, `seed*`. `Habibi/src` TypeScript — 474 modules. `backend/docker-compose.yml`, `Dockerfile`, `requirements*.txt`. ADRs `0001` and `0002`.

**Out of scope.** `PRAXIST-main/` (guest tree, no runtime import edge into the product). `node_modules`, `.venv`, generated route tree internals.

**How the six analyses were combined.** Five analysts ran in parallel — dependency direction, domain isolation, API boundary, infrastructure boundary, frontend boundary — plus a direct thread. Every headline number below was measured at least twice by different people using different scripts; where two measurements disagree, both appear in *Analyst disagreements* with their methods rather than being silently reconciled.

**Technique.** stdlib `ast` over every module: each `Import`/`ImportFrom` recorded with importer, target, line, and whether it sits at module level (**eager**) or inside a `def` (**lazy**). Route decorators read from the AST, not by grep. SQL by regex requiring *both* a keyword and a `.execute(` on the same file. Frontend imports by regex with `@/*` resolved from `tsconfig.json`.

**Known false-positive modes, stated so the numbers can be trusted or discounted:**
- A **lazy** edge inside a never-called function is still counted. Lazy means *deferred*, never *optional*.
- SQL keyword counts can hit docstrings. The AST-exact cross-check is `from sqlalchemy import text`, and it is quoted wherever the claim matters.
- Route counts are decorator-shaped; a re-registration would double-count.
- Frontend value-vs-type import split over-counts VALUE for mixed specifiers (`import { A, type B }`).

**One tooling failure worth recording.** `grep -rn` and the ripgrep-backed search tool time out on this tree; every count here comes from a Python script instead. Separately, two analysts and I wrote `graph.json` into a shared scratchpad directory and clobbered each other. One of my intermediate results — "zero domain modules import `db`" — was an artifact of reading another agent's file, and it is the opposite of the truth. Every number below was re-derived under a private path after that was caught.

---

## 2. The architecture that actually exists

The brief asked whether `Presentation → Application → Domain → Infrastructure` holds *or another explicit architecture exists*. Another one exists, it is documented, and grading this system against the layer cake would produce the wrong findings.

### 2.1 The gated decision pipeline

`agent_core/treatment/README.md:31`, `agent_core/reco/README.md:20` and `agent_core/authority/README.md:9` all declare the same shape:

```
features → candidates → veto → score → arbitrate → explore → log → [enact]
```

Four packages implement it: `treatment` (25 modules), `reco` (14), `authority` (10), `live_qa` (10). The stated invariant is an **ordering** rule, not a layering rule — `treatment/README.md:33`:

> *"Exploration is last, and that is the architectural boundary. It sees only actions that already cleared every gate … so it decides which permitted thing happens, never whether a forbidden one does."*

**Measured: the ordering holds.** Ranking each module by its documented pipeline stage and counting intra-package edges:

| Package | intra edges | respect stage order | apparent inversions |
|---|---:|---:|---:|
| `agent_core.treatment` | 26 | 25 | 1 |
| `agent_core.reco` | 17 | 12 | 5 |
| `agent_core.authority` | 8 | 7 | 1 |
| `agent_core.live_qa` | 2 | 2 | 0 |
| `agent_core.compliance` | 3 | 3 | 0 |

**All 7 apparent inversions are my ranking's fault, not the code's**, and I verified each by hand. `reco/models.py:43-46` and `treatment/models.py:55` import `Candidate`, `SCHEMA_VERSION`, `ScoredOffer` — types and constants from later stages, because `models.py` in these packages is the **ML-model loader** (a scorer), not a low-level type module. I ranked it as the latter. `authority/policy.py:16` imports `escalate_line` from `talk` — a copy string. **Zero real control inversions.**

### 2.2 The façade is deliberate and `enact` is deliberately withheld

`agent_core/authority/__init__.py:17-19` exports exactly `recommend_authority`, `AuthorityResult`, the fee constants and the three verdicts. `agent_core/live_qa/__init__.py:13-14` exports `evaluate_live_qa` and `TurnFacts`. **Neither exports `enact`.** That is the boundary: callers may ask for a decision; they may not take the action.

Measured entry points from outside each package:

| Package | external edges | through the façade | direct to a submodule |
|---|---:|---:|---|
| `agent_core.treatment` | 18 | **18** | — |
| `agent_core.reco` | 15 | 13 | 2 → `reco.features` (`bot_tools`, `voice.tools`) |
| `agent_core.authority` | 21 | 15 | 2 → `.policy`, **2 → `.enact`**, 1 → `.matrix`, 1 → `.features` |
| `agent_core.live_qa` | 13 | 5 | **4 → `.enact`**, 2 → `.pack`, 2 → `.scorecard` |

**The `enact` bypasses are not gate bypasses, and I checked before reporting them.** `agent_core/authority/enact.py:35-37` re-enforces: `apply_goodwill` raises `AuthorityError("shadow_mode")` unless `config.mode()` is live, and it requires a `decision_id` — so the gate is enforced by *data*, not by import path. That is a legitimate design and I am not filing it.

One real exception, and it is documented as intentional: `enact.py:2-4` says the specialist path `post_waiver_for_dispute` *"does not need live mode — escalation is the review"*, and it calls `_post` with `decision_id=None`. A human at the disputes desk can post to `ledger_entries` with no engine decision. That is a designed exception with a stated rationale, not a violation.

### 2.3 The process boundary is real and enforced by packaging

Five app processes (`backend/docker-compose.yml:72,133,162,186,220`): `api`, `worker`, `bot_worker`, `voice`, `voice_insurance`. Two images: `Dockerfile:5` `base` and `Dockerfile:32` `voice`.

The dependency split is deliberate and explained at `requirements-voice.txt:4-5`:

> *"Kept separate from requirements.txt so CRM API upgrades are not coupled to Pipecat's transitive graph (onnxruntime, aiortc, av, silero)."*

`pipecat-ai[...]==1.6.0` is in `requirements-voice.txt:26` and absent from `requirements.txt`. **This is why 897 of 1,339 internal imports (67%) are lazy.** The lazy imports in this codebase are overwhelmingly not sloppiness — they are load-bearing deployment boundaries, keeping `voice/`'s SDK graph out of the API image.

That reading has a limit, and the dependency-direction analyst found it: the split is **additive**, not exclusive. `Dockerfile:19-20` installs `requirements.txt` — including `fastapi==0.139.2` — into the base layer of *every* image. So `voice/twilio_ops.py:93` importing `voice.ws_proxy` (which imports `fastapi` eagerly at `:13`) costs nothing today only because FastAPI ships in the voice image too. The containers are four commands over one dependency set, not four dependency boundaries.

---

## 3. Findings — Critical

### C1 — `db.py` is the boundary that does not exist, and it must be cut whole

`backend/db.py` is **18,088 lines, 440 functions, fan-in 101, fan-out 46**. 101 of 267 production modules import it — 38% of the backend. It is not a shared kernel: a shared kernel has fan-out 0. This one imports the domain back.

What persistence imports (all lazy unless marked):

| `db.py` site | target | why it matters |
|---|---|---|
| `db.py:1265`, `17781`, `17907-17947` | `agent_core.treatment` | persistence calls the decision engine |
| `db.py:17970`, `17988`, `17989` | `agent_core.authority`, `.enact` | and the money-posting stage |
| `db.py:2264, 2326, 6190, 6474, 8592, 10269, 10327` | `contact_policy` | and the RBI/DPDP veto |
| `db.py:12942…14707` (23 sites) | `agent_core.cards.*`, `.tuning`, `.skills.*` | and the card compiler |
| `db.py:10299, 10300, 10888` | `whatsapp`, `whatsapp_outbound` | and the channel adapters |
| `db.py:13539`, `15789` | `azure_speech`, `azure_openai` | and the provider SDKs |
| `db.py:10733` | `bot_jobs` | and the job queue |
| `db.py:18` – `:24` **eager** | `contact_window`, `money_inr`, `tenant_context`, `visibility`, `env_utils`, `pg_errors`, `schemas` | the only clean part |
| `db.py:18005` **eager** | `followups_db` | a re-export block carrying `# noqa: E402` |

**The measured consequence.** Building the full import graph (eager + lazy) and running Tarjan gives one strongly-connected component of **76 modules — 28% of the backend** — containing `db`, `contact_policy`, `payments`, `payment_events`, `promise_fulfillment`, `authz`, `azure_speech`, `twilio_sms`, `whatsapp_outbound` and all four Locked Engines. On the **eager-only** graph the largest SCC is 4, and those are package-`__init__` re-export pairs. The cycle is entirely a runtime phenomenon.

I then tested which cut breaks it:

| Cut | largest SCC |
|---|---:|
| *(baseline)* | **76** |
| Remove `db.py`'s **outgoing** edges | **19** |
| Remove `db.py`'s **incoming** edges | **19** |
| Remove only `db → provider/messaging` edges | 75 |
| Remove only `db → Locked Engine` edges | 73 |
| Remove all `db → agent_core.*` edges | 71 |

**Partial cuts buy nothing.** The coupling is not diffuse across 76 modules; it is one file, and it has to be split as a unit. What is left after the cut is a genuine 19-module cluster — `agent_core.turn`, `understanding`, `guardrails`, `prompt`, `tools.*`, `llm_gateway`, `azure_openai` — the agent-turn core, which is a real thing that belongs together.

**What it costs today, not in theory.** There is no bottom of the stack: a signature change in `agent_core/treatment/` can break the file that 101 modules import. And `db.py` cannot be split, because the split line would have to run through the domain.

---

### C2 — The Locked Engines can write an audit row for an action that was rolled back

Four decision engines accept an injected connection and **fall back to opening their own** from the `db.engine` module global. Measured across the backend: **64 modules, 262 references to `db.engine`.**

`agent_core/treatment/engine.py:241-259` is the shape, and its own comment states the cost:

```python
    if conn is not None:
        return _decide(conn, ...)
    # One connection for the whole read phase, then the log writes on its own.
    with db.engine.connect() as owned:
        return _decide(owned, ..., log_conn=None)
```

Same pattern at `agent_core/authority/engine.py:220-229`. **`agent_core/reco/engine.py:138-158` is worse: `_recommend` takes no `conn` parameter at all** — there is no seam to inject through, so every recommendation is read on a connection the caller does not own.

**The concrete failure.** When the fallback fires, the decision is read on one connection and the decision-log row is written on another. A caller that rolls back cannot retract the log row. In a regulated collections product that is an audit record asserting a treatment decision was taken for a borrower when it was not — and the audit trail is the artefact the RBI inspection reads.

**This is a subtraction, not an abstraction.** The injection path already exists in two of the four engines. The fix is to delete the fallback and make `conn` required; `agent_core/treatment/decisions.py:41-61` (`_writer`/`_reader`, *"use the caller's transaction, or open one"*) already expresses the intended contract.

---

### C3 — ADR-0001's owner module has zero importers, and the four live formulas have measurably diverged

`docs/adr/0001-one-owner-for-the-tool-grant.md` is **accepted**. It says the Tool Grant module *"is the gate rather than a helper returning a set"*, because *"every caller that receives one is free to union something onto it, and several did."*

`agent_core/tools/grant.py` is 247 lines. **Its production importer count is zero** — verified independently twice, by two different import-graph scripts. Its only references are `tests/test_tool_grant.py:26`, `tests/test_tool_grant_characterization.py:47`, `tests/test_import_cycles.py:35`. Its own docstring at `grant.py:30` concedes it: *"Nothing imports this yet."*

The four formulas actually in production:

| Site | Who uses it |
|---|---|
| `agent_core/skills/runtime.py:182-204` `MouthTurn.tools()` | voice (`voice/bot.py:1131-1136`), WhatsApp/text (`bot_runtime.py:912-941`), sandbox (`sandbox_runtime.py:230-244`) |
| `agent_core/cards/compile.py:494-510`, `:627-639` | the **publish gate** |
| `voice/tools.py:2911-2912` `keep = set(allowed_tool_names) \| ALWAYS_ON` | the voice runtime — literally the union ADR-0001 names as the bug |
| `flow_graph.py:773-785` `_FLOW_CONTROL_TOOLS` | the Studio's authoring catalog |

**A verified divergence, not a hypothetical one.** `agent_core/skills/intersect.py:65-68` — `_apply_channel` returns `names` unchanged when `channel_tools is None`. `compile.py:630` passes `channel_tools=`; `skills/runtime.py:194,200` **does not**. So the publish gate computes a channel-filtered grant and both runtimes compute a channel-blind one. A card naming a text-only tool is granted it on a voice call, where no handler exists — and the gate that validated the card applied a different rule than the runtime that enforces it. That is exactly the failure ADR-0001's opening paragraph describes.

**A second, in the codebase's own words.** `voice/tools.py:80-93` `ALWAYS_ON` holds 11 names; `flow_graph.py:773` `_FLOW_CONTROL_TOOLS` holds 10 — no `capture_call_goal`. `voice/tools.py:79` says so outright: *"the two still differ."* The test pinning them, `tests/test_tool_grant.py:133`, opens with `pytest.importorskip("voice.tools")` at `:135` — so it **silently skips wherever pipecat is absent**, which is the API image and CI.

---

### C4 — ADR-0002's fail-open is still the live default on both channels

`docs/adr/0002-cardless-agents-are-denied-every-tool.md` is accepted. `agent_core/skills/runtime.py:127-140` (`has_grant`) records the true state: the decision is *"accepted but not yet implemented."*

- **Text / WhatsApp:** `bot_runtime.py:947-951` ends `else bot_tools.TOOL_DEFINITIONS` — the hand-maintained list the ADR says was deleted. It lives at `bot_tools.py:59-85` and contains **all nine skill-gated writes**: `create_promise_to_pay`, `flag_dispute`, `apply_goodwill`, `capture_nonpayment_reason`, `set_contact_preference`, `capture_lead`, `decline_offer`, `request_documents`, `check_product_eligibility` (gate list at `agent_core/skills/intersect.py:29-48`).
- Enforcement inverts the same way: `bot_tools.py:831` — `if ctx.allowed_tools is not None and ...`. A cardless mouth is not merely *offered* every write; it is **permitted to execute** them.
- **Voice:** `voice/tools.py:2911` — `if allowed_tool_names is not None:`. Same inversion, on the regulated channel.

The state ADR-0002 calls structurally unreachable is the current default for any mouth whose card read fails.

---

### C5 — The borrower reads and hears rupees in Western grouping, in the two places `money_inr` exists to prevent

`money_inr.py:10-23` states why it was written: seven functions formatted rupees seven ways, and *"the model was reading — and speaking — 'one million two hundred thirty four thousand' shaped numbers to Indian borrowers."* Five call sites were converted to delegate (`db.py:3183`, `db.py:12298`, `customer_insights.py:47`, `agent_core/context.py:260`, `agent_core/authority/talk.py`).

**Two were not, and neither imports `money_inr`** — and they are the two that reach the borrower directly:

- `promise_fulfillment.py:105-112` `_fmt_inr` → `f"{int(n):,}"`, Python's Western grouping.
- `mission.py:368-372` `_inr` → the same.

| amount | `money_inr.inr` | `promise_fulfillment._fmt_inr` / `mission._inr` |
|---|---|---|
| 1234567 | `₹12,34,567` | `1,234,567` |
| 250000 | `₹2,50,000` | `250,000` |

Where they land, verified by reading the call sites:

- `promise_fulfillment.py:194-204` `_confirm_copy` — the SMS/WhatsApp a borrower receives: *"We've recorded your promise to pay ₹{rupees} by {date}."*
- `promise_fulfillment.py:203-220` `_spoken` — **what the agent says out loud**: *"I've recorded {rupees} rupees by {date}."*
- `promise_fulfillment.py:437`, `:466` — WhatsApp template parameters.
- `payment_events.py:158`, `:625` — imports the private `pf._fmt_inr` across module boundaries.
- `mission.py:375` `briefing()` — the developer message the outbound agent opens the call from.

This is a boundary finding, not a formatting nit: the shared kernel exists, is documented, is imported by everything that *displays* money, and is bypassed by everything that *speaks* it.

### C6 — The frontend's backend contract is declared in mock fixtures and never validated

`Habibi/src/types/` contains exactly one file — `view-transitions.d.ts`, a DOM ambient declaration — and **zero domain types**. `src/data/*-seed.ts`, the mock fixtures, export **261**.

```ts
// Habibi/src/api/customers.ts:11-20
import { customers, getCustomer, type Customer, … } from "@/data/customer360-seed";
// Habibi/src/api/customers.ts:27-29
export async function fetchCustomers(): Promise<Customer[]> {
  if (USE_MOCK) return mockDelay(customers);
  return apiGet<Customer[]>("/customers");     // unchecked cast
}
```

`Customer` — the type the live backend response is asserted to satisfy — is declared in the mock fixture file. **229 unchecked generic casts** (226 of them in `api/`), and `api/config.ts:183` is literally `return JSON.parse(text) as T`. Runtime validation: **0**. `zod@^3.24.2` is a dependency and is used exactly once, for route search params (`routes/customers.$customerId.tsx:16-18`) — a precise scan for `.safeParse(` and `*Schema.parse(` returns **0 hits**.

11 `api/` modules take their types this way (`api/audit.ts:9`, `api/authority.ts:22`, `api/contact-policy.ts:14`, `api/customers.ts:21,22`, `api/kb.ts:18`, `api/products.ts:15`, `api/voice-sandbox.ts:2`). `api/billing.ts:144` goes further and re-exports seed formatters into the app: `export { changePct, inr, inrCompact, sumRange, usageUnits } from "@/data/billing-seed"`.

**The failure this produces.** A backend field rename leaves `tsc` green across all 331 component files, leaves every test green, and leaves the mock demo working. It surfaces only as `undefined` rendering in a live collections console. The schema of record for a regulated backend is a mock file that only the frontend has ever agreed to.

**The fix is not "move the types to `src/types/`."** It is to parse at the single place that already exists — `apiGet` in `api/config.ts` — so the cast becomes a check. The transport boundary is already sound (§6); it just doesn't validate what comes back through it.

---

### C7 — The RBI contact-gate sequence is written seven times, and twice inside HTTP handlers

The regulated ordering for placing an outbound call is `mission.build → outbound.reserve → contact_policy.admit → outbound.suppress → outbound.place`. `outbound.py` owns `reserve`/`suppress`/`place`; `contact_policy.py` owns `admit`. Neither owns the **sequence**, and the sequence is where the compliance lives — reserve before admit, suppress on refusal, place only after.

Scripted for all three calls co-occurring in one module, then each site read by hand:

| site | reserve | admit | place |
|---|---|---|---|
| **`main.py:3768`** — `POST /twilio/voice/outbound` | 3768 | 3777 | 3811 (suppress 3788) |
| **`main.py:4088`** — `POST /demo/outbound-call` | 4088 | 4097 | 4152 (suppress 4144) |
| `cadence.py` | 429 | 445 | 492 |
| `campaigns.py` | 540 | 557 | 610 |
| `payment_events.py` | 866 | 583 | 882 |
| `agent_core/treatment/enact.py` | 360 | 102 | 384 |
| `scripts/dial_test.py` | 152 | 176 | 215 |

Two of them are HTTP handlers, ~320 lines apart in the same file, orchestrating five modules each. `POST /twilio/voice/outbound` (`main.py:3731`) also takes a `dict[str, Any]` body and opens its own `db.engine.begin()` — so the statutory calling-hours, DND, cooling-off and daily-cap gate ordering is HTTP-layer code, taking an unvalidated body, on the route that dials real PSTN numbers.

**Cost:** a change to the compliance ordering — say, checking `admit` before reserving a slot rather than after — has to land in seven files, and there is nothing that would fail if it landed in six. This is the same failure ADR-0001 describes for the Tool Grant, in a different regulated decision, and without an ADR.

---

## 4. Findings — High

### H1 — The real persistence API is four private helpers, and that is what blocks splitting `db.py`

`db.py` has **no `__all__`** and 440 top-level functions (178 public, 262 private). Outside modules reach past the public surface:

| private member | external sites | defined at |
|---|---:|---|
| `db._tenant()` | 80 | `db.py:113` |
| `db._rows()` | 57 | `db.py:382` |
| `db._one()` | 54 | `db.py:386` |
| `db._jsonb()` | 22 | `db.py:14068` |

Plus `db._actor_user_id`, `db._id`, `db._activity`, `db._IST`, `db._DEFAULT_PERSONA/_VOICE/_GUARDRAILS`, and `agent_core.cards.compile._ROLLBACK_TRIGGERS` reached from `db.py` in the other direction. Totals differ by scope: **239 sites / 41 modules** counting production only; **338 sites / 72 modules** counting tests and scripts.

Every importer uses `import db`; **not one uses `from db import X`** across all 211 production import statements. So all 440 names are reachable from every call site, and nothing marks which are contract.

Worst binders: `agent_core/skills/persist.py` (23), `ops_screens.py` (19), `work_runtime/adapter_pg.py` (18), `llm_gateway/canary.py` (14), `agent_core/twin.py` (13), `agent_core/eval/corpus.py` (10), `agent_core/mcp_http/tasks.py` (10).

**Why this is the finding that gates all the others.** C1 says `db.py` must be cut whole. H1 is why it currently cannot be: a split breaks 41 production modules bound to its privates and 101 bound to its name. Naming a row-helper module below `db.py` — `_rows`, `_one`, `_tenant`, `_jsonb`, `_actor_user_id`, which cover 202 of the 239 reach-throughs — is not an abstraction for a diagram. It is the precondition for any structural work on the largest file in the repo.

---

### H2 — The RBI calling window is decided in nine places; two consult the published rule set

The **constant** is shared well: `RBI_VOICE_START`/`RBI_VOICE_END` is imported from `contact_policy` at `agent_core/live_qa/checks.py:15`, `live_qa/scorecard.py:17`, `agent_core/policy_export.py:12`, `agent_core/treatment/timing.py:33`, `treatment/metrics.py:343`, `payment_events.py:139`.

The **decision** is not. `policy_rules.py:118` `calling_window(channel)` exists so a tenant can publish a narrower window — that is the entire point of the module, and `scripts/seed_policy_rules.py:99` seeds it. It has exactly **two** production call sites, both in `contact_policy.py`:

| site | consults `policy_rules.calling_window()` |
|---|---|
| `contact_policy.py:511` — the dial-time veto | **yes** |
| `contact_policy.py:682` — `narrow_window` | **yes** |
| `agent_core/treatment/timing.py:88-92` — scheduler window | no |
| `agent_core/live_qa/checks.py:171` — live barge | no |
| `agent_core/live_qa/scorecard.py:292` — post-call score | no |
| `agent_core/treatment/metrics.py:345-365` — **re-implemented in SQL** (`EXTRACT(HOUR FROM …)`) | no |
| `payment_events.py:132-145` `next_voice_window` | no |
| `agent_core/policy_export.py:53-59` — Rego export | no |
| **`agent_core/compliance/detectors.py:297-298`** — **its own literals** `RBI_CALL_START_HOUR = 8`, `RBI_CALL_END_HOUR = 19` | no |

**The cost, stated concretely.** A tenant that publishes a narrower window gets it enforced at dial time and nowhere else: the scheduler diaries a call the dialler then refuses, the QA scorecard grades that call against the wrong window, and the compliance sweep reports zero breaches against a window it is not checking.

`detectors.py:297-298` is the sharpest of these — it is the only site that restates the *numbers*, no test pins them (`RBI_CALL_START_HOUR` appears nowhere else in the repo), and sixteen lines below it the same function writes `from contact_policy import _zone  # one definition of the timezone fallback` (`detectors.py:314`). It imports one definition from `contact_policy` and restates another.

---

### H3 — `work_runtime` is a port with three of seven operations, so callers reach around it

The intention is right and worth copying. `work_runtime/api.py:1` — *"Public Temporal-shaped API. Adapter is chosen here, not at call sites."* `api.py:10-17` selects on `agent_core.platform_flags.temporal_enabled()`; `adapter_temporal.py:12-21` fails closed with `RuntimeError("temporal_adapter_not_promoted")` rather than silently falling back, and says why at `work_runtime/__init__.py:1-12`. The whole port is 42 lines.

**But the port exposes 3 operations and the Postgres adapter exposes 7.** `list_jobs`, `claim_next`, `finish`, `park_input_required` (`adapter_pg.py:144, 164, 189, 209`) have no port equivalent, so their callers import the concrete:

- `agent_core/clerk.py:17` — `from work_runtime import idempotency_key, start_workflow`
- `agent_core/clerk.py:18` — `from work_runtime.adapter_pg import claim_next, finish, park_input_required`

One file, two consecutive lines, port and concrete. Also `agent_core/copilot.py:101` and `main.py:1405` (`list_jobs`), and `tests/test_phase4.py:108,424` — so the tests protecting the swap are themselves bound to the concrete.

**Two callers skip the adapter entirely** and hand-write the queue table:
- `agent_core/treatment/enact.py:702` — `INSERT INTO work_runtime_jobs (…) VALUES (… 'mandate_representment', 'submitted' …)`
- `agent_core/treatment/sweep.py:243` — `INSERT INTO work_runtime_jobs (…) 'working' …`

**Cost, dated.** The day `TEMPORAL_ENABLED` is flipped, `start_workflow` routes to Temporal while `clerk`'s drain loop raises `RuntimeError` and two treatment paths keep inserting into the Postgres table nobody is draining. That is a split-brain job queue, and it is the exact swap the package was built to make safe.

There is no `Protocol` or `ABC` in `work_runtime/` — the contract is duck-typed. The two adapters agree today only because `adapter_temporal` is three `raise` statements.

---

### H4 — Thirty-one tables are written from more than one module, including the regulated ones

Scripting `INSERT INTO` / `UPDATE … SET` / `DELETE FROM` targets across all production modules: **138 tables written, 31 of them by more than one module.** The ones that matter:

| table | writers |
|---|---|
| `ledger_entries` — **money** | `payments.py:171`, `payment_events.py:301`, `agent_core/authority/enact.py:163` |
| `consent_records` — **DPDP consent** | `db.py:6630`, `contact_policy.py:708` |
| `violations` — **compliance** | `db.py:7090`, `agent_core/compliance/scan.py:109`, `voice/persist.py:639` |
| `call_attempts` | `outbound.py:373`, `call_closer.py:1057`, `post_call_actions.py:395`, `voice/amd.py:411` |
| `promises` | `db.py:5147`, `promise_fulfillment.py:908` |
| `followups` | `db.py:5220`, `post_call_actions.py:218`, `promise_fulfillment.py:921`, `agent_core/treatment/enact.py:453` |
| `work_runtime_jobs` | `work_runtime/adapter_pg.py:63`, `agent_core/treatment/enact.py:706`, `agent_core/treatment/sweep.py:247` |
| `messages` | `db.py:10309`, `bot_jobs.py:283`, `bot_runtime.py:411`, `promise_fulfillment.py:426`, `written_followup.py:300` |

**Why this is a boundary finding and not a style one.** Two modules writing the same table are coupled with **no import edge at all** — the import graph is blind to it. Every invariant on `ledger_entries` must now be re-asserted in three places, and the three do not share a code path. This is also the coupling the dependency-direction analyst named as the blind spot in their own method, and it is denser than the import graph.

---

### H5 — The tenant predicate is hand-written in a hundred files and the Postgres backstop is not switched on

`db.py` centralises the *engine*: `create_engine` appears exactly twice in the tree (`db.py:15,138` and `tests/test_rls.py:260`), and `db.py:138-183` passes the tenant as a libpq **startup parameter** so it cannot be un-set by a ROLLBACK. That part is excellent.

What is not centralised is the predicate. **248 hand-written `tenant_id` SQL predicates across 44 production modules**, and **306 `db._tenant()` call sites across 55**. `from sqlalchemy import text` appears in **102 of 267 modules**; **872 raw-SQL lines live outside `db.py`**, across 117 modules.

`rls.py` is the designed answer — 634 lines deriving row-level-security policies from the foreign-key graph, with a rationale (`rls.py:1-30`) that names this exact failure: *"a forgotten predicate is not a crash — it is one tenant reading another's rows, returned with a 200."* Its application importer count is **zero**, which is **correct**: it is operator tooling driven by `scripts/rls.py:34` and pinned by `tests/test_rls.py`. Flagging it as dead code would be wrong.

The finding is that it is **inert**: `rls.py:19-23` states the application currently connects as a role with `BYPASSRLS`, and `enable()` refuses in that case rather than pretending. So until an operator runs it against a non-bypassing role, the 248 hand-written predicates are the only live tenant defence. I could not check whether that has been done — no database access under the read-only constraint.

---

### H6 — The voice turn bypasses the breaker, the spend cap and the metering the text turn goes through

Two Azure OpenAI clients exist on different axes:

- `azure_openai.py:14` — `from openai import AzureOpenAI` (sync). Every call goes through `_azure_call` (`azure_openai.py:146-150`), which acquires a semaphore *outside* `circuit_breaker.get_breaker("azure_openai")` so an internal busy signal is not recorded as a dependency failure — a deliberate, documented distinction (`:142-145`).
- `voice/llm_pool.py:22` — `from openai import AsyncAzureOpenAI, DefaultAsyncHttpxClient` (async), feeding `pipecat.services.azure.llm.AzureLLMService` at `:24`. **No breaker, no `llm_gateway` spend cap, no `usage_meter` path.**

So a rate-limit storm on the voice path will not open the circuit the text path depends on, and the two do not share a cost ceiling.

Three Twilio clients with three credential reads: `twilio_sms.py:73-76`, `voice/twilio_ops.py:257-259` (a byte-identical `Client(sid, token, http_client=TwilioHttpClient(timeout=10))`), and `main.py:3398` `from twilio.request_validator import RequestValidator` inside a route helper — webhook-signature validation living in the HTTP layer rather than in a Twilio adapter.

More broadly: **the circuit breaker covers 4 of roughly 12 outbound dependencies.** Covered — `azure_openai.py:146`, `azure_speech.py:411`, `whatsapp.py:70,130`, `storage.py:160`. Not covered — `twilio_sms.py:76`, `voice/twilio_ops.py:257`, `webhooks_dispatch.py:171`, `llm_gateway/client.py:116`, `provider_tts.py:148,166,191`, `provider_voice_sync.py:77`, `tts_catalog_sync.py:105`, `voice_sandbox.py:113`, `voice/llm_pool.py:236`, `agent_core/providers/fish_service.py:92,109,111`, `agent_core/providers/fish_tts.py:177,300`, `agent_core/providers/openrouter_tts.py:122`, `agent_core/vault/persist.py:155,172`, `agent_core/connectors/persist.py:361,394`. Three bespoke retry loops, no shared policy: `llm_gateway/client.py:114`, `webhooks_dispatch.py:365-406`, `azure_speech.py:429`.

The mechanism is good and the mapping is right — `CircuitOpenError` becomes a 503 once, at `main.py:712-717`, and breaker state is exposed through `/ready` (`main.py:767`). Extend it; do not invent a second one.

---

### H7 — The decision layer imports the channel adapters

The engines that decide *what* to do also import the wire that carries it:

| site | target |
|---|---|
| `agent_core/treatment/enact.py:296` | `twilio_sms` (inside `_send_sms`) |
| `promise_fulfillment.py:23` **eager** | `webhooks_dispatch` |
| `promise_fulfillment.py:419` | `whatsapp_outbound` |
| `promise_fulfillment.py:689`, `:999` | `twilio_sms` |
| `payments.py:20` **eager** | `webhooks_dispatch` |
| `agent_core/reco/models.py:466`, `agent_core/tools/kb_plan.py:270`, `agent_core/treatment/rerank.py:146`, `agent_core/understanding.py:359` | `azure_openai` |

**Cost:** adding a channel means editing the enactment engine, and the enactment engine cannot be exercised without Twilio configuration. The concept of a seam is already half-present — `enact.py` raises `NoExecutor("no_phone_on_file")`, naming an executor that does not exist as a type.

---

### H8 — `USE_MOCK` is a presentation-layer conditional, and it is used as a capability check it cannot perform

`USE_MOCK` has 378 references. 308 are inside `api/`, which is correct — `api/config.ts:11-24` is a well-built switch that throws if a production build tries to enable it. But **25 references sit in `components/` and 42 in `routes/`, across 23 screen files**, and they are branches that change what renders:

- `components/floor/ApprovalsQueue.tsx:9` — `if (USE_MOCK || data.length === 0) return null;`
- `routes/agent-studio.skills.index.tsx:177,183` — `disabled={USE_MOCK}`
- `routes/integrations.tsx:211` — `{!USE_MOCK && …}`
- `routes/documents.tsx:142` — `USE_MOCK && d.id.endsWith("7") && Math.random() < 0.15`
- `routes/floor.tsx:65,72,166,203,211`

**Cost:** the demo and the product are different applications, and the difference is decided in JSX. Widgets that only render under mock have never been seen against a live backend; widgets hidden under mock are never demoed.

The sharpest instance is `routes/callbacks.tsx:83` — `if (!USE_MOCK) return [UNASSIGNED_LABEL, ...humanNames(staff)]`. That asks *"are we mocked?"* when the real question is *"did `/staff` return rows?"* So a live backend with an empty `/staff` renders an empty assignee dropdown with no error. The boundary that prevents this already exists: return the capability from `api/`, and let `USE_MOCK` stay in `api/config.ts`.
### H9 — Forty-two write routes accept an unvalidated body, including every money path

`schemas.py` holds 247 Pydantic models, 186 with `extra="forbid"`, and `main.py` declares **zero** `BaseModel` of its own — the typed half is done properly. But of 152 POST/PATCH handlers: **70 take a typed body, 33 take `dict[str, Any]` or `Body(...)`, 9 take a raw `Request` and hand-parse**, 40 have no body. With the 7 untyped DELETEs, **42 write routes have no schema at the boundary.**

The ones touching regulated state:

| `main.py` | route | what is unvalidated |
|---|---|---|
| `:2464`, `:2476` | `POST /vault/refs`, `…/rotate` | `secret=str(payload.get("secret") or "")` — an omitted or mistyped secret becomes `""`, is stored as a vault ref, and returns 200 |
| `:2490` | `POST /mcp/keys` | **tool grants.** `scopes` checked only for `isinstance(list)`; element types unchecked, then passed to `mint_key` |
| `:2857` | `PATCH /roles/{id}/permissions` | **RBAC.** `permissionIds` list-checked, then `[str(x) for x in ids]` into `db.replace_role_permissions` — arbitrary strings become grants |
| `:3731` | `POST /twilio/voice/outbound` | **contact windows + PSTN.** `to`/`phone`, `customerId`/`customer_id`, `botId`, all `str(...).strip()`, dual-key accepted |
| `:3835` | `PATCH /platform/switches/{key}` | kill switches; only `isinstance(enabled, bool)` |
| `:795`, `:825`, `:857`, `:882` | the four payment routes | **money.** Raw `Request` / raw body → `json.loads` → `parse_webhook_payload` / `pe.ingest(conn, body)` |
| `:4879`, `:4955`, `:4975` | `POST /outbound/campaigns[/…]` | **contact windows.** Cohort selector, targets, status — all `dict[str, Any]` |
| `:2598` | `POST /a2a` | task creation, and doubly exempt from auth (see §7) |

Separately, **61 of the 247 models carry no `model_config`**, so unknown fields are silently *ignored* rather than rejected — including the request models `PromiseCreateRequest`, `PaymentPlanCreateRequest`, `DisputeCreateRequest`, `HandoffDisclosureRequest`.

---

### H10 — Twenty-eight handlers own a database transaction, and thirteen author SQL inside the controller

Verified good news first: **`httpx` 0, `requests` 0, `psycopg` 0, `boto3` 0, `subprocess` 0 inside any handler.** Provider access goes through thin adapters. The controllers do not hold low-level *network* clients.

They hold the low-level *database* client. **28 distinct handlers open their own connection or transaction** — `db.engine.begin()` in 13 (`main.py:786, 802, 842, 875, 894, 3645, 3701, 3757, 3845, 4054, 4898, 4964, 5001`), `db.engine.connect()` in 16 (`:819, 2702, 2821, 3831, 3946, 3997, 4761, 4781, 4815, 4842, 4857, 4944, 5012, 5037, 5057, 5092, 5138`). **Thirteen of them author SQL inline**, 16 sites (`:2704, 2823, 2829, 3702, 3947, 4055, 4069, 4782, 4816, 4858, 5013, 5038, 5058, 5064, 5093, 5141`). Seven sites reach into `db.py` privates from a handler: `db._rows` (`:2822, 2828`), `db._actor_user_id` (`:3850, 4911`), `db._tenant` (`:3957, 4064`), `db._one` (`:2703`).

The tenancy consequence is the serious one. Nothing in `main.py` binds a tenant from the request — `tenant_context` defaults to the process-wide `db.TENANT_ID` — and `main.py:392-397` lists RLS tenant isolation among the controls that are **off**, with `_assert_hardening_gate` (`:401`) refusing to boot in production without `ALLOW_UNHARDENED_PRODUCTION=1`. So the tenant predicate is built by **string concatenation in the handler**: `main.py:4773`, `:4852`, `:5029` assemble `clauses = ["a.tenant_id = :tenant"]` then `f"WHERE {' AND '.join(clauses)}"`, with more hard-coded at `:2824, 2835, 3705, 3952, 4059, 4822, 5014, 5060`. There is no second line of defence behind any of them (H5).

---

### H11 — 178 of 314 routes have no response contract, and the wire shape is therefore defined inside `db.py`

**136 routes declare a `response_model` (43%)** — GET 74/152, POST 42/125, PATCH 19/28, DELETE 1/7, WebSocket 0/2, across 104 distinct models. Route decorators carry `tags`, `summary`, `operation_id`, `responses` and `dependencies` **zero** times, so there is no generated documentation either.

Of the rest: **59 handlers return a `db.*` result directly with no model**, 7 return raw DB rows (`[dict(r) for r in rows]`), 18 assemble a literal dict inline. For those 178 routes the contract is **365 distinct camelCase dict keys, 655 occurrences, hand-built across 18,000 lines of `db.py`** — which is also why `db.py:24` imports the response models eagerly.

The split is per-subsystem, not chronological:

| declares a model | declares none |
|---|---|
| `/prompt-versions` 10/10, `/handoff` 6/6, `/conversations` 6/6, `/flow` 5/5, `/kb` 20/23, `/customers` 5/6, `/routing-rules` 5/6 | `/agent-studio` **0/26**, `/outbound` 0/14, `/eval` 0/11, `/treatment` 0/9, `/mcp` 0/7, `/twilio` 0/7, `/connectors` 0/6, `/webhook-endpoints` 0/6, `/a2a` 0/5, `/gateway` 0/4 |

The older CRM routes have a contract; every newer agent-platform subsystem skipped it. A per-1000-line banding of `main.py` shows the same shape, not a gradient — the 2000–2999 band is 12%, and it is exactly the `/agent-studio`, `/connectors`, `/vault`, `/mcp`, `/a2a`, `/gateway`, `/eval` block.

**Where this becomes a live defect.** `main.py:5008-5016` does `SELECT * FROM campaign_runs` and `main.py:4846` does `SELECT r.*`, straight to the wire. `/outbound/number-pools` therefore ships `tenant_id` to the browser — and the frontend has typed it as the contract. `Habibi/src/api/outbound.ts:301-307` says so, and is worth quoting because it is the clearest statement of the problem anywhere in the repo:

> *"This endpoint has no response_model on the server: it returns raw table rows, so these field names ARE the contract and they are snake_case, unlike every other type in this file. Mirrors sql/22_campaigns.sql."*

Adding a column to `campaign_runs` changes the public API. The frontend knows, wrote it down, and had no way to fix it from its side.

---

## 5. Findings — Medium

**M1 — The DPDP blocking-consent set is stated five times.** `contact_policy.py:37` `BLOCKING_CONSENT` is canonical `{"opted_out","dnd","expired"}`. Four independent copies, currently identical: `payment_events.py:28`, `promise_fulfillment.py:29`, `capture.py:331` (`_CONSENT_BLOCKING_STATUSES`), `agent_core/reco/arbitration.py:39` (`_CONSENT_BLOCKING`). Only `written_followup.py:174-177` imports the canonical one. `payment_events.py` and `promise_fulfillment.py` **already import `contact_policy` elsewhere** (`payment_events.py:134,540,816`; `promise_fulfillment.py:589,998`), so the copy buys nothing at all. Adding a fifth blocking status — a DPDP withdrawal state — is five edits, and missing one means a channel the borrower opted out of keeps sending.

**M2 — `compliance_copy.tenant_contacts` opens its own connection.** `compliance_copy.py:50` — `with dbmod.engine.connect() as conn:` — and it takes no `conn` parameter. Both callers are already inside a transaction (`agent_core/treatment/enact.py:231`, `written_followup.py:248`), so the RBI §100AA disclosure footer is read outside the caller's transaction and cannot see a tenant row written earlier in it. `tests/test_outbound_completion.py:94` works around this with `monkeypatch.setattr(compliance_copy, "written_footer", …)`, which means the module the disclosure requirement depends on has its DB path untested at the unit level. The fix is one parameter.

**M3 — The TypeScript port of the contact-policy veto has two verified divergences.** `Habibi/src/api/contact-policy.ts:90-207` reimplements `contact_policy._veto` with its own `RBI_VOICE_START = 8`/`END = 19` (`:90-91`), day parser (`:125-148`) and veto ladder (`mockVeto`, `:176-207`). It is honestly labelled and gated behind `USE_MOCK`. Divergences: it has **no `data_purpose === "promotional"` check** — the DPDP purpose-limitation refusal that Python raises as `REASON_NO_PROMO_CONSENT` at `contact_policy.py:494-499` — and it reads only `contact.dnd` where Python reads `customer.get("dnd") or customer.get("dnd_registry")` (`contact_policy.py:504`). Bounded to dev/demo builds, so not High. But the demo teaches operators a rule that permits a promotional contact the real veto refuses.

To be fair to this file, its header is the best statement of the boundary in the repo (`api/contact-policy.ts:5-10`): *"The answer is the backend's, never the browser's… Recomputing any part of it here produces a second opinion that disagrees with the veto the dialler will actually apply, which on this screen means telling an agent it is fine to ring someone at 03:00."* The live path obeys that completely. Only the mock branch does not.

**M4 — 42% of frontend mutations are declared in screens.** `useQuery` is almost perfectly encapsulated — 119 in `api/`, 1 in `components/`, 1 in `routes/`. `useMutation` is not: 59 in `api/`, **12 in `components/`, 31 in `routes/`**. Query keys are ad-hoc string arrays invalidated by hand (`routes/callbacks.tsx:78`, `routes/customers.$customerId.lazy.tsx:117-118,179`); there is no key factory, so an invalidation typo fails silently rather than erroring.

**M5 — Config is read in business code, not at the edge.** `os.getenv` at **212 sites across 77 modules**; `os.environ` at 12 more. The typed helpers `env_utils.env_int/env_float` are used at only 47 sites in 14 modules — 4.4× less. Adapters reading their own env is fine (`azure_openai.py`, `azure_speech.py`, `storage.py`). What is not: `agent_core/treatment/models.py:591,601,607` and `agent_core/tools/kb_rerank.py:74,87,94,112` — model and reranker behaviour depending on process environment read at call time. `agent_core/treatment/config.py` runs both idioms in one file (6 `os.getenv`, 21 `env_int/env_float`). And `db.py:13987` is an env read 13,900 lines into the file.

**M6 — `routes/sandbox.lazy.tsx:433` bypasses the transport wrapper.** Raw `fetch(\`${API_BASE_URL}/interactions/${id}/export?format=${format}\`)` with no headers and no `credentials`, while `apiGetBlob` (`api/config.ts:264`) exists and does exactly this with `X-API-Key`, `X-Actor-User-Id` and the timeout. It is the **only** network call outside `src/api/` in the entire frontend — 6 real `fetch` calls exist and 5 are in `api/config.ts`. The day the backend enforces `API_KEY`, this one export 401s while everything else succeeds.

**M7 — Two competing TTS abstractions.** `agent_core/providers/factory.py` (pipecat binding, live calls) and `provider_tts.py` (HTTP preview) are separate dispatch paths over the same vendors, and the façade is bypassed by its own consumers: `provider_tts.py:180,215,271` and `provider_voice_sync.py:211,239` import the `fish_tts`/`openrouter_tts` concretes directly. `provider_tts.py:250-252` is a second vendor dispatch table and `:261-276` already special-cases `"fish"` in the cache salt. Adding a vendor means editing both paths.

**M8 — `voice/twilio_ops.py:93` imports the HTTP layer to read a feature flag.** `from voice.ws_proxy import ws_proxy_enabled`, and `voice/ws_proxy.py:13` imports `fastapi` eagerly. Its cost today is **zero** — and that is the finding. `Dockerfile:19-20` puts `requirements.txt` (with `fastapi==0.139.2`) in the base layer of every image, so the break is masked by packaging rather than prevented by design.

**M9 — `followups_db.py` and `voice/persist.py` are a second and third `db.py`.** `followups_db.py` holds 58 SQL statements / 53 `.execute(` and has exactly one importer — `db.py:18005`, an eager re-export block carrying `# noqa: E402`. `voice/persist.py` holds 37/28 and opens 22 of its own connections. Three persistence modules, no shared conventions; `followups_db.py:16` and `:1519` reach into `db._IST`.

**M10 — 83 distinct `db.py` error codes collapse into one HTTP status.** `_handle_write` (`main.py:720-738`) maps `KeyError→404`, `PermissionError→403`, `ValueError→409`, `IntegrityError→409` across 82 call sites. `db.py` raises `ValueError` **83 times**, and they are not one kind of thing: `bot_id_required`, `empty_message`, `invalid_severity`, `invalid_updated_after` mean *the client sent garbage* (422), while `publish_conflict`, `handoff_already_claimed`, `deployment_already_active` mean *someone got there first, refetch and retry* (409). A client cannot write correct retry logic against this. And because `detail` is `str(exc)`, the internal snake_case error code **is** the public error contract, declared nowhere.

**M11 — Authentication is not total; there are seven schemes.** Authorization is (see §7). Authentication is one middleware (`ApiKeyMiddleware`, `main.py:260`) plus six handler-local schemes: `_twilio_signature_ok` (`main.py:3488, 3555, 3577, 3619, 3686`), `payments.verify_webhook_signature` (`:832`), `payment_events.verify_webhook_signature` (`:867`), `whatsapp.verify_signature` (`:4611`), `_voice_ws_upgrade_authorized` (`:4233`), `a2a_mod.require_partner(headers)` (`:2604`). Inbound webhooks legitimately need signature auth rather than API keys — the finding is that six of them are each implemented at a call site rather than as one boundary. `POST /a2a` is *doubly* exempt: an early return at `main.py:279-280` **and** an entry in `authz.PUBLIC_ROUTES` (`authz.py:246`), while taking `dict[str, Any]` and creating platform tasks.

---

## 6. Findings — Low

**L1 — Type-only inversions in the frontend.** `api/promises.ts:15,16` import `CreateInput` and `PlanInput` from `components/promises/PromiseSheet` and `PlanBuilderSheet` — the data layer's write signature is defined by a form component's draft type. Also `lib/gate-status.ts:21` and `data/callbacks-seed.ts:5` importing `LozengeTone` from the design system. All erased at compile time; they cost navigability, not correctness.

**L2 — One frontend feature cycle.** `components/sandbox/TuningStudio.tsx:9 → components/prompt-studio/VoiceCatalogBrowser.tsx` and `components/prompt-studio/AgentCardPanels.tsx:31 → components/sandbox/EvalCockpit.tsx`. 4 edges, both directions, out of 119 feature→feature edges — cross-feature coupling is otherwise 14/119, which is low.

**L3 — The Outcome vocabulary is stated four times.** `call_closer.py:66-84` (15 codes), `agent_core/cards/compile.py:123-141` (identical, with the restatement documented at `:120-122`), `alembic/versions/20260822_0094_outbound_attempts.py:105-120`, and a `CHECK` in `sql/21_outbound.sql`. Currently consistent and pinned by `tests/test_outbound_missions.py:510`, which runs without a database. Separately, `agent_core/treatment/decisions.py:310-325` defines a *different* nine-value set also named `OUTCOMES` — a collision against `CONTEXT.md`'s single "Outcome" term, not a logic duplicate.

**L4 — Two eager `agent_core → db` edges.** `agent_core/cards/clone.py:15` and `agent_core/skills/persist.py:12` are the only module-level `import db` inside the card and skill packages; the other 31 `agent_core → db` edges are lazy. They pull `db`'s eager closure into any process that touches card cloning or skill persistence.

**L5 — `components/sandbox/inspector/TwinTab.tsx` collapses every layer into one leaf.** `:5` imports `apiGet, apiPost, USE_MOCK, mockDelay`; `:8-14` declares its own `CorpusRow` DTO; `:23` branches on `USE_MOCK`; `:26` posts to `/eval/twin-corpus/grow`; `:65` disables on `USE_MOCK`. It is the only file in the frontend that does this, which is exactly why it is worth fixing before it becomes the pattern.

**L6 — `src/hooks/` is a dead directory.** Two files; `use-mobile.tsx` has zero importers and `use-min-width.ts` has one. The real hooks convention is `api/*.ts` and co-located files like `components/sandbox/voice/useSandboxLiveCall.ts` — which is also where the only provider SDK in the frontend lives, and arguably belongs in `lib/`.

---

## 7. What is already right — copy these, and do not regress them

Recorded because a remediation pass aimed at C1 could easily damage several of these.

**Nothing imports `main.py`.** Zero edges, across 267 modules and 1,339 import statements. The 5,449-line HTTP file is a pure sink. For a codebase with a god module in it, that is a striking and deliberate result — whatever went wrong with `db.py` did not go wrong with the HTTP layer.

**The web framework does not leak.** `fastapi`/`starlette` appear in exactly **3 modules**: `main.py:19-32`, `voice/ws_proxy.py:13`, `agent_core/mcp_http/http_app.py:9-13`. `HTTPException` is referenced **202 times, all in `main.py`, zero elsewhere** — verified by a full scan of every production file. The practical payoff is exactly what you would want: every policy engine is reusable by the voice worker, the WhatsApp worker and the background sweeps, because none of them can raise a web error.

**Wire schemas do not leak inward either.** `schemas.py` has exactly **2 importers** — `db` and `main`. 247 wire classes, and the domain never sees them.

**Engine ownership is genuinely centralised.** `create_engine` appears **twice in the entire tree** (`db.py:15,138`, plus `tests/test_rls.py:260`). `db.py:138-183` passes the tenant as a libpq *startup parameter* so no ROLLBACK can revert it, with the `@event.listens_for(engine, "begin")` `SET LOCAL` override beside it and the reasoning written out. This part of `db.py` is the seam. The other 17,900 lines are not.

**The Protocol seams in the engines are real and documented.** `agent_core/treatment/features.py:397` — `class FeatureProvider(Protocol)`, docstring: *"The seam. Implement against your own schema and the rest works."* — with `SqlFeatureProvider` beside it as the concrete. Repeated at `agent_core/reco/features.py:193` and `agent_core/authority/features.py:87`, plus `Recommender(Protocol)` at `treatment/scoring.py:183` and `reco/scoring.py:68`. **This is the pattern the rest of the repo should adopt**: the domain owns the interface, the SQL implementation is a swappable class. It already exists here; it just was not extended to persistence.

**Half the domain is already pure.** 51 of 102 domain-intent modules — 12,414 lines — have no SQL, no `db` import, no provider SDK. Fully pure and worth naming: `money_inr.py` and `contact_window.py` (leaf modules, stdlib only, docstrings that name the divergent copies they replaced and why they must import nothing), `agent_core/authority/matrix.py` (196 lines, a pure decision table), `agent_core/live_qa/checks.py` (15/15 pure functions over a `TurnFacts` value object — the whole live-compliance suite runs with no DB and no clock), `agent_core/treatment/timing.py`, `treatment/scoring.py`, `reco/scoring.py`, `compliance/detectors.py`, `skills/intersect.py`, `tools/catalog.py`, `agent_core/cards/compile.py` (981 lines), `agent_core/understanding.py`.

**`visibility.py` is how to keep a storage-shaped rule out of the storage layer.** A regulated rule — row visibility — expressed as a pure function returning a SQL fragment (`visibility.py:148-163`). No cursor, fully testable, one string to review.

**`contact_policy._veto` is the best-shaped regulated function in the repo.** `contact_policy.py:477-529` is a pure function of `(purpose, channel, customer, status, now_local, rules, data_purpose, promo_status)` — no connection, no I/O, no clock. It is why the RBI ladder is stated once and why `contact_policy.py:494-499` can hold the DPDP purpose-limitation refusal with a four-line comment explaining why it must be checked *before* the in-session shortcut. The surrounding module takes `conn` as a parameter and **never opens its own transaction** (0 `engine.begin()` sites across 19 conn-taking functions) — which is what lets it lock `contact_day_counters FOR UPDATE` inside the caller's transaction.

**Cursor-as-parameter is used widely and is not a violation.** 74 modules define functions taking `conn`/`connection`/`engine`; 42 of the 103 SQL-writing modules never touch `db.engine` at all. `agent_core/treatment/decisions.py:41-61` (`_writer`/`_reader`, *"use the caller's transaction, or open one"*) is the correct expression of it. That seam is why C2 is a one-line fix rather than a redesign.

**`agent_core/treatment/policy.py` is the counter-example to H2.** `:12-16` explicitly refuses to reimplement contact rules; `:463-484` delegates to `contact_policy` and fails closed. It is the one module in the calling-window inventory that got the direction right.

**The small shared-kernel modules are exemplary.** `env_utils.py` (75 lines, `os` + `math` only, explicit `__all__`, docstring recording the exact import cycle it was extracted to break, and `:70-74` refusing `nan`/`inf` for timeouts), `pg_errors.py` (30 lines, `__all__` at `:10`, isolating the psycopg2-vs-psycopg3 SQLSTATE shape and the 42830 message trap), `agent_core/platform_flags.py` (15 flags, one file, all default-off). All have fan-out 0. Nothing to fix.

**The circuit-breaker placement is the best seam in the backend.** Breaker owned by the adapter, not the call site; `CircuitOpenError` mapped to a 503 exactly once at the edge (`main.py:712-717`); state exposed through `/ready` (`main.py:767`) and a scrape-time Prometheus collector (`observability.py:27`) rather than checked inline. `azure_openai.py:142-150` even acquires the semaphore *outside* the breaker so an internal busy signal is not miscounted as a dependency failure. H6 is a coverage gap in a correct mechanism, not a wrong one.

**Observability is at the edge and stays there.** `observability.py` has 3 importers; `main.py:39` is the only application one. Route labels are template-based, not raw paths (`observability.py:18-20`), so label cardinality is bounded.

**`storage.py` is single-adapter containment, achieved.** The only `minio` import in the tree (`:106`), with a breaker whose `ignore_exceptions=(ValueError,)` and written rationale keep configuration errors from tripping it (`:160-172`).

**The frontend transport boundary is the strongest single thing in the repo.** `api/config.ts` holds **6 of the 7 `fetch` calls in the entire frontend**, and there are **zero** `axios`, `XMLHttpRequest`, `EventSource`, `WebSocket` or `sendBeacon` uses anywhere. One base URL, defined once, **fatal in production if unconfigured** (`config.ts:30-32`). `AbortSignal.any([caller, timeout])` at `:69-75` so a caller's signal cannot silently drop the 30-second timeout. `retryUnlessClientError` at `:157-169` distinguishing a verdict from a fault — it stops retrying 4xx but keeps retrying 408 and 429. Every one of those carries a comment naming the bug it fixed.

**And the two halves agree on paths.** Cross-checking every `/`-prefixed string literal in `Habibi/src` against the 275 distinct backend route paths: **227 matched, and no frontend call targets a route that does not exist.** Of the 48 unmatched backend routes, 22 are inbound or infrastructure endpoints that correctly have no frontend caller (Twilio callbacks, WhatsApp webhooks, payment callbacks, `/health`, `/ready`, `/metrics`, `/ws`, `/a2a`, `/mcp`).

**Provider SDKs are contained in the frontend to a degree most React apps do not manage.** Exactly two third-party-service SDK imports exist, both in one file and both **dynamically** imported: `components/sandbox/voice/useSandboxLiveCall.ts:251-252` (`@pipecat-ai/client-js`, `@pipecat-ai/small-webrtc-transport`). Zero `@daily-co`, `livekit`, `twilio`, `openai`, `@azure/`, `firebase`, `supabase`, `stripe`, or analytics SDKs. Zero `RTCPeerConnection`. And the transport endpoint is **server-provided rather than client-constructed** — `api/voice-sandbox.ts:38` returns `webrtcUrl`, with a comment saying it exists *"rather than hardcoding :7860"*.

**`components/ui` is a sealed design system** — 62 edges out, 48 of them to `lib/utils`, and **zero** to `api/`, `routes/` or feature code. `components → routes` is **0**. One `QueryClient` in the whole tree (`router.tsx:6-17`), threaded through router context.

**`agent_core/cards/__init__.py`** breaks a real cycle with PEP 562 and a 25-line comment naming the exact failing import chain. Correct technique, correctly documented.

**A general observation worth recording.** An unusual number of modules in this repo carry a docstring naming the specific bug or divergence they were written to close — `money_inr.py:10-23`, `env_utils.py:1-13`, `pg_errors.py:22-30`, `rls.py:1-30`, `contact_policy.py:1-19`, `api/config.ts:62-75`, `api/contact-policy.ts:5-10`, `requirements-voice.txt:4-5`. That institutional memory is why this audit could distinguish deliberate decisions from accidents at all, and it is worth more than most of the structure it describes.

**Authorization is total, fail-closed, and provable — and it is the model for everything else missing here.** `main.py:585` puts `dependencies=[Depends(_authz_guard)]` on the `FastAPI(...)` constructor itself, so coverage is by construction rather than by discipline. The guard is at `main.py:504-546`; the registry is two reviewable tables at `authz.py:213` (`PUBLIC_ROUTES`, 26 entries) and `authz.py:254` (`ROUTE_PERMISSIONS`, 292), and `authz.check` (`authz.py:817-841`) **denies unregistered routes**. Statically matching both tables against all 314 scanned routes: **0 uncovered.** The 4 registry entries with no static route are exactly the voice-host routes registered conditionally at `main.py:668-671`.

This is the single best-built thing on the HTTP surface, and the shape generalises: one table, applied by construction, unregistered entries denied, coverage provable by a test. The same shape would fix H11 (a route→response-model table that fails the build when a route has neither) and H10's tenancy problem.

**`agent_core/mcp_http/http_app.py` is a whole HTTP surface done properly in 110 lines** — auth middleware with an explicit exempt set, one dispatch function `handle_rpc(method, params, principal)`, and exception-type→protocol-code translation at the edge (`PermissionError→-32001`, `KeyError→-32601`). Paired with `mcp_tools.py`, which carries a declared `inputSchema` per tool and a redundant `DENIED` deny-list asserted in tests. It is proof the team can build the boundary `main.py` lacks; it exists 40 metres away in the same repo.

---

## 8. Boundary candidates worth the cost

Ordered by payoff per unit of risk. Each names the concrete failure it prevents. None of them is a new layer.

**B1 — Make `conn` required in the four Locked Engines. (Fixes C2.)**
Delete the `db.engine.connect()` fallback at `agent_core/treatment/engine.py:258` and `authority/engine.py:224`; give `reco/engine.py:_recommend` the `conn` parameter it never had. Scope: 4 files, then the 64 modules / 262 `db.engine` references can be narrowed over time. **Prevents:** a decision-log row surviving a rolled-back action — an audit record asserting a treatment happened to a borrower when it did not. **Cheap because the seam already exists** in two of the four engines and `treatment/decisions.py:41-61` already states the contract.

**B2 — Name a row-helper module below `db.py`. (Unblocks C1.)**
`_rows`, `_one`, `_tenant`, `_jsonb`, `_actor_user_id` cover 202 of the 239 production reach-throughs. Give them a public home and an `__all__`. **This is not an abstraction for a diagram — it is the precondition for splitting the 18,088-line file at all.** Today a split breaks 41 modules bound to `db.py`'s privates and 101 bound to its name. Do this before attempting C1, not after.

**B3 — Land ADR-0001: make `agent_core/tools/grant.py` the imported owner. (Fixes C3 and C4 together.)**
Not a new boundary — a designed, tested, accepted one with fan-in 0. 247 lines, pinned by two test files. **Prevents:** the verified channel-filter divergence between the publish gate and both runtimes, the `ALWAYS_ON` / `_FLOW_CONTROL_TOOLS` drift the code already admits to at `voice/tools.py:79`, and the ADR-0002 fail-open where a cardless mouth is *permitted* — not merely offered — all nine skill-gated writes. It also removes a latent handoff bug ADR-0001 names explicitly: the voice runtime filters its registry once at session start, so a mid-call handoff keeps the handing-off agent's tools.

**B4 — Give the outbound gate sequence one owner. (Fixes C7.)**
`mission.build → reserve → admit → suppress → place` is written at seven sites, two of them HTTP handlers. Move the sequence into `outbound.py` beside the functions it already owns, and let the seven callers call one thing. **Prevents:** a compliance-ordering change landing in six files out of seven with nothing failing. This is the highest-value single refactor in the report and it touches under 400 lines.

**B5 — Complete the `work_runtime` port and put a `Protocol` on it. (Fixes H3.)**
Add `list_jobs`, `claim_next`, `finish`, `park_input_required` to `api.py` — the port is 42 lines and the operations already exist in `adapter_pg.py:144-209`. **Prevents:** the split-brain the day `TEMPORAL_ENABLED` flips, where `start_workflow` routes to Temporal while `clerk`'s drain loop raises and two treatment paths keep writing the Postgres queue table nobody drains. Then delete the two raw `INSERT INTO work_runtime_jobs` at `treatment/enact.py:702` and `sweep.py:243`.

**B6 — A route→response-model table, enforced the way `authz` is. (Fixes H11.)**
178 routes have no declared response shape, so `db.py` is where the wire format lives. `authz.ROUTE_PERMISSIONS` already proves the mechanism works and is provable by test at 314/314. **Prevents:** `SELECT *` reaching the browser — `/outbound/number-pools` ships `tenant_id` today, and `Habibi/src/api/outbound.ts:301-307` has already documented that a schema change is an API change.

**B7 — Parse at `apiGet`. (Fixes C6.)**
One function, `Habibi/src/api/config.ts:183`, currently `return JSON.parse(text) as T`. `zod` is already a dependency. **Prevents:** a backend field rename staying green through `tsc`, every test, and the mock demo, and surfacing only as `undefined` in a live collections console. Moving types out of `data/*-seed.ts` is a follow-on tidy, not the fix.

**B8 — Import `contact_policy.BLOCKING_CONSENT` and `policy_rules.calling_window` at the sites that copy them. (Fixes H2, M1.)**
Nine calling-window decision sites, five consent-set copies. Two of the copying modules already import `contact_policy` for other reasons. Delete the literals — starting with `agent_core/compliance/detectors.py:297-298`, which restates `8` and `19` sixteen lines above a comment reading *"one definition of the timezone fallback."*

### What I am deliberately **not** recommending

- **A repository or DAO layer.** The `conn`-as-parameter convention already provides the seam, 42 of 103 SQL-writing modules use it correctly, and `contact_policy` needs `SELECT … FOR UPDATE` in the caller's transaction to enforce the frequency cap at all. A repository interface between them would break the atomicity that makes the cap correct.
- **A service layer between `main.py` and `db.py`.** The problem is not a missing tier; it is that `db.py` is two files wearing one name. `ops_screens.py` already demonstrates what a second such module gets you.
- **Splitting `agent_core` further, or extracting a "domain" package.** Half of it is already pure (51 modules, 12,414 lines), the Locked Engine layering measurably holds, and the façades work. There is nothing to gain.
- **A DTO layer, or moving Pydantic out of `agent_core/cards/schema.py` and `flow_graph.py`.** Pydantic is in the base image of every process, so it imposes no boundary cost; the boundary that *is* real is pipecat, and the code already respects it (`agent_core/tools/schema.py:158-164`).
- **Reporting `rls.py`'s zero importers as dead code.** It is operator tooling, correctly absent from every runtime path. The finding is that it is inert (H5), not that it is unused.
- **Reporting the 897 lazy imports as a hygiene problem.** Most of them are the deployment boundary described in §2.3. They are a symptom of C1, and they will resolve when `db.py` is split — not before, and not by being rewritten as eager.

---

## 9. Analyst disagreements, resolved

**`db.py` importer count: 200 vs 101.** Both correct, different populations. 200 counts tests and scripts; **101** is production modules only, and both analysts plus my own graph agree on that number exactly. The report uses 101.

**Runtime SCC size: 76 vs 88 vs "~110".** The dependency-direction analyst and I independently measured **76** on explicit import edges — same number, different scripts. They measured **88** when parent-package `__init__` edges are added (`import a.b.c` really does execute `a/__init__.py`, which neither prior report stated). `05-dependency-graph.md` reports ~108–111; neither of us could reproduce it under either convention, and we do not know theirs. The report uses 76 and names the convention.

**Production module count: 265 vs 267 vs "269".** My 267 includes `voice/ws_proxy.py` and `voice/workers/insurance.py`, which the other analyst's walk excluded. Immaterial to every conclusion; both are stated.

**`db._tenant()` as evidence of tenant drift — downgraded.** The infrastructure analyst read `db.py:96-107`'s docstring about "four different spellings" and reported the coexistence of `db.current_tenant()` (93 sites) and `db._tenant()` (80 sites) as live drift. I checked `db.py:113`: `_tenant = current_tenant` — a direct assignment. The two names cannot disagree. The drift the docstring describes is the *historical* state that this alias closed. What remains is that 19 external modules bind to a name the adjacent comment calls "module-internal", which is H1's encapsulation problem, not a correctness one. Filed at that weight.

**`enact` imported directly as a gate bypass — not filed.** Four external modules import `authority.enact` or `live_qa.enact` past a façade that deliberately withholds them. Before reporting it I read `agent_core/authority/enact.py:35-37`: `apply_goodwill` raises `AuthorityError("shadow_mode")` unless the engine is live, and requires a `decision_id`. The gate is enforced by data, not by import path. Recorded here rather than as a finding.

**`create_engine` location: `db.py:15` vs `db.py:138`.** Both right — `:15` is the import, `:138` the construction. No disagreement, just two readings of one fact.

**Route count: 314 vs 312.** 314 decorators over 312 handler functions; two handlers carry two decorators. The API analyst also recovered up to 4 more routes registered at runtime by `voice.host.register_routes` (`main.py:668-671`) that no static scan can see — so 314 is a floor, and they found it from authz-registry orphans rather than from a running app.

---

## 10. Corrections made during this audit

**My first "domain never imports `db`" result was an artifact and is the opposite of the truth.** Three agents wrote `graph.json` into a shared scratchpad directory and overwrote one another; I read a frontend graph while querying for backend modules and got a clean zero. The real figure is **101 production modules, 211 import sites** (§C1). Everything downstream was re-derived under a private path. This is worth recording as a method failure, not just a slip: a plausible zero is the most dangerous result an audit can produce.

**My first frontend/backend route diff reported 16 frontend calls to nonexistent backend routes. All 16 were false.** My normalizer turned a `${qs}` query-string suffix into a path segment, so `/leads${qs}` became `/leads{}` and failed to match `/leads`. Corrected: **zero** frontend calls target a route that does not exist.

**My frontend path scanner was line-based and missed every multi-line call**, including `/customers/{}/contact-policy`, which I had read with my own eyes minutes earlier. Rewritten to scan whole file text. Final coverage: 227 of 275 backend paths matched. The residual 48 is 22 correctly-inbound endpoints plus 26 my method cannot resolve — I verified at least one of those 26 (`/interactions/{}/export`) *is* called, via a `${API_BASE_URL}`-prefixed template my leading-slash regex cannot see. **So the 26 are inconclusive, not dead routes**; dead code is report 07's subject, not this one.

**I ranked seven Locked Engine import edges as pipeline inversions before checking them.** All seven were my ranking's fault — `models.py` in `reco` and `treatment` is the ML-model loader, not a low-level type module, so its imports of `Candidate` and `SCHEMA_VERSION` run *with* the pipeline, not against it. Zero real inversions.

---

## 11. What could not be verified

- **Nothing was executed.** Read-only: no build, no server, no migration, no test run, no database access. Every number is static.
- **Whether `scripts/rls.py` has ever been run against this database.** This decides whether H5 is a latent risk or the live state. It needs a `psql` session, which the constraint forbids.
- **Whether the 897 lazy edges are hot.** A lazy import in a never-called function is a latent dependency, not an active one. The 76-module SCC is an upper bound on what *can* be reached, not a profile of what is.
- **Whether the C3 grant divergence currently fires.** It requires a published card naming a text-only tool. That is a `prompt_versions` query, and no analyst read the database.
- **Coupling through the database itself.** H4 measures it by writer, which is a floor: two modules writing the same table share no import edge, and the table-level coupling graph is almost certainly denser than the import graph. A full read/write matrix across 138 tables was out of scope.
- **Whether the 33 `dict[str, Any]` bodies are re-validated downstream.** Verified that the handler does not; for `agent_core.*` callees (`create_draft_skill`, `upsert_connector`, `mint_key`) not every callee was read.
- **Whether the frontend's 560 type aliases match the 247 Pydantic models.** This is exactly the check nothing in the repo performs, and it needs its own pass. The one case the repo has already confessed is `outbound.ts:301-307` (H11).
- **`db.py` and `main.py` were sampled, not read end to end** — 18,088 and 5,449 lines. A duplicated calling-window or consent rule inside an unsampled region of `db.py` would not appear here; `db.py:6187` mentions the RBI window in a comment that no analyst opened the surrounding function for.
- **Dynamic imports.** One analyst scanned string constants matching first-party module names and found 22, all already in the graph (`agent_core/cards/__init__.py:53-55`, `voice/bot.py:2529-2550`). Fan-in counts are lower bounds regardless.
