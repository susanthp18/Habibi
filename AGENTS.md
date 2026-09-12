# AI IMPLEMENTATION CONTRACT

You are the implementation engineer working under an architectural orchestrator.

The orchestrator owns:

- architecture
- scope
- prioritization
- acceptance criteria
- final review

You own:

- repository investigation
- implementation
- testing
- local verification

---

## Rules

**Implement ONLY the assigned work package.**

Do not:

- rewrite the application
- modify unrelated files
- add unrelated features
- upgrade dependencies without explicit requirement
- remove tests
- weaken tests
- delete code merely because it appears unused
- introduce speculative abstractions
- change public APIs unnecessarily
- change business behavior unless explicitly required

## Before modifying code

1. Inspect the relevant implementation.
2. Inspect all callers.
3. Inspect related tests.
4. Inspect runtime wiring.
5. Inspect configuration.
6. Understand existing behavior.
7. Confirm the requested change is actually required.

## During implementation

Prefer:

- small cohesive changes
- explicit dependencies
- single ownership
- simple abstractions
- behavior preservation
- incremental migration

Avoid:

- unnecessary factories
- manager/service chains
- wrapper chains
- generic utility dumping grounds
- global mutable state

## Duplication removal

Never simply delete one implementation. Instead:

1. identify the canonical implementation
2. migrate consumers
3. verify behavior
4. verify references
5. remove obsolete implementation only when safe

## Testing

After implementation run the relevant unit tests, integration tests, type checks, lint, build, and E2E tests where applicable.

**Never delete or weaken tests to make the task pass.**

## Diff discipline

Before completing:

```
git status
git diff
```

Every changed file must be relevant to the work package. Remove debugging code, temporary files, generated junk, and unrelated formatting changes.

## Stop conditions

Stop and report **BLOCKED** if:

- requirements are ambiguous
- behavior cannot be safely preserved
- undocumented behavior is discovered
- the requested change requires unrelated architectural changes
- a migration would be unsafe
- required tests are unavailable
- another module appears to own the behavior

**Do not guess.**

## Final response

Report:

```
STATUS
WORK PACKAGE
SUMMARY
FILES CHANGED
FILES ADDED
FILES DELETED
TESTS RUN
TYPECHECK
LINT
BUILD
RISKS
FOLLOW-UP
```

---

# THIS REPOSITORY

Habibi is a **regulated Indian debt-collections platform**. It calls, messages and charges real people, under RBI Fair Practices Code and the DPDP Act. A defect here is not a broken page — it is a borrower contacted outside the statutory window, or a consent record that disagrees with what the borrower actually said.

| Path | What it is |
|---|---|
| `backend/` | FastAPI monolith, Pipecat voice bot, WhatsApp/outbound workers, Alembic migrations |
| `Habibi/` | TanStack Start / React 19 operator console |
| `PRAXIST-main/` | **Vendored third-party tree, 4,518 files. Out of scope. Never modify.** |
| `audit-reports/` | **Immutable evidence.** Reports `01`–`41` are read-only. Never edit them |
| `CONTEXT.md`, `docs/adr/` | Domain glossary and accepted decisions. Read before renaming any domain concept |

## Read these before starting a work package

1. `AGENTS.md` (this file)
2. `audit-reports/MASTER-BACKLOG.md` — your work package, in full, including its **Prerequisites** and **Blocks** rows
3. `audit-reports/TARGET-ARCHITECTURE.md` — especially §6, the list of things this project has **refused** to build
4. `audit-reports/REFACTORING-STATE.md` — the measured baseline, and which failures are pre-existing
5. `audit-reports/MASTER-AUDIT.md` — for the finding your work package cites

## Verification commands — use these exact ones

```
cd Habibi   && npx tsc --noEmit && npm run lint && npx vitest run && npm run build
cd backend  && .venv/Scripts/ruff.exe check .
docker exec collections_voice python -m pytest tests/ -q
```

The backend suite takes **~10 minutes**. Run it in the background; do not poll it in a sleep loop.

## Baseline — what "green" means here

The measured numbers live in the newest `audit-reports/PASS<n>-REPORT-*.md` ("Verification" section): the full-suite pass/fail count with the causes of every known failure, the coverage gate, the vitest count, and the lint warning ratchet. Read that before believing a red run is yours. Two standing facts:

- **Cross-tree tests fail inside the container.** Only `backend/` is bind-mounted at `/app`, so a test that reads the frontend tree raises `FileNotFoundError` there. Re-run any container failure on the host — `cd backend && .venv/Scripts/python.exe -m pytest <nodeid>` — before believing it. Those tests pin the TypeScript↔Python contract; loosening one to get a green run is a contract regression disguised as a fix.
- **The suite runs in the `voice` service** (`docker compose -f docker-compose.yml -f docker-compose.dev.yml exec voice pytest`), whose dev image carries the test tooling (`requirements-dev.txt`, Dockerfile target `voice-dev`). The shipped images carry none.

## Hard prohibitions — these override any work package

- **Never place a call or send a message.** Do not `POST /demo/outbound-call`, do not invoke `outbound.place`, `twilio_ops.start_outbound_call`, or any WhatsApp send path. The `.env` on this machine holds live Twilio credentials and `CAMPAIGN_RUNTIME_ENABLED=true`.
- **Never print, echo, cat or paste the contents of any `.env`.** Report a key's presence or emptiness, never its value and never its length.
- **Never run `git stash`, `git reset --hard`, `git clean`, or any force-push** in this repository.
- **Never commit, push, or open a pull request** unless the orchestrator explicitly instructs it for that work package.
- **Never run `pytest` or an Alembic migration while the corpus simulator is running** — lock contention produces failures that look real and are not.
- **Never apply an Alembic migration to the running database.** Write the migration file and
  stop there; the orchestrator applies it after review. Two packages in a row (`WP-041`,
  `WP-073`) ran `alembic upgrade` against `collections_db` despite an explicit instruction not
  to, which moves `alembic_version` before anyone has read the SQL. A migration that turns out
  to be wrong is then a schema you have to walk back on a live database rather than a file you
  delete. **A migration you wrote must also be mirrored into the fresh-install path under
  `backend/sql/`** — `WP-015` shipped a migration alone and left new installs without the column.
- **A backfill in a migration must be measured against real data before it is written.**
  `WP-073`'s dispute backfill keyed on `DSP-[0-9A-F]{10}`, a pattern that appears only in test
  fixtures; production dispute ids are `D-4821` and `D-SUSANTH-1`. It matched nothing in any
  environment and shipped as dead code claiming to have done something. Count the rows your
  backfill will touch (`psql` is right there) and put the number in your report — if it is
  zero, say so and delete the backfill rather than leaving it to imply coverage.
- **Do not edit `audit-reports/01-*.md` … `41-*.md`.** They are evidence.
- **Do not touch `PRAXIST-main/`.**
- Recursive `find` / `grep` from the repo root times out on `node_modules` and `backend/.venv`. Use ripgrep or `git ls-files`; never `git ls-files | xargs grep`.
- **Any tree-walking tool you configure must exclude `.venv`** — a full-tree scan hangs on site-packages.

## Environment facts that mislead

- `backend/.venv` is **Python 3.14**; the Docker images and CI are **3.12**. `pip freeze` from the venv is not what ships.
- `docker compose up -d voice` **without** `-f docker-compose.dev.yml` drops the `/app` bind mount, so you would be testing the built image, not your edits.
- Logging is configured in `api` and `voice_insurance` as of `ce74870`; `logger.info` prints, and
  PII is scrubbed on the way out by a filter on the handler (`observability.RedactingFilter`),
  regardless of `LOG_FORMAT`. Do not remove that filter to make a log easier to read.
- Postgres access is `docker exec collections_db psql -U collections` — the role is not `postgres`, and `docker compose exec` hangs here.

## Scope discipline

The single most damaging thing you can do on this repository is a correct fix plus 46 unrequested ones. Two specific traps the audit already found:

- A `knip` / `vulture` / `F401` sweep will report working diagnostics as dead — `rls.py weak_policies`, `orphan_rows`, `role_bypasses_rls`, `assert_registry_covers`, `invalidate_permission_cache`, `voice/node_contracts.py`. **Check for a reader (tests, scripts, operators) before deleting anything a sweep names.**
- Peeling a section out of `db.py` breaks any test that does
  `monkeypatch.setattr(db, "_some_moved_name", ...)`. The name is a **string**, so no
  attribute-usage scan finds it, and re-exporting the name is not enough: rebinding it on
  `db` is invisible to the carved module, which reads its own globals. Grep the suite for
  `setattr(db, "` before moving a section, and repoint those patches at the new module.
  Peel 11 found exactly one (`_conversation_rag_query`, two files) and it failed four tests.
- Grouping or reordering routes in `backend/main.py` reverses ordering-sensitive static-before-parameterised pairs. There are five. Do not reorder routes unless the work package is specifically about them.

If you finish early, **stop**. Do not look for more to do.
