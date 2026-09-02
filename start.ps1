<#
  SatQuery AI - one-command launcher (Windows / PowerShell)

    .\start.ps1              # install if needed, then run backend + frontend
    .\start.ps1 -Setup       # force a full reinstall and retrain the RS model
    .\start.ps1 -NoFrontend  # backend only (API + /docs)
    .\start.ps1 -Build       # build the frontend and serve it from the backend

  Requires Python 3.10+ and Node 18+ on PATH.
#>
[CmdletBinding()]
param(
    [switch]$Setup,
    [switch]$NoFrontend,
    [switch]$Build,
    [int]$Port = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$venv = Join-Path $root '.venv'
$py = Join-Path $venv 'Scripts\python.exe'

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "    $msg" -ForegroundColor DarkGray }
function Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "  SatQuery AI - agentic remote-sensing analysis" -ForegroundColor White
Write-Host "  SIH26167 (ISRO) - Team Avengers" -ForegroundColor DarkGray

# ---------------------------------------------------------------- python env
if ((-not (Test-Path $py)) -or $Setup) {
    Step 'Creating the Python environment'
    $sys = (Get-Command python -ErrorAction SilentlyContinue)
    if (-not $sys) { throw 'Python 3.10+ was not found on PATH. Install it from python.org first.' }
    if (-not (Test-Path $venv)) { & python -m venv $venv }
    Ok 'virtualenv ready'

    Step 'Installing backend dependencies (this takes a minute the first time)'
    & $py -m pip install --upgrade pip --quiet
    & $py -m pip install -r (Join-Path $backend 'requirements.txt') --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    Ok 'dependencies installed'
}

# ---------------------------------------------------------------- RS model
$model = Join-Path $root 'data\models\eurosat_rs_classifier.pkl'
if ((-not (Test-Path $model)) -or $Setup) {
    Step 'Adapting the scene classifier to remote-sensing imagery (EuroSAT)'
    Warn 'Downloads ~95 MB of real Sentinel-2 patches and trains for ~3 minutes.'
    Warn 'The app runs without it - that tool simply reports itself unavailable.'
    Push-Location $backend
    try { & $py -m app.ml.train_eurosat --limit-per-class 900 }
    catch { Warn "Training skipped: $_" }
    finally { Pop-Location }
} else {
    Ok 'remote-sensing classifier already trained'
}

# ---------------------------------------------------------------- frontend
if (-not $NoFrontend) {
    if ((-not (Test-Path (Join-Path $frontend 'node_modules'))) -or $Setup) {
        Step 'Installing frontend dependencies'
        if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
            throw 'Node.js 18+ / npm was not found on PATH. Install it from nodejs.org.'
        }
        Push-Location $frontend
        try { & npm install } finally { Pop-Location }
    }
    if ($Build) {
        Step 'Building the frontend'
        Push-Location $frontend
        try { & npm run build } finally { Pop-Location }
        Ok 'built - the backend will serve it at /app'
    }
}

# ---------------------------------------------------------------- run
Step 'Starting the backend'
$env:SATQUERY_PORT = "$Port"
$api = Start-Process -FilePath $py -PassThru -WorkingDirectory $backend `
    -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port")
Ok "backend pid $($api.Id) -> http://127.0.0.1:$Port"

# Wait for the API to answer before opening a browser at it.
$ready = $false
foreach ($i in 1..40) {
    Start-Sleep -Milliseconds 500
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        if ($r.status -eq 'ok') { $ready = $true; break }
    } catch { }
}
if ($ready) {
    Ok 'backend healthy'
    if ($r.rs_model.available) {
        Ok ("RS classifier: held-out accuracy {0:P2}" -f $r.rs_model.test_accuracy)
    } else {
        Warn 'RS classifier not trained - run .\start.ps1 -Setup to add it'
    }
    if (-not $r.llm.available) {
        Ok 'LLM not configured - deterministic rule parser and template narrator in use'
    }
} else {
    Warn 'Backend did not report healthy in 20s; check the window it opened.'
}

$ui = "http://127.0.0.1:$Port/"
if (-not $NoFrontend -and -not $Build) {
    Step 'Starting the frontend dev server'
    $web = Start-Process -FilePath 'npm.cmd' -PassThru -WorkingDirectory $frontend `
        -ArgumentList @('run', 'dev')
    Ok "frontend pid $($web.Id)"
    Start-Sleep -Seconds 4
    $ui = "http://localhost:$FrontendPort/"
}

Write-Host ""
Write-Host "  Console : $ui" -ForegroundColor Green
Write-Host "  API docs: http://127.0.0.1:$Port/docs" -ForegroundColor Green
Write-Host ""
Write-Host "  Press Ctrl+C to stop." -ForegroundColor DarkGray
Start-Process $ui

try {
    Wait-Process -Id $api.Id
} finally {
    Step 'Shutting down'
    foreach ($p in @($api, $web)) {
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
}
