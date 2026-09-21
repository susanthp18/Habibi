set -euo pipefail
echo INFLIGHT
docker exec collections_db psql -U collections -d collections -tAc \
  "select count(*) from call_attempts where closed_at is null and state in ('reserved','dialing','ringing','answered','live')"
echo SIZES
du -sh /home/azureuser/beeonix-payint/Habibi /home/azureuser/beeonix-payint/backend
du -sh /home/azureuser/beeonix-payint/Habibi/node_modules || true
mkdir -p /home/azureuser/habibi-backups
echo OK
