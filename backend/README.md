# Collections Agent — CRM Backend

FastAPI + PostgreSQL 16 + pgvector. Serves read/query endpoints and Phase 3A mutation endpoints from the normalized enterprise data layer.

## Setup (first time)
```
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

## Database
```
cd backend
docker compose up -d
```

Apply schema in order:
```
Get-ChildItem sql/*.sql | Sort-Object Name | ForEach-Object {
  docker exec -i collections_db psql -U collections -d collections -v ON_ERROR_STOP=1 -f - < $_.FullName
}
```

Seed coherent sample data:
```
.venv/Scripts/python seed_postgres.py
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
```
.venv/Scripts/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```
Interactive API docs: http://127.0.0.1:8000/docs

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
