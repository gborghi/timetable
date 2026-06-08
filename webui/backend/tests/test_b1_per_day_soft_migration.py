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


# ---------------------------------------------------------------------
# Task 2: solve_phase_b_for_day objective migrated to the pragma stream.
#
# solve_phase_b_for_day's real signature is
#   solve_phase_b_for_day(day, profs, classes, triples, class_profs,
#                         dc_value, ...)
# and it returns ``(out, status)`` where ``out`` is a dense dict
#   {(prof, class, subj, day, hour): 0|1}.
# A new keyword ``return_objective=True`` makes it return
#   ``(out, status, objective_value)`` (the legacy 2-tuple callers are
# untouched). The value tests below read that third element.
# ---------------------------------------------------------------------


def _tiny_day_fixture(n_hours: int):
    """One class 1A, one teacher T1, ``n_hours`` Mat hours on day 1.

    Returns ``(profs, classes, triples, class_profs, dc_value)`` ready
    to feed ``solve_phase_b_for_day``."""
    import cpsat_v2_timetable as cv2  # type: ignore
    cv2._apply_working_hours_config()
    profs = {
        "T1": {
            "classi": {"1A": {"Mat": {"ore": n_hours}}},
            "glibero": [6, 5, 4],
        },
    }
    classes, triples, class_profs = cv2.build_indices(profs)
    dc_value = {("T1", "1A", "Mat", 1): n_hours}
    return profs, classes, triples, class_profs, dc_value


def test_phase_b_per_day_functional_feasible_placement():
    """SACRED functional contract: the per-day solver still runs, still
    produces a HARD-feasible placement (4 Mat hours placed for 1A on
    day 1, no double-booking). Must pass before AND after migration."""
    import cpsat_v2_timetable as cv2  # type: ignore
    profs, classes, triples, class_profs, dc_value = _tiny_day_fixture(4)
    out, status = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc_value,
        time_limit=5, workers=2, log=False)
    assert out is not None  # feasible
    placed = {(d, h) for (p, cl, s, d, h), v in out.items() if v}
    # exactly 4 hours placed for 1A on day 1
    assert len(placed) == 4, placed
    # all on day 1
    assert all(d == 1 for (d, h) in placed)
    # no double-booking: 4 distinct (day, hour) cells
    assert len({(p, cl, s, d, h)
                for (p, cl, s, d, h), v in out.items() if v}) == 4


def test_phase_b_per_day_objective_zero_on_determined_optimum():
    """VALUE characterization: 4 contiguous hours under no-holes places
    8,9,10,11 -- no h13 (no sixth cost), no interior gap (no buchi).
    Objective == 0. Must hold before and after migration (zero-drift)."""
    import cpsat_v2_timetable as cv2  # type: ignore
    profs, classes, triples, class_profs, dc_value = _tiny_day_fixture(4)
    out, status, obj = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc_value,
        time_limit=5, workers=2, log=False, return_objective=True)
    assert out is not None
    placed = {h for (p, cl, s, d, h), v in out.items() if v}
    assert placed == {8, 9, 10, 11}, placed
    assert obj == 0, obj


def test_phase_b_per_day_objective_sixth_cost_when_h13_forced():
    """VALUE characterization (forced sixth): 6 Mat hours under no-holes
    fill 8..13 contiguously -- h13 is occupied so the class is busy at
    the sixth hour. Cost = 1 sixth-at-h13 * weight 5 = 5, no buchi (no
    interior gap). Objective == 5 (== legacy W_SIXTH_B)."""
    import cpsat_v2_timetable as cv2  # type: ignore
    profs, classes, triples, class_profs, dc_value = _tiny_day_fixture(6)
    out, status, obj = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc_value,
        time_limit=5, workers=2, log=False, return_objective=True)
    assert out is not None
    placed = {h for (p, cl, s, d, h), v in out.items() if v}
    assert placed == {8, 9, 10, 11, 12, 13}, placed
    assert obj == 5, obj
