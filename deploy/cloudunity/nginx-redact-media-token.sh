#!/usr/bin/env bash
# Keep the media socket's capability token out of nginx's access log.
#
# Carriers open wss://.../api/v1/telephony/ws/<workflow>/<org>/<run>/<token>,
# and the token is a bearer capability: whoever holds it can join the call's
# audio. The engine now masks it in its own lines (ws_auth.redact_token); this
# does the same for nginx, for the PayInt site only -- the host serves other
# projects, so the global log format is left alone. Idempotent; restores the
# site file if nginx rejects the result.
set -euo pipefail

SITE=/etc/nginx/sites-enabled/beeonixpayint_config
CONF=/etc/nginx/conf.d/payint-log-redact.conf
BACKUP_DIR=/etc/nginx/payint-backups   # not sites-enabled: nginx would load a copy there

sudo tee "$CONF" >/dev/null <<'NGINX'
# PayInt: the media socket's path with its capability token masked (see deploy/cloudunity/nginx-redact-media-token.sh).
map $request_uri $payint_log_uri {
    ~^(?<keep>/api/v1/telephony/ws/[^/]+/[^/]+/[^/]+)/[0-9a-f]{16,} "$keep/[REDACTED]";
    default $request_uri;
}
log_format payint_redacted '$remote_addr - $remote_user [$time_local] "$request_method $payint_log_uri $server_protocol" '
                           '$status $body_bytes_sent "$http_referer" "$http_user_agent"';
NGINX

if ! sudo grep -q payint_redacted "$SITE"; then
  sudo mkdir -p "$BACKUP_DIR"
  sudo cp "$(readlink -f "$SITE")" "$BACKUP_DIR/beeonixpayint_config.$(date +%Y%m%dT%H%M%S)"
  sudo sed -i --follow-symlinks \
    '/location ~ \^\/api\/v1\/(telephony|public|agent-stream)\/ {/a\        access_log /var/log/nginx/access.log payint_redacted;' \
    "$SITE"
fi

if sudo nginx -t; then
  sudo systemctl reload nginx
  echo "nginx: media token masked in the PayInt access log"
else
  latest=$(ls -t "$BACKUP_DIR"/beeonixpayint_config.* | head -1)
  sudo cp "$latest" "$(readlink -f "$SITE")"
  sudo rm -f "$CONF"
  echo "nginx rejected the change; restored $latest" >&2
  exit 1
fi
