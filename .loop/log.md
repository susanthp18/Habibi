# BigBound Loop Log
Loop state dir: D:\Hackathon\.loop\ (.hermes/ is write-protected this session). Prompts: prompts/*.txt, run via `claude -p "$(cat prompts/X.txt)" --dangerously-skip-permissions`, output to out/. Scope snapshots before_cN.txt / after_cN.txt.

## BASELINE — 2026-08-22, host venv
- backend: 2347 passed, 12 skipped, 0 failed (325.7s)
- Habibi: typecheck exit 0 | lint exit 0 (62 warnings, 0 errors) | build exit 0
- GATE: passed >= 2347, failed == 0, all three FE commands exit 0.

## CYCLE 1 — DISCOVERY — LANDED
- Job: read-only repo survey for built-but-not-connected functionality.
- Result: report at out/cycle1.txt; changed nothing (verified: grep spot-checks of orphan endpoints all empty, ContactabilityPill code matches quoted evidence).
- Queue seeded -> queue.md (12 findings).
- Learned: USE_MOCK seam at Habibi/src/api/config.ts is disciplined — every screen routes through it; mock-data problem is concentrated in duplicated business rules, not stray arrays. Workers all wired (bot_worker.py:34-43/70-102, worker.py:407-415). Sidebar groups start at Sidebar.tsx:56.

## CYCLE 2 — treatment-console-absent [P1] — LANDED
- Job: give /treatment/* (9 endpoints) its operator console.
- Diff: exactly 4 paths — NEW src/api/treatment.ts, src/routes/treatment{,.lazy}.tsx, routeTree.gen.ts (auto-gen). Sidebar.tsx:77 also edited but invisible to porcelain diff because it was ALREADY dirty in pre-existing WIP — blind spot: scope-check must diff content, not just status, for already-dirty files.
- Verified myself: typecheck 0 | lint 0 err/62 warn (=baseline) | opened localhost:8080/treatment — live backend data rendering (29 decisions, 51.7% coverage, suppression mix, causal panel honestly refuses number). Claude also caught WhatsApp/acronym casing bugs via screenshots.
- Note: Claude did NOT commit (correct — I didn't ask; decide commit policy later).

## CYCLE 3 — contactability-browser-tz [P2] — LANDED
- Diff in scope: ContactabilityPill.tsx (withinWindow deleted, formatter over server verdict + pending/unknown states), NEW api/contact-policy.ts (typed hook, channel=voice explicit, 60s refetch, mock emulation of contact_policy._veto), CustomerHeader.tsx (passes customerId), customer360-seed.ts (+allowedDays on Anita Desai).
- Claude reproduced all 4 defect cases pre-fix (pill green while backend vetoes), verified post-fix incl. 18:59/19:00 boundary. Unknown future reason codes default non-green.
- I verified myself: typecheck 0, lint 0err/62warn, opened AC-88214→anita-desai 360 at 01:20 IST Sunday: pill renders "Outside calling hours" (her window Mon–Sat 11–18). Honest degradation elsewhere on page too.
- Learned: customer ids are slugs (anita-desai), not account numbers. Habibi has NO test runner — queued vitest setup as its own item; mockVeto/contactabilityState exported pure w/ injectable clock ready for tests. Claude cannot screenshot (no browser tooling in its sandbox) — UI verification is MY job every cycle.
- FE-only cycle → no pytest needed.

## CYCLE 4 — dispute-sla-computed-twice [P4, cross-stack] — LANDED (relaunched 04:41 after quota reset)
- Diff: db.py (_sla_label -> _dispute_sla tuple sla/slaLabel/slaMinutes, TS thresholds, migrated sole caller), schemas.py (fields on both response models - extra=forbid made this mandatory), disputes-seed.ts (slaInfo() DELETED, consumers read server fields incl. board sort/filter/metrics), NEW data/dispute-sla.ts (justified out-of-scope: avoids ESM TDZ cycle between seeds), NEW tests/test_dispute_sla.py (boundaries: warn edge, past-due breach, far-future ok, closed done, null due).
- Verified: targeted 95 passed + extra suites 163; FE typecheck/lint green; I opened /disputes myself — cards render, SLA chips absent-but-graceful vs stale API.
- BEHAVIOUR CHANGE (deliberate): null sla_due_at now Open/ok (was instantly-breached on board via capturedAt fallback). Unified on _work_item_sla answer.
- OPERATIONAL NOTE: :8000 runs WITHOUT --reload → serves old serializer until human restarts it. Console shows empty chips meanwhile. DO NOT restart it ourselves.
- FULL GATE: 2358 passed (+11), 12 skipped, 1 FAILED test_job_claim::test_two_claimers_never_take_same_job → DIAGNOSED: two native `python -m worker` (kb-index SKIP LOCKED drainers, port-less so absent from brief) steal the synthetic job mid-race. Environment lottery, not a regression (baseline runs predate... they passed twice by luck). Passed count UP, nothing deleted.

## CYCLE 5 — test_job_claim hermeticity — LANDED
- Diff: exactly backend/tests/test_job_claim.py (+239/-36; my re-run: 1 passed 6.16s).
- Mechanism: window minimisation (3-party barrier, conns pre-opened) + proof-based detection (blocking FOR UPDATE post-read under lock_timeout + visible + lockable signals) → LOUD skip naming worker contention ONLY when foreign theft provable; else original assertions run. Negative-control testing caught and fixed a detector false-excuse (probe_gate lock). Assertions byte-intact (verified via grep on diff).
- 6 consecutive green runs vs LIVE workers; siblings audited (6 tests) — none implicated, none changed; scratch rows cleaned up.
- Follow-up queued: probe job should be own throwaway kb_documents row (live worker would really reindex on a bucket-enabled box).

## CYCLE 6 — inr-grouping-split [P4, db.py] — LANDED
- Diff: db.py _inr rewritten (Indian grouping; None→"—"; ₹-12,34,567 sign-inside to match client's exact node output) + NEW tests/test_money_formatting.py (16 boundary cases). No FE change needed — verified server==node en-IN literals.
- Sweep found 6 more Western formatters (queued as P2-batch) + no-op .replace typo at customer_insights.py:46. Declined to fix in-scope: needs shared money module + circular-import care. Correct restraint.
- Targeted: 16 + 103 passed. FULL GATE running now (db.py touched → mandatory).

## CYCLE 7 — authority-matrix-reimplemented-in-ts [P4, FE] — RUNNING
- Job: Customer-360 Authority panel consumes GET /authority/next (main.py:4712, orphaned); delete hardcoded matrix from customerInsights.ts:200-240; mock mirrors backend rules incl. 11 escalate reasons; honest pending/unavailable states.
## CYCLE 8 — morning-batch-audit + qa-trend-unrounded-floats [P3] — FIXING
- 19:40 IST resume after ~11h idle. Tree had GROWN: 558 dirty paths vs ~270 at c7. A batch of work landed 09:16–10:34 IST (another session; change-log shows QA sweeps until ~19:05) implementing most of my queue.
- MY AUDIT (all verified independently):
  - money_inr.py shared module wired into ALL 7 call sites incl. context.py/talk.py/enact.py/narrate.py/scoring.py/customer_insights.py → P2 Western-grouping batch DONE by batch.
  - webhooks P1 REAL: webhooks_dispatch.py (HMAC-signed POSTs keyed on sha256(secret), SSRF re-resolve + private-IP refusal — loopback receivers correctly impossible), payments.py dispatches dispute.created/payment events inside txn, bot_worker.py:145 drains via process_one (SKIP-LOCKED claim/settle/reclaim). Legacy simulated rows remain in log only.
  - vitest NEW in Habibi (`npm test`): 54 tests / 4 files green. FE tests exist for contactability pill + billing compact etc.
  - Integrations PoolHealthStrip renders live key-pool health (azure 1/1, dg 2/2, cartesia 5/5, honest "No key configured" for gladia/speechmatics).
  - :8000 was RESTARTED by someone today → cycle-4 SLA fields NOW SERVED (sla=breach, label "724h 39m over") and disputes board chips match API byte-for-byte → c4 pending item CLOSED.
  - /agent-studio index: Recent changes viewer live ("chain verified · 5"), matches GET /agent-studio/change-log hashes/seqs.
  - Bot detail: Bindings tab (2 tenant-inherited bindings + resolution explainer), Change log tab (chain intact, per-publish facets/gates/hashes), Evals tab with CritiquesPanel ("Skill critiques — never written to a skill", honest empty state), Outbound tab Reach pane mounts NumberPoolTable (empty state verified in code; API [] live).
  - /qa Disagreements view: honest explicit empty state ("a real result, not an empty screen").
- Lint regression found+fixed BY ME pre-Claude: 2 prettier errors in agent-studio.index.tsx (morning batch left them) → eslint --fix, back to 0err/62warn baseline.
- TOOLING NOTE (not app bug): drive_preview mouse clicks silently no-op on TAB STRIPS (/qa tabs, studio side-tabs) while keyboard Enter + real OS clicks work; mid-page row clicks land fine. Also pane driver can wedge (actions report success, content frozen; close/open_preview resets). Verify tabs via keyboard or computer_use native clicks.
- BUG FILED TO CLAUDE (one task): qa-trend-card section breakdown prints raw floats ("72.66666666666667") — AgentTrendCard.tsx:69 {s.value} unformatted while sparkline uses toFixed(0); aggregation in qa-seed.ts is correct sum/count. Fix label render only; bars keep exact fractions. Prompt: .loop/prompts/cycle8_task.txt.
- ~6:10am quota hit mid-cycle, but post-mortem showed implementation COMPLETE: authority.ts (+493) client+mock; authority-policy.ts extended (was pre-dirty, invisible to porcelain diff); customerInsights.ts matrix DELETED (tombstone); OverviewTab.tsx + CustomerContextPanel.tsx wired to useAuthorityNext/applyAuthority.
- MY verification: typecheck/lint/build green; live GET /authority/next?customerId=anita-desai → cap_inr ₹250 + talkTrack; console Authority panel renders EXACTLY that verdict + shadow banner. Old TS copy had said Escalate for same customer — drift resolved in server's favour.
- Residuals CLOSED by me: pending/unavailable states exist in AuthorityPolicyBlock.tsx (explicit state machine, honest copy); dark-theme safe by construction (all design tokens, no raw hex). Visual dark eyeball remains as low-priority filler only.
- LESSON REINFORCED: judge partial cycles by CONTENT (grep imports/usages), never by porcelain diff alone or single-string greps — tombstone comments masquerade as dead code either way.
- FULL GATE post-cycle-6: 2375 passed (+17 vs baseline), 12 skipped, 0 failed. Job-claim passed in-suite — hardening held.
- Reset timer: proc_3425ab69b5fd, sleep 12300 from ~6:24am → fires ~9:41am IST.
- C8 FIX LANDED+VERIFIED: Claude edited ONLY AgentTrendCard.tsx (+7/-3: Math.round label, text-[11px]→text-body-tiny tokens, prettier wrap); zero new paths vs before_c8 snapshot, 0 deletions repo-wide. MY LIVE REPRO: /qa→Agent Trends→card shows 73/86/83/80/77 integers; bars keep exact fractions (width expr untouched). Gates: typecheck ✓ lint 0err/62w ✓ vitest 54/54 ✓ build ✓. Claude honestly reported no regression test (no jsdom dep) + no playwright — acceptable, render-site format.

## CYCLE 9 — webhooks-page-full-audit — LANDED (page PASS, zero product bugs)
- Scope: /webhooks operator surface for the newly-real dispatch pipeline. Cross-checks UI↔API: 1 endpoint (Core CRM, active, 5 events), 2 deliveries/24h, 100% success — all match GET /webhook-endpoints + /webhook-deliveries.
- Flows verified: New-endpoint sheet (opens; Create correctly disabled until name+URL+event; full form: target/signing/event groups/retry/headers). CREATE verified end-to-end in CLEAN BROWSER (browser_exec): POST /webhook-endpoints exact payload → toast "Created QA Loop Receiver" + secretOnce shown once w/ Copy action → list refetch. Drawer: health (Success 24h/7d 100%, p95), Subscribed events, Retry policy summary, tabs incl. Delivery log + Signing. TEST FIRE verified: drawer Test fire tab → Send test delivery → POST /webhook-endpoints/{id}/test?event=call.completed → toast "→ 200 · 63ms". DELETE verified via API (200) after cleanup; server restored to Core-CRM-only.
- THE 3-STRIKE SAGA RESOLVED: preview pane failed to create endpoint 3x (silent closes/no-ops). Clean-browser arbitration proved APP CORRECT — all 3 were drive_preview pointer artifacts in the sheet region (run1 likely hit Cancel/backdrop = silent dismiss, exactly reproducible symptom). Pattern now confirmed across tab strips AND sheets: mouse no-ops/misaims while keyboard + real clicks work. NOT an app bug class; do not file to Claude off pane-driver symptoms alone — arbitrate in browser_exec first.
- Residuals (small): Delete confirm-dialog UX not observed (overlay stack contamination from wedged pane driver — recheck fresh); delivery-log filter combos untested; Event catalog popover unchecked; Rotate/Pause deliberately not fired against seed endpoint (state-churn caution).

## CYCLE 10 — billing-display-defects x3 + infra repair — LANDED
- INFRA: Claude CLI broke mid-session (self-update left 500B placeholder bin/claude.exe → "native binary not installed"); discovery run died at startup. Fixed via `node node_modules/@anthropic-ai/claude-code/install.cjs` (337MB real binary, v2.1.241, probe OK). Discovery audit REQUEUED.
- /billing audited UI↔API (GET /billing): 3 real display defects found+filed; 1 candidate dropped by code check ("24.1minute" = text-extraction artifact of ml-050 margin — real spacing fine).
- Claude fixed all 3: (1) BudgetPanel alerts {a.when}→formatKbDate → "21 Jul 26"; (2) ServiceCostTable Δ renders "—" when prev===0&&cost>0 (changePct sentinel exposed as fabricated +100%; contract untouched); (3) unit-cost sites inr()→inrCompact() sub-rupee precision (₹0→₹0.0667, ₹1→₹1.29/1.43 real rates now visible; also ServiceDrawer). inrCompact ladder itself upgraded: one-decimal L/Cr suffixes, epsilon floor "<₹0.0001" instead of fake zero — mirrors backend money_inr.py::inr_compact.
- MY VERIFICATION: served modules show all three changes; live /billing shows 21 Jul 26 / — column / ₹0.0667·₹1.29·₹1.43·₹0.0017. Gates: vitest 56/56 (+2 new for inrCompact), typecheck ✓, lint 0err/62w ✓, build ✓.

## CYCLE 10 (cont) — untouched-area discovery audit (voice/, skills/, connectors/) — DONE
- 15 findings, evidence-quoted, in out/cycle10.txt. TOP: [P1] voice/bot.py:1815 CRM persist failure swallowed → call proceeds unrecorded; [P1] crm_sink.py:1241/:585/:653 queued CRM jobs silently discarded when interaction_id unset; [P1] connectors/persist.py:252 httpx.post w/o SSRF guard while webhooks_dispatch.resolve_public_host exists (169.254.169.254 passes _https_ok); [P2] bot_tools.py:174 paylink read bypasses approval+circuit; [P2] connectors/persist.py:95 default id not tenant-scoped → PK violation for 2nd tenant; [P2] skills/runtime.py:71 DB fail→silent disk-defaults fallback can RE-GRANT removed tools; [P2] lint.py lint_pack dead code; [P2] bot_tools.py:799 dispatch drops model args; [P2] sign.py dev-key fallback; [P3] scripts.py contact-window drift (10-19 vs db 9-20); [P3] intersect.py bare except strips ext.* tools on DB blip; + perf/dead-code/test-gap notes.

## CYCLE 11 — voice-crm-unrecorded-call + crm-sink-silent-drop + connector-ssrf — LANDED
- First attempt died on network (ENOTFOUND) mid-run, leaving partial edits; ALSO the Claude placeholder-binary breakage RECURRED (self-update at 04:00 rewrote bin/claude.exe to 500B stub) — repaired again via install.cjs; resumed with explicit build-on-state note.
- Diff scope vs before_c11: session.py (+crm_degraded field), bot.py (mark_crm_degraded on bind failure + teardown minimal row), crm_sink.py (CRM_DEGRADED_DISPOSITION, mark_crm_degraded w/ logger.error, _note_dropped rate-limited per-session drop logging w/ per-kind totals at teardown, unrecorded-call guard at :328), connectors/persist.py (_validate_url -> resolve_public_host w/ connector_url_private_forbidden / https_only / unresolvable codes; blocked URL = clean error result NOT circuit-breaker count), NEW tests test_connector_ssrf_guard.py (DNS mocked like test_webhooks_dispatch) + test_voice_crm_degraded.py. 562 dirty paths (+4).
- GATES: full suite run1: 2518 passed/1 failed (test_decision_intelligence_p0 sweep test); that test passes solo x4 and in combo with new tests (62 passed) -> suspected env lottery; full rerun: 2519 passed / 12 skipped / 0 FAILED. Baseline held (+24 vs 2495). No FE changes this cycle.

## CYCLE 12 — paylink-bypass + connector-id-collision + skills-fail-open — LANDED
- Three P2s from discovery filed+fixed: (1) bot_tools.py get_customer_context now routes paylink read through connectors.dispatch (approval+circuit enforced; graceful omit on rejection); (2) connectors/persist.py default id tenant-scoped -> no PK collision on second tenant same slug, upsert still idempotent per tenant; (3) skills/runtime.py DB-fault path FAILS CLOSED (logger.error + return []), disk-defaults fallback removed on this path — no silent re-grant of removed tools.
- New tests: test_connector_governance.py (10) + test_skill_packs_fail_closed.py (5, asserts pack_for_slug NOT consulted).
- MY VERIFICATION: scope check — only the 4 permitted files changed (runtime.py M + 2 new test files beyond c11 state); grep confirms dispatch import at :177/:179, fail-closed comment+return [] at runtime.py:74-82. FULL SUITE: 2535 passed / 12 skipped / 0 failed (+16).

## CYCLE 13 — dispatch-args-dropped + dev-signing-key + corrupt-pack-substitution — LANDED
- Findings 8/9/13 fixed: (1) bot_tools.py:799 dispatch now threads parsed model args into JSON-RPC arguments (merged over always-present customer_id; backwards compatible; new test_connector_dispatch_args.py); (2) skills/sign.py — missing SKILL_PLATFORM_KEY earns built-in dev key ONLY in explicitly non-prod APP_ENV, else raises naming the var (new test_skill_signing_key.py); (3) skills/persist.py — corrupt signed pack row is TERMINAL for that slug (skipped, logger.exception kept); disk packs only fill slugs with NO signed row. End-to-end test asserts removed tool (create_promise_to_pay) stays absent while healthy slugs keep grants.
- Scope check: only sign.py+persist.py M and 2 new test files vs before_c13.
- MY RERUN of full suite: 2567 passed / 12 skipped / 0 failed (matches Claude's run).
- NEW LEAD (Claude-flagged, queued): vault/seal.py:20 reads SKILL_PLATFORM_KEY as VAULT_MASTER_KEY fallback — same committed-constant exposure via another door.
- Remaining open from cycle10 discovery: findings 1, 2, 5, 7, 10, 11, 12, 14, 15.

## CYCLE 14 — contact-window-drift + intersect-bare-except + vault-key-fallback — LANDED
- Fixes: (1) NEW leaf backend/contact_window.py — single source of the preferred-window rule; db._outside_preferred_window now delegates, skills/scripts.py copy DELETED and imports shared rule (drift 10-19 vs 9-20 resolved; db default authoritative); (2) skills/intersect.py bare-except -> logger.error + compile-issue sink threaded through cards/compile.py (DISCLOSED out-of-scope touch, required) so a DB blip during compile surfaces "connector tools unavailable" instead of silently stripping ext.* tools; (3) vault/seal.py SKILL_PLATFORM_KEY fallback REMOVED — VAULT_MASTER_KEY only, dev-key allowed solely under declared non-prod APP_ENV, else RuntimeError naming the var (.env.example + docs/ops/vault-inventory.md corrected accordingly — disclosed).
- New tests x3: test_contact_window_shared.py (one verdict both entry points), test_connector_bind_degrades_loudly.py, test_vault_master_key.py.
- Scope check vs before_c14: exactly the delta Claude reported. seal.py importing _env_name from skills/sign flagged by Claude as debt (env allowlist should live in env_utils).
- GATES: run1 2606 passed/1 failed (test_kb_speculation debounce — passes solo x3 + full-file; kb-index worker race class per c4 note); MY RERUN FULL: 2607 passed / 12 skipped / 0 FAILED. Baseline held (+40 vs cycle-7 gate 2567... actually +40 vs 2567 = 2607).

## CYCLE 15 — env-helper-promotion + g10-crash + job-claim-cleanup — LANDED
- (1) env_utils.py gains public NON_PROD_ENVS/env_name/allows_dev_key; seal.py+sign.py import from there (vault no longer reaches into skills private); new test_env_name_shared_helper.py. Claude flagged usage_meter.py:257 has its own _env_name copy — left (outside scope), queued as one-line follow-up.
- (2) G10 get_connector DB failure now degrades loudly via issue-sink (fail on real authoring issues; warn "connector lookup unavailable — ext.* gates skipped" and publish NOT blocked when only the lookup dies); new test_g10_connector_lookup_degrades.py.
- (3) test_job_claim probe ALREADY had own throwaway kb_documents row (precondition met); residual fixed: forensic SELECT...FOR UPDATE no longer shares a txn with DELETEs — nested best-effort re-sweep prevents lock_timeout rollback leaking probe job+doc into shared DB.
- Scope: exactly env_utils.py M + 2 new tests vs before_c15.
- MY RERUN FULL SUITE: 2646 passed / 12 skipped / 0 failed. Matches.

## CYCLE 16 — dup-registry-read + paylink-tenant-leak + dead-linter-wired — LANDED (FINAL for this run)
- (1) connectors/persist.py bound_tool_names: list_connectors() called ONCE, both maps built from it; slug resolution pinned by counting-stub test. (2) first_party.paylink_status now tenant-scoped (cross-tenant customer_id == unknown-id result; same-tenant positive kept; tenant_context.bind proves predicate real). (3) lint_pack wired into create_draft_skill + upsert_skill_from_pack + editor PATCH + import + gardener drafts + first-party seeding: unknown_tools/malformed_tool_name REJECT, other findings attach as non-blocking lintWarnings + logger.warning; test asserts every first-party pack passes its own linter.
- Scope vs before_c16: exactly first_party.py M, lint.py M, 2 new tests. persist.py dedup folded into pre-dirty state.
- MY RERUN FULL SUITE: 2658 passed / 12 skipped / 0 failed (+12). Matches Claude verbatim.
- STOP POINT per human: "complete with this cycle... then i am going to test it manually."

## CYCLE 17 — usage_meter env fold + circuit-breaker coverage — LANDED (killed-run recovered)
- Claude run was killed externally mid-flight; partial edits were complete + green (46 targeted tests passed). Scope: usage_meter.py (env helper folded onto env_utils), connectors/circuit.py, NEW test_connector_circuit.py + test_usage_meter_billing_env.py. Full-suite verification absorbed into C18 gate.

## CYCLE 18 — CORE-FLOW P1: sandbox inbound dead at turn 1 (skillSlug 422) — LANDED
- USER DIRECTIVE: from now on the loop focuses on CORE AGENTIC functionality: tools use, latency, inbound E2E, outbound E2E, edge cases. Live browser testing is the primary instrument.
- FOUND LIVE: /sandbox Prompt rehearsal — EVERY customer turn POSTed 422 extra_forbidden body.skillSlug; conversation dead after greeting; zero bot replies. Root cause = 3-layer contract drift: FE api/sandbox.ts always sends skillSlug; sandbox_runtime.py:442 reads it (mouth_turn_state active_slug); schemas.py SandboxTurnCreateRequest (extra=forbid) omitted it. No backend test posted the real browser body.
- FIX: schemas.py +skillSlug field; NEW tests/test_sandbox_turn_schema.py (6 tests incl. junk-extra still 422). MY GATES: full suite 2709/1flaky -> RERUN CLEAN 2710 passed/12 skipped/0 failed.
- LIVE VERIFY (clean browser): API restarted with fix -> turn now 200 in 10.8s; bot replies grounded in HDFC Collections Policy (1 chunk, 7979ms, 1338t); turn2 ombudsman threat -> 6.6s, auto-escalate guardrail fired correctly ("routing to Tier 2"), grounded in FAQ chunks. INBOUND FLOW RESTORED END-TO-END.
- EDGE CASES OBSERVED (queued for next cycles): (a) missing-recording-disclosure flag fires on BOTH turns — greeting includes disclosure text but flag still set; either disclosure-detection or the greeting template needs reconciliation; (b) turn2 showed "0 chunks" while grounding chips list 3 FAQ refs — chip/count mismatch to investigate; (c) latency variance 3.0-10.8s per turn — measure p95 across scenarios.

## CYCLE 19 — disclosure-false-positive + grounding-count-mismatch — LANDED
- Both core-flow telemetry defects from live sandbox testing fixed: (1) guardrails.py — strict _DISCLOSURE_RE (subject+modal+recorded patterns; "record your promise to pay" NOT a disclosure) + public mentions_recording_disclosure(); channels answer "disclosed on this CALL?" from history incl. greeting; crm_sink pinned to same predicate (single definition, test-enforced). False positive on every greeted run eliminated; undisclosed+dues still fires. (2) sandbox chunkIds/chunks unified through append_sandbox_turn — footer count == chips count, asserted for FAQ-only/real-chunk/ungrounded turns.
- Scope vs before_c19: agent_core/{__init__,guardrails}, sandbox_runtime.py, Habibi api/sandbox.ts + NEW tests both sides. Claude used --model opus --effort medium per user directive.
- MY VERIFICATION: vitest 62/62 (5 files) ✓, typecheck ✓, MY full pytest rerun: 2731 passed / 12 skipped / 0 failed. Claude's flake note accepted: inspect.getsource-based tests fail if source edited mid-run (turn_start_and_call_identity reads crm_sink.py source).
- CORE-FOCUS NEXT: latency p95 measurement across scenarios (queued), outbound E2E via campaigns surface, tool-use edge cases (authority/waiver paths), escalation journey.
cycle 20 notes: disclosure fix verified live (flag gone); latency sample 8.4s/1315t/1chunk; NEW EDGE: waiver-blocked guardrail halts run after agent offered escalation - turn2 POST never fired; need policy check halt-vs-warn

## CYCLE 21 — waiver-blocked-fires-on-refusal [P1 core-flow] — LANDED
- Live-caught: bot gave CORRECT refusal+escalation, guardrail flagged waiver-blocked (mention regex), run HALTED, customer dead-ended. Root cause: mention-match cannot distinguish promise from refusal.
- FIX (guardrails.py +115): commitment detector — first-person agent voice + promise verbs, per-sentence scoping; refusal cues suppress (cannot/unable/requires approval/supervisor/escalat*); later-sentence-refusal still flags if promise stands earlier. Gates kept: neverPromiseWaiver, intent gate, goodwill escape, flag name, should_halt membership.
- 21 new tests in test_guardrail_violations.py (verbatim live refusal -> no flag; promises -> flag+halt).
- MY RERUN: 2751 passed / 12 skipped / 0 failed. Scope: guardrails.py + tests only.
- OPEN (queued): Hinglish promise detection gap (lexicon.py has multilingual machinery); prompt.py:89 + live_qa/checks.py:291 copy still describes old mention semantics.


## CYCLE 22 — turn-latency telemetry + budget regression test — LANDED
- sandbox_runtime.py: per-stage perf_counter instrumentation (retrieval/chat/persist) with greppable INFO breakdown; NEW tests/test_turn_latency_budget.py (7 tests): non-LLM overhead budget (~3x calibrated median), aggregate==sum integrity invariant, stage<=total guards. Measured: enrichment analyze_turn ~1.15s ON CRITICAL PATH — flagged as biggest available win (allow_llm=False exists; move off reply path or overlap with retrieval).
- MY RERUN: 2758 passed / 12 skipped / 0 failed.
- QUEUED NEXT: enrichment off critical path; outbound E2E live sweep; Hinglish waiver-promise gap.


## CYCLE 23 — enrichment off critical path — LANDED
- Design: OVERLAP (prefetch understanding with retrieval, collect before persist) behind SANDBOX_ENRICHMENT_ASYNC=1 default ON; turn.py gains optional understanding= param (disclosed out-of-scope touch, inline call preserved for all other callers). Measured: +21.9ms visible vs +485.7ms before (500ms enrichment); one-analysis-per-turn guard; enrichment lands in response AND rows.
- NEW tests/test_turn_enrichment_overlap.py (6 tests, three-config comparison). Scope delta: turn.py M + new test file only.
- MY RERUN: 2763 passed/1 ERROR cross_tenant add_lead_followup-args7 -> passes solo + whole-file (32 passed) = collection-time flake class, not regression. Net passed 2763 >= prior 2758.


## CYCLE 24 — outbound decision-core audit (report-only) — DONE, findings in chat tail
- Audit completed by Claude but the full file was NOT written to .loop/out/ (only stdout tail captured). Key findings from its report: compliance vetoes (DND/opt-out/hours/window/caps) enforced at DIAL TIME on both paths — correct design. ALL five gaps live in campaigns.process_one + cadence.process_one — the only untested functions in the chain:
  #3 cadence.py:409-418 retry that fails to place strands the case permanently (safe to fix)
  #5a cadence.py:304 pausing a campaign does not stop already-opened ladders (safe)
  #5b missing tests for both orchestration functions (stops recurrence; safe)
  #1, #2, #4 = ranked lower / need human judgement (Twilio spend shape).
- NEXT CYCLES: fix #3, then #5a+#5b with tests, defer spend-shaped items.
- NOTE: audit text lost (stdout-only). Future report-only tasks must write to a file explicitly.


## CYCLE 25 — pause-does-not-stop-ladders + stranded-retry — LANDED
- cadence.py: paused campaign gates ladder firing within one poll (paused runs ordered LAST not filtered - starvation test; _PAUSE_LOGGED dedupe; only 'paused' gates, 'finished' deliberately doesn't); placement-failure path requeues with next_attempt or exhausts on last attempt, ERROR logged, max_attempts respected on failure path. 7 new tests in test_cadence_pause_and_strand.py.
- MY RERUN: 2771 passed / 12 skipped / 0 failed. Scope: cadence.py + new tests.
- REPORT-ONLY leftovers queued: process_one happy path never checks max_attempts pre-dial; outbound.place 'never raises' contract unenforced (to_e164/engine.begin can throw) and campaigns.process_one calls it undefended.


## CYCLE 26 — place-contract + pre-dial-ceiling — LANDED
- outbound.py: place() contract made TRUE — operational failures (to_e164, DB) return structured failure + ERROR naming campaignRunId/context (reserve() now returns those, additive); programming errors still raise. campaigns.process_one benefits without change (it was the undefended caller; state=dialing committed before place).
- cadence.py: pre-dial max_attempts ceiling -> STATE_EXHAUSTED via cycle-25 mechanism, INFO logged, last rung still placed (comparison matches on_outcome).
- NEW test_place_contract.py. Scope: outbound.py M (pre-dirty absorbed), cadence.py M (absorbed), new tests.
- MY RERUN: 2783 passed / 12 skipped / 0 failed.
- REPORTED NOT FIXED (queued): state_write_failed double-dial window needs reconcile-by-callSid; number-pool lookup swallows bugs (contract-compliant); to_e164 not libphonenumber.


## CYCLE 27 — inbound live-call resilience audit (report-only) — DONE, full report .loop/out/cycle27_voice_audit.txt
- Pattern: anything reachable from the SANDBOX is well-built+tested; everything only happening on a REAL carrier leg is unhandled+untested (dead air = exception, driven by real incidents).
- TOP 8 GAPS: G1 STT-death invisible to watchdogs -> 180s dead line + borrower blamed (CRITICAL, needs-human); G2 zero ErrorFrame consumers in voice/ (CRITICAL, needs-human); G3 Twilio reconnect -> duplicate interaction + PTP idempotency defeated via interaction_id-keyed key (HIGH; part-a provider_call_id-keyed fix nearly mechanical but touches money=human); G4 verified caller hung up by verify_attempts counter / silent mid-call rebind (SAFE half: re-entry guard; rebind policy human); G5 idle strikes reset on VAD start -> noisy line burns slot to duration cap (needs-human); G6 committed write w/ interrupted confirmation never reconciled (mechanism exists _live_correction run_llm=False; entity-list decision human); G7 concurrent tool calls race ToolState/node (Flows semantics human); G8 transcript not PII-redacted while tool args are (SAFE-AUTO-FIX: pii_redact.redact_text on text_content).
- NEXT CYCLES: apply SAFE fixes G4-counter + G8 with tests; queue human list for Susanth.


## CYCLE 28 — verified-caller-hangup + transcript-PII — LANDED
- G4 counter half: _verify_identity_handler short-circuits when session.identity_verified already True (no attempt increment, no terminate_politely/handoff on a verified borrower); unverified path byte-identical.
- G8: append_transcript_turn now redacts text_content via persist-local redaction (digit-runs >=7 -> bullets + last 2; rationale pinned: above amounts/4-digit tails, below 10-digit mobiles, matches _mask_phone keep-2). No existing test assertions affected (transcript tests INSERT raw SQL, bypassing the write path - noted as fixture-evidence gap).
- MY RERUN: 2791 passed / 12 skipped / 0 failed. Scope: voice/{tools,persist}.py M + 1 new test file.
- STILL NEEDS-HUMAN (cycle 27): G1 STT-death watchdog policy, G2 ErrorFrame consumer/call-ending policy, G3 reconnect dedupe + provider_call_id-keyed PTP idempotency (money), G4 rebind policy, G5 VAD-vs-transcript strike reset, G6 interrupted-confirmation entity list, G7 Flows multi-node semantics.


## CYCLE 29 — PTP idempotency keyed to carrier call (G3a) — LANDED
- voice/tools.py _create_ptp_handler: key now voice-ptp:{provider_call_id or interaction_id}:... — reconnect-minted interaction no longer defeats dedupe; old-format rows keep keys (no migration). Pre-fix revert check: tests 1+4 fail without the change (load-bearing, not vacuous).
- NEW test_voice_ptp_idempotency.py (4 tests through production entry point build_tools->handler->domain->db_tx real rows).
- MY RERUN FULL: 2795 passed / 12 skipped / 0 failed.
- QUEUED G3b-family: flag_dispute/request_callback/request_documents voice-* keys still interaction_id-scoped (lower money-relevance); test_idempotency.py:71 docstring stale.


## CYCLE 30 — sibling voice-write keys to provider_call_id — LANDED
- flag_dispute/request_callback/request_documents keys now provider_call_id-scoped w/ interaction_id fallback; suffixes unchanged; test_voice_ptp_idempotency.py -> test_voice_write_idempotency.py covering all 4 tools.
- MY RERUN FULL: 2811 passed / 12 skipped / 0 failed.
- Deploy-window caveat noted (in-flight call replay gets one extra row; pre-existing).
- CORE-LOOP STATE: inbound E2E restored+instrumented, latency telemetry+budget, outbound decision core hardened (pause/strand/place-contract/ceiling), live-call resilience safe-fixes applied (verify re-entry, transcript PII, PTP+sibling idempotency). REMAINING NEEDS-HUMAN: G1 STT-death policy, G2 ErrorFrame consumer, G3b reconnect interaction dedupe, G5 VAD-vs-transcript strikes, G6 interrupted-confirmation entity list, G7 Flows multi-node semantics.

