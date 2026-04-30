#!/usr/bin/env bash
# ============================================================
#  piTantum - launcher (Linux / macOS)
#  "Omnia, Lucili, aliena sunt, tempus tantum nostrum est."
#                                  (Seneca, Ep. I,1)
# ------------------------------------------------------------
#  Avvia in background:
#    - Backend  : uvicorn su  http://127.0.0.1:8000
#    - Frontend : vite    su  http://127.0.0.1:5173
#
#  I log finiscono in webui/logs/{backend,frontend}.log; i PID
#  vengono scritti in webui/logs/pids cosi' `stop.sh` li puo'
#  killare puliti. Se la venv del backend o node_modules mancano
#  vengono creati automaticamente.
#
#  Uso:
#    ./start.sh            # avvia backend + frontend in background
#    ./start.sh --foreground   # avvia entrambi in foreground (Ctrl+C ferma)
#    ./stop.sh             # ferma i processi avviati da start.sh
# ============================================================

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERE="$SCRIPT_DIR"
cd "$HERE"

LOG_DIR="$HERE/logs"
mkdir -p "$LOG_DIR"
PID_FILE="$LOG_DIR/pids"

FOREGROUND=0
for a in "$@"; do
    case "$a" in
        --foreground|-f) FOREGROUND=1 ;;
        --help|-h)
            sed -n '2,18p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
    esac
done

c_red()    { printf '\033[31m%s\033[0m\n' "$*"; }
c_green()  { printf '\033[32m%s\033[0m\n' "$*"; }
c_yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
c_blue()   { printf '\033[34m%s\033[0m\n' "$*"; }

echo
cat <<'BANNER'
============================================================
              _____            _
   _ __ (_) |_   _|_ _ _ __ | |_ _   _ _ __ ___
  | '_ \| |   | |/ _` | '_ \| __| | | | '_ ` _ \
  | |_) | |   | | (_| | | | | |_| |_| | | | | | |
  | .__/|_|   |_|\__,_|_| |_|\__|\__,_|_| |_| |_|
  |_|         "Tempus tantum nostrum est"
------------------------------------------------------------
 "Omnia, Lucili, aliena sunt, tempus tantum nostrum est."
                                       Seneca, Ep. I,1
============================================================
BANNER
echo " Cartella:  $HERE"
echo "============================================================"

# ---------- Pre-flight: python ----------
PYBIN=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PYBIN="$c"; break; fi
done
if [ -z "$PYBIN" ]; then
    c_red "[X] ERRORE: python3 non e' nel PATH."
    echo "    Installa Python 3.11+ dal package manager della tua distro:"
    echo "      Ubuntu/Debian:   sudo apt install python3 python3-venv python3-pip"
    echo "      Fedora/RHEL:     sudo dnf install python3 python3-pip"
    echo "      Arch:            sudo pacman -S python python-pip"
    echo "      macOS:           brew install python"
    exit 1
fi

# ---------- Pre-flight: node + npm ----------
if ! command -v npm >/dev/null 2>&1; then
    c_red "[X] ERRORE: npm non e' nel PATH."
    echo "    Installa Node.js LTS:"
    echo "      Ubuntu/Debian:   sudo apt install nodejs npm"
    echo "      Fedora/RHEL:     sudo dnf install nodejs npm"
    echo "      Arch:            sudo pacman -S nodejs npm"
    echo "      macOS:           brew install node"
    echo "      Universale:      https://nodejs.org/en/download"
    exit 1
fi

# ---------- File presence ----------
if [ ! -f "$HERE/backend/main.py" ]; then
    c_red "[X] ERRORE: backend/main.py mancante. Cartella corrotta?"; exit 1
fi
if [ ! -f "$HERE/frontend/package.json" ]; then
    c_red "[X] ERRORE: frontend/package.json mancante. Cartella corrotta?"; exit 1
fi

# ---------- Backend venv ----------
VENV_PY="$HERE/backend/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
    c_yellow "[!] venv backend assente: la creo ora ($PYBIN -m venv backend/.venv)..."
    if ! "$PYBIN" -m venv "$HERE/backend/.venv"; then
        c_red "[X] ERRORE: creazione venv fallita."
        echo "    Su Debian/Ubuntu: sudo apt install python3-venv"
        exit 1
    fi
    c_yellow "[!] Installo requirements (~90 MB, 1-3 min)..."
    if ! "$VENV_PY" -m pip install --upgrade pip >>"$LOG_DIR/pip.log" 2>&1; then
        c_red "[X] ERRORE: pip upgrade fallito (vedi logs/pip.log)."; exit 1
    fi
    if ! "$VENV_PY" -m pip install -r "$HERE/backend/requirements.txt" \
            >>"$LOG_DIR/pip.log" 2>&1; then
        c_red "[X] ERRORE: pip install fallito (vedi logs/pip.log)."; exit 1
    fi
    c_green "[OK] venv pronto."
fi

# ---------- Frontend node_modules ----------
if [ ! -d "$HERE/frontend/node_modules" ]; then
    c_yellow "[!] node_modules assente: lancio 'npm install' (scarica ~150 MB, 2-4 min)..."
    pushd "$HERE/frontend" >/dev/null
    if ! npm install >>"$LOG_DIR/npm-install.log" 2>&1; then
        popd >/dev/null
        c_red "[X] ERRORE: npm install fallito (vedi logs/npm-install.log)."
        exit 1
    fi
    popd >/dev/null
    c_green "[OK] node_modules pronto."
fi

# ---------- Port check ----------
port_in_use() {
    local p="$1"
    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"$p" -sTCP:LISTEN -t >/dev/null 2>&1
    elif command -v ss >/dev/null 2>&1; then
        ss -tln "( sport = :$p )" 2>/dev/null | tail -n +2 | grep -q .
    elif command -v netstat >/dev/null 2>&1; then
        netstat -tln 2>/dev/null | awk '{print $4}' | grep -q ":$p$"
    else
        return 1   # nessun tool disponibile, assumiamo libera
    fi
}

if port_in_use 8000; then
    c_yellow "[!] AVVISO: la porta 8000 e' gia' in uso. Il backend potrebbe non partire."
fi
if port_in_use 5173; then
    c_yellow "[!] AVVISO: la porta 5173 e' gia' in uso. Vite potrebbe scegliere un'altra porta."
fi

# ---------- Spawn ----------
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
: > "$BACKEND_LOG"
: > "$FRONTEND_LOG"

start_backend() {
    cd "$HERE"
    exec "$VENV_PY" -m uvicorn backend.main:app \
        --host 127.0.0.1 --port 8000
}
start_frontend() {
    cd "$HERE/frontend"
    exec npm run dev
}

if [ "$FOREGROUND" -eq 1 ]; then
    echo
    c_blue "Foreground mode: Ctrl+C ferma entrambi i processi."
    # Run both via a tiny supervisor that traps INT/TERM and kills the
    # children cleanly.
    ( start_backend ) &
    BPID=$!
    ( start_frontend ) &
    FPID=$!
    cleanup() {
        echo
        c_yellow "Ricevuto segnale di stop, killo backend ($BPID) e frontend ($FPID)..."
        kill "$BPID" "$FPID" 2>/dev/null || true
        wait "$BPID" "$FPID" 2>/dev/null || true
        exit 0
    }
    trap cleanup INT TERM
    echo
    c_green "Backend  -> http://127.0.0.1:8000/api/health   (PID $BPID)"
    c_green "Frontend -> http://127.0.0.1:5173              (PID $FPID)"
    echo
    echo "Aspetta ~10 secondi che entrambi siano pronti, poi apri"
    echo "http://127.0.0.1:5173 nel browser."
    wait
    exit 0
fi

# Background mode
nohup bash -c "
    cd '$HERE'
    exec '$VENV_PY' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
" >>"$BACKEND_LOG" 2>&1 &
BPID=$!

nohup bash -c "
    cd '$HERE/frontend'
    exec npm run dev
" >>"$FRONTEND_LOG" 2>&1 &
FPID=$!

# write PIDs for stop.sh
{ echo "BACKEND_PID=$BPID"; echo "FRONTEND_PID=$FPID"; } > "$PID_FILE"

# Detach so closing the terminal doesn't kill them
disown "$BPID" 2>/dev/null || true
disown "$FPID" 2>/dev/null || true

echo
echo "============================================================"
c_green " Server avviati in background."
echo
c_blue   "   Backend  -> http://127.0.0.1:8000/api/health   (PID $BPID)"
c_blue   "   Frontend -> http://127.0.0.1:5173              (PID $FPID)"
echo
echo " Logs:"
echo "    tail -f $BACKEND_LOG"
echo "    tail -f $FRONTEND_LOG"
echo
echo " Per fermare:"
echo "    ./stop.sh         # ferma i processi avviati da questo script"
echo "    oppure manualmente: kill $BPID $FPID"
echo "============================================================"
echo
echo "Aspetta ~10 secondi che entrambi siano pronti, poi apri"
echo "http://127.0.0.1:5173 nel browser."
