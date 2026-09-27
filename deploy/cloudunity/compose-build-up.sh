#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/azureuser/beeonix-payint
cd "$ROOT/backend"
COMPOSE=(docker-compose -p payint --env-file .env --env-file ../deploy/cloudunity/compose.env -f docker-compose.yml -f docker-compose.agentstudio.yml)

echo "== rebuild api =="
"${COMPOSE[@]}" build api

echo "== recreate app containers =="
"${COMPOSE[@]}" up -d --no-build api bot_worker worker wk_batch
# The legacy in-house voice runner is retired: every call runs on Voice Studio
# (TELEPHONY_PROVIDER=studio from docker-compose.agentstudio.yml). Stopped, not
# removed, so it stays available for a rollback.
docker stop collections_voice >/dev/null 2>&1 || true

echo "== release production UI =="
bash "$ROOT/deploy/cloudunity/ui-production.sh"

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
