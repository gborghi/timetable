"""Sblocco 1 -- align ``add_class_no_holes`` / ``add_h3_presence_at_11``
with ``add_class_no_overlap`` busy aggregation.

The three methods plus the corresponding DSL pragmas
(``no_holes_class`` / ``class_present_at_hour``) must agree on what
"the class is busy at slot (cl, d, h)" means:

* sostegno (DVA support) triples are EXCLUDED from the aggregation;
* coteach members in the same (cl, subj) are OR'd into ONE indicator;
* parallel-intra members are OR'd into ONE indicator;
* inter-class group slots feed each home class under
  ``__grp__<gn>__<subj>`` keys.

Without this alignment ``add_class_no_holes`` would treat a sostegno
hour as a fresh class occupation (false positive) or count k coteach
members as k occupations (double-counting), drifting from the legacy
``solve_phase_b_for_day`` ``keys_by_busy`` logic.
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


# ============================================================
# Helpers
# ============================================================


def _solver(model):
    from ortools.sat.python import cp_model
    s = cp_model.CpSolver()
    s.parameters.num_search_workers = 1
    s.parameters.cp_model_presolve = False
    return s, cp_model


def _enumerate(ms, max_solutions: int = 64):
    """Enumerate every feasible slot-assignment (frozenset) of the
    HARD model. Used to compare feasible sets before / after the
    refactor."""
    from ortools.sat.python import cp_model

    class _Collector(cp_model.CpSolverSolutionCallback):
        def __init__(self, slot, found):
            super().__init__()
            self._slot = slot
            self._found = found
            self.n = 0

        def on_solution_callback(self):
            picked = frozenset(
                k for k, v in self._slot.items() if self.Value(v))
            self._found.add(picked)
            self.n += 1
            if self.n >= max_solutions:
                self.StopSearch()

    found: set = set()
    s, _ = _solver(ms.model)
    cb = _Collector(ms.slot, found)
    s.Solve(ms.model, cb)
    return found


# ============================================================
# 1. sostegno + no_holes -- exclusion logic
# ============================================================


def test_no_holes_excludes_support_triple():
    """A class with 1h Mat + 1h sostegno on the same day must satisfy
    no-holes via the non-support lesson alone. With aggregation
    aligned, ``present[h]`` for sostegno's hour reflects only the
    non-support occupation -- exactly what Phase B does."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 1}}}, "max_hours": 18},
        "Sost": {
            "classi": {"1A": {"sostegno": {"ore": 1}}},
            "max_hours": 18,
        },
    }
    dc = {
        ("T1", "1A", "Mat", 1): 1,
        ("Sost", "1A", "sostegno", 1): 1,
    }
    cfg = ConstraintConfig(
        enforce_no_holes=True,
        enforce_h3_presence_at_11=False,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=False,
        support_assignments=[
            {"teacher_name": "Sost", "class_name": "1A",
             "subject": "sostegno", "n_hours": 1},
        ],
    )
    ms = MonolithicSolver(profs, dc, cfg)
    ms.build()
    s, cp_model = _solver(ms.model)
    status = s.Solve(ms.model)
    # Must be feasible: Mat+sostegno together at h=8 satisfies no_holes.
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), (
        s.StatusName(status))
    # Both must be at the SAME hour (sostegno HARD shadow): the
    # support's hour mirrors Mat's hour. The legacy Phase B reaches
    # the same conclusion.
    mat_h = next(h for (t, _cl, s_, _d, h), v in ms.slot.items()
                  if t == "T1" and s.Value(v))
    sost_h = next(h for (t, _cl, s_, _d, h), v in ms.slot.items()
                  if t == "Sost" and s.Value(v))
    assert mat_h == sost_h


def test_no_holes_with_only_sostegno_is_unsat():
    """A class whose ONLY weekly hour is a sostegno hour must be
    UNSAT: sostegno requires a non-support partner at the same slot,
    and there is none. Confirms the busy aggregation correctly
    excludes sostegno -- the rule cannot be satisfied by sostegno
    alone."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {
        "Sost": {
            "classi": {"1A": {"sostegno": {"ore": 1}}},
            "max_hours": 18,
        },
    }
    dc = {("Sost", "1A", "sostegno", 1): 1}
    cfg = ConstraintConfig(
        enforce_no_holes=True,
        enforce_h3_presence_at_11=False,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=False,
        support_assignments=[
            {"teacher_name": "Sost", "class_name": "1A",
             "subject": "sostegno", "n_hours": 1},
        ],
    )
    ms = MonolithicSolver(profs, dc, cfg)
    ms.build()
    s, cp_model = _solver(ms.model)
    status = s.Solve(ms.model)
    assert status == cp_model.INFEASIBLE


# ============================================================
# 2. coteach + no_holes -- aggregation logic
# ============================================================


def test_no_holes_with_coteach_is_feasible():
    """A coteach group of 2 teachers in (1A, Chim) for 2 hours.
    With busy aggregation aligned, the 2 members' slots are OR'd into
    1 occupation -- so Phase B's no_holes chain sees a single class
    hour at each coteach slot, as expected."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {
        "TA": {"classi": {"1A": {"Chim": {"ore": 2}}},
                "max_hours": 18},
        "TB": {"classi": {"1A": {"Chim": {"ore": 2}}},
                "max_hours": 18},
    }
    # TA leads the cattedra (2h Chim), TB compresenza on the same 2h.
    dc = {
        ("TA", "1A", "Chim", 1): 2,
        ("TB", "1A", "Chim", 1): 2,
    }
    cfg = ConstraintConfig(
        enforce_no_holes=True,
        enforce_h3_presence_at_11=False,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=False,
        coteach_groups=[{
            "group_id": "G1",
            "class_name": "1A",
            "subject": "Chim",
            "n_hours": 2,
            "teachers": ["TA", "TB"],
            "required": True,
        }],
    )
    ms = MonolithicSolver(profs, dc, cfg)
    ms.build()
    s, cp_model = _solver(ms.model)
    status = s.Solve(ms.model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), (
        s.StatusName(status))
    # Both teachers share the SAME 2 slots.
    ta_slots = {(d, h) for (t, _cl, _s, d, h), v in ms.slot.items()
                 if t == "TA" and s.Value(v)}
    tb_slots = {(d, h) for (t, _cl, _s, d, h), v in ms.slot.items()
                 if t == "TB" and s.Value(v)}
    assert ta_slots == tb_slots


# ============================================================
# 3. parallel intra-class + no_holes -- aggregation logic
# ============================================================


def test_no_holes_with_parallel_intra_is_feasible():
    """A parallel-intra group: religione/alternativa in 1A. Two
    distinct subjects, same hour, students choose one or the other.
    Without aggregation, no_holes would see the two slots as TWO
    occupations and could falsely require contiguity twice. Aligned
    aggregation treats them as ONE occupation per (1A, d, h)."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {
        "TR": {"classi": {"1A": {"Religione": {"ore": 1}}},
                "max_hours": 18},
        "TA": {"classi": {"1A": {"Alternativa": {"ore": 1}}},
                "max_hours": 18},
    }
    dc = {
        ("TR", "1A", "Religione", 1): 1,
        ("TA", "1A", "Alternativa", 1): 1,
    }
    cfg = ConstraintConfig(
        enforce_no_holes=True,
        enforce_h3_presence_at_11=False,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=False,
        parallel_groups=[{
            "group_id": "PG1",
            "class_name": "1A",
            "members": [
                {"teacher_name": "TR", "subject": "Religione"},
                {"teacher_name": "TA", "subject": "Alternativa"},
            ],
        }],
    )
    ms = MonolithicSolver(profs, dc, cfg)
    ms.build()
    s, cp_model = _solver(ms.model)
    status = s.Solve(ms.model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), (
        s.StatusName(status))
    # Both members occupy the SAME slot (parallel HARD ties them).
    tr_slots = {(d, h) for (t, _cl, _s, d, h), v in ms.slot.items()
                 if t == "TR" and s.Value(v)}
    ta_slots = {(d, h) for (t, _cl, _s, d, h), v in ms.slot.items()
                 if t == "TA" and s.Value(v)}
    assert tr_slots == ta_slots
    # And no_holes holds: contiguous from h=8.
    assert tr_slots == {(1, 8)}


# ============================================================
# 4. zero-drift: simple scenario unchanged
# ============================================================


def test_zero_drift_simple_scenario_no_registries():
    """When NO sostegno / coteach / parallel intra is in play, the
    new busy aggregation must be a no-op: feasible set identical to
    the legacy raw OR over slots."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 4}}},
                "max_hours": 18},
    }
    dc = {("T1", "1A", "Mat", 1): 4}
    cfg = ConstraintConfig(
        enforce_no_holes=True,
        enforce_h3_presence_at_11=False,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=False,
    )
    ms = MonolithicSolver(profs, dc, cfg)
    ms.build()
    feasible = _enumerate(ms)
    # 4 contiguous hours from h=8: only one feasible placement
    # (h=8..11). Validates that the new aggregation didn't tighten
    # nor relax the rule on a scenario with empty registries.
    assert len(feasible) == 1
    expected = frozenset(
        ("T1", "1A", "Mat", 1, h) for h in (8, 9, 10, 11))
    assert next(iter(feasible)) == expected


# ============================================================
# 5. h11 presence with sostegno -- exclusion logic
# ============================================================


def test_h11_presence_excludes_sostegno_for_any_d():
    """A class with 4h Mat + 1h sostegno covers h=8..11. h=11 must be
    busy (Mat is there). The any_d aggregation uses non-support
    indicators so this works correctly."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 4}}}, "max_hours": 18},
        "Sost": {
            "classi": {"1A": {"sostegno": {"ore": 1}}},
            "max_hours": 18,
        },
    }
    dc = {
        ("T1", "1A", "Mat", 1): 4,
        ("Sost", "1A", "sostegno", 1): 1,
    }
    cfg = ConstraintConfig(
        enforce_no_holes=True,
        enforce_h3_presence_at_11=True,
        enforce_motorie_pair=False,
        enforce_math_italian_pair=False,
        support_assignments=[
            {"teacher_name": "Sost", "class_name": "1A",
             "subject": "sostegno", "n_hours": 1},
        ],
    )
    ms = MonolithicSolver(profs, dc, cfg)
    ms.build()
    s, cp_model = _solver(ms.model)
    status = s.Solve(ms.model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE), (
        s.StatusName(status))
    # h=11 must be Mat (non-support) busy.
    h11_busy = any(
        s.Value(v)
        for (t, _cl, sub, d, h), v in ms.slot.items()
        if _cl == "1A" and h == 11 and sub != "sostegno")
    assert h11_busy


# ============================================================
# 6. DSL pragma alignment via owner_model
# ============================================================


def test_dsl_no_holes_pragma_uses_exclusion_when_owner_model_present():
    """The DSL pragma ``no_holes_class("1A")`` must produce the same
    feasibility as the OO ``add_class_no_holes`` when the compiler
    has access to the owner_model's busy registries. Tests the
    sostegno + Mat scenario from above through the DSL path."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 1}}}, "max_hours": 18},
        "Sost": {
            "classi": {"1A": {"sostegno": {"ore": 1}}},
            "max_hours": 18,
        },
    }
    dc = {
        ("T1", "1A", "Mat", 1): 1,
        ("Sost", "1A", "sostegno", 1): 1,
    }

    def _build(via_dsl):
        cfg = ConstraintConfig(
            enforce_no_holes=True,
            enforce_h3_presence_at_11=False,
            enforce_motorie_pair=False,
            enforce_math_italian_pair=False,
            support_assignments=[
                {"teacher_name": "Sost", "class_name": "1A",
                 "subject": "sostegno", "n_hours": 1},
            ],
        )
        ms = MonolithicSolver(profs, dc, cfg)
        ms.build(via_dsl=via_dsl)
        return ms

    legacy = _build(via_dsl=False)
    dsl = _build(via_dsl=True)
    s_l = _enumerate(legacy)
    s_d = _enumerate(dsl)
    assert s_l == s_d, (sorted(s_l), sorted(s_d))


def test_dsl_h11_pragma_uses_exclusion_when_owner_model_present():
    """Same as above but for ``class_present_at_hour_all(11)``."""
    from cp_sat_constraint_model import (
        MonolithicSolver, ConstraintConfig)
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 4}}}, "max_hours": 18},
        "Sost": {
            "classi": {"1A": {"sostegno": {"ore": 1}}},
            "max_hours": 18,
        },
    }
    dc = {
        ("T1", "1A", "Mat", 1): 4,
        ("Sost", "1A", "sostegno", 1): 1,
    }

    def _build(via_dsl):
        cfg = ConstraintConfig(
            enforce_no_holes=True,
            enforce_h3_presence_at_11=True,
            enforce_motorie_pair=False,
            enforce_math_italian_pair=False,
            support_assignments=[
                {"teacher_name": "Sost", "class_name": "1A",
                 "subject": "sostegno", "n_hours": 1},
            ],
        )
        ms = MonolithicSolver(profs, dc, cfg)
        ms.build(via_dsl=via_dsl)
        return ms

    legacy = _build(via_dsl=False)
    dsl = _build(via_dsl=True)
    s_l = _enumerate(legacy)
    s_d = _enumerate(dsl)
    assert s_l == s_d, (sorted(s_l), sorted(s_d))


# ============================================================
# 7. helper sanity: _build_class_busy_indicators direct
# ============================================================


def test_build_class_busy_indicators_sostegno_excluded():
    """Direct unit test of the helper: when sostegno is registered,
    the helper returns the non-support slot only."""
    from cp_sat_constraint_model import (
        ConstraintModel, ConstraintConfig)
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 1}}}, "max_hours": 18},
        "Sost": {
            "classi": {"1A": {"sostegno": {"ore": 1}}},
            "max_hours": 18,
        },
    }
    dc = {
        ("T1", "1A", "Mat", 1): 1,
        ("Sost", "1A", "sostegno", 1): 1,
    }
    cfg = ConstraintConfig(
        support_assignments=[
            {"teacher_name": "Sost", "class_name": "1A",
             "subject": "sostegno", "n_hours": 1},
        ],
    )
    cm = ConstraintModel(profs, dc, cfg)
    cm.add_support_assignments()
    # At (1A, day=1, h=8): both Mat and sostegno slots exist.
    busy = cm._build_class_busy_indicators("1A", 1, 8)
    # Helper must return exactly 1 indicator (the Mat slot). The
    # sostegno slot is excluded.
    assert len(busy) == 1
    # The single indicator IS the Mat slot var (no aggregator
    # wrapping needed when len(vs) <= 1).
    assert busy[0] is cm.slot[("T1", "1A", "Mat", 1, 8)]


def test_build_class_busy_indicators_coteach_aggregated():
    """Direct unit test: when a coteach group is registered, the
    helper returns ONE aggregator indicator for the k members."""
    from cp_sat_constraint_model import (
        ConstraintModel, ConstraintConfig)
    profs = {
        "TA": {"classi": {"1A": {"Chim": {"ore": 2}}},
                "max_hours": 18},
        "TB": {"classi": {"1A": {"Chim": {"ore": 2}}},
                "max_hours": 18},
    }
    dc = {
        ("TA", "1A", "Chim", 1): 2,
        ("TB", "1A", "Chim", 1): 2,
    }
    cfg = ConstraintConfig(
        coteach_groups=[{
            "group_id": "G1", "class_name": "1A", "subject": "Chim",
            "n_hours": 2, "teachers": ["TA", "TB"], "required": True,
        }],
    )
    cm = ConstraintModel(profs, dc, cfg)
    cm.add_coteach_groups()
    busy = cm._build_class_busy_indicators("1A", 1, 8)
    # 2 members in same (1A, Chim): aggregated to ONE indicator.
    assert len(busy) == 1
    # The single indicator is the aggregator BoolVar (NewBoolVar
    # with name starting "agg_..."). It's NOT one of the raw slot
    # vars -- it's the AddMaxEquality output.
    assert "agg" in busy[0].Name()


def test_build_class_busy_indicators_parallel_intra_aggregated():
    """Direct unit test: parallel-intra group of k members yields
    ONE aggregator indicator at each (cl, d, h)."""
    from cp_sat_constraint_model import (
        ConstraintModel, ConstraintConfig)
    profs = {
        "TR": {"classi": {"1A": {"Religione": {"ore": 1}}},
                "max_hours": 18},
        "TA": {"classi": {"1A": {"Alternativa": {"ore": 1}}},
                "max_hours": 18},
    }
    dc = {
        ("TR", "1A", "Religione", 1): 1,
        ("TA", "1A", "Alternativa", 1): 1,
    }
    cfg = ConstraintConfig(
        parallel_groups=[{
            "group_id": "PG1", "class_name": "1A",
            "members": [
                {"teacher_name": "TR", "subject": "Religione"},
                {"teacher_name": "TA", "subject": "Alternativa"},
            ],
        }],
    )
    cm = ConstraintModel(profs, dc, cfg)
    cm.add_parallel_groups_intra_class()
    busy = cm._build_class_busy_indicators("1A", 1, 8)
    # 2 distinct subjects in same parallel group: aggregated to
    # ONE indicator under busy_key __par__PG1.
    assert len(busy) == 1
    assert "agg" in busy[0].Name()
