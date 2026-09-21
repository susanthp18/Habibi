#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/azureuser/beeonix-payint
test -f "$ROOT/backend/.env"
test -f "$ROOT/Habibi/package-lock.json"

echo "== npm ci Habibi =="
docker run --rm --cpus=1.5 --memory=2g --memory-swap=2g \
  -v "$ROOT/Habibi:/app" -w /app node:22-bookworm \
  bash -lc 'npm ci --no-audit --no-fund'

echo "== rebuild api+voice =="
cd "$ROOT/backend"
docker compose --env-file ../deploy/cloudunity/compose.env -f docker-compose.yml build api voice

echo "== recreate app containers =="
docker compose --env-file ../deploy/cloudunity/compose.env -f docker-compose.yml up -d --no-build \
  api voice bot_worker worker wk_batch

echo "== restart UI =="
docker restart payint_ui

echo "== wait =="
for i in $(seq 1 80); do
  if docker inspect -f '{{.State.Health.Status}}' collections_api 2>/dev/null | grep -q healthy; then
    echo "api healthy after ${i}"
    break
  fi
  sleep 3
done

docker ps --filter name=collections_ --format '{{.Names}} {{.Status}}'
docker ps --filter name=payint_ --format '{{.Names}} {{.Status}}'
curl -sS -o /dev/null -w "local_api:%{http_code}\n" -m 5 http://127.0.0.1:8100/ready || true
curl -sS -o /dev/null -w "https_app:%{http_code}\n" -m 10 https://beeonixpayint.bigtapp.net/app/ || true
echo DONE
