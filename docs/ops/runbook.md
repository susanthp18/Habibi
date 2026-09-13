# Runbook

One page. What to look at when something pages, and the command that answers
each question. Everything runs from `backend/`; use `docker exec`, not
`docker compose exec` (the latter hangs on the dev machine).

## Is it up?

| Question | Command |
|---|---|
| Is the API alive? | `curl -s http://127.0.0.1:8000/health` |
| Can it serve? (DB ping, pool headroom, MinIO) | `curl -s http://127.0.0.1:8000/ready` — 503 with the failing part in `detail` |
| What is every process reporting? | `curl -s -H "X-API-Key: <key with perm-observability-read>" http://127.0.0.1:8000/metrics`; the worker, bot_worker and voice processes expose the same on `:9100` (`METRICS_PORT`) |
| Dev Prometheus | `http://localhost:9090` (Status → Targets; Alerts shows `ops/alerts.yml`) |

## The four alerts (`ops/alerts.yml`)

### Dead jobs
`job_queue_depth{status="dead"} > 0` — a job exhausted its retries.

The queue label names the table (`observability._QUEUES` lists the twelve).
The three job tables share a shape:

```bash
docker exec collections_db psql -U collections -c "SELECT 'bot_turn_jobs' AS q, id, status, error, updated_at FROM bot_turn_jobs WHERE status='dead' UNION ALL SELECT 'work_runtime_jobs', id, status, error, updated_at FROM work_runtime_jobs WHERE status='dead' UNION ALL SELECT 'kb_index_jobs', id, status, error, updated_at FROM kb_index_jobs WHERE status='dead' ORDER BY updated_at DESC LIMIT 20;"
```

Read `error`, fix the cause, then requeue by setting `status='queued', attempts=0` on the rows you understand. A dead job is never deleted: it is the record that the work was not done.

### Stuck queue
`job_queue_oldest_seconds > 900` — the oldest pending job has waited fifteen minutes. Either the worker for that queue is down (`docker ps`, `docker logs collections_worker --tail 100`) or one job is holding the loop. `docker top collections_worker` shows whether it is alive; `bot_worker` runs the stages named in `agent_core/worker_roles.py`.

### Open breaker
`circuit_breaker_state{state="open"} == 1` for five minutes — a dependency (Azure OpenAI, Speech, MinIO, a connector) has failed enough times that calls are being refused without being tried. The breaker name says which. Check the dependency itself first; the breaker closes on its own after `resetTimeoutS` if the next call succeeds. Nothing here needs a restart.

### Pool exhausted
`db_pool_available == 0` — every SQLAlchemy connection is checked out. `/ready` is already answering 503, so the load balancer is shedding. Look for a long transaction:

```bash
docker exec collections_db psql -U collections -c "SELECT pid, now()-xact_start AS age, state, left(query,80) FROM pg_stat_activity WHERE datname='collections' AND xact_start IS NOT NULL ORDER BY age DESC LIMIT 10;"
```

`DB_POOL_SIZE` / `DB_MAX_OVERFLOW` are the knobs, but a pool that empties is almost always one query, not a small pool.

## Row-level security

```bash
docker exec collections_voice python scripts/rls.py status
```

(From the host the DSN in `.env` points at the compose network name, so run it inside a container.)

Every tenant-scoped table must read `enforced`. A table that is not is a cross-tenant read waiting to happen; `enable` refuses while the app role could still bypass.

## A call's evidence

```bash
docker exec collections_voice python -c "from voice.call_export import build_bundle; import json; print(json.dumps(build_bundle('CL-...'), default=str)[:2000])"
```

`build_bundle` is the complaint pack: the redacted transcript, the tool calls, the consent state and the money rows for one interaction. Everything in it is already masked at rest; nothing in it is re-derived.

## Rolling back

`docs/ops/rollback.md` — images by SHA, the two commands, and why the database does not move with them.

## Secrets

`docs/ops/vault-inventory.md` — what lives in `vault_refs`, how it is sealed, and `scripts/reseal_vault.py` after a `VAULT_MASTER_KEY` change.

## MCP

`docs/ops/mcp.md` — the stdio and HTTP servers, keys, and `GET /mcp/status`.
