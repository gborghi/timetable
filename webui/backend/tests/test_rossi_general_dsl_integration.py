"""End-to-end integration test for the user's 'Rossi' use case.

Two HARD GeneralConstraint rows saved on a per-teacher scope, then
verified end-to-end across the four fixes:

  (a) "Rossi: 3 ore Fisica in 3A NON in giorni consecutivi"
      Uses the new ``consecutive_days(d1, d2)`` predicate (Fix 3).

  (b) "Rossi: 3 ore Fisica in 3C tutte stesso giorno con almeno una
      coppia consecutiva"
      Uses the existing ``same_day`` / ``consecutive`` predicates,
      composed via the per-teacher general DSL editor (Fix 2).

The test exercises the full pipeline:

  1. POST /api/constraints/general saves the rows with
     scope=teacher + owner_id (the route exposed in the teacher
     edit modal by Fix 2).
  2. ``dsl_translator.load_all_dsl_constraints`` aggregates the
     8th source (GeneralConstraint -- Fix 1) alongside the
     existing 7 tables.
  3. ``MonolithicSolver.add_dsl_constraint`` routes the parsed
     AST through the compile-time evaluator
     (engine/dsl_to_cpsat.py:_eval_static_call -- Fix 3 +
     compile-time arithmetic from Fix 4 not exercised here but
     loaded), so a dc that violates (a) is rejected during
     CP-SAT search rather than discovered post-hoc.
  4. ``metaheuristics.is_hard_feasible(sol, profs,
     dsl_hard_expressions=[...])`` confirms the rendered solution
     satisfies the rules under the post-hoc evaluator (the path
     used by Feasibility Check + the cascade of metaheuristics).
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


# ---------- DSL strings for the two Rossi rules ----------

DSL_A_NO_CONSECUTIVE_DAYS = (
    'forall l1 in lessons where l1.teacher == Rossi and '
    'l1.class == 3A and l1.subject == Fisica: '
    'forall l2 in lessons where l2.teacher == Rossi and '
    'l2.class == 3A and l2.subject == Fisica: '
    '(l1.day == l2.day) or not consecutive_days(l1.day, l2.day)'
)

# (b) "all 3 hours of (Rossi, 3C, Fisica) on the same day" — compiled
# as a forall-forall body that emits forbid-pair constraints when
# the static body (``same_day(l1, l2)``) is False. With 3 candidate
# lessons all required to be selected, this forces the 3 picks
# onto a single day.
#
# The user's original (b) also asks for ``consecutive(l1, l2)``
# pair-wise across the 3 hours. The strict double-forall form is
# infeasible for n>=3 (it would require every pair to be adjacent,
# which {h, h+1, h+2} doesn't satisfy for the (h, h+2) pair). The
# canonical way to express "n hours in one consecutive window" is
# ``subject_pair_must`` (the n=2 pragma) or a dedicated n-block
# pragma (TODO(audit) at the engine level). For this integration test we
# pin the same-day part as the new general-DSL feature; the
# consecutive-hours part is verified separately via the n=2 form
# in test_compile_time_3c_pair_consecutive_n2.
# Note on argument shape: the compile-time static evaluator
# (engine/dsl_to_cpsat.py:_eval_static_call) implements ``same_day``
# / ``consecutive`` for 2-tuple slot args (``l.slot`` -> (day, hour))
# rather than for the full 5-tuple slot key. The post-hoc evaluator
# in webui/backend/utils/general_dsl.py accepts both forms. We use
# ``l1.slot`` here so the same expression works in BOTH evaluators.
DSL_B_SAME_DAY = (
    'forall l1 in lessons where l1.teacher == Rossi and '
    'l1.class == 3C and l1.subject == Fisica: '
    'forall l2 in lessons where l2.teacher == Rossi and '
    'l2.class == 3C and l2.subject == Fisica: '
    'same_day(l1.slot, l2.slot)'
)
DSL_B_PAIR_CONSECUTIVE_N2 = (
    'forall l1 in lessons where l1.teacher == Rossi and '
    'l1.class == 3C and l1.subject == Fisica: '
    'forall l2 in lessons where l2.teacher == Rossi and '
    'l2.class == 3C and l2.subject == Fisica: '
    'consecutive(l1.slot, l2.slot)'
)


# ---------- Fixture: temp DB + 2 GeneralConstraints saved via API ----------


@pytest.fixture
def rossi_db_with_constraints(app_with_temp_db):
    """Persists Rossi + 2 GeneralConstraint rows (scope=teacher) via
    the /api/constraints/general POST endpoint -- the same path the
    Fix-2 teacher panel uses."""
    from fastapi.testclient import TestClient
    from webui.backend import models
    app, TestSession = app_with_temp_db
    client = TestClient(app)

    with TestSession() as db:
        rossi = models.Teacher(name="Rossi", max_hours=18)
        db.add(rossi); db.flush()
        rossi_id = rossi.id
        # Required entities so the dataset is coherent (the API only
        # validates the DSL expression itself, not entity FKs).
        db.add(models.SchoolClass(name="3A", year=3, section="A"))
        db.add(models.SchoolClass(name="3C", year=3, section="C"))
        db.add(models.Subject(name="Fisica"))
        db.commit()

    # POST the 3 constraints via the API.
    payloads = [
        {"expression": DSL_A_NO_CONSECUTIVE_DAYS,
         "label": "(a) 3A non-consecutive days",
         "level": "hard", "weight": 0,
         "scope": "teacher", "owner_id": rossi_id},
        {"expression": DSL_B_SAME_DAY,
         "label": "(b) 3C same-day",
         "level": "hard", "weight": 0,
         "scope": "teacher", "owner_id": rossi_id},
    ]
    created_ids = []
    for p in payloads:
        r = client.post("/api/constraints/general", json=p)
        assert r.status_code == 200, (p, r.text)
        created_ids.append(r.json()["id"])

    return {
        "client": client,
        "TestSession": TestSession,
        "rossi_id": rossi_id,
        "constraint_ids": created_ids,
    }


# ---------- Step 1: API persistence + loader integration (Fix 1 + 2) ----


def test_api_persists_then_loader_picks_up_general_constraints(
    rossi_db_with_constraints,
):
    """The rows POSTed via /api/constraints/general appear in
    load_all_dsl_constraints under source='general_constraint' and
    scope_kind='teacher'. Confirms Fix 1's loader entry is wired up
    correctly when the rows arrive through the API path that Fix 2
    exposes from the teacher tab."""
    import dsl_translator as dt
    TS = rossi_db_with_constraints["TestSession"]
    rossi_id = rossi_db_with_constraints["rossi_id"]
    with TS() as db:
        rules = dt.load_all_dsl_constraints(db)
    gc_rules = [r for r in rules if r["source"] == "general_constraint"]
    assert len(gc_rules) == 2, gc_rules
    assert all(r["scope_kind"] == "teacher" for r in gc_rules), gc_rules
    assert all(r["scope_id"] == rossi_id for r in gc_rules), gc_rules
    # All expressions parse cleanly (the one requiring Fix 3's
    # consecutive_days predicate exercises the new builtin).
    from webui.backend.utils import general_dsl as gd
    for r in gc_rules:
        gd.parse(r["expression"])


# ---------- Step 2: compile-time enforcement (Fix 3 + 4) ----


def _build_solver(profs, dc):
    """Build a MonolithicSolver with the canonical Phase B HARD
    constraints disabled where they would interfere with this
    minimal scenario. h3 + no_holes are tested elsewhere."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    return MonolithicSolver(profs, dc, ConstraintConfig(
        enforce_no_holes=False,
        enforce_h3_presence_at_11=False,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=False))


def test_compile_time_blocks_consecutive_day_dc_for_3a():
    """With dc placing 3A Fisica on consecutive days (1, 2, 3), the
    constraint (a) ``not consecutive_days(l1.day, l2.day)`` makes
    the model INFEASIBLE -- proving the rule is enforced during
    CP-SAT search, not just discovered post-hoc.

    This is the negative test for the compile-time path.
    """
    profs = {"Rossi": {
        "classi": {"3A": {"Fisica": {"ore": 3}}}, "max_hours": 18}}
    dc = {("Rossi", "3A", "Fisica", d): 1 for d in (1, 2, 3)}
    ms = _build_solver(profs, dc)
    ms.add_dsl_constraint(DSL_A_NO_CONSECUTIVE_DAYS)
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is None and status == "INFEASIBLE", (
        f"expected INFEASIBLE under consecutive-day dc; "
        f"got status={status} sol={sol}")


def test_compile_time_accepts_non_consecutive_day_dc_for_3a():
    """With dc placing 3A Fisica on non-consecutive days (1, 3, 5),
    the same compile-time constraint is satisfied and the solver
    returns a feasible solution.

    Positive test for the compile-time path.
    """
    profs = {"Rossi": {
        "classi": {"3A": {"Fisica": {"ore": 3}}}, "max_hours": 18}}
    dc = {("Rossi", "3A", "Fisica", d): 1 for d in (1, 3, 5)}
    ms = _build_solver(profs, dc)
    ms.add_dsl_constraint(DSL_A_NO_CONSECUTIVE_DAYS)
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    days = sorted({k[3] for k in sol if k[2] == "Fisica"})
    assert days == [1, 3, 5], (
        f"expected exactly days {{1,3,5}}; got {days}")


def test_compile_time_3c_same_day():
    """3C: with two-day flexible dc (1 hr on day 2, 2 hr on day 3),
    the same-day rule (b) makes the model INFEASIBLE because the
    forced split across days violates ``forall l1, l2: same_day``.

    Negative test for the same-day rule on day-spread input."""
    profs = {"Rossi": {
        "classi": {"3C": {"Fisica": {"ore": 3}}}, "max_hours": 18}}
    dc = {("Rossi", "3C", "Fisica", 2): 1,
          ("Rossi", "3C", "Fisica", 3): 2}
    ms = _build_solver(profs, dc)
    ms.add_dsl_constraint(DSL_B_SAME_DAY)
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is None and status == "INFEASIBLE", (
        f"expected INFEASIBLE under split-day dc; got status={status}")


def test_compile_time_3c_pair_consecutive_n2():
    """The strict double-forall ``consecutive(l1.slot, l2.slot)``
    works for n=2 (every pair of 2 lessons is the only pair, so
    "every pair consecutive" reduces to "the one pair is
    consecutive"). With dc placing 2 hr on day 2, the rule forces
    those 2 hours adjacent.

    Pins the n=2 behaviour. The n>=3 form is infeasible by design
    (every pair includes (h, h+2)) and a future block-pragma is
    follow-up work."""
    profs = {"Rossi": {
        "classi": {"3C": {"Fisica": {"ore": 2}}}, "max_hours": 18}}
    dc = {("Rossi", "3C", "Fisica", 2): 2}
    ms = _build_solver(profs, dc)
    ms.add_dsl_constraint(DSL_B_PAIR_CONSECUTIVE_N2)
    sol, status = ms.solve(time_limit_s=5.0, workers=1)
    assert sol is not None, status
    hours = sorted({k[4] for k in sol if k[3] == 2})
    assert len(hours) == 2 and hours[1] - hours[0] == 1, (
        f"pair-consecutive not enforced; got hours {hours}")


# ---------- Step 3: combined (a) + (b) end-to-end + post-hoc ----


def test_full_rossi_solution_passes_post_hoc_evaluator(
    rossi_db_with_constraints,
):
    """Combined scenario: 2 HARD GeneralConstraint rows (saved via
    the API in the fixture), loaded via load_all_dsl_constraints,
    compiled at search time. Resulting solution is then evaluated
    post-hoc via the same path Feasibility Check / metaheuristics
    use (``_build_world_from_sol`` + ``general_dsl.evaluate``).

    The canonical Phase B HARD checks of ``is_hard_feasible`` (H1..
    H4 / H_A / H_B / H_C) are tested elsewhere; this test focuses
    on the DSL path: whether the evaluator agrees with the
    compile-time decision the solver made.
    """
    import dsl_translator as dt
    import metaheuristics as meta
    from webui.backend.utils import general_dsl as gd

    TS = rossi_db_with_constraints["TestSession"]
    with TS() as db:
        rules = dt.load_all_dsl_constraints(db)
    gc_exprs = [r["expression"] for r in rules
                 if r["source"] == "general_constraint"]
    assert len(gc_exprs) == 2, gc_exprs

    # 3A on non-consecutive days, 3C all on day 2.
    profs = {"Rossi": {
        "classi": {
            "3A": {"Fisica": {"ore": 3}},
            "3C": {"Fisica": {"ore": 3}},
        },
        "max_hours": 18,
    }}
    dc = {("Rossi", "3A", "Fisica", 1): 1,
          ("Rossi", "3A", "Fisica", 3): 1,
          ("Rossi", "3A", "Fisica", 5): 1,
          ("Rossi", "3C", "Fisica", 2): 3}
    ms = _build_solver(profs, dc)
    for expr in gc_exprs:
        ms.add_dsl_constraint(expr)
    sol, status = ms.solve(time_limit_s=15.0, workers=1)
    assert sol is not None, status

    # 3A: days {1, 3, 5}, no consecutive pair.
    days_3a = sorted({k[3] for k in sol if k[1] == "3A"})
    assert days_3a == [1, 3, 5], days_3a
    for i in range(len(days_3a) - 1):
        assert days_3a[i + 1] - days_3a[i] >= 2, days_3a

    # 3C: all 3 hours on day 2 (forced by dc + same-day rule).
    sl_3c = sorted([k[4] for k in sol if k[1] == "3C" and k[3] == 2])
    assert len(sl_3c) == 3, sl_3c

    # Post-hoc DSL evaluation: build the world from the solver's
    # output and confirm every saved rule evaluates to True. This
    # is the same evaluator chain Feasibility Check uses.
    world = meta._build_world_from_sol(sol, profs)
    for expr in gc_exprs:
        tree = gd.parse(expr)
        ok = gd.evaluate(tree, world)
        assert ok is True, (
            f"post-hoc evaluator rejected expression the compile-"
            f"time accepted -- evaluator/compiler divergence: {expr}")


def test_post_hoc_evaluator_rejects_constructed_violation(
    rossi_db_with_constraints,
):
    """Construct an INVALID solution by hand (3A days are 1 and 2,
    which violates rule (a)) and verify the post-hoc evaluator
    flags it. This is the negative test for the evaluator path
    that mirrors the compile-time INFEASIBLE result of
    test_compile_time_blocks_consecutive_day_dc_for_3a."""
    import dsl_translator as dt
    import metaheuristics as meta

    TS = rossi_db_with_constraints["TestSession"]
    with TS() as db:
        rules = dt.load_all_dsl_constraints(db)
    gc_exprs = [r["expression"] for r in rules
                 if r["source"] == "general_constraint"]

    profs = {"Rossi": {
        "classi": {"3A": {"Fisica": {"ore": 3}},
                    "3C": {"Fisica": {"ore": 3}}},
        "max_hours": 18,
    }}
    # Hand-built violating solution: 3A on days {1, 2, 3} (consecutive!).
    bad_sol = {
        ("Rossi", "3A", "Fisica", 1, 8): 1,
        ("Rossi", "3A", "Fisica", 2, 8): 1,
        ("Rossi", "3A", "Fisica", 3, 8): 1,
        ("Rossi", "3C", "Fisica", 4, 8): 1,
        ("Rossi", "3C", "Fisica", 4, 9): 1,
        ("Rossi", "3C", "Fisica", 4, 10): 1,
    }
    feasible = meta.is_hard_feasible(
        bad_sol, profs, dsl_hard_expressions=gc_exprs, verbose=False)
    assert feasible is False, (
        "post-hoc evaluator failed to reject 3A on consecutive "
        "days; rule (a) not enforced through the evaluator path")
