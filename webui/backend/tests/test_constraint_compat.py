"""Tests for the pure engine `constraint_compat` module + the
`solve_phase_b_for_day(..., diagnostics_sink=...)` capture hook.

`constraint_compat` is frontend-agnostic (no webui import); it turns the
engine's free-text DSL diagnostic strings into structured
`ConstraintWarning`s naming constraint + pipeline + reason + suggestion.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
WEBUI = os.path.normpath(os.path.join(HERE, "..", ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for _p in (ENGINE, WEBUI, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# --------------------------------------------------------------------------
# Step 1 (pure module): classify + summarize
# --------------------------------------------------------------------------

def test_classify_and_summarize_compile_failed():
    import constraint_compat as cc
    diags = [
        'compile_failed:Docente Rossi non disp.:KeyError:foo',
        "forall body dynamic and not nested-forall; skipped",
        "pragma teacher_five_penalty (level=phase_a) skipped: "
        "compiler level=phase_b",
    ]
    warns = cc.summarize(diags, pipeline="per_day_cpsat")
    assert len(warns) == 3
    w0 = warns[0]
    assert w0.pipeline == "per_day_cpsat"
    assert "Rossi" in w0.constraint or "Rossi" in w0.reason
    assert w0.suggestion  # non-empty
    assert w0.severity in ("warning", "error", "info")
    # dynamic-body constraints: suggestion should mention metaheuristic
    dyn = [w for w in warns if "dynamic" in w.reason.lower()]
    assert dyn and "metaheuristic" in dyn[0].suggestion.lower()
    # all serialise
    assert all(isinstance(w.to_dict(), dict) for w in warns)


def test_classify_colon_bearing_expr_label_not_truncated():
    """CG/BP and week-refinement embed the full DSL *expression* as the
    label, and such expressions legitimately contain colons (e.g.
    ``forall t in teachers: ...``). The classifier must preserve the whole
    expression as the constraint label instead of splitting on its colon."""
    import constraint_compat as cc
    expr = "forall t in teachers: count(t, mon) <= 2"
    diags = [
        f"compile_failed:{expr}:bp:not_modeled_in_pricer",
        f"compile_failed:{expr}:refinement:exhausted",
    ]
    warns = cc.summarize(diags, pipeline="branch_and_price")
    assert len(warns) == 2, warns
    for w in warns:
        assert w.constraint == expr, w.constraint
        assert w.raw  # original diagnostic preserved
    reasons = " ".join(w.reason for w in warns)
    assert "pricer" in reasons
    assert "exhausted" in reasons


def test_classify_compile_failed_extra_has_no_label():
    """The per-day 'extra' form ``compile_failed_extra:<ExcType>:<msg>`` has
    no constraint label; it must not crash and should carry the message."""
    import constraint_compat as cc
    warns = cc.summarize(
        ["compile_failed_extra:KeyError:boom"], pipeline="per_day_cpsat")
    assert len(warns) == 1
    assert "boom" in warns[0].reason
    assert warns[0].severity == "error"


def test_summarize_drops_info_and_dedups():
    import constraint_compat as cc
    diags = [
        "loaded 4 DSL rules",            # info -> dropped
        "forall over 'teachers' not yet supported (only 'lessons')",
        "forall over 'teachers' not yet supported (only 'lessons')",  # dup
    ]
    warns = cc.summarize(diags, pipeline="per_day_cpsat")
    assert len(warns) == 1
    assert warns[0].suggestion


def test_summarize_never_crashes_on_garbage():
    import constraint_compat as cc
    warns = cc.summarize(["", "???", 12345], pipeline="week_cpsat")
    assert all(w.suggestion for w in warns)
    assert all(w.pipeline == "week_cpsat" for w in warns)


# --------------------------------------------------------------------------
# Step 3 (sink): solve_phase_b_for_day captures dsl_diagnostics
# --------------------------------------------------------------------------

def _tiny_day_fixture():
    """One class 1A, one teacher T1, 3 Mat hours on day 1 -- trivially
    feasible single-day Phase-B sub-problem (mirrors the B2 fixture)."""
    import cpsat_v2_timetable as cv2  # type: ignore
    cv2._apply_working_hours_config()
    profs = {
        "T1": {
            "classi": {"1A": {"Mat": {"ore": 3}}},
            "glibero": [6, 5, 4],
        },
    }
    classes, triples, class_profs = cv2.build_indices(profs)
    dc_value = {("T1", "1A", "Mat", 1): 3}
    return profs, classes, triples, class_profs, dc_value


def test_solve_phase_b_for_day_sink_captures_unsupported_construct():
    import cpsat_v2_timetable as cv2
    import constraint_compat as cc

    profs, classes, triples, class_profs, dc_value = _tiny_day_fixture()

    sink: list[str] = []
    # `forall x in teachers: false` is parseable but the per-day CP
    # compiler only models `forall ... in lessons`; it appends the
    # diagnostic "forall over 'teachers' not yet supported (only
    # 'lessons')" and SKIPS the rule -- the solve stays feasible.
    out, status = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc_value,
        time_limit=10, workers=2,
        enforce_no_holes=False,
        via_dsl=True,
        extra_dsl_expressions=["forall x in teachers: false"],
        diagnostics_sink=sink,
    )

    # Functional: the bad rule is warned, not fatal -> feasible result.
    assert out is not None
    assert status in (cv2.cp_model.OPTIMAL, cv2.cp_model.FEASIBLE)

    # The sink captured the diagnostic.
    assert sink, "diagnostics_sink should be non-empty"
    assert any("not yet supported" in str(d) for d in sink), sink

    warns = cc.summarize(sink, pipeline="per_day_cpsat")
    assert warns, "summarize should yield >=1 warning"
    w = warns[0]
    assert w.pipeline == "per_day_cpsat"
    assert w.suggestion  # non-empty


def test_solve_phase_b_for_day_no_sink_default_unchanged():
    """Default (no sink) path: 2-tuple return, behaviour unchanged."""
    import cpsat_v2_timetable as cv2

    profs, classes, triples, class_profs, dc_value = _tiny_day_fixture()

    res = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc_value,
        time_limit=10, workers=2,
        enforce_no_holes=False,
    )
    assert isinstance(res, tuple) and len(res) == 2
    out, status = res
    assert out is not None
