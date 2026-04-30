@echo off
REM ============================================================
REM  piTantum - launcher (Windows)
REM  "Omnia, Lucili, aliena sunt, tempus tantum nostrum est."
REM                            (Seneca, Ep. I,1)
REM ------------------------------------------------------------
REM  Apre due finestre cmd visibili e separate:
REM    - Backend  : uvicorn su  http://127.0.0.1:8000
REM    - Frontend : vite    su  http://127.0.0.1:5173
REM
REM  Le finestre figlie restano aperte (cmd /k). Se uno dei due
REM  processi muore vedi l'errore in finestra. Ctrl+C in ciascuna
REM  per fermarle, oppure chiudi le finestre.
REM ============================================================

setlocal EnableExtensions EnableDelayedExpansion

set "HERE=%~dp0"
REM trim trailing backslash
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

echo.
echo ============================================================
echo                _____            _
echo      _ __ (_) ^|_   _^|_ _ _ __ ^| ^|_ _   _ _ __ ___
echo     ^| '_ \^| ^|   ^| ^|/ _` ^| '_ \^| __^| ^| ^| ^| '_ ` _ \
echo     ^| ^|_^) ^| ^|   ^| ^| ^(_^| ^| ^| ^| ^| ^|_^| ^|_^| ^| ^| ^| ^| ^| ^|
echo     ^| .__/^|_^|   ^|_^|\__,_^|_^| ^|_^|\__^|\__,_^|_^| ^|_^| ^|_^|
echo     ^|_^|         "Tempus tantum nostrum est"
echo ------------------------------------------------------------
echo  "Omnia, Lucili, aliena sunt, tempus tantum nostrum est."
echo                                       Seneca, Ep. I,1
echo ============================================================
echo  Cartella:  %HERE%
echo ============================================================

REM Forziamo nel PATH di QUESTA cmd la cartella nodejs standard,
REM in modo che lo script funzioni anche se Esplora Risorse era
REM aperto prima dell'installazione di Node (nuovi processi cmd
REM avviati da Esplora Risorse vecchio non hanno il PATH fresco).
if exist "%ProgramFiles%\nodejs\npm.cmd" set "PATH=%ProgramFiles%\nodejs;%PATH%"
if exist "%ProgramFiles(x86)%\nodejs\npm.cmd" set "PATH=%ProgramFiles(x86)%\nodejs;%PATH%"
if exist "%LOCALAPPDATA%\Programs\nodejs\npm.cmd" set "PATH=%LOCALAPPDATA%\Programs\nodejs;%PATH%"

REM --- Pre-flight: Node + Python venv ---
where /Q npm
if errorlevel 1 (
    echo.
    echo  [X] ERRORE: npm non e' raggiungibile.
    echo      Node.js non risulta installato (oppure non e' nel PATH^).
    echo.
    echo      Installa la versione LTS da:
    echo          https://nodejs.org/en/download
    echo      Poi CHIUDI completamente Esplora Risorse e questa
    echo      finestra, riapri Esplora Risorse e rilancia start.bat.
    echo.
    pause
    exit /b 1
)

if not exist "%HERE%\backend\.venv\Scripts\python.exe" (
    echo.
    echo  [X] ERRORE: il venv del backend non esiste.
    echo      Aspettato:  %HERE%\backend\.venv\Scripts\python.exe
    echo.
    echo      Crealo con:
    echo          cd "%HERE%\backend"
    echo          python -m venv .venv
    echo          .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "%HERE%\backend\main.py" (
    echo.
    echo  [X] ERRORE: backend\main.py mancante. Cartella corrotta?
    echo      Controlla che il sync Dropbox sia completo.
    echo.
    pause
    exit /b 1
)

if not exist "%HERE%\frontend\package.json" (
    echo.
    echo  [X] ERRORE: frontend\package.json mancante. Cartella corrotta?
    echo.
    pause
    exit /b 1
)

if not exist "%HERE%\frontend\node_modules" (
    echo.
    echo  [!] node_modules assente. Lancio "npm install" la prima volta.
    echo      Scarica circa 150 MB; richiede 2-4 minuti.
    echo.
    pushd "%HERE%\frontend"
    call npm install
    set "NPM_RC=!ERRORLEVEL!"
    popd
    if not "!NPM_RC!"=="0" (
        echo.
        echo  [X] ERRORE durante npm install (exit code !NPM_RC!^).
        echo      Controlla la connessione e riprova.
        pause
        exit /b 1
    )
)

REM --- Check porte gia' occupate ---
netstat -ano -p tcp | find "127.0.0.1:8000" | find "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo  [!] AVVISO: la porta 8000 e' gia' in uso.
    echo      Chiudi l'altro processo prima di rilanciare il backend,
    echo      oppure modifica la porta nei comandi qui sotto.
    echo.
)
netstat -ano -p tcp | find "127.0.0.1:5173" | find "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo  [!] AVVISO: la porta 5173 e' gia' in uso (Vite gia' attivo?^).
    echo.
)

REM --- Avvio backend e frontend in due finestre separate ---
echo.
echo  Avvio backend Uvicorn  (porta 8000)...
start "piTantum - backend" cmd /k "cd /d ""%HERE%"" && backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"

echo  Avvio frontend Vite    (porta 5173)...
start "piTantum - frontend" cmd /k "cd /d ""%HERE%\frontend"" && npm run dev"

echo.
echo ============================================================
echo  Server avviati in due finestre separate.
echo.
echo    Backend  ^>  http://127.0.0.1:8000/api/health
echo    Frontend ^>  http://127.0.0.1:5173
echo.
echo  Aspetta ~10 secondi che entrambi siano pronti, poi apri
echo  http://127.0.0.1:5173 nel browser.
echo.
echo  Per fermare:
echo    - chiudi le due finestre cmd "piTantum - backend" e
echo      "piTantum - frontend", oppure
echo    - premi Ctrl+C in ciascuna.
echo ============================================================
echo.
echo Premi un tasto per chiudere SOLO questa finestra di lancio.
echo (le due finestre con i server resteranno attive)
pause >nul
endlocal
