# 17 — Distributed state and cache consistency

**Scope:** `backend/` HTTP, workers, voice process; `Habibi/src` operator UI. `PRAXIST-main/` excluded.
**Date:** 2026-09-02
**Mode:** Read-only. No application file was modified, no migration run, no write issued.
**Method:** five parallel analysts — React state, TanStack Query, backend process state, Redis/cache, database consistency — plus a parent verification pass. Every finding below was re-derived from source. Claims that failed a second source check were dropped or corrected.

Vocabulary is `CONTEXT.md`: Mouth, Agent Card, Skill Pack, Locked Engine, Deployment, Tool Grant, Offer, Gate, Flow, Handoff, Reachability, Mission, Cadence, Outcome. The Inbox sidebar flag `contactableNow` is the **contact Gate** (`contact_policy.evaluate`), not Agent Card Reachability. Those two words are not interchangeable here.

Companion reports: [12-data-model.md](./12-data-model.md) (schema dual-spines, partial uniques), [15-concurrency.md](./15-concurrency.md) (queues, races), [16-performance.md](./16-performance.md) (cache cost, not cache truth), [19-auth-authz.md](./19-auth-authz.md) (grant semantics).

---

## The measurement caveat

No live Redis `KEYS`, no Postgres catalog, no React Query Devtools dump. Docker was not queried this session. Every claim is structural: a named store, the code that reads it, the code that writes it, and the window in which they can disagree.

Three rules:

1. **A cache with a documented TTL is not a bug because it is stale for that TTL.** It becomes a finding when a write path exists and does not bust it, or when two caches of the same fact use different TTLs and different keys, or when a UI treats a projection as the Gate that will actually fire.
2. **Editor local state is allowed.** A Mouth draft in `useState` is not a competing Deployment. It becomes a finding when the editor and the published row are both shown as “what is live.”
3. **Mock seeds are a second universe, not production SoT.** `USE_MOCK` defaults true in dev (`Habibi/src/api/config.ts:11-22`) and is a hard error in production builds. Mock-only localStorage and mutable seed arrays are called out as a developer trap, not as a live split-brain.

Findings are **Confirmed** (code-cited) or **Opportunity**. Nothing below is labelled inconsistent from a runtime trace.

---

## Verdict

**Postgres is the only durable source of truth. Redis is not a cache. There is no second book.**

The split-brain this codebase is capable of is almost entirely **projections that were meant to be disposable and then got read as facts**: process-local TTL maps that writes do not bust, React `useState` copies of loader data, denormalized columns that runtime no longer maintains, and two honest contact-Gate evaluations (WhatsApp vs voice) presented as one operator concept.

What is already disciplined:

- No Redux, Zustand, or domain React Context. Server state lives in one `QueryClient` at the root (`__root.tsx:158`).
- `load_active_bundle` always hits `bot_deployments` + `prompt_versions` (`agent_core/deployment.py:15-93`). There is no in-process Deployment cache.
- `work_items` is a VIEW (`sql/95_views.sql`). Domain tables stay authoritative.
- The contact Gate’s **decision** path counts `contact_events` / `contact_day_counters`, not `channel_consents.used_this_week`. That column is labelled a cache in the DDL (`sql/03_consent.sql:47-48`) and the Python that refreshes it (`contact_policy.py:855-884`).
- At most one published Mouth per bot and one active Deployment per `(bot, env)` (`sql/09_bot_config.sql:139-141,264-266`).
- Voice sandbox sessions moved to Postgres after the file store silently split API and voice (`voice_session_store.py:1-28`).
- TanStack Query mutations almost never optimistic-update. The `onMutate` props on sheets are callbacks named by the page, not React Query rollbacks. There is no optimistic-update bug class here because the class was never adopted.

What is not:

- Customer 360 **detaches** the customer from QueryClient the moment the page mounts, then a goodwill mutation invalidates a query key that **no hook uses**.
- Role-grant writes update Postgres and leave `_perms_cache` holding the old Tool Grant for up to 30 seconds — `invalidate_permission_cache` is test-only.
- The consent screen’s weekly-cap bar is a different number than the Gate that will admit or deny the next send.
- `customers.last_contact_at` is written by seed scripts and never again. Mission already reads `contact_events`. Customer 360 still displays the seed timestamp.
- KB retrieval is cached twice, in two processes, with two TTLs, and ingest does not bust either.

The system does not have conflicting *databases*. It has conflicting *readers*.

---

## Map of stores

| Layer | Where it lives | Survives process restart? | Shared across API / worker / voice? | Role |
|---|---|---|---|---|
| Database | PostgreSQL 16, SQLAlchemy Core | Yes | Yes | Canonical book |
| Redis | `redis:7-alpine`, channel `bigbound.voice.mesh` | No (pub/sub, no domain keys) | Voice + API publish; insurance worker subscribes | Mesh bus only |
| Process memory | Module dicts, LRU+TTL, `lru_cache`, disk `.cache/` | No (disk TTS caches do) | **No** — one copy per process | Performance projections |
| TanStack Query | One `QueryClient` constructed in `getRouter()` (`router.tsx:6-16`), provided at `__root.tsx:158` | No (tab) | n/a (one browser) | Server-state cache |
| React local | `useState` / `useRef` / URL search | No | n/a | UI, editors, **mirrors** |
| React context | shadcn form/chart/carousel + sidebar collapse | No | n/a | Chrome only — **no domain context** |
| Browser storage | `localStorage` keys listed below | Yes (origin) | n/a | Preferences; mock presence |
| Session | `X-API-Key` + optional `X-Actor-User-Id` request headers (`config.ts:49-54`) | No cookie, no `sessionStorage` | n/a | Actor identity is env, not a session store |
| Files | `backend/models/*.json`; TTS `.cache/` | Yes | Only if volume-mounted | ML artefacts; audio bytes |

`REDIS_URL` is injected into `api`, `voice`, and `voice_insurance` (`docker-compose.yml:90,203,237`). The **API process never uses it** — only `voice/mesh_bus.py` and the insurance worker do. `worker` and `bot_worker` do not get the env. Persistence is off: `redis-server --save "" --appendonly no` (`docker-compose.yml:25`). Mesh events are not durable. Comments that recommend Redis (`azure_openai.py:42`, `outbound.py:43,578`, `voice/admission.py:26`) describe a store that was not built.

---

## Census

### React local / context / URL

| Store | Kind | Holds domain data? |
|---|---|---|
| QueryClient defaults | `staleTime: 15_000`, `refetchOnWindowFocus: true`, `retry: 1` | Server cache |
| Router | `defaultPreload: "intent"`, **`defaultPreloadStaleTime: 0`** (`router.tsx:23-24`) | Preload always considered stale — extra fetch, not a second SoT |
| Customer 360 | `useState<Customer>(initial)` copied from the **router loader**, not from QueryClient (`customers.$customerId.lazy.tsx:98-104`) | **Yes — detached mirror** |
| Mouth editor | `prompt` / `persona` / `voice` / `guardrails` / `flow` / `card` useState (`prompt-studio.lazy.tsx:198-231`) | Yes — editor draft, by design |
| Floor | `calls` / `alerts` useState synced from `useFloor()` when `!USE_MOCK` (`floor.tsx:57-69`) | Live: mirror. Mock: independent simulation |
| Inbox | `localSuggestions` / `localDraft` overlay on the cached thread (`inbox.tsx:119-122,156-162`) | Yes — RAG projection |
| Inbox | `conversationPollCount` **module-level** (`inbox.ts:28`) | Poll cadence, not domain |
| Integrations | `localOverrides` mock-only credential edits (`integrations.tsx:64`) | Mock only |
| Inbox | `activeId` useState + URL `conversationId` | Selection — **can disagree** (S15) |
| Context | `SidebarUiContext`, form/chart/carousel internals | Chrome |

`prefetchQuery` / `ensureQueryData`: **0** call sites.

`React.memo`: **0**. Irrelevant to consistency; noted so “unnecessary renders” is not mistaken for a second store.

### Browser storage

| Key | File | Purpose |
|---|---|---|
| `theme` | `lib/theme.ts:33`, `__root.tsx:17`, `animated-theme-toggler.tsx:218` | Preference. **Two writers** of the same key |
| sidebar collapse | `components/shell/sidebar-ui.tsx` | Preference |
| inbox split widths | `SplitPanes.tsx` | Preference |
| notifications-read set | `NotificationsPopover.tsx` | Client-only “read” set — **not** server notifications |
| Mouth editor layout / help / dismiss | VoicePanel, VoiceParamsPanel, PromptEditor | Preference |
| Agent Studio changelog open | `agent-studio.index.tsx` | Preference |
| TTS voice prefs | `lib/tts-voice-prefs.ts` | Preference |
| `habibi.agentPresence` | `api/presence.ts:14-35` | **Mock-only** presence. Live mode uses `agent_presence` |

No `sessionStorage`. No `document.cookie` reads. No IndexedDB.

### TanStack Query

Global: 15 s stale, refetch on focus. Per-hook overrides matter more than the default.

| Query key (prefix) | Freshness | Invalidated by |
|---|---|---|
| `["conversations"]` | `staleTime: 2_000`; poll 4 s / 1.5 s if typing (`inbox.ts:120-135`) | visibility + send/takeover merge |
| `["customers"]` | 30 s (`customers.ts:214-219`) | 360 `refreshCustomer` — **not** goodwill apply |
| `["customer", id]` | **No `useQuery` exists** | OverviewTab still invalidates it (`OverviewTab.tsx:73`) |
| `["customer-insights", id]` | 30 s | 360 mutations; goodwill; lead capture |
| `["treatment-next", customerId, accountId, trigger]` | default 15 s | **not** invalidated by 360 goodwill / insights |
| `["contact-policy", id, channel, purpose]` | stale 30 s, poll 60 s (`contact-policy.ts:56-69`) | none on send (clock-driven) |
| `["floor"]` | stale 2 s, poll 3 s | supervisor action, alert ack |
| `["handoff", …]` | queue/active 5 s; session 2 s while live | claim / wrap-up; `setQueryData` on session |
| `["me-presence"]` | 30 s | `setQueryData` on PATCH success — no invalidate |
| `["kb", …]` | 10–15 s | KB page mutations |
| `["outbound", …]` | campaigns 60 s poll on number-pools | campaign mutations only |
| `["staff"]` | **5 min** | none observed |
| `["agent-studio"]` / prompt versions / `["deployments"]` | default | publish / compile helpers (`prompt-studio.ts:129-138`) |

Polls share a query key per screen (one Inbox poll, one Floor poll). That is not a stampede of duplicate keys. The stampede risk is **backend** TTL expiry (see S5).

### Process-local caches (Python)

| Module | Store | Bound | TTL | Write-bust? | Processes |
|---|---|---|---|---|---|
| `authz.py:646-666` | `_perms_cache` / `_roles_cache` | 512 | 30 s (`AUTHZ_CACHE_TTL_S`) | Function exists; **never called from production** | every process that imports authz |
| `actor_context.py:115-149` | `_user_exists_cache` | `_USER_EXISTS_MAX` | 30 s | `invalidate_user_exists_cache` **never called** | API |
| `kb_retrieve.py:359-428` | result LRU | 256 | 120 s (`KB_RESULT_CACHE_TTL_S`) | **none** (no `clear`) | API, voice, workers that retrieve |
| `azure_openai.py:43-44` | embed LRU | 256 | **none** (size only) | n/a (bytes→vector is a pure function of deployment+text) | each process |
| `policy_rules.py:77-80` | resolved RuleSet | 512 | 60 s | `reset_cache` — tests/seed only | every decision process |
| `platform_switches.py:88-130` | enabled bool | tiny | **2 s** | `set_enabled` calls `invalidate(key)` in **this** process (`:230`) | all four diallers |
| `agent_core/treatment/allocate.py:448-455` | dual prices | 1 | 60 s | `reset_cache` — tests/scripts | worker |
| `voice/kb_enrich.py:84-85` | `KbCache` | 32 | **180 s** | session-scoped | voice |
| `kb_rate_limit.py:26-27,74-101` | deque fallback | window | 60 s | n/a | API, on Postgres failure only |
| `tts_preview_cache.py` / `azure_speech.py` | disk files | 200 MB / 14 d | 14 d | oldest-first eviction | API (preview), voice |
| `agent_core/providers/registry.py:521` | `_RUNTIME_CACHE` | unbounded by class name | none | tests pop | voice |
| `storage.py:22-23` | Minio client | 1 | cfg-key | n/a | |
| `flow_graph.py:856` | `@lru_cache(maxsize=1)` | 1 | process life | restart | |
| `agent_core/sentiment.py:63` | `@lru_cache(512)` | 512 | process life | n/a (pure) | |
| `agent_core/context.py:178` | `@lru_cache(256)` | 256 | process life | restart | |

`compile_agent_studio_card` (`db.py:13372`) is **not** cached. Correct for Gate honesty; cost is report 16.

### Redis

| Fact | Evidence |
|---|---|
| Service | `docker-compose.yml:19-24` `redis:7-alpine` |
| Channel | `voice/mesh_bus.py:21` `bigbound.voice.mesh` |
| Client | Pipecat `RedisBus`; publish-only on the API (`mesh_bus.py:42-46`); insurance worker reads (`voice/workers/insurance.py`) |
| Fallback | `_LocalBus` in-process if `REDIS_URL` unset or init fails |
| Domain keys | **None found** — no `SET`/`GET` of customer, grant, bundle, or KB |
| Persistence | Default Redis ephemeral. A mesh miss drops a specialist-handoff **event**, not a ledger row |

### Database projections (not caches in RAM, still copies)

| Copy | Canonical | Refresh |
|---|---|---|
| `channel_consents.used_this_week` | `COUNT` of `contact_events` last 7 local days | `_refresh_used_this_week` on `admit()` only; failure swallowed (`contact_policy.py:1005-1012`) |
| `contact_day_counters.outreach_sessions` | reservation for the daily cap | `admit._reserve_day` `FOR UPDATE`. Evaluate reads the same table (`_today_count`, `:368-379`) |
| `accounts.outstanding` | operational balance | Updated with ledger inserts in `payments.py:187`, `authority/enact.py:179`, bounce fee `payment_events.py:317` |
| `ledger_entries.balance` | intended running total (`DATA_MODEL.md`) | **Writers leave it NULL** — INSERT lists `id, account_id, type, description, amount, posted_at` (`authority/enact.py:163-165`) |
| `customers.last_contact_at` | should be last outreach | **No runtime `UPDATE`**. Seed only (`seed_postgres.py:752`). Mission already queries `contact_events` (`mission.py:179-217`) |
| `customers.dnd` | denormalized DND | Contact Gate uses `channel_consents`. Inbox uses `dnd` only if `evaluate` throws (`db.py:8601-8605`) |
| `mcp_connectors.tools_cache` | last successful tools/list | Written in `agent_core/connectors/persist.py:309` |
| `prompt_versions.agent_card` jsonb | the card on that version | Compile derives Tool Grant; does not persist the grant |
| `treatment_model_registry` | champion/challenger ledger | Reco still loads `models/propensity.json` from disk (`agent_core/reco/models.py:237`) |

---

## Canonical source of truth (per entity)

Read this table left to right. Anything in “forbidden as truth” is a projection that has been observed being treated as live.

| Entity | Canonical | Legitimate projection | Forbidden as truth |
|---|---|---|---|
| Customer | `customers` | `GET /customers/:id` loader; list `["customers"]` (skinny) | 360 `useState` after a mutation that did not `fetchCustomer`; mock `customer360-seed` |
| Account / rupees owed | `accounts.outstanding` | Voice `VoiceSession.outstanding` for **this call only** (`voice/session.py:54`) | `ledger_entries.balance`; 360 state after goodwill; client `deriveCustomerInsights` metrics |
| Ledger lines | `ledger_entries` rows | 360 ledger tab from customer payload | |
| EMI | `emi_installments` | | |
| Bounce / payment event | `payment_events` | | |
| Promise / PTP | `promises` | `work_items` view | |
| Dispute, callback, document, lead | those tables | `work_items` view | |
| Channel consent | `channel_consents.status` (+ purpose) | | `customers.dnd` except evaluate-failure fallback |
| Weekly touches | `contact_events` (`_week_counted`) | `used_this_week` **display** | Consent UI using `usedThisWeek` as the Gate |
| Daily outreach cap | `contact_day_counters` | | Re-counting events for the daily cap (evaluate does not) |
| Contact Gate (now) | live `contact_policy.evaluate` / `admit` | RQ `["contact-policy", …]` (30–60 s); Inbox `contactableNow` (up to 4 s, **WhatsApp**) | 360 pill (**voice**) treated as the same flag; mock `_veto` port in live mode |
| Conversation | `conversations` + `messages` | RQ `["conversations"]` | `mergeThreads` preserved RAG chips; `localSuggestions`; mock `inbox-seed` mutated in place |
| Connected session | `interactions` (+ transcript) | Floor / Handoff snapshots | Treating `call_attempts` as “the” session |
| Unanswered / suppressed dial | `call_attempts` | | |
| Outcome | attempt/interaction outcome columns the closer writes | Cadence readers of that code | Inbox thread `status` (`bot`/`assigned`) — that is handler, not Outcome |
| Mission | mission assembly at dial + `call_attempts.objective` | | Campaign row without an attempt |
| Cadence | cadence case table / closer | RQ `["outbound", "cadence"]` 15 s | |
| Mouth draft | `prompt_versions` `status=draft` after autosave; editor useState before | | Showing draft as Deployment |
| Mouth published | `prompt_versions` unique published per bot | | |
| Deployment | `bot_deployments` unique active per `(bot_id, environment)` | `load_active_bundle` (uncached read); canary `pick_deployment_id` | Compile preview; sandbox `resolve_prompt_bundle` without a deployment |
| Agent Card | `prompt_versions.agent_card` on the version being shipped | Editor `card` useState | Published card while a draft is open (they fixed this once; keep it) |
| Tool Grant | compile of card + packs + channel at the turn | | Offer (may only shrink the grant) |
| Skill Pack | skills tables | | |
| KB passage | indexed chunks for the Deployment’s `kbSnapshotId` | result cache ≤120 s; voice `KbCache` ≤180 s | Cache after reindex of the **same** snapshot id |
| Authz / operator Tool Grant | `role_permissions` ∪ `user_roles` | `_perms_cache` ≤30 s | Cache after `PATCH /roles` |
| Presence | `agent_presence` | RQ `["me-presence"]` | `localStorage habibi.agentPresence` in live mode |
| Theme | `localStorage theme` + `documentElement.classList` | `useSyncExternalStore` | |
| Operator session | request headers / API key map | | Browser session |
| Outbound kill switch | `platform_switches` row; absence = off | 2 s process cache | |
| Statutory / client rules | `policy_rule_sets` as-of instant | 60 s process cache | |
| Treatment hold | `treatment_holds` where `released_at IS NULL` | RQ `["treatment-holds"]` | |
| Treatment decision | `treatment_decisions` committed row | RQ `["treatment-next"]` | 360 insights payload after `engine.connect()` rollback |
| Work item | source entity row | `work_items` view | A second work-item table (there isn’t one) |
| Sandbox Live session | `voice_sandbox_sessions` | file backend only when Postgres unreachable | Split file+Postgres |
| Mesh Handoff event | Redis pub/sub (ephemeral) | local bus | Using the bus as session SoT |
| Propensity / treatment estimators | `treatment_model_registry` champion | `models/*.json` on disk as the **load path** | Assuming the file and the registry row match after a train that did not register |
| MCP tool list | live tools/list | `tools_cache` jsonb | |
| KB rate limit | `kb_rate_limit_counters` | process deque if the counter write fails | |

---

## Confirmed findings

### S1. Customer 360 holds a detached copy of the customer, and goodwill busts a query that does not exist

**Where:** `customers.$customerId.tsx:22-25` (loader), `customers.$customerId.lazy.tsx:98-121`, `OverviewTab.tsx:67-73` · **Confirmed**

The detail route loads `GET /customers/:id` in the **router loader**, copies it into `useState`, and never registers `["customer", id]` with QueryClient. `refreshCustomer` invalidates `["customers"]` (the **list**) and `["customer-insights", id]`, then `fetchCustomer`s into `setCustomer`. PTP / dispute / document / call mutations go through that path.

Goodwill does not. `applyMut.onSuccess` invalidates:

- `["authority-next", customerId]` — real
- `["customer-insights", customerId]` — real
- `["customer", customerId]` — **no `useQuery` in the tree uses this key**

After a waiver, `accounts.outstanding` and `ledger_entries` have changed (`authority/enact.py:163-185`). The 360 header, ledger tab, and `deriveCustomerInsights` fallback still render the **useState** customer. Insights may refetch (new NBA, new metrics) while the rest of the page still shows the pre-waiver outstanding. Two numbers on one card, both labelled as this borrower.

`noteMutation` patches `notes` in useState and does not refresh the list either — acceptable for notes, same pattern.

**Conflict:** Postgres vs React local vs a dead QueryClient key. Severity **P1** (operator money display, not the waiver write).

---

### S2. Permission and user-exists caches are never busted on the write that changes them

**Where:** `db.py:473-508` `replace_role_permissions`; `authz.py:652-666`; `main.py:2858` `PATCH` roles; `actor_context.py:121-127` · **Confirmed**

`invalidate_permission_cache`’s docstring says “call after a role change.” Grep of production Python: the only callers are tests. `replace_role_permissions` writes `role_permissions` and returns. For up to `_PERMS_TTL_S` (30 s) every `has_permission` check in **this process** still sees the old grant set.

Workers and voice have their **own** maps. Even a correct API-side invalidate would leave bot_worker and voice stale for the TTL. Today the API does not invalidate either.

Same shape: `invalidate_user_exists_cache` is defined and never called. A deleted user can look existent to `ApiKeyMiddleware` for 30 s.

**Conflict:** `role_permissions` vs `_perms_cache`. Severity **P1** (authz window; companion 19). Instant revoke is not guaranteed.

---

### S3. The consent screen’s weekly bar is not the number the Gate uses

**Where:** DDL `sql/03_consent.sql:25,47-48`; refresh `contact_policy.py:855-884,1005-1012`; Gate `evaluate` `_week_counted` `:382-400,592-594`; UI `FrequencyCapsEditor.tsx:20,39`, `ChannelChip.tsx:13` · **Confirmed**

Admission and evaluate count `contact_events` (allowed, `touch_counted`, last 7 local days). The operator consent matrix serializes `used_this_week` (`db.py:2102-2123`). That column is refreshed only inside `admit()` when a touch counted, in a nested transaction whose failure is logged and swallowed.

Drift conditions:

1. A week rolls forward with no new `admit` — events age out of the 7-day window; the column does not.
2. Refresh fails — ledger moved, column did not.
3. Any writer of `contact_events` that is not `admit` — column stays.

The Gate will not over-dial because of this: evaluate ignores the column. The operator **will** see “3/3 this week” when the Gate would still allow, or the reverse. That is a conflicting source of truth for the same English sentence.

**Conflict:** `contact_events` vs `channel_consents.used_this_week` vs the consent UI. Severity **P1** (operator), not a safety bypass.

---

### S4. `customers.last_contact_at` is a seed fossil; live last-contact already has a ledger

**Where:** column `sql/02_customer_account.sql:60`; selected `db.py:997,1049,3402,3691`; **zero** runtime `UPDATE`; Mission `_last_contact` reads `contact_events` (`mission.py:179-217`); seed `seed_postgres.py:752` · **Confirmed**

Customer 360 and list payloads expose `lastContact` from the column. The Mouth’s Mission context computes last contact from the ledger (and even joins delivery state). Those two timestamps are not required to agree and, after the first live outreach, will not.

**Conflict:** `customers.last_contact_at` vs `contact_events`. Severity **P1** (operator + Mission vs 360).

---

### S5. KB is cached twice, neither cache is invalidated on ingest, TTLs disagree

**Where:** `kb_retrieve.py:359-398,536-544,1087` (120 s, 256, key includes `kb_snapshot_id` + tenant + query); `voice/kb_enrich.py:84-85` (180 s, 32); no `_result_cache.clear` anywhere; embed LRU `azure_openai.py:43-44` size-only · **Confirmed**

A new Deployment with a new snapshot id is a new key — that path is consistent. Reindexing or editing chunks **under the same snapshot id** leaves API hits serving the previous retrieval for up to 120 s, and the voice process serving its own copy for up to 180 s. Inbox RAG and the live Mouth can quote different passages for the same question in that window.

No singleflight: on TTL expiry, concurrent retrieves all miss and all embed. Stampede is bounded by `kb_rate_limit` (Postgres counter, process deque fallback).

**Conflict:** indexed chunks vs API result cache vs voice `KbCache`. Severity **P1** (borrower-facing wording, time-bounded).

---

### S6. Next-best-action has three producers; one of them pretends to have logged a decision

**Where:** server insights `db.py:1220-1275` + `_treatment_snapshot` `recommend_treatment` inside `engine.connect()` with **no `commit()`**; client fallback `customers.ts:47-58` + `deriveCustomerInsights`; treatment console `["treatment-next"]` (`treatment.ts:1047-1053`); 360 render `insightsQuery.data ?? deriveCustomerInsights(customer)` (`customers.$customerId.lazy.tsx:108-114`) · **Confirmed**

While `customer-insights` is pending or failed, the page shows the **client** derivation. The comment in `customerInsights.ts:12-17` says the contact ladder was removed from both copies; the fallback still exists for the rest of the card. A 500 on `/insights` is logged and then replaced with a different NBA (`customers.ts:55`).

`_treatment_snapshot` “deliberately” writes a `treatment_decisions` row so opening a card trains the shadow corpus (`db.py:1259-1262`). `get_customer_insights` uses `engine.connect()` (`:1228`). SQLAlchemy 2.0.51 rolls back on close without `commit()`. The payload can still carry a `decisionId` that is not in the table. `["treatment-next"]` on the treatment page is a second engine call, a second query key, not invalidated by 360 goodwill.

**Conflict:** `treatment_decisions` vs insights JSON vs client fallback vs `["treatment-next"]`. Severity **P1**.

---

### S7. “Contactable now” is two Gates with two channels and two freshness windows

**Where:** Inbox `_inbox_contactable(..., channel="whatsapp")` (`db.py:8584-8600,8833`); 360 `useContactPolicy` defaults **voice** and documents that the backend default is WhatsApp so it sends both query params (`contact-policy.ts:43-47,56-69`); Inbox poll 4 s; policy query stale 30 s / refetch 60 s · **Confirmed**

WhatsApp 24 h window vs RBI voice hours are different vetoes. Both answers can be honest and still look like a bug when the Inbox row is green and the 360 pill is red. Inbox then **caches** `contactableNow` on the thread; delta merge keeps `context` if the delta omits it (`inbox.ts:49-56`). Full list every 15th poll (~60 s) heals.

A **third** “Contactable” chip lives on the consent page: `ContactablePill` runs `contactableSummary` / `isContactableNow` from `consent-seed.ts:380-417` against the fetched consent record, including `usedThisWeek >= frequencyCapPerWeek`. That is a client re-implementation of the Gate, using the denormalized weekly column (S3). Consent mutations invalidate `["consent"]` only (`consent.tsx:50-51`) — not `["contact-policy"]` and not Inbox threads.

`localSuggestions` / `localDraft` overlay the thread until the next RAG run (`inbox.tsx:156-162`). `mergeThreads` will not wipe RAG chips on a delta that omitted them — intentional, and a stale-chip window until full refresh or `runRagRefresh`.

**Conflict:** three evaluations + two caches. Severity **P2** (labelling), P1 if an operator uses the Inbox or consent chip to decide a **voice** dial.

---

### S8. Operational balance is `accounts.outstanding`; `ledger_entries.balance` is a dead column the docs still describe as SoT

**Where:** writers `payments.py:187`, `authority/enact.py:163-185`, `payment_events.py:317`; INSERT omits `balance`; `DATA_MODEL.md` still says “running `balance`” · **Confirmed**

The writers that were checked update **both** a ledger row and `accounts.outstanding`. That is the right dual-write if outstanding is a maintained aggregate. The unused `balance` column is a trap: a future reader (or an analyst summing `balance`) disagrees with outstanding without any runtime bug.

Voice copies outstanding onto `VoiceSession` at bind (`voice/session.py:54`). A waiver mid-call does not update the session object. Call-local snapshot — label it, do not treat it as the book.

**Conflict:** docs + null column vs `accounts.outstanding`. Severity **P2** (modelling), P1 if anyone queries `balance`.

---

### S9. Estimator files and `treatment_model_registry` can disagree after train-without-register

**Where:** load path `agent_core/reco/models.py:237` `RECO_MODEL_PATH` default `models/propensity.json`; registry `sql/05_collections.sql:600+`; `agent_core/treatment/registry.py` · **Confirmed**

The registry is the champion ledger. The audio/reco path loads a JSON file from disk. A train that writes the file and does not register, or a register that does not deploy the file into the image, is two champions.

**Conflict:** disk artefact vs registry row. Severity **P2** until a deploy pipeline proves they move together.

---

### S10. TTS bytes have three TTLs

**Where:** disk `azure_speech.py` / `tts_preview_cache.py` 14 d + 200 MB; HTTP `Cache-Control: private, max-age=3600` (`main.py:3042-3047`); `X-TTS-Cache` header reports the **disk** hit · **Confirmed**

The browser may serve audio for an hour after the disk copy was evicted, or the reverse. Preview-only — not the Mouth’s telephony TTS path. Inconsistent TTL assumption, not a CRM split-brain.

Severity **P2**.

---

### S11. Kill switch and policy-rule caches are cross-process stale by construction

**Where:** `platform_switches.py:83-87,128-130,230` (2 s; local invalidate on write); `policy_rules.py:71-77,444` (60 s; `reset_cache` not on a live publish path — no `main.py` policy-rule write found) · **Confirmed**

The 2 s outbound tail is documented in the module docstring as a property of the control. Writes clear the API process; `bot_worker` / `voice` converge within TTL. Policy rules change rarely; 60 s without a bust is the stated design. Both are **consistent with their comments** and still mean “the row in Postgres is not what this process will use for up to TTL.”

Severity **P2** (known tail). Do not advertise the kill switch as instant across the fleet.

---

### S12. Dev mock is a complete parallel book

**Where:** `USE_MOCK` default true (`config.ts:11-22`); mutable `seedThreads` on takeover/send (`inbox.ts:168-183`); mock presence localStorage; `mockEvaluateContactPolicy` ports `_veto`; Floor mock interval mutates `useState` and **does not** sync from the query (`floor.tsx:64-69`) · **Confirmed**

Production builds cannot enable mock. The trap is a developer or demo build with `VITE_USE_MOCK` unset talking to a live API **or** the reverse. Two books, one UI.

Severity **P2** (environment), P0 if someone ships a mis-set env — the production guard throws, which is the right fail.

---

### S13. Query mutations that change one book and leave another screen’s cache

**Where:** `consent.tsx:50-51`; `handoff.ts:267-288`; `handoff.lazy.tsx:363`; treatment hold invalidation in `api/treatment.ts` · **Confirmed**

These are QueryClient-level split-brains, not Postgres ones:

- Opt-out on the consent page does not bust `["contact-policy"]`. The 360 pill can stay green for up to 60 s.
- Wrap-up can insert a promise (`handoff.ts:267-274`) and only invalidates handoff keys. The promises list and Customer 360 stay stale until their own staleTime.
- Hold place/release invalidates holds/cases, not `["treatment-next"]`.
- Disclosure/suggestion POSTs never `setQueryData`; UI is local; failures are swallowed.

Severity **P2** (operator lists), P1 for the consent → Gate pill path because it is the same English sentence as S3/S7.

---

### S14. Per-process counters that look fleet-wide

**Where:** `llm_gateway/client.py:22,35,181` `_spend_inr`; `voice/admission.py:26-28,60-64` `_active` slots; Redis comments that were not implemented · **Confirmed**

Gateway spend caps reset per process and are not persisted. Voice admission is a per-container slot map; compose can run `voice` and `voice_insurance` (and an embedded host) without a shared counter. Outbound dial pressure correctly uses Postgres `call_attempts` instead (`outbound.py:569-583`). These are not CRM row conflicts; they are **capacity SoTs that fragment by replica**.

Severity **P2**.

---

### S15. Inbox `activeId` and the URL are two selection stores

**Where:** `inbox.tsx:111,128-136` · **Confirmed**

URL → `activeId` is one-way. An empty `?conversationId=` still auto-selects `threads[0]` into `useState` without `navigate`. The UI shows a thread; a refresh loses it. Deep-link vs “whatever is open” is the same operator concept with two owners.

Severity **P2**.

---

## Duplicate / derived state (compact)

| Fact | Copies | Sync | Finding |
|---|---|---|---|
| Customer record | loader, useState, `["customers"]` list | manual `fetchCustomer` | S1 |
| Insights / NBA | server insights, client `deriveCustomerInsights`, `["treatment-next"]` | none | S6 |
| Contactable | evaluate(WhatsApp) Inbox, evaluate(voice) 360, client `isContactableNow` on consent | independent | S7, S13 |
| Weekly cap | events count vs `used_this_week` | admit only | S3 |
| Last contact | column vs `contact_events` | never | S4 |
| Grants | DB vs `_perms_cache` × N processes | TTL only | S2 |
| KB hit | index vs API LRU vs voice LRU | TTL only | S5 |
| Outstanding | `accounts` vs session vs 360 state vs ledger.balance | partial | S1, S8 |
| Mouth | editor, draft row, published row, active deployment | autosave / publish | by design if labelled |
| Operator session | `["me"]` + module `meCache` (`me.ts:43-53`) | Header identity vs RQ | TTL of the promise until failure |
| Theme | localStorage vs DOM vs two writers | both write `theme` | preference only |
| Floor snapshot | RQ vs useState | live effect; mock no | S12 |
| Work items | view vs source tables | always (view) | good |
| Deployment bundle | always DB | n/a | good |

---

## Invalidation map (gaps only)

| Write | Should bust | Actually busts |
|---|---|---|
| `PATCH` role permissions | `_perms_cache` (all processes) | nothing |
| User delete / disable | `_user_exists_cache` | nothing |
| KB ingest / reindex same snapshot | `kb_retrieve._result_cache`, voice `KbCache` | RQ `["kb", …]` on the operator page only |
| `admit()` refresh fail | `used_this_week` | column left stale |
| Goodwill apply | 360 customer, list, insights, treatment-next, ledger | insights + authority-next + **dead** `["customer", id]` |
| Inbox send / takeover | `["conversations"]` | `setQueryData` merge + background invalidate — good |
| Publish Mouth | versions, published, deployments, agent-studio | `prompt-studio.ts:129-138` — good |
| Platform switch | other processes’ 2 s cache | local process only — documented |
| Policy rule seed/publish | `_CACHE` 60 s | tests/scripts `reset_cache` only |
| Presence PATCH | `["me-presence"]` | `setQueryData` — good enough |
| Consent save / opt-out / renew | `["contact-policy"]`, Inbox `contactableNow` | `["consent"]` only (`consent.tsx:50-51`) |
| Handoff wrap-up with PTP | `["promises"]`, `["customers"]`, 360 | `["handoff"]` only (`handoff.ts:286-288`) |
| Treatment hold place/release | `["treatment-next"]` | `treatment-holds` / `treatment-cases` only |
| Handoff disclosure / suggestion accept | session query | local React state; errors swallowed (`handoff.lazy.tsx:363`) |

Optimistic updates: **none** in React Query (`onMutate` in sheet props is a page callback). No rollback bug to report. Handoff compliance checkboxes are the exception: local state with no query sync and `.catch(() => undefined)`.

Stampede: no singleflight on embed, KB retrieve, policy resolve, or authz load. One uvicorn worker still has a threadpool. Opportunity, not a split-brain.

---

## Opportunities

1. Put Customer 360 on `["customer", id]` (or `ensureQueryData` in the loader) and delete the useState mirror. Point goodwill at that key. One line in `OverviewTab.tsx` is already trying to.
2. Call `authz.invalidate_permission_cache()` from `replace_role_permissions` (and accept other processes wait 30 s, or drop the TTL on write via a Postgres `NOTIFY` later).
3. Stop serializing `used_this_week`. Have the consent API count like `_week_counted`, or refresh the column from evaluate as well as admit.
4. Stop selecting `customers.last_contact_at` for operators; reuse Mission’s `contact_events` query. Or write the column in `admit()`.
5. `kb_retrieve` needs `result_cache_clear()` on ingest/reindex; voice `KbCache` should die with snapshot id change (it already keys on snapshot — confirm ingest bumps the id).
6. `get_customer_insights`: either `begin()`/`commit()` the shadow decision or stop calling `recommend_treatment`. Do not return a `decisionId` that will not exist.
7. Name the Inbox flag `contactableOnWhatsApp` (or pass `channel=voice` when the operator’s next action is a call). Invalidate `["contact-policy"]` from consent writes; invalidate `["promises"]` from wrap-up.
8. Singleflight the KB/embed miss path.
9. Register train artefacts in `treatment_model_registry` in the same step that writes `models/*.json`.
10. Drop or populate `ledger_entries.balance`. Do not leave a documented running total null.

---

## Already good

- **One QueryClient at the root.** AppShell remounts per route (architecture 03); the cache does not.
- **No domain React Context.** Sidebar collapse is chrome.
- **Postgres is the session store for Sandbox Live** after a real split-brain (`voice_session_store.py`).
- **KB rate limit is a Postgres counter**, not Redis, with a logged process fallback (`kb_rate_limit.py:1-11`).
- **`load_active_bundle` is uncached.** Publish is visible on the next turn.
- **Partial uniques** for published Mouth, active Deployment, active treatment hold.
- **`work_items` is a view.**
- **Contact Gate does not read `used_this_week`.**
- **Platform switches fail closed** (missing row = off) and bust the local cache on write.
- **Inbox merge is explicit** about not wiping messages/RAG on sparse deltas (`inbox.ts:49-73`).
- **Presence in live mode is a table**, `setQueryData` on PATCH.
- **Mouth editor local state** is the correct editor pattern; they already fixed card PATCH snapping back to published (`prompt-studio.lazy.tsx:227-230`).
- **No RQ optimistic updates**, hence no optimistic rollback holes.
- **Redis is not pretending to be a CRM cache.**

---

## Ranked remediation

1. **S1** — QueryClient owns Customer 360; delete the dead key or make it real.
2. **S2** — Bust authz cache on `replace_role_permissions`.
3. **S6** — Commit or don’t write treatment-on-open; kill the client NBA fallback in live mode.
4. **S3 / S4** — Stop showing denormalized columns the writers abandoned.
5. **S5** — Clear KB result caches on ingest; align voice TTL with API or share nothing.
6. **S7** — One channel per “contactable” chip, labelled.
7. **S8 / S9 / S10 / S11** — Docs and TTL honesty.

---

## What could not be verified

- Live Redis contents or `NOTIFY` channels beyond `mesh_bus.py`.
- Whether any production deploy sets `UVICORN_WORKERS>1` (compose pins 1; embed comment assumes >1 would need Redis).
- Whether `ledger_entries.balance` is populated by a trigger not in `sql/13_triggers.sql` (no match found).
- Whether a policy-rule publish API exists outside `scripts/seed_policy_rules.py`.
- Browser HTTP cache behaviour against the TTS `max-age=3600` header.
- Actual 30 s authz-window exploits — structural only.

---

## Corrections applied during verification

- Redis is **not** a KB or CRM cache. Prior performance report 16 said this; re-confirmed. `REDIS_URL` on the API process does not imply API caching. Compose also disables RDB/AOF (`--save "" --appendonly no`).
- `CustomerResponse` embeds **one** account via `LATERAL … LIMIT 1` (`db.py:1019-1028`) — a serialization choice, not a second customer table.
- `conversations.bot_state` has two writers (`bot_runtime._save_bot_state`, `return_conversation_to_bot`) — a race, companion 15, not a second SoT.
- `customers.dnd` is OR-merged with `consent_records.dnd_registry` in the consent API (`db.py:2313`); Gate ORs similarly. Updating only one column is a drift path (opportunity, not S-class until a write site is shown that skips the other).
- `used_this_week` is **not** on the admit/evaluate hot path. A finding that “the Gate uses a stale cache column” would be false. The **UI** uses it.
- Inbox `onMutate` on sheets is not React Query optimistic updates.
- `load_active_bundle` is not cached — a performance miss, a consistency win.
- Customer list `["customers"]` is not a full 360 record; invalidating it does not refresh an open detail page.
- Floor `useState` in live mode **is** synced from the query; only mock mode diverges.
- `work_items` is not a competing table.
)
