"""B3 — spectral_v2 add_buchi_soft routed through soft_costs.

`decomposition_spectral_v2.add_buchi_soft` no longer hand-rolls the
teacher-gap (buchi) encoding; it delegates to
`soft_costs.buchi_pairs` and returns the per-(teacher, day) buchi vars
so the three call sites' ``model.Minimize(sum(...))`` is unchanged.

These tests pin the FUNCTIONAL contract:

1. With a slot configuration FORCED to a known interior gap, the sum of
   the returned vars equals the interior-hole count (objective VALUE
   preserved vs. the old per-slot encoding, which summed one bool per
   interior hole with implicit weight 1).
2. As a free objective, minimizing the returned vars packs the hours
   (drives interior holes to zero) — the steering behavior is intact.
3. The orchestrated spectral pipeline still returns a HARD-feasible
   solution (no regression in the closure guarantee).
"""
from __future__ import annotations

import os
import sys

from ortools.sat.python import cp_model

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for _p in (WEBUI_DIR, ENGINE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _build_single_teacher_slot(model, prof, cl, subj, day, hours):
    """One BoolVar per hour for a single (prof, class, subject), keyed
    the way the spectral stages key `slot`: (prof, class, subj, hour)."""
    return {
        (prof, cl, subj, h): model.NewBoolVar(f"s_{prof}_{cl}_{subj}_{h}")
        for h in hours
    }


def test_add_buchi_soft_sum_equals_interior_hole_count():
    """Force occupation at hours 8, 10, 12 (gaps at 9 and 11). The
    interior-hole count is 2; sum of the returned buchi vars must be 2
    and the model must solve."""
    import decomposition_spectral_v2 as dec  # type: ignore

    prof, cl, subj, day = "P", "1A", "Mat", 0
    hours = list(dec.HOURS)  # 8..13
    model = cp_model.CpModel()
    slot = _build_single_teacher_slot(model, prof, cl, subj, day, hours)
    # Occupy 8, 10, 12; empty everywhere else -> interior holes at 9, 11.
    for h in hours:
        model.Add(slot[(prof, cl, subj, h)] == (1 if h in (8, 10, 12) else 0))

    triples_active = [(prof, cl, subj, 3)]
    gap_terms = dec.add_buchi_soft(model, triples_active, slot, day, "T")
    assert gap_terms, "expected at least one buchi var"

    total = model.NewIntVar(0, 100, "total_gap")
    model.Add(total == sum(gap_terms))

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    # span = 12-8+1 = 5 occupied=3 -> 2 interior holes.
    assert solver.Value(total) == 2


def test_add_buchi_soft_no_interior_holes_when_packed():
    """Occupation at 8, 9, 10 (contiguous) -> zero interior holes."""
    import decomposition_spectral_v2 as dec  # type: ignore

    prof, cl, subj, day = "P", "1A", "Mat", 0
    hours = list(dec.HOURS)
    model = cp_model.CpModel()
    slot = _build_single_teacher_slot(model, prof, cl, subj, day, hours)
    for h in hours:
        model.Add(slot[(prof, cl, subj, h)] == (1 if h in (8, 9, 10) else 0))

    gap_terms = dec.add_buchi_soft(
        model, [(prof, cl, subj, 3)], slot, day, "T")
    total = model.NewIntVar(0, 100, "total_gap")
    model.Add(total == sum(gap_terms))

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(total) == 0


def test_add_buchi_soft_minimize_packs_hours():
    """As the sole objective, Minimize(sum(buchi)) drives a free
    placement (3 of 6 hours) to a contiguous block -> zero gaps."""
    import decomposition_spectral_v2 as dec  # type: ignore

    prof, cl, subj, day = "P", "1A", "Mat", 0
    hours = list(dec.HOURS)
    model = cp_model.CpModel()
    slot = _build_single_teacher_slot(model, prof, cl, subj, day, hours)
    # Exactly 3 occupied hours, otherwise free.
    model.Add(sum(slot[(prof, cl, subj, h)] for h in hours) == 3)

    gap_terms = dec.add_buchi_soft(
        model, [(prof, cl, subj, 3)], slot, day, "T")
    model.Minimize(sum(gap_terms))

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    busy = sorted(h for h in hours
                  if solver.Value(slot[(prof, cl, subj, h)]) == 1)
    assert len(busy) == 3
    # Contiguous block => no interior holes.
    assert busy[-1] - busy[0] == 2, f"hours not packed: {busy}"


def test_add_buchi_soft_empty_triples_returns_empty():
    """No active triples -> no buchi vars (callers skip Minimize)."""
    import decomposition_spectral_v2 as dec  # type: ignore

    model = cp_model.CpModel()
    assert dec.add_buchi_soft(model, [], {}, 0, "T") == []


def test_spectral_pipeline_still_hard_feasible():
    """End-to-end: the orchestrated spectral_v2 pipeline (the path that
    calls add_buchi_soft in stages A/B/C) still closes the timetable
    HARD-feasibly. Mirrors the mini scenario of the native-locks test:
    one cluster, no bridges, 3 profs over 2 classes."""
    import cpsat_v2_timetable as cv2  # type: ignore
    import decomposition_loop as dl  # type: ignore
    import numpy as np

    profs = {
        "ProfA": {"classi": {"1A": {"Mat": {"ore": 4}},
                              "1B": {"Mat": {"ore": 4}}},
                  "glibero": [6, 5, 4]},
        "ProfB": {"classi": {"1A": {"Ita": {"ore": 4}},
                              "1B": {"Ita": {"ore": 4}}},
                  "glibero": [6, 5, 4]},
        "ProfC": {"classi": {"1A": {"Sto": {"ore": 2}},
                             "1B": {"Sto": {"ore": 2}}},
                  "glibero": [6, 5, 4]},
    }
    classes = sorted({c for p in profs.values() for c in p["classi"]})
    labels = np.zeros(len(classes), dtype=int)
    bridges: set[str] = set()

    res = dl.run_partitioned_pipeline(
        profs, labels, classes, bridges,
        time_a=4, time_bridges=4, time_cluster=4,
        time_ricucitura=4, time_mono=4,
        workers=2, log=False,
    )
    assert res["status"] in ("ok", "partial"), res["status"]
    sol = res["full_solution"]
    assert sol, "empty solution"

    # HARD invariant 1: total hours per (prof, class, subject) preserved.
    expected = {}
    for p, info in profs.items():
        for c, subs in info["classi"].items():
            for s, meta in subs.items():
                expected[(p, c, s)] = meta["ore"]
    placed: dict = {}
    for (p, c, s, _d, _h), v in sol.items():
        if v == 1:
            placed[(p, c, s)] = placed.get((p, c, s), 0) + 1
    for key, want in expected.items():
        assert placed.get(key, 0) == want, (key, placed.get(key, 0), want)

    # HARD invariant 2: no class double-booked in any (day, hour).
    class_cell: dict = {}
    for (p, c, s, d, h), v in sol.items():
        if v == 1:
            class_cell[(c, d, h)] = class_cell.get((c, d, h), 0) + 1
    assert all(n <= 1 for n in class_cell.values()), "class double-booked"

    # HARD invariant 3: no teacher double-booked in any (day, hour).
    teacher_cell: dict = {}
    for (p, c, s, d, h), v in sol.items():
        if v == 1:
            teacher_cell[(p, d, h)] = teacher_cell.get((p, d, h), 0) + 1
    assert all(n <= 1 for n in teacher_cell.values()), "teacher double-booked"
