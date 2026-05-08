#!/usr/bin/env bash
# Rebuild every mock-school profile (school_<name>.pkl + profs_<name>.pkl)
# under engine/scripts/data/<profile>/ so the dashboard's "Importa modelli
# risolti" dropdown is no longer empty for non-mega profiles.
#
# Bash equivalent of scripts/rebuild_profiles.ps1 -- same flag set,
# same output layout, same gitignored-by-default pickles. Use this on
# Linux / macOS / Git Bash on Windows.
#
# Usage (from the repo root):
#     ./scripts/rebuild_profiles.sh
#     ./scripts/rebuild_profiles.sh --profiles small,medium
#     ./scripts/rebuild_profiles.sh --assignment-time 30 --skip-existing
#
# Environment overrides also work and take precedence over flag
# defaults: PYTHON, ASSIGNMENT_TIME, ASSIGNMENT_WORKERS.
#
# See scripts/README.md for context.
set -euo pipefail

profiles="small,medium,big,huge,superhuge"
assignment_time="${ASSIGNMENT_TIME:-60}"
assignment_workers="${ASSIGNMENT_WORKERS:-8}"
python_exe="${PYTHON:-python}"
skip_existing=0

while [ $# -gt 0 ]; do
    case "$1" in
        -p|--profiles)
            profiles="$2"; shift 2 ;;
        -t|--assignment-time)
            assignment_time="$2"; shift 2 ;;
        -w|--assignment-workers)
            assignment_workers="$2"; shift 2 ;;
        --python)
            python_exe="$2"; shift 2 ;;
        --skip-existing)
            skip_existing=1; shift ;;
        -h|--help)
            sed -n '1,18p' "$0"; exit 0 ;;
        *)
            # Backwards-compat: positional profile names.
            profiles="$1"
            shift
            while [ $# -gt 0 ]; do
                profiles="$profiles,$1"
                shift
            done
            ;;
    esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
engine_dir="$repo_root/engine"
data_dir="$repo_root/engine/scripts/data"
mkdir -p "$data_dir"

echo
echo "[rebuild] repo root:  $repo_root"
echo "[rebuild] engine dir: $engine_dir"
echo "[rebuild] data dir:   $data_dir"
echo "[rebuild] profiles:   $profiles"
echo

IFS=',' read -ra profile_list <<< "$profiles"
for profile in "${profile_list[@]}"; do
    profile="${profile// /}"
    [ -z "$profile" ] && continue
    profile_dir="$data_dir/$profile"
    mkdir -p "$profile_dir"
    school_pkl="$profile_dir/school_${profile}.pkl"
    profs_pkl="$profile_dir/profs_${profile}.pkl"

    if [ "$skip_existing" = "1" ] \
            && [ -f "$school_pkl" ] && [ -f "$profs_pkl" ]; then
        echo "[$profile] SKIP (both pickles already exist)"
        continue
    fi

    echo "============================================================"
    echo "[$profile] step 1/2 - big_mock_school -> $school_pkl"
    echo "============================================================"
    "$python_exe" "$engine_dir/big_mock_school.py" \
        --profile "$profile" --out "$school_pkl"

    echo
    echo "============================================================"
    echo "[$profile] step 2/2 - cpsat_v2_assignment -> $profs_pkl"
    echo "============================================================"
    "$python_exe" "$engine_dir/cpsat_v2_assignment.py" \
        --school "$school_pkl" --out "$profs_pkl" \
        --time "$assignment_time" \
        --workers "$assignment_workers" \
        --no-log

    s_size=$(stat -c%s "$school_pkl" 2>/dev/null || stat -f%z "$school_pkl")
    p_size=$(stat -c%s "$profs_pkl" 2>/dev/null || stat -f%z "$profs_pkl")
    echo
    s_kb=$(awk "BEGIN{printf \"%.1f\", $s_size/1024}")
    p_kb=$(awk "BEGIN{printf \"%.1f\", $p_size/1024}")
    echo "[$profile] OK  school=${s_kb}KB  profs=${p_kb}KB"
    echo
done

echo
echo "[rebuild] done. Files:"
find "$data_dir" -name '*.pkl' -print | sort | while read -r f; do
    rel="${f#$repo_root/}"
    sz=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f")
    printf "  %-60s  %8d bytes\n" "$rel" "$sz"
done
