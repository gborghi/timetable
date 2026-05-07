"""Phase 3 integration tests -- ``cp_sat_scope='week'`` path.

Covers the three (cp_sat_scope, phase_a_mode) combinations supported by
the schema validator + ``run_phase_b`` + ``_solve_phase_b_week``:

* ``week + skip``         -- pure week solver, no Phase A
* ``week + soft_hint``    -- Phase A runs, dc_value pushed via AddHint
* ``week + always``       -- forbidden (validator + run_phase_b raise)

Plus the OO ``MonolithicSolver(dc_value=None, scope=None)`` direct path
to keep the engine-level surface covered without going through the
DB-backed pipeline (which needs init_db + DB fixtures).

These tests exercise small 3-class scenarios so each finishes in
seconds; they are NOT marked slow.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


# ============================================================
# Fixtures
# ============================================================


def _profs_3_classes():
    """3 classes, each with Mat (5h) + Ita (5h) + Sto (3h) = 13h/week
    per class; one teacher per (class, subject). 9 cattedre, 39 hours
    fitting in 36 cells per class -> tight but feasible. Uses
    Matematica + Italiano so the pair_exists rule (HARD) kicks in for
    each class on >=2h days."""
    profs: dict = {}
    for cl in ("1A", "1B", "1C"):
        profs[f"TM_{cl}"] = {
            "classi": {cl: {"Matematica": {"ore": 5}}},
            "max_hours": 18,
        }
        profs[f"TI_{cl}"] = {
            "classi": {cl: {"Italiano": {"ore": 5}}},
            "max_hours": 18,
        }
        profs[f"TS_{cl}"] = {
            "classi": {cl: {"Storia": {"ore": 3}}},
            "max_hours": 18,
        }
    return profs


def _config(**kw):
    from cp_sat_constraint_model import ConstraintConfig
    base = dict(
        enforce_no_holes=True,
        enforce_h3_presence_at_11=True,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=True,
    )
    base.update(kw)
    return ConstraintConfig(**base)


# ============================================================
# Engine-level: MonolithicSolver(dc_value=None, scope=None)
# ============================================================


def test_week_solver_skip_phase_a_feasible():
    """``MonolithicSolver(dc_value=None, scope=None)`` solves the
    full week from scratch and returns a HARD-feasible solution."""
    from cp_sat_constraint_model import MonolithicSolver

    profs = _profs_3_classes()
    cfg = _config()
    ms = MonolithicSolver(profs, dc_value=None, config=cfg, scope=None)
    assert ms.weekly_mode is True
    # Each cattedra: 6 days * 6 hours = 36 slot vars per cattedra, 9
    # cattedre -> 324 slot vars total.
    assert len(ms.slot) == 9 * 36
    # day_count_for_hint: 9 cattedre * 6 days = 54 IntVars for AddHint.
    assert len(ms.day_count_for_hint) == 9 * 6
    sol, status = ms.solve(time_limit_s=20, workers=2, log=False)
    assert status in ("OPTIMAL", "FEASIBLE"), status
    assert sol is not None and len(sol) > 0
    # HARD-feasibility: each cattedra has exactly its weekly ore.
    by_tcs: dict = {}
    for (t, c, s, _d, _h), v in sol.items():
        by_tcs[(t, c, s)] = by_tcs.get((t, c, s), 0) + 1
    expected = {
        ("TM_1A", "1A", "Matematica"): 5,
        ("TI_1A", "1A", "Italiano"): 5,
        ("TS_1A", "1A", "Storia"): 3,
        ("TM_1B", "1B", "Matematica"): 5,
        ("TI_1B", "1B", "Italiano"): 5,
        ("TS_1B", "1B", "Storia"): 3,
        ("TM_1C", "1C", "Matematica"): 5,
        ("TI_1C", "1C", "Italiano"): 5,
        ("TS_1C", "1C", "Storia"): 3,
    }
    assert by_tcs == expected


def test_week_solver_pair_exists_reified():
    """When the week solver picks a day distribution that places >=2h
    of Mat (or Ita) on the same day, the reified pair_exists rule
    forces at least one consecutive pair. Verify on every active
    (teacher, class, day) with >= 2 hours."""
    from cp_sat_constraint_model import MonolithicSolver

    profs = _profs_3_classes()
    cfg = _config()
    ms = MonolithicSolver(profs, dc_value=None, config=cfg, scope=None)
    sol, status = ms.solve(time_limit_s=20, workers=2, log=False)
    assert status in ("OPTIMAL", "FEASIBLE"), status
    by_tcsd: dict = {}
    for (t, c, s, d, h), v in sol.items():
        if s in ("Matematica", "Italiano"):
            by_tcsd.setdefault((t, c, s, d), []).append(h)
    violations = []
    for k, hours in by_tcsd.items():
        if len(hours) < 2:
            continue
        hsorted = sorted(hours)
        has_consec = any(hsorted[i + 1] == hsorted[i] + 1
                          for i in range(len(hsorted) - 1))
        if not has_consec:
            violations.append((k, hours))
    assert not violations, violations


def test_week_solver_motorie_pair_reified():
    """Scienzemotorie must_pair: on days with exactly 2 Motorie hours,
    the two hours MUST be consecutive (reified is_two gate)."""
    from cp_sat_constraint_model import MonolithicSolver
    profs = {
        "TMot": {
            "classi": {"1A": {"Scienzemotorie": {"ore": 4}}},
            "max_hours": 18,
        },
    }
    cfg = _config(enforce_motorie_pair=True,
                   enforce_math_italian_pair=False,
                   enforce_h3_presence_at_11=False)
    ms = MonolithicSolver(profs, dc_value=None, config=cfg, scope=None)
    sol, status = ms.solve(time_limit_s=10, workers=2, log=False)
    assert status in ("OPTIMAL", "FEASIBLE"), status
    by_d: dict = {}
    for (_t, _c, _s, d, h), v in sol.items():
        by_d.setdefault(d, []).append(h)
    # Every day with exactly 2 hours must have them consecutive.
    for d, hs in by_d.items():
        if len(hs) == 2:
            a, b = sorted(hs)
            assert b == a + 1, f"day {d}: {hs} not consecutive"


def test_week_solver_phase_a_hint_warmstart():
    """phase_a_mode='soft_hint' warm path: produce a Phase A solution
    via DayCountModel and push it through ``add_phase_a_hint``. The
    hint is best-effort -- the assertion is only that AddHint
    succeeds and returns the expected hint count."""
    from cp_sat_constraint_model import (
        DayCountModel, MonolithicSolver)

    profs = _profs_3_classes()
    cfg = _config()
    # Phase A
    dcm = DayCountModel(profs, config=cfg)
    dc_value, status = dcm.solve(time_limit_s=10, workers=2, log=False)
    assert status in ("OPTIMAL", "FEASIBLE"), status
    assert dc_value, "Phase A must produce non-empty dc_value"
    # Week solver in skip mode + AddHint
    ms = MonolithicSolver(profs, dc_value=None, config=cfg, scope=None)
    n = ms.add_phase_a_hint(dc_value)
    # Every (t, cl, s, d) in dc_value with positive hours should hit a
    # day_count_for_hint slot.
    n_positive = sum(1 for v in dc_value.values() if v > 0)
    assert n == n_positive, (
        f"hinted {n}, expected {n_positive} positive dc_value entries")
    sol, status = ms.solve(time_limit_s=20, workers=2, log=False)
    assert status in ("OPTIMAL", "FEASIBLE"), status
    assert sol


def test_week_solver_no_hint_in_day_mode():
    """``add_phase_a_hint`` is a no-op when the model isn't in weekly
    mode (e.g. legacy Phase B per-day path). Returns 0."""
    from cp_sat_constraint_model import MonolithicSolver
    profs = {"T": {"classi": {"1A": {"Mat": {"ore": 1}}}, "max_hours": 18}}
    dc = {("T", "1A", "Mat", 1): 1}
    cfg = _config(enforce_motorie_pair=False,
                   enforce_math_italian_pair=False,
                   enforce_h3_presence_at_11=False)
    ms = MonolithicSolver(profs, dc, cfg)
    assert ms.weekly_mode is False
    n = ms.add_phase_a_hint({("T", "1A", "Mat", 1): 1})
    assert n == 0


# ============================================================
# Schema validation
# ============================================================


def test_phase_b_schema_week_skip():
    from webui.backend.schemas import PhaseBRunIn
    m = PhaseBRunIn(cp_sat_scope="week", phase_a_mode="skip")
    assert m.cp_sat_scope == "week"
    assert m.phase_a_mode == "skip"


def test_phase_b_schema_week_soft_hint():
    from webui.backend.schemas import PhaseBRunIn
    m = PhaseBRunIn(cp_sat_scope="week", phase_a_mode="soft_hint")
    assert m.cp_sat_scope == "week"
    assert m.phase_a_mode == "soft_hint"


def test_phase_b_schema_week_always_rejected():
    from webui.backend.schemas import PhaseBRunIn
    with pytest.raises(ValueError) as exc:
        PhaseBRunIn(cp_sat_scope="week", phase_a_mode="always")
    assert "incompatible" in str(exc.value).lower()


def test_phase_b_schema_day_skip_rejected():
    from webui.backend.schemas import PhaseBRunIn
    with pytest.raises(ValueError) as exc:
        PhaseBRunIn(cp_sat_scope="day", phase_a_mode="skip")
    assert "requires phase_a_mode='always'" in str(exc.value)


def test_phase_b_schema_unknown_scope():
    from webui.backend.schemas import PhaseBRunIn
    with pytest.raises(ValueError):
        PhaseBRunIn(cp_sat_scope="month")


def test_phase_b_schema_unknown_mode():
    from webui.backend.schemas import PhaseBRunIn
    with pytest.raises(ValueError):
        PhaseBRunIn(phase_a_mode="hint_hard")


# ============================================================
# Programmatic run_phase_b validation (no DB / threads)
# ============================================================


def test_run_phase_b_rejects_week_always():
    """``run_phase_b`` mirrors the schema validator so harness /
    full-pipeline callers get the same guard. The validation runs
    BEFORE any thread is started, so this never reaches the engine."""
    from webui.backend.optimization import run_phase_b
    with pytest.raises(ValueError) as exc:
        run_phase_b(
            k=4, time_a=1.0, time_bridges=1.0, time_cluster=1.0,
            time_ricucitura=1.0, time_mono=1.0, workers=1, log=False,
            cp_sat_scope="week", phase_a_mode="always",
        )
    assert "incompatible" in str(exc.value).lower()


def test_run_phase_b_rejects_day_skip():
    from webui.backend.optimization import run_phase_b
    with pytest.raises(ValueError) as exc:
        run_phase_b(
            k=4, time_a=1.0, time_bridges=1.0, time_cluster=1.0,
            time_ricucitura=1.0, time_mono=1.0, workers=1, log=False,
            cp_sat_scope="day", phase_a_mode="soft_hint",
        )
    assert "requires phase_a_mode='always'" in str(exc.value)


def test_run_phase_b_rejects_bad_values():
    from webui.backend.optimization import run_phase_b
    with pytest.raises(ValueError):
        run_phase_b(
            k=4, time_a=1.0, time_bridges=1.0, time_cluster=1.0,
            time_ricucitura=1.0, time_mono=1.0, workers=1, log=False,
            cp_sat_scope="century",
        )
    with pytest.raises(ValueError):
        run_phase_b(
            k=4, time_a=1.0, time_bridges=1.0, time_cluster=1.0,
            time_ricucitura=1.0, time_mono=1.0, workers=1, log=False,
            phase_a_mode="meditate",
        )


# ============================================================
# Cross-mode parity: week vs default-day for tiny scenario
# ============================================================


def test_week_and_day_both_feasible_tiny():
    """Tiny scenario solved by BOTH (a) the legacy day-mode pipeline
    and (b) the week solver -- both must produce HARD-feasible
    solutions with the right total hours per cattedra."""
    import cpsat_v2_timetable as cv2  # type: ignore
    from cp_sat_constraint_model import MonolithicSolver

    profs = _profs_3_classes()

    # (a) day-mode reference: legacy Phase A + per-day mono
    classes_v, triples, class_profs = cv2.build_indices(profs)
    dc = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=10, workers=2, log=False,
    )
    full_day: dict = {}
    for d in cv2.DAYS:
        out, _ = cv2.solve_phase_b_for_day(
            d, profs, classes_v, triples, class_profs, dc,
            time_limit=10, workers=2, log=False,
        )
        if out:
            full_day.update(out)
    assert full_day, "day-mode produced empty solution"

    # (b) week-mode
    cfg = _config()
    ms = MonolithicSolver(profs, dc_value=None, config=cfg, scope=None)
    sol_week, status = ms.solve(time_limit_s=20, workers=2, log=False)
    assert status in ("OPTIMAL", "FEASIBLE"), status

    # Both must conserve total hours per cattedra. Legacy day-mode
    # ``solve_phase_b_for_day`` returns a dense dict (slot values 0
    # AND 1); the OO solver returns only the active 1-valued entries.
    # Filter to active hours before counting.
    def _ore_per_tcs(sol):
        out = {}
        for (t, c, s, _d, _h), v in sol.items():
            if not v:
                continue
            out[(t, c, s)] = out.get((t, c, s), 0) + 1
        return out

    assert _ore_per_tcs(full_day) == _ore_per_tcs(sol_week)
