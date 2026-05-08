"""Per-granularity Branch-and-Price wiring tests.

Each granularity in `engine.column_generation._BP_GRANULARITIES` must
end up in a real BP loop -- not a silent fallback to iterative-
diversified. This file pins one test per granularity that asserts:

  - the engine accepts the granularity name end-to-end (CLI/API enum),
  - the BP loop iterates at least once
    (`bp_iterations_done >= 1`),
  - the run did not silently fall back
    (no `granularity_not_implemented` reason, no
    `has no CP-SAT pricer` warning),
  - on the small two-class scaffold the result is at least
    HARD-feasible after assembly OR after completion.

These tests live under top-level `tests/` so that
`pytest tests/test_bp_granularities.py::test_teacher_subject_iterates`
works from the project root without needing the
`webui/backend` package.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
ENGINE = os.path.join(ROOT, "engine")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


# ---------- small scaffold (kept self-contained for the top-level
# test path; mirrors webui/backend/tests/test_advanced_techniques.py
# `_two_class_profs` / `_two_class_dc`) ----------

def _two_class_profs():
    """Two-teacher, two-class scaffold.

    T1 covers Mat in 1A and 1B; T2 covers Ita in 1A and 1B. Each
    cattedra is 4 hrs/week. The scaffold is the smallest one that
    exercises the (teacher, *, subject) slice across multiple
    classes -- the natural unit for the teacher-subject pricer.
    """
    return {
        "T1": {
            "classi": {"1A": {"Mat": {"ore": 4}},
                        "1B": {"Mat": {"ore": 4}}},
            "glibero": [6],
            "max_hours": 18,
        },
        "T2": {
            "classi": {"1A": {"Ita": {"ore": 4}},
                        "1B": {"Ita": {"ore": 4}}},
            "glibero": [6],
            "max_hours": 18,
        },
    }


def _two_class_dc():
    """Day-counts that match `_two_class_profs`. Each cattedra
    lives on its OWN day so greedy + CP-SAT placements never
    collide on (t, d, h)."""
    return {
        ("T1", "1A", "Mat", 1): 4,
        ("T1", "1B", "Mat", 2): 4,
        ("T2", "1A", "Ita", 3): 4,
        ("T2", "1B", "Ita", 4): 4,
    }


_FALLBACK_REASONS = {"granularity_not_implemented"}


def _is_fallback(info: dict) -> bool:
    reason = (info.get("bp_terminated_reason") or "").split(":")[0]
    if reason in _FALLBACK_REASONS:
        return True
    for w in info.get("warnings", []):
        if "has no CP-SAT pricer" in str(w):
            return True
    return False


def _assert_bp_iterated(info: dict, granularity: str) -> None:
    assert info.get("granularity") == granularity, info
    assert not _is_fallback(info), (
        f"granularity={granularity!r} fell back: "
        f"reason={info.get('bp_terminated_reason')!r} "
        f"warnings={info.get('warnings')}")
    iters = int(info.get("bp_iterations_done") or 0)
    assert iters >= 1, (
        f"granularity={granularity!r} did not iterate "
        f"(bp_iterations_done={iters!r}, "
        f"reason={info.get('bp_terminated_reason')!r})")


def _run_bp(granularity: str):
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    return cg.run_column_generation(
        profs, dc_value, time_budget_s=30.0,
        patterns_per_teacher=2, max_iterations=2, log=False,
        mode="branch-and-price", granularity=granularity,
        bp_max_iterations=3, pricer_time_limit=2.0,
        pricer_workers=1,
    )


# ---------- teacher-subject (the granularity owned by this file) ----------

def test_teacher_subject_pricer_smoke():
    """Direct call to the teacher-subject pricer with a strong dual
    on (T1, 1A, Mat, 1) must produce a column that places ALL 8
    Mat-hours of T1 (4 in 1A on day 1 + 4 in 1B on day 2) and
    earns rc < 0."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    lambda_duals = {("T1", "1A", "Mat", 1): 100.0}
    pat, rc = cg._pricing_subproblem_teacher_subject(
        "T1", "Mat", profs, dc_value,
        lambda_duals, mu_t=0.0,
        time_limit=2.0, workers=1,
    )
    assert pat is not None, f"pricer returned None, rc={rc}"
    assert rc < 0.0, f"expected rc<0, got {rc}"
    placed = sum(1 for (p, _c, s, _d, _h), v in pat.items()
                  if v and p == "T1" and s == "Mat")
    assert placed == 8


def test_teacher_subject_iterates():
    """End-to-end BP with granularity=teacher-subject must enter
    the BP loop, not fall back to iterative-diversified, and
    converge to a HARD-feasible (or completion-feasible) plan."""
    sol, info = _run_bp("teacher-subject")
    _assert_bp_iterated(info, "teacher-subject")
    assert (info["feasible_after_assembly"]
            or info["feasible_after_completion"]), info


# ---------- class-day ----------

def test_class_day_pricer_smoke():
    """Direct call to the class-day pricer with a strong dual on
    (T1, 1A, Mat, day=1) must produce a HARD-feasible partial
    pattern restricted to the (1A, day=1) cell that places all 4
    Mat-hours of T1 there, with rc < 0."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    lambda_cover = {("T1", "1A", "Mat", 1): 100.0}
    col, rc = cg._pricing_subproblem_class_day(
        "1A", 1, profs, dc_value,
        lambda_cover, mu_class={}, mu_teacher={},
        time_limit=2.0, workers=1,
    )
    assert col is not None, f"class-day pricer returned None, rc={rc}"
    assert rc < 0.0, f"expected rc<0, got {rc}"
    for (_p, c, _s, d, _h), v in col.items():
        if v:
            assert c == "1A" and d == 1, (
                f"class-day column leaked to ({c}, day={d})")
    placed = sum(1 for v in col.values() if v)
    assert placed == 4, (
        f"class-day must place all 4h of (T1, 1A, Mat) on day 1, "
        f"got {placed}")


def test_class_day_iterates():
    """End-to-end BP with granularity=class-day must enter the BP
    loop, not fall back to iterative-diversified, and converge to
    a HARD-feasible (or completion-feasible) plan."""
    sol, info = _run_bp("class-day")
    _assert_bp_iterated(info, "class-day")
    assert (info["feasible_after_assembly"]
            or info["feasible_after_completion"]), info


# ---------- teacher-class-subject ----------

def test_teacher_class_subject_pricer_smoke():
    """Direct call to the teacher-class-subject pricer with a strong
    dual on (T1, 1A, Mat, 1) must produce a column that places ALL
    4 hours of (T1, 1A, Mat) on day 1, leaves the OTHER class slice
    (1B Mat) intact via the greedy base, and earns rc < 0."""
    import column_generation as cg
    profs = _two_class_profs()
    dc_value = _two_class_dc()
    lambda_duals = {("T1", "1A", "Mat", 1): 100.0}
    pat, rc = cg._pricing_subproblem_teacher_class_subject(
        "T1", "1A", "Mat", profs, dc_value,
        lambda_duals, mu_t=0.0,
        time_limit=2.0, workers=1,
    )
    assert pat is not None, f"pricer returned None, rc={rc}"
    assert rc < 0.0, f"expected rc<0, got {rc}"
    placed_in_scope = sum(
        1 for (p, c, s, d, _h), v in pat.items()
        if v and p == "T1" and c == "1A" and s == "Mat" and d == 1
    )
    assert placed_in_scope == 4, (
        f"teacher-class-subject must place all 4h of (T1, 1A, Mat) "
        f"on day 1, got {placed_in_scope}")
    placed_other_class = sum(
        1 for (p, c, s, _d, _h), v in pat.items()
        if v and p == "T1" and c == "1B" and s == "Mat"
    )
    assert placed_other_class == 4, (
        f"greedy base for (T1, 1B, Mat) must be preserved, got "
        f"{placed_other_class}")


def test_teacher_class_subject_iterates():
    """End-to-end BP with granularity=teacher-class-subject must
    enter the BP loop, not fall back to iterative-diversified, and
    converge to a HARD-feasible (or completion-feasible) plan."""
    sol, info = _run_bp("teacher-class-subject")
    _assert_bp_iterated(info, "teacher-class-subject")
    assert (info["feasible_after_assembly"]
            or info["feasible_after_completion"]), info


# ---------- parity check across all 9 granularities (regression
# guard for sibling sessions wiring class-day / teacher-class-subject)

@pytest.mark.parametrize(
    "granularity",
    [
        "teacher",
        "teacher-day",
        "teacher-class",
        "teacher-class-subject",
        "teacher-subject",
        "class",
        "class-day",
        "day",
        "curriculum",
    ],
)
def test_every_granularity_iterates(granularity):
    sol, info = _run_bp(granularity)
    _assert_bp_iterated(info, granularity)
