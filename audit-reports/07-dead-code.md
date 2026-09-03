# 07 — Dead code and reachability forensics

Habibi does not have a large proven-dead application surface. What looks unused is usually a decorator, a string registry, a file route, a skill pack on disk, or a migration still in progress. The honest leftovers are a superseded brand mark, an unread pair of factory-flag wrappers, a TTS sync module that was never wired in, a shadcn kit that nothing in the product imports, and several dual paths the ADRs have already decided to retire.

**Do not delete anything in this report solely because a scanner could not find a reference.** Confirm dynamic loading, config, and CI before any removal.

## Verdict

| Class | Count of named findings | What it means here |
| --- | --- | --- |
| **A** Proven dead | 1 | Authors documented it unused; no import found |
| **B** Highly likely dead | ~12 units | No refs, dynamic use unlikely, or retirement already decided but code still sits |
| **C** Possibly dead | kit + dual paths | Dual implementations, scaffolding, shadcn inventory |
| **D** Static-analysis false positive | many | Looks unused; actually reached |
| **E** Dynamically referenced | many | String/importlib/file-route/DB class path |
| **F** Unknown | HTTP surface, coverage | Needs traffic or a completed tool run |

Highest-confidence cleanup, if product agrees:

1. `Habibi/src/components/brand/BigBoundMark.tsx` plus `.bb-mark` CSS (**A**).
2. `backend/provider_voice_sync.py` is implemented and never called by admin/worker sync — wire it or drop it (**B**).
3. `AGENT_CARDS_ENABLED` / `campaign_runtime_enabled()` wrappers have no production call sites (**B**). Cards compile regardless; outbound is gated by the Postgres `outbound.enabled` switch, not the campaign env flag.
4. Unused shadcn modules and their exclusive npm packages are kit leftovers (**C**, not a deletion mandate).

## Method

Five read-only analysts (TypeScript, Python, tests, dynamic-loading, legacy) plus a parent pass that re-checked the high-signal claims.

| Tool / search | Outcome |
| --- | --- |
| Knip (`npx knip` in `Habibi/`) | Available (v6.34.0). Full run did not finish. Not used as evidence. |
| Vulture | `[tool.vulture]` in `backend/pyproject.toml`; **vulture is not in `requirements.txt`**. Not run. |
| Ruff | CI runs `ruff check .` in backend. Config warns not to auto-fix unused names that are re-exports. |
| Import / reference search | Scoped greps under `Habibi/src` and `backend/` (full-tree grep hangs on `.venv` / `node_modules`). |
| Route discovery | TanStack `routeTree.gen.ts` + FastAPI `@app.*` on `main:app` (no `include_router`). |
| CI | `.github/workflows/backend-pytest.yml`, `frontend-typecheck.yml`. |
| ADRs | Tool Grant one-owner and cardless deny-all are accepted in code comments; `docs/adr/` files were not opened in this pass (path listing timed out). Runtime still implements the old behaviour. |

**Trees in scope:** `Habibi/` (TanStack Start + Vite + React) and `backend/` (FastAPI, workers, voice, Alembic). No Next.js. No Celery. No Django.

**Trees treated as noise:** `backend/.venv/`, `Habibi/node_modules/`. Vulture config already excludes `.venv/` and `alembic/`.

## Classification key

| Code | Meaning | Deletion? |
| --- | --- | --- |
| **A** | Proven dead — documented unused and no static or dynamic reference | Candidate, still grep CSS/Storybook first |
| **B** | Highly likely dead — no refs, dynamic use unlikely, or retirement decided | Candidate after the listed runtime/config check |
| **C** | Possibly dead — dual path, kit, scaffolding, or CLI-only | Product decision; not a scanner verdict |
| **D** | False positive — scanner would flag it; it is used | Keep |
| **E** | Dynamically referenced — registry, importlib, file route, DB class path, CLI | Keep |
| **F** | Unknown — evidence missing | Do not delete |

---

## Do not delete (reachability map)

Static tools will flag these. They are live.

### Backend — **E** / **D**

| Unit | How it is reached |
| --- | --- |
| `@app.get/post/...` in `backend/main.py` (~314 handlers) | FastAPI decorator registration. Vulture already ignores `@app.*`. |
| `agent_core/cards/__init__.py` PEP 562 `__getattr__` exports (`compile_card`, `AgentCard`, bot IDs) | Lazy `importlib.import_module`. TYPE_CHECKING re-exports look F401-dead on purpose. |
| `agent_core/providers/factory.py` `_import_class` + `registry.py` `service_class` | DB/seed strings such as `voice.tts_pool.KeepAliveAzureTTSService`, `agent_core.providers.fish_service.FishTTSService`. |
| `bot_tools.py` `HANDLERS` / `execute_tool` | Tool name → function. |
| `voice/tools.py` `tools` dict + `ALWAYS_ON` | Voice tool registry. |
| `agent_core/skills/scripts.py` `SCRIPTS` | `run_skill_script(name)`. |
| `agent_core/skills/packs/*/SKILL.md` | Filesystem scan (`iter_first_party_packs` / `pack_for_slug`). |
| `agent_core/connectors` first-party `ext.*` tools | Name dispatch (`ext.paylink.*`, `ext.lms.*`). |
| `voice/bot.py` `_RUN_BOT_MODULES` | Warm `importlib.import_module` at boot. |
| `voice/flows.py` vs `flows_dynamic.py` | Selected by `VOICE_FLOW_GRAPH` (`legacy` / `hub` / `db` / `auto`). |
| `work_runtime/adapter_temporal.py` | Imported when `temporal_enabled()` is true. Stub by design (raises `temporal_adapter_not_promoted`). Flag **is** read in `work_runtime/api.py`. |
| `mcp_server.py` / `mcp_tools.py` | Separate process (`python -m mcp_server`), not mounted on FastAPI. |
| `backend/alembic/versions/*.py` | Alembic revision graph. |
| `backend/sql/*.sql` | Empty-DB bootstrap; CI applies these then `alembic stamp head`. Parallel to Alembic, not abandoned. |
| `seed_susanth.py` | Imported by `seed_postgres.py`. CI cannot seed without `WHATSAPP_TEST_TO` because this path is unguarded. **Not dead.** |
| `scripts/dial_test.py` | Manual CLI (`python -m scripts.dial_test`). Name matches pytest `*_test.py` so collection may import it; it defines no tests. |
| `bot_*` modules and `identity.bot_id` | Glossary: “bot” is the legacy spelling, still used for identifiers and tables. Not a dead path. |

### Frontend — **E** / **D**

| Unit | How it is reached |
| --- | --- |
| `Habibi/src/routes/*.tsx` and `*.lazy.tsx` | TanStack file routes; `routeTree.gen.ts` does `.lazy(() => import(...))`. |
| `/prompt-studio` | Compat redirect to `/agent-studio`. `prompt-studio.lazy.tsx` still owns `PromptStudioPage` for `/agent-studio/$botId`. |
| `@pipecat-ai/client-js`, `@pipecat-ai/small-webrtc-transport` | Dynamic `import()` in `useSandboxLiveCall.ts`. |
| `Habibi/src/data/agent-tuning.ts` | Static imports from sandbox UI and `api/voice-sandbox.ts` (not only dynamic). |
| `Habibi/scripts/*.ts` (`export-seeds.ts`, etc.) | CLI (`npx tsx`), not app-imported. |
| `@/components/charts` barrel | Used by dashboard charts (`RecoveryTrendChart`, `CallVolumeChart`, …). Leaf modules are live. |
| `@/components/ui/spinner` | Imported by live `button.tsx`. |
| `@/components/ui/button` | Used across feature components. |

### Flags that are read (not obsolete because default-off)

Defined in `backend/agent_core/platform_flags.py`. Defaults off is the factory contract, not evidence of death.

`MCP_HTTP_ENABLED`, `MCP_CLIENT_ENABLED`, `MCP_TASKS_ENABLED`, `MCP_APPS_ENABLED`, `A2A_ENABLED`, `EVAL_GATE_ENABLED`, `REDTEAM_GATE_ENABLED`, `OUTBOUND_EVAL_GATE_ENABLED` (G-OB9 in `cards/compile.py`), `LLM_GATEWAY_ENABLED`, `VISION_INGEST_ENABLED`, `POLICY_EXPORT_ENABLED`, `TEMPORAL_ENABLED` (selects the Temporal stub), `VOICE_FLOW_GRAPH`, `BOUNCE_VOICE_ENABLED`, DB `outbound.enabled`.

---

## Findings

### A — Proven dead

| Path | Unit | Evidence | Check before delete |
| --- | --- | --- | --- |
| `Habibi/src/components/brand/BigBoundMark.tsx` | `BigBoundMark` | File comment: “Kept on disk, unused by shell chrome. Live mark is `EqualizerMark`.” Only other hit is that comment in `EqualizerMark.tsx`. No component imports. | Remove paired `.bb-mark` rules in `styles.css`. Confirm no Storybook/marketing import outside `Habibi/src`. |

`backend/dashboard_calc.py` (mock dashboard) is **already absent locally**; GitHub `main` may still have it. Not a local deletion candidate.

### B — Highly likely dead / unread

| Path | Unit | Evidence | Check before delete |
| --- | --- | --- | --- |
| `backend/provider_voice_sync.py` | `run_sync` and vendor fetchers | Built to fill non-Azure `tts_voice_catalog`. Admin `POST /tts-voices/catalog/sync` and `scripts/sync_tts_voices.py` call `tts_catalog_sync.run_sync` (Azure) only. Has `if __name__ == "__main__"` CLI. | Ask operators whether anyone runs `python provider_voice_sync.py`. Better product fix may be wiring it into the existing sync path rather than deleting it. |
| `backend/agent_core/platform_flags.py` | `agent_cards_enabled()` / `AGENT_CARDS_ENABLED` | Defined, in `.env.example`, tested in `test_platform_flags.py`. No production caller under `agent_core/`, `main.py`, `voice/`, `bot_runtime.py`. Cards compile regardless. | Search docs/runbooks/other branches. Removing the name from the locked flag list is a deliberate contract change. |
| `backend/agent_core/platform_flags.py` | `campaign_runtime_enabled()` / `CAMPAIGN_RUNTIME_ENABLED` | Documented in `.env.example` as cadence/campaign dialer. No hits in `main.py`, `worker.py`, `bot_worker.py`, `voice/`, `outbound.py`, `mission.py`. Master outbound switch is Postgres `outbound.enabled`. Not even in `test_platform_flags.py`’s parametrize list. | Confirm no `os.getenv("CAMPAIGN_RUNTIME_ENABLED")` in a process not searched; confirm product still wants this as a future gate vs dead wrapper. |
| `backend/agent_core/tools/grant.py` | `ToolGrant` | Docstring: “Nothing imports this yet.” Production runtimes still call `intersect.effective_tools` / `offered_tools`. Tests import it (`test_tool_grant.py`, characterization). In-progress migration (ADR-0001), not abandoned. | Do not delete. Migrate call sites; then delete the old formulas, not this module. |
| `backend/agent_core/skills/runtime.py` | `mouth_turn_state` | Docstring: no runtime calls this; kept for tests that pin fail-closed pack resolution. No refs in `voice/` or `bot_runtime.py`. Stale comment in `cards/__init__.py` still mentions a voice import that is gone. | Drop with the grant-migration tickets once tests stop projecting through it. |
| `Habibi/package.json` | `date-fns` | No `from "date-fns"` under `Habibi/src`. | Confirm scripts/tests; then drop. |
| `Habibi/package.json` | `liveline` | Chart components named Liveline* are hand-rolled SVG. No `from "liveline"`. | Confirm; then drop. |
| `Habibi/package.json` | `@hookform/resolvers` | No imports. | Tied to unused `ui/form.tsx`. |
| `Habibi/package.json` | `@pipecat-ai/client-react` | No import. Live path uses `client-js` + `small-webrtc-transport`. | Confirm comments/docs only. |
| Exclusive deps of unused shadcn wrappers | `embla-carousel-react`, `input-otp`, `react-day-picker`, `recharts`, `vaul`, `react-hook-form` | Each only imported by an unused `components/ui/*` module (see C). | Delete wrapper and dep together, or keep as kit. |
| `backend/tests/test_migrations.py` | `test_alembic_upgrade_downgrade_roundtrip` | `@pytest.mark.skipif` unless `RUN_ALEMBIC_ROUNDTRIP` ∈ {1,true,yes}. CI sets `RUN_ALEMBIC_ROUNDTRIP: "0"`. **Never runs in CI.** `test_alembic_has_exactly_one_head` still runs. | Intentional opt-in, not a dead file. Enable on a scratch DB if you want the roundtrip gated. |

### C — Possibly dead / dual / kit / scaffolding

| Path | Unit | Evidence | Check before delete |
| --- | --- | --- | --- |
| `Habibi/src/components/ui/{menubar,navigation-menu,hover-card,aspect-ratio,carousel,input-otp,breadcrumb,pagination,calendar,form,chart,drawer,context-menu,progress,scroll-area,avatar,radio-group,toggle,toggle-group,link}.tsx` | shadcn inventory | No imports from `Habibi/src/routes`. Typical Lovable/shadcn dump. **Spinner and button are live — not in this list.** `calendar` is mentioned only in a comment in `agent-studio.index.tsx`. | Product: keep as kit vs prune. `sideEffects: false` already tree-shakes unused modules from the bundle. |
| Matching Radix packages | `@radix-ui/react-{menubar,navigation-menu,hover-card,aspect-ratio,context-menu,progress,scroll-area,avatar,radio-group,toggle,toggle-group}` | Only referenced by the unused wrappers above. | Same kit decision. |
| `Habibi/src/components/records/index.ts` | barrel | Feature code imports leaf files (`RecordsTable`, …), not `@/components/records`. Leaves are live. | Optional tidy. |
| `Habibi/src/components/ui/button.tsx`, `badge.tsx` | shadcn variant aliases | Comment: kept so existing call sites compile; Phase 3 codemod target. | Finish the codemod first. |
| `backend/voice/spike.py` | V0 latency probe | `python -m voice.spike`. In `ruff.toml` E402 ignores. Not in compose / `run_stack.ps1`. | Ask whether latency probes still use it. |
| `backend/tests/test_tool_grant_characterization.py` | scaffolding suite | Header: “SCAFFOLDING — delete this file in #13, with the formulas it pins.” **Still collected and run.** Permanent twin: `test_tool_grant.py`. | Delete only with the old formulas. |
| Cardless fail-open | `skills/runtime.py` `has_grant`; `bot_runtime.py`; `sandbox_runtime._SANDBOX_TOOL_NAMES`; `voice/tools.py` when `allowed_tool_names is None` | ADR-0002 decided deny-all; code still fail-opens. Characterization tests pin the difference. | Inventory mouths with empty `agent_card` before flipping. |
| `VOICE_FLOW_GRAPH=legacy\|hub` + `voice/flows.py` | hardcoded / hub experiment | Kill-switch and merged hub still selectable. Default `auto`. Bot may build hardcoded then replace with authored. | Read deployed env and sandbox `flowGraph` overrides. |
| Triple always-on tools | `voice/tools.py` `ALWAYS_ON`; `grant.py` `VOICE_ALWAYS`; `flow_graph._FLOW_CONTROL_TOOLS` | Intentional temporary duplication; ticket #9. | After grant owns the floor. |
| `Habibi/src/routes/prompt-studio.lazy.tsx` `legacyShipBaseline` / `legacyShipEdit` | pre-card mouth editor | Active when `!cardIsAuthored`. Tied to compile G0 “empty agent_card — legacy mouth”. | Re-verify no published/draft versions with empty cards. |
| `main.py` voice WS `?proxy_secret=` | query-string auth | Header/path secret preferred; query form kept; Twilio Stream cannot use query (31920). | Audit Stream URLs still using query form. |
| `dev-up.ps1` vs `run_stack.ps1` vs compose | three stack starters | README calls host Python via `dev-up` “legacy local”; all three documented. | Team convention, not dead code. |
| Fish S1 vs S2 TTS | `fish_tts.py` / `fish_service.py` | S1 syntax called “legacy”; default S2. OpenRouter is failover, not a duplicate abandoned client. | Check bindings still on `s1`. |

### D — False positives (corrected against the analysts)

| Claim that looked dead | Actual class | Why |
| --- | --- | --- |
| `seed_susanth.py` unused personal fixture | **D** | `seed_postgres.py` imports and calls it. CI comment: seed dies without `WHATSAPP_TEST_TO` because this path is unguarded. |
| `ui/spinner.tsx` unused | **D** | `button.tsx` imports `Spinner`. Buttons are used widely. |
| `@/components/charts` barrel unused | **D** | Dashboard charts import it. |
| `TEMPORAL_ENABLED` unread | **E** | `work_runtime/api.py` imports `temporal_enabled` and loads `adapter_temporal` when on. The **adapter** is a stub (**B** as a product path, **E** as a flag). |
| `/prompt-studio` dead route | **D** | Always redirects; still the URL compatibility shim. Do not delete `prompt-studio.lazy.tsx` — it exports `PromptStudioPage` for agent-studio. |
| `sql/*.sql` abandoned because Alembic exists | **D** | CI applies SQL then stamps Alembic. Numbering gap `20260722_0015` is cosmetic (`0016.down_revision = 0014`). |
| Multiple `*policy*` modules | **D** | Different locked engines (contact, treatment, authority, live QA, reco, handoff). |
| `Habibi` vs `habibi` | **D** | Windows case-insensitive; one tree. |
| Azure OpenAI vs `llm_gateway` | **E** | Kill-switch coexistence, not a leftover client. |
| Offer reco vs treatment | **D** | Different products (NBO vs next-best treatment). |

### F — Unknown (do not treat as dead)

- Whether any FastAPI handler is uncalled by the UI or by Twilio/webhooks. Proving that needs a client call-graph or traffic, not Python imports.
- Per-export unused symbols inside large files (`prompt-studio.lazy.tsx`, `agent_studio` API, `treatment`).
- Whether `TREATMENT_MANDATE_RAIL_MODULE` names an external adapter in some deploy (no in-repo `present`).
- Tenant DB rows: provider `service_class`, MCP connectors, webhook `event_types`, published cards, `prompt_versions.flow` node keys.
- Full knip / vulture / coverage reports (tools did not complete or are not installed).
- Tests targeting deleted production modules (no `pytest --collect-only` in this environment).

---

## Tests — what actually runs

| Surface | Runner | CI | Reachability notes |
| --- | --- | --- | --- |
| Backend | pytest defaults (`test_*.py`) under `backend/` | `backend-pytest.yml` when `backend/**` changes | Installs `requirements-voice.txt`. Seeds demo. Ruff + SQL apply + Alembic stamp. |
| Frontend | vitest `src/**/*.test.ts(x)` | `frontend-typecheck.yml` when `Habibi/**` changes | 11 suites. Typecheck + vitest + lint. |
| E2E | none found | — | No Playwright/Cypress. |

**Proven never in the automated matrix (A for CI, not for the file):** Alembic upgrade/downgrade roundtrip (`RUN_ALEMBIC_ROUNDTRIP=0`).

**No unconditional skips/xfails/`.skip` found** in backend tests or vitest.

**Path-filter gap (B for cross-stack guards):** `test_agent_card_schema_drift.py` / `test_language_registry_drift.py` live in backend tests but guard Habibi files. A Habibi-only PR does not run them.

**Pipecat `importorskip`:** many voice tests skip without voice deps. CI installs them; local API-only installs will not collect those modules.

**`scripts/dial_test.py`:** collect noise (pytest `*_test.py` pattern), zero tests, **E** as a manual dial CLI.

Shared fixtures in `backend/tests/conftest.py` (`db_tx`, `card_and_packs`, `api_headers`, autouse KB/treatment switches) are used. No unused helper module was proven.

---

## Unused dependencies

### Frontend (`Habibi/package.json`) — **B** unless noted

| Package | Class | Why |
| --- | --- | --- |
| `date-fns` | **B** | No app import |
| `liveline` | **B** | Name collision with hand-rolled charts |
| `@hookform/resolvers` | **B** | No import |
| `@pipecat-ai/client-react` | **B** | Comment only |
| `embla-carousel-react`, `input-otp`, `react-day-picker`, `recharts`, `vaul`, `react-hook-form` | **B** if wrappers go; **C** if kit stays | Only unused `ui/*` consumers |
| `@pipecat-ai/client-js`, `@pipecat-ai/small-webrtc-transport` | **E** | Dynamic import |
| Used Radix / TanStack / xyflow / sonner / cmdk / lucide | **D** | Live |

### Backend pins — none proven unused

Spot-checked: `tiktoken` → KB chunking; `minio` → storage; redis/websockets → voice; prometheus/sentry → observability; `requirements-voice.txt` → voice image / tests; `requirements-mcp.txt` → optional MCP process.

Do not remove redis/websockets/tiktoken/fastembed because the API process does not import them — other processes/images do.

`pipecat-ai-flows` and the Speechmatics extra are **deliberate omissions**, not dead weight. `[tool.vulture]` without vulture in the pin set is a config leftover (**C**).

---

## Dual paths the ADRs already decided to retire

These are live, not dead. Deleting the old side now would change production behaviour.

1. **Tool Grant (ADR-0001).** `ToolGrant` exists; runtimes still use `intersect` formulas. Characterization suite is the bridge. Sequence: migrate call sites → delete old formulas + `test_tool_grant_characterization.py` → keep `test_tool_grant.py`.
2. **Cardless deny-all (ADR-0002).** Module denies; text/sandbox/voice still fail-open when there is no card. Flip only after mouths have cards.
3. **`VOICE_FLOW_GRAPH`.** `legacy`/`hub` vs authored DB graph. Both builders are used. Remove hardcoded `flows.py` only after every prod mouth has a compilable authored graph and no sandbox override uses `legacy`.

---

## Commented-out code, `*_old` modules, abandoned experiments

- No `*_old` / `*_legacy` / `*_deprecated` module filenames found in hot paths.
- No large commented-out function dumps found in sampled `voice/` / `agent_core/` files (**F** for an exhaustive dump search — `.venv` noise blocked a full-tree pass).
- `voice/spike.py` is the explicit abandoned-experiment shape: kept as a manual probe, not on the product path (**C**).
- Empty `backend/_tmp_import_graph_out/` (if still present) is an analysis artifact (**C**).

---

## Recommended next checks (not deletions)

1. Run knip with `--exclude` for generated route trees, and vulture with the existing `pyproject.toml` exclude list, **outside** `.venv`. Treat hits as hypotheses; walk this report’s **E** map before acting.
2. `SELECT` mouths/deployments with empty or missing `agent_card` (validates ADR-0002).
3. Read deployed `VOICE_FLOW_GRAPH` and sandbox session overrides.
4. Decide whether `provider_voice_sync` should be wired into `/tts-voices/catalog/sync` or removed.
5. Decide whether unread `AGENT_CARDS_ENABLED` / `CAMPAIGN_RUNTIME_ENABLED` wrappers stay as reserved names or leave the locked list.
6. Finish Tool Grant tickets before deleting `ALWAYS_ON`, cardless fallbacks, `mouth_turn_state`, or the characterization suite.
7. If pruning shadcn: delete wrapper + exclusive npm dep together; leave `button`, `spinner`, and any Radix package a live wrapper still imports.

## Caveats

- Knip and vulture did not produce a certified unused-export list in this environment.
- Full-repo glob/grep timed out on vendor trees; searches were scoped.
- “No import found” is never sufficient for **A** when the unit is named in a registry, seed, card, skill pack, env flag, or generated route tree.
- Local tree can diverge from GitHub `main`; this report is for the local checkout dated 2026-09-02.
