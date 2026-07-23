# Knowledge Base (RAG) — Production Plan

> Status: **Approved decisions locked** (2026-07-22); revised with review feedback  
> Screen: Habibi `/knowledge-base` (currently mock)  
> Goal: Production-grade RAG admin + retrieval spine on Azure OpenAI + Postgres/pgvector (+ MinIO from KB-2)

---

## 1. Decisions (locked)

| # | Question | Decision |
|---|---|---|
| 1 | Object storage | **MinIO** — but **deferred to KB-2** (upload wizard / `kb_source_files`). KB-0/KB-1 bootstrap reads `source_db/` from disk. |
| 2 | Indexing execution | **Durable jobs + Postgres `FOR UPDATE SKIP LOCKED` worker** (no Redis/Arq required yet; upgrade path clear) |
| 3 | Starting corpus | **`source_db/policy`**, **`source_db/FAQ`**, **`source_db/benefits`** via an **explicit product → files manifest** (loud fail on missing/misnamed paths) |
| 4 | Delivery approach | **Best path**: foundations + disk ingest → retrieve spine → MinIO + admin CRUD → gaps/FAQ polish → Inbox consumer |
| 5 | Test Retrieval UX | **Vector snippets (always) + optional LLM drafted answer** via Azure **chat deployment** |
| 6 | Tenancy | **KB is global/shared for this PoC** — no `tenant_id` on `kb_*` tables; `storage_ref` uses `kb/{doc_id}/...` (no tenant segment). Documented for Phase-5 if/when per-tenant KB is needed. |
| 7 | Demo narrative | HL Assurance corpus powers **insurance cross-sell / upsell** for the HDFC retail collections bot (ties to Upsell & Leads) — not a second unrelated dataset |

### Why these choices

- **MinIO at KB-2, not KB-0** — Retrieval quality is the #1 demo risk; proving it does not need object storage. Bootstrap can read `source_db/` off disk and fill `kb_chunks`. MinIO earns its keep when the upload wizard needs durable originals in `kb_source_files`. `storage.py` is called from one ingest path — filesystem-first costs nothing you rewrite.
- **SKIP LOCKED worker** — Policy files are large (33–110 KB markdown). Sync HTTP upload→embed will time out. Jobs in `kb_index_jobs` are already in the schema. Later: same job table, swap claim loop for Arq.
- **Explicit FAQ/product manifest** — `Fraud_FQAs.txt` already breaks a `{Product}_FAQs.txt` glob. Hardcoded paths make missing/misnamed files a loud failure, not a silent gap.
- **KB global** — No `kb_*` table has `tenant_id` today; inventing `{tenant}` in `storage_ref` while retrieve has no tenant filter contradicts the rest of the app’s `TENANT_ID='hdfc.retail'` scoping. PoC = one shared KB. If Phase-5 needs per-tenant KB, add `tenant_id` to `kb_documents` + `faq_pairs` in that migration and scope `retrieve()` then — not half-now.
- **Snippets + drafted answer** — Retrieve first; optional chat rewrite for Test panel. Same shared `retrieve()` feeds Inbox later, with prompt-injection defenses from day one.

---

## 2. Current state

### Done (KB-0 … KB-4)
- Azure OpenAI client, tiktoken chunker, atomic SKIP LOCKED ingest, explicit corpus manifest, disk bootstrap
- Partial HNSW + over-fetch retrieve; Test Retrieval live via `POST /kb/retrieve`
- MinIO in compose + `storage.py`; docs/stats/chunks/upload/patch/reindex/versions/jobs APIs
- Documents tab + inspector + upload wizard wired through `Habibi/src/api/kb.ts` (`VITE_USE_MOCK=false`)
- FAQ CRUD + live Analytics Gaps (`/kb/faqs`, `/kb/gaps`, gap link) wired in FAQ/Gaps tabs
- Inbox debounced `POST /conversations/{id}/suggestions/refresh` → shared `retrieve()` → `ai_response_suggestions`
- Hardening: content-hash skip, rate limits, embed batch + stuck-job env knobs, `kb_snapshots` hook

### Still later
- Optional Phase-5 per-tenant KB (`tenant_id` on `kb_*`)

### Related consumers
- Inbox Phase C → `ai_response_suggestions` via same retriever ✅
- Bot Analytics gaps → `unanswered_questions` + `analytics_kb_gap_links` ✅ (KB-3)
- Sandbox / Pipecat → `kb_snapshots` + `retrieval_logs` (snapshot API ready)

---

## 3. Target architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Habibi /knowledge-base                                      │
│  Docs | FAQs | Analytics Gaps | Test Retrieval              │
└───────────────────────────┬─────────────────────────────────┘
                            │ Habibi/src/api/kb.ts
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ FastAPI                                                      │
│  /kb/* CRUD · upload · reindex · retrieve · jobs · stats     │
│  azure_openai.py  ·  kb_ingest.py  ·  kb_retrieve.py         │
└───────┬───────────────────┬───────────────────┬─────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
   source_db/ (KB-0/1)  Postgres 16 + pgvector  Azure OpenAI
   MinIO (KB-2+)        kb_* + partial HNSW     embed + chat
        ▲                   ▲
        │                   │
        └───── worker ──────┘
         claim kb_index_jobs
         (SKIP LOCKED)
```

**Locked stack**
| Layer | Choice |
|---|---|
| Vector store | Postgres + **pgvector** only (no Chroma/Pinecone) |
| Embedding | Azure **embedding deployment** (env), dim **pinned 1536** |
| Chat | Azure **chat deployment** (env) |
| Object store | **MinIO from KB-2**; disk for bootstrap |
| Tenancy | **Global KB** (no `tenant_id` on `kb_*` in this workstream) |
| Jobs | `kb_index_jobs` + **SKIP LOCKED** worker (single-node PoC) |
| API style | Same as Documents/Inbox: `schemas.py` → `db.py` → `main.py` → `api/kb.ts` |

---

## 4. Infra & configuration

### 4.1 Azure OpenAI (env only — never commit keys)

Deployment names are **whatever is provisioned on your Azure resource**, not fixed OpenAI model IDs. A mismatch yields a silent/opaque Azure 404. Set env to **match your deployments**; do not treat example strings as canonical.

```env
AZURE_OPENAI_ENDPOINT=https://....openai.azure.com/
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_API_VERSION=2025-04-01-preview
# These MUST match deployment names in your Azure OpenAI resource:
AZURE_OPENAI_CHAT_DEPLOYMENT=<your-chat-deployment-name>
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=<your-embedding-deployment-name>
# Pinned hard — kb_chunks.embedding is vector(1536); any other dim fails INSERT
AZURE_OPENAI_EMBEDDING_DIMS=1536
```

Assert at startup: `AZURE_OPENAI_EMBEDDING_DIMS == 1536` (fail fast if misconfigured).

Add placeholders to `backend/.env.example`. Runtime client: `backend/azure_openai.py` using official `openai` Azure client.
- `embed_texts(texts: list[str]) -> list[list[float]]` (batched); validate each vector length == 1536
- `chat_complete(messages, ...) -> str`
- Timeouts, retries, structured logging (latency, token usage, **deployment name from env**)

### 4.2 MinIO — Phase KB-2 (not KB-0)

```yaml
# Conceptual — wire into compose at KB-2
minio:
  image: minio/minio
  command: server /data --console-address ":9001"
  ports: ["9000:9000", "9001:9001"]
  volumes: [minio_data:/data]
  environment:
    MINIO_ROOT_USER: minioadmin
    MINIO_ROOT_PASSWORD: minioadmin
```

App env (KB-2+):
```env
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=collections-kb
MINIO_SECURE=false
```

Helper: `backend/storage.py` (introduced at KB-2)
- `put_bytes(key, data, content_type) -> storage_ref`
- `get_bytes(storage_ref) -> bytes`
- `storage_ref` format: `minio://{bucket}/kb/{doc_id}/{filename}` — **no `{tenant}` segment** (KB is global; path is future-simple, not fake-multi-tenant)
- Ensure bucket on API lifespan when MinIO is configured

**KB-0/KB-1 bootstrap:** read files from `source_db/` via absolute/repo-relative paths; no MinIO required. Optional later: copy originals into MinIO when standing up KB-2 so the library has downloadable sources.

### 4.3 Vector index — avoid filtered-HNSW under-return

**Demo risk #1:** A plain query that `WHERE d.enabled AND d.status='indexed' AND c.embedding IS NOT NULL` then `ORDER BY embedding <=> q LIMIT k` is unsafe with HNSW. pgvector applies those predicates **after** the index returns candidates, so `LIMIT k` can under-return (or the planner falls back to seq scan) once disabled/unindexed chunks sit near the query. Clean corpus of 27 docs hides this; disabling one doc breaks the demo.

**Chosen fix (ship this — not the plain filtered query):**

1. **Partial HNSW** — only rows with embeddings participate in the index:
   ```sql
   CREATE INDEX IF NOT EXISTS idx_kb_chunks_embedding_hnsw
     ON kb_chunks USING hnsw (embedding vector_cosine_ops)
     WHERE embedding IS NOT NULL;
   ```
2. **Disable = remove from searchable set** — on `enabled=false` (or status leaving `indexed`), **delete that document’s chunks from `kb_chunks`** (or move to a side table). Re-enable re-queues an index job that re-embeds from source. Searchable table ≈ “what HNSW should see.”
3. **Over-fetch safety net** — still fetch `LIMIT k * 4` from the ANN path, then filter/trim to `k` in Python (handles residual status races without silent short lists). Prefer pgvector ≥ 0.8 `SET hnsw.iterative_scan = 'relaxed_order'` **per retrieve transaction** when available; keep over-fetch as portable fallback.

**Do not ship** the naïve filtered `LIMIT :k` as the only path.

### 4.4 Worker

- Entry: `python -m backend.worker` (or lifespan background task in API for single-node PoC)
- Loop: claim next `kb_index_jobs` where `status='queued'` with `FOR UPDATE SKIP LOCKED` → `running` → process → `succeeded`/`failed`
- Idempotent: re-running a job for a doc **atomically replaces** that doc’s chunks (see §7)
- **Stuck-job reaping:** by `updated_at` age (PoC-correct). No `locked_by` column — fine for single-node SKIP LOCKED; if we ever scale to multiple workers we cannot attribute a stuck `running` job to a specific worker without adding `locked_by` / lease metadata. Note that limit; do not pretend we have multi-worker observability yet.

---

## 5. Schema gaps (migration)

Align DB with UI shapes in `kb-seed.ts` and production needs:

| Change | Why |
|---|---|
| `kb_documents.tags jsonb DEFAULT '[]'` | UI tags |
| `kb_documents.embedding_model text` | Show model on inspector (store **deployment name** used) |
| `kb_documents.last_indexed_at timestamptz` | KPI + table column |
| `kb_documents.product_key text` | Group Car/Home/Travel across policy/benefits/FAQ |
| **Add** `kb_documents.type` CHECK | Today there is **no** type CHECK — we are **adding** one. Allowed values for ingest: `policy`, `benefits` (plus UI leftovers `sop`, `product`, `compliance`, `faq` if we keep seed parity). Ingest values **must** match the CHECK or inserts fail. |
| `kb_chunks.chunk_index integer NOT NULL` | Ordered chunk list |
| Partial HNSW on `kb_chunks.embedding WHERE embedding IS NOT NULL` | Safe ANN (§4.3) |
| Optional: `faq_pairs.embedding vector(1536)` | Hybrid FAQ retrieval |
| **No `tenant_id` on `kb_*` in this workstream** | Global KB (§1 decision 6). Phase-5 per-tenant = new migration + retrieve scope. |

Filename stays on `kb_source_files` (JOIN for list serialization; populated at KB-2 / optional backfill).  
`updatedBy` from `users` via `updated_by_user_id`.

---

## 6. Corpus: `source_db`

### Demo narrative
App tenant/branding is **HDFC retail collections**. Corpus is **HL Assurance** insurance products. That is intentional: the bot **cross-sells / upsells insurance** (Upsell & Leads screen) using this KB — one story, not two unrelated datasets. Surface product names clearly in doc titles/tags (`product_key`, tags like `car`, `travel`).

### Explicit ingest manifest (required)

Do **not** glob `{Product}_FAQs.txt`. Hardcode every path. Missing or misnamed file → **hard fail** the bootstrap with the product key and expected path.

```python
# Conceptual — backend/scripts/kb_corpus_manifest.py
CORPUS_MANIFEST = [
  {
    "product_key": "car",
    "policy": "source_db/policy/Car_policy.md",
    "faq": "source_db/FAQ/Car_FAQs.txt",
    "benefits": "source_db/benefits/Car_benefits.txt",
  },
  {
    "product_key": "fraud",
    "policy": "source_db/policy/Fraud_policy.md",
    "faq": "source_db/FAQ/Fraud_FQAs.txt",  # real filename (typo preserved)
    "benefits": "source_db/benefits/Fraud_benefits.txt",
  },
  # ... every product, every path explicit ...
]
```

Bootstrap validates: for each entry, all three paths exist and are non-empty **before** any DB write. One missing file aborts the whole run.

### Inventory (27 files, 9 products) — mirror of manifest

| product_key | Policy | FAQ | Benefits |
|---|---|---|---|
| car | `policy/Car_policy.md` | `FAQ/Car_FAQs.txt` | `benefits/Car_benefits.txt` |
| choice | `policy/Choice_policy.md` | `FAQ/Choice_FAQs.txt` | `benefits/Choice_benefits.txt` |
| early | `policy/Early_policy.md` | `FAQ/Early_FAQs.txt` | `benefits/Early_benefits.txt` |
| fraud | `policy/Fraud_policy.md` | `FAQ/Fraud_FQAs.txt` | `benefits/Fraud_benefits.txt` |
| home | `policy/Home_policy.md` | `FAQ/Home_FAQs.txt` | `benefits/Home_benefits.txt` |
| hospital | `policy/Hospital_policy.md` | `FAQ/Hospital_FAQs.txt` | `benefits/Hospital_benefits.txt` |
| maid | `policy/Maid_policy.md` | `FAQ/Maid_FAQs.txt` | `benefits/Maid_benefits.txt` |
| personal_accident | `policy/PersonalAccident_policy.md` | `FAQ/PersonalAccident_FAQs.txt` | `benefits/PersonalAccident_benefits.txt` |
| travel | `policy/Travel_policy.md` | `FAQ/Travel_FAQs.txt` | `benefits/Travel_benefits.txt` |

### Ingest mapping

| Source kind | → `kb_documents.type` | Indexing strategy |
|---|---|---|
| policy `.md` | `policy` | Markdown heading-aware chunking → `kb_chunks` + embeddings |
| benefits `.txt` | `benefits` | Paragraph/sentence chunking → `kb_chunks` + embeddings |
| FAQ `.txt` | (rows in `faq_pairs`) | Parse `Q:` / `A:` → **`faq_pairs`**; optionally embed Q+A for hybrid retrieval |

**FAQ parse rule:** lines starting with `Q:` start a question; following `A:` (multi-line until next `Q:`) is the answer. `intent` = slug from `product_key` + short hash of question. `linked_document_id` → matching policy doc for that product.

**Bootstrap script:** `backend/scripts/ingest_source_db.py`
1. Load manifest; **fail loud** if any path missing
2. Read each file from disk (`source_db/…`)
3. Create/update `kb_documents` / `faq_pairs`
4. Enqueue `kb_index_jobs` (or embed inline for first bootstrap)
5. Worker (or inline) fills vectors — **no MinIO in KB-0/1**

Seed IDs: stable keys like `kb-policy-car`, `kb-benefits-car`, `faq-car-001`, …

---

## 7. Indexing pipeline

### KB-0/1 (disk bootstrap)

```
Manifest entry
  → read bytes from source_db path
  → kb_documents status=indexing (+ product_key, type, tags)
  → kb_index_jobs status=queued
       │
       ▼
Worker claims job (SKIP LOCKED)
  → read source text (from path recorded on job/doc, or re-read known bootstrap path)
  → extract text (md/txt passthrough)
  → chunk with tiktoken (size/overlap from job; default 512 / 64 tokens)
  → batch Azure embeddings (assert dim 1536)
  → ATOMIC replace (§7.1)
  → doc status=indexed, last_indexed_at=now()
  → job status=succeeded
  On error: job failed + error text; doc status=failed; OLD chunks left intact
```

### KB-2+ (upload / re-index from MinIO)

Same pipeline, but bytes come from MinIO via `kb_source_files.storage_ref`.

### 7.1 Re-index atomicity (mandatory)

**Never** delete-then-embed. If Azure fails mid-way after a delete, the doc has zero chunks, still looks “indexed,” and silently drops out of retrieval.

**Required ordering:**

1. Chunk source text in memory  
2. **Embed all new chunks first** (Azure calls complete successfully; vectors in memory / temp structure)  
3. **Then, in ONE DB transaction:**  
   - `DELETE FROM kb_chunks WHERE document_id = :id`  
   - `INSERT` all new chunk rows (text + embedding + chunk_index)  
   - Update `kb_documents` → `status='indexed'`, `last_indexed_at=now()`  
   - Update job → `succeeded`  
4. On any failure before/during step 2: leave existing chunks untouched; mark job `failed`, doc `failed` (or keep previous `indexed` if we prefer availability — prefer **failed + old chunks retained** so retrieval does not go empty)

Disable path: `enabled=false` → delete chunks (or exclude via side table) in a transaction with the flag flip, so HNSW searchable set stays consistent (§4.3). Re-enable → enqueue job → embed → atomic insert.

### Defaults
- `chunk_size`: **512 tokens** measured with **tiktoken** (required). Do **not** use a chars/4 heuristic — that inverts the relationship (512 tokens ≈ 2048 chars, not 512 chars) and produces ~4× undersized chunks.
- `overlap`: **64 tokens** (tiktoken)
- `embedding_model`: value of `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`
- Skip re-index if content hash unchanged and chunk params unchanged

### Versioning (“New version”) — KB-2+
- New `kb_source_files` row in MinIO, bump `kb_documents.version`, re-queue job
- Atomic replace only after successful embed (§7.1); prior MinIO object retained for audit

---

## 8. Retrieval pipeline

### Core `retrieve(query, k, source)` — global KB (no tenant filter)

1. Embed query via Azure (dim assert 1536)
2. ANN search with **over-fetch + trim** (and iterative_scan when available):
   ```sql
   -- Inside a transaction; if pgvector >= 0.8:
   --   SET LOCAL hnsw.iterative_scan = 'relaxed_order';
   SELECT c.*, d.title, d.id AS doc_id, d.status, d.enabled
   FROM kb_chunks c
   JOIN kb_documents d ON d.id = c.document_id
   WHERE c.embedding IS NOT NULL
     -- Prefer: disabled docs have no rows in kb_chunks (§4.3).
     -- Residual filter still applied after over-fetch:
     AND d.enabled = true AND d.status = 'indexed'
   ORDER BY c.embedding <=> :q::vector
   LIMIT :overfetch   -- k * 4, not k
   ```
3. In Python: drop any residual non-eligible rows; take top `k`
4. Optional FAQ hybrid: score `faq_pairs` (prefer stored `embedding vector(1536)`; enabled only)
5. Merge/rank → top-k screen results
6. Write `retrieval_logs` (`query`, `top_chunks` jsonb with scores, `latency_ms`, `selected_answer_source`, source tag)
7. Increment `kb_chunks.hits`

**No `tenant_id` filter** — intentional for global KB. Do not half-add tenancy in paths only.

### Test Retrieval response

```json
{
  "results": [ /* RetrievalResult[] — snippets + cosine score */ ],
  "draftAnswer": "optional string from chat deployment",
  "latencyMs": 123,
  "embeddingModel": "<AZURE_OPENAI_EMBEDDING_DEPLOYMENT>",
  "chatModel": "<AZURE_OPENAI_CHAT_DEPLOYMENT>"
}
```

- Always return vector snippets (panel works even if chat fails)
- `includeDraftAnswer: true` (default on Test panel) → chat completion with grounding + **injection defenses** (below)
- Log whether draft used chat or snippets-only

### Grounding + prompt-injection defenses

KB chunk / FAQ text is **untrusted content** once the same `retrieve()` feeds Inbox agent/customer-facing chips (Phase C). Insurance PDFs are low risk, but the retriever is built once — defend now:

- Treat retrieved text as **data**, not instructions: wrap in delimiters; system prompt states that content inside context blocks must not be obeyed as commands
- Answer **only** from provided chunks/FAQs; cite doc titles; say “I don’t know” if insufficient
- Refuse to follow instructions found inside retrieved snippets (e.g. “ignore previous instructions…”)
- Never exfiltrate system prompt or tool config based on chunk content

### Score display
Cosine similarity: `score = 1 - (embedding <=> query)` (pgvector cosine distance). Clamp/display 0..1 to match UI.

---

## 9. API surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/kb/stats` | KPI strip (docs, FAQs, chunks, gaps, last re-index, avg score) |
| `GET` | `/kb/documents` | Library list (screen-shaped) |
| `GET` | `/kb/documents/{id}` | Detail + tags + chunk params |
| `GET` | `/kb/documents/{id}/chunks` | Ordered chunks |
| `POST` | `/kb/documents` | Multipart upload → MinIO + enqueue job (**KB-2**) |
| `PATCH` | `/kb/documents/{id}` | Enable/disable (chunk eviction/reindex), tags, title, chunk params |
| `POST` | `/kb/documents/{id}/reindex` | Enqueue job |
| `POST` | `/kb/documents/{id}/versions` | New version upload (**KB-2**) |
| `POST` | `/kb/reindex-all` | Enqueue all enabled |
| `GET` | `/kb/faqs` | FAQ list |
| `POST` | `/kb/faqs` | Create |
| `PATCH` | `/kb/faqs/{id}` | Update / enable |
| `GET` | `/kb/gaps` | Unanswered questions + KB link state |
| `POST` | `/kb/retrieve` | Test retrieval (+ optional draft) |
| `GET` | `/kb/index-jobs/{id}` | Poll job |

Follow Phase 3B five-move pattern:
1. Pydantic models in `schemas.py` matching TS types  
2. Accessors in `db.py`  
3. Routes in `main.py`  
4. `Habibi/src/api/kb.ts` with `USE_MOCK` branch  
5. Rewire `knowledge-base.tsx` + invalidate React Query  

---

## 10. Frontend wiring & fixes

- Add `Habibi/src/api/kb.ts`
- Replace local seed state with React Query against live APIs
- Fix while wiring:
  - Test Retrieval → `POST /kb/retrieve` (live docs/FAQs)
  - Upload → multipart; poll job; refetch chunks (**KB-2**)
  - FAQ linked-doc dropdown → live documents list
  - New version → `POST .../versions`
  - Gaps Attach doc → open upload or link flow
  - Stats avg score → from `/kb/stats` / `retrieval_logs`
- Keep seed behind `VITE_USE_MOCK=true` for offline UI work
- Product titles/tags should read as insurance upsell KB (HL Assurance products), not generic “policy doc #3”

---

## 11. Delivery phases (best path)

### Phase KB-0 — Foundations (disk ingest; no MinIO)
- [x] Azure env + client + smoke embed/chat; **assert EMBEDDING_DIMS=1536**; deployment names from env
- [x] Alembic: schema gap columns; **add** `type` CHECK; optional `faq_pairs.embedding`; **partial HNSW**
- [x] `kb_chunking` with **tiktoken** (512 / 64 tokens)
- [x] `kb_ingest` + atomic replace (§7.1) + SKIP LOCKED worker + `updated_at` reaper
- [x] Explicit `CORPUS_MANIFEST` + `scripts/ingest_source_db.py` reading `source_db/` from disk (loud fail)
- [x] Verify: all manifest files ingested; chunks non-null embeddings; disable-doc does not under-return top-k

### Phase KB-1 — Retrieval spine (first visible win)
- [x] `POST /kb/retrieve` with over-fetch (+ iterative_scan if available) — **not** plain filtered `LIMIT k`
- [x] `retrieval_logs` + hits
- [x] Optional draft answer with grounding + injection defenses
- [x] Wire Test Retrieval tab live
- [x] Manual quality check: Car NCD / windscreen, Travel, Home; plus **disable one doc and confirm top-k still fills**

### Phase KB-2 — MinIO + library admin
- [x] MinIO in docker-compose + `storage.py` (`minio://{bucket}/kb/{doc_id}/...`)
- [x] List/get documents + chunks + stats
- [x] Upload wizard → MinIO + `kb_source_files` + job
- [x] Enable/disable (chunk eviction) + re-index one/all + job polling
- [x] Wire Documents tab + inspector + upload wizard
- [x] New version endpoint + button
- [x] Optional: backfill bootstrap originals into MinIO

### Phase KB-3 — FAQs + Gaps
- [x] FAQ CRUD APIs + wire FAQ tab/editor
- [x] Gaps from live analytics tables
- [x] Create FAQ from gap; attach/link document

### Phase KB-4 — Consumers & hardening
- [x] Shared `retrieve()` → Inbox `ai_response_suggestions` (debounced); same injection posture
- [x] Optional LLM draft rewrite: Inbox flips `includeDraftAnswer` (same grounded `kb_retrieve` path as Test Retrieval — no second rewrite)
- [x] Rate limits / batch embed sizing / stuck-job reaper tuning
- [x] Content-hash skip for no-op re-index
- [x] Snapshot hook (`kb_snapshots`) for sandbox readiness
- [x] Ops: logging, error surfacing in UI, `.env.example` complete
- [ ] (If needed later) Phase-5: add `tenant_id` to `kb_documents` + `faq_pairs` and scope retrieve — not before

---

## 12. Production checklist

- [ ] Secrets only in `.env` (rotate any key that was pasted in chat)
- [ ] Never commit `.env`, MinIO secrets, or Azure keys
- [ ] Deployment names match Azure resource; `EMBEDDING_DIMS=1536` asserted
- [ ] Partial HNSW + disable-evicts-chunks + over-fetch; **no** naïve filtered `LIMIT k`
- [ ] Re-index: embed-all → single txn delete+insert; never delete-then-embed
- [ ] Manifest ingest; no glob for FAQ filenames
- [ ] Index job is source of truth for status (no fake `setTimeout`)
- [ ] Failed jobs leave actionable `error`; **old chunks retained** on failed re-index
- [ ] Structured logs: job id, doc id, latency, embed/chat tokens, deployment names
- [ ] Draft answer grounded + injection-resistant
- [ ] KB global: no fake `{tenant}` in `storage_ref`; no silent tenant filter
- [ ] Demo story: insurance upsell KB for collections bot
- [ ] Distinguish RAG corpus from Document Desk fulfilment files
- [ ] Worker: single-node SKIP LOCKED; reaper by `updated_at`; no `locked_by` until multi-worker

---

## 13. Module layout (proposed)

```
backend/
  azure_openai.py       # embed + chat client (deployment names from env)
  kb_chunking.py        # md/txt/FAQ parsers + tiktoken chunker
  kb_ingest.py          # job processor: fetch → chunk → embed → ATOMIC write
  kb_retrieve.py        # over-fetch ANN + optional draft (+ injection posture)
  worker.py             # SKIP LOCKED claim loop + updated_at reaper
  storage.py            # MinIO put/get (KB-2+)
  scripts/
    kb_corpus_manifest.py  # explicit product → paths
    ingest_source_db.py    # disk bootstrap; loud fail
  sql/ + alembic/       # partial HNSW + column gaps + type CHECK
  main.py / db.py / schemas.py  # /kb/* routes

Habibi/src/api/kb.ts    # USE_MOCK seam
```

---

## 14. Dependencies to add

**Python (KB-0):** `openai`, `tiktoken` (required for chunk sizing), `httpx` if not pulled  
**Python (KB-2):** `minio` (or `boto3` S3 API)  
**Compose (KB-2):** `minio` (+ optional `minio/mc` bucket init)  
**Frontend:** none new beyond existing React Query / fetch helpers

---

## 15. Success criteria

1. All **manifest** policies/benefits chunked + embedded; all FAQs loaded (including Fraud via `Fraud_FQAs.txt`); missing path aborts ingest
2. Test Retrieval returns real cosine-ranked snippets for insurance upsell queries
3. Disabling a document does **not** under-return top-k
4. Failed re-index leaves previous chunks searchable
5. Optional draft answer cites docs, refuses unsupported claims, ignores instructions inside chunks
6. Upload / re-index / enable-disable work end-to-end via MinIO + jobs (**KB-2**)
7. Mock UI path still available via `VITE_USE_MOCK`
8. Same `retrieve()` callable later for Inbox chips without a second pipeline

---

## 16. Explicit non-goals (this workstream)

- Pipecat / voice runtime RAG (Phase 4 — reuse this retriever later)
- Replacing Document Desk fulfilment storage
- Separate vector DB
- Per-tenant KB / `tenant_id` on `kb_*` (defer to Phase-5 if needed)
- Multi-worker `locked_by` leases (single-node PoC)
- Full Keycloak hardening (keep existing actor/tenant env pattern for non-KB screens)

---

*KB workstream complete through **KB-4**. Optional later: Phase-5 per-tenant KB if required.*
