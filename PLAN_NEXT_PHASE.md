# Collections Agent — Next-Phase Plan

Continues [PLAN.md](PLAN.md). Phases 1–2 (frontend seam + enterprise Postgres read layer) are **done**. This plan covers everything from here to a near-production system.

## Where we are (done ✅)

- **Frontend** — 24 TanStack screens; golden-path screens read through `src/api/*` seams.
- **Enterprise data layer** — 106 tables + `work_items` view in PostgreSQL 16 (Docker, pgvector), fully seeded (18 customers, 42 interactions, cross-linked, 0 orphans, 205 FKs / 77 CHECKs / 200 indexes validated). Triggers for `updated_at`, invariant constraints, Alembic baseline.
- **Read API** — FastAPI + SQLAlchemy Core + Pydantic (`schemas.py`) emitting the frontend contract; verified rendering on Postgres.

## 0. Immediate cleanups (small, do first)

- [ ] Add `.env` to `backend/.gitignore` (holds credentials).
- [ ] Seed polish: the synthetic "extra" customers show placeholder values (`₹0`, `0d`, `1 Jan`, mixed `HDFC-RL-…`/`AC-…` formats). Backfill realistic values or drop them so every customer looks real.
- [ ] Re-verify the other golden-path screens on Postgres (Dashboard, Audit, Upsell, Handoff) the way Customer 360 was verified.

---

## Phase 3A — Write / Mutation layer  ⭐ (do next — the pivotal enabler)

Everything is read-only. The screens have real actions and none persist; Pipecat can't write back either. This unblocks both. **Prerequisite for Phase 4.**

**Backend (per entity: Pydantic request model → endpoint → transactional write → `activity_events` row):**
- [ ] **Interactions / call wrap-up** — `POST /interactions/{id}/wrap-up` (disposition, notes, flags) and `POST /interactions` (log manual call). Wrap-up may spawn a promise/dispute/callback.
- [ ] **Promises** — `POST /promises` (create/capture PTP), `PATCH /promises/{id}` (status → kept/broken/partial, reschedule, paid_amount). Broken → auto-create `followup`. Payment plans: `POST /payment-plans` (+ first installment promise).
- [ ] **Disputes** — `POST /disputes`, `PATCH /disputes/{id}` (status transitions, assign), `POST /disputes/{id}/evidence`, resolve/reject with `resolution_code`.
- [ ] **Callbacks** — `POST /callbacks`, `PATCH /callbacks/{id}` (reschedule/assign/status/disposition), `POST /callbacks/{id}/reminders`. Respect consent/DND window.
- [ ] **Leads** — `POST /leads`, `PATCH /leads/{id}` (stage move, assign, won/lost, offer edit), `POST /leads/{id}/followups`.
- [ ] **Documents** — `POST /document-requests`, `PATCH` (status), delivery attempts.
- [ ] **Customer notes** — `POST /customers/{id}/notes`.
- [ ] **Consent** — `PATCH /consent/{customer_id}` (channels, DND toggle, renew), `POST /consent/{customer_id}/opt-out`.
- [ ] **Compliance** — `PATCH /violations/{id}` (status/assign/notes).
- [ ] **QA** — `POST/PATCH /scorecards`, coaching actions.

**Cross-cutting conventions:**
- [ ] Every mutation writes an `activity_events` row (unified timeline / Customer 360 feed).
- [ ] All writes transactional; return the updated resource (via `schemas.py`).
- [ ] Validation + proper error codes (404 / 409 conflict on illegal state transition / 422).
- [ ] Idempotency keys where the bot may retry (call wrap-up, PTP capture).
- [ ] Optional: optimistic-concurrency via `updated_at` check.

**Frontend:**
- [ ] Replace the in-memory mutation helpers (upsell `moveStage`, customer360 `submitSheet`, etc.) with TanStack `useMutation` calling the new endpoints + query invalidation.
- [ ] Toasts/errors from real responses.

**Acceptance:** capture a PTP in Customer 360 → row in `promises` + `activity_events` → appears on the Promises screen and the customer timeline after refetch.

---

## Phase 3B — Wire the remaining screens (breadth)

Enterprise data is already seeded for all of these; each is endpoint(s) + `schemas.py` mapping + frontend seam. Parallelizable. Tier by value:

- [ ] **Tier 1 (collections core):** Promises, Disputes, Callbacks, Consent/DND, Compliance, Bot Analytics, Document Fulfilment.
- [ ] **Tier 2 (QA/bot config):** QA Scorecards, Redaction, Knowledge Base, Prompt Studio, Call Simulation Sandbox, Routing Builder.
- [ ] **Tier 3 (admin/live-ops):** Integrations, Webhooks, Billing, Floor Command, Conversation Inbox, My Workspace (`work_items` view), Notifications, Settings.

Notes: config screens (KB, Prompt Studio, Routing, Integrations, Webhooks) are **editing** surfaces — they need write endpoints too, coordinate with 3A. Floor/Inbox/Handoff live data comes fully alive in Phase 4 (WebSocket).

---

## Phase 4 — Pipecat voice bot (the product core)

**Pipeline:**
- [ ] Pipecat orchestrator: **Twilio** (telephony) → **Deepgram** (STT) → **LLM** (Azure/OpenAI, tool-calling) → **ElevenLabs** (TTS).
- [ ] Wire provider keys from the Integrations config (or `.env`).

**Bot capabilities (from `features.md`):**
- [ ] Caller identification (phone → customer) + identity verification → `identity_verifications`.
- [ ] Tools calling **read** endpoints: dues/balance, payment history, EMI schedule, late-fee/waiver info, upsell eligibility.
- [ ] **RAG** for FAQ/policy: add `vector` column + HNSW index on `kb_chunks`, embedding pipeline, retrieval → `retrieval_logs`.
- [ ] Compliance disclosures (recording notice, mini-Miranda) → `interaction_disclosures`.
- [ ] Sentiment monitoring + escalation triggers via `routing_rules`.
- [ ] Contextual upsell (eligibility-gated, sentiment-gated) → capture `leads`.
- [ ] Dispute capture → `disputes`.

**Write-back (uses Phase 3A endpoints):**
- [ ] On hang-up: generate summary, disposition, PTP/lead/dispute → persist via mutation endpoints → Dashboard/Customer 360 update.
- [ ] AHT + upsell-conversion metrics logged.

**Realtime (live-ops):**
- [ ] WebSocket streaming transcript + sentiment → **Handoff Hub** & **Floor Command** render live; supervisor actions (`supervisor_actions`) and human handoff (`interaction_handoffs`).

**Acceptance:** the golden path runs end-to-end — inbound call → identify → RAG-answered dues query → upsell → hang-up → summary + PTP land in the DB → screens reflect it.

---

## Phase 5 — Hardening (before production)

All already *designed-for*; this is enablement, not redesign.

- [ ] **RLS multi-tenancy** — enable Row-Level Security, policies per tenant, per-request `SET app.tenant_id` in the DB session middleware.
- [ ] **Auth (Keycloak/OIDC)** — self-hosted Keycloak, JWT validation, enforce against `roles`/`permissions`/`user_roles`; replace the hardcoded current-user.
- [ ] **PII encryption + Vault** — column encryption for phone/PAN/Aadhaar; HashiCorp Vault for provider secrets (resolve `vault://` refs).
- [ ] **Append-only audit** — revoke UPDATE/DELETE (or triggers) on `audit_log`, `optout_events`, `interaction_disclosures`, `activity_events`.
- [ ] **Partitioning** — monthly range partitions for `webhook_deliveries`, `billing_usage_daily`, `retrieval_logs`, `routing_rule_executions`, `interaction_sentiment`.
- [ ] **Task queue** — Arq/Celery (or Postgres `SKIP LOCKED`) for reminders, webhook delivery+retry, document generation, KB indexing.
- [ ] **Perf/infra** — pgbouncer pooling, async SQLAlchemy+asyncpg decision, rate limiting.
- [ ] **Observability** — structured logging, OpenTelemetry traces, health/readiness probes.
- [ ] **MinIO** — stand up self-hosted object storage; resolve `storage_ref` for media/documents/exports.

---

## Phase 6 — Deployment / Ops (Docker Compose on-prem)

- [ ] Full `docker-compose`: `db` (pgvector), `minio`, `keycloak`, `api`, `frontend`, `worker`, `redis` (if Arq).
- [ ] Env/secrets management; healthchecks; restart policies.
- [ ] Migrations run on deploy (Alembic `upgrade head`); **production seed strategy** (real data ingest, not synthetic).
- [ ] Backups (pg_dump/WAL), restore runbook.
- [ ] CI: lint, typecheck, migration check, smoke tests.

---

## Sequencing & dependencies

```
0. Cleanups ─┐
             ├─> 3A Mutations ─┬─> 3B Wire screens (breadth, parallel)
             │                 └─> 4 Pipecat (needs 3A write endpoints)
             └────────────────────> 5 Hardening ──> 6 Deploy
```
- **3A is the gate** — both 3B (frontend actions) and 4 (bot write-back) depend on it.
- 3B and 4 can run in parallel once 3A exists.
- 5 can start in parallel (RLS/auth/partitioning are largely independent) but must complete before 6.

## Open decisions to confirm

- LLM/STT/TTS providers actually licensed/available (Azure OpenAI vs OpenAI; Deepgram; ElevenLabs; Twilio account).
- Async vs sync data layer (recommend async + asyncpg if bot concurrency is high).
- MinIO now (Phase 4 media) vs local FS interim.
- Embedding model + `vector` dimension for RAG.

## Suggested immediate next action

Build **Phase 3A** starting with call-wrap-up + PTP + dispute writes (the collections core and exactly what the bot emits), and verify a create-PTP round-trips into Customer 360.
