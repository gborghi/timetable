#!/usr/bin/env bash
# check_refs.sh -- audit dangling references and missing citations
# in docs/manual.pdf.
#
# Compiles the manual through the standard pipeline (lualatex +
# biber + makeindex + lualatex x2) capturing the verbose log,
# then greps for undefined refs and missing citations and prints
# a summary. Exit non-zero if any are found, so the script can
# be used in CI / pre-commit.
#
# Usage:
#   scripts/check_refs.sh
set -euo pipefail
cd "$(dirname "$0")/.."

JOB="manual"
DOCS=docs

cd "$DOCS"

LOG=/tmp/${JOB}_refs.log

lualatex -interaction=nonstopmode -file-line-error "$JOB.tex" \
    > /tmp/pass1.log 2>&1 || true
biber "$JOB" > /dev/null 2>&1 || true
[[ -f "$JOB.idx" ]] && makeindex "$JOB.idx" > /dev/null 2>&1 || true
lualatex -interaction=nonstopmode -file-line-error "$JOB.tex" \
    > /tmp/pass2.log 2>&1 || true
lualatex -interaction=nonstopmode -file-line-error "$JOB.tex" \
    > "$LOG" 2>&1 || true

echo "[check_refs] scanning $LOG"

UNDEF_REFS=$(grep -E "Warning: Reference \`[^']+' on page" "$LOG" \
    | sed -E "s/.*Reference \`([^']+)'.*/\1/" \
    | sort -u || true)

UNDEF_CITES=$(grep -E "Warning: Citation \`[^']+' on page" "$LOG" \
    | sed -E "s/.*Citation \`([^']+)'.*/\1/" \
    | sort -u || true)

NREFS=$(echo -n "$UNDEF_REFS" | grep -c . || true)
NCITES=$(echo -n "$UNDEF_CITES" | grep -c . || true)

if [[ -n "$UNDEF_REFS" ]]; then
  echo
  echo "Undefined references ($NREFS):"
  echo "$UNDEF_REFS" | sed 's/^/  /'
fi
if [[ -n "$UNDEF_CITES" ]]; then
  echo
  echo "Undefined citations ($NCITES):"
  echo "$UNDEF_CITES" | sed 's/^/  /'
fi

# Cleanup intermediate compilation artefacts (PDF stays).
rm -f "${JOB}".{aux,log,toc,out,bcf,run.xml,idx,ind,ilg,bbl,blg,lof,lot} \
      "${JOB}"-blx.bib

if [[ "$NREFS" -eq 0 && "$NCITES" -eq 0 ]]; then
  echo "[check_refs] OK -- no dangling references or missing citations."
  exit 0
fi

echo
echo "[check_refs] FAILED -- $NREFS refs + $NCITES cites need fixing."
exit 1
