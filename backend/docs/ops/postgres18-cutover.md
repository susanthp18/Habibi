# PostgreSQL 18 decision-substrate cutover

This is a runbook, not an authorization to migrate. W6 ships and remains
supported on PostgreSQL 16 through `EXCLUDE USING gist`. Do not run any command
below until the change record names the DBA, incident commander, rollback
owner, maintenance window, tested backups, and application build SHA.

## Preconditions

- Source is PostgreSQL 16 and is healthy, backed up, and restore-tested.
- Target is PostgreSQL 18 with the same extensions, locale, encoding, timezone,
  parameter group, encryption, network policy, and storage class.
- `btree_gist`, `vector`, and every extension reported by `pg_extension` exist
  at compatible versions on the target.
- Alembic is at one reviewed head on both sides. Recreate schema from the
  reviewed DDL before copying data; logical replication does not replicate DDL,
  roles, sequences, large objects, or extension installation.
- No unlogged table, table without a usable replica identity, publication gap,
  or unsupported data type remains. Record the inventory in the change ticket.
- The application remains on the PostgreSQL 16-compatible GiST constraints.
  Converting them to PostgreSQL 18 `WITHOUT OVERLAPS` is a later migration after
  the cutover proves stable.

## Capacity and WAL-slot guardrails

Measure the source database, largest tables, write rate, WAL generated per hour,
and a full-copy duration in a rehearsal of production scale. Provision target
storage for the copied database, indexes, temporary build space, and at least
two days of peak WAL.

Before creating a logical slot, set a ticketed WAL budget:

- warning at 50% of reserved slot headroom;
- stop new copy work at 70%;
- at 80%, or when projected exhaustion is less than twice the measured time to
  recreate the copy, stop the subscriber, drop the slot, restore headroom, and
  restart from a new copy;
- never let a stalled slot consume the source's final 20% free storage.

Dropping the slot abandons that synchronization attempt. It is safer than
filling the source volume. The incident commander decides; automation may stop
and alert but must not drop a slot.

## Copy-first synchronization

1. Create audited, named migration roles. The publisher owns no application
   tables and has only replication plus the documented `SELECT` grants. The
   subscriber apply role owns target tables but is not a superuser. Neither
   application nor worker roles receive `BYPASSRLS`.
2. Revoke broad defaults, set `NOBYPASSRLS` explicitly on application, worker,
   reporting, and evaluation roles, and capture `pg_roles` plus table grants.
3. Create the target schema and validate all constraints that must exist before
   the copy. Defer only indexes/constraints whose omission is explicitly
   approved for copy speed, and recreate them before go/no-go.
4. Create a publication covering the reviewed table inventory and a
   subscription with initial data copy enabled. Record copy start time, source
   LSN, slot name, publication, subscription, and target.
5. Monitor `pg_stat_subscription`, table synchronization state, source slot
   retained WAL, target replay/apply errors, disk, locks, and long transactions.
6. After every table reports ready, recreate deferred indexes and constraints
   with the online-DDL procedure. Run `ANALYZE` on the target.
7. Compare per-table row counts, tenant counts, control sums in integer paise,
   manifest/reconciliation totals, temporal overlap checks, and a deterministic
   sample of row hashes. Any unexplained difference is a no-go.

## Sequences and non-table state

Logical replication does not advance sequences. During the final write pause,
inventory every owned sequence and set the target to at least the source's
`last_value`, preserving `is_called`. Repeat after replication reaches the
barrier LSN and before any target writer starts. Recreate and verify:

- roles, memberships, ownership, grants, default privileges, and RLS policies;
- extensions, functions, triggers, views, materialized views, scheduled jobs,
  publications, and settings;
- large objects or external object references;
- monitoring, backups, WAL archiving, connection limits, and statement
  timeouts.

The change ticket stores redacted command output. It must not store passwords,
connection strings, or `.env` contents.

## Reverse replication before cutover

Rollback is credible only if target writes can return to PostgreSQL 16.
Before the application cutover:

1. Prove every post-cutover table and value remains writable by PostgreSQL 16.
   Do not introduce a PostgreSQL 18-only data shape during the rollback window.
2. Prepare the reverse publication on PostgreSQL 18 and the PostgreSQL 16
   subscriber definition, but keep reverse apply disabled while forward
   replication owns the stream.
3. Rehearse the direction change on a disposable pair, including origin
   filtering so rows do not loop.
4. Record the exact forward-subscription disable, final-LSN barrier,
   reverse-subscription enable, lag check, and fencing sequence.
5. Confirm slot headroom for both directions and name who may drop either slot.

If reverse replication cannot be configured and rehearsed before cutover, the
go/no-go result is no-go.

## Cutover

1. Announce the write freeze. Stop API and worker writers; do not merely remove
   them from the load balancer. Confirm no borrower-facing sender or rail
   adapter is running.
2. Capture source health, backup identity, current WAL flush LSN, open
   transactions, replication lag, and application build SHA.
3. Wait until the target has applied the barrier LSN. Re-run row/control-sum
   reconciliation and temporal-overlap checks.
4. Advance target sequences, then run read-only smoke tests using the real
   application roles. Confirm RLS, `NOBYPASSRLS`, evaluation-schema isolation,
   and statement timeouts.
5. Change the secret-managed database endpoint. Do not edit or print `.env`.
6. Start one API instance with outbound/campaign/rail execution disabled.
   Verify health, authorization, tenant isolation, decision preview, and
   read-only operator paths.
7. Start workers in stages, keeping all live action switches disabled. Verify
   queue claims, snapshot jobs, PIT checks, and usage attribution.
8. Only the incident commander may restore previously approved live switches
   after database, application, and compliance checks are green.
9. Keep PostgreSQL 16 intact and fenced for the full rollback window.

## Go/no-go

Go requires all of the following:

- target at the barrier LSN with zero unexplained reconciliation differences;
- all deferred DDL recreated and valid;
- sequences advanced;
- application/worker roles are `NOBYPASSRLS` and cannot read F9 protected data;
- p95/p99 query latency, locks, CPU, memory, disk, WAL, and error rates are
  within the rehearsal envelope;
- PIT sample and two-tenant colliding-loan fixture are green;
- backups and monitoring are active on PostgreSQL 18;
- reverse replication is configured, rehearsed, and ready before the first
  target write.

Any missing evidence, slot-headroom breach, unknown lag, schema drift, privilege
drift, or unexplained control-total difference is a no-go.

## T+24-hour rollback

The rollback window lasts 24 hours after the first PostgreSQL 18 application
write. During it, no PostgreSQL 18-only schema feature may be introduced.

1. Disable all borrower-facing and rail execution, then fence PostgreSQL 18
   writers.
2. Let reverse replication reach a recorded barrier LSN on PostgreSQL 16.
3. Reconcile row counts, integer-paise control sums, temporal constraints,
   decisions, outbox rows, and usage events.
4. Advance PostgreSQL 16 sequences from PostgreSQL 18.
5. Point one disabled-action API instance at PostgreSQL 16 and run the same
   role/RLS/read-only smoke checks.
6. Redirect the endpoint, then restore processes in stages. Live actions remain
   disabled until the incident commander approves.
7. Preserve PostgreSQL 18, both LSN barriers, logs, and reconciliation evidence
   for investigation. Do not drop slots until the DBA signs the final state.

After T+24, rollback becomes restore-and-reconcile rather than a direction flip;
the change record must explicitly close the reverse-replication window.

## PostgreSQL 16 fallback

If the cutover is deferred or refused, continue operating `fct_*` on
PostgreSQL 16. `btree_gist` plus tenant-leading partial `EXCLUDE USING gist`
constraints provides the required non-overlap semantics. Keep the PG18-only
conversion out of application code, continue rehearsing copy/reverse-copy, and
schedule a new cutover only after the failed gate has evidence.
