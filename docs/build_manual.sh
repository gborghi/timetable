#!/usr/bin/env bash
# Build the unified PDF manual using lualatex + biber + makeindex.
#
# Output (in docs/):
#   manual.pdf -- monografia unica, capitoli numerati progressivamente
#
# Usage:
#   docs/build_manual.sh           # full build (lualatex x3 + biber + makeindex)
#   docs/build_manual.sh --quick   # single lualatex pass (no biblio/index update)
set -euo pipefail
cd "$(dirname "$0")"

QUICK=0
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=1 ;;
    *) echo "[manual] unknown arg: $arg" >&2 ;;
  esac
done

JOB="manual"
TEX="${JOB}.tex"

if [[ ! -f "$TEX" ]]; then
  echo "[manual] $TEX not found"
  exit 1
fi

echo "[manual] === $JOB ==="
lualatex -interaction=nonstopmode -halt-on-error "$TEX" >/dev/null \
    || { echo "[manual] $JOB pass 1 FAILED"; exit 1; }
if [[ "$QUICK" -eq 0 ]]; then
  [[ -f "${JOB}.bcf" ]] && biber "$JOB" >/dev/null || true
  [[ -f "${JOB}.idx" ]] && makeindex "${JOB}.idx" >/dev/null || true
  lualatex -interaction=nonstopmode -halt-on-error "$TEX" >/dev/null
  lualatex -interaction=nonstopmode -halt-on-error "$TEX" >/dev/null
fi

# Cleanup intermediate artefacts (PDF stays). We keep .aux + .bbl
# so a subsequent quick `lualatex manual.tex` (without biber) still
# resolves citations -- nuking them was confusing users who edited
# a chapter and re-ran lualatex by hand.
rm -f "${JOB}".{log,toc,out,bcf,run.xml,idx,ind,ilg,blg,lof,lot} \
      "${JOB}"-blx.bib

if [[ -f "${JOB}.pdf" ]]; then
  sz=$(wc -c < "${JOB}.pdf")
  echo "[manual] $JOB.pdf done ($sz bytes)"
fi
echo "[manual] OK"
