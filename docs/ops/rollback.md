# Rollback

A named engineer can execute this at 3am without asking anyone. The two
commands that move the processes back are in §2. Everything around them
exists because **those two commands do not move the database.**

Images are tagged with the 40-character commit SHA that built them and
pushed to GHCR (`ghcr.io/<owner>/<repo>/collections-api:<sha>` and
`…/collections-voice:<sha>`). There is no `latest` tag. `git revert` is
not a rollback: it does not change what is running, and it does not
restore rows that a migration already rewrote.

The operator console (`Habibi/`) has no Dockerfile and no image. This
procedure covers the five application containers. The console is a
separate static build; CI now runs `npm run build`, but its hosting path
is still undefined — rolling it back is a hosting-side restore of the
previous build artefact, not an image swap.

Run every `docker` command from `backend/`. Use `docker exec`, not
`docker compose exec` (the latter hangs on this machine). Do not
`POST /demo/outbound-call` or otherwise place a call while diagnosing.

Substitute:

| Variable | Value |
|---|---|
| `IMAGE_PREFIX` | `ghcr.io/<owner>/<repo>/` — **trailing slash required** |
| `IMAGE_TAG` | the 40-character commit SHA |

On this repository that prefix is `ghcr.io/susanthp18/habibi/`.

---

## 0 · What is running right now

```bash
docker inspect -f '{{.Config.Image}}' collections_api
docker inspect -f '{{.Config.Image}}' collections_voice
```

Write both lines down **before** any upgrade. That string is the
`IMAGE_TAG` you will pass in §2. If the tag is `local`, there is no
published SHA to pull and this procedure cannot yet roll the images
back — only a rebuild from a known commit remains, which is the
situation WP-001 exists to end.

Login (once per host) if the images are not already on the machine:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin
```

Do not print the token. `GHCR_TOKEN` is a PAT or `GITHUB_TOKEN` with
`read:packages` (private packages) or an empty scope (public).

---

## 1 · Before every upgrade — dump the database

Do this **immediately before** `alembic upgrade head`. Do not dump into
the git working tree: a collections dump is borrower PII.

```bash
mkdir -p "$HOME/habibi-backups"
DUMP="$HOME/habibi-backups/collections-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker exec collections_db pg_dump -U collections -Fc collections > "$DUMP"
ls -l "$DUMP"
```

The role is `collections`, not `postgres`. Custom format (`-Fc`) is
what `pg_restore` in §3 expects.

Then deploy the new SHA:

```bash
IMAGE_PREFIX=ghcr.io/susanthp18/habibi/ IMAGE_TAG=<new-sha> docker compose pull
IMAGE_PREFIX=ghcr.io/susanthp18/habibi/ IMAGE_TAG=<new-sha> docker compose up -d --no-build
```

Then, only if this release includes a migration:

```bash
docker exec collections_api alembic upgrade head
```

---

## 2 · Roll the images back (two commands)

`<previous-sha>` is the value you wrote down in §0.

```bash
IMAGE_PREFIX=ghcr.io/susanthp18/habibi/ IMAGE_TAG=<previous-sha> docker compose pull
IMAGE_PREFIX=ghcr.io/susanthp18/habibi/ IMAGE_TAG=<previous-sha> docker compose up -d --no-build
```

`--no-build` is load-bearing. Without it, compose will rebuild
`:local` from the working tree and you will not be on the SHA you named.

Confirm:

```bash
docker inspect -f '{{.Config.Image}}' collections_api
docker inspect -f '{{.Config.Image}}' collections_voice
```

Both must end in `:<previous-sha>`.

### What this reverts

- The API, KB worker, bot worker, voice runner, and voice insurance
  processes. They share two images (`collections-api`,
  `collections-voice`); the five containers move together.

### What this does not revert

- **Postgres.** Schema and rows stay at whatever `alembic upgrade`
  (and the application) already wrote. Rolling the image back does not
  run `alembic downgrade`, and you must not run it yourself — see below.
- **Redis / MinIO contents.**
- **In-flight carrier side effects.** A call already ringing, an SMS
  already accepted by Twilio, a WhatsApp already handed to Meta — none
  of those unhappen. Stop outbound before a risky deploy
  (`platform_switches` `outbound.enabled`, not an env flag) if the
  release touches dialling.
- **The operator console**, which is not in these images.

If the release you are undoing **did not migrate**, §2 is the whole
rollback. If it **did** migrate, continue to §3.

---

## 3 · Restore the database (only when the schema or rows moved)

`pg_restore` from the dump in §1 is the database rollback. Not
`alembic downgrade`.

Stop writers first so they cannot land rows during the restore:

```bash
docker stop collections_api collections_kb_worker collections_bot_worker \
  collections_voice collections_voice_insurance
```

Then restore and bring the **previous** images back up:

```bash
docker exec -i collections_db pg_restore -U collections -d collections \
  --clean --if-exists --no-owner < "$DUMP"

IMAGE_PREFIX=ghcr.io/susanthp18/habibi/ IMAGE_TAG=<previous-sha> docker compose up -d --no-build
```

`--clean --if-exists` drops objects in the dump before recreating them.
It is the correct inverse of an upgrade; it is also destructive of
anything written *after* the dump. That is why the dump is taken
immediately before the upgrade, and why writers are stopped first.

---

## 4 · Why `alembic downgrade` is not the rollback

No downgrade in this repository has ever been executed by CI
(`RUN_ALEMBIC_ROUNDTRIP=0`). The functions run only in an emergency,
and three of them destroy regulatory evidence:

| Revision | Downgrade does | What is then unrecoverable |
|---|---|---|
| `20260822_0098` | `DELETE FROM channel_consents WHERE purpose='promotional'` | Every promotional DPDP consent basis ever captured. Restoring the schema does not restore the permission; you would have to re-collect consent. |
| `20260813_0066` | Drops `contact_events` and `contact_day_counters` | The RBI frequency-cap ledger. `channel_consents.used_this_week` is only a cache of it. |
| `20260822_0094` | Drops `call_attempts` and `call_outcomes` | The proof a call was **not** placed, including suppressed attempts. |

Several upgrades also mutate real rows **unconditionally** (they are
not gated by `seed_guard`):

| Revision | What `upgrade` rewrites |
|---|---|
| `20260812_0064` | Stock role grants |
| `20260815_0073` | `DELETE FROM prompt_versions` plus first-party bot inserts |
| `20260819_0084` | Persona / prompt text (what the Mouth says to a borrower) |
| `20260825_0101` | The same class of rewrite. **`downgrade()` is `pass`** — the prior persona text is gone from the database. Recoverable only from the dump, or from the `0084` revision text if you are willing to reconstruct by hand. |
| `20260901_0103` | Eval fixtures |

So: dump before upgrade; restore from the dump; never `alembic
downgrade` against a customer database.

---

## 5 · Frontend

`Habibi/` is not in `docker-compose.yml`. CI (`frontend-typecheck.yml`)
now runs `npm run build` because `nitro` is pinned to
`3.0.260603-beta` and a build-breaking change would otherwise ship
green. Rolling the console back is whatever the host that serves
`Habibi/` already does with a previous artefact. Do not invent a
container for it here.
