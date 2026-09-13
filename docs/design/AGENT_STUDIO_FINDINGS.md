# Agent Studio — the complete findings

**Generated** from `audit-reports/agent-studio-nextgen/` by `render_findings.py`. Do not edit by hand; edit `backlog.json` and regenerate.

The argument, the architecture and the work plan are in [AGENT_STUDIO_NEXT_GEN.md](./AGENT_STUDIO_NEXT_GEN.md). This is its reference half: every finding in full, then the cross-cutting inventories, then the gaps in the audit itself.

**345 findings — 81 MAJOR, 206 MINOR, 58 trivial — across 24 slices.** Every one was adversarially verified by a second agent instructed to refute it; the two that were refuted are excluded. Severity: MAJOR = wrong runtime behaviour, wrong publish verdict, silent data loss, a lie to the operator, or a regulated-path defect; MINOR = incorrect but contained; trivial = cosmetic.

Line numbers were accurate when read against commit `026cada`, in a tree that was moving (see the working-tree caveat in the companion). **Re-anchor every citation before acting on it.**

**Closure is recorded per finding in `raw/closures.json`** — 121 closed (every MAJOR, by the re-verification of 2026-09-09 and its same-day commits; the pass-7 residue by commit), 4 deferred with the reason named. A MINOR or trivial finding with no closure line was worked under a MASTER-BACKLOG work package (passes 3–6) and has not been re-verified by id, so it is not claimed closed here.

## Contents

- [Ship tab — canary, shadow, auto-rollback, deployments](#ship-tab--canary-shadow-auto-rollback-deployments) — 15 findings, 5 MAJOR
- [Evals tab — suites, reports, and the publish gates](#evals-tab--suites-reports-and-the-publish-gates) — 20 findings, 3 MAJOR
- [Skills — card tab, library, detail, packs, signing](#skills--card-tab-library-detail-packs-signing) — 19 findings, 9 MAJOR
- [Connectors — tab, registry, ext.* dispatch](#connectors--tab-registry-ext-dispatch) — 17 findings, 5 MAJOR
- [Change log — the hash chain and what it covers](#change-log--the-hash-chain-and-what-it-covers) — 12 findings, 4 MAJOR
- [Guardrails tab — six toggles, two sliders, banned words](#guardrails-tab--six-toggles-two-sliders-banned-words) — 11 findings, 4 MAJOR
- [Outbound tab — direction, missions, cadences, post-call, pools](#outbound-tab--direction-missions-cadences-post-call-pools) — 21 findings, 5 MAJOR
- [Flow tab — canvas, inspector, validator, the two runtimes](#flow-tab--canvas-inspector-validator-the-two-runtimes) — 17 findings, 5 MAJOR
- [Tools tab — grant vs offer, locked engines, voice cap](#tools-tab--grant-vs-offer-locked-engines-voice-cap) — 10 findings, 1 MAJOR
- [Tool catalog — 26 specs across voice, text, MCP and flow](#tool-catalog--26-specs-across-voice-text-mcp-and-flow) — 15 findings, 1 MAJOR
- [Agent graph tab — handoffs and the handoff runtime](#agent-graph-tab--handoffs-and-the-handoff-runtime) — 11 findings, 3 MAJOR
- [Sandbox — parity between what you test and what you ship](#sandbox--parity-between-what-you-test-and-what-you-ship) — 16 findings, 5 MAJOR
- [Fleet index — roster, clone, archive, reachability](#fleet-index--roster-clone-archive-reachability) — 12 findings, 4 MAJOR
- [System Prompt tab — lint, token estimate, the render path](#system-prompt-tab--lint-token-estimate-the-render-path) — 13 findings, 4 MAJOR
- [Persona tab — traits, presets, language](#persona-tab--traits-presets-language) — 11 findings, 1 MAJOR
- [Voice (TTS) tab — catalog, params, preview, runtime binding](#voice-tts-tab--catalog-params-preview-runtime-binding) — 11 findings, 2 MAJOR
- [Bindings tab — provider models per slot](#bindings-tab--provider-models-per-slot) — 12 findings, 2 MAJOR
- [Policy tab — the six locked engines](#policy-tab--the-six-locked-engines) — 8 findings, 0 MAJOR
- [Card editor shell — hydration, autosave, drafts, publish](#card-editor-shell--hydration-autosave-drafts-publish) — 17 findings, 1 MAJOR
- [Header and version history](#header-and-version-history) — 11 findings, 0 MAJOR
- [Agent Card → runtime — the field-by-field inventory](#agent-card-→-runtime--the-field-by-field-inventory) — 23 findings, 10 MAJOR
- [Type mirror — TypeScript vs Pydantic](#type-mirror--typescript-vs-pydantic) — 13 findings, 0 MAJOR
- [Authorization, tenancy and audit on every studio write](#authorization-tenancy-and-audit-on-every-studio-write) — 17 findings, 6 MAJOR
- [Code organization, duplication, dead code, test gaps](#code-organization-duplication-dead-code-test-gaps) — 13 findings, 1 MAJOR
- [Cross-cutting inventories](#cross-cutting-inventories)
- [Gaps in this audit](#gaps-in-this-audit-33)

---

## Ship tab — canary, shadow, auto-rollback, deployments

15 findings — 5 MAJOR, 8 MINOR, 2 trivial; 5 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-ship.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `SHIP-01` — `shadow` is stored in three tables and read by no router — a "shadow" canary sends real customer calls to the candidate

**MAJOR** · dead-config · prior: 2m.2 · **closed** in `fcbfefd` (pass 3)

**Files** — `Habibi/src/components/prompt-studio/ShipTab.tsx:169`, `Habibi/src/components/prompt-studio/ShipTab.tsx:209`, `backend/agent_core/canary.py:57`, `backend/agent_core/canary.py:129`, `backend/db_prompt_studio.py:2122`, `backend/agent_core/deployment.py:38`

**Mechanism** — The checkbox is labelled "Shadow (log split, do not change customer treatment)" (ShipTab.tsx:175). The flag reaches deployment_experiments.shadow (canary.py:129) and bot_deployments.shadow (db_prompt_studio.py:2122) and the change-log entry (change_log.py:208). The only traffic router, pick_deployment_id (canary.py:57-77), never reads exp['shadow']; nor does load_active_bundle (deployment.py:34-52). A grep of every `shadow` occurrence under backend/ shows no other reader — the other hits are the unrelated treatment/reco/authority shadow modes. Nothing executes a second, non-speaking pipeline anywhere in backend/voice/**, bot_runtime.py, outbound.py or mission.py. So shadow=true at 40% is an ordinary 40% live canary. The in-code warning at ShipTab.tsx:209-214 makes it worse: by warning only at pct>=100 it asserts that shadow *does* suppress treatment below 100%.

**Trigger** — Publish any card with experiment.shadow=true and traffic_pct<100; borrowers in the canary bucket are handled by the candidate mouth for real while the console says treatment is unchanged.

**Fix** — Either implement it (pick_deployment_id returns the baseline when shadow is set, and the canary bundle is executed only into logs) or make it un-authorable: remove the checkbox and the column, and have G12 fail `shadow=true` until a shadow executor exists. Do not leave a control that claims customers are unaffected.

#### `SHIP-02` — Voice and outbound ignore the canary percentage entirely — 100% of calls hit the candidate

**MAJOR** · bug · **closed** in `fcbfefd` (pass 3)

**Files** — `backend/agent_core/canary.py:71`, `backend/voice/bot.py:427`, `backend/mission.py:516`, `backend/agent_core/deployment.py:38`, `backend/bot_runtime.py:712`, `Habibi/src/components/prompt-studio/ShipTab.tsx:96`

**Mechanism** — pick_deployment_id splits on a hash of customer_id, but short-circuits: `if pct >= 100 or not customer_id: return canary_id` (canary.py:71-72). voice/bot.py:427 calls `load_active_bundle("production", fallback_environments=("sandbox",))` with neither bot_id nor customer_id, so every voice call resolves to the canary deployment regardless of traffic_pct. The outbound mission envelope resolves its card through db.get_active_deployment (mission.py:514-520), which is the canary row too (publish marks the canary 'active' and the previous deployment 'retired', db_prompt_studio.py:2079-2092). Only the WhatsApp turn loop passes customer_id (bot_runtime.py:712-716) and therefore actually splits. The Ship tab's headline says "Canary is a real traffic split" (ShipTab.tsx:97).

**Trigger** — Publish at 25% and place or receive a voice call: the candidate prompt/persona/flow answers, and every outbound mission is built from the candidate card.

**Fix** — Pass the call's customer_id (and bot_id) into load_active_bundle from voice/bot.py, and resolve the outbound mission card through pick_deployment_id rather than get_active_deployment. Where no customer id exists (a cold inbound with no match), fall back to the *baseline*, not the canary — an unattributable call is not a canary volunteer.

#### `SHIP-03` — The `slo_miss` trigger compares call length against a latency budget — enabling it rolls back every canary on the next sweep

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/canary.py:292`, `backend/agent_core/canary.py:27`, `backend/agent_core/canary.py:385`, `backend/sql/04_interactions.sql:28`, `backend/sql/04_interactions.sql:22`, `Habibi/src/components/prompt-studio/ShipTab.tsx:15`

**Mechanism** — _slo_miss computes `percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_sec * 1000.0)` over interactions and compares it to VOICE_SLO_MS=800 (canary.py:296-307). `interactions.duration_sec` is total handle time in seconds (04_interactions.sql:28; used as AHT at db_dashboard.py:360, followups_db.py:1381). Multiplying seconds by 1000 yields the call length in milliseconds, so any voice call longer than 0.8 s puts p95 above 800 and `reason='slo_miss'` fires. The UI sells this as "Voice SLO miss (p95 > 800ms)" (ShipTab.tsx:15), i.e. turn latency — for which the real columns exist and are unused: interactions.latency_ms (04_interactions.sql:22) and interaction_transcript.ttfb_ms/llm_ttfb_ms/tts_ttfb_ms (04_interactions.sql:90-98).

**Trigger** — Tick "Voice SLO miss", publish a canary, let one voice call of normal length complete; the next sweep (bot_worker.py:145-156) rolls the canary back and the change log records a latency regression that did not happen.

**Fix** — Measure latency, not duration: p95 over interaction_transcript.ttfb_ms (or interactions.latency_ms) for turns belonging to the canary deployment, and keep the 800 ms constant. Add a regression test that a 90-second call with 300 ms TTFB does not trip slo_miss.

#### `SHIP-05` — Manual deployment rollback does not stop a running canary — traffic keeps going to the rolled-back candidate, and no gate is re-run

**MAJOR** · bug · **closed** in `4e06f87` (pass 3)

**Files** — `backend/db_prompt_studio.py:2292`, `backend/db_prompt_studio.py:2364`, `backend/agent_core/canary.py:35`, `backend/agent_core/canary.py:68`, `backend/db_prompt_studio.py:1494`, `Habibi/src/api/prompt-studio.ts:824`

**Mechanism** — rollback_bot_deployment (db_prompt_studio.py:2292-2427) archives/publishes prompt versions, marks the current active row 'rolled_back' and inserts a new active row — and never touches deployment_experiments. A canary published at 40% leaves a `running` experiment whose canary_deployment_id is that now-rolled-back row. pick_deployment_id consults the running experiment FIRST (canary.py:66-77) and resolves it with db.get_deployment, which loads by id with no status filter (db_prompt_studio.py:1494-1499, 1581-1600). So after the rollback the split still routes the canary bucket (and, per SHIP-02, all voice traffic) to the deployment the operator just rolled back, while GET /bot-deployments/active reports the restored one. Separately, the rollback path calls no compile_card/assert_publishable — it re-publishes a prompt version with every gate bypassed — and the front end does not even refresh the experiment list, because useRollbackBotDeployment invalidates ['bot-deployments'] (prompt-studio.ts:124-136) and the experiments query is keyed ['deployments','experiments',botId] (agent-studio.ts:851).

**Trigger** — Publish a 40% canary, then press rollback (header path, or the Ship button once SHIP-04 is fixed): the console says the previous config is live; the router disagrees.

**Fix** — In rollback_bot_deployment, close any running experiment for (bot, env) in the same transaction — reuse canary.rollback_experiment(reason='deployment_rollback') or an equivalent UPDATE — before inserting the new active row; make pick_deployment_id ignore experiments whose canary deployment is no longer 'active'; and have the rollback mutation invalidate ['deployments'] as well. If a rollback should be gated, run compile_card on the restored version and record the report; if it deliberately is not, say so in the docstring.

#### `SHIP-06` — Every auto-rollback trigger measures the whole bot, not the canary cohort — the baseline's failures roll back the candidate and vice versa

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/canary.py:206`, `backend/agent_core/canary.py:236`, `backend/agent_core/canary.py:263`, `backend/agent_core/canary.py:281`, `backend/agent_core/canary.py:298`, `backend/agent_core/canary.py:381`, `backend/sql/04_interactions.sql:26`, `backend/voice/persist.py:143`, `backend/outbound.py:373`

**Mechanism** — All five SQL evaluators filter on bot only — `i.handler_bot_id = :b` (canary.py:206, 264, 299) or `a.bot_id = :b` / `bot_id = :b` (canary.py:237, 283) — and the eval_fail branch reads the bot's latest red-team report (canary.py:381-384), which is not a canary measurement at all. During a 25% canary both cohorts run under the same bot_id, so 75% of the evidence comes from the baseline: one abandoned call or one third-party leak produced by the *unchanged* deployment pulls the canary, and a canary that leaks on 25% of traffic is judged on a pool three-quarters of which is not it. The attribution data exists and is written: interactions.deployment_id (sql/04_interactions.sql:26, populated by voice/persist.py:149-154) and call_attempts.deployment_id (outbound.py:375-395).

**Trigger** — Any running experiment where either cohort misbehaves; the rollback_reason recorded names a trigger the canary may not have caused.

**Fix** — Join each evaluator to the canary deployment: `AND i.deployment_id = :canary` / `AND a.deployment_id = :canary`, passing canary_deployment_id from the sweep row (canary.py:357-368). For eval_fail, compare the red-team report bound to the canary's prompt version rather than the bot's latest.

#### `SHIP-04` — "One-click rollback of active deployment" always fails — it posts the active deployment's own id to an endpoint that rejects it

MINOR · bug · DOWNGRADED

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:1419`, `Habibi/src/components/prompt-studio/ShipTab.tsx:259`, `Habibi/src/components/prompt-studio/ShipTab.tsx:266`, `backend/db_prompt_studio.py:2330`, `backend/main.py:3370`, `backend/main.py:828`, `backend/tests/test_agent_studio_edge_cases.py:318`

**Mechanism** — The shell passes `activeDeploymentId={activeDeployment?.id}` (lazy.tsx:1419) and the button calls `rollbackDep.mutateAsync(activeDeploymentId)` (ShipTab.tsx:266). POST /bot-deployments/{id}/rollback means "re-activate THIS deployment", and db_prompt_studio.rollback_bot_deployment raises ValueError('deployment_already_active') when the target is already active (2325-2331), which _handle_write maps to 409 (main.py:825-830; the mapping is even unit-tested at test_agent_studio_edge_cases.py:320). The working call site passes the prior deployment: `activeDeployment?.rollbackDeploymentId ?? priorDeployment?.id` (lazy.tsx:993). So the Ship tab's rollback is a button that can only ever produce `toast.error("deployment_already_active")`.

**Trigger** — Open Ship on any bot with an active production deployment and press the button.

**Fix** — Pass the rollback target, not the active id: give ShipTab the same `activeDeployment.rollbackDeploymentId ?? priorDeployment.id` the header rollback uses, hide the button when that is null (the header path already toasts "No prior production deployment"), and label it with the version it will restore.

#### `SHIP-07` — Card-less bots' Ship tab still shows a fabricated "100% / no shadow / no triggers" — the baseline filters on an experiment status that cannot exist

MINOR · stale · prior: 2m.4

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:460`, `Habibi/src/routes/prompt-studio.lazy.tsx:468`, `Habibi/src/routes/prompt-studio.lazy.tsx:1155`, `backend/sql/18_phase5.sql:13`, `backend/agent_core/canary.py:117`, `Habibi/src/components/prompt-studio/ShipTab.tsx:79`

**Mechanism** — legacyShipBaseline picks `(experimentsQuery.data ?? []).find(e => e.status === 'active')` (lazy.tsx:460). deployment_experiments.status is CHECKed to ('running','rolled_back','promoted') (sql/18_phase5.sql:13) and only ever written as those three (canary.py:100, 117, 179). The predicate never matches, so the function always returns the hardcoded {trafficPct:100, shadow:false, autoRollback:[]} it was written to replace — the exact behaviour the comment at lazy.tsx:249-255 says was fixed. Ten lines away, ShipTab correctly matches `status === 'running'` (ShipTab.tsx:79). Knock-on: publishBaseline.rollout (lazy.tsx:1155) diffs against that fiction, so PublishDialog's Rollout row is computed from a rollout production is not running.

**Trigger** — Open Ship on a bot with no authored card while a 25% experiment is running: the slider reads 100%, the trigger boxes are clear, and publishing ships 100%.

**Fix** — Match `e.status === 'running'` (and scope to environment 'production'), or better, derive both the tab default and the diff baseline from the same helper ShipTab uses.

#### `SHIP-08` — Hash split is modulo-biased: a 50% canary takes ~59% of customers, a 10% canary ~12%

MINOR · bug

**Files** — `backend/agent_core/canary.py:73`

**Mechanism** — `bucket = digest[0] % 100` maps one byte (0-255) onto 100 buckets, so buckets 0-55 receive three source values and 56-99 receive two. Since the canary takes `bucket < pct`, every pct <= 56 is inflated by up to 17% relative: pct=50 → 150/256 = 58.6%; pct=10 → 30/256 = 11.7%; pct=25 → 75/256 = 29.3%. The number in the audit trail and in the console is not the fraction of borrowers exposed.

**Trigger** — Any experiment with 0 < pct <= 56.

**Fix** — Use enough entropy for a uniform mapping, e.g. `int.from_bytes(digest[:8], 'big') % 100`, and assert the distribution in test_phase5.

#### `SHIP-09` — A failed experiments fetch renders as "no canary running" and takes the canary rollback button with it

MINOR · degradation-lie · prior: 2.2

**Files** — `Habibi/src/components/prompt-studio/ShipTab.tsx:76`, `Habibi/src/components/prompt-studio/ShipTab.tsx:79`, `Habibi/src/components/prompt-studio/ShipTab.tsx:216`, `Habibi/src/api/agent-studio.ts:849`

**Mechanism** — `const running = (experiments.data ?? []).find(e => e.status === 'running')` (ShipTab.tsx:79) collapses isLoading and isError into the same empty array, and the whole "Running experiment" block including "Roll back canary" is rendered only `{running ? ... : null}` (ShipTab.tsx:216-258). The query exposes isError (agent-studio.ts:849-859) and the section shows nothing about the failure. This is the same class the prior audit logged as 2.2 for the deployment fetchers, on the one screen where an operator goes to stop a bad canary.

**Trigger** — API outage or 5xx on GET /bot-deployments/experiments while a canary is live.

**Fix** — Render three states: pending (skeleton), error ("Could not read the running experiment" plus a retry, never an implied all-clear), empty ("no canary running").

#### `SHIP-10` — The traffic slider looks like a live dial but only edits a draft — a running experiment's percentage cannot be changed at all

MINOR · disconnected

**Files** — `Habibi/src/components/prompt-studio/ShipTab.tsx:158`, `Habibi/src/components/prompt-studio/ShipTab.tsx:96`, `Habibi/src/routes/prompt-studio.lazy.tsx:475`, `backend/main.py:3203`, `backend/main.py:3210`, `backend/agent_core/canary.py:96`

**Mechanism** — onChange writes card.experiment (lazy.tsx:478-492) or local state; nothing reaches the server until Publish. There is no PATCH for deployment_experiments — the only writers are record_experiment on publish (canary.py:96-133) and rollback_experiment. Yet the section opens with "Canary is a real traffic split" (ShipTab.tsx:97) and the running-experiment card immediately below shows a different, live percentage (ShipTab.tsx:222) with no label distinguishing "authored, ships next publish" from "live now".

**Trigger** — An operator dragging the slider from 25% to 5% to calm a suspicious canary changes nothing about the live split.

**Fix** — Label the slider "Next publish" and the panel "Live now", and either add a ramp endpoint that updates the running experiment's traffic_pct or say plainly that the only live controls are promote (publish at 100%) and roll back.

#### `SHIP-11` — Canary rollback does not invalidate the deployment queries it changes (and deployment rollback does not invalidate the experiment query)

MINOR · bug

**Files** — `Habibi/src/api/agent-studio.ts:877`, `Habibi/src/api/prompt-studio.ts:124`, `Habibi/src/api/prompt-studio.ts:907`, `Habibi/src/api/agent-studio.ts:851`

**Mechanism** — useRollbackExperiment invalidates ['deployments'] and the agent-studio keys (agent-studio.ts:877-881), but the deployment queries are keyed ['bot-deployments', ...] (prompt-studio.ts:123, 907, 915) — a different root — so after a canary rollback has flipped the active row back to the baseline (canary.py:166-174) the header's active deployment, the prior-deployment computation (lazy.tsx:337-352) and ShipTab's activeDeploymentId all keep 15s-stale pre-rollback values. The mirror image also holds: useRollbackBotDeployment → invalidatePromptStudio (prompt-studio.ts:124-136) never invalidates ['deployments'], so the running-experiment panel survives a deployment rollback unchanged.

**Trigger** — Press "Roll back canary"; the active-deployment chip and the rollback target continue to name the retired canary until a refetch.

**Fix** — Invalidate both roots from both mutations, or unify on one key namespace for deployments and experiments.

#### `SHIP-12` — PublishDialog reports "Rollout: unchanged" for every authored card, including a publish that moves traffic from 100% to 40%

MINOR · bug · prior: 2a.3

**Files** — `Habibi/src/components/prompt-studio/PublishDialog.tsx:91`, `Habibi/src/components/prompt-studio/PublishDialog.tsx:217`, `Habibi/src/routes/prompt-studio.lazy.tsx:1155`, `Habibi/src/routes/prompt-studio.lazy.tsx:1599`

**Mechanism** — Both sides pass `rollout: cardIsAuthored ? null : ...` (lazy.tsx:1155 and 1599), so for an authored card rolloutChanged is stableStringify(null) !== stableStringify(null) = false (PublishDialog.tsx:91-92) and the dialog prints "Rollout: unchanged" (217-225) on the publish that introduces the canary. The change is folded into "Agent card: changed", but the line explicitly named Rollout states the opposite, and all four first-party bots are authored, so this is the default path.

**Trigger** — Set 40% + triggers on an authored card and open Publish.

**Fix** — Derive `rollout` from card.experiment for authored cards instead of nulling it, so the row states the real before/after — and show the numbers ("100% → 40%, rollback on abandon_rate") rather than a changed/unchanged word.

#### `SHIP-13` — The auto-rollback sweep runs for one tenant only, and rides inside the clerk import's try-block

MINOR · bug

**Files** — `backend/agent_core/canary.py:357`, `backend/agent_core/canary.py:363`, `backend/bot_worker.py:145`, `backend/tenant_context.py:75`

**Mechanism** — sweep_rollbacks selects `WHERE status='running' AND tenant_id = :t` with db.current_tenant() (canary.py:363-367), which outside a request context is the process default (tenant_context.py:75-77 → db.TENANT_ID). A worker process therefore never evaluates triggers for any other tenant's canaries — they stay running forever with no watchdog. The call site compounds it: the sweep is nested inside `try: from agent_core.clerk import ...` (bot_worker.py:145-160), so a failure importing an unrelated module skips the canary stage and logs it as "queue=clerk failed".

**Trigger** — A second tenant publishes a canary; or agent_core.clerk fails to import in the worker image.

**Fix** — Iterate distinct tenant_ids from the running experiments (or drop the tenant predicate for this sweep and bind per row), and lift the canary stage out of the clerk try-block with its own logger name.

#### `SHIP-14` — trafficPct on the publish request is unbounded: >100 compiles as "full ship" and then dies as a constraint violation

trivial · shape-mismatch

**Files** — `backend/schemas.py:2409`, `backend/agent_core/cards/compile.py:878`, `backend/db_prompt_studio.py:2119`, `backend/sql/09_bot_config.sql:256`, `backend/agent_core/cards/schema.py:358`

**Mechanism** — PromptVersionPublishRequest.trafficPct is `int | None` with no bounds (schemas.py:2409) while the card model constrains it to 0..100 (schema.py:358). compile.py:878 clamps the value before G12, so trafficPct=500 reports "G12 canary pass — full ship", after which the unclamped pct is inserted into bot_deployments.traffic_pct (db_prompt_studio.py:2119) and violates `CHECK (traffic_pct BETWEEN 0 AND 100)` (09_bot_config.sql:256) → 409 constraint_violation.

**Trigger** — Any API client (not the slider) publishing with trafficPct>100.

**Fix** — `trafficPct: int | None = Field(default=None, ge=0, le=100)`, so the rejection is a 422 naming the field rather than a gate that passed followed by a database error.

#### `SHIP-15` — Two unrelated things are called a canary; the Ship tab shows neither the model canary nor considers it on rollback

trivial · disconnected

**Files** — `backend/llm_gateway/canary.py:73`, `backend/main.py:2900`, `Habibi/src/api/integrations.ts:452`, `Habibi/src/components/prompt-studio/ShipTab.tsx:94`

**Mechanism** — llm_gateway.canary.model_for (canary.py:73-89) silently overrides the live model per profile for the whole tenant, driven from the Integrations screen (integrations.ts:452-472). The Ship tab, the screen that claims to own what is shipping, never reads it, and canary.sweep_rollbacks has no branch that pulls a model canary when a mouth canary's triggers fire (agent_core/canary.py:370-421) — the two rollout axes are unaware of each other, so a bad turn during a mouth canary may be the model's.

**Trigger** — A gateway model canary running at the same time as a deployment canary.

**Fix** — Surface the active gateway canary (candidate model + stage) as a read-only row on Ship, and record it in the deployment experiment so a rollback reason can be attributed to the right axis.

---

## Evals tab — suites, reports, and the publish gates

20 findings — 3 MAJOR, 15 MINOR, 2 trivial; 5 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-evals.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `EVALS-1` — G7/G8/G-OB9 certify a publish with the newest report for the BOT, from any prompt version — prompt_version_id is written by nobody

**MAJOR** · bug · **closed** in `acaaa58` (pass 3)

**Files** — `backend/db_prompt_studio.py:1914`, `backend/db_inbox.py:1592`, `backend/db_inbox.py:1610`, `backend/agent_core/eval/run.py:92`, `backend/agent_core/cards/compile.py:965`, `backend/sql/14_agent_factory.sql:46`, `backend/llm_gateway/canary.py:180`

**Mechanism** — eval_reports carries prompt_version_id (sql/14_agent_factory.sql:46) and save_eval_report accepts it (db_inbox.py:1610), but no production caller ever supplies it: run_named_suite passes only suite_id/bot_id/status/summary/trials/origin (run.py:92-99), and the only other call sites are tests. The column is therefore NULL on every real row. get_latest_eval_report (db_inbox.py:1582-1601) selects `WHERE r.bot_id = :bot AND s.kind = :kind ORDER BY r.created_at DESC LIMIT 1` — it does not know what version is being published, and publish (db_prompt_studio.py:1914-1917) hands exactly that to compile_card, where _eval_gate returns pass on `status == "pass"` (compile.py:970-971). Nothing compares the report's age to the draft's. Compounding it: the nightly worker (worker.py:335-357) runs run_continuous, whose reports are attributed to kaia-v2-4 by name-matching (run.py:26-33), and the LLM-gateway model canary (llm_gateway/canary.py:172-181) files three more under the same bot — so kaia's G7/G8 are green permanently without any human having evaluated any version.

**Trigger** — Run "Collections regression" from kaia-v2-4's Evals tab (green report EVR-x). Rewrite the prompt, delete verify_identity from the flow, add tools, publish. With EVAL_GATE_ENABLED=true and regression in card.eval.require, G7 reports pass and cites EVR-x — a report produced by fixture graders before the change existed. No newer run is required and no staleness is signalled.

**Fix** — Have run_named_suite record the draft prompt_version_id it was launched against (the Evals tab already knows it) and make get_latest_eval_report take a prompt_version_id, failing the gate — not passing it — when the newest report for that bot predates the version being published. Minimum viable: fail G7/G8 when report.created_at < prompt_versions.updated_at for the draft.

#### `EVALS-2` — The Twin requirement and the G11 twin gate read different tables — running the twin suite from the tab can never satisfy the gate

**MAJOR** · disconnected · **closed** in `9972995` (pass 3)

**Files** — `backend/agent_core/cards/compile.py:721`, `backend/agent_core/cards/compile.py:722`, `backend/db_prompt_studio.py:1916`, `backend/db_inbox.py:1572`, `backend/agent_core/twin.py:150`, `backend/agent_core/twin.py:160`, `backend/agent_core/twin.py:123`, `backend/main.py:1007`, `backend/agent_core/eval/corpus.py:141`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:256`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:392`

**Mechanism** — Ticking Twin sets card.eval.require=[...,"twin"], which makes twin_required true and G11 blocking (compile.py:721-722). But compile_card's twin_report comes from _latest_twin_gate_report (db_prompt_studio.py:1916 → db_inbox.py:1570-1577 → agent_core/twin.py:150-175), which selects the newest row of the twin_runs table for the tenant — a table the eval path never writes. The Evals tab meanwhile displays the twin requirement's status from latestByKind, i.e. the newest eval_reports row whose suite kind is 'twin' (AgentCardPanels.tsx:301-304, 393-404), which is exactly what the "Collections twin outcomes" suite (corpus.py:143-152) produces. The two are unrelated: latest_gate_report is not filtered by bot_id or prompt version either, so whichever card last ran a twin simulation decides G11 for every card in the tenant.

**Trigger** — Tick Twin on any card, click Run on "Collections twin outcomes" → the tab shows twin · pass. Publish: if twin_runs is empty, G11 fails with "twin suite has not been run" against a green badge on the same screen. Conversely, one old passing twin_runs row makes G11 green for a card that has never run a twin suite.

**Fix** — Pick one source. Either G11 takes get_latest_eval_report(bot_id=..., kind="twin") like G7/G8 do, or the tab stops rendering eval_reports twin rows as the evidence for the twin requirement and shows the twin_runs verdict instead.

#### `EVALS-3` — "Capability" is offered as a publish requirement and gates nothing

**MAJOR** · dead-config · **closed** in `9972995` (pass 3)

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:255`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:314`, `backend/agent_core/cards/schema.py:21`, `backend/agent_core/cards/compile.py:716`, `backend/agent_core/cards/compile.py:718`, `backend/agent_core/cards/compile.py:722`, `backend/agent_core/cards/compile.py:464`, `backend/agent_core/cards/compile.py:966`

**Mechanism** — EvalRequire admits "capability" (schema.py:21) and the tab renders a checkbox for it with the hint "the things this card claims it can do" (AgentCardPanels.tsx:255), under a paragraph that states "When the eval/red-team flags are on, a failed suite blocks publish" (AgentCardPanels.tsx:313-316). compile_card only ever calls _eval_gate with names "regression" (G7:716), "redteam" (G8:718), "twin" (G11:722) and "outbound" (G-OB9:464). card.eval.require is read in exactly two places (compile.py:721 and :966) and neither can produce a capability gate. A capability suite going red therefore never blocks anything, while the tab lists it beside regression and redteam as a shipping requirement and shows its red badge.

**Trigger** — Tick Capability, run "Collections capability" and let it fail. The tab shows capability · fail in red. Publish succeeds: the compile report contains no capability gate at all, and the operator has no way to notice the omission because the gate list never mentions the word.

**Fix** — Either add a gate — `_eval_gate("G16", "capability", eval_gate_enabled(), get_latest_eval_report(kind="capability"), card)` — or remove "capability" from EvalRequire and from EVAL_REQUIRE so the card cannot express a requirement the compiler does not implement.

#### `EVALS-11` — Every critique is filed against skill "ptp-negotiate" regardless of which grader failed or which card ran the suite

MINOR · bug

**Files** — `backend/agent_core/eval/critique.py:67`, `backend/agent_core/eval/critique.py:72`, `backend/agent_core/eval/critique.py:31`, `Habibi/src/components/prompt-studio/CritiquesPanel.tsx:25`, `Habibi/src/components/prompt-studio/CritiquesPanel.tsx:28`

**Mechanism** — critique_from_report reads the failed trials' grader names to choose the suggested line (critique.py:41-45) but hardcodes `"slug": "ptp-negotiate"` on both the INSERT (critique.py:67) and the returned row (critique.py:72). The report's bot_id is selected in the query (critique.py:30) and then discarded. CritiquesPanel renders that slug next to the path "SKILL.md" (CritiquesPanel.tsx:27-30), so a crm_card_injection or skill_jailbreak critique produced from insurance-v1's red-team report instructs a human to add an objection line to the PTP negotiation skill.

**Trigger** — Critique any failed report on any card that is not kaia's PTP skill: the row reads "SKILL.md · ptp-negotiate" with a line about CRM-card delimiters.

**Fix** — Resolve the slug from the trial — the grader-to-skill mapping, or the card's attached packs via the report's bot_id — and refuse to file a critique when no slug can be resolved rather than defaulting to one.

#### `EVALS-12` — Every trial's transcript, tool calls and CRM outcomes are written as empty literals, so a failed report cannot be inspected

MINOR · bug · **closed** in `5d5ae1a` (pass 7)

**Files** — `backend/db_inbox.py:1662`, `backend/db_inbox.py:1663`, `backend/db_inbox.py:1664`, `backend/sql/14_agent_factory.sql:60`, `backend/agent_core/eval/harness.py:19`, `backend/main.py:2812`

**Mechanism** — save_eval_report inserts every eval_trials row with `"transcript": _jsonb([]), "tools": _jsonb([]), "crm": _jsonb({})` (db_inbox.py:1655-1658) — hardcoded, never derived from the trial — even though the columns exist for exactly this (sql/14_agent_factory.sql:60-63) and the harness has the fixture in hand (harness.py:22-33). Only grader_verdicts survives. GET /eval/reports/{id} (main.py:2813-2823) does not return trials at all, and no UI screen renders them. So when a regression suite goes red the operator can see the count and the one-line detail and nothing else: which fixture, which tool sequence, what the CRM row looked like are all discarded at write time and unrecoverable.

**Trigger** — Any failed trial. The row is stored, the evidence is not.

**Fix** — Persist the task's fixture (or at least its tool_calls / crm-shaped keys) into the trial, and return trials from GET /eval/reports/{id} so a red badge can be opened.

#### `EVALS-13` — GET /eval/reports/{report_id} has no tenant predicate, unlike every other eval read

MINOR · security

**Files** — `backend/main.py:2812`, `backend/main.py:2818`, `backend/db_inbox.py:1674`, `backend/authz.py:356`, `backend/agent_core/eval/critique.py:84`

**Mechanism** — The handler executes `SELECT * FROM eval_reports WHERE id = :id` with no tenant filter and returns the raw row, including tenant_id (main.py:2817-2823). Every sibling read scopes to db._tenant() — list_eval_reports (db_inbox.py:1673), list_eval_suites (db_inbox.py:1720), list_critiques (critique.py:88), list_corpus (corpus.py:31), critique_from_report (critique.py:33). authz grants this route to any BOT_READ holder (authz.py:356), so the guard is permission, not tenancy. The route has no frontend caller anywhere in Habibi/src, which bounds the exposure to a deliberate API call with a known report id.

**Trigger** — A BOT_READ actor in tenant A GETs an EVR id belonging to tenant B and receives that tenant's suite id, bot id, pass/fail status and summary.

**Fix** — Add `AND tenant_id = :tenant` with db._tenant(), and return a shaped row rather than SELECT * so tenant_id stops leaving the process at all.

#### `EVALS-14` — The canary auto-rollback trigger named "eval_fail" only ever samples red-team; a red regression or outbound report rolls nothing back

MINOR · bug

**Files** — `backend/agent_core/canary.py:381`, `backend/agent_core/canary.py:382`, `backend/agent_core/canary.py:384`, `backend/agent_core/cards/schema.py:41`, `backend/db_inbox.py:1592`

**Mechanism** — The watchdog's eval branch is `if "eval_fail" in triggers: report = db.get_latest_eval_report(bot_id=exp["bot_id"], kind="redteam")` (canary.py:381-384). The trigger's name is generic and the Ship tab offers it as one choice; regression and outbound reports — the other two kinds the compiler gates on — are never read here. A card canarying at 40% whose nightly regression suite turns red keeps taking traffic, while the identical failure in the red-team suite pulls it. Note also that the report it samples is the newest for the bot with no version scoping, the same defect as EVALS-1, so the rollback can fire on a report belonging to a different version than the canary.

**Trigger** — Publish with traffic_pct=40 and auto_rollback=["eval_fail"]. Let the nightly regression run fail. Nothing rolls back and no signal reaches the operator.

**Fix** — Sample every kind the card requires (card.eval.require) rather than hardcoding redteam, or rename the trigger to redteam_fail so the Ship tab stops promising more than it does.

#### `EVALS-15` — The Twin hint claims replays of real calls; no eval suite of any kind executes the candidate agent

MINOR · doc-vs-code · **closed** in `36349ac` (pass 7)

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:256`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:313`, `backend/agent_core/eval/harness.py:10`, `backend/agent_core/eval/run.py:1`, `backend/agent_core/eval/corpus.py:78`

**Mechanism** — The Twin checkbox's hint reads "replays of real calls against the candidate" (AgentCardPanels.tsx:256). The twin suite's tasks are created by grow_from_kept_promises with grader 'ptp_row' over a scrubbed {amount, promise_date, status} row derived from the promises table (corpus.py:81-105) — an outcome record, not a call — and every suite kind, twin included, is executed by the same loop that dispatches a grader name against a stored JSON fixture (run.py:63-79, harness.py:12-30). No prompt, persona, flow, tool grant or model is loaded on this path; the docstrings are explicit that there is "No LLM on this path". The card being published has no causal influence on any suite's result. The tab's own top paragraph is honest about this ("Code graders hit CRM-shaped fixtures", :313) — the twin hint is the line that contradicts it.

**Trigger** — Read the two lines on the same screen. An operator picks Twin believing red-team-grade replay coverage is being added to their publish bar.

**Fix** — Reword the hint to what the suite is ("code graders over outcomes grown from kept promises"), or build the replay the hint describes.

#### `EVALS-16` — Ticking Outbound on an inbound-only card produces no gate at all, not even a skipped one

MINOR · bug

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:257`, `backend/agent_core/cards/compile.py:267`, `backend/agent_core/cards/compile.py:268`, `backend/agent_core/cards/compile.py:464`, `backend/agent_core/cards/compile.py:919`

**Mechanism** — _outbound_gates returns after appending only G-OB1 skipped when the card does not dial (compile.py:267-270), so the G-OB9 append at compile.py:461-464 is never reached for an inbound card. The checkbox's hint promises "gated by G-OB9, on the same terms as G7/G8" (AgentCardPanels.tsx:257), and the requirement list then renders an outbound row with a live report status (:393-404) beside four requirements that do appear in the gate list. The requirement evaporates rather than being reported skipped by name, so the compile report gives the operator no way to see that the box they ticked has no effect on this card.

**Trigger** — Tick Outbound on kaia-v2-4 (inbound). The requirements list shows outbound with a pass/fail lozenge; the compile report contains G-OB1 skipped "inbound-only card" and no G-OB9 line whatsoever.

**Fix** — Append `_gate("G-OB9", "outbound", "skipped", "inbound-only card")` on the early-return path so the gate reports honestly, and grey the checkbox when card.outbound.dials is false.

#### `EVALS-17` — EvalCockpit renders load failure and pending as "No eval reports yet."

MINOR · bug · prior: 2k.1 (adjacent — reportTone was fixed in AgentCardPanels but this component still hardcodes pass?success:danger at :68; harmless today because eval_reports.status is CHECKed to pass/fail/error)

**Files** — `Habibi/src/components/sandbox/EvalCockpit.tsx:11`, `Habibi/src/components/sandbox/EvalCockpit.tsx:13`, `Habibi/src/components/sandbox/EvalCockpit.tsx:27`, `Habibi/src/components/sandbox/EvalCockpit.tsx:40`, `Habibi/src/api/agent-studio.ts:425`, `Habibi/src/components/prompt-studio/CritiquesPanel.tsx:63`

**Mechanism** — `const rows = reports.data ?? []` (EvalCockpit.tsx:13) with the only branch being `rows.length === 0 ? "No eval reports yet."` (:40-41) — no isPending, no isError. A 403 or a 500 on /eval/reports reads as a tenant that has never evaluated anything, immediately under a card-scoped tab about publish gating. The "Run continuous suite" button has the same pattern as EVALS-5: `void schedule.mutateAsync()` with no onError in useRunEvalSchedule (agent-studio.ts:425-435), so a 422 redteam_required or a timeout is silent.

**Trigger** — Any failure or the first paint of /eval/reports. Compare CritiquesPanel.tsx:67-81 directly below it, which handles all three states correctly.

**Fix** — Add isPending / isError branches mirroring CritiquesPanel, and an onError toast on the schedule mutation.

#### `EVALS-18` — The card-scoped Evals tab embeds a tenant-wide report list and a tenant-wide "Run continuous suite" button with no card attribution

MINOR · code-organization

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:453`, `Habibi/src/components/sandbox/EvalCockpit.tsx:10`, `Habibi/src/components/sandbox/EvalCockpit.tsx:11`, `Habibi/src/components/sandbox/EvalCockpit.tsx:21`, `Habibi/src/components/sandbox/EvalCockpit.tsx:50`, `backend/agent_core/eval/schedule.py:44`

**Mechanism** — EvalsTab renders `<EvalCockpit />` with compact defaulting to false (AgentCardPanels.tsx:453), so inside a tab scoped to one botId the operator gets useEvalReports() with no botId — the whole tenant's last 50 reports — rendered by ReportRow, which shows suite, kind, origin and date but never botId (EvalCockpit.tsx:50-71). Directly above it sits EvalReportsList, headed "Eval reports for this card". The two lists are visually identical and only one is scoped. The same panel's "Run continuous suite" button (EvalCockpit.tsx:21-31) POSTs /eval/schedule/run, which runs every regression, red-team, twin and capability suite in the tenant synchronously (schedule.py:44-56) — a tenant-wide, minutes-long write triggered from one card's tab with no confirmation.

**Trigger** — Open insurance-v1's Evals tab: below "No eval reports for this card" sits a list of kaia's green collections runs with no indication they belong to another card.

**Fix** — Pass compact and a botId to EvalCockpit here, or show a card column; and move the tenant-wide schedule trigger to a tenant-level screen behind a confirmation.

#### `EVALS-19` — The tenant-wide fallback silently disappears when 50 newer card-scoped reports crowd it out of the window

MINOR · bug · prior: 2k.2 (the tab-side fix is present at AgentCardPanels.tsx:300-310 and works; this is a new limit-window hole in that fix)

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:300`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:307`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:415`, `Habibi/src/api/agent-studio.ts:415`, `backend/main.py:2803`, `backend/db_inbox.py:1675`

**Mechanism** — The fix for prior 2k.2 reads bot-less scheduled reports out of `useEvalReports()` (AgentCardPanels.tsx:300) and skips any row that has a botId (:307-308). That query sends no limit, so the backend default of 50 applies (main.py:2804-2806, db_inbox.py:1674), ordered created_at DESC across the whole tenant. If the 50 newest reports all carry a botId — a plausible afternoon of manual runs across nine cards, or the canary path which attributes its three runs to kaia-v2-4 (run.py:26-33, llm_gateway/canary.py:180) — no bot-less row is in the window and the tab reverts to "never run on <botId>" for a suite that ran green last night. The fallback is a client-side filter over a server-side page.

**Trigger** — Not demonstrated against live data. Mechanism: 50+ bot-attributed reports newer than the last scheduled run.

**Fix** — Fetch the fallback with an explicit server-side filter for bot-less reports (a botId=__none__ style parameter, or kind-scoped queries with a small limit) rather than filtering a shared page client-side.

#### `EVALS-4` — A suites-query failure renders as "no suites" and falsely tells the operator their pinned suite does not exist

MINOR · bug · DOWNGRADED

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:269`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:377`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:378`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:379`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:423`, `Habibi/src/api/agent-studio.ts:344`, `backend/agent_core/cards/schema.py:168`

**Mechanism** — useEvalSuites has no isPending/isError branch anywhere in EvalsTab; every read is `(suitesQuery.data ?? [])`. Two consequences. (a) The suite list at :421-443 renders empty on both first paint and outright failure, so "there are no suites to run" is indistinguishable from "the suite catalogue could not be loaded" — the operator concludes evals are not configured for this tenant. (b) The staleness check at :377-379 is `card.eval?.suite_id && !(suitesQuery.data ?? []).some(...)`, so with data undefined it asserts, in a warning lozenge, `<suite id> is not a suite that exists`. That statement is false on every mount of a card with a pinned suite and stays on screen permanently if /eval/suites is down. This is the same class as prior finding 2i.1 on the Connectors tab, which was rated MAJOR.

**Trigger** — Open the Evals tab of any card whose card.eval.suite_id is set: between mount and the fetch resolving, the orange "… is not a suite that exists" lozenge renders. Make /eval/suites 500 (or revoke bot.read) and it never clears, while the Run list reads as an empty catalogue.

**Fix** — Branch on suitesQuery.isPending / isError like EvalReportsList already does (:479-495): show a loader, show an explicit "could not load the suite catalogue" error, and gate the pinned-suite warning behind suitesQuery.isSuccess.

#### `EVALS-5` — A failed suite run is completely silent — no toast, no error row, and the last-run banner disappears

MINOR · bug

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:438`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:445`, `Habibi/src/api/agent-studio.ts:366`, `Habibi/src/api/agent-studio.ts:377`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:496`

**Mechanism** — The Run button is `onClick={() => void run.mutateAsync(suite.id)}` (AgentCardPanels.tsx:438). useRunEvalSuite (agent-studio.ts:366-383) defines onSuccess only — no onError — and the component renders nothing for run.isError; the only feedback path is `run.data ? <banner> : null` (:445-449). On failure mutateAsync rejects, the `void` does not catch it (unhandled rejection, console-only), run.data is undefined, so the banner from any previous successful run vanishes and nothing replaces it. The button returns from "Running…" to "Run". Compare the sibling Critique button at :499-521, which has both an onError handler and per-row status text.

**Trigger** — Run a suite whose id was deleted (404 eval_suite_not_found from main.py:2793-2794), or run any suite while the DB is unreachable: click Run, watch "Running…", then the screen returns to exactly its prior state minus the last-run line. The operator reasonably reads this as "the run produced nothing".

**Fix** — Use run.mutate with an onError toast, or add an isError branch beside the run.data banner. Also key isPending per suite — today `disabled={run.isPending}` (:437) disables every suite's Run button while any one is running.

#### `EVALS-6` — An exception inside a grader aborts the whole run, files no report, and the 'error' status the schema reserves is never written

MINOR · bug

**Files** — `backend/agent_core/eval/harness.py:14`, `backend/agent_core/eval/harness.py:27`, `backend/agent_core/eval/graders.py:122`, `backend/agent_core/eval/graders.py:61`, `backend/sql/14_agent_factory.sql:47`, `backend/agent_core/eval/run.py:89`, `backend/main.py:2790`

**Mechanism** — run_suite_fixtures loops `verdict = run_grader(...)` with no try/except (harness.py:19-21) and computes status as only "pass" or "fail" (harness.py:28). eval_reports.status permits 'error' (sql/14_agent_factory.sql:47) and nothing can ever produce it. grade_skill_jailbreak imports agent_core.skills.intersect at call time (graders.py:125-126) and grade_crm_card_injection calls into prompt_render (graders.py:61), so a broken import or a renderer exception on one task propagates out of run_named_suite before save_eval_report is reached (run.py:91-92) — the whole suite is lost, no report row exists, and the endpoint 500s. Combined with EVALS-5 the operator sees nothing at all; the gate then reports "suite has not been run" as if nobody had tried.

**Trigger** — Any exception in one grader (renderer change, missing module, malformed fixture producing a TypeError) discards the other N-1 graded trials and files no report.

**Fix** — Wrap run_grader per task, record the failure as a failed trial with the exception text, and set the report status to 'error' when any trial errored — the vocabulary the table already reserves and that reportTone (AgentCardPanels.tsx:49) already renders.

#### `EVALS-7` — card.eval.suite_id ("Pinned suite") is authored, stored and never read by anything

MINOR · dead-config

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:349`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:361`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:368`, `backend/agent_core/cards/schema.py:168`, `backend/agent_core/eval/run.py:18`, `backend/db_inbox.py:1592`, `backend/agent_core/cards/compile.py:966`

**Mechanism** — The select writes card.eval.suite_id into the draft card. Grepping the whole backend for `eval.suite_id` finds only schema.py:168 (the field) and a comment at agent_core/eval/run.py:18 explaining that the relation was deliberately NOT used for attribution. No gate, runner or query reads it: get_latest_eval_report keys on bot_id and suite kind alone (db_inbox.py:1592-1594), and _eval_gate reads only card.eval.require (compile.py:966). The control's own default option, "— latest report of each required kind —", implies that choosing a value replaces that behaviour with a pinned one. It does not; picking a suite changes nothing anywhere.

**Trigger** — Pin "Outbound conduct" on a card whose required kind is regression, then publish: G7 still resolves the newest regression report for the bot, exactly as it did before pinning.

**Fix** — Either honour it — when card.eval.suite_id is set, restrict get_latest_eval_report to that suite for the matching kind — or make the control read-only documentation and say so, as the Tools tab does for snapshotted values.

#### `EVALS-8` — The outbound conduct suite — the one G-OB9 gates on — is never run by the scheduler, and scheduled_suite_ids is dead code that says otherwise

MINOR · stale

**Files** — `backend/agent_core/eval/schedule.py:12`, `backend/agent_core/eval/schedule.py:20`, `backend/agent_core/eval/schedule.py:35`, `backend/agent_core/eval/schedule.py:53`, `backend/worker.py:346`, `backend/main.py:2824`, `backend/agent_core/eval/fixtures.py:469`

**Mechanism** — run_continuous defaults `wanted = ("regression","redteam","twin","capability")` (schedule.py:35) and skips any suite whose kind is not in it (schedule.py:50-52); scheduled_suite_ids filters on the same four kinds (schedule.py:20-22). 'outbound' is in neither, though eval_suites' CHECK admits it (sql/14_agent_factory.sql:11) and the first-party "Outbound conduct" suite is seeded with kind='outbound' (fixtures.py:474-483). Both the nightly worker (worker.py:346, no kinds argument) and POST /eval/schedule/run (main.py:2828-2830, likewise) therefore never touch it. Separately, scheduled_suite_ids has no caller anywhere in the repo — run_continuous re-queries the table itself — so the one function that names the scheduler's scope is dead and cannot drift-check anything.

**Trigger** — Set OUTBOUND_EVAL_GATE_ENABLED=true and add "outbound" to an outbound card's eval.require on a tenant that has never manually run the suite. G-OB9 fails "outbound suite has not been run" and stays failed forever; nothing in the nightly job will ever produce the report, and no UI copy says the outbound kind is excluded (EvalCockpit.tsx:19 lists "regression, red-team, capability and twin", which is accurate but easy to miss).

**Fix** — Add 'outbound' to the default kinds in run_continuous and to scheduled_suite_ids, or delete scheduled_suite_ids and document the exclusion in the tab.

#### `EVALS-9` — Debt-word leak graders match substrings, so a compliant voicemail containing "reminder" is graded as disclosing a debt

MINOR · bug

**Files** — `backend/agent_core/eval/graders.py:201`, `backend/agent_core/eval/graders.py:209`, `backend/agent_core/eval/graders.py:211`, `backend/agent_core/eval/graders.py:256`, `backend/agent_core/eval/graders.py:276`, `backend/agent_core/eval/graders.py:393`

**Mechanism** — _DEBT_WORDS includes "emi" and "due" (graders.py:207,211) and all three consumers test membership with a bare substring `w in script` / `w in said` / `w in first` (graders.py:256, 276, 393) against a lower-cased join, with no word boundary. "emi" is a substring of "reminder"/"remind"/"reminders" — the single most likely word in a compliant callback voicemail — and of "chemistry", "academic" etc.; "due" catches any token containing it. The failure detail then reads "voicemail names emi", which points the operator at a word that is not in their script.

**Trigger** — Author an outbound task whose voicemail_script is "This is a reminder to call us back on 1800 123 4567; our grievance officer is on the same line." — a message that discloses nothing — and grade_voicemail_discloses_nothing fails it. The same substring rule fails an opening turn of "Reminder — am I speaking with Vikram?" in grade_outbound_opens_by_confirming. The shipped fixtures happen to avoid the word (fixtures.py:250-256), so the seeded suite is green and the trap is latent.

**Fix** — Match on word boundaries — tokenise, or use re.search(rf"\\b{re.escape(w)}\\b", text) — and keep the list of stems explicit.

#### `EVALS-20` — eval_tasks.pass_bar is written by every seeder and read by nothing

trivial · dead-config

**Files** — `backend/sql/14_agent_factory.sql:26`, `backend/agent_core/eval/run.py:47`, `backend/agent_core/eval/harness.py:27`, `backend/agent_core/eval/corpus.py:78`, `backend/agent_core/eval/graduate.py:40`, `backend/agent_core/eval/fixtures.py:452`

**Mechanism** — The column exists with a default of 'all' and every insert path sets it explicitly (fixtures.py:452,494,533,638,651; corpus.py:81-83; graduate.py:40-41; sql/23_outbound_evals.sql:42+). load_suite_fixtures does not select it (run.py:47-52) and run_suite_fixtures hardcodes all-must-pass — `status = "pass" if failed == 0` (harness.py:27). A task written with any other bar would be graded as 'all' silently.

**Trigger** — Set pass_bar='majority' on a task; nothing changes.

**Fix** — Honour it in the harness or drop the column.

#### `EVALS-21` — get_latest_eval_report — the gate's only input — has no tenant predicate

trivial · security

**Files** — `backend/db_inbox.py:1588`, `backend/db_inbox.py:1592`, `backend/db_inbox.py:1674`, `backend/sql/14_agent_factory.sql:45`

**Mechanism** — The gate lookup filters `WHERE r.bot_id = :bot AND s.kind = :kind` only (db_inbox.py:1593), while its neighbour list_eval_reports opens with `r.tenant_id = :tenant` (db_inbox.py:1673). Unreachable today because bots.id is a global primary key so one bot belongs to one tenant, but this is the single query that decides G7, G8 and G-OB9, and it is the one that does not name the tenant.

**Trigger** — None reachable at present; a future bot-id scheme that is unique per tenant rather than globally would make a cross-tenant report satisfy a publish gate.

**Fix** — Add `AND r.tenant_id = :tenant` for symmetry with every other read in the module.

---

## Skills — card tab, library, detail, packs, signing

19 findings — 9 MAJOR, 8 MINOR, 2 trivial; 13 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-skills.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `SKILLS-01` — The Agent Card's skill version pin is decorative — the runtime always loads the newest signed row

**MAJOR** · dead-config · prior: 2h.1 · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/cards/schema.py:102-107`, `backend/agent_core/skills/runtime.py:72`, `backend/agent_core/skills/persist.py:642-677`, `backend/agent_core/skills/persist.py:592-601`, `backend/agent_core/skills/persist.py:704`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:774`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:797-806`

**Mechanism** — `CardSkillRef` carries `version: str = "1"` and `pin: PinMode = "exact"` (schema.py:105-107) and the publish-time Agent Card stores both. `packs_from_card` reads only `ref.skill_id` (runtime.py:72) and hands the bare slug list to `packs_for_slugs`, which resolves each slug with `_latest_signed_version(slug=…)` — `WHERE sv.status='signed' ORDER BY sv.created_at DESC LIMIT 1` (persist.py:596-601). Neither `version` nor `pin` is compared to anything anywhere in the repo (grep for `.pin`/`ref.version` returns only the four literal writers). So a published prompt_version — the immutable contract this platform is built on — names a skill by slug and silently executes whatever body and allowed-tools someone signs into that slug afterwards, with no republish, no gate, and no change-log entry on the card. SkillsTab's attach now writes the catalog's displayed version instead of a literal "1" (AgentCardPanels.tsx:800-806) and its comment claims that fixes the pinning problem; it changes only what is recorded, not what is loaded, and it omits `pin` entirely.

**Trigger** — Sign any new version of a slug an already-published card names (e.g. edit `ptp-negotiate` in the Skills library and press Sign). Every live call on kaia-v2-4 begins using the new body and new tool set on the next bundle load, while the published card still reads `{"skill_id":"ptp-negotiate","version":"1","pin":"exact"}`.

**Fix** — Make `packs_for_slugs` take `(slug, version, pin)` and select the exact `skill_versions` row for `pin=="exact"`, falling back to latest-signed only for a `latest`/`range` pin; fail closed (drop the slug, as the corrupt-pack path already does at persist.py:670-672) when the pinned version is missing or unsigned. Add a G9 sub-check that every card ref resolves to a version that exists. Until then, stop writing a `version` the system does not honour.

#### `SKILLS-02` — "Revert to signed" / "Restore" changes the Studio display but not what the mouth loads

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/skills/persist.py:445-471`, `backend/agent_core/skills/persist.py:566-601`, `backend/agent_core/skills/persist.py:642-677`, `backend/db_prompt_studio.py:834`, `Habibi/src/routes/agent-studio.skills.$skillId.tsx:246-263`, `Habibi/src/routes/agent-studio.skills.$skillId.tsx:353-367`

**Mechanism** — `revert_skill` writes `skills.latest_version_id = target.id` and nothing else (persist.py:459-470). Every read the Studio performs keys on `latest_version_id` (persist.py:162, 210). The runtime does not: `_latest_signed_version` orders by `sv.created_at DESC` (persist.py:578,598) and ignores `latest_version_id` completely. So when a slug has two or more signed versions, reverting to the older one moves the lozenge, the version list's "· latest" marker and the toast ("Reverted to v1"), while `packs_from_card` keeps resolving the newer signed row — its body, its `allowed_tools`, its skill-gated write unlocks. The compile preview and G9 also use `packs_for_slugs` (db_prompt_studio.py:834), so the gate agrees with the runtime and only the operator is told otherwise. This is the one control an operator reaches for when a signed skill turns out to be wrong in production.

**Trigger** — Two signed versions per slug already exist on any seeded install: `seed_postgres.py:1458-1477` hardcodes version "1"/`{sid}-v1` while `ensure_first_party_skills` derives the id from `metadata.version` (persist.py:20-21, 36-37), so ptp-negotiate (1.5.0), hardship-intake (1.1.0) and verify-and-disclose (1.1.0) each get a second signed row on first boot. Click Restore on the older row: the page says v1 is latest; the mouth keeps loading v1.5.0. Behavioural divergence lands the moment an operator patches + signs a content-differing version and then tries to roll it back.

**Fix** — Resolve packs by `skills.latest_version_id` (joined and re-checked for `status='signed'`) rather than by `created_at DESC`, so one column decides what is current for the UI, the gate and the runtime alike. Add `ORDER BY created_at DESC, id DESC` as a tie-break either way — two rows written in one transaction currently resolve arbitrarily under a frozen `now()`.

#### `SKILLS-03` — Skill HMAC verification never reaches the runtime — an unverifiable pack still grants tools and injects its body

**MAJOR** · security · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/skills/persist.py:91-100`, `backend/agent_core/skills/persist.py:660-673`, `backend/agent_core/skills/intersect.py:113-114`, `backend/agent_core/skills/runtime.py:166-173`, `backend/agent_core/skills/runtime.py:271-286`, `backend/agent_core/cards/compile.py:731`, `backend/.env.example:336-340`

**Mechanism** — `pack_from_version_row` computes `pack.signed = signed and bool(signature) and verify_signature(content_hash, signature)` (persist.py:96-98). A repo-wide grep for `.signed` shows exactly one consumer: `compile.py:731` (`unsigned = [p.slug for p in packs if not p.signed]`) — the publish-time G9 gate. Nothing on any runtime path branches on it. `MouthTurn.prompt()` (runtime.py:166-173) injects the body of any pack in `self.packs`; `effective_tools` unions `pack.allowed_tools` into the grant via `union_skill_tools` (intersect.py:113-114) with no signature test; `load_skill` (runtime.py:277-286) returns the body and tool list for any attached pack. Selection is by `status='signed'` — a stored *string column*, not a verified signature. So a row whose body was edited in the database while `status` stayed 'signed', or every tenant-signed row after a key rotation, keeps unlocking `create_promise_to_pay` / `flag_dispute` / `apply_goodwill` and keeps feeding its instructions to a live collections call. The signature is checked only at the door the pack has already walked through.

**Trigger** — Rotate `SKILL_PLATFORM_KEY` (the documented procedure at .env.example:337-341). First-party packs are re-signed on boot; every tenant-signed pack now fails `verify_signature` — and keeps running, silently, until someone tries to publish a card that names it. Or: `UPDATE skill_versions SET body=… WHERE status='signed'` with no signature change.

**Fix** — Filter in `packs_for_slugs`: drop (and log, as the corrupt-parse path does at persist.py:670-672) any row whose signature does not verify, so the mouth fails closed exactly as it does for a DB outage (runtime.py:83-91). Verify at read time in `list_skills`/`get_skill` too, so the library reports the truth.

#### `SKILLS-04` — Importing a .md/.zip permanently overwrites a signed first-party pack — no slug guard, and boot-sync will never restore it

**MAJOR** · security · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/main.py:2451-2481`, `backend/agent_core/skills/persist.py:354-358`, `backend/agent_core/skills/persist.py:243-313`, `backend/agent_core/skills/persist.py:744-745`, `backend/agent_core/skills/pack.py:152`, `backend/seed_postgres.py:1457`, `Habibi/src/routes/agent-studio.skills.index.tsx:140-149`

**Mechanism** — `create_draft_skill` deliberately refuses to be an upsert — `if slug_exists(slug): raise ValueError("skill_slug_taken")`, with the comment "creating over an existing slug silently unsigned a first-party pack and replaced its body" (persist.py:354-358), pinned by `test_create_rejects_an_existing_slug`. The import endpoint calls `upsert_skill_from_pack` directly (main.py:2491) and has no such guard. A file whose frontmatter reads `name: ptp-negotiate` therefore takes the `ON CONFLICT (skill_id, version) DO UPDATE` path (persist.py:282-291) and overwrites `body`, `allowed_tools`, `content_hash`, sets `signature = NULL` and `status = 'draft'`; the parent row's `ON CONFLICT` origin CASE (persist.py:249-253) moves origin from `first_party` to `tenant` because the CASE only preserves `tenant`/`gardener`. That last part makes it permanent: `ensure_first_party_skills` skips any row whose origin is tenant/gardener (persist.py:744-745), so no restart ever restores the platform pack. The UI reports "Imported as unsigned draft" (index.tsx:143) — true of the row it created, silent about the signed production pack it destroyed.

**Trigger** — Library → "Import zip" with any .md whose `name:` matches an existing slug. Requires only AGENT_EDIT (authz.py:324), not AGENT_PUBLISH.

**Fix** — Route import through the same guard: refuse a taken slug (409 `skill_slug_taken`) or auto-uniquify via `unique_slug`, and never let an import path flip a `first_party` row's origin. Wrap the handler in `_handle_write` while there (see SKILLS-13).

#### `SKILLS-05` — The library's "signed" lozenge echoes a stored column and never verifies the signature it claims to represent

**MAJOR** · degradation-lie · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/skills/persist.py:60`, `backend/agent_core/skills/persist.py:15`, `backend/agent_core/skills/persist.py:190-216`, `Habibi/src/routes/agent-studio.skills.index.tsx:159`, `Habibi/src/routes/agent-studio.skills.index.tsx:337-339`, `Habibi/src/routes/agent-studio.skills.$skillId.tsx:230`, `Habibi/src/routes/agent-studio.skills.$skillId.tsx:249`, `Habibi/src/routes/agent-studio.skills.$skillId.tsx:336`

**Mechanism** — `_map_skill` derives `"signed": row["signature_status"] == "signed"` (persist.py:60) and `status` from the version row's `status` string. Neither `list_skills` nor `get_skill` ever calls `verify_signature` — the only callers are `sign_skill` (persist.py:422), `revert_skill` (persist.py:457) and `pack_from_version_row` (persist.py:96), none of which is on the read path. The library header states "Signing is HMAC, not a badge" (index.tsx:159) directly above a lozenge that is exactly a badge. After a key rotation, or after any direct edit of a `status='signed'` row, every affected pack renders green in both the library and the detail page, the Sign button is disabled (`disabled={sign.isPending || skill.signed}`, $skillId.tsx:230) so an operator cannot even re-sign from the UI, and G9 will fail the next publish citing a pack the screen insists is fine.

**Trigger** — Rotate `SKILL_PLATFORM_KEY`, or hand-edit a signed row. Open /agent-studio/skills: every tenant pack still reads "signed", Sign is greyed out, publish fails with `unsigned or out-of-scope skill tools`.

**Fix** — Verify on read: have `_map_version` compute `signatureValid = verify_signature(content_hash, signature)` and render three states (signed-and-valid, signed-but-unverifiable, unsigned). Keep Sign enabled when the stored signature does not verify.

#### `SKILLS-06` — API restart silently demotes an operator's signed edit of a first-party skill back to the platform version

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/skills/persist.py:729-765`, `backend/agent_core/skills/persist.py:400`, `backend/agent_core/skills/persist.py:403-405`, `backend/agent_core/skills/persist.py:427-442`, `backend/agent_core/skills/persist.py:310-313`, `backend/main.py:499-501`

**Mechanism** — `patch_skill` preserves origin (`pack.origin = current["origin"]`, persist.py:400), so an edited first-party skill stays `origin='first_party'` and is NOT protected by the tenant/gardener skip at persist.py:744-745. On boot, `ensure_first_party_skills` computes `expected_vid` from the disk pack's `metadata.version` and then `set_latest = latest_is_this or existing["signature_status"] == 'signed'` (persist.py:749-752). After an operator patches and signs (which sets `signature_status='signed'`, persist.py:438-441), `latest_is_this` is False but the signature_status test is True — so `set_latest=True` and the boot upsert writes `latest_version_id` back to the disk pack's row (persist.py:310-313). The operator's signed version is demoted with no log line naming it, no change-log entry, and no UI signal. Worse, because the runtime selects by `created_at DESC` (SKILLS-02), the operator's newer row is still what every call loads — so after a restart the Skills library and the live mouth disagree about which body is in production.

**Trigger** — Edit any first-party skill in the detail page, Save, Sign, then restart the API (or trigger a boot-sync). The version list's "· latest" marker jumps back to the platform row.

**Fix** — Only advance `latest_version_id` when the current latest IS the disk row (`set_latest = latest_is_this`), or gate the whole refresh on `content_hash` being unchanged. Log at WARNING whenever boot-sync moves a latest pointer an operator set.

#### `SKILLS-08` — A pack's declared `mouth:` channels are parsed and never enforced — internal-only skills ride on a customer-facing card

**MAJOR** · dead-config · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/skills/pack.py:31`, `backend/agent_core/skills/pack.py:144-155`, `backend/agent_core/skills/defaults.py:22-31`, `backend/agent_core/skills/defaults.py:35-42`, `backend/agent_core/skills/packs/floor-coach/SKILL.md:10-17`, `backend/agent_core/skills/packs/qa-examiner/SKILL.md:10-12`, `backend/agent_core/skills/runtime.py:271-286`, `backend/agent_core/skills/intersect.py:51`

**Mechanism** — `parse_skill_md` reads `metadata.mouth` into `SkillPack.mouth` (pack.py:144-155). A repo-wide grep for `.mouth` finds writers only — no gate, no runtime filter, no lint rule reads it. `floor-coach` declares `mouth: [internal]` and its body is agent-whisper copy ("Whisper copy is for the human agent"); it is nonetheless in `COLLECTIONS_SKILLS` (defaults.py:30), i.e. attached to kaia-v2-4, the customer-facing collections mouth. `load_skill` (runtime.py:277) matches on slug alone against the attached list, so the model can activate it mid-call and its body becomes a developer message on a live customer conversation. The same holds for `qa-examiner` on the supervisor card. The frontmatter field exists precisely to prevent this and is inert.

**Trigger** — On a kaia-v2-4 voice call, the model calls `load_skill(slug="floor-coach")` — a tool it is always offered (`PLATFORM_SKILL_TOOLS`, intersect.py:51). Nothing refuses.

**Fix** — Enforce `pack.mouth` in two places: `load_skill`/`resolve_mouth` should drop packs whose `mouth` list excludes the current channel (thread the channel through `resolve_mouth`, as `channel_tools` already is), and add a compile gate that fails a card attaching a pack whose declared mouths do not include any channel the card serves.

#### `SKILLS-09` — load_skill tells the model it may call tools that are not in its grant or renderable on its channel

**MAJOR** · shape-mismatch · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/skills/runtime.py:280-284`, `backend/agent_core/skills/intersect.py:206-209`, `backend/voice/tools.py:2828-2833`, `backend/bot_tools.py:744-748`, `backend/bot_tools.py:769-793`, `backend/agent_core/skills/intersect.py:65-68`, `backend/agent_core/skills/intersect.py:198`, `backend/agent_core/tools/catalog.py:210`, `backend/agent_core/skills/defaults.py:23`, `backend/agent_core/skills/defaults.py:33-34`

**Mechanism** — `load_skill` returns `"allowed_tools": sorted(tools_after_references(pack.allowed_tools, …))` — the pack's raw list, never intersected with the card's effective grant or with the channel's renderable set (runtime.py:280-284). Both handlers forward it verbatim into the tool result the model reads (voice/tools.py:2830, bot_tools.py:747). The offer side does the intersection correctly — `offered_tools` adds only `[n for n in active.allowed_tools if n in allowed and n not in idle]` (intersect.py:198) — so the two halves of the same activation disagree. Concretely: `verify-and-disclose` (attached to all four first-party cards, defaults.py:33-35) lists `verify_identity`, which is `channels=VOICE_ONLY` (catalog.py:210) and has no entry in the text registry's `HANDLERS` (bot_tools.py:769-793). On WhatsApp, `_apply_channel` (intersect.py:65-68) correctly strips it from the grant and the offer — and then `load_skill` hands the model a result naming it, alongside a body that instructs "Call verify_identity, then read context. Never skip disclosure or share dues with an unverified party." The model is told to verify identity with a tool it is not given, on a regulated disclosure path.

**Trigger** — WhatsApp/text conversation on kaia-v2-4 or intake-v1 where the model calls `load_skill(slug="verify-and-disclose")`.

**Fix** — Have `load_skill` take the turn's `ToolState` (or the card + channel) and return `sorted(set(pack.allowed_tools) & set(state.offered))`, plus an explicit `unavailable_on_this_channel` list so the body's instructions can be reconciled rather than silently contradicted. Add a gate warning when a pack's `allowed_tools` contain names not renderable on any channel the card serves.

#### `SKILLS-10` — "Load in sandbox" always falls back to kaia-v2-4 for the only skills you can actually author, producing a run that exercises nothing

**MAJOR** · degradation-lie · prior: 4.7 · **closed** in `9972995` (pass 3)

**Files** — `Habibi/src/routes/agent-studio.skills.$skillId.tsx:192-206`, `backend/agent_core/skills/persist.py:126-137`, `backend/agent_core/skills/persist.py:611-613`, `backend/agent_core/skills/persist.py:378`, `backend/agent_core/skills/runtime.py:166-173`, `backend/sandbox_runtime.py:719-726`, `Habibi/src/components/sandbox/SandboxHeader.tsx:137`

**Mechanism** — The button now sends `botId: skill.attachedCards?.[0] ?? "kaia-v2-4"`. `attachedCards` is populated only from `skill_attachments` joined to `prompt_versions` with `pv.status='published'` on a non-archived bot (persist.py:125-135), and attachments only exist for signed versions (persist.py:611-613) synced at publish (db_prompt_studio.py:1962). Every skill an operator can create or clone is an unsigned tenant draft, so `attachedCards` is empty by construction and the fallback always fires. The sandbox then runs kaia-v2-4's card, whose `skills[]` does not name the draft slug, so `resolve_mouth(agentCard, active_slug=skill_slug)` finds no matching pack and `MouthTurn.prompt()` returns `body_message=None` (runtime.py:169-172) — silently. The run completes green having injected none of the skill under test. This is the class of failure the sandbox exists to prevent, and the code comment at $skillId.tsx:198-202 claims it was fixed.

**Trigger** — Create a new skill in the library, land on the detail page, click "Load in sandbox", run a turn. The transcript shows a normal kaia run with no skill body.

**Fix** — Disable the button (with a title explaining why) when `attachedCards` is empty, or let the operator pick a card. Server-side, make `runSandboxTurn` return an explicit `skill_not_attached` marker when `skillSlug` is supplied and does not resolve, and surface it in the run header — a rehearsal that silently rehearses nothing is worse than a refused one.

#### `SKILLS-07` — The Skills tab holds the compile report and never warns that attaching this pack fails G9

MINOR · code-organization · DOWNGRADED

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:774-777`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:883-899`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:94-96`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:128-140`, `backend/agent_core/cards/compile.py:724-751`

**Mechanism** — `SkillsTab` runs `useCompilePreview(botId, {agentCard: card})` (AgentCardPanels.tsx:776) — the full `CompileReport`, gates included — and reads exactly one field off it, `skill_description_tokens`. G9 is the gate this tab governs: it fails when a pack's `allowed_tools` are not a subset of `card.tools.include ∪ locked ∪ {load_skill, run_skill_script}` (compile.py:733-745), which is precisely what the Attach button can cause, and the tab renders each pack's `allowedTools` as inert grey text with no comparison against the card. Three functions above, `ToolsTab` does the right thing with the same query object: it pulls G6 out of `preview.data.gates` and renders a fail/warn/pass lozenge with the gate's detail (AgentCardPanels.tsx:128-140). The prior audit's live probe found kaia-v2-4's draft already unpublishable for exactly this reason (`set_contact_preference`, `capture_nonpayment_reason` allowed by packs but absent from the draft card) — a state this tab creates and then declines to mention. The author learns about it at the publish dialog, after the work.

**Trigger** — On any authored card, Attach a pack listing a skill-gated tool the card does not include (e.g. `ptp-negotiate` on a card without `create_promise_to_pay`). The tab shows nothing; the card is now unpublishable.

**Fix** — Mirror ToolsTab: pull `gates.find(g => g.gate === 'G9')` from `preview.data`, render its status and detail as a lozenge in the header row, and mark the offending tool chips on each row (compare `skill.allowedTools` against `card.tools.include ∪ locked ∪ PLATFORM_SKILL_TOOLS`) so the fix is visible where the cause is.

#### `SKILLS-11` — The sandbox loads the chosen skill's body but computes its tool offer from a different active skill

MINOR · shape-mismatch

**Files** — `backend/sandbox_runtime.py:197-232`, `backend/sandbox_runtime.py:828-833`, `backend/sandbox_runtime.py:852-862`

**Mechanism** — The prompt half resolves with the operator's explicit slug: `resolve_mouth(card, intent=intent, active_slug=skill_slug)` (sandbox_runtime.py:828-833). The tool half — `_run_sandbox_tool_loop` — is called without it (sandbox_runtime.py:853-862) and re-resolves as `resolve_mouth(agent_card, intent=intent)` (sandbox_runtime.py:214), so `active_slug` comes from the `INTENT_TO_SKILL` map instead. The turn therefore runs skill A's instructions against skill B's offered tool set (or against the idle set when the intent maps to nothing, in which case every skill-gated write is withheld and the rehearsal cannot reach the behaviour under test). Two `resolve_mouth` calls in one turn that disagree about which skill is active.

**Trigger** — Sandbox a turn with `skillSlug=ptp-negotiate` on a customer utterance the classifier scores as `hardship`: body = ptp-negotiate, offer widened for hardship-intake.

**Fix** — Pass `skill_slug` into `_run_sandbox_tool_loop` and use one `MouthTurn` for both halves — `resolve_mouth` was split into `prompt()`/`tools()` (runtime.py:141-215) precisely so one resolution answers both questions.

#### `SKILLS-12` — INTENT_TO_SKILL is a hardcoded seven-entry map no card can author, so most packs never auto-activate

MINOR · dead-config

**Files** — `backend/agent_core/skills/runtime.py:28-36`, `backend/agent_core/skills/runtime.py:99-104`, `backend/agent_core/skills/runtime.py:38-45`, `backend/agent_core/skills/defaults.py:8-42`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:813-815`

**Mechanism** — `resolve_intent_skill` looks the classified intent up in a module-level dict of seven fixed pairs (runtime.py:28-36). There is no card field, no DB table and no Studio control that can add an entry. Four of the eleven first-party packs — `doc-fulfil`, `broken-ptp-chase`, `qa-examiner`, `floor-coach`, plus `supervisor-brief` — appear on no right-hand side, and every tenant-authored or gardener-promoted skill is unreachable by intent by construction. Those packs still pay for their description in the always-on prefix (runtime.py:39-45, counted by G6's `CATALOG_PREFIX_TOKEN_CAP`) and can only ever be activated by the model choosing to call `load_skill` on a slug it was told about in one line of prose. The Skills tab tells the author "The body loads on `load_skill` or intent" (AgentCardPanels.tsx:814-815) without distinguishing the packs for which "or intent" is false. `insurance-lapse` is also mapped from `product_faq`, which reads like a mis-binding rather than a design choice.

**Trigger** — Attach any tenant skill, or `doc-fulfil`, to a card: it costs prefix tokens on every turn and will never be activated by intent.

**Fix** — Move the map onto the card (an `intents: []` per `CardSkillRef`, or `metadata.intents` in the pack frontmatter, which is where the author already declares `mouth` and `data_class`), and lint at publish for a pack that no intent can reach. Failing that, label those rows in the tab as `load_skill only`.

#### `SKILLS-13` — Import and KB-gap promotion bypass _handle_write, so authoring errors return 500 instead of the mapped 422/409

MINOR · bug · **closed** in `5d5ae1a` (pass 7)

**Files** — `backend/main.py:2451-2481`, `backend/main.py:2510-2534`, `backend/main.py:818-834`, `backend/main.py:772-774`, `backend/main.py:724-745`, `backend/agent_core/skills/gardener.py:16-17`, `Habibi/src/routes/agent-studio.skills.index.tsx:146-148`

**Mechanism** — Every other skills write is wrapped in `_handle_write`, which maps `ValueError` through `_VALUE_ERROR_STATUS` (main.py:828-833). The import handler calls `upsert_skill_from_pack` bare (main.py:2491) and `promote_kb_gap_to_skill` calls `create_draft_skill` bare (main.py:2526). So `skill_missing_frontmatter`, `skill_missing_name`, `skill_allowed_tools_not_a_list` — all three of which are given explicit 422 mappings at main.py:770-772 and can be raised by no other endpoint — escape as unhandled 500s, as do `skill_lint_failed` (an unknown allowed-tool in the imported file), `zipfile.BadZipFile` for a non-zip upload, and `UnicodeDecodeError` for a non-UTF-8 file. `skill_slug_taken` from a repeat gap promotion (the gardener slug is `gardener-{intent}`, gardener.py:17-18, so two gaps with the same top intent collide) is also a 500. The library toasts whatever the client throws (index.tsx:146-148), so the operator sees a server error for a malformed file they can fix.

**Trigger** — Import a .md with no `---` frontmatter, or a .zip containing no SKILL.md variant that reaches the parser, or promote two KB gaps sharing a top intent.

**Fix** — Wrap both handlers in `_handle_write`, and catch `BadZipFile`/`UnicodeDecodeError` in the import branch as 422 with a named detail.

#### `SKILLS-14` — The /skills/{id}/attach and /detach endpoints have no caller and are overwritten at publish

MINOR · disconnected

**Files** — `backend/main.py:2404-2424`, `backend/agent_core/skills/persist.py:606-639`, `backend/agent_core/skills/persist.py:680-708`, `backend/db_prompt_studio.py:1959-1964`, `Habibi/src/api/agent-studio.ts:645-760`

**Mechanism** — No frontend module references `/skills/*/attach` or `/detach` (grep across Habibi/src returns nothing); the Skills tab attaches by mutating `card.skills[]` locally and letting autosave persist the draft (AgentCardPanels.tsx:783-807 → prompt-studio.lazy.tsx:1394). Server-side the rows they write are transient anyway: publishing a version runs `sync_attachments_from_card`, which `DELETE`s every attachment for that prompt_version_id and rebuilds from the card (persist.py:690-709, called at db_prompt_studio.py:1962). So the endpoints are an API-only side door whose effect is erased by the next publish of that version, while carrying a semantic the card path does not (`attach_skill_to_prompt` refuses an unsigned skill with `skill_unsigned`, persist.py:611-613 — the card path has no such check before G9).

**Trigger** — Call POST /agent-studio/skills/{id}/attach against a published version, then republish that bot: the attachment is gone and the card never knew about it.

**Fix** — Either delete both endpoints, or make them write the card (`card.skills`) so there is one writer for one fact.

#### `SKILLS-15` — A read-only GET can seed the catalog and rewrite a published card's agent_card with no change-log entry

MINOR · security

**Files** — `backend/agent_core/skills/persist.py:180-186`, `backend/agent_core/skills/persist.py:191`, `backend/agent_core/skills/persist.py:777-821`, `backend/authz.py:310-312`, `backend/main.py:499-501`

**Mechanism** — `list_skills` self-heals an empty catalog by calling `ensure_first_party_skills()` and recursing (persist.py:180-186), and `get_skill` reaches it through `list_skills()` (persist.py:191). `GET /agent-studio/skills` and `GET /agent-studio/skills/{id}` are `BOT_READ` (authz.py:310-312). `ensure_first_party_skills` is not a read: it INSERTs/UPDATEs `skills` and `skill_versions`, INSERTs `skill_attachments`, and — at persist.py:811-820 — issues `UPDATE prompt_versions SET agent_card = … WHERE id = :id` against rows whose `status='published'`, injecting a `skills: [{skill_id, version:"1", pin:"exact"}, …]` list into a card that has already been published, gated and hashed. No `record_change_log` accompanies it, so the Change log tab — the tamper-evidence surface — shows nothing, and the published contract now differs from the one G0-G15 were run against.

**Trigger** — Any BOT_READ actor opening the Skills library on an install whose catalog is empty (a migrate-only deploy, the documented reason this path exists). Also fires on every API boot via main.py:499-503 for any published card whose `agent_card.skills` is absent.

**Fix** — Make catalog seeding an explicit boot/admin action only — have `list_skills` report an empty catalog honestly rather than repairing it from a GET. Whatever path rewrites a published `agent_card` must write a change-log entry naming itself, or it should refuse and surface the drift instead.

#### `SKILLS-16` — Seeded and boot-synced installs carry two signed version rows per pack for the three packs past 1.0.0

MINOR · stale · **closed** in `5d5ae1a` (pass 7)

**Files** — `backend/seed_postgres.py:1455-1494`, `backend/agent_core/skills/persist.py:20-21`, `backend/agent_core/skills/persist.py:749-763`, `backend/agent_core/skills/packs/ptp-negotiate/SKILL.md:14`, `Habibi/src/routes/agent-studio.skills.$skillId.tsx:342-372`

**Mechanism** — `seed_skills` hardcodes `vid = f"{sid}-v1"` and `version: "1"` for every pack regardless of its frontmatter (seed_postgres.py:1458, 1477). `ensure_first_party_skills` derives the row id from `_stored_version(pack.version)`, which collapses only `"1"`/`"1.0.0"` to `"1"` (persist.py:20-21) — so `ptp-negotiate` (metadata.version 1.5.0), `hardship-intake` (1.1.0) and `verify-and-disclose` (1.1.0) get a second row `skill-<slug>-v1_5_0` on first boot, both signed, both holding identical content. The detail page's Versions panel then lists `v1 · signed` and `v1.5.0 · signed · latest`, offering a Restore link on the older one — which is the trigger for SKILLS-02 — and the library's `version` field reports whichever `latest_version_id` currently points at.

**Trigger** — Open /agent-studio/skills/skill-ptp-negotiate on any seeded install.

**Fix** — Make `seed_skills` use `_stored_version(pack.version)` and `_version_row_id` (or simply call `ensure_first_party_skills`) so seed and boot agree on one row id per pack version.

#### `SKILLS-17` — The Skills library's only test greps its own source text and asserts no behaviour

MINOR · test-gap · **closed** in `a33efbd` (pass 7)

**Files** — `Habibi/src/routes/agent-studio.skills.index.test.ts:1-15`, `Habibi/src/routes/agent-studio.skills.index.tsx:245-263`

**Mechanism** — The whole suite for a 460-line route is `readFileSync(...)` plus three `toContain`/`not.toContain` string assertions. It passes if the words `clonePending` and `AlertDialog` appear anywhere in the file — including in a comment — and would keep passing if the dialog never opened, the clone slug were never sent, or the delete confirmation were wired to the wrong row. The repo has already moved the other way for the frontend suite (commit f7c6c42, "the suite can render, so keyboard paths are asserted by pressing"), and nothing renders or presses here. Nothing at all covers import, delete-guard reasons, the isError-with-cached-data banner (index.tsx:253-263) or the create-form validation.

**Trigger** — n/a — the gap is the finding.

**Fix** — Render the route with a mocked query client and assert the behaviours: clone dialog opens and posts the typed slug, Delete is disabled with the right `title` for each refusal reason, a failed refetch keeps the grid and shows the warning banner, and create refuses a blank description without collapsing the form.

#### `SKILLS-18` — Exporting a skill with no resolvable latest version returns a 200 zip containing an empty SKILL.md

trivial · bug

**Files** — `backend/main.py:2426-2449`, `backend/agent_core/skills/persist.py:209-215`, `backend/sql/15_skills.sql:44-47`

**Mechanism** — `get_skill` sets `markdown` only inside `if latest:` (persist.py:210-215). If `latest_version_id` is NULL or points at a row that is not in the version list, the key is absent and the export writes `zf.writestr("SKILL.md", row.get("markdown") or "")` — a valid zip with a zero-byte SKILL.md, served as 200 with the correct filename. Re-importing it raises `skill_missing_frontmatter`, which is itself a 500 (SKILLS-13). The FK is `ON DELETE SET NULL` (sql/15_skills.sql:44-48), so a NULL latest is representable.

**Trigger** — Export a skill row whose `latest_version_id` is NULL.

**Fix** — 404 (or 409 `skill_has_no_version`) when `markdown` is absent rather than streaming an empty pack.

#### `SKILLS-19` — The key-rotation runbook in .env.example understates what rotation does to tenant packs

trivial · doc-vs-code · DOWNGRADED · **closed** in `5d5ae1a` (pass 7)

**Files** — `backend/.env.example:336-340`, `backend/agent_core/skills/persist.py:60`, `backend/agent_core/skills/persist.py:96-98`, `backend/agent_core/skills/intersect.py:113-114`

**Mechanism** — The comment says "Rotating this key: restart the API so ensure_first_party_skills re-signs disk packs. Tenant drafts stay unsigned until a human signs them again." Tenant *drafts* were already unsigned; the affected rows are tenant packs that WERE signed. Those keep `signature_status='signed'` in the database, keep rendering green in the library (persist.py:60), keep granting their skill-gated tools and injecting their bodies on live calls (intersect.py:113-114 — see SKILLS-03), and fail only at the next publish of a card that names them. The runbook gives an operator no reason to expect any of that.

**Trigger** — Follow the documented rotation procedure on an install with tenant-signed packs.

**Fix** — Correct the comment, and give the rotation a real procedure: re-sign or explicitly retire every tenant-signed version, and have the library show verification state (SKILLS-05) so the blast radius is visible.

---

## Connectors — tab, registry, ext.* dispatch

17 findings — 5 MAJOR, 10 MINOR, 2 trivial; 7 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-connectors.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `CONNECTORS-1` — "Test" toasts success for a failed or SSRF-blocked health probe, and a blocked probe leaves health untouched

**MAJOR** · degradation-lie · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `Habibi/src/components/integrations/McpConsole.tsx:108`, `Habibi/src/components/integrations/McpConsole.tsx:111-113`, `Habibi/src/api/integrations.ts:312-318`, `Habibi/src/router.tsx:13-15`, `backend/agent_core/connectors/persist.py:317-323`, `backend/agent_core/connectors/circuit.py:84`, `backend/main.py:2556-2561`, `backend/main.py:814-816`

**Mechanism** — health_test returns {"ok": False, "error": ...} on a 200 rather than raising (persist.py:317-323), so _handle_write passes it straight through. The button does `void mut.test.mutateAsync(r.id).then(() => toast.success("Health test ran"))` with no inspection of `ok` and no `.catch`. Worse for the blocked-URL branch (persist.py:318-321): it returns early WITHOUT calling circuit.record_failure and WITHOUT touching the health column, so the row keeps whatever health it had ("unknown"/"healthy") forever.

**Trigger** — Operator clicks Test on a remote_mcp connector whose URL now resolves to a private/metadata address (or is simply unreachable). UI shows a green "Health test ran" toast; the Health column still reads healthy or unknown; nothing on screen says the target is refused.

**Fix** — Read the result: `const r = await mut.test.mutateAsync(id); r.ok ? toast.success(...) : toast.error(`Health test failed: ${r.error}`)`, and add a `.catch`. In persist.health_test, set `health = 'down'` (or a new 'blocked') on the connector_url_* branch so the table reflects the refusal even without the toast.

#### `CONNECTORS-3` — Re-saving an existing connector through "Add connector" silently reverts approved → draft

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `Habibi/src/components/integrations/McpConsole.tsx:148`, `Habibi/src/components/integrations/McpConsole.tsx:152`, `backend/agent_core/connectors/persist.py:185`, `backend/agent_core/connectors/persist.py:169`

**Mechanism** — The form posts no `status`, so upsert_connector computes `str(payload.get("status") or "draft")` (persist.py:185), and the ON CONFLICT (tenant_id, slug) branch does `status = EXCLUDED.status` (persist.py:169). Re-submitting an existing slug therefore overwrites an approved row back to draft. The toast still says "Connector saved".

**Trigger** — Operator fixes a typo in a live connector's URL by retyping the same slug and clicking Add connector. The row silently de-approves; every card bound to it now fails G10 not_approved on the next publish and dispatch returns connector_not_bound at runtime.

**Fix** — In upsert_connector, only set status when the payload explicitly carries one: change the conflict clause to `status = COALESCE(:status_explicit, mcp_connectors.status)`, or have the UI send the row's current status when editing. Registration should never be able to change approval state implicitly.

#### `CONNECTORS-4` — "Connect IdP" always writes the CIMD issuer to rows[0], not to a selected connector

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `Habibi/src/components/integrations/McpConsole.tsx:192`, `Habibi/src/components/integrations/McpConsole.tsx:195`, `backend/agent_core/connectors/persist.py:79`, `backend/agent_core/connectors/persist.py:424-444`, `backend/main.py:2563-2569`

**Mechanism** — The button is disabled on `!rows[0]` and mutates `{ id: rows[0].id, issuer }` — the first row of a list the backend returns ORDER BY slug (persist.py:80). There is no connector selector anywhere in the panel, and the success toast reports only the generated clientId, never which connector it landed on.

**Trigger** — With connectors lms, paylink and bank-mcp registered, an operator types the bank's IdP issuer and clicks Connect IdP. cimd_issuer and cimd_client_id are stamped on `lms` (alphabetically first). The screen shows "CIMD client cimd-xxxx" and the operator believes the bank connector is federated.

**Fix** — Add a row-level Connect IdP action (or a connector select bound to the issuer input) and name the connector in the toast. Until then, disable the button rather than defaulting to rows[0].

#### `CONNECTORS-5` — Bind/Unbind in the Connectors tab changes nothing any model can ever call — ext.* is in the Grant but in no Offer, and voice has no ext handler at all

**MAJOR** · disconnected · **closed** in `5435761` (pass 3)

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:1003`, `backend/agent_core/skills/intersect.py:117-123`, `backend/agent_core/skills/intersect.py:164`, `backend/agent_core/skills/intersect.py:168`, `backend/agent_core/skills/intersect.py:198`, `backend/agent_core/tools/schema.py:238`, `backend/voice/tools.py:2918-2919`, `backend/bot_tools.py:158-160`, `backend/bot_runtime.py:943`

**Mechanism** — bound_tool_names puts ext.* into effective_tools/Grant (intersect.py:117-123), but idle_offered_tools strips every name starting with "ext." (:164,:168) and the only widening branch adds names from the ACTIVE skill pack's allowed_tools (:198) — no shipped pack under backend/agent_core/skills/packs/ lists an ext.* tool. Even if one did, ToolCatalog.openai_tools does `[self.specs[n] for n in names if n in self.specs]` (schema.py:238) and ext.* names are not catalog specs, so they would be dropped from the OpenAI tool list. On voice, build_tools filters a hardcoded handler dict by `keep` (voice/tools.py:2918-2919) and no key starts with ext., so an ext.* tool has no handler and cannot be registered. The one paylink dispatch that does happen is hardcoded in _tool_get_customer_context (bot_tools.py:158-160) and never reads card.connectors.

**Trigger** — Bind or Unbind `paylink` on the collections card and publish. The compile report's effective_tools changes; the running bot's behaviour does not — the paylink prefetch fires either way, and no ext.* tool is ever offered on voice or text.

**Fix** — Decide which it is. If connector tools are meant to be callable, register ToolSpecs for bound ext.* names so openai_tools can render them and add an ext.* branch to voice/tools.py's dispatch; if they are meant to be internal prefetches only, make the paylink prefetch conditional on the card actually binding paylink and relabel the tab so it does not read as a capability grant.

#### `CONNECTORS-6` — A binding to a connector that is no longer approved disappears from the tab, leaving no way to unbind it and a permanently unpublishable card

**MAJOR** · bug · **closed** in `5435761` (pass 3)

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:925`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:985`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:1003`, `backend/agent_core/cards/compile.py:820`

**Mechanism** — The list renders only `connectorsQuery.data.filter(c => c.status === "approved")` (:925) and the Unbind control lives inside that map (:985-1006). A card whose connectors[] still names a connector that has since been de-approved (see CONNECTORS-3, or an explicit disable) has no row, so no Unbind button exists — while G10 keeps emitting {"not_approved": id} and failing the publish (compile.py:820-822). The only hint is the yellow prefix banner at :949-953, which shows the prefix string but names no connector and offers no action.

**Trigger** — Connector `bank-mcp` is bound to a card, then de-approved on Integrations. The author opens the Connectors tab, sees only paylink and lms, sees no binding, hits Publish and gets G10 fail naming a connector the tab will not show them.

**Fix** — Render bound-but-not-approved connectors as a separate section (from `card.connectors` minus the approved list) with a status lozenge and a working Unbind, so the offending binding is both visible and removable.

#### `CONNECTORS-11` — Snapshotted allow_prefixes outrank the registry forever, so narrowing a connector's prefixes revokes nothing from bound cards

MINOR · stale · prior: 2i.2 (still present)

**Files** — `backend/agent_core/connectors/persist.py:224`, `backend/agent_core/connectors/persist.py:233`, `backend/agent_core/cards/compile.py:805-809`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:1003`

**Mechanism** — Bind copies `conn.allowPrefixes` into the card (AgentCardPanels.tsx:1003). bound_tool_names then prefers the card's copy: `ref.allow_prefixes or ref.allowPrefixes or conn["allowPrefixes"]` (persist.py:224). Tightening the registry's prefix list — the natural way to revoke one remote tool without de-approving the whole connector — has no effect on any card that already snapshotted the wider list, and the tab's banner (:949-953) prints the stale card copy with no comparison against the registry.

**Trigger** — Ops narrows bank-mcp's allow_prefixes from ["ext.bank."] to ["ext.bank.read_"] to revoke a write tool. Every already-published card keeps binding the full ext.bank. set.

**Fix** — Intersect rather than override — `set(card_prefixes) & set(registry_prefixes)` — so a registry narrowing always applies; and show a staleness badge in the tab when the two lists differ.

#### `CONNECTORS-12` — Postgres array literals are built by string concatenation, so a comma in a slug or allowPrefix injects extra array elements — including an empty prefix that matches every remote tool

MINOR · security

**Files** — `backend/agent_core/connectors/persist.py:140`, `backend/agent_core/connectors/persist.py:180-181`, `backend/agent_core/connectors/persist.py:233`, `backend/agent_core/cards/clone.py:111-112`, `backend/agent_core/cards/compile.py:808`

**Mechanism** — prefixes default to [f"ext.{slug}."] (persist.py:140) and both arrays are serialised as `"{" + ",".join(prefixes) + "}"` (:180-181) rather than bound as a list. A slug or an explicit allowPrefixes entry containing a comma splits into extra elements. Nothing validates registry prefixes: attach_connector_to_card validates only card-side prefixes (clone.py:111-112) and G10 only checks `ref.allow_prefixes` (compile.py:808-809). An injected empty-string element makes `prefixed.startswith(p)` (persist.py:233) true for every cached remote tool name.

**Trigger** — POST /connectors with allowPrefixes=["ext.bank.,"] (or a slug containing a comma) writes {ext.bank.,""}; every tool in that connector's tools_cache then binds regardless of the intended prefix restriction.

**Fix** — Pass the lists as bound parameters (psycopg adapts a Python list to a text[]) instead of concatenating, and reject slugs/prefixes that do not match ^[a-z0-9._-]+$ in upsert_connector.

#### `CONNECTORS-14` — Three uncoordinated writers of prompt_versions.agent_card with no version guard; the connector-attach client is dead code

MINOR · code-organization

**Files** — `backend/main.py:2244-2258`, `backend/main.py:2126-2144`, `backend/main.py:3227-3231`, `backend/agent_core/cards/clone.py:113-126`, `backend/db_prompt_studio.py:1776-1779`, `Habibi/src/api/agent-studio.ts:839-846`, `Habibi/src/routes/prompt-studio.lazy.tsx:636-681`

**Mechanism** — POST /agent-studio/cards/{bot_id}/connectors read-modify-writes the latest draft's agentCard (clone.py:113-126); PATCH /agent-studio/cards/{bot_id} (main.py:2127-2145) and PATCH /prompt-versions/{id} (main.py:3228-3232) each replace the whole agent_card column (db_prompt_studio.py:1774-1777). None carries an etag/updated_at precondition, so it is last-write-wins. The Studio's 1200 ms autosave (routes/prompt-studio.lazy.tsx:646-657) re-PATCHes its in-memory card after every edit, so a connector attached out-of-band is silently reverted by the next keystroke. Additionally all three call restore_prompt_version_as_draft when no draft exists (clone.py:119, main.py:2137), so two concurrent calls can produce two drafts and the next publish 409s ambiguous_draft_to_publish (main.py:2244-2252). The frontend client for the attach endpoint, useAttachConnector (agent-studio.ts:840-845), is exported and called from nowhere.

**Trigger** — A script (or agent) POSTs /agent-studio/cards/kaia-v2-4/connectors while an author has the Studio open. 1.2 s after their next edit, the autosave PATCH writes the card without the new connector; the attach silently vanishes with no conflict and no message.

**Fix** — Give the draft an updated_at/version precondition and 409 on mismatch (the publish path already does this for the unique published index), or delete the attach endpoint and its unused client and keep PATCH as the single writer.

#### `CONNECTORS-15` — attach_connector_to_card binds an unapproved connector without complaint

MINOR · bug

**Files** — `backend/agent_core/cards/clone.py:104-112`, `backend/main.py:2244-2258`, `backend/agent_core/cards/compile.py:820-821`

**Mechanism** — The docstring says "Stamp an approved connector onto the latest draft card" but the function checks only existence (clone.py:107-109) and that prefixes start with "ext." (:111-112). Status is never read. The Studio tab filters to approved rows client-side (AgentCardPanels.tsx:925), so the API is looser than the only UI that uses it. G10 does catch it at publish (compile.py:820-822).

**Trigger** — POST /agent-studio/cards/{id}/connectors with a draft connector returns 200; the failure surfaces much later as a G10 not_approved at publish, and per CONNECTORS-6 the tab will not show the binding so it cannot be removed.

**Fix** — Raise ValueError("connector_not_approved") in attach_connector_to_card when conn_row["status"] != "approved" — _handle_write already maps it to a 409 — so the rejection lands where the operator made the mistake.

#### `CONNECTORS-16` — "Add connector" hardcodes dataClass to ["pii"] with no control, and G10 only checks the list is non-empty

MINOR · bug

**Files** — `Habibi/src/components/integrations/McpConsole.tsx:158`, `backend/agent_core/connectors/persist.py:141`, `backend/agent_core/connectors/persist.py:199-200`, `backend/agent_core/cards/compile.py:826-827`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:994-996`

**Mechanism** — The registration form sends `dataClass: ["pii"]` unconditionally (McpConsole.tsx:158) — there is no input for it. upsert_connector would default to ["pii"] anyway (persist.py:141). G10's only data-class test is `if not conn.get("dataClass")` (compile.py:826-827), so any non-empty value passes and the declared class is never compared against what the connector actually returns or against the card's own data_class.

**Trigger** — A core-banking connector returning balances and payment references is registered through the UI and permanently labelled pii-only. The Connectors tab renders "pii · healthy" (AgentCardPanels.tsx:995) and every downstream data-class review reads the wrong classification.

**Fix** — Add a multi-select for data class to the form (money / pii / marketing / internal), and have G10 compare the connector's declared classes against the binding card's identity.data_class rather than only checking non-emptiness.

#### `CONNECTORS-17` — ext.* names sit in the Tool Grant but in no Offer, so the only way one executes is a name the model was never shown — and that path skips skill gating

MINOR · security · **closed** in `by design` (pass 7)

**Files** — `backend/bot_tools.py:806-821`, `backend/agent_core/skills/intersect.py:117-123`, `backend/agent_core/skills/intersect.py:164`, `backend/bot_runtime.py:943`, `backend/bot_runtime.py:949`

**Mechanism** — effective_tools unions ext.* into the Grant (intersect.py:117-123) and bot_runtime assigns it to ctx.allowed_tools (bot_runtime.py:943). execute_tool's only guard is `name in ctx.allowed_tools` (bot_tools.py:806-808), and the ext.* branch (:810-823) runs before the handler lookup, before CATALOG.normalize, and outside the SKILL_GATED_TOOLS machinery. Because ext.* is stripped from every offer (intersect.py:164,168), a model can only emit such a name by hallucination or by prompt injection carrying the string — precisely the case the Offer⊆Grant design is supposed to make harmless, except here the Grant is strictly wider than anything ever offered.

**Trigger** — A borrower message containing `ext.paylink.get_status` induces the model to emit that tool call on a card that binds paylink; it executes against real payment_intents rows with no skill attached and no verification step in the path.

**Fix** — Either register ext.* names in the catalog so they are offered deliberately, or keep them out of ctx.allowed_tools until a pack activates them — the Grant should not be permanently wider than the union of reachable offers.

#### `CONNECTORS-2` — allowed_env is written, displayed and never enforced — a sandbox-only connector dispatches in production

MINOR · dead-config · DOWNGRADED

**Files** — `backend/agent_core/connectors/persist.py:184`, `backend/agent_core/connectors/persist.py:120`, `backend/agent_core/connectors/persist.py:238-289`, `backend/agent_core/cards/compile.py:804-829`, `Habibi/src/api/integrations.ts:126`, `backend/alembic/versions/20260815_0076_mcp_phase3.py:86-87`

**Mechanism** — upsert_connector defaults allowed_env to "sandbox" (persist.py:184) and _public surfaces it as allowedEnv (:120), but no runtime module reads it: dispatch (persist.py:238-289) checks status and circuit only, and G10 (compile.py:800-830) checks approved/https/dataClass/health and never env. A grep for allowed_env/allowedEnv across agent_core/, voice/, bot_tools.py, bot_runtime.py, sandbox_runtime.py and outbound.py returns no reader.

**Trigger** — Register a bank connector for sandbox testing (the form sends no env, so it lands as "sandbox"), approve it, bind it. Its tools dispatch identically on the production bot — the field that exists to prevent exactly this is inert.

**Fix** — Gate dispatch on env: read the deployment env once and return {"ok": False, "error": "connector_env_not_allowed"} when conn["allowedEnv"] is neither "both" nor the running env. Add the same check to G10 so the publish is blocked rather than the call failing at runtime.

#### `CONNECTORS-7` — Connector registration and approval write no audit row and require no admin role

MINOR · security · DOWNGRADED · **closed** in `340a707` (pass 7)

**Files** — `backend/main.py:2532-2537`, `backend/main.py:2549-2554`, `backend/main.py:2556-2561`, `backend/agent_core/connectors/persist.py:193-206`, `backend/agent_core/connectors/persist.py:132-190`, `backend/db.py:404-415`, `backend/authz.py:328-332`, `backend/main.py:532-577`, `backend/main.py:607-611`, `backend/main.py:839-848`

**Mechanism** — approve() (persist.py:193-206), upsert_connector() (:132-190) and cimd_connect() (:424-444) each run a bare UPDATE/INSERT and return; none calls db.record_activity (db.py:404-416), the convention used elsewhere (agent_core/authority/enact.py:245). The endpoints take no `Depends(require_admin)` — require_admin exists (main.py:843-852) and is used exactly once in the whole file, on /tts/voices/sync (main.py:3078). Approval is the control that decides whether a remote MCP server receives a vault bearer token and answers with payment data.

**Trigger** — Any authenticated non-admin actor POSTs /connectors/{id}/approve. The connector goes live; nothing records who approved it or when, and there is no change-log entry for an auditor to reconstruct.

**Fix** — Add `Depends(require_admin)` to POST /connectors, /approve and /cimd, and write a db.record_activity row (entity_type="connector") inside each write, carrying the actor from actor_context. The hash-chained agent change-log at main.py:2166-2180 is the model to follow.

#### `CONNECTORS-8` — Approve and Add-connector mutations have no error handler — a rejected write is rendered as nothing happening

MINOR · degradation-lie

**Files** — `Habibi/src/api/integrations.ts:302-311`, `Habibi/src/components/integrations/McpConsole.tsx:104`, `Habibi/src/components/integrations/McpConsole.tsx:152-160`, `backend/agent_core/connectors/persist.py:134-139`, `backend/agent_core/connectors/persist.py:196-200`

**Mechanism** — useConnectorMutations defines only onSuccess (integrations.ts:302-311). `mut.approve.mutate(r.id)` (McpConsole.tsx:104) swallows the rejection entirely; `void mut.upsert.mutateAsync(...).then(...)` (:152-160) leaves an unhandled rejection with no toast. The backend rejects both with real 409/422s — connector_data_class_required and connector_url_https_only from approve() (persist.py:198-200), connector_slug_required / connector_url_https_only from upsert (persist.py:135,139). The `cimd` button is the one that gets it right (:203-205).

**Trigger** — Operator clicks Approve on a connector with an empty data_class, or an http:// URL. The button does nothing visible, the row stays draft, no message appears; the operator retries or concludes the button is broken.

**Fix** — Give the mutations an onError that toasts the detail, or mirror the cimd button's `.catch((err) => toast.error(err.message))` on approve and upsert.

#### `CONNECTORS-9` — Connectors tab warns that connector tools count toward the voice cap; they cannot reach voice at all

MINOR · degradation-lie

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:949-953`, `backend/agent_core/cards/compile.py:687-692`, `backend/agent_core/skills/intersect.py:164`, `backend/agent_core/skills/intersect.py:168`, `backend/voice/tools.py:2918-2919`

**Mechanism** — The warning-styled banner reads "Activated connector tools still count toward the voice cap." G6 counts idle_offered_tools, which strips every ext.* name (intersect.py:164,168), and voice/tools.py:2918-2919 filters a hardcoded handler dict that contains no ext.* key, so no connector tool exists on voice under any activation.

**Trigger** — Author binds a connector, sees a warning telling them their 12-tool voice budget is at risk, and removes a real tool to make room for a cost that does not exist.

**Fix** — Replace the sentence with the truth: connector tools are text-channel-only and are never offered on voice, so they do not count against G6.

#### `CONNECTORS-10` — The tab promises "Compiler G10 checks HTTPS, data-class, and health" while MCP_CLIENT_ENABLED=false makes G10 skip entirely, and no screen reports that flag

trivial · degradation-lie · DOWNGRADED

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:944-945`, `Habibi/src/components/prompt-studio/PublishDialog.tsx:178`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:1023-1025`, `backend/agent_core/cards/compile.py:758-759`, `backend/agent_core/connectors/persist.py:254-255`, `backend/main.py:2646-2666`, `backend/.env.example:325`

**Mechanism** — compile.py:758-760 emits G10 "skipped — MCP client flag is off" when mcp_client_enabled() is false, and dispatch returns {"ok": False, "error": "mcp_client_disabled"} (persist.py:254-255). The shipped default is MCP_CLIENT_ENABLED=false (.env.example:325). GET /connectors still lists every row regardless of the flag (main.py:2537-2541), and GET /mcp/status reports httpEnabled, tasksEnabled and appsEnabled but not clientEnabled (main.py:2660-2670) — so neither the Studio tab nor the Integrations MCP panel can tell the operator the whole connector subsystem is switched off.

**Trigger** — On a default deployment an author binds connectors, sees a green G10 skipped (not fail), publishes, and believes the HTTPS/data-class/health checks ran. They did not, and no connector tool binds.

**Fix** — Add `clientEnabled: mcp_client_enabled()` to GET /mcp/status and surface it on both screens; when it is false, render a banner on the Connectors tab saying bindings are inert and G10 will skip rather than check.

#### `CONNECTORS-13` — allow_prefixes are a bind-time filter only — dispatch never checks them

trivial · bug · DOWNGRADED

**Files** — `backend/agent_core/connectors/persist.py:238-289`, `backend/agent_core/connectors/persist.py:257-265`, `backend/bot_tools.py:806-808`, `backend/bot_tools.py:158-160`

**Mechanism** — dispatch resolves the connector from `connector_id` or from `name.split(".")[1]` (persist.py:258-261), checks status and circuit, then calls _call_remote — it never asks whether `name` falls inside the connector's or the card's allow_prefixes. Enforcement lives only in bot_tools.execute_tool's `ctx.allowed_tools` membership check (bot_tools.py:806), which is derived from the Grant. Any caller that reaches dispatch directly — _tool_get_customer_context (bot_tools.py:158-160) does exactly that — bypasses the prefix restriction entirely.

**Trigger** — A future direct dispatch call (or a Grant computed from a different card than the one running) invokes an ext.* name outside the bound prefixes; the registry lets it through.

**Fix** — Move the prefix check into dispatch: resolve the connector, then refuse with {"ok": False, "error": "connector_prefix_not_bound"} unless `name` starts with one of the connector's allow_prefixes. Enforcement belongs at the point of execution, the way grant.may_execute does for catalog tools.

---

## Change log — the hash chain and what it covers

12 findings — 4 MAJOR, 7 MINOR, 1 trivial; 4 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-changelog.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `CHANGELOG-1` — The chain hashes the payload; the screen renders the unhashed columns — who, when and which agent are all forgeable under a green "Chain intact"

**MAJOR** · security · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/change_log.py:150`, `backend/agent_core/change_log.py:157`, `backend/agent_core/change_log.py:162`, `backend/agent_core/change_log.py:336`, `backend/agent_core/change_log.py:373`, `backend/sql/12_crosscutting.sql:23`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:98`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:120`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:129`, `backend/main.py:2177`

**Mechanism** — `_write` digests `body` = payload + action + botId + seq + prevHash (change_log.py:157). `actor_user_id` and `created_at` are NEVER in that body — they are only INSERT columns (change_log.py:162-177). `read_entries` then renders the COLUMNS for all four visible identity fields and explicitly drops the hashed copies: `"actorUserId": row["actor_user_id"]`, `"action": row["action"]`, `"botId": row["entity_id"]`, `"at": str(row["created_at"])`, with `**{k: v for k, v in payload.items() if k not in {"action", "botId"}}` (change_log.py:336-345). `verify_chain` rebuilds the digest from the payload alone (`body = {k: v for k, v in payload.items() if k != "entryHash"}`, change_log.py:373). So an UPDATE that rewrites actor_user_id, created_at, action or entity_id changes every field the operator reads while verify_chain still returns ok:true and ChangeLogTab.tsx:98 prints "Chain intact". The same hole opens without an attacker: `actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL` (sql/12_crosscutting.sql:23) — deleting a departed employee's users row nulls the "who" on every entry they ever wrote, and ChangeLogTab.tsx:129 renders `entry.actorUserId ?? "unknown"` beneath the green banner.

**Trigger** — `UPDATE audit_log SET actor_user_id='someone-else', created_at=now() WHERE id='AUD-…'` — or simply `DELETE FROM users WHERE id='priya-nair'`. Reload the tab: entries now name a different person (or "unknown") at a different time, banner still green, reason null.

**Fix** — Put the identity in the hash. In `_write`, add `"actorUserId": actor_user_id` and an explicit `"at": <ISO string generated in Python>` to `body` before `_digest(body)`, and have `read_entries` render `payload["actorUserId"]`, `payload["action"]`, `payload["botId"]` and `payload["at"]` rather than the columns (keep the columns for indexing/FK, and surface a column-vs-payload disagreement as its own chain reason). Drop `ON DELETE SET NULL` on audit_log.actor_user_id — an audit row must not be mutated by an unrelated delete.

#### `CHANGELOG-2` — Deleting the newest entries leaves the chain verifying clean — tail truncation is invisible, and verify_chain never checks seq contiguity

**MAJOR** · bug · **closed** in `fcbfefd` (pass 3)

**Files** — `backend/agent_core/change_log.py:349`, `backend/agent_core/change_log.py:363`, `backend/agent_core/change_log.py:369`, `backend/agent_core/change_log.py:379`, `backend/agent_core/change_log.py:120`, `backend/tests/test_agent_change_log.py:34`, `backend/tests/test_agent_change_log.py:186`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:6`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:207`

**Mechanism** — `verify_chain` walks oldest→newest and only reports a break when an entry's `prevHash` disagrees with its predecessor's `entryHash` (change_log.py:369-378). Removing the last N rows removes the only entries that could disagree: the remaining prefix still verifies genesis→head and returns `{ok: True, checked: N-k}`. `seq` is in the hashed body and is read for ordering (change_log.py:363) but never checked for contiguity, so the loop cannot notice that the walk ended at seq 7 when the last publish wrote seq 12. The UI states the opposite in three places: "a removed or rewritten entry shows up as a break rather than as an absence" (ChangeLogTab.tsx:207-209), the file header "a rewritten or deleted historical entry is visible rather than merely absent" (:6-8), and change_log.py:23-26 "Editing or deleting a historical row breaks every later link" — true only when a later link exists. The test suite pins only the oldest-row case: `first_entry = _entries(cloned_bot)[-1]["id"]` (test_agent_change_log.py:186), and `read_entries` is seq DESC (change_log.py:327), so `[-1]` is the OLDEST entry. No test deletes the head.

**Trigger** — Publish twice, then `DELETE FROM audit_log WHERE id = <newest entry id>`. `db.agent_change_log(bot)["chain"]` returns `{"ok": true, "reason": null}` and the tab renders the green "Chain intact — every link points at the entry before it" banner over a log that is missing its most recent publish.

**Fix** — Assert seq contiguity inside the existing walk — track an index and fail with a new reason `seq_gap` when `int(payload.get("seq") or 0) != i + 1`. That catches head, middle and tail deletion in one check and costs nothing (seq is already hashed, so it cannot be patched up without breaking entryHash). Optionally also persist a per-tenant head pointer (seq + entryHash) outside audit_log and compare it to the walked head.

#### `CHANGELOG-3` — Canary rollback swaps the live deployment and writes nothing to the chain — including the auto-rollback the publish entry promised

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/canary.py:136`, `backend/agent_core/canary.py:167`, `backend/agent_core/canary.py:420`, `backend/bot_worker.py:148`, `backend/main.py:3211`, `backend/main.py:3217`, `backend/db_prompt_studio.py:2411`, `Habibi/src/api/agent-studio.ts:870`, `Habibi/src/api/agent-studio.ts:202`, `Habibi/src/components/prompt-studio/ShipTab.tsx:77`

**Mechanism** — `rollback_experiment` retires the canary deployment and reactivates the baseline — `UPDATE bot_deployments SET status='retired' WHERE id=:canary` / `SET status='active' WHERE id=:baseline` (canary.py:166-174) — which is exactly what `rollback_bot_deployment` does, and that one records `change_log.record_rollback` (db_prompt_studio.py:2413-2422) with the comment "A rollback changes what callers hear exactly as much as a publish does, so it belongs in the same chain". `rollback_experiment` imports no change_log and writes no audit_log row. It has two callers: the wired button POST /bot-deployments/experiments/{id}/rollback (main.py:3222, agent-studio.ts:869-881, ShipTab.tsx:77) and the automatic sweep at canary.py:420, which fires on the very `auto_rollback` triggers the publish entry faithfully records (`rollout.autoRollback`, change_log.py:206-210). So the log names the trigger and never records it firing: after an automatic rollback the tab still shows the publish as the last event and the operator reads a card as live on a version it is no longer serving. The frontend even assumes the write happened — `useRollbackExperiment` onSuccess calls `invalidateAgentStudio(qc)`, which invalidates `["agent-change-log"]` (agent-studio.ts:202-204) and refetches an unchanged log.

**Trigger** — Publish at 40% with auto-rollback on error_rate, then click Roll back on the Ship tab (or let the sweep fire). bot_deployments flips to the baseline; GET /agent-studio/change-log returns the same entries it did before.

**Fix** — Give `rollback_experiment` the connection it already holds and call `change_log.record_rollback(conn, tenant_id=…, actor_user_id=db._actor_user_id() or 'system', entry_id=db._id('AUD'), bot_id=exp['bot_id'], to_deployment_id=baseline, from_deployment_id=canary, version_id=<baseline's prompt_version_id>)` inside the `engine.begin()` block at canary.py:149, and carry the `rollback_reason` into the payload so an automatic rollback is distinguishable from a manual one. Record it only when `baseline` is set, matching the `baselineRestored` distinction the function already draws.

#### `CHANGELOG-4` — The chain head is read without a tenant-scoped lock — two concurrent publishes of different bots fork the chain into a permanent, unclearable "tampered with" banner

**MAJOR** · bug · **closed** in `fcbfefd` (pass 3)

**Files** — `backend/agent_core/change_log.py:120`, `backend/agent_core/change_log.py:149`, `backend/db_prompt_studio.py:1869`, `backend/db_prompt_studio.py:2327`, `backend/db_prompt_studio.py:691`, `backend/db_prompt_studio.py:746`, `backend/sql/12_crosscutting.sql:20`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:64`

**Mechanism** — The chain is per TENANT (`_chain_head` filters on tenant_id + entity_type only, change_log.py:120-129), but the only serialization publish takes is per BOT: `pg_advisory_xact_lock(hashtext(:k))` with `k = f"{bot_id}:production"` (db_prompt_studio.py:1867-1871), and rollback uses the same bot-scoped key (:2327-2329). Two publishes for two different bots in one tenant therefore hold different locks, both read the same `(prev_hash, prev_seq)`, both compute `seq = prev_seq + 1` and `prevHash = H_n`, and both INSERT. `audit_log` has no unique constraint that would turn this into an IntegrityError — it is `id TEXT PRIMARY KEY` plus one index on tenant_id (sql/12_crosscutting.sql:20-30). `verify_chain` then walks A (prevHash H_n == expected, expected := H_A) and B (prevHash H_n != H_A) and returns `{ok: false, reason: "prev_hash_mismatch"}` forever. The tab renders that as "Chain BROKEN — this change log has been tampered with … Treat this as an integrity incident, not a display problem" (ChangeLogTab.tsx:67-76), and there is no repair path: the entries are append-only by design and every later entry chains off the fork.

**Trigger** — Two operators press Publish on two different cards in the same tenant within the same instant (or one operator publishes while the canary sweep at canary.py:420 is mid-transaction on another bot). Both succeed; every subsequent load of the change log reports tamper.

**Fix** — Serialize on the thing the chain is scoped to. Take `pg_advisory_xact_lock(hashtext(:tenant || ':agent-change-log'))` as the first statement of `_write` (change_log.py:149), so every appender of the tenant chain queues regardless of which bot it is publishing. Belt and braces: add `CREATE UNIQUE INDEX ON audit_log (tenant_id, entity_type, ((payload->>'seq')::bigint)) WHERE entity_type = 'bot'` so a lost race becomes a 409 retry rather than a permanent fork.

#### `CHANGELOG-10` — "What the compiler said at the time" is true only for publishes — rollback never recompiles, so it records no gate verdict at all

MINOR · doc-vs-code

**Files** — `backend/agent_core/change_log.py:238`, `backend/db_prompt_studio.py:2292`, `backend/db_prompt_studio.py:2411`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:149`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:207`

**Mechanism** — `record_rollback`'s payload is `{deploymentId, replacedDeploymentId, versionId}` — no gates and no hashes (change_log.py:238-242) — because `rollback_bot_deployment` never calls `compile_card`: it locks, validates the deployment is production and not already active, and inserts a fresh active row (db_prompt_studio.py:2292-2380; the only `compile_card` calls in the module are at :837 preview and :1908 publish). A rollback therefore re-activates a prompt version whose gates may no longer pass — a skill signature revoked since, a connector disapproved, an eval suite now failing — and the record says nothing about it. The tab's header promises "who changed what this agent says, and what the compiler said at the time" (ChangeLogTab.tsx:207) and the gate line is simply omitted when `gateCount === 0` (:149), so the absence reads as "no gates to report" rather than "no gates were run". Same for archive and restore, though those change the roster rather than the words.

**Trigger** — Roll back a deployment after a skill has been unsigned: the chain records the rollback with no gate map, and the tab shows a Rolled-back row with no compiler verdict beside it.

**Fix** — Either run `compile_card` against the deployment's prompt version inside `rollback_bot_deployment` and pass `report=` through to `record_rollback` (recording, not blocking — a rollback should not be gated), or make the UI say "no compile report — rollbacks re-ship a previously gated version without recompiling" instead of rendering nothing.

#### `CHANGELOG-11` — The "introspective" verb test asserts over a Python set and cannot see either of the two TypeScript maps it claims to protect

MINOR · test-gap · prior: 2n.2

**Files** — `backend/tests/test_agent_change_log.py:138`, `backend/tests/test_agent_change_log.py:147`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:35`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:121`, `Habibi/src/lib/agent-roster.ts:152`, `Habibi/src/lib/agent-roster.ts:159`

**Mechanism** — `test_every_lifecycle_action_has_a_verb_the_log_can_render` says "A new `record_*` writing an unlisted action fails here rather than rendering as a raw `agent.whatever` on the fleet index" (test_agent_change_log.py:130-134), but its assertion is `emitted == {"agent.publish", "agent.rollback", "agent.archive", "agent.restore"}` over `vars(change_log)` — a Python-side self-check. The two maps that actually decide whether an action renders as a verb are `ACTION_LABEL`/`ACTION_TONE` (ChangeLogTab.tsx:35-47) and `CHANGE_VERBS` (agent-roster.ts:152-157), in a different language and a different test runner. Adding `RESTORE`-style constant #5 keeps this test green while both frontends fall through to their raw-string fallbacks (ChangeLogTab.tsx:121 `?? entry.action`, agent-roster.ts:160) — which is exactly the failure prior finding 2n.2 recorded. The two TS maps are also duplicated: same four keys, different strings ("Rolled back" vs "rolled back"), with nothing tying them together.

**Trigger** — Add a fifth `record_*` action to change_log.py; the backend suite passes and the new action renders as a bare wire string in both the tab and the fleet panel.

**Fix** — Move the four action ids into one exported TS constant consumed by both maps, and add a vitest that asserts every key of the backend's action list has a label and a tone — or generate the TS list from the Python constants at build time. Reword the Python test's docstring so it stops claiming coverage it does not have.

#### `CHANGELOG-5` — In production the "who" column collapses to the ACTOR_USER_ID default, so every entry names one real, seeded human regardless of who acted

MINOR · bug · DOWNGRADED

**Files** — `backend/actor_context.py:60`, `backend/actor_context.py:37`, `backend/actor_context.py:229`, `backend/actor_context.py:63`, `Habibi/src/api/config.ts:46`, `Habibi/src/api/config.ts:49`, `backend/.env.example:193`, `backend/.env.example:195`, `backend/db_prompt_studio.py:2151`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:129`

**Mechanism** — `_allow_actor_header()` defaults to `not _app_is_prod()` (actor_context.py:60-73), so in production the console's `X-Actor-User-Id` is dropped and `get_actor_user_id()` falls through to `default_actor_user_id()` = `ACTOR_USER_ID` env, defaulting to the literal `"priya-nair"` (actor_context.py:36-37, db_core.py:124, .env.example:195) — a real seeded user whose existence is enforced at boot by `validate_configured_actors` (actor_context.py:161-177). `change_log.record_publish` stores `uid or "system"` from that resolution (db_prompt_studio.py:1903, :2151) and the tab prints it verbatim (ChangeLogTab.tsx:129). Unless API_KEY_MAP gives every operator their own key, the tamper-evident record attributes every publish, rollback, archive and restore to one named individual. The code itself flags the alternative as a known trade-off (WP-070, actor_context.py:64-67), but that comment is about dropping the header, not about the audit trail it feeds.

**Trigger** — Deploy with APP_ENV=prod and no per-user API_KEY_MAP, publish as any operator: the change log records priya-nair. Not demonstrated here because it depends on the deployed env; the resolution path is unambiguous in code.

**Fix** — Fail closed for the audit path specifically: when no actor can be resolved from an authenticated identity, write a synthetic id (e.g. `unattributed:<api-key-fingerprint>`) rather than a real users.id, so the log never puts a name on an action that name did not take. Longer term this is WP-070 / the Phase 5 JWT `sub` note at db_core.py:360.

#### `CHANGELOG-6` — Entries are silently capped at 50 with no truncation indicator, beside a chain count over every row in the tenant

MINOR · bug

**Files** — `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:177`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:224`, `Habibi/src/api/agent-studio.ts:977`, `backend/agent_core/change_log.py:316`, `backend/agent_core/change_log.py:328`, `backend/main.py:2173`

**Mechanism** — `useChangeLog(botId)` uses the default `limit = 50` (agent-studio.ts:977) and the tab never passes another (ChangeLogTab.tsx:177). `read_entries` clamps to `max(1, min(limit, 500))` and applies `ORDER BY seq DESC … LIMIT :n` (change_log.py:316, :327). A card with more than 50 lifecycle events therefore shows the newest 50 with no "showing 50 of N", no pagination and no limit control, directly beneath a banner reading "{chain.checked} entries verified across the tenant" — a number computed over every audit row and unrelated to what is listed. On the screen the file itself calls "the first artefact an auditor asks for", truncation renders as completeness.

**Trigger** — Any card with >50 publish/rollback/archive/restore entries: the 51st-oldest is unreachable from the UI and nothing on screen says so.

**Fix** — Have `read_entries` return a total count (a windowed `count(*) OVER ()` costs one column) and render "showing 50 of 137 for this card" with a Load more that raises `limit` toward the 500 ceiling; or paginate on `seq`.

#### `CHANGELOG-7` — The fleet Recent-changes panel feeds the raw Postgres timestamp to new Date() without the space→T fix the tab documents as necessary

MINOR · bug

**Files** — `Habibi/src/routes/agent-studio.index.tsx:304`, `Habibi/src/routes/agent-studio.index.tsx:366`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:54`, `backend/agent_core/change_log.py:342`, `backend/schemas.py:3548`

**Mechanism** — `read_entries` returns `"at": str(row["created_at"])` (change_log.py:342), i.e. Python's `str(datetime)` — `"2026-09-05 12:34:56.789012+00:00"`, space-separated and not ISO-8601. `ChangeLogTab.stamp()` handles exactly this: `Date.parse(at.replace(" ", "T"))` plus a `Number.isNaN` guard that falls back to printing the raw string (ChangeLogTab.tsx:54-59). The fleet panel does neither — it calls `new Date(latest.at).toLocaleDateString(...)` in the collapsed header (agent-studio.index.tsx:302-306) and `new Date(entry.at).toLocaleString(...)` in the expanded list (:365-372). V8 accepts the space form through a lenient fallback parser; engines that do not (Safari has historically returned Invalid Date for a space-separated datetime with an offset) render "Invalid Date" as the when of every audit row, and the collapsed header reads "priya-nair published kaia-v2-4 · Invalid Date".

**Trigger** — Open the Agent Studio fleet index in a browser whose Date parser rejects the non-ISO form. Not reproduced here (no browser run), but the asymmetry with the sibling component — which carries a comment explaining why the replace exists — is unambiguous in code.

**Fix** — Export `stamp`/a shared `parseLogTimestamp` from ChangeLogTab (or Habibi/src/lib) and use it in both places; better, normalise on the server — `row["created_at"].isoformat()` in `read_entries` — so no consumer has to know Postgres's repr.

#### `CHANGELOG-8` — Both empty states enumerate three of the four recorded verbs, dropping "restored" — the same omission the file header says was already fixed

MINOR · doc-vs-code · prior: 2n.2 (the maps half was fixed; the prose half was not)

**Files** — `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:88`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:219`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:39`, `backend/agent_core/change_log.py:45`, `backend/agent_core/change_log.py:275`, `Habibi/src/routes/agent-studio.index.tsx:307`, `Habibi/src/routes/agent-studio.index.tsx:340`

**Mechanism** — `agent.restore` is a recorded action (change_log.py:45, :275) and the tab's own header comment (ChangeLogTab.tsx:31-34) narrates adding it to ACTION_LABEL/ACTION_TONE (:39, :46) precisely because "the one screen an auditor reads" must not spell an action in wire format. Two prose strings on the same screen were not updated: the zero-chain banner says "No agent has been published, rolled back or archived in this tenant" (:88-90) and the empty-list state says "This card has never been published, rolled back or archived" (:219-221). The fleet panel gets it right in both of its equivalents — "nothing published, rolled back, archived or restored yet" (agent-studio.index.tsx:307, :340). So the tab's empty state asserts a scope narrower than what the endpoint actually records, on the screen whose job is to state its own scope precisely.

**Trigger** — Open the Change log tab for a card with no entries: the copy tells the reader restores are outside this record when they are inside it.

**Fix** — Add "or restored" to both strings, and pull the verb list from `Object.values(ACTION_LABEL)` so the maps and the prose cannot drift again.

#### `CHANGELOG-9` — The evidence is fetched and dropped — the six component digests, prevHash, seq, versionId and deploymentId are never rendered anywhere

MINOR · disconnected

**Files** — `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:117`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:166`, `Habibi/src/api/agent-studio.ts:899`, `backend/agent_core/change_log.py:197`, `backend/agent_core/change_log.py:213`, `backend/schemas.py:3559`

**Mechanism** — `record_publish` stores `hashes` — one SHA-256 per prompt/persona/voice/guardrails/flow/agent_card (change_log.py:197, :212) — plus `versionId`, `deploymentId`, `previousVersionId`, `seq` and `prevHash`. All are typed on `ChangeLogEntry` (agent-studio.ts:900-923) and returned by the API (schemas.py:3531-3562). `EntryRow` renders none of them: it shows the action lozenge, version labels, actor, timestamp, summary, the `changed` component NAMES, the rollout line, the gate line, and a 12-character prefix of `entryHash` (ChangeLogTab.tsx:117-171). So the screen tells the auditor WHICH components moved but never lets them check a digest against a `prompt_versions` row, and shows no `prevHash`, so the chain cannot be followed by hand from the artefact the doc calls the first thing an auditor asks for. The digests are the whole reason the module stores hashes instead of copies (change_log.py:18-21).

**Trigger** — Open any publish entry: `hashes` arrives over the wire on every request and is discarded by the renderer.

**Fix** — Render the digests behind a disclosure on each entry — component name, 12-char digest, and the full value in a title/copy affordance — and show `prevHash` beside `entryHash` so the link is checkable. At minimum surface them in the row's title attribute rather than dropping the response's most load-bearing field.

#### `CHANGELOG-12` — The tab's error state has no retry control, unlike the identical error state on the fleet panel

trivial · code-organization

**Files** — `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:177`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:187`, `Habibi/src/routes/agent-studio.index.tsx:229`, `Habibi/src/routes/agent-studio.index.tsx:311`

**Mechanism** — `ChangeLogTab` destructures only `{data, isPending, isError, error}` (ChangeLogTab.tsx:177) and its error branch renders a warning box with no action (:187-197), so recovering from a transient failure requires switching tabs or reloading. The fleet panel destructures `refetch`/`isFetching` and renders a Retry button beside the same failure (agent-studio.index.tsx:229, :311-321). Both error copies are honest — neither renders the failure as an empty log — so this is a control gap, not a lie.

**Trigger** — Change log request fails on the tab: the only affordance is to navigate away.

**Fix** — Pull `refetch`/`isFetching` off the hook and add the same Retry button the fleet panel uses.

---

## Guardrails tab — six toggles, two sliders, banned words

11 findings — 4 MAJOR, 4 MINOR, 3 trivial; 4 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-guardrails.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `GUARDRAILS-1` — WhatsApp files an RBI recording-disclosure violation on every bot turn while its own prompt forbids the disclosure

**MAJOR** · bug · **closed** in `fcbfefd` (pass 3)

**Files** — `backend/agent_core/guardrails.py:240-243`, `backend/agent_core/prompt.py:74-86`, `backend/agent_core/prompt.py:117-125`, `backend/bot_runtime.py:1273-1287`, `backend/voice/persist.py:618-664 (violation is idempotent per interaction+rule)`

**Mechanism** — build_system_prompt(channel='whatsapp') drops the recording rule and tells the model 'never state a call-recording disclosure' (prompt.py:75-86, 120-127). But bot_runtime.py:1272-1290 then calls persist.evaluate_and_flag_bot_turn with the same guardrails dict (alwaysDiscloseRecording=True on every seeded card), turn_index=turn_count (>=1 from the first reply, bot_runtime.py:709), no recording_disclosed argument and no channel gate; evaluate_guardrails flags 'missing-recording-disclosure' whenever turn_index >= _DISCLOSURE_DEADLINE_TURN and the reply lacks the disclosure (guardrails.py:250-253). persist.py:877-895 then writes an interaction flag, a medium live alert (flag is in _LIVE_ALERT_FLAGS :779) and an r-rec compliance violation (_FLAG_RULE_MAP :574), and live_qa.check_recording raises a critical finding with no channel gate (checks.py:185-197; compare check_hours :162 which does gate). The bot is penalised for obeying the platform.

**Trigger** — Any WhatsApp conversation handled by the bot with alwaysDiscloseRecording on (the default and every seeded card, seed_postgres.py:946-957): after the first reply, every turn adds an RBI-DISC-01 violation and a compliance alert to the interaction.

**Fix** — Gate the disclosure check on channel: either add a channel parameter to evaluate_guardrails and skip the alwaysDiscloseRecording block for _TEXT_CHANNELS (mirroring guardrail_rules), or in bot_runtime pass recording_disclosed=True / strip the flag for channel='whatsapp'; add the same channel guard to live_qa.check_recording.

#### `GUARDRAILS-2` — 'Hard-blocks' hints are true only in the sandbox; on voice and WhatsApp the rule is evaluated after the reply was spoken/sent

**MAJOR** · degradation-lie · **closed** in `fcbfefd` (pass 3)

**Files** — `Habibi/src/components/prompt-studio/GuardrailsPanel.tsx:28-45`, `backend/agent_core/guardrails.py:251-262`, `backend/sandbox_runtime.py:897-908`, `backend/voice/crm_sink.py:541-545`, `backend/voice/crm_sink.py:1527-1549`, `backend/bot_runtime.py:1099-1104`, `backend/bot_runtime.py:1273-1287`

**Mechanism** — The hints for neverQuoteRate ('Hard-blocks APR / % rate quotes in bot replies'), neverPromiseWaiver ('Hard-blocks waiver promises') and refusePoliticsReligion ('Hard-blocks political/religious digressions') describe should_halt, which only the sandbox calls (sandbox_runtime.py:907). On voice the evaluation runs in the CrmSink drain after the TTS has played (crm_sink.py:543 'The audio for this turn has already been spoken') and produces an alert plus a next-turn critic nudge. On WhatsApp the message is persisted and sent at bot_runtime.py:1098-1103 and evaluate_and_flag_bot_turn runs afterwards at :1272-1290; there is no pre-send evaluate/should_halt anywhere in bot_runtime.py (grep: no should_halt, no rate-quoted). 'politics-religion-engaged' additionally maps to no alert and no violation on live channels (persist.py:574-593). Operators reading the tab believe a rate quote cannot reach a customer; it can, and does, on both live channels.

**Trigger** — Publish a card with neverQuoteRate on; on a live call or WhatsApp thread the model quotes '18% p.a.' — the customer hears/reads it, and the operator sees a medium alert afterwards.

**Fix** — Either add a pre-send evaluate_guardrails + should_halt in bot_runtime (regenerate once, then fall back to a safe line) and reword the voice reality honestly, or change the three hints to 'Sandbox: halts the run. Live: flags the turn, alerts the floor and self-corrects on the next reply' so the tab stops promising a block it does not perform.

#### `GUARDRAILS-3` — maxSeconds ('Max call duration') has no consumer that ends a call; voice uses a fixed 10-minute cap and WhatsApp passes elapsed=0

**MAJOR** · dead-config · **closed** in `fcbfefd` (pass 3)

**Files** — `Habibi/src/components/prompt-studio/GuardrailsPanel.tsx:157-170`, `backend/agent_core/guardrails.py:227-229`, `backend/voice/persist.py:588-593`, `backend/bot_runtime.py:1280`

**Mechanism** — The slider stores 120-900s. On voice the only consumer is evaluate_guardrails producing a 'max-seconds' flag (guardrails.py:243-245); the flag is listed as a non-bot flag with no alert and no violation (persist.py:591-593) and nothing in voice/bot.py reads maxSeconds — the call is ended by _max_duration_watchdog on a hard-coded _MAX_CALL_DURATION_SECS = 600 (bot.py:164, 1743-1752). So 900 is silently 600 and 120 does nothing except feed the turn critic a bogus 'compliance rule' directive (see GUARDRAILS-5). On WhatsApp elapsed_seconds is always 0 (bot_runtime.py:1283) so the flag can never fire. Only the sandbox halts on it (guardrails.py:264).

**Trigger** — Set Max call duration to 2m and place a live call: it runs 10 minutes. Set it to 15m: it still ends at 10.

**Fix** — Read bundle['guardrails']['maxSeconds'] in bot.py and use min(maxSeconds, _MAX_CALL_DURATION_SECS) for the watchdog sleep, or drop the slider and show the fixed cap as read-only text.

#### `GUARDRAILS-4` — maxTurns slider range 4-40 is honest on no channel: sandbox caps at 3, WhatsApp at 12, voice never enforces

**MAJOR** · degradation-lie · **closed** in `fcbfefd` (pass 3)

**Files** — `Habibi/src/components/prompt-studio/GuardrailsPanel.tsx:145-156`, `backend/sandbox_runtime.py:365`, `backend/agent_core/guardrails.py:11-15`, `backend/agent_core/guardrails.py:221-225`, `backend/bot_runtime.py:859-864`

**Mechanism** — Sandbox: effective = min(_HARD_MAX_TURNS=SANDBOX_HARD_MAX_TURNS default 3, maxTurns) (sandbox_runtime.py:366, 711-716; guardrails.py:8-15), so with the slider floor at 4 the slider is never the binding value. WhatsApp: max_turns = min(maxTurns, BOT_HARD_MAX_TURNS=12) (bot_runtime.py:57-58, 859; .env.example:115), so 13-40 are silently 12. Voice: evaluate_and_flag_bot_turn passes hard_max_turns=50 (persist.py:828) and the resulting 'max-turns' flag is a non-bot flag (persist.py:591-593) with no alert; nothing in voice/bot.py, voice/tools.py or crm_sink.py reads maxTurns or acts on the flag, so a voice call never ends or escalates on turn count. The panel labels it 'Max turns per call'.

**Trigger** — Set Max turns to 30 and publish; a WhatsApp thread escalates to a human at turn 13, a sandbox run halts at exchange 3, a voice call runs indefinitely.

**Fix** — Surface the per-channel effective ceiling in the panel (return SANDBOX_HARD_MAX_TURNS / BOT_HARD_MAX_TURNS from an endpoint and render 'effective: min(x, cap)'), and on voice have crm_sink treat 'max-turns' as a graceful close/escalate trigger or remove 'per call' from the label.

#### `GUARDRAILS-11` — escalateAbuse / escalateLegal cannot switch escalation off on voice (or abuse on WhatsApp); the toggles only edit the prompt line and a flag

MINOR · dead-config

**Files** — `backend/voice/crm_sink.py:113`, `backend/voice/crm_sink.py:943-946`, `backend/agent_core/guardrails.py:208-219`, `backend/bot_runtime.py:815`, `backend/bot_runtime.py:823-831`

**Mechanism** — On voice, CrmSink's customer-turn tripwire calls detect_abuse / detect_legal unconditionally and escalates via _trigger_escalate → _live_escalate (crm_sink.py:943-945, 824-848; bot.py:1568-1577) without consulting self.guardrails. On WhatsApp hard_abuse = lexicon.is_abusive(customer_text) is unconditional (bot_runtime.py:815, 823-826); only the legal path is gated through evaluate_guardrails' auto-escalate (guardrails.py:217-223). Switching either toggle off therefore changes the '## Guardrails' prompt text and whether an 'auto-escalate' flag is written, but not whether the call/thread is handed to a human. This is the safe direction, but the switch labelled 'Escalate on abusive language' does not control escalation on abusive language.

**Trigger** — Turn both escalate toggles off (as seeded v1_0 does for abuse, seed_postgres.py:1029), publish, and have a caller swear: the call still escalates.

**Fix** — Either gate the tripwires on self.guardrails.get('escalateAbuse'/'escalateLegal') (and hard_abuse on guardrails in bot_runtime), or mark the two switches as 'always on for live channels; affects prompt wording and QA flags only'.

#### `GUARDRAILS-5` — Turn critic tells the live model it 'broke a compliance rule' for session-limit and caller-conduct flags

MINOR · bug

**Files** — `backend/voice/crm_sink.py:1571-1577`, `backend/agent_core/turn_critic.py:106-111`, `backend/agent_core/turn_critic.py:193-215`

**Mechanism** — crm_sink passes every flag returned by evaluate_and_flag_bot_turn to enqueue_critique (crm_sink.py:1560-1565). _guardrail_correction has no filter (turn_critic.py:172-186) and, for any non-omission flag, injects 'Your last reply broke a compliance rule (max-turns). Do not repeat that wording' (:207-212). persist.py:588-593 explicitly documents 'max-turns', 'max-seconds', 'auto-escalate' and 'politics-religion' as flags describing the caller or a session limit, not bot misconduct — so once maxTurns/maxSeconds is crossed on a voice call the model receives a high-severity correction about a mistake it did not make, spending one of the per-call correction budget slots (crm_sink.py:638-649).

**Trigger** — A voice call exceeds guardrails.maxSeconds (default 480s) or the customer says something abusive: the next bot turn is preceded by a bogus 'you broke a compliance rule' developer directive.

**Fix** — Filter persist._NON_BOT_FLAGS (export it) out of guardrail_flags before enqueue_critique, or inside _guardrail_correction.

#### `GUARDRAILS-6` — Sandbox judges the voice-only disclosure guardrail against a prompt that tells the model it is in a text chat and must not disclose

MINOR · degradation-lie

**Files** — `backend/agent_core/turn.py:75-80`, `backend/agent_core/prompt.py:117-125`, `backend/sandbox_runtime.py:755-760`, `backend/sandbox_runtime.py:897-908`

**Mechanism** — assemble_turn_messages calls build_system_prompt without a channel (turn.py:78-84), so the sandbox system message takes channel='text' (prompt.py:151), drops the disclosure rule and adds 'This is NOT a phone call ... never state a call-recording disclosure' (prompt.py:120-127). sandbox_runtime.py:897-906 nevertheless evaluates alwaysDiscloseRecording and reports 'missing-recording-disclosure' on every bot turn of any run whose persona openingBot does not itself disclose (recording_disclosed comes only from history, :755-761). The model cannot clear the flag without violating its prompt; test_the_flag_still_fires_when_nothing_ever_disclosed pins the behaviour. The Guardrails tab's 'Prompt rehearsal' therefore shows a compliance flag the voice runtime would not raise the same way (voice's greet_disclose node always discloses).

**Trigger** — Run a sandbox rehearsal with a persona whose openingBot lacks 'this call is recorded' (or edit a seeded one): every bot turn carries missing-recording-disclosure in guardrailFlags.

**Fix** — Pass channel='voice' through assemble_turn_messages for voice-card rehearsals (and use build_voice_system_prompt or guardrail_rules(channel='voice')), or skip the alwaysDiscloseRecording evaluation whenever the prompt was framed as a text channel.

#### `GUARDRAILS-7` — Lint 'recording_disclosure_unenforced' claims nothing on the card discloses recording, but inbound voice always discloses via the greet_disclose flow node

MINOR · degradation-lie

**Files** — `backend/prompt_lint.py:155-172`, `backend/voice/flows.py:210-244`, `backend/voice/flows.py:936-943`, `backend/voice/tools.py:579-613`

**Mechanism** — With alwaysDiscloseRecording off and no disclosure in the prompt, lint_prompt warns 'Nothing on this card discloses call recording' (prompt_lint.py:156-170; mock mirror prompt-studio.ts:791-796). On inbound voice the entry node is greet_disclose (flows.py:942), whose task message says 'say the call is recorded for quality and compliance' and requires the disclose_recording tool (flows.py:213-222, 243), which records the disclosure and injects the never-repeat note (tools.py:579-613) — none of it conditioned on the toggle. The toggle therefore does not remove the disclosure on inbound voice; only outbound (entry confirm_identity, flows.py:938-941) and text channels are actually silent. The lint's advice ('turn the guardrail on') is fine, its factual claim is not.

**Trigger** — Turn 'Always disclose recording' off on a card with no disclosure text: the tab warns nothing discloses, yet every inbound test call still opens with the disclosure.

**Fix** — Reword the finding to state what actually happens per channel ('inbound voice still discloses through the greeting node; outbound calls and WhatsApp will not'), or make greet_disclose read the toggle so the lint statement becomes true.

#### `GUARDRAILS-10` — Duration readout rounds half-minutes and out-of-range stored values are shown clamped while state keeps the raw number

trivial · a11y · prior: 2f

**Files** — `Habibi/src/components/prompt-studio/GuardrailsPanel.tsx:157-170`, `Habibi/src/components/prompt-studio/GuardrailsPanel.tsx:145-156`, `Habibi/src/components/prompt-studio/GuardrailsPanel.tsx:98-104`, `backend/db_prompt_studio.py:145-146`

**Mechanism** — The slider steps by 30s but the label prints Math.round(maxSeconds/60)+'m', so 150s reads '3m' and 450s reads '8m'. _prompt_guardrails coerces but does not clamp (db_prompt_studio.py:145-146), so a row holding maxTurns=3 or maxSeconds=60 renders the thumb at the slider minimum while the fingerprint/autosave keeps the raw value; nudging the thumb silently rewrites it into range. The word input also still has no aria-label (prior 2f trivia).

**Trigger** — Drag Max call duration to 2.5 minutes; or open a version whose guardrails were written outside the Studio.

**Fix** — Format as m:ss (or step by 60), and clamp in _prompt_guardrails or show the raw value in the readout.

#### `GUARDRAILS-8` — WhatsApp's own 'already disclosed' detector uses substring markers that diverge from the canonical disclosure regex

trivial · shape-mismatch · DOWNGRADED

**Files** — `backend/bot_runtime.py:258-266`, `backend/agent_core/guardrails.py:30-56`

**Mechanism** — _history_already_disclosed_recording matches 'recorded for quality', 'call is recorded', 'whatsapp is recorded', 'recorded for compliance' as bare substrings (bot_runtime.py:259) and drives the dialog-control line 'Recording disclosure was already given — do not repeat it' (:280-283). mentions_recording_disclosure (guardrails.py:31-46) is the declared canonical home ('so the authoring gate and the runtime detector cannot drift apart') and does not accept 'this WhatsApp is recorded' (subject must be call/conversation/chat) while it does accept wordings the substring list misses ('we are recording this conversation'). The same turn can be 'disclosed' for the prompt and 'missing' for the guardrail, or vice versa.

**Trigger** — Bot writes 'This WhatsApp chat is recorded for quality' — dialog block says disclosed; evaluate_guardrails (once GUARDRAILS-1 is fixed by threading recording_disclosed) would still count it as missing unless both use one predicate.

**Fix** — Replace the marker tuple with agent_core.guardrails.mentions_recording_disclosure and pass the result as recording_disclosed to evaluate_and_flag_bot_turn.

#### `GUARDRAILS-9` — Toggle hint 'Flags missing disclosure on turn 1' understates the check; the mock lint uses a looser 'record' substring than the server

trivial · doc-vs-code

**Files** — `Habibi/src/components/prompt-studio/GuardrailsPanel.tsx:40`, `backend/agent_core/guardrails.py:22`, `backend/agent_core/guardrails.py:240-243`, `Habibi/src/api/prompt-studio.ts:779`, `backend/prompt_lint.py:140`

**Mechanism** — The flag fires on every bot turn with turn_index >= 1 until a disclosure has been heard (guardrails.py:250-253), not 'on turn 1'. Separately the USE_MOCK lint path tests /record/i (prompt-studio.ts:779) while the server uses the strict mentions_recording_disclosure regex (prompt_lint.py:140), so mock mode reports 'duplicated' for a prompt containing 'record your promise to pay' that the real server would not flag.

**Trigger** — Read the hint; or run the UI in mock mode with such a prompt.

**Fix** — Change the hint to 'Flags every turn until the disclosure has been made' and reuse the same disclosure regex in the mock.

---

## Outbound tab — direction, missions, cadences, post-call, pools

21 findings — 5 MAJOR, 16 MINOR, 0 trivial; 5 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-outbound.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `OUTBOUND-01` — 'Closes the case' and 'Partly worked' are authored, gated, published — and the Closer never reads them

**MAJOR** · dead-config · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:536-552`, `backend/call_closer.py:99`, `backend/call_closer.py:102`, `backend/call_closer.py:949`, `backend/mission.py:314`, `backend/agent_core/cards/schema.py:237`, `backend/agent_core/cards/schema.py:238`

**Mechanism** — MissionEditor writes objective.success and objective.partial through two CodeGrids. mission.build copies success onto the mission envelope (mission.py:314) and nothing ever reads mission['success']. The Closer computes the outcome with `success = SUCCESS_BY_OBJECTIVE.get(objective, frozenset({'ptp_captured','paid_in_call'}))` (call_closer.py:949) — a module constant — and the comment directly above that constant claims the opposite: "``CardObjective.success`` overrides them per published card, which is the point of authoring missions rather than hardcoding them" (call_closer.py:99-101). `objective.partial` has no reader at all: agent_core/cards/schema.py:238 is its only backend occurrence — no gate, no runtime, no analytics. `objective_met` feeds call_outcomes.objective_met, which drives the Reach pane's 'resolved' column via GET /outbound/reasons (main.py:4954-4958) and treatment attribution.

**Trigger** — Author opens a mission, unticks `part_payment_agreed` from 'Closes the case' on dpd_reminder (or ticks it into 'Partly worked'), publishes green. Every subsequent dpd_reminder that ends in part_payment_agreed is still recorded objective_met=true, and the Reach pane counts it as resolved. The four first-party defaults happen to mirror SUCCESS_BY_OBJECTIVE exactly (agent_core/cards/defaults.py:200-232), which is why nobody has noticed.

**Fix** — In call_closer.py:949, resolve the card first — `mission.card_for_bot(attempt['bot_id']).outbound.objective(objective).success` — and fall back to SUCCESS_BY_OBJECTIVE only when the card declares no mission. Either implement `partial` (a third axis on call_outcomes, or at minimum exclude partials from objective_met) or delete the field, the CodeGrid and its 'kept apart so a partial is not scored as a win' hint.

#### `OUTBOUND-02` — Cadence retries dial as DEFAULT_BOT_ID, so every attempt after the first runs the wrong card

**MAJOR** · disconnected · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/cadence.py:418`, `backend/cadence.py:419`, `backend/cadence.py:429`, `backend/mission.py:461`, `backend/mission.py:474`, `backend/call_closer.py:753`, `backend/tests/test_outbound_studio_bindings.py:36`

**Mechanism** — cadence.process_one hardcodes `bot_id = dbmod.DEFAULT_BOT_ID` (cadence.py:418) and builds the retry's mission from that bot's card (cadence.py:419), then stamps it onto the attempt (cadence.py:429 reserve(bot_id=bot_id)). mission.resolve_outbound_bot_id exists precisely for this and its own docstring says "Hard-coding ``DEFAULT_BOT_ID`` at the call site is how a card authored in Agent Studio still rang as ``kaia-v2-4``" (mission.py:461-462) — cadence.py is the one caller that still does it. The case row (call_cadence_state) carries no bot_id, so the authoring bot is lost the moment the first attempt closes. The damage compounds: the retry carries the default card's entry_node, max_duration_sec, allowed_offers, authority_profile and voicemail policy, and because attempt.bot_id is now the default bot, call_closer._post_call_policy (call_closer.py:669-671) and _advance_cadence (call_closer.py:753) then read the *default* card's post_call rules and retry ladder for the rest of the ladder.

**Trigger** — Author a card on any bot other than kaia-v2-4, give it a mission with its own entry node and a 5-attempt ladder, publish, and run a campaign against it. Attempt 1 dials with the authored mission (campaigns.py:526 honours run.bot_id). Attempt 2 onward dials as kaia-v2-4 with kaia's missions, kaia's voicemail policy and kaia's 3-attempt ceiling.

**Fix** — Carry the bot through the ladder: add bot_id to call_cadence_state (or read it off the case's last attempt) and call `mission.resolve_outbound_bot_id(explicit=case_bot_id, objective=objective)` at cadence.py:418. Extend test_outbound_studio_bindings.py's DEFAULT_BOT_ID assertions (:36-51) to cover cadence.py, which they currently skip.

#### `OUTBOUND-03` — The caller-ID pool the card names is honoured by campaigns only — engine dials and retries ignore it

**MAJOR** · disconnected · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/campaigns.py:539`, `backend/campaigns.py:549`, `backend/cadence.py:429`, `backend/agent_core/treatment/enact.py:386`, `backend/outbound.py:677-696`, `backend/outbound.py:1062`, `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:277-303`

**Mechanism** — outbound.place selects a from-number only when the attempt row carries `numberPool` (outbound.py:677-690 → pick_number outbound.py:1062), and reserve only sets it when the caller passes `number_pool=`. campaigns.process_one is the sole caller that does (campaigns.py:539,549). cadence.process_one's reserve (cadence.py:429-441) and both treatment reserves (enact.py:380, enact.py:442) omit the argument entirely, so those dials fall back to the deployment's single TWILIO_PHONE_NUMBER. pick_number's own docstring names the reason this matters: "BFSI service and transactional calls must originate from the 1600 series" (outbound.py:1066-1068).

**Trigger** — Pick a service_1600 pool in DirectionPanel's 'Caller-ID pool' select (which also adopts pool_kind, OutboundCardEditor.tsx:286-294) and publish. Campaign dials originate from the 1600 series; every treatment-engine dial and every cadence retry for the same borrower originates from the generic number — the same conversation, two caller IDs, one of them off the series the tenant registered for it.

**Fix** — Resolve the pool where the card is resolved: pass `number_pool=getattr(card.outbound,'number_pool',None)` at cadence.py:429 and enact.py:380/442. Better, have outbound.reserve derive it from bot_id when the caller does not pass one, so a new dial path cannot silently opt out.

#### `OUTBOUND-04` — `direction` is not a kill switch: a card switched to inbound keeps dialling, including mid-campaign

**MAJOR** · disconnected · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `Habibi/src/components/prompt-studio/OutboundTab.tsx:455`, `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:255`, `backend/campaigns.py:527`, `backend/campaigns.py:540`, `backend/agent_core/treatment/enact.py:424`, `backend/agent_core/cards/schema.py:357`, `backend/voice/bot.py:553-556`

**Mechanism** — The tab tells the operator "inbound only — this agent never dials" (OutboundTab.tsx:455) and the DirectionPanel repeats "never dials" (OutboundCardEditor.tsx:255). Nothing on the dial path enforces it. campaigns.process_one resolves the card (campaigns.py:527) and then never consults `card.outbound.dials` or `card.outbound.objective(objective)` before reserving and placing. enact._dial_bot does check, but fail-open: `if card is not None and card.outbound.dials and card.outbound.objectives:` (enact.py:368) — an inbound-only card fails the second conjunct and the mission check is skipped entirely, so the dial proceeds. Because card_for_bot re-reads the *currently active* production deployment on every dial (mission.py:498-515), the answer to 'does changing direction on a live card affect an in-flight campaign' is: it changes the mission envelope but does not stop the run. With the mission removed, mission.build gets objective_spec=None and produces entryNode '' (mission.py:302), so voice/bot.py:555 never sets the entry node and the call falls back to the inbound door — the VS-4D8667B522 failure compile.py:288-292 says the compiler exists to refuse.

**Trigger** — A campaign is running. An operator flips Direction to `inbound` (or deletes the mission) and publishes to stop the calls. The run keeps dialling; the next attempt opens on the inbound greeting instead of the mission's entry node.

**Fix** — Add the same guard campaigns already has the card for: at campaigns.py:527, skip/pause the run when `not card.outbound.dials` or `card.outbound.objective(run['objective']) is None`, marking the target with a reason rather than dialling. Make enact.py:368 fail closed — `if card is not None and not card.outbound.dials: raise NoExecutor('card_is_inbound_only')`. Until then the tab must not promise 'never dials'.

#### `OUTBOUND-06` — Five live panes render a failed query as an authoritative zero or empty state

**MAJOR** · degradation-lie · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `Habibi/src/components/prompt-studio/OutboundTab.tsx:626`, `Habibi/src/components/prompt-studio/OutboundTab.tsx:642`, `Habibi/src/components/prompt-studio/OutboundTab.tsx:517`, `Habibi/src/components/prompt-studio/OutboundTab.tsx:556`, `Habibi/src/components/prompt-studio/OutboundTab.tsx:662`, `Habibi/src/components/prompt-studio/OutboundTab.tsx:710`, `Habibi/src/components/prompt-studio/NumberPoolTable.tsx:112-131`

**Mechanism** — None of useReachStats, useCadenceCases, useCampaigns, useNonpaymentReasons or useObligations has an isError branch. On failure: the Reach tiles print `${stats.data?.answered ?? 0} of ${stats.data?.attempts ?? 0} dials` and `Blocked by policy: {String(stats.data?.suppressed ?? 0)}` (OutboundTab.tsx:626,642) — i.e. an asserted zero for the compliance figure; Cadence prints the composed empty state 'No open ladders — A ladder opens when a call ends without resolving the case…' (:515-521); Campaign runs prints 'No runs. A run groups missions that were already authorised…' with no loading state at all, so it also flashes that during every load (:554-557); Reasons prints 'Nothing captured yet' (:660-665); Obligations prints 'Nothing outstanding. …an agent that keeps its promises is the whole trust proposition' (:708-713). Each of these is a business claim, not a placeholder. NumberPoolTable in the same pane does it correctly (NumberPoolTable.tsx:117-127: 'Caller-ID pool health unavailable — cannot confirm which numbers are still dialling').

**Trigger** — The API is down, the session has expired, or /outbound/obligations 500s on one bad row. The operator reads 'Nothing outstanding' and 'Blocked by policy 0' and concludes the agent owes nobody a callback and the contact gate refused nothing this fortnight.

**Fix** — Give each of the five an isError branch modelled on NumberPoolTable.tsx:117-127, and gate the empty copy on `isSuccess`. Add an isLoading branch to the campaign runs list.

#### `OUTBOUND-05` — Campaign status changes are not tenant-scoped — any run id can be started, paused or cancelled cross-tenant

MINOR · security · DOWNGRADED

**Files** — `backend/main.py:5140`, `backend/campaigns.py:373-392`, `backend/campaigns.py:153-190`, `backend/db_core.py:127-138`, `backend/tenant_context.py:75-77`, `backend/rls.py:18-22`

**Mechanism** — Every other campaign read filters on tenant (list: main.py:4993; get: main.py:5150 'AND tenant_id = :t'; add_targets_from_selector: campaigns.py:363). set_campaign_status does not: main.py:5142 calls `campaigns.set_status(conn, run_id, status)` and the UPDATE is `WHERE id = :id` with no tenant predicate (campaigns.py:386). This is the exact call the Outbound tab's Start/Pause button makes (OutboundTab.tsx:594). The sibling POST /outbound/campaigns/{run_id}/targets has the same shape: add_targets inserts `FROM customers c WHERE c.id = :cid` and updates campaign_runs `WHERE id = :run` (campaigns.py:172,182) with no tenant check on either the run or the customer, so a borrower from one tenant can be attached to another tenant's run.

**Trigger** — An authenticated user of tenant B posts {status:'running'} to /outbound/campaigns/CR-XXXXXXXXXX/status for a run id belonging to tenant A — a cancelled or paused run resumes and starts ringing tenant A's borrowers. Run ids are `CR-` + 10 uppercase hex (campaigns.py:70), and they leak through the shared attempt ledger.

**Fix** — Thread tenant_id into campaigns.set_status and add `AND tenant_id = :t` to the UPDATE at campaigns.py:386, returning 404 when it matches nothing. Do the same for add_targets (both the run update and the customer SELECT) and for the /targets endpoint.

#### `OUTBOUND-07` — cadence.time_of_day is a published field with no reader anywhere

MINOR · dead-config

**Files** — `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:842-858`, `backend/agent_core/cards/schema.py:207`, `backend/agent_core/cards/schema.py:292`, `backend/main.py:5284`, `backend/cadence.py:241`

**Mechanism** — CadenceEditor offers a 'Time of day' select over vocab.timeOfDay (engine|fixed|spread), which /outbound/card-vocabulary derives from the schema Literal (main.py:5294). schema.py:292 is the only backend occurrence of the field name outside that endpoint: no compile gate reads it, and cadence.py schedules purely on backoff_for (cadence.py:242) with no time-of-day component. `engine` implies the decision engine will place the retry in a scored hour; nothing does.

**Trigger** — Set a ladder to 'spread' and publish. The retry lands at now + backoff_hours exactly as before, at whatever hour that is (bounded only by contact_policy's statutory window at dial time).

**Fix** — Either implement it in cadence.process_one's scheduling (cadence.py:242 nxt computation) or remove time_of_day from CardCadence, the vocabulary endpoint and the editor. A published field that does nothing is the failure test_outbound_conduct.py:10-12 was written about.

#### `OUTBOUND-08` — 'When the attempts run out' escalates to nobody — escalate_to has no runtime caller and the 'escalated' ladder state is never written

MINOR · dead-config

**Files** — `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:860-887`, `backend/cadence.py:600-604`, `backend/cadence.py:57`, `backend/cadence.py:232-239`, `backend/agent_core/cards/schema.py:291`, `Habibi/src/api/outbound.ts:135`, `backend/agent_core/cards/defaults.py:244`

**Mechanism** — cadence.escalation_target (cadence.py:600-604) is the only reader of CardCadence.escalate_to and it has no callers anywhere in the backend. STATE_ESCALATED is defined (cadence.py:57) and never assigned; an exhausted ladder is written STATE_EXHAUSTED with reason 'max_attempts' (cadence.py:233) and stops. The frontend's CadenceCase type still lists 'escalated' as a reachable state (outbound.ts:135). The first-party collections card ships escalate_to='human' (defaults.py:244), so the panel shows an escalation configured on every seeded card that will never fire. Only publish gate G-OB7 (compile.py:414-430) reads the value.

**Trigger** — Set 'When the attempts run out' to a handoff target, publish green (G-OB7 passes), and let a ladder exhaust. The case ends 'exhausted', nothing is handed to anyone, and the Cadence pane shows the stopped_reason 'max_attempts' rather than the escalation the operator configured.

**Fix** — Either call escalation_target from the exhaustion branch (cadence.py:232-241) and write STATE_ESCALATED plus whatever handoff/treatment row it implies, or delete escalate_to, escalation_target, STATE_ESCALATED and the editor control. The cadence module docstring (cadence.py:15-17) says followthrough.py owns this decision — if that is the intent, the control belongs there, not on the card.

#### `OUTBOUND-09` — 'Per borrower per day' bounds nothing at runtime; the hint implies it does

MINOR · dead-config

**Files** — `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:808-820`, `backend/agent_core/cards/schema.py:265`, `backend/agent_core/cards/compile.py:350`, `backend/cadence.py:260`, `Habibi/src/api/agent-card.ts:234-236`

**Mechanism** — CardCadence.per_day is read in exactly two places: publish gate G-OB3 (compile.py:350) and the _DefaultCadence stub (cadence.py:260, never consulted for pacing). cadence.on_outcome and cadence.process_one schedule on backoff_hours and max_attempts only; the per-day ceiling that actually applies is contact_policy's, checked at dial time (contact_policy.py:919-954), and the card cannot lower it. The TS doc comment restates the false claim: "Bounded again at runtime by contact_policy's own cap, which a card can only ever lower" (agent-card.ts:238-240) — the card never enters that computation.

**Trigger** — Set per_day=1 on a ladder with backoff_hours=[2,3] and publish. Nothing enforces one contact a day; contact_policy's own cap (default 3) is the only limit.

**Fix** — Either enforce it — pass the card's per_day into contact_policy.admit as a per-mission narrowing, or refuse to schedule a retry that would be the (per_day+1)th today at cadence.py:242 — or drop the field and G-OB3 with it. Fix the hint text at OutboundCardEditor.tsx:822-826 either way.

#### `OUTBOUND-10` — The borrower cap the editor quotes and G-OB3 enforces ignores published policy rules, so both can be wrong in the permissive direction

MINOR · bug

**Files** — `backend/main.py:5301`, `backend/agent_core/cards/compile.py:346-350`, `backend/contact_policy.py:91-101`, `backend/contact_policy.py:918-919`, `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:808-820`

**Mechanism** — /outbound/card-vocabulary returns `contact_policy.daily_cap()` with no rules argument (main.py:5312), and G-OB3 does the same (compile.py:348). daily_cap(None) returns the env value only (contact_policy.py:99-101). The enforcing path resolves the tenant's published rule set first — `rules = _rules_for(...); cap = daily_cap(rules)` (contact_policy.py:918-919) — and a rule set may lower it. So the editor's hint 'borrower cap is 3/day' and a green G-OB3 can both be quoting a cap that is not the one the dialler will apply.

**Trigger** — A tenant publishes a policy rule set with daily_cap=1 while CONTACT_DAILY_CAP=3. CadenceEditor shows 'borrower cap is 3/day', per_day=3 passes G-OB3, and every second contact that day is vetoed at dial time — precisely the 'arithmetically guaranteed to be vetoed' case the gate's own comment (compile.py:337-345) says it exists to catch.

**Fix** — Resolve the tenant's rules in both places: open a connection and call `contact_policy.daily_cap(policy_rules.resolve(conn, tenant_id=...))` in the vocabulary endpoint and in _outbound_gates, or add a helper that takes tenant_id so the two cannot diverge.

#### `OUTBOUND-11` — 'Message length' on a voicemail is authored, transported and never applied

MINOR · dead-config

**Files** — `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:617-625`, `backend/agent_core/cards/schema.py:223`, `backend/mission.py:346`, `backend/voice/amd.py:164`, `backend/voice/amd.py:294-306`

**Mechanism** — VoicemailPolicy.max_sec (5-60) is copied into the mission envelope (mission.py:346) and into the runtime policy dict as 'maxSec' (amd.py:164). Neither the handler that decides to speak (amd.py:294-306) nor voicemail_script (amd.py:75-130) takes a length bound — only `leave` and `includeGrievance` are consumed. `maxSec`/`max_sec` appears nowhere else in the backend.

**Trigger** — Set Message length to 5 seconds and publish. The full templated voicemail plays regardless.

**Fix** — Either bound the script — truncate or select a shorter template in voicemail_script using policy['maxSec'], or cap the TTS playback — or delete the field, the schema bound and the NumberField.

#### `OUTBOUND-12` — A card the compiler could not parse is reported as 'outbound gates skipped — inbound only'

MINOR · degradation-lie

**Files** — `Habibi/src/components/prompt-studio/OutboundTab.tsx:107-109`, `backend/agent_core/cards/compile.py:263-264`, `backend/agent_core/cards/compile.py:267-268`, `backend/agent_core/cards/compile.py:554-568`, `backend/agent_core/cards/compile.py:921-929`

**Mechanism** — compile_card leaves `card = None` when G0's model_validate raises (compile.py:558-567) and still calls _outbound_gates(None, ...) (compile.py:919), which emits G-OB1 skipped with detail 'no card' (compile.py:264) — the same status the genuinely inbound-only case emits with detail 'inbound-only card' (compile.py:268). OutboundGates keys only on status: `const skipped = gates.every(g => g.status === 'skipped')` and then asserts 'outbound gates skipped — inbound only' (OutboundTab.tsx:108-109), discarding the detail that distinguishes the two.

**Trigger** — Any edit anywhere in the studio that makes the draft card fail AgentCard validation (an unknown key, an out-of-range value written by another tab or a hand-edited card) while `outbound.direction` is 'outbound'. The Outbound tab then reassures the author that this agent does not dial, on a card that declares it does.

**Fix** — Read the detail: render 'card is not valid — see G0' when the single skipped G-OB1 carries detail 'no card', and keep the inbound-only copy for detail 'inbound-only card'.

#### `OUTBOUND-13` — 'N outbound gates pass' counts the skipped eval gate as a pass

MINOR · degradation-lie

**Files** — `Habibi/src/components/prompt-studio/OutboundTab.tsx:105`, `Habibi/src/components/prompt-studio/OutboundTab.tsx:110-112`, `backend/agent_core/cards/compile.py:963-967`, `backend/agent_core/cards/compile.py:461-465`

**Mechanism** — The lozenge filters on the G-OB prefix (OutboundTab.tsx:105), which picks up G-OB9, then reports `{gates.length} outbound gates pass` whenever no gate has status 'fail' (OutboundTab.tsx:110-112). G-OB9 is skipped whenever OUTBOUND_EVAL_GATE is off or 'outbound' is not in card.eval.require (compile.py:453-464) — the default state. The success lozenge therefore says nine gates pass when eight passed and the outbound eval gate was not evaluated at all. This is the mirror image of the Evals tab's 'skipped shown as failed' problem: here skipped is shown as passing, on the gate that checks whether the outbound suite ever ran.

**Trigger** — Open the Outbound tab on any authored outbound card with the outbound eval gate flag off. Lozenge reads '9 outbound gates pass'.

**Fix** — Count and label the three statuses separately, e.g. '8 pass · 1 skipped', and never fold skipped into the pass count.

#### `OUTBOUND-14` — Start/Pause on a campaign run fails silently — including the 409s that mean outbound is switched off

MINOR · bug

**Files** — `Habibi/src/components/prompt-studio/OutboundTab.tsx:585-604`, `Habibi/src/api/outbound.ts:489-497`, `backend/main.py:5131-5139`, `backend/platform_switches.py:141-143`

**Mechanism** — useSetCampaignStatus has no error surface and the Campaign runs list renders none — only `setStatus.isPending` is consulted (OutboundTab.tsx:591). The endpoint returns 409 'campaign_runtime_disabled' when CAMPAIGN_RUNTIME_ENABLED is off and 409 'outbound_disabled' when the master switch is off (main.py:5131-5140), and platform_switches.outbound_enabled is "Off by default, in every deployment" (platform_switches.py:133-135). Contrast the same file's CohortBuilder, which does render preview.isError (:327-331) and create.isError (:362-366).

**Trigger** — Two ways round. (a) Fresh deployment, master switch off: the operator clicks Start on their first run, nothing happens, no message, and the tab gives no indication anywhere that outbound is disabled. (b) The Pause click fails (409/500/expired session): the button re-enables, no error appears, and the run keeps dialling — on the one panel in the product whose buttons ring real phones.

**Fix** — Render setStatus.isError beside the run the way create.isError is rendered at :362-366, mapping 'outbound_disabled' and 'campaign_runtime_disabled' to plain sentences. Better still, surface the master switch state in the Campaign runs header so the Start button is not offered against a disabled dialler.

#### `OUTBOUND-15` — Campaign progress hides skipped targets, so a completed run reads as one that stopped early

MINOR · bug

**Files** — `Habibi/src/components/prompt-studio/OutboundTab.tsx:577`, `Habibi/src/api/outbound.ts:127-129`, `backend/main.py:4986-4993`, `backend/campaigns.py:641-648`, `backend/campaigns.py:523`, `backend/campaigns.py:576-583`

**Mechanism** — targets_done is incremented only when a dial is actually placed (campaigns.py:626-631). A target skipped for 'no_phone_on_file' (campaigns.py:523) or a permanent contact-policy refusal — opted out, DND, customer gone (campaigns.py:576-583) — is marked 'skipped' and never counted. _finish_if_drained then finishes the run once nothing is pending or dialing (campaigns.py:653-668). The list renders only `{r.targets_done}/{r.targets_total}` (OutboundTab.tsx:577), even though the endpoint returns pending/done/skipped per run (main.py:5000-5007) and the TS type carries them (outbound.ts:120-122), both unused.

**Trigger** — A 500-borrower run where 180 are opted out finishes with status 'finished' and the line '320/500' — indistinguishable from a run that was cancelled two-thirds through, and it hides the compliance-relevant fact that 180 were suppressed.

**Fix** — Render the three counts the API already returns: `{done} called · {skipped} skipped · {pending} waiting of {targets_total}`.

#### `OUTBOUND-16` — The mission Cadence select always offers 'default', which silently swaps the authored ladder for the built-in

MINOR · bug

**Files** — `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:495-512`, `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:785-787`, `backend/agent_core/cards/compile.py:429-440`, `backend/agent_core/cards/schema.py:346-355`, `backend/agent_core/cards/defaults.py:236-245`

**Mechanism** — MissionEditor hardcodes `<option value="default">default</option>` above the card's own ladder names (OutboundCardEditor.tsx:504). G-OB8 explicitly exempts the literal 'default' from its existence check — `if objective.cadence not in defined and objective.cadence != "default"` (compile.py:434-436) — so choosing it publishes green even when the card defines no cadence with that name. cadence_for then returns a bare `CardCadence()` (schema.py:355), i.e. 3 attempts / 1 per day / 4-24-72 / the schema's default retry_on and stop_on. The first-party card names its ladder 'collections' (defaults.py:238), so this is one click away on every seeded card, and nothing in the UI or the compile report says the authored ladder stopped applying.

**Trigger** — On a card whose only ladder is 'collections' (5 attempts, custom stop_on), open a mission's Cadence select and pick 'default'. Publish is green; every retry now walks the built-in 3-attempt ladder instead.

**Fix** — Only offer 'default' when the card actually defines a cadence named 'default'; otherwise show a warning lozenge on the mission ('falls back to the built-in ladder') the way CadencesEditor's empty state already explains it (OutboundCardEditor.tsx:952-957).

#### `OUTBOUND-17` — Renaming a ladder does not enforce a unique name, and duplicate names collapse silently

MINOR · bug

**Files** — `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:766-780`, `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:915-919`, `backend/agent_core/cards/schema.py:355`, `backend/agent_core/cards/compile.py:434`

**Mechanism** — CadencesEditor.add dedupes when creating (`while (used.has(name)) name = \`${base}-${n++}\``, :911-915), but the rename onBlur writes whatever was typed with no uniqueness check (:766-780). cadence_for resolves with `next((c for c in self.cadences if c.name == name), CardCadence())` (schema.py:355) — the first match wins. G-OB8 only tests membership (compile.py:434), so two ladders named the same publish green and the second becomes unreachable.

**Trigger** — Rename 'ladder-2' to 'collections' on a card that already has a 'collections' ladder. Both render, both show a mission count, and only the first is ever applied.

**Fix** — Reject or auto-suffix a duplicate in the rename handler, matching what add already does, and surface a danger lozenge for any duplicated name.

#### `OUTBOUND-18` — The New run panel disappears with no explanation when the published card declares no missions, and its mission list never refreshes

MINOR · bug

**Files** — `Habibi/src/components/prompt-studio/OutboundTab.tsx:413`, `Habibi/src/components/prompt-studio/OutboundTab.tsx:543-545`, `Habibi/src/api/outbound.ts:443`, `Habibi/src/api/outbound.ts:487`, `Habibi/src/api/outbound.ts:496`, `backend/main.py:5325-5341`

**Mechanism** — objectiveKeys comes from the *published* card via /outbound/missions (OutboundTab.tsx:413) and CohortBuilder is rendered only when that list is non-empty (:543-545) — with no empty state, so on every card that has not yet published a mission the entire 'New run' panel is absent and the Cadence pane offers no way to build a cohort and no sentence saying why. Nothing in Habibi/src invalidates the ['outbound','missions', botId] key: useCreateCampaign and useSetCampaignStatus invalidate only ['outbound','campaigns'] (outbound.ts:487,496), and there is no invalidation on publish. The query also mixes sources — main.py:5337-5347 prefers the studio *draft's* flow for graphEntries but the *published* card for objectives — so the Entry-step dropdown and the mission list can describe two different versions.

**Trigger** — Author a first mission, publish, stay on the tab: the Mission dropdown and the New run panel do not appear until the query refetches (tab remount or window focus). On a card with no published mission the panel simply is not there.

**Fix** — Render an explicit empty state where CohortBuilder would be ('No published mission on this card — publish one before creating a run'), and invalidate ['outbound','missions'] from the publish mutation.

#### `OUTBOUND-19` — The client and the editor claim G-OB6 validates success/partial/stop_on; it validates neither

MINOR · doc-vs-code

**Files** — `Habibi/src/api/outbound.ts:250-251`, `backend/main.py:5287-5288`, `backend/agent_core/cards/compile.py:390-407`, `backend/agent_core/cards/schema.py:237-238`, `backend/agent_core/cards/schema.py:279-289`

**Mechanism** — outbound.ts:249-251 documents outcomeCodes as "The Closer's taxonomy — `success`, `partial`, `stop_on`, and a post-call rule's `when`. G-OB6 rejects anything outside it", and main.py:5299-5301 repeats it. G-OB6 (compile.py:391-408) checks only `rule.when in OUTCOME_CODES` and each `rule.do` verb. CardObjective.success/partial (schema.py:237-238) and CardCadence.stop_on (schema.py:279-289) are unvalidated `list[str]` — no Literal, no gate. Today the editor only offers valid codes so nothing drifts, but the safety net the comment promises does not exist for any other authoring path (API PATCH, a restored old card, a hand-written card).

**Trigger** — PATCH a card with objective.success=['definitely_paid'] via /agent-studio/cards/{botId}. It validates, compiles green, and the Closer silently never matches it (compounded by OUTBOUND-01, which means it would not be read even if it did).

**Fix** — Extend G-OB6 to check objective.success, objective.partial and cadence.stop_on against OUTCOME_CODES, or correct both comments to say what the gate covers.

#### `OUTBOUND-20` — The backend still allows a cancelled run to be restarted; only the UI guard stops it

MINOR · bug · prior: 2l.4

**Files** — `Habibi/src/components/prompt-studio/OutboundTab.tsx:589-592`, `backend/main.py:5121-5130`, `backend/campaigns.py:373-392`

**Mechanism** — The UI fix for the prior finding landed — Start is now disabled for both 'finished' and 'cancelled' (OutboundTab.tsx:591). The endpoint validates only that the *target* status is one of running/paused/finished/cancelled (main.py:5121-5130) and set_status writes it unconditionally (campaigns.py:373-392) with no transition table, so cancelled→running and finished→running are both accepted over the API. set_status also re-stamps `started_at = COALESCE(started_at, now())` and clears paused_at, so a resurrected run keeps its original start time.

**Trigger** — POST {status:'running'} to a cancelled run's status endpoint (or click Start in any client that lacks this UI's guard). The run resumes dialling a cohort somebody deliberately stopped.

**Fix** — Put the transition table in campaigns.set_status where every caller gets it: refuse running from 'cancelled' or 'finished' with 409, rather than relying on a disabled button.

#### `OUTBOUND-21` — The slice's only frontend test asserts substrings in source files

MINOR · test-gap

**Files** — `Habibi/src/api/outbound.test.ts:1-24`, `backend/tests/test_outbound_studio_bindings.py:36-51`, `backend/cadence.py:418`

**Mechanism** — outbound.test.ts is 24 lines and contains two readFileSync/toContain assertions ('botId?: string' appears in outbound.ts; 'agentCard: card, flow' appears in OutboundTab.tsx). Nothing renders OutboundTab or the four sub-editors, so no test covers: that a DirectionPanel/MissionEditor/CadenceEditor/PostCallEditor change reaches card.outbound, the rejected-input banner, the Start/Pause guard states, the OutboundGates status branches, or the empty/error states. On the backend, test_outbound_studio_bindings.py pins enact.py and main.py against a hardcoded DEFAULT_BOT_ID (:36-51) but not cadence.py — the one file where the hardcode survives (cadence.py:418, OUTBOUND-02).

**Trigger** — Any of the findings above would ship green: the suite that exists cannot fail on behaviour.

**Fix** — Render the tab with a mock vocabulary and assert the writes and guard states; extend the DEFAULT_BOT_ID assertion in test_outbound_studio_bindings.py to cover every module that reserves an attempt (cadence.py, campaigns.py, enact.py).

---

## Flow tab — canvas, inspector, validator, the two runtimes

17 findings — 5 MAJOR, 11 MINOR, 1 trivial; 9 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-flow.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `FLOW-1` — GET /flow/built-in cannot run in the API container: import chain requires pipecat

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/main.py:2068-2081`, `backend/voice/flow_export.py:35`, `backend/voice/flows.py:28`, `backend/voice/tools.py:26`, `backend/requirements.txt:23`, `backend/Dockerfile:5,23-24,54-55`, `backend/docker-compose.yml:79-83`, `backend/docker-compose.dev.yml:15-20`, `Habibi/src/api/flow.ts:267-268`, `Habibi/src/routes/prompt-studio.lazy.tsx:1508-1519`, `Habibi/src/components/flow/FlowCanvas.tsx:995-1013`

**Mechanism** — main.py:2079 does `from voice.flow_export import built_in_collections_graph`; flow_export.py:35 imports `voice.flows`, flows.py:28 imports `voice.tools`, and tools.py:26 does a module-level `from pipecat.flows import NO_RESPONSE, flows_tool_options`. requirements.txt:23 states pipecat lives only in requirements-voice.txt, which the Dockerfile installs only in the builder/voice stages (:54-55); docker-compose.yml:79-83 builds the `api` service from `target: base`. In that process the import raises ModuleNotFoundError → HTTP 500. flow_graph.py's own docstring (:756-762) and test_flow_tool_catalog.py:5-8 confirm the API process is designed to run without pipecat, and the sibling /flow/transitions deliberately parses tools.py as text for exactly this reason (flow_graph.py:846-850) — /flow/built-in did not get the same treatment.

**Trigger** — In the compose deployment open any card's Flow tab and click 'Load the built-in script' (empty state) or '⋯ → Reload built-in script…'. The toast shows the 500 body; the graph never loads. This also voids the mitigation the prior audit relied on for 2b.6 (stale kaia draft).

**Fix** — Make the export importable without pipecat: move MONEY_GOAL_INTENTS and the export into a pipecat-free module and have voice/flows.py import lazily, or have the API proxy GET /flow/built-in to the voice runner (VOICE_RUNNER_URL) which has the stack. Add a test in the API-import CI job (b4e1f47) that calls the endpoint.

#### `FLOW-2` — Built-in export marks only call_ended as endConversation — wrap_up, terminate_politely and escalate_close stop hanging up once reloaded and published

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/voice/flow_export.py:187`, `backend/voice/flow_export.py:143-159`, `backend/voice/flow_export.py:293-296`, `backend/voice/flows.py:722`, `backend/voice/flows.py:740`, `backend/voice/flows.py:770`, `backend/voice/flows_dynamic.py:371-380`, `backend/voice/flows_dynamic.py:496-505`, `backend/tests/test_flow_export.py:156-159`, `Habibi/src/components/flow/FlowNodes.tsx:73-75`

**Mechanism** — _node_json sets `"endConversation": key == "call_ended"` (flow_export.py:187) and never reads the node's `post_actions`. The Python script ends the call with `post_actions: end_conversation` on wrap_up (:722), terminate_politely (:740) and escalate_close (:770). flows_dynamic.py:500-505 only emits end_conversation when data.endConversation is true, so under the authored graph those three nodes speak their closing line and then wait: wrap_up and terminate_politely have `functions: []` and no authored edges, so the only exit is the model spontaneously calling the global end_call; terminate_politely's instruction is 'Do not ask further questions', so a refused/third-party caller sits in dead air until the idle ladder hangs up. test_flow_export.py only checks call_ended (:156), so the export's claim of being 'derived, not transcribed' (flow_export.py:9-14) is untested for post_actions. The canvas does surface 'Nothing leaves this step and it does not end the call' on two of the three (FlowNodes.tsx:74-75), but the reload toast still says the built-in script was loaded.

**Trigger** — Reload built-in script (where the endpoint works), publish, place a call that refuses verification: the built-in Python hangs up after the apology; the authored graph does not.

**Fix** — In _node_json derive `endConversation` from `any(a.get('type') == 'end_conversation' for a in node.get('post_actions') or [])`, and add a test asserting wrap_up/terminate_politely/escalate_close export with endConversation true.

#### `FLOW-3` — Tool picker, /flow/validate and G1 accept any catalog tool; the card's Tool Grant silently drops it at runtime and the canvas still counts its hop as an exit

**MAJOR** · disconnected · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `Habibi/src/components/flow/FlowInspector.tsx:406-435`, `Habibi/src/components/flow/FlowInspector.tsx:736-748`, `Habibi/src/components/flow/FlowCanvas.tsx:1281`, `Habibi/src/components/flow/FlowCanvas.tsx:1318`, `Habibi/src/components/flow/FlowCanvas.tsx:550-627`, `Habibi/src/components/flow/FlowNodes.tsx:69-78`, `backend/main.py:3003-3012`, `backend/flow_graph.py:429-433`, `backend/flow_graph.py:806-833`, `backend/agent_core/cards/compile.py:569-573`, `backend/agent_core/tools/grant.py:57-88`, `backend/voice/bot.py:1141-1146`, `backend/voice/tools.py:2917-2919`, `backend/voice/flows_dynamic.py:414-424`

**Mechanism** — ToolList offers every entry of /flow/tools (the full voice catalog, flow_graph.py:806-832) with no reference to card.tools/skills. /flow/validate (main.py:3011) and G1's assert_publishable (compile.py:573 → flow_graph.py:429-432) both validate node tools against that same full catalog, so a node carrying e.g. create_promise_to_pay on a card whose skill pack was detached compiles green. At runtime bot.py:1141-1146 computes the grant, tools.py:2918-2919 filters the registry to grant ∪ ALWAYS_ON, and flows_dynamic.py:414-424 skips the missing key with only a logger.warning. No compile gate compares flow tools with the grant (compile.py's only graph read is :302, G-OB2). Worse, the canvas derives ghost edges and the node's out-degree from the tool's hop (FlowCanvas.tsx:562-590, :626) so a node whose sole exit is an ungranted tool shows an exit and no 'Nothing leaves this step' hint (FlowNodes.tsx:74-75) while at runtime it is a dead end — the same failure class node_contracts.py was written for, but NODE_REQUIRED covers only built-in keys and is not applied to authored graphs.

**Trigger** — Detach the skill pack that grants create_promise_to_pay on the Skills tab, keep it on negotiate_ptp in the Flow tab, publish (all gates pass), call: the model is never offered the tool on that node.

**Fix** — Add a compile gate (or extend G4) that intersects every node's tools and globalTools with the card's effective grant and fails/warns on the difference; surface the same intersection in ToolList (disabled row with 'not on this card') and exclude ungranted tools from implicitEdges/degree counts.

#### `FLOW-4` — A version flagged flowUnreadable is silently overwritten with the empty sentinel by the first autosave, while the tab says 'Nothing has been changed'

**MAJOR** · degradation-lie · prior: 2b.2 · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/db_prompt_studio.py:155-174`, `backend/db_prompt_studio.py:1764-1772`, `backend/db_prompt_studio.py:199-203`, `backend/schemas.py:2226-2235`, `Habibi/src/routes/prompt-studio.lazy.tsx:224-226`, `Habibi/src/routes/prompt-studio.lazy.tsx:398`, `Habibi/src/routes/prompt-studio.lazy.tsx:645-656`, `Habibi/src/routes/prompt-studio.lazy.tsx:1160-1173`, `Habibi/src/routes/prompt-studio.lazy.tsx:1459-1478`, `Habibi/src/api/prompt-studio.ts:1011-1016`

**Mechanism** — _prompt_flow serves `flow: {}` for an unparseable row (db_prompt_studio.py:172-173); the response model materialises it as `{version:1,globalTools:[],nodes:[],edges:[]}` (schemas.py:2226). The editor stores that object as `flow` (lazy.tsx:398) — non-null — so the 'omit when null' protection (lazy.tsx:224-226, prompt-studio.ts:1013-1016) does not apply: the first autosave triggered by any other edit sends `flow: <sentinel>`, and the PATCH writes it over the column (db_prompt_studio.py:1768-1773). If the unreadable row is the published one, the new draft carries the sentinel, `flowUnreadable` is then read from the draft (lazy.tsx:1167-1172) and the red panel is replaced by 'No authored flow' — the signal disappears before the operator acts. The panel text (:1471-1476) claims nothing has changed and that only restore/load-built-in replace the row; in fact one keystroke in the prompt does. db_prompt_studio.py:199-203 names 'a write from a newer build' as a cause, i.e. the destroyed JSON can be a graph a newer build reads.

**Trigger** — Open a bot whose draft has an out-of-schema flow (the panel shows 'stored graph could not be read'), type one character in the System Prompt, wait 1.2 s: the draft's flow column is now the empty sentinel and the panel is gone.

**Fix** — When the loaded row has flowUnreadable=true keep `flow` state at null (so autosave/publish omit the key and the backend leaves the column alone) until the author explicitly loads the built-in script or starts blank; alternatively have the PATCH refuse to overwrite an unparseable column with the sentinel unless a `replaceUnreadable` flag is sent.

#### `FLOW-5` — Captured yes/no variables serialise as 'True'/'False' while identity_verified is 'true'/'false' — an `equals true` expression edge on a captured boolean never fires

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/voice/flows_dynamic.py:246-256`, `backend/voice/flows_dynamic.py:272`, `backend/voice/flows_dynamic.py:78`, `backend/voice/flows_dynamic.py:112-118`, `backend/voice/flow_vars.py:60-63`, `backend/voice/flow_vars.py:131-134`, `Habibi/src/components/flow/FlowInspector.tsx:926-934`, `Habibi/src/components/flow/FlowInspector.tsx:940-963`, `backend/tests/test_flow_graph_authoring.py:176-180`

**Mechanism** — The extract tool declares `type: boolean` for yes/no variables (flows_dynamic.py:246-256), so the model returns JSON true/false; `variables.update(captured)` (:272) → FlowVariables.set stores `str(value)` = 'True'/'False' (flow_vars.py:63). evaluate_clause compares strings exactly (flow_vars.py:131-134). The system variable identity_verified is deliberately lower-cased 'so an authored `equals true` clause matches' (flows_dynamic.py:116-118), so the editor teaches authors to write `true`; the same clause against a captured boolean is always false. test_flow_graph_authoring.py:178-181 pins the 'True' spelling. The condition editor offers a free-text value with no boolean picker (FlowInspector.tsx:930-960).

**Trigger** — Add variable `wants_plan` type yes/no on a step; add an expression edge `wants_plan is true` to negotiate_ptp; publish; in a call the model records wants_plan=true and the edge never fires (nor does `is false`).

**Fix** — Normalise booleans in FlowVariables.set (`'true'/'false'` for bool) or in the extract handler, and render a true/false picker in the clause editor when the referenced variable is boolean.

#### `FLOW-10` — 'Line spoken on entry' is ignored on 'Say verbatim' nodes, yet the validator demands it for listen-first outbound entries

MINOR · shape-mismatch · **closed** in `a91d371` (pass 7)

**Files** — `backend/voice/flows_dynamic.py:384-407`, `backend/flow_graph.py:559-573`, `Habibi/src/components/flow/FlowInspector.tsx:706-725`, `Habibi/src/components/flow/FlowNodes.tsx:416`

**Mechanism** — flows_dynamic.py:386-392 handles `instructionType == 'say'` by emitting a single tts_say pre_action from `instructions`; `entry_line` is only emitted in the else branch (:399-407). The inspector shows the entry-line field whenever 'Listen before speaking' is on, regardless of instruction type (FlowInspector.tsx:710-722), and the card renders it as spoken (FlowNodes.tsx:416). silent_outbound_entry (flow_graph.py:562-575) errors on `not respondImmediately and not entryLine` even though a say node speaks its text on entry, so the author is forced to add a line that is then discarded.

**Trigger** — Make a 'Say verbatim' step the entry for dpd_reminder with 'Listen before speaking' on; validator errors; add an entry line; publish; the line is never spoken.

**Fix** — In the say branch prepend the entry line as a second tts_say (or hide the field for say nodes) and make silent_outbound_entry accept a non-empty say text as speech on entry.

#### `FLOW-11` — End-node instructions are consumed at runtime but hidden from the inspector

MINOR · disconnected · **closed** in `6089743` (pass 7)

**Files** — `backend/voice/flows_dynamic.py:370-380`, `Habibi/src/components/flow/FlowInspector.tsx:659-661`, `Habibi/src/api/flow.ts:194-211`, `backend/voice/flow_export.py:167-172`

**Mechanism** — For `type == 'end'` flows_dynamic renders `node.data.instructions` as the farewell developer message, falling back to 'Close the call politely in one short sentence.' (:373-378). NodeInspector wraps every content section in `!isEnd &&` (FlowInspector.tsx:661), so the farewell can never be seen or edited: a reloaded built-in graph carries _FAREWELL_TASK on call_ended invisibly, and a hand-added End node (emptyGraph flow.ts:191-207 or the 'End' button) ships the hardcoded fallback with no way to change wording.

**Trigger** — Select the End node: no instruction field; publish; the farewell wording is whatever the JSON holds.

**Fix** — Show a single 'Farewell line' textarea for end nodes bound to data.instructions (and render it on the EndNode card).

#### `FLOW-12` — 'moves' badge is a hand list that misses four tools whose ghost edges the canvas draws (capture_call_goal, flag_dispute, request_callback, capture_lead)

MINOR · stale

**Files** — `backend/flow_graph.py:788-804`, `backend/flow_graph.py:828`, `backend/voice/tools.py:628,682`, `backend/voice/tools.py:1327,1391`, `backend/voice/tools.py:1546,1608`, `backend/voice/tools.py:2273,2358`, `backend/tests/test_flow_transitions.py:79-84`, `backend/tests/test_flow_tool_catalog.py:61-64`, `Habibi/src/components/flow/FlowInspector.tsx:376-386`

**Mechanism** — `transitions` in /flow/tools comes from the frozenset _TRANSITIONING_TOOLS (flow_graph.py:788-803, :828), while ghost edges come from the AST reader implicit_transitions(). tools.py returns `_node(...)` from capture_call_goal (:682), flag_dispute (:1391), request_callback (:1608) and capture_lead (:2358) — and test_flow_transitions.py:81-82 asserts two of them — but none is in the frozenset. test_flow_tool_catalog.py:60-64 only checks the listed keys are flagged, not the converse. So ToolRow shows no 'moves' badge (FlowInspector.tsx:379) and the node card no arrow for tools that do transition, while the canvas draws their hop.

**Trigger** — Tick request_callback on a node: no 'moves' badge, yet a dotted edge to wrap_up appears.

**Fix** — Compute `transitions` as `key in implicit_transitions()` (or assert `_TRANSITIONING_TOOLS == set(implicit_transitions())` in the test).

#### `FLOW-13` — Export and runtime drop the non-tts pre_actions and the close-probe offer clause: summarize_context/mesh_activate_insurance are dead under an authored graph

MINOR · dead-config · **closed** in `a91d371` (pass 7)

**Files** — `backend/voice/flow_export.py:143-159`, `backend/voice/flows.py:657-661`, `backend/voice/flows.py:678-690`, `backend/voice/bot.py:1499-1545`, `backend/voice/flows_dynamic.py:384-407`, `backend/voice/flows_dynamic.py:450-464`, `backend/flow_graph.py:148-181`

**Mechanism** — _entry_line keeps only `tts_say` pre_actions (flow_export.py:154), so gated_upsell's `summarize_context` and `mesh_activate_insurance` (flows.py:640-644) are not represented in FlowNodeData and flows_dynamic can only ever emit tts_say/function/end_conversation actions. bot.py:1515 and :1540 still register both actions on every call, so under VOICE_FLOW_GRAPH=auto with a published graph they are registered and never invoked (topic-hop summarisation is lost on the upsell hop). Likewise pre_close's `_PRE_CLOSE_TASK.format(offer=state.close_probe_offer_clause)` (flows.py:683-687) is rendered at export time with an empty offer, and flows_dynamic's pre_close special-case (:450-464) appends a KB message but never the live offer clause.

**Trigger** — Publish the reloaded built-in graph; reach gated_upsell or pre_close on a call.

**Fix** — Either add an explicit `actions: ["summarize_context", ...]` node field (validated against bot.py's registered names) or document in the export/tab that these hooks are built-in-only; render the pre_close offer clause in flows_dynamic when the node key is pre_close.

#### `FLOW-14` — Flow tab is shown for every card and its empty state claims the version 'runs the built-in collections script', but only the voice runtime reads the graph

MINOR · doc-vs-code

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:1109-1111`, `Habibi/src/routes/prompt-studio.lazy.tsx:1486-1500`, `backend/bot_runtime.py`, `backend/sandbox_runtime.py`, `backend/voice/bot.py:1167-1176`

**Mechanism** — TABS always includes flow (lazy.tsx:1111). bot_runtime.py (WhatsApp/text) and sandbox_runtime.py contain no reference to `flow`/FlowGraph (grep: zero matches), and the only consumer is bot.py:1167-1176. The empty-state copy (lazy.tsx:1490-1500) tells the author of a text-channel card that this version 'runs the built-in collections script' and that loading the graph will change what it does, which is false for that channel; nothing in the tab says the graph governs voice only.

**Trigger** — Open a WhatsApp-only card's Flow tab.

**Fix** — State 'Voice calls only' in the tab header/empty state and, if the card has no voice channel, render the tab read-only with that note.

#### `FLOW-15` — Runtime special-cases node keys (confirm_identity, escalate_close, pre_close) invisibly; confirm_identity is not in the reserved-key list the editor shows

MINOR · doc-vs-code

**Files** — `backend/voice/flows_dynamic.py:433-462`, `backend/flow_graph.py:47-67`, `Habibi/src/components/flow/FlowInspector.tsx:637-651`

**Mechanism** — flows_dynamic appends extra developer messages when node.key is confirm_identity (:437-449) or escalate_close/pre_close (:450-464). The inspector's only hint about key semantics is RESERVED_NODE_KEYS (FlowInspector.tsx:614-628), which deliberately excludes confirm_identity (flow_graph.py:47-53) and says nothing about injected instructions, so an author renaming or reusing those keys changes behaviour they cannot see, and an author who reads the 'Reserved key' hint believes the list is exhaustive.

**Trigger** — Rename node key confirm_identity to outbound_greet: the 'no tool before confirmation' guard silently disappears.

**Fix** — Move the injected text into the exported node instructions (so it is visible and editable) or list these keys in /flow/reserved-keys with a 'runtime adds instructions' note.

#### `FLOW-16` — Condition/variable editor advertises no variable names; flows_dynamic's claim that SESSION_VARIABLES is 'the contract the Flow editor advertises' is false

MINOR · doc-vs-code

**Files** — `backend/voice/flows_dynamic.py:81-93`, `backend/main.py:2058-2101`, `Habibi/src/components/flow/FlowInspector.tsx:692-695`, `Habibi/src/components/flow/FlowInspector.tsx:940-946`, `backend/voice/flow_vars.py:98-110`, `backend/voice/flow_vars.py:127-134`

**Mechanism** — SESSION_VARIABLES (call_goal, identity_verified, outstanding, …) plus date/time are the only system names an instruction can interpolate or an edge can test, but no endpoint exposes them (grep: only flows_dynamic.py/flow_export.py reference the tuple) and the inspector offers a free-text `variable` input (FlowInspector.tsx:935-941) and a generic '{{variable}}' hint (:692-695). A typo renders literally into the developer message (flow_vars.py:98-110, by design) and an expression edge on it evaluates false forever, with no validator warning.

**Trigger** — Type `{{customer_name}}` in a step or `identity_verfied is true` on an edge: validates green, never resolves.

**Fix** — Expose GET /flow/variables (SESSION_VARIABLES + date/time) and offer a datalist of system + captured variables in both editors; warn in validate_graph on unknown names.

#### `FLOW-6` — Graph-level 'Tools available from every step' offers four CRM reads that flows_dynamic silently strips from globals

MINOR · dead-config

**Files** — `Habibi/src/components/flow/FlowInspector.tsx:499-521`, `Habibi/src/components/flow/FlowInspector.tsx:406-435`, `backend/flow_graph.py:511-513`, `backend/voice/flows_dynamic.py:507-518`

**Mechanism** — GraphInspector renders the full catalog as global-tool checkboxes and counts the selection in its label (FlowInspector.tsx:500). validate_graph only checks membership in the catalog (flow_graph.py:517-519). flows_dynamic.py:510-518 builds global_functions excluding get_customer_context, get_payment_history, get_emi_schedule and request_documents with no log and no validator warning, so an author who adds them as globals sees a green graph and a counter that includes tools the runtime never exposes.

**Trigger** — Deselect everything, tick request_documents under 'Tools available from every step', publish: the tool is offered on no node.

**Fix** — Either drop the strip (the card grant already decides exposure) or surface it: emit a validate_graph warning `global_not_allowed` for those keys and disable the rows in GraphInspector with the reason.

#### `FLOW-7` — Validator outage reports '0 flow errors — publish blocked' and a stale canvas verdict; the off-canvas path still keeps the last verdict

MINOR · degradation-lie · prior: 2b.4

**Files** — `Habibi/src/components/flow/FlowCanvas.tsx:481-518`, `Habibi/src/components/flow/FlowCanvas.tsx:1320`, `Habibi/src/routes/prompt-studio.lazy.tsx:227`, `Habibi/src/routes/prompt-studio.lazy.tsx:722-734`, `Habibi/src/routes/prompt-studio.lazy.tsx:744-758`, `Habibi/src/routes/prompt-studio.lazy.tsx:941-943`, `Habibi/src/routes/prompt-studio.lazy.tsx:1267-1268`, `Habibi/src/components/prompt-studio/StudioHeader.tsx:98-101`

**Mechanism** — On a failed /flow/validate the canvas now reports `{ok:false, issues:[warning validator_unreachable]}` (FlowCanvas.tsx:505-517) — but it does not put that warning into its own `issues`, so the toolbar pill and the GraphInspector issue list keep showing the previous verdict (dimmed) with nothing about the outage. The parent sets flowValid=false (lazy.tsx:745) while flowErrorCount counts severity=error only, so the header renders '0 flow errors — publish blocked' (StudioHeader.tsx:100) and Publish toasts 'Fix conversation-flow errors before publishing' (lazy.tsx:942) with no error to fix. Off the Flow tab the effect at lazy.tsx:724-731 still swallows the failure and keeps the last verdict with the gate starting open (:227) — the original 2b.4 shape.

**Trigger** — Stop the API mid-edit on the Flow tab: header shows '0 flow errors — publish blocked'; switch to Prompt tab first and the gate instead stays whatever it last was.

**Fix** — Merge the validator_unreachable issue into the canvas `issues` and treat it as blocking in the header copy ('flow not checked — publish blocked'); apply the same unreachable handling in the lazy.tsx:724 effect.

#### `FLOW-8` — MissionEntries renders a failed vocabulary query as 'No outbound missions available' and hides the node's existing entryFor claims

MINOR · degradation-lie

**Files** — `Habibi/src/components/flow/FlowInspector.tsx:183-231`, `Habibi/src/components/flow/FlowInspector.tsx:200-206`, `Habibi/src/api/outbound.ts:280-291`

**Mechanism** — The section branches on `missions.length === 0` and distinguishes only `vocab.isPending`; `vocab.isError` falls through to 'No outbound missions available. They come from the card vocabulary.' (FlowInspector.tsx:203-206) — an error rendered as a business statement, the pattern 2i.1 flagged on Connectors. The checkbox list is the only view of `node.data.entryFor`, so while the query fails a node's existing claims are neither visible nor removable, yet G-OB2 keeps failing on them.

**Trigger** — Break /outbound/card-vocabulary (or open the inspector while it 500s) and select the confirm_identity node.

**Fix** — Add an isError branch ('Could not load missions — this is not a statement about this step') and render the already-claimed keys from node.data.entryFor regardless of catalog availability.

#### `FLOW-9` — ToolList shows 'Tool catalog unavailable.' for loading, error and empty alike; a node's attached tools vanish from the inspector

MINOR · degradation-lie

**Files** — `Habibi/src/components/flow/FlowInspector.tsx:406-435`, `Habibi/src/components/flow/FlowInspector.tsx:736-746`, `Habibi/src/components/flow/FlowCanvas.tsx:1281`, `Habibi/src/components/flow/FlowCanvas.tsx:1318`

**Mechanism** — FlowCanvas passes `toolsQuery.data ?? []` (:1281, :1319) with no pending/error signal; ToolList renders one string for all three states (FlowInspector.tsx:421-424). Because the node's tools are shown only as checked rows of the catalog, a node with five tools shows none while the catalog is unavailable, and the 'Tools · N' label (:738) still counts them.

**Trigger** — Open a node inspector while /flow/tools is slow or failing.

**Fix** — Pass isPending/isError into NodeInspector/GraphInspector and, when the catalog is absent, list node.data.tools as plain removable chips.

#### `FLOW-17` — Copy drift: card-vocabulary returns 'inbound' although the inspector comment says the endpoint excludes it; reload toasts say 'steps' vs 'nodes'

trivial · doc-vs-code · **closed** in `6089743` (pass 7)

**Files** — `backend/main.py:5292`, `backend/flow_graph.py:76-78`, `Habibi/src/components/flow/FlowInspector.tsx:194-197`, `Habibi/src/components/flow/FlowCanvas.tsx:1002-1004`, `Habibi/src/routes/prompt-studio.lazy.tsx:1512`

**Mechanism** — main.py:5292 returns `list(fg.OBJECTIVES)` which starts with 'inbound'; FlowInspector.tsx:196 says 'The endpoint already excludes it; this is belt and braces' (only the client filter does). The two load-built-in success toasts describe the same count as 'steps' (FlowCanvas.tsx:1003) and 'nodes' (lazy.tsx:1512).

**Trigger** — Read the code / trigger both loads.

**Fix** — Correct the comment or filter server-side; unify the toast wording.

---

## Tools tab — grant vs offer, locked engines, voice cap

10 findings — 1 MAJOR, 7 MINOR, 2 trivial; 1 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-tools.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `TOOLS-1` — Tools tab offers Add for nine flow-control verbs that are not catalog tools; Add makes G4 fail while the tab shows G6 green

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:154-181`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:103-112`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:95`, `backend/flow_graph.py:773-784`, `backend/flow_graph.py:822`, `backend/flow_graph.py:829`, `backend/agent_core/cards/compile.py:623`, `backend/agent_core/cards/compile.py:643-647`, `backend/agent_core/tools/grant.py:57-69`, `backend/schemas.py:14-25`, `backend/tests/test_tool_grant.py:181-186`

**Mechanism** — GET /flow/tools is the voice-filtered CATALOG plus _FLOW_CONTROL_TOOLS (flow_graph.py:822), so disclose_recording, refuse_verification, not_account_holder, begin_negotiate, begin_dispute, begin_wrap_up, return_to_position, pause_for_caller and end_call arrive as rows with locked=false. The tab renders every row with an enabled Add/Remove button and the 'optional' label (AgentCardPanels.tsx:163-181). Clicking Add appends the key to card.tools.include (:103-112). G4 computes unknown = include − CATALOG.specs (compile.py:623) and fails 'include names not in catalog' (:644-647); test_tool_grant.py:184 pins that these nine names are never in CATALOG. The tab reads only the G6 gate from the same report (:95), so the operator sees 'G6 pass' and no red until Publish. Conversely Remove on these rows can never happen (they are never in include) and they are ALWAYS_ON at runtime (voice/tools.py:2918), so the 'optional / Add' presentation is false in both directions.

**Trigger** — Open any authored card's Tools tab, click Add on end_call (or any of the nine), wait for autosave, then Publish: G4 fails 'include names not in catalog' while the Tools tab header still shows a green G6 lozenge.

**Fix** — In ToolsTab, treat rows whose key is in a VOICE_ALWAYS/flow-control set (expose `alwaysOn: true` from flow_graph.tool_catalog alongside `locked`) as non-toggleable with a 'always on (voice floor)' lozenge, and never write them into include. Also surface the report's G4 gate next to G6.

#### `TOOLS-2` — Tab surfaces only G6 although its own edits trip G4 and G9; a pack-required tool can be unticked with no live signal

MINOR · degradation-lie

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:95`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:129-140`, `backend/agent_core/cards/compile.py:724-751`, `Habibi/src/components/prompt-studio/PublishDialog.tsx:174-180`

**Mechanism** — useCompilePreview returns the full gate list, but ToolsTab picks `gates.find(g => g.gate === 'G6')` (:95) and renders nothing for G4 or G9. G9 fails when a pack on card.skills lists a tool that is not in include ∪ locked ∪ PLATFORM_SKILL_TOOLS (compile.py:734-747) — exactly what the Remove button produces. The full report is shown only in PublishDialog via CompileReportList after the manual runCompile. The prior audit's live-state note (kaia-v2-4 draft failing G9 on set_contact_preference / capture_nonpayment_reason) is this path.

**Trigger** — On kaia-v2-4 (skills attached) click Remove on set_contact_preference; the tab keeps showing 'G6 pass'; Publish then fails G9 'tools_not_on_card'.

**Fix** — Render the G4 and G9 gate results beside G6 in the header strip (same Lozenge pattern), and on each row show a 'required by skill <slug>' marker derived from the attached packs' allowed_tools so Remove is disabled or warned.

#### `TOOLS-3` — G6 'skipped' is painted green in the Tools tab

MINOR · degradation-lie

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:133`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:125`, `backend/agent_core/cards/compile.py:682-683`, `backend/agent_core/cards/compile.py:557-567`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:1027-1036`

**Mechanism** — The tone expression is `fail ? danger : warn ? warning : success`, so status 'skipped' maps to success. compile_card emits G6 skipped 'no card' whenever `card is None` (:682-683), which happens for an authored card that fails G0 schema validation (:558-567) — the preview is enabled because identity.bot_id is present. The sibling CompileReportList maps skipped to neutral (:1027-1036), so the two renderings of the same gate disagree.

**Trigger** — Any G0 failure on an authored card (e.g. a cloned card carrying an unknown key, or an out-of-range outbound value) — the Tools tab shows a green 'G6 skipped — no card' lozenge and '0 / 12 idle voice tools'.

**Fix** — Reuse the CompileReportList tone mapping (skipped → neutral) or extract one `gateTone(status)` helper and use it in both places.

#### `TOOLS-4` — 'on the card' counter counts two engines the table cannot show and omits the ~10 always-on tools the voice runtime adds

MINOR · shape-mismatch · prior: 2g.2

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:126`, `backend/flow_graph.py:817-829`, `backend/agent_core/cards/schema.py:58-68`, `backend/agent_core/cards/schema.py:114`, `backend/agent_core/tools/grant.py:88`, `backend/voice/tools.py:2918`, `backend/agent_core/cards/defaults.py:55-85`

**Mechanism** — The counter is `new Set([...include, ...locked]).size`. card.tools.locked contains recommend_treatment and evaluate_live_qa, which are not in CATALOG and therefore have no row in /flow/tools (flow_graph.py:817-821, locked flag only for LOCKED_MOUTH_TOOLS :829), so the number is always 2 higher than the rows marked on. What voice/tools.py builds is effective_tools ∪ ALWAYS_ON (:2918), i.e. for the default collections card 34 names versus a counter of 26. Prior 2g.2 (still present at :126) covered the include/locked drift; the two-engine overcount and the always-on undercount are additional.

**Trigger** — Open kaia-v2-4 Tools tab: counter reads 26, only 24 rows show 'Remove', and a live call is built with 34 tools.

**Fix** — Show the compiler's numbers instead: `preview.data.effective_tools.length` labelled 'granted' (and optionally list the always-on floor separately), and drop the client-side union.

#### `TOOLS-5` — A skill-gated tool on include but on no attached pack shows 'Remove' (on) while the runtime never grants it

MINOR · degradation-lie

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:155`, `backend/agent_core/skills/intersect.py:29-48`, `backend/agent_core/skills/intersect.py:107-115`, `backend/agent_core/cards/compile.py:70-71`, `backend/agent_core/cards/defaults.py:63`, `backend/bot_tools.py:806-808`

**Mechanism** — Row state is `includeSet.has(key) || isLocked` (:155). effective_tools strips every SKILL_GATED_TOOLS name that no attached pack lists (intersect.py:113-114) when the card has skills, so create_promise_to_pay / flag_dispute / apply_goodwill / capture_lead etc. can be 'on' in the tab and absent from the grant. The Skills tab's own copy says exactly this (:814-816), and the compile report already carries effective_tools/idle_tools (compile.py:70-71) which the Tools tab ignores. G9 does not catch the reverse direction (card ⊇ packs is what it checks), so nothing turns red.

**Trigger** — Detach ptp-negotiate in the Skills tab, return to Tools: create_promise_to_pay still shows 'Remove' and counts toward 'on the card', but voice/tools.py drops it and bot_tools.execute_tool returns tool_not_on_card_or_skill.

**Fix** — Colour rows from `preview.data.effective_tools` (granted) vs include (authored) and label the difference 'on the card but not granted — no attached skill lists it'.

#### `TOOLS-6` — Toggle is a no-op for verify_identity, capture_call_goal, load_skill and run_skill_script, yet rows say 'optional'

MINOR · dead-config

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:154-181`, `backend/agent_core/tools/catalog.py:158-181`, `backend/agent_core/tools/catalog.py:188-211`, `backend/agent_core/tools/catalog.py:598-645`, `backend/agent_core/tools/grant.py:88`, `backend/agent_core/tools/grant.py:213`, `backend/agent_core/skills/intersect.py:105-106`, `backend/agent_core/skills/intersect.py:114-116`, `backend/voice/tools.py:2918`

**Mechanism** — verify_identity and capture_call_goal are catalog tools inside VOICE_ALWAYS (grant.py:88), unioned into every voice grant (grant.py:213; voice/tools.py:2918). load_skill and run_skill_script are PLATFORM_SKILL_TOOLS, added to `names` unconditionally (intersect.py:105-106,114,116) on every channel. All four appear as ordinary rows (in CATALOG with the voice channel) with an enabled Add/Remove and the 'optional' label, so removing them from include changes nothing the runtime does and adding them changes nothing either.

**Trigger** — On intake-v1 click Add on run_skill_script (shows 'Add' today): no behavioural change — it was already granted. Click Remove on verify_identity on kaia-v2-4: the voice bot still offers it on every node.

**Fix** — Have flow_graph.tool_catalog emit an `alwaysOn` flag (VOICE_ALWAYS ∪ PLATFORM_SKILL_TOOLS) and render those rows disabled with a 'platform floor' lozenge, mirroring the locked treatment.

#### `TOOLS-8` — Compile never passes channel_tools, so G4/G6 and the report's effective_tools ignore the channel filter the runtime applies

MINOR · shape-mismatch

**Files** — `backend/db_prompt_studio.py:838-857`, `backend/db_prompt_studio.py:1908-1925`, `backend/agent_core/cards/compile.py:526`, `backend/agent_core/cards/compile.py:627-639`, `backend/agent_core/skills/intersect.py:79-82`, `backend/voice/bot.py:1141-1143`, `backend/agent_core/tools/catalog.py:214-231`

**Mechanism** — compile_card accepts channel_tools (compile.py:526) and forwards it into effective_tools/idle_offered_tools (:627-639), but neither the dry-run (db_prompt_studio.py:837-857) nor publish (:1908-1926) supplies it, so the preview's idle count and effective_tools are computed channel-agnostically while voice/bot.py:1141-1143 filters to CATALOG.for_channel(voice). A TEXT_ONLY tool on include (identify_customer, ingest_customer_document) counts toward the voice cap in G6 and appears in effective_tools though the voice runtime drops it. The UI cannot add these (tool_catalog is voice-filtered), so the trigger needs a hand-edited or imported card.

**Trigger** — Publish a card whose include JSON contains identify_customer: G6 counts it as an idle voice tool; the voice grant does not contain it.

**Fix** — Pass `channel_tools={s.name for s in CATALOG.for_channel('voice')}` (or compute per card channel) from both compile call sites, or report per-channel effective lists in CompileReport.

#### `TOOLS-9` — Missing non-mouth locked engines fail G3 but no tab can show or repair them

MINOR · disconnected

**Files** — `backend/agent_core/cards/compile.py:600-615`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:202-241`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:103-112`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:1019-1040`, `backend/flow_graph.py:817-829`

**Mechanism** — G3 fails with missing_locked when recommend_treatment or evaluate_live_qa is absent from card.tools.locked (compile.py:603-613). The Tools tab has no rows for them (not in CATALOG, flow_graph.py:817-821) and its toggle only writes include (:103-112); the Policy tab reads policy_bindings, not tools.locked (:203,226-235). So the only surface for tools.locked content is the raw JSON, and the failure reads 'engines cannot be unbound' with no pointer to which screen fixes it.

**Trigger** — Import or PATCH a card whose tools.locked is ['recommend_next_offer','evaluate_authority']; every tab is green until Publish reports G3 missing_locked.

**Fix** — Have PolicyTab also render each LOCKED_POLICY_ENGINES entry's presence in card.tools.locked (red when missing) and offer a one-click 'restore locked engines' that writes the full LOCKED_POLICY_ENGINES list.

#### `TOOLS-10` — No pending state for the catalog; any compile HTTP error is labelled 'compiler unreachable'

trivial · a11y

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:86`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:129-130`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:188-197`, `backend/main.py:2194-2212`

**Mechanism** — While useFlowTools is pending, rows = [] (:86) and the empty/error branches are both suppressed (:195), so the table renders a bare header with no loading indicator. For the preview, `preview.isError` (:129) covers a 500 from compile_card as well as a network failure, yet the lozenge always says 'compiler unreachable'; the endpoint returns 200 for gate failures (main.py:2195-2212), so an error here is a compiler crash, not unreachability.

**Trigger** — Slow /flow/tools: table header with no rows and no spinner. A compile 500: 'compiler unreachable'.

**Fix** — Render LoadingState while toolsQuery.isPending; show the error message (or status) in the preview lozenge title instead of the fixed 'unreachable' text.

#### `TOOLS-7` — PLATFORM_SKILL_TOOLS granted to cards with no skills, contrary to the module's own comment

trivial · doc-vs-code · DOWNGRADED

**Files** — `backend/agent_core/skills/intersect.py:50-51`, `backend/agent_core/skills/intersect.py:105-106`, `backend/agent_core/skills/intersect.py:114-116`, `backend/agent_core/cards/defaults.py:330`, `backend/agent_core/skills/defaults.py:35`

**Mechanism** — The comment at intersect.py:50 says load_skill/run_skill_script are 'Always offered when the card has skills', but `platform = PLATFORM_SKILL_TOOLS & catalog_names` is unioned into `names` at :106 and re-added after channel filtering at :116 with no `card.skills` condition. run_skill_script executes scripts; a card whose author left it off include (supervisor-brief: include=['add_customer_note'], defaults.py:118) still receives it in the grant, widening the grant beyond the card (ADR-0001).

**Trigger** — Resolve the supervisor-brief card through MouthTurn.tools: allowed contains load_skill and run_skill_script though include names neither and no skill packs are attached to require them.

**Fix** — Gate `platform` on `bool(card.skills) or attached_skills` (as the comment states) or on membership in include, and update the comment to match whichever rule is chosen.

---

## Tool catalog — 26 specs across voice, text, MCP and flow

15 findings — 1 MAJOR, 11 MINOR, 3 trivial; 5 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-catalog.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `CATALOG-2` — Both TEXT_ONLY catalog tools are unreachable, and the WhatsApp prompt tells the model to call one of them

**MAJOR** · disconnected · **closed** in `fcbfefd` (pass 3)

**Files** — `backend/agent_core/tools/catalog.py:213-232`, `backend/agent_core/tools/catalog.py:684-709`, `backend/agent_core/cards/defaults.py:54-117`, `backend/agent_core/skills/intersect.py:104-107`, `backend/agent_core/skills/runtime.py:196-203`, `backend/agent_core/tools/grant.py:88`, `backend/bot_runtime.py:525-546`, `backend/bot_runtime.py:943-949`, `backend/bot_tools.py:806-808`, `backend/bot_tools.py:789-790`, `backend/flow_graph.py:815-820`

**Mechanism** — `identify_customer` and `ingest_customer_document` are the catalog's only TEXT_ONLY specs and appear on none of the four first-party cards' include lists (defaults.py:56-116) and in none of the eleven skill packs' `allowed-tools`. `effective_tools` is `card.tools.include ∩ catalog` plus locked/platform/connector names (intersect.py:107-110), and `VOICE_ALWAYS` (grant.py:88) has no text analogue, so both names are absent from `tool_state.allowed`. `bot_runtime.py:943` assigns that set to `tool_ctx.allowed_tools`, and `execute_tool` refuses anything outside it with `tool_not_on_card_or_skill` (bot_tools.py:820-822); `turn_tools` (bot_runtime.py:948) never renders them either. Meanwhile bot_runtime.py:545 injects into every WhatsApp system prompt: "If the caller identity is unclear, call identify_customer with phone digits or account last-4 before money or lead tools." The reason no operator can fix this from the Studio is CATALOG-1's sibling: `/flow/tools` is filtered to `"voice" in spec.channels` (flow_graph.py:817-820), so both text-only names are invisible in the card Tools tab and in the skill editor's picker.

**Trigger** — Any WhatsApp thread where the bound customer is ambiguous. The model follows the prompt line, emits identify_customer, and `execute_tool` returns `tool_not_on_card_or_skill` — burning a tool iteration and leaving the thread bound to whatever the webhook guessed. Separately, a customer-sent receipt can never be filed through the tool path (only through POST /document-requests/ingest, main.py:1735).

**Fix** — Add `identify_customer` (and `ingest_customer_document` if it is still wanted as a tool at all) to `_INTAKE_TOOLS`/`_COLLECTIONS_TOOLS` in defaults.py, or add a `TEXT_ALWAYS` floor in grant.py mirroring VOICE_ALWAYS. Whichever way, stop filtering the Studio's tool palette to the voice channel — return the channel set on FlowToolResponse and let the card editor show tools for the channels the card declares. If neither tool is meant to be reachable, delete the prompt line at bot_runtime.py:545 and the two specs.

#### `CATALOG-1` — The Studio's only tool picker offers nine names that the publish gate G4 rejects

MINOR · shape-mismatch · DOWNGRADED

**Files** — `backend/flow_graph.py:774-785`, `backend/flow_graph.py:806-822`, `backend/agent_core/tools/grant.py:56-68`, `backend/agent_core/cards/compile.py:623`, `backend/agent_core/cards/compile.py:644-646`, `backend/db_prompt_studio.py:1912`, `backend/db_prompt_studio.py:1927`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:79`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:104-115`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:155-172`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:1020-1032`

**Mechanism** — `tool_catalog()` builds the `/flow/tools` palette as (catalog specs on the voice channel) ∪ `_FLOW_CONTROL_TOOLS` (flow_graph.py:822). Nine of those ten flow-control names — disclose_recording, refuse_verification, not_account_holder, begin_negotiate, begin_dispute, begin_wrap_up, return_to_position, pause_for_caller, end_call — deliberately do NOT exist in `agent_core.tools.CATALOG` (flow_graph.py:766-772 says so explicitly; grant.py:56-68 keeps them out of the catalog on purpose). The card Tools tab renders every palette row with an Add button whose handler pushes `t.key` straight into `card.tools.include` (AgentCardPanels.tsx:109). At publish, `compile_card` computes `unknown = [n for n in card.tools.include if n not in catalog_names]` with `catalog_names = set(CATALOG.specs)` (compile.py:623, db_prompt_studio.py:1912) and fails G4 with "include names not in catalog" (compile.py:644-646); `_assert_card(report)` then blocks the publish.

**Trigger** — Open /agent-studio/<botId> → Tools tab, click Add on any of the nine flow-control rows (e.g. `end_call`, `pause_for_caller`), then Publish. G4 fails on a name the editor itself offered a moment earlier. The rows are indistinguishable from the 24 legitimate ones — no badge, no disabled state (only `locked` disables, AgentCardPanels.tsx:163).

**Fix** — Either mark the `_FLOW_CONTROL_TOOLS` rows in FlowToolResponse (add a `flow_only: bool` field set from `key not in CATALOG.specs`) and have ToolsTab render them read-only, or give ToolsTab its own catalog-only endpoint. Cheapest correct fix: add the field in flow_graph.tool_catalog()/schemas.FlowToolResponse and filter on it in AgentCardPanels.ToolsTab, leaving FlowCanvas (which legitimately needs the flow-control names for node tool lists) unchanged.

#### `CATALOG-11` — apply_goodwill emits a CRM chip typed as a dispute with no deep link, unlike every sibling write

MINOR · disconnected · **closed** in `3637d46` (pass 7)

**Files** — `backend/agent_core/tools/domain.py:928-935`, `backend/agent_core/tools/domain.py:73-75`, `backend/agent_core/tools/domain.py:857-859`, `backend/agent_core/tools/catalog.py:465-489`, `backend/voice/tools.py:454-475`, `backend/voice/tools.py:1536`

**Mechanism** — Every other entity-bearing handler resolves its link through `_link(tool_name, id)`, which reads `ToolSpec.deep_link` (domain.py:73-75) — create_promise_to_pay `/promises?id=`, flag_dispute `/disputes?id=`, request_callback, request_documents, capture_lead. `domain.apply_goodwill` hardcodes `entity="dispute"` and `entity_id=posted.get("disputeId")` but never sets `deep_link` (domain.py:928-935), and the `APPLY_GOODWILL` spec declares neither `entity` nor `deep_link` (catalog.py:465-489). `_announce` then emits an RTVI `crm.entity` with `deep_link=None` (voice/tools.py:463-468).

**Trigger** — A goodwill waiver is posted on a live call. The Inspector shows a CRM chip labelled "dispute" that cannot be clicked through to the dispute it reversed a fee on, while the flag_dispute chip a minute earlier could. The money-moving write is the one with no trail from the chip.

**Fix** — Either give APPLY_GOODWILL `entity="dispute", deep_link="/disputes?id={id}"` in the catalog and use `_entity("apply_goodwill")`/`_link("apply_goodwill", ...)` in domain.py:928-935, or reuse the flag_dispute template explicitly: `deep_link=_link("flag_dispute", posted.get("disputeId"))`.

#### `CATALOG-12` — capture_lead's voice idempotency key is still interaction-scoped after the other four writes moved to the carrier call

MINOR · code-organization

**Files** — `backend/voice/tools.py:2334-2337`, `backend/voice/tools.py:1264-1265`, `backend/voice/tools.py:1349-1352`, `backend/voice/tools.py:1563-1565`, `backend/voice/tools.py:2388-2392`, `backend/agent_core/tools/domain.py:448-465`

**Mechanism** — Four voice CRM writes were deliberately re-scoped to `session.provider_call_id or session.interaction_id` with a shared comment explaining that a media-stream reconnect mints a brand-new interaction row (PTP voice/tools.py:1263, dispute :1354, callback :1554, documents :2389). `capture_lead` kept the old form `f"voice-lead:{session.interaction_id or 'no-ix'}:{cid}:{product_id}"` (voice/tools.py:2336), so after a reconnect the same lead gets a different idempotency key.

**Trigger** — A Twilio media-stream reconnect mid-call, followed by the model re-capturing the same lead. The idempotency layer no longer matches. The blast radius is contained because `domain.capture_lead` independently checks `db.find_open_lead` and handles `duplicate_open_lead:` from the advisory lock (domain.py:452-475), so the second write returns the existing lead — which is why this is SUSPECTED rather than a demonstrated duplicate row.

**Fix** — Use the same `call_scope = session.provider_call_id or session.interaction_id or "no-ix"` prefix as its four siblings. Better still, hoist that expression to one local at the top of `build_tools` so a fifth write cannot be added with the old scope.

#### `CATALOG-14` — escalate_to_human's voice handler branches on four reason strings the enum cannot produce

MINOR · stale

**Files** — `backend/voice/tools.py:2682-2695`, `backend/agent_core/tools/catalog.py:55-63`, `backend/agent_core/tools/catalog.py:541-565`, `backend/db_routing.py:552-562`, `backend/voice/persist.py:1167-1177`

**Mechanism** — `ESCALATE_TO_HUMAN.reason` is required with `enum=ESCALATION_REASONS` — the seven values at catalog.py:55-63. The routing-context builder tests `reason_l in {"compliance", "abuse", "legal"}` (voice/tools.py:2687), `{"sentiment_drop", "angry"}` (:2691) and `{"verification_failed", "verify_failed"}` (:2693). `abuse`, `legal`, `angry` and `verify_failed` are not in the enum and appear in no other vocabulary; the guardrail_flag they would have set (`legal-threat` / `abusive-language`) is therefore unreachable through this path. No CHECK violation results, because both write paths coerce anything outside the eight-value set to `customer_requested` (db_routing.py:562, persist.py:1177) — which is also why an out-of-enum reason would degrade silently rather than error.

**Trigger** — Never, for the four dead values. The live consequence is the inverse: `escalate_to_human(reason="compliance")` on a legal threat sets `guardrail_flag="abusive-language"` (voice/tools.py:2688-2690 picks legal-threat only when "legal" is in the string), so a compliance escalation is routed as abuse.

**Fix** — Validate `reason` against `ESCALATION_REASONS` in the handler (the sibling `capture_nonpayment_reason` does exactly this at voice/tools.py:1683-1684), drop the four unreachable branch values, and carry the legal-vs-abuse distinction in `detail` rather than by substring-matching an enum.

#### `CATALOG-3` — _TRANSITIONING_TOOLS is missing four tools that do transition, so the canvas's "moves" badge lies

MINOR · stale

**Files** — `backend/flow_graph.py:787-803`, `backend/flow_graph.py:828`, `backend/flow_graph.py:678-703`, `backend/flow_graph.py:938-957`, `backend/voice/tools.py:681-683`, `backend/voice/tools.py:1391`, `backend/voice/tools.py:1608`, `backend/voice/tools.py:2358`, `Habibi/src/components/flow/FlowCanvas.tsx:642`, `Habibi/src/components/flow/FlowInspector.tsx:379-386`

**Mechanism** — `_TRANSITIONING_TOOLS` is a hand-maintained frozenset (flow_graph.py:788-804) that feeds `FlowToolResponse.transitions` (flow_graph.py:828) and hence the "moves" badge (FlowCanvas.tsx:642, FlowInspector.tsx:379). Four registered tools return a next node and are absent from it: `capture_call_goal` → `_node("verify_identity")` (voice/tools.py:682, and RESERVED_NODE_KEYS:56 documents exactly this hop), `flag_dispute` → `_node("escalate_close")` (voice/tools.py:1391), `request_callback` → `_node("wrap_up")` (voice/tools.py:1608), `capture_lead` → `_node("wrap_up")` (voice/tools.py:2358). The AST-derived `implicit_transitions()` finds all four (it resolves the `_spec(...)` bindings via the delegate pass at flow_graph.py:942-957), so the validator's `redundant_with_tool` warning (flow_graph.py:684-703) contradicts the badge on the same screen.

**Trigger** — Author a node carrying `flag_dispute` with an authored edge to `escalate_close`. The tool shows no "moves" badge — the docstring's whole warning ("Pairing one with graph edges on the same node gives the model two ways out of it") is silently withheld — while `assert_publishable` raises `redundant_with_tool` on the edge. The author is told the edge is redundant with a tool the UI says does not move anything.

**Fix** — Derive `transitions` from `implicit_transitions()` instead of the hand-list: `"transitions": bool(hops.get(key))` in tool_catalog(), falling back to `_TRANSITIONING_TOOLS` only when the AST parse fails (flow_graph.py:874-877 already returns {} on that path). That deletes the drift class rather than adding four names to it.

#### `CATALOG-4` — ToolResult.analytics is written by ten handlers and read by nothing, under a comment claiming Bot Analytics reads it

MINOR · dead-config

**Files** — `backend/agent_core/tools/domain.py:12`, `backend/agent_core/tools/domain.py:43`, `backend/agent_core/tools/domain.py:53-72`, `backend/agent_core/tools/domain.py:503-505`, `backend/agent_core/tools/domain.py:544-546`, `backend/agent_core/tools/domain.py:565`, `backend/agent_core/tools/kb.py:499`, `backend/agent_core/tools/kb.py:809`, `backend/db_bot_analytics.py:124-129`

**Mechanism** — `ToolResult.analytics` is populated at ten sites. `to_llm()` (domain.py:57-72) does not include it; voice's `_announce` (voice/tools.py:454-475) ignores it; `bot_tools` returns `{**result.data}` and drops it; `mcp_tools` returns the handler payload. A repo-wide search for `.analytics` outside domain.py's own `__post_init__` guard returns zero read sites. Bot Analytics reads `commercial_events` / `activity_events` directly (db_bot_analytics.py:124-128). The class docstring (domain.py:12) advertises the field as one of three things "the caller can uniformly derive", and capture_lead carries thirteen lines of comment (domain.py:544-548) asserting "Bot Analytics reads this list, and claiming an upsell_presented whose row was never written makes the funnel disagree with the commercial-events table" — the careful `emitted=analytics` out-parameter threading through `db.create_lead` (domain.py:503-505) and the conditional append at :565 are load-bearing for no consumer.

**Trigger** — No runtime misbehaviour — the events themselves are written by `capture.*` inside the handlers. The defect is the false comment: the next person to change what `create_lead` emits will maintain a contract nobody has, and anyone auditing "how does the funnel know an offer was presented" is pointed at the wrong mechanism.

**Fix** — Either delete the field and the three comments that justify it, or give it the one consumer it claims: have voice's `_traced` / `CrmSink` and `bot_runtime` fold `result.analytics` into the `bot_tool_calls` audit row so a call's declared events can be reconciled against `commercial_events`. Do not leave the comment standing either way.

#### `CATALOG-5` — The "read-only" MCP surface writes a commercial event, un-attributed, with no offer-sourcing guard

MINOR · security

**Files** — `backend/mcp_tools.py:1-16`, `backend/mcp_tools.py:40-58`, `backend/mcp_tools.py:100-106`, `backend/mcp_tools.py:126`, `backend/mcp_tools.py:250-260`, `backend/agent_core/tools/catalog.py:26-35`, `backend/agent_core/tools/catalog.py:756-774`, `backend/agent_core/tools/domain.py:190-197`, `backend/agent_core/tools/domain.py:236-248`, `backend/agent_core/tools/domain.py:296-347`, `backend/capture.py:1526-1554`, `backend/voice/tools.py:1810-1813`, `backend/bot_tools.py:536-539`

**Mechanism** — catalog.py:24-35 and mcp_tools.py:1-16 both state the MCP surface is read-only ("Every mutating tool is excluded … until it does, it reads"). `check_product_eligibility` is on BOTH_AND_MCP (catalog.py:773) and its MCP handler (mcp_tools.py:97-104) calls `domain.check_product_eligibility` with `record_event` left at its default True, so `_check_and_record_eligibility` runs `capture.record_eligibility_checked` inside `db.engine.begin()` (domain.py:237-245) and emits an `eligibility_checked` commercial event (capture.py:1526-1554) — with `interaction_id=None` (so `entity_type="customer"`) and `actor_bot_id=None`. Separately, the MCP handler is the only one of the three that omits `domain.offer_sourcing_violation`, which voice (voice/tools.py:1808) and text (bot_tools.py:536-539) both apply before evaluating: an external agent can therefore probe every product id in the catalog against a named customer and each probe writes a row.

**Trigger** — An MCP client calls check_product_eligibility for customer C across the product list. Each call writes a commercial_events row attributed to no bot and joined to no interaction, inflating the eligibility-check leg of the offer funnel and leaving an unattributable audit trail; the bot_tool_calls audit row is only written when C has a prior interaction (mcp_tools.py:249-253).

**Fix** — Pass `record_event=False` from mcp_tools._check_product_eligibility (the parameter already exists — domain.py:200-206 documents it for capture_lead's re-check), or plumb an `actor` label through `record_eligibility_checked` so MCP-originated checks are distinguishable. Also state in the module docstring that this tool writes an analytics row, since "it reads" is currently false.

#### `CATALOG-6` — limit's declared maximum is enforced on voice only and is dropped from the wire schema on text

MINOR · shape-mismatch

**Files** — `backend/agent_core/tools/catalog.py:101-118`, `backend/agent_core/tools/catalog.py:119-135`, `backend/agent_core/tools/schema.py:72-79`, `backend/agent_core/tools/schema.py:104`, `backend/agent_core/tools/schema.py:141-152`, `backend/voice/tools.py:1133`, `backend/voice/tools.py:1164`, `backend/bot_tools.py:172-173`, `backend/bot_tools.py:181-182`, `backend/mcp_tools.py:86-87`, `backend/mcp_tools.py:96-97`

**Mechanism** — `get_payment_history.limit` declares minimum=1/maximum=20 and `get_emi_schedule.limit` minimum=1/maximum=24. `json_schema(strict=True)` explicitly drops minimum/maximum/default (schema.py:72-78), and `to_openai_tool` defaults to strict=True — so on WhatsApp, the sandbox and any strict text deployment the model never sees the bounds. The voice handlers clamp (`max(1, min(int(...), 20))`, voice/tools.py:1133/1164) but the text and MCP handlers do not: `int(args.get("limit") or 8)` then `ledger[:limit]` (bot_tools.py:172/181, mcp_tools.py:86/96). A negative limit is worse than unclamped — `list[:-1]` silently drops the most recent entry rather than erroring.

**Trigger** — A model that emits `limit: 500` on WhatsApp gets the customer's entire ledger into the turn (token cost, and more history than the tool's own description promises). A model that emits `limit: -1` gets the ledger minus its newest row, and nothing anywhere reports that a bound was violated.

**Fix** — Clamp in the two text handlers and the two MCP handlers the way voice does — or better, add a `ToolSpec.clamp_args()` next to `normalize_args` that applies minimum/maximum, and call it from all three dispatchers, since the strict renderer will keep hiding these constraints from the model.

#### `CATALOG-7` — Every WhatsApp dispute is filed as priority high; the same tool on voice files normal unless it is fraud

MINOR · bug

**Files** — `backend/bot_tools.py:270-292`, `backend/bot_tools.py:278`, `backend/agent_core/tools/domain.py:817-819`, `backend/voice/tools.py:1355-1364`

**Mechanism** — `domain.flag_dispute` derives priority as `high` only for `fraud` and `normal` otherwise (domain.py:817-819), and voice passes no priority at all (voice/tools.py:1360-1370) so it gets that rule. The text handler hardcodes `priority="high"` for every dispute (bot_tools.py:278). The catalog spec exposes no `priority` argument, so this is not an author or model choice — it is a per-channel constant.

**Trigger** — A customer raises the same `wrong_amount` grievance on WhatsApp and on the phone. The chat one lands on the disputes queue as high, the voice one as normal. Any SLA, sort order or workload split driven by `disputes.priority` treats channel as severity.

**Fix** — Drop `priority="high"` from bot_tools.py:278 and let domain.flag_dispute decide, so both channels file the same grievance at the same priority. If chat genuinely warrants an escalation, make it a documented rule inside domain.flag_dispute rather than a channel constant.

#### `CATALOG-8` — add_customer_note on text raises KeyError on a missing `text`, the exact hole the PTP handler was patched for

MINOR · bug

**Files** — `backend/bot_tools.py:341-343`, `backend/bot_tools.py:238-241`, `backend/bot_tools.py:834`, `backend/bot_tools.py:848-862`, `backend/agent_core/tools/schema.py:104-124`, `backend/agent_core/tools/schema.py:186-200`, `backend/agent_core/tools/catalog.py:529-534`, `backend/voice/tools.py:1629-1634`

**Mechanism** — Under strict function calling every property is listed in `required` and optionality is carried by a nullable type (schema.py:118-124); `normalize_args` then drops explicit nulls (schema.py:196-199). `_tool_create_promise` guards against exactly this (bot_tools.py:238-241, with a comment naming the failure), and the voice handler guards too (voice/tools.py:1633-1636 returns `empty_note`). `_tool_add_note` does not: `args["text"]` (bot_tools.py:342) raises KeyError, which falls to the generic handler at bot_tools.py:855-862 and returns `tool_failed:KeyError` — a code the model cannot act on, logged as a runtime failure rather than a correctable argument error.

**Trigger** — The model calls add_customer_note with `text: null` (or omits it on a non-strict deployment). The turn burns an iteration on an opaque `tool_failed:KeyError`, and the operator sees a KeyError traceback in the logs for what is a model argument mistake.

**Fix** — `body = str(args.get("text") or "").strip(); if not body: return {"ok": False, "error": "empty_note"}` — the same shape as voice/tools.py:1633-1636 and bot_tools.py:238-241.

#### `CATALOG-9` — An eval grader accepts a tool named record_optout that exists in no registry, and the catalog has no opt-out tool at all

MINOR · test-gap · **closed** in `3637d46` (pass 7)

**Files** — `backend/agent_core/eval/graders.py:285-308`, `backend/agent_core/eval/fixtures.py:299-307`, `backend/agent_core/cards/defaults.py:265`, `backend/post_call_actions.py:284-301`, `backend/post_call_actions.py:487`, `backend/agent_core/cards/compile.py:160`, `backend/agent_core/tools/catalog.py:393-433`

**Mechanism** — `grade_stops_after_opt_out` passes when `"record_optout" in names`, where `names` is the observed tool-call list (graders.py:299), and the shipped fixture `evt-ob-optout` asserts a pass using exactly that tool call (fixtures.py:303-306). `record_optout` is not in `CATALOG`, not in `voice/tools.py`'s registry, not in `bot_tools.HANDLERS`, and not in `mcp_tools.HANDLERS` — it is a post-call *action* verb (defaults.py:265, `PostCallRule(when="opt_out_requested", do=["record_optout", "stop_cadence"])`, executed by post_call_actions.py). No agent on any channel can emit it, and the catalog offers no in-call way to record an opt-out.

**Trigger** — The grader's tool-name half can never fire against a real trial, so only `fixture["optout_recorded"]` can ever satisfy it. The suite reads as covering "the agent wrote the opt-out" while it only covers "something, post-call, wrote it" — and the gap it papers over is real: a borrower who says "stop calling me" mid-call has no tool that records it before the Closer runs.

**Fix** — Drop the `record_optout` name from graders.py:299 and fixtures.py:305 so the grader keys only on `optout_recorded`; then decide separately whether an in-call opt-out tool belongs in the catalog (the honest answer given `set_contact_preference`'s `window_would_be_empty` branch at voice/tools.py:1774-1785, which already routes the caller toward one it cannot call).

#### `CATALOG-10` — _FLOW_CONTROL_TOOLS declares verify_identity, contradicting its own docstring and shadowing the catalog description everywhere

trivial · stale · DOWNGRADED · **closed** in `3637d46` (pass 7)

**Files** — `backend/flow_graph.py:766-775`, `backend/flow_graph.py:815-822`, `backend/agent_core/tools/catalog.py:188-211`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:159`, `Habibi/src/routes/agent-studio.skills.$skillId.tsx:13`

**Mechanism** — The dict's docstring says it holds "Flow-control tools that exist only inside `voice.tools.build_tools` and so are absent from the channel-agnostic `agent_core.tools.CATALOG`" (flow_graph.py:766-772). `verify_identity` (flow_graph.py:775) is in the catalog — it is `VERIFY_IDENTITY` at catalog.py:188-212, and grant.py:73-80 explains at length why it is a catalog tool. Because `entries.update(_FLOW_CONTROL_TOOLS)` runs after the catalog loop (flow_graph.py:822), the palette's description for verify_identity is the short flow-control string, not the catalog's "Verify caller identity before any account details are shared. Call only after the caller has spoken digits — never with placeholder text."

**Trigger** — The Tools tab (AgentCardPanels.tsx:159) and the skill editor's tool picker both render `t.description` as the authoritative statement of what the model is told. For this one tool — the gate every regulated write sits behind — they show a paraphrase that omits the "never with placeholder text" instruction that is actually in the prompt.

**Fix** — Remove the `verify_identity` entry from `_FLOW_CONTROL_TOOLS` (its 9 remaining entries are genuinely catalog-absent), and reverse the merge order or use `setdefault` so a catalog description can never be shadowed again.

#### `CATALOG-13` — capture_call_goal is the one voice handler that skips CATALOG.normalize, making its declared alias inert

trivial · stale

**Files** — `backend/voice/tools.py:628-637`, `backend/voice/tools.py:719`, `backend/agent_core/tools/catalog.py:167-180`, `backend/agent_core/tools/schema.py:186-200`

**Mechanism** — `CAPTURE_CALL_GOAL.goal_summary` declares `aliases=("goalSummary",)` (catalog.py:177). Every other voice handler opens with `args = CATALOG.normalize("<name>", args)` — twenty call sites, e.g. verify_identity at voice/tools.py:719 — but `_capture_call_goal_handler` reads `args.get("goal_summary")` directly (voice/tools.py:632). The alias therefore resolves on no channel: the tool is VOICE_ONLY, and voice is the only place it could have been applied.

**Trigger** — A model emitting `goalSummary` (the shape the legacy catalog published, which is why the alias exists) gets `empty_goal` and is told to "ask what they need, then call again" — a re-ask of a caller who already stated their goal. The Flows schema publishes only the canonical name, so this needs a model that drifts, not a normal turn; hence TRIVIAL.

**Fix** — Insert `args = CATALOG.normalize("capture_call_goal", args)` at voice/tools.py:632, matching every sibling. Alternatively drop the alias from the spec if the legacy shape can no longer appear.

#### `CATALOG-16` — No CRM write carries a timeout_secs while the one KB read does

trivial · bug · DOWNGRADED · **closed** in `3637d46` (pass 7)

**Files** — `backend/agent_core/tools/catalog.py:859`, `backend/agent_core/tools/schema.py:158-176`, `backend/voice/tools.py:1034-1040`, `backend/voice/tools.py:1268-1281`

**Mechanism** — `timeout_secs` is rendered into the Pipecat `FlowsFunctionSchema` only when set (schema.py:174-176), and `search_knowledge_base` is the only spec that sets it (catalog.py:859, 20s). Every CRM write — create_promise_to_pay, flag_dispute, request_callback, request_documents, capture_lead, apply_goodwill — runs `domain.*` inside `asyncio.to_thread` (e.g. voice/tools.py:1272-1281) with no declared bound, so a saturated connection pool or a lock wait holds the audio path for as long as the driver does. `cancel_on_interruption` is correctly left False on all of them (a write must not be cancelled mid-flight), so the timeout is the only available bound.

**Trigger** — Not demonstrated — I did not trace Pipecat Flows' own default handler timeout, so I cannot show that a hung `db.create_promise` produces unbounded dead air rather than a framework-level abort. The asymmetry itself is unambiguous: the cheapest read on the card has a ceiling and the money writes do not.

**Fix** — Confirm the FlowManager's default (pipecat.flows) first. If there is none, give the six write specs a generous `timeout_secs` (10-15s) so the model gets a failure it can speak around — `domain` already returns `crm_write_failed` with a spoken fallback for every one of them — instead of silence.

---

## Agent graph tab — handoffs and the handoff runtime

11 findings — 3 MAJOR, 7 MINOR, 1 trivial; 6 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-graph.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `GRAPH-1` — Doc vs code: a handoff never loads the receiving card's prompt, tools or flow on either channel

**MAJOR** · doc-vs-code · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `CONTEXT.md:46-48`, `backend/agent_core/tools/grant.py:15-18`, `backend/agent_core/tools/grant.py:168-175`, `backend/agent_core/cards/routing.py:12-16`, `backend/voice/tools.py:2789-2808`, `backend/bot_tools.py:448`, `backend/bot_runtime.py:712-714`, `backend/bot_runtime.py:933`, `backend/bot_runtime.py:947`, `backend/db_inbox.py:1479-1501`, `backend/voice/mesh.py:126-152`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:754`

**Mechanism** — CONTEXT.md:47-48 defines Handoff as a transfer where 'the receiving agent brings its own card, and therefore its own grant', and grant.py:168-175 says the receiving bundle 'is resolved by bot id and handed straight here'. No caller does this. Voice: the handler returns (result.to_llm(), None) so no node change, the same FlowManager/tools/prompt continue, and BOT_TO_MESH_ROLE only mutates voice/mesh active_role, which nothing reads to change tools or prompt (mesh.py:126-152; only status() and mesh_bus publish it). WhatsApp: bot_tools.py:448 sets ctx.bot_id = target for the remainder of one turn, but the next turn's bundle is load_active_bundle(bot_id=_bot_id()) (bot_runtime.py:712-714) and ToolContext.bot_id/agent_card are rebuilt from env BOT_ID and that bundle (:933, :948); interactions.handler_bot_id (the only durable write, db_inbox.py:1484) is read by analytics/QA/canary/compliance only. The graph tab's 'handoff' reachability lozenge ('Reached mid-conversation from a live card's allowlist', AgentCardPanels.tsx:754; index.tsx:64-68) therefore describes a bookkeeping write, not a change of agent.

**Trigger** — Operator allows Insurance on the Collections card, publishes, and a caller asks for insurance; the model calls handoff_to_agent, the interaction is re-attributed to insurance-v1, but the caller keeps talking to the Collections prompt with the Collections tool set (voice) or the BOT_ID card (WhatsApp).

**Fix** — Either implement the transfer (voice: on ok result return the target card's entry node built from load_active_bundle(bot_id=target) with ToolGrant.for_bundle; text: resolve the bundle by interactions.handler_bot_id instead of env BOT_ID at bot_runtime.py:712-714) or rewrite CONTEXT.md:47-48, grant.py:13-18/172-175, routing.py:12-16 and the two UI help strings to say a handoff re-attributes the interaction and does not change the running agent.

#### `GRAPH-2` — Voice handoff allowlist reads the built-in card constants, not the published card, and disables itself on clone-card deployments

**MAJOR** · security · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/voice/tools.py:2781-2788`, `backend/voice/tools.py:278-305`, `backend/agent_core/tools/domain.py:1026-1032`, `backend/agent_core/cards/defaults.py:342-346`, `backend/db_inbox.py:1457-1460`, `backend/bot_tools.py:400-429`, `backend/voice/bot.py:444-448`, `backend/voice/flows_dynamic.py:414-424`

**Mechanism** — voice/tools.py:2786 builds the allowlist from card_for(bot_id).handoff_targets() — the Python constants in defaults.py — and on KeyError (any non-first-party bot_id, i.e. every cloned card, since bot_id comes from the bundle at bot.py:444-448) sets allowlist=None, which domain.handoff_to_agent:1027 treats as unrestricted. build_tools (:278-305) is never given the bundle's agentCard, so an operator removing Insurance from kaia's card in the Agent graph tab and publishing has no effect on voice (card_for still lists it), while the mesh pre_action right next to it does consult bundle['agentCard'] (bot.py:1524). The text channel fixed exactly this bug in bot_tools.py:400-429 ('resolution order is live card → built-in card → deny'); voice still has the pre-fix behaviour.

**Trigger** — Publish a cloned card (e.g. Lapse Specialist) with handoffs=[kaia-v2-4] to a voice deployment; the model can hand off to any bot id, including supervisor-brief or another tenant's bot. Or: remove Insurance from the Collections allowlist in the graph tab, publish, and voice still allows the hop.

**Fix** — Pass bundle.get('agentCard') into build_tools (or onto ToolState) and mirror bot_tools._handoff_allowlist: parse the live card first, fall back to card_for, and return set() (deny) rather than None when neither resolves.

#### `GRAPH-3` — The `when` condition is stored but never reaches the model; the tab tells the author it is 'guidance for the model'

**MAJOR** · dead-config · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:669-673`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:705-712`, `backend/agent_core/tools/catalog.py:577-596`, `backend/agent_core/cards/schema.py:123`, `backend/agent_core/cards/defaults.py:167-168`, `backend/agent_core/cards/defaults.py:288-289`

**Mechanism** — The only editor for handoffs writes `when` (AgentCardPanels.tsx:705-712) and the help text says 'The condition is guidance for the model, not a rule the runtime enforces'. But handoff_to_agent's description and target_bot_id/reason/payload descriptions are static strings (catalog.py:570-593); CATALOG.get(name).to_flows_schema (voice/tools.py:419) and CATALOG.openai_tools (bot_runtime.py:949) render those, and a repo-wide search finds no reader of card.handoffs[].when — compile.py:394's `.when` is PostCallRule. The model is never told which specialist exists or when to hand off; the default cards' when texts ('in-policy upsell after PTP', 'collections intent') are decorative.

**Trigger** — Author types a when condition, saves and publishes; behaviour is identical with the field empty. The operator reasonably believes they have steered routing.

**Fix** — Either inject the card's handoffs into the offered tool (e.g. build target_bot_id's ArgSpec enum/description from card.handoffs at offer time, or append a 'Handoffs: <to_bot_id> — <when>' block to the system prompt), or change the UI copy to say the condition is documentation only and is not shown to the model.

#### `GRAPH-10` — Intake's HumanGate on handoff_to_agent (require identity) has no enforcer

MINOR · dead-config

**Files** — `backend/agent_core/cards/defaults.py:171`, `backend/agent_core/cards/schema.py:389`, `backend/voice/tools.py:2773-2808`, `backend/bot_tools.py:432-449`

**Mechanism** — The Intake card declares HumanGate(tool_name='handoff_to_agent', require='identity'), but a repo-wide search for human_gates finds only schema.py:389 and defaults.py; neither handoff handler checks verification state before transferring. An unverified caller can be re-attributed to another card.

**Trigger** — Run intake-v1 and call handoff_to_agent before verify_identity.

**Fix** — Enforce card.human_gates in bot_tools.execute_tool / voice _traced (deny with a spoken_summary when require='identity' and session is unverified), or remove the field until a consumer exists.

#### `GRAPH-4` — payload_schema has no editor and no reader; the handoff `payload` argument is dropped on the floor

MINOR · dead-config · **closed** in `6089743` (pass 7)

**Files** — `backend/agent_core/cards/schema.py:122`, `Habibi/src/api/agent-card.ts:158`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:600-609`, `backend/agent_core/tools/catalog.py:588-592`, `backend/db_inbox.py:1479-1509`, `backend/agent_core/tools/domain.py:1071-1080`

**Mechanism** — CardHandoff.payload_schema exists in the schema and TS type, the graph editor only spreads it through (:607-609) and nothing in the backend validates the tool's `payload` against it or reads it at all. The `payload` arg ('Compact JSON context for the receiving card', catalog.py:591) is stringified, passed to db_inbox.handoff_to_agent, echoed in the return dict (:1507) and then discarded: the UPDATE (:1479-1492) and _activity row (:1493-1501) do not store it, and domain.py:1071-1080 does not surface it either. No receiving card exists to consume it (GRAPH-1).

**Trigger** — Any handoff call with payload; nothing downstream can recover it. Any payload_schema on a card is inert.

**Fix** — Drop payload_schema from the schema/TS type (bump schema_version) or persist `payload` into the activity row / a handoff_payloads column and validate it against payload_schema in domain.handoff_to_agent.

#### `GRAPH-5` — A handoff to an archived (or other-tenant) bot passes G5 and is invisible and unremovable in the editable allowlist

MINOR · bug · **closed** in `a91d371` (pass 7)

**Files** — `backend/db_inbox.py:1511-1514`, `backend/db_prompt_studio.py:842`, `backend/agent_core/cards/compile.py:665`, `backend/main.py:2284-2291`, `backend/db_prompt_studio.py:326`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:685-687`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:611-615`, `backend/db_inbox.py:1458-1459`

**Mechanism** — G5's known_bot_ids is list_bot_ids() = `SELECT id FROM bots` with no archived_at and no tenant predicate, so a handoff to a retired card (or another tenant's bot id) passes the gate. The graph endpoint's nodes come from list_agent_studio_cards() with include_archived=False (:2291, :326), so the archived target has no node; the editable UI renders rows only for nodes (:685-687), so the stale edge is not listed and has no Remove button, while legalTargets (:615) still treats it as a legal walk. At runtime db_inbox.handoff_to_agent:1459 also accepts the archived bot, so the hop is a no-op re-attribution to a card that takes no traffic. Reachability correctly excludes archived cards' edges, so the two vocabularies disagree about the same edge.

**Trigger** — Allow a cloned card as a target, archive that clone on the fleet index, return to the source card's graph tab: the edge vanishes from the editor, compile stays green, and the published card keeps a dead handoff.

**Fix** — In compile_agent_studio_card pass known_bot_ids filtered to non-archived bots of the current tenant (or add an archived_at IS NULL / tenant predicate to list_bot_ids), and have the graph tab render card handoffs whose target is not a node as a removable 'unknown/retired target' row.

#### `GRAPH-6` — Graph tab renders a failed or pending /graph fetch as an empty allowlist

MINOR · degradation-lie

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:585-589`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:684-725`, `Habibi/src/api/agent-studio.ts:322-340`

**Mechanism** — useAgentGraph's isPending/isError are never read (the component only destructures data at :588). On error or while loading, nodes=[] so the chip row and the 'Handoff allowlist' list render empty, the hint reads 'Select a card above…', and if the card has no handoffs the dashed box asserts 'No handoffs on this card. Every conversation stays on <bot>' — a statement of fact made without data. A card with handoffs shows chips-less edges and no target rows, so Remove is unavailable with no explanation.

**Trigger** — API down, 404 for the bot, or the first render before the query resolves.

**Fix** — Branch on graphQuery.isPending (skeleton) and graphQuery.isError (inline error with retry) before rendering the node list, as commit 01d1fec did for list reads elsewhere.

#### `GRAPH-7` — handoff_to_agent is granted to the Collections card but never offered on any node of the built-in voice flow

MINOR · disconnected · **closed** in `a91d371` (pass 7)

**Files** — `backend/agent_core/cards/defaults.py:67`, `backend/agent_core/cards/defaults.py:91`, `backend/agent_core/cards/defaults.py:113`, `backend/voice/tools.py:2911`, `backend/voice/flows.py:922-932`, `backend/voice/flows_dynamic.py:414-424`, `backend/flow_graph.py:805-821`

**Mechanism** — The three customer-facing default cards include handoff_to_agent and voice/tools.py registers it (:2911), but voice/flows.py builds every node's functions by explicit name through _fns(tools, ...) and the global_functions list (:922-932) names five tools; the string handoff_to_agent does not appear anywhere in flows.py. Only an authored graph can offer it (flow_graph.tool_catalog includes voice-channel catalog tools, :817-821). On the shipped script the graph tab's 'Legal walk' can never be exercised by voice, and the mesh hop (bot.py:1519-1544) is the only in-call specialist path — a hardcoded flow action, not a card-driven handoff.

**Trigger** — Publish kaia with the built-in flow (flow={}); on a live call the model has no handoff tool despite the Tools tab and graph tab showing it.

**Fix** — Offer handoff_to_agent on the hub/position nodes (or globally) when the card lists at least one handoff, or make the graph tab state that handoffs are only offerable from an authored flow node.

#### `GRAPH-8` — Text sandbox evaluates the handoff allowlist against kaia's card, not the card under test

MINOR · bug

**Files** — `backend/sandbox_runtime.py:206`, `backend/sandbox_runtime.py:219-228`, `backend/bot_tools.py:416-424`, `backend/agent_core/tools/domain.py:1026-1038`

**Mechanism** — run_tools receives agent_card (:206) but the ToolContext is built with bot_id=db.DEFAULT_BOT_ID and never sets ctx.agent_card (:219-230). _handoff_allowlist therefore falls to card_for(DEFAULT_BOT_ID) — the Collections constants — regardless of which card the sandbox is running. A Lapse clone whose only handoff is kaia-v2-4 gets handoff_not_allowlisted (allowlist check precedes the no_interaction check at domain.py:1027 vs :1034), while a card that removed Insurance still sees the hop allowed.

**Trigger** — Open the sandbox for a cloned card and ask to be transferred to Collections.

**Fix** — Set ctx.agent_card = agent_card and ctx.bot_id = the card's identity.bot_id in sandbox_runtime.run_tools, the same way bot_runtime.py:948 does.

#### `GRAPH-9` — Tool-driven voice handoff flips the mesh role without publishing it; the flow pre_action does both

MINOR · disconnected

**Files** — `backend/voice/tools.py:2800-2806`, `backend/voice/mesh.py:129-133`, `backend/voice/bot.py:1115-1121`, `backend/voice/bot.py:1528-1534`, `backend/voice/mesh_bus.py:114-158`

**Mechanism** — voice/tools.py:2805 calls voice_mesh.activate_role directly, so no mesh.role event is published and no BusActivateWorkerMessage reaches the insurance LLMWorker sidecar, whereas the two flow-driven paths (bot.py:1115, :1528) go through mesh_bus.activate_and_publish with customer/interaction/bot ids. Under Redis the sidecar and Floor observers therefore see handoffs made by the flow but not those made by the model calling handoff_to_agent; under local bus neither path changes behaviour (GRAPH-1).

**Trigger** — VOICE_MULTI_AGENT_ENABLED=true with REDIS_URL; the model calls handoff_to_agent(insurance-v1) — mesh.status() shows insurance but the sidecar never activates.

**Fix** — Use mesh_bus.activate_and_publish(role, session_id=..., customer_id=session.customer_id, interaction_id=session.interaction_id, bot_id=bot_id) in _handoff_to_agent_handler, or delete the mesh flip there since it has no consumer.

#### `GRAPH-11` — whenDraft shadows the saved `when` after Remove/Allow or an external draft change

trivial · bug

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:587`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:705-712`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:714-721`

**Mechanism** — whenDraft is per-target local state that is never cleared; the input value is `whenDraft[n.id] ?? on.when`, so after Remove then Allow the old text reappears (and Allow at :718 writes it back), and if the draft is discarded/restored while the graph tab stays mounted the input keeps showing text the card no longer holds until the next blur rewrites it.

**Trigger** — Type a when, Remove, Allow again; or Discard draft with the graph tab open.

**Fix** — Delete whenDraft[n.id] in setHandoff (on remove and on blur commit) and key the input on the card's when.

---

## Sandbox — parity between what you test and what you ship

16 findings — 5 MAJOR, 9 MINOR, 2 trivial; 6 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-sandbox.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `SANDBOX-01` — Test in Sandbox executes zero tools — the Tool Grant is never exercised, and SANDBOX_TEXT_TOOLS cannot turn it on

**MAJOR** · disconnected · prior: none · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/sandbox_runtime.py:852`, `backend/sandbox_runtime.py:843`, `backend/sandbox_runtime.py:190`, `backend/schemas.py:2532`, `backend/schemas.py:2580`, `backend/main.py:3446`, `Habibi/src/api/sandbox.ts:309`, `Habibi/src/routes/sandbox.lazy.tsx:279`, `backend/.env.example:378`

**Mechanism** — The text tool loop runs only when `_sandbox_tools_enabled(...) and customer_id` (backend/sandbox_runtime.py:852). `customer_id` is read from `context["customerId"] / context["customer_id"] / payload["customerId"]` (backend/sandbox_runtime.py:843-848). None can ever be present: `SandboxContext` is `extra="forbid"` and declares no customerId field (backend/schemas.py:2532-2543), `SandboxTurnCreateRequest` is `extra="forbid"` (backend/schemas.py:2580) so a top-level customerId 422s, and the only client never sends `context` at all (Habibi/src/routes/sandbox.lazy.tsx:279-286 omits it; Habibi/src/api/sandbox.ts:305-311 then posts context:null, which backend/main.py:3446-3450 pops). `SANDBOX_TEXT_TOOLS=true` (backend/.env.example:378, read at backend/sandbox_runtime.py:191) is ANDed with the same unreachable customer_id, so the documented switch is inert. `_run_sandbox_tool_loop` (backend/sandbox_runtime.py:197-364) — the Tool Grant via mouth.tools(), the catalog execution, the identity-verification path in bot_tools, the bot_tool_calls audit — is dead code from the HTTP surface.

**Trigger** — Open any card in Prompt Studio, click Test in Sandbox, send any customer turn. The reply is a plain chat completion with no tools offered. A card whose entire value is create_promise_to_pay / get_customer_context / handoff_to_agent rehearses green having called none of them.

**Fix** — Add `customerId` to SandboxContext (backend/schemas.py:2532) and have the sandbox bind the scenario persona to a CRM row the way the voice path already does (backend/voice_sandbox.py:129-165), then pass it from Habibi/src/routes/sandbox.lazy.tsx:279. Until then the header should say tools are off rather than implying a full rehearsal.

#### `SANDBOX-02` — Every sandbox turn renders the prompt with the default context, not the scenario persona

**MAJOR** · bug · prior: none · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/sandbox_runtime.py:529`, `backend/sandbox_runtime.py:531`, `backend/sandbox_runtime.py:643`, `backend/sandbox_runtime.py:818`, `backend/agent_core/turn.py:55`, `backend/agent_core/prompt.py:38`, `Habibi/src/api/sandbox.ts:116`, `Habibi/src/api/sandbox.ts:248`, `Habibi/src/api/sandbox.ts:309`, `Habibi/src/routes/sandbox.lazy.tsx:279`

**Mechanism** — `create_sandbox_run` builds the persona context (backend/sandbox_runtime.py:529, from Habibi/src/api/sandbox.ts:112-122 contextFromPersona) and uses it only to render the opening template (backend/sandbox_runtime.py:531); it is returned to the client but never written to sandbox_runs. `append_sandbox_turn` then passes `payload.get("context")` (backend/sandbox_runtime.py:818), which the client never sends, so `assemble_turn_messages` falls through to `default_context(None)` (backend/agent_core/turn.py:55 → backend/agent_core/prompt.py:38-50): customer_name "Customer", account_no "XXXX", overdue_amount "0", due_date "". The untrusted CRM developer card (backend/agent_core/turn.py:83-86) carries those placeholders too.

**Trigger** — Run the "Rahul Sharma, ₹62,400 overdue, 47 DPD" scenario. The PersonaCard shows Rahul and the amount; the model is told it is talking to "Customer" with ₹0 outstanding, so every rehearsal of a prompt that references {overdue_amount} or {customer_name} tests the empty case.

**Fix** — Persist the run context (a jsonb column on sandbox_runs, or re-render from the scenario persona in append_sandbox_turn) and feed it into assemble_turn_messages instead of the per-turn payload.

#### `SANDBOX-06` — Tuning presets are a second, drifted copy in the browser; the server endpoint that exists to prevent this has no caller

**MAJOR** · stale · prior: none · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `Habibi/src/components/sandbox/TuningStudio.tsx:112`, `Habibi/src/components/sandbox/TuningStudio.tsx:198`, `Habibi/src/data/agent-tuning.ts:107`, `Habibi/src/data/agent-tuning.ts:136`, `Habibi/src/data/agent-tuning.ts:149`, `Habibi/src/data/agent-tuning.ts:162`, `backend/agent_core/tuning.py:62`, `backend/agent_core/tuning.py:73`, `backend/agent_core/tuning.py:85`, `backend/agent_core/tuning.py:95`, `backend/agent_core/tuning.py:107`, `backend/agent_core/tuning.py:158`, `backend/main.py:3466`, `Habibi/src/api/voice-sandbox.ts:67`

**Mechanism** — TuningStudio reads only the hardcoded `AGENT_TUNING_PRESETS` (Habibi/src/components/sandbox/TuningStudio.tsx:112 and the picker at 198-219); `fetchTuningPresets` (Habibi/src/api/voice-sandbox.ts:67-76) and `GET /sandbox/tuning/presets` (backend/main.py:3466-3470 → backend/agent_core/tuning.py:158-163) have no caller anywhere in Habibi/src. The two copies have drifted: default preset idle_timeout_secs 6.0 (Habibi/src/data/agent-tuning.ts:107) vs 12.0 server-side, where the 12.0 carries an explicit incident note about 6.0 firing inside normal thinking time on call VS-6B252E0479 (backend/agent_core/tuning.py:54-62); brisk-verification idle 5 vs 10 and frequency_penalty left at 0.3 vs 0.1 (Habibi/src/data/agent-tuning.ts:136 vs backend/agent_core/tuning.py:73, 85); firm-legal idle 8 vs 15, frequency_penalty 0.5 vs 0.4, tts style "empathetic" vs "serious" (Habibi/src/data/agent-tuning.ts:149-162 vs backend/agent_core/tuning.py:95-107). The endpoint also returns no `summary` field although the client's type demands one (backend/agent_core/tuning.py:160 vs Habibi/src/api/voice-sandbox.ts:68), which is why nothing ever wired it up.

**Trigger** — Pick "Empathetic-collections" in the Tuning Studio and start a Live call: the agent runs a 6-second idle timeout — the value the backend reverted after a production incident — and Promote then writes it into the production deployment (see SANDBOX-08).

**Fix** — Delete AGENT_TUNING_PRESETS as a source of truth, add `summary` to backend/agent_core/tuning.py:158 list_presets, and load presets through the existing endpoint. Keep the client constant only as an offline/mock fallback.

#### `SANDBOX-07` — The voice sandbox overwrites the version's authored tuning with a tuning object the browser built

**MAJOR** · bug · prior: none · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/voice/bot.py:411`, `backend/voice/bot.py:418`, `backend/agent_core/tuning.py:354`, `backend/voice_sandbox.py:179`, `Habibi/src/components/sandbox/voice/useSandboxLiveCall.ts:237`, `Habibi/src/routes/sandbox.lazy.tsx:176`, `Habibi/src/data/agent-tuning.ts:230`

**Mechanism** — voice/bot.py first sets bundle["tuning"] from the prompt version (backend/voice/bot.py:412-416), then merges the session tuning over it (backend/voice/bot.py:418-423). `merge_tuning_delta` deep-merges and re-normalizes (backend/agent_core/tuning.py:354-356), so a COMPLETE tuning object wins on every key. The session tuning is exactly that: voice_sandbox normalizes whatever the browser posted (backend/voice_sandbox.py:172) and the page always posts a full object (Habibi/src/components/sandbox/voice/useSandboxLiveCall.ts:234-239), built by `tuningFromVoiceConfig(activePrompt.voice, DEFAULT_AGENT_TUNING)` (Habibi/src/routes/sandbox.lazy.tsx:176-180 → Habibi/src/data/agent-tuning.ts:231-261), which derives only tts voice/rate/pitch/style from the version and takes llm, stt, vad, turn and interaction wholesale from the browser default.

**Trigger** — Publish a card with a tuned llm.temperature / vad.start_secs / interaction.idle_timeout_secs, then Live-rehearse the same version: the call runs the browser defaults, not the authored values. The version's tuning is never audible in the sandbox.

**Fix** — Send only the operator's actual deltas (the Tuning Studio already tracks them for the live-apply path) rather than a full object, or seed the panel from the resolved bundle's tuning instead of DEFAULT_AGENT_TUNING.

#### `SANDBOX-08` — Promote from the Sandbox ships a different deployment than Publish from Prompt Studio, for the same version

**MAJOR** · bug · prior: none · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `Habibi/src/routes/sandbox.lazy.tsx:442`, `Habibi/src/routes/sandbox.lazy.tsx:659`, `backend/db_prompt_studio.py:2002`, `backend/db_prompt_studio.py:2012`, `backend/db_prompt_studio.py:2020`, `backend/agent_core/tuning.py:387`, `backend/voice/bot.py:579`, `backend/sandbox_runtime.py:763`

**Mechanism** — `promote()` posts the browser's tuning state (Habibi/src/routes/sandbox.lazy.tsx:442-455). In publish_prompt_version that takes the "Sandbox Promote — Tuning Studio payload is authoritative" branch (backend/db_prompt_studio.py:2001-2003), which SKIPS `apply_voice_config_overlay` — the step the Prompt Studio path runs to fold the Voice tab's speed / pitch / warmth and the provider `params` bag into tts (backend/db_prompt_studio.py:2004-2018). The promoted deployment therefore loses the Voice tab's prosody and provider params, and prompt_versions.tuning is overwritten with the browser's values (backend/db_prompt_studio.py:2019-2028). Compounding it, the PromoteDialog advertises "temp {tuning.llm.temperature}" (Habibi/src/routes/sandbox.lazy.tsx:659) as though that number was rehearsed, but text turns read temperature from prompt_versions.tuning (backend/sandbox_runtime.py:766-770), not from the panel — in text mode the slider is inert.

**Trigger** — Set the Voice tab's warmth/speed/params in Prompt Studio, rehearse in the text sandbox, hit Promote: the shipped deployment has different prosody and no provider params than the one the Publish button would have produced from the identical version, and the temperature shown on the confirm dialog was never used by a single turn.

**Fix** — Run apply_voice_config_overlay on the promote branch too (or make promote send only the deltas the operator moved), and either wire the panel's llm section into the text turn or disable it outside Live mode.

#### `SANDBOX-03` — The sandbox never runs the flow graph the operator authored — publish ships it, the rehearsal does not

MINOR · disconnected · DOWNGRADED · prior: none

**Files** — `backend/sandbox_runtime.py:706`, `backend/bot_runtime.py:1`, `backend/voice/bot.py:1172`, `backend/agent_core/deployment.py:125`, `Habibi/src/routes/prompt-studio.lazy.tsx:1074`

**Mechanism** — `flow` occurs zero times in backend/sandbox_runtime.py. The draft the button saves carries `flow` (Habibi/src/routes/prompt-studio.lazy.tsx:1072) and resolve_prompt_bundle returns it (backend/agent_core/deployment.py:120), but the text sandbox loads the version with db.get_prompt_version and reads only prompt / persona / guardrails / tuning / agentCard (backend/sandbox_runtime.py:698-770). The live voice runtime checks `voice_uses_authored_flow(bundle["flow"])` and builds the node graph (backend/voice/bot.py:1170-1176). So node transitions, per-node tool restrictions and terminal nodes are untested by the surface named "Test in Sandbox".

**Trigger** — Author a flow in the canvas (verify → disclose → negotiate), click Test in Sandbox, and the run is a single free-form prompt loop. The flow is exercised for the first time in production, or in Live mode only.

**Fix** — Either run the authored flow in the text sandbox (the flow engine is channel-agnostic enough to drive a text turn), or label the text tab "prompt + retrieval only" and route flow rehearsal to Live mode explicitly.

#### `SANDBOX-04` — The sandbox tells a voice card it is in a chat thread and must never disclose recording, then flags it for not disclosing

MINOR · degradation-lie · DOWNGRADED · prior: none

**Files** — `backend/agent_core/turn.py:75`, `backend/agent_core/prompt.py:145`, `backend/agent_core/prompt.py:74`, `backend/agent_core/prompt.py:116`, `backend/sandbox_runtime.py:756`, `backend/agent_core/guardrails.py:240`, `backend/seed_postgres.py:1358`, `backend/alembic/versions/20260722_0019_sandbox_scenarios_seed.py:47`

**Mechanism** — `assemble_turn_messages` calls `build_system_prompt` without a channel (backend/agent_core/turn.py:75-81), so it defaults to "text" (backend/agent_core/prompt.py:145). That drops the alwaysDiscloseRecording rule from the rendered guardrails (backend/agent_core/prompt.py:74-75) AND injects the channel framing "You are messaging this customer in a written chat thread. This is NOT a phone call ... never state a call-recording disclosure even if an instruction above tells you to always disclose one" (backend/agent_core/prompt.py:116-123). The same turn then calls evaluate_guardrails with the card's guardrails (backend/sandbox_runtime.py:900-916), which raises `missing-recording-disclosure` from turn index 1 (backend/agent_core/guardrails.py:22, 240-243) when the bot obeys the instruction the sandbox just gave it.

**Trigger** — Rehearse a voice card with alwaysDiscloseRecording on, using a scenario whose openingBot does not contain the disclosure (the seed has such scenarios — see backend/tests/test_sandbox_disclosure_and_grounding.py:33 GREETING_THAT_DOES_NOT). Turn 1 comes back red with a compliance flag against a prompt that is correct for the channel it will actually ship on.

**Fix** — Pass the card's real channel into build_system_prompt from the sandbox (voice cards render the voice framing), and gate the missing-recording-disclosure check on the same channel so the instruction and the assertion cannot contradict each other.

#### `SANDBOX-05` — Every sandbox run halts at 3 customer turns; the live text path computes the same max-turns flag and throws it away

MINOR · bug · DOWNGRADED · prior: none

**Files** — `backend/sandbox_runtime.py:366`, `backend/sandbox_runtime.py:712`, `backend/sandbox_runtime.py:948`, `backend/bot_runtime.py:851`, `backend/bot_runtime.py:816`, `backend/agent_core/guardrails.py:222`, `Habibi/src/routes/sandbox.lazy.tsx:466`

**Mechanism** — `_HARD_MAX_TURNS` defaults to 3 (backend/sandbox_runtime.py:366) and `effective_max = min(3, card.maxTurns)` (backend/sandbox_runtime.py:712, re-checked under the row lock at 948). Exceeding it raises `sandbox_max_turns:3` → HTTP 409, and evaluate_guardrails independently appends `max-turns` (backend/agent_core/guardrails.py:221-225) which should_halt treats as terminal (backend/agent_core/guardrails.py:251-263), so the run is marked completed. The live text runtime calls evaluate_guardrails and only ever inspects the result for "auto-escalate" (backend/bot_runtime.py:816-825) — max-turns never stops a production conversation. The frontend hardcodes the same 3 as a literal (Habibi/src/routes/sandbox.lazy.tsx:466), so raising SANDBOX_HARD_MAX_TURNS desyncs the header counter.

**Trigger** — Author maxTurns=12 in the Guardrails tab and rehearse: the sandbox halts on exchange 3 with a max-turns guardrail the operator did not configure, and there is no way to test turn 4 onwards — where handoffs, escalations and long negotiations actually live.

**Fix** — Separate the cost ceiling from the guardrail: keep a budget cap that reports itself as "sandbox budget reached", not as a guardrail flag, and let the card's maxTurns be the value under test. Read the ceiling from one place (server) rather than duplicating 3 in the client.

#### `SANDBOX-09` — The sandbox tool loop runs as DEFAULT_BOT_ID and never sets ctx.agent_card, so the handoff allowlist would be the wrong card's

MINOR · security · prior: none

**Files** — `backend/sandbox_runtime.py:219`, `backend/sandbox_runtime.py:224`, `backend/bot_tools.py:416`, `backend/bot_tools.py:424`, `backend/bot_runtime.py:947`

**Mechanism** — `_run_sandbox_tool_loop` builds ToolContext with `bot_id=db.DEFAULT_BOT_ID` (backend/sandbox_runtime.py:224) and never assigns `ctx.agent_card`, although it has the card in hand (it passes the same dict to resolve_mouth at backend/sandbox_runtime.py:214). `_handoff_allowlist` therefore skips the live-card branch (backend/bot_tools.py:416-419) and falls back to `card_for(DEFAULT_BOT_ID)` (backend/bot_tools.py:423-429) — kaia's built-in constant card — where the live text runtime sets it explicitly with the comment "the handoff allowlist belongs to the card this turn is running" (backend/bot_runtime.py:947). Every tool audit row and actor_bot_id would also be attributed to kaia.

**Trigger** — Latent while SANDBOX-01 keeps the loop unreachable. The moment tools are enabled for a non-default card, its handoff targets are enforced against kaia's list and its tool calls are logged under kaia's bot id.

**Fix** — Set `ctx.agent_card = version.get("agentCard")` and `bot_id = version.get("botId") or db.DEFAULT_BOT_ID` in backend/sandbox_runtime.py:219-231, mirroring backend/bot_runtime.py:947.

#### `SANDBOX-10` — The sandbox tool loop has no load_skill activation — progressive disclosure cannot be rehearsed

MINOR · bug · prior: none

**Files** — `backend/sandbox_runtime.py:214`, `backend/sandbox_runtime.py:276`, `backend/bot_runtime.py:1023`, `backend/bot_tools.py:739`

**Mechanism** — The live text runtime, after a successful load_skill, appends the skill body as a developer message and recomputes the offered tool list from the activated mouth (backend/bot_runtime.py:1023-1038). The sandbox loop does neither: `tools` is computed once before the loop (backend/sandbox_runtime.py:214-218) and the tool-result branch (backend/sandbox_runtime.py:281-322) only appends the JSON result. `_tool_load_skill` deliberately strips the body from its return value (backend/bot_tools.py:739-750) because the caller is expected to inject it, so in the sandbox the model gets `{"ok": true, "body_loaded": true}` and no instructions.

**Trigger** — Latent behind SANDBOX-01. Once tools are on, a card whose ptp-negotiate tools only appear after activating the skill would rehearse with a narrower tool list and no skill instructions than the one publish ships.

**Fix** — Lift the load_skill branch out of backend/bot_runtime.py:1023-1038 into a shared helper and call it from both loops.

#### `SANDBOX-11` — The sandbox skill picker offers the whole global library and silently no-ops a slug the card does not carry

MINOR · degradation-lie · prior: 4.7

**Files** — `Habibi/src/routes/sandbox.lazy.tsx:609`, `backend/sandbox_runtime.py:829`, `backend/agent_core/skills/runtime.py:168`, `backend/agent_core/skills/runtime.py:236`, `Habibi/src/routes/agent-studio.skills.$skillId.tsx:196`

**Mechanism** — The dropdown is populated from `skillsQuery.data`, the full catalog returned by /agent-studio/skills (Habibi/src/routes/sandbox.lazy.tsx:609), not from the card's attached skills. `resolve_mouth(..., active_slug=slug).prompt()` returns `body_message=None` when the slug is not among the card's packs (backend/agent_core/skills/runtime.py:168-173) and the sandbox inserts nothing (backend/sandbox_runtime.py:829-836). Nothing tells the operator. Separately, an operator-pinned slug overrides intent-based activation for every turn (backend/agent_core/skills/runtime.py:230-234) — live only activates on intent match or an explicit load_skill call, so pinning also rehearses an activation pattern production will not produce.

**Trigger** — Open the sandbox from an insurance skill's detail page (Habibi/src/routes/agent-studio.skills.$skillId.tsx:194-203) against a card that does not attach it: the header shows the skill selected, the run is green, and the skill body was never in the prompt.

**Fix** — Filter the picker to the selected card's attached skills, and surface "not attached to this card" when a search param names one that is not.

#### `SANDBOX-12` — The sandbox's opening turn is scenario fixture text, not the card's greeting — and it is what satisfies the recording-disclosure check

MINOR · bug · prior: none

**Files** — `Habibi/src/routes/sandbox.lazy.tsx:238`, `backend/sandbox_runtime.py:531`, `backend/sandbox_runtime.py:756`, `backend/seed_postgres.py:1358`, `backend/voice/bot.py:1172`

**Mechanism** — `openingTemplate` is the scenario seed's `openingBot` (Habibi/src/routes/sandbox.lazy.tsx:238), rendered and persisted as bot turn 0 (backend/sandbox_runtime.py:531, 606-628). That fixture text is then scanned to decide whether the run has already made its recording disclosure (backend/sandbox_runtime.py:756-761). Publish ships the flow's first node or the authored prompt's own greeting (backend/voice/bot.py:1170-1176), which the sandbox never renders.

**Trigger** — A card whose authored greeting omits the disclosure still passes the sandbox's disclosure check because the test scenario's greeting contains it — the compliance signal is coming from a fixture, not from the thing being published.

**Fix** — Render the card's own opening (flow first node, or the prompt's greeting) as turn 0 and keep the scenario's openingBot only as an operator-selectable override.

#### `SANDBOX-13` — Text sandbox runs are never completed and the persisted transcript is never read back

MINOR · disconnected · prior: none · **closed** in `6089743` (pass 7)

**Files** — `backend/main.py:3461`, `backend/voice_sandbox.py:238`, `Habibi/src/api/sandbox.ts:170`, `Habibi/src/routes/sandbox.lazy.tsx:219`, `backend/sandbox_runtime.py:1039`

**Mechanism** — `POST /sandbox/runs/{id}/complete` (backend/main.py:3461-3463) has no client in Habibi/src/api/sandbox.ts — the only caller is the voice stop path (backend/voice_sandbox.py:243-252). `GET /sandbox/runs/{id}` has a client (`useSandboxRun`, Habibi/src/api/sandbox.ts:150-176) with no component caller; the page renders only its local `turns` state. So every text rehearsal leaves a `running` sandbox_runs row behind, a reload loses the conversation, and the server-authoritative record — grounded chunk titles, guardrail flags, latency — is written and never shown.

**Trigger** — Run three text turns, reload the page: the transcript is gone and the row still reads running. Reset/scenario-change (Habibi/src/routes/sandbox.lazy.tsx:208-227) drops the run client-side without telling the server.

**Fix** — Call /complete on reset, scenario change and unmount; use useSandboxRun to rehydrate an in-flight run from the runId.

#### `SANDBOX-16` — /voice/sandbox/{id}/tune writes die with the session — nothing reaches a deployment

MINOR · bug · prior: none

**Files** — `backend/voice_sandbox.py:251`, `backend/voice_sandbox.py:238`, `backend/main.py:3497`, `Habibi/src/components/sandbox/TuningStudio.tsx:139`

**Mechanism** — `tune_voice_sandbox` merges the delta into the session store entry and nothing else (backend/voice_sandbox.py:255-281); its own docstring says it only exists so a Restart picks the knobs up. `stop_voice_sandbox` marks the session stopped (backend/voice_sandbox.py:236-252) and no code path copies the merged tuning to bot_deployments or prompt_versions. The panel presents the change as landed ("Applied" flash, Habibi/src/components/sandbox/TuningStudio.tsx:139-156) with no indication it is session-scoped.

**Trigger** — Spend a Live call dialling in barge_in, idle timeout and style; stop the call. The tuning is gone. The only way to keep it is Promote — which ships the browser's drifted preset values instead (SANDBOX-06/08).

**Fix** — Either persist the session tuning back onto the prompt version on stop, or say plainly in the panel that live tuning is session-scoped until promoted.

#### `SANDBOX-14` — Sandbox tool-iteration budget is 4 where the live text runtime allows 6

trivial · bug · prior: none

**Files** — `backend/sandbox_runtime.py:178`, `backend/bot_runtime.py:54`

**Mechanism** — `_SANDBOX_MAX_TOOL_ITERS = 4` is a module constant with no env override (backend/sandbox_runtime.py:178); live reads BOT_MAX_TOOL_ITERATIONS with a default of 6 (backend/bot_runtime.py:54). A multi-tool turn that completes live can exhaust the budget in the sandbox and fall to the tool-free final completion (backend/sandbox_runtime.py:325-352).

**Trigger** — Latent behind SANDBOX-01; fires as soon as the tool loop is reachable and a turn needs five tool round-trips.

**Fix** — Read the same env knob in both loops.

#### `SANDBOX-15` — VoiceSandboxStartRequest declares four fields the handler never reads

trivial · dead-config · prior: none

**Files** — `backend/schemas.py:3296`, `backend/voice_sandbox.py:173`

**Mechanism** — `customerId`, `accountId`, `botId` and `deploymentId` are accepted by the request model (backend/schemas.py:3296-3301) and dropped: start_voice_sandbox reads only promptVersionId, kbSnapshotId, scenarioId, persona and tuning (backend/voice_sandbox.py:166-224). A caller pinning botId or deploymentId gets a 200 and the version's bot instead.

**Trigger** — Any integration or test that posts botId/deploymentId expecting them to select the deployment: they are silently ignored.

**Fix** — Remove the fields, or honour botId/deploymentId when resolving the bundle.

---

## Fleet index — roster, clone, archive, reachability

12 findings — 4 MAJOR, 5 MINOR, 3 trivial; 6 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-fleet.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `FLEET-1` — Reachability chip is computed from the DRAFT card's handoffs, not the published one the runtime enforces

**MAJOR** · degradation-lie · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/db_prompt_studio.py:429-430`, `backend/db_prompt_studio.py:353-359`, `backend/db_prompt_studio.py:507-536`, `backend/agent_core/cards/routing.py:92-94`, `backend/bot_tools.py:398-427`, `Habibi/src/routes/agent-studio.index.tsx:64-68`

**Mechanism** — list_agent_studio_cards feeds reachability() with c['agentCard'], which _agent_studio_card_summary sets to `_card_of(draft) or published_card` (db_prompt_studio.py:433-434) — the editor's unsaved-to-production draft wins. get_agent_studio_card does the same through _handoff_edges' `ORDER BY (p.status = 'draft') DESC` (:530). routing.py's own docstring promises edges 'show up as soon as it is published' (:92-94), and the text runtime's allowlist is parsed from the deployed bundle's card (bot_tools.py:409-418), i.e. the published row. So a handoff added or removed in a draft flips a target between 'via handoff' and 'unreachable' on the fleet while production routing is unchanged; the help text 'Reached mid-conversation from X's handoff allowlist' (index.tsx:67) then describes an allowlist nobody is running.

**Trigger** — On a card with a live deployment, add a handoff to some clone in the editor (autosaves to the draft) and do not publish. Return to /agent-studio: the clone reads 'via handoff'. Delete a handoff in a draft: the still-routed target reads 'unreachable'.

**Fix** — Build the walk from publishedCard (fall back to card_dump defaults only for a first-party bot with no published row) in both list_agent_studio_cards and _handoff_edges, or compute both and render a distinct 'via handoff (draft only)' state.

#### `FLEET-2` — 'via handoff' on the voice channel is not backed by the card at all: voice allowlist is the Python default, and unrestricted for clones

**MAJOR** · disconnected · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/voice/tools.py:2783-2788`, `backend/agent_core/tools/domain.py:1027-1033`, `backend/agent_core/cards/defaults.py:342-346`, `backend/bot_tools.py:398-427`, `Habibi/src/routes/agent-studio.index.tsx:64-68`

**Mechanism** — The voice handoff handler sets `allowlist = set(card_for(bot_id).handoff_targets())` (voice/tools.py:2786): card_for only knows the four first-party constants (defaults.py:342-346), so a tenant's edited handoffs on a published first-party card are ignored, and for any clone it raises KeyError → `allowlist = None` (:2788), which domain.handoff_to_agent treats as no restriction (`if allowlist is not None and target not in allowlist`, domain.py:1024). The text channel was fixed to read the live card and deny on miss (bot_tools.py:400-427) but voice was not. The fleet's 'via handoff' chip therefore describes neither channel's enforcement for voice: the chip is derived from card JSON edges, voice enforces the code constant (first-party) or nothing (clones).

**Trigger** — Publish a clone with an empty handoffs array, deploy it, and have the voice model call handoff_to_agent with any bot id: it succeeds, while the fleet shows the target 'unreachable'. Conversely, remove Insurance from Collections' handoffs and publish: the fleet says Insurance is unreachable; voice still hands off to it.

**Fix** — In voice/tools.py resolve the allowlist from the session's deployed bundle card (same order as bot_tools._handoff_allowlist: live card → built-in → deny with an empty set, never None).

#### `FLEET-3` — An archived card can be edited and published back into production; the fleet then shows 'archived · takes no traffic' beside 'deployed · 100%'

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `Habibi/src/routes/agent-studio.index.tsx:673-686`, `Habibi/src/routes/agent-studio.index.tsx:79-84`, `Habibi/src/routes/agent-studio.index.tsx:596-614`, `backend/db_prompt_studio.py:1860-1975`, `backend/main.py:3247-3275`

**Mechanism** — The Edit button is rendered for archived cards (index.tsx:675-686) and neither the editor shell nor StudioHeader/PublishDialog/ShipTab reads archivedAt or reachability (grep of prompt-studio.lazy.tsx and those components: zero matches). publish_prompt_version (db_prompt_studio.py:1860-1975) and the /prompt-versions/{id}/publish route (main.py:3247-3275) never consult bots.archived_at — the only references to that column in the backend are the roster functions at db_prompt_studio.py:326-754. A publish on an archived bot therefore inserts an active production deployment. The fleet then renders reachability 'archived' with help 'Retired. Kept for audit; takes no traffic' (index.tsx:81-85) and, two lines below, 'deployed · 100%' (index.tsx:600-608); list_agent_studio_cards even seeds the reachability walk with that archived bot (`deployed=[... deploymentStatus == 'live']`, :355-359) while get_agent_studio_card's _live_deployment_bot_ids excludes archived bots (:559), so the fleet and the editor disagree on neighbours' reachability too.

**Trigger** — Archive a clone, tick 'Show archived', click Edit, click Publish in the editor (compile passes — no gate reads archived_at). Reload the fleet.

**Fix** — Refuse publish (409 card_archived) in db_prompt_studio.publish_prompt_version and restore_prompt_version_as_draft when bots.archived_at IS NOT NULL; in the UI, disable Edit→Publish for archived cards (render a Restore-first banner) and hide the Edit button or make it read-only on archived rows.

#### `FLEET-4` — evalStatus lozenge reports 'pass' when the latest redteam passed even if the latest regression suite failed

**MAJOR** · degradation-lie · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/db_prompt_studio.py:478-481`, `backend/db_inbox.py:1582-1600`, `Habibi/src/routes/agent-studio.index.tsx:636-644`

**Mechanism** — `evalStatus = redteam.status or regression.status or 'skipped'` (db_prompt_studio.py:474-478) is a first-non-empty chain, not a worst-of: the regression result is consulted only when there is no redteam report at all. get_latest_eval_report is per kind (db_inbox.py:1590-1594), so a card whose newest redteam run is 'pass' and whose newest regression run is 'fail' is rendered `evals: pass` in success tone with the title 'Eval suite result' (index.tsx:638-644). The publish gates read both kinds separately (db_prompt_studio.py:1907-1908), so the fleet's one-word verdict contradicts what the compiler will say.

**Trigger** — Run the redteam suite (pass) then run the regression suite for the same card and let it fail; open /agent-studio — the card is green.

**Fix** — Compute evalStatus as fail if either latest report is fail, else pass only if both required kinds pass, else skipped; or emit both statuses and render two lozenges.

#### `FLEET-5` — Archive does not stop handoffs to the retired card: G5 and db.handoff_to_agent accept archived targets, so 'stops taking traffic immediately' is enforced nowhere

MINOR · degradation-lie · **closed** in `a91d371` (pass 7)

**Files** — `Habibi/src/routes/agent-studio.index.tsx:724-729`, `backend/db_prompt_studio.py:1877`, `backend/agent_core/cards/compile.py:661-678`, `backend/db_inbox.py:1455-1460`, `backend/db_prompt_studio.py:656-690`

**Mechanism** — Archive only retires bot_deployments rows (db_prompt_studio.py:670-680). The publish compiler's G5 builds known_bots from `SELECT id FROM bots` with no archived filter (:1877) so a caller card keeps or newly gains a handoff to an archived bot with a green gate (compile.py:665-678); db.handoff_to_agent only checks `SELECT 1 FROM bots WHERE id=:id` (db_inbox.py:1459) and then sets interactions.handler_bot_id to the archived bot. Nothing in voice/, bot_runtime.py or agent_core/tools reads archived_at. The AlertDialog copy 'the card stops taking traffic immediately' (index.tsx:728) describes only the deployment row; the conversation graph still routes to it and analytics/QA/compliance attribute those interactions to a retired bot (canary.py:206, live_qa/scorecard.py:265, compliance/context.py:166).

**Trigger** — Archive a clone that appears in Collections' handoffs; publish Collections (G5 passes); on a live call have the model call handoff_to_agent(target=<archived clone>) — it succeeds and handler_bot_id becomes the archived id.

**Fix** — Filter known_bots to `archived_at IS NULL` in publish (and in compile preview), and have db.handoff_to_agent raise ValueError('target_bot_archived'); soften the dialog copy until then.

#### `FLEET-6` — Template catalog failure renders as an empty dropdown with a disabled Create button — error as absence

MINOR · degradation-lie

**Files** — `Habibi/src/routes/agent-studio.index.tsx:389`, `Habibi/src/routes/agent-studio.index.tsx:433-439`, `Habibi/src/routes/agent-studio.index.tsx:482-516`, `Habibi/src/api/agent-studio.ts:787-819`

**Mechanism** — useAgentStudioTemplates() (index.tsx:389) exposes isError/isLoading, but the Clone panel reads only templates.data: the <select> maps `(templates.data ?? [])` (:491), templateId stays '' (:430-439), and Create is disabled by `!templateId` (:503) with no reason. A 5xx or network failure on GET /agent-studio/templates therefore looks identical to a tenant with no templates: a blank select and a dead button, no message, no Retry — the same pattern the fleet grid itself handles correctly at :527-542.

**Trigger** — Make GET /agent-studio/templates fail (API down mid-session, 500), click 'Clone card'.

**Fix** — Branch on templates.isLoading / templates.isError inside the panel (spinner, then an error line with a Retry that calls templates.refetch), and give the disabled Create a reason via ReasonedAction.

#### `FLEET-7` — Eval trend dots come from the tenant's newest 50 reports and vanish silently on error, so 'no dots' means nothing

MINOR · degradation-lie

**Files** — `Habibi/src/routes/agent-studio.index.tsx:392-399`, `Habibi/src/routes/agent-studio.index.tsx:101-102`, `Habibi/src/api/agent-studio.ts:397-421`, `backend/main.py:2817-2822`, `backend/db_inbox.py:1671-1700`

**Mechanism** — useEvalReports() is called with no kind/botId/limit (index.tsx:392; agent-studio.ts:415-419 builds an empty query string), so the server applies `limit: int = Query(default=50)` (main.py:2817) over the whole tenant newest-first. A card whose last runs are older than the 50 most recent tenant-wide reports gets zero dots even though its evalStatus lozenge (server-side, per bot) says pass — two adjacent verdicts about the same history disagree. evalReports.isError is never read (index.tsx:392-399), so a failed request also renders as 'no recent runs' (EvalTrend returns null at :102).

**Trigger** — Run the eval schedule a few times on a busy tenant (or run one suite 50+ times on kaia-v2-4), then look at any other card's row.

**Fix** — Either fetch per-bot with a small limit (useEvalReports(undefined, botId) inside the card, or a server aggregate 'last 3 per bot'), and render an explicit error/empty state instead of null when evalReports.isError.

#### `FLEET-8` — 'Clone card' clones a code template, not the card: tenant edits to the source's published card are dropped while its prompt/flow are copied

MINOR · doc-vs-code

**Files** — `backend/agent_core/cards/clone.py:41-49`, `backend/agent_core/cards/clone.py:70-87`, `backend/agent_core/cards/templates.py:124-171`, `Habibi/src/routes/agent-studio.index.tsx:448-449`, `Habibi/src/routes/agent-studio.index.tsx:467-506`, `Habibi/src/api/agent-studio.ts:822-829`

**Mechanism** — The UI always sends templateId (index.tsx:505-506), so clone_card takes `card = template_card(template)` (clone.py:42-43), which starts from card_dump(<first-party constant>) (templates.py:128,150,158,166) — the published card's `agentCard` is used only on the sourceBotId path the UI never exercises (:44-45). Meanwhile prompt, persona, voice, guardrails and flow ARE taken from the source's published version (:70-74). A tenant who removed tools, added a connector, changed handoffs or configured outbound on Collections and then clicks 'Clone card' → 'Collections' gets the shipped default card with their edited mouth: mixed provenance the header copy ('clone a card, attach connectors, canary, then ship', :448-449) does not disclose, and the button is labelled 'Clone card' while the panel says 'Clone a template'.

**Trigger** — Edit kaia-v2-4's Tools tab to drop three tools and publish; Clone card → Collections; open the clone's Tools tab: all 23 default tools are back, but the flow/prompt are the tenant's.

**Fix** — Either derive the template from the source's published card when one exists (apply template deltas on top of it) or rename the control 'New agent from template' and state in the panel that the card comes from the template while the mouth comes from the source's published version.

#### `FLEET-9` — 'direct only' claims the card is addressable by bot id, but no production entry point ever passes a bot id other than BOT_ID

MINOR · stale

**Files** — `Habibi/src/routes/agent-studio.index.tsx:69-74`, `backend/agent_core/cards/routing.py:17-21`, `backend/voice/bot.py:427`, `backend/bot_runtime.py:712`, `backend/agent_core/copilot.py:283-290`, `backend/sandbox_runtime.py:510-524`

**Mechanism** — The `direct` state exists so Intake (live deployment, no inbound edge) is not called unreachable, and its help says 'Addressed directly by bot id — it has its own live deployment' (index.tsx:72-73; routing.py:17-21). The full caller list of load_active_bundle is voice/bot.py:427 (no bot_id → DEFAULT_BOT_ID), bot_runtime.py:712 (env BOT_ID), copilot.py:285 (handler_bot_id, display chip only), sandbox_runtime.py:512 (no bot_id; explicit promptVersionId otherwise). No inbound channel, dialler or router resolves a card by bot id, so for inbound traffic 'direct only' is operationally the same as 'unreachable' rendered in a calmer information tone. It also blocks nothing: the chip is purely descriptive.

**Trigger** — Look at Intake on the fleet: 'direct only' in information tone, while established runtime facts say every inbound call resolves BOT_ID and handoff_to_agent never loads Intake's bundle.

**Fix** — Reword the help to 'Has a live deployment but no inbound route today — only the sandbox and copilot can load it' and use warning tone, or drop `direct` until a router that dispatches by bot id exists.

#### `FLEET-10` — Fleet and editor can disagree on reachability for targets of a first-party card that has no prompt version yet

trivial · shape-mismatch · DOWNGRADED · **closed** in `a91d371` (pass 7)

**Files** — `backend/db_prompt_studio.py:353-359`, `backend/db_prompt_studio.py:436-442`, `backend/db_prompt_studio.py:507-536`, `backend/db_prompt_studio.py:605-618`

**Mechanism** — list_agent_studio_cards walks edges from every summary's agentCard, which for a first-party bot with no draft/published row is card_dump(bot_id) (db_prompt_studio.py:438-440) — Intake's default handoffs to Collections and Insurance count. get_agent_studio_card instead walks _handoff_edges(), a query over prompt_versions joined to bots (:523-531) that yields nothing for a bot without a version row, plus the requested card itself (:610). On a fresh install where intake-v1 has never been given a version, the fleet shows Insurance 'via handoff' while GET /agent-studio/cards/insurance-v1 (editor header, graph tab nodes at main.py:2277-2287 use the list, but the card's own row uses get) reports 'direct'.

**Trigger** — Fresh database after migrations (bots seeded by alembic 0073, no prompt_versions for intake-v1); compare the fleet chip on insurance-v1 with the single-card GET.

**Fix** — Have _handoff_edges union in card_dump defaults for FIRST_PARTY_BOTS that have no version row, or have get_agent_studio_card reuse list_agent_studio_cards' edge list.

#### `FLEET-11` — Toggling 'Show archived' replaces the whole roster with the loading spinner

trivial · a11y

**Files** — `Habibi/src/routes/agent-studio.index.tsx:385-386`, `Habibi/src/routes/agent-studio.index.tsx:523-526`, `Habibi/src/api/agent-studio.ts:207-217`

**Mechanism** — includeArchived is part of the query key (agent-studio.ts:209) and the query sets no placeholderData, so the first render after the checkbox flips has data undefined and isLoading true → the `isLoading && !data` branch (index.tsx:523) unmounts every card and shows 'Loading fleet'; focus on the checkbox survives but the grid the user was reading jumps to a spinner and back.

**Trigger** — Tick or untick 'Show archived' on a warm page.

**Fix** — Pass `placeholderData: keepPreviousData` to useAgentStudioCards (or render isFetching as a subtle bar) so the roster stays mounted while the wider list loads.

#### `FLEET-12` — Create draft has no in-flight indicator, unlike every sibling control on the screen

trivial · a11y

**Files** — `Habibi/src/routes/agent-studio.index.tsx:502-516`, `Habibi/src/routes/agent-studio.index.tsx:314-318`, `Habibi/src/routes/agent-studio.index.tsx:533-541`

**Mechanism** — The Retry buttons (index.tsx:316-317, 536-537) and ReasonedAction (:165-166) pass `loading` alongside `disabled`; the Create draft button only sets `disabled={clone.isPending || !templateId}` (:503), so a slow clone (bots INSERT + prompt_versions INSERT + full card summary) reads as an inexplicably greyed button rather than a pending action.

**Trigger** — Click Create draft on a slow API.

**Fix** — Add `loading={clone.isPending}` to the Create draft Button.

---

## System Prompt tab — lint, token estimate, the render path

13 findings — 4 MAJOR, 5 MINOR, 4 trivial; 7 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-prompt.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `PROMPT-1` — The seeded prompt_versions rows still carry the CRM tokens and the duplicate disclosure; only persona_presets were ever repaired

**MAJOR** · stale · **closed** in `fcbfefd` (pass 3)

**Files** — `backend/alembic/versions/20260722_0018_prompt_studio_schema_seed.py:36`, `backend/alembic/versions/20260722_0018_prompt_studio_schema_seed.py:148`, `backend/alembic/versions/20260722_0018_prompt_studio_schema_seed.py:222`, `backend/alembic/versions/20260819_0084_persona_presets_crm_free.py:85`, `backend/alembic/versions/20260825_0101_persona_presets_drop_redundant_disclosure.py:70`, `backend/seed_postgres.py:919`, `backend/seed_postgres.py:1078`, `backend/prompt_render.py:114`

**Mechanism** — Migration 0018 defines EMPATHETIC_PROMPT at :36-41 as "Greet {customer_name} warmly…\nReference their account {account_no} and the overdue amount of {overdue_amount} due on {due_date}.\n…\nAlways disclose that the call is recorded for quality and compliance." and seeds it verbatim as the prompt of v1_4, status='published' (:148-158) — the row the entry bot kaia-v2-4 resolves to. FIRM_PROMPT (:43-47), COMPLIANCE_PROMPT (:49-52) and UPSELL_PROMPT (:54-57) carry the same tokens and seed v1_2/v1_1/v1_3. The two repair migrations only ever touch persona_presets: 0084's upgrade() loops `SELECT config FROM persona_presets` (:83-101) and 0101's loops `SELECT id, config FROM persona_presets` (:69-87). A grep of every alembic revision for `UPDATE prompt_versions` returns only 0018's own status flip (:355), 0029 (tuning) and 0073 (bot_id backfill) — nothing rewrites the prompt text. seed_postgres.py:917-924 was fixed (its _emp_prompt is CRM-free and disclosure-free) and it upserts on every run, so a database rebuilt from the seeder is clean — but a database that replayed 0018 and then migrated forward still serves the old text, and `upsert` on prompt_versions only reaches it if the seeder is re-run. At runtime prompt_render.py:114 deletes lines 2 and 3 of that six-line prompt before the model sees them, so the live Collections policy is four lines, not six, and the surviving disclosure line is a second copy of the rule agent_core/prompt.py:82-87 already injects (which is documented at agent_core/prompt.py:76-80 as having caused a live call to disclose three times).

**Trigger** — Open Prompt Studio on kaia-v2-4 in any environment whose database replayed migration 0018 (i.e. any long-lived dev/demo DB rather than one re-seeded from seed_postgres.py). The auto-lint returns four crm_variable_in_system_prompt warnings plus one recording_disclosure_duplicated info on the published prompt, and every card cloned or restored from it inherits them.

**Fix** — Add a migration that applies the same rewrite 0084/0101 applied to persona_presets to prompt_versions.prompt — replace the CRM-token lines with the CRM-context-card wording and drop the DROP_LINE disclosure — for the seeded ids v1_0…v1_4 and any row whose prompt still matches one of 0018's four constants. Alternatively rewrite 0018's four constants to the seed_postgres.py text so a fresh replay is born clean, and ship the data migration for databases already past it.

#### `PROMPT-2` — A spaceless flow token naming a CRM field silently deletes its line, while the lint and the editor both say the braces are read aloud — and the CRM warning is masked away

**MAJOR** · bug · **closed** in `fcbfefd` (pass 3)

**Files** — `backend/prompt_lint.py:65`, `backend/prompt_lint.py:73`, `backend/prompt_lint.py:89`, `backend/prompt_render.py:94`, `backend/prompt_render.py:114`, `Habibi/src/components/prompt-studio/PromptEditor.tsx:250`, `Habibi/src/data/prompt-studio-seed.ts:80`, `backend/tests/test_prompt_lint.py:156`, `backend/tests/test_prompt_lint.py:193`

**Mechanism** — prompt_lint.py:65-67 asserts that "a double-brace token here matches neither TOKEN_RE nor the CRM stripper, so it is not substituted, not dropped, and not reported", and the flow_syntax_in_prompt message (:73-79) tells the author "the braces are spoken aloud". Both are false for the spaceless form. _CRM_TOKEN_RE (prompt_render.py:94-96) is `\{(account_no|customer_name|due_date|last_payment|overdue_amount)\}` and searches the raw line; in `Greet {{customer_name}} warmly.` the substring `{customer_name}` starts at the second brace and matches, so strip_unrendered_crm_tokens (:114) deletes the entire line. The lint cannot see this because it masks flow tokens to spaces before the single-brace scan (:89) — the mask is correct for the spaced form `{{ customer_name }}`, where the inner text is ` customer_name ` and _CRM_TOKEN_RE genuinely does not match, but it is wrong for the spaceless one. The frontend repeats the mask (prompt-studio-seed.ts:78-81) so detectCrmVars returns nothing and the amber CRM banner (PromptEditor.tsx:245-262) never fires; only the red flow banner shows, and it says at :251 "never substitutes them and never strips them, so the braces are read aloud". The same asymmetry runs the other way for operator tokens: `{{agent_name}}` has its inner token substituted by prompt_render.py:80, so the model receives `{Priya}`. Two tests lock the wrong model in: test_prompt_lint.py:155 is docstringed "one is spoken aloud, the other deletes its line", and test_prompt_lint.py:192-211 asserts that `Greet {{customer_name}} now.` produces flow_syntax_in_prompt and no crm_variable_in_system_prompt.

**Trigger** — Type `Greet {{customer_name}} warmly and confirm the overdue balance.` into the System Prompt tab. The editor shows one red banner saying the braces will be spoken. At runtime the line is deleted outright, so the greeting instruction and the balance instruction both vanish from the live policy with no trace.

**Fix** — Run the CRM check against the unmasked text and reconcile the two messages: report a spaceless flow token whose name is a CRM field as line-deleting (the strictest true consequence) rather than as spoken, and keep the spoken-aloud wording only for the spaced form and for non-CRM names. The masking at prompt_lint.py:89 and prompt-studio-seed.ts:78 should mask for the unknown_variable scan but not for the CRM scan. Update test_prompt_lint.py:155 and :192 to assert the runtime's actual behaviour.

#### `PROMPT-3` — A failed deterministic lint renders as a clean prompt: the prohibited-word ERROR and both recording-disclosure findings exist only server-side and have no error or pending surface

**MAJOR** · bug · **closed** in `fcbfefd` (pass 3)

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:569`, `Habibi/src/routes/prompt-studio.lazy.tsx:1431`, `Habibi/src/api/prompt-studio.ts:870`, `Habibi/src/api/prompt-studio.ts:877`, `Habibi/src/components/prompt-studio/PromptEditor.tsx:207`, `backend/prompt_lint.py:143`, `backend/prompt_lint.py:203`

**Mechanism** — freshLint (lazy.tsx:569-573) is `[...(autoLint.data ?? []), ...advisory]`. `autoLint` is a react-query useQuery (prompt-studio.ts:871-877); on any failure `data` is undefined and freshLint collapses to `[]`. Neither `autoLint.isError`, `autoLint.error` nor `autoLint.isPending` is passed to PromptEditor (lazy.tsx:1424-1437 passes only `lintFindings={freshLint}`), and PromptEditor renders the "Lint findings" panel only when `otherFindings.length > 0` (PromptEditor.tsx:194), so a failed pass and a clean pass are pixel-identical. The three findings that exist ONLY on the server — prohibited_word_in_prompt at severity "error" (prompt_lint.py:203-212), recording_disclosure_duplicated (:143-155) and recording_disclosure_unenforced (:161-173) — therefore disappear silently. The client-side banners cover CRM, flow and unknown tokens, which is exactly why the absence is invisible: the author sees banners firing normally and concludes the lint ran. The module comment at prompt-studio.ts:874-877 states "'your prompt is clean' is the one thing this must never say by accident" and then omits the error branch that makes it say it. There is also no first-load pending state, so between mount and the 400 ms debounce plus round trip the panel reads clean.

**Trigger** — Any 5xx, timeout, gateway drop or auth expiry on POST /prompt-versions/lint while an author is editing. A prompt containing "we will threaten legal escalation" against the seeded prohibited list (["guarantee","police","arrest","threaten","family will pay","harassment"]) shows no error at all, and publish is not gated on the lint either (see PROMPT-9).

**Fix** — Pass autoLint.isError/isPending into PromptEditor and render an explicit "Lint could not run — findings unknown" strip in the findings slot, distinct from both the empty and the populated states. Given the prohibited-word rule is severity error and compliance-relevant, also surface the lint state in PublishDialog.

#### `PROMPT-9` — Nothing gates or even mentions the lint at publish — a prompt whose every CRM line will be deleted ships warn-only, and the publish dialog never sees the findings

**MAJOR** · disconnected · **closed** in `fcbfefd` (pass 3)

**Files** — `backend/main.py:3286`, `backend/main.py:3247`, `backend/agent_core/cards/compile.py:1`, `backend/agent_core/cards/compile.py:40`, `Habibi/src/routes/prompt-studio.lazy.tsx:940`, `Habibi/src/routes/prompt-studio.lazy.tsx:1583`

**Mechanism** — prompt_lint.lint_prompt has exactly one caller in the whole tree, the advisory endpoint at main.py:3286 (verified by grep over backend/**.py: every other hit is a test or a comment). publish_prompt_version (main.py:3247-3276) raises only on FlowInvalidError, CompileError, KeyError, ValueError and IntegrityError — it never lints. The publish compiler's gate list (compile.py:1-15, G0–G15 plus G-OB*) contains no gate that reads prompt text: G15 reads the voice locale, G12 the canary split, G14 the actor's permission, and so on. On the client, `publish` (lazy.tsx:940-945) blocks only on `!flowValid`, and PublishDialog (lazy.tsx:1583-1606) receives fromLabel/toLabel/from/to/flowIssues/compileReport/compileError/compileBusy — no lint findings, no lint state. So the only place a CRM-token warning or a prohibited-word ERROR is ever shown is the Prompt tab itself, and an author who publishes from the Guardrails or Ship tab sees nothing. Combined with PROMPT-1 this is how three published cards (per the comment at prompt-studio.ts:841-847) came to carry line-deleting tokens.

**Trigger** — Author a prompt whose every substantive line references a CRM field, switch to any other tab, click Publish, type PUBLISH. It ships; the live system prompt is the two or three lines that had no CRM token.

**Fix** — Either surface the deterministic lint in PublishDialog as a blocking-severity section beside the compile report (errors block Confirm, warnings require acknowledgement), or add a publish-time gate that re-runs lint_prompt on the version being published and fails on severity="error" plus a card-level count of CRM lines that would be deleted. The lint is already deterministic and LLM-free, so it is safe to run inside the compiler.

#### `PROMPT-12` — The mock lint client reimplements the rules wrongly, so mock mode gives a clean bill of health for the exact defects the real lint exists to catch

MINOR · stale

**Files** — `Habibi/src/api/prompt-studio.ts:762`, `Habibi/src/api/prompt-studio.ts:778`, `Habibi/src/api/prompt-studio.ts:797`, `Habibi/src/api/config.ts:15`, `backend/agent_core/guardrails.py:24`, `backend/prompt_lint.py:184`

**Mechanism** — In USE_MOCK the client synthesises findings itself (:761-806) instead of calling the endpoint, and its rules diverge from prompt_lint.py in four ways: (1) the unknown-variable filter uses the full KNOWN_VARIABLES list (:765), so the five CRM names are treated as valid and no crm_variable_in_system_prompt is ever produced; (2) flow_syntax_in_prompt does not exist at all; (3) the disclosure detector is `/record/i` (:778) rather than agent_core.guardrails._DISCLOSURE_RE, so "I'll record that in the CRM" — the exact phrase guardrails.py:24-28 says must not count — satisfies it; (4) the prohibited check is a bare `.includes()` (:797) with neither the whole-word boundary of prompt_lint.py:184-189 nor the clause-scoped negation of :193-202, so it flags the first-party prompt's own "Never threaten legal action" as an error.

**Trigger** — Run the frontend against the mock API (demo, storybook, offline dev) with the seeded EMPATHETIC_PROMPT loaded: the four CRM tokens produce no lint finding at all, and a prompt saying "Never threaten legal action" produces a false error.

**Fix** — Reuse the shared helpers already exported from prompt-studio-seed.ts (detectCrmVars/detectFlowVars/detectUndefinedVars) inside the mock branch so the mock and the inline banners agree, and drop the disclosure and prohibited rules from the mock rather than approximate them.

#### `PROMPT-4` — The "sent/call" figure omits the Skills description block the voice loop appends after the builder returns

MINOR · shape-mismatch · **closed** in `5d5ae1a` (pass 7)

**Files** — `backend/main.py:3348`, `backend/voice/bot.py:102`, `backend/agent_core/skills/runtime.py:39`, `backend/agent_core/skills/runtime.py:172`, `backend/agent_core/skills/defaults.py:22`, `Habibi/src/components/prompt-studio/PromptEditor.tsx:182`

**Mechanism** — main.py:3346-3348 assembles the voice figure as `build_voice_system_prompt(rendered, guardrails, persona=…)` and counts that. The live voice path does the same at voice/bot.py:95-99 and then appends more: `resolve_mouth(bundle['agentCard']).prompt().prefix` (voice/bot.py:102-106), which is `description_block(packs)` — a "## Skills" header, a load_skill instruction line, and one `- <slug>: <description>` line per attached pack (agent_core/skills/runtime.py:39-45, :164-173). kaia-v2-4 attaches eight packs (agent_core/skills/defaults.py:22-31), so the shipped system message carries roughly 150–250 tokens the footer never counts. The footer's tooltip (PromptEditor.tsx:180-184) claims the number is "The assembled system message… Re-sent on every LLM call", which is a completeness claim the figure does not meet. The platform already computes this quantity elsewhere as CompileReport.skill_description_tokens.

**Trigger** — Open the System Prompt tab on any card with attached skills — all four first-party cards qualify. The "N sent/call" figure and its cost are understated by the skills block on every one of them.

**Fix** — Have the estimate endpoint accept the agent card (or the bot id) and append `resolve_mouth(card).prompt().prefix` before counting, mirroring voice/bot.py:102-106; or reuse the compile report's skill_description_tokens and add it. Failing that, retitle the tooltip so it does not claim to be the whole assembled message.

#### `PROMPT-6` — The cost footer labels a per-LLM-request figure "/call" on a product where "call" means the phone call

MINOR · degradation-lie

**Files** — `Habibi/src/components/prompt-studio/PromptEditor.tsx:189`, `Habibi/src/components/prompt-studio/PromptEditor.tsx:198`, `Habibi/src/components/prompt-studio/PromptEditor.tsx:200`, `Habibi/src/components/prompt-studio/PromptEditor.tsx:182`

**Mechanism** — The footer renders `{shipped} sent/call` (:189) and `${shippedCostUsd}/call` (:200) under the title "Prompt-input only — excludes completion + RAG context" (:198). The token figure's own tooltip (:180-184) correctly says the message is "Re-sent on every LLM call — 2-3x per turn", but the cost figure's tooltip says nothing about multiplicity, and both visible labels read "/call". On a collections voice product a "call" is a phone call of twenty-odd turns, so the operator's natural reading of "$0.0024/call" is 40–60x below the actual prompt-input cost of one conversation. The cost tooltip also omits the largest remaining prompt-input component — the JSON tool schemas for the whole Tool Grant, re-sent on every request alongside the system message.

**Trigger** — Any operator budgeting from the footer: multiply "$0.0024/call" by expected daily call volume and the answer is short by roughly the number of LLM requests per conversation.

**Fix** — Relabel both figures "/LLM request" (or "/model call"), and add the per-turn multiplier to the cost tooltip as it already is on the token tooltip. Mention that tool schemas are excluded, the same way completion and RAG already are.

#### `PROMPT-7` — A failed token estimate renders as a permanent "counting tokens…", so an outage looks like work in progress

MINOR · bug

**Files** — `Habibi/src/components/prompt-studio/PromptEditor.tsx:127`, `Habibi/src/components/prompt-studio/PromptEditor.tsx:164`, `Habibi/src/api/prompt-studio.ts:596`, `backend/main.py:3317`

**Mechanism** — `estimate = estimateQuery.data` (:127) and the footer branches on `tokens == null` to render `<span>counting tokens…</span>` (:163-165). `estimateQuery.isError` is never consulted. Because prompt-studio.ts:594 sets `retry: retryUnlessClientError`, a 400/422 fails once and stops immediately, and a 500 exhausts its retries — either way `data` stays undefined and the footer says "counting tokens…" indefinitely while the cost cell shows "—". There is no way for the author to tell an in-flight request from a dead endpoint.

**Trigger** — Paste a prompt over 200 000 characters (main.py:3325-3326 returns 400 prompt_too_large) or take the API down while the tab is open.

**Fix** — Branch on estimateQuery.isError and render "token count unavailable" with the error, distinct from the pending text.

#### `PROMPT-8` — unknown_variable is reported twice — once as a server lint row and once as the client-side banner — because INLINE_CODES omits it

MINOR · bug · prior: 2a.2 · **closed** in `6089743` (pass 7)

**Files** — `Habibi/src/components/prompt-studio/PromptEditor.tsx:70`, `Habibi/src/components/prompt-studio/PromptEditor.tsx:86`, `Habibi/src/components/prompt-studio/PromptEditor.tsx:274`, `backend/prompt_lint.py:109`, `Habibi/src/data/prompt-studio-seed.ts:292`

**Mechanism** — INLINE_CODES (:70-74) excludes only crm_variable_in_system_prompt, flow_syntax_in_prompt and llm_checklist from the "Lint findings" panel, on the stated invariant (":62-65") that a finding shown as a banner must not also appear as a row. `unknown_variable` is not in the set, so the server row from prompt_lint.py:109-116 renders in the panel — "warn Unknown variable {foo} — will not be substituted at runtime." — while detectUndefinedVars (:59, prompt-studio-seed.ts:292-294) independently renders the amber "Unknown variable(s): {foo} — they won't be substituted at runtime" banner at :264-281. Same defect, same remedy, two rows. (Distinct from prior 2a.2, which was per-occurrence duplication inside the panel; that is fixed by the (code,message) dedupe at :83-92.)

**Trigger** — Type `{foo}` into the prompt. Two identical warnings appear, one above the other.

**Fix** — Add "unknown_variable" to INLINE_CODES, since the banner already states the same consequence for the same token set.

#### `PROMPT-10` — lint_prompt's role parameter is unreachable — the request schema has no field for it

trivial · dead-config

**Files** — `backend/prompt_lint.py:50`, `backend/prompt_lint.py:59`, `backend/prompt_lint.py:94`, `backend/main.py:3286`, `backend/schemas.py:2701`

**Mechanism** — lint_prompt takes `role: str = "system"` (:50) and uses it at :59 to pick `SYSTEM_SAFE_VARIABLES` vs `KNOWN_VARIABLES` and at :94 to choose between the crm_variable_in_system_prompt and unknown_variable codes. PromptLintRequest (schemas.py:2702-2709) has `model_config = ConfigDict(extra="forbid")` and declares only prompt/guardrails/includeLlm, and main.py:3286-3290 never forwards a role. No test passes role either. The whole non-system branch is dead.

**Trigger** — None — it is unreachable by construction.

**Fix** — Drop the parameter, or add `role` to PromptLintRequest and have the caller send it if a developer/user-role linting surface is actually planned.

#### `PROMPT-11` — The browser holds a hand-copied third implementation of the token regexes with no drift test

trivial · test-gap · DOWNGRADED

**Files** — `Habibi/src/data/prompt-studio-seed.ts:59`, `Habibi/src/data/prompt-studio-seed.ts:67`, `Habibi/src/data/prompt-studio-seed.ts:80`, `backend/prompt_lint.py:23`, `backend/prompt_lint.py:89`, `backend/prompt_render.py:42`, `backend/tests/test_agent_card_schema_drift.py:124`, `backend/tests/test_system_prompt_rendering.py:144`

**Mechanism** — test_agent_card_schema_drift.py:126-146 pins SYSTEM_SAFE_VARIABLES and CRM_VARIABLES between prompt_render.py and prompt-studio-seed.ts by parsing the TS source — but only the two constant lists. FLOW_TOKEN_RE (prompt-studio-seed.ts:57) is a hand copy of prompt_lint.py:23, PROMPT_TOKEN_RE (:65) of prompt_render.py:42, and the masking rule at :78-81 of prompt_lint.py:89. None is pinned. PROMPT-2 is a live demonstration of what that costs: the masking rule is subtly wrong and it is wrong identically in both copies, so a Python-only fix would leave the browser still hiding the CRM banner.

**Trigger** — Any change to TOKEN_RE or the flow-token pattern on either side.

**Fix** — Extend test_agent_card_schema_drift.py to extract the two regex literals from the TS source and compare their pattern strings to the Python ones, the way it already does for the constant lists.

#### `PROMPT-13` — llm_lint_failed / llm_lint_unavailable survive only as a transient toast — nothing on the Prompt tab records that the critique did not run

trivial · bug · **closed** in `6089743` (pass 7)

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:1041`, `Habibi/src/routes/prompt-studio.lazy.tsx:570`, `Habibi/src/components/prompt-studio/PromptEditor.tsx:97`, `Habibi/src/components/prompt-studio/PromptEditor.tsx:298`, `backend/prompt_lint.py:303`, `backend/prompt_lint.py:369`

**Mechanism** — When Azure is unconfigured or errors, _llm_checklist returns a single info finding coded llm_lint_unavailable (prompt_lint.py:304-310) or llm_lint_failed (:369-376). onLint stores the whole response in `lintFindings` (lazy.tsx:1041) and toasts the failure (:1048-1050), but freshLint keeps only `f.code === "llm_checklist"` (lazy.tsx:570) and PromptEditor's aiFindings filter does the same (PromptEditor.tsx:97). Once the toast expires there is no record: the Critique panel is simply absent, which is indistinguishable from "nothing was flagged". The toast copy is correctly worded as an error, so this is only a persistence gap, not a false verdict at the moment of the click.

**Trigger** — Press "Critique wording" with AZURE_OPENAI unset, dismiss the toast, look at the tab.

**Fix** — Let the two unavailable codes through into a persistent row in the Critique section, styled as a failure rather than a suggestion.

#### `PROMPT-5` — The text-channel branch of the estimate omits the ~450-token WhatsApp behaviour block and the dialog-control block bot_runtime appends

trivial · shape-mismatch · DOWNGRADED

**Files** — `backend/main.py:3350`, `backend/bot_runtime.py:516`, `backend/bot_runtime.py:529`, `backend/bot_runtime.py:555`, `Habibi/src/components/prompt-studio/PromptEditor.tsx:43`, `backend/schemas.py:2732`

**Mechanism** — main.py:3350-3356 builds the text figure as `build_system_prompt(rendered_prompt=…, context_blocks=[], channel="whatsapp")` with no skill_catalog. The live text path (bot_runtime.py:511-526) passes `skill_catalog=skill_prefix`, and then bot_runtime.py:527-556 concatenates a hard-coded "## WhatsApp behaviour" section of roughly a dozen multi-line bullets plus `_dialog_control_block(...)` onto the same system string. None of that is counted. The defect is latent today only because PromptEditor.tsx:39-43 hardcodes `channel: "voice"` and no UI ever requests the text figure — but the endpoint accepts `channel: "text"` (schemas.py:2733) and test_prompt_token_estimate.py:79-84 exercises it, so any caller that trusts it gets a figure that understates the WhatsApp system message by several hundred tokens.

**Trigger** — Call POST /prompt-versions/estimate-tokens with channel="text", or wire a channel toggle into the footer for a messaging-only card.

**Fix** — Move the WhatsApp behaviour + dialog-control concatenation out of bot_runtime.py:527-556 into a named builder in agent_core/prompt.py and call it from both bot_runtime and the estimate, the same way the voice branch shares build_voice_system_prompt. Also thread skill_catalog into the text branch.

---

## Persona tab — traits, presets, language

11 findings — 1 MAJOR, 8 MINOR, 2 trivial; 3 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-persona.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `PERSONA-1` — Persona language never binds the recogniser on a real call — every tuning reaching resolve_session_tuning is pre-normalised to stt.language='en-IN', which the function treats as an explicit override

**MAJOR** · degradation-lie · **closed** in `fcbfefd` (pass 3)

**Files** — `backend/voice/tuning_apply.py:417`, `backend/voice/tuning_apply.py:442-450`, `backend/agent_core/tuning.py:302`, `backend/agent_core/tuning.py:37-38`, `backend/agent_core/tuning.py:146-148`, `backend/agent_core/deployment.py:70`, `backend/agent_core/deployment.py:112`, `backend/voice/bot.py:411-423`, `backend/voice/bot.py:437`, `backend/voice/bot.py:587-597`, `backend/db_prompt_studio.py:183`, `backend/db_prompt_studio.py:1620-1621`, `backend/db_prompt_studio.py:2004-2019`, `Habibi/src/components/prompt-studio/PersonaSliders.tsx:223-227`, `backend/tests/test_language_is_one_setting.py:56-85`

**Mechanism** — resolve_session_tuning decides precedence by reading `explicit_lang = raw['stt']['language']` (tuning_apply.py:415) and only applies the persona tag when that is empty (:444). But `normalize_tuning` always writes `stt['language'] = str(stt.get('language') or 'en-IN')` (tuning.py:302) and default_tuning() already carries 'en-IN' (tuning.py:37-39). Every producer of the dict handed to resolve_session_tuning runs normalisation first: get_prompt_version (_map_prompt_version, db_prompt_studio.py:183), the draft insert seeds tuning from apply_voice_config_overlay(default_tuning()) (:1620-1621), publish persists normalize_tuning(...) into prompt_versions.tuning and deployments.tuning (:2009-2029), load_active_bundle/resolve_prompt_bundle normalise again (deployment.py:70,110), and the voice sandbox path normalises the version tuning (bot.py:85). So `raw` at bot.py:589 always has stt.language set, `explicit_lang` is never empty, and the persona tag is never applied; the log at tuning_apply.py:428-433 will report "using tuning 'en-IN' over persona 'Hindi'" on every Hindi card. The unit tests only call resolve_session_tuning({}, ...) — a shape no production path produces.

**Trigger** — Set Primary language = Hindi (or any non-English) on the Persona tab, publish, place or receive a call without having set stt.language in the Sandbox Tuning Studio and promoted it. The prompt says 'Speak Hindi' but AzureSTT is bound to en-IN; the tab's own hint ('Sets … what speech recognition listens for (hi-IN)') is false.

**Fix** — Make the precedence decision on the *stored* raw jsonb before normalisation (thread deployment/version tuning raw into resolve_session_tuning, or record an explicit `stt.language_source`/`explicit` marker when the Tuning Studio sets it) and add a test that feeds `normalize_tuning({})` / default_tuning() with persona_language='Hindi' and asserts stt.language == 'hi-IN'.

#### `PERSONA-11` — No frontend test covers PersonaSliders and the backend STT-binding test only exercises a raw dict that production never produces

MINOR · test-gap

**Files** — `backend/tests/test_language_is_one_setting.py:56-85`, `backend/tests/test_voice_persona_reaches_the_call.py:35-97`, `Habibi/src/components/prompt-studio/PersonaSliders.tsx`

**Mechanism** — test_the_persona_language_binds_the_recogniser calls resolve_session_tuning({}, persona_language='Tamil') — an empty tuning, whereas every caller passes a normalised dict (see PERSONA-1); no test asserts the binding through load_active_bundle/deployment tuning. test_voice_persona_reaches_the_call covers prompt text only. Glob **/*Persona*.test.tsx finds nothing, so preset confirm/undo, the language hint and Hear tone have no component test.

**Trigger** — n/a (coverage).

**Fix** — Add a test feeding default_tuning() (and a publish-shaped tuning) with persona_language and asserting stt.language; add a PersonaSliders test for preset → confirm → Undo and the presets error state.

#### `PERSONA-2` — Vernacular fallback chips never reach AgentTuning.stt.fallback_languages, so the recogniser cannot switch to a language the prompt promises fluency in

MINOR · dead-config

**Files** — `Habibi/src/components/prompt-studio/PersonaSliders.tsx:228-246`, `backend/voice/natural.py:133-145`, `backend/voice/tuning_apply.py:442-450`, `backend/voice/bot.py:1593-1614`, `backend/voice/bot.py:1669-1670`, `backend/agent_core/tuning.py:303-308`, `backend/voice/safety.py:104-146`, `backend/voice/crm_sink.py:935`

**Mechanism** — persona.fallbackLanguages is rendered into the system prompt as 'You are fluent in Tamil, Telugu' (natural.py:145) and into G15's card_locales, but the STT fallback list the mid-call `_live_language` switch is bounded by (bot.py:1594, 1670) comes solely from tuning.stt.fallback_languages, which normalisation fills with ['hi-IN','en-IN'] (tuning.py:303) and which resolve_session_tuning only re-orders (tuning_apply.py:449-450) — it never adds tags derived from persona.fallbackLanguages. The model is instructed to switch to Tamil; the recogniser is not allowed to.

**Trigger** — Tick Tamil as a vernacular fallback, publish, have a caller open in Tamil: the LLM is told to switch, `_live_language` refuses because ta-IN is not in stt.fallback_languages, and transcription stays en-IN/hi-IN.

**Fix** — In resolve_session_tuning, map persona.fallbackLanguages through languages.tag_for and union them into stt.fallback_languages (after the primary), and say so in the PersonaSliders hint; or drop the 'fluent in' clause when the tag is not in the recogniser list.

#### `PERSONA-3` — Persona tab renders a presets fetch failure (and an empty table) as silently 'no presets' — Prompt tab has an empty state, Persona tab has none

MINOR · degradation-lie

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:334`, `Habibi/src/routes/prompt-studio.lazy.tsx:185`, `Habibi/src/components/prompt-studio/PersonaSliders.tsx:158-178`, `Habibi/src/components/prompt-studio/PromptEditor.tsx:373-378`, `Habibi/src/api/prompt-studio.ts:496-502`

**Mechanism** — `presets = presetsQuery.data ?? []` (lazy.tsx:334) collapses loading, error and empty into the same empty array; presetsQuery.isError/isPending are never read. PersonaSliders maps the array under a 'Presets' heading with no fallback (159-177), so a 500 from /persona-presets shows a heading with nothing under it. PromptEditor at least prints 'No presets configured…' (392-397) — but that copy is also wrong on an error, and the two tabs show different things for the same failure.

**Trigger** — Break /persona-presets (or run against a tenant with an empty persona_presets table) and open the Persona tab.

**Fix** — Read presetsQuery.isError/isPending in the route and pass a status to both panels; render 'Presets could not be loaded' vs 'No presets configured' distinctly, in both tabs.

#### `PERSONA-4` — 'Hear tone' auditions a different voice configuration than the Voice tab's Preview: it omits the model params and any language, so non-Azure voices play with backend defaults and a Hindi persona is spoken in English

MINOR · disconnected · **closed** in `6089743` (pass 7)

**Files** — `Habibi/src/components/prompt-studio/PersonaSliders.tsx:110-120`, `Habibi/src/components/prompt-studio/PersonaSliders.tsx:269-273`, `Habibi/src/components/prompt-studio/VoicePanel.tsx:438-450`, `Habibi/src/api/prompt-studio.ts:1110-1130`, `backend/main.py:3110-3127`, `backend/schemas.py:2651-2670`, `backend/azure_speech.py:236`, `Habibi/src/data/prompt-studio-seed.ts:296-322`

**Mechanism** — PersonaSliders.hearPreview builds the previewTts body without `params` (110-120), so previewTts sends `params: {}` (prompt-studio.ts:1126); VoicePanel sends `params: modelParamsRef.current` (VoicePanel.tsx:448). main.py:3110 merges `{'speed': payload.speed, **params}` and provider_tts caches on params, so for a Fish/Cartesia/Deepgram voice the persona preview uses vendor defaults and a different cache key than the Voice tab — two 'preview' buttons, two voices. Separately, renderPersonaPreview is hardcoded English ('Namaste Rahul-ji…', ₹18,450) and the request carries no language, so Azure synthesises with xml:lang en-IN (build_ssml default, azure_speech.py:236) regardless of persona.language; the panel's caption says only that prosody comes from the Voice tab, so the language omission is undisclosed.

**Trigger** — Pick a Fish voice with temperature 0.3 on the Voice tab, set Primary language Hindi, press Hear tone on the Persona tab.

**Fix** — Pass `params: voice.params` (and `fresh`) from PersonaSliders exactly as VoicePanel does — ideally share one previewTts call-site helper — and either send languageTag(persona.language) to /tts/preview or state in the caption that the preview is English regardless of the language chosen.

#### `PERSONA-5` — card.mouth.languages is dead config: defaulted to ['English','Hindi'] on every card, never edited, never read — G15 and every runtime use persona.language instead

MINOR · dead-config

**Files** — `backend/agent_core/cards/schema.py:93-99`, `backend/agent_core/cards/schema.py:381`, `backend/db_prompt_studio.py:983-1012`, `backend/agent_core/cards/compile.py:194-225`, `backend/agent_core/cards/compile.py:940-942`, `Habibi/src/api/agent-card.ts:139-141`

**Mechanism** — CardMouthRef.languages (schema.py:99) is stamped into agent_card on every card, but no backend module reads `.mouth.languages` (the only `languages` readers in backend/*.py are provider_voice_sync.py:149,251,274, about vendor voices), the frontend declares the field (agent-card.ts:141) and never renders or edits it, and G15's 'card locales' are computed from prompt_versions.persona (voice_locale_facts, db_prompt_studio.py:1004-1011). Two 'what languages does this card speak' fields exist and can disagree with nothing reporting it; the Agent Card — the publish-time contract per CONTEXT.md — carries a language claim that is not the one the compiler checks.

**Trigger** — Set Primary language = Tamil with no fallbacks on the Persona tab; publish. agent_card.mouth.languages still says ['English','Hindi'] on the published row; anything (analytics, a future gate, an export) reading the card gets the wrong languages.

**Fix** — Either derive mouth.languages from persona at publish (write [language, *fallbackLanguages] into the card and make G15 read the card) or delete the field from the schema and the TS type.

#### `PERSONA-6` — Text channels put two languages in one system message: the '{language}' token follows the customer row / sandbox caller while the Persona block follows the card

MINOR · shape-mismatch

**Files** — `backend/bot_runtime.py:69`, `backend/bot_runtime.py:494-503`, `backend/bot_runtime.py:511-522`, `backend/agent_core/prompt.py:167-170`, `backend/agent_core/turn.py:55`, `backend/agent_core/turn.py:72-82`, `Habibi/src/api/sandbox.ts:116-124`, `backend/voice/bot.py:64-77`, `backend/main.py:3339-3356`

**Mechanism** — Voice (bot.py:64-78) and the token estimate (main.py:3341) substitute persona.language for {language}. bot_runtime substitutes customers.language (:69, :501 `conv.get('language') or 'English'`) and the sandbox substitutes the simulated caller's language (turn.py:56 from sandbox.ts:121), then both append '## Persona\n- Language: <persona.language>' (prompt.py:150). A Hindi card talking to a customer whose row says English renders 'Speak in English.' followed by '- Language: Hindi'. The estimate-tokens footer, which claims to assemble 'the message the runtime actually sends' (PromptEditor.tsx:183), models the voice behaviour only.

**Trigger** — Publish a card with Primary language Hindi and a preset template containing 'Speak in {language}'; open a WhatsApp conversation for a customer whose customers.language is 'English' (or run a sandbox text turn with an English persona).

**Fix** — Decide one owner: either drop customer language into the delimited CRM card as a 'preferred language' hint and substitute persona.language for {language} on every channel (matching voice), or render the Persona block's language line from the same source the token used.

#### `PERSONA-7` — Voicemail script reads persona keys (agentName/name/issuer/brand) that PersonaState can never carry, so the voicemail identifies as the hardcoded 'Priya from HDFC Bank' while the live prompt uses AGENT_NAME/BANK_NAME

MINOR · disconnected

**Files** — `backend/voice/amd.py:91-105`, `backend/voice/amd.py:42-43`, `backend/voice/bot.py:1461-1473`, `backend/schemas.py:2147-2162`, `backend/db_prompt_studio.py:71-91`, `backend/agent_core/prompt.py:9-16`, `backend/compliance_copy.py:39-74`

**Mechanism** — attach_voicemail_handlers is given the card persona (bot.py:1470) and voicemail_script looks up p['agentName'] / p['name'] / p['issuer'] / p['brand'] (amd.py:95-103). PersonaState is extra='forbid' with exactly traits/language/fallbackLanguages (schemas.py:2157-2162) and _prompt_persona whitelists to those keys (db_prompt_studio.py:87-95), and tuning has no 'persona' block (no match in agent_core/tuning.py), so every lookup misses and the message falls to _DEFAULT_AGENT_NAME='Priya' / _DEFAULT_ISSUER='HDFC Bank' (amd.py:42-43) or tenant_contacts().issuer. The live system prompt names the agent from AGENT_NAME (prompt.py:9-11). A tenant that renames the agent gets a call that says 'I am Kaia' and a voicemail that says 'this is Priya'.

**Trigger** — Set AGENT_NAME=Kaia (or BANK_NAME) in the voice container env; an outbound call hits voicemail.

**Fix** — Have voicemail_script take agent_name()/bank_name() from agent_core.prompt (the same source as the system prompt) and delete the dead persona key lookups, or add the fields to PersonaState and the Persona tab if per-card naming is wanted.

#### `PERSONA-8` — Persona sliders and the language select are unlabeled for assistive tech; fallback chips lack type='button'

MINOR · a11y

**Files** — `Habibi/src/components/prompt-studio/PersonaSliders.tsx:181-201`, `Habibi/src/components/prompt-studio/PersonaSliders.tsx:204-216`, `Habibi/src/components/prompt-studio/PersonaSliders.tsx:233-244`, `Habibi/src/components/ui/slider.tsx:9-21`

**Mechanism** — Each trait's name is a <span> (184) next to a Radix Slider whose Thumb has no aria-label/aria-labelledby (slider.tsx:19), so five sliders announce as 'slider 82' with no name. 'Primary language' is a <div> (205-207), not a <label htmlFor>, for the <select> (208). The fallback chips are <button> without type='button' (233) — the preset chips in the same file were fixed for exactly this (164-167) — and their pressed state is colour-only (no aria-pressed).

**Trigger** — Tab through the Persona tab with a screen reader.

**Fix** — Pass aria-label={t.label} (or aria-labelledby to an id on the span) into Slider, wrap 'Primary language' in <label htmlFor>, and give the chips type='button' aria-pressed={on}.

#### `PERSONA-10` — Server accepts any persona.language string and any trait integer; an unregistered language publishes with G15 silently skipping and the recogniser silently unchanged

trivial · bug · DOWNGRADED · **closed** in `5d5ae1a` (pass 7)

**Files** — `backend/schemas.py:2147-2162`, `backend/db_prompt_studio.py:71-91`, `backend/db_prompt_studio.py:1004-1011`, `backend/agent_core/cards/compile.py:207-210`, `backend/voice/tuning_apply.py:418-427`, `backend/voice/natural.py:114-121`

**Mechanism** — PersonaTraits are unbounded ints and PersonaState.language is a bare str (schemas.py:2147-2162); _prompt_persona coerces but does not clamp or check the registry (db_prompt_studio.py:76-95). A language outside agent_core.languages yields no tag, so voice_locale_facts returns [] and G15 reports 'skipped — no voice or no card language' rather than a warning (compile.py:209-210); at call time tuning_apply only logs a warning (:419-427). Traits of 500 or -20 pass straight into persona_style_line's cut-points. The UI cannot author these values (select bound to LANGUAGES, sliders 0-100), so the trigger is API/legacy-row only.

**Trigger** — PUT /prompt-versions/{id} with persona.language='Hinglish' or traits.empathy=500; publish succeeds with a green/skipped G15.

**Fix** — Constrain PersonaTraits with Field(ge=0, le=100) and validate language against languages.names() (or make G15 'warn' when the primary language has no tag instead of 'skipped').

#### `PERSONA-9` — Changing the primary language leaves the old primary (or the new one) inside fallbackLanguages, hidden by the chip filter but persisted and rendered on text channels

trivial · bug

**Files** — `Habibi/src/components/prompt-studio/PersonaSliders.tsx:58`, `Habibi/src/components/prompt-studio/PersonaSliders.tsx:208-216`, `Habibi/src/components/prompt-studio/PersonaSliders.tsx:230`, `backend/agent_core/prompt.py:167-168`, `backend/voice/natural.py:133-138`, `Habibi/src/data/prompt-studio-seed.ts:209-213`

**Mechanism** — update({language}) (210) does not touch fallbackLanguages, and the chip list filters `l !== value.language` (230), so with DEFAULT_PERSONA {language:'English', fallbackLanguages:['Hindi']} choosing Hindi as primary stores fallbackLanguages:['Hindi'] with no visible chip to remove it. Voice dedupes (natural.py:136), G15 dedupes (db_prompt_studio.py:1009), but build_system_prompt prints '- Language: Hindi\n- Fallback languages: Hindi' (prompt.py:150) and the stored row is self-contradictory.

**Trigger** — Open a fresh card, change Primary language from English to Hindi, save.

**Fix** — In the select's onChange, also filter the new primary out of fallbackLanguages.

---

## Voice (TTS) tab — catalog, params, preview, runtime binding

11 findings — 2 MAJOR, 8 MINOR, 1 trivial; 3 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-voice.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `VOICE-1` — Catalog Refresh is Azure-only but its soft-removal is not provider-scoped: it either marks every non-Azure voice removed (forcing runtime fallback to Aarti) or, as today, silently skips all removals while toasting 'Catalog refreshed'

**MAJOR** · bug · **closed** in `fcbfefd` (pass 3)

**Files** — `backend/tts_catalog_sync.py:212`, `backend/tts_catalog_sync.py:326-347`, `backend/worker.py:39-62`, `backend/provider_voice_sync.py:295-354`, `backend/main.py:3077-3086`, `backend/db_prompt_studio.py:1266-1272`, `backend/voice/tuning_apply.py:450-464`, `Habibi/src/components/prompt-studio/VoiceCatalogBrowser.tsx:257-283`

**Mechanism** — run_sync fetches only Azure voices (tts_catalog_sync.py:192-205) yet its removal UPDATE is `WHERE removed_at IS NULL AND NOT (short_name = ANY(:names))` with no provider_id clause (332-336), so every fish:/cartesia:/deepgram: row is a removal candidate. The only protection is the plausibility guard `len(seen) >= live_prior*0.8` (326-328) where live_prior counts ALL providers. With the catalog the code itself describes (2,113 rows, VoiceCatalogBrowser.tsx:439; 774 Azure, db_prompt_studio.py:1102; 890 Cartesia, provider_tts.py:116) 774 < 1690, so the guard trips on every admin Refresh: nothing is ever soft-removed (a genuinely retired Azure voice is never flagged 'removed', so get_tts_voice_warning never fires for it and the runtime keeps sending the dead name to Azure), a WARNING is logged, and run_sync still returns error=None → the UI toasts 'Catalog refreshed · 774 voices' (Browser:273) under a button titled 'Re-pull the provider voice catalogs' (Browser:553) that pulls one provider. If non-Azure rows ever fall under 20% of the catalog, the guard passes and one click soft-removes all of them; get_tts_voice_warning then returns code 'removed' (db_prompt_studio.py:1265-1272) and resolve_session_tuning rewrites tuning.tts.voice to en-IN-AartiNeural on every call (tuning_apply.py:454-464) — every Fish/Cartesia-voiced card silently speaks Aarti. No code path in the repo writes non-Azure rows (searched main.py, db.py, agent_core/**, scripts/, tts_catalog_sync.py), so Refresh can never restore them either.

**Trigger** — Operator with admin role opens Voice tab → Filters → Refresh. Today: toast claims a refresh while removals are skipped and the log warns. With a smaller non-Azure set (<20% of rows): all non-Azure voices vanish from the picker and bound cards fall back to Aarti at call time.

**Fix** — Scope both the prefetch and the removal UPDATE to `provider_id IS NULL OR provider_id = 'azure'`, compute live_prior over that same subset, and surface the skipped-removal condition in the TtsSyncRun (e.g. `softRemovalSkipped: true`) so the Browser toast can say so instead of 'Catalog refreshed'. Rename the button/title to 'Refresh Azure catalog' until a multi-provider sync exists.

#### `VOICE-2` — Bindings-tab voiceRef is dead config and a provider/voice mismatch is never checked: the Voice tab's short name is force-fed to whatever TTS service is bound (or the Azure fallback)

**MAJOR** · dead-config · **closed** in `fcbfefd` (pass 3)

**Files** — `backend/agent_core/providers/factory.py:226-227`, `backend/voice/tuning_apply.py:236`, `backend/agent_core/tuning.py:283`, `backend/voice/bot.py:660-676`, `backend/voice/provider_bind.py:59-79`, `backend/agent_core/providers/fish_service.py:129-139`, `backend/db_prompt_studio.py:961-979`, `backend/agent_core/cards/compile.py:194-226`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:192`, `Habibi/src/components/prompt-studio/VoiceParamsPanel.tsx:326-405`

**Mechanism** — factory.build applies binding.voice_ref only `if binding.voice_ref and 'voice' not in settings` (factory.py:226-227). bot.py:661 passes settings=tts_settings_kwargs(tuning), which always contains 'voice' (tuning_apply.py:236) because normalize_tuning fills tts.voice with en-IN-AartiNeural when absent (tuning.py:283). So the Bindings tab's voiceRef never speaks. Conversely nothing compares the voice's provider (provider_tts.voice_row / the `{provider}:` prefix) with the bound provider: a card whose Voice tab selected `fish:<ref>` on a tenant with no fish binding hits NoBindingError → Azure fallback (provider_bind.py:70-79) and build_tts_settings hands AzureTTSService voice='fish:<ref>' (tuning_apply.py:270-277); a card with en-IN-AartiNeural on a Fish binding hands FishTTSService reference_id='en-IN-AartiNeural' (fish_service.py:139). The panel's RuntimeNotice (VoiceParamsPanel.tsx:369-405) only reports the model's import status, so both cases show a green 'These settings publish with the version' notice, pass G0-G15 (compile.py has no binding gate — grep 'binding' hits only G3 policy bindings at 594-616), and fail on the first utterance of a live call.

**Trigger** — Select any Fish/Cartesia voice in the Voice tab on a bot whose tenant has no binding for that provider (the shipped default), publish, place a call. Or set a voiceRef in Agent Studio → Providers → Bindings and observe it is never used.

**Fix** — Add a compile gate (G16 'voice_provider') that resolves provider_tts.voice_row(short) and factory.resolve_chain(tenant, 'tts', bot, locale) and warns/blocks when the voice's provider is not first in the chain; in factory.build let binding.voice_ref win only when the tuning voice belongs to a different provider, or drop voiceRef from the Bindings UI.

#### `VOICE-10` — Retired provider_models rows are never disabled by the seed upsert, so the panel can bind a Fish/OpenRouter voice to a stale model row that reports runtime 'live'

MINOR · stale

**Files** — `backend/agent_core/providers/persist.py:57-88`, `backend/main.py:5441-5442`, `backend/main.py:5471`, `Habibi/src/components/prompt-studio/VoicePanel.tsx:240-242`, `backend/agent_core/providers/registry.py:437-455`

**Mechanism** — sync_seed upserts ON CONFLICT (provider_id, kind, model_id) (persist.py:69) and never disables rows absent from SEED. When the OpenRouter model id moved from the expired free promotion to 'fish-audio/s2.1-pro' (registry.py:440-461 names the old id), the old row stays enabled and list_models returns both. For that row find_model returns None, so runtime defaults to (RUNTIME_LIVE, '') and sampling False (main.py:5440-5442, 5471) — an audition-only provider reported as live. VoicePanel picks the first row per provider (240-242), so which of the two wins depends on display_name ordering.

**Trigger** — Any deployment whose provider_models table predates commit 5c143eb: open a voice from that provider and compare RuntimeNotice / 'New take' against the registry.

**Fix** — In sync_seed, `UPDATE provider_models SET enabled=false WHERE id NOT IN (seed ids)`; in list_provider_models, report RUNTIME_UNAVAILABLE ('not in registry') when find_model is None.

#### `VOICE-3` — 'Speaking style' selector is dead config: preview ignores it and runtime derives style from warmth

MINOR · dead-config

**Files** — `Habibi/src/components/prompt-studio/VoicePanel.tsx:683-703`, `Habibi/src/components/prompt-studio/VoicePanel.tsx:388`, `backend/main.py:3163-3171`, `backend/azure_speech.py:460-468`, `backend/agent_core/tuning.py:359-366`, `backend/agent_core/tuning.py:397-409`, `backend/db_prompt_studio.py:1740-1748`, `backend/db_prompt_studio.py:2012-2018`

**Mechanism** — The Select at VoicePanel.tsx:688-702 writes voice.style and schedules a live preview; previewTts sends `style` (prompt-studio.ts:1118) and TtsPreviewRequest accepts it (schemas.py:2660), but tts_preview never reads payload.style — azure_speech.synthesize has no style parameter (azure_speech.py:460-469) and picks express-as from warmth (189-220). At save/publish apply_voice_config_overlay is called without style (db_prompt_studio.py:1740-1748, 2012-2018; signature tuning.py:359-366) and sets tts.style from warmth (397-406). The stored value only reaches deployments.voice_config (1992-2000), which the runtime reads solely for azureVoiceName (deployment.py:78-80). selectVoice also silently writes styles[0] on every selection (VoicePanel.tsx:388), and the 'style not offered' banner (555-562) advises picking a replacement that changes nothing.

**Trigger** — Pick an Azure voice with styles, change 'Speaking style', press Preview — the audio is identical; publish — the call uses friendly/empathetic from warmth regardless.

**Fix** — Either pass voice.style through TtsPreviewRequest into azure_speech.synthesize and into apply_voice_config_overlay (tts.style/style_degree, overriding the warmth mapping when set), or remove the selector and the styles[0] write.

#### `VOICE-4` — PersistenceNotice promises 'a published call is synthesized with what you hear here' but pause_ms never reaches a call and speed/warmth are rendered differently at runtime

MINOR · degradation-lie

**Files** — `Habibi/src/components/prompt-studio/VoiceParamsPanel.tsx:332-343`, `backend/agent_core/providers/registry.py:121-122`, `backend/agent_core/voice_ssml.py:61-84`, `backend/agent_core/tuning.py:359-366`, `backend/agent_core/tuning.py:391-409`, `backend/azure_speech.py:177-220`, `backend/azure_speech.py:246-252`, `backend/voice/tuning_apply.py:232-253`

**Mechanism** — PARAM_AZURE_TTS declares pause_ms as an SSML control (registry.py:121-122) and the panel writes it to voice.pauseMs (VoicePanel.tsx:740). apply_voice_config_overlay takes no pause argument (tuning.py:359-366) and tts_settings_kwargs emits none (tuning_apply.py:232-254); build_voice_ssml, the only runtime consumer of pauseMs (voice_ssml.py:57,83), has no caller. For the other three: preview clamps speed to 0.5-1.5 and adds a warmth pitch/rate bias plus catalog-aware express-as (azure_speech.py:246-252, 177-220), while runtime uses rate=clamp(0.85..1.25, speed*1.03), pitch=p*2%, and a fixed friendly/empathetic style regardless of the voice's StyleList (tuning.py:391-406). The notice at VoiceParamsPanel.tsx:333-343 asserts equivalence.

**Trigger** — Set Sentence pause to 1200 ms (or speed 1.5) on an Azure voice, preview, publish, call: the pause is absent and the speed is capped at 1.25×1.03.

**Fix** — Either fold pauseMs into tuning (e.g. tts.params.pause_ms consumed by a sentence-break text filter) and unify the warmth/speed mapping into one shared function used by both azure_speech.build_ssml and apply_voice_config_overlay, or reword the notice to name which controls ship and mark pause_ms 'preview only' in the schema.

#### `VOICE-5` — Azure controls display schema defaults while the wire/runtime use the VoiceConfig columns when params lacks the key

MINOR · shape-mismatch

**Files** — `Habibi/src/components/prompt-studio/VoiceParamsPanel.tsx:190`, `Habibi/src/components/prompt-studio/VoicePanel.tsx:254`, `Habibi/src/components/prompt-studio/VoicePanel.tsx:438-448`, `Habibi/src/components/prompt-studio/VoicePanel.tsx:723`, `backend/agent_core/providers/registry.py:114-123`, `backend/main.py:3163-3171`, `backend/db_prompt_studio.py:1740-1748`, `backend/db_prompt_studio.py:2185-2190`

**Mechanism** — VoiceParamsPanel renders `values[spec.key] ?? spec.default` (line 190) with values = voice.params (VoicePanel.tsx:254,723). The Azure preview path ignores params and uses payload.speed/pitch/warmth/pauseMs (main.py:3163-3171), and the runtime fold uses voice.speed/pitch/warmth (db_prompt_studio.py:1740-1748). A version whose columns differ from the schema defaults (rate 1.0, pitch 0, warmth 62, pause 320 — registry.py:114-122) but whose params bag lacks those keys (every version saved before params existed, every Sandbox-promoted or restored one: _restorable_voice resets params to {} at 2190) shows the default in the slider while preview and call use the column. Only once the operator drags the slider do the two reconverge (VoicePanel.tsx:733-741 writes both).

**Trigger** — Open the Voice tab on a version with e.g. warmth 45 and params {} (the mock seed's v1.1 shape): the Warmth control reads 62, Preview plays warmth 45.

**Fix** — In VoicePanel, seed the four Azure display values from the columns: pass `values={{...modelParams, rate: value.speed, pitch: value.pitch, warmth: value.warmth, pause_ms: value.pauseMs}}` for the azure provider (display only, no write).

#### `VOICE-6` — Language-agnostic voices (locale 'und') trip the locale-mismatch lozenge and G15 as 'voice speaks und'

MINOR · bug

**Files** — `Habibi/src/components/prompt-studio/VoicePanel.tsx:63-65`, `Habibi/src/components/prompt-studio/VoicePanel.tsx:219-224`, `backend/agent_core/cards/compile.py:191`, `backend/agent_core/cards/compile.py:211-225`, `Habibi/src/components/prompt-studio/VoiceCatalogTable.tsx:344-348`, `backend/provider_voice_sync.py:117`, `backend/provider_voice_sync.py:222`

**Mechanism** — primarySubtag('und') is 'und' (VoicePanel.tsx:63-65; compile.py:191), which is never in the card's {en, hi, ...} set, so localeMismatch returns {spoken:'und'} and G15 returns warn 'voice speaks und, card speaks en-IN' (compile.py:219-226). The catalog does hold such rows: VoiceCatalogTable renders locale==='und' as 'auto' (341-345) and provider_tts documents 'und means the vendor gave no language' (137-140). The publish dialog then asks the operator to confirm a mismatch that does not exist.

**Trigger** — Select a Cartesia voice whose row has locale 'und'; the inspector shows 'Locale mismatch — voice speaks und' and compile reports G15 warn.

**Fix** — Treat 'und' (and empty) as 'no claim' in both primarySubtag callers: return null / skip G15 with detail 'voice is language-agnostic'.

#### `VOICE-7` — Detail sheet Cost row still attributes Azure pricing to non-Azure voices

MINOR · bug

**Files** — `Habibi/src/components/prompt-studio/VoicePanel.tsx:900-907`, `Habibi/src/components/prompt-studio/VoiceCatalogBrowser.tsx:67-82`, `backend/db_prompt_studio.py:1173-1181`, `backend/db_prompt_studio.py:1143-1148`

**Mechanism** — tierBadge was fixed to show 'See provider' for providerId !== 'azure' (Browser:67-82), but VoiceDetailCard's Cost row (VoicePanel.tsx:900-907) still prints `~$${approxUsdPer1MChars} / 1M chars` or 'See Azure pricing'. approxUsdPer1MChars comes from LEFT JOIN tts_price_tiers on c.price_tier (db_prompt_studio.py:1180-1184) — Azure's published band — so a Fish/Cartesia row with price_tier 'standard' shows Azure's $15 and one with NULL says 'See Azure pricing'. Both name the wrong vendor.

**Trigger** — Click the (i) on any non-Azure row.

**Fix** — Reuse the tierBadge rule: when voice.providerId && voice.providerId !== 'azure', render 'See provider pricing' and never the number.

#### `VOICE-8` — A failed detail lookup is rendered as the business verdict 'Unknown voice … runtime will speak the fallback'; a failed warning lookup is rendered as no warning

MINOR · degradation-lie

**Files** — `Habibi/src/components/prompt-studio/VoiceCatalogBrowser.tsx:1003-1025`, `Habibi/src/components/prompt-studio/VoicePanel.tsx:642-649`, `Habibi/src/components/prompt-studio/VoicePanel.tsx:330-337`, `Habibi/src/components/prompt-studio/VoicePanel.tsx:523-531`

**Mechanism** — useSelectedCatalogVoice's `.catch` stores {voice:null} for any rejection — 404, 500, network, 401 (Browser:1010-1014) — and the header then says 'Unknown voice <id>' (VoicePanel.tsx:646-648), whose comment asserts the runtime will speak the fallback. fetchTtsVoiceWarning's catch sets warning to null (VoicePanel.tsx:334-335), so an API outage hides a real 'removed' warning; openDetail swallows too (528-530). No toast or retry in any branch.

**Trigger** — API unreachable or returning 5xx while the Voice tab is open: every selected voice reads 'Unknown voice', no catalog warning is shown, Preview still works.

**Fix** — Distinguish isNotFound(err) from other errors in useSelectedCatalogVoice (resolution 'error' with a retry affordance) and toast on non-404 failures of fetchTtsVoiceWarning.

#### `VOICE-9` — Table column sort orders only the pages loaded so far while the header implies a catalog-wide sort

MINOR · bug · **closed** in `6089743` (pass 7)

**Files** — `Habibi/src/components/prompt-studio/VoiceCatalogTable.tsx:106-119`, `Habibi/src/components/prompt-studio/VoiceCatalogBrowser.tsx:226-229`, `Habibi/src/components/prompt-studio/VoiceCatalogBrowser.tsx:702-706`, `backend/db_prompt_studio.py:1149`

**Mechanism** — sorted = [...items].sort(...) (Table:108-119) where items is pages.flatMap (Browser:226-229) of a keyset-paginated query ordered by locale, display_name (db_prompt_studio.py:1149). Sorting 'Voice' A→Z on a 774-row result with 50 loaded shows 50 alphabetised rows; scrolling appends the next page, which re-sorts and interleaves, moving rows the operator was reading.

**Trigger** — Filter to Azure, click the Voice header, scroll.

**Fix** — Pass sort key/dir to /tts-voices/catalog as server-side ORDER BY (with a matching keyset cursor), or disable header sort until hasNextPage is false and say so in the header title.

#### `VOICE-12` — Provider-chip counts and 'All' total ignore the active status filter

trivial · shape-mismatch · deferred: the counts hook lives in Habibi/src/api/providers.ts, the other stream's uncommitted file

**Files** — `backend/db.py:7452-7466`, `backend/db.py:7485-7487`, `Habibi/src/components/prompt-studio/VoiceCatalogBrowser.tsx:386-411`, `Habibi/src/components/prompt-studio/VoiceCatalogBrowser.tsx:514-522`

**Mechanism** — list_tts_voice_provider_counts hardcodes status='GA' (db.py:7460) while the Browser lets the operator switch status to Preview (514-522); the chips keep GA counts, so 'Azure · 774' sits over a list of 12 Preview voices.

**Trigger** — Filters → Status → Preview.

**Fix** — Accept ?status= on /tts-voices/catalog-provider-counts and key the query on it, or hide counts when status !== 'GA'.

---

## Bindings tab — provider models per slot

12 findings — 2 MAJOR, 8 MINOR, 2 trivial; 3 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-bindings.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `BINDINGS-2` — Slot switch keeps the previous slot's modelId; nothing on any layer checks model.kind == binding.slot

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `Habibi/src/components/prompt-studio/BindingsTab.tsx:49`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:59`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:85`, `backend/schemas.py:3426`, `backend/main.py:5489`, `backend/agent_core/providers/persist.py:151`, `backend/alembic/versions/20260821_0092_provider_registry.py:118`, `backend/agent_core/providers/factory.py:154`, `backend/agent_core/providers/factory.py:224`

**Mechanism** — `setSlot` (BindingsTab.tsx:85) does not reset `modelId` (state at :49). The models query re-fetches for the new slot but the Select's value still holds the old slot's provider_model_id, and `canSave = Boolean(modelId) && priorityValid` (:59) is true, so Save posts a tts model id under slot='stt'. ProviderBindingInput (schemas.py:3426-3436) validates only the slot string; upsert_provider_binding (main.py:5490) does no kind check; upsert_binding (persist.py:151-205) writes it; the table has no CHECK relating slot to provider_models.kind (migration 0092:113-131). At runtime resolve_chain joins on provider_model_id and filters only b.slot (factory.py:152-154), so the STT position of the pipeline is handed a TTS service class, which imports and constructs successfully (factory.py:225,239) — the call ends up with no recogniser.

**Trigger** — Add binding → Slot="Text to speech" → pick "Microsoft Azure · Azure neural" → change Slot to "Speech to text" → Save. Row is accepted and the table renders it green "Enabled" under the Speech-to-text slot.

**Fix** — Reset modelId in setSlot's handler; and reject the mismatch server-side — join provider_models in upsert_provider_binding (main.py:5490) and 422 when m.kind != payload.slot, plus a DB CHECK/trigger so curl cannot write it either.

#### `BINDINGS-3` — The model picker offers unconfigured, preview-only and unconstructable models with no marking; binding one renders green and silently runs Azure

**MAJOR** · degradation-lie · prior: AGENT_STUDIO_BUG_HUNT.md:247 cross-cutting theme 1 ("bindings render dead vendors green") — still present; the Bindings tab had no section of its own in that audit. · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `Habibi/src/components/prompt-studio/BindingsTab.tsx:105`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:204`, `Habibi/src/api/providers.ts:49`, `backend/main.py:5455`, `backend/agent_core/providers/registry.py:454`, `backend/agent_core/providers/registry.py:529`, `backend/agent_core/providers/openrouter_tts.py:192`, `backend/agent_core/providers/factory.py:285`, `backend/voice/provider_bind.py:80`

**Mechanism** — GET /providers/models returns `configured` (false when no API key), `runtime` ('live'|'preview_only'|'unavailable') and `runtimeDetail` precisely so a picker can say why a model will not run (main.py:5424-5470; the fields are typed at providers.ts:42-51). BindingsTab renders `{m.providerName} · {m.displayName}` and nothing else (:105-109). OpenRouter's fish-audio/s2.1-pro is declared live_capable=False (registry.py:452) and its service class raises NotImplementedError on construction (openrouter_tts.py:192-197); the Deepgram/Speechmatics recognisers need Pipecat extras that are not installed. Binding one produces a row whose State column reads a green "Enabled" lozenge (:204-208) — enabled is the row's own boolean, not a health check — while provider_bind's generic `except Exception` swallows the build failure and returns the hardcoded Azure fallback (provider_bind.py:82-99). VoiceParamsPanel.tsx:401 already renders runtimeDetail correctly, so the pattern exists in-repo.

**Trigger** — Bind OpenRouter · Fish Audio S2.1 Pro to the tts slot. The Bindings table shows Enabled/green forever; every call runs Azure; the only evidence is an ERROR line in the voice container's log.

**Fix** — In the option list, show `configured`/`runtime` (grey + reason for preview_only/unavailable, as VoiceParamsPanel does) and disable non-live SelectItems. In the table, replace the enabled-only State lozenge with a resolved health state that folds in the model's runtime status.

#### `BINDINGS-1` — The "Language model" slot is a slot nothing can fill and nothing reads

MINOR · dead-config · DOWNGRADED

**Files** — `Habibi/src/components/prompt-studio/BindingsTab.tsx:40`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:44`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:105`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:141`, `backend/agent_core/providers/registry.py:53`, `backend/agent_core/providers/persist.py:97`, `backend/voice/bot.py:638`, `backend/voice/bot.py:655`, `backend/voice/bot.py:683`, `backend/voice/llm_pool.py:42`, `backend/schemas.py:3429`

**Mechanism** — BindingsTab offers three slots including llm; the backend accepts slot='llm' (schemas.py:3429 pattern, and the migration CHECK) and would store the row. But the registry SEED contains zero ModelSpec with kind="llm" (15 specs, all stt/tts), so GET /providers/models?kind=llm returns []. Worse, even a hand-crafted llm binding is unreachable: provider_bind is called only for 'stt' and 'tts' (voice/bot.py:638,655) and the LLM is constructed unconditionally as KeepAliveAzureLLMService from AZURE_OPENAI_VOICE_* env (voice/bot.py:683, llm_pool.py:44-57). bot_runtime.py and sandbox_runtime.py never touch the registry at all.

**Trigger** — Open Bindings → Add binding → Slot = "Language model". The Model picker renders zero items behind the placeholder "Pick a model" with no error and no explanation (BindingsTab.tsx:100-111 has an isError branch but no empty branch). The operator reads this as "the catalog hasn't loaded", not "this slot does not exist".

**Fix** — Either drop 'llm' from SLOTS/SLOT_LABEL (BindingsTab.tsx:40-45) and from the schema pattern until an llm ModelSpec and an llm consumer exist, or render an explicit empty state ("no models are registered for this slot") and route the voice LLM through provider_bind like STT/TTS. Do not leave a slot that stores a row the runtime cannot read.

#### `BINDINGS-10` — Empty state describes a fallback that does not exist ("whatever the registry defaults to")

MINOR · doc-vs-code

**Files** — `Habibi/src/components/prompt-studio/BindingsTab.tsx:282`, `backend/agent_core/providers/factory.py:265`, `backend/voice/provider_bind.py:70`, `backend/voice/bot.py:646`, `backend/voice/bot.py:669`, `backend/voice/tuning_apply.py:266`

**Mechanism** — The empty state says the runtime "falls back to whatever the registry defaults to" (:282-284). The registry has no default: NoBindingError is raised (factory.py:262-265) and provider_bind substitutes the caller's `fallback` lambda, which in both cases constructs a hardcoded Azure service (bot.py:644-650 AzureSTTService, bot.py:670-676 KeepAliveAzureTTSService) using AZURE_SPEECH_* env. The distinction matters because that Azure fallback still receives the card's tuning voice (tuning_apply.py:236) — a card whose Voice tab selected a Cartesia or Fish voice and has no tts binding sends a non-Azure voice name to Azure TTS.

**Trigger** — Read the empty state on any card with no bindings; or select a non-Azure voice on the Voice tab of a card with no tts binding and place a call.

**Fix** — Say what actually happens: "no binding — the call runs the Azure default configured in the environment". Separately, warn on this tab (or at compile) when the card's selected voice belongs to a provider that has no binding for the tts slot.

#### `BINDINGS-11` — The tab explains and lists tenant defaults but can only ever create card-scoped rows, and has no enable/disable control for the State it displays

MINOR · code-organization

**Files** — `Habibi/src/components/prompt-studio/BindingsTab.tsx:66`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:197`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:204`, `backend/schemas.py:3431`, `backend/schemas.py:3436`

**Mechanism** — AddBindingRow hardcodes `botId` into the payload (:66) — the API accepts botId:null (schemas.py:3431) but the UI never sends it, so a tenant default can only be created by curl even though the table renders, explains and can delete them (:197-198, :310-313). Likewise the State column renders Enabled/Disabled (:204-208) with no control to toggle it; POST always sends the schema default enabled=true (schemas.py:3436), so a disabled binding can only be re-enabled as a side effect of re-saving it at the same identity — which also nulls its voice_ref (BINDINGS-7).

**Trigger** — Try to add a tenant default, or to disable a binding without deleting it, from this screen.

**Fix** — Add a Scope control (This card / Tenant default) to the add form with a confirmation for the tenant option, and an enabled toggle that PATCHes/upserts only that field.

#### `BINDINGS-5` — Provider provenance is written on every call and read by nothing — the Azure fallback leaves no record anywhere

MINOR · disconnected · DOWNGRADED

**Files** — `backend/voice/provider_bind.py:116`, `backend/voice/provider_bind.py:124`, `backend/voice/bot.py:653`, `backend/voice/bot.py:677`, `backend/voice/bot.py:678`, `backend/voice/bot.py:700`

**Mechanism** — provider_bind.record() stamps `session.extra["providers"][slot] = {provider, model, bindingId, source}` on every bind (called at bot.py:653,677). Its docstring (:121-127) states the purpose: "Analytics attributes cost and latency per provider. Without this it would read the *configured* provider from the binding table and attribute a call that actually fell back to Azure against Cartesia's numbers." Nothing reads it. Searching `.extra[` across backend/voice/** finds writers and readers for amd, call_sid, mission, tuning, ending, audio_media_id — and no reader for "providers". voice/persist.py contains no occurrence of the string at all, so it is not persisted to the call record and no endpoint can surface it. The module docstring's claim (:25-27) that "the transcript and the CRM record cannot claim a provider that never spoke" is therefore false — those records say nothing about the provider in either direction.

**Trigger** — Any call where the bound provider is down or unconstructable: provider_bind returns Azure with source='fallback', the Bindings tab still shows the bound vendor green, and no artefact outside a container log line says which engine spoke.

**Fix** — Persist session.extra['providers'] onto the call/interaction row at teardown (voice/persist.py) and surface source != 'binding' in the Bindings tab and the call detail, so a fallback is visible where the binding is asserted.

#### `BINDINGS-6` — "Edit" discards the row it was clicked on and opens a blank Add form

MINOR · bug

**Files** — `Habibi/src/components/prompt-studio/BindingsTab.tsx:47`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:163`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:212`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:303`

**Mechanism** — BindingRow declares `onEdit: (b: ProviderBinding) => void` and calls it with the binding (:212). The parent passes `onEdit={() => setAdding(true)}` (:303), throwing the argument away. AddBindingRow has its own initial state (slot="tts", modelId="", locale="", priority="100", :48-51) and no props to seed it, so "Edit" on an stt row at priority 50 in locale en-IN opens an empty tts/100/any form.

**Trigger** — Click Edit on any binding row.

**Fix** — Either lift the row into AddBindingRow as initial state (and rename the button's effect accordingly), or remove the Edit button until an edit form exists — an inert control that looks like it loaded nothing is worse than no control.

#### `BINDINGS-7` — Re-saving a binding at the same identity nulls its voice_ref, and the form has no field to carry it back

MINOR · bug · deferred: voice_ref column: schemas/integrations.py and providers/persist.py are the other stream's uncommitted files (provider runtime, 2026-09-13)

**Files** — `Habibi/src/components/prompt-studio/BindingsTab.tsx:61`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:149`, `backend/schemas.py:3433`, `backend/main.py:5498`, `backend/agent_core/providers/persist.py:187`

**Mechanism** — AddBindingRow's save (:61-78) sends slot/providerModelId/botId/locale/priority and no voiceRef; ProviderBindingInput defaults voiceRef to None (schemas.py:3433); upsert_binding's ON CONFLICT sets `voice_ref = EXCLUDED.voice_ref` (persist.py:186), i.e. NULL. Identity is (tenant, bot, slot, locale, priority) and the form's priority default is always "100", so re-adding the same slot at the default priority overwrites rather than extending the failover chain — the copy at :149-151 says so, but not that the voice is dropped. Contained because voice_ref is not read at runtime today (see BINDINGS-8); it becomes real the moment that guard is reachable.

**Trigger** — A binding whose voice_ref was set out-of-band (the only writer is this POST, so today only curl); re-save the same slot/locale/priority from the tab → Voice column goes to "—".

**Fix** — Use ON CONFLICT ... SET voice_ref = COALESCE(EXCLUDED.voice_ref, agent_provider_bindings.voice_ref), or add a Voice field to the form and require the caller to state it explicitly.

#### `BINDINGS-8` — The Voice column shows a field the TTS path can never read

MINOR · dead-config

**Files** — `Habibi/src/components/prompt-studio/BindingsTab.tsx:192`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:294`, `backend/agent_core/providers/factory.py:226`, `backend/voice/tuning_apply.py:235`, `backend/voice/bot.py:661`

**Mechanism** — factory.build applies voice_ref only under `if binding.voice_ref and "voice" not in settings` (factory.py:227-228), where `settings = {**binding.settings, **overrides}` (:226) and overrides are tts_settings_kwargs(tuning), which unconditionally sets `kwargs["voice"] = tts["voice"]` (tuning_apply.py:235-236) on the only live TTS bind (bot.py:655-659). The guard is therefore never true on the audio path: the voice always comes from the card's tuning (Voice tab), never from the binding. The table nonetheless devotes a "Voice" column to it (:294, :192), asserting a determinant of what the caller hears.

**Trigger** — Any TTS call. A binding row displaying voiceRef 'en-IN-NeerjaNeural' while the card's tuning says a Cartesia voice will speak the Cartesia voice.

**Fix** — Either make voice_ref authoritative for the bound engine (and have the Voice tab write it), or drop the column and the `voice_ref` argument path so no screen claims a control that does nothing — the repo already applies that rule to empty params_schemas (registry.py:194-210).

#### `BINDINGS-9` — Locale is unvalidated free text matched exactly at runtime; a typo yields a permanently green binding that never applies

MINOR · degradation-lie · deferred: locale 422: routers/integrations.py is the other stream's uncommitted file

**Files** — `Habibi/src/components/prompt-studio/BindingsTab.tsx:67`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:113`, `Habibi/src/api/providers.ts:22`, `backend/agent_core/providers/factory.py:158`, `backend/voice/bot.py:635`, `backend/agent_core/tuning.py:302`

**Mechanism** — The Locale input (:113-121) is a bare text box with placeholder "any" and no validation, no format hint and no use of the selected model's declared `locales` array (typed at providers.ts:28, populated from registry ModelSpec.locales). save() sends `locale.trim() || null` (:67). resolve_chain matches `b.locale = :locale` (factory.py:158) — an exact, case-sensitive Postgres comparison against bind_locale, which is normalize_tuning's stt.language, e.g. 'en-IN' (bot.py:636, tuning.py:302). 'en-in', 'en', 'English' or 'en_IN' all store and display fine and never match, and the row renders green "Enabled" with the tab's footer (:310-313) explaining a resolution order it will never enter.

**Trigger** — Type 'en-in' (or any non-BCP-47-cased value) in Locale and save. Table shows the binding as active; every call resolves past it to the next candidate or the Azure fallback.

**Fix** — Replace the free-text input with a select seeded from the chosen model's `locales` (plus an explicit "any"), or normalise/validate the value server-side in upsert_provider_binding against the model's declared locales and 422 on a value the model does not serve.

#### `BINDINGS-12` — Icon-only delete button has no accessible name; its only warning is a title tooltip

trivial · a11y · DOWNGRADED

**Files** — `Habibi/src/components/prompt-studio/BindingsTab.tsx:223`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:229`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:128`

**Mechanism** — The button's only child is `<Trash2 aria-hidden-less icon />` (:229) with no aria-label and no visually hidden text; the `title` (:223-227) is the sole carrier of both the name and the "affects every card" warning. Screen-reader users hear an unnamed button in every row; the tenant-scope warning is unreachable by keyboard and on touch. Contrast with the Locale/Priority inputs in the same file, which do carry aria-label (:119, :127).

**Trigger** — Tab to the delete control in any binding row with a screen reader.

**Fix** — Add an aria-label that states scope and action (e.g. `Remove tenant-default text-to-speech binding — affects every card`), and move the warning into visible copy or a confirm dialog (see BINDINGS-4).

#### `BINDINGS-13` — No test covers the bindings CRUD endpoints or the tab

trivial · test-gap · DOWNGRADED · **closed** in `40557ab` (pass 7)

**Files** — `backend/tests/test_voice_provider_bind.py:1`, `backend/tests/test_provider_registry_runtime.py:1`, `Habibi/src/components/prompt-studio/BindingsTab.tsx:1`

**Mechanism** — backend/tests covers provider_bind's fallback semantics (test_voice_provider_bind.py), the pool, preview routing and registry runtime status — but nothing exercises POST/DELETE /providers/bindings, so the missing slot/kind check (BINDINGS-2) and the voice_ref-nulling upsert (BINDINGS-7) have no failing test to catch them. There is no test file for BindingsTab.tsx anywhere under Habibi/src, so the tenant-scoped delete and the un-reset modelId are unguarded on both sides.

**Trigger** — n/a — coverage observation.

**Fix** — Add an API test asserting a 422 on slot/kind mismatch and that a re-upsert preserves voice_ref, and a component test asserting that changing Slot clears the chosen model and that deleting an inherited row requires confirmation.

---

## Policy tab — the six locked engines

8 findings — 0 MAJOR, 5 MINOR, 3 trivial; 1 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-policy.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `POLICY-1` — card.policy_bindings has zero runtime readers — the Policy tab authors nothing and binds nothing

MINOR · disconnected · DOWNGRADED

**Files** — `backend/agent_core/cards/schema.py:20`, `backend/agent_core/cards/schema.py:133-141`, `backend/agent_core/cards/schema.py:386`, `backend/agent_core/cards/compile.py:593-616`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:202-242`, `Habibi/src/routes/prompt-studio.lazy.tsx:1399`, `backend/voice/bot.py:1138-1144`, `backend/agent_core/tools/grant.py:207-213`

**Mechanism** — A repo-wide grep for `policy_binding` under backend/ (excluding .venv) returns exactly four hits: schema.py:386 (the field), compile.py:596/601/609/616 (gate G3), and one test. No file under backend/voice/**, bot_runtime.py, bot_tools.py, sandbox_runtime.py, outbound.py, mission.py, cadence.py or agent_core/** (other than cards/compile.py) mentions it. backend/voice/ references the card at exactly one place — voice/tools.py:2781-2788 card_for() for the handoff allowlist — and never touches policy_bindings. Meanwhile the field it displays is `PolicyBinding = Literal["required"]` (schema.py:20) on a model where all six fields default to "required" (schema.py:133-141) with extra="forbid", so a card that passes AgentCard.model_validate (compile.py:560) necessarily has all six == "required". The tab has no onChange (AgentCardPanels.tsx:202, prompt-studio.lazy.tsx:1399), no button, no link and no query. It is therefore a read-only render of six values that can never differ, describing a contract nothing enforces at runtime.

**Trigger** — Open Prompt Studio → any bot → Policy. Six green "required" lozenges. Change nothing (there is nothing to change), publish, place a call: no code path anywhere consults the field.

**Fix** — Either give the binding teeth or stop presenting it as one. Teeth: have the runtime read it — e.g. voice/tools.py's recommend_next_offer / evaluate_authority handlers and voice/persist.py's live_qa call should refuse to run (or hard-fail the call) when the active bundle's card does not bind the engine, and contact_policy.evaluate should record the binding it enforced. Honesty: delete PolicyBindings and G3's binding half, and replace the tab with a read-only "engine status" panel that reports the real gates (the four *_MODE env values and the DB rules) plus links to the screens that own them.

#### `POLICY-2` — Policy tab claims four engines "decide" while all four ship in shadow mode, gated by process-wide env vars the tab cannot see

MINOR · degradation-lie · DOWNGRADED

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:206-209`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:226-227`, `backend/.env.example:410`, `backend/.env.example:478`, `backend/.env.example:542`, `backend/.env.example:555`, `backend/agent_core/reco/engine.py:270-278`, `backend/agent_core/reco/engine.py:113`, `backend/agent_core/authority/engine.py:290`, `backend/agent_core/reco/config.py:51-62`, `backend/agent_core/treatment/config.py:50-64`, `backend/agent_core/authority/config.py:23-36`, `backend/agent_core/live_qa/config.py:34-48`

**Mechanism** — The tab's standing copy is "These engines decide. The mouth cannot unbind them. Reco / treatment / authority / live QA / DND stay code with a log." and every row renders `<Lozenge tone="success">required</Lozenge>` whenever the (always-present, always-"required") binding is read. But whether an engine decides anything is set by four environment variables read at call time — reco/config.py:53-62 (RECO_MODE), treatment/config.py:50-60 (TREATMENT_MODE), authority/config.py:23-36 (AUTHORITY_MODE), live_qa/config.py:34-45 (LIVE_QA_BARGE_MODE) — each defaulting to shadow and shipped as `shadow` in .env.example:410,478,542,555. In shadow, reco/engine.py:247-256 returns `suppressed=True, reason="shadow_mode"` with zero offers on every call, and authority/engine.py:290 sets `suppressed = mode != MODE_LIVE` so every authority verdict is advisory. These are process-wide: no per-tenant, per-bot or per-card override exists. The one screen in the studio labelled Policy therefore asserts, in the reassuring colour, that four engines are live and binding on a deployment where all four are muted, and it has no read of the mode at all.

**Trigger** — Deploy with the shipped backend/.env.example (all four modes = shadow). Open Prompt Studio → Policy on any agent. Six green "required" lozenges under "These engines decide." Then place a call: recommend_next_offer returns suppressed=shadow_mode every time and no offer is ever spoken.

**Fix** — Surface the engine mode next to each binding. Add a small read endpoint (or extend the compile report) that returns the four resolved modes, and render `required · engine: shadow` in warning tone when a bound engine is not live — a bound engine running in shadow or off is exactly the state an operator needs to see on a screen called Policy. Fix the copy so it says what the binding actually guarantees (the tool stays on the card) rather than that the engine decides.

#### `POLICY-3` — Two of the four rows name a mouth tool that does not exist in any catalog or call path

MINOR · stale

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:55-62`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:215-217`, `backend/agent_core/cards/schema.py:55-68`, `backend/agent_core/tools/catalog.py:437`, `backend/agent_core/tools/catalog.py:723`, `backend/voice/persist.py:838-862`, `backend/flow_graph.py:806-831`

**Mechanism** — POLICY_ENGINES lists `{ key: "treatment", tool: "recommend_treatment" }` and `{ key: "live_qa", tool: "evaluate_live_qa" }`, and the row renders the string in a monospace slot identical to the two rows that *are* real tools. Neither name exists in agent_core/tools/catalog.py (which defines only evaluate_authority:437 and recommend_next_offer:723 of the four), neither is in LOCKED_MOUTH_TOOLS (schema.py:66-68), and neither has a handler in voice/tools.py or bot_tools.py. recommend_treatment is invoked only from batch/event paths outside a call (db.py:997, db_treatment_holds.py:306, payment_events.py:443, promise_fulfillment.py:834, treatment/followthrough.py:436, treatment/sweep.py:177); evaluate_live_qa is invoked once per persisted turn from voice/persist.py:842 and is not a tool at all. schema.py:56-57 states this honestly ("two are Python engines with no mouth tool (yet)"); the tab does not, and the Tools tab — which builds its rows from the catalog via flow_graph.py:800-829 — cannot show either name, so an author who goes looking for the tool the Policy tab named finds nothing.

**Trigger** — Open Policy, read "Treatment · recommend_treatment", switch to Tools and search for recommend_treatment. It is not in the table, because it is not a tool.

**Fix** — Mark the two engine-only rows distinctly — drop the monospace tool slot and label them "Python engine — no mouth tool" (the wording schema.py already uses), or render them in a separate group below the two catalog tools. Derive the flag from LOCKED_MOUTH_TOOLS rather than hardcoding `tool: null` per row.

#### `POLICY-4` — In dev mock mode the Policy tab reports six unbound engines and a blocked publish for every agent

MINOR · bug · prior: 2j

**Files** — `Habibi/src/api/agent-studio.ts:97-98`, `Habibi/src/api/agent-studio.ts:292-306`, `Habibi/src/api/config.ts:15-27`, `Habibi/src/data/prompt-studio-seed.ts`, `Habibi/src/routes/prompt-studio.lazy.tsx:141-144`, `Habibi/src/routes/prompt-studio.lazy.tsx:438-441`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:203`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:232-236`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:64-71`, `backend/agent_core/cards/compile.py:595-616`, `backend/db_prompt_studio.py:209`

**Mechanism** — Every entry in MOCK_CARDS carries `agentCard: {}` and `publishedCard: {}` (agent-studio.ts:97-98 for intake-v1, same for the rest), and the mock prompt-version store never seeds an agentCard either. asCard (prompt-studio.lazy.tsx:141-144) returns null for a zero-key object, so effectiveCard collapses to the `?? {}` terminal at prompt-studio.lazy.tsx:439. PolicyTab then reads `bindings = card.policy_bindings ?? {}` (AgentCardPanels.tsx:203) — every key undefined — and falls into the third branch, rendering six danger lozenges reading "not bound — G3 blocks publish" with the tooltip "G3 fails a card that does not bind every engine." That claim is false even on its own terms: PolicyBindings has default_factory values for all six (schema.py:133-141), so a card whose JSON omits policy_bindings entirely validates with all six == "required" and G3 passes (compile.py:600-616). Dev default is mock=true (config.ts:25), so this is the state every developer and every offline demo sees. PolicyTab has no isPending/isError/not-authored branch — the file already has NotAuthoredNotice (AgentCardPanels.tsx:64-71) and this tab is the one that never uses it.

**Trigger** — `npm run dev` with no VITE_USE_MOCK set → Prompt Studio → any agent → Policy. Six red "not bound — G3 blocks publish" rows for cards that compile clean.

**Fix** — Give PolicyTab the not-authored branch the other tabs have: `if (!isAuthoredCard(card)) return <NotAuthoredNotice what="policy bindings" />` before the list. And correct the missing-key lozenge — an absent policy_bindings object is filled by the server-side default and does not block publish; only a present-but-wrong value does, and that value cannot survive validation either (see POLICY-5). Seeding the mock cards with a real card dump would also stop the demo lying.

#### `POLICY-5` — G3's binding half is unreachable, and the test that claims to cover it asserts a different gate

MINOR · test-gap

**Files** — `backend/agent_core/cards/compile.py:595-616`, `backend/agent_core/cards/schema.py:20`, `backend/agent_core/cards/schema.py:133-141`, `backend/tests/test_agent_card_compile.py:55-62`

**Mechanism** — G3 computes `missing = [key for key in REQUIRED_POLICY_KEYS if getattr(card.policy_bindings, key, None) != "required"]`, but `card` at that point is the product of AgentCard.model_validate (compile.py:560). PolicyBindings declares all six fields as `PolicyBinding = Literal["required"]` with that literal as the default and extra="forbid", so validation either fills every key with "required" or raises. `missing` is therefore always empty and the "missing_bindings" issue can never be emitted. The test named `test_unbinding_reco_fails_g3` proves the point rather than the gate: it sets `dumped["policy_bindings"]["reco"] = "off"` and then asserts `g0.status == "fail"` — G0, not G3 — because the invalid literal aborts validation, leaves card None, and makes G3 emit "skipped — no card" (compile.py:596). So the gate the test is named for is never exercised and cannot be. Only G3's second half (LOCKED_POLICY_ENGINES ⊆ card.tools.locked, compile.py:604) is live.

**Trigger** — Read compile.py:598-615 against schema.py:133-141; run backend/tests/test_agent_card_compile.py::test_unbinding_reco_fails_g3 and observe it passes on G0.

**Fix** — Drop the `missing` computation and the misleading issue key, leaving G3 as the locked-tools check it actually is, and rename the test to test_unbinding_reco_fails_g0 (the behaviour is correct — a bad literal should fail schema — the name is what lies). If policy bindings are meant to become multi-valued, widen PolicyBinding to a real Literal union first; only then does G3's binding half have work to do.

#### `POLICY-6` — The tab restates the six-key policy vocabulary locally and imports the shared constant without using it

trivial · code-organization · DOWNGRADED

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:26`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:29`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:55-62`, `Habibi/src/api/agent-card.ts:116-125`, `Habibi/tsconfig.json:19-20`, `backend/agent_core/cards/schema.py:70-77`

**Mechanism** — `REQUIRED_POLICY_KEYS` (line 26) and `type PolicyKey` (line 29) are imported into AgentCardPanels.tsx and never referenced anywhere in the 1000+ line file — a grep for either name in that file returns only the import lines. The tab instead hardcodes its own six-entry POLICY_ENGINES array (55-62). The intent to derive from the shared list is visible in the import and was not carried out. Consequence: if backend REQUIRED_POLICY_KEYS (schema.py:70-77) gains a seventh key, G3 will start failing publishes for a binding the Policy tab does not render and gives no way to see — the same class of drift the file's own header comment (lines 22-30) says the typed card was introduced to prevent. TypeScript will not catch it, because POLICY_ENGINES keys are only used to index a Partial record.

**Trigger** — Add a key to backend REQUIRED_POLICY_KEYS. The frontend compiles clean, the Policy tab renders six rows, and G3 blocks publish on the seventh.

**Fix** — Build POLICY_ENGINES by mapping over REQUIRED_POLICY_KEYS with a `Record<PolicyKey, {label, tool}>` lookup, so the array is exhaustive by construction and a new backend key is a TypeScript error until the label is supplied. That also makes the two imports live.

#### `POLICY-7` — The Policy tab is a navigational dead end: it names six engines and links to none of the five screens that configure them

trivial · disconnected · DOWNGRADED · **closed** in `6089743` (pass 7)

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:202-242`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:2-3`, `Habibi/src/routes/upsell.tsx`, `Habibi/src/routes/treatment.tsx`, `Habibi/src/routes/qa.tsx`, `Habibi/src/routes/routing.tsx`, `Habibi/src/routes/consent.tsx`

**Mechanism** — PolicyTab renders no `<Link>` and no button; the `Link` and `ExternalLink` imports at AgentCardPanels.tsx:2-3 are consumed by other tabs in the file. Every one of the six rows has a real configuration surface elsewhere in the app — upsell.tsx for reco, treatment.tsx for treatment, qa.tsx for live QA, routing.tsx for routing rules (the rows db_routing.py:648 actually evaluates), consent.tsx for DND/consent (the state contact_policy.py:487,529 actually reads) — and the tab points at none of them. An operator who arrives here because something about policy is wrong has nowhere to go from the screen named Policy.

**Trigger** — Open Policy. Try to act on any row. There is no control and no destination.

**Fix** — Give each row a right-hand "Configure →" link to its owning route (reco → /upsell, treatment → /treatment, authority → the authority matrix screen, live_qa → /qa, routing → /routing, dnd → /consent). That turns a tautological display into the index it should be.

#### `POLICY-9` — Tab copy enumerates five engines for six rows and credits the card with a DND relationship it does not have

trivial · doc-vs-code

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:206-209`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:55-62`, `backend/contact_policy.py:487`, `backend/contact_policy.py:529`

**Mechanism** — The lead paragraph lists "Reco / treatment / authority / live QA / DND" — five — above a list of six rows; `routing` is silently omitted from the prose and present in the UI. The closing sentence, "This card cannot disable DND", implies the card stands in some relationship to DND. It does not: DND is read entirely from customer and consent rows in contact_policy.py (_veto at :487 checks `customer['dnd'] or customer['dnd_registry']`, evaluate at :529), and contact_policy.py contains no reference to an agent card of any kind. No card can disable DND for the same reason no card can enable it.

**Trigger** — Read the tab header against the six rows below it.

**Fix** — Say six things if six render, and replace "This card cannot disable DND" with what is true — DND and calling hours are enforced in contact_policy.py from consent state, outside the card entirely — ideally next to the link POLICY-7 asks for.

---

## Card editor shell — hydration, autosave, drafts, publish

17 findings — 1 MAJOR, 11 MINOR, 5 trivial; 3 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-shell.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `SHELL-2` — Rollback (a production re-publish) is gated by BOT_WRITE while publish needs AGENT_PUBLISH; card edits via the editor need only BOT_WRITE although the card route demands AGENT_EDIT

**MAJOR** · security · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/db_prompt_studio.py:2347-2404`, `backend/main.py:3382-3385`, `backend/main.py:2995-3000`, `backend/db_prompt_studio.py:1774-1778`

**Mechanism** — ROUTE_PERMISSIONS maps POST /bot-deployments/{id}/rollback to BOT_WRITE (authz.py:280) but POST /prompt-versions/{id}/publish to AGENT_PUBLISH (:291). rollback_bot_deployment archives the live row, sets another version 'published' and inserts an active production deployment (db_prompt_studio.py:2340-2410) — the same effect as publish, minus compile gates — so an actor allowed to author but not to publish can still swap what live callers hear. Separately, the editor never calls PATCH /agent-studio/cards (AGENT_EDIT, authz.py:302); its autosave carries agentCard inside PATCH /prompt-versions (BOT_WRITE, authz.py:289; lazy.tsx:654; toPatchInput prompt-studio.ts:115), so tools, handoffs, connectors and policy bindings are editable with BOT_WRITE alone. ROLE_DEFAULTS (authz.py:151-203) grant BOT_WRITE only to admin today, so the split is latent until an operator configures a custom role; the catalogue text for BOT_WRITE ('Author and publish prompts…', :130) already contradicts the table.

**Trigger** — Grant a role BOT_WRITE without AGENT_PUBLISH/AGENT_EDIT; that user opens History → 'Rollback to …' and production swaps; they also toggle tools on the Tools tab and the card autosaves.

**Fix** — Map POST /bot-deployments/{id}/rollback to AGENT_PUBLISH, and either require AGENT_EDIT for PATCH /prompt-versions bodies that carry agentCard (check in the handler) or route card edits through the AGENT_EDIT endpoint.

#### `SHELL-1` — Fingerprint drift from server-normalised fields: permanent 'unsaved' chip after 'Start from blank', adding a flow node, or authoring a zero-version bot

MINOR · bug · prior: 2.1 — key-order half fixed at lazy.tsx:162-171; the omitted-fields half the same comment describes is still present

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:1527`, `backend/db_prompt_studio.py:1770-1772`, `backend/schemas.py:2377-2389`

**Mechanism** — stableStringify fixes key order but keeps `null` and `[]` distinct from an absent key (stable-stringify.ts:22-26 drops only undefined). Local shapes lack fields the server always echoes: emptyGraph() and newNodeData() emit nodes without `entryFor` while FlowNodeData.entryFor defaults to [] (flow_graph.py:167) and PromptVersionResponse serialises it; DEFAULT_VOICE has no `style`/`params` while _prompt_voice always emits `style: None` and `params: {}` (db_prompt_studio.py:116,122; tuning.py:241-242). After a save, markSaved stores the server-shaped fingerprint (lazy.tsx:656-665) while local state keeps the seed shape, so `unsaved` (lazy.tsx:528-537) is true for the rest of the session, 'Draft saved' can never render (StudioHeader.tsx:104), and when draftId flips null→id the effect re-runs and issues one redundant PATCH (deps lazy.tsx:684-699). The 2026-08-25 fix comment (lazy.tsx:148-160) describes exactly this omitted-fields case as solved; only the key-order half is.

**Trigger** — Flow tab → 'Start from blank' (or add a node on the canvas), wait 1.2 s: header reads 'unsaved · draft vX' forever although the PATCH succeeded. Or open a bot with zero prompt versions and type a prompt.

**Fix** — After a successful save adopt the echoed row into local state for the structured fields (setFlow(draft.flow), setVoice(draft.voice)) when the operator has not edited since the request started, or normalise locally before fingerprinting (entryFor: [], style: null, params: {}) — and make emptyGraph()/newNodeData() emit entryFor: [].

#### `SHELL-10` — publish() ignores an in-flight autosave; the race creates an orphan or post-publish duplicate draft

MINOR · bug

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:940-990`, `Habibi/src/routes/prompt-studio.lazy.tsx:643`, `Habibi/src/api/prompt-studio.ts:942-989`, `Habibi/src/api/prompt-studio.ts:1018-1026`, `Habibi/src/api/prompt-studio.ts:922-940`

**Mechanism** — publish() reads draftId synchronously (lazy.tsx:947) and does not await savingRef (:643). If the first autosave is still creating the draft (draftId null), publishStudioDraft creates and publishes a second version (prompt-studio.ts:979-987) and the autosave's row lands as an identical orphan draft that hydration will resume on reload (lazy.tsx:386-388). If an autosave PATCH lands after promotion it gets 409 prompt_version_not_draft, which isDraftPatchFallbackError (:922-940) treats as 'draft gone' → createPromptVersion → a fresh draft identical to the version just published appears seconds after 'Published vX'. The effect cleanup clears the debounce timer on publish, so only in-flight requests race.

**Trigger** — Type, immediately open Publish and confirm within ~1.5 s on a slow API.

**Fix** — Have publish await any in-flight ensureDraft (or the mutation's isPending) and cancel the timer explicitly; do not fall back to create when the 409 detail is prompt_version_not_draft and the version is now published.

#### `SHELL-12` — A transient card-GET refetch failure after hydration replaces the whole editor with the 'Could not load' panel and disables autosave

MINOR · degradation-lie

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:1350-1368`

**Mechanism** — `blocked` checks cardQuery.isError regardless of whether data is already present (lazy.tsx:1193-1215). The card query refetches on window focus and on every autosave invalidation (prompt-studio.ts:134); after retryUnlessClientError exhausts (agent-studio.ts:292-305) a 5xx sets isError with stale data retained, the editor subtree unmounts (:1360-1375) and autosave returns early (:621) while the operator's unsaved text is still in state with only 'Back to the fleet' offered.

**Trigger** — Edit, then let the API return 500 for /agent-studio/cards/{id} on a focus refetch.

**Fix** — Block only when cardQuery.isError && !cardQuery.data; otherwise show an inline banner and keep autosaving against the known-good botId.

#### `SHELL-13` — Version list is a silent 200-row page: an old published row can drop out, flipping the header to 'never published' and resetting labels

MINOR · bug · **closed** in `6089743` (pass 7)

**Files** — `backend/db_core.py:211`, `backend/db_core.py:215`, `backend/db_prompt_studio.py:225`, `Habibi/src/api/prompt-studio.ts:165-169`, `Habibi/src/routes/prompt-studio.lazy.tsx:413-425`, `Habibi/src/routes/prompt-studio.lazy.tsx:541`, `Habibi/src/components/prompt-studio/StudioHeader.tsx:80-84`

**Mechanism** — fetchPromptVersions passes no limit (prompt-studio.ts:165-169) so list_prompt_versions clamps to DEFAULT_LIST_LIMIT=200 newest-first (db_core.py:211,215; db:225). publishedRow/published are derived from that page (lazy.tsx:413-425); once a bot accumulates >200 newer drafts/archives/restores, the live row vanishes from the list, the header says 'never published' (StudioHeader.tsx:80-84), nextLabel restarts at v1.1 (:541), `dirty` diffs against history[0], and versionCount understates.

**Trigger** — Long-lived bot with many autosave-created drafts and restores (each restore, sandbox try on a discarded draft, and publish adds a row).

**Fix** — Read the live row from GET /prompt-versions/published?botId (main.py:2043, fetcher already exists) instead of scanning the page, and paginate the drawer.

#### `SHELL-3` — Restore-as-draft stores label NULL, the API serves the id as the label, autosave/publish write that id back as the label, and the version counter resets to v1.0

MINOR · bug

**Files** — `backend/db_prompt_studio.py:2252`, `backend/db_prompt_studio.py:180`, `Habibi/src/routes/prompt-studio.lazy.tsx:546-549`, `Habibi/src/routes/prompt-studio.lazy.tsx:541`, `Habibi/src/api/prompt-studio.ts:107`, `backend/db_prompt_studio.py:1724-1726`, `Habibi/src/data/prompt-studio-seed.ts:360-365`, `Habibi/src/components/prompt-studio/StudioHeader.tsx:169-173`

**Mechanism** — restore_prompt_version_as_draft inserts label=None (db:2252); _map_prompt_version substitutes the id ('v1_4-r-ab12cd', db:180). draftLabel takes the draft's own label when it exists (lazy.tsx:546-549), so the header reads 'Publish v1_4-r-ab12cd', every autosave PATCH sends label=that id (toPatchInput prompt-studio.ts:107; patch writes it, db:1724-1726) making the placeholder permanent, and publishing yields a live row labelled with the id. nextVersionLabel then fails its /^v\d+\.\d+$/ match and returns 'v1.0' (seed.ts:360-365; lazy.tsx:541), so the next draft is 'v1.0' — a label that typically already exists in the archive.

**Trigger** — History → Restore on any archived/published row → publish it. Header afterwards: '<id> published' and 'Publish v1.0'.

**Fix** — Have restore carry the source label (the drawer already disambiguates duplicates with 'attempt N'), or treat label === id as unlabeled in draftLabel and use nextLabel.

#### `SHELL-4` — Discarding the only draft leaves draftId pointing at the archived row; Publish stays enabled and the next autosave resurrects the discarded text

MINOR · bug · prior: 2a.4 — the `live` fallback is fixed; this is the remaining branch

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:885-923`, `Habibi/src/routes/prompt-studio.lazy.tsx:898`, `Habibi/src/routes/prompt-studio.lazy.tsx:1252`, `Habibi/src/api/prompt-studio.ts:1018-1026`, `Habibi/src/api/prompt-studio.ts:922-940`

**Mechanism** — discardDraft resets draftId/state only inside `if (live)` (lazy.tsx:898); when the discarded draft was the bot's only version there is no alternative, so draftId keeps the archived id, draftSummary keeps its note and canPublish = Boolean(draftId) remains true (lazy.tsx:1252). The next keystroke PATCHes the archived row → 409 prompt_version_not_draft → isDraftPatchFallbackError → createPromptVersion with the discarded content (prompt-studio.ts:1018-1026), silently undoing the discard; History shows 'Discarded draft …' toast followed by a new identical draft.

**Trigger** — Clone a card (draft only), History → Discard on that draft, then type one character.

**Fix** — When draftId === v.id, always setDraftId(null) and reset draftSummary; if there is no `live` row, keep the text but treat the editor as an unsaved new version (markSaved('')).

#### `SHELL-5` — 'Test in Sandbox' overwrites the draft summary with 'sandbox try' and does not update the summary ref, so the note oscillates on the next autosave

MINOR · bug · prior: 2.4 — fixed for autosave, still present on this button

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:1063-1080`, `Habibi/src/routes/prompt-studio.lazy.tsx:1076`, `Habibi/src/routes/prompt-studio.lazy.tsx:1066`, `Habibi/src/routes/prompt-studio.lazy.tsx:320`, `backend/db_prompt_studio.py:2253`, `backend/db_prompt_studio.py:1751-1753`

**Mechanism** — onTestSandbox PATCHes with a literal summary 'sandbox try' (lazy.tsx:1076) — the pattern draftSummary (lazy.tsx:320) was introduced to remove — and never assigns draftSummary.current. A restored draft's 'restored from v1.2' (db:2253) becomes 'sandbox try' on the server, then the next autosave sends the stale ref value and flips it back; the History drawer alternates between the two. It also keys on `dirty` (differs from live, :1066) rather than `unsaved`, so a fully saved draft is PATCHed anyway purely to change its summary.

**Trigger** — Restore a version, click Test in Sandbox, return and type: the draft's summary reads 'sandbox try', then 'restored from …' again.

**Fix** — Send draftSummary.current (or leave summary undefined so PATCH preserves it) and gate the write on `unsaved || !draftId`.

#### `SHELL-6` — Rollback to production is a single unconfirmed click while every sibling destructive control confirms

MINOR · a11y

**Files** — `Habibi/src/components/prompt-studio/VersionHistory.tsx:180-188`, `Habibi/src/components/prompt-studio/VersionHistory.tsx:228`, `Habibi/src/components/prompt-studio/VersionHistory.tsx:300-333`, `Habibi/src/components/prompt-studio/PublishDialog.tsx:301`, `Habibi/src/routes/prompt-studio.lazy.tsx:992-1024`

**Mechanism** — The 'Rollback to <version>' button calls onRollback directly (VersionHistory.tsx:183); Discard opens an AlertDialog (:228 → :300-333), preset replacement asks in-app (lazy.tsx:1590-1640), and Publish requires typing PUBLISH (PublishDialog.tsx:301). Rollback changes what live callers hear immediately, skips compile gates (see SHELL-7) and records no note, yet is the only production-changing control with no confirmation; unsaved local edits are also replaced without warning (lazy.tsx:1001-1020).

**Trigger** — Open History on a bot with a prior deployment and click once on the warning-toned button under 'Active production'.

**Fix** — Wrap in the existing AlertDialog naming source and target versions (or a typed confirm like publish) and warn when `unsaved` is true.

#### `SHELL-7` — Manual rollback leaves the canary experiment 'running' and skips compile gates; a later sweep can reactivate the old baseline beside the new active row

MINOR · bug · DOWNGRADED

**Files** — `backend/alembic/versions/20260725_0039_bot_deployments_active_unique.py`, `backend/agent_core/canary.py:165-180`, `backend/agent_core/canary.py:418-422`

**Mechanism** — publish_prompt_version promotes any running experiment before recording a new one (canary.py:96-106 via db:2126-2136); rollback_bot_deployment never touches deployment_experiments and never calls compile_card/assert_publishable or sync_attachments_from_card (contrast db:1874-1927, 1960-1964). After a manual rollback of a canary, the experiment row stays 'running' with canary_deployment_id = the now rolled_back row; sweep_rollbacks (canary.py:351-420) can later trigger rollback_experiment, which UPDATEs the baseline deployment back to 'active' (canary.py:171-174) while the rollback's freshly inserted row is also active — two active production rows, hidden by the LIMIT 1 in _ACTIVE_DEPLOYMENT_SELECT (db:1443-1456). No unique active index was found in db.py/db_core.py. Gate-skipping means a version whose skills were since unsigned or connectors revoked goes live untested.

**Trigger** — Publish at 40% with auto_rollback eval_fail, click Rollback in History, then let a red-team report fail: the sweep reactivates the retired baseline.

**Fix** — In rollback_bot_deployment mark the bot's running experiments 'rolled_back' (or promoted) in the same transaction, run compile_card on the target version (or write 'gates skipped' into the change-log entry), and add a partial unique index on bot_deployments(bot_id, environment) WHERE status='active'.

#### `SHELL-8` — Every autosave invalidates the whole ['agent-studio'] key, refetching the fleet, the card and any mounted compile preview (a 16-gate POST per save)

MINOR · bug

**Files** — `Habibi/src/api/prompt-studio.ts:125-136`, `Habibi/src/api/prompt-studio.ts:1045-1051`, `Habibi/src/api/agent-studio.ts:247-282`, `Habibi/src/api/agent-studio.ts:292-305`

**Mechanism** — invalidatePromptStudio (prompt-studio.ts:125-136) invalidates ['agent-studio'] and ['agent-change-log'] and is wired to useEnsureStudioDraft (:1045-1051), i.e. to each 1200 ms autosave. useCompilePreview keys on ['agent-studio','compile-preview',…] (agent-studio.ts:247-282) so while Tools/Outbound is open every autosave re-POSTs the compiler; useAgentStudioCard (:292-305) refetches too, and a failed refetch feeds SHELL-12.

**Trigger** — Open the Tools tab and type in the purpose field: one compile POST per debounce window in addition to the preview's own.

**Fix** — Split invalidation: autosave invalidates only VERSIONS_KEY (+ the card query for this botId); keep the broad set for publish/discard/restore/rollback.

#### `SHELL-9` — No unsaved-changes guard and no retry after 'Autosave failed': edits inside the debounce window or after one failed PATCH are lost on navigation

MINOR · bug

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:615-700`, `Habibi/src/routes/prompt-studio.lazy.tsx:671`, `Habibi/src/routes/prompt-studio.lazy.tsx:1240-1270`, `Habibi/src/components/prompt-studio/StudioHeader.tsx:105`

**Mechanism** — The shell has no beforeunload/useBlocker (none in prompt-studio.lazy.tsx). After a failed save setSaveStatus('error') (lazy.tsx:671) and the effect will not re-run until a dependency changes, so the edit sits unsaved behind an 'Autosave failed' lozenge (StudioHeader.tsx:105) with no retry; a sidebar link or the blocked panel's 'Back to the fleet' discards it silently. Edits made within 1200 ms of navigating away are never sent.

**Trigger** — Type, then click a sidebar link within a second; or stop the API, type, see 'Autosave failed', restart the API and navigate away.

**Fix** — Flush pending edits on unmount/pagehide (fire the save immediately), retry failed autosaves with backoff, and block route navigation while `unsaved` is true.

#### `SHELL-11` — Opening a bot whose versions store an empty card writes the server's default/scaffold card into the draft with zero operator action

trivial · bug · DOWNGRADED

**Files** — `backend/db_prompt_studio.py:418-441`, `backend/db_prompt_studio.py:502-503`, `Habibi/src/routes/prompt-studio.lazy.tsx:688-704`

**Mechanism** — Hydration sets local card from the version row (asCard({}) → null, lazy.tsx:399) and markSaved with card=null; effectiveCard then falls to cardQuery.data.agentCard (:438-441), which get_agent_studio_card fills from card_dump or scaffold_card when no version carries a card (db:429-441). `dirty` compares that resolved card against publishedCard/published.agentCard (null) (:493-505) → true on load; `unsaved` is true too; after 1200 ms autosave PATCHes agentCard = scaffold (:654) or creates a draft. The card the bot 'has' changes because someone looked at it.

**Trigger** — A tenant bot whose draft/published rows have agent_card = '{}' (create_prompt_version falls back to {} when inheritance and card_dump both miss, db:1633-1660) — open its editor and wait.

**Fix** — Hydrate `card` from the same resolved source the server used, or exclude a server-supplied default from `dirty`/autosave until a card tab is touched.

#### `SHELL-14` — prompt-studio.lazy.tsx route component is unreachable dead code with a second hardcoded kaia-v2-4

trivial · dead-config

**Files** — `Habibi/src/routes/prompt-studio.tsx:22-32`

**Mechanism** — prompt-studio.tsx beforeLoad always throws a redirect (:13-21), so the lazy Route's component rendering PromptStudioPage botId="kaia-v2-4" (:102-107) never mounts; its head() meta is likewise never used.

**Trigger** — Visit /prompt-studio — you are redirected before the component loads.

**Fix** — Delete the lazy Route component (keep the redirect file) so the botId hardcode does not survive into a future edit.

#### `SHELL-15` — The first version of a never-published bot is labelled v1.1

trivial · bug

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:541`, `Habibi/src/data/prompt-studio-seed.ts:360-365`

**Mechanism** — nextLabel = nextVersionLabel(publishedRow?.label ?? "v1.0") increments the fallback, so with nothing live the first draft/publish is 'v1.1'.

**Trigger** — Open a bot with no published row; header reads 'Publish v1.1'.

**Fix** — Return 'v1.0' when there is no published row instead of incrementing the placeholder.

#### `SHELL-16` — Draft-count dot on the History button is a role-less span with aria-label

trivial · a11y · prior: 2a.7 — still present at StudioHeader.tsx:119-124 · **closed** in `6089743` (pass 7)

**Files** — `Habibi/src/components/prompt-studio/StudioHeader.tsx:119-124`

**Mechanism** — aria-label on a <span> without role is not reliably announced; the count is conveyed by colour only.

**Trigger** — Screen reader on the History button with an open draft.

**Fix** — Render visually hidden text ('1 draft') or give the span role="img".

#### `SHELL-17` — publish() and onRollback still assign persona/voice/guardrails without DEFAULT_* fallbacks

trivial · bug · prior: 2.5 — fixed in loadDraft, still latent in publish/rollback

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:966-968`, `Habibi/src/routes/prompt-studio.lazy.tsx:1005-1007`, `Habibi/src/routes/prompt-studio.lazy.tsx:847-870`, `backend/schemas.py:2208-2222`

**Mechanism** — loadDraft gained the `?? DEFAULT_*` guards (lazy.tsx:847-870) but publish (:966-968) and rollback (:1005-1007) did not. Harmless while PromptVersionResponse requires the three objects (schemas.py:2208-2222) and _prompt_persona/_prompt_voice/_prompt_guardrails always emit them.

**Trigger** — Only a schema change that makes these nullable.

**Fix** — Reuse one `adoptVersion(v)` helper for hydration, loadDraft, publish, rollback and discard so the fallbacks cannot diverge.

---

## Header and version history

11 findings — 0 MAJOR, 7 MINOR, 4 trivial; 2 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-header.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `HEADER-1` — The card-less bot's rollout baseline filters experiments by a status the schema forbids, so every Studio publish silently re-ships at 100% traffic

MINOR · dead-config · DOWNGRADED

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:455-467`, `Habibi/src/routes/prompt-studio.lazy.tsx:460`, `Habibi/src/routes/prompt-studio.lazy.tsx:461`, `Habibi/src/routes/prompt-studio.lazy.tsx:468-469`, `Habibi/src/routes/prompt-studio.lazy.tsx:958`, `Habibi/src/routes/prompt-studio.lazy.tsx:1145-1158`, `Habibi/src/components/prompt-studio/ShipTab.tsx:79`, `backend/sql/18_phase5.sql:13`, `backend/agent_core/canary.py:99-108`, `backend/agent_core/canary.py:111-133`, `backend/db_prompt_studio.py:1889-1890`, `backend/agent_core/cards/clone.py:53-57`, `backend/agent_core/cards/defaults.py:353-370`, `backend/db_prompt_studio.py:429-441`, `Habibi/src/routes/prompt-studio.lazy.tsx:1193-1208`, `Habibi/src/routes/prompt-studio.lazy.tsx:141-144`

**Mechanism** — `legacyShipBaseline` is the documented resting value and publish-diff baseline for a bot with no authored Agent Card: `const live = (experimentsQuery.data ?? []).find((e) => e.status === "active")` (prompt-studio.lazy.tsx:460). `deployment_experiments.status` is constrained to `('running','rolled_back','promoted')` (sql/18_phase5.sql:13) and the only writer inserts `'running'` (canary.py:114-124), so `live` is always undefined and the memo always returns the hardcoded `{trafficPct:100, shadow:false, autoRollback:[]}` at :461. `DeploymentExperiment.status` is typed `string` (api/agent-studio.ts:457) so nothing catches it, and ShipTab.tsx:79 — reading the same list — uses the correct `'running'`, which is what makes this a typo rather than a convention. Consequences: (a) `ship = legacyShipEdit ?? legacyShipBaseline` (:469) resets to 100/false/[] on every reload, so the operator's canary setting is discarded exactly as the comment at :250-255 says must never happen again; (b) publish() sends `trafficPct: ship.trafficPct` = 100 (:958), and db_prompt_studio.py:1888 takes that over the card, so `record_experiment` promotes the running canary (canary.py:99-102) and inserts nothing new (pct>=100 returns early at :107); (c) `publishBaseline.rollout` (:1155) is the same always-100 object, so PublishDialog prints "Rollout: unchanged" (PublishDialog.tsx:216-226) on a publish that takes a 40% shadow canary to full production traffic.

**Trigger** — On a bot whose agentCard has no `identity.bot_id` (isAuthoredCard false — every cloned/legacy card), set Canary traffic to 40% on the Ship tab and publish. Reload the Studio: the slider reads 100%. Publish again for any unrelated prompt edit — the dialog says "Rollout: unchanged" and the publish moves the bot to 100% traffic and marks the experiment 'promoted'.

**Fix** — Change `e.status === "active"` to `e.status === "running"` at prompt-studio.lazy.tsx:460, matching ShipTab.tsx:79. Then narrow `DeploymentExperiment.status` in api/agent-studio.ts:457 to `"running" | "promoted" | "rolled_back"` so the next such comparison fails to compile.

#### `HEADER-13` — Deployment rollback never closes the running canary experiment, so the Ship tab keeps reporting a canary that routes nothing

MINOR · stale

**Files** — `backend/db_prompt_studio.py:2290-2424`, `backend/db_prompt_studio.py:2364-2374`, `backend/db_prompt_studio.py:2376-2394`, `backend/agent_core/canary.py:99-108`, `backend/agent_core/canary.py:351-365`, `backend/agent_core/canary.py:136-184`, `Habibi/src/components/prompt-studio/ShipTab.tsx:79`, `Habibi/src/components/prompt-studio/ShipTab.tsx:216-227`, `Habibi/src/components/prompt-studio/VersionHistory.tsx:179-189`, `Habibi/src/routes/prompt-studio.lazy.tsx:992`

**Mechanism** — `rollback_bot_deployment` retires the active deployment, re-publishes the prior prompt version and inserts a fresh deployment row (db_prompt_studio.py:2368-2409). It never touches `deployment_experiments`: there is no `record_experiment` and no `rollback_experiment` call in the function, unlike publish (which promotes the running row at canary.py:99-102). The experiment therefore keeps `status='running'` while its `canary_deployment_id` points at a deployment now marked `rolled_back` (:2370-2377). ShipTab still renders "Running experiment — 40% canary" from that row (ShipTab.tsx:79, 216-227) and `sweep_rollbacks` keeps evaluating auto-rollback triggers for it (canary.py:355-365). The header's own rollback control (VersionHistory.tsx:179-189 → prompt-studio.lazy.tsx:992) is the button that produces this state.

**Trigger** — Publish at 40% canary, then use Rollback in the version-history drawer. The Ship tab still shows a running 40% experiment for a deployment that is serving nothing.

**Fix** — Inside the rollback transaction in db_prompt_studio.py (after the deployment swap at :2409), mark any `status='running'` experiment for this bot+environment as `'rolled_back'` with a reason of `'deployment_rollback'`, mirroring canary.py:175-183.

#### `HEADER-2` — restore-as-draft stores a NULL label, so publishing a restored version stamps a row id as the version label and the next label falls back to v1.0

MINOR · bug · DOWNGRADED

**Files** — `backend/db_prompt_studio.py:2221`, `backend/db_prompt_studio.py:2252`, `backend/db_prompt_studio.py:180`, `backend/db_prompt_studio.py:1724-1726`, `Habibi/src/api/prompt-studio.ts:105-117`, `Habibi/src/routes/prompt-studio.lazy.tsx:541`, `Habibi/src/routes/prompt-studio.lazy.tsx:546-549`, `Habibi/src/data/prompt-studio-seed.ts:360-365`, `Habibi/src/components/prompt-studio/StudioHeader.tsx:78-82`, `Habibi/src/components/prompt-studio/VersionHistory.tsx:74-76`, `backend/agent_core/change_log.py:200-212`

**Mechanism** — `restore_prompt_version_as_draft` inserts `"label": None` (db_prompt_studio.py:2252) with id `f"{source['id']}-r-{uuid4hex6}"` (:2221). `_map_prompt_version` then substitutes the id for the missing label (`label = r.get("label") or r.get("id")`, :180), so the API serves the restored draft as label `"v1_3-r-ab12cd"`. The editor picks that up as `draftLabel` (prompt-studio.lazy.tsx:546-549) and `toPatchInput` sends `label: body.label` on every autosave (api/prompt-studio.ts:107), so patch_prompt_version writes that id string into the label column for real (db_prompt_studio.py:1729-1731). Publish it and `publishedRow.label` is `"v1_3-r-ab12cd"`; `nextVersionLabel` only matches `/^v\d+\.\d+$/` and otherwise returns the literal `"v1.0"` (prompt-studio-seed.ts:362-364). So `nextLabel` at prompt-studio.lazy.tsx:541 collapses to v1.0 and the header offers "Publish v1.0" on a card that was at v1.6. The header lozenge also reads "v1_3-r-ab12cd published" (StudioHeader.tsx:81). Every one of those labels is hashed into the change-log entry (db_prompt_studio.py:1806, change_log.record_publish :2143-2156), which is the regulated record of what the agent was told to say and when. The VersionHistory docstring at VersionHistory.tsx:74-76 asserts the opposite behaviour ("A draft inherits the label of the version it descends from"), so nobody reading the UI would expect this.

**Trigger** — Card is live at v1.6. Open History, click Restore on archived v1.3, type one character (autosave writes label), Publish. Header now reads "v1_3-r-ab12cd published" and the next Publish button says v1.0. The change log records the sequence v1.6 → v1_3-r-ab12cd → v1.0.

**Fix** — In db_prompt_studio.py:2252 carry the source label across (`"label": src_label` — it is already computed at :2222) or mint a proper successor label there. Independently, harden prompt-studio.lazy.tsx:541 so a non-matching current label bumps from the newest matching `v<major>.<minor>` in history rather than resetting to v1.0.

#### `HEADER-3` — Load draft / Restore / post-discard reload silently destroy up to a full autosave window of authored prompt text, with no confirmation

MINOR · bug

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:616-617`, `Habibi/src/routes/prompt-studio.lazy.tsx:636-637`, `Habibi/src/routes/prompt-studio.lazy.tsx:682`, `Habibi/src/routes/prompt-studio.lazy.tsx:684-686`, `Habibi/src/routes/prompt-studio.lazy.tsx:847-883`, `Habibi/src/routes/prompt-studio.lazy.tsx:867-876`, `Habibi/src/routes/prompt-studio.lazy.tsx:899-921`, `Habibi/src/routes/prompt-studio.lazy.tsx:933`, `Habibi/src/routes/prompt-studio.lazy.tsx:829-845`, `Habibi/src/components/prompt-studio/VersionHistory.tsx:280-286`

**Mechanism** — Autosave is debounced 1200ms (prompt-studio.lazy.tsx:681). `loadDraft` sets `skipAutosave.current = true` and then replaces prompt/persona/voice/guardrails/flow/card (:848-860). That state change re-runs the autosave effect, whose cleanup clears the pending timer (:683-685), and the effect body returns immediately on `skipAutosave.current` (:617) — so no timer is rescheduled. `markSaved` is then called with the newly loaded fingerprint (:867-876), so `unsaved` is false and nothing remains to trigger a save. The edits made in the last debounce window (plus any in-flight-network window) are gone with no record and no undo. The same path is reached from the drawer's "Load" (VersionHistory.tsx:214), from `restore` (:933) and from `discardDraft`'s live-reload branch (:899-921). The codebase already holds the opposite standard one function away: `applyPreset` (:829-845) refuses to overwrite authored text without an in-app confirmation dialog, for exactly this reason.

**Trigger** — Type a sentence into the System Prompt tab, then within ~1.2s open History and click Load on another draft (or Restore on an archived version). The sentence is not in either version and was never sent to the server.

**Fix** — Await the pending save before switching: if `unsaved` is true, either flush the autosave (call ensureDraft synchronously) before mutating state in `loadDraft`, or gate Load/Restore behind the same AlertDialog pattern `applyPreset` uses, naming what is about to be discarded.

#### `HEADER-4` — Discarding the only draft leaves draftId pointing at the archived row, so Publish stays enabled and republishes the text just discarded

MINOR · bug · prior: 2a.4 (the sibling case — reloading the discarded row — was fixed; this branch was not)

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:885-928`, `Habibi/src/routes/prompt-studio.lazy.tsx:894-897`, `Habibi/src/routes/prompt-studio.lazy.tsx:898-922`, `Habibi/src/routes/prompt-studio.lazy.tsx:924`, `Habibi/src/routes/prompt-studio.lazy.tsx:1252`, `Habibi/src/components/prompt-studio/StudioHeader.tsx:67`, `Habibi/src/api/prompt-studio.ts:921-938`, `Habibi/src/api/prompt-studio.ts:970-983`, `backend/db_prompt_studio.py:1719-1720`, `backend/main.py:3227-3232`, `backend/main.py:824-828`

**Mechanism** — `discardDraft` only clears editor state and `setDraftId(null)` inside `if (live)` (prompt-studio.lazy.tsx:898-922). On a card whose only version was that draft, `live` is null (:894-897 excludes v.id) and the whole block is skipped: the editor keeps the discarded text and `draftId` still names the now-archived row. `canPublish={Boolean(draftId) || dirty}` (:1252) is therefore true and `publishDisabled` is false (StudioHeader.tsx:67), so Publish is live. Confirming it runs publishStudioDraft, whose PATCH 409s (`prompt_version_not_draft`, db_prompt_studio.py:1720), is classified as a fallback error (api/prompt-studio.ts:927) and falls through to `createPromptVersion` (:981) from the still-populated editor body — publishing the discarded content to production. The success toast at :924 has already told the operator the draft is gone.

**Trigger** — On a card with exactly one version (a fresh clone with a single draft), open History, Discard the draft, then click Publish and confirm. The discarded prompt goes live.

**Fix** — Move `setDraftId(null)` and `clearLint()` out of the `if (live)` branch in prompt-studio.lazy.tsx:898, and when there is no other version reset the editor to the seeded defaults the empty-history branch uses (:369-379) rather than leaving discarded text in the textarea.

#### `HEADER-5` — Test in Sandbox and Publish create drafts outside the in-flight-save guard, so a click during the autosave window can fork a second draft

MINOR · bug

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:305-311`, `Habibi/src/routes/prompt-studio.lazy.tsx:639-643`, `Habibi/src/routes/prompt-studio.lazy.tsx:673-678`, `Habibi/src/routes/prompt-studio.lazy.tsx:682`, `Habibi/src/routes/prompt-studio.lazy.tsx:1067`, `Habibi/src/routes/prompt-studio.lazy.tsx:947`, `Habibi/src/api/prompt-studio.ts:1017-1025`, `Habibi/src/api/prompt-studio.ts:980-983`, `backend/db_prompt_studio.py:1629-1631`, `backend/main.py:2233-2241`

**Mechanism** — `savingRef`/`resaveRef` exist precisely so that a second write cannot start while `ensureDraft` is creating a draft with `draftId` still null — the comment at prompt-studio.lazy.tsx:305-311 spells out the duplicate-draft failure. Only the autosave body honours them (:638-643, :673-678). `onTestSandbox` calls `ensureDraftMutation.mutateAsync` directly (:1067) and `publish` calls `publishMutation.mutateAsync` (:947) → `publishStudioDraft` → `createPromptVersion` (api/prompt-studio.ts:980-983); neither checks `savingRef.current` nor cancels the pending `autosaveTimer`. If the button's request is slower than the remainder of the 1200ms debounce, the timer fires with `draftId` still null and creates a second draft for the same edit. The result is two open drafts: the version drawer grows a phantom row, and `POST /agent-studio/cards/{bot_id}/publish` starts 409-ing `ambiguous_draft_to_publish` (main.py:2231-2239) for that bot.

**Trigger** — On a card with no open draft, type, then click "Test in Sandbox" (or Publish) within the debounce window on a slow connection. Two drafts appear in History for one edit.

**Fix** — Have both handlers take the same guard: clear `autosaveTimer.current`, set `savingRef.current = true` for the duration of the mutation, and honour `resaveRef` on completion — or factor the create-or-patch into one `flushDraft()` all three callers share.

#### `HEADER-6` — Version history is a single unpaginated 200-row page — the History count, the Live group and the by-bot publish endpoint all truncate silently

MINOR · bug · **closed** in `6089743` (pass 7)

**Files** — `Habibi/src/api/prompt-studio.ts:165-169`, `backend/main.py:2020-2027`, `backend/db_core.py:211-212`, `backend/db_core.py:215-227`, `backend/db_prompt_studio.py:225`, `backend/db_prompt_studio.py:243-244`, `Habibi/src/routes/prompt-studio.lazy.tsx:386`, `Habibi/src/routes/prompt-studio.lazy.tsx:1265`, `backend/main.py:2217`, `backend/main.py:2225-2228`

**Mechanism** — `fetchPromptVersions` sends no `limit` (api/prompt-studio.ts:167-168), so `clamp_list_limit(None)` resolves to `DEFAULT_LIST_LIMIT = 200` (db_core.py:211,221-222) and the query is `ORDER BY created_at DESC ... LIMIT 200` (db_prompt_studio.py:243). Nothing in the client pages past that: `history` is the whole model behind `versionCount={history.length}` (prompt-studio.lazy.tsx:1265), the drawer's per-group counts (VersionHistory.tsx:244), `publishedRow` (:429-432) and `nextLabel` (:541). Once a card accumulates 200 versions newer than its published row, `publishedRow` is undefined, the header claims "never published" for a live card (StudioHeader.tsx:78-79), `nextLabel` resets to v1.0, and the drawer shows no Live group. Below that threshold the count itself is still a quiet lie once 200 is exceeded overall. The by-bot publish endpoint inherits the same window: `db.list_prompt_versions(bot_id=bot_id)` with no limit (main.py:2214) means a caller naming an older draft's `versionId` gets 404 `prompt_version_not_found` for a draft that exists (main.py:2222-2229).

**Trigger** — A card with more than 200 prompt_versions rows: the History button's count stops growing and the older half of the timeline is unreachable. With 200 rows created since the last publish, the header reports a live card as never published.

**Fix** — Either page the drawer (pass `limit`/`offset` and add a "load older" control) or, at minimum, fetch the live row independently — `GET /prompt-versions/published?botId=` (main.py:2031) already exists and is not window-dependent — and drive `publishedRow`/`nextLabel`/the header lozenge from it. Add `limit=db.MAX_LIST_LIMIT` at main.py:2214 so the by-bot publish enumerates every draft.

#### `HEADER-10` — A card that has never published offers "Publish v1.1" — v1.0 can never be minted

trivial · bug

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:541`, `Habibi/src/routes/prompt-studio.lazy.tsx:546-549`, `Habibi/src/data/prompt-studio-seed.ts:360-365`, `Habibi/src/components/prompt-studio/StudioHeader.tsx:78-79`, `Habibi/src/components/prompt-studio/StudioHeader.tsx:173`, `backend/db_prompt_studio.py:1530-1537`, `backend/db_prompt_studio.py:1616-1617`

**Mechanism** — `nextLabel = nextVersionLabel(publishedRow?.label ?? "v1.0")`. When nothing is published the fallback "v1.0" is fed through the incrementer, which returns "v1.1" (prompt-studio-seed.ts:364). So the first version of every new or cloned card is stamped v1.1 and the header reads "never published" beside "Publish v1.1" (StudioHeader.tsx:79, 173). The stored id also becomes `v1_1` (db_prompt_studio.py:1617,1534), so a card's history can never contain a v1.0 authored through the Studio.

**Trigger** — Clone a card and look at the header before the first publish.

**Fix** — Pass the seed label rather than its predecessor: `const nextLabel = publishedRow ? nextVersionLabel(publishedRow.label) : "v1.0"` at prompt-studio.lazy.tsx:541.

#### `HEADER-12` — "Restore" leaves the History drawer open on top of the editor it just repopulated, while "Load" closes it

trivial · bug · **closed** in `6089743` (pass 7)

**Files** — `Habibi/src/routes/prompt-studio.lazy.tsx:1559-1563`, `Habibi/src/routes/prompt-studio.lazy.tsx:1564`, `Habibi/src/routes/prompt-studio.lazy.tsx:1565-1568`, `Habibi/src/routes/prompt-studio.lazy.tsx:930-938`, `Habibi/src/components/prompt-studio/VersionHistory.tsx:287-292`

**Mechanism** — `onLoadDraft` wraps `loadDraft(v)` with `setHistoryOpen(false)` (prompt-studio.lazy.tsx:1565-1568) and `onCompare` closes the drawer too (:1562). `onRestore={(v) => void restore(v)}` (:1564) does not, even though `restore` ends in the same `loadDraft` (:933) and produces the same "you are now editing something else" state change. The operator is left looking at a modal sheet over an editor whose contents just changed under it.

**Trigger** — Open History and click Restore on any archived version.

**Fix** — Close the drawer in the restore handler the way the load handler does — `onRestore={(v) => { setHistoryOpen(false); void restore(v); }}` at prompt-studio.lazy.tsx:1564.

#### `HEADER-8` — PublishDialog recomputes the full O(m·n) LCS diff on every Studio render, including every keystroke while the dialog is closed

trivial · code-organization · DOWNGRADED · deferred: PublishDialog.tsx is the other stream's uncommitted file

**Files** — `Habibi/src/components/prompt-studio/PublishDialog.tsx:56-74`, `Habibi/src/components/prompt-studio/PublishDialog.tsx:72`, `Habibi/src/components/prompt-studio/PublishDialog.tsx:88-92`, `Habibi/src/data/prompt-studio-seed.ts:325-353`, `Habibi/src/routes/prompt-studio.lazy.tsx:1583-1606`, `Habibi/src/components/prompt-studio/DiffModal.tsx:44`

**Mechanism** — `<PublishDialog>` is mounted unconditionally (prompt-studio.lazy.tsx:1583) with `to={{prompt, ...}}` rebuilt from live editor state on every render. The component body has no `open` guard and no memo: `const lines = diffStudioVersions(from, to)` runs at PublishDialog.tsx:72, plus three `stableStringify` pairs at :88-92, before any early return. `diffPrompts` allocates a full `(m+1)×(n+1)` number matrix and fills it (prompt-studio-seed.ts:330-335). For a 500-line prompt that is a ~275k-cell allocation and fill on every keystroke of the System Prompt tab, for a dialog nobody has opened. DiffModal has the same shape but is protected by its `if (!base) return null` at DiffModal.tsx:44.

**Trigger** — Type into the System Prompt tab of a card with a long prompt; the LCS runs per render with the publish dialog closed.

**Fix** — Add `if (!open) return null;` at the top of PublishDialog (the reset effect at :144-149 already keys on `open`, and Radix unmounts the content anyway), or wrap `lines` and the three changed-flags in `useMemo` keyed on `open` plus the stringified sides.

#### `HEADER-9` — VersionHistory's attempt-numbering docstring describes label inheritance the backend does not implement

trivial · doc-vs-code

**Files** — `Habibi/src/components/prompt-studio/VersionHistory.tsx:71-81`, `Habibi/src/components/prompt-studio/VersionHistory.tsx:82-101`, `backend/db_prompt_studio.py:2252`, `backend/db_prompt_studio.py:180`

**Mechanism** — The docstring above `attemptSuffixes` states "A draft inherits the label of the version it descends from, and autosave, a sandbox promote and an authored edit each write one". restore-as-draft — the only write path that descends a draft from another version — stores `label: None` (db_prompt_studio.py:2252) and the row surfaces with its id as the label (:180). So restored drafts never share a label bucket with their parent and never get an "attempt N" suffix; the four-consecutive-v1.5 case the comment cites comes from repeated create-from-`nextLabel`, not from inheritance.

**Trigger** — Restore any archived version and look at the timeline: the new row is labelled `<parent-id>-r-<hex>`, not the parent's label, and carries no attempt suffix.

**Fix** — Either make restore inherit the label (see HEADER-2's fix, which makes the comment true) or correct the comment to say drafts are labelled from `nextVersionLabel` and that restores are id-labelled.

---

## Agent Card → runtime — the field-by-field inventory

23 findings — 10 MAJOR, 10 MINOR, 3 trivial; 10 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-runtime.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `RUNTIME-01` — human_gates is enforced nowhere — the card's identity/floor requirement has no reader at all

**MAJOR** · dead-config · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/cards/schema.py:53`, `backend/agent_core/cards/schema.py:157-162`, `backend/agent_core/cards/schema.py:389`, `backend/agent_core/cards/defaults.py:131`, `backend/agent_core/cards/defaults.py:149-151`, `backend/agent_core/cards/defaults.py:171`, `backend/agent_core/cards/defaults.py:312`, `backend/agent_core/cards/defaults.py:328`, `backend/voice/tools.py:516-523`, `backend/agent_core/cards/compile.py:519-954`

**Mechanism** — `human_gates` appears in exactly four places in the backend: the schema (schema.py:158,389), the first-party card constructors (defaults.py:150-151, :171, :312) and the frontend type (Habibi/src/api/agent-card.ts:317,335). There is no reader in backend/voice/**, bot_tools.py, sandbox_runtime.py, agent_core/tools/** — and no gate in compile.py either, so it is not even compile-only. What actually gates voice writes is the hardcoded `_require_customer()` at voice/tools.py:516-523, which checks `session.identity_verified` for every write regardless of what the card says. The two stronger modes are worse: `require="floor"` and `require="both"` mean supervisor sign-off, and nothing in the codebase implements a per-tool approval hold — /floor/approvals (main.py:1494) is a work-runtime screen no tool consults.

**Trigger** — Publish a card with `human_gates: [{tool_name: "apply_goodwill", require: "both"}]`. Every gate passes (no gate reads the field), the change log records the new contract, and at runtime apply_goodwill executes on identity alone with no supervisor step. Symmetrically, removing `{tool_name: "create_promise_to_pay", require: "identity"}` from kaia's card changes nothing — PTP stays identity-gated by voice/tools.py:1218.

**Fix** — Either enforce it or stop publishing it. Enforcement: resolve the card's human_gates in the tool dispatch path (voice/tools.py `_spec` wrapper and bot_tools.py:770-800 dispatch table), map `identity` onto the existing `_require_customer()` result and implement `floor`/`both` as a real approval hold before the write. If floor approval is not going to exist this quarter, narrow HumanGateRequire to Literal["identity"], add a compile gate asserting every gated tool_name is in the effective tool set, and say in the Policy tab that identity gating is platform-wide rather than card-authored.

#### `RUNTIME-02` — card.memory is dead in its entirety — including the scopes that describe what is retained about a borrower

**MAJOR** · dead-config · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/cards/schema.py:144-155`, `backend/agent_core/cards/schema.py:387`, `backend/voice/crm_sink.py:1154-1190`, `backend/voice/crm_sink.py:1614`, `backend/bot_runtime.py:49-50`, `backend/bot_runtime.py:871`, `backend/bot_runtime.py:893`, `backend/agent_core/compaction.py:12`, `backend/agent_core/compaction.py:35-50`, `backend/agent_core/turn.py:37`

**Mechanism** — Grepping the whole backend for a reader of the card's `memory` sub-model returns nothing — not a runtime reader, not a compile gate. Every card therefore ships the schema default `scopes: ["turn", "call"]` (no card in defaults.py or templates.py overrides it), which reads as "this agent retains nothing across calls". Meanwhile voice/crm_sink.py:1161-1184 writes a persistent `customer_memory` row — a cross-call summary plus open commitments — after every verified call, gated only on the env flag `voice_config.voice_memory()` and identity. Separately, `compaction.raw_last_n` is bypassed: bot_runtime.py:871 uses `_history_limit()` = env BOT_HISTORY_LIMIT (default 16, bot_runtime.py:49-50) and passes that as `last_n` at :893, while agent_core/turn.py:37 uses the module constant. `summarize_over_budget` has no flag to switch — compaction.py:47 always produces a summary.

**Trigger** — Any published card (all four first-party ones today) declares customer-scoped memory off and gets a customer_memory row written on every verified voice call. An operator setting `raw_last_n: 4` to shorten context sees 16 turns still sent to the model.

**Fix** — Thread the card into the two consumers: pass `card.memory.compaction.raw_last_n` as `last_n` in bot_runtime.py:891 and agent_core/turn.py:90 (falling back to the env value only when there is no card), and make voice/crm_sink.py:1165 require `"customer" in card.memory.scopes` in addition to the env flag. If the retention decision is genuinely platform-wide, delete CardMemory from the schema rather than publishing a retention claim the runtime does not honour.

#### `RUNTIME-03` — experiment.shadow never reaches routing — a shadow canary serves real callers

**MAJOR** · degradation-lie · prior: 2m.2 · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/canary.py:57-77`, `backend/agent_core/canary.py:87`, `backend/agent_core/canary.py:114-129`, `backend/agent_core/canary.py:342`, `backend/agent_core/deployment.py:37-50`, `backend/agent_core/cards/schema.py:365`, `backend/agent_core/cards/compile.py:880-895`

**Mechanism** — `shadow` is written into deployment_experiments (canary.py:116,129) and read back for display (canary.py:342), but `pick_deployment_id` (canary.py:57-77) — the only routing function, called from agent_core/deployment.py:40 for voice, WhatsApp and the sandbox — branches solely on `traffic_pct`. A running experiment with `shadow=true, traffic_pct=25` therefore routes 25% of real borrowers onto the canary version and speaks its output to them. Everywhere else in this codebase "shadow" means decide-and-log-but-never-act (agent_core/reco/config.py:23, treatment/config.py:29, authority/README.md:22), so the word is load-bearing and here it is inert.

**Trigger** — Ship a 25% canary with Shadow on from the Ship tab. G12 passes (compile.py:882 only looks at pct and triggers), the experiment row records shadow=true, and one caller in four is served by the unproven version with nothing marking their transcript as an experiment.

**Fix** — In `pick_deployment_id`, return the baseline (or active) deployment whenever `exp["shadow"]` is true, and run the canary version out-of-band if a true shadow evaluation is wanted. Failing that, reject shadow at publish (compile.py G12) with "shadow is not implemented" rather than accepting a flag that changes nothing but the label.

#### `RUNTIME-05` — voice handoff_to_agent allowlists against the built-in card, not the live one — and denies nothing when the bot is not first-party

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/voice/tools.py:2773-2797`, `backend/voice/tools.py:2781`, `backend/voice/tools.py:2783-2788`, `backend/agent_core/tools/domain.py:1009-1027`, `backend/bot_tools.py:400-429`, `backend/voice/bot.py:1138`

**Mechanism** — voice/tools.py:2786 builds the allowlist from `card_for(bot_id)` — the four Python constants in agent_core/cards/defaults.py — rather than from the card this call is actually running (`bundle["agentCard"]`, which voice/bot.py:1138 already has in hand). Two consequences. (1) A clone or a first-party card whose published `handoffs` were edited is enforced against the built-in list, so a target removed in the Studio is still reachable and a target added is refused. (2) `card_for` raises KeyError for any non-first-party bot_id, the except at :2787-2788 sets `allowlist = None`, and domain.handoff_to_agent:1027 reads None as unrestricted (`if allowlist is not None and ...`) — so a cloned agent may hand off to any bot in the tenant. This is precisely the failure bot_tools.py:400-412 documents as fixed on the text path; the voice path was not fixed with it, and routing.py:13-16 still describes the intended behaviour as if it were.

**Trigger** — Publish a clone (bot_id "kaia-clone-1") with a single handoff to intake-v1 and take a voice call on it. The model calls handoff_to_agent(target_bot_id="insurance-v1"): card_for("kaia-clone-1") raises KeyError, allowlist becomes None, and the transfer is allowed and written to interactions.handler_bot_id.

**Fix** — Replace voice/tools.py:2783-2788 with the same resolution order bot_tools._handoff_allowlist uses — live card from the bundle first, built-in card second, empty set (deny) last — and pass the bundle's agentCard into build_collections_flow/build_authored_flow alongside `allowed_tool_names`. Denying on an unknown card is the safe end; escalate_to_human remains available.

#### `RUNTIME-06` — a2a.expose and a2a.skill_ids are both dead: the well-known card is served for any bot to any authenticated partner, and lists card.skills instead

**MAJOR** · security · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/main.py:2711-2721`, `backend/agent_core/a2a.py:38-69`, `backend/agent_core/a2a.py:72-105`, `backend/agent_core/a2a.py:80`, `backend/agent_core/a2a.py:108-119`, `backend/agent_core/cards/compile.py:897-917`, `backend/agent_core/cards/schema.py:369-373`, `backend/agent_core/cards/defaults.py:318-331`

**Mechanism** — G13 (compile.py:898) only fires when `card.a2a.expose` is true, and publish only checks for a partner cert in that case (db_prompt_studio.py:1894). But the serving side never asks: main.py:2711-2717 calls `agent_card_document(botId or DEFAULT_BOT_ID)` after `require_partner`, and a2a.py:72-105 reads nothing under `raw["a2a"]`. So any active partner can pull the card document for any bot_id in the tenant, including cards with `expose: false` that were never gated for A2A exposure. Separately, `a2a.skill_ids` — the field whose whole purpose is to say which skills are offered to partners — is ignored: a2a.py:80 iterates `raw["skills"]`, i.e. the internal skill attachment list, so a card exposing one skill advertises all of them; and create_task:116-120 authorises against a2a_partners.allowed_skills, never against the card.

**Trigger** — GET /.well-known/agent-card.json?botId=supervisor-brief-v1 with a valid partner cert. That card has `a2a` unset (defaults.py:318-333), so expose is false and G13 was skipped at publish — yet the document is returned, listing every attached skill including internal ones.

**Fix** — In a2a.agent_card_document, parse the card and raise KeyError('agent_card_not_exposed') unless `a2a.expose` is true; build `skills_out` from `a2a.skill_ids` (intersected with card.skills so it cannot widen), and intersect partner.allowed_skills with the same list in create_task.

#### `RUNTIME-07` — the A2A partner card is rendered from the DRAFT card, not the published one

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/a2a.py:74-77`, `backend/db_prompt_studio.py:429-430`, `backend/db_prompt_studio.py:503`, `backend/main.py:2711-2717`

**Mechanism** — agent_card_document reads `db.get_agent_studio_card(bot_id)["agentCard"]`. That key is deliberately draft-preferred — db_prompt_studio.py:429 sets `card = _card_of(draft) or published_card` so the editor reads back its own unsaved-to-production edits, and the summary even reports which it chose in `cardSource`. The published card is available on the same row as `publishedCard` (:503) and is not used. So the identity, purpose and skill list an external partner is served come from an in-progress draft that has passed no gate and may never be published.

**Trigger** — Open a card in Agent Studio, change display_name/purpose and detach a skill (the editor PATCHes the draft), then have a partner fetch /.well-known/agent-card.json — it returns the unpublished draft's name and skill list. Discarding the draft silently changes the partner-facing contract back.

**Fix** — Read `publishedCard` in a2a.agent_card_document (falling back to 404 rather than to the draft), or resolve the card through the active deployment the way mission.card_for_bot:516-521 does. The A2A document is a publish-time contract; it must not follow an editor's draft.

#### `RUNTIME-08` — CardObjective.success does not decide whether a mission succeeded — the closer uses a hardcoded table, and both the comment and the Outbound tab say otherwise

**MAJOR** · stale · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/call_closer.py:99-112`, `backend/call_closer.py:949-950`, `backend/call_closer.py:1005`, `backend/call_closer.py:1032`, `backend/call_closer.py:1059`, `backend/mission.py:315`, `backend/main.py:5366`, `backend/agent_core/cards/schema.py:237-238`

**Mechanism** — call_closer.py:949 computes `success = SUCCESS_BY_OBJECTIVE.get(objective, ...)` from the module-level dict at :102-112 and never looks at the card, even though it already resolves the card two lines of context away (`mission_mod.card_for_bot` at :669 and :754). The comment at :99-101 states the opposite — "``CardObjective.success`` overrides them per published card, which is the point of authoring missions rather than hardcoding them". mission.py:315 does copy `success` into the Mission envelope, and nothing reads it back: `mission["success"]` has no consumer in voice/**, cadence.py or call_closer.py. `CardObjective.partial` has no reader at all, not even a gate. Meanwhile GET /outbound/missions returns `success` per objective (main.py:5366) so the Outbound tab shows the operator the codes they authored.

**Trigger** — Author `success: ["callback_requested"]` on a document_chase objective and publish. The tab shows it, the change log diffs it, and a call ending in callback_requested is still scored `objective_met=false` because SUCCESS_BY_OBJECTIVE["document_chase"] is {"no_resolution"}. Every downstream reach/outcome metric and the abandon_rate rollback trigger inherit the wrong verdict.

**Fix** — In call_closer, resolve the card once (it already does, for post_call and cadence) and use `card.outbound.objective(objective).success` when the objective declares one, falling back to SUCCESS_BY_OBJECTIVE only when it is empty. Do the same for `partial` or delete the field. Fix the comment at :99-101 either way.

#### `RUNTIME-09` — cadence.escalate_to is gated at publish and read by nobody — an exhausted ladder escalates to no one

**MAJOR** · dead-config · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/cadence.py:600-604`, `backend/cadence.py:231-240`, `backend/cadence.py:402-410`, `backend/agent_core/cards/compile.py:409-427`, `backend/agent_core/cards/compile.py:173`, `backend/agent_core/cards/schema.py:289-291`, `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:860-875`

**Mechanism** — `escalation_target(card_outbound, objective)` at cadence.py:600-604 is the only code that reads `escalate_to`, and it has no caller anywhere in the backend. Both exhaustion paths — on_outcome at :232-240 and process_one at :400-410 — call `_stop(..., STATE_EXHAUSTED, "max_attempts", ...)` and return; nothing hands the case to the named bot or to a human queue. The field is nevertheless validated by G-OB7 (compile.py:412-427, which even checks the target is on the handoff allowlist) and has an editor control (OutboundCardEditor.tsx:867), so an operator authoring "escalate_to: human" after 3 attempts gets a green publish and a case that simply stops.

**Trigger** — Publish a cadence with max_attempts 3 and escalate_to "human", then let a borrower's ladder run out. call_cadence_state flips to `exhausted` with stopped_reason `max_attempts`; no work item, no handoff, no alert.

**Fix** — Call `escalation_target` at both exhaustion sites and act on it — enqueue a human work item for "human", or record a handoff to the named bot — or drop escalate_to and G-OB7 and remove the control, so the card stops promising a rung it does not have.

#### `RUNTIME-13` — outbound.direction never blocks a dial — an inbound-only card is dialled from, and the objective guard is skipped precisely when the card forbids dialling

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/treatment/enact.py:358-370`, `backend/mission.py:450-494`, `backend/campaigns.py:526-557`, `backend/agent_core/cards/schema.py:324`, `backend/agent_core/cards/schema.py:356-358`

**Mechanism** — enact.py:368 reads `if card is not None and card.outbound.dials and card.outbound.objectives:` and only then refuses an unclaimed objective. When `direction == "inbound"` (the schema default, and what every first-party card carries), `dials` is False, so the entire guard is skipped and the dial proceeds — the inverse of the comment above it at :359-363 ("a dial placed against a card that forbids it should not happen at all"). mission.resolve_outbound_bot_id compounds it: `_claims` requires `dials`, but every fall-through returns `default` unconditionally (:486-495), so the tenant default bot is selected whether or not its card dials. campaigns.py:526-552 does not check `dials` at all before reserving and placing.

**Trigger** — Run a bounce_cure campaign (or let the treatment engine enact one) against kaia-v2-4, whose published card has `outbound.direction: "inbound"` and no objectives. resolve_outbound_bot_id returns kaia, the enact guard is skipped because dials is False, and the borrower is dialled by an agent whose published contract says it never dials.

**Fix** — Invert the guard: refuse when `card is not None and not card.outbound.dials` (raise NoExecutor("card_forbids_outbound")), and check `card.outbound.dials` in campaigns.py before reserve. Keep the objective check as a second, narrower refusal for cards that do dial.

#### `RUNTIME-14` — cadence retries are always placed as the tenant default bot, so the ladder abandons the card that opened it

**MAJOR** · bug · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/cadence.py:418-440`, `backend/cadence.py:127-145`, `backend/mission.py:450-463`, `backend/mission.py:494`, `backend/mission.py:498-530`

**Mechanism** — cadence.process_one hardcodes `bot_id = dbmod.DEFAULT_BOT_ID` at :418 and resolves the card, the Mission and the dial from it (:419-440). The ladder row has no bot column to lose it from — ensure_case's INSERT (:130-135) never stores one — even though the originating attempt does (call_attempts.bot_id, referenced at call_closer.py:754 and qa_autoscore.py:161). So every retry after the first is placed by kaia's card: kaia's objective spec, voicemail policy, allowed_offers, authority profile, number pool and prompt version, regardless of which agent placed attempt 1. mission.resolve_outbound_bot_id exists for exactly this resolution (:451-463, whose docstring names the bug: "Hard-coding DEFAULT_BOT_ID at the call site is how a card authored in Agent Studio still rang as kaia-v2-4") and is not called here.

**Trigger** — A campaign run with bot_id=insurance-v1 places attempt 1 with insurance-v1's mission; the call goes to no_answer; four hours later the cadence worker dials attempt 2 as kaia-v2-4 with kaia's mission envelope and voice. The borrower hears a different agent about the same case, and the two attempts sit on one ladder with two version numbers.

**Fix** — Add `bot_id` to call_cadence_state (populated by ensure_case from the attempt), select it in claim_due, and use `mission_mod.resolve_outbound_bot_id(explicit=case["bot_id"], objective=objective)` at cadence.py:418. Until the column exists, read it back from `call_attempts` via `case["last_attempt_id"]`.

#### `RUNTIME-04` — publish reads traffic_pct and auto_rollback off the card but not shadow, then overwrites the card's shadow with the request default

MINOR · shape-mismatch

**Files** — `backend/db_prompt_studio.py:1827`, `backend/db_prompt_studio.py:1889-1891`, `backend/db_prompt_studio.py:1937-1946`, `backend/db_prompt_studio.py:2122`, `backend/main.py:3262`, `backend/schemas.py:2409-2410`

**Mechanism** — publish_prompt_version derives `pct` and `triggers` from `card_raw["experiment"]` when the request omits them (db_prompt_studio.py:1890-1891), but `shadow` has no such fallback — it is the function parameter, defaulting to False (:1827), matching PromptVersionPublishRequest.shadow's default (schemas.py:2410). The shipped-experiment fold at :1940-1946 then writes `"shadow": bool(shadow)` back onto the card, so an authored `experiment.shadow: true` is silently rewritten to false on the version row and in the change-log digest. The Studio happens to send it (prompt-studio.lazy.tsx:959 from card.experiment at :470-473), so the loss only bites API callers, clones published through POST /agent-studio/cards/{bot_id}/publish without a body, and any path that publishes a card it did not itself edit.

**Trigger** — POST /prompt-versions/{id}/publish with `{}` on a draft whose card has `experiment: {traffic_pct: 30, shadow: true, auto_rollback: [...]}`: pct 30 and the triggers survive, shadow becomes false, and the card is rewritten to say so.

**Fix** — Mirror the pct/triggers pattern: `shadow = shadow if shadow is not None else bool(exp.get("shadow"))`, with the request field typed `bool | None = None` in schemas.py:2410.

#### `RUNTIME-10` — cadence.time_of_day has no reader and no gate

MINOR · dead-config

**Files** — `backend/agent_core/cards/schema.py:207`, `backend/agent_core/cards/schema.py:292`, `backend/cadence.py:241-249`, `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:843-857`

**Mechanism** — `time_of_day` (engine | fixed | spread) exists on CardCadence, has a select control in the Outbound editor, and is read nowhere in the backend — cadence.py:242 schedules `next_attempt_at` purely as now() + backoff, and the only other `time_of_day` hits in the repo are the unrelated `{time_of_day}` prompt variable (agent_core/clock.py:75, agent_core/prompt.py:47). Not even a compile gate references it.

**Trigger** — Set a cadence to "spread" and every retry still fires at now()+backoff, clustering exactly as "fixed" would.

**Fix** — Either implement the three modes in cadence.py:242 (engine = current behaviour, fixed = snap to the campaign window, spread = jitter within it), or remove the field and its control.

#### `RUNTIME-11` — cadence.per_day cannot lower the runtime contact cap, contrary to the field's own docstring

MINOR · doc-vs-code

**Files** — `backend/agent_core/cards/schema.py:263-265`, `backend/agent_core/cards/compile.py:340-359`, `backend/contact_policy.py:90-101`, `backend/contact_policy.py:881-920`, `backend/cadence.py:445-458`, `backend/campaigns.py:557`

**Mechanism** — schema.py:263-265 says per_day is "Bounded again at runtime by contact_policy's own cap, which a card can only ever lower." The runtime does the opposite: contact_policy.admit (called from cadence.py:445 and campaigns.py:557) computes its budget from `daily_cap(rules)` — env CONTACT_DAILY_CAP narrowed by tenant rules (contact_policy.py:99-101) — and never receives the card or per_day. G-OB3 (compile.py:350) only refuses a card whose per_day *exceeds* the global cap. So per_day is a publish-time sanity check that lowers nothing.

**Trigger** — Author per_day=1 on a cadence while CONTACT_DAILY_CAP=3. The ladder's backoff (default 4h) allows a second and third attempt within a day and contact_policy admits both.

**Fix** — Pass the card's per_day into contact_policy.admit as an additional per-purpose ceiling (min with daily_cap), or correct the docstring and the editor copy to say per_day is a validation bound, not a runtime limit.

#### `RUNTIME-15` — identity.data_class and identity.regulator_tags have no consumer anywhere

MINOR · dead-config

**Files** — `backend/agent_core/cards/schema.py:89-90`, `backend/agent_core/cards/defaults.py:144-145`, `backend/agent_core/cards/defaults.py:170`, `backend/agent_core/cards/defaults.py:291`, `backend/agent_core/cards/defaults.py:311`, `backend/agent_core/cards/defaults.py:327`, `backend/agent_core/cards/compile.py:827`

**Mechanism** — Every `data_class` reference in the backend belongs to something else: the mcp_connectors column (agent_core/connectors/persist.py:141,199 and the G10 issue at compile.py:827) or SKILL.md pack metadata (agent_core/skills/pack.py:141). The card's own identity.data_class and regulator_tags are only ever written (defaults.py:144-145 sets `regulator_tags=["rbi-fair-practices","dpdp"]` on all four cards) — never read by redaction, by the compliance export (/compliance/policy-export, main.py:2779), by pii_redact.py, or by any gate. They are labels on a contract that nothing keys off.

**Trigger** — Publish a card with `data_class: ["marketing"]` and no "pii": the agent still reads and speaks PII through the same CRM tools, and the compliance policy bundle is unchanged.

**Fix** — Either key something off them — the obvious candidates are the compliance policy export and a G10-style gate refusing a connector whose data_class exceeds the card's — or drop them from the schema so the published contract stops asserting a classification nothing enforces.

#### `RUNTIME-16` — identity.channels never refuses a channel at runtime; only the publish gates read it

MINOR · dead-config

**Files** — `backend/agent_core/cards/schema.py:16`, `backend/agent_core/cards/schema.py:88`, `backend/agent_core/cards/compile.py:643`, `backend/agent_core/cards/compile.py:685`, `backend/bot_runtime.py:909-916`, `backend/voice/bot.py:1135-1143`, `backend/agent_core/tools/grant.py:91-102`, `backend/agent_core/cards/defaults.py:324`

**Mechanism** — The two readers are both gates: compile.py:643 (G4 decides whether locked mouth tools are required) and :685 (G6 decides whether the voice tool cap applies). The runtimes filter tools by the *catalog's* channel metadata, not the card's: bot_runtime.py:915 uses `CATALOG.for_channel(CHANNEL_TEXT)` and voice/bot.py:1142 `CHANNEL_VOICE`, and grant.py:91-102 does the same. Nothing anywhere asks whether the inbound channel is on `identity.channels` before serving the call or the message.

**Trigger** — Publish supervisor-brief-v1 (channels: ["internal"], defaults.py:324) and address it as the WhatsApp bot via BOT_ID, or activate a production deployment for it: bot_runtime serves the conversation normally. The card says the agent is internal-only and nothing acts on that.

**Fix** — Check `channel in card.identity.channels` at the two entry points — bot_runtime's job intake and voice/bot's session start — and refuse (or fall back to the entry bot) when it is not, logging the refusal. That is also what makes the fleet index's reachability story true.

#### `RUNTIME-17` — mouth.languages is dead — the voice-locale gate reads persona, not the card

MINOR · dead-config

**Files** — `backend/agent_core/cards/schema.py:99`, `backend/db_prompt_studio.py:983-1012`, `backend/db_prompt_studio.py:1905-1907`, `backend/db_prompt_studio.py:822`, `backend/agent_core/cards/compile.py:197-208`, `backend/agent_core/cards/compile.py:942`

**Mechanism** — G15 is the only thing that reasons about a card's languages, and its `card_locales` argument comes from `voice_locale_facts(target["voice"], target["persona"])`, which builds the tag list from `persona.language` and `persona.fallbackLanguages` (db_prompt_studio.py:1004-1011). `mouth.languages` is never passed in and has no other reader in the backend — so the card can declare ["English","Tamil"] while the gate judges against the persona's Hindi and no one is told the two disagree.

**Trigger** — Set mouth.languages to ["Tamil"] on a card whose persona says Hindi and pick a Hindi voice: G15 passes on the persona and the card's language claim is inert.

**Fix** — Make G15 compare all three (voice locale, persona languages, card mouth.languages) and warn when the card and persona disagree, or delete CardMouthRef.languages — one of them has to be the answer.

#### `RUNTIME-18` — mouth.flow_ref points at nothing

MINOR · dead-config

**Files** — `backend/agent_core/cards/schema.py:93-99`, `backend/agent_core/deployment.py:87-89`, `backend/voice/bot.py:1170-1176`

**Mechanism** — CardMouthRef documents itself as "Pointers, not copies", but the flow is resolved straight off the prompt version — `"flow": version.get("flow")` (deployment.py:89), consumed at voice/bot.py:1170. `flow_ref` has no reader in the backend at all, and no gate validates that it resolves to anything.

**Trigger** — Set flow_ref to a nonexistent id and publish: every gate passes and the call runs the version's own flow.

**Fix** — Remove the field, or make G1/G2 resolve it and fail when it names a flow that does not exist.

#### `RUNTIME-19` — skills[].version and skills[].pin are ignored — every attachment resolves by slug alone

MINOR · dead-config

**Files** — `backend/agent_core/cards/schema.py:102-107`, `backend/agent_core/skills/runtime.py:56-98`, `backend/agent_core/skills/runtime.py:72`, `backend/agent_core/skills/persist.py:689`, `backend/agent_core/cards/compile.py:478`

**Mechanism** — packs_from_card collects `[ref.skill_id for ref in card.skills]` (runtime.py:72) and hands the slugs to packs_for_slugs; the same is true of the compile path (compile.py:478) and the publish sync (persist.py:689). `version` and the exact/caret `pin` mode are never compared against anything, so a card pinned to version "1" silently runs whatever signed pack is current for that slug.

**Trigger** — Sign a v2 of ptp-negotiate that adds a tool. Every card pinned `version: "1", pin: "exact"` picks it up on the next call, with no publish and no change-log entry.

**Fix** — Store a version on signed packs and have packs_for_slugs resolve (slug, version, pin); fail closed when an exact pin cannot be satisfied. Otherwise remove both fields so the card stops claiming a pin it does not have.

#### `RUNTIME-20` — handoffs[].payload_schema is never validated and handoffs[].when is never evaluated

MINOR · dead-config

**Files** — `backend/agent_core/cards/schema.py:118-123`, `backend/agent_core/tools/domain.py:1009-1049`, `backend/agent_core/cards/compile.py:661-678`, `backend/agent_core/cards/templates.py:139`

**Mechanism** — domain.handoff_to_agent takes `payload: str | None` and passes it through to db.handoff_to_agent as an opaque string (:1043-1049) — the target's declared payload_schema is never fetched or checked, and neither is it checked at publish (G5 at compile.py:665-666 only verifies the target bot exists and is not self). `when` is free prose with no reader; it renders in the graph editor and nothing routes on it.

**Trigger** — Declare `payload_schema: {"required": ["policy_no"]}` on the insurance handoff. The model hands off with an empty payload and the transfer succeeds.

**Fix** — Validate the payload against the target's schema inside domain.handoff_to_agent (soft-fail with a spoken summary on mismatch, as the other failure branches do), and add a G5 check that payload_schema is a well-formed JSON Schema. Mark `when` as prose in the schema comment so nobody expects it to route.

#### `RUNTIME-22` — eval.suite_id is authored on every first-party card and deliberately refused by the runner

MINOR · dead-config

**Files** — `backend/agent_core/cards/schema.py:168`, `backend/agent_core/cards/defaults.py:132`, `backend/agent_core/cards/defaults.py:152`, `backend/agent_core/cards/defaults.py:172`, `backend/agent_core/cards/defaults.py:292`, `backend/agent_core/cards/defaults.py:313`, `backend/agent_core/cards/defaults.py:329`, `backend/agent_core/eval/run.py:14-36`, `backend/main.py:2791-2803`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:361-379`

**Mechanism** — All four first-party cards set a suite_id (defaults.py:172, :292, :313, :329), and agent_core/eval/run.py:14-34 documents at length why it will not resolve a card from it — the relation is one-to-many, so it returns a name match or None instead. No other code reads `card.eval.suite_id`: POST /eval/suites/{suite_id}/run takes the suite in the path and the bot in a query param (main.py:2792-2803), and the eval gates match by kind, not by suite id (compile.py:966-968).

**Trigger** — Change eval.suite_id on a card and no suite selection, scheduling or gate behaviour changes.

**Fix** — Delete the field. run.py's reasoning is sound and the field's continued presence on the card invites exactly the wrong inference; if a card must name its regression suite, make the gate read it and fail when the report's suite_id does not match.

#### `RUNTIME-12` — outbound.concurrency_share is publishable and reserves nothing

trivial · dead-config

**Files** — `backend/agent_core/cards/schema.py:332-334`, `backend/tests/test_outbound_card_switches.py:15-18`, `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:99`, `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:338-345`

**Mechanism** — The field is validated (0-100), round-tripped by the editor's state reducer (OutboundCardEditor.tsx:99) and read by nothing — outbound.place has no per-card reservation. This is acknowledged rather than accidental: the test file header (test_outbound_card_switches.py:16-19) and an editor comment (:338) both say a control for it would be "this exact failure authored on purpose", which is why no slider exists.

**Trigger** — Set concurrency_share via the API (the editor omits the control but the schema accepts it) and publish; the outbound fleet gate allocates identically.

**Fix** — Delete the field until the fleet gate can honour it. A card member that is documented as deliberately inert still ships in the published contract and in the change-log diff.

#### `RUNTIME-21` — identity.owner_user_id has no reader

trivial · dead-config

**Files** — `backend/agent_core/cards/schema.py:87`, `Habibi/src/api/agent-card.ts:132`

**Mechanism** — Every `owner_user_id` in the backend belongs to leads, promises or work items (db.py:4333, db_dashboard.py:364, etc.). The card's own owner is never read — not by authz.py for a permission check, not by the change log for attribution (which uses the acting user, agent_core/change_log.py), and not by any gate.

**Trigger** — Set an owner and nothing changes about who may edit, publish, archive or restore the card.

**Fix** — Either use it (an ownership check in authz's card write path, or an "owner" column on the fleet index) or drop it.

#### `RUNTIME-23` — policy_bindings can only ever hold one value, so G3's binding half is unfalsifiable

trivial · dead-config · prior: 2j

**Files** — `backend/agent_core/cards/schema.py:20`, `backend/agent_core/cards/schema.py:133-141`, `backend/agent_core/cards/compile.py:594-616`, `backend/agent_core/reco/config.py:54`, `backend/agent_core/treatment/config.py:51`, `backend/agent_core/authority/config.py:24`, `backend/agent_core/live_qa/config.py:35`

**Mechanism** — `PolicyBinding = Literal["required"]` (schema.py:20), so `getattr(card.policy_bindings, key, None) != "required"` at compile.py:601 can never be true for a card that parsed — any other value fails G0 first. Only the second half of G3 (`missing_locked`, :604) can actually fail. The six bindings are therefore a display-only structure, and no runtime path reads them: the reco/treatment/authority/live_qa engines take their mode from env (agent_core/reco/config.py:54, treatment/config.py:51, authority/config.py:24, live_qa/config.py:35), not from the card.

**Trigger** — None — the branch is unreachable by construction. The visible symptom is a Policy tab presenting six controls whose only legal value is the one shown.

**Fix** — Say so: collapse the six fields to a single computed assertion in the compile report, and have the Policy tab render the engines' actual runtime modes (which are env-driven and can legitimately be shadow) rather than six lozenges that cannot change.

---

## Type mirror — TypeScript vs Pydantic

13 findings — 0 MAJOR, 9 MINOR, 4 trivial; 2 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-types.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `TYPES-01` — Skill lint warnings reach the wire and die at the TypeScript boundary — the author is still told nothing

MINOR · disconnected · DOWNGRADED · **closed** in `6089743` (pass 7)

**Files** — `backend/agent_core/skills/lint.py:40`, `backend/agent_core/skills/lint.py:54-70`, `backend/agent_core/cards/compile.py:693-704`, `Habibi/src/routes/agent-studio.skills.index.tsx:140-146`

**Mechanism** — `upsert_skill_from_pack` attaches non-blocking lint findings to the saved row (`saved["lintWarnings"] = warnings`, persist.py:317). `AgentStudioSkillResponse` declares `lintWarnings: list[dict[str, Any]] | None` (schemas.py:3655) and POST/PATCH/import /agent-studio/skills all serve that model with `response_model_exclude_unset=True`, so the warnings genuinely go out on the wire. The TypeScript `SkillSummary` (agent-studio.ts:463-483) — the return type of `useCreateSkill` (agent-studio.ts:690), `usePatchSkill`, `importSkillZip` and `useAgentStudioSkill` — declares no `lintWarnings` member, and grepping Habibi/src for `lintWarnings` returns nothing. So the field is dropped at the type boundary and no component renders it. The lint module's own test file opens with "The skill linter was dead code" and asserts `description_too_long` is reported "or the author was told nothing" (test_skill_lint_wiring.py:96) — that assertion passes at the Python API and is false at the screen.

**Trigger** — Create or edit a skill whose description exceeds CATALOG_PREFIX_TOKEN_CAP (e.g. via the Skills tab or a .md import). The save succeeds, the server logs a warning (persist.py:316), the response carries `lintWarnings: [{code: "description_too_long", ...}]`, and the studio shows a plain success. The author discovers it later as a G6 / skill_description_tokens failure on the card that attaches the skill — the exact late rejection the linter was wired up to prevent.

**Fix** — Add `lintWarnings?: Array<{ code: string; message?: string; [k: string]: unknown }>` to `SkillSummary` in Habibi/src/api/agent-studio.ts, and surface it after a save in the skill editor (agent-studio.skills.$skillId.tsx) as a non-blocking warning banner. Give `usePatchSkill` / `useSignSkill` / `useRevertSkill` a real return type instead of the untyped `apiPatch`/`apiPost` they use today, so the field is reachable from every write.

#### `TYPES-02` — The Agent Card drift test guards 14 top-level names and leaves ~80 nested fields — including all of CardOutbound — unasserted

MINOR · test-gap

**Files** — `backend/tests/test_agent_card_schema_drift.py:55-85`, `backend/agent_core/cards/schema.py:79-419`, `Habibi/src/api/agent-card.ts:126-300`

**Mechanism** — `test_top_level_members_match` compares `set(AgentCard.model_fields)` against the `AGENT_CARD_MEMBERS` literal, and `test_the_declared_type_covers_every_member` compares that literal against the `type AgentCard` block. Both operate only on the 14 top-level names. Nothing walks into `CardIdentity`, `CardTools`, `CardHandoff`, `CardConnector`, `CardSkillRef`, `CardMemory`, `Compaction`, `HumanGate`, `CardEval`, `CardExperiment`, `CardA2A`, `CardOutbound`, `CardObjective`, `CardCadence`, `VoicemailPolicy`, `CardPostCall` or `PostCallRule` — ~80 fields across 17 models, every one of them under `extra="forbid"`. The file's own docstring claims the broader guarantee ("The TypeScript Agent Card and the Pydantic one must describe the same card") and the type's docstring says "`test_agent_card_schema_drift.py` fails if the two lists of top-level members stop matching" — which is the honest reading, but the file heading is not. I verified by hand that the nested mirror is correct *today*; the exposure is that it is correct by luck rather than by check, and CardOutbound's 10 fields plus CardObjective's 9 and CardCadence's 8 are the newest and least-walked.

**Trigger** — Add a field to any nested card model (or rename one) and both tests still pass. The corresponding editor panel silently cannot write it — or, in the invented-field direction, writes a key that `parse_card` rejects at G0 with a message naming a field the author picked from a control the app drew.

**Fix** — Extend test_agent_card_schema_drift.py with a recursive comparison: walk `AgentCard.model_fields` into every nested BaseModel and compare each model's field set against the members declared in the corresponding `export type X = {…}` block in agent-card.ts (the file already names each type identically to its Pydantic class, so the mapping is mechanical). Assert both directions, with the same two error messages the top-level test already writes.

#### `TYPES-03` — agent-studio.ts mirrors 14 Pydantic response models with no drift guard of any kind

MINOR · test-gap

**Files** — `backend/tests/test_agent_studio_response_models.py:28-46`, `backend/tests/test_sandbox_turn_schema.py:198-213`, `Habibi/src/api/agent-studio.ts:342`, `Habibi/src/api/agent-studio.ts:62-74`

**Mechanism** — `test_agent_studio_response_models.py` proves the HTTP body equals the *mapper* output key-for-key (`_assert_same_shape`, lines 28-46) — a backend-to-backend check. Nothing compares either side to `agent-studio.ts`. `nullability.test.ts` reads three files (`api/types/customer360.ts`, `api/types/audit.ts`, `api/customers.ts`) and asserts string literals in them; it names nothing in the studio. So `AgentCardSummary`, `CompileReport`, `CompileGate`, `AgentGraph`, `ChangeLogEntry`, `ChainVerdict`, `SkillSummary`, `CloneTemplate`, `EvalSuite`, `EvalReport`, `DeploymentExperiment`, `SkillCritique`, `QaDisagreement` and `RolesCatalog` are hand mirrors with a zero-test blast radius. The four concrete drifts I found (TYPES-04, -05, -06, -07) are all in this file, which is what an unguarded surface looks like after a few months.

**Trigger** — Any change to a model in schemas.py:3470-3690 or to CompileReport in compile.py. Backend tests stay green; the studio silently stops reading the new field, or keeps reading a removed one as `undefined`.

**Fix** — Add a source-reading drift test alongside test_agent_card_schema_drift.py, keyed on the docstring each Pydantic model already carries ("Mirrors Habibi AgentCardSummary", schemas.py:3477; "Mirrors Habibi PromptVersion", schemas.py:2206; "Mirrors Habibi TtsVoice", schemas.py:2253): parse the named `export type X = {…}` block out of the TS file and compare member sets against `model_fields`. The docstrings already declare the pairing — nothing reads them.

#### `TYPES-04` — ChangeLogEntry omits `hashes` and `previousVersionId` — the per-component hashes that make the audit entry checkable never reach the screen

MINOR · shape-mismatch

**Files** — `backend/schemas.py:3552`, `backend/schemas.py:3559`, `backend/agent_core/change_log.py:197`, `Habibi/src/api/agent-studio.ts:899-921`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:166-169`

**Mechanism** — `record_publish` writes `previousVersionId` and `hashes` (the per-component SHA of prompt/persona/voice/guardrails/flow/agent_card, from `component_hashes(version)`) into the audit payload; `read_entries` spreads the whole payload onto the entry (change_log.py:343); `AgentStudioChangeLogEntryResponse` declares both (schemas.py:3542, 3549). The TypeScript `ChangeLogEntry` declares neither. `ChangeLogTab` renders `entry.entryHash` — the chain link — and has no access to the component hashes, which are the half that lets a reader tie an entry to a specific version's contents rather than only to its neighbours in the chain.

**Trigger** — Publish any version, then open the Change log tab. `changed` shows which components moved; the hashes that would let an auditor verify *what* they moved to are on the wire and unreachable from the type. Same for `previousVersionId`: the tab shows `previousVersionLabel` (a human label, not stable) with no id to link to.

**Fix** — Add `previousVersionId?: string | null` and `hashes?: Record<string, string>` to ChangeLogEntry (agent-studio.ts:892-916). Render the component hashes in the expanded entry beside `changed`, and use `previousVersionId` to make the "previous version" label a link.

#### `TYPES-06` — AgentGraph.edges[].to is typed non-nullable while the endpoint emits `h.get("to_bot_id")` and the response model allows null

MINOR · shape-mismatch

**Files** — `backend/main.py:2281-2285`, `backend/schemas.py:3590-3593`, `Habibi/src/api/agent-studio.ts:318`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:614`, `backend/db_prompt_studio.py:1774-1778`, `Habibi/src/api/agent-card.ts:157`

**Mechanism** — The graph endpoint reads handoffs straight off the stored draft JSON without parsing the card (`raw.get("handoffs")`, main.py:2266) and builds `{"from": bot_id, "to": h.get("to_bot_id")}` — `None` for any handoff row missing the key. `AgentStudioGraphEdgeResponse.to` is correspondingly `str | None = None` (schemas.py:3584). The TypeScript `AgentGraph` declares `edges: { from: string; to: string }[]` (agent-studio.ts:317). The null is reachable because drafts are persisted unvalidated — `patch_prompt_version` casts `agentCard` to jsonb with no `parse_card` (db_prompt_studio.py:1775-1779) — and `CardHandoff.to_bot_id` is optional on the TS side too (agent-card.ts:148). AgentGraphTab already defends against the value its own type says cannot exist (`.filter((e) => e.to)`, AgentCardPanels.tsx:610), which is the tell.

**Trigger** — A draft whose `handoffs` array contains a row without `to_bot_id` (hand-edited JSON, a partially-applied migration, or any future editor that stages an empty row). Today's only consumer filters it out; a new consumer trusting `to: string` gets `null` where the type promised a bot id.

**Fix** — Type it as the server declares it: `edges: { from: string; to: string | null }[]` in agent-studio.ts:317. Optionally tighten the backend instead by dropping edges with a falsy target at main.py:2282 and making `to: str` required — but pick one, do not leave the two disagreeing.

#### `TYPES-07` — SkillSummary collapses the backend's summary/detail split and drops three declared fields

MINOR · shape-mismatch

**Files** — `backend/schemas.py:3624-3644`, `backend/schemas.py:3647-3655`, `backend/schemas.py:3605-3621`, `Habibi/src/routes/agent-studio.skills.$skillId.tsx:342-360`

**Mechanism** — The backend has two models: `AgentStudioSkillSummaryResponse` (16 required fields, served by GET /agent-studio/skills) and `AgentStudioSkillResponse` which subclasses it and adds six optional detail fields. TypeScript has one `SkillSummary` typed for both endpoints, which (a) loses the distinction — a list row is typed as if it might carry `body`, `markdown`, `frontmatter`, `versions`; (b) omits `contentHash` (schemas.py:3634, required), `evalSuite` (schemas.py:3633, required) and `lintWarnings` (see TYPES-01); (c) declares `latestVersionId?: string` where the wire is `str | None`, so `null` is assignable to nothing and a strict `!`-assertion would lie; (d) types `versions?: Array<{ id; version; status }>` — three of the fourteen fields on `AgentStudioSkillVersionResponse` (schemas.py:3596-3614), so `signedBy`, `signature`, `contentHash` and `allowedTools` per version are unreachable even though the detail route serves them and the version list at agent-studio.skills.$skillId.tsx:344-360 is exactly where they would be shown.

**Trigger** — Read-only: the studio simply cannot display a skill's content hash, its bound eval suite, or per-version signature provenance. `latestVersionId` null-vs-undefined bites only if someone writes a non-null assertion.

**Fix** — Split into `SkillSummary` and `SkillDetail extends SkillSummary` mirroring the two Pydantic models; add `contentHash: string`, `evalSuite: unknown | null`, `lintWarnings?`, widen `latestVersionId` to `string | null`, and type `versions` against the full `AgentStudioSkillVersionResponse`.

#### `TYPES-08` — BotDeployment omits trafficPct, shadow and evalReportId — the three fields that say what a deployment is actually taking

MINOR · shape-mismatch

**Files** — `backend/schemas.py:2339-2358`, `backend/schemas.py:2356-2358`, `Habibi/src/api/prompt-studio.ts:452`, `Habibi/src/api/prompt-studio.ts:477`, `Habibi/src/api/prompt-studio.ts:884-895`, `Habibi/src/routes/prompt-studio.lazy.tsx:459-467`, `backend/db_prompt_studio.py:1577`

**Mechanism** — `BotDeploymentResponse` carries `trafficPct: int = 100`, `shadow: bool = False` and `evalReportId: str | None` (schemas.py:2338-2340) — the record of what split and what eval evidence a deployment shipped under. The TypeScript `BotDeployment` (prompt-studio.ts:33-46) declares 12 of the 15 fields and none of those three. The Ship tab gets its split from a different source, `DeploymentExperiment` on GET /bot-deployments/experiments (agent-studio.ts:449-459, consumed at prompt-studio.lazy.tsx:458-466), so a deployment row rendered from `useBotDeployments` can never say what traffic it holds.

**Trigger** — Any deployments list rendered from the `BotDeployment` type shows the deployment without its split; a canary at 40% is indistinguishable from a full ship, and `evalReportId` — the link from a live deployment to the eval that let it through G7/G8 — is unreachable.

**Fix** — Add `trafficPct: number; shadow: boolean; evalReportId: string | null;` to `BotDeployment` in prompt-studio.ts:33-46, and render the split on the deployment row so the experiment query stops being the only place it exists.

#### `TYPES-10` — Sandbox read types drop five served fields, including the tool-loop trace

MINOR · shape-mismatch

**Files** — `backend/schemas.py:2633-2634`, `backend/schemas.py:2487`, `backend/schemas.py:2489`, `backend/schemas.py:2494`, `backend/schemas.py:2496`, `backend/sandbox_runtime.py:1106`

**Mechanism** — `SandboxBotTurn.toolCalls: list[dict[str, Any]]` (schemas.py:2624, commented "Tool-loop trace from sandbox_runtime") is on the POST /sandbox/runs/{id}/turns response and absent from the TypeScript `SandboxTurnResult.botTurn` (sandbox.ts:67-82); no frontend consumer exists (the `toolCalls` matches in Habibi/src are trace.ts:60 and the live-voice event stream, which are different payloads). Separately, `SandboxRunTurnResponse` declares `sentimentLabel`, `retrievedChunkIds`, `tokenCount` and `createdAt` (schemas.py:2487-2494) that `SandboxRunDetail.turns` (sandbox.ts:98-115) does not name — so a replayed run shows a raw sentiment float with no label while a live turn shows the label from `customerTurn.sentimentLabel`.

**Trigger** — Run a text-sandbox turn that calls a tool: the trace is computed, serialised and dropped. Reload a completed run: the per-turn sentiment label and the retrieved-vs-cited chunk id distinction are on the wire and unreadable.

**Fix** — Add `toolCalls?: Array<Record<string, unknown>>` to `SandboxTurnResult.botTurn` and render it in the sandbox inspector's Tools tab (which already renders the same shape from trace.ts). Add `sentimentLabel`, `retrievedChunkIds`, `tokenCount`, `createdAt` to `SandboxRunDetail.turns`.

#### `TYPES-11` — Every /eval/* route serves an untyped dict, so the Evals tab's TypeScript types mirror nothing and the response-shape test cannot see them

MINOR · tool-definition

**Files** — `backend/main.py:2796-2798`, `backend/main.py:2812-2822`, `backend/db_inbox.py:1726-1739`, `backend/db_inbox.py:1700-1714`, `Habibi/src/api/agent-studio.ts:342`, `backend/tests/test_agent_studio_response_models.py:53`

**Mechanism** — GET /eval/suites, /eval/reports, /eval/reports/{id}, /eval/critiques, /eval/disagreements and /eval/twin-corpus declare no `response_model`. `list_eval_suites` returns `[dict(r) for r in rows]` over `SELECT id, kind, name, description, created_at` (db_inbox.py:1728-1737) — raw snake_case `created_at` reaches the wire, and TS `EvalSuite` (agent-studio.ts:353) names four of the five. `test_every_agent_studio_route_declares_a_response_shape` filters on `route.path.startswith("/agent-studio")` (test_agent_studio_response_models.py:53), so it asserts nothing about /eval/*, and by the same filter nothing about /flow/*, /sandbox/*, /prompt-versions, /connectors*, /mcp/*, /a2a*, /bot-deployments* or /outbound/*. That is most of the Studio's wire.

**Trigger** — Any change to the eval_suites or eval_reports SELECT list silently changes the wire. There is no model to fail, no mapper comparison to fail, and no TS drift test — three layers of guard that all stop at the /agent-studio prefix.

**Fix** — Declare response models for the /eval/* routes the studio reads (suites, reports, critiques, disagreements) mirroring the existing AgentStudio* naming, and widen the route filter in test_agent_studio_response_models.py:47-64 from `/agent-studio` to the set of studio prefixes the audit enumerates.

#### `TYPES-05` — CompileReport.mission_entries is computed, serialised and never consumed; its docstring names a consumer that reads a different endpoint

trivial · dead-config · DOWNGRADED

**Files** — `backend/agent_core/cards/compile.py:953`, `Habibi/src/api/agent-studio.ts:62-74`, `backend/main.py:5344-5348`, `backend/main.py:5363`

**Mechanism** — `CompileReport.mission_entries: dict[str, str]` is populated on every compile (`mission_entries=_mission_entries(flow)`, compile.py:952) and shipped as part of the `response_model=CompileReport` body of POST /agent-studio/cards/{bot_id}/compile. Its docstring says "The Outbound tab renders this beside what the card claims, because the two disagreeing is the failure G-OB2 exists to catch". The TypeScript `CompileReport` (agent-studio.ts:60-71) declares seven members and not this one; grepping Habibi/src for `mission_entries` or `missionEntries` returns nothing. The Outbound tab does render both halves — from `graphEntries` and `graphEntryNode`/`agrees` on GET /outbound/missions (main.py:5344-5361), a second, independently computed copy of the same fact.

**Trigger** — Open the compile preview on any card. `mission_entries` is computed and sent on every keystroke-debounced compile (useCompilePreview, agent-studio.ts:230-260) and discarded. The cost is a stale docstring pointing a future reader at the wrong producer for a G-OB2 disagreement.

**Fix** — Either declare `mission_entries: Record<string, string>` on the TS CompileReport and let the Outbound tab read the compile report it already holds (dropping the second source), or delete the field from CompileReport and correct the docstring to name /outbound/missions. Two independently derived copies of "where does this mission start" is exactly the shape G-OB2 exists to police.

#### `TYPES-09` — PromptVersion omits `tuning`, the column publish reads and VoicePanel writes through

trivial · shape-mismatch · DOWNGRADED · **closed** in `6089743` (pass 7)

**Files** — `Habibi/src/api/types/prompt-studio.ts:61-85`, `backend/db_prompt_studio.py:1735-1749`, `backend/db_prompt_studio.py:1755-1762`, `Habibi/src/api/prompt-studio.ts:45`, `Habibi/src/components/prompt-studio/VersionHistory.tsx:164-166`

**Mechanism** — `PromptVersionResponse.tuning: dict[str, Any]` (schemas.py:2224) is served on every version read. The TypeScript `PromptVersion` (api/types/prompt-studio.ts:59-82) declares id, label, author, status, createdAt, summary, prompt, persona, voice, guardrails, flow, flowUnreadable, botId, agentCard — no `tuning`. The field is not decorative: `patch_prompt_version` folds the VoicePanel's voice config into it on every autosave (`apply_voice_config_overlay`, db_prompt_studio.py:1735-1745) with the comment "publish reads this", and an explicit Tuning Studio write overrides it (db_prompt_studio.py:1755-1761). So the studio edits `tuning` indirectly and can never read back what it produced.

**Trigger** — Adjust a voice slider, autosave, then look at the version: the derived tuning that will ship is on the wire and invisible to the editor, to the diff and to the version-history comparison.

**Fix** — Add `tuning?: Record<string, unknown>` to `PromptVersion` (api/types/prompt-studio.ts) and include it in the version diff, so a publish cannot change the runtime tuning without the diff saying so.

#### `TYPES-12` — agent-card.ts restates six closed vocabularies that the backend guards against each other, and a cast in the editor makes the TypeScript half unenforceable

trivial · test-gap · DOWNGRADED

**Files** — `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:653`, `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:660`, `Habibi/src/components/flow/FlowInspector.tsx:178-198`, `backend/tests/test_outbound_card_vocabulary.py:14-18`

**Mechanism** — agent-card.ts restates `Objective` (13 members), `Direction`, `VoicemailMode`, `TimeOfDay`, `PoolKind` and `PostCallQa`. Backend-side these are well policed: test_outbound_card_vocabulary.py asserts the /outbound/card-vocabulary lists equal `fg.OBJECTIVES` and each `get_args(schema.<Literal>)`, and its docstring says the whole defence is that "the frontend restates nothing". The frontend does restate them. Only `ROLLBACK_TRIGGERS` has a matching TS assertion (test_agent_card_schema_drift.py:86-101) — added, per its own docstring, after exactly this class of bug. Worse, the restatement cannot even fail loudly: OutboundCardEditor casts the server-supplied option with `key as Objective` (line 659) and `o as Objective` (line 653), so a vocabulary the backend widened flows through the TypeScript union untouched.

**Trigger** — Add a member to `flow_graph.OBJECTIVES` and `schema.Objective`. Every backend test passes, /outbound/card-vocabulary offers it, the `as Objective` cast accepts it — and the stale TS `Objective` union is now a comment claiming to be a type. In the opposite direction (a member removed from the Literal but left in the TS union) the editor's own type would still bless a value the card rejects at parse.

**Fix** — Extend test_agent_card_schema_drift.py with the same regex-and-compare treatment ROLLBACK_TRIGGERS already gets, for `Objective`, `Direction`, `VoicemailMode`, `TimeOfDay`, `PoolKind`, `Channel`, `DataClass`, `MemoryScope`, `EvalRequire` and `HumanGateRequire` against `get_args()` of each Literal. Then drop the `as Objective` casts in OutboundCardEditor.tsx:653,659 in favour of a narrowing predicate, so the union actually gates.

#### `TYPES-13` — nullability.test.ts covers three non-studio files while ~40 nullable studio wire fields go unpinned

trivial · test-gap · DOWNGRADED

**Files** — `Habibi/src/api/types/nullability.test.ts:11-63`, `backend/schemas.py:3593`, `backend/schemas.py:3633`, `backend/schemas.py:2347-2353`

**Mechanism** — The nullability suite reads `api/types/customer360.ts`, `api/types/audit.ts` and `api/customers.ts` and asserts string literals in them (`summary: string | null;` etc.). It names no studio file. Meanwhile the studio wire is full of `X | None`: AgentStudioCardResponse has six (`trafficPct`, `lastPublish`, `promptVersionId`, `draftVersionId`, `archivedAt`, plus AgentStudioChangeLogEntryResponse's fifteen), AgentStudioGraphEdgeResponse.to, AgentStudioSkillSummaryResponse.latestVersionId, BotDeploymentResponse's five, PromptTokenEstimateResponse's two. TYPES-06 (`to: string` vs `str | None`) and TYPES-07 (`latestVersionId?: string` vs `str | None`) are both instances the existing suite is shaped to catch and does not, because it was written for one work-package's files and never widened.

**Trigger** — A nullable studio field is typed non-nullable; `strict` TypeScript compiles clean because the assertion lives in a test that reads different files.

**Fix** — Add a studio block to nullability.test.ts covering api/agent-studio.ts, api/prompt-studio.ts, api/types/prompt-studio.ts and api/sandbox.ts — or, better, generate the assertions from the Pydantic models in the drift test proposed in TYPES-03, where `field.annotation` already knows whether None is allowed.

---

## Authorization, tenancy and audit on every studio write

17 findings — 6 MAJOR, 11 MINOR, 0 trivial; 8 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-authz.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `AUTHZ-1` — Approving a connector or refreshing its tool cache silently widens the live Tool Grant of an already-published card — INTEGRATIONS_WRITE, no publish gate, no change-log entry

**MAJOR** · security · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/skills/intersect.py:117-123`, `backend/agent_core/connectors/persist.py:193`, `backend/agent_core/connectors/persist.py:222`, `backend/agent_core/connectors/persist.py:230`, `backend/agent_core/connectors/persist.py:306`, `backend/bot_runtime.py:916`, `backend/bot_runtime.py:943`, `backend/bot_tools.py:806`, `backend/bot_tools.py:810`, `backend/voice/bot.py:1141`, `backend/agent_core/change_log.py:162`

**Mechanism** — card.connectors is resolved at TURN time, not at publish time. skills/runtime.py:192-199 (Mouth.turn_state, reached from voice/bot.py:100 resolve_mouth) calls intersect.effective_tools, which at intersect.py:117-123 calls connectors/persist.bound_tool_names. That function re-reads the registry (persist.py:216) and admits ext.* names only when `conn['status'] != 'approved': continue` (persist.py:222) and only for names present in `conn.get('toolsCache')` (persist.py:230-233). Both of those columns are mutable after publish by INTEGRATIONS_WRITE: POST /connectors/{id}/approve flips status (persist.py:201-205) and POST /connectors/{id}/test rewrites tools_cache from whatever the remote MCP server returns (persist.py:303-314). The publish compiler's G10 (compile.py:753-864) reads the same columns but only at publish, and the published prompt_versions row records only the card's connector *reference*, not the connector's state. So the Agent Card contract — the thing the change log hashes — does not pin the tool set that the runtime actually grants. Nothing in agent_core/change_log.py:41-44 records either mutation.

**Trigger** — Card kaia names connector `paylink` with allow_prefixes ['ext.paylink.']; it is approved and G10 passes at publish. Later the remote server advertises a new tool `refund` under that prefix. Anyone holding INTEGRATIONS_WRITE (or an automated health probe) calls POST /connectors/paylink/test; tools_cache now contains it. The next voice turn's effective_tools includes ext.paylink.refund and voice/tools.py will execute it. No republish, no AGENT_PUBLISH, no compile report, no change-log row, and GET /agent-studio/change-log still shows the last publish as the most recent change to what this agent can do.

**Fix** — Freeze the connector state into the published artifact: at publish, resolve bound_tool_names once and store the resolved ext.* name list (plus the connector's status and tools_cache digest) on the deployment bundle, and have runtime.Mouth.turn_state intersect against that stored list instead of re-reading mcp_connectors. If a live read must stay, then approve/test/upsert on a connector referenced by any published card must require AGENT_PUBLISH and must write a change_log entry with a new kind (agent.tool_grant) so the chain covers it.

#### `AUTHZ-2` — Deployment rollback re-publishes production on BOT_WRITE and never runs the compiler — every gate G0-G15, including G14 agent_publish, is skipped

**MAJOR** · security · prior: SHELL-2 · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/db_prompt_studio.py:2292`, `backend/db_prompt_studio.py:2358`, `backend/db_prompt_studio.py:2378`, `backend/agent_core/cards/compile.py:932`, `backend/main.py:3371`

**Mechanism** — POST /prompt-versions/{id}/publish is AGENT_PUBLISH (authz.py:290) and db_prompt_studio.publish_prompt_version calls compile_card + assert_publishable (db_prompt_studio.py:1906-1936) with has_publish=_authz.has_permission(uid, AGENT_PUBLISH) feeding G14 (compile.py:932-938). POST /bot-deployments/{deployment_id}/rollback is BOT_WRITE (authz.py:279) and db_prompt_studio.rollback_bot_deployment (2292-2424) does the same two production mutations — UPDATE prompt_versions SET status='published' (2358-2365) and INSERT bot_deployments ... 'production','active' (2378-2405) — with no call to compile_card anywhere in the function. So a BOT_WRITE holder promotes an arbitrary prior prompt version to `published` and makes it the active production deployment while G0 (schema), G9 (signed skills), G12 (canary), G13 (A2A mTLS) and G14 (agent.publish) never execute. The docstring at 2294 states the invariant ('Re-publish is mandatory') without noticing that it re-publishes past the compiler.

**Trigger** — Grant a custom role BOT_WRITE and nothing else. GET /bot-deployments?botId=kaia-v2-4 to list retired rows, then POST /bot-deployments/{that id}/rollback. Production now serves that prompt version; the actor never held AGENT_PUBLISH and G14 was never evaluated.

**Fix** — Raise the route to AGENT_PUBLISH in authz.py:279 (matching the sibling at :278) and, independently, run compile_card + assert_publishable inside rollback_bot_deployment on the version it is about to re-publish — a version that was publishable six weeks ago is not necessarily publishable against today's catalog, skill signatures or A2A certs.

#### `AUTHZ-3` — PATCH /prompt-versions/{id} accepts `agentCard` on BOT_WRITE, so AGENT_EDIT is unenforceable for card authoring

**MAJOR** · security · prior: SHELL-2 · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/schemas.py:2388`, `backend/schemas.py:2373`, `backend/authz.py:287`, `backend/main.py:2144`, `backend/db_prompt_studio.py:1774`

**Mechanism** — PATCH /agent-studio/cards/{bot_id} requires AGENT_EDIT (authz.py:301) and its handler (main.py:2127-2145) ends in db.patch_prompt_version(draft_id, {'agentCard': card}). PATCH /prompt-versions/{version_id} requires only BOT_WRITE (authz.py:288), and PromptVersionPatchRequest declares `agentCard: dict[str, Any] | None` (schemas.py:2389), which patch_prompt_version writes to the same column (db_prompt_studio.py:1774-1778). The full escalation path needs no AGENT_EDIT at all: POST /prompt-versions/{published_id}/restore-as-draft (BOT_WRITE, authz.py:291) manufactures the draft, then PATCH rewrites its Agent Card — tools.include, handoffs, connectors, skills, human_gates. AGENT_EDIT is described as 'Author agent cards, tools and handoff allowlists' (authz.py:131); the separation of duties it declares does not exist.

**Trigger** — Actor holds BOT_WRITE only. GET /prompt-versions/published?botId=kaia-v2-4 -> POST /prompt-versions/{id}/restore-as-draft -> PATCH /prompt-versions/{new draft id} with body {"agentCard": {...tools.include widened...}}. All three calls pass the guard.

**Fix** — Either drop `agentCard` from PromptVersionPatchRequest and make the card route the only writer, or split the guard so a patch body containing agentCard/flow requires AGENT_EDIT while prompt/persona/voice/guardrails stay BOT_WRITE. A per-field requirement cannot live in the route table, so the clean version is the first.

#### `AUTHZ-6` — G13 (A2A mTLS) is satisfied by a self-asserted DN string that an INTEGRATIONS_WRITE holder types in, and it ignores the bot it is asked about

**MAJOR** · security · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/a2a.py:222`, `backend/agent_core/a2a.py:262`, `backend/agent_core/a2a.py:264`, `backend/agent_core/cards/compile.py:897`, `backend/agent_core/cards/compile.py:917`, `backend/db_prompt_studio.py:1894`

**Mechanism** — publish_prompt_version calls partner_has_cert(bot_id) when the card exposes A2A (db_prompt_studio.py:1888-1894) and feeds the result to G13, which the compiler docstring calls blocking (compile.py:13). partner_has_cert immediately does `del bot_id` (a2a.py:264) and then asks only whether the tenant has ANY active partner row with a non-empty cert_fingerprint (a2a.py:267-279). That fingerprint comes from upsert_partner, which accepts `certFingerprint` verbatim or derives one from a `certDn` string with fingerprint_dn (a2a.py:222-227) — no certificate is presented, parsed or validated. So the publish-time mTLS gate for a bot is passed by any INTEGRATIONS_WRITE holder posting {"certDn": "CN=anything"} once, for any bot in the tenant.

**Trigger** — POST /a2a/partners {"name":"x","certDn":"CN=x"} once. Every subsequent publish of every A2A-exposing card in that tenant reports G13 pass.

**Fix** — Require a real certificate (PEM) on the partner row and derive the fingerprint from it, and make partner_has_cert actually consult the bot — the parameter is accepted and discarded, which is the clearest signal the gate was never wired to the question it claims to answer.

#### `AUTHZ-7` — Changing who may publish an agent card writes no audit record at all

**MAJOR** · security · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/db.py:215`, `backend/db.py:243`, `backend/db.py:253`, `backend/main.py:2984`, `backend/agent_core/change_log.py:162`

**Mechanism** — PATCH /roles/{role_id}/permissions -> db.replace_role_permissions (db.py:215-270) sets roles.configured_at, DELETEs every role_permissions row and re-inserts the caller's set. It writes nothing to audit_log, nothing to activity_events, and roles/role_permissions carry no changed_by column. The only writer of audit_log in the whole backend is agent_core/change_log.py:162, and its vocabulary is four kinds — PUBLISH/ROLLBACK/ARCHIVE/RESTORE (change_log.py:41-44). So the single most privileged write in the product — granting or revoking perm-agent-publish, or granting perm-admin-write, which resolve_role_grants:695-696 turns into ALL_PERMISSIONS — leaves no trace of who did it or when. The hash-chained change log at GET /agent-studio/change-log presents itself as the tamper-evident record of what changed about an agent (change_log.py:1-30), and it cannot answer 'who was allowed to publish this'.

**Trigger** — An admin grants perm-agent-publish to role-agent, an agent publishes a card, the grant is removed. GET /agent-studio/change-log shows the publish with an actor who, by the time an auditor looks, holds no publish permission and no record explains why the publish was permitted.

**Fix** — Write an audit_log row from replace_role_permissions with the before/after grant sets, inside the same transaction as the DELETE/INSERT (the change_log._write pattern at change_log.py:137-180 already takes a connection for exactly this reason). A new chain kind, or a plain audit_log row with action='role.grants.replace', both work; the requirement is that it commits with the change.

#### `AUTHZ-9` — Canary/experiment rollback swaps the live production deployment with no change-log entry and no actor recorded anywhere

**MAJOR** · security · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/agent_core/canary.py:136`, `backend/agent_core/canary.py:167`, `backend/agent_core/canary.py:175`, `backend/main.py:3211`, `backend/main.py:3214`, `backend/db_prompt_studio.py:2410`

**Mechanism** — rollback_experiment (canary.py:149-191) sets the canary deployment to 'retired' and the baseline deployment back to 'active' (canary.py:166-174) — the same class of change as db_prompt_studio.rollback_bot_deployment, which explicitly records one ('A rollback changes what callers hear exactly as much as a publish does, so it belongs in the same chain', db_prompt_studio.py:2411-2424). rollback_experiment writes no change_log entry, records no actor on the deployment rows it flips, and the only trace is deployment_experiments.rollback_reason — a free-text string taken from the request body (main.py:3214) with no identity attached. The route's `reason` defaults to the literal 'manual', so the record of who moved production traffic off a canary is the word 'manual'.

**Trigger** — POST /bot-deployments/experiments/{id}/rollback. GET /agent-studio/change-log for that bot shows nothing between the publish that started the canary and the next publish, while production has been served by a different deployment for the interval in between.

**Fix** — Call change_log.record_rollback from inside rollback_experiment's transaction with from/to deployment ids, exactly as db_prompt_studio.py:2413-2424 does — it already takes a connection argument for this.

#### `AUTHZ-10` — Connector approval, MCP key mint/rotate and provider bindings record no actor — the columns to record one do not exist

MINOR · security · **closed** in `340a707` (pass 7)

**Files** — `backend/agent_core/mcp_http/auth.py:100`, `backend/agent_core/mcp_http/auth.py:110`, `backend/alembic/versions/20260815_0076_mcp_phase3.py:72`

**Mechanism** — mcp_connectors (DDL at 20260815_0076_mcp_phase3.py:72-99) has no approved_by / approved_at column, and approve() (persist.py:201-205) writes only status. mcp_keys is minted with no created_by (auth.py:106-122). upsert_provider_binding (main.py:5489-5501) passes tenant/slot/model and no actor, for a write whose own registry comment says it is 'a data-residency decision, not a preference' (authz.py:392-394). None of the three writes an audit_log row (the only writer is change_log.py:162). Every one of these is a trust decision about a regulated collections agent — which external server it may call, which key may drive it, which vendor processes the caller's audio — and none of them can be attributed after the fact.

**Trigger** — An auditor asks who approved connector conn-hdfc.retail-paylink, or who bound the tts slot to a non-EU vendor. The database has the answer for neither.

**Fix** — Add actor + timestamp columns to mcp_connectors, mcp_keys and provider_bindings and populate them from db._actor_user_id() (already imported wherever these writes live), or route all three through an audit_log write. The former is cheaper and puts the answer next to the state it explains.

#### `AUTHZ-11` — The version-level writes carry no tenant predicate while the card-level writes do

MINOR · security

**Files** — `backend/db_prompt_studio.py:1713`, `backend/db_prompt_studio.py:1855`, `backend/db_prompt_studio.py:2212`, `backend/db_prompt_studio.py:2269`, `backend/db_prompt_studio.py:2316`, `backend/db_prompt_studio.py:661`, `backend/agent_core/skills/persist.py:606`

**Mechanism** — Inside one module the two halves disagree. archive_agent_studio_card (661), restore_agent_studio_card (730,740) and get_agent_studio_card (595) all scope with `AND tenant_id = :t`. patch_prompt_version (1713), discard_prompt_version (2270), restore_prompt_version_as_draft (2207), publish_prompt_version (1852) and rollback_bot_deployment (2310) all select `WHERE id = :id` alone. restore_prompt_version_as_draft is the sharpest: it reads any version's prompt, persona, guardrails and agent_card by id and INSERTs a copy stamped with the CALLER's `_tenant()` (2238-2251) — a cross-tenant copy of another tenant's Mouth into your own drafts. rollback_bot_deployment does the same for deployments and then records the change_log entry under the caller's tenant (2417), so the affected tenant's own chain would not show it. attach_skill_to_prompt/detach_skill_from_prompt (persist.py:606-638) likewise take an arbitrary prompt_version_id with neither a tenant nor a draft check. Latent today: nothing binds a per-request tenant (tenant_context.py:75-77 falls back to the process constant) and grep of backend/ finds no ENABLE ROW LEVEL SECURITY or CREATE POLICY anywhere, so the Python predicate is the only tenancy there is.

**Trigger** — Bind a second tenant per request (the seam tenant_context.py:80-84 exists for exactly this) and the first BOT_WRITE call to POST /prompt-versions/{other tenant's version}/restore-as-draft copies their prompt into yours.

**Fix** — Add `AND tenant_id = :t` to the five SELECTs and make the UPDATEs match. The module already imports _tenant in each of these functions for other reasons (1839, 2199, 2300), so this is a predicate, not a plumbing change.

#### `AUTHZ-12` — perm-redteam-run is offered on the Roles screen and enforced by no route

MINOR · dead-config

**Files** — `Habibi/src/routes/roles.tsx:84`, `backend/main.py:2779`

**Mechanism** — REDTEAM_RUN is defined (authz.py:94), catalogued with the description 'Run red-team suites against a card' (authz.py:134), upserted into the permissions table at boot (ensure_permission_catalog, authz.py:876) and rendered as a togglable checkbox by roles.tsx:84-96. It appears in no ROUTE_PERMISSIONS entry, and grep of backend/*.py finds no other reference. Red-team suites actually run through POST /eval/suites/{suite_id}/run (main.py:2780), which is EVAL_RUN (authz.py:351) — the same permission as a regression suite. Revoking perm-redteam-run therefore stops nobody from running red-team suites, and granting it enables nothing.

**Trigger** — Untick perm-redteam-run for every role. POST /eval/suites/redteam-basic/run still succeeds for any EVAL_RUN holder. The Roles screen showed the operator a control that does nothing.

**Fix** — Either gate the redteam suites on it — the route would need to branch on suite kind, so more likely split the route into /eval/suites/{id}/run and a redteam sibling — or delete REDTEAM_RUN from PERMISSION_CATALOG. A permission an operator can toggle and that changes nothing is worse than no permission, because it reads as a control that is in place.

#### `AUTHZ-13` — The frontend has no notion of the actor's permissions, so every privileged studio control renders enabled and fails after the click with a raw permission id

MINOR · a11y · **closed** in `e30ce97` (pass 7)

**Files** — `backend/main.py:577`, `backend/schemas.py:531`, `backend/main.py:1314`, `Habibi/src/api/config.ts:103`

**Mechanism** — GET /me is public (authz.py:245) and MeResponse (schemas.py:531-543, extra='forbid') returns id/name/kind/team/status/tenantId — no roles, no permissions. Nothing else exposes the caller's grants: GET /roles returns the whole tenant's role table, not the caller's. So no component can gate on authorization, and none does — StudioHeader's publishDisabled is `!(canPublish ?? dirty) || publishBlocked` (StudioHeader.tsx:67) fed `Boolean(draftId) || dirty` (prompt-studio.lazy.tsx:1252), which is draft state. The sharpest case is the Roles screen itself: GET /roles is BOT_READ while PATCH /roles/{id}/permissions is ADMIN_WRITE (authz.py:362-363), so a supervisor opens the page, sees a full grid of live checkboxes for every permission on every role, and every toggle fails. The failure text is the API detail verbatim (config.ts:104-106) over the 403 body main.py:577 builds — the toast reads 'PATCH /roles/role-agent/permissions failed: forbidden:perm-admin-write'.

**Trigger** — Sign in as a supervisor, open /roles, tick any box.

**Fix** — Add `permissions: string[]` to MeResponse (it is already the public, self-scoped route, and it already resolves the actor) and disable — do not hide — the controls the caller cannot use, with the reason on the tooltip. That also lets the 403 toast be written in English instead of echoing a permission id.

#### `AUTHZ-14` — With a shared API_KEY every caller resolves to ACTOR_USER_ID, which the seed makes an admin — enforcement is on and universally satisfied

MINOR · degradation-lie

**Files** — `backend/authz.py:640`, `backend/actor_context.py:229`, `backend/actor_context.py:35`, `backend/seed_postgres.py:691`, `backend/authz.py:743`

**Mechanism** — enforcement_enabled returns True as soon as API_KEY is set (authz.py:639-640). But with API_KEY set and API_KEY_MAP empty, resolve_authenticated_actor falls through to _resolve_shared_key_actor, which returns default_actor_user_id() — 'priya-nair' (actor_context.py:229-238, :37) — for every caller unless ALLOW_ACTOR_HEADER is on, which it is not in production (actor_context.py:60-73). seed_postgres.py:691 assigns priya-nair role-admin, and _load_grants short-circuits any admin-named role to ALL_PERMISSIONS (authz.py:743-746). So in the shared-key configuration the registry is enforced against one superuser identity: every permission check passes, every write is attributed to the same person, and the Roles screen's grants describe a policy that is never consulted. .env.example ships API_KEY= and API_KEY_MAP= both blank with the comment 'Preferred multi-user keys' (:190), so the shared-key path is the easy one to land on.

**Trigger** — Deploy with APP_ENV=production and a single API_KEY. Grant role-agent nothing. An agent's key still publishes agent cards, because the key is the shared one and the actor is priya-nair.

**Fix** — Refuse to boot in production with API_KEY set and API_KEY_MAP empty, or at minimum log a startup warning that names the collapsed identity. validate_configured_actors (actor_context.py:161) already runs at lifespan and is the right place.

#### `AUTHZ-17` — AUTHZ_ENFORCE=0 does not disable authorization on /tts-voices/catalog/sync — it is the one route with a second, independent admin definition

MINOR · doc-vs-code

**Files** — `backend/main.py:838`, `backend/authz.py:856`, `backend/db_redaction.py:99`

**Mechanism** — authz.py:33 documents AUTHZ_ENFORCE as overriding 'in either direction', and check() early-returns when enforcement is off (authz.py:856). POST /tts-voices/catalog/sync carries both the registry entry ADMIN_WRITE (authz.py:387) and a per-route Depends(require_admin) (main.py:3066-3067). require_admin (main.py:839-848) keys off API_KEY/API_KEY_MAP alone and does not consult enforcement_enabled, so AUTHZ_ENFORCE=0 with API_KEY set leaves this one route gated. It also uses a different definition of admin: db_redaction.actor_is_admin (:99-127) matches role name 'admin' or a literal role_permissions row for perm-admin-write, ignoring roles.configured_at and ROLE_DEFAULTS, so the two enforcers can disagree for a role whose ADMIN_WRITE is resolved rather than stored.

**Trigger** — Set AUTHZ_ENFORCE=0 to debug a permissions problem in staging. Every route opens except this one, which still 403s 'admin_required' — a different detail string from the registry's 'forbidden:perm-admin-write', so the two failures do not even look related.

**Fix** — Delete the Depends(require_admin) — the registry entry already says ADMIN_WRITE and the global guard already enforces it. That leaves one definition of admin and one kill switch.

#### `AUTHZ-18` — No test asserts that a production-mutating route requires a production-level permission

MINOR · test-gap

**Files** — `backend/tests/test_authz.py:579`, `backend/tests/test_authz.py:592`

**Mechanism** — tests/test_authz.py is thorough on structure — the registry is total (:40), no entry names a route that does not exist (:45), every registered permission is in the catalog (:124), and no GET requires a write permission (:579 test_no_read_route_requires_a_write_permission). The converse is untested. test_agent_cannot_publish_an_agent_card (:592) pins the one route whose permission is right; nothing pins the ones that are wrong. AUTHZ-2 (rollback re-publishes on BOT_WRITE), AUTHZ-3 (agentCard editable on BOT_WRITE) and AUTHZ-4 (archive stops traffic on AGENT_EDIT) would all be caught by one test that asserts a fixed set of production-mutating path templates requires AGENT_PUBLISH.

**Trigger** — The three findings above shipped and are green in CI.

**Fix** — Add a test that names the routes which change what production says or whether it says anything — publish, both rollbacks, archive, restore, and any route reachable to a BOT_WRITE-only actor that can write prompt_versions.agent_card — and asserts each maps to AGENT_PUBLISH. Structure it as a literal list, so adding a route to it is a deliberate act.

#### `AUTHZ-19` — patch_skill rewrites a first-party skill that delete_skill refuses to touch

MINOR · security

**Files** — `backend/agent_core/skills/persist.py:381`, `backend/agent_core/skills/persist.py:400`, `backend/agent_core/skills/persist.py:514`, `backend/agent_core/skills/persist.py:660`, `backend/agent_core/skills/persist.py:744`, `backend/main.py:2333`

**Mechanism** — delete_skill guards first-party packs explicitly ('first-party packs are re-seeded on API boot, so deleting one is a no-op that looks like a success', persist.py:502-514), and the authz registry cites those guards as the reason DELETE can be AGENT_EDIT (authz.py:314-316). patch_skill (persist.py:381-410) has no equivalent guard: it carries the existing origin forward (:400) and re-upserts with signed=False, so an AGENT_EDIT holder can rewrite a first-party skill's body and its allowed-tools list and drop it to unsigned. Production is protected at the next publish — G9 blocks unsigned attached packs (compile.py:749) and ensure_first_party_skills never overwrites tenant edits (persist.py:744) — but the currently published card resolves packs by slug through _latest_signed_version, so the tenant's edited-then-signed version can displace the platform's.

**Trigger** — PATCH /agent-studio/skills/{first-party skill id} with a new allowed_tools list, then POST .../sign (AGENT_PUBLISH). packs_for_slugs now returns the tenant's version for that slug for every card that names it.

**Fix** — Apply delete_skill's origin guard to patch_skill: refuse a first-party skill and tell the caller to clone it (clone_skill at :474 already exists for exactly this), which is what the fleet's clone-first model assumes.

#### `AUTHZ-4` — Archiving takes a live agent off the air on AGENT_EDIT, while the safety brake that stops a bad canary needs AGENT_PUBLISH — the two rollback routes also disagree with each other

MINOR · security · DOWNGRADED

**Files** — `backend/db_prompt_studio.py:652`, `backend/db_prompt_studio.py:654`, `backend/db_prompt_studio.py:683`, `backend/agent_core/cards/routing.py:34`

**Mechanism** — Three sibling routes rank risk in the wrong order. POST /agent-studio/cards/{bot_id}/archive is AGENT_EDIT (authz.py:302), and archive_agent_studio_card deliberately retires the active production deployment rather than refusing (db_prompt_studio.py:632-638 docstring; the UPDATE at 683-692 sets status='retired' on the active production row) — an authoring permission that stops production traffic. POST /bot-deployments/experiments/{id}/rollback is AGENT_PUBLISH (authz.py:278), yet canary.rollback_experiment (canary.py:136-191) only swaps an already-published baseline back to active: it is the incident-response brake, and it is gated harder than the thing it protects against. POST /bot-deployments/{id}/rollback, which actually changes what production says, is BOT_WRITE (authz.py:279). The result is that an on-call responder provisioned to stop a bad rollout needs the publish permission, while an author can silence an agent and a BOT_WRITE holder can change its script.

**Trigger** — An AGENT_EDIT holder POSTs /agent-studio/cards/kaia-v2-4/archive: inbound traffic to that card has no active deployment. Conversely, a responder holding BOT_WRITE watching a bad 40% canary gets 403 on /bot-deployments/experiments/{id}/rollback.

**Fix** — Archive of a card with an active production deployment should require AGENT_PUBLISH (or refuse and require an explicit undeploy step). Experiment rollback should drop to BOT_WRITE or to a new incident permission — a route whose only effect is 'move traffic back to the version that was already approved' must be reachable by whoever is on call.

#### `AUTHZ-5` — POST /a2a/partners overwrites another tenant's partner row: ON CONFLICT (id) with no tenant predicate

MINOR · security · DOWNGRADED

**Files** — `backend/agent_core/a2a.py:220`, `backend/agent_core/a2a.py:238`, `backend/tenant_context.py:75`

**Mechanism** — upsert_partner takes `id` from the caller's payload (a2a.py:221) and inserts with ON CONFLICT (id) DO UPDATE (a2a.py:238-245). The conflict target is the primary key, not (tenant_id, id), and tenant_id is deliberately absent from the SET list — so a conflicting row keeps its original tenant while name, card_url, cert_fingerprint, cert_dn, allowed_skills and status are all replaced by the caller's values. Every sibling write in this codebase guards the row (`WHERE ... AND tenant_id = :t`, e.g. connectors/persist.py:91, mcp_http/auth.py:161, db.py:232); this one does not. The read path list_partners IS tenant-scoped (a2a.py:213), so the victim tenant sees its partner's certificate fingerprint and allowed_skills silently changed and the attacker sees nothing in the response.

**Trigger** — Actor with INTEGRATIONS_WRITE in tenant B posts {"id": "<tenant A partner id>", "certDn": "CN=attacker", "allowedSkills": ["..."]} to POST /a2a/partners. Tenant A's partner now authenticates with the attacker's fingerprint. Latent only because nothing binds a per-request tenant today (tenant_context.py:75-77, no RLS policy exists in backend/), so a single process serves one tenant.

**Fix** — Change the conflict target to a (tenant_id, id) unique constraint, or refuse a caller-supplied `id` that does not already belong to db.current_tenant(); and add tenant_id to the DO UPDATE guard the way connectors/persist.py:91 does.

#### `AUTHZ-8` — POST /mcp/keys/{key_id}/revoke reports success for a key it did not revoke

MINOR · degradation-lie · DOWNGRADED

**Files** — `backend/agent_core/mcp_http/auth.py:158`, `backend/main.py:2620`, `backend/main.py:2626`

**Mechanism** — revoke_key (auth.py:158-163) runs UPDATE mcp_keys SET revoked_at = now() WHERE id = :id AND tenant_id = :t and returns None without inspecting rowcount. The route (main.py:2622-2628) discards the return and returns a hardcoded {"ok": True}. A typo'd key id, an id from another tenant, or an already-deleted row all produce the same 200 {"ok": true} as a real revocation. Its sibling rotate_key does check (auth.py:174-175 raises KeyError -> 404), and delete_provider_binding does too (main.py:5528-5529 -> 404), so the codebase's own convention is to report a no-op. Revocation is the one operation an operator performs under time pressure, in response to a leaked key.

**Trigger** — POST /mcp/keys/mcpk-typo/revoke -> 200 {"ok": true}. The console shows the action succeeded; GET /mcp/keys still lists the real key as un-revoked, but nothing draws attention to it, and the leaked key keeps working.

**Fix** — Capture .rowcount from the UPDATE and raise KeyError('mcp_key_not_found') when it is 0, so _handle_write maps it to 404 — the same shape rotate_key already uses two functions below.

---

## Code organization, duplication, dead code, test gaps

13 findings — 1 MAJOR, 6 MINOR, 6 trivial; 3 recorded closed in `raw/closures.json`.

What this slice is, end to end, is in `raw/audit-org.json` (`summary`, `endpoints`, `runtime_consumers`, `checked_fine`).

#### `ORG-04` — One handoff allowlist, two implementations: bot_tools' is hardened, voice/tools' is a copy that lost both hardenings

**MAJOR** · code-organization · prior: Established fact: "The voice handoff allowlist reads the Python-constant card via card_for() (voice/tools.py:2783-2788), NOT the published card; a non-first-party bot_id yields allowlist=None = unrestricted" — this finding is the organizational cause (a duplicated control where only one copy was fixed), not a restatement of the symptom. · **closed** in `RESTATUS-2026-09-09` (pass 3)

**Files** — `backend/bot_tools.py:398-427`, `backend/voice/tools.py:2783-2796`, `backend/agent_core/tools/domain.py:1026-1031`, `backend/agent_core/cards/defaults.py:334-346`, `backend/agent_core/cards/handoff_policy.py:11-30`, `backend/voice/bot.py:406-410`, `backend/voice/bot.py:444-447`, `backend/voice_sandbox.py:180-215`, `backend/main.py:3482`

**Mechanism** — `bot_tools._handoff_allowlist` (:400-429) resolves live card → built-in card → **deny**, and its own docstring (:402-412) records why: resolving from env `BOT_ID` enforced the wrong clone's targets, and returning `None` made `domain.handoff_to_agent` treat the call as unrestricted, so "the check therefore disabled itself at precisely the moment identity was misconfigured". `voice/tools.py:2782-2789` is the same control re-implemented for the voice runtime and it does neither: it reads only `card_for(bot_id)` — the Python constant in defaults.py:342, not the published card — and on `KeyError` sets `allowlist = None`, the unrestricted sentinel. A tenant clone or any non-first-party bot therefore has no handoff restriction on voice while the identical conversation over WhatsApp is restricted. The message-channel fix was applied to one of the two copies and the other was never located, which is what having two copies buys.

**Trigger** — Clone a first-party card in the Studio, deploy it, and place a voice call: `card_for(clone_bot_id)` raises KeyError, `allowlist` is `None`, and `domain.handoff_to_agent` (domain.py:1027) transfers the live conversation to any bot id the model names.

**Fix** — Extract `_handoff_allowlist` into `agent_core/tools/handoff_allowlist.py` (live card via `parse_card` → `card_for` → `set()`), call it from both `bot_tools.py:432` and `voice/tools.py:2782`, and pass the session's card into the voice handler the way `ToolContext.agent_card` already carries it on the message side. Add one test asserting both runtimes deny an unknown bot id.

#### `ORG-01` — The response_model guard stops at the literal prefix /agent-studio, leaving 41 studio routes with no declared wire shape

MINOR · test-gap · DOWNGRADED

**Files** — `backend/tests/test_agent_studio_response_models.py:53`, `backend/tests/test_agent_studio_response_models.py:59`, `backend/tests/test_agent_studio_response_models.py:64`, `backend/main.py:2527`, `backend/main.py:2573`, `backend/main.py:2599`, `backend/main.py:2740`, `backend/main.py:2781`, `backend/main.py:2890`, `backend/main.py:2928`, `backend/main.py:3205`, `backend/main.py:3468`, `backend/main.py:3482`, `backend/main.py:5233`, `backend/main.py:5463 (counter-example: declares response_model)`, `backend/main.py:5407 (counter-example)`

**Mechanism** — `_studio_routes()` filters `route.path.startswith("/agent-studio")` (test_agent_studio_response_models.py:53) and then asserts `len(routes) == 26` and `route.response_model is not None` (:59, :64). Every other endpoint the Studio's fifteen tabs call sits under a different prefix — /connectors, /vault, /mcp, /a2a, /eval, /gateway, /roles, /bot-deployments/experiments, /sandbox/tuning, /voice/sandbox, /providers/bindings, /outbound/card-vocabulary — and none of them declares a response_model. Their TypeScript types (api/agent-studio.ts:357 EvalSuite[], :419 EvalReport[], :774 RolesCatalog, :855 DeploymentExperiment[], api/providers.ts:210 ProviderBinding[]) are hand-written against nothing. The docstring at test_agent_studio_response_models.py:1-6 states exactly why this matters — FastAPI silently filters undeclared fields — and the guard's own coverage assertion (a hardcoded 26) is what conceals the gap: adding a route under any other prefix does not move the number.

**Trigger** — Add or rename a key in `agent_core/canary.list_experiments`'s row, or in `list_eval_suites`, and the Ship or Evals tab renders `undefined` with a green suite; nothing in the backend suite fails, and `tsc` still compiles because the TS type was hand-written to match the old shape.

**Fix** — Replace the prefix filter with the route-registry pattern authz already uses (`main.py:533` + `authz.ROUTE_PERMISSIONS`): a table of every route path plus its declared response shape, an `assert_registry_covers`-style test over `app.routes`, and an explicit exempt list for the four streaming/binary routes (`/agent-studio/skills/{id}/export`, `/tts/preview`, `/billing/export.csv`, `/interactions/{id}/export`). TARGET-ARCHITECTURE.md:272 already names this as the intended mechanism ("the same table shape, added after 178 → 0").

#### `ORG-02` — The Evals tab paints the same status word two different colours in one screen, because the gate-verdict module it exists to prevent has no importers

MINOR · code-organization · DOWNGRADED

**Files** — `Habibi/src/lib/gate-status.ts:23-51`, `Habibi/src/components/sandbox/EvalCockpit.tsx:68`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:47-53`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:451-453`, `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:29`, `backend/agent_core/eval/harness.py:27`, `backend/agent_core/eval/run.py:92-95`, `backend/agent_core/cards/compile.py:683`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:132-134`

**Mechanism** — `lib/gate-status.ts` was written to be the single mapping for `GateStatus = pass|fail|warn|skipped` (compile.py:45); its docstring names the two exact bugs it fixes, one of them "the Evals tab treated any non-'pass' report as danger, so a `skipped` suite rendered red directly beneath the tab's own copy saying 'Skipped is honest'". Only `partitionGates` is ever imported (ChangeLogTab.tsx:29). `GATE_TONE`, `GATE_LABEL`, `gateTone`, `isGateFailure`, `isGateWarning` have zero importers, and six surfaces re-derive the mapping by hand. AgentCardPanels.tsx:451-453 renders `EvalReportsList` (which uses the corrected local `reportTone`, :47-53, colouring `skipped` neutral) two lines above `<EvalCockpit />`, whose line 68 is verbatim the bug: `report.status === "pass" ? "success" : "danger"`. A suite the scheduler skipped (compile.py:965-968) is therefore neutral in the upper list and red in the lower one, on the same tab, for the same report. AgentCardPanels.tsx:133 has the opposite fallback — `fail ? danger : warn ? warning : success` — so any G6 status outside {fail, warn} is painted green, which is the one thing CONTEXT.md:39 says a gate must never do.

**Trigger** — Open the Evals tab for a card whose `card.eval.require` omits a suite the scheduler ran: `list_eval_suites`/`/eval/reports` returns `status: "skipped"`, EvalReportsList shows a neutral lozenge and EvalCockpit shows a red one, three lines apart.

**Fix** — Import `gateTone` from `@/lib/gate-status` at all six sites (EvalCockpit.tsx:68, AgentCardPanels.tsx:47-53/133/1027-1036, ShipTab.tsx:140-148, agent-studio.index.tsx:115-118) and delete the local maps; give `gateTone`'s unknown-value fallback a test. Then delete the now-duplicated `CompileReportList` body from ShipTab.tsx:135-153 and import the exported `CompileReportList` (AgentCardPanels.tsx:1016) that PublishDialog.tsx:14 already uses — the two gate lists are character-for-character identical.

#### `ORG-03` — /prompt-studio's lazy route component is unreachable dead code behind an unconditional redirect, and it hardcodes the entry bot id the backend reads from env

MINOR · code-organization

**Files** — `Habibi/src/routes/prompt-studio.tsx:13-22`, `Habibi/src/routes/prompt-studio.lazy.tsx:103-109`, `Habibi/src/routes/agent-studio.$botId.lazy.tsx:20`, `Habibi/src/components/bot-analytics/UnansweredTable.tsx:80-84`, `backend/db_prompt_studio.py:1441`

**Mechanism** — `prompt-studio.tsx:13-22` has a `beforeLoad` whose every branch ends in `throw redirect(...)` — to `/agent-studio/$botId` when `unansweredId` is present, to `/agent-studio` otherwise. TanStack runs `beforeLoad` before the lazy component loads, so `prompt-studio.lazy.tsx:103-109` (`createLazyFileRoute("/prompt-studio")` with `component: PromptStudioRedirected`) can never mount, and the `head()` block at prompt-studio.tsx:23-33 can never apply. Both dead sites hardcode `botId: "kaia-v2-4"` (prompt-studio.tsx:17, prompt-studio.lazy.tsx:107), which the backend resolves from `os.getenv("BOT_ID")` (routing.py:44, db_prompt_studio.py:1441). The live editor path is `agent-studio.$botId.lazy.tsx:20`, which passes the URL param. Both dead sites also give a reader two plausible entry points into a 1,660-line file.

**Trigger** — A deployment that sets `BOT_ID` to anything but `kaia-v2-4`: the surviving live redirect at prompt-studio.tsx:17 still sends an operator arriving from a KB-gap link to `/agent-studio/kaia-v2-4`, a card that need not exist.

**Fix** — Delete `prompt-studio.lazy.tsx:103-109` and the `head()` at prompt-studio.tsx:23-33 (the meta belongs on `agent-studio.tsx:5-15`, which already carries it). Replace the hardcoded `"kaia-v2-4"` at prompt-studio.tsx:17 with the entry bot id the fleet index already fetches (`AgentCardSummary.reachability === "entry"` from GET /agent-studio/cards), or redirect to `/agent-studio` and let the fleet resolve it.

#### `ORG-07` — mesh_roles.json carries 43 lines of per-role tool lists that nothing reads — a second, silently divergent grant vocabulary

MINOR · code-organization · prior: Established fact: "backend/voice/mesh.py active_role is written and never read to change tools or prompt." This adds the specific dead payload (the tool lists) and the misleading docstring that invites edits to it.

**Files** — `backend/voice/mesh_roles.json:6-13`, `backend/voice/mesh_roles.json:17-28`, `backend/voice/mesh_roles.json:33-41`, `backend/voice/mesh.py:5-7`, `backend/voice/mesh.py:29-33`, `backend/voice/mesh.py:56-67`, `backend/voice/mesh.py:89`, `backend/voice/mesh_bus.py:17`, `backend/voice/mesh_bus.py:94`, `backend/tests/test_mesh_roles_json.py:16-18`, `backend/agent_core/tools/grant.py:121-123`

**Mechanism** — `mesh_roles.json` declares `tools[]` for `intake` (5), `collections` (10) and `insurance` (6). `voice/mesh.py:58-66` validates every entry is a non-empty string and raises `mesh_role_invalid_tools` on a bad one, then stores them on `MeshRole.tools` (:33). No code in `backend/` reads `MeshRole.tools`: the only mesh consumers are `activate_role` (voice/tools.py:2805, voice/bot.py:1528) and `release_session`. The file's own header comment (mesh.py:5-7) calls it "the shape a future Agent Card subset uses" and says "Adding a specialist is an edit to that file, not a code change" — which reads as a live grant surface to anyone changing tool access, and is not one. The Tool Grant is `card ∪ packs ∪ connectors ∪ always-on` (grant.py:121-123, CONTEXT.md:30-32); this file is a fourth list that looks like a fifth input and is not consulted.

**Trigger** — An operator removes `apply_goodwill` from the `collections` role in mesh_roles.json to restrict it, redeploys, and the tool remains fully callable — the change is validated on load, stored, and ignored.

**Fix** — Delete `tools` from `mesh_roles.json` and from `MeshRole` (mesh.py:33) plus its validation (mesh.py:58-64), leaving `name`/`description`, and update the module docstring at mesh.py:5-7 so it no longer advertises a grant surface. If the mesh is ever meant to narrow the grant, it must go through `ToolGrant`, not a parallel JSON.

#### `ORG-09` — All fifteen Studio tabs have zero rendering tests; the one studio test greps source text

MINOR · test-gap · DOWNGRADED · **closed** in `a33efbd` (pass 7)

**Files** — `Habibi/src/routes/agent-studio.skills.index.test.ts:8-14`, `Habibi/vitest.config.ts:20-30`, `Habibi/src/routes/prompt-studio.lazy.tsx:1109-1133`, `Habibi/src/routes/prompt-studio.lazy.tsx:164-171`, `Habibi/src/routes/prompt-studio.lazy.tsx:1145-1158`, `Habibi/src/components/prompt-studio/PublishDialog.tsx:84-96`, `Habibi/src/lib/agent-roster.test.ts:1-11`

**Mechanism** — `git ls-files src/**/*.test.ts*` returns nineteen files; exactly one is in the studio slice — `agent-studio.skills.index.test.ts`, which `readFileSync`s the sibling `.tsx` and asserts it contains the strings `clonePending` and `AlertDialog` (:11-13). Not one of the fifteen tabs at prompt-studio.lazy.tsx:1109-1133 is rendered by any test. Untested logic includes `fingerprint`/`stableStringify` dirty detection (:162-171, :493-527) whose docstring records a PATCH loop that fed itself; `publishBaseline` (:1145-1160) whose docstring records a diff that reported "+0 · −0" for a publish introducing the entire prompt; the publish path (:940-991); and `PublishDialog`'s change detection (:88-96). `vitest.config.ts:24-30` already documents the jsdom opt-in (`// @vitest-environment jsdom` + `@/test/jsdom`) and commit 50ede50 established that the suite can render, so the capability exists and is unused here.

**Trigger** — Any refactor of the shell's hydration or autosave effects (prompt-studio.lazy.tsx:355-418, 616-734) ships with a green suite; the failure surfaces as an autosave loop or a permanently-unsaved chip in front of an operator.

**Fix** — Three jsdom suites, highest value first: (1) `prompt-studio.dirty.test.tsx` — mount `PromptStudioPage` with a mocked query client, assert `dirty` is false immediately after a save round-trip with a server-shaped row (the regression the fingerprint docstring describes); (2) `AgentCardPanels.evals.test.tsx` — render `EvalsTab` with a `skipped` report and assert both lozenges agree (locks ORG-02); (3) `PublishDialog.test.tsx` — assert a flow-only and a card-only change each report a non-empty diff. Then extend, rather than add, coverage tab by tab.

#### `ORG-12` — The route vocabulary is three-way split and CONTEXT.md's glossary contradicts the API's own primary noun

MINOR · doc-vs-code

**Files** — `CONTEXT.md:38-39`, `CONTEXT.md:56-58`, `backend/agent_core/cards/compile.py:45`, `backend/agent_core/cards/compile.py:965-968`, `backend/agent_core/cards/schema.py:190`, `backend/main.py:5279`, `audit-reports/TARGET-ARCHITECTURE.md:259`

**Mechanism** — Three names for one thing appear on three route families — `/prompt-versions` (the Mouth), `/bot-deployments` (the Deployment), `/agent-studio` (the Card) — with `bot_id` as the identifier throughout. §6.9 (TARGET-ARCHITECTURE.md:259) refuses to rename any of that, correctly, because those strings are DB-keyed. Two drifts are *not* DB-keyed and are therefore in scope. First, CONTEXT.md:39 defines a Gate as having "three honest outcomes: pass, block, or skip" while `compile.py:45` defines `GateStatus = Literal["pass", "fail", "warn", "skipped"]` — four outcomes, two of them spelled differently, and `warn` (which does not block a publish) has no glossary entry at all; ORG-02 shows six surfaces guessing at that missing fourth case. Second, CONTEXT.md:58 lists `objective` under Mission's _Avoid_, while `objective` is the field name on the card (`schema.py:190`), the key in the vocabulary endpoint (`main.py:5280`), and the word the Outbound tab shows the operator. Separately, `prompt-studio.lazy.tsx` and `api/prompt-studio.ts` are file names for a feature the router, the nav and the docs all call Agent Studio — a pure file rename with no wire or DB consequence.

**Trigger** — Not a runtime defect: an agent following the glossary writes `blocked` for a failing gate, or renames a card field to `mission`, and breaks `extra="forbid"` validation on a published card.

**Fix** — Two doc edits and one file rename, none of them a migration: (a) amend CONTEXT.md:39 to the four real outcomes and define `warn` as "ran, had something to say, did not block"; (b) amend CONTEXT.md:58 to drop `objective` from _Avoid_ and record that `objective` is the card field while Mission is the concept, or rename the glossary entry to Objective; (c) rename `routes/prompt-studio.lazy.tsx` → `routes/agent-studio.$botId.page.tsx`, `api/prompt-studio.ts` → `api/mouth-versions.ts`, `components/prompt-studio/` → `components/agent-studio/`, leaving every URL, DB column and HTTP path untouched, which is exactly the latitude §6.9 grants ("fix names only where a file is already being rewritten for another reason") when ORG-11's split rewrites those files anyway.

#### `ORG-06` — Two reachability label vocabularies, and the comment introducing the second one says they are the same

trivial · code-organization · DOWNGRADED

**Files** — `Habibi/src/routes/agent-studio.index.tsx:55-90`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:694-701`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:743-758`

**Mechanism** — `agent-studio.index.tsx:55-85` defines `ROUTING`, mapping the four backend states plus `archived` to operator-facing labels: "takes inbound", "via handoff", "direct only", "unreachable", "archived", each with its own help sentence. `AgentCardPanels.tsx:744-757` defines a second map, `ROUTE_TONE` + `ROUTE_HELP`, over the same five states — with different help text and no labels at all, so line 696-698 renders the raw enum word (`entry`, `handoff`, `direct`) as the chip. The comment at AgentCardPanels.tsx:743 asserts "Same vocabulary the fleet index uses, so one word does not mean two things" — the fleet says "takes inbound" and the Agent graph tab, one click away, says "entry" for the same card. The fleet's `routing()` helper (:88-90) also has an unknown-value fallback that the panel's `?? "neutral"` does not match.

**Trigger** — Open the fleet index, note a card badged "direct only", click into it, open the Agent graph tab: the same card is badged "direct" with a differently worded tooltip.

**Fix** — Move `ROUTING` out of `agent-studio.index.tsx` into `Habibi/src/lib/reachability.ts` alongside its `routing()` fallback, export `label`/`tone`/`help`, import it in `AgentCardPanels.tsx:694-698`, and delete `ROUTE_TONE`/`ROUTE_HELP`. This is the same shape as the `gate-status.ts` fix in ORG-02 and should land with it.

#### `ORG-08` — db_prompt_studio.py is three modules: prompt studio, the TTS voice catalog, and bot deployments

trivial · code-organization · DOWNGRADED

**Files** — `backend/db_prompt_studio.py:1-13`, `backend/db_prompt_studio.py:1308-1355`, `backend/db_prompt_studio.py:1357`, `backend/db_prompt_studio.py:1435-1441`

**Mechanism** — The module docstring (:1-8) justifies keeping reads and writes together — "seventeen internal write→read edges make splitting them a mistake" — which is a claim about prompt versions, not about the whole file. Lines 860-1356 are the Azure/multi-vendor TTS voice catalog: `list_tts_voices`, `list_tts_voice_catalog`, `get_tts_voice_catalog_entry`, `list_tts_price_tiers`, `tts_catalog_is_populated`, `get_tts_voice_warning`, `_tts_sync_run_row`, `latest_tts_sync_run`, `list_tts_sync_runs` — ~500 lines whose only tie to prompt versions is `resolve_prompt_azure_voice` (:961) and `voice_locale_facts` (:983). Lines 1357-1604 plus 2292-2430 are the deployment table (`list_bot_deployments`, `get_active_deployment`, `get_deployment`, `_map_bot_deployment_row`, `rollback_bot_deployment`) behind its own section banner at :1435-1441. The file already declares its seam with a banner and still holds all three; at 2,430 lines it is the single largest thing an agent must load to change a voice-catalog query.

**Trigger** — Any change to the TTS catalog forces a reader through publish, compile and rollback logic first; the file is above the point where a targeted read is possible.

**Fix** — Split at the two existing banners into `db_tts_catalog.py` (860-1356) and `db_deployments.py` (1357-1604 + 2292-2430), each following the same `_db()` late-binding rule the header documents (:9-13) and each re-exported from `db.py:7382` exactly as now, so no call site changes. The remaining ~860 lines are prompt versions and agent-studio cards, which is what the docstring's seventeen-edge argument actually covers.

#### `ORG-10` — 1,000 lines of studio routes are spliced into main.py in two non-contiguous blocks, and one endpoint calls another endpoint's handler 1,032 lines away

trivial · code-organization · DOWNGRADED

**Files** — `backend/main.py:2202-2203`, `backend/main.py:2229`, `backend/main.py:2241`, `backend/main.py:3234-3235`, `backend/main.py:5407`, `backend/main.py:5463`, `backend/main.py:5488`, `backend/main.py:5534`, `backend/main.py:5557`, `backend/main.py:5569`, `backend/main.py:1588-1616`

**Mechanism** — The Studio's surface is `main.py:2021-2520` and `3003-3520`, separated by 480 lines of connectors/MCP/A2A/eval/gateway/roles that the same tabs also call, with two more of its endpoints stranded at :5409-5556 (`/providers/bindings`, the Bindings tab) and :5559-5581 (`/tts-voices/catalog-*-counts`, the Voice tab) — 2,500 lines from the rest of `/tts-voices`. `/providers/*` serves two unrelated features from one prefix: the Integrations page at :1590-1618 and the studio Bindings tab at :5465-5536. `publish_agent_studio_card` (:2204) calls `publish_prompt_version` (:3236) as a plain function, so a route handler is doubling as an internal service call across a thousand lines. Authz does not obstruct a split — it is one global dependency (:533-539) keyed on the path template — and `test_agent_studio_response_models.py:67-72` already pins the one order-sensitive pair, so the split's only real risk (route order) has a precedent test to extend.

**Trigger** — Not a runtime defect: an agent asked to change a studio endpoint must load a 5,573-line file and cannot find `/providers/bindings` or `/tts-voices/catalog-locale-counts` by proximity to the rest of the tab they serve.

**Fix** — Three `APIRouter`s in `backend/routers/`: `studio_cards` (/agent-studio, /prompt-versions, /flow), `studio_runtime` (/bot-deployments, /sandbox, /voice/sandbox, /providers/bindings, /gateway/canary), `studio_catalog` (/connectors, /vault, /mcp, /a2a, /eval, /tts-voices, /persona-presets), included in that order. Move `publish_prompt_version`'s body into `db_prompt_studio` or a `studio_publish` helper so neither router calls the other's handler. Add the ordered-path snapshot test TARGET-ARCHITECTURE.md:274 already names ("an ordered-list snapshot, not a set") before moving anything, and keep `test_agent_studio_response_models.py:67` green across the move.

#### `ORG-11` — AgentCardPanels.tsx holds six tabs and a hook in 1,047 lines, one of which is a dead one-line passthrough

trivial · code-organization · DOWNGRADED · **closed** in `6089743` (pass 7)

**Files** — `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:73`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:202`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:260`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:576`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:760`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:914`, `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:1045-1047`, `Habibi/src/routes/prompt-studio.lazy.tsx:83`, `Habibi/src/routes/prompt-studio.lazy.tsx:93-100`

**Mechanism** — Six of the fifteen tabs — Tools (:73), Policy (:202), Evals (:260), Agent graph (:576), Skills (:760), Connectors (:914) — share one file, while the other nine each have their own (`ShipTab.tsx`, `BindingsTab.tsx`, `ChangeLogTab.tsx`, `OutboundTab.tsx`, `PromptEditor.tsx`, `PersonaSliders.tsx`, `VoicePanel.tsx`, `GuardrailsPanel.tsx`, and Flow inline). The six inside are the ones that edit the Agent Card, which is a coherent reason for a directory, not for a file: `prompt-studio.lazy.tsx:88-93` already imports them individually, so the bundling buys nothing. The file also exports `useStudioCompile` (:1045-1047), a body of `return useCompileCard(botId);` with zero importers — the shell imports `useCompileCard` directly at prompt-studio.lazy.tsx:84.

**Trigger** — Not a runtime defect: a change to the Connectors tab loads the Evals tab's 200 lines of report plumbing, and the file is the largest single obstacle to the per-tab tests ORG-09 asks for.

**Fix** — Split into `components/prompt-studio/card/{ToolsTab,PolicyTab,EvalsTab,AgentGraphTab,SkillsTab,ConnectorsTab}.tsx` with `NotAuthoredNotice` and `reportTone` moving to a shared `card/shared.tsx` (or, per ORG-02, `reportTone` disappearing into `@/lib/gate-status`). Move `CompileReportList` (:1016) to its own file since PublishDialog and ShipTab both want it. Delete `useStudioCompile` (:1045-1047).

#### `ORG-13` — Two POST routes under /agent-studio/skills survive only because nobody has added POST /agent-studio/skills/{skill_id}

trivial · code-organization

**Files** — `backend/main.py:2296-2305`, `backend/main.py:2309-2310`, `backend/main.py:2439-2440`, `backend/main.py:2472-2473`, `backend/tests/test_agent_studio_response_models.py:67-72`

**Mechanism** — `GET /agent-studio/skills/scripts` (:2297) is declared before `GET /agent-studio/skills/{skill_id}` (:2310) with a comment explaining why, and `test_agent_studio_response_models.py:67-72` pins that one pair by index. `POST /agent-studio/skills/import` (:2440) and `POST /agent-studio/skills/run-script` (:2473) are single-segment POSTs declared *after* the `{skill_id}` block; they work today only because no `POST /agent-studio/skills/{skill_id}` exists. The pinning test checks exactly one pair, so the invariant is documented as "scripts before skill_id" rather than "no static segment may follow its parameterised sibling", which is the rule that actually holds.

**Trigger** — Someone adds `POST /agent-studio/skills/{skill_id}` (a natural place for a "run this skill" action) anywhere before line 2440; skill import and script execution both start 404ing or, worse, dispatch to the new handler with `skill_id="import"`.

**Fix** — Move `/import` and `/run-script` above the `{skill_id}` group beside `/scripts`, and generalise the test: for every path in `_studio_routes()`, assert no static-segment route is declared after a parameterised route it would be shadowed by, for the same method. That generalised assertion is also what makes the ORG-10 router split safe.

#### `ORG-14` — db.latest_tts_sync_run is defined, re-exported and unreachable

trivial · code-organization

**Files** — `backend/db_prompt_studio.py:1308-1326`, `backend/db.py:7402`, `backend/main.py:3041-3044`, `backend/db_prompt_studio.py:1329-1355`

**Mechanism** — `latest_tts_sync_run()` (db_prompt_studio.py:1308) is re-exported through `db.py:7402` and has no caller in `backend/` — not main.py, not the voice tree, not tests. The endpoint that would use it, `GET /tts-voices/catalog/sync-runs` (main.py:3043), calls `list_tts_sync_runs` (:1329) instead. It shares `_tts_sync_run_row` (:1283) with the live function, so it will keep compiling and keep looking maintained.

**Trigger** — Not a runtime defect: it is 21 lines of query that a reader must classify before concluding it is unreachable.

**Fix** — Delete `latest_tts_sync_run` (db_prompt_studio.py:1308-1328) and its re-export (db.py:7402); `_tts_sync_run_row` stays for `list_tts_sync_runs`. Fold this into the ORG-08 split.

---

# Cross-cutting inventories

These are not findings and carry no ids: a drift pair, a dependency between two tabs or a contradiction between a doc and the code has no single site to pin one to. They come from the connectedness pass over all 24 slices (`raw/connectedness.json`).

## Double sources of truth (20, of which 10 have already drifted)

Every duplicated vocabulary in this slice that was given a cross-language drift test has held; every one that was not has drifted. Collapsing a pair onto one owner is only half the fix — the test is the half that keeps it collapsed.

### Per-agent tool vocabulary: card `tools.include` vs voice/mesh_roles.json role tool lists  ⚠️ **already drifted**

- `backend/agent_core/cards/defaults.py:55-118 (_COLLECTIONS_TOOLS/_INTAKE_TOOLS/_INSURANCE_TOOLS/_SUPERVISOR_TOOLS) → CardTools.include at defaults.py:148`
- `backend/voice/mesh_roles.json:7-13 (intake), :18-29 (collections), :34-41 (insurance), :46 (supervisor_brief)`

**Risk** — An operator who narrows a role's tools in mesh_roles.json believes they revoked a tool, but the Tool Grant is card ∪ packs ∪ connectors ∪ always-on (backend/agent_core/tools/grant.py:121-123) and nothing in backend/ reads MeshRole.tools (backend/voice/mesh.py:33), so the tool stays fully callable. Drifted today: intake 5 vs 8, collections 10 vs 24, insurance 6 vs 16, supervisor_brief [] vs [add_customer_note].

### Gate/report verdict vocabulary and its colour mapping  ⚠️ **already drifted**

- `backend/agent_core/cards/compile.py:45 GateStatus = Literal["pass","fail","warn","skipped"]`
- `CONTEXT.md:38-39 ("three honest outcomes: pass, block, or skip")`
- `Habibi/src/lib/gate-status.ts:23-30 GATE_TONE/GATE_LABEL (the canonical map; only partitionGates is ever imported)`
- `Habibi/src/api/agent-studio.ts:57 (TS union)`
- `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:1027-1036 (CompileReportList: skipped → neutral)`
- `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:129-131 (G6 lozenge: anything not fail/warn → success)`
- `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:47-53 reportTone`
- `Habibi/src/components/sandbox/EvalCockpit.tsx:68 (status === "pass" ? success : danger)`

**Risk** — The same word is painted three different colours on one screen: AgentCardPanels.tsx:129-131 paints a `skipped` G6 GREEN — the one thing CONTEXT.md:39 says a gate must never do — while EvalCockpit.tsx:68 paints a `skipped` report RED three lines below a neutral one from reportTone.

### Agent tuning presets — browser copy vs server copy  ⚠️ **already drifted**

- `Habibi/src/data/agent-tuning.ts:107, :112-166 AGENT_TUNING_PRESETS + DEFAULT_AGENT_TUNING`
- `backend/agent_core/tuning.py:48-115 PRESET_EMPATHETIC_COLLECTIONS / PRESET_BRISK_VERIFICATION / PRESET_FIRM_LEGAL`
- `backend/main.py:3466 GET /sandbox/tuning/presets → backend/agent_core/tuning.py:158-163 (the endpoint that exists to prevent this; Habibi/src/api/voice-sandbox.ts:67 has no caller)`

**Risk** — The Tuning Studio (Habibi/src/components/sandbox/TuningStudio.tsx:112, :198) serves the browser copy, so "Empathetic-collections" runs interaction.idle_timeout_secs 6.0 — the exact value backend/agent_core/tuning.py:54-62 reverted to 12.0 after call VS-6B252E0479, where the bot talked over the caller — and Promote writes it into a production deployment. Brisk-verification idle 5 vs 10, frequency_penalty 0.3 vs 0.1; Firm-legal idle 8 vs 15, frequency_penalty 0.5 vs 0.4, tts style "empathetic" vs "serious".

### Handoff allowlist — two implementations of one control  ⚠️ **already drifted**

- `backend/bot_tools.py:400-429 _handoff_allowlist (live card → built-in card → deny, with a docstring recording both fixes)`
- `backend/voice/tools.py:2783-2788 (built-in card only; KeyError → allowlist = None)`
- `backend/agent_core/tools/domain.py:1027 (the shared consumer: None means unrestricted)`

**Risk** — The message-channel copy was hardened and the voice twin was never located, so the identical conversation is restricted on WhatsApp and unrestricted on the phone: a clone bot id raises KeyError in card_for, allowlist becomes None, and voice handoff_to_agent transfers a live borrower to any bot in the tenant.

### Reachability label vocabulary  ⚠️ **already drifted**

- `Habibi/src/routes/agent-studio.index.tsx:55-85 ROUTING (labels + per-state help)`
- `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:744-757 ROUTE_TONE + ROUTE_HELP (no labels; :694-698 renders the raw enum)`
- `backend/agent_core/cards/routing.py:1-25 (the backend definition of the four states)`

**Risk** — One card is badged "direct only" on the fleet index and "direct" one click later in the Agent graph tab, with differently worded tooltips — under a comment at AgentCardPanels.tsx:743 asserting the two use the same vocabulary. The fleet's routing() helper also has an unknown-value fallback (:88-90) the panel's `?? "neutral"` does not match.

### Seeded persona/prompt text — four copies, two repair migrations that reach only one of them  ⚠️ **already drifted**

- `backend/alembic/versions/20260722_0018_prompt_studio_schema_seed.py:36-57 (EMPATHETIC/FIRM/COMPLIANCE/UPSELL prompts, seeded into prompt_versions at :148-158)`
- `backend/seed_postgres.py:918-940 (_emp_prompt et al., upserted on every run)`
- `Habibi/src/data/prompt-studio-seed.ts:131-152 (the mock copies)`
- `backend/sql/09_bot_config.sql:376 (persona_presets), repaired by backend/alembic/versions/20260819_0084_persona_presets_crm_free.py:83 and 20260825_0101_persona_presets_drop_redundant_disclosure.py:69`

**Risk** — Migration 0018's copies still carry {customer_name}/{account_no}/{overdue_amount}/{due_date} plus "Always disclose that the call is recorded", while the other three are CRM-free. Both repair migrations loop over persona_presets only, so a long-lived database that replayed 0018 serves a published Collections prompt whose lines 2 and 3 backend/prompt_render.py:114 deletes before the model sees them, and whose surviving disclosure line duplicates the one backend/agent_core/prompt.py:80-86 already injects.

### Rollout configuration — card.experiment vs the deployment_experiments row vs the publish request  ⚠️ **already drifted**

- `backend/agent_core/cards/schema.py:365 card.experiment (traffic_pct / shadow / auto_rollback)`
- `backend/sql/18_phase5.sql:13-18 deployment_experiments columns, written at backend/agent_core/canary.py:116-133`
- `backend/schemas.py:2409-2410 PromptVersionPublishRequest.{traffic_pct,shadow,auto_rollback}`
- `backend/db_prompt_studio.py:1889-1891 (card fallback for pct and triggers) and :1940-1946 (fold back onto the card)`

**Risk** — publish_prompt_version derives pct and triggers from the card when the request omits them but has no such fallback for `shadow` (backend/db_prompt_studio.py:1827 default False), then writes `"shadow": bool(shadow)` back onto the card at :1943 — so an authored experiment.shadow: true is silently rewritten to false on the version row and in the change-log digest by any publish that does not resend it.

### legacyShip vs card.experiment — two Ship states behind one tab  ⚠️ **already drifted**

- `Habibi/src/routes/prompt-studio.lazy.tsx:459-467 legacyShipBaseline and :256 legacyShipEdit (card-less bots)`
- `Habibi/src/routes/prompt-studio.lazy.tsx:468-476 `ship` derived from effectiveCard.experiment (authored cards)`
- `Habibi/src/routes/prompt-studio.lazy.tsx:477-490 setShip, which writes to one or the other`

**Risk** — legacyShipBaseline selects the live experiment with `e.status === "active"` (:460), but backend/sql/18_phase5.sql:13 constrains status to ('running','rolled_back','promoted') — so the branch never matches and every card-less bot's Ship tab shows a fabricated 100% / no shadow / no triggers, which prompt-studio.lazy.tsx:1155 then feeds to the publish dialog as the rollout baseline.

### "Was the recording disclosure made" — four detectors  ⚠️ **already drifted**

- `backend/agent_core/guardrails.py:30-56 mentions_recording_disclosure (the canonical regex)`
- `backend/bot_runtime.py:258-266 (WhatsApp's own substring markers)`
- `backend/prompt_lint.py:140 (the lint's server-side check)`
- `Habibi/src/api/prompt-studio.ts:779 (the mock lint's looser 'record' substring)`

**Risk** — The three non-canonical copies disagree with the regex in both directions: WhatsApp files an RBI recording-disclosure violation on every bot turn while its own prompt forbids the disclosure (GUARDRAILS-1), and mock mode gives a clean bill of health for the exact defects the real lint exists to catch (PROMPT-12).

### Policy engine vocabulary — six keys, three declarations  ⚠️ **already drifted**

- `backend/agent_core/cards/schema.py:70-77 REQUIRED_POLICY_KEYS and :58-68 LOCKED_POLICY_ENGINES / LOCKED_MOUTH_TOOLS`
- `Habibi/src/api/agent-card.ts:110-125 LOCKED_POLICY_ENGINES + REQUIRED_POLICY_KEYS`
- `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:55-62 POLICY_ENGINES (a local restatement; the file imports REQUIRED_POLICY_KEYS at :26 without using it)`

**Risk** — The local restatement adds a `tool` column the shared constant does not have, and two of its four named tools (recommend_treatment, evaluate_live_qa) are explicitly NOT catalog tools per backend/agent_core/cards/schema.py:65-68 LOCKED_MOUTH_TOOLS — so the Policy tab tells an operator the mouth can call two tools that exist in no catalog or call path.

### Mesh role name vs card identity.slug (the comment at defaults.py:45 asserts they match)

- `backend/agent_core/cards/defaults.py:46-51 BOT_TO_MESH_ROLE`
- `backend/agent_core/cards/defaults.py:161, :282, :302, :321 (identity.slug on the four first-party cards)`
- `backend/voice/mesh_roles.json:5, :16, :32, :44 (role names)`

**Risk** — The voice handoff flips the mesh role by looking the TARGET bot id up in the Python dict (backend/voice/tools.py:2800-2806), so a renamed slug, a fifth card or any clone silently gets no role flip — and backend/agent_core/cards/defaults.py:367 scaffold_card kebab-cases bot_id into slug, which can never equal a mesh role name.

### Mission/objective vocabulary — thirteen keys written out four times

- `backend/flow_graph.py:76-90 OBJECTIVES (declared owner)`
- `backend/agent_core/cards/schema.py:190-204 Objective Literal ("Mirrors flow_graph.OBJECTIVES")`
- `Habibi/src/api/agent-card.ts:86-101 type Objective`
- `Habibi/src/api/outbound.ts:188-201 MOCK_MISSIONS.available`

**Risk** — schema.Objective is what extra="forbid" validates a published card against and what G-OB2 checks (backend/agent_core/cards/compile.py:301-328), so a key added to the graph but not the Literal fails Pydantic at the publish button naming a value the Outbound dropdown just offered; the only pin is the HTTP surface (backend/tests/test_outbound_card_vocabulary.py:42), not the two Literals.

### RollbackTrigger vocabulary (schema.py / compile.py / canary.py / TypeScript)

- `backend/agent_core/cards/schema.py:41-52 RollbackTrigger + derived ROLLBACK_TRIGGERS`
- `backend/agent_core/cards/compile.py:29, :516 (_ROLLBACK_TRIGGERS alias)`
- `backend/agent_core/canary.py:20, :94 (import)`
- `Habibi/src/api/agent-card.ts:51-58 ROLLBACK_TRIGGERS`

**Risk** — REFUTED as a live risk: the two Python consumers import from schema.py rather than restating it, and backend/tests/test_agent_card_schema_drift.py:89-104 parses the TS source and fails if the two lists disagree. This is the only duplicated vocabulary in the slice with a cross-language pin, and it is the one that has not drifted — the counter-example that makes every other entry here a choice rather than an accident.

### Prompt variable vocabulary and its token regexes

- `backend/prompt_render.py:18-39 KNOWN_VARIABLES / SYSTEM_SAFE_VARIABLES`
- `Habibi/src/data/prompt-studio-seed.ts:21-47 SYSTEM_SAFE_VARIABLES / CRM_VARIABLES / KNOWN_VARIABLES`
- `backend/prompt_render.py:42 TOKEN_RE vs Habibi/src/data/prompt-studio-seed.ts:65 PROMPT_TOKEN_RE`
- `backend/prompt_lint.py:23 flow-token pattern vs Habibi/src/data/prompt-studio-seed.ts:57 FLOW_TOKEN_RE, and the masking rule at backend/prompt_lint.py:89 vs seed.ts:78-81`

**Risk** — The two NAME lists are pinned across languages (backend/tests/test_agent_card_schema_drift.py:125-145) and agree. The three regex/masking copies are not pinned at all, and PROMPT-2 shows the masking rule is subtly wrong identically in both copies — so a Python-only fix would leave the browser still hiding the CRM warning.

### Mouth defaults — server normaliser vs client seed

- `backend/db_prompt_studio.py:43-67 _DEFAULT_PERSONA / _DEFAULT_VOICE / _DEFAULT_GUARDRAILS (used by _prompt_persona at :71, _prompt_voice at :94, guardrails at :132-146)`
- `Habibi/src/data/prompt-studio-seed.ts:186-213 DEFAULT_GUARDRAILS / DEFAULT_VOICE / DEFAULT_PERSONA (traits from PRESETS[0], :160)`

**Risk** — Byte-identical today (traits 82/40/55/60/20, English + Hindi fallback, priya/en-IN-AartiNeural/1.0/0/62/320, maxTurns 20, maxSeconds 480) and guarded by no test. When they diverge, the server normalises the row on read while the client seeds the editor, so the operator sees one value and the runtime uses another — the same shape as SHELL-1's permanent "unsaved" chip.

### Eval suite kind vocabulary (SQL CHECK / Pydantic Literal / TS union / UI list)

- `backend/sql/14_agent_factory.sql:11 CHECK (kind IN ('regression','capability','redteam','twin','outbound'))`
- `backend/agent_core/cards/schema.py:21 EvalRequire Literal`
- `Habibi/src/api/agent-card.ts:44 EvalRequire`
- `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:252-258 EVAL_REQUIRE (the checkboxes)`

**Risk** — Membership agrees, but the gate layer does not: backend/agent_core/cards/compile.py:716-722 builds gates for regression, redteam, twin and outbound only, so "Capability" is a fifth member the UI offers, the DB accepts and no gate can ever consult — a vocabulary that is consistent in spelling and inconsistent in meaning.

### SkillPack allowed-tools vs the card's tool grant

- `backend/agent_core/skills/packs/*/SKILL.md `allowed-tools` → SkillPack.allowed_tools (backend/agent_core/skills/pack.py:144-155)`
- `backend/agent_core/cards/schema.py:114 CardTools.include (+ locked)`
- `backend/agent_core/cards/compile.py:733-751 G9 (allowed_tools ⊆ include ∪ locked ∪ PLATFORM_SKILL_TOOLS)`
- `backend/agent_core/skills/intersect.py:107-114 (the runtime intersection, applied in the other direction)`

**Risk** — The two lists are coupled only at publish. After publish, re-signing a pack with a new tool changes what the mouth may call with no publish and no change-log entry, because backend/agent_core/skills/persist.py:689 resolves packs by slug and ignores skills[].version/pin (backend/agent_core/cards/schema.py:102-107).

### Change-log verb vocabulary

- `backend/agent_core/change_log.py:42-45 PUBLISH/ROLLBACK/ARCHIVE/RESTORE`
- `Habibi/src/components/prompt-studio/ChangeLogTab.tsx:44-56 ACTION_LABEL + ACTION_TONE`
- `Habibi/src/lib/agent-roster.ts:152-157 CHANGE_VERBS`

**Risk** — All three maps carry the four verbs today, and the only guard (backend/tests/test_agent_change_log.py:138-147) asserts over a Python set and cannot see either TypeScript map. The prose has already drifted from the maps: both empty states (ChangeLogTab.tsx:88, :219) enumerate three verbs and drop "restored", the omission the file header says was already fixed.

### First-party Agent Cards: Python constants vs the published DB rows

- `backend/agent_core/cards/defaults.py:157-333 (the four Python card constructors) via card_for at :342`
- `prompt_versions.agent_card, seeded from card_dump at backend/seed_postgres.py:1089, :1115 and thereafter edited through PATCH /agent-studio/cards/{bot_id} (backend/main.py:2138 → backend/db_prompt_studio.py:1774)`

**Risk** — The mouth path reads the DB card (backend/agent_core/skills/runtime.py:218 → intersect.py:85), but three live paths read the Python constant instead — the voice handoff allowlist (backend/voice/tools.py:2786), the mesh role flip (backend/voice/tools.py:2800), and mission.card_for_bot's fallback (backend/mission.py:498-530). They agree only until the first Studio edit; after that a handoff target removed in the Studio is still reachable on the phone. Not marked drifted because confirming it needs the live prompt_versions rows, which this read-only audit cannot open.

### Sandbox hard turn cap — env var vs a literal in the browser

- `backend/sandbox_runtime.py:366 _HARD_MAX_TURNS = max(1, int(os.getenv("SANDBOX_HARD_MAX_TURNS", "3")))`
- `Habibi/src/routes/sandbox.lazy.tsx:465-468 `const hard = 3``

**Risk** — They agree only at the default. Raising SANDBOX_HARD_MAX_TURNS moves the server's cap (backend/sandbox_runtime.py:712, :948 raise sandbox_max_turns) while the header counter keeps counting to 3, so the rehearsal appears to end early with no explanation.

## Studio writes with no runtime reader (38)

Grouped by tab. Each is a W4 decision: connect it, or delete it from schema, type, UI and gate in one commit.

- Persona tab → persona.fallbackLanguages → Habibi/src/components/prompt-studio/PersonaSliders.tsx:228-246 writes the vernacular chips; they never reach AgentTuning.stt.fallback_languages (backend/agent_core/tuning.py:303-308, backend/voice/tuning_apply.py:442-450), so the recogniser cannot switch to a language the prompt promises fluency in. (Read by G15 and the text-channel persona block only.)
- Persona tab → persona.language → PersonaSliders.tsx:204-216; never binds the recogniser on a real call, because every tuning reaching resolve_session_tuning is pre-normalised to stt.language='en-IN' (backend/voice/tuning_apply.py:417, :442-450; backend/agent_core/tuning.py:302).
- Voice tab → voice.styleName ("Speaking style") → Habibi/src/components/prompt-studio/VoicePanel.tsx:683-703; preview ignores it (backend/main.py:3163-3171) and the runtime derives style from warmth (backend/agent_core/tuning.py:397-409).
- Voice tab → voice.pauseMs → Habibi/src/components/prompt-studio/VoiceParamsPanel.tsx:332-343; never reaches a call (backend/agent_core/voice_ssml.py:61-84, backend/azure_speech.py:177-220).
- Guardrails tab → guardrails.maxSeconds → GuardrailsPanel.tsx:157-170; no consumer ends a call — voice uses the fixed backend/voice/bot.py:164 cap and WhatsApp passes elapsed=0 (backend/bot_runtime.py:1280).
- Guardrails tab → guardrails.maxTurns → GuardrailsPanel.tsx:145-156; the sandbox min()s it against a hard 3 (backend/sandbox_runtime.py:366, :712), WhatsApp against 12 (backend/agent_core/guardrails.py:11-15), and the live text loop discards the resulting flag (backend/bot_runtime.py:816-825).
- Guardrails tab → escalateAbuse / escalateLegal → GuardrailsPanel.tsx:14-26; they cannot switch escalation off on voice (backend/voice/crm_sink.py:943-946) or abuse on WhatsApp — the toggles only choose a prompt line (backend/agent_core/prompt.py:88-92).
- Flow tab → graph-level "Tools available from every step" for the four CRM reads → Habibi/src/components/flow/FlowInspector.tsx:499-521; backend/voice/flows_dynamic.py:507-518 strips them from globals.
- Flow tab → non-tts pre_actions on a node → backend/voice/flow_export.py:143-159 drops them, so summarize_context and mesh_activate_insurance are dead under any authored graph (backend/voice/flows.py:657-661).
- Flow tab → "Line spoken on entry" on a Say-verbatim node → FlowInspector.tsx:706-725; backend/voice/flows_dynamic.py:384-407 ignores it on that node type while backend/flow_graph.py:559-573 demands it for listen-first outbound entries.
- Tools tab → the include toggle for verify_identity / capture_call_goal / load_skill / run_skill_script → Habibi/src/components/prompt-studio/AgentCardPanels.tsx:154-181; backend/agent_core/tools/grant.py:88 and backend/agent_core/skills/intersect.py:105-116 re-add all four.
- Tools tab → tools.max_voice_tools → compile-only (backend/agent_core/cards/compile.py:688); backend/agent_core/skills/intersect.py:149 idle_offered_tools applies no cap at runtime.
- Policy tab → all six policy_bindings → AgentCardPanels.tsx:202-242; zero runtime readers (backend/agent_core/cards/schema.py:133-141), and PolicyBinding is Literal["required"] (schema.py:20) so G3's binding half is unfalsifiable (compile.py:598-616).
- Evals tab → card.eval.suite_id ("Pinned suite") → AgentCardPanels.tsx:353-372; backend/agent_core/eval/run.py:14-34 refuses to resolve a bot from it and no runner or gate reads it.
- Evals tab → card.eval.require entry "capability" → AgentCardPanels.tsx:255; backend/agent_core/cards/compile.py:716-722 emits no capability gate at all.
- Agent graph tab → handoffs[].when → AgentCardPanels.tsx:705-712; never rendered into the tool description or prompt (backend/agent_core/tools/catalog.py:577-596).
- Agent graph tab → handoffs[].payload_schema (no editor at all) → backend/agent_core/cards/schema.py:118-123; backend/agent_core/tools/domain.py:1043-1049 passes payload through as an opaque string and G5 does not check it (compile.py:661-678).
- Agent graph / Policy → card.human_gates (no editor at all) → backend/agent_core/cards/schema.py:158-162, written on every first-party card at backend/agent_core/cards/defaults.py:150-151, :171; no reader in backend/voice/**, bot_tools.py, agent_core/tools/** or compile.py — voice writes are gated by the hardcoded backend/voice/tools.py:516-523.
- Skills tab → skills[].version and skills[].pin → AgentCardPanels.tsx:797-806; backend/agent_core/skills/runtime.py:72 → persist.py:689 resolves by slug alone, so an exact pin runs whatever pack is newest.
- Connectors tab → the Bind/Unbind state → AgentCardPanels.tsx:1003; ext.* reaches the Grant (backend/agent_core/skills/intersect.py:117-123) but no Offer (:164, :198) and voice has no ext handler (backend/voice/tools.py:2918-2919).
- Connectors (Integrations) → allowed_env → backend/agent_core/connectors/persist.py:184, displayed and never enforced at dispatch (:238-289), so a sandbox-only connector dispatches in production.
- Outbound tab → objectives[].success and objectives[].partial → OutboundCardEditor.tsx:536-552; backend/call_closer.py:949 uses SUCCESS_BY_OBJECTIVE (:102-112) and `partial` has no reader anywhere.
- Outbound tab → cadences[].escalate_to → OutboundCardEditor.tsx:860-887; backend/cadence.py:600-604 escalation_target has no caller, and the 'escalated' ladder state is never written.
- Outbound tab → cadences[].time_of_day → OutboundCardEditor.tsx:842-858; backend/cadence.py:241-242 always schedules now()+backoff, and no gate reads it.
- Outbound tab → cadences[].per_day → OutboundCardEditor.tsx:808-820; backend/contact_policy.py:90-101 daily_cap never receives the card, so the card cannot lower the cap its own docstring says it lowers.
- Outbound tab → voicemail.max_sec ("Message length") → OutboundCardEditor.tsx:617-625; transported through backend/mission.py:346 and never applied by backend/voice/amd.py:294-306.
- Outbound (schema only, no control) → outbound.concurrency_share → backend/agent_core/cards/schema.py:332-334; the outbound fleet gate has no per-card reservation, acknowledged at backend/tests/test_outbound_card_switches.py:16-19.
- Outbound tab → outbound.direction → OutboundTab.tsx:455 / OutboundCardEditor.tsx:255; backend/agent_core/treatment/enact.py:368 skips its guard exactly when dials is False, and backend/campaigns.py:526-552 never checks it — an inbound-only card is still dialled from.
- Outbound tab → outbound.number_pool → OutboundCardEditor.tsx:277-303; honoured only by campaigns (backend/campaigns.py:539-549), while engine dials (backend/agent_core/treatment/enact.py:386) and cadence retries (backend/cadence.py:429) ignore it.
- Ship tab → experiment.shadow → ShipTab.tsx:169-175; backend/agent_core/canary.py:57-77 pick_deployment_id never reads it, and backend/db_prompt_studio.py:1943 overwrites the card's value with the request default.
- Ship tab → experiment.traffic_pct → ShipTab.tsx:160-167; voice, outbound and WhatsApp all resolve the bundle by env BOT_ID (backend/voice/bot.py:427, backend/mission.py:516, backend/bot_runtime.py:712) rather than through canary.pick_deployment_id, so 100% of calls hit the candidate.
- Bindings tab → binding.voice_ref → BindingsTab.tsx:192, :294; backend/agent_core/providers/factory.py:226-227 only applies it when "voice" is absent, and backend/voice/tuning_apply.py:234-235 always supplies it.
- Bindings tab → the "Language model" slot → BindingsTab.tsx:40-44; no LLM is ever constructed from a binding (backend/voice/bot.py:638-683, backend/voice/llm_pool.py:42).
- Card identity (no tab edits these; they ride every publish) → identity.owner_user_id (backend/agent_core/cards/schema.py:87), identity.data_class and identity.regulator_tags (schema.py:89-90, written on all four cards at backend/agent_core/cards/defaults.py:144-145), identity.channels (schema.py:88, compile-only — both runtimes filter by catalog channel metadata at backend/bot_runtime.py:915 and backend/voice/bot.py:1142), mouth.flow_ref and mouth.languages (schema.py:93-99) — none has a runtime reader.
- Card memory (no tab, no editor) → memory.scopes, memory.compaction.raw_last_n, memory.compaction.summarize_over_budget → backend/agent_core/cards/schema.py:144-155; zero readers, while backend/voice/crm_sink.py:1161-1184 writes a persistent cross-call customer_memory row gated only on an env flag.
- A2A (no tab) → a2a.expose and a2a.skill_ids → backend/agent_core/cards/schema.py:369-373; the served document ignores both (backend/main.py:2711-2717, backend/agent_core/a2a.py:72-105, :116-120), so any active partner can pull any bot's card and gets every attached skill.
- Change log tab → the per-component digests, prevHash, seq, versionId and deploymentId → written at backend/agent_core/change_log.py:197-213 and served (backend/schemas.py:3559), fetched by Habibi/src/components/prompt-studio/ChangeLogTab.tsx:117 and rendered nowhere.
- Sandbox → the four VoiceSandboxStartRequest fields the handler never reads (backend/schemas.py, SANDBOX-15) and POST /voice/sandbox/{id}/tune (backend/main.py:3497 → backend/voice_sandbox.py:238-251), whose writes die with the session and never reach a deployment.

## Runtime behaviour no tab can author (16)

The inverse: real behaviour that needs a code deploy to change, and where an operator would reasonably go looking for it.

- backend/agent_core/cards/routing.py:34-44 (`os.getenv("BOT_ID") or db.DEFAULT_BOT_ID`, backend/.env.example:108) → which card answers every inbound call and message. An operator would expect to set this on the Fleet index, where Habibi/src/routes/agent-studio.index.tsx:59-63 badges exactly one card "takes inbound" — but that chip is a read-only derivation of an env var and no Studio control can move it.
- backend/voice/mesh_roles.json:3-49 + backend/voice/mesh.py:39-67 → the specialist roles and their per-role tool lists. An operator would look in the Tools tab (Habibi/src/components/prompt-studio/AgentCardPanels.tsx:154-181) or the Agent graph; the file has no Studio surface, and editing it changes nothing because MeshRole.tools has no reader.
- backend/voice/bot.py:1519-1541 + backend/voice/flows.py:657-661 → the collections→insurance topic hop, hardcoded as a `mesh_activate_insurance` pre_action on one built-in node. An operator would look in the Flow tab's node inspector (pre-actions) or the Agent graph; neither can author it, and backend/voice/flow_export.py:143-159 drops non-tts pre_actions so it dies entirely under an authored graph.
- backend/agent_core/skills/runtime.py:28-36 INTENT_TO_SKILL → which detected intent auto-loads which skill pack. An operator would look in the Skills tab, whose own copy at AgentCardPanels.tsx:813-815 says "The body loads on load_skill or intent" without ever showing or letting them edit the seven-entry map, so most packs never auto-activate.
- backend/call_closer.py:102-112 SUCCESS_BY_OBJECTIVE (read at :949) → what counts as a successful mission, and therefore every reach/outcome metric and the abandon_rate rollback trigger. An operator would look at Outbound → mission → "Closes the case" (Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:536-552), which is authored, gated, published and ignored.
- backend/voice/tools.py:516-523 _require_customer → the identity gate applied to every voice write regardless of card. An operator would look at card.human_gates (backend/agent_core/cards/schema.py:158-162), which has no editor in the Studio and no enforcer anywhere; "floor" and "both" (supervisor sign-off) are implemented nowhere at all.
- backend/agent_core/prompt.py:74-96 guardrail_rules → the exact sentences of every compliance instruction the model receives, including the recording-disclosure wording and its "never say it again" clause. An operator would look at the Guardrails tab (Habibi/src/components/prompt-studio/GuardrailsPanel.tsx:14-46), which only toggles booleans selecting which fixed sentence is emitted.
- backend/voice/flows.py (the built-in collections script) resolved via backend/agent_core/deployment.py:87-89 → the conversation graph an unauthored version actually runs. An operator would look at the Flow tab, whose empty state (Habibi/src/routes/prompt-studio.lazy.tsx:1486-1500) names it — and GET /flow/built-in cannot even execute in the API container because its import chain requires pipecat (backend/main.py:2068-2081 → backend/voice/flow_export.py:35 → backend/voice/flows.py:28).
- backend/contact_policy.py:487-525 (customer DND, the RBI 08:00-19:00 voice window, preferred hours and allowed days) and :90-101 daily_cap → when a borrower may be contacted at all. An operator would look at the Policy tab's "DND / calling hours" row (AgentCardPanels.tsx:60), which binds nothing, or at Outbound → "Per borrower per day" (OutboundCardEditor.tsx:808-820), which the runtime never receives.
- backend/voice/bot.py:164 `_MAX_CALL_DURATION_SECS = 10 * 60`, enforced by the watchdog at :1743-1768 → the hard ceiling on every voice call. An operator would look at Guardrails → "Max call duration" (GuardrailsPanel.tsx:157-170), a 2-15 minute slider that ends no call on any channel.
- backend/bot_runtime.py:49-50 `_history_limit()` = env BOT_HISTORY_LIMIT (default 16), used at :871 and :891-895 → how much conversation history reaches the model. An operator would look at card.memory.compaction.raw_last_n (backend/agent_core/cards/schema.py:144-155), which has no reader and no gate; backend/agent_core/compaction.py:35-50 likewise always summarises, so summarize_over_budget has no switch either.
- backend/agent_core/reco/config.py:51-62, backend/agent_core/treatment/config.py:50-64, backend/agent_core/authority/config.py:23-36, backend/agent_core/live_qa/config.py:34-48 → whether each locked engine decides or merely shadows, taken from process-wide env vars (backend/.env.example:410, :478, :542, :555). An operator would look at the Policy tab, which asserts all four "decide" (AgentCardPanels.tsx:206-227) and cannot see the flag.
- backend/sandbox_runtime.py:366 SANDBOX_HARD_MAX_TURNS → the rehearsal turn budget that ends every sandbox run at three customer turns. An operator would look at Guardrails → "Max turns per call", set it to 12, and still be unable to rehearse turn 4 onwards — where handoffs, escalations and long negotiations live.
- backend/agent_core/tools/grant.py:88 VOICE_ALWAYS → roughly ten tools every voice call carries regardless of the card, including verify_identity and the flow-control verbs. An operator would look at the Tools tab counter "N on the card" (AgentCardPanels.tsx:126), which omits them and counts two locked engines the table cannot show.
- backend/agent_core/skills/intersect.py:29-48 SKILL_GATED_TOOLS → which catalog tools require an attached pack before the runtime will grant them. No tab lists it; the Tools tab still shows such a tool as on, with a "Remove" button, when no pack carries it (AgentCardPanels.tsx:155).
- backend/voice/flows_dynamic.py:433-462 → runtime special-casing of the node keys confirm_identity, escalate_close and pre_close. An operator would look at the Flow inspector's reserved-key list (Habibi/src/components/flow/FlowInspector.tsx:637-651), which does not include confirm_identity.

## Controls that call nothing, or whose effect is observable nowhere (27)

Each names what a user reasonably expects the control to do.

- Ship tab, "Shadow" checkbox (Habibi/src/components/prompt-studio/ShipTab.tsx:169-175, labelled "Shadow (log split, do not change customer treatment)") — a user reasonably expects the canary to decide and log without speaking to anyone; backend/agent_core/canary.py:57-77 pick_deployment_id branches only on traffic_pct and never reads exp["shadow"], so a 25% shadow canary speaks to one borrower in four.
- Ship tab, traffic slider (ShipTab.tsx:160-167) — expected to be the live dial on a running canary; it only edits card.experiment in the draft (Habibi/src/routes/prompt-studio.lazy.tsx:482-489) and takes effect at the next publish, and voice/outbound then ignore the split entirely (backend/voice/bot.py:427, backend/mission.py:516, backend/bot_runtime.py:712 all resolve by env BOT_ID, never through canary.pick_deployment_id).
- Ship tab, "One-click rollback of active deployment" (ShipTab.tsx:259-266 via prompt-studio.lazy.tsx:1419) — expected to put production back on the previous version; it posts the ACTIVE deployment's own id to a route that rejects exactly that id (backend/db_prompt_studio.py:2330, backend/main.py:3370), so the button always fails.
- Connectors tab, Bind/Unbind (Habibi/src/components/prompt-studio/AgentCardPanels.tsx:1003) — expected to give or take an agent's access to a remote tool; ext.* names enter the Tool Grant (backend/agent_core/skills/intersect.py:117-123) but are excluded from every Offer (intersect.py:164, :198) and voice has no ext dispatcher at all (backend/voice/tools.py:2918-2919), so no model can ever call one.
- Tools tab, Add for the nine flow-control verbs (AgentCardPanels.tsx:154-181 fed from backend/flow_graph.py:773-784) — expected to grant a tool; those names are not catalog tools, so adding one makes G4 fail at publish (backend/agent_core/cards/compile.py:643-647) while the tab's only lozenge still shows G6 green (AgentCardPanels.tsx:129-140).
- Tools tab, the on/off toggle rows for verify_identity, capture_call_goal, load_skill and run_skill_script (AgentCardPanels.tsx:154-181, rows labelled "optional") — expected to remove the tool; backend/agent_core/tools/grant.py:88 VOICE_ALWAYS and backend/agent_core/skills/intersect.py:105-116 add all four back unconditionally.
- Evals tab, "Pinned suite" select (AgentCardPanels.tsx:353-372) — expected to choose which suite gates this card; backend/agent_core/eval/run.py:14-34 documents at length that it will not resolve a bot from a suite id, and no gate reads card.eval.suite_id (compile.py:966-968 matches by kind).
- Evals tab, the "Capability" publish-requirement checkbox (AgentCardPanels.tsx:255) — expected to add a gate; backend/agent_core/cards/compile.py:716-722 builds eval gates for regression, redteam, twin and outbound only, so ticking it produces no gate, not even a skipped one.
- Agent graph tab, the `when` text input on each handoff row (AgentCardPanels.tsx:705-712, under copy at :669-673 calling it "guidance for the model") — expected to steer the model's choice of target; the string is stored on the card and never rendered into any tool description or prompt (backend/agent_core/tools/catalog.py:577-596).
- Outbound tab, the mission "Closes the case" / "Partly worked" outcome pickers (Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:536-552) — expected to define success for this mission; backend/call_closer.py:949 scores against the module-level SUCCESS_BY_OBJECTIVE table (call_closer.py:102-112) and never reads the card.
- Outbound tab, cadence "time of day" select engine/fixed/spread (OutboundCardEditor.tsx:842-858) — expected to spread or pin retry times; backend/cadence.py:241-242 always schedules now() + backoff, and no gate reads the field either.
- Outbound tab, "When the attempts run out" escalate_to select (OutboundCardEditor.tsx:860-887) — expected to hand an exhausted ladder to a human or another bot; backend/cadence.py:600-604 escalation_target has no caller and both exhaustion paths (cadence.py:232-240, :400-410) just stop.
- Outbound tab, voicemail "Message length" (OutboundCardEditor.tsx:617-625) — expected to bound the message; backend/voice/amd.py:294-306 composes and leaves the script without consulting max_sec.
- Guardrails tab, "Max call duration" slider, 120-900s (Habibi/src/components/prompt-studio/GuardrailsPanel.tsx:157-170) — expected to end a long call; nothing ends a call on it: voice uses the fixed backend/voice/bot.py:164 _MAX_CALL_DURATION_SECS = 10 * 60 watchdog (:1743-1768) and WhatsApp passes elapsed=0 (backend/bot_runtime.py:1280).
- Guardrails tab, "Max turns per call" slider, 4-40 (GuardrailsPanel.tsx:145-156) — honest on no channel: the sandbox hard-caps at 3 (backend/sandbox_runtime.py:366, :712), WhatsApp at 12 (backend/agent_core/guardrails.py:11-15), and the live text loop computes the max-turns flag then inspects the result only for auto-escalate (backend/bot_runtime.py:816-825).
- Voice tab, "Speaking style" selector (Habibi/src/components/prompt-studio/VoicePanel.tsx:683-703) — expected to change how the agent sounds; Preview ignores it (backend/main.py:3163-3171) and the runtime derives style from the warmth slider (backend/agent_core/tuning.py:397-409).
- Bindings tab, the "Language model" slot (Habibi/src/components/prompt-studio/BindingsTab.tsx:40-44) — expected to choose the LLM for this card; nothing constructs an LLM from a provider binding (backend/voice/bot.py:638-683, backend/voice/llm_pool.py:42).
- Bindings tab, "Edit" on a binding row (BindingsTab.tsx:163, :212) — expected to load that row for editing; it discards the row and opens a blank Add form.
- Bindings tab, the "Voice" column / voice_ref (BindingsTab.tsx:192, :294) — displayed as the voice this binding will speak with; backend/agent_core/providers/factory.py:226-227 applies voice_ref only when "voice" is absent from settings, and backend/voice/tuning_apply.py:234-235 always supplies it.
- Policy tab, the six binding rows (AgentCardPanels.tsx:202-242) — presented as bindings an author sets; PolicyBinding is Literal["required"] (backend/agent_core/cards/schema.py:20) so the only legal value is the one shown, and no runtime path reads policy_bindings (the engines take their mode from env: backend/agent_core/reco/config.py:51-62, treatment/config.py:50-64, authority/config.py:23-36, live_qa/config.py:34-48).
- Integrations console, "Test" on a connector (Habibi/src/components/integrations/McpConsole.tsx:108-113) — expected to report probe health; it toasts success for a failed or SSRF-blocked probe, and a blocked probe leaves the health column untouched (backend/agent_core/connectors/persist.py:317-323).
- Integrations console, "Connect IdP" (McpConsole.tsx:192-195) — expected to attach an issuer to the connector it sits beside; it always writes the CIMD issuer to rows[0] (backend/agent_core/connectors/persist.py:424-444).
- Roles screen, the perm-redteam-run permission (Habibi/src/routes/roles.tsx:84) — expected to control who may run a red-team suite; no route enforces it (backend/main.py:2779).
- Skills detail, "Load in sandbox" (Habibi/src/routes/agent-studio.skills.$skillId.tsx:192-206) — expected to rehearse this pack on a card that carries it; it falls back to kaia-v2-4 for exactly the skills an operator can author, and the sandbox picker then silently no-ops a slug the card does not carry (backend/sandbox_runtime.py:829, Habibi/src/routes/sandbox.lazy.tsx:609).
- Sandbox Tuning Studio, the tuning writes (Habibi/src/components/sandbox/TuningStudio.tsx:139 → POST /voice/sandbox/{id}/tune, backend/main.py:3497) — expected to persist a tuning you can promote; backend/voice_sandbox.py:238-251 keeps it in the session object and nothing reaches a deployment.
- Change log tab, the evidence block (Habibi/src/components/prompt-studio/ChangeLogTab.tsx:117, :166) — the six component digests, prevHash, seq, versionId and deploymentId are fetched (backend/agent_core/change_log.py:197-213, backend/schemas.py:3559) and rendered nowhere, so the one screen an auditor reads shows a green "Chain intact" with none of the material that makes it checkable.
- POST /agent-studio/skills/{id}/attach and /detach (backend/main.py:2404-2424) — endpoints with no caller in Habibi/src, and publish overwrites whatever they wrote (backend/db_prompt_studio.py:1959-1964).

## Where one tab's edit changes another tab's validity (12)

And whether the studio surfaces it live, only at publish, or never.

- Flow ↔ Outbound (G-OB2). Every mission's `entry_node` must be a node in the graph AND that node must claim the mission in `entryFor`: backend/agent_core/cards/compile.py:301-328. PUBLISH-ONLY, and badly reported: the Flow inspector's MissionEntries (Habibi/src/components/flow/FlowInspector.tsx:183-231) edits the graph half live, the Outbound tab edits the card half (Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:495-512), and neither renders G-OB2 — the Outbound tab shows a count (OutboundTab.tsx:105-112) that counts a skipped gate as a pass. Deleting or renaming a node in Flow silently invalidates a mission in Outbound until the publish button.
- Tools ↔ Skills (G9). A pack's allowed_tools must be a subset of tools.include ∪ tools.locked ∪ PLATFORM_SKILL_TOOLS: backend/agent_core/cards/compile.py:733-751. PUBLISH-ONLY. Unticking a tool in the Tools tab makes an attached pack fail G9; the Tools tab surfaces only G6 (Habibi/src/components/prompt-studio/AgentCardPanels.tsx:129-140) and the Skills tab holds the same compile report and never warns (AgentCardPanels.tsx:774-777, :883-899).
- Skills ↔ Tools grant. Detaching a pack removes its skill-gated writes from the runtime grant even though they stay on tools.include: backend/agent_core/skills/intersect.py:107-114. NEVER SURFACED — the Tools tab keeps rendering the tool as on, with a "Remove" button (AgentCardPanels.tsx:155), while backend/bot_tools.py:806-808 refuses to execute it.
- Voice ↔ Persona (G15). The chosen voice's locale is compared against the card's locales, which are built from persona.language + persona.fallbackLanguages (backend/db_prompt_studio.py:1004-1011) and consumed at backend/agent_core/cards/compile.py:942. BOTH: a locale-mismatch lozenge appears live in the Voice tab (Habibi/src/components/prompt-studio/VoicePanel.tsx:219-224) and G15 fires again at publish. Two distortions: card.mouth.languages is never consulted (backend/agent_core/cards/schema.py:99 has no reader), and a language-agnostic voice with locale 'und' trips both as "voice speaks und".
- Ship ↔ Evals (G7/G8/G11/G-OB9 and G12). A publish is certified by the newest eval report for the BOT (backend/agent_core/cards/compile.py:717-722, :965-968 via get_latest_eval_report), and G12 refuses any split below 100% without an auto_rollback trigger (compile.py:879-890). SPLIT: G12's requirement is warned about LIVE in the Ship tab (Habibi/src/components/prompt-studio/ShipTab.tsx:191-201), while G7/G8 are publish-only and read a report from any prompt version — prompt_version_id is written by nobody (backend/db_prompt_studio.py:1914, backend/sql/14_agent_factory.sql:46) — so clicking Run in the Evals tab changes the Ship tab's publishability with no link between the two screens and no attribution to the version under test.
- Connectors ↔ Tools. Binding a connector adds ext.* names to the card's effective tool list (backend/agent_core/skills/intersect.py:117-123 → backend/agent_core/connectors/persist.py:220-234), which is what the Tools tab counts and what G6 caps. NEVER SURFACED CORRECTLY: the Connectors tab warns "Activated connector tools still count toward the voice cap" (AgentCardPanels.tsx:949-953) while backend/agent_core/cards/compile.py:687-692 excludes them and voice has no ext dispatcher at all; and approving a connector on the Integrations screen widens the live grant of an ALREADY-PUBLISHED card with no gate and no change-log entry (backend/agent_core/connectors/persist.py:193, backend/agent_core/change_log.py:162).
- Agent graph ↔ Fleet reachability. Adding a handoff on card A changes card B's reachability chip, computed as a transitive closure from the entry card: backend/agent_core/cards/routing.py:59-94. LIVE — and wrong: backend/db_prompt_studio.py:429-430 is draft-preferred, so an UNSAVED graph edit on A already flips B's chip on the fleet index (Habibi/src/routes/agent-studio.index.tsx:64-68) while the runtime still enforces the published card; on voice the chip is not backed by the card at all (backend/voice/tools.py:2786).
- Prompt ↔ Guardrails. Turning on alwaysDiscloseRecording injects a fixed disclosure rule into the system prompt (backend/agent_core/prompt.py:74-86) on top of whatever the authored prompt already says — and the seeded Collections prompt says it too (backend/alembic/versions/20260722_0018_prompt_studio_schema_seed.py:40). NEVER SURFACED: the Prompt tab shows no guardrail contribution and the Guardrails tab shows no prompt text; the only detector is the advisory lint (backend/prompt_lint.py:155-172), which nothing gates and which the publish dialog never receives (Habibi/src/routes/prompt-studio.lazy.tsx:940-945, :1583-1606).
- Bindings ↔ Voice. The Voice tab picks a short name and the Bindings tab picks the TTS provider that will be handed it: backend/voice/tuning_apply.py:234-235 always puts tts.voice into the settings bag, so backend/agent_core/providers/factory.py:226-227 can never apply the binding's own voice_ref. NEVER SURFACED: no layer checks that the short name belongs to the bound provider (backend/voice/provider_bind.py:59-79), the Bindings tab still renders voice_ref in a "Voice" column (Habibi/src/components/prompt-studio/BindingsTab.tsx:192, :294), and switching slots keeps the previous slot's modelId with nothing checking model.kind == binding.slot (BindingsTab.tsx:49-85).
- Flow ↔ Tools. A node may be given any catalog tool by the picker (Habibi/src/components/flow/FlowInspector.tsx:406-435), /flow/validate and G1 accept it (backend/flow_graph.py:429-433, backend/agent_core/cards/compile.py:569-573), and the card's Tool Grant then drops it at runtime (backend/agent_core/tools/grant.py:57-88, backend/voice/bot.py:1141-1146) while the canvas still counts its hop as an exit. NEVER SURFACED — neither tab knows about the other's list.
- Persona ↔ Voice (audition). Persona's "Hear tone" and Voice's "Preview" audition different configurations: Habibi/src/components/prompt-studio/PersonaSliders.tsx:110-120 omits the model params and any language, so a Hindi persona is auditioned in English on backend defaults, while VoicePanel.tsx:438-450 sends the full set. NEVER SURFACED.
- Skills ↔ Sandbox. The sandbox loads the chosen skill's body but computes its tool offer from a different active skill (backend/sandbox_runtime.py:828-833, :852-862), runs as DEFAULT_BOT_ID without setting ctx.agent_card (:219-228), and executes zero tools at all (:843-852). NEVER SURFACED: the rehearsal cannot show what attaching or detaching a pack does to the grant.

## Documentation and UI copy the code contradicts (20)

Both sides cited. Fixing one of these means changing the code or the sentence — deciding which is the point.

- CONTEXT.md:46-48 defines Handoff as "Transfer of a live conversation from one agent to another … The receiving agent brings its own card, and therefore its own grant." The code transfers nothing: backend/agent_core/tools/domain.py:1009-1049 → backend/db_inbox.py:1441 writes interactions.handler_bot_id and one activity row; backend/voice/tools.py:2789-2806 returns (result, None) so the flow, prompt and tool registry are unchanged; backend/bot_runtime.py:712-714 loads the bundle by env BOT_ID on the next message. No card is loaded and no grant is rebuilt.
- docs/adr/0001-one-owner-for-the-tool-grant.md, Consequences: "a mid-call handoff changes the card and must change the grant with it", restated at backend/agent_core/tools/grant.py:15-18. backend/voice/bot.py:1138-1144 filters the tool registry once at session start and nothing re-runs ToolGrant.for_bundle on handoff, so the handing-off agent's grant survives the transfer — the exact state the ADR says it is a prerequisite for fixing.
- docs/adr/0002-cardless-agents-are-denied-every-tool.md: "Fail-open becomes structurally unreachable rather than defended by a fix: there is no branch in which an absent card grants a tool." backend/voice/tools.py:2783-2788 sets allowlist = None when card_for(bot_id) raises KeyError, and backend/agent_core/tools/domain.py:1027 reads None as unrestricted (`if allowlist is not None and target not in allowlist`), so a bot with no first-party card may hand off to anything. backend/agent_core/tools/grant.py:26-28 also still documents a legacy escape hatch ("Callers that still need the legacy ungated fallback ask is_cardless and supply it themselves") that the ADR says was deleted.
- CONTEXT.md:38-39 defines a Gate as having "three honest outcomes: pass, block, or skip". backend/agent_core/cards/compile.py:45 declares GateStatus = Literal["pass", "fail", "warn", "skipped"] — four outcomes, two spelled differently, and `warn` (which does not block a publish) has no glossary entry at all. Habibi/src/lib/gate-status.ts:1-30 exists to be the one mapping and is imported for partitionGates only.
- backend/agent_core/cards/schema.py:263-265 documents cadence.per_day as "Bounded again at runtime by contact_policy's own cap, which a card can only ever lower." backend/contact_policy.py:90-101 daily_cap() takes only the env var and tenant rules and is never passed the card (call sites backend/cadence.py:445, backend/campaigns.py:557); backend/agent_core/cards/compile.py:343-359 only refuses a per_day that EXCEEDS the global cap.
- backend/call_closer.py:99-101: "``CardObjective.success`` overrides them per published card, which is the point of authoring missions rather than hardcoding them." backend/call_closer.py:949 computes success from the module dict SUCCESS_BY_OBJECTIVE (:102-112) and never reads the card it already resolved (mission_mod.card_for_bot at :669, :754).
- backend/voice/mesh.py:5-8: "Roles are data (mesh_roles.json), not Python constants … Adding a specialist is an edit to that file, not a code change." backend/voice/mesh.py:58-66 validates MeshRole.tools and stores it; nothing in backend/ reads MeshRole.tools — the Tool Grant is card ∪ packs ∪ connectors ∪ always-on (backend/agent_core/tools/grant.py:121-123).
- backend/agent_core/cards/schema.py:93-98 describes CardMouthRef as "Pointers, not copies". backend/agent_core/deployment.py:87-89 resolves the flow straight off the prompt version (`"flow": version.get("flow")`, consumed at backend/voice/bot.py:1170-1176); mouth.flow_ref has no reader and no gate resolves it.
- Habibi/src/components/prompt-studio/AgentCardPanels.tsx:669-673 tells the author "The condition is guidance for the model, not a rule the runtime enforces". The condition never reaches the model either: backend/agent_core/tools/catalog.py:577-596 builds the handoff_to_agent description without `when`, and card.handoffs[].when has no other consumer.
- Habibi/src/components/prompt-studio/AgentCardPanels.tsx:944-945 says "Compiler G10 checks HTTPS, data-class, and health", and :949-953 warns "Activated connector tools still count toward the voice cap." backend/agent_core/cards/compile.py:758-759 skips G10 entirely when MCP_CLIENT_ENABLED is false (backend/.env.example:325) with no screen reporting the flag, and compile.py:687-692 excludes ext.* from the idle voice count while backend/voice/tools.py:2918-2919 has no ext handler at all.
- Habibi/src/components/prompt-studio/GuardrailsPanel.tsx:28-45 labels four toggles "Hard-blocks …". backend/agent_core/guardrails.py:251-262 should_halt is honoured only by the sandbox (backend/sandbox_runtime.py:897-908); on voice (backend/voice/crm_sink.py:1527-1549) and WhatsApp (backend/bot_runtime.py:1273-1287) the rule is evaluated after the reply was spoken or sent. GuardrailsPanel.tsx:40's "Flags missing disclosure on turn 1" also understates backend/agent_core/guardrails.py:240-243, which reads the whole call history.
- Habibi/src/components/prompt-studio/AgentCardPanels.tsx:256 describes the Twin requirement as "replays of real calls against the candidate". backend/agent_core/eval/harness.py:10 and backend/agent_core/eval/run.py:1-34 show no eval suite of any kind executes the candidate agent; separately the Twin tab writes and the G11 gate reads different tables (backend/agent_core/cards/compile.py:721-722 vs backend/agent_core/twin.py:150-160).
- Habibi/src/components/prompt-studio/VoiceParamsPanel.tsx:332-343 promises "a published call is synthesized with what you hear here". pause_ms never reaches a call (backend/agent_core/voice_ssml.py:61-84, backend/azure_speech.py:177-220), and speed/warmth are rendered differently at runtime (backend/agent_core/tuning.py:359-409).
- Habibi/src/components/prompt-studio/BindingsTab.tsx:282 tells an operator that with no binding the call uses "whatever the registry defaults to". There is no such fallback: backend/agent_core/providers/factory.py:265 and backend/voice/provider_bind.py:70 fall through to the hardcoded Azure path (backend/voice/bot.py:646, :669).
- Habibi/src/routes/agent-studio.index.tsx:69-74 explains "direct only" as "Addressed directly by bot id — it has its own live deployment". No production entry point ever passes a bot id other than the env one: backend/voice/bot.py:427 and backend/bot_runtime.py:712 both resolve through backend/agent_core/cards/routing.py:34-44 (`os.getenv("BOT_ID") or db.DEFAULT_BOT_ID`). agent-studio.index.tsx:724-729 likewise says archiving "stops taking traffic immediately" while backend/agent_core/cards/compile.py:661-678 (G5) and backend/db_inbox.py:1455-1460 both accept an archived handoff target.
- Habibi/src/components/prompt-studio/AgentCardPanels.tsx:743 asserts "Same vocabulary the fleet index uses, so one word does not mean two things" above ROUTE_TONE/ROUTE_HELP (:744-757), which carry no labels — so :694-698 renders the raw enum word. Habibi/src/routes/agent-studio.index.tsx:55-85 shows the same card as "direct only" with different help text.
- Habibi/src/api/outbound.ts:250-251 and backend/main.py:5287-5288 both tell the author that G-OB6 validates success/partial/stop_on. backend/agent_core/cards/compile.py:390-407 validates the post-call rule vocabulary and neither of those fields (backend/agent_core/cards/schema.py:237-238, :279-289).
- Habibi/src/components/prompt-studio/ChangeLogTab.tsx:149, :207 present the gate column as "What the compiler said at the time". Rollback never recompiles (backend/db_prompt_studio.py:2292-2424 calls no compile_card), so a rollback entry records no gate verdict at all — and backend/agent_core/change_log.py:42-45 records four verbs while ChangeLogTab.tsx:88 and :219 enumerate three, dropping "restored".
- backend/voice/flows_dynamic.py:81-93 calls SESSION_VARIABLES "the contract the Flow editor advertises". Habibi/src/components/flow/FlowInspector.tsx:692-695, :940-946 advertise no variable names at all; and Habibi/src/routes/prompt-studio.lazy.tsx:1486-1500's Flow empty state says the version "runs the built-in collections script" on cards whose only channel is text, where the graph is never read (only backend/voice/bot.py:1167-1176 reads it).
- CONTEXT.md:56-58 lists `objective` under Mission's _Avoid_, while `objective` is the card field name (backend/agent_core/cards/schema.py:190), the vocabulary endpoint's key (backend/main.py:5280) and the word the Outbound tab shows the operator. An agent following the glossary and renaming it breaks extra="forbid" validation on every published card.

---

# Gaps in this audit (33)

A critic re-read the audit against the source, looking for what the 24 slices missed: control-surface entries no slice mentioned, backend routes no slice listed, `checked_fine` claims that are wrong, and defect classes a static read cannot reach. Each line is *what — why it matters — what to read or run*. These are work, not caveats.

- 16 exported hooks in Habibi/src/api/agent-studio.ts are named in no slice — `useArchiveAgentCard` (:219), `useAgentStudioSkills` (:642), `SKILL_MUTATIONS_AVAILABLE` (:665), `EVAL_SCHEDULE_AVAILABLE` (:667), `useSkillScripts` (:691), `useRunSkillScript` (:728), `useRolesCatalog` (:756), `usePatchRolePermissions` (:778), `useCloneAgentCard` (:822), `useDeploymentExperiments` (:849), `fetchChangeLog` (:970), `fetchSkillCritiques` (:1033), `useSkillCritiques` (:1038), `useCritiqueReport` (:1046), `fetchQaDisagreements` (:1098), `useQaDisagreements` (:1103) — their endpoints were audited but the client half (cache key, invalidation set, `enabled` guard, `USE_MOCK` branch, retry policy) never was, and that is exactly the layer where SHIP-11 and SHELL-8 found real defects — read Habibi/src/api/agent-studio.ts:640-760 and :1030-1109.
- 26 exported functions in Habibi/src/api/prompt-studio.ts are named in no slice, including the entire TTS-catalog client (`fetchTtsVoiceCatalog` :291, `fetchTtsVoiceDetail` :335, `fetchTtsPricing` :345, `syncTtsVoiceCatalog` :361, `fetchTtsSyncRuns` :377, `useTtsVoiceCatalog` :403, `useInfiniteTtsVoiceCatalog` :413, `useTtsSyncRuns` :432, `useTtsPricing` :440) and the whole draft-lifecycle set (`patchPromptVersion` :626, `restorePromptVersionAsDraft` :689, `rollbackBotDeployment` :708, `discardPromptVersion` :736, `lintPromptVersion` :756, `estimatePromptTokens` :541, `useDiscardPromptVersion` :816, `useLintPrompt` :832, `usePublishStudioDraft` :1029, `useRestorePromptVersionAsDraft` :1037) — the voice slice audited the TTS *panels* and the header slice the *screen*, but nobody read the transport that feeds both — read Habibi/src/api/prompt-studio.ts:291-448 and :603-760.
- `useInfiniteTtsVoiceCatalog` (prompt-studio.ts:413) is the only infinite query in the studio and no slice opened it — pagination-cursor bugs (duplicate or dropped pages) are invisible to every other check in the audit — read Habibi/src/api/prompt-studio.ts:291-334 (`fetchTtsVoiceCatalog` query construction) with :413-431.
- `onImport` (agent-studio.skills.index.tsx:139-149) invalidates only `["agent-studio","skills"]` directly instead of calling `invalidateAgentStudio`, so importing a pack leaves the change log (`["agent-change-log"]`) stale — every sibling write path (create/clone/delete/sign/revert) routes through `invalidateAgentStudio` (agent-studio.ts:202-205); no slice mentions `onImport` — read Habibi/src/routes/agent-studio.skills.index.tsx:139-149 against Habibi/src/api/agent-studio.ts:196-205.
- the Clone-skill dialog tells the operator the opposite of what the server does — the copy at agent-studio.skills.index.tsx:405-407 says "reusing one overwrites the first", while `clone_skill` refuses with `skill_slug_taken` (backend/agent_core/skills/persist.py:482-483); and unlike the Create form, which disables its button on `slugTaken` (:232) and shows "already taken" inline (:243), the Clone action's only guard is `!toSlug(cloneSlug)` (:419), so a collision surfaces as a bare error toast — read Habibi/src/routes/agent-studio.skills.index.tsx:100-118, :393-430 and backend/agent_core/skills/persist.py:474-490.
- `exportSkillZip` (agent-studio.ts:738-749) builds a detached `<a>`, calls `a.click()` without appending it to the document, and calls `URL.revokeObjectURL(url)` synchronously on the next line — a pattern that cancels the download in several browsers; the skills slice names the function but audits only the endpoint, and `revokeObjectURL` appears nowhere in backlog.json — read Habibi/src/api/agent-studio.ts:738-749.
- no `onSubmit` handler exists on any of the four screens — the New-skill form (skills.index.tsx:200-240), the Clone-card form (agent-studio.index.tsx:470-520) and the Clone-slug dialog (skills.index.tsx:400-430) are `<div>` + `<Button>`, so Enter in the name/slug field does nothing; the repo ships Habibi/src/components/keyboard-alternatives.test.tsx and a commit specifically about asserting keyboard paths, but no slice checked these three — read Habibi/src/routes/agent-studio.skills.index.tsx:200-240 and Habibi/src/routes/agent-studio.index.tsx:470-520.
- `onFlowValidation` (prompt-studio.lazy.tsx:1536, defined ~:744-758), `presetPending`/the preset AlertDialog (:1613-1650), `setSelected` on the skill tool chips (skills.$skillId.tsx:287), `runScript` (skills.$skillId.tsx:399) and `groupRoster`/`toSlug`/`fileRef` are named in no slice — read those call sites.
- `apiUpload` (Habibi/src/api/config.ts:267-279) is the transport for skill-pack import and is named in no slice; it applies no client-side size or MIME check while the file input advertises `.zip,.md` (skills.index.tsx:167), and its only bound is a 120 s timeout — read Habibi/src/api/config.ts:267-279 with Habibi/src/routes/agent-studio.skills.index.tsx:163-172.
- the KB-gap banner (`gapBanner`, prompt-studio.lazy.tsx:1270-1300) is unmentioned by every slice even though its sibling endpoint `POST /kb/gaps/{gap_id}/promote-skill` (backend/main.py:2499) is audited three times — read Habibi/src/routes/prompt-studio.lazy.tsx:1260-1305.
- `GET /compliance/policy-export` (backend/main.py:2768, `export_policy_bundle`) is the only studio-range endpoint that appears in NO slice at all — not in endpoints[], not in any finding, not in checked_fine; it sits between two audited routes (`POST /a2a/tasks/{task_id}/signal` :2760 and `POST /eval/suites/{suite_id}/run` :2780) and was skipped — read backend/main.py:2768-2777 and backend/agent_core/policy_export.py:15-37.
- the policy-export bundle is the GRC-facing projection of policy, and it contains none of the Agent Studio card state the whole audit is about — `bundle()` emits only calling hours, five authority caps and a hardcoded `"dnd": {"contactWhenDnd": False}` (backend/agent_core/policy_export.py:22-32), so `card.policy_bindings`, `card.human_gates`, `card.guardrails` and every per-card DND/authority override are invisible to the regulator artefact; the `policy` slice audited the six binding keys and never asked what the export shows — read backend/agent_core/policy_export.py:15-76 against backend/agent_core/cards/schema.py:70-77.
- four `/providers` configuration routes are in no slice — `GET /providers` (main.py:1589), `PATCH /providers/{provider_id}/configs/{environment}` (:1594), `POST /providers/{provider_id}/test` (:1606), `GET /providers/{provider_id}/test-logs` (:1614); the bindings slice covered only `/providers/bindings|models|pools`, so the write path that changes which credentials a bound provider uses was never read — read backend/main.py:1585-1625.
- `PATCH /redaction-rules/{pii_type}` (main.py:1952) is in no slice — the guardrails slice audited only `GET /redaction-rules` (main.py:1923) and asserts at checked_fine[guardrails.5] that the PII section is "read-only", which is true of the *panel* but not of the API behind it — read backend/main.py:1952-1965.
- `GET /compliance/rule-coverage` (main.py:1786) and `POST /compliance/rescan` (main.py:1800) are in no slice, and `useComplianceRuleCoverage` (Habibi/src/api/compliance.ts:178) is likewise unmentioned — read backend/main.py:1786-1812.
- `GET /kb/gaps` (main.py:4655) and `POST /kb/gaps/{gap_id}/link` (main.py:4660) are in no slice while their sibling `POST /kb/gaps/{gap_id}/promote-skill` (main.py:2499) is audited by three — the studio's gap banner reads the first of these — read backend/main.py:4650-4670.
- two studio-adjacent routes bypass `_authz_guard` entirely by sitting in `PUBLIC_ROUTES` — `GET /.well-known/agent-card.json` (backend/authz.py:246, handler main.py:2700) and `POST /a2a` (authz.py:247, handler main.py:2713); their only authentication is `a2a_mod.require_partner(headers)` inside the handler, and `client_cert_dn` (main.py:2716) and the handler names `a2a_well_known_card`/`a2a_protocol_task` appear in no slice — the runtime slice noted only that `a2a.expose` is unchecked at serve time — read backend/main.py:2700-2736 and backend/agent_core/a2a.py `require_partner`/`client_cert_dn`.
- checked_fine[catalog.8] cites `GET /agent-studio/skills/scripts` at "backend/main.py:2316-2318" — that range is inside `get_agent_studio_skill` (main.py:2310-2323); the scripts handler is main.py:2297-2308, and it serves `SCRIPT_NAMES` (agent_core/skills/scripts.py:55), not the `SCRIPTS` dict the entry names (scripts.py:50-53); the enum is at catalog.py:635, not 636 — the substantive equality holds, the citation does not — read backend/main.py:2297-2323 and backend/agent_core/skills/scripts.py:50-55.
- checked_fine[flow.4] cites `/flow/validate` at "backend/main.py:3005-3011" — that is `list_persona_presets` (main.py:3003-3006); `POST /flow/validate` is main.py:2992-3001 — read backend/main.py:2992-3010.
- checked_fine[voice.15] "Sync endpoint is admin-gated (main.py:3078)" points at `POST /tts/preview` (main.py:3078), which has NO admin gate; the real gate is `Depends(require_admin)` at main.py:3067 plus `("POST","/tts-voices/catalog/sync"): ADMIN_WRITE` at authz.py:387 — the claim is true but the cited line is its counter-example, and a reader spot-checking it would conclude an ungated route is gated — read backend/main.py:3061-3080 and backend/authz.py:381-389.
- `runtime_consumers` maps `outbound.direction` and `outbound.objectives[].key` to "agent_core/treatment/enact.py:368" and ":369" — those lines are now inside `_conversation`/WhatsApp queueing (enact.py:360-372); the actual reader is enact.py:424-425 (`card.outbound.dials and card.outbound.objectives`, then `card.outbound.objective(objective)`), and `dials` is a derived property (schema.py:357) not a field, so the mapping is right in substance and wrong at every line — read backend/agent_core/treatment/enact.py:415-430 and backend/agent_core/cards/schema.py:315-360.
- the audit is not a snapshot of one tree — `git diff HEAD -- backend/main.py` shows 11 insertions / 24 deletions still uncommitted, including the deletion of `GET /offers/tuner-suggestions` (~line 1091), which shifted every route below it by 11 lines mid-audit; the 08:44 and 10:10 slice batches (fleet, shell, header-era, prompt, catalog, skills, outbound, runtime) cite main.py ~11 lines high (runtime says 2130/2214/2711/3215/3246 for routes actually at 2119/2203/2700/3204/3235; skills says 2356 for a route at 2346) while the 10:27/10:51 batches (authz, org, bindings, policy, evals) are exact — read `git diff HEAD -- backend/main.py` and re-anchor every main.py citation in the early slices before publishing.
- the working tree moved far beyond main.py during the audit window — `git status --porcelain` lists 78 entries against the 8 in the session-start snapshot, including modified backend/authz.py, backend/db.py (−2604 lines), backend/campaigns.py, backend/agent_core/treatment/{enact,engine,arbitration,decisions,explore,followthrough,scoring}.py, deleted backend/agent_core/tuner.py and backend/agent_core/treatment/rerank.py, an untracked backend/db_inbox.py (2585 lines, the file every handoff finding cites) and a new migration backend/alembic/versions/20260906_0107_honest_engines.py — findings anchored in those files are stale by construction and must be re-verified — run `git status --porcelain` and `git diff --stat HEAD`.
- checked_fine[types.1], the entry whose entire value is field-for-field precision, drifts 2 lines on its own anchors — it cites CardIdentity at "schema.py:77-88" (actual 79-89) and CardMouthRef at ":90-97" (actual 92-99) — read backend/agent_core/cards/schema.py:79-100.
- checked_fine[header.11] promises "publish_prompt_version writes exactly the six things the slice asked about" and then enumerates seven (archived prior row, promoted draft, retired-plus-new deployment, canary experiment, change-log entry, skill-attachment sync, kb snapshot resolution) — the mechanism was read, the closure claim was not counted — read backend/db_prompt_studio.py:1864-2160.
- checked_fine[changelog.2] certifies the invalidation mechanism as fixed ("Archive, restore, connector attach and experiment rollback all route through it") while SHIP-11 in the same corpus documents that `["deployments"]` (agent-studio.ts:851, :878) and `["bot-deployments"]` (prompt-studio.ts:122, :907, :915) are different roots and neither invalidator reaches the other — the entry is narrowly true and reads as a clean bill; separately, the docstring it endorses (agent-studio.ts:199-201, "The two roots that do NOT are listed here explicitly") is false: `["deployments"]`, `["roles"]`, `["eval-critiques"]`, `["eval-disagreements"]`, `["eval-reports"]`, `["eval-suites"]`, `["flow-tools"]`, `["connectors"]` and `["provider-bindings"]` are all outside `["agent-studio"]` — read Habibi/src/api/agent-studio.ts:180-210 with Habibi/src/api/prompt-studio.ts:120-137.
- no checked_fine entry in any slice was re-verified against the current tree before merge — publishing them as a clean bill without a re-anchor pass converts 447 unverified assertions into claimed coverage — re-open each cited range; a cheap first pass is to check only the ~140 entries that cite backend/main.py, backend/authz.py, backend/db.py, backend/campaigns.py or backend/agent_core/treatment/*.
- no card was ever queried, so "dead config" cannot distinguish an unenforced promise from an unused field — run `docker exec collections_db psql -U collections -c "select bot_id, agent_card->'human_gates', agent_card->'memory', agent_card->'experiment'->'shadow', agent_card->'outbound'->'concurrency_share' from prompt_versions where status='published';"` (per MEMORY: the role is `collections`, and `compose exec` hangs).
- every "pinned by tests/…" claim is unverified, and the suite has known failures and six untracked new files — run `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec voice pytest -q tests/test_authz.py tests/test_tool_grant.py tests/test_agent_card_schema_drift.py tests/test_handoff_to_agent.py tests/test_flow_tool_catalog.py tests/test_outbound_card_vocabulary.py` (bind-mount matters: the container tests the built image otherwise, and never run this while the corpus simulator holds locks).
- no runtime evidence exists for any UI claim — start the app and drive one loop: open /agent-studio, clone a template, open the card, edit Tools, watch the network panel for `POST /agent-studio/cards/{id}/compile` per keystroke and per autosave, then export a skill zip and press Enter in the New-skill name field.
- "zero readers anywhere in the backend" was established by name search, which cannot see reflective access — grep backend for `agent_card.get(`, `card.model_dump(`, `for k, v in` over card dicts, and `getattr(card`, and confirm none of them iterate the sub-models the audit declared dead.
- no concurrent path was exercised — the two that matter are two publishes of different bots racing the tenant-scoped hash chain, and two sandbox turn appends racing one run — run `pytest -q tests/test_agent_change_log.py tests/test_sandbox_turn_schema.py` and then two overlapping `POST /prompt-versions/{id}/publish` against different bot_ids in the same tenant, checking `verify_chain` afterwards.
- the frontend has 19 test files total and three touch the studio, so there is no regression net under any of the 42 unaudited hooks or 76 handlers in Section 1 — the cheapest closure is a single `vitest` run plus one new test per destructive path (archive, delete-skill, clone-skill collision, import) — run `cd Habibi && npm test` to establish the current baseline before adding any.
