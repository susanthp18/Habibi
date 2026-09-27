#!/usr/bin/env bash
# Finish a partial CloudUnity overlay. Restores backend/.env from the
# stamped copy in /tmp. Does not run alembic. Does not start Asterisk.
set -euo pipefail

ROOT=/home/azureuser/beeonix-payint
STAMP=20260918T162242Z

echo "== wipe leftover Habibi as root =="
sudo rm -rf "$ROOT/Habibi"

echo "== extract =="
mkdir -p "$ROOT"
tar -xzf /tmp/habibi.tgz -C "$ROOT"
tar -xzf /tmp/backend.tgz -C "$ROOT"

echo "== restore secrets =="
test -f "/tmp/backend.env.$STAMP"
cp -a "/tmp/backend.env.$STAMP" "$ROOT/backend/.env"
chmod 600 "$ROOT/backend/.env"
if [ -f "/tmp/habibi.env.production.$STAMP" ]; then
  cp -a "/tmp/habibi.env.production.$STAMP" "$ROOT/Habibi/.env.production"
  cp -a "$ROOT/Habibi/.env.production" "$ROOT/Habibi/.env"
  chmod 600 "$ROOT/Habibi/.env"
fi
sudo mv "/tmp/habibi-node_modules.$STAMP" "$ROOT/Habibi/node_modules"

test -f "$ROOT/backend/.env"
test -f "$ROOT/Habibi/vite.config.ts"
test -f "$ROOT/backend/voice/telephony.py"
echo "$(date -u +%Y%m%dT%H%M%SZ) overlay no-asterisk-overlay no-alembic (schema NOT migrated by this script)" > "$ROOT/DEPLOYED_SHA"
echo "trees restored"

echo "== rebuild images =="
cd "$ROOT/backend"
docker-compose -p payint --env-file .env --env-file ../deploy/cloudunity/compose.env -f docker-compose.yml -f docker-compose.agentstudio.yml build api

echo "== recreate app containers =="
docker-compose -p payint --env-file .env --env-file ../deploy/cloudunity/compose.env -f docker-compose.yml -f docker-compose.agentstudio.yml up -d --no-build \
  api bot_worker worker wk_batch
# The legacy in-house voice runner is retired: every call runs on Voice Studio
# (TELEPHONY_PROVIDER=studio from docker-compose.agentstudio.yml). Stopped, not
# removed, so it stays available for a rollback.
docker stop collections_voice >/dev/null 2>&1 || true

echo "== release production UI =="
docker run --rm --memory=2g --cpus=2 \
  -v "$ROOT/Habibi:/app" -w /app node:22-bookworm \
  npm install --no-audit --no-fund --loglevel=error
bash "$ROOT/deploy/cloudunity/ui-production.sh"

echo "== wait health =="
for i in $(seq 1 80); do
  if docker inspect -f '{{.State.Health.Status}}' collections_api 2>/dev/null | grep -q healthy; then
    echo "api healthy after ${i}"
    break
  fi
  sleep 3
done

echo "== status =="
docker ps --filter name=collections_ --format '{{.Names}} {{.Status}}'
docker ps --filter name=payint_ --format '{{.Names}} {{.Status}}'
curl -sS -o /dev/null -w "local_api:%{http_code}\n" -m 5 http://127.0.0.1:8100/ready || true
curl -sS -o /dev/null -w "https_app:%{http_code}\n" -m 10 https://beeonixpayint.bigtapp.net/app/ || true
echo DONE
