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
# $PSScriptRoot is backend\scripts, so its parent IS backend. The old fallback
# appended a second "backend" segment (backend\backend), producing a path that
# can never exist and silently starting every process in the wrong directory.
$Backend = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$Backend\main.py")) {
  throw "Cannot find backend\main.py at $Backend"
}
$Py = Join-Path $Backend ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
  Write-Error "Missing venv at $Py — create backend\.venv and install requirements.txt"
}

Write-Host "Backend root: $Backend"
Write-Host "Starting uvicorn :8000 ..."
$Api = Start-Process -FilePath $Py -ArgumentList "-m","uvicorn","main:app","--host","127.0.0.1","--port","8000" -WorkingDirectory $Backend -PassThru

# Poll /ready instead of sleeping a fixed 2s: on a cold start (migrations, model
# load) the workers used to come up against an API that was not listening yet,
# and on a fast start we wasted the wait.
$ReadyTimeoutSec = 60
$Deadline = (Get-Date).AddSeconds($ReadyTimeoutSec)
$Ready = $false
while ((Get-Date) -lt $Deadline) {
  if ($Api.HasExited) {
    throw "uvicorn exited during startup (exit code $($Api.ExitCode)) — check the API window for the error"
  }
  try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/ready" -UseBasicParsing -TimeoutSec 3
    if ($resp.StatusCode -eq 200) { $Ready = $true; break }
  } catch {
    Start-Sleep -Milliseconds 500
  }
}
if (-not $Ready) {
  throw "API did not become ready within $ReadyTimeoutSec seconds — not starting workers"
}
Write-Host "API ready."

Write-Host "Starting KB worker ..."
Start-Process -FilePath $Py -ArgumentList "-m","worker" -WorkingDirectory $Backend
Write-Host "Starting bot worker ..."
Start-Process -FilePath $Py -ArgumentList "-m","bot_worker" -WorkingDirectory $Backend
Write-Host "Starting voice bot :7860 ..."
Start-Process -FilePath $Py -ArgumentList "-m","voice.bot" -WorkingDirectory $Backend
Write-Host "Done. Probes: http://127.0.0.1:8000/health  http://127.0.0.1:8000/ready"
