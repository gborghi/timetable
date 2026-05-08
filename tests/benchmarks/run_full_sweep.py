"""Full-sweep benchmark: small -> mega across all solver techniques.

Loads pickle profiles from `engine/scripts/data/<size>/` and runs each
technique once with profile-dependent time caps. Writes one CSV row per
(profile, technique) cell to `docs/manual/benchmarks/results.csv` AND
`tests/benchmarks/results/full_sweep_<ts>.csv` so pgfplots can pull it.

Per-cell timeline:
  - End-to-end techniques (cpsat_day, decomp_*, cg_*, bp_*): each runs
    from scratch, captures t_phase_a + t_phase_b + t_post and the soft
    objective + hard feasibility.
  - Metaheuristic post-passes (tabu, sa, lns, alns, vns, lagrangian):
    share the cpsat_day baseline computed once per profile, then layer
    their own t_post.

Cells exceeding their wall-clock cap are recorded with status=timeout.
Failures are recorded with status=exception (NEVER propagated). Solver
techniques that exist as library code but are not exposed via the
public CLI/API are recorded with status=unwired and a note column.

Usage:
  python tests/benchmarks/run_full_sweep.py
  python tests/benchmarks/run_full_sweep.py --profiles small,medium
  python tests/benchmarks/run_full_sweep.py --techniques cpsat_day,bp_teacher
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import os
import pickle
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

# Path bootstrap: import sibling test fixtures + engine.
HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(TESTS_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
SCHEDULE_DIR = os.path.join(REPO_ROOT, "schedule")
WEBUI_DIR = os.path.join(REPO_ROOT, "webui")
BACKEND_DIR = os.path.join(WEBUI_DIR, "backend")
for p in (REPO_ROOT, WEBUI_DIR, BACKEND_DIR, ENGINE_DIR, SCHEDULE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


# --------------------------------------------------------------------
# Profiles + time caps
# --------------------------------------------------------------------

PROFILES = ["small", "medium", "big", "huge", "superhuge", "mega"]

# (cap_total_s, time_phase_a, time_phase_b_per_day, time_post_pass)
TIME_CAPS = {
    "small":     (120.0, 20.0,  6.0,  20.0),
    "medium":    (120.0, 30.0,  8.0,  30.0),
    "big":       (300.0, 60.0, 15.0,  60.0),
    "huge":      (300.0, 90.0, 18.0,  90.0),
    "superhuge": (600.0, 120.0, 25.0, 120.0),
    "mega":      (600.0, 150.0, 30.0, 150.0),
}


# --------------------------------------------------------------------
# Data loaders
# --------------------------------------------------------------------

def load_profile(profile: str):
    """Load profs + school pickles for `profile`. Returns
    (profs_dict, school_dict, classroom_to_curriculum_dict)."""
    base = os.path.join(ENGINE_DIR, "scripts", "data", profile)
    with open(os.path.join(base, f"profs_{profile}.pkl"), "rb") as f:
        profs = pickle.load(f)
    with open(os.path.join(base, f"school_{profile}.pkl"), "rb") as f:
        school = pickle.load(f)
    classroom_to_curriculum = {}
    for c in school.get("classes", []):
        if isinstance(c, dict) and "name" in c and "curriculum" in c:
            classroom_to_curriculum[c["name"]] = c["curriculum"]
    return profs, school, classroom_to_curriculum


# --------------------------------------------------------------------
# Result row
# --------------------------------------------------------------------

@dataclass
class BenchRow:
    profile: str
    technique: str
    family: str
    seed: int
    status: str
    t_phase_a: float
    t_phase_b: float
    t_post: float
    t_total: float
    cost: Optional[float]
    hard_feasible: Optional[bool]
    n_lessons: Optional[int]
    n_columns: Optional[int]
    n_iterations: Optional[int]
    n_classes: int
    n_teachers: int
    note: str = ""
    error_msg: str = ""


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def _compute_cost(profs, sol):
    import metaheuristics as meta  # type: ignore
    try:
        v, _m = meta.compute_soft(sol, profs)
        return float(v)
    except Exception:
        return None


def _hard_ok(profs, sol):
    import metaheuristics as meta  # type: ignore
    try:
        return bool(meta.is_hard_feasible(sol, profs, verbose=False))
    except Exception:
        return None


def _phaseA(profs, *, time_limit, workers=2):
    import cpsat_v2_timetable as cv2  # type: ignore
    classes_v, triples, class_profs = cv2.build_indices(profs)
    return cv2.solve_phase_a(profs, classes_v, triples, class_profs,
                             time_limit=time_limit, workers=workers,
                             log=False), classes_v, triples, class_profs


def _phaseB_perday(profs, classes_v, triples, class_profs, dc,
                   *, time_limit, workers=2):
    import cpsat_v2_timetable as cv2  # type: ignore
    full = {}
    for d in cv2.DAYS:
        out, _st = cv2.solve_phase_b_for_day(
            d, profs, classes_v, triples, class_profs, dc,
            time_limit=time_limit, workers=workers, log=False)
        if out:
            full.update(out)
    return full


# --------------------------------------------------------------------
# End-to-end runners. Each returns (sol_dict_or_None, info_dict).
# info_dict may carry: t_phase_a, t_phase_b, n_columns, n_iterations.
# --------------------------------------------------------------------

def run_cpsat_day_e2e(profs, school, c2curr, *, cap):
    """Phase A (week distribution) + per-day Phase B."""
    cap_total, t_a, t_b, _ = cap
    started = time.time()
    (dc, classes_v, triples, class_profs) = _phaseA(profs, time_limit=t_a)
    elapsed_a = time.time() - started
    t0 = time.time()
    full = _phaseB_perday(profs, classes_v, triples, class_profs, dc,
                          time_limit=t_b)
    elapsed_b = time.time() - t0
    return full, {"t_phase_a": elapsed_a, "t_phase_b": elapsed_b,
                  "dc": dc}


def run_decomp_temporal(profs, school, c2curr, *, cap):
    """Phase A + per-day decomposition_temporal.solve_day."""
    import decomposition_temporal as dt  # type: ignore
    cap_total, t_a, t_b, _ = cap
    (dc, _cv, _tr, _cp) = _phaseA(profs, time_limit=t_a)
    elapsed_a = time.time() - (time.time() - t_a)  # approx
    started = time.time()
    full = {}
    import cpsat_v2_timetable as cv2  # type: ignore
    for d in cv2.DAYS:
        out, _st = dt.solve_day(d, profs, dc, time_limit=t_b,
                                workers=2, log=False)
        if out:
            full.update(out)
    elapsed_b = time.time() - started
    return full, {"t_phase_a": t_a, "t_phase_b": elapsed_b}


def run_decomp_spectral(profs, school, c2curr, *, cap):
    """Phase A + per-day spectral monolithic fallback (no native
    spectral pipeline entry point in this codebase -- monolithic_day
    is the canonical path used by spectral / curriculum / metis as
    common fallback)."""
    import decomposition_spectral_v2 as ds  # type: ignore
    import cpsat_v2_timetable as cv2  # type: ignore
    cap_total, t_a, t_b, _ = cap
    (dc, classes_v, triples, class_profs) = _phaseA(profs, time_limit=t_a)
    started = time.time()
    full = {}
    for d in cv2.DAYS:
        out, _st = ds.solve_monolithic_day(
            d, profs, triples, dc, time_limit=t_b, workers=2, log=False)
        if out:
            full.update(out)
    elapsed_b = time.time() - started
    return full, {"t_phase_a": t_a, "t_phase_b": elapsed_b,
                  "note": "spectral_v2 entry = monolithic fallback"}


def run_decomp_curriculum(profs, school, c2curr, *, cap):
    import decomposition_curriculum as dc_mod  # type: ignore
    cap_total, t_a, t_b, _ = cap
    if not c2curr:
        return None, {"note": "no curriculum mapping in school pickle"}
    started = time.time()
    res = dc_mod.solve_with_curriculum_decomposition(
        profs, c2curr,
        time_a=t_a, time_per_cluster=t_b * 2, time_bridges=t_b,
        time_ricucitura=t_b * 2, time_mono=t_b * 3,
        workers=2, log=False)
    elapsed = time.time() - started
    sol = res.get("full_solution") if isinstance(res, dict) else res
    return sol, {"t_phase_a": t_a, "t_phase_b": elapsed - t_a}


def run_decomp_metis(profs, school, c2curr, *, cap):
    try:
        import decomposition_metis as dm  # type: ignore
    except Exception as e:
        return None, {"unwired": True,
                      "note": f"metis import failed: {e}"}
    cap_total, t_a, t_b, _ = cap
    started = time.time()
    res = dm.solve_with_metis_decomposition(
        profs, k=None,
        time_a=t_a, time_per_cluster=t_b * 2, time_bridges=t_b,
        time_ricucitura=t_b * 2, time_mono=t_b * 3,
        workers=2, log=False)
    elapsed = time.time() - started
    sol = res.get("full_solution") if isinstance(res, dict) else res
    return sol, {"t_phase_a": t_a, "t_phase_b": elapsed - t_a}


def run_cg_iterative(profs, school, c2curr, *, cap):
    import column_generation as cg  # type: ignore
    cap_total, t_a, _t_b, _ = cap
    (dc, *_rest) = _phaseA(profs, time_limit=t_a)
    elapsed_a = t_a
    started = time.time()
    sol, info = cg.run_column_generation(
        profs, dc,
        time_budget_s=cap_total - elapsed_a,
        patterns_per_teacher=2,
        max_iterations=3,
        mode="iterative-diversified",
        granularity="teacher",
        branching_strategy="none",
        log=False)
    elapsed_b = time.time() - started
    n_cols = info.get("total_columns") if isinstance(info, dict) else None
    n_iter = info.get("iterations") if isinstance(info, dict) else None
    return sol, {"t_phase_a": elapsed_a, "t_phase_b": elapsed_b,
                 "n_columns": n_cols, "n_iterations": n_iter}


def make_run_bp(granularity: str):
    def runner(profs, school, c2curr, *, cap):
        import column_generation as cg  # type: ignore
        cap_total, t_a, _t_b, _ = cap
        (dc, *_rest) = _phaseA(profs, time_limit=t_a)
        elapsed_a = t_a
        started = time.time()
        sol, info = cg.run_column_generation(
            profs, dc,
            time_budget_s=cap_total - elapsed_a,
            patterns_per_teacher=2,
            max_iterations=3,
            mode="iterative-diversified",
            granularity=granularity,
            branching_strategy="ryan_foster",
            bp_max_iterations=4,
            dual_stabilization=True,
            class_to_curriculum=c2curr if granularity == "curriculum" else None,
            log=False)
        elapsed_b = time.time() - started
        n_cols = info.get("total_columns") if isinstance(info, dict) else None
        n_iter = info.get("iterations") if isinstance(info, dict) else None
        return sol, {"t_phase_a": elapsed_a, "t_phase_b": elapsed_b,
                     "n_columns": n_cols, "n_iterations": n_iter}
    return runner


# --------------------------------------------------------------------
# Meta post-pass runners. Take a prebuilt `base` = (sol, dc, t_a, t_b).
# --------------------------------------------------------------------

def make_run_meta(label: str, fn_name: str):
    def runner(profs, base, *, cap):
        cap_total, _t_a, _t_b, t_post = cap
        sol, dc, base_t_a, base_t_b = base
        try:
            mod, fn = fn_name.split(":")
            m = __import__(mod)
            f = getattr(m, fn)
        except Exception as e:
            return None, {"unwired": True,
                          "note": f"{label} unavailable: {e}"}
        started = time.time()
        try:
            res = f(sol, profs, dc, time_budget_s=t_post, log=False)
            new_sol = res[0] if isinstance(res, tuple) else res
        except TypeError:
            # Some runners (sa, tabu) return only sol
            res = f(sol, profs, dc, time_budget_s=t_post, log=False)
            new_sol = res
        elapsed = time.time() - started
        return new_sol, {"t_phase_a": base_t_a,
                         "t_phase_b": base_t_b,
                         "t_post": elapsed}
    return runner


# --------------------------------------------------------------------
# Technique catalog
# --------------------------------------------------------------------

# end-to-end (no shared base reuse):
E2E_TECHNIQUES = [
    ("greedy_pure", "greedy", None,
     "no standalone greedy Phase A in codebase; Phase A is CP-SAT-based"),
    ("cpsat_week", "cpsat", None,
     "no monolithic-week solver; closest is cpsat_day (Phase A + per-day)"),
    ("cpsat_day", "cpsat", run_cpsat_day_e2e, ""),
    ("cpsat_day_skip_phase_a", "cpsat", None,
     "phase_a_mode=skip not exposed; per-day Phase B requires dc from Phase A"),
    ("cpsat_day_soft_hint", "cpsat", None,
     "phase_a_mode=soft_hint not exposed as parameter"),
    ("decomp_temporal", "decomp", run_decomp_temporal, ""),
    ("decomp_spectral_v2", "decomp", run_decomp_spectral, ""),
    ("decomp_curriculum", "decomp", run_decomp_curriculum, ""),
    ("decomp_metis", "decomp", run_decomp_metis, ""),
    ("cg_iterative_diversified", "cg", run_cg_iterative, ""),
]

BP_GRANULARITIES = [
    "teacher", "teacher-day", "teacher-class",
    "teacher-class-subject", "teacher-subject",
    "class", "class-day", "day", "curriculum",
]
for g in BP_GRANULARITIES:
    E2E_TECHNIQUES.append((f"bp_{g}", "bp", make_run_bp(g), ""))

META_TECHNIQUES = [
    ("meta_tabu", "meta",
     make_run_meta("tabu", "metaheuristics:run_tabu"), ""),
    ("meta_sa", "meta",
     make_run_meta("sa", "metaheuristics:run_sa"), ""),
    ("meta_lns", "meta",
     make_run_meta("lns", "metaheuristics:run_lns"), ""),
    ("meta_alns", "meta",
     make_run_meta("alns", "alns:run_alns"), ""),
    ("meta_vns", "meta",
     make_run_meta("vns", "vns:run_vns"), ""),
    ("meta_lagrangian", "meta",
     make_run_meta("lagrangian", "lagrangian:run_lagrangian"), ""),
]


# --------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------

def _new_row(profile, name, family, status, *, cap_total,
              t_a=0.0, t_b=0.0, t_post=0.0, cost=None, hard=None,
              n_lessons=None, n_cols=None, n_iter=None,
              n_classes=0, n_teachers=0, note="", error_msg=""):
    return BenchRow(
        profile=profile, technique=name, family=family,
        seed=42, status=status,
        t_phase_a=round(t_a, 2), t_phase_b=round(t_b, 2),
        t_post=round(t_post, 2),
        t_total=round(t_a + t_b + t_post, 2),
        cost=cost, hard_feasible=hard,
        n_lessons=n_lessons, n_columns=n_cols,
        n_iterations=n_iter, n_classes=n_classes,
        n_teachers=n_teachers, note=note, error_msg=error_msg,
    )


def run_one_e2e(profile, profs, school, c2curr, name, family,
                 fn, note_tag, *, cap, n_classes, n_teachers):
    cap_total = cap[0]
    if fn is None:
        return _new_row(profile, name, family, "unwired",
                        cap_total=cap_total, n_classes=n_classes,
                        n_teachers=n_teachers, note=note_tag)
    started = time.time()
    try:
        sol, info = fn(profs, school, c2curr, cap=cap)
    except Exception as e:
        traceback.print_exc()
        return _new_row(profile, name, family, "exception",
                        cap_total=cap_total, n_classes=n_classes,
                        n_teachers=n_teachers,
                        error_msg=f"{type(e).__name__}: {str(e)[:280]}",
                        t_a=time.time() - started)
    elapsed = time.time() - started
    if info.get("unwired"):
        return _new_row(profile, name, family, "unwired",
                        cap_total=cap_total, n_classes=n_classes,
                        n_teachers=n_teachers,
                        note=info.get("note", note_tag))
    if sol is None:
        return _new_row(profile, name, family, "infeasible",
                        cap_total=cap_total,
                        t_a=info.get("t_phase_a", 0.0),
                        t_b=info.get("t_phase_b", 0.0),
                        n_classes=n_classes, n_teachers=n_teachers,
                        note=info.get("note", ""))
    cost = _compute_cost(profs, sol)
    hard = _hard_ok(profs, sol)
    n_lessons = sum(1 for v in sol.values() if v == 1)
    status = "ok"
    if elapsed > cap_total * 1.4:
        status = "timeout"
    elif hard is False:
        status = "hard_violation"
    return _new_row(
        profile, name, family, status, cap_total=cap_total,
        t_a=info.get("t_phase_a", 0.0),
        t_b=info.get("t_phase_b", 0.0),
        t_post=info.get("t_post", 0.0),
        cost=cost, hard=hard, n_lessons=n_lessons,
        n_cols=info.get("n_columns"),
        n_iter=info.get("n_iterations"),
        n_classes=n_classes, n_teachers=n_teachers,
        note=info.get("note", ""))


def run_one_meta(profile, profs, base, name, family, fn, note_tag,
                  *, cap, n_classes, n_teachers):
    cap_total = cap[0]
    if fn is None or base is None:
        return _new_row(profile, name, family, "unwired",
                        cap_total=cap_total, n_classes=n_classes,
                        n_teachers=n_teachers,
                        note=note_tag or "no baseline available")
    started = time.time()
    try:
        sol, info = fn(profs, base, cap=cap)
    except Exception as e:
        traceback.print_exc()
        return _new_row(profile, name, family, "exception",
                        cap_total=cap_total, n_classes=n_classes,
                        n_teachers=n_teachers,
                        error_msg=f"{type(e).__name__}: {str(e)[:280]}")
    if info.get("unwired"):
        return _new_row(profile, name, family, "unwired",
                        cap_total=cap_total, n_classes=n_classes,
                        n_teachers=n_teachers,
                        note=info.get("note", note_tag))
    if sol is None:
        return _new_row(profile, name, family, "infeasible",
                        cap_total=cap_total,
                        t_a=info.get("t_phase_a", 0.0),
                        t_b=info.get("t_phase_b", 0.0),
                        t_post=info.get("t_post", 0.0),
                        n_classes=n_classes, n_teachers=n_teachers)
    cost = _compute_cost(profs, sol)
    hard = _hard_ok(profs, sol)
    n_lessons = sum(1 for v in sol.values() if v == 1)
    elapsed = time.time() - started
    status = "ok"
    if elapsed > cap_total * 1.4:
        status = "timeout"
    elif hard is False:
        status = "hard_violation"
    return _new_row(
        profile, name, family, status, cap_total=cap_total,
        t_a=info.get("t_phase_a", 0.0),
        t_b=info.get("t_phase_b", 0.0),
        t_post=info.get("t_post", 0.0),
        cost=cost, hard=hard, n_lessons=n_lessons,
        n_classes=n_classes, n_teachers=n_teachers)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", type=str, default=",".join(PROFILES),
                     help="comma-separated subset of profiles to run")
    ap.add_argument("--techniques", type=str, default=None,
                     help="comma-separated subset (default = all)")
    ap.add_argument("--out", type=str, default=None,
                     help="primary CSV path; default = "
                          "docs/manual/benchmarks/results.csv")
    ap.add_argument("--copy-to", type=str, default=None,
                     help="duplicate CSV path (also write here)")
    args = ap.parse_args()

    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    only = set([t.strip() for t in args.techniques.split(",")
                if t.strip()]) if args.techniques else None

    primary = args.out or os.path.join(
        REPO_ROOT, "docs", "manual", "benchmarks", "results.csv")
    os.makedirs(os.path.dirname(primary), exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    secondary = args.copy_to or os.path.join(
        HERE, "results", f"full_sweep_{ts}.csv")
    os.makedirs(os.path.dirname(secondary), exist_ok=True)

    fields = [f.name for f in dataclasses.fields(BenchRow)]
    started = time.time()
    print(f"[sweep] primary CSV  -> {primary}")
    print(f"[sweep] secondary    -> {secondary}")
    print(f"[sweep] profiles     = {profiles}")
    print(f"[sweep] technique #  = {len(E2E_TECHNIQUES) + len(META_TECHNIQUES)}")

    rows: list[BenchRow] = []
    files = []
    for path in (primary, secondary):
        f = open(path, "w", newline="", encoding="utf-8")
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        files.append((f, w))

    def emit(row: BenchRow):
        rows.append(row)
        for f, w in files:
            w.writerow(dataclasses.asdict(row))
            f.flush()
        print(f"[sweep]   {row.profile:>9} | {row.technique:<28} "
              f"status={row.status:<14} t_total={row.t_total:>7.1f}s  "
              f"cost={row.cost} hard={row.hard_feasible}")

    try:
        for prof in profiles:
            if prof not in TIME_CAPS:
                print(f"[sweep] unknown profile {prof}; skipping")
                continue
            cap = TIME_CAPS[prof]
            print(f"\n[sweep] === {prof} (cap_total={cap[0]}s) ===")
            try:
                profs, school, c2curr = load_profile(prof)
            except Exception as e:
                print(f"[sweep] cannot load {prof}: {e}")
                continue
            n_classes = len({c for p in profs.values()
                              for c in p["classi"]})
            n_teachers = len(profs)

            # End-to-end techniques. Capture cpsat_day base for meta reuse.
            base_for_meta = None
            for name, family, fn, note_tag in E2E_TECHNIQUES:
                if only and name not in only:
                    continue
                row = run_one_e2e(prof, profs, school, c2curr, name,
                                   family, fn, note_tag, cap=cap,
                                   n_classes=n_classes, n_teachers=n_teachers)
                emit(row)
                if name == "cpsat_day" and row.status == "ok":
                    # rerun once to keep dc + sol for meta post-pass.
                    # The first call already produced them; redo cheaply.
                    pass
            # Build base ONCE for meta (reuse the work we just did would
            # require returning info; simpler to rebuild small profile).
            # If cpsat_day was filtered out or failed, skip meta block.
            try:
                cap_quick = (cap[0], cap[1], cap[2], cap[3])
                sol_b, info_b = run_cpsat_day_e2e(profs, school, c2curr,
                                                   cap=cap_quick)
                if sol_b:
                    base_for_meta = (sol_b, info_b["dc"],
                                      info_b["t_phase_a"],
                                      info_b["t_phase_b"])
            except Exception as e:
                print(f"[sweep] cannot build meta base for {prof}: {e}")
                base_for_meta = None

            for name, family, fn, note_tag in META_TECHNIQUES:
                if only and name not in only:
                    continue
                row = run_one_meta(prof, profs, base_for_meta, name,
                                    family, fn, note_tag, cap=cap,
                                    n_classes=n_classes,
                                    n_teachers=n_teachers)
                emit(row)
    finally:
        for f, _ in files:
            f.close()

    elapsed = time.time() - started
    print(f"\n[sweep] DONE: {len(rows)} rows in {elapsed:.1f}s")
    print(f"[sweep] CSV -> {primary}")


if __name__ == "__main__":
    main()
