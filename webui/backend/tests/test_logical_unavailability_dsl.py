"""LogicalUnavailability -> DSL: niente piu' testo grezzo al compilatore
(Liceo M5: '<=' tra str e int sul profilo small)."""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

import dsl_translator as dt  # noqa: E402


def test_short_form_becomes_forall_rule():
    out = dt.logical_unavailability_to_dsl("teacher", "Rossi", "(d=2 and h<=9)")
    assert out == ['forall l in lessons where l.teacher == "Rossi" and '
                   '((l.day == 2 and l.hour <= 9)): false']


def test_single_clause_dnf_becomes_cells():
    dnf = json.dumps([[{"day": 1, "hour": 8, "negate": False},
                       {"day": 1, "hour": 9, "negate": True}]])
    out = dt.logical_unavailability_to_dsl("class", "1A", "lun8 AND NOT lun9", dnf)
    assert out == ['forall l in lessons where l.class == "1A" and '
                   'l.day == 1 and l.hour == 8: false']


def test_disjunctive_or_unknown_is_not_forwarded():
    dnf = json.dumps([[{"day": 1, "hour": 8, "negate": False}],
                      [{"day": 2, "hour": 8, "negate": False}]])
    assert dt.logical_unavailability_to_dsl("teacher", "R", "lun8 OR mar8", dnf) == []
    assert dt.logical_unavailability_to_dsl("teacher", "R", "boh") == []
    assert dt.logical_unavailability_to_dsl("teacher", None, "(d=1)") == []


def test_full_dsl_passes_through():
    e = 'forall l in lessons where l.teacher == "R": l.hour != 13'
    assert dt.logical_unavailability_to_dsl("teacher", "R", e) == [e]


def test_compiles_without_type_error():
    import dsl_to_cpsat as d2c
    import cp_sat_constraint_model as csm
    from ortools.sat.python import cp_model
    m = cp_model.CpModel()
    slot = {("Rossi", "1A", "Mat", d, h): m.NewBoolVar(f"x{d}{h}")
            for d in (1, 2) for h in (8, 9, 10)}
    c = d2c.DSLConstraintCompiler(m, slot, config=csm.ConstraintConfig(),
                                  classroom_for_slot=None, plessi_data=None)
    for e in dt.logical_unavailability_to_dsl("teacher", "Rossi", "(d=2 and h<=9)"):
        c.compile(e)
    m.Add(slot[("Rossi", "1A", "Mat", 2, 8)] == 1)
    assert cp_model.CpSolver().Solve(m) == cp_model.INFEASIBLE
