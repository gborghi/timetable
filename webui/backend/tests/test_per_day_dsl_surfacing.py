"""Per-day Phase-B DSL diagnostics surfacing.

The monolithic per-day path (`solve_phase_b_for_day`) collects free-text
DSL diagnostics into a `diagnostics_sink`. The orchestrator turns that sink
into structured, RunLog-bound `[phaseB.day][WARN]` lines via the pure
`_per_day_dsl_warning_lines` helper (mirrors the week path's
`[phaseB.week][WARN]` surfacing). This is the unit under test; the sink
*population* itself is covered by test_constraint_compat's per-day sink test.
"""
from __future__ import annotations


def test_per_day_dsl_warning_lines_summarizes_and_formats():
    from backend.optimization import _per_day_dsl_warning_lines
    sink = [
        "forall over 'teachers' not yet supported (only 'lessons')",
        "loaded 4 DSL rules",            # info -> dropped
    ]
    lines = _per_day_dsl_warning_lines(sink)
    assert lines, "should yield >=1 warning line"
    assert all(ln.startswith("[phaseB.day][WARN]") for ln in lines)
    assert any("not yet supported" in ln for ln in lines)
    # informational loader lines are not warnings
    assert not any("loaded 4 DSL rules" in ln for ln in lines)


def test_per_day_dsl_warning_lines_dedups():
    from backend.optimization import _per_day_dsl_warning_lines
    sink = [
        "forall over 'teachers' not yet supported (only 'lessons')",
        "forall over 'teachers' not yet supported (only 'lessons')",
    ]
    assert len(_per_day_dsl_warning_lines(sink)) == 1


def test_per_day_dsl_warning_lines_empty_inputs():
    from backend.optimization import _per_day_dsl_warning_lines
    assert _per_day_dsl_warning_lines([]) == []
    assert _per_day_dsl_warning_lines(None) == []
