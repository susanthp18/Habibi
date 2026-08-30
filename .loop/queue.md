# BigBound Queue — ranked (from Cycle 1 discovery, evidence in out/cycle1.txt)

## Done
- [x] [P1] treatment-console-absent — Cycle 2 LANDED.
- [x] [P2] contactability-browser-tz — DONE cycle 3.
- [x] [P4] authority-matrix-reimplemented-in-ts — DONE cycle 7 (server verdict live on Customer-360; drift resolved).
- [x] [P4] dispute-sla-computed-twice — DONE cycle 4. :8000 restarted by morning session → fields SERVED, board chips match API. CLOSED cycle 8.
- [x] [P4] inr-grouping-split — DONE cycle 6 (_inr → Indian grouping, 16 boundary tests).
- [x] [P2-batch] Western-grouped formatters (context.py/talk.py/enact.py/narrate.py/scoring.py/customer_insights.py) — DONE by morning batch: shared backend/money_inr.py wired into all 7 sites; verified cycle 8 audit.
- [x] [setup] vitest for Habibi — DONE by morning batch: `npm test` live, 54 tests green; verified cycle 8.
- [x] [P4] inr-compact-drift — DONE by morning batch: billing-seed.ts inrCompact rewritten (lowercase k, sub-rupee honest path) + billing-seed.test.ts; verified cycle 8 audit.
- [x] [S] whatsapp-fallback-template-env-dead — DONE by morning batch: promise_fulfillment.py reads WHATSAPP_FALLBACK_TEMPLATE_* + test_whatsapp_template_fallback.py.
- [x] [P1] webhooks-never-fire — DONE by morning batch: webhooks_dispatch.py (HMAC-signed POSTs, SSRF guard, txn-safe enqueue) wired from payments.py business events; drained by bot_worker.py:145 process_one. Verified cycle 8 audit (code+API+worker chain). Live-fire vs loopback impossible BY DESIGN (SSRF guard refuses private receivers) — POST mechanics covered by tests.
- [x] [P1] provider-pools-and-bindings-dead — DONE by morning batch: PoolHealthStrip mounted on /integrations (renders live key-pool health incl. honest "No key configured"); BindingsTab on agent-studio bot detail. Verified cycle 8 in browser.
- [x] [P1] number-pool-health-invisible — DONE by morning batch: NumberPoolTable on Outbound→Reach pane; loading/empty/error/data states all present in code; API returns [] live today. Visual-in-place check blocked only by pane-driver wedge (tooling), not app.
- [x] [P1] agent-change-log-has-no-viewer — DONE by morning batch: "Recent changes" viewer on /agent-studio index ("chain verified · 5") + per-bot Change log tab with facets/gates/hashes; matches API byte-for-byte. Verified cycle 8.
- [x] [P1] eval-critique-and-disagreement-queues-orphaned — DONE by morning batch: CritiquesPanel in Evals tab + DisagreementsView tab on /qa (honest empty state). Verified cycle 8.

## Queued
- [P2-batch] connector/skill hardening (cycle 10 discovery): bot_tools.py:174 paylink read bypasses approval+circuit breaker (route via dispatch); connectors/persist.py:95 default conn id not tenant-scoped -> PK violation for 2nd tenant; first_party.py paylink_status missing tenant predicate (cross-tenant read); skills/sign.py dev-key fallback trusts forgeable sigs when SKILL_PLATFORM_KEY unset; bot_tools.py:799 dispatch drops model args; skills/runtime.py:71 DB-fail fallback to disk defaults can re-grant removed tools (fail closed + log); intersect.py:108 bare except silently strips ext.* tools (surface as compile warning).
- [P3] contact-window-duplicated-drift — skills/scripts.py DEFAULT_WINDOW 10:00-19:00 vs db._outside_preferred_window 9-20; same promise date gets two verdicts. Move pure rule to shared module, import both sides.
- [P3] skills/persist.py:635 corrupt signed pack degrades to unsigned disk pack under same slug (skip slug instead).
- [P4] connectors circuit breaker zero test coverage incl. fail-closed-forever branch (unparseable timestamp should mean open-expired not permanent block).
- [cleanup] voice/spike.py dead (329 LOC, no importer); connectors seed_first_party() zero callers (would hit PK bug if called); latency.py shim only used by spike+bot.
- [test-gap] voice/{usage,call_export,mesh_bus,ws_proxy,rtvi_events,llm_pool,log_bridge,workers/insurance}.py untested.
- [x] [P3] qa-trend-unrounded-floats — FIXED cycle 8 (AgentTrendCard label → Math.round; bars keep exact fractions; gates green; live-verified).
- [follow-up] test_job_claim probe should create its own throwaway kb_documents row — live worker really reindexes on a bucket-enabled box.
- [P5-residual] Authority panel dark-theme VISUAL eyeball (states verified in code; low priority filler).
- [P5 x62] react-hooks/exhaustive-deps warnings — a few per cycle, never all at once.
- [x] Discovery audit cycle10 findings 3,4,5,6,8,9,10,11,12,13,14 FIXED (cycles 11-16). REMAINING OPEN: finding 1 voice/bot.py CRM-persist swallow (partially: degraded flag landed; abort-vs-degrade policy note), finding 2 crm_sink drop-visibility (DONE c11 - verify), finding 7 lint_pack (DONE c16), finding 15 circuit tests (open). usage_meter.py:257 _env_name copy = one-line follow-up. Studio UI could show skill lintWarnings.

## Not covered yet (future discovery)
- voice/ Pipecat subtree; agent_core/{skills,connectors,vault,live_qa} vs console; sandbox//floor SSE paths.
