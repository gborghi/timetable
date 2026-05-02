#!/usr/bin/env bash
# Build docs/manual.pdf using the lualatex + biber + makeindex + lualatex x2
# pipeline. ASCII pure in manual.tex. Run from anywhere; the script cd's to
# its own directory first.
#
# Usage:
#   docs/build_manual.sh           # build, with all aux/bib indexing passes
#   docs/build_manual.sh --quick   # single lualatex pass (skip biber + index)
#
# Outputs: docs/manual.pdf
set -euo pipefail

cd "$(dirname "$0")"

QUICK=0
if [[ "${1:-}" == "--quick" ]]; then
  QUICK=1
fi

JOB=manual
TEX=manual.tex

echo "[manual] pass 1: lualatex"
lualatex -interaction=nonstopmode -halt-on-error "$TEX" >/dev/null

if [[ "$QUICK" -eq 0 ]]; then
  if [[ -f "$JOB.bcf" ]]; then
    echo "[manual] biber"
    biber "$JOB" >/dev/null || true
  fi
  if [[ -f "$JOB.idx" ]]; then
    echo "[manual] makeindex"
    makeindex "$JOB.idx" >/dev/null || true
  fi
  echo "[manual] pass 2: lualatex"
  lualatex -interaction=nonstopmode -halt-on-error "$TEX" >/dev/null
  echo "[manual] pass 3: lualatex"
  lualatex -interaction=nonstopmode -halt-on-error "$TEX" >/dev/null
fi

echo "[manual] cleaning aux files"
rm -f "$JOB".{aux,log,toc,out,bcf,run.xml,idx,ind,ilg,bbl,blg,lof,lot} \
       "$JOB"-blx.bib

echo "[manual] OK -> docs/manual.pdf"
