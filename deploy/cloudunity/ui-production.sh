#!/usr/bin/env bash
# Build and switch only PayInt's UI on the shared CloudUnity host.
# The currently serving UI remains live until the new Node build and its
# /app/ assets pass local probes. Previous release directories are retained.
set -euo pipefail

ROOT=/home/azureuser/beeonix-payint
UI="$ROOT/Habibi"
CONF=/etc/nginx/sites-available/beeonixpayint_config
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
RELEASE="$ROOT/habibi-ui-releases/$STAMP"

exec 9>"$ROOT/.ui-production.lock"
flock -n 9 || { echo 'A PayInt UI deployment is already running' >&2; exit 1; }
test -f "$UI/.env.production"
test -d "$UI/node_modules"
test -f "$UI/package-lock.json"

CURRENT=$(sudo python3 - "$CONF" <<'PY'
import re
import sys

text = open(sys.argv[1], encoding='utf-8').read()
ports = re.findall(r'upstream\s+payint_ui\s*\{\s*server\s+127\.0\.0\.1:(\d+)\s*;', text)
assert len(ports) == 1, 'Expected exactly one PayInt UI upstream'
assert 'server_name beeonixpayint.bigtapp.net;' in text
print(ports[0])
PY
)
case "$CURRENT" in
  3108|3111) NEXT=3110 ;;
  3110) NEXT=3111 ;;
  *) echo "Unexpected PayInt UI port $CURRENT" >&2; exit 1 ;;
esac

FREE_GB=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
[[ -n "$FREE_GB" && "$FREE_GB" -ge 10 ]] || {
  echo 'Less than 10 GB free; refusing to build on the shared host' >&2
  exit 1
}

echo '== build the existing server source with a bounded builder =='
docker run --rm --memory=3g --cpus=2 \
  -e NITRO_PRESET=node-server \
  -e NITRO_APP_BASE_URL=/app/ \
  -e HABIBI_BASE=/app/ \
  -v "$UI:/app" -w /app node:22-bookworm \
  npm run build -- --logLevel=error
test -f "$UI/.output/server/index.mjs"
grep -q '"preset": "node-server"' "$UI/.output/nitro.json"

echo '== snapshot an immutable release and preserve old hashed assets =='
mkdir -p "$RELEASE/.output"
rsync -a "$UI/.output/" "$RELEASE/.output/"
if [[ "$CURRENT" == 3110 || "$CURRENT" == 3111 ]]; then
  OLD_NAME="payint_ui_prod_$CURRENT"
  OLD_OUTPUT=$(docker inspect "$OLD_NAME" --format '{{range .Mounts}}{{if eq .Destination "/app/.output"}}{{.Source}}{{end}}{{end}}')
  test -d "$OLD_OUTPUT/public/assets"
  rsync -a --ignore-existing "$OLD_OUTPUT/public/assets/" "$RELEASE/.output/public/assets/"
fi

NAME="payint_ui_prod_$NEXT"
if docker container inspect "$NAME" >/dev/null 2>&1; then
  LABEL=$(docker inspect "$NAME" --format '{{index .Config.Labels "com.bigtapp.payint.ui"}}')
  [[ "$LABEL" == production ]] || { echo "Refusing to replace $NAME" >&2; exit 1; }
  docker stop "$NAME" >/dev/null
  docker rm "$NAME" >/dev/null
fi
if ss -ltn "sport = :$NEXT" | grep -q 'LISTEN'; then
  echo "Port $NEXT is in use; refusing to affect another service" >&2
  exit 1
fi

echo "== start candidate on loopback port $NEXT =="
docker run -d --name "$NAME" --restart unless-stopped \
  --label com.bigtapp.payint.ui=production \
  --memory=1g --cpus=2 \
  -p "127.0.0.1:$NEXT:3108" \
  -e NODE_ENV=production -e NITRO_PORT=3108 -e NITRO_HOST=0.0.0.0 \
  -v "$RELEASE/.output:/app/.output:ro" -w /app \
  node:22-bookworm node .output/server/index.mjs >/dev/null

READY=false
for _ in $(seq 1 20); do
  if [[ $(curl -sS -o /dev/null -w '%{http_code}' -m 3 "http://127.0.0.1:$NEXT/app/studio/releases" 2>/dev/null) == 200 ]] &&
     [[ $(curl -sS -o /dev/null -w '%{http_code}' -m 3 "http://127.0.0.1:$NEXT/app/studio/reports" 2>/dev/null) == 200 ]]; then
    READY=true
    break
  fi
  sleep 1
done
[[ "$READY" == true ]] || { echo 'Candidate UI did not become ready' >&2; exit 1; }
ASSET=$(find "$RELEASE/.output/public/assets" -maxdepth 1 -name '*.js' -printf '%f\n' -quit)
test -n "$ASSET"
[[ $(curl -sS -o /dev/null -w '%{http_code}' -m 5 "http://127.0.0.1:$NEXT/app/assets/$ASSET") == 200 ]]
if curl -sS -m 5 "http://127.0.0.1:$NEXT/app/studio/releases" | grep -aqE '/@vite/|/@id/virtual:tanstack-start-dev'; then
  echo 'Candidate still serves development modules' >&2
  exit 1
fi

echo '== switch only the PayInt nginx upstream =='
BACKUP="$ROOT/habibi-ui-releases/nginx-$STAMP.conf"
sudo cp -a "$CONF" "$BACKUP"
sudo python3 - "$CONF" "$CURRENT" "$NEXT" <<'PY'
import os
import re
import sys

path, current, next_port = sys.argv[1:]
text = open(path, encoding='utf-8').read()
pattern = r'(upstream\s+payint_ui\s*\{\s*server\s+127\.0\.0\.1:)' + re.escape(current) + r'(\s*;)'
updated, count = re.subn(pattern, lambda match: match[1] + next_port + match[2], text)
assert count == 1, 'PayInt upstream changed unexpectedly'
temp = path + '.ui-next'
with open(temp, 'w', encoding='utf-8') as handle:
    handle.write(updated)
os.replace(temp, path)
PY
if ! sudo nginx -t || ! sudo systemctl reload nginx; then
  sudo cp -a "$BACKUP" "$CONF"
  sudo nginx -t && sudo systemctl reload nginx
  echo 'nginx rejected candidate; restored prior PayInt UI upstream' >&2
  exit 1
fi
if [[ $(curl -sS -o /dev/null -w '%{http_code}' -m 10 'https://beeonixpayint.bigtapp.net/app/studio/releases') != 200 ]]; then
  sudo cp -a "$BACKUP" "$CONF"
  sudo nginx -t && sudo systemctl reload nginx
  echo 'Public UI probe failed; restored prior PayInt UI upstream' >&2
  exit 1
fi

# Keep the old container and release on disk for rollback, but stop its CPU use.
if [[ "$CURRENT" == 3108 ]]; then
  docker stop payint_ui >/dev/null
else
  docker stop "payint_ui_prod_$CURRENT" >/dev/null
fi
echo "PayInt UI production release $STAMP is live on loopback port $NEXT"
