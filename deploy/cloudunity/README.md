# CloudUnity — beeonixpayint.bigtapp.net

Shared VM (`20.205.178.161`). Other products already occupy 80/443, 5432–5439, 6379, 8001/8006/8008, 8080–8084, 9000–9001. This overlay uses **unused loopback ports only**. It does not replace existing nginx sites.

| Process | Bind | Why this port |
|---|---|---|
| Habibi UI | `127.0.0.1:3108` | 8080 is SearxNG |
| FastAPI | `127.0.0.1:8100` | keep a PayInt block; 8000 is unused but 8001+ are taken |
| Voice | `127.0.0.1:7860` | free |
| Postgres | `127.0.0.1:5440` | 5432–5439 taken |
| MinIO | `127.0.0.1:9102` / `9103` | 9000–9001 are EIP MinIO |

Do not publish these on `0.0.0.0`. Do not `certbot` a name that is not `beeonixpayint.bigtapp.net`. Do not `nginx -s reload` until `nginx -t` is clean.

## Bring the API up (does not start other compose projects)

```bash
cp deploy/cloudunity/compose.env.example deploy/cloudunity/compose.env
# Fill secrets in backend/.env on the server. Never commit that file.
cd backend
docker compose --env-file ../deploy/cloudunity/compose.env -f docker-compose.yml up -d
```

Compose project name stays `backend` (directory name) unless you set `-p payint`. Container names are `collections_*`, which were not in use on this VM.

## UI

```bash
cd Habibi
cp ../deploy/cloudunity/habibi.env.example .env.production
npm run build
npx vite preview --host 127.0.0.1 --port 3108
```

## nginx (after DNS already points here)

```bash
sudo cp deploy/cloudunity/nginx/beeonixpayint.bigtapp.net.conf \
  /etc/nginx/sites-available/beeonixpayint_config
sudo ln -s /etc/nginx/sites-available/beeonixpayint_config /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d beeonixpayint.bigtapp.net
```

## PayInt Voice Studio (voice-agent engine)

Laptop: `bash deploy/cloudunity/pack-release.sh` builds `dist/{habibi,backend,agentstudio,deploy}.tgz`
from `git archive HEAD` — it refuses a dirty tree, and gitignored paths
(`.env`, `node_modules`, `.venv`) are excluded by construction rather than by
an exclude list that drifts. `scp` them to `/tmp/` and run
`bash /tmp/voice-studio-rollout.sh` on the VM. The rollout is re-runnable:
`sql/66`–`69` are `IF NOT EXISTS`, the secrets are only generated when absent,
and the nginx edit is skipped once its marker is present.
It backs up the code, generates missing Voice Studio secrets into `backend/.env`,
builds and starts `collections_agentstudio` (+ its Redis and the TURN relay on
3478), applies `sql/66`–`sql/69` by hand (alembic is not run; 0156 stays
pending), enables row security for them, installs UI deps and inserts `nginx/voice-studio.locations.conf`.
NSG `cloudunity-nsg` rule `PayInt-Voice-Studio-TURN` (570) opens 3478 tcp+udp.

Then seed the engine (as an admin user id):

```bash
docker exec collections_api python -m scripts.agentstudio_seed_models --actor <user>
docker exec collections_api python -m scripts.voice_studio_kb_import --actor <user>
docker exec collections_api python -m scripts.voice_studio_seed --actor <user> --hooks-url http://api:8000/voice-studio/hooks --env-file /tmp/vs.env
# copy VOICE_STUDIO_API_KEY from the container's /tmp/vs.env into backend/.env, then
# recreate api bot_worker worker wk_batch so calls and WhatsApp use the engine.
```

Before any deploy or routing change, snapshot what is live (every agent's
published version and definition, every inbound number, outbound objective and
WhatsApp binding):

```bash
docker exec collections_api python -m scripts.voice_studio_snapshot --out /app/.cache/vs-snapshots
```
For the 2026-09-26 rollout, a read-only snapshot of published definition 4 and
the inbound number's prior agent mapping is saved in
`voice-studio-rollback-2026-09-26.json` (the number is masked to its last four
digits). Refresh this snapshot before any later deployment.

The seed creates missing outbound, inbound, and WhatsApp starters, validates their published tools and paths, and
leaves every existing definition and route intact. Review and publish each
new agent in the visual builder. The current outbound published definition 4
is the starting point. In **Agent routing**, validate and activate WhatsApp and
finally the inbound number, while outbound remains on definition 4. Then edit
the outbound agent in a draft: remove its old inbound and WhatsApp branches,
and add an **Action failed** closing edge whose **Failure close path** checkbox
is on and whose closing prompt says the action was not recorded. Publish the
outbound-only version after review and validate its outbound objectives. This screen
audits changes and checks the published version, tool destinations, credentials,
context presets, and channel graph before activation. It also shows the prior
mapping after activation, so restore that agent ID there if inbound routing
does not behave as expected. Check engine and API startup/routing logs before
placing any demo call. WhatsApp uses an exact WhatsApp binding; it never falls
back to the outbound default. Call audio appears under **Call recordings**;
reusable prompt audio remains under **Audio Library**.

### Voice Studio releases and rollback

Agents go live only through **Publish** in the agent editor: the release checks
(approved tools, credentials, context parameters, the channel rules of every
route the agent serves) must pass and a "what changed" note is required. Each
publish is recorded with its author in `voice_studio_releases` and listed under
**Voice Studio → Releases**. The engine refuses direct publishes that skip this.

To roll an agent back, open it, choose the earlier version in its version
history and **Roll back to vN** with a reason. The version is re-checked and
published as the next version (history only grows), on every channel the agent
serves. To undo a routing change, re-assign the channel on **Agent routing** to
the agent recorded in the latest snapshot.
