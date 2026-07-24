# Start local stack in documented order.
# Preferred (supervised, restart: unless-stopped):
#   cd backend; docker compose up -d --build
#
# This script starts the four app processes on the host venv instead
# (data plane assumed already up: docker compose up -d db minio).
#
# Connection budget reminder (see optimization.md / .env.example):
#   sum(pool_size+max_overflow across processes) < Postgres max_connections - reserved

$ErrorActionPreference = "Stop"
$Backend = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$Backend\main.py")) {
  $Backend = Join-Path (Split-Path -Parent $PSScriptRoot) "backend"
}
$Py = Join-Path $Backend ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
  Write-Error "Missing venv at $Py — create backend\.venv and install requirements.txt"
}

Write-Host "Backend root: $Backend"
Write-Host "Starting uvicorn :8000 ..."
Start-Process -FilePath $Py -ArgumentList "-m","uvicorn","main:app","--host","127.0.0.1","--port","8000" -WorkingDirectory $Backend
Start-Sleep -Seconds 2
Write-Host "Starting KB worker ..."
Start-Process -FilePath $Py -ArgumentList "-m","worker" -WorkingDirectory $Backend
Write-Host "Starting bot worker ..."
Start-Process -FilePath $Py -ArgumentList "-m","bot_worker" -WorkingDirectory $Backend
Write-Host "Starting voice bot :7860 ..."
Start-Process -FilePath $Py -ArgumentList "-m","voice.bot" -WorkingDirectory $Backend
Write-Host "Done. Probes: http://127.0.0.1:8000/health  http://127.0.0.1:8000/ready"
