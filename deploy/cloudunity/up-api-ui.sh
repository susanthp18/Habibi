#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/azureuser/beeonix-payint
cd "$ROOT/backend"
# Existing stack was created with -p payint. Do not use the directory default
# (backend) or compose will try to create a second Postgres volume.
COMPOSE=(docker-compose -p payint --env-file .env --env-file ../deploy/cloudunity/compose.env -f docker-compose.yml)

echo "== drop accidental backend_* leftovers if empty =="
docker network rm backend_default 2>/dev/null || true
docker volume rm backend_pgdata backend_minio_data backend_voice_sessions 2>/dev/null || true

echo "== recreate api-family on new image; keep voice =="
"${COMPOSE[@]}" up -d --no-build --no-deps --force-recreate api bot_worker worker wk_batch
docker restart payint_ui

echo "== wait api health =="
for i in $(seq 1 40); do
  if docker inspect -f '{{.State.Health.Status}}' collections_api 2>/dev/null | grep -q healthy; then
    echo "api healthy after ${i}"
    break
  fi
  sleep 3
done

echo "== images =="
docker inspect -f '{{.Name}} {{.Config.Image}} created={{.Created}}' collections_api collections_voice collections_bot_worker collections_db

echo "== probes =="
curl -sS -o /dev/null -w "local_api:%{http_code}\n" -m 5 http://127.0.0.1:8100/ready || true
curl -sS -o /dev/null -w "https_ready:%{http_code}\n" -m 10 https://beeonixpayint.bigtapp.net/api/ready || true
curl -sS -o /dev/null -w "https_app:%{http_code}\n" -m 10 https://beeonixpayint.bigtapp.net/app/ || true
docker-compose -p payint ls || true
docker ps --filter name=collections_ --format '{{.Names}} {{.Status}}'
docker ps --filter name=payint_ --format '{{.Names}} {{.Status}}'
echo DONE
