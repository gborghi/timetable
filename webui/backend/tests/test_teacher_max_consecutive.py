"""Tests for the ``teacher_max_consecutive`` canonical pragma.

``Teacher.max_consecutive`` is a HARD column ("max ore consecutive nel
giorno"). It must compile to a sliding-window CP-SAT constraint: in any
window of (n+1) consecutive hours on any day, the teacher occupies at
most n of them -- i.e. no run of (n+1) busy hours in a row.

Before this pragma existed the translator emitted a generic
nested-forall/count expression the compiler could not translate
(``count rhs dynamic; skipped``), so the constraint silently did not
bind.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
WEBUI = os.path.normpath(os.path.join(HERE, "..", ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for p in (ENGINE, WEBUI, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


def _make_solver(profs, dc, **cfg):
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    return MonolithicSolver(profs, dc, ConstraintConfig(**cfg))


def test_max_consecutive_forbids_run_over_cap():
    """4 contiguous hours (forced via no_holes; the proven-feasible
    baseline places them at 8-11) with a cap of 2 is INFEASIBLE: a run
    of 4 exceeds the cap."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 4}}}, "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 4}
    ms = _make_solver(profs, dc)
    ms.add_dsl_constraint('no_holes_class("1A")')
    ms.add_dsl_constraint('teacher_max_consecutive("T1", 2)')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is None, (
        f"expected INFEASIBLE (run of 4 contiguous > cap 2); got {status}")


def test_max_consecutive_allows_run_at_cap():
    """4 contiguous hours with a cap of 4 is FEASIBLE (run == cap)."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 4}}}, "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 4}
    ms = _make_solver(profs, dc)
    ms.add_dsl_constraint('no_holes_class("1A")')
    ms.add_dsl_constraint('teacher_max_consecutive("T1", 4)')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status


def test_max_consecutive_spreads_hours_to_avoid_run():
    """4 hours/day, cap 2, 6-hour grid, no-holes OFF so the hours are
    free to spread: a feasible solution exists and contains no run of 3
    consecutive busy hours."""
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 4}}}, "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 4}
    ms = _make_solver(profs, dc, enforce_no_holes=False)
    ms.add_dsl_constraint('teacher_max_consecutive("T1", 2)')
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    hours = sorted(k[4] for k in sol if k[3] == 1)
    for i in range(len(hours) - 2):
        assert not (hours[i + 1] == hours[i] + 1
                    and hours[i + 2] == hours[i] + 2), (
            f"found a run of 3 consecutive hours despite cap 2: {hours}")


def test_loader_emits_max_consecutive_pragma():
    """A Teacher row with max_consecutive set is translated into the
    canonical ``teacher_max_consecutive(name, n)`` HARD pragma by the
    unified loader (previously it emitted nothing for this column)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend import models
    from backend.db import Base
    from engine.dsl_translator import load_all_dsl_constraints

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    sess = Session()
    sess.add(models.Teacher(name="Rossi Mario", max_consecutive=3,
                            min_free_days=0))
    sess.commit()

    rules = load_all_dsl_constraints(sess, include_soft=False)
    matching = [r for r in rules
                if r["expression"] == 'teacher_max_consecutive("Rossi Mario", 3)']
    assert len(matching) == 1, [r["expression"] for r in rules]
    assert matching[0]["is_hard"] is True


def test_loader_skips_max_consecutive_when_non_binding():
    """max_consecutive >= 6 cannot bind on a 6-hour day, so the loader
    skips it to avoid flooding every solver with no-op constraints."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend import models
    from backend.db import Base
    from engine.dsl_translator import load_all_dsl_constraints

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    sess = Session()
    sess.add(models.Teacher(name="Bianchi Anna", max_consecutive=6,
                            min_free_days=0))
    sess.commit()

    rules = load_all_dsl_constraints(sess, include_soft=False)
    assert not any("teacher_max_consecutive" in r["expression"]
                   for r in rules), [r["expression"] for r in rules]
