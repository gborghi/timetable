from __future__ import annotations
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
WEBUI = os.path.normpath(os.path.join(HERE, "..", ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for p in (ENGINE, WEBUI, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from ortools.sat.python import cp_model


def test_sixth_slot_terms_one_per_slot_at_h13():
    """sixth_slot_terms emits exactly one (weight*var) term per slot var
    whose hour == 13, and none for other hours."""
    import soft_costs
    model = cp_model.CpModel()
    slot = {
        ("T1", "1A", "Mat", 1, 12): model.NewBoolVar("a"),
        ("T1", "1A", "Mat", 1, 13): model.NewBoolVar("b"),
        ("T1", "1B", "Mat", 1, 13): model.NewBoolVar("c"),
    }
    pairs, aux = soft_costs.sixth_slot_pairs(model, slot, weight=50, sixth_hour=13)
    # 2 slots at h13 -> 2 (weight, var) pairs; no aux vars in slot mode
    assert len(pairs) == 2
    assert all(w == 50 for w, _v in pairs)
    assert aux == []


def test_compute_soft_cost_expr_sixth_unchanged_after_delegation():
    """Smoke test (mode='default' only): after compute_soft_cost_expr was
    refactored to delegate its sixth-hour block to soft_costs, a
    MonolithicSolver built with mode='default' still produces a solvable
    model when its soft terms are minimized. This does NOT assert an
    objective-equality and does NOT exercise the phase_b_per_day path --
    the per-day path (sixth_class_busy_terms) is covered directly by
    test_sixth_class_busy_terms_aggregates_per_class_day below."""
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 6}}}, "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 6}
    ms = MonolithicSolver(profs, dc, ConstraintConfig(enforce_no_holes=False))
    terms, _ = ms.compute_soft_cost_expr(mode="default")
    ms.model.Minimize(sum(terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(ms.model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_sixth_class_busy_terms_aggregates_per_class_day():
    """Direct unit coverage for the extracted per-day encoder
    (mode='phase_b_per_day'), without the full solver. Pins the
    three-branch aggregation contract by calling the function with a
    fake busy_indicator_fn over real BoolVars:
      - empty busy list for a (class, day) -> skipped (no term, no aux)
      - exactly one indicator       -> used directly (no new aux var)
      - two+ indicators             -> one OR'd aux BoolVar + one term
    """
    import soft_costs
    model = cp_model.CpModel()
    i1 = model.NewBoolVar("i1")
    i2 = model.NewBoolVar("i2")
    busy = {
        ("1A", 1): [i1],        # single -> used directly, no aux
        ("1B", 1): [i1, i2],    # two -> one aux var
        ("1C", 1): [],          # empty -> skipped
    }
    classes = ["1A", "1B", "1C"]
    days = [1]
    terms, aux = soft_costs.sixth_class_busy_terms(
        model, lambda cl, d, h: busy[(cl, d)], classes, days,
        weight=5, sixth_hour=13)
    # 1A + 1B contribute a term; 1C (empty) is skipped.
    assert len(terms) == 2
    # Only the 2-indicator case (1B) created an OR aux BoolVar.
    assert len(aux) == 1
    # The single-indicator case reuses i1 directly (no fresh aux var),
    # so the lone aux var is distinct from both raw indicators.
    assert aux[0] is not i1
    assert aux[0] is not i2


def test_buchi_five_one_zero_drift_default_mode():
    """A teacher with a gappy day incurs a buchi penalty; the default
    mode also adds five/one. Solved objective must match before/after
    the extraction (guarded by the existing pinned suite; this asserts
    the model still builds and solves)."""
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 5}}}, "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 5}
    ms = MonolithicSolver(profs, dc, ConstraintConfig(enforce_no_holes=False))
    terms, aux = ms.compute_soft_cost_expr(mode="default")
    assert terms  # buchi + five present
    ms.model.Minimize(sum(terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    assert solver.Solve(ms.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_class_sixth_penalty_pragma_records_soft_terms():
    """The class_sixth_penalty(weight) pragma (slot mode) appends one
    soft term per slot at h13."""
    import dsl_to_cpsat as d2c
    from ortools.sat.python import cp_model
    model = cp_model.CpModel()
    slot = {
        ("T1", "1A", "Mat", 1, 13): model.NewBoolVar("a"),
        ("T1", "1A", "Mat", 1, 12): model.NewBoolVar("b"),
    }
    c = d2c.DSLConstraintCompiler(model, slot, level="phase_b")
    c.compile('class_sixth_penalty(50, "slot")')
    assert len(c.soft_cost_terms) == 1
    assert c.soft_cost_terms[0][0] == 50


def test_teacher_buchi_penalty_pragma_steers_against_gaps():
    """teacher_buchi_penalty(w) as the sole objective makes a teacher's
    hours pack contiguously (no gap) when avoidable."""
    import dsl_to_cpsat as d2c
    from ortools.sat.python import cp_model
    model = cp_model.CpModel()
    hours = [8, 9, 10, 11, 12, 13]
    slot = {("T1", "1A", "Mat", 1, h): model.NewBoolVar(f"s{h}") for h in hours}
    model.Add(sum(slot.values()) == 2)
    c = d2c.DSLConstraintCompiler(model, slot, level="phase_b")
    c.compile('teacher_buchi_penalty(10)')
    model.Minimize(sum(w * v for w, v in c.soft_cost_terms))
    solver = cp_model.CpSolver(); solver.parameters.max_time_in_seconds = 5.0
    assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    busy = sorted(h for h in hours if solver.Value(slot[("T1", "1A", "Mat", 1, h)]))
    assert busy[1] == busy[0] + 1, f"buchi penalty should pack hours: {busy}"


def test_five_one_pragma_empty_slot_degrades_gracefully():
    """A five/one pragma on a compiler with an EMPTY slot scope degrades
    gracefully: it records a slot-scope diagnostic, adds no soft terms,
    and never raises. The guard checks the input actually consumed
    (self.slot), not the irrelevant self.day_count."""
    import dsl_to_cpsat as d2c
    from ortools.sat.python import cp_model
    for pragma, label in (("teacher_five_penalty", "teacher_five_penalty"),
                          ("teacher_one_penalty", "teacher_one_penalty")):
        model = cp_model.CpModel()
        c = d2c.DSLConstraintCompiler(model, {}, level="phase_a")
        c.compile(f"{pragma}(10)")
        assert c.soft_cost_terms == [], f"{pragma} should add no terms on empty slot"
        assert any("slot empty" in d for d in c.diagnostics), c.diagnostics
        # The honest diagnostic names the pragma and the empty slot scope,
        # and must NOT mention day_count (the debugging trap we removed).
        assert any(label in d and "day_count" not in d for d in c.diagnostics)


def test_build_soft_pragmas_default_mode_includes_sixth_buchi_five_one():
    import dsl_translator
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 5}}}, "max_hours": 18}}
    classes = ["1A"]
    stream = dsl_translator.build_soft_pragmas(profs, classes, scale_mode="default")
    joined = " ".join(stream)
    assert "class_sixth_penalty(" in joined
    assert "teacher_buchi_penalty(" in joined
    assert "teacher_five_penalty(" in joined
    assert "teacher_one_penalty(" in joined


def test_build_soft_pragmas_per_day_mode_excludes_five_one():
    import dsl_translator
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 5}}}, "max_hours": 18}}
    stream = dsl_translator.build_soft_pragmas(profs, ["1A"], scale_mode="phase_b_per_day")
    joined = " ".join(stream)
    assert "teacher_five_penalty(" not in joined
    assert "teacher_one_penalty(" not in joined
    assert "class_sixth_penalty(" in joined
