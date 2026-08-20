# Collections Agent — CRM Backend

FastAPI + PostgreSQL 16 + pgvector. Serves read/query endpoints and Phase 3A mutation endpoints from the normalized enterprise data layer.

## Setup (first time)
```
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

## Database

Create and fill `backend/.env` **first** — every `docker compose up`, including
the database and MinIO containers, reads its credentials from it. The API,
workers and voice runner read theirs at import time, so a missing file leaves
every container running against defaults:
```
cd backend
cp .env.example .env      # then edit: DATABASE_URL, AZURE_OPENAI_*, TWILIO_*, WHATSAPP_*
```

Database and object store only:
```
docker compose up -d db minio
```

Full stack (API + KB worker + bot worker + voice), with connection budgets baked into compose:
```
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api python scripts/seed_demo.py   # optional; refuses APP_ENV=production
```

Probes: `http://127.0.0.1:8000/health` · `http://127.0.0.1:8000/ready`  
Voice WebRTC UI: `http://127.0.0.1:7860`

Data-plane only (legacy local Python processes via `scripts/dev-up.ps1`):
```
docker compose up -d db minio
```

Apply schema in order (first-time empty DB, before or instead of Alembic baseline stamp):
```
Get-ChildItem sql/*.sql | Sort-Object Name | ForEach-Object {
  Get-Content -Raw $_.FullName | docker exec -i collections_db psql -U collections -d collections -v ON_ERROR_STOP=1 -f -
}
```

MinIO: set `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` in `backend/.env` before `docker compose up` (production rejects `minioadmin` defaults).

Seed coherent sample data (host venv):
```
.venv/Scripts/python scripts/seed_demo.py
```

The current SQL-applied schema is stamped as Alembic baseline `20260721_0001`.
Phase 3A write support is migration `20260721_0002` (`idempotency_keys`).
Use Alembic for future schema changes:
```
.venv/Scripts/python -m alembic current
.venv/Scripts/python -m alembic revision -m "describe change"
.venv/Scripts/python -m alembic upgrade head
```

## Run

The API alone is not a working system. It **accepts** outbound work and queues
it; a worker is what actually sends it. Start both.

```
.venv/Scripts/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```
```
.venv/Scripts/python -m bot_worker
```

Interactive API docs: http://127.0.0.1:8000/docs

| Process | Required for | Symptom when missing |
|---|---|---|
| `uvicorn main:app` (:8000) | everything | nothing loads |
| `bot_worker` | WhatsApp sends (agent replies **and** bot turns), statutory SMS, clerk jobs | `POST /conversations/{id}/messages` returns **200** and the message never arrives — it sits in `whatsapp_outbound_jobs` at `queued` |
| `voice.bot` (:7860) | voice calls, Call sandbox | Start call fails to connect |
| `worker` | KB indexing | ingested documents never become searchable |

`docker compose up` starts all four. Running natively, they are four terminals.

To check whether anything is stuck:
```
docker exec collections_db psql -U collections -d collections -c "select status, count(*), now()-min(created_at) as oldest from whatsapp_outbound_jobs group by status"
```
A non-empty `queued` row with an `oldest` older than a few seconds means no
worker is draining it.

## Endpoints
| Method | Path | Notes |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/customers` | list (full records) |
| GET | `/customers/{id}` | full record, 404 if unknown |
| GET | `/dashboard?range&segment&team` | server-side filtered KPIs |
| GET | `/calls` | audit trail |
| GET | `/leads` | upsell pipeline |
| GET | `/handoff/active` | live-call snapshot |
| POST/PATCH | `/interactions`, `/interactions/{id}/wrap-up` | manual call logging and wrap-up |
| POST/PATCH | `/promises`, `/promises/{id}` | promise-to-pay capture/status |
| POST | `/payment-plans` | payment plan plus first promise |
| POST/PATCH | `/disputes`, `/disputes/{id}`, `/disputes/{id}/evidence` | dispute workflow |
| POST/PATCH | `/callbacks`, `/callbacks/{id}`, `/callbacks/{id}/reminders` | callback workflow |
| POST/PATCH | `/leads`, `/leads/{id}`, `/leads/{id}/followups`, `/followups/{id}` | upsell workflow |
| POST/PATCH | `/document-requests`, `/document-requests/{id}`, `/document-requests/{id}/delivery-attempts` | document fulfilment |
| POST/PATCH | `/customers/{id}/notes`, `/consent/{id}`, `/consent/{id}/opt-out` | notes and consent |
| POST/PATCH | `/violations/{id}`, `/scorecards`, `/scorecards/{id}` | compliance and QA |

## Files
- `main.py` — FastAPI app, routes, CORS
- `db.py` — PostgreSQL connection and read/query accessors
- `schemas.py` — explicit Pydantic API response contracts
- `sql/*.sql` — ordered Postgres DDL
- `seed_postgres.py` — coherent seed graph from `seed/*.json`
- `alembic/` — baseline migration and future schema migration home
