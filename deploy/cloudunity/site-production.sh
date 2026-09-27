#!/usr/bin/env bash
# Release the PayInt marketing site (the "/" pages) from a prebuilt static
# bundle: bash site-production.sh /tmp/site.tgz
#
# site.tgz is Site/dist/client, built and packed on the laptop by
# pack-release.sh (Site/ is not in git). The bundle is served by a pinned nginx
# container on an alternate loopback port, probed, and only then does the host
# nginx's `upstream payint_site` switch to it -- the same blue/green pattern as
# ui-production.sh. The old container and release stay on disk for rollback.
# Never serve `vite dev` here: it compiles on first visit and ships no
# prerendered markup.
set -euo pipefail

BUNDLE=${1:?usage: site-production.sh /path/to/site.tgz}
ROOT=/home/azureuser/beeonix-payint
CONF=/etc/nginx/sites-available/beeonixpayint_config
SITE_CONF="$ROOT/deploy/cloudunity/nginx/site-static.conf"
IMAGE=nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
RELEASES="$ROOT/site-releases"
RELEASE="$RELEASES/$STAMP"

exec 9>"$ROOT/.site-production.lock"
flock -n 9 || { echo 'A PayInt site deployment is already running' >&2; exit 1; }
test -f "$BUNDLE"
test -f "$SITE_CONF"

CURRENT=$(sudo python3 - "$CONF" <<'PY'
import re
import sys

text = open(sys.argv[1], encoding='utf-8').read()
ports = re.findall(r'upstream\s+payint_site\s*\{\s*server\s+127\.0\.0\.1:(\d+)\s*;', text)
assert len(ports) == 1, 'Expected exactly one PayInt site upstream'
print(ports[0])
PY
)
case "$CURRENT" in
  3109|3113) NEXT=3112 ;;
  3112) NEXT=3113 ;;
  *) echo "Unexpected PayInt site port $CURRENT" >&2; exit 1 ;;
esac

echo '== unpack and check the bundle =='
mkdir -p "$RELEASE"
tar -xzf "$BUNDLE" -C "$RELEASE"
for page in "" platform decision-engine agents compliance security product lenders insurance pricing demo; do
  test -f "$RELEASE/$page${page:+/}index.html" || { echo "bundle is missing /$page" >&2; exit 1; }
done
if grep -rlqE '/@vite/client|/src/entry-client' "$RELEASE"/index.html "$RELEASE"/*/index.html; then
  echo 'Bundle is a development build' >&2
  exit 1
fi
grep -q '<title>' "$RELEASE/index.html" || { echo 'Bundle is not prerendered' >&2; exit 1; }

NAME="payint_site_prod_$NEXT"
if docker container inspect "$NAME" >/dev/null 2>&1; then
  LABEL=$(docker inspect "$NAME" --format '{{index .Config.Labels "com.bigtapp.payint.site"}}')
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
  --label com.bigtapp.payint.site=production \
  --memory=128m --cpus=1 --read-only --tmpfs /var/cache/nginx --tmpfs /var/run \
  -p "127.0.0.1:$NEXT:80" \
  -v "$RELEASE:/usr/share/nginx/html:ro" \
  -v "$SITE_CONF:/etc/nginx/conf.d/default.conf:ro" \
  "$IMAGE" >/dev/null

READY=false
for _ in $(seq 1 20); do
  if [[ $(curl -sS -o /dev/null -w '%{http_code}' -m 3 "http://127.0.0.1:$NEXT/" 2>/dev/null) == 200 ]] &&
     [[ $(curl -sS -o /dev/null -w '%{http_code}' -m 3 "http://127.0.0.1:$NEXT/platform/" 2>/dev/null) == 200 ]]; then
    READY=true
    break
  fi
  sleep 1
done
[[ "$READY" == true ]] || { echo 'Candidate site did not become ready' >&2; exit 1; }
ASSET=$(grep -oE 'assets/[^"]+\.js' "$RELEASE/index.html" | head -1 | cut -d/ -f2)
test -n "$ASSET"
[[ $(curl -sS -o /dev/null -w '%{http_code}' -m 5 "http://127.0.0.1:$NEXT/assets/$ASSET") == 200 ]]

echo '== switch only the PayInt site upstream =='
BACKUP="$RELEASES/nginx-$STAMP.conf"
sudo cp -a "$CONF" "$BACKUP"
sudo python3 - "$CONF" "$CURRENT" "$NEXT" <<'PY'
import os
import re
import sys

path, current, next_port = sys.argv[1:]
text = open(path, encoding='utf-8').read()
pattern = r'(upstream\s+payint_site\s*\{\s*server\s+127\.0\.0\.1:)' + re.escape(current) + r'(\s*;)'
updated, count = re.subn(pattern, lambda match: match[1] + next_port + match[2], text)
assert count == 1, 'PayInt site upstream changed unexpectedly'
temp = path + '.site-next'
with open(temp, 'w', encoding='utf-8') as handle:
    handle.write(updated)
os.replace(temp, path)
PY
if ! sudo nginx -t || ! sudo systemctl reload nginx; then
  sudo cp -a "$BACKUP" "$CONF"
  sudo nginx -t && sudo systemctl reload nginx
  echo 'nginx rejected candidate; restored prior PayInt site upstream' >&2
  exit 1
fi
PUBLIC=$(curl -sS -m 10 'https://beeonixpayint.bigtapp.net/platform/' || true)
if ! grep -q "$ASSET" <<<"$PUBLIC"; then
  sudo cp -a "$BACKUP" "$CONF"
  sudo nginx -t && sudo systemctl reload nginx
  echo 'Public site probe did not see the new release; restored prior PayInt site upstream' >&2
  exit 1
fi

# Keep the old container and release on disk for rollback, but stop its CPU use.
if [[ "$CURRENT" == 3109 ]]; then
  docker stop payint_site >/dev/null
else
  docker stop "payint_site_prod_$CURRENT" >/dev/null
fi
# Keep the three newest releases; the one just replaced is among them.
ls -1dt "$RELEASES"/2*/ 2>/dev/null | tail -n +4 | xargs -r rm -rf
echo "PayInt site release $STAMP is live on loopback port $NEXT"
