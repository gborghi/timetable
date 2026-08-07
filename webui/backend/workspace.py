"""Workspace helpers: coverage gating and run-directory management.

Moved from optimization.py to reduce monolith size (finding A1)."""

from __future__ import annotations

import os
from collections import defaultdict


def _coverage_strict() -> bool:
    """Whether an incomplete timetable should fail the run (default yes).

    P0 truthfulness: a Phase-B solve that leaves lessons unplaced is a
    partial result, not a success. Set PITANTUM_COVERAGE_STRICT=0 to keep
    the partial solution (marked done) for inspection instead of raising.
    """
    return os.environ.get("PITANTUM_COVERAGE_STRICT", "1").strip().lower() \
        not in ("0", "false", "no", "off")


def _coverage_ratio(full_solution: dict, dc_value: dict | None):
    """placed lessons / hours Phase A said must be placed, or None.

    ``dc_value`` maps (p, cl, subj, day) -> hour-count; its sum is the
    total hours the schedule must contain. ``full_solution`` has one key
    per placed (p, cl, subj, day, hour) cell. Returns None when the
    required total is unknown (dc_value missing/empty) so callers skip
    the gate rather than divide by zero.
    """
    if not dc_value:
        return None
    required = sum(int(v) for v in dc_value.values())
    if required <= 0:
        return None
    placed = sum(1 for v in full_solution.values() if v)
    return placed / required


def _gate_coverage(full_solution: dict, dc_value: dict | None, *,
                   stage: str, metrics: dict) -> None:
    """Record coverage in ``metrics`` and, when strict + incomplete,
    raise so the run is marked failed instead of silently 'done' with a
    partial timetable. Uses a small epsilon to tolerate FP rounding."""
    cov = _coverage_ratio(full_solution, dc_value)
    if cov is None:
        return
    metrics["coverage"] = round(cov, 4)
    if cov < 0.999:
        placed = sum(1 for v in full_solution.values() if v)
        required = sum(int(v) for v in dc_value.values())
        msg = (
            f"{stage}: coverage {cov * 100:.1f}% "
            f"({placed}/{required} ore collocate) < 100%: alcune lezioni "
            "non sono state collocate (giorni/cluster non risolti nel "
            "tempo limite)."
        )
        if _coverage_strict():
            raise RuntimeError(
                msg + " Orario NON valido e non salvato come attivo. "
                "Aumenta i time limit, allenta i vincoli, o imposta "
                "PITANTUM_COVERAGE_STRICT=0 per accettare il parziale."
            )
        print(f"[{stage}][WARN] {msg}")


def _uncovered_report(full_solution: dict,
                      dc_value: dict | None) -> list[dict]:
    """Which cattedre Phase A required but Phase B left (partly) unplaced.

    Turns a bare coverage percentage into the actionable list the audit
    asked for (finding 17): the (class, subject, day, teacher) cells with
    missing hours, worst first. ``dc_value`` maps (p, cl, subj, day) ->
    required hour-count. Returns [] when the required total is unknown.
    """
    if not dc_value:
        return []
    placed: dict[tuple, int] = defaultdict(int)
    for (p, cl, s, d, h), val in full_solution.items():
        if val:
            placed[(p, cl, s, d)] += 1
    out: list[dict] = []
    for key, need in dc_value.items():
        try:
            p, cl, s, d = key
        except Exception:
            continue
        got = placed.get((p, cl, s, d), 0)
        if got < int(need):
            out.append({"class": cl, "subject": s, "day": int(d),
                        "teacher": p, "missing": int(need) - got})
    out.sort(key=lambda r: -r["missing"])
    return out


def _runs_dir() -> str:
    # PITANTUM_RUNS_DIR overrides the default location. Set it to an
    # absolute path outside the source tree when two archive instances
    # share a filesystem or container volume, so they never clobber each
    # other's run files (finding 32). Default: webui/data/runs/&lt;db_hash&gt;.
    env_runs_dir = os.environ.get("PITANTUM_RUNS_DIR")
    if env_runs_dir:
        base = os.path.abspath(os.path.expanduser(env_runs_dir.strip()))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        base = os.path.normpath(os.path.join(here, "..", "data", "runs"))
    # Isolate run work-files per archive: two instances pointed at
    # different databases (PITANTUM_DB_URL) must NOT share a workspace,
    # or they silently overwrite each other's files (finding 32). The
    # run_id is a per-DB autoincrement, so without this namespacing run 7
    # of archive A and run 7 of archive B collide on disk. Namespace by a
    # short stable hash of the resolved DB URL.
    import hashlib
    try:
        from .db import DB_URL
        # Not security-sensitive: just a stable per-DB directory name.
        key = hashlib.sha1(
            DB_URL.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    except Exception:
        key = "default"
    out = os.path.join(base, key)
    os.makedirs(out, exist_ok=True)
    return out


def _run_workspace(run_id: int) -> str:
    p = os.path.join(_runs_dir(), str(run_id))
    os.makedirs(p, exist_ok=True)
    return p
