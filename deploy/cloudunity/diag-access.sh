#!/usr/bin/env bash
set -euo pipefail
echo "===== UI ENV NAMES ====="
docker inspect payint_ui --format '{{range .Config.Env}}{{println .}}{{end}}' | cut -d= -f1 | sort
echo "===== HABIBI .env.production KEYS ====="
if [ -f /home/azureuser/beeonix-payint/Habibi/.env.production ]; then
  grep -E '^[A-Z0-9_]+=' /home/azureuser/beeonix-payint/Habibi/.env.production | cut -d= -f1
else
  echo none
fi
echo "===== HABIBI .env KEYS ====="
if [ -f /home/azureuser/beeonix-payint/Habibi/.env ]; then
  grep -E '^[A-Z0-9_]+=' /home/azureuser/beeonix-payint/Habibi/.env | cut -d= -f1
else
  echo none
fi
echo "===== ENTRA KEYS IN BACKEND ENV ====="
grep -E '^ENTRA_' /home/azureuser/beeonix-payint/backend/.env | cut -d= -f1
echo "===== ENTRA VALUES EMPTY? ====="
python3 - <<'PY'
from pathlib import Path
p = Path("/home/azureuser/beeonix-payint/backend/.env")
for line in p.read_text(errors="replace").splitlines():
    if not line.startswith("ENTRA_"):
        continue
    key, _, val = line.partition("=")
    print(f"{key} empty={not bool(val.strip())} quoted={val[:1] in '\"'}")
PY
echo "===== API /me and entra logs ====="
docker logs collections_api --since 6h 2>&1 | grep -E '/me |entra |provision|unauthorized|GET /me|401|403|Entra' | tail -80
echo "===== nginx /api/me ====="
sudo awk '/\/api\/me/ {print}' /var/log/nginx/access.log 2>/dev/null | tail -25 || true
echo "===== USERS matching susanth or bootstrap ====="
docker exec collections_db psql -U collections -d collections -c "SET app.tenant_id = 'hdfc.retail'; SELECT id, name, status, bootstrap_admin, entra_upn IS NOT NULL AS has_upn, email IS NOT NULL AS has_email FROM users WHERE bootstrap_admin IS TRUE OR lower(coalesce(entra_upn,'')) LIKE '%susanth%' OR lower(coalesce(email,'')) LIKE '%susanth%' OR lower(coalesce(name,'')) LIKE '%susanth%';"
echo "===== USER ROLES ====="
docker exec collections_db psql -U collections -d collections -c "SET app.tenant_id = 'hdfc.retail'; SELECT u.id, u.status, u.bootstrap_admin, ur.role_id FROM users u LEFT JOIN user_roles ur ON ur.user_id = u.id WHERE u.bootstrap_admin IS TRUE OR lower(coalesce(u.entra_upn,'')) LIKE '%susanth%' OR lower(coalesce(u.email,'')) LIKE '%susanth%';"
echo "===== ROLE GRANT COUNTS ====="
docker exec collections_db psql -U collections -d collections -c "SET app.tenant_id = 'hdfc.retail'; SELECT r.id, r.name, count(rp.permission_id) AS grants FROM roles r LEFT JOIN role_permissions rp ON rp.role_id = r.id GROUP BY r.id, r.name ORDER BY r.name;"
echo "===== JWKS REACHABLE FROM API ====="
docker exec collections_api python -c "import urllib.request; urllib.request.urlopen('https://login.microsoftonline.com/common/discovery/v2.0/keys', timeout=8); print('jwks_ok')" 2>&1 | tail -5
echo "===== PAYINT UI TAIL ====="
docker logs payint_ui --since 2h 2>&1 | tail -15
echo DONE
