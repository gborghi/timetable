#!/usr/bin/env bash
# Build the three PDF manuals using lualatex + biber + makeindex.
#
# Outputs (all in docs/):
#   manual_generale.pdf    Parte I  -- per coordinatori d'orario
#   appendici_tecniche.pdf Parte II -- per sviluppatori
#   manual_completo.pdf    entrambe le parti in un unico volume
#
# Usage:
#   docs/build_manual.sh           # build all 3 PDFs (lualatex x2 each)
#   docs/build_manual.sh --quick   # single lualatex pass per PDF
#   docs/build_manual.sh <name>    # build only one
set -euo pipefail
cd "$(dirname "$0")"

QUICK=0
PICK=""
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=1 ;;
    manual_generale|appendici_tecniche|manual_completo) PICK="$arg" ;;
    *) echo "[manual] unknown arg: $arg" >&2 ;;
  esac
done

build_one() {
  local job="$1"
  local tex="${job}.tex"
  if [[ ! -f "$tex" ]]; then
    echo "[manual] missing $tex, skipping"
    return
  fi
  echo "[manual] === $job ==="
  lualatex -interaction=nonstopmode -halt-on-error "$tex" >/dev/null \
      || { echo "[manual] $job pass 1 FAILED"; return 1; }
  if [[ "$QUICK" -eq 0 ]]; then
    [[ -f "${job}.bcf" ]] && biber "$job" >/dev/null || true
    [[ -f "${job}.idx" ]] && makeindex "${job}.idx" >/dev/null || true
    lualatex -interaction=nonstopmode -halt-on-error "$tex" >/dev/null
    lualatex -interaction=nonstopmode -halt-on-error "$tex" >/dev/null
  fi
  # Cleanup
  rm -f "${job}".{aux,log,toc,out,bcf,run.xml,idx,ind,ilg,bbl,blg,lof,lot} \
        "${job}"-blx.bib
  if [[ -f "${job}.pdf" ]]; then
    local sz=$(wc -c < "${job}.pdf")
    echo "[manual] $job -> $job.pdf ($sz bytes)"
  fi
}

if [[ -n "$PICK" ]]; then
  build_one "$PICK"
else
  build_one manual_generale
  build_one appendici_tecniche
  build_one manual_completo
fi

echo "[manual] OK"
