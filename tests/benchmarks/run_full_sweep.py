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
# Caps relaxed (2026-05): proportional to profile size.
# small=2min, medium=3min, big=6min, huge=10min, superhuge=20min, mega=30min.
TIME_CAPS = {
    "small":     (120.0,  20.0,  6.0,  20.0),
    "medium":    (180.0,  30.0,  8.0,  30.0),
    "big":       (360.0,  60.0, 15.0,  60.0),
    "huge":      (600.0,  90.0, 18.0,  90.0),
    "superhuge": (1200.0, 180.0, 30.0, 180.0),
    "mega":      (1800.0, 240.0, 40.0, 240.0),
}


# --------------------------------------------------------------------
# Data loaders
# --------------------------------------------------------------------

def load_profile(profile: str):
    """Load profs + school pickles for `profile`. Returns
    (profs_dict, school_dict, classroom_to_curriculum_dict, inputs)
    where inputs = (coteach, support, pot, par, grp) is always
    (None, None, None, None, None) for the pickle path -- pickles
    carry zero constraint stratification."""
    base = os.path.join(ENGINE_DIR, "scripts", "data", profile)
    with open(os.path.join(base, f"profs_{profile}.pkl"), "rb") as f:
        profs = pickle.load(f)
    with open(os.path.join(base, f"school_{profile}.pkl"), "rb") as f:
        school = pickle.load(f)
    classroom_to_curriculum = {}
    for c in school.get("classes", []):
        if isinstance(c, dict) and "name" in c and "curriculum" in c:
            classroom_to_curriculum[c["name"]] = c["curriculum"]
    return profs, school, classroom_to_curriculum, (None, None, None,
                                                     None, None)


def _make_in_memory_db():
    """Spin up a fresh in-memory SQLite + sessionmaker, with the
    full models.py schema baked in. Caller closes the Session and
    disposes the engine when done."""
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    # Use a tempfile rather than :memory: -- the DB is consumed by
    # `import_profile_sqlite_into_db` which uses `db.connection()`
    # and that survives across statements better with a real file.
    tmpdir = tempfile.mkdtemp(prefix="bench_v2_")
    url = f"sqlite:///{tmpdir}/bench_live.db"
    eng = create_engine(url, connect_args={"check_same_thread": False},
                         future=True)
    Sess = sessionmaker(bind=eng, autoflush=False, autocommit=False,
                         future=True)
    from backend import db as backend_db
    from backend import models  # noqa: F401  -- register mappers
    backend_db.Base.metadata.create_all(bind=eng)
    return eng, Sess


def load_profile_from_sqlite(profile: str):
    """Load profile from `<profile>.sqlite` produced by
    webui/backend/scripts/build_profile_db.py. Returns the same shape as
    `load_profile()` but with a meaningful `inputs` tuple extracted
    from the constraint tables.

    The 5 channel helpers (coteach/support/pot/parallel/group) are
    consumed by the runners directly. Slot-level constraints
    (teacher_unavailability, DSL `general_constraints`,
    `logical_unavailabilities`, `curriculum_logical_constraints`)
    are NOT routed to the solver from this bench harness -- the
    runners' signatures don't accept them. The mandatory-free-days
    table is merged into `glibero` (the only slot/day-level signal
    that fits the existing profs schema cleanly)."""
    sqlite_path = os.path.join(ENGINE_DIR, "scripts", "data",
                                profile, f"{profile}.sqlite")
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(sqlite_path)
    eng, Sess = _make_in_memory_db()
    db = Sess()
    try:
        from backend import engine_io
        engine_io.import_profile_sqlite_into_db(db, sqlite_path,
                                                 replace=True)
        profs = engine_io.profs_dict_from_db(db)
        coteach = engine_io.coteach_groups_for_solver(db) or None
        support = engine_io.support_assignments_from_db(db) or None
        pot = engine_io.potenziamento_assignments_from_db(db) or None
        par = engine_io.parallel_groups_for_solver(db) or None
        grp = engine_io.group_assignments_for_solver(db) or None
        # Curriculum mapping: class_name -> curriculum from the
        # `school_classes` table.
        from backend import models
        c2curr = {}
        for cl in db.query(models.SchoolClass).all():
            if cl.curriculum:
                c2curr[cl.name] = cl.curriculum
        # Merge HARD mandatory free days into glibero. The pickle
        # loader synthesises a 3-day glibero from teacher.free_day +
        # 2 random fillers; here we override the random part with the
        # explicit stress entries so the sweep actually feels them.
        teacher_by_id = {t.id: t for t in db.query(models.Teacher).all()}
        for mfd in db.query(models.TeacherMandatoryFreeDay).all():
            t = teacher_by_id.get(mfd.teacher_id)
            if t is None or t.name not in profs:
                continue
            glib = list(profs[t.name].get("glibero", []))
            if mfd.day not in glib:
                glib.append(int(mfd.day))
            profs[t.name]["glibero"] = glib[:3] if len(glib) > 3 else glib
        # `school` is kept for API symmetry with the pickle loader,
        # but most fields are not consumed downstream.
        school = {"classes": [{"name": cl.name,
                                 "curriculum": cl.curriculum,
                                 "year": cl.year}
                                for cl in db.query(models.SchoolClass)
                                            .all()]}
    finally:
        db.close()
        eng.dispose()
    inputs = (coteach, support, pot, par, grp)
    return profs, school, c2curr, inputs


# --------------------------------------------------------------------
# Result row
# --------------------------------------------------------------------

@dataclass
class BenchRow:
    profile: str
    dataset: str           # "pickle" (no constraints) | "sqlite" (full stratification)
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


def _hard_ok(profs, sol, inputs=(None, None, None, None, None)):
    import metaheuristics as meta  # type: ignore
    coteach, support, _pot, par, grp = inputs
    try:
        return bool(meta.is_hard_feasible(
            sol, profs, verbose=False,
            group_assignments=grp,
            coteach_groups=coteach,
            parallel_groups=par,
            support_assignments=support))
    except Exception:
        return None


def _phaseA(profs, *, time_limit, workers=2,
             inputs=(None, None, None, None, None)):
    import cpsat_v2_timetable as cv2  # type: ignore
    coteach, support, pot, par, grp = inputs
    classes_v, triples, class_profs = cv2.build_indices(profs)
    return cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=time_limit, workers=workers, log=False,
        coteach_groups=coteach, support_assignments=support,
        potenziamento_assignments=pot, parallel_groups=par,
        group_assignments=grp,
    ), classes_v, triples, class_profs


def _phaseB_perday(profs, classes_v, triples, class_profs, dc,
                   *, time_limit, workers=2,
                   inputs=(None, None, None, None, None)):
    import cpsat_v2_timetable as cv2  # type: ignore
    coteach, support, _pot, par, grp = inputs
    full = {}
    for d in cv2.DAYS:
        out, _st = cv2.solve_phase_b_for_day(
            d, profs, classes_v, triples, class_profs, dc,
            time_limit=time_limit, workers=workers, log=False,
            coteach_groups=coteach, support_assignments=support,
            parallel_groups=par, group_assignments=grp,
        )
        if out:
            full.update(out)
    return full


# --------------------------------------------------------------------
# End-to-end runners. Each returns (sol_dict_or_None, info_dict).
# info_dict may carry: t_phase_a, t_phase_b, n_columns, n_iterations.
# --------------------------------------------------------------------

_NULL_INPUTS = (None, None, None, None, None)


def run_cpsat_day_e2e(profs, school, c2curr, *, cap, inputs=_NULL_INPUTS):
    """Phase A (week distribution) + per-day Phase B."""
    cap_total, t_a, t_b, _ = cap
    started = time.time()
    (dc, classes_v, triples, class_profs) = _phaseA(
        profs, time_limit=t_a, inputs=inputs)
    elapsed_a = time.time() - started
    t0 = time.time()
    full = _phaseB_perday(profs, classes_v, triples, class_profs, dc,
                          time_limit=t_b, inputs=inputs)
    elapsed_b = time.time() - t0
    return full, {"t_phase_a": elapsed_a, "t_phase_b": elapsed_b,
                  "dc": dc}


def _import_cpsat_oo():
    """Resolve MonolithicSolver/DayCountModel/ConstraintConfig from
    engine.cp_sat_constraint_model. The engine dir is already on
    sys.path so the bare-import path works either way."""
    try:
        from cp_sat_constraint_model import (  # type: ignore
            MonolithicSolver, DayCountModel, ConstraintConfig)
    except ImportError:
        from engine.cp_sat_constraint_model import (  # type: ignore
            MonolithicSolver, DayCountModel, ConstraintConfig)
    return MonolithicSolver, DayCountModel, ConstraintConfig


def _default_config():
    """ConstraintConfig matching the production webui call site
    in optimization._solve_phase_b_week (no_holes + h11 + motorie +
    math_italian). All group/lock fields default to []."""
    _, _, ConstraintConfig = _import_cpsat_oo()
    return ConstraintConfig(
        enforce_no_holes=True,
        enforce_h3_presence_at_11=True,
        enforce_motorie_pair=True,
        enforce_math_italian_pair=True,
    )


def _n_days():
    import cpsat_v2_timetable as cv2  # type: ignore
    return len(cv2.DAYS)


def run_cpsat_week_e2e(profs, school, c2curr, *, cap, inputs=_NULL_INPUTS):
    """Pure monolithic-week solver. Uses
    ``MonolithicSolver(scope=None, dc_value=None)``: weekly_mode is
    on, the slot vars carry the weekly equality
    ``sum_{d,h} slot == ore``, and the day distribution is a CP-SAT
    decision (no Phase A at all). Equivalent to the production path
    ``cp_sat_scope='week', phase_a_mode='skip'``. Full cap budget
    spent on the single mono solve."""
    cap_total, _t_a, _t_b, _ = cap
    MonolithicSolver, _DayCountModel, _CC = _import_cpsat_oo()
    cfg = _default_config()
    started = time.time()
    ms = MonolithicSolver(profs, dc_value=None, config=cfg, scope=None)
    sol, status = ms.solve(time_limit_s=cap_total, workers=2, log=False)
    elapsed = time.time() - started
    return sol, {"t_phase_a": 0.0, "t_phase_b": elapsed,
                 "note": f"week+skip, {len(ms.slot)} slot vars, "
                          f"status={status}"}


def run_cpsat_day_skip_phase_a_e2e(profs, school, c2curr, *, cap,
                                     inputs=_NULL_INPUTS):
    """``phase_a_mode='skip'`` flavour matched to the per-day time
    budget so the comparison vs ``cpsat_day`` is on the same Phase B
    pool. Same engine as ``cpsat_week`` but with mono budget
    ``t_b * NUM_DAYS`` instead of full ``cap_total``."""
    _cap_total, _t_a, t_b, _ = cap
    MonolithicSolver, _DayCountModel, _CC = _import_cpsat_oo()
    cfg = _default_config()
    nd = _n_days()
    budget = float(t_b) * nd
    started = time.time()
    ms = MonolithicSolver(profs, dc_value=None, config=cfg, scope=None)
    sol, status = ms.solve(time_limit_s=budget, workers=2, log=False)
    elapsed = time.time() - started
    return sol, {"t_phase_a": 0.0, "t_phase_b": elapsed,
                 "note": f"week+skip, mono_budget=t_b*{nd}={budget}s, "
                          f"status={status}"}


def run_cpsat_day_soft_hint_e2e(profs, school, c2curr, *, cap,
                                  inputs=_NULL_INPUTS):
    """``phase_a_mode='soft_hint'``: solve Phase A via
    ``DayCountModel`` to get a ``dc_value``, then push it into the
    week-mode ``MonolithicSolver`` through ``add_phase_a_hint``
    (best-effort warm start, NOT a HARD constraint). Time split
    matches ``cpsat_day``: ``t_a`` for Phase A + ``t_b * NUM_DAYS``
    for the mono solve."""
    _cap_total, t_a, t_b, _ = cap
    MonolithicSolver, DayCountModel, _CC = _import_cpsat_oo()
    cfg = _default_config()
    nd = _n_days()
    mono_budget = float(t_b) * nd
    started_a = time.time()
    dcm = DayCountModel(profs, config=cfg)
    dc_value, status_a = dcm.solve(
        time_limit_s=float(t_a), workers=2, log=False)
    elapsed_a = time.time() - started_a
    if not dc_value:
        return None, {"t_phase_a": elapsed_a, "t_phase_b": 0.0,
                      "note": f"DayCountModel returned {status_a}"}
    started_b = time.time()
    ms = MonolithicSolver(profs, dc_value=None, config=cfg, scope=None)
    n_hints = ms.add_phase_a_hint(dc_value)
    sol, status_b = ms.solve(time_limit_s=mono_budget, workers=2,
                              log=False)
    elapsed_b = time.time() - started_b
    return sol, {"t_phase_a": elapsed_a, "t_phase_b": elapsed_b,
                 "note": f"week+soft_hint, {n_hints} hints, "
                          f"status={status_b}"}


def run_decomp_temporal(profs, school, c2curr, *, cap,
                         inputs=_NULL_INPUTS):
    """Phase A + per-day decomposition_temporal.solve_day."""
    import decomposition_temporal as dt  # type: ignore
    cap_total, t_a, t_b, _ = cap
    coteach, _support, _pot, _par, grp = inputs
    (dc, _cv, _tr, _cp) = _phaseA(profs, time_limit=t_a, inputs=inputs)
    elapsed_a = time.time() - (time.time() - t_a)  # approx
    started = time.time()
    full = {}
    import cpsat_v2_timetable as cv2  # type: ignore
    for d in cv2.DAYS:
        out, _st = dt.solve_day(d, profs, dc, time_limit=t_b,
                                workers=2, log=False,
                                coteach_groups=coteach,
                                group_assignments=grp)
        if out:
            full.update(out)
    elapsed_b = time.time() - started
    return full, {"t_phase_a": t_a, "t_phase_b": elapsed_b}


def run_decomp_spectral(profs, school, c2curr, *, cap,
                         inputs=_NULL_INPUTS):
    """Phase A + per-day spectral monolithic fallback (no native
    spectral pipeline entry point in this codebase -- monolithic_day
    is the canonical path used by spectral / curriculum / metis as
    common fallback)."""
    import decomposition_spectral_v2 as ds  # type: ignore
    import cpsat_v2_timetable as cv2  # type: ignore
    cap_total, t_a, t_b, _ = cap
    coteach, support, _pot, par, grp = inputs
    (dc, classes_v, triples, class_profs) = _phaseA(
        profs, time_limit=t_a, inputs=inputs)
    started = time.time()
    full = {}
    for d in cv2.DAYS:
        out, _st = ds.solve_monolithic_day(
            d, profs, triples, dc, time_limit=t_b, workers=2, log=False,
            coteach_groups=coteach, support_assignments=support,
            parallel_groups=par, group_assignments=grp)
        if out:
            full.update(out)
    elapsed_b = time.time() - started
    return full, {"t_phase_a": t_a, "t_phase_b": elapsed_b,
                  "note": "spectral_v2 entry = monolithic fallback"}


def run_decomp_curriculum(profs, school, c2curr, *, cap,
                           inputs=_NULL_INPUTS):
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


def run_decomp_metis(profs, school, c2curr, *, cap, inputs=_NULL_INPUTS):
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


def run_cg_iterative(profs, school, c2curr, *, cap, inputs=_NULL_INPUTS):
    import column_generation as cg  # type: ignore
    cap_total, t_a, _t_b, _ = cap
    coteach, support, _pot, par, grp = inputs
    (dc, *_rest) = _phaseA(profs, time_limit=t_a, inputs=inputs)
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
        coteach_groups=coteach, support_assignments=support,
        parallel_groups=par, group_assignments=grp,
        log=False)
    elapsed_b = time.time() - started
    n_cols = info.get("total_columns") if isinstance(info, dict) else None
    n_iter = info.get("iterations") if isinstance(info, dict) else None
    return sol, {"t_phase_a": elapsed_a, "t_phase_b": elapsed_b,
                 "n_columns": n_cols, "n_iterations": n_iter}


def make_run_bp(granularity: str):
    def runner(profs, school, c2curr, *, cap, inputs=_NULL_INPUTS):
        import column_generation as cg  # type: ignore
        cap_total, t_a, _t_b, _ = cap
        coteach, support, _pot, par, grp = inputs
        (dc, *_rest) = _phaseA(profs, time_limit=t_a, inputs=inputs)
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
            coteach_groups=coteach, support_assignments=support,
            parallel_groups=par, group_assignments=grp,
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
    def runner(profs, base, *, cap, inputs=_NULL_INPUTS):
        cap_total, _t_a, _t_b, t_post = cap
        sol, dc, base_t_a, base_t_b = base
        coteach, support, _pot, par, grp = inputs
        try:
            mod, fn = fn_name.split(":")
            m = __import__(mod)
            f = getattr(m, fn)
        except Exception as e:
            return None, {"unwired": True,
                          "note": f"{label} unavailable: {e}"}
        started = time.time()
        kwargs = dict(time_budget_s=t_post, log=False,
                       coteach_groups=coteach,
                       support_assignments=support,
                       parallel_groups=par,
                       group_assignments=grp)
        try:
            res = f(sol, profs, dc, **kwargs)
            new_sol = res[0] if isinstance(res, tuple) else res
        except TypeError:
            # Fallback for runners that don't accept the constraint
            # kwargs (older signatures): drop them and retry.
            res = f(sol, profs, dc, time_budget_s=t_post, log=False)
            new_sol = res[0] if isinstance(res, tuple) else res
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
    ("cpsat_week", "cpsat", run_cpsat_week_e2e, ""),
    ("cpsat_day", "cpsat", run_cpsat_day_e2e, ""),
    ("cpsat_day_skip_phase_a", "cpsat", run_cpsat_day_skip_phase_a_e2e, ""),
    ("cpsat_day_soft_hint", "cpsat", run_cpsat_day_soft_hint_e2e, ""),
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

def _new_row(profile, dataset, name, family, status, *, cap_total,
              t_a=0.0, t_b=0.0, t_post=0.0, cost=None, hard=None,
              n_lessons=None, n_cols=None, n_iter=None,
              n_classes=0, n_teachers=0, note="", error_msg=""):
    return BenchRow(
        profile=profile, dataset=dataset, technique=name, family=family,
        seed=42, status=status,
        t_phase_a=round(t_a, 2), t_phase_b=round(t_b, 2),
        t_post=round(t_post, 2),
        t_total=round(t_a + t_b + t_post, 2),
        cost=cost, hard_feasible=hard,
        n_lessons=n_lessons, n_columns=n_cols,
        n_iterations=n_iter, n_classes=n_classes,
        n_teachers=n_teachers, note=note, error_msg=error_msg,
    )


def run_one_e2e(profile, dataset, profs, school, c2curr, name, family,
                 fn, note_tag, *, cap, n_classes, n_teachers,
                 inputs=_NULL_INPUTS):
    cap_total = cap[0]
    if fn is None:
        return _new_row(profile, dataset, name, family, "unwired",
                        cap_total=cap_total, n_classes=n_classes,
                        n_teachers=n_teachers, note=note_tag)
    started = time.time()
    try:
        sol, info = fn(profs, school, c2curr, cap=cap, inputs=inputs)
    except Exception as e:
        traceback.print_exc()
        return _new_row(profile, dataset, name, family, "exception",
                        cap_total=cap_total, n_classes=n_classes,
                        n_teachers=n_teachers,
                        error_msg=f"{type(e).__name__}: {str(e)[:280]}",
                        t_a=time.time() - started)
    elapsed = time.time() - started
    if info.get("unwired"):
        return _new_row(profile, dataset, name, family, "unwired",
                        cap_total=cap_total, n_classes=n_classes,
                        n_teachers=n_teachers,
                        note=info.get("note", note_tag))
    if sol is None:
        return _new_row(profile, dataset, name, family, "infeasible",
                        cap_total=cap_total,
                        t_a=info.get("t_phase_a", 0.0),
                        t_b=info.get("t_phase_b", 0.0),
                        n_classes=n_classes, n_teachers=n_teachers,
                        note=info.get("note", ""))
    cost = _compute_cost(profs, sol)
    hard = _hard_ok(profs, sol, inputs)
    n_lessons = sum(1 for v in sol.values() if v == 1)
    status = "ok"
    if elapsed > cap_total * 1.4:
        status = "timeout"
    elif hard is False:
        status = "hard_violation"
    return _new_row(
        profile, dataset, name, family, status, cap_total=cap_total,
        t_a=info.get("t_phase_a", 0.0),
        t_b=info.get("t_phase_b", 0.0),
        t_post=info.get("t_post", 0.0),
        cost=cost, hard=hard, n_lessons=n_lessons,
        n_cols=info.get("n_columns"),
        n_iter=info.get("n_iterations"),
        n_classes=n_classes, n_teachers=n_teachers,
        note=info.get("note", ""))


def run_one_meta(profile, dataset, profs, base, name, family, fn,
                  note_tag, *, cap, n_classes, n_teachers,
                  inputs=_NULL_INPUTS):
    cap_total = cap[0]
    if fn is None or base is None:
        return _new_row(profile, dataset, name, family, "unwired",
                        cap_total=cap_total, n_classes=n_classes,
                        n_teachers=n_teachers,
                        note=note_tag or "no baseline available")
    started = time.time()
    try:
        sol, info = fn(profs, base, cap=cap, inputs=inputs)
    except Exception as e:
        traceback.print_exc()
        return _new_row(profile, dataset, name, family, "exception",
                        cap_total=cap_total, n_classes=n_classes,
                        n_teachers=n_teachers,
                        error_msg=f"{type(e).__name__}: {str(e)[:280]}")
    if info.get("unwired"):
        return _new_row(profile, dataset, name, family, "unwired",
                        cap_total=cap_total, n_classes=n_classes,
                        n_teachers=n_teachers,
                        note=info.get("note", note_tag))
    if sol is None:
        return _new_row(profile, dataset, name, family, "infeasible",
                        cap_total=cap_total,
                        t_a=info.get("t_phase_a", 0.0),
                        t_b=info.get("t_phase_b", 0.0),
                        t_post=info.get("t_post", 0.0),
                        n_classes=n_classes, n_teachers=n_teachers)
    cost = _compute_cost(profs, sol)
    hard = _hard_ok(profs, sol, inputs)
    n_lessons = sum(1 for v in sol.values() if v == 1)
    elapsed = time.time() - started
    status = "ok"
    if elapsed > cap_total * 1.4:
        status = "timeout"
    elif hard is False:
        status = "hard_violation"
    return _new_row(
        profile, dataset, name, family, status, cap_total=cap_total,
        t_a=info.get("t_phase_a", 0.0),
        t_b=info.get("t_phase_b", 0.0),
        t_post=info.get("t_post", 0.0),
        cost=cost, hard=hard, n_lessons=n_lessons,
        n_classes=n_classes, n_teachers=n_teachers)


def feasibility_precheck(profs, inputs, *, time_limit=120.0):
    """Verify HARD-feasibility of the loaded profile via
    ``MonolithicSolver(scope=None)`` with a short budget. Returns
    (is_feasible: bool, status: str, t_elapsed: float). Used as a
    sanity gate before running the full sweep on a SQLite-stratified
    profile -- if even the monolithic solver can't find a solution
    in `time_limit` seconds, the bench cells will all fail, and the
    user should relax a constraint in the source DB."""
    MonolithicSolver, _DCM, _CC = _import_cpsat_oo()
    cfg = _default_config()
    started = time.time()
    try:
        ms = MonolithicSolver(profs, dc_value=None, config=cfg, scope=None)
        sol, status = ms.solve(time_limit_s=float(time_limit),
                                workers=2, log=False)
    except Exception as e:
        return False, f"exception:{type(e).__name__}", time.time() - started
    elapsed = time.time() - started
    return sol is not None, status, elapsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", type=str, default=",".join(PROFILES),
                     help="comma-separated subset of profiles to run")
    ap.add_argument("--techniques", type=str, default=None,
                     help="comma-separated subset (default = all)")
    ap.add_argument("--source", "--dataset", type=str, default="sqlite",
                     dest="source",
                     choices=("pickle", "sqlite", "both"),
                     help="data source: legacy pickle (no constraints), "
                          "SQLite stress profile (full stratification), "
                          "or both back-to-back for a delta comparison. "
                          "`--dataset` is an alias kept for symmetry "
                          "with the bench docs.")
    ap.add_argument("--skip-precheck", action="store_true",
                     help="skip MonolithicSolver feasibility precheck "
                          "before running the bench cells")
    ap.add_argument("--precheck-time", type=float, default=120.0,
                     help="time budget for the feasibility precheck "
                          "(default 120s)")
    ap.add_argument("--out", type=str, default=None,
                     help="primary CSV path; default = "
                          "docs/manual/benchmarks/results.csv")
    ap.add_argument("--copy-to", type=str, default=None,
                     help="duplicate CSV path (also write here)")
    ap.add_argument("--append", action="store_true",
                     help="append to the primary CSV instead of "
                          "overwriting it (useful for incremental runs)")
    args = ap.parse_args()

    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    only = set([t.strip() for t in args.techniques.split(",")
                if t.strip()]) if args.techniques else None
    if args.source == "both":
        sources = ("pickle", "sqlite")
    else:
        sources = (args.source,)

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
    write_mode = "a" if args.append else "w"
    for i, path in enumerate((primary, secondary)):
        # Append-mode skips the header if the file already has rows
        already_has_header = (
            args.append and os.path.exists(path)
            and os.path.getsize(path) > 0)
        f = open(path, write_mode, newline="", encoding="utf-8")
        w = csv.DictWriter(f, fieldnames=fields)
        if not already_has_header:
            w.writeheader()
        files.append((f, w))

    def emit(row: BenchRow):
        rows.append(row)
        for f, w in files:
            w.writerow(dataclasses.asdict(row))
            f.flush()
        print(f"[sweep]   {row.profile:>9}/{row.dataset:<6} | "
              f"{row.technique:<28} status={row.status:<14} "
              f"t_total={row.t_total:>7.1f}s  "
              f"cost={row.cost} hard={row.hard_feasible}")

    try:
        for source in sources:
            if source == "pickle":
                loader = load_profile
            elif source == "sqlite":
                loader = load_profile_from_sqlite
            else:
                raise ValueError(f"unknown source: {source}")
            print(f"\n[sweep] ============================")
            print(f"[sweep]  source = {source.upper()}")
            print(f"[sweep] ============================")
            for prof in profiles:
                if prof not in TIME_CAPS:
                    print(f"[sweep] unknown profile {prof}; skipping")
                    continue
                cap = TIME_CAPS[prof]
                print(f"\n[sweep] === {prof} ({source}) "
                      f"cap_total={cap[0]}s ===")
                try:
                    profs, school, c2curr, inputs = loader(prof)
                except FileNotFoundError as e:
                    print(f"[sweep] cannot load {prof} from {source}: "
                          f"{e}")
                    continue
                except Exception as e:
                    print(f"[sweep] {prof}/{source} loader failed: {e}")
                    traceback.print_exc()
                    continue
                n_classes = len({c for p in profs.values()
                                  for c in p["classi"]})
                n_teachers = len(profs)
                # Feasibility precheck: only meaningful for SQLite
                # (pickle profiles have no constraints, always
                # feasible by construction).
                if (not args.skip_precheck) and source == "sqlite":
                    feas, st, te = feasibility_precheck(
                        profs, inputs, time_limit=args.precheck_time)
                    print(f"[sweep] precheck {prof}/sqlite: "
                          f"feasible={feas} status={st} "
                          f"elapsed={te:.1f}s")
                    if not feas:
                        emit(_new_row(
                            prof, source, "_precheck",
                            "precheck", "infeasible",
                            cap_total=cap[0],
                            t_a=te, n_classes=n_classes,
                            n_teachers=n_teachers,
                            note=f"MonolithicSolver(scope=None) "
                                  f"could not satisfy in "
                                  f"{args.precheck_time}s; status={st}; "
                                  f"relax one constraint in "
                                  f"build_profile_db and rebuild"))
                        continue

                # End-to-end techniques.
                for name, family, fn, note_tag in E2E_TECHNIQUES:
                    if only and name not in only:
                        continue
                    row = run_one_e2e(
                        prof, source, profs, school, c2curr, name,
                        family, fn, note_tag, cap=cap,
                        n_classes=n_classes, n_teachers=n_teachers,
                        inputs=inputs)
                    emit(row)
                # Build base ONCE for meta (re-runs cpsat_day for
                # cheap; the previous E2E loop discarded the dc/sol).
                base_for_meta = None
                try:
                    sol_b, info_b = run_cpsat_day_e2e(
                        profs, school, c2curr, cap=cap, inputs=inputs)
                    if sol_b:
                        base_for_meta = (sol_b, info_b["dc"],
                                          info_b["t_phase_a"],
                                          info_b["t_phase_b"])
                except Exception as e:
                    print(f"[sweep] cannot build meta base for "
                          f"{prof}/{source}: {e}")
                    base_for_meta = None

                for name, family, fn, note_tag in META_TECHNIQUES:
                    if only and name not in only:
                        continue
                    row = run_one_meta(
                        prof, source, profs, base_for_meta, name,
                        family, fn, note_tag, cap=cap,
                        n_classes=n_classes,
                        n_teachers=n_teachers, inputs=inputs)
                    emit(row)
    finally:
        for f, _ in files:
            f.close()

    elapsed = time.time() - started
    print(f"\n[sweep] DONE: {len(rows)} rows in {elapsed:.1f}s")
    print(f"[sweep] CSV -> {primary}")


if __name__ == "__main__":
    main()
