# W6 decision-substrate evidence

Recorded 2026-09-08.

## Scope

W6 is implemented as a PostgreSQL 16-compatible substrate. No migration was
applied to the running `collections` database and no PostgreSQL 18 cutover was
executed. No carrier, messaging, or payment-rail operation was invoked.

The Alembic chain is `20260906_0110` → `20260906_0111` →
`20260906_0112` → `20260908_0113`. The fresh-install mirror is
`sql/25_decision_substrate.sql`.

## Measured population before shard work

A read-only query against the running PostgreSQL 16 database, at Alembic
`20260906_0112`, measured:

- 27 account rows;
- 302 treatment-decision rows;
- 3,314 usage-event rows.

Migration `0113` leaves `accounts.shard_key` and `shard_version` nullable and
does not backfill them. `scripts/backfill_account_shards.py` is dry-run by
default and writes only with `--apply`; its measured output must be reviewed
before execution. No backfill was executed by W6.

## Duration gates

The real 14-day exit gate is **not yet measured**. `scripts/soak_w6.py` exits 2
until an operator supplies both the observed duration and declared book scale.
It passes only when all fourteen real days have:

- zero recorded PIT mismatches and green PIT runs;
- every shard complete;
- at least 99.5% of eligible accounts decided;
- completion by 08:00 IST;
- eligible population at or above the declared book scale.

No synthetic or shortened run is reported as W6 acceptance evidence.

## Verification recorded 2026-09-08

- Alembic has a single head: `20260908_0113`.
- `ruff check .` passed.
- Host pytest: `tests/test_honest_engines_w5.py`,
  `tests/test_honest_engines_exit_criteria.py`,
  `tests/test_honest_engines_w6.py`, and `tests/test_migrations.py`
  → 42 passed, 1 skipped (Alembic roundtrip, no scratch `TEST_DATABASE_URL`).
- `scripts/soak_w6.py` exits 2 with `not yet measured`.
- Scratch schema parity (`scripts/verify_w6_schema.py`) is **not measured**;
  `W6_SCHEMA_SCRATCH_DATABASE_URL` was unset. The script refuses any database
  whose name is not scratch/test/ci.
- Habibi `tsc --noEmit` succeeded. `npm run lint` and `vitest` failures are
  outside this package (login/SSO/sandbox prettier and a timed-out import
  scan). W6 did not change the frontend tree.
- No `alembic upgrade` was run against `collections`.

## Inputs still owned by the bank or DBA

- Signed dictionaries and production adapters for C1–C10 and O1–O6.
- The legal owner of mandate presentment authority.
- Reporting-standby endpoint, measured replay-lag budget, and the dedicated
  standby settings.
- Declared pilot and full-book scale.
- PostgreSQL 18 target sizing, copy rehearsal, WAL-slot headroom, maintenance
  window, reverse-replication rehearsal, and named rollback authority.
- Approval and measured output for the account-shard backfill.
