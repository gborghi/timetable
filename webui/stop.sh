#!/usr/bin/env bash
# Ferma il backend e il frontend avviati da start.sh.
# Legge i PID da webui/logs/pids; in fallback cerca i processi su porta
# 8000 (uvicorn backend.main:app) e 5173 (vite dev).

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERE="$SCRIPT_DIR"
PID_FILE="$HERE/logs/pids"

c_yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
c_green()  { printf '\033[32m%s\033[0m\n' "$*"; }
c_red()    { printf '\033[31m%s\033[0m\n' "$*"; }

stopped_any=0

stop_pid() {
    local pid="$1" label="$2"
    if [ -z "$pid" ]; then return; fi
    if ! kill -0 "$pid" 2>/dev/null; then
        c_yellow "[!] $label PID $pid non in esecuzione."
        return
    fi
    # Try clean SIGTERM first; if still alive after 3s, SIGKILL the
    # whole process tree (uvicorn spawns a worker, npm spawns vite).
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
    for i in 1 2 3; do
        sleep 1
        if ! kill -0 "$pid" 2>/dev/null; then
            c_green "[OK] $label fermato (PID $pid)."
            stopped_any=1
            return
        fi
    done
    c_yellow "[!] $label PID $pid non risponde a SIGTERM, mando SIGKILL."
    pkill -KILL -P "$pid" 2>/dev/null || true
    kill -KILL "$pid" 2>/dev/null || true
    c_green "[OK] $label fermato (PID $pid, SIGKILL)."
    stopped_any=1
}

if [ -f "$PID_FILE" ]; then
    BACKEND_PID=""
    FRONTEND_PID=""
    # shellcheck disable=SC1090
    . "$PID_FILE"
    stop_pid "${BACKEND_PID:-}"  "Backend"
    stop_pid "${FRONTEND_PID:-}" "Frontend"
    rm -f "$PID_FILE"
fi

# Fallback: kill anything still listening on the two well-known ports.
fallback_kill_port() {
    local port="$1" label="$2"
    if command -v lsof >/dev/null 2>&1; then
        local pids
        pids=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)
        if [ -n "$pids" ]; then
            c_yellow "[!] Trovato processo residuo su porta $port ($label): $pids"
            for p in $pids; do stop_pid "$p" "$label (porta $port)"; done
        fi
    fi
}
fallback_kill_port 8000 "Backend"
fallback_kill_port 5173 "Frontend"

if [ "$stopped_any" -eq 0 ]; then
    c_yellow "Nessun processo Timetable risultava attivo."
fi
