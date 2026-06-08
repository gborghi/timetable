# Solver-Compatibility Warning System Plan

> **For agentic workers:** superpowers:subagent-driven-development. Implementer + reviewer. Steps `- [ ]`.

**Goal:** Stop silently dropping DSL constraints a pipeline can't honor. Collect the diagnostics that already exist, STRUCTURE them into `{constraint, pipeline, reason, suggestion, severity}`, and SURFACE them (return from the solver + write to RunLog) so the frontend can show "constraint X was not enforced by solver Y — revise the constraint or the method."

**Background (investigated):** ~50 diagnostic-append sites already exist in `engine/dsl_to_cpsat.py` (per-construct "not yet supported / dynamic; skipped", pragma-level mismatch) and `engine/cpsat_v2_timetable.py` (`compile_failed`/`db_load_failed` at :1391/:1398/:1406/:1428). `solve_phase_b_for_day` builds a local `dsl_diagnostics` list but returns `(out, status)` and DISCARDS it (stdout only). The week path stores `solver.dsl_diagnostics` but only prints a count. Nothing reaches RunLog/UI. Per-pipeline capability differs: CP compilers (mono-week/per-day/decomp) skip un-modelable constructs; the metaheuristic post-hoc evaluator (`general_dsl.evaluate`) accepts more (e.g. dynamic nested forall) — this asymmetry drives the "suggestion."

**Frontend-agnostic:** the classifier/structuring lives in the ENGINE (`engine/constraint_compat.py`), pure, no webui imports. The orchestration (webui) maps it to RunLog. The frontend modal consumes RunLog (out of scope here — the data becomes available).

**Test policy:** functional/contract sacred (solving still works; warnings are ADDITIVE — a dropped constraint still doesn't crash). New behavior = diagnostics now surfaced. Commit + push per task.

---

## File Structure
- **Create** `engine/constraint_compat.py` — pure: `ConstraintWarning` dataclass + `classify_diagnostic` + `suggest` + `summarize`.
- **Modify** `engine/cpsat_v2_timetable.py` — `solve_phase_b_for_day(..., diagnostics_sink=None)`: when provided, `diagnostics_sink.extend(dsl_diagnostics)` (non-breaking; return shape unchanged).
- **Modify** `webui/backend/optimization.py` — the per-day + week orchestration: pass a sink, `summarize`, write warnings to RunLog.
- **Create** `webui/backend/tests/test_constraint_compat.py` + `tests` for the sink + surfacing.

---

## Task 1: `engine/constraint_compat.py` + the diagnostics sink

**Files:** Create `engine/constraint_compat.py`; modify `engine/cpsat_v2_timetable.py`. Test: `webui/backend/tests/test_constraint_compat.py`.

- [ ] **Step 1: failing unit test**
Write tests for the pure module:
```python
def test_classify_and_summarize_compile_failed():
    import constraint_compat as cc
    diags = [
        'compile_failed:Docente Rossi non disp.:KeyError:foo',
        "forall body dynamic and not nested-forall; skipped",
        "pragma teacher_five_penalty (level=phase_a) skipped: compiler level=phase_b",
    ]
    warns = cc.summarize(diags, pipeline="per_day_cpsat")
    assert len(warns) == 3
    w0 = warns[0]
    assert w0.pipeline == "per_day_cpsat"
    assert "Rossi" in w0.constraint or "Rossi" in w0.reason
    assert w0.suggestion  # non-empty
    assert w0.severity in ("warning", "error", "info")
    # dynamic-body constraints: suggestion should mention metaheuristic post-hoc
    dyn = [w for w in warns if "dynamic" in w.reason.lower()]
    assert dyn and "metaheuristic" in dyn[0].suggestion.lower()
    # all serialise
    assert all(isinstance(w.to_dict(), dict) for w in warns)
```
Run → FAIL (module missing).

- [ ] **Step 2: implement `engine/constraint_compat.py`**
```python
from __future__ import annotations
from dataclasses import dataclass, asdict

@dataclass
class ConstraintWarning:
    constraint: str       # label / best-effort identifier
    pipeline: str         # e.g. "per_day_cpsat", "week_cpsat", "metaheuristic"
    reason: str           # human-readable why it wasn't honored
    suggestion: str       # what the user can do
    severity: str = "warning"   # info | warning | error
    raw: str = ""         # the original diagnostic string
    def to_dict(self):
        return asdict(self)

# category detection from the existing diagnostic string forms
def classify_diagnostic(diag: str) -> tuple[str, str, str]:
    """Return (category, constraint_label, reason)."""
    d = diag.strip()
    if d.startswith("compile_failed"):
        parts = d.split(":", 3)
        label = parts[1] if len(parts) > 1 else "(unknown)"
        reason = (parts[3] if len(parts) > 3 else d)
        return "compile_failed", label, f"compile error: {reason}"
    if d.startswith("db_load_failed") or d.startswith("dsl_augmentation_failed"):
        return "load_failed", "(rule set)", d
    if "dynamic" in d and "skipped" in d:
        return "dynamic_unsupported", "(dynamic constraint)", d
    if d.startswith("pragma ") and "skipped" in d:
        return "pragma_level_mismatch", d.split()[1] if len(d.split())>1 else "(pragma)", d
    if "not yet supported" in d:
        return "unsupported_construct", "(construct)", d
    if "loaded" in d and "DSL rules" in d:
        return "info", "(loader)", d
    return "other", "(constraint)", d

_SUGGEST = {
    "compile_failed": "The {pipeline} solver could not build this constraint. "
        "Check the rule's syntax/entities, or run a metaheuristic post-pass "
        "(it evaluates all DSL constraints on the finished timetable).",
    "dynamic_unsupported": "This constraint is too dynamic for the {pipeline} "
        "CP solver to model directly. A metaheuristic post-pass enforces it "
        "post-hoc, or simplify it to a per-slot / static form.",
    "unsupported_construct": "The {pipeline} compiler does not model this "
        "construct yet. Try a metaheuristic post-pass, or rephrase the rule.",
    "pragma_level_mismatch": "This rule applies to a different solve phase than "
        "{pipeline}; it is enforced where its phase runs. No action needed if "
        "another phase covers it.",
    "load_failed": "The rule set failed to load for {pipeline}. Check the DB "
        "rules; re-run after fixing.",
    "other": "This rule was not fully honored by {pipeline}. Review it or try "
        "a different method.",
}

def suggest(category: str, pipeline: str) -> str:
    return _SUGGEST.get(category, _SUGGEST["other"]).format(pipeline=pipeline)

def summarize(diagnostics, *, pipeline: str) -> list[ConstraintWarning]:
    out, seen = [], set()
    for diag in diagnostics or []:
        cat, label, reason = classify_diagnostic(str(diag))
        if cat == "info":
            continue   # informational loader lines are not warnings
        key = (cat, label, reason)
        if key in seen:
            continue
        seen.add(key)
        sev = "error" if cat in ("compile_failed", "load_failed") else "warning"
        out.append(ConstraintWarning(
            constraint=label, pipeline=pipeline, reason=reason,
            suggestion=suggest(cat, pipeline), severity=sev, raw=str(diag)))
    return out
```

- [ ] **Step 3: thread `diagnostics_sink` out of `solve_phase_b_for_day`**
Add `diagnostics_sink=None` (keyword-only). READ the function: it builds a local `dsl_diagnostics` list. Right before each `return`, add: `if diagnostics_sink is not None: diagnostics_sink.extend(dsl_diagnostics)`. Default None → no behavior change, return shape unchanged. Add a test: call `solve_phase_b_for_day` with `via_dsl=True`, a `db` holding a rule the per-day CP compiler can't fully model (find/construct one — e.g. a dynamic nested-forall over a non-`lessons` source, or use an `extra_dsl_expressions=["<an unsupported construct>"]`), and a `sink=[]`; assert the sink is non-empty AND `constraint_compat.summarize(sink, pipeline="per_day_cpsat")` yields a warning with a non-empty suggestion. [Functional: the solve still returns a feasible result — the bad rule is warned, not fatal.]

- [ ] **Step 4: verify** `pytest backend/tests/test_constraint_compat.py -q` + `pytest backend/tests/test_b2_per_day_table_soft.py backend/tests/test_b1_per_day_soft_migration.py -q` (per-day still green). Push.

- [ ] **Step 5: commit + push** `git commit -m "feat(engine): constraint_compat warnings + solve_phase_b diagnostics_sink"; git push origin main`

---

## Task 2: surface warnings to RunLog in the orchestration

**Files:** Modify `webui/backend/optimization.py`. Test: a backend test that a run with an un-modelable constraint produces a RunLog WARNING.

- [ ] **Step 1: failing test** — READ how `run_phase_b` / `_solve_phase_b_per_day` (or the per-day loop) calls `solve_phase_b_for_day`, and how `run_manager`/RunLog writes log lines (find the log-writing API — e.g. a `log(run_id, msg, level=...)` or appending RunLog rows). Write a test: trigger a per-day run (or call the orchestration helper directly) with a DB rule the per-day CP can't model; assert a RunLog entry (or the run result) contains a structured warning naming the constraint + the suggestion. Run → FAIL (no warning surfaced today).

- [ ] **Step 2: implement** — in the per-day orchestration: build `sink = []`, pass `diagnostics_sink=sink` into every `solve_phase_b_for_day(...)` call (across days), then after solving: `warns = constraint_compat.summarize(sink, pipeline="per_day_cpsat")`; for each, write a RunLog WARNING line (use the existing RunLog/run_manager API) like `f"[constraint] {w.constraint}: {w.reason} — {w.suggestion}"`, and/or attach `[w.to_dict() for w in warns]` to the run result/telemetry. Do the same for the week path using `solver.dsl_diagnostics` + `pipeline="week_cpsat"`. Import `constraint_compat` via the engine import idiom.

- [ ] **Step 3: verify** the new test + `pytest backend/tests -k "phase_b or scope_week or run_manager or optimization" -q -m "not slow"` green. Rewrite any OUTCOME test that asserted no-warnings (note it).

- [ ] **Step 4: commit + push** `git commit -m "feat(backend): surface solver-compat warnings to RunLog"; git push origin main`

---

## Task 3: (metaheuristic capability note) + regression
- [ ] In `compute_soft`/`is_hard_feasible`, the post-hoc evaluator skips unevaluable rules silently. OPTIONAL: collect those skips into a sink too (pipeline="metaheuristic") for symmetry. If too invasive, note in `log.md` and skip.
- [ ] Regression: `pytest backend/tests -m "not slow" -q` (known perf flakes isolated). Commit + push.

---

## Notes
- The classifier parses the EXISTING free-text diagnostic strings. If a diagnostic format is ambiguous, default to category "other" with a generic suggestion (never crash on an unrecognized string).
- Keep `constraint_compat.py` free of any webui import (frontend-agnostic).
- The frontend modal that renders these warnings is out of scope — the data now reaches RunLog/the run result; a follow-up can render it.
- `no_same_class_consecutive_days(cl)` pragma + B-gen time-threshold pragmas are SEPARATE follow-ups (the DSL already expresses cross-day via nested forall; B-gen adds new soft types).
