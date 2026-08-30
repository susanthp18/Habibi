<#
.SYNOPSIS
  Stop and restart the whole native stack -- exactly one instance of each service.

.DESCRIPTION
  Restarting by hand went wrong in a way worth encoding here. The obvious way to
  stop a service is to find whoever holds its port, but `bot_worker`, `worker`
  and `voice.workers.insurance` do not listen on anything. Three restarts later
  the machine was running three KB workers, three insurance workers and six
  bot_worker processes, all sweeping the same tables on the same timers.

  Nothing crashes when that happens, which is the problem: duplicate workers
  double the nightly sweeps, double the eval schedule, and quietly contend on
  the treatment queue. It surfaced as a test failure that looked like a real
  regression and was not.

  So this stops by *command line*, not by port, and refuses to start a second
  copy of anything.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File backend\run_stack.ps1
  powershell -ExecutionPolicy Bypass -File backend\run_stack.ps1 -Stop
  powershell -ExecutionPolicy Bypass -File backend\run_stack.ps1 -NoFrontend
#>
[CmdletBinding()]
param(
    # Stop everything and exit without starting it again.
    [switch]$Stop,
    # Leave the Vite dev server alone (it has its own HMR and is slow to boot).
    [switch]$NoFrontend
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$Web = Join-Path (Split-Path -Parent $Root) 'Habibi'

if (-not (Test-Path $Py)) { throw "python not found at $Py -- create the venv first" }

# Every service, in start order. `Match` is what identifies an already-running
# instance; it must be specific enough not to match this script or an editor.
$Services = @(
    @{ Name = 'api';             Args = @('-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000'); Match = 'uvicorn main:app'; Log = 'api' }
    @{ Name = 'bot_worker';      Args = @('-m', 'bot_worker');                                                   Match = '-m bot_worker';   Log = 'botworker' }
    @{ Name = 'kb_worker';       Args = @('-m', 'worker');                                                       Match = '-m worker';       Log = 'worker' }
    @{ Name = 'voice';           Args = @('-m', 'voice.bot', '--host', '127.0.0.1', '--port', '7860');            Match = '-m voice.bot';    Log = 'voice' }
    @{ Name = 'voice_insurance'; Args = @('-m', 'voice.workers.insurance');                                      Match = 'voice.workers.insurance'; Log = 'voice_insurance' }
)

function Get-StackProcesses {
    param([string]$Match)
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains('Hackathon\backend\.venv') -and $_.CommandLine.Contains($Match) }
}

function Stop-Stack {
    foreach ($svc in $Services) {
        $procs = @(Get-StackProcesses -Match $svc.Match)
        if ($procs.Count -gt 0) {
            # More than one pair here means a previous restart leaked. Say so:
            # silently cleaning it up hides the thing worth knowing.
            if ($procs.Count -gt 2) {
                Write-Warning ("{0}: {1} processes running -- duplicates from an earlier restart" -f $svc.Name, $procs.Count)
            }
            foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
            Write-Host ("stopped {0} ({1} process(es))" -f $svc.Name, $procs.Count)
        }
    }
    if (-not $NoFrontend) {
        $vite = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($vite) { Stop-Process -Id $vite.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Host 'stopped vite' }
    }
    Start-Sleep -Seconds 3
}

Stop-Stack
if ($Stop) { Write-Host 'stack stopped.'; return }

foreach ($svc in $Services) {
    $running = @(Get-StackProcesses -Match $svc.Match)
    if ($running.Count -gt 0) {
        Write-Warning ("{0} did not stop -- not starting a second copy" -f $svc.Name)
        continue
    }
    Start-Process -FilePath $Py -ArgumentList $svc.Args -WorkingDirectory $Root `
        -RedirectStandardOutput (Join-Path $Root ("{0}.out.log" -f $svc.Log)) `
        -RedirectStandardError  (Join-Path $Root ("{0}.err.log" -f $svc.Log)) `
        -WindowStyle Hidden
    Write-Host ("started {0}" -f $svc.Name)
}

if (-not $NoFrontend) {
    $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
    if ($npm) {
        Start-Process -FilePath $npm -ArgumentList @('run', 'dev') -WorkingDirectory $Web `
            -RedirectStandardOutput (Join-Path $Web 'vite.out.log') `
            -RedirectStandardError  (Join-Path $Web 'vite.err.log') `
            -WindowStyle Hidden
        Write-Host 'started vite'
    } else {
        Write-Warning 'npm not found -- frontend not started'
    }
}

# Health, not just "the process exists". A worker that dies on import leaves no
# port behind to notice, so the count is checked too.
Write-Host ''
foreach ($port in 8000, 7860, 8080) {
    if ($NoFrontend -and $port -eq 8080) { continue }
    $up = $false
    foreach ($i in 1..30) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { $up = $true; break }
        Start-Sleep -Seconds 2
    }
    Write-Host ("port {0}: {1}" -f $port, $(if ($up) { 'LISTEN' } else { 'NOT LISTENING' }))
}
foreach ($svc in $Services) {
    $n = @(Get-StackProcesses -Match $svc.Match).Count
    # One logical service is a parent + child pair on Windows.
    $state = if ($n -eq 0) { 'DOWN' } elseif ($n -le 2) { 'ok' } else { "DUPLICATED ($n)" }
    Write-Host ("{0,-16} {1}" -f $svc.Name, $state)
}
