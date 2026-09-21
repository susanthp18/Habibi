#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/azureuser/beeonix-payint
cd "$ROOT/backend"
COMPOSE=(docker-compose --env-file .env --env-file ../deploy/cloudunity/compose.env -f docker-compose.yml)

echo "== rebuild api+voice =="
"${COMPOSE[@]}" build api voice

echo "== recreate app containers =="
"${COMPOSE[@]}" up -d --no-build api voice bot_worker worker wk_batch

echo "== restart UI =="
docker restart payint_ui

echo "== wait api health =="
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
