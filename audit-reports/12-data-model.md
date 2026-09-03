# 12 — Data model

**Scope:** Habibi `backend/` — `sql/*.sql`, `alembic/versions/`, `db.py`, `schemas.py`, `voice/persist.py`, domain writers, `DATA_MODEL.md`.  
**Date:** 2026-09-02  
**Mode:** Read-only. No source, config, git, or dependency changes.  
**Companion reports:** [04-backend-architecture.md](./04-backend-architecture.md) (god-module persistence), [13-query-performance.md](./13-query-performance.md) (cost of access paths), [15-concurrency.md](./15-concurrency.md) (queues and races), [02-domain-capability-map.md](./02-domain-capability-map.md) §6 (one concept, many models).  
**Live catalog:** Docker was not available in this session. Table/constraint claims are from authored DDL and writers. Row counts and `pg_catalog` measurements in report 13 (2026-09-02, `collections_db`) remain the last live snapshot.

Legend:

- **Observed fact** — stated from repository evidence.
- **Strong inference** — supported by code + tests, with limited runtime uncertainty.
- **Weak inference** — plausible, needs a live catalog or race test.
- **Recommendation** — future work only; nothing in this audit was fixed.

Five parallel read-only analysts: SQLAlchemy/entity, migration, query, relationship, data-integrity. Every P0/P1 claim below was re-derived from source in this session, not taken from an agent summary alone.

---

## Verdict

Habibi has **no ORM and two sources of schema truth**. Entities are PostgreSQL tables authored in `backend/sql/*.sql` (filename order) plus an Alembic chain whose baseline is an empty stamp. Python talks to them through SQLAlchemy Core `text()` on one process-wide Engine (`db.py:138-150`). Pydantic v2 in `schemas.py` is the API contract, not the database model. `backend/models/` holds JSON ML artefacts (`propensity.json`, treatment estimators). `alembic/env.py` sets `target_metadata = None`, so autogenerate cannot drift from mapped classes because there are no mapped classes.

The book is **coherent where money, contact, and “one live row” matter, and split where a session is recorded**.

What is already well designed:

- **Partial unique indexes** for “one current”: active deployment, published prompt, open bounce per EMI, open pay-link per promise, live treatment hold, one champion model per target.
- **Idempotency that survived real incidents:** `idempotency_keys` PK is `(tenant_id, endpoint, key)` after a documented cross-tenant leak; WhatsApp `provider_ref`, bot-turn wamid, payment `(tenant, source, source_ref)`, Twilio `provider_call_id`.
- **Handler XOR CHECKs** on interactions, promises, violations, participants — the triplet `*_kind` + `*_user_id` + `*_bot_id` is a real invariant, not a comment.
- **`work_items` is a VIEW** (`sql/95_views.sql`). Domain tables stay authoritative. That decision is correct and should not be reversed.
- **`contact_events` + `contact_day_counters`** are the contact Gate’s ledger; `channel_consents.used_this_week` is an explicit cache refreshed from the ledger.

What is not done:

- **`DATA_MODEL.md` describes the original CRM book.** The live schema also contains outbound (`call_attempts` / `call_outcomes`), campaigns, policy-as-data, treatment/authority/reco logs, bot runtime queues, skills, MCP, work-runtime, and agent-card jsonb. The mermaid ERD is a subset, not a map of production.
- **Two session spines.** `interactions` is the CRM spine for a *connected* call or chat. `call_attempts` exists because an unanswered dial left no `interactions` row. They join optionally (`call_attempts.interaction_id` SET NULL). Treating either as “the” session entity is a modelling error.
- **Advertised hardening is still schema-shaped, not enforced.** RLS is derived in `rls.py` and off by default. PII sits in plaintext columns. `audit_log` has no immutability trigger. Production boot is allowed with `ALLOW_UNHARDENED_PRODUCTION=1`.
- **A handful of uniqueness rules the writers assume are not in the database:** one WhatsApp conversation per customer, one conversation per interaction, one active PTP per account, unique EMI `(account_id, installment_index)`.

This is not a rewrite candidate. It is a **constraint-backfill and documentation-sync** candidate: put the uniques the app already races on into Postgres, keep the dual spines and name them, and stop treating `DATA_MODEL.md` as current.

**Overall:** unusually strong *partial-unique* and *idempotency* design for a codebase of this size, unusually stale *intent documentation* relative to `sql/21`–`sql/22`, and a persistence layer that is a god module wrapping a carefully authored schema rather than an ORM wrapping a sloppy one.

---

## 1. How the “model layer” actually works

There is no SQLAlchemy ORM. Repo-wide application code does not use `declarative_base`, `Mapped[`, `relationship(`, `sessionmaker`, or SQLModel. Confirmed by `alembic/env.py:21` (`target_metadata = None`) and by `db.py:15-16` importing `create_engine`, `event`, `text` only.

```
HTTP / worker / voice
  → Pydantic body (schemas.py)  or  dict[str, Any]
  → db.py / ops_screens.py / followups_db.py / voice/persist.py / domain module
  → sqlalchemy.text(...) on engine.connect() | engine.begin()
  → PostgreSQL 16 + pgvector
```

| Layer | What it is | What it is not |
|---|---|---|
| `sql/*.sql` | Authoritative **current** shape. CI applies it, then **stamps** Alembic (`/.github/workflows/backend-pytest.yml:103-127`). | Not a migration history. |
| `alembic/versions/` | Deltas for databases that already exist. Head `20260901_0103`, linear from empty baseline `20260721_0001`. | Not replayable on a sql/-built DB (DuplicateColumn). |
| `schemas.py` | API/JSON contract. `CustomerResponse` `extra="forbid"`. Channel vocabulary includes `"call"`. | Not table classes. One customer JSON embeds one account. |
| `db.py` | Repository + serializer + CRM orchestration (~18k lines). | Not a unit of tenancy. Tenancy is predicates + a libpq GUC. |
| `backend/models/*.json` | Treatment/propensity artefacts on disk. | Not ORM models. `treatment_model_registry` is the ledger; files are what the audio path loads. |

Docker Compose does **not** auto-migrate. Comments at `docker-compose.yml:13-16` tell the operator to `alembic upgrade head` then optionally `seed_demo.py`. That upgrade path **fails on a truly empty volume**: baseline `0001` is a no-op, so 0002+ run against missing tables. Fresh install is sql/ then `stamp head` (CI). Docker quick-start omits the sql/ step — a topology gap, not a schema bug.

---

## 2. Census (from authored DDL)

**171 base tables** (no duplicate CREATE names) **+ 1 view** (`work_items`). Approx. **196 CHECK** clauses, **391 REFERENCES**, **17** inline UNIQUE, **34** unique indexes. Extensions: `vector` only (`sql/00_extensions.sql`). No native Postgres `ENUM` types — status machines are `TEXT` + `CHECK`, as `DATA_MODEL.md` specified. Nullable `tenant_id` appears on three tables: `policy_rule_sets` (statutory), `budgets` (org-wide), `audit_log` (SET NULL).

| Domain file | Tables (count) |
|---|---|
| `01_identity.sql` | 9 — tenants, teams, users, bots, agent_presence, RBAC |
| `02_customer_account.sql` | 8 — products, customers, accounts, ledger, EMI, payment_events |
| `03_consent.sql` | 8 — consent, channel_consents, contact ledger, policy-as-data |
| `04_interactions.sql` | 16 — interactions spine, conversations, messages, memory |
| `05_collections.sql` | 21 — PTP, disputes, docs, callbacks, treatment, mandates, authority |
| `06_sales.sql` | 5 — leads, NBO graph, offer_decisions |
| `07_compliance_qa.sql` | 12 — rules, violations, QA, live_qa, scans |
| `08_redaction.sql` | 6 |
| `09_bot_config.sql` | 20 — KB, prompts, TTS catalog, deployments, sandbox |
| `10_admin.sql` | 22 — providers, webhooks, billing, platform_switches |
| `11_analytics.sql` | 5 |
| `12_crosscutting.sql` | 8 — activity, audit, idempotency, bot queues, voice_sessions |
| `14`–`19` phases | eval, skills, MCP, work-runtime, A2A, canaries |
| `21_outbound.sql` | 3 — call_attempts, call_outcomes, agent_obligations |
| `22_campaigns.sql` | 5 — runs, targets, cadence, number pools |
| `95_views.sql` | `work_items` |

Alembic: **102 version files**, single head `20260901_0103` (revises `20260826_0102`). `tests/test_migrations.py` asserts exactly one head. Baseline `0001` `upgrade()` is `pass`.

---

## 3. Authoritative source-of-truth ranking

Read this as “what a regulator, a floor lead, or a later migration should believe,” not as table popularity.

### 3.1 True roots

| Entity | Why it wins |
|---|---|
| **`tenants`** | CASCADE hub. `id` is a slug (`hdfc.retail`). Process fallback `TENANT_ID` in `db.py:92`. |
| **`customers`** | Debtor identity. `consent_records.customer_id` UNIQUE (1:1). Global `id` TEXT PK (slug, not UUID). |
| **`accounts`** | Loan/card. Outstanding, DPD, bucket live here, **not** on `customers`. Customer 1—N Account is a real FK (`02_customer_account.sql:83`). |
| **`products`** | Catalog shared by accounts and NBO. |
| **`bots`** | Mouth identity. Agent Card is **not** a table; it is `prompt_versions.agent_card` jsonb. Retired mouths keep a row (`bots.archived_at`, `sql/20_agent_card_lifecycle.sql`). |
| **`users`** | Human staff. RBAC tables exist; enforcement is a separate control plane. |

### 3.2 Session and contact (two spines, both canonical)

| Entity | Question it answers | Not a substitute for |
|---|---|---|
| **`interactions`** | What happened in a *connected* voice or chat session? CRM 360, QA, redaction, transcript, Floor. | Reach metrics. Unanswered dials never create this row (`21_outbound.sql:8-14`). |
| **`conversations` + `messages`** | Text-transport layer (Inbox). `interaction_id` NOT NULL CASCADE — a live chat is on the spine from creation (`04_interactions.sql:172-174`; writer `db.py:10541-10580`). | Voice. A voice interaction usually has **no** conversation row until escalate creates one. |
| **`voice_sessions`** | Live bind: which worker/transport owns this interaction right now. Always hangs off `interactions`. | Transcript (that is `interaction_transcript`). |
| **`call_attempts` + `call_outcomes`** | What we *dialled*, including suppressions and no-answers. Outcome splits **connection** vs **business** (`21_outbound.sql:96-120`). 1:1 `ux_call_outcomes_attempt`. | `interactions.disposition` (legacy, four values conflating connect and conversation). |
| **`contact_events`** | Append-only outreach ledger. Source of truth for caps. | `channel_consents.used_this_week` (cache). |
| **`contact_day_counters`** | Atomic daily budget, `FOR UPDATE` inside `contact_policy.admit()`. | Application memory. |

### 3.3 Money and collections work

| Entity | Role |
|---|---|
| **`promises`** | PTP commitment. Amount + status machine. |
| **`payment_intents`** | Pay-link / settlement object for a PTP or bounce. Partial unique: one *open* intent per promise and per bounce event. |
| **`payment_plans` + `promise_installments`** | Installment schedule under a plan. Weaker CHECKs than `promises`. |
| **`ledger_entries`** | Posted transactions. `accounts.outstanding` is a **denormalized balance** some writers bump (bounce fee: `payment_events.py:316-318`) while ledger `balance` is nullable and often omitted on insert. |
| **`payment_events`** | Bounce *is* the case. Projects into `work_items` as `entity_type='bounce'`. |
| **`disputes`, `callbacks`, `document_requests`, `followups`, `leads`** | Domain queues. **Not** `work_items`. |
| **`treatment_holds`** | Collections veto. Partial unique on live `(customer, COALESCE(account,''), kind)`. |
| **`treatment_decisions` / `offer_decisions` / `authority_decisions` / `live_qa_decisions`** | Append-only engine logs. Each engine owns its log. |

### 3.4 Derived / cache / projection — do not write here as if it were state

| Surface | Kind |
|---|---|
| **`work_items`** | Read-only VIEW. UNION of open disputes, callbacks, docs, broken/due PTPs, leads, non-lead followups, open bounces. Status vocabulary is **not** unified: leads contribute `stage` into the `status` column. |
| **`channel_consents.used_this_week`** | Cache of `contact_events`. Refresh: `contact_policy.py:855-884`. |
| **`CustomerResponse.accountId` / `.outstanding`** | First account via `LEFT JOIN LATERAL … LIMIT 1` preferring `AC-%` (`db.py:1019-1028`). Multi-account borrowers look single-account on every list and 360 shell. |
| **`analytics_*`** | Materialized rollups for Bot Analytics. |
| **`kb_snapshots.document_ids` jsonb** | Frozen ID lists, not FKs. |

### 3.5 Config that versions behaviour

`prompt_versions` (one published per bot), `bot_deployments` (one active per bot+environment), `policy_rule_sets` / `policy_rules` (what was in force, with effective dates), `skills` / `skill_versions`.

---

## 4. Dual spines (not duplication — two questions)

```
                    tenants
                       │
                   customers ── accounts ── ledger / EMI / mandates
                       │
         ┌─────────────┼──────────────────────────────┐
         ▼             ▼                              ▼
   interactions   call_attempts ──────────► call_outcomes
   (connected)    (every dial, incl. no-answer)
         │             │
         ├── conversations ─ messages ─ bot_turn_jobs     (WhatsApp)
         ├── voice_sessions + interaction_transcript      (voice)
         ├── promises / disputes / callbacks / docs       (workflow origin, SET NULL)
         └── activity_events (polymorphic, no FK)
```

**Fact:** `call_attempts.interaction_id` is nullable SET NULL. An attempt can exist before connect and survive if the interaction is later deleted. That is the point of the table (`21_outbound.sql:8-14`).

**Fact:** WhatsApp creates the interaction **first**, then the conversation, in one transaction (`db.py:10541-10580`). Prefix is `IX-…`. Voice `start_voice_call` uses prefix `CL-…` (`voice/persist.py:36,131`) and commits the interaction **before** inserting `voice_sessions`, so a missing registry table does not roll back CRM (`voice/persist.py:122-214`). Manual CRM log uses `CL` again (`db.py:8337`).

**Identifier inconsistency (fact):** interaction ids are not one series. `IX` vs `CL` vs DATA_MODEL.md’s `CL-######`. All are TEXT. None are UUID primary keys (UUIDs appear only as suffixes inside `_sid` / `_id` helpers).

Voice and WhatsApp are not two conversation tables. `voice_sessions` never parents `messages`. Escalate may later insert a conversation for a voice interaction (`db.py` escalate path; `test_escalate_txn.py`).

---

## 5. Duplicate entities and duplicate concepts

“Duplicate” here means **two stores for one business question**, not two tables in a parent/child.

### 5.1 Same question, two answers (fix the name, rarely the table)

| Concept | Stores | What to believe |
|---|---|---|
| Mouth identity | `bots` vs “Agent Card” vs `bot_deployments` | `bots` = identity; `prompt_versions.agent_card` = grant/skills blob; `bot_deployments` = released combination. Not three Mouths. See report 02 §6.1. |
| Session outcome | `interactions.disposition` vs `call_outcomes.connection`+`business` vs `treatment_decisions.outcome` vs `callbacks.disposition` | Outbound: `call_outcomes`. Connected CRM: interaction. Treatment log is the engine’s own memory. |
| DND / consent | `customers.dnd` vs `consent_records.dnd_registry` vs `channel_consents` vs UI `optedIn: bool` | Channel+purpose row is the Gate. `customers.dnd` is a party flag. UI boolean **drops** `dnd`/`expired`. Mapping `_consent_channel`: SQL `voice` → API `"call"` (`db.py:897-901`, `schemas.py:57`). |
| Outstanding | `accounts.outstanding` vs `ledger_entries.balance` vs 360 JSON | Account column is what list/dashboard/promise fulfilment read. Ledger running `balance` is nullable and not always written (bounce fee insert lists no `balance`: `payment_events.py:301-303`). They can drift. |
| What we promised | `promises` (borrower PTP) vs `agent_obligations` (agent’s word) vs `customer_memory.open_commitments` jsonb | Money: `promises`. “I’ll send the statement”: `agent_obligations`. JSON memory is LLM state, **outside** the PTP table. Do not delete it as unused. |
| TTS voice | `tts_voices` (studio alias, 6-row era) vs `tts_voice_catalog` (Azure ShortName) vs `bot_deployments.tts_voice_id` (plain text after `20260727_0048` dropped the FK) | Catalog + ShortName string. `tts_voices` remains because Prompt Studio still has a table; the FK was the obsolete part. |
| Work | `work_items` VIEW vs `/handoff/queue` vs Inbox `needs_human` vs `work_runtime_jobs` vs Floor | Different audiences. Unifying them into one table would reintroduce status drift the VIEW was written to prevent. |
| Follow-up | `followups` (XOR promise/lead, CHECK at `05_collections.sql:260`) vs `callbacks` vs `agent_obligations` kind=`callback` | Human task vs scheduled call vs spoken promise. |

### 5.2 API shape vs relational shape (fact)

`CustomerResponse` (`schemas.py:151-171`) is a **document**: one `accountId`, nested ledger/EMI/promises. The database is 1—N accounts. `_base_customer_row` picks one account with a LATERAL limit. That is a presentation fold, not a second customer entity — but every operator screen that trusts `accountId` is looking at an arbitrary account.

`ConsentResponse.channel` is `Literal["call","whatsapp","sms","email"]`. SQL channel includes `voice` and `chat`. Chat consent is dropped in `_consent_channel` (`return None`).

Same table, two Pydantic contracts: `PromiseResponse.status` omits `due_today` (`schemas.py:110`) while `PromiseListResponse` includes it (`schemas.py:570+`) and the CHECK allows it (`05_collections.sql:23`). Customer 360 can 422 a valid row the Promises screen serializes.

### 5.3 Not duplicates (do not collapse)

- `activity_events` vs `audit_log` vs engine decision logs — timeline vs admin vs locked-engine evidence.
- `bot_turn_jobs` vs `whatsapp_outbound_jobs` vs `kb_index_jobs` vs `work_runtime_jobs` vs `webhook_deliveries` — four claim/lease queues plus an HTTP outbox. Same *pattern*, different objects.
- `interaction_transcript` vs `messages` vs `sandbox_run_turns` — channel-specific turn stores.

---

## 6. Identifier conventions

| Kind | Practice | Risk |
|---|---|---|
| PK | `TEXT` prefixed slugs (`vikram-rao`, `AC-#####`, `PTP-####`, `UNKNOWN-CALLER`) | Globally unique, **not** `(tenant_id, id)`. Two tenants cannot both own `UNKNOWN-CALLER`. |
| Tenant | `tenants.id` slug; GUC `app.tenant_id` at connect (`db.py:126-149`) | Child `tenant_id` is **not** CHECKed equal to parent’s tenant. An interaction can point at another tenant’s customer if a writer is wrong. RLS would hide this; RLS is off. |
| Phone | `customers.phone_primary` nullable, **no unique** | WhatsApp identity is an application lookup (`_find_customer_by_phone`). Two rows can share a number. |
| Email | `users.email` unconstrained unique | Staff collision is possible. |
| Handler | Triplet + XOR CHECK on several tables | `DATA_MODEL.md:246` lists `handoff` on interactions; SQL CHECK is only `'human','bot'` (`04_interactions.sql:6`). The doc is wrong. |
| Polymorphic | `activity_events.entity_type` + `entity_id` | No FK, no CHECK on `entity_type`. Orphans are insertable. Indexed `(entity_type, entity_id)`. |
| External | `provider_ref`, `provider_call_id`, `source_ref` | Opaque strings with partial uniques. `messages.provider_ref` unique is **global**, not per tenant. |
| Mission / campaign | `call_attempts.mission_id`, `campaign_run_id`, `deployment_id` | **Intentionally not FKs** (`21_outbound.sql:25-26`). `campaign_targets.account_id`, `decision_id`, `last_attempt_id` likewise unconstrained (`22_campaigns.sql:60-65`). |

**`UNKNOWN-CALLER` (fact):** `voice/persist.py:28-54` upserts a sentinel customer with a **global** primary key. `ON CONFLICT (id) DO NOTHING` does not retarget `tenant_id`. The first tenant to connect owns the row; later tenants reuse it. Interactions then store `tenant_id` of the caller process against a customer of another tenant. **Strong inference:** this is a tenancy hole the moment a second tenant exists in one database. Demo is single-tenant, so it is silent today.

---

## 7. Relationships and delete semantics

~380 `REFERENCES` tokens in `sql/` plus nine named constraints in `sql/90_deferred_fks.sql` (load-order and soft cycles: `teams.supervisor_user_id` ↔ `users.team_id`; `contact_delivery_events.message_id` before `messages` exists; `tts_voice_catalog.provider_id` before `providers`).

**M:N with pair PKs:** `role_permissions`, `user_roles`, `webhook_subscriptions`, `export_job_records`, `skill_attachments`. Fine.

**CASCADE that matters:** deleting a `tenants` or `customers` row wipes the book. `interactions` CASCADE wipes transcript, media, conversations, messages, queues, voice_sessions. Alembic `20260726_0042` changed queue FKs to CASCADE because customer erasure aborted mid-delete — that history is why those FKs look “aggressive.”

**Subtle CASCADE:** `treatment_holds.account_id` ON DELETE CASCADE — deleting an account drops account-scoped holds; customer-level holds (`account_id` NULL) remain. `supervisor_actions.supervisor_user_id` CASCADE — deleting a supervisor **removes the audit of barge/whisper**.

**SET NULL (origin survives, spine link dies):** promises/disputes/callbacks/leads `interaction_id`; `call_attempts.interaction_id`; `violations.interaction_id`.

**NO ACTION / RESTRICT:** catalog parents (`products`, rubrics, `prompt_versions.bot_id`, `agent_provider_bindings.provider_model_id` RESTRICT).

**Polymorphic / missing FKs — not automatically defects:**

| Column | Verdict |
|---|---|
| `activity_events.entity_id` | By design. Do not add a FK. Optional: CHECK on `entity_type` vocabulary. |
| `ledger_entries.invoice_id` | No FK to `invoices`. Billing invoices and account invoices may be different concepts; do not drop the column. |
| `bot_deployments.tts_voice_id` | FK **removed on purpose** (`0048`). ShortName string. |
| `bot_deployments.eval_report_id` | No FK. Nullable compiler artefact. |
| `kb_rate_limit_counters.tenant_id` | No FK (`12_crosscutting.sql:99`). Counter table; orphan tenant strings possible. |
| `bot_tool_calls.agent_id/skill_id/connector_id` | No FK. Writers often NULL. Attribution CHECK requires `job_id OR interaction_id` (`12_crosscutting.sql:152-153`). Keep. |
| `contact_events.related_id` | Opaque link to message id. Comment in `03_consent.sql:175-177` warns against a second FK. |

---

## 8. Constraints: what is strong, what is assumed

### 8.1 Strong (copy these)

Partial uniques: active deployment, published prompt per bot, open bounce per EMI, open payment intent per promise/event, live treatment hold (with `COALESCE` for NULL account), champion model, one due reminder per promise, provider-call uniqueness on attempts and voice_sessions, message wamid, bot-turn wamid, WhatsApp outbound job per message, contact delivery transition, MCP key hash while unrevoked, running canary/experiment.

XOR: handler triplets; followups exactly one of `promise_id`/`lead_id`; `policy_rule_sets` statutory ⇔ `tenant_id IS NULL`.

1:1: `consent_records.customer_id`; `qa_scorecards.interaction_id`; `redaction_records.interaction_id`; `call_outcomes.attempt_id`.

### 8.2 Assumed by writers, not enforced

| Assumption | Reality |
|---|---|
| One conversation per interaction | `idx_conversations_interaction_id` only (`04_interactions.sql:182`). Escalate “reuses latest.” |
| One WhatsApp thread per customer | SELECT latest then INSERT (`db.py:10510-10520`). **Two concurrent first messages → two threads.** |
| One active PTP per account | Status CHECK only. Multiple `upcoming` rows allowed. |
| Unique EMI schedule slot | `emi_installments` has **no** `UNIQUE (account_id, installment_index)`. Same for `promise_installments (plan_id, installment_index)`. |
| One `agent_presence` row per user | No unique on `user_id`. |
| Duplicate-lead guard | Index + advisory lock; **explicitly not unique** (`06_sales.sql:32-37`). |
| `accounts.status = 'active'` | Partial index `idx_accounts_delinquent` uses that string (`02_customer_account.sql:111-112`). Column has **no CHECK**. Same gap: `payment_plans.status`, `qa_scorecards.status`, `export_jobs.status`, `invoices.status`. |
| Amounts positive | `numeric(14,2) NOT NULL` without `> 0` on promises, intents, ledger. Signed ledger types (`charge`/`payment`/…) make a global `> 0` CHECK the wrong tool; a per-type CHECK is the missing one. |
| Append-only logs | Convention only. `13_triggers.sql` is `updated_at` on mutable tables. **`followups` is not in that mutable list** — `updated_at` will not auto-tick unless a later file added a trigger (none found). `audit_log` has no UPDATE trigger and no REVOKE. |

### 8.3 Suspicious nullables (with writers)

| Column | Why it looks wrong | Why it may be right |
|---|---|---|
| `customers.phone_primary` | WhatsApp key | Unbound / sentinel callers. Encrypt later, don’t NOT NULL without a story. |
| `interactions.account_id` | Spine without a loan | Unknown caller; chat before account pick. SET NULL on account delete. |
| `interactions.direction` | No default | Writers usually pass inbound/outbound. |
| `audit_log.tenant_id` | Platform actions; **weak RLS** | Documented nullable. Prefer NOT NULL + a platform tenant over “sometimes null.” |
| `budgets.tenant_id` | Org-wide vs tenant budgets | Two partial uniques (`uq_budgets_org_env_month` / `uq_budgets_tenant_env_month`). Intentional. |
| `policy_rule_sets.tenant_id` | Statutory binds everyone | CHECK-enforced. Intentional. |
| `disputes.disputed_amount` | Money optional | Some dispute types have no quantum. |
| `whatsapp_outbound_jobs.customer_id` | Send without a customer FK required | SET NULL parent; still has `to_phone`. |
| `messages.delivery_status` | No CHECK | Current state overwritten by receipts; history is `contact_delivery_events`. |

**Do not recommend dropping** `used_this_week`, `customers.dnd`, `interactions.disposition`, `tts_voices`, `customer_memory.open_commitments`, `prompt_versions.tuning`, or `calibration_sessions.name`. Each has migration and/or writer history (`0061` exists *because* those calibration columns were in `sql/` and missing from existing DBs).

---

## 9. Migration topology and drift

### 9.1 Two install paths (fact)

| Path | Who | What happens |
|---|---|---|
| **Fresh (CI, parity test, documented sql/ load)** | `backend-pytest.yml:103-127`, `test_schema_parity.py:124-129` | `CREATE EXTENSION vector`; apply `sql/*.sql` in sorted filename order; **`alembic stamp head`**. Migrations 0002+ are **not replayed** (would DuplicateColumn). |
| **Existing deployment** | Operator `docker compose exec api alembic upgrade head` | Replay 0002…0103 on top of whatever the volume had. |
| **Alembic roundtrip** | `test_migrations.py`, opt-in `RUN_ALEMBIC_ROUNDTRIP=1` | Scratch DB only; name must contain `test`/`scratch`/`ci`. |

`seed_guard.py`: schema always runs; demo INSERTs in old revisions only if `ALEMBIC_SEED_DEMO` is truthy. Default off. CI seeds via `scripts/seed_demo.py`, not Alembic.

### 9.2 Drift controls — and their blind spots

1. **CI regex** (`backend-pytest.yml:149-170`) extracts `op.create_table` / `op.add_column` from migration files and asserts those names exist after a sql/ load. **One direction only** (sql/ behind Alembic).
2. **Cannot see `op.execute("""CREATE TABLE …""")`.** Historically `voice_sessions` was created that way (`12_crosscutting.sql:200-206` comment): CI missed it; fresh sql/ DBs had no table; `persist.start_voice_call` swallowed the error; every CRM tool returned `no_interaction`.
3. **`test_schema_parity.py`** compares columns **and** index/constraint *definitions* (not names — 26 FKs differ only in auto vs explicit names). Opt-in scratch URL; CI **does** set `SCHEMA_PARITY_DATABASE_URL`.
4. **`20260812_0061`** exists because the reverse direction already happened: `calibration_sessions.name` / `target_scores` and `coaching_actions.category` were in `sql/` and in no migration. Existing deployments lacked columns every developer had.

`work_items`: `sql/95_views.sql` and Alembic `20260817_0082` claim to be mirrors (lead due date + hide lead-linked followups). Keep them in lockstep by hand; `CREATE OR REPLACE VIEW` cannot patch one UNION branch.

### 9.3 Destructive / irreversible (history, not a deletion list)

| Revision | What | Note |
|---|---|---|
| `0048` | DROP `bot_deployments` → `tts_voices` FK; rewrite `tts_voice_id` to ShortName | Behaviour change, not unused-column cleanup. |
| `0040` | DELETE duplicate `budgets` / `provider_configs` before unique indexes; change `idempotency_keys` PK | Data-collapsing on purpose. |
| `0073` | DELETE `prompt_versions` where `bot_id` still NULL | Fleet migration. |
| `0101` | Rewrite persona/prompt text that duplicated recording disclosure | Row repair; sql/ seeds regenerated from one source. |
| `0103` | UPDATE empty eval fixtures | Restores grader honesty; downgrade restores vacuous pass. |

**Ungated data on `upgrade head`:** `seed_guard.py` blocks demo INSERTs unless `ALEMBIC_SEED_DEMO` is set. Several revisions still mutate rows unconditionally: `0064` stock role grants, `0073` first-party bots + DELETE orphan prompts, `0101` persona text, `0103` eval fixtures. Those are repairs, but they run on a customer DB.

Baseline `0001` cannot rebuild a database. The rebuild artefact is `sql/`. There is no automated `work_items` VIEW parity test — sql/ and `0082` must stay twins by hand. Alembic roundtrip is opt-in and **off in CI** (`RUN_ALEMBIC_ROUNDTRIP: "0"`).

### 9.4 Hardening schema vs advertised

`DATA_MODEL.md:298-304` still says RLS, OIDC, and PII encryption are deferred. That remains true in DDL: **no `ENABLE ROW LEVEL SECURITY` in `sql/`**, no `pgcrypto` column encryption, no append-only trigger on `audit_log`. `rls.py` can derive policies from the FK graph and `scripts/rls.py enable` verifies counts inside a transaction. Application role today is expected to be superuser/BYPASSRLS — enable-without-provision is worse than off. `test_rls.py` covers derivation; live enforcement needs `RLS_DATABASE_URL`.

---

## 10. Queries as a model smell (not a latency audit)

Report 13 owns EXPLAIN and pool math. This section is only what queries reveal about the model.

**There is no repository package.** `db.py` is the repository. Domain engines (`contact_policy`, `outbound`, `payment_events`, `voice/persist`) issue their own `text()` SQL. `main.py` still has inline SQL on a few paths (report 04). That is three writers for some entities, which is how `accounts.outstanding` and `ledger_entries.balance` diverge.

**N+1 is explicit loops, not lazy-load.** `list_customers` is **not** N+1 (`include_detail=False`, one LATERAL). `get_customer` **is** a 360 fan-out: consent, ledger, EMI, interactions, promises, disputes, documents, notes (`db.py:1086-1158`) — a missing “customer 360” query object, not a missing ORM `joinedload`. `_customer_activity_preview` (`db.py:1188-1198`) ORs six `entity_id IN (SELECT …)` because `activity_events` is polymorphic. That is the cost of the unified timeline: one table, no FK, six probes. Inbox repeats the smell: `_thread_context` is five queries **per conversation** after `list_conversations` already batched messages. Webhook list hydrates each endpoint with four child queries (`ops_screens.py`). LATERAL “primary account” is copy-pasted (`db.py:1019-1028`, `:2241`, `:3406`, `:9040`).

**App-enforced integrity that should be constraints** (repeat of §8.2): WhatsApp conversation uniqueness, one active PTP, EMI pair unique. Lead uniqueness is **deliberately** app-only (re-engage lost leads). Do not add that unique without a product decision. Phone uniqueness is fail-closed in `_find_customer_by_phone` with **no unique index** and **no tenant predicate**.

**Tenant predicates:** `_base_customer_row` always filters `c.tenant_id` + `visibility.predicate` (`db.py:978`). `test_cross_tenant_reads.py` exists because seven list accessors historically had no tenant WHERE (including `list_callbacks` with **no WHERE at all**). Remaining holes unless RLS is on: `list_violations` (`db.py:7007-7043`), `list_conversations` base (`db.py:8994-9052` joins customers without `c.tenant_id`), `list_staff` / `list_teams`, `_find_customer_by_phone`. Child tables without `tenant_id` (`accounts`, `promises`, `disputes`, …) rely on join-to-customer. That is consistent with RLS hop-1 derivation — and invisible until RLS is on.

**Transaction taxonomy (model-relevant):**

| Pattern | Example | Integrity implication |
|---|---|---|
| Single `engine.begin()` | Most CRM writes | Interaction+conversation insert is atomic. |
| Commit interaction, then best-effort child | `voice/persist.py` voice_sessions | Prefer a live interaction with no registry row over rolling both back. Documented. |
| Claim + commit + carrier IO | outbound, webhook dispatch, WhatsApp send | Correct queue pattern (report 13/15). |
| Open txn across Twilio | payment-events webhook (`main.py` → `pe.ingest`) | Lock held across HTTP — concurrency report, not a missing table. |

---

## 11. Hidden integrity assumptions (verified)

| Claim in docs / comments | Verdict |
|---|---|
| Every chat has an `interactions` row from creation | **True** for `_open_whatsapp_conversation`. |
| `work_items` cannot drift | **True** — VIEW. Status *labels* still mean different things per `entity_type`. |
| `used_this_week` is a cache | **True** — rebuilt from `contact_events`. Tested `test_contact_policy.py`. |
| Interaction is the spine for *all* calls | **False** for unanswered outbound. `call_attempts` is that spine. |
| `DATA_MODEL.md` handler_kind includes `handoff` | **False** in SQL. Handoff is `interaction_handoffs`, not a handler_kind. |
| One published prompt per tenant | **False** after `0073`. Unique is per **bot**. |
| Secrets are vault refs | **Modelled** (`vault_refs`, `credential_ref`). Encryption of PII columns is not. |
| Append-only audit | **Convention.** No trigger. |
| `followups.updated_at` maintained by trigger | **Not** in `13_triggers.sql` mutable list. |

Python vs SQL enum: treatment holds, contact policy, handoff reasons, coaching statuses are aligned and tested. Cross-table drift: `a2a_tasks.status` uses `'input-required'` (hyphen) vs `work_runtime_jobs` `'input_required'` (underscore) (`18_phase5.sql:47-48` vs `17_phase4.sql:46-48`).

---

## 12. `DATA_MODEL.md` vs `sql/` (documentation debt)

The file is still the best **glossary of the original CRM book** (customers, interactions, promises, work_items VIEW, TEXT+CHECK, prefixed ids). It is **not** the current schema map.

**Present in SQL, absent or underspecified in the ERD / domain map:** `call_attempts`, `call_outcomes`, `agent_obligations`, `voice_sessions`, `campaign_runs`/`campaign_targets`/`call_cadence_state`/`number_pools`, `policy_rule_sets`/`policy_rules`, `contact_delivery_events`, `mandates`, `treatment_*`, `authority_decisions`, `offer_decisions`, `bot_turn_jobs`, `whatsapp_outbound_jobs`, `bot_tool_calls`, `idempotency_keys`, `skills`, eval factory, MCP, work-runtime, `platform_switches`, `customer_memory`, `tts_voice_catalog`.

**Wrong in the doc:** `handler_kind` includes `handoff`; Channel catalog omits `field` (contact_events) and API `"call"` vs SQL `voice`.

**Still right and load-bearing:** one entity per CRM concept; agents are ids not display names; interaction for connected sessions; `work_items` is a view; secrets as refs; tenants from day one; deferred RLS/encryption called out as a **release gate**.

---

## 13. Findings (priority)

### P0 — integrity now, at any volume

1. **`UNKNOWN-CALLER` is a global PK.** Second tenant in one database reuses the first tenant’s customer. Add a per-tenant sentinel (`UNKNOWN-CALLER` + tenant in the unique key, or `{tenant}:unknown`) before multi-tenant production. (`voice/persist.py:28-54`.)
2. **RLS off, child tables without `tenant_id`, no CHECK that child.tenant = parent.tenant.** Application predicates are tested (`test_cross_tenant_reads.py`) and have already been found missing once. Remaining list holes: `list_violations`, `list_conversations`, staff/teams, phone lookup. The last line of defence is still a GUC nobody enables. (`DATA_MODEL.md:302`, `rls.py`, `main.py` hardening gate.)

### P1 — races and silent vocabulary holes

3. **No unique `(customer_id, channel)` on `conversations`.** Concurrent WhatsApp ingest can split a thread. The SELECT-latest writer assumes uniqueness.
4. **No unique `conversations.interaction_id`.** Doc implies 1:1.
5. **No one-active-promise partial unique** on `(account_id) WHERE status IN ('upcoming','due_today','partial')`. Product may want multiples; if not, the database will not save you.
6. **`accounts.status` (and several sibling status columns) unconstrained** while a partial index and the treatment sweep predicate `'active'`. Garbage in, seq scan / missed delinquents.
7. **`emi_installments` / `promise_installments` missing composite unique** on `(parent_id, installment_index)`.
8. **`accounts.outstanding` vs `ledger_entries`** — two balances. Pick a writer (ledger trigger, or stop updating outstanding ad hoc).
9. **`audit_log.tenant_id` nullable** + no append-only enforcement. Weak RLS hop; admin events can be unscoped.
10. **CI schema check blind to `op.execute` DDL.** Already bit `voice_sessions`. Prefer parity test as the gate, not the regex.

### P2 — model clarity

11. **Publish the two-spine story** in `DATA_MODEL.md`: `interactions` = connected session; `call_attempts` = dial. Stop calling interaction “every call.”
12. **API `call` vs SQL `voice`.** One vocabulary. Chat consent currently dropped.
13. **Customer 360 LATERAL first-account fold.** Either expose accounts as an array or mark `accountId` as “primary” with an explicit rule.
14. **`a2a_tasks` vs `work_runtime_jobs` status hyphen/underscore.**
15. **`followups.updated_at` trigger omitted** from `13_triggers.sql`.
16. **`supervisor_actions` CASCADE on supervisor delete** destroys barge/whisper evidence. SET NULL is the usual audit choice.
17. **`qa_scorecards.status` default `'unscored'` with no CHECK.**
18. **`PromiseResponse` omits `due_today`** while the table and the Promises list type allow it.
19. **Docker `alembic upgrade head` on an empty volume fails** (0001 is no-op). Document sql/ then stamp as the only empty-DB path.
20. **Inbox `_thread_context` and webhook `_endpoint_contract`** re-hydrate children in Python; missing canonical batch reads, not missing tables.

---

## 14. Target shape (from patterns already in this tree)

Do not introduce an ORM. Do not merge `call_attempts` into `interactions`. Do not materialize `work_items`.

Copy what already works:

1. **Partial unique for every “one live row”** the code already races on (conversation per customer+channel, optionally one active PTP).
2. **Ledger as money SoT** with `accounts.outstanding` maintained by one trigger or one function, the way `used_this_week` is already a cache of `contact_events`.
3. **Keep handler XOR CHECKs** as the template for any new polymorphic actor column. Do not add a fourth style.
4. **Keep dual schema** but treat `test_schema_parity.py` as required CI (it already is when the scratch DB exists) and stop adding `op.execute(CREATE TABLE)` without a sql/ mirror — the voice_sessions incident is the playbook.
5. **RLS enable** as the actual release gate, after `provision-role` so the app is not a bypass role.
6. **Refresh `DATA_MODEL.md`** as a map: original CRM book + outbound spine + policy-as-data + engine logs. Leave column-level detail in `sql/`.

---

## 15. What this audit will not recommend deleting

| Object | Why it looks unused / redundant | Why it stays until a migration argues otherwise |
|---|---|---|
| `tts_voices` | FK dropped in `0048` | Studio alias table; writers and UI may still list it. |
| `channel_consents.used_this_week` | Duplicate of contact_events | Documented cache; refreshed on admit. |
| `customers.dnd` | Duplicate of consent | Party-level flag; Gate reads channel+purpose. |
| `interactions.disposition` | Duplicate of call_outcomes | Pre-outbound CRM and QA still read it. |
| `customer_memory` jsonb | Duplicate of promises | Cross-call LLM memory; different grain. |
| `prompt_versions.tuning` | Once missing from sql/ | Prompt Studio writes it; `0061` era lesson. |
| `activity_events` | “Could be per-entity tables” | Consolidation is the design; polymorphic on purpose. |
| `work_runtime_jobs` | Duplicate of followups | Clerk/self-service durable workflow, not agent queue. |

---

## Methodology notes

- Dual-path schema, no ORM, GUC tenancy, and `work_items` VIEW confirmed from files cited above.
- Relationship graph and delete semantics corroborated against `sql/90_deferred_fks.sql` and writers in `db.py` / `voice/persist.py`.
- Integrity catalog corroborated against partial unique indexes in `sql/02`, `03`, `05`, `09`, `12`, `21` and tests `test_idempotency.py`, `test_cross_tenant_reads.py`, `test_schema_parity.py`, `test_migrations.py`.
- Query amplification and open-transaction-across-HTTP are owned by reports 13 and 15; this file only records the **model** implication.
- No packages installed. No live `information_schema` dump this session.
