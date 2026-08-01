"""Finding 08b + 34 full coverage: every solver entry point that can place
lessons threads `class_flags` (and special-room ctx where applicable), so a
class-card toggle is honored on the per-day, week, spectral, temporal and
column-generation paths — not only the monolithic one."""
import inspect

import column_generation as cg
import cpsat_v2_timetable as cv2
import decomposition_spectral_v2 as spec
import decomposition_temporal as temp
from ortools.sat.python import cp_model


def _has(fn, param):
    return param in inspect.signature(fn).parameters


def test_every_solver_entry_point_accepts_class_flags():
    for fn in (
        cv2.solve_phase_b_for_day,
        cv2.add_consecutive_constraints_phase_b,
        spec.stage_a_bridges,
        spec.stage_b_cluster_internals,
        spec.stage_c_ricucitura,
        spec.solve_monolithic_day,
        temp.solve_day,
        temp.run_temporal_pipeline,
        cg.run_column_generation,
        cg._completion_solver,
    ):
        assert _has(fn, "class_flags"), f"{fn.__name__} missing class_flags"


def test_special_room_ctx_threaded_where_all_classes_visible():
    # The whole-slot solvers carry special_room_ctx; the per-teacher-subset
    # spectral stages deliberately do NOT (a global per-slot cap can't
    # decompose along the teacher partition -- it lives in the monolithic
    # reconstitution).
    for fn in (cv2.solve_phase_b_for_day, spec.solve_monolithic_day,
               temp.solve_day, temp.run_temporal_pipeline,
               cg.run_column_generation, cg._completion_solver):
        assert _has(fn, "special_room_ctx"), fn.__name__


def test_add_consecutive_gates_motorie_per_class():
    # Two classes each with a 2-hour Scienze motorie cattedra; turning the
    # motorie pair OFF for 1A must drop 1A's must-pair constraint but keep
    # 1B's. We compare the number of constraints in the model proto.
    def build(class_flags):
        m = cp_model.CpModel()
        slot = {}
        profs = {}
        for cl in ("1A", "1B"):
            profs[f"T{cl}"] = {"classi": {cl: {"Scienze motorie": {"ore": 2}}}}
            for h in cv2.HOURS:
                slot[(f"T{cl}", cl, "Scienze motorie", h)] = m.NewBoolVar(
                    f"{cl}_{h}")
        dc = {(f"T{cl}", cl, "Scienze motorie", cv2.DAYS[0]): 2
              for cl in ("1A", "1B")}
        cv2.add_consecutive_constraints_phase_b(
            m, slot, cv2.DAYS[0], profs, dc, class_flags=class_flags)
        return len(m.Proto().constraints)

    base = build(None)
    off_1a = build({"1A": {"motorie_pairs": False}})
    assert off_1a < base   # fewer constraints: 1A's motorie pair dropped
