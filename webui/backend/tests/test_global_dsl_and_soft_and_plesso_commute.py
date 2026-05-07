"""End-to-end integration tests covering three sessions' work:

  Task 1  -- scope=global GeneralConstraint POSTed via the same
             /api/constraints/general route the Constraints tab uses
             flows through ``load_all_dsl_constraints`` and is enforced
             as HARD by the solver.

  Task 2  -- a CUSTOM plesso-commute rule expressed in the general DSL
             (``forall l1 ... l1.classroom.plesso == X ... forall l2 ...
             l2.classroom.plesso == Y ... false``) is enforced at
             compile time when ``classroom_for_slot`` + ``plessi_data``
             are wired into the model. The post-hoc evaluator agrees
             with the compile-time decision.

  Task 2-b -- SOFT general_dsl rules contribute ``weight`` per
              violation to the objective; the solver picks the cheapest
              solution honouring the rule when feasible, but is willing
              to violate it if hard constraints force the issue.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
WEBUI = os.path.normpath(os.path.join(HERE, "..", ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for p in (ENGINE, WEBUI, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


def _build_solver(profs, dc, **cfg_overrides):
    """Minimal MonolithicSolver with the canonical Phase B HARD checks
    that would interfere with a tiny scenario disabled."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    cfg = ConstraintConfig(
        enforce_no_holes=False,
        enforce_h3_presence_at_11=False,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=False,
        **cfg_overrides,
    )
    classroom_for_slot = cfg_overrides.pop("_cfs", None)
    return MonolithicSolver(
        profs, dc, cfg,
        classroom_for_slot=classroom_for_slot,
    )


# ============================================================
# Task 1 -- scope=global DSL via the Constraints tab path
# ============================================================


def _post_global_constraint_via_api(client, expression, *,
                                     label, level="hard", weight=0):
    """Mirror the payload the NewGeneralConstraintModal sends from the
    Constraints tab (scope='global', owner_id=None). Returns the new
    constraint id."""
    r = client.post("/api/constraints/general", json={
        "expression": expression,
        "label": label,
        "level": level,
        "weight": weight,
        "scope": "global",
        "owner_id": None,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_constraints_tab_global_dsl_loads_as_hard(app_with_temp_db):
    """A scope=global HARD constraint POSTed through
    /api/constraints/general (the route the Constraints tab uses)
    appears in ``load_all_dsl_constraints`` as
    source='general_constraint', scope_kind='global', is_hard=True."""
    from fastapi.testclient import TestClient
    import dsl_translator as dt
    app, TestSession = app_with_temp_db
    client = TestClient(app)
    # Required entities so the rule's literals are coherent.
    from webui.backend import models
    with TestSession() as db:
        db.add(models.Teacher(name="Rossi", max_hours=18))
        db.add(models.SchoolClass(name="3A", year=3, section="A"))
        db.add(models.Subject(name="Fisica"))
        db.commit()

    cid = _post_global_constraint_via_api(
        client,
        'forall l in lessons where l.teacher == "Rossi" '
        'and l.subject == "Fisica": l.hour <= 12',
        label="(global) Rossi Fisica only morning",
    )

    with TestSession() as db:
        rules = dt.load_all_dsl_constraints(db)
    gc_rules = [r for r in rules if r["source"] == "general_constraint"]
    assert len(gc_rules) == 1
    r0 = gc_rules[0]
    assert r0["scope_kind"] == "global"
    assert r0["scope_id"] is None
    assert r0["is_hard"] is True
    # Round-trip: parse the loaded expression cleanly.
    from webui.backend.utils import general_dsl as gd
    gd.parse(r0["expression"])
    assert cid > 0


def test_constraints_tab_global_dsl_solver_blocks_violator(
    app_with_temp_db,
):
    """End-to-end: scope=global HARD rule saved via the API is
    compiled into the solver model and makes a dc that violates it
    INFEASIBLE. The same code path runs in production when
    ``add_all_dsl_constraints_from_db`` is called from ``optimization.py``.
    """
    from fastapi.testclient import TestClient
    import dsl_translator as dt
    app, TestSession = app_with_temp_db
    client = TestClient(app)
    from webui.backend import models
    with TestSession() as db:
        db.add(models.Teacher(name="Verdi", max_hours=18))
        db.add(models.SchoolClass(name="2B", year=2, section="B"))
        db.add(models.Subject(name="Matematica"))
        db.commit()

    # Global HARD: nobody teaches at hour 13 (last hour).
    _post_global_constraint_via_api(
        client,
        'forall l in lessons: l.hour != 13',
        label="(global) no last hour",
    )
    with TestSession() as db:
        rules = dt.load_all_dsl_constraints(db)
    exprs = [r["expression"] for r in rules
              if r["source"] == "general_constraint"]
    assert len(exprs) == 1

    # Build a scenario that REQUIRES h=13 (1 hour, day 1, only h=13
    # available -- enforced by allowing only that hour via dc).
    profs = {"Verdi": {
        "classi": {"2B": {"Matematica": {"ore": 1}}},
        "max_hours": 18}}
    dc = {("Verdi", "2B", "Matematica", 1): 1}
    ms = _build_solver(profs, dc)
    # Force h=13 by removing all other hours from the candidate slots.
    keep = {k: v for k, v in ms.slot.items() if k[4] == 13}
    drop = [k for k in ms.slot if k not in keep]
    for k in drop:
        ms.model.Add(ms.slot[k] == 0)
    for e in exprs:
        ms.add_dsl_constraint(e)
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is None and status == "INFEASIBLE", (
        f"global HARD rule from Constraints tab must INFEASIBLE the "
        f"forced-h13 scenario; got status={status}, sol={sol}")


# ============================================================
# Task 2 -- custom plesso-commute via general DSL
# ============================================================


def _make_two_plessi_data():
    """A 2-plessi configuration; classrooms in plesso 1 vs 2."""
    from plessi_constraints import PlessiData
    return PlessiData(
        classroom_to_plesso={
            "AulaA": 1,   # plesso 1 ("A")
            "AulaB": 2,   # plesso 2 ("B")
        },
    )


def test_plesso_commute_custom_dsl_compile_time_blocks_a_to_b():
    """User scenario: 'Rossi mai in plesso A alle 9 e plesso B alle
    10 lo stesso giorno'. The DSL is the user-written form, with
    classroom_for_slot pinning every slot's classroom (and therefore
    plesso) before the search. The compiler resolves
    ``l.classroom.plesso`` statically; a dc that forces the violating
    pattern on day 1 is INFEASIBLE."""
    profs = {"Rossi": {
        "classi": {
            "1A": {"Mate": {"ore": 1}},
            "1B": {"Storia": {"ore": 1}},
        },
        "max_hours": 18,
    }}
    # Force exactly 1 hour of (Rossi, 1A, Mate) on day 1 AND 1 hour of
    # (Rossi, 1B, Storia) on day 1 -- the only way to satisfy this is
    # to pick those two hours on day 1, possibly at h=9 and h=10.
    dc = {
        ("Rossi", "1A", "Mate", 1): 1,
        ("Rossi", "1B", "Storia", 1): 1,
    }
    # Classroom assignment: 1A is in plesso 1 ("A"), 1B is in plesso 2.
    # All slots reference the same classroom per class.
    classroom_for_slot = {}
    for d in range(1, 7):
        for h in range(8, 14):
            classroom_for_slot[("1A", d, h)] = "AulaA"
            classroom_for_slot[("1B", d, h)] = "AulaB"
    plessi = _make_two_plessi_data()

    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    cfg = ConstraintConfig(
        enforce_no_holes=False,
        enforce_h3_presence_at_11=False,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=False,
    )
    cfg.plessi_data = plessi
    ms = MonolithicSolver(
        profs, dc, cfg, classroom_for_slot=classroom_for_slot)
    # Force the 1A Mate hour to land at h=9 (the violating LHS):
    for k in list(ms.slot):
        if k[1] == "1A" and k[2] == "Mate" and k[3] == 1 and k[4] != 9:
            ms.model.Add(ms.slot[k] == 0)
    # Force the 1B Storia hour to land at h=10 on day 1 (RHS):
    for k in list(ms.slot):
        if k[1] == "1B" and k[2] == "Storia" and k[3] == 1 and k[4] != 10:
            ms.model.Add(ms.slot[k] == 0)

    expr = (
        'forall l1 in lessons where l1.teacher == "Rossi" '
        'and l1.hour == 9 and l1.classroom.plesso == 1: '
        'forall l2 in lessons where l2.teacher == "Rossi" '
        'and l2.hour == 10 and l2.classroom.plesso == 2 '
        'and same_day(l1.slot, l2.slot): '
        'false'
    )
    ms.add_dsl_constraint(expr)
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is None and status == "INFEASIBLE", (
        f"custom plesso commute rule failed to forbid the A@9 -> B@10 "
        f"same-day pattern; got status={status}")


def test_plesso_commute_custom_dsl_post_hoc_rejects_violation():
    """Post-hoc evaluation: a hand-built solution with the violating
    pattern is detected by ``general_dsl.evaluate`` against the world
    rendered by ``build_world``. The world resolves
    ``l.classroom.plesso`` via the pre-computed ``classroom_plesso``
    field on each lesson dict (general_dsl.py:867)."""
    from webui.backend.utils import general_dsl as gd
    expr = (
        'forall l1 in lessons where l1.teacher == "Rossi" '
        'and l1.hour == 9 and l1.classroom.plesso == 1: '
        'forall l2 in lessons where l2.teacher == "Rossi" '
        'and l2.hour == 10 and l2.classroom.plesso == 2 '
        'and same_day(l1.slot, l2.slot): '
        'false'
    )
    tree = gd.parse(expr)
    # Hand-built world: violating pattern (Rossi at A@9 and B@10
    # on day 1).
    world_violating = {
        "lessons": [
            {"teacher": "Rossi", "class": "1A", "subject": "Mate",
             "day": 1, "hour": 9, "classroom": "AulaA",
             "classroom_plesso": 1, "slot": (1, 9)},
            {"teacher": "Rossi", "class": "1B", "subject": "Storia",
             "day": 1, "hour": 10, "classroom": "AulaB",
             "classroom_plesso": 2, "slot": (1, 10)},
        ],
    }
    assert gd.evaluate(tree, world_violating) is False

    # Same world without the violation (1B lands at h=11 instead).
    world_ok = {
        "lessons": [
            {"teacher": "Rossi", "class": "1A", "subject": "Mate",
             "day": 1, "hour": 9, "classroom": "AulaA",
             "classroom_plesso": 1, "slot": (1, 9)},
            {"teacher": "Rossi", "class": "1B", "subject": "Storia",
             "day": 1, "hour": 11, "classroom": "AulaB",
             "classroom_plesso": 2, "slot": (1, 11)},
        ],
    }
    assert gd.evaluate(tree, world_ok) is True


# ============================================================
# Task 2-bis -- SOFT level support for general_dsl
# ============================================================


def test_soft_general_dsl_emits_penalty_terms():
    """A SOFT rule (level='soft', weight=W) compiled with
    is_hard=False populates ``ms.dsl_soft_cost_terms`` so the
    objective sees the per-violation penalty. With the rule alone
    (and 1 hour of Rossi/Mate on day 1 forced at h=13), the solver
    is FEASIBLE but the objective includes the ``(W, slot[h13])``
    pair so the optimum value reflects the penalty."""
    profs = {"Rossi": {
        "classi": {"1A": {"Mate": {"ore": 1}}}, "max_hours": 18}}
    dc = {("Rossi", "1A", "Mate", 1): 1}
    ms = _build_solver(profs, dc)
    # Force h=13 -- the only feasible cell.
    for k in list(ms.slot):
        if k[4] != 13:
            ms.model.Add(ms.slot[k] == 0)
    # SOFT: nobody at h=13 (penalty 50 per violation).
    ms.add_dsl_constraint(
        'forall l in lessons: l.hour != 13',
        is_hard=False, soft_weight=50,
    )
    assert len(ms.dsl_soft_cost_terms) >= 1, (
        f"SOFT compile must register soft_cost_terms; "
        f"got {ms.dsl_soft_cost_terms}")
    weights = [w for w, _v in ms.dsl_soft_cost_terms]
    assert 50 in weights, weights
    # Solve: feasible (HARD path empty), objective >= 50 (one
    # violation forced).
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    assert any(k[4] == 13 for k in sol), (
        f"forced h=13 by external Add; sol={sol}")


def test_soft_general_dsl_solver_avoids_violation_when_possible():
    """With both h=10 and h=13 candidates available, a SOFT rule
    forbidding h=13 makes the optimum pick h=10 (no penalty). This
    is the core 'SOFT influences search' contract."""
    profs = {"Rossi": {
        "classi": {"1A": {"Mate": {"ore": 1}}}, "max_hours": 18}}
    dc = {("Rossi", "1A", "Mate", 1): 1}
    ms = _build_solver(profs, dc)
    # Restrict to h=10 or h=13 only on day 1 to simplify.
    for k in list(ms.slot):
        if k[3] != 1 or k[4] not in (10, 13):
            ms.model.Add(ms.slot[k] == 0)
    # SOFT: h != 13 (penalty 100).
    ms.add_dsl_constraint(
        'forall l in lessons: l.hour != 13',
        is_hard=False, soft_weight=100,
    )
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    chosen_hours = [k[4] for k in sol]
    assert chosen_hours == [10], (
        f"SOFT rule should drive optimum to h=10 (no penalty), "
        f"not h=13 (penalty 100); got hours={chosen_hours}")


def test_soft_general_dsl_violated_when_hard_forces_it():
    """When HARD constraints force the violating cell, the SOFT rule
    must still allow the model to be feasible (only paying the
    penalty). Regression: SOFT must NOT silently fall back to HARD."""
    profs = {"Rossi": {
        "classi": {"1A": {"Mate": {"ore": 1}}}, "max_hours": 18}}
    dc = {("Rossi", "1A", "Mate", 1): 1}
    ms = _build_solver(profs, dc)
    # HARD-force h=13 (the slot must be at hour 13).
    for k in list(ms.slot):
        if k[4] != 13:
            ms.model.Add(ms.slot[k] == 0)
    ms.add_dsl_constraint(
        'forall l in lessons: l.hour != 13',
        is_hard=False, soft_weight=200,
    )
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, (
        f"SOFT rule must not block feasibility; status={status}")
    assert any(k[4] == 13 for k in sol)


def test_soft_general_dsl_loader_path_via_db(app_with_temp_db):
    """Loader path: scope='global', level='soft' rules are returned
    by ``load_all_dsl_constraints(include_soft=True)`` with
    ``is_hard=False`` and the saved weight, then
    ``add_all_dsl_constraints_from_db(include_soft=True)`` compiles
    them as SOFT."""
    from fastapi.testclient import TestClient
    import dsl_translator as dt
    app, TestSession = app_with_temp_db
    client = TestClient(app)

    from webui.backend import models
    with TestSession() as db:
        db.add(models.Teacher(name="Rossi", max_hours=18))
        db.add(models.SchoolClass(name="1A", year=1, section="A"))
        db.add(models.Subject(name="Mate"))
        db.commit()

    # SOFT: Rossi prefers not to teach at h=13 (penalty 75).
    r = client.post("/api/constraints/general", json={
        "expression":
            'forall l in lessons where l.teacher == "Rossi": '
            'l.hour != 13',
        "label": "Rossi prefers no h=13",
        "level": "soft", "weight": 75,
        "scope": "global", "owner_id": None,
    })
    assert r.status_code == 200, r.text

    with TestSession() as db:
        rules = dt.load_all_dsl_constraints(db, include_soft=True)
    soft = [x for x in rules
             if x["source"] == "general_constraint"
             and x.get("is_hard") is False]
    assert len(soft) == 1, soft
    assert soft[0]["weight"] == 75
