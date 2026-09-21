#!/usr/bin/env bash
# Overlay laptop Habibi + backend onto CloudUnity. Does not start Asterisk,
# does not run alembic, does not touch backend/.env.
set -euo pipefail

ROOT=/home/azureuser/beeonix-payint
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/home/azureuser/habibi-backups/code-pre-${STAMP}.tgz
mkdir -p /home/azureuser/habibi-backups

echo "== backup code (no node_modules, no .env) =="
tar -czf "$BACKUP" -C "$ROOT" \
  --exclude=Habibi/node_modules \
  --exclude=backend/.venv \
  --exclude=backend/.env \
  Habibi backend
ls -lh "$BACKUP"

echo "== keep secrets and node_modules =="
cp -a "$ROOT/backend/.env" "/tmp/backend.env.$STAMP"
if [ -f "$ROOT/Habibi/.env.production" ]; then
  cp -a "$ROOT/Habibi/.env.production" "/tmp/habibi.env.production.$STAMP"
fi
if [ -d "$ROOT/Habibi/node_modules" ]; then
  sudo mv "$ROOT/Habibi/node_modules" "/tmp/habibi-node_modules.$STAMP"
fi

echo "== replace trees =="
rm -rf "$ROOT/Habibi" "$ROOT/backend"
mkdir -p "$ROOT"
tar -xzf /tmp/habibi.tgz -C "$ROOT"
tar -xzf /tmp/backend.tgz -C "$ROOT"
cp -a "/tmp/backend.env.$STAMP" "$ROOT/backend/.env"
if [ -f "/tmp/habibi.env.production.$STAMP" ]; then
  cp -a "/tmp/habibi.env.production.$STAMP" "$ROOT/Habibi/.env.production"
  # `vite dev` ignores .env.production; payint_ui is a dev server.
  cp -a "$ROOT/Habibi/.env.production" "$ROOT/Habibi/.env"
  chmod 600 "$ROOT/Habibi/.env"
fi
if [ -d "/tmp/habibi-node_modules.$STAMP" ]; then
  sudo mv "/tmp/habibi-node_modules.$STAMP" "$ROOT/Habibi/node_modules"
fi
test -f "$ROOT/backend/.env"
test -f "$ROOT/Habibi/vite.config.ts"
test -f "$ROOT/backend/voice/telephony.py"
echo "$(date -u +%Y%m%dT%H%M%SZ) overlay no-asterisk-overlay no-alembic (schema NOT migrated by this script)" > "$ROOT/DEPLOYED_SHA"

echo "== rebuild images (Twilio path, no telephony overlay) =="
cd "$ROOT/backend"
docker-compose -p payint --env-file .env --env-file ../deploy/cloudunity/compose.env -f docker-compose.yml build api voice

echo "== recreate app containers =="
docker-compose -p payint --env-file .env --env-file ../deploy/cloudunity/compose.env -f docker-compose.yml up -d --no-build \
  api voice bot_worker worker wk_batch

echo "== restart UI (keep node_modules; npm ci if lock changed) =="
docker restart payint_ui

echo "== wait health =="
for i in $(seq 1 60); do
  if docker inspect -f '{{.State.Health.Status}}' collections_api 2>/dev/null | grep -q healthy \
     && curl -sS -o /dev/null -m 3 -w '' http://127.0.0.1:3108/app/; then
    echo "up after ${i} tries"
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
