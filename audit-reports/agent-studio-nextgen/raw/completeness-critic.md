COMPLETENESS CRITIC — WHAT THE 24-SLICE AUDIT MISSED
Method: re-derived the control surface from source, diffed it against all 24 `raw/audit-*.json` files (endpoints[], findings[], checked_fine[], runtime_consumers[]) and against `backlog.json` (345 findings). Every claim below is anchored to a line I opened.

═══════════════════════════════════════════════════════════════
SECTION 1 — THE REAL CONTROL SURFACE vs THE AUDIT
═══════════════════════════════════════════════════════════════

1A. HANDLERS ENUMERATED (four screens, 76 handlers total)

Habibi/src/routes/prompt-studio.lazy.tsx (1660 lines, 25 handlers)
  :782 toast action onClick · :1055 `{label:"Read", onClick:()=>setTab("prompt")}` · :1293 KB-gap banner Dismiss (`setGapBannerDismissed` + `navigate({search:{}})`) · :1324 tab-strip `setTab(t.key)` · :1360 back to /agent-studio · :1387/:1391/:1394/:1397/:1405/:1411 six card tabs `onChange={(next)=>setCard(next)}` · :1417 `onChange={setShip}` · :1428 `onChange={setPrompt}` · :1442 `onChange={setPersona}` · :1452 `onChange={setVoice}` · :1455 `onChange={setGuardrails}` · :1506 "Load the built-in script" → `fetchBuiltInFlow()` · :1528 "Start from blank" → `setFlow(emptyGraph())` · :1536 `onChange={setFlow}` + `onValidation={onFlowValidation}` · :1551/:1578/:1585/:1613 four `onOpenChange` · :1605 `onConfirm={(note)=>void publish(note)}` · :1641 `commitPreset(presetPending)`

Habibi/src/routes/agent-studio.index.tsx (748 lines, 18 handlers)
  :174 ReasonedAction wrapper · :283 toggle · :318/:538 `refetch()` · :456 `onCheckedChange` showArchived · :463 → /agent-studio/skills · :467 `setOpen(true)` · :485 template select · :500 name Input · :504 "Create draft" → `clone.mutateAsync` · :517 Cancel · :582/:649/:678 navigate to $botId · :690 Sandbox → /sandbox · :703 `onArchive(card)` · :719 AlertDialog `onOpenChange` · :735 `runArchive(card,true)`

Habibi/src/routes/agent-studio.skills.index.tsx (460 lines, 17 handlers)
  :168 file input `onChange` → `onImport(file)` · :183 Import zip → `fileRef.current?.click()` · :190 New skill toggle · :197 Back to fleet · :216/:225 name/description · :233 `onCreate()` · :237 Cancel · :325/:358 navigate to $skillId · :371 `onClone` · :380 `onDelete` · :393/:433 two `onOpenChange` · :410 `setCloneSlug(toSlug(...))` · :418 `runClone` · :447 `runDelete`

Habibi/src/routes/agent-studio.skills.$skillId.tsx (441 lines, 16 handlers)
  :152/:185 back to library · :192 "Load in sandbox" → navigate · :212 `exportSkillZip(skill.id)` · :224 `onSave()` · :231 `sign.mutateAsync` · :255 `revert.mutateAsync({skillId})` · :275 description · :287 tool chip → `setSelected(...)` · :307 body · :359 version "Restore" → `revert.mutateAsync({skillId, versionId})` · :381 script select · :392 scriptJson · :399 "Run" → `runScript.mutateAsync`

Zero `useMutation` calls live in the four route files — every mutation is imported from api/. Zero `onSubmit` handlers exist in any of the four.

1B. EXPORTED HOOKS AND THEIR AUDIT COVERAGE
api/agent-studio.ts exports 40 symbols; api/prompt-studio.ts exports 42. **42 of the 82 are named in no slice's endpoints[], findings[] or checked_fine[]**, and 26 of those have zero mentions anywhere in backlog.json either.

GAP: 16 exported hooks in Habibi/src/api/agent-studio.ts are named in no slice — `useArchiveAgentCard` (:219), `useAgentStudioSkills` (:642), `SKILL_MUTATIONS_AVAILABLE` (:665), `EVAL_SCHEDULE_AVAILABLE` (:667), `useSkillScripts` (:691), `useRunSkillScript` (:728), `useRolesCatalog` (:756), `usePatchRolePermissions` (:778), `useCloneAgentCard` (:822), `useDeploymentExperiments` (:849), `fetchChangeLog` (:970), `fetchSkillCritiques` (:1033), `useSkillCritiques` (:1038), `useCritiqueReport` (:1046), `fetchQaDisagreements` (:1098), `useQaDisagreements` (:1103) — their endpoints were audited but the client half (cache key, invalidation set, `enabled` guard, `USE_MOCK` branch, retry policy) never was, and that is exactly the layer where SHIP-11 and SHELL-8 found real defects — read Habibi/src/api/agent-studio.ts:640-760 and :1030-1109.

GAP: 26 exported functions in Habibi/src/api/prompt-studio.ts are named in no slice, including the entire TTS-catalog client (`fetchTtsVoiceCatalog` :291, `fetchTtsVoiceDetail` :335, `fetchTtsPricing` :345, `syncTtsVoiceCatalog` :361, `fetchTtsSyncRuns` :377, `useTtsVoiceCatalog` :403, `useInfiniteTtsVoiceCatalog` :413, `useTtsSyncRuns` :432, `useTtsPricing` :440) and the whole draft-lifecycle set (`patchPromptVersion` :626, `restorePromptVersionAsDraft` :689, `rollbackBotDeployment` :708, `discardPromptVersion` :736, `lintPromptVersion` :756, `estimatePromptTokens` :541, `useDiscardPromptVersion` :816, `useLintPrompt` :832, `usePublishStudioDraft` :1029, `useRestorePromptVersionAsDraft` :1037) — the voice slice audited the TTS *panels* and the header slice the *screen*, but nobody read the transport that feeds both — read Habibi/src/api/prompt-studio.ts:291-448 and :603-760.

GAP: `useInfiniteTtsVoiceCatalog` (prompt-studio.ts:413) is the only infinite query in the studio and no slice opened it — pagination-cursor bugs (duplicate or dropped pages) are invisible to every other check in the audit — read Habibi/src/api/prompt-studio.ts:291-334 (`fetchTtsVoiceCatalog` query construction) with :413-431.

GAP: `onImport` (agent-studio.skills.index.tsx:139-149) invalidates only `["agent-studio","skills"]` directly instead of calling `invalidateAgentStudio`, so importing a pack leaves the change log (`["agent-change-log"]`) stale — every sibling write path (create/clone/delete/sign/revert) routes through `invalidateAgentStudio` (agent-studio.ts:202-205); no slice mentions `onImport` — read Habibi/src/routes/agent-studio.skills.index.tsx:139-149 against Habibi/src/api/agent-studio.ts:196-205.

GAP: the Clone-skill dialog tells the operator the opposite of what the server does — the copy at agent-studio.skills.index.tsx:405-407 says "reusing one overwrites the first", while `clone_skill` refuses with `skill_slug_taken` (backend/agent_core/skills/persist.py:482-483); and unlike the Create form, which disables its button on `slugTaken` (:232) and shows "already taken" inline (:243), the Clone action's only guard is `!toSlug(cloneSlug)` (:419), so a collision surfaces as a bare error toast — read Habibi/src/routes/agent-studio.skills.index.tsx:100-118, :393-430 and backend/agent_core/skills/persist.py:474-490.

GAP: `exportSkillZip` (agent-studio.ts:738-749) builds a detached `<a>`, calls `a.click()` without appending it to the document, and calls `URL.revokeObjectURL(url)` synchronously on the next line — a pattern that cancels the download in several browsers; the skills slice names the function but audits only the endpoint, and `revokeObjectURL` appears nowhere in backlog.json — read Habibi/src/api/agent-studio.ts:738-749.

GAP: no `onSubmit` handler exists on any of the four screens — the New-skill form (skills.index.tsx:200-240), the Clone-card form (agent-studio.index.tsx:470-520) and the Clone-slug dialog (skills.index.tsx:400-430) are `<div>` + `<Button>`, so Enter in the name/slug field does nothing; the repo ships Habibi/src/components/keyboard-alternatives.test.tsx and a commit specifically about asserting keyboard paths, but no slice checked these three — read Habibi/src/routes/agent-studio.skills.index.tsx:200-240 and Habibi/src/routes/agent-studio.index.tsx:470-520.

GAP: `onFlowValidation` (prompt-studio.lazy.tsx:1536, defined ~:744-758), `presetPending`/the preset AlertDialog (:1613-1650), `setSelected` on the skill tool chips (skills.$skillId.tsx:287), `runScript` (skills.$skillId.tsx:399) and `groupRoster`/`toSlug`/`fileRef` are named in no slice — read those call sites.

GAP: `apiUpload` (Habibi/src/api/config.ts:267-279) is the transport for skill-pack import and is named in no slice; it applies no client-side size or MIME check while the file input advertises `.zip,.md` (skills.index.tsx:167), and its only bound is a 120 s timeout — read Habibi/src/api/config.ts:267-279 with Habibi/src/routes/agent-studio.skills.index.tsx:163-172.

GAP: the KB-gap banner (`gapBanner`, prompt-studio.lazy.tsx:1270-1300) is unmentioned by every slice even though its sibling endpoint `POST /kb/gaps/{gap_id}/promote-skill` (backend/main.py:2499) is audited three times — read Habibi/src/routes/prompt-studio.lazy.tsx:1260-1305.

═══════════════════════════════════════════════════════════════
SECTION 2 — UNAUDITED BACKEND SURFACE
═══════════════════════════════════════════════════════════════
Parsed every route decorator in backend/main.py: **313 routes, 97 of them inside the five studio ranges.** Diffed against every METHOD+PATH string appearing anywhere in the 24 slice files (184 distinct).

GAP: `GET /compliance/policy-export` (backend/main.py:2768, `export_policy_bundle`) is the only studio-range endpoint that appears in NO slice at all — not in endpoints[], not in any finding, not in checked_fine; it sits between two audited routes (`POST /a2a/tasks/{task_id}/signal` :2760 and `POST /eval/suites/{suite_id}/run` :2780) and was skipped — read backend/main.py:2768-2777 and backend/agent_core/policy_export.py:15-37.

GAP: the policy-export bundle is the GRC-facing projection of policy, and it contains none of the Agent Studio card state the whole audit is about — `bundle()` emits only calling hours, five authority caps and a hardcoded `"dnd": {"contactWhenDnd": False}` (backend/agent_core/policy_export.py:22-32), so `card.policy_bindings`, `card.human_gates`, `card.guardrails` and every per-card DND/authority override are invisible to the regulator artefact; the `policy` slice audited the six binding keys and never asked what the export shows — read backend/agent_core/policy_export.py:15-76 against backend/agent_core/cards/schema.py:70-77.

GAP: four `/providers` configuration routes are in no slice — `GET /providers` (main.py:1589), `PATCH /providers/{provider_id}/configs/{environment}` (:1594), `POST /providers/{provider_id}/test` (:1606), `GET /providers/{provider_id}/test-logs` (:1614); the bindings slice covered only `/providers/bindings|models|pools`, so the write path that changes which credentials a bound provider uses was never read — read backend/main.py:1585-1625.

GAP: `PATCH /redaction-rules/{pii_type}` (main.py:1952) is in no slice — the guardrails slice audited only `GET /redaction-rules` (main.py:1923) and asserts at checked_fine[guardrails.5] that the PII section is "read-only", which is true of the *panel* but not of the API behind it — read backend/main.py:1952-1965.

GAP: `GET /compliance/rule-coverage` (main.py:1786) and `POST /compliance/rescan` (main.py:1800) are in no slice, and `useComplianceRuleCoverage` (Habibi/src/api/compliance.ts:178) is likewise unmentioned — read backend/main.py:1786-1812.

GAP: `GET /kb/gaps` (main.py:4655) and `POST /kb/gaps/{gap_id}/link` (main.py:4660) are in no slice while their sibling `POST /kb/gaps/{gap_id}/promote-skill` (main.py:2499) is audited by three — the studio's gap banner reads the first of these — read backend/main.py:4650-4670.

NO MISSED ROUTER MODULE — but the reason matters:
There is exactly one `FastAPI(` in the whole backend (main.py:608) and **zero** `APIRouter(` / `include_router` anywhere; all 313 routes are `@app.*` decorators in main.py. So no router module was missed. I independently re-ran the coverage check that checked_fine[authz.0] claims: parsing main.py's 313 routes against authz.py's `PUBLIC_ROUTES` (26) ∪ `ROUTE_PERMISSIONS` (291) yields **0 unclassified routes and 0 stale registry rows**. That claim holds.

GAP: two studio-adjacent routes bypass `_authz_guard` entirely by sitting in `PUBLIC_ROUTES` — `GET /.well-known/agent-card.json` (backend/authz.py:246, handler main.py:2700) and `POST /a2a` (authz.py:247, handler main.py:2713); their only authentication is `a2a_mod.require_partner(headers)` inside the handler, and `client_cert_dn` (main.py:2716) and the handler names `a2a_well_known_card`/`a2a_protocol_task` appear in no slice — the runtime slice noted only that `a2a.expose` is unchecked at serve time — read backend/main.py:2700-2736 and backend/agent_core/a2a.py `require_partner`/`client_cert_dn`.

═══════════════════════════════════════════════════════════════
SECTION 3 — CHALLENGING "CHECKED_FINE"
═══════════════════════════════════════════════════════════════
Sampled 18 entries across 10 slices (authz, catalog, flow, graph, header, policy, runtime, types, voice, bindings), preferring whole-mechanism claims, and opened every cited line.

CONFIRMED CORRECT (re-derived independently, do not re-open):
 • [authz.0] registry totality — my own parse: 313 routes, 0 unclassified, 0 stale. `assert_registry_covers` is at authz.py:911-927 and `test_registry_covers_every_route` at tests/test_authz.py:40 enumerates `app_main.app.routes`. Exact.
 • [graph.5] `_handoff_allowlist` live card → built-in → deny — bot_tools.py:400-429. Cited range exact.
 • [catalog.19] `VOICE_ALWAYS` at agent_core/tools/grant.py:88. Exact.
 • [policy.12] `policy_bindings: PolicyBindings = Field(default_factory=PolicyBindings)` (schema.py:386) makes the field structurally unskippable; `scaffold_card` at defaults.py:364-370. Claim holds.
 • [authz.12] `resolve_role_grants` at main.py:2968-2970. Exact.
 • [flow.4] substantively correct: `assert_publishable` defaults `known_tools` to `[t["key"] for t in tool_catalog()]` (flow_graph.py:426-430), the same source `validate_flow` passes (main.py:2999-3000).
 • [catalog.0] arithmetic checks out: the voice registry dict (voice/tools.py:2882-2914) holds 33 names; `VOICE_FLOW_TOOLS` is nine (grant.py:73 "the nine above"); 33 − 9 = 24.
 • [bindings.2] / [voice.8] Fish free-model expiry is genuinely flipped — `OPENROUTER_TTS_MODEL=fish-audio/s2.1-pro` (.env.example:591) and `FISH_TTS_MODEL=s2.1-pro` (.env.example:612), both exact. (Note: this means the standing MEMORY.md note "Fish free model expires — NOT flipped" is now stale, not the audit.)

WRONG OR OVERSTATED — these are findings the audit actively missed or mis-anchored:

GAP: checked_fine[catalog.8] cites `GET /agent-studio/skills/scripts` at "backend/main.py:2316-2318" — that range is inside `get_agent_studio_skill` (main.py:2310-2323); the scripts handler is main.py:2297-2308, and it serves `SCRIPT_NAMES` (agent_core/skills/scripts.py:55), not the `SCRIPTS` dict the entry names (scripts.py:50-53); the enum is at catalog.py:635, not 636 — the substantive equality holds, the citation does not — read backend/main.py:2297-2323 and backend/agent_core/skills/scripts.py:50-55.

GAP: checked_fine[flow.4] cites `/flow/validate` at "backend/main.py:3005-3011" — that is `list_persona_presets` (main.py:3003-3006); `POST /flow/validate` is main.py:2992-3001 — read backend/main.py:2992-3010.

GAP: checked_fine[voice.15] "Sync endpoint is admin-gated (main.py:3078)" points at `POST /tts/preview` (main.py:3078), which has NO admin gate; the real gate is `Depends(require_admin)` at main.py:3067 plus `("POST","/tts-voices/catalog/sync"): ADMIN_WRITE` at authz.py:387 — the claim is true but the cited line is its counter-example, and a reader spot-checking it would conclude an ungated route is gated — read backend/main.py:3061-3080 and backend/authz.py:381-389.

GAP: `runtime_consumers` maps `outbound.direction` and `outbound.objectives[].key` to "agent_core/treatment/enact.py:368" and ":369" — those lines are now inside `_conversation`/WhatsApp queueing (enact.py:360-372); the actual reader is enact.py:424-425 (`card.outbound.dials and card.outbound.objectives`, then `card.outbound.objective(objective)`), and `dials` is a derived property (schema.py:357) not a field, so the mapping is right in substance and wrong at every line — read backend/agent_core/treatment/enact.py:415-430 and backend/agent_core/cards/schema.py:315-360.

GAP: the audit is not a snapshot of one tree — `git diff HEAD -- backend/main.py` shows 11 insertions / 24 deletions still uncommitted, including the deletion of `GET /offers/tuner-suggestions` (~line 1091), which shifted every route below it by 11 lines mid-audit; the 08:44 and 10:10 slice batches (fleet, shell, header-era, prompt, catalog, skills, outbound, runtime) cite main.py ~11 lines high (runtime says 2130/2214/2711/3215/3246 for routes actually at 2119/2203/2700/3204/3235; skills says 2356 for a route at 2346) while the 10:27/10:51 batches (authz, org, bindings, policy, evals) are exact — read `git diff HEAD -- backend/main.py` and re-anchor every main.py citation in the early slices before publishing.

GAP: the working tree moved far beyond main.py during the audit window — `git status --porcelain` lists 78 entries against the 8 in the session-start snapshot, including modified backend/authz.py, backend/db.py (−2604 lines), backend/campaigns.py, backend/agent_core/treatment/{enact,engine,arbitration,decisions,explore,followthrough,scoring}.py, deleted backend/agent_core/tuner.py and backend/agent_core/treatment/rerank.py, an untracked backend/db_inbox.py (2585 lines, the file every handoff finding cites) and a new migration backend/alembic/versions/20260906_0107_honest_engines.py — findings anchored in those files are stale by construction and must be re-verified — run `git status --porcelain` and `git diff --stat HEAD`.

GAP: checked_fine[types.1], the entry whose entire value is field-for-field precision, drifts 2 lines on its own anchors — it cites CardIdentity at "schema.py:77-88" (actual 79-89) and CardMouthRef at ":90-97" (actual 92-99) — read backend/agent_core/cards/schema.py:79-100.

GAP: checked_fine[header.11] promises "publish_prompt_version writes exactly the six things the slice asked about" and then enumerates seven (archived prior row, promoted draft, retired-plus-new deployment, canary experiment, change-log entry, skill-attachment sync, kb snapshot resolution) — the mechanism was read, the closure claim was not counted — read backend/db_prompt_studio.py:1864-2160.

GAP: checked_fine[changelog.2] certifies the invalidation mechanism as fixed ("Archive, restore, connector attach and experiment rollback all route through it") while SHIP-11 in the same corpus documents that `["deployments"]` (agent-studio.ts:851, :878) and `["bot-deployments"]` (prompt-studio.ts:122, :907, :915) are different roots and neither invalidator reaches the other — the entry is narrowly true and reads as a clean bill; separately, the docstring it endorses (agent-studio.ts:199-201, "The two roots that do NOT are listed here explicitly") is false: `["deployments"]`, `["roles"]`, `["eval-critiques"]`, `["eval-disagreements"]`, `["eval-reports"]`, `["eval-suites"]`, `["flow-tools"]`, `["connectors"]` and `["provider-bindings"]` are all outside `["agent-studio"]` — read Habibi/src/api/agent-studio.ts:180-210 with Habibi/src/api/prompt-studio.ts:120-137.

GAP: no checked_fine entry in any slice was re-verified against the current tree before merge — publishing them as a clean bill without a re-anchor pass converts 447 unverified assertions into claimed coverage — re-open each cited range; a cheap first pass is to check only the ~140 entries that cite backend/main.py, backend/authz.py, backend/db.py, backend/campaigns.py or backend/agent_core/treatment/*.

═══════════════════════════════════════════════════════════════
SECTION 4 — STRUCTURAL BLIND SPOTS
═══════════════════════════════════════════════════════════════
The method was static, read-only, no database, no test run, no browser, against a frontend with 19 test files (only three studio-adjacent: agent-studio.skills.index.test.ts, lib/agent-roster.test.ts, api/types/nullability.test.ts). That leaves five whole classes of defect unreachable.

(a) "Dead config" is unfalsifiable without data. Every one of the 22 NONE verdicts in audit-runtime.json — `memory.*`, `human_gates.*`, `mouth.*`, `identity.data_class`, `experiment.shadow`, `outbound.concurrency_share`, `cadences[].time_of_day`, `objectives[].partial` — means "I found no reader in the source I read", not "no live card sets this". A field that is dead in code but populated in production is a compliance artefact that promises enforcement nobody performs; a field that is empty everywhere is merely dead schema. The audit cannot tell those apart, and the difference is the whole severity.
GAP: no card was ever queried, so "dead config" cannot distinguish an unenforced promise from an unused field — run `docker exec collections_db psql -U collections -c "select bot_id, agent_card->'human_gates', agent_card->'memory', agent_card->'experiment'->'shadow', agent_card->'outbound'->'concurrency_share' from prompt_versions where status='published';"` (per MEMORY: the role is `collections`, and `compose exec` hangs).

(b) Cited tests were never run. The slices cite roughly forty backend test files as proof a behaviour is pinned — tests/test_authz.py:40, test_tool_grant.py:88/124-163, test_agent_card_schema_drift.py:126-146, test_handoff_to_agent.py:76-85, test_flow_tool_catalog.py:38-77, test_outbound_card_vocabulary.py:36-110 and more — and a test file's *existence* is not evidence it passes. MEMORY records 1 real pre-existing failure since 2026-09-02 and 4 more due 2026-09-15, plus six brand-new `test_honest_engines_*.py` files landing untracked today.
GAP: every "pinned by tests/…" claim is unverified, and the suite has known failures and six untracked new files — run `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec voice pytest -q tests/test_authz.py tests/test_tool_grant.py tests/test_agent_card_schema_drift.py tests/test_handoff_to_agent.py tests/test_flow_tool_catalog.py tests/test_outbound_card_vocabulary.py` (bind-mount matters: the container tests the built image otherwise, and never run this while the corpus simulator holds locks).

(c) No browser drove the UI. Every claim about loading states, disabled buttons, dialog resets, toast copy, focus and keyboard is a reading of JSX, not an observation. Three specific things are unknowable this way: whether `exportSkillZip`'s detached `a.click()` + synchronous `revokeObjectURL` (agent-studio.ts:738-749) actually downloads; whether Enter submits any of the three studio forms that have no `onSubmit`; and whether the `useCompilePreview` 400 ms debounce (agent-studio.ts:260-280) plus SHELL-8's autosave invalidation actually converge or oscillate.
GAP: no runtime evidence exists for any UI claim — start the app and drive one loop: open /agent-studio, clone a template, open the card, edit Tools, watch the network panel for `POST /agent-studio/cards/{id}/compile` per keystroke and per autosave, then export a skill zip and press Enter in the New-skill name field.

(d) Static reading cannot see dynamic dispatch. Sixteen slices concluded "no reader" from name-based searching. That is blind to `getattr`, dict-keyed dispatch, jsonb key iteration, and any field reached by serializing the card into a prompt or an LLM tool schema. `card.human_gates` and `card.memory` are exactly the shape that would be read that way if they were read at all.
GAP: "zero readers anywhere in the backend" was established by name search, which cannot see reflective access — grep backend for `agent_card.get(`, `card.model_dump(`, `for k, v in` over card dicts, and `getattr(card`, and confirm none of them iterate the sub-models the audit declared dead.

(e) Nothing observed concurrency, ordering, or clock. CHANGELOG-4 (unlocked chain head) and the sandbox `SELECT … FOR UPDATE` claim (checked_fine[sandbox.6], sandbox_runtime.py:920-955) are both about interleaving, and both were reasoned about rather than exercised. Likewise MEMORY records that `now()` in db_tx tests is transaction start, which changes what any date-dependent gate does.
GAP: no concurrent path was exercised — the two that matter are two publishes of different bots racing the tenant-scoped hash chain, and two sandbox turn appends racing one run — run `pytest -q tests/test_agent_change_log.py tests/test_sandbox_turn_schema.py` and then two overlapping `POST /prompt-versions/{id}/publish` against different bot_ids in the same tenant, checking `verify_chain` afterwards.

GAP: the frontend has 19 test files total and three touch the studio, so there is no regression net under any of the 42 unaudited hooks or 76 handlers in Section 1 — the cheapest closure is a single `vitest` run plus one new test per destructive path (archive, delete-skill, clone-skill collision, import) — run `cd Habibi && npm test` to establish the current baseline before adding any.