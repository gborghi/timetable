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


def _fixture_slot(model):
    """A small one-teacher, one-day fixture with a gap: lessons placed at
    hours 8, 9 and 12 (hours 10/11 idle) so the buchi encoder has work to
    do. Two distinct classes keep the slot keys unique."""
    return {
        ("T1", "1A", "Mat", 1, 8): model.NewBoolVar("a"),
        ("T1", "1A", "Mat", 1, 9): model.NewBoolVar("b"),
        ("T1", "1B", "Mat", 1, 12): model.NewBoolVar("c"),
    }


def test_buchi_and_daydist_terms_builds_baseline():
    """Baseline guard for the accessor refactor: the EXISTING slot-based
    public entry point builds a solvable model and emits a stable number
    of objective terms. With include_five_one=True one (teacher, day)
    record yields 3 obj terms (buchi + is_five + is_one)."""
    import soft_costs
    model = cp_model.CpModel()
    slot = _fixture_slot(model)
    obj_terms, aux = soft_costs.buchi_and_daydist_terms(
        model, slot, ["T1"], [1], [8, 9, 10, 11, 12, 13],
        buchi_weight=1000, five_weight=3000, one_weight=8000,
        include_five_one=True)
    # One in-scope (teacher, day) -> buchi + is_five + is_one = 3 terms.
    assert len(obj_terms) == 3
    assert aux  # auxiliary vars were created
    # Force every lesson on so the gap is real, then confirm it solves.
    for v in slot.values():
        model.Add(v == 1)
    model.Minimize(sum(obj_terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_buchi_pairs_builds_baseline():
    """Baseline guard: the slot-based buchi_pairs entry emits one
    (weight, var) pair per in-scope (teacher, day) and builds."""
    import soft_costs
    model = cp_model.CpModel()
    slot = _fixture_slot(model)
    pairs, aux = soft_costs.buchi_pairs(
        model, slot, ["T1"], [1], [8, 9, 10, 11, 12, 13], weight=1000)
    assert len(pairs) == 1
    assert all(w == 1000 for w, _v in pairs)
    assert aux


def test_accessor_entry_matches_slot_entry():
    """The accessor entry, fed a slot-filtering accessor over the same
    fixture, builds the same number of obj terms as the slot-based entry
    and produces a solvable model. Term order is five, one, buchi (CG
    order) -- asserted via the documented contract below."""
    import soft_costs
    model = cp_model.CpModel()
    slot = _fixture_slot(model)

    def vars_at(t, d, h):
        return [v for (tt, _c, _s, dd, hh), v in slot.items()
                if tt == t and dd == d and hh == h]

    obj_terms, aux = soft_costs.buchi_daydist_terms_from_accessor(
        model, vars_at, ["T1"], [1], [8, 9, 10, 11, 12, 13],
        buchi_weight=1000, five_weight=3000, one_weight=8000,
        include_five_one=True)
    # Same record count as the slot entry -> 3 obj terms.
    assert len(obj_terms) == 3
    assert aux
    for v in slot.values():
        model.Add(v == 1)
    model.Minimize(sum(obj_terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_accessor_obj_term_order_is_five_one_buchi():
    """Pin the OBJ-TERM ORDER contract: per record the accessor entry
    appends five, then one, then buchi -- matching
    column_generation._add_full_soft_cost_terms. We read back the linear
    coefficients of each term to confirm the weight sequence."""
    import soft_costs
    model = cp_model.CpModel()
    slot = _fixture_slot(model)

    def vars_at(t, d, h):
        return [v for (tt, _c, _s, dd, hh), v in slot.items()
                if tt == t and dd == d and hh == h]

    obj_terms, _aux = soft_costs.buchi_daydist_terms_from_accessor(
        model, vars_at, ["T1"], [1], [8, 9, 10, 11, 12, 13],
        buchi_weight=1000, five_weight=3000, one_weight=8000,
        include_five_one=True)
    # one (teacher, day) record -> [3000*is_five, 8000*is_one, 1000*buchi]
    # each term is an IntAffine (weight * BoolVar); read its coefficient.
    coeffs = [t.coefficient for t in obj_terms]
    assert coeffs == [3000, 8000, 1000]
