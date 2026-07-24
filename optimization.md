# Application Optimization & Production-Readiness Audit

**Verdict:** this is a strong hackathon/demo stack (Postgres SKIP LOCKED queues, pgvector RAG, separate voice runner), but it is **not production-ready**. The blockers are not “missing Redis/Celery” first — they are **a 15-connection DB pool as the binding concurrency ceiling**, **5 `async def` routes that can block the event loop if they call sync clients inline**, **no auth**, **file-based voice session state**, **mock-by-default UI**, and **ops that assume one laptop with four hand-started processes**.

---

## 1. Architecture reality (what you actually run)

| Process | Role | Prod risk |
|---|---|---|
| `uvicorn main:app` (:8000) | All CRM + webhooks + sandbox turns + TTS/STT | Default QueuePool (15 conns) saturates before the threadpool; slow Azure holds a pool slot + a thread |
| `python -m worker` | KB embed/index | Single claimer; not in compose; holds its own DB pool |
| `python -m bot_worker` | WhatsApp bot turns | Single claimer; not in compose; holds its own DB pool |
| `python -m voice.bot` (:7860) | Live WebRTC voice | Separate process; API only HTTP-probes it; holds its own DB pool |
| Compose | **Only** Postgres + MinIO | No API/workers/voice packaging |

Redis/Celery are commented futures in `.env.example`. That is fine for now — **Postgres `FOR UPDATE SKIP LOCKED` is the right constrained-infra choice**. The gap is using that queue pattern inconsistently: WA bot turns are queued; sandbox RAG, WhatsApp agent sends, TTS/STT, and many Azure calls still sit on the HTTP path.

---

## 2. Critical inefficiencies (will break under real load)

### A. Blocking I/O ceilings (DB pool + threadpool + the 5 async routes)

**132 of 137 routes are sync `def`; only 5 are `async def`.** Starlette runs sync `def` endpoints in the anyio threadpool (default **40 threads**) — they **never touch the event loop**. A slow Azure call in a sync CRM route ties up **one threadpool slot**, not the loop.

The actual saturation ceilings:

#### 1. DB connection pool is the binding constraint (not the threadpool)

`create_engine(DATABASE_URL, pool_pre_ping=True)` uses SQLAlchemy’s default `QueuePool`: **`pool_size=5`, `max_overflow=10` → 15 connections max per process**.

With a 40-slot threadpool, **40 concurrent requests but only 15 DB connections** means ~25 threads block on connection checkout (default **30s** timeout, then failures). You hit **DB-pool exhaustion at ~15 concurrent DB-touching requests**, long before the threadpool or any Azure limit.

This promotes explicit pool sizing + `statement_timeout` to **Tier 0-critical** (see §8 / §9).

#### 2. The genuine event-loop blockers are the 5 `async def` routes

| Route | Location | Risk |
|---|---|---|
| `stt_transcribe` | `main.py` ~864 | **Prime suspect** — calls sync `azure_speech.transcribe(...)` inline |
| `whatsapp_webhook_receive` | `main.py` ~1282 | **Prime suspect** — calls sync `db.process_whatsapp_webhook(...)` inline |
| `kb_upload_document` | `main.py` ~1121 | Audit for sync MinIO / DB after `await file.read()` |
| `kb_new_version` | `main.py` ~1156 | Same |
| `lifespan` | `main.py` ~142 | Startup only; still avoid long sync work without offload |

If any of these call sync Azure Speech / sync DB / sync urllib **inline** (no `asyncio.to_thread`), that **blocks the loop and stalls every request in the process**.

**Fix:** wrap blocking bits in `asyncio.to_thread`, **or** demote the route to sync `def` so the threadpool isolates them.

#### 3. Azure / Speech / WhatsApp / MinIO client churn (on sync routes → thread slots + pool slots)

Azure OpenAI is sync and **creates a new client per call** (`azure_openai.get_client()`). Same pattern for Speech (`httpx.Client` per call), WhatsApp (`urllib`), MinIO. Voice already does it right (`llm_pool` + `asyncio.to_thread`) — CRM does not.

**Sharper framing for `get_client()`:** the cost is not “event-loop blocking” (sync routes are off-loop). Each `AzureOpenAI(...)` builds a **fresh httpx pool with no HTTP keep-alive to Azure**, so every embed/chat pays a **new TLS handshake** on top of the already-painful India→East US RTT (~500–700ms floor in §6). The singleton fix is your **single biggest per-call latency win** — recovering connection reuse against a high-RTT link — not just “less blocking.”

**Impact under load:** sandbox turn / KB retrieve / inbox suggestions / TTS preview each hold a **threadpool slot** and usually a **DB connection** for seconds. You exhaust the **15-conn pool** first; then checkout queues pile up; only later do you approach the 40-thread ceiling.

### B. No parallelization where it would help

- Customer detail builds via many **sequential** queries (consent, ledger, EMI, interactions, promises, disputes, docs, notes).
- Transcripts are classic **N+1** in `db.py` `_interaction_contracts` (one transcript query per interaction).
- KB hit counters update **one UPDATE per chunk** instead of `WHERE id = ANY(:ids)`.
- Embed batches are sequential (OK), but independent CRM reads never use `asyncio.gather` / thread fan-out.

### C. File-based voice session authority

Sandbox voice sessions live under `.cache/...` with a global `latest.json`. Multi-user / multi-host / restart = wrong config or race. This is a hard production blocker for Live Sandbox.

### D. Auth / tenancy / actor are env spoofing

No JWT/API key on routes. `TENANT_ID` + `ACTOR_USER_ID` from env. Frontend `fetch` has **no auth, timeout, abort, or credentials**. Anyone who can reach `:8000` reads PII and burns Azure budget.

**CORS trap for cookie auth:** middleware uses `allow_origin_regex` with **no `allow_credentials=True`**. The moment Tier 0 adds cookie-based auth, **cross-origin cookies will not be sent**. Prod needs an **explicit origin allowlist + `allow_credentials=True`** (you cannot use `allow_origins=["*"]` with credentials). Note this now so auth does not silently half-work.

### E. Frontend still demo-shaped

- `USE_MOCK` defaults to **`true`** (`Habibi/src/api/config.ts`).
- Floor / Webhooks / Integrations are **seed-only** (no API seam).
- Handoff “live” still replays client simulation.
- Inbox polls full conversation list every 1.5–4s.
- Fake-looking secrets in `integrations-seed` ship in the JS bundle.

### F. Health is a lie

`GET /health` returns `{"status":"ok"}` with no DB/MinIO/worker/voice check. Orchestrators will route traffic to a broken box.

**`/ready` must check pool headroom, not just `SELECT 1`.** A readiness probe that only runs `SELECT 1` will **pass while the pool is exhausted** and requests are queuing on checkout. Have `/ready` also report `pool.checkedout()` vs capacity so orchestrators can shed load.

### G. Worker × pool math (or you’ll DOS your own Postgres)

“Raise uvicorn workers” and “explicit pool” multiply:

```text
total connections ≈ uvicorn_workers × (pool_size + max_overflow)
                  + kb_worker_pool
                  + bot_worker_pool
                  + voice_runner_pool
```

Postgres default `max_connections=100`. Example: **4 workers × 15 = 60**, plus KB worker + bot worker + voice → easy to blow past 100 and start refusing connections.

**Rule:** budget connections across **all** processes; set per-process `pool_size` / `max_overflow` so the sum stays under `max_connections − reserved`. Consider **PgBouncer (transaction mode)** before adding replicas.

### H. No `statement_timeout` anywhere

Confirmed absent. A single runaway query holds a pooled connection until it finishes — and since the pool is only 15, **one bad query accelerates exhaustion in §2.A / §2.G**.

Add `connect_args={"options": "-c statement_timeout=15000"}` to `create_engine` (workers get a longer one). Cheap, defends the tight ceiling — **Tier 1 (with pool sizing promoted beside Tier 0)**.

### I. No response compression

GZip middleware count = 0. Over-fetch (audit, bot-analytics, customer-detail, full conversation lists) ships **uncompressed JSON**.

`app.add_middleware(GZipMiddleware, minimum_size=1024)` is a one-liner that cuts fat-payload cost while contract-first API work lands — **Tier 2**.

### J. HNSW `ef_search` is never set

`kb_retrieve.py` sets `hnsw.iterative_scan = 'relaxed_order'` (good — correct pgvector 0.8 knob for filtered vector search), but **not** `hnsw.ef_search`, so recall/latency runs at the default (**40**).

Add `SET LOCAL hnsw.ef_search = N` as a tunable so you can trade RAG recall against latency deliberately.

---

## 3. Design principles that are missing

| Principle | Current state | Why it matters |
|---|---|---|
| **Separation of concerns** | `main.py` ~1.3k lines, `db.py` ~10k lines god-module | Can’t test, can’t enforce auth middleware cleanly, can’t swap stores |
| **Fail-fast config** | Multiple custom `.env` parsers; soft-fail MinIO/price book | Mid-request explosions; silent drift |
| **Backpressure** | No concurrency semaphores on Azure; process-local KB rate limit; default 15-conn pool | One UI can exhaust DB pool then DOS Postgres if you naively scale workers |
| **Connection budget** | Pool + worker counts chosen independently | `workers × pool` blows `max_connections` |
| **Idempotency everywhere** | Good for WA outbound jobs / CRM header paths; **voice `create_promise_to_pay` passes no idempotency key** while WhatsApp does — concrete duplicate-write bug on the voice path; also missing for many other CRM writes / sandbox | Duplicate PTP / cost / side effects |
| **Observability** | Almost no structured logs / metrics / tracing / request IDs | Blind p99, blind Azure 429s, blind queue lag |
| **Readiness vs liveness** | Only liveness; no pool-headroom signal | Bad deploys look healthy; exhausted pools still “ready” |
| **Dependency pinning** | `requirements.txt` unpinned | Non-reproducible prod |
| **Process supervision** | Manual 4-process start | Voice/workers die silently |
| **Demo vs prod data path** | Seeds inside Alembic migrations | `upgrade head` injects fake tenants into “prod” |
| **Contract-first API** | FE filters/aggregates (audit, bot analytics, workspace) client-side | Over-fetch + FE/BE logic drift |
| **Transport efficiency** | No GZip | Fat JSON over the wire while over-fetch remains |
| **Graceful degradation** | No circuit breaker for Azure/Meta | Cascading failure |
| **Multi-tenant isolation** | Documented as Phase 5; storage has no tenant segment | Unsafe if exposed |
| **CORS ready for cookie auth** | `allow_origin_regex`, no `allow_credentials` | Cookie auth will silently fail cross-origin |

---

## 4. Backend deep dive

### Sync vs async (correct model)

| Severity | Gap | Practical fix |
|---|---|---|
| **Critical** | Default DB pool = **15** conn/process; threadpool = **40** → pool exhausts first | Explicit `pool_size` / `max_overflow` / `pool_recycle`; budget across processes; `/ready` reports headroom |
| **Critical** | 5 `async def` routes may call sync clients inline (`stt_transcribe`, WhatsApp webhook are prime suspects) | `asyncio.to_thread` for blocking bits, **or** demote to sync `def` |
| **Critical** | Sync `AzureOpenAI`; new client per call → **fresh TLS + no keep-alive** on India→East US RTT | Module-level singleton client (mirror `voice/llm_pool.py`) — latency win first, thread occupancy second |
| **High** | Sync `httpx.Client` per TTS/STT request | Shared `httpx.Client`; STT path must not run sync on the event loop (see async audit) |
| **High** | Sync `urllib` WhatsApp send on agent reply path | Enqueue outbound send job (same SKIP LOCKED pattern); API returns `sending` |
| **High** | No `statement_timeout` | `connect_args` with `-c statement_timeout=15000` (longer for workers) |
| **Medium** | Sync Minio client recreated per op | Reuse one `Minio` client; heavy ingest stays on worker |
| **Medium** | Raising uvicorn workers without pool budget | Cap `workers × (pool_size+max_overflow) + other processes < max_connections − reserved`; PgBouncer before replicas |
| **Low (good)** | Voice uses async OpenAI + thread offload for sync DB/KB | Reuse this pattern for CRM hot paths and for the 5 async routes |

### Parallelization / concurrency

| Severity | Gap | Practical fix |
|---|---|---|
| **High** | No `asyncio.gather`, no thread pools in CRM app code, no Celery/Redis | Parallelize independent DB fetches in customer detail; keep retrieve→draft serial (draft needs chunks) |
| **Medium** | Single-process poll loops with `time.sleep` in workers | Run N worker processes; SKIP LOCKED already supports it — **only after connection budget is set** |
| **Low (good)** | `FOR UPDATE … SKIP LOCKED`, coalesce, reclaim stuck | Document “scale = more processes”; keep Arq/Redis as later option |

### Connection pooling / N+1 / RAG knobs

| Severity | Gap | Practical fix |
|---|---|---|
| **Critical** | `create_engine(..., pool_pre_ping=True)` only — default 5+10 | Explicit pool settings per process from env; monitor `pg_stat_activity`; budget vs `max_connections` |
| **High** | N+1 transcripts in `_interaction_contracts` | Single `WHERE interaction_id = ANY(:ids)` + group in Python |
| **Medium** | Many sequential queries in `_customer_contract` detail | Batch where possible; “summary” vs “full” endpoint |
| **Medium** | Per-chunk `UPDATE kb_chunks SET hits = hits + 1` | One `UPDATE … WHERE id = ANY(:ids)` |
| **Medium** | `hnsw.ef_search` unset (default 40) | `SET LOCAL hnsw.ef_search = N` tunable alongside existing `iterative_scan` |
| **Low** | No `engine.dispose()` on shutdown | Lifespan exit: `engine.dispose()` |

### Error handling / retries / breakers

| Severity | Gap | Practical fix |
|---|---|---|
| **High** | No circuit breaker for Azure / Meta / MinIO | Simple in-process breaker (open after N failures / 60s) |
| **Medium** | `timeout=60`, `max_retries=3` on sync Azure client | Lower API-path timeout (15–20s); longer timeouts only in workers |
| **Low (good)** | Job `mark_failed_or_retry` with exponential backoff + dead-letter | Keep; prefer queue retries over in-request retries |

### Caching

| Severity | Gap | Practical fix |
|---|---|---|
| **Medium** | No Redis; only local caches | Without Redis: sticky sessions / single API replica for sandbox voice; or Postgres-backed rate table |
| **Low (good)** | Disk TTS cache under `.cache/tts` | Acceptable; optionally MinIO for shared TTS blobs |
| **Low** | Embedding/query results never cached | Short TTL **in-memory LRU** keyed by hash(query) — **correct for one API process**. The moment you run `uvicorn --workers >1` (which connection budgeting pushes you toward), each worker has its own LRU → low hit rate and **N× the cost**. **This cache and the process-local KB rate-limit are the two things that actually force Redis** — see “When to add Redis” below |

### Auth / rate limiting / tenancy / CORS

| Severity | Gap | Practical fix |
|---|---|---|
| **Critical** | No auth on CRM routes; CORS allows any localhost port via regex | Network ACL short-term; OIDC/JWT ASAP |
| **Critical** | Cookie auth planned without `allow_credentials=True` + explicit origins | Prod: origin allowlist + `allow_credentials=True` (never `*` with credentials) |
| **Critical** | Global `TENANT_ID` env; KB storage no tenant segment | Keep single-tenant until RLS; never expose API publicly |
| **High** | `ACTOR_USER_ID` from env — all writes as one user | Bind actor to auth subject |
| **Medium** | Process-local KB rate limit | Postgres token bucket, reverse-proxy limit, or Redis once multi-worker |
| **Low (good)** | WhatsApp webhook HMAC | Keep; ensure secret always set in prod |

### File-based session state

| Severity | Gap | Practical fix |
|---|---|---|
| **Critical** | `.cache/voice_sandbox_sessions/` + global `latest.json` | Pass `sessionId` via WebRTC metadata; store session in Postgres; stop using `latest` |
| **High** | Local `.cache` for TTS/recordings | Cap cache size; prefer MinIO for recordings |
| **Medium** | Non-atomic read-modify-write on session JSON | Use DB row with `UPDATE … RETURNING` |

### Idempotency (named gaps)

| Severity | Gap | Practical fix |
|---|---|---|
| **High** | Voice `create_promise_to_pay` → `db.create_promise(...)` with **no idempotency key**; WhatsApp path uses keys | Pass a stable key (e.g. interaction + amount + date hash) from voice tools |
| **Medium** | Many other CRM writes / sandbox turns lack keys | Header-based idempotency on mutating routes |

---

## 5. Frontend deep dive

### Critical

| Finding | Path(s) | Suggested fix |
|---|---|---|
| `USE_MOCK` defaults to `true` | `Habibi/src/api/config.ts` | Default to `false` in production builds; fail CI if unset |
| Floor is 100% client seed + fake live tick | `routes/floor.tsx`, `data/floor-seed.ts` | Add `api/floor.ts`; remove local simulation in live mode |
| Webhooks & Integrations bypass API | `routes/webhooks.tsx`, `routes/integrations.tsx` | Same pattern as other modules with live endpoints |
| No auth on API client | `api/config.ts`, `api/me.ts` | Session cookie or Bearer; route guards; 401 → login; FE `credentials: "include"` must match CORS `allow_credentials` |
| Fake secrets in client bundle | `data/integrations-seed.ts` | Strip production-looking secrets; placeholders only |

### High

| Finding | Suggested fix |
|---|---|
| Fetch wrapper: no timeout, abort, retry, or credentials | Single `apiFetch` with `AbortSignal.timeout`, optional retry, `credentials` |
| `apiGet` error handling weaker than mutations | Route all methods through one helper using `errorDetail` |
| Inbox over-polls full conversation list | WebSocket/SSE or delta/`updatedAfter`; poll only when tab visible |
| Handoff “live” is client script replay | Gate simulation to `USE_MOCK`; live = WS stream |
| Eager route graph (no code-splitting) | TanStack Router lazy routes; dynamic import heavy deps |
| Hardcoded localhost defaults | Require `VITE_API_BASE_URL` in prod; relative `/api` + reverse proxy |
| Most screens ignore query errors | Shared `QueryErrorState`; don’t treat error as empty data |
| QueryClient has no defaults | `retry: 1`, `staleTime: 15_000`, controlled refetch-on-focus |

### Medium

| Finding | Suggested fix |
|---|---|
| Sandbox voice status polled every 8s | React Query + focus-aware interval; or SSE |
| KB index job busy-loop polling | Accept `signal`; exponential backoff |
| Client-side filtering duplicates backend | Push filters/aggregations to query params / summary endpoints |
| Seed modules imported across UI | Split types/formatters from seed payloads |
| Pipecat client typed as `any` | Use `@pipecat-ai/client-js` types; drop `as any` |

---

## 6. Infra / ops / data layer

### Docker / compose

- Compose only runs Postgres + MinIO — no api/frontend/worker/bot_worker/voice.
- No Dockerfile anywhere.
- MinIO uses `:latest` (non-reproducible).
- Postgres published on host with default `collections/collections` — unsafe if LAN-exposed.

**Constrained fix:** Keep compose as data-plane; add a start script for the four app processes; pin MinIO image tag/digest.

### Alembic / seeds

- Single linear head (healthy).
- Dual schema path risk (sql/*.sql vs Alembic).
- Many revisions mix **schema + demo seed** — `upgrade head` on a clean “prod” DB injects synthetic data.

**Constrained fix:** Schema-only migrations going forward; optional `scripts/seed_demo.py`. Never run seed migrations against real customer DBs.

### Postgres / JSONB / vector

- Solid btree indexes and HNSW for RAG.
- JSONB heavy for config blobs — fine for PoC; almost no GIN.
- Sync SQLAlchemy with **default 15-conn pool** — binding concurrency ceiling (§2.A).
- `hnsw.iterative_scan` set; **`hnsw.ef_search` not set** (default 40).
- No `statement_timeout`.
- Worker × pool math can exceed `max_connections=100` — budget before scaling; PgBouncer (transaction mode) before replicas.

### Redis / Celery

- Absent by design; SKIP LOCKED is the broker.
- Scale path (`REDIS_URL`, `BOT_QUEUE_BACKEND=postgres|arq`) documented but unimplemented.

**Stay on SKIP LOCKED until multi-node.** Add process supervision and queue-depth alerts first.

**True Redis triggers (process-local today):** embedding-query LRU and KB rate-limit — both shatter under `uvicorn --workers >1`.

### Voice process model

- Separate `:7860` runner; no process manager.
- Session state on filesystem — not multi-host safe.
- Vite `/voice-rtc` proxy is dev-only.

### Ngrok / WhatsApp

- Live WA requires `PUBLIC_BASE_URL` (tunnel). Human/ops dependency; Meta webhook re-point on every ngrok restart.

### Packaging / tests / health

- Python deps unpinned.
- No `tests/`, no CI.
- `/health` is liveness-only; `/ready` must include **pool headroom**, not only `SELECT 1`.
- No GZip middleware.

### Known latency floors (from spike notes)

- Warm LLM TTFB ~1.3–1.9s India → East US 2.
- Network floor ~500–700ms — co-locate Azure region if demo-critical.
- **TLS handshake on every `get_client()` stacks on that floor** — singleton keep-alive is the #1 per-call latency fix.

---

## 7. What is already good (keep)

- Postgres **SKIP LOCKED** job queues with reclaim / backoff / dead-letter (`bot_jobs`, `kb_ingest`).
- WhatsApp webhook HMAC + outbound “sending” discipline.
- Voice LLM keep-alive pool + CRM sink off the audio path.
- TTS disk cache with atomic writes.
- pgvector + HNSW for RAG; `hnsw.iterative_scan = 'relaxed_order'` already set.
- Alembic currently single linear head.
- Compose binds MinIO to localhost and refuses default credentials.
- Sync `def` routes correctly isolated on the anyio threadpool (do not “async-wash” them without a reason).

Do **not** rip these out for Redis/Celery until you have multi-node evidence.

---

## 8. Proposed improvements (best with constrained infra)

### Tier 0 — stop shipping a demo as prod + defend the binding ceiling (1–3 days)

1. **Auth gate**: API key or JWT middleware; FE `Authorization` / cookies; bind `ACTOR_USER_ID` to auth subject. If cookies: **explicit origin allowlist + `allow_credentials=True`** (CORS gap today).
2. Flip **`USE_MOCK` default to false in prod builds**; fail boot if mock in `PROD`.
3. Wire Floor / Webhooks / Integrations behind real APIs (or hide routes).
4. **`/health` + `/ready`**: DB ping **and pool headroom** (`checkedout` vs capacity); optional MinIO; voice status separate.
5. **Explicit DB pool + connection budget across all processes** (API workers × pool + KB + bot + voice &lt; `max_connections − reserved`). This is the **binding concurrency ceiling** — not the threadpool.
6. Pin Python deps; document/start-order the 4 processes (or a `dev-up` script).

### Tier 1 — latency, timeouts, async-route safety (biggest wins without Redis)

1. **`statement_timeout`** on API engine (~15s); longer for workers — defends the 15-conn ceiling from runaway queries.
2. **Singleton** Azure OpenAI + shared `httpx.Client` — recover **HTTP keep-alive / TLS reuse** on India→East US (largest per-call latency win); secondary benefit: less thread occupancy.
3. **Audit the 5 `async def` routes** for inline sync blocking; `to_thread` or demote to sync `def`. Start with `stt_transcribe` and WhatsApp webhook.
4. Azure concurrency **semaphore** (cap concurrent LLM calls, e.g. 4–8) so threadpool + pool aren’t held by unbounded Azure fan-out.
5. Queue **agent WhatsApp sends** the same way bot turns are queued; API returns `sending`.
6. Sandbox turns: hard timeout + concurrency limit; optionally job+poll if UX allows.
7. Rule: do **not** raise uvicorn workers until pool budget is set; prefer PgBouncer before replicas.

### Tier 2 — parallelize / batch / compress the cheap wins

1. Fix transcript **N+1** → one `WHERE interaction_id = ANY(:ids)`.
2. Batch KB hit updates.
3. Customer detail: parallel independent queries in a thread pool **or** one wider SQL / summary endpoint.
4. **`GZipMiddleware(minimum_size=1024)`** — one-liner while contract-first work continues.
5. In-memory LRU for **embedding query hash** — OK for **one** API process; **flag: multi-worker → low hit rate / N× cost → Redis** (same as KB rate-limit).
6. Inbox: stop full-list polling → `updatedAfter` delta or SSE; only poll when tab visible.
7. `SET LOCAL hnsw.ef_search = N` tunable.
8. Voice PTP: pass **idempotency key** into `db.create_promise`.

### Tier 3 — voice / session correctness

1. Kill `latest.json`; pass `sessionId` via SmallWebRTC `request_data` → `runner_args.body`.
2. Persist sandbox voice sessions in Postgres (same DB you already have).
3. Consume persona + `kbSnapshotId` for real in the voice path.

### Tier 4 — structure for growth (still no Celery required)

1. Split `APIRouter`s by domain; stop growing `db.py`.
2. Schema-only Alembic vs `scripts/seed_demo.py`.
3. Structured JSON logs + `X-Request-Id`; cheap queue-depth SQL view.
4. Minimal tests: alembic heads==1, `/ready` (+ pool headroom), WA idempotency, voice PTP idempotency, job claim.
5. Add workers to compose with `restart: unless-stopped`.

### When to add Redis / Celery / httpx-async / PgBouncer (later)

| Add when… | Use for… |
|---|---|
| `uvicorn --workers >1` or &gt;1 API replica | **Redis** for embedding LRU + KB rate-limit (process-local caches break) |
| Job volume exceeds Postgres claim contention | Arq/Celery on Redis (already sketched `BOT_QUEUE_BACKEND`) |
| Connection budget can’t fit needed workers | **PgBouncer** (transaction mode) before more replicas |
| CRM routes are mostly `async def` by design | `httpx.AsyncClient` end-to-end |
| Multi-host voice | Redis/Postgres session store (not files) |

Until then: **budgeted Postgres pools + statement_timeout + shared HTTP clients + async-route hygiene + semaphores** get you most of the way.

---

## 9. Suggested order of attack

```text
Auth + mock-off + /ready(+pool headroom)
    → EXPLICIT DB POOL + statement_timeout + connection budget across processes
        → singleton Azure/httpx (keep-alive / TLS reuse) + Azure semaphore
            → audit the 5 async routes for inline blocking (stt + WA webhook first)
                → queue WA agent sends + fix N+1/batch hits + GZip + voice PTP idempotency
                    → voice sessionId (kill latest.json)
                        → FE polling → deltas/SSE; lazy routes
                            → routers split + seed/migration hygiene + smoke tests
                                → Redis only when multi-worker forces shared cache/rate-limit
                                → PgBouncer before replicas if conn budget is the wall
```

---

## 10. Bottom line

The app is constrained less by “no Redis/Celery” and more by a **15-connection DB pool (the real concurrency ceiling)**, **async routes that can block the event loop with inline sync I/O**, **TLS churn on every Azure call against a high-RTT link**, **no auth**, **demo defaults in the UI**, and **file-local voice state**. Sync CRM routes do **not** starve the event loop — they occupy threadpool slots; the pool runs out first. Fix pool budgeting, timeouts, keep-alive, and the five async suspects first with what you already have. Redis/Celery/PgBouncer are scale-up tools for when multi-worker and connection math demand them — not the first missing design principle.
