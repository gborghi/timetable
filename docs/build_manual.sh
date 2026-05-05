#!/usr/bin/env bash
# Build BOTH PDF manuals using lualatex + biber + makeindex.
#
# Output (in docs/):
#   manual.pdf    -- Italian edition (canonical, fuller text)
#   manual_en.pdf -- English edition (parallel structure;
#                    chapters that have a full translation are
#                    fully rendered, the others carry an English
#                    summary pointing to the IT chapter)
#
# Usage:
#   docs/build_manual.sh                  # full build of both
#   docs/build_manual.sh --quick          # single lualatex pass
#                                           (no biblio/index update)
#   docs/build_manual.sh --it             # build only the IT PDF
#   docs/build_manual.sh --en             # build only the EN PDF
set -euo pipefail
cd "$(dirname "$0")"

QUICK=0
ONLY_IT=0
ONLY_EN=0
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=1 ;;
    --it)    ONLY_IT=1 ;;
    --en)    ONLY_EN=1 ;;
    *) echo "[manual] unknown arg: $arg" >&2 ;;
  esac
done

build_one () {
  local JOB="$1"
  local TEX="${JOB}.tex"
  if [[ ! -f "$TEX" ]]; then
    echo "[manual] $TEX not found, skip"
    return
  fi
  echo "[manual] === $JOB ==="
  lualatex -interaction=nonstopmode -halt-on-error "$TEX" >/dev/null \
      || { echo "[manual] $JOB pass 1 FAILED"; return 1; }
  if [[ "$QUICK" -eq 0 ]]; then
    [[ -f "${JOB}.bcf" ]] && biber "$JOB" >/dev/null || true
    [[ -f "${JOB}.idx" ]] && makeindex "${JOB}.idx" >/dev/null || true
    lualatex -interaction=nonstopmode -halt-on-error "$TEX" >/dev/null
    lualatex -interaction=nonstopmode -halt-on-error "$TEX" >/dev/null
  fi
  # Cleanup intermediate artefacts (keep .aux + .bbl for quick rebuilds).
  rm -f "${JOB}".{log,toc,out,bcf,run.xml,idx,ind,ilg,blg,lof,lot} \
        "${JOB}"-blx.bib
  if [[ -f "${JOB}.pdf" ]]; then
    local sz
    sz=$(wc -c < "${JOB}.pdf")
    echo "[manual] $JOB.pdf done ($sz bytes)"
  fi
}

if [[ "$ONLY_EN" -eq 1 ]]; then
  build_one "manual_en"
elif [[ "$ONLY_IT" -eq 1 ]]; then
  build_one "manual"
else
  build_one "manual"
  build_one "manual_en"
fi

echo "[manual] OK"
