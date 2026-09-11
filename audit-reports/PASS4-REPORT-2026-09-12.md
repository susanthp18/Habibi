# Agent Studio pass 4 — report (2026-09-12)

Plan: `snuggly-petting-sonnet.md` (WS1–WS8). 65 commits on `autonomous-modernization`, `14f9109` … `84bb222`, one concern per commit. Nothing pushed (the "honest engines" stream has not committed its 0122). Dev DB stamped `20260912_0135`.

## What landed, by workstream

### WS1 · Regulated residue — 25/25 + the hardening gate
All twenty-five items from report 41, each with the test that would have caught it (SSRF resolve-then-reconnect, the PTP savepoint, WhatsApp identity and sampling, promise local midnight, permissions over role names, savepoints at the three poisoning sites, goodwill decision from the call, the work_runtime lease, ANY→cancelled, evidence-deleting downgrades, the shipped signing key, settle batches, the missing uniques, `calling_window` owner ×9, the Twilio breaker, the insights failure, the hot mic, the idempotency key, "Start call", pool-derived admission, one clock/one environment, carrier I/O after commit, consent and ledger on the hash chain, the KB cache / `last_contact_at` / detached 360 state). The boot gate reads `rls.status()` and the append-only trigger (sql/43); PII column encryption is the one deferred control left.

### WS2 · The fleet is live on the dev stack
`voice/flows.py` deleted; the conversation is `agent_core/cards/graphs/{collections,insurance,supervisor}.json`; every member has a published graph; G-F1 (closure) and G-F3 (identity before writes) added; `scripts/fleet_parity.py` reports 4/4; `FLEET_ENABLED=true`, `DOOR_ENABLED=true`. Fallout found and fixed this pass (`dbe98d5`): an unauthored `entry_node` used to land a hop on the member's greeting — the compiler's default is now `flow_graph.business_entry` (the rule the seeding script had derived on the side), and the Door is the voice channel default, so the fleet index has one entry and kaia is reached through it. Decision kept: edges stay implicit (`TRANSITIONS` is the declared data); Phase-3 publish/deploy split not built.

### WS3 · The wire contract is a totality
- **169 → 0** routes without `response_model`; **42 → 0** `dict[str, Any]` route bodies; 16 non-JSON routes declare `response_class` and sit in `_UNTYPED_BY_DESIGN` (checked for staleness). Models written from the builders' keys, checked live (0 dropped keys) and against the frontend (`tsc` green). The two baseline files are deleted.
- **51 → 0** transaction-owning handlers, **18 → 0** inline SQL in routers: `db_outbound.py`, `db_compliance.py` (new), `bank_boundary.api.read/write`, `platform_switches.read_all/flip`, `payments.open_hosted_intent/complete_hosted_intent/record_provider_payment`, `delivery_receipts.record_twilio_sms_status`, `db_inbox.get_eval_report`, `db.list_role_grant_rows`. `tests/test_db_layering.py` walks every router with `ast`.
- HTTP-layer tests for `POST /webhooks/payments/{provider}`, `GET|POST /webhooks/whatsapp`, `GET /pay/{token}`, `POST /pay/{token}/complete`, plus the five moved routes.

### WS4 · db.py is the CRM kernel
6,871 → **2,836 lines**: `db_handoff`, `db_leads`, `db_documents`, `db_callbacks`, `db_violations`, `db_consent`; strays moved (voice counts → `db_prompt_studio`, `_TRACE_MAX_TURNS` → `db_trace`); `schemas` imported lazily. `test_db_layering` pins ≤ 3,200 and that no `db_*.py` binds `engine` from `db_core`. `followups_db.py` was **not** absorbed: despite its name it holds coaching/calibration/redaction/export accessors.

### WS5 · The giants
- **Pins first**: `tests/test_voice_tool_schemas_snapshot.py` (full-grant registry, every collections node as compiled, `TRANSITIONS`) and `tests/test_run_bot_pipeline_snapshot.py` (the real `run_bot` under a fake transport: eleven stages, handlers, flow entry, context roles). Both byte-identical before and after every move.
- `run_bot` 2,100 → **54 lines** over `voice/bot_{flow,pipeline,handlers}.py` (`1e883cc`).
- `publish_prompt_version` → `_freeze/_compile/_deploy/_record` (43-line orchestrator); `compile_card` → five gate phases over one state, emission order pinned on the four cards (`3734586`).
- `AgentCardPanels.tsx` 1,139 → 33 (six `panels/*Tab.tsx`); `prompt-studio.lazy.tsx` 1,876 → 1,402 with `studio/{useStudioDraft,useStudioQueries,PromptStudioShell,FlowTabBody}` (`c371f52`).
- **Deferred**: `voice/tools.py build_tools` → package, and `bot_runtime._handle_turn` split. Both files carry the other stream's uncommitted hunks (`kb.llm_payload`, the run-up); a split now would either carry their work into my commit or strand it. They are the first thing after that stream's 0122 lands; the snapshot pins are already in place for them. The ≤400-line route target was not reachable by pure moves (a reducer is a design change).

### WS6 · Studio residue
Seven vocabularies with one owner and a drift test each (`tests/test_studio_vocabulary_drift.py`, proven red on a probe); the browser's drifted tuning presets deleted; `fallbackLanguages` and `maxTurns` connected; the stripped CRM globals named in `flow_graph` and warned by G16; attach/detach endpoints, `shadow?` fields and the `is_cardless` prose deleted; G9/G10 surfaced; trust items (forms, slug pre-check, bounded upload, `health='blocked'` with sql/45, Hear-tone params); `policy_export` emits the real DND rule, calling windows and the card's gates. **Skipped** (held files): WhatsApp `maxSeconds`, `bot_runtime`'s disclosure detector, `voicemail.max_sec`, `voice.pauseMs` (on `VoiceConfig`, read by the SSML preview), the TTS preview language, `CONTEXT.md` lines 39/66.

### WS7 · Transport and types
`apiPatch/apiDelete` take a schema; zod schemas on customers/promises/consent/handoff/outbound written from the backend models (types widened where the wire was looser); `no-seed-imports.test.ts` pins the api modules. pyright basic on `agent_core/{tools,cards,fleet}`, `outbound.py`, `flow_graph.py`, `policy_rules.py` — 35 real Optional leaks fixed, green, in CI; `contact_policy.py` (18 findings, held) joins when its edits land. Source-text pins ratcheted at 105 (`test_no_new_source_pins.py`).

### WS8 · Envelope
Role-split worker services under the `split-workers` profile; idle backoff; `request_id` on the three job tables (sql/44) and in the text log line; Prometheus in the dev overlay (`up{job="habibi-api"}==1`); Dockerfile `USER app` + `cap_drop: [ALL]` (images rebuilt, stack healthy); one price book; `ALLOW_ACTOR_HEADER` off by default; `.env.bak.reco` gone. **Finding**: a migrate-from-empty CI job is not honest here — the initial commit's `sql/` already carried what migration 0003 adds (verified: baseline sql + `alembic upgrade head` fails at 0003). The mirror pairing (`test_every_mirrored_sql_file_has_exactly_one_migration`) is the drift check that can be kept true.

## Verification
- `test_route_structure`, `test_db_layering`, both snapshots, `fleet_parity` 4/4, `eval_gate_preflight` clean, `rls.status()` enforcing 222/222, pyright 0 errors, `tsc` 0, vitest (api + studio) 81/81, `npm run build` ✓.
- Full backend suite (voice container, 20 min): **4,260 passed, 73 skipped, 25 failed** (1 deselected). Full vitest: **209/209** (35 files).
- The 25: `test_treatment_followthrough` ×18 — the dev DB carries 211 live-mode `wait` decisions the labeller has never attributed because the stack runs with `TREATMENT_LABELS_ENABLED` unset (the engines stream's flag; `--purge` clears only SIM rows); `test_honest_engines_w7` ×3 and `test_the_money_path_tells_the_truth` ×1 (the other stream's uncommitted work; the latter passes in isolation); `test_a2a_task_input_required_with_cert`, `test_demo_call_product_fixes_are_wired`, `test_a_lead_with_no_accounts_is_not_settled` (pre-existing, listed below); `test_four_workers_have_healthchecks` was the one real hit from this pass — the pin regexed compose and missed the YAML anchor; it parses now (`26caa18`).
- Known failures not from this pass: `test_phase5::test_a2a_task_input_required_with_cert`, `test_outbound_studio_bindings::test_demo_call_product_fixes_are_wired` (the other stream's `kb.py`), `test_contact_policy::test_a_lead_with_no_accounts_is_not_settled` (FK on leftover sweep claims in the dev DB), `test_honest_engines_w7`, `test_treatment_followthrough` ×2. Frontend `npm run lint` is red at baseline on files this pass did not touch (prettier/CRLF); the files this pass touched are clean.

## Left for pass 5
`build_tools` package and `_handle_turn` split (after 0122); the six WS6 skips above; the prompt-studio route reducer; contact_policy.py under pyright; a live voice dial through the Door (manual); the pre-existing `voice_sessions` volume is root-owned on this laptop (fallback path only — recreate the volume to fix).
