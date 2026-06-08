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


def test_class_busy_mode_aggregates_one_term_per_class_at_h13():
    """class_sixth_penalty(5, "class_busy") emits ONE (weight,var) term
    per class busy at h13 -- not per slot. Two teachers on the SAME
    class at h13 => one aggregated term, weight 5."""
    import dsl_to_cpsat as d2c
    from ortools.sat.python import cp_model
    model = cp_model.CpModel()
    slot = {
        ("TA", "1A", "Chim", 1, 13): model.NewBoolVar("a13"),
        ("TB", "1A", "Chim", 1, 13): model.NewBoolVar("b13"),
        ("TA", "1A", "Chim", 1, 12): model.NewBoolVar("a12"),
        ("TC", "1B", "Mat", 1, 13): model.NewBoolVar("c13"),
    }
    c = d2c.DSLConstraintCompiler(model, slot, level="phase_b")
    c.compile('class_sixth_penalty(5, "class_busy")')
    assert len(c.soft_cost_terms) == 2
    assert all(w == 5 for w, _v in c.soft_cost_terms)
