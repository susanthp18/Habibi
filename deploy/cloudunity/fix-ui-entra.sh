#!/usr/bin/env bash
# payint_ui runs `vite dev`, which ignores .env.production. Copy Entra client
# vars into .env and restart the UI. Never prints secret values.
set -euo pipefail

HAB=/home/azureuser/beeonix-payint/Habibi
test -f "$HAB/.env.production"
umask 077
cp -a "$HAB/.env.production" "$HAB/.env"
chmod 600 "$HAB/.env"

echo "===== .env KEY NAMES ====="
grep -E '^[A-Z0-9_]+=' "$HAB/.env" | cut -d= -f1

python3 - <<'PY'
from pathlib import Path

needed = ("VITE_ENTRA_CLIENT_ID", "VITE_ENTRA_TENANT_ID", "VITE_ENTRA_API_SCOPE")
text = Path("/home/azureuser/beeonix-payint/Habibi/.env").read_text(errors="replace")
vals = {}
for line in text.splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        continue
    key, _, val = stripped.partition("=")
    vals[key.strip()] = val.strip().strip('"').strip("'")
for key in needed:
    present = key in vals
    empty = not bool(vals.get(key, ""))
    print(f"{key} present={present} empty={empty}")
missing = [key for key in needed if not vals.get(key)]
if missing:
    raise SystemExit("missing or empty: " + ",".join(missing))
PY

echo "===== restart payint_ui ====="
docker restart payint_ui
sleep 4
for i in $(seq 1 30); do
  if curl -sS -o /dev/null -m 3 -w '' http://127.0.0.1:3108/app/; then
    echo "ui up after ${i}"
    break
  fi
  sleep 2
done

curl -sS -o /dev/null -w "https_app:%{http_code}\n" -m 10 https://beeonixpayint.bigtapp.net/app/ || true
curl -sS -o /dev/null -w "https_me_noauth:%{http_code}\n" -m 10 https://beeonixpayint.bigtapp.net/api/me || true
echo "===== payint_ui tail ====="
docker logs payint_ui --since 2m 2>&1 | tail -20
echo DONE
