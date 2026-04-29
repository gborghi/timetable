# ============================================================
#  Timetable WebUI - launcher (PowerShell)
# ------------------------------------------------------------
#  Apre due finestre PowerShell separate per backend e frontend,
#  con echo iniziale di startup. Le finestre figlie restano
#  aperte (-NoExit) cosi' vedi i log e gli eventuali errori.
# ============================================================

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Timetable WebUI launcher" -ForegroundColor Cyan
Write-Host (" Cartella:  {0}" -f $here)
Write-Host "============================================================" -ForegroundColor Cyan

# Aggiungi al PATH di questa sessione la cartella nodejs standard,
# in modo da gestire il caso "Esplora Risorse aperto prima
# dell'installazione di Node".
$nodeCandidates = @(
    "$env:ProgramFiles\nodejs",
    "${env:ProgramFiles(x86)}\nodejs",
    "$env:LOCALAPPDATA\Programs\nodejs"
)
foreach ($c in $nodeCandidates) {
    if (Test-Path "$c\npm.cmd") {
        $env:PATH = "$c;$env:PATH"
        break
    }
}

function Fail($msg) {
    Write-Host ""
    Write-Host " [X] $msg" -ForegroundColor Red
    Write-Host ""
    Read-Host "Premi INVIO per uscire"
    exit 1
}

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    Fail "npm non raggiungibile. Installa Node.js LTS da https://nodejs.org/en/download e riapri questa finestra."
}

if (-not (Test-Path "$here\backend\.venv\Scripts\python.exe")) {
    Fail ("venv backend non trovato. Crealo con:`n" +
          "    cd $here\backend; python -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt")
}

if (-not (Test-Path "$here\backend\main.py")) { Fail "backend\main.py mancante (sync Dropbox incompleto?)" }
if (-not (Test-Path "$here\frontend\package.json")) { Fail "frontend\package.json mancante (sync Dropbox incompleto?)" }

if (-not (Test-Path "$here\frontend\node_modules")) {
    Write-Host " [!] node_modules assente. Lancio npm install (2-4 min)..." -ForegroundColor Yellow
    Push-Location "$here\frontend"
    & npm.cmd install
    $rc = $LASTEXITCODE
    Pop-Location
    if ($rc -ne 0) { Fail "npm install fallito (exit $rc)." }
}

# Avviso porte gia' in uso
foreach ($port in 8000, 5173) {
    $busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($busy) {
        Write-Host " [!] AVVISO: porta $port gia' in ascolto (PID $($busy.OwningProcess[0]))." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host " Avvio backend Uvicorn  (porta 8000)..."
$beCmd = "Set-Location '$here'; & '$here\backend\.venv\Scripts\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"
Start-Process -FilePath "powershell.exe" -WorkingDirectory $here `
    -ArgumentList "-NoExit", "-Command", $beCmd -WindowStyle Normal | Out-Null

Write-Host " Avvio frontend Vite    (porta 5173)..."
$feCmd = "Set-Location '$here\frontend'; npm.cmd run dev"
Start-Process -FilePath "powershell.exe" -WorkingDirectory "$here\frontend" `
    -ArgumentList "-NoExit", "-Command", $feCmd -WindowStyle Normal | Out-Null

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Server avviati in due finestre separate." -ForegroundColor Green
Write-Host ""
Write-Host "   Backend  >  http://127.0.0.1:8000/api/health"
Write-Host "   Frontend >  http://127.0.0.1:5173"
Write-Host ""
Write-Host " Aspetta ~10 secondi che entrambi siano pronti, poi apri"
Write-Host " http://127.0.0.1:5173 nel browser."
Write-Host ""
Write-Host " Per fermare: chiudi le due finestre figlie, o Ctrl+C."
Write-Host "============================================================"
Write-Host ""
Read-Host "Premi INVIO per chiudere SOLO questa finestra di lancio (le due finestre con i server restano attive)"
