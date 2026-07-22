# Build Guide — turning DATA_MODEL.md into SQL + seed data

High-level steps to author the schema and ingest sample data, following [`DATA_MODEL.md`](DATA_MODEL.md). Postgres is already running (`collections_db`, pgvector enabled).

---

## 0. Connection

```
docker exec -it collections_db psql -U collections -d collections     # interactive
docker exec -i  collections_db psql -U collections -d collections < file.sql   # run a file
```
App DSN: `postgresql+psycopg://collections:collections@localhost:5432/collections`

---

## 1. File layout

Split DDL into ordered files by dependency layer (numeric prefix = apply order). Don't put 100 tables in one file — you'll fight ordering and lose your place.

```
backend/sql/
  00_extensions.sql        -- CREATE EXTENSION vector;
  01_identity.sql          -- tenants, teams, users, bots, agent_presence, roles, permissions, role_permissions, user_roles
  02_customer_account.sql  -- customers, customer_notes, products, product_eligibility_rules, accounts, ledger_entries, emi_installments
  03_consent.sql
  04_interactions.sql      -- interactions + all interaction_* + conversations, messages, canned_responses, ai_response_suggestions, live_alerts, supervisor_actions, identity_verifications
  05_collections.sql       -- payment_plans, promises, promise_*, disputes, dispute_evidence, document_*, callbacks, callback_reminders, followups
  06_sales.sql             -- leads, lead_eligibility
  07_compliance_qa.sql     -- compliance_rules, violations, qa_*
  08_redaction.sql
  09_bot_config.sql        -- kb_*, faq_pairs, prompt_versions, tts_voices, persona_presets, bot_deployments, routing_*, sandbox_*, retrieval_logs
  10_admin.sql             -- providers*, webhooks*, event_types, billing*, invoices*, budgets*
  11_analytics.sql
  12_crosscutting.sql      -- activity_events, audit_log
  90_deferred_fks.sql      -- ALTER TABLE ... ADD CONSTRAINT for circular/forward FKs (see §4)
  95_views.sql             -- work_items view (must be AFTER all base tables exist)
  seed/                    -- one file per layer, SAME order (or a Python seeder — see §6)
```

Apply order is: `00 → 12`, then `90_deferred_fks`, then `95_views`, then `seed/*`.

---

## 2. DDL conventions (how a DATA_MODEL bullet becomes a column)

| Model says | Write in SQL |
|---|---|
| id like `CL-######`, slug | `id TEXT PRIMARY KEY` (human-readable keys stay TEXT) |
| an enum (from the Enum Catalog) | `col TEXT NOT NULL CHECK (col IN ('a','b','c'))` — **not** native `ENUM` |
| money / amount | `numeric(14,2)` |
| a timestamp | `timestamptz` |
| JSON blob (persona/voice/guardrails, conditions, event payloads) | `jsonb` |
| embeddings (later, RAG) | `vector(1536)` + HNSW index |
| `X → Entity` reference | `x_id TEXT NOT NULL REFERENCES entity(id)` (add `ON DELETE` per §5) |
| optional reference `X?` | same but nullable, no `NOT NULL` |
| every mutable table | add `created_at timestamptz NOT NULL DEFAULT now()` and `updated_at timestamptz NOT NULL DEFAULT now()` |
| handler/owner/actor that can be human **or** bot | the triplet: `x_kind TEXT CHECK (x_kind IN ('human','bot')) , x_user_id TEXT REFERENCES users(id), x_bot_id TEXT REFERENCES bots(id)` + `CHECK` (§3) |

Add indexes on every FK you'll filter/join by (`CREATE INDEX ON interactions(customer_id);`) and on hot query columns (status, scheduled_at, tenant_id).

## 3. Polymorphic columns — the one thing FKs can't protect

`work_items` (view), `activity_events`, `followups` (promise_id? / lead_id?), `ai_response_suggestions` (conversation_id? / interaction_id? / transcript_turn_id?), and the handler/owner triplets are polymorphic — SQL can't FK them. Enforce integrity with a `CHECK` that exactly one target is set:

```sql
-- followups: exactly one parent
CHECK ( (promise_id IS NOT NULL)::int + (lead_id IS NOT NULL)::int = 1 )

-- handler triplet: kind matches which id is filled
CHECK ( (handler_kind='human' AND handler_user_id IS NOT NULL AND handler_bot_id IS NULL)
     OR (handler_kind='bot'   AND handler_bot_id  IS NOT NULL AND handler_user_id IS NULL) )
```
For `activity_events(entity_type, entity_id)` you can't FK the id — validate with a post-seed query (§7).

## 4. Creation order & circular FKs

Postgres (unlike SQLite) requires a referenced table to **exist at CREATE time**. Two consequences:

1. **Follow the layer order** in §1 — parents before children. Within a file, order tables the same way.
2. **Circular / forward references** — don't inline the FK; create the column, then add the constraint in `90_deferred_fks.sql`:
   - `teams.supervisor_user_id` ↔ `users.team_id` (mutual)
   - `interactions.deployment_id → bot_deployments` (bot_config is layer 09, after interactions in 04)
   - `followups.lead_id → leads` (leads is layer 06, after collections in 05)
   ```sql
   -- 90_deferred_fks.sql
   ALTER TABLE teams ADD CONSTRAINT fk_teams_supervisor
     FOREIGN KEY (supervisor_user_id) REFERENCES users(id);
   ALTER TABLE interactions ADD CONSTRAINT fk_interactions_deployment
     FOREIGN KEY (deployment_id) REFERENCES bot_deployments(id);
   ```

## 5. ON DELETE policy

- Child rows that belong to a parent (`interaction_transcript`, `messages`, `dispute_evidence`, `promise_installments`, `qa_scorecard_entries`, `pii_findings`, …): `ON DELETE CASCADE`.
- Cross-entity references you want to keep even if the source goes (`interaction_id` on a promise/lead, `assignee_user_id`): `ON DELETE SET NULL` (make the column nullable).
- Reference/catalog tables (`products`, `compliance_rules`, `document_templates`, `event_types`): `ON DELETE RESTRICT` (default) — never silently delete a referenced rule/template.

## 6. Seeding — coherence is the whole game

Insert in the **same dependency order** as the DDL so every FK resolves. Two options:

- **SQL seed files** (`seed/01_identity.sql` …) — fine for reference/config tables and small sets.
- **Python seeder** (recommended for the cross-linked core) — build the graph in memory so ids line up, then insert. This is where you get *one* customer set (~12) that appears consistently across interactions, promises, disputes, callbacks, leads, consent — instead of the frontend's divergent per-screen sets.

Coherence rules:
1. Pick the **~12 canonical customers** once (reuse the real slugs: `vikram-rao`, `anita-desai`, …). Everything references these ids.
2. Give each customer 1–2 `accounts`; hang `emi_installments` + `ledger_entries` off the account.
3. Create ~40 `interactions` (mix of bot/human/handoff, voice/chat) → then derive promises, disputes, documents, leads, violations, QA scorecards **from those interaction ids** so `interaction_id` links are real.
4. `consent_records` 1:1 with each customer (+ `channel_consents`).
5. Config/admin/analytics tables (`providers`, `event_types`, `compliance_rules`, `kb_documents`, `billing_services`, `intent_aggregates`…) are mostly standalone reference data — seed representative rows, no cross-links needed.
6. Wrap each seed file/run in a transaction (`BEGIN; … COMMIT;`) so a coherence bug rolls back cleanly.

Tip: you can lift real values from the existing exports in `backend/seed/*.json` (customers, calls, leads) as a starting point.

## 7. Apply & verify

```bash
# apply all, stop on first error
cd backend
for f in sql/0*.sql sql/1*.sql sql/90_*.sql sql/95_*.sql; do
  echo ">> $f"; docker exec -i collections_db psql -U collections -d collections -v ON_ERROR_STOP=1 -f - < "$f" || break
done
```
Postgres enforces FKs **immediately**, so a bad reference fails the insert on the spot — that's your primary validation. After seeding, sanity-check:
```sql
-- row counts per table
SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY 1;

-- orphan check for a POLYMORPHIC column that has no FK (example: activity_events → interactions)
SELECT ae.* FROM activity_events ae
LEFT JOIN interactions i ON ae.entity_type='interaction' AND ae.entity_id=i.id
WHERE ae.entity_type='interaction' AND i.id IS NULL;   -- expect 0 rows

-- spot-check a join across the spine
SELECT c.name, count(i.*) calls, count(p.*) promises
FROM customers c
LEFT JOIN interactions i ON i.customer_id=c.id
LEFT JOIN promises p ON p.customer_id=c.id
GROUP BY 1 ORDER BY 2 DESC;
```

## 8. Order of attack (suggested)

1. `00`–`03` (identity → customer/account → consent) + seed → verify the customer/account core loads.
2. `04` interactions + seed ~40 interactions → this unblocks everything downstream.
3. `05`–`06` collections + sales, seeding **from** interaction ids.
4. `07`–`08` compliance/QA + redaction (also hang off interactions).
5. `09`–`12` bot config, admin, analytics, cross-cutting (mostly standalone).
6. `95_views.sql` (`work_items`) last, then the verification queries in §7.

Build and validate layer-by-layer — don't write all 100 tables then discover an ordering problem at the end.
