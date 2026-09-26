#!/usr/bin/env bash
# Roll PayInt Voice Studio onto CloudUnity: overlay the laptop trees
# (/tmp/{habibi,backend,agentstudio,deploy}.tgz), fill missing secrets, build and
# start the engine next to the API, apply sql/66-69 (Voice Studio tables) and
# add the nginx locations. Never runs alembic (0156 stays unapplied) and never
# prints a secret. Seeding the engine is a separate step (see README).
set -euo pipefail

ROOT=/home/azureuser/beeonix-payint
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p /home/azureuser/habibi-backups

echo "== backup code =="
tar -czf "/home/azureuser/habibi-backups/code-pre-${STAMP}.tgz" -C "$ROOT" \
  --exclude=Habibi/node_modules --exclude=backend/.venv --exclude=backend/.env \
  --exclude=Habibi/.env --exclude=Habibi/.env.production \
  Habibi backend deploy $( [ -d "$ROOT/agentstudio" ] && echo agentstudio )

echo "== keep secrets and node_modules =="
cp -a "$ROOT/backend/.env" "/tmp/backend.env.$STAMP"
cp -a "$ROOT/deploy/cloudunity/compose.env" "/tmp/compose.env.$STAMP"
[ -f "$ROOT/Habibi/.env.production" ] && cp -a "$ROOT/Habibi/.env.production" "/tmp/habibi.env.production.$STAMP"
[ -d "$ROOT/Habibi/node_modules" ] && sudo mv "$ROOT/Habibi/node_modules" "/tmp/habibi-node_modules.$STAMP"

echo "== replace trees =="
sudo rm -rf "$ROOT/Habibi" "$ROOT/backend" "$ROOT/agentstudio" "$ROOT/deploy"
for t in habibi backend agentstudio deploy; do tar -xzf "/tmp/$t.tgz" -C "$ROOT"; done
cp -a "/tmp/backend.env.$STAMP" "$ROOT/backend/.env"
cp -a "/tmp/compose.env.$STAMP" "$ROOT/deploy/cloudunity/compose.env"
if [ -f "/tmp/habibi.env.production.$STAMP" ]; then
  cp -a "/tmp/habibi.env.production.$STAMP" "$ROOT/Habibi/.env.production"
  cp -a "$ROOT/Habibi/.env.production" "$ROOT/Habibi/.env"   # payint_ui is `vite dev`
  chmod 600 "$ROOT/Habibi/.env"
fi
[ -d "/tmp/habibi-node_modules.$STAMP" ] && sudo mv "/tmp/habibi-node_modules.$STAMP" "$ROOT/Habibi/node_modules"
chmod 600 "$ROOT/backend/.env"

echo "== Voice Studio secrets (generated only when missing) =="
for k in AGENTSTUDIO_INTERNAL_SECRET VOICE_STUDIO_HOOK_TOKEN AGENTSTUDIO_JWT_SECRET AGENTSTUDIO_TURN_SECRET \
         AGENTSTUDIO_TELEPHONY_WS_SECRET AGENTSTUDIO_DB_PASSWORD AGENTSTUDIO_REDIS_PASSWORD; do
  grep -q "^$k=" "$ROOT/backend/.env" || { echo "$k=$(openssl rand -hex 32)" >> "$ROOT/backend/.env"; echo "  added $k"; }
done
echo "== Voice Studio settings in compose.env =="
grep -E '^(AGENTSTUDIO_[A-Z_]+)=' "$ROOT/deploy/cloudunity/compose.env.example" | while IFS= read -r line; do
  k=${line%%=*}
  grep -q "^$k=" "$ROOT/deploy/cloudunity/compose.env" || { echo "$line" >> "$ROOT/deploy/cloudunity/compose.env"; echo "  added $k"; }
done
echo "$STAMP overlay + PayInt Voice Studio engine; sql/66-69 by hand; alembic not run" > "$ROOT/DEPLOYED_SHA"

cd "$ROOT/backend"
COMPOSE=(docker-compose -p payint --env-file .env --env-file ../deploy/cloudunity/compose.env
         -f docker-compose.yml -f docker-compose.agentstudio.yml)

echo "== build =="
"${COMPOSE[@]}" build api voice agentstudio_engine

echo "== schema: sql/66-69 Voice Studio (agents, releases, MCP keys, release attempts; additive) =="
for f in sql/66_voice_studio_agents.sql sql/67_voice_studio_releases.sql          sql/68_voice_studio_mcp_keys.sql sql/69_voice_studio_release_attempts.sql; do
  docker exec -i collections_db psql -U collections -d collections -v ON_ERROR_STOP=1 < "$f"
done

echo "== row security for the new tables (before the API starts: its startup gate refuses otherwise) =="
# The API's own env reaches the DB; backend/.env alone points at 127.0.0.1.
ENVF=$(umask 077; mktemp)
docker inspect collections_api --format '{{range .Config.Env}}{{println .}}{{end}}'   | grep -E '^(DATABASE_URL|MIGRATION_DATABASE_URL|TENANT_ID|APP_ENV|POSTGRES_[A-Z_]*|PII_[A-Z_]*)=' > "$ENVF"
RLS=(docker run --rm --network payint_default --env-file "$ENVF" -e PYTHONPATH=/app -w /app collections-api:local python scripts/rls.py)
"${RLS[@]}" apply
"${RLS[@]}" enable --verify-as collections_app
rm -f "$ENVF"

echo "== start engine, recreate app containers =="
"${COMPOSE[@]}" up -d --no-build agentstudio_db_init agentstudio_redis agentstudio_turn agentstudio_engine
"${COMPOSE[@]}" up -d --no-build api voice bot_worker worker wk_batch

echo "== UI deps + restart =="
# The tree was replaced under payint_ui's bind mount: restart to re-attach first.
docker restart payint_ui
docker exec payint_ui sh -c "cd /app && npm install --no-audit --no-fund --loglevel=error"
docker restart payint_ui

echo "== nginx =="
CONF=/etc/nginx/sites-available/beeonixpayint_config
if ! sudo grep -q "PayInt Voice Studio" "$CONF"; then
  sudo cp -a "$CONF" "/home/azureuser/habibi-backups/beeonixpayint_config.$STAMP"
  sudo python3 - "$CONF" "$ROOT/deploy/cloudunity/nginx/voice-studio.locations.conf" <<'PY'
import sys
conf, block = sys.argv[1], open(sys.argv[2]).read()
s = open(conf).read()
anchor = "    location /api/ {"
assert s.count(anchor) == 1, "anchor not unique"
open(conf, "w").write(s.replace(anchor, block + anchor))
PY
  if sudo nginx -t; then sudo systemctl reload nginx; else
    sudo cp -a "/home/azureuser/habibi-backups/beeonixpayint_config.$STAMP" "$CONF"; echo "nginx -t failed; restored"; exit 1
  fi
fi

echo "== health =="
for i in $(seq 1 80); do
  docker inspect -f '{{.State.Health.Status}}' collections_agentstudio 2>/dev/null | grep -q healthy && { echo "engine healthy after $i"; break; }
  sleep 3
done
docker ps --filter name=collections_ --format '{{.Names}} {{.Status}}'
docker ps --filter name=payint_ --format '{{.Names}} {{.Status}}'
curl -sS -o /dev/null -w "local_api:%{http_code}\n" -m 5 http://127.0.0.1:8100/ready || true
curl -sS -o /dev/null -w "engine:%{http_code}\n" -m 5 http://127.0.0.1:8200/api/v1/health || true
curl -sS -o /dev/null -w "https_app:%{http_code}\n" -m 10 https://beeonixpayint.bigtapp.net/app/ || true
echo DONE
