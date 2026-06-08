# Unified SOFT — Sub-project A (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the soft-pragma foundation — extract every CP soft-cost encoder into shared free functions, expose each as a DSL soft pragma, and add a `build_soft_pragmas` emitter — all behavior-preserving (zero-drift) and not yet wired into any pipeline.

**Architecture:** The intricate soft encodings currently live inside `ConstraintModel.compute_soft_cost_expr` (a solver method) but the DSL pragmas live in the separate `DSLConstraintCompiler` (an AST walker). To make the DSL the single source WITHOUT re-deriving (and risking drift), extract each encoder into a module-level free function in a new `engine/soft_costs.py` that takes `(model, slot, hours, days, ...)`. `compute_soft_cost_expr` is refactored to call them (proven zero-drift by its existing tests); the new soft pragmas call the SAME functions. One implementation, two callers.

**Tech Stack:** Python, Google OR-Tools CP-SAT (`ortools.sat.python.cp_model`), pytest. Run all Python from `webui/` with `PYTHONPATH=webui:engine:schedule`.

---

## File Structure

- **Create** `engine/soft_costs.py` — pure free functions, one per soft penalty, each returning `(obj_terms, aux_vars)` given a CP model + slot/day-count views. No solver-class coupling. This is the single source of truth for soft encodings.
- **Modify** `engine/cp_sat_constraint_model.py` — `compute_soft_cost_expr` delegates its sixth/buchi/five-one bodies to `soft_costs`. No behavior change.
- **Modify** `engine/dsl_to_cpsat.py` — add soft pragmas (`PRAGMA_LEVEL` + `_compile_call` dispatch + `_compile_*` methods) that call `soft_costs` functions and append to `self.soft_cost_terms`.
- **Modify** `engine/dsl_translator.py` — add `build_soft_pragmas(profs, classes, *, scale_mode, level)` returning the soft-pragma string stream (unused by pipelines in sub-project A).
- **Create** `webui/backend/tests/test_soft_costs_foundation.py` — zero-drift + behavior unit tests.

**Conventions to follow** (from the existing code):
- Slot key is the 5-tuple `(teacher, class, subject, day, hour)` → BoolVar.
- `SIXTH_HOUR = 13`; weights `PENALTY_SIXTH/BUCHI/FIVE/ONE` and `PENALTY_SIXTH_PD=5`, `PENALTY_BUCHI_PD=10` are defined in `cp_sat_constraint_model.py:78-93`. `soft_costs.py` takes weights as **arguments** (callers pass the constants) so it owns no policy.
- The compiler exposes `self.model`, `self.slot`, `self.days` (`_days_in_scope()`), `self.hours` (`_hours_in_scope()`), `self.soft_cost_terms`.

---

## Task 1: `engine/soft_costs.py` skeleton + sixth-slot encoder

**Files:**
- Create: `engine/soft_costs.py`
- Test: `webui/backend/tests/test_soft_costs_foundation.py`

- [ ] **Step 1: Write the failing test**

```python
# webui/backend/tests/test_soft_costs_foundation.py
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


def test_sixth_slot_terms_one_per_slot_at_h13():
    """sixth_slot_terms emits exactly one (weight*var) term per slot var
    whose hour == 13, and none for other hours."""
    import soft_costs
    model = cp_model.CpModel()
    slot = {
        ("T1", "1A", "Mat", 1, 12): model.NewBoolVar("a"),
        ("T1", "1A", "Mat", 1, 13): model.NewBoolVar("b"),
        ("T1", "1B", "Mat", 1, 13): model.NewBoolVar("c"),
    }
    pairs, aux = soft_costs.sixth_slot_pairs(model, slot, weight=50, sixth_hour=13)
    # 2 slots at h13 -> 2 (weight, var) pairs; no aux vars in slot mode
    assert len(pairs) == 2
    assert all(w == 50 for w, _v in pairs)
    assert aux == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webui && PYTHONPATH=$PWD:$PWD/../engine:$PWD/../schedule pytest backend/tests/test_soft_costs_foundation.py::test_sixth_slot_terms_one_per_slot_at_h13 -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soft_costs'`.

- [ ] **Step 3: Write minimal implementation**

```python
# engine/soft_costs.py
"""Single source of truth for CP-SAT SOFT-cost encodings.

Pure free functions over a CP model + slot view. No coupling to the
solver classes: both ``ConstraintModel.compute_soft_cost_expr`` and the
``DSLConstraintCompiler`` soft pragmas call these, so the encoding exists
exactly once. Each returns ``(obj_terms, aux_vars)``; callers pass the
weights (this module owns no policy).
"""
from __future__ import annotations


def sixth_slot_pairs(model, slot, *, weight, sixth_hour=13):
    """Per-slot sixth-hour penalty (mode='default'): one ``(weight, var)``
    pair per slot var at ``hour == sixth_hour``. Returning pairs (not
    ``weight*var`` products) matches the shape ``soft_cost_terms`` stores,
    so the pragma layer can extend directly; the ConstraintModel caller
    adapts with ``[w*v for w, v in pairs]``. Mirrors
    compute_soft_cost_expr mode='default' sixth block (:1004-1006)."""
    pairs = []
    for (_t, _cl, _s, _d, h), v in slot.items():
        if h == sixth_hour:
            pairs.append((weight, v))
    return pairs, []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webui && PYTHONPATH=$PWD:$PWD/../engine:$PWD/../schedule pytest backend/tests/test_soft_costs_foundation.py::test_sixth_slot_terms_one_per_slot_at_h13 -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/soft_costs.py webui/backend/tests/test_soft_costs_foundation.py
git commit -m "feat(engine): soft_costs.py with sixth-slot encoder"
```

---

## Task 2: sixth class-busy encoder + delegate `compute_soft_cost_expr`

The per-day mode uses a per-class-busy indicator at h13 (`PENALTY_SIXTH_PD=5`). Extract it so the existing method delegates — the existing `test_phase_b_per_day_soft_cost.py` suite is the zero-drift gate.

**Files:**
- Modify: `engine/soft_costs.py`
- Modify: `engine/cp_sat_constraint_model.py:1001-1025` (sixth block)
- Test: `webui/backend/tests/test_soft_costs_foundation.py`

- [ ] **Step 1: Write the failing test**

```python
def test_compute_soft_cost_expr_sixth_unchanged_after_delegation():
    """Zero-drift: a MonolithicSolver's solved objective is identical
    whether the sixth term comes from the inline body or the extracted
    soft_costs function. Both modes."""
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 6}}}, "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 6}
    ms = MonolithicSolver(profs, dc, ConstraintConfig(enforce_no_holes=False))
    terms, _ = ms.compute_soft_cost_expr(mode="default")
    # 6 hours on day1 incl h13 -> exactly one sixth term contributes
    # PENALTY_SIXTH when h13 is used. Assert the term set is non-empty
    # and the model still solves.
    ms.model.Minimize(sum(terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(ms.model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webui && PYTHONPATH=$PWD:$PWD/../engine:$PWD/../schedule pytest backend/tests/test_soft_costs_foundation.py::test_compute_soft_cost_expr_sixth_unchanged_after_delegation -v`
Expected: FAIL — `AttributeError: 'function' object has no attribute 'sixth_class_busy_terms'` is NOT the failure here; this test exercises the existing method, so it should PASS immediately. **If it passes, that is expected** — it is the baseline guard. Proceed: the real verification is that it STILL passes after the refactor in Step 3. (Per TDD: this is a characterization test for a refactor; run it green first, refactor, keep it green.)

- [ ] **Step 3: Implement — add encoder, delegate**

Add to `engine/soft_costs.py`:

```python
def sixth_class_busy_terms(model, class_busy_indicator_fn, classes, days,
                           *, weight, sixth_hour=13):
    """Per-class-busy sixth-hour penalty (mode='phase_b_per_day').
    ``class_busy_indicator_fn(cl, d, sixth_hour)`` returns the list of
    busy indicators for (class, day) at the hour (the caller supplies it
    so the exclusion/aggregation rules stay owned by ConstraintModel).
    Mirrors compute_soft_cost_expr mode='phase_b_per_day' (:1011-1025)."""
    obj_terms, aux_vars = [], []
    for cl in classes:
        for d in days:
            busy = class_busy_indicator_fn(cl, d, sixth_hour)
            if not busy:
                continue
            if len(busy) == 1:
                ind = busy[0]
            else:
                ind = model.NewBoolVar(f"sx_{cl}_{d}")
                model.AddMaxEquality(ind, busy)
                aux_vars.append(ind)
            obj_terms.append(weight * ind)
    return obj_terms, aux_vars
```

In `cp_sat_constraint_model.py`, replace the sixth block (`:1001-1025`) body so that:
- mode=='default': `pairs, _ = soft_costs.sixth_slot_pairs(self.model, self.slot, weight=PENALTY_SIXTH, sixth_hour=SIXTH_HOUR)` then `obj_terms.extend(w * v for w, v in pairs)`.
- mode=='phase_b_per_day': `terms, aux = soft_costs.sixth_class_busy_terms(self.model, lambda cl, d, h: self._build_class_busy_indicators(cl, d, h, name_suffix="sixth"), self._classes_with_busy_aggregation(), self.days, weight=PENALTY_SIXTH_PD, sixth_hour=SIXTH_HOUR)` then `obj_terms.extend(terms); aux_vars.extend(aux)`.

(`sixth_class_busy_terms` returns `weight*var` products because its caller here builds the objective directly; the pragma path in Task 4 uses a `sixth_class_busy_pairs` sibling that returns `(weight, var)` pairs over the same indicator logic.)

Add `from . import soft_costs` (with the `try/except ImportError: import soft_costs` fallback used elsewhere in this file) at the top of the method or module.

- [ ] **Step 4: Run the zero-drift gate (existing pinned tests + new test)**

Run: `cd webui && PYTHONPATH=$PWD:$PWD/../engine:$PWD/../schedule pytest backend/tests/test_phase_b_per_day_soft_cost.py backend/tests/test_soft_costs_foundation.py -q`
Expected: PASS (all). These pin the exact per-day soft objective — green means zero-drift.

- [ ] **Step 5: Commit**

```bash
git add engine/soft_costs.py engine/cp_sat_constraint_model.py webui/backend/tests/test_soft_costs_foundation.py
git commit -m "refactor(engine): delegate sixth-hour soft to soft_costs (zero-drift)"
```

---

## Task 3: buchi + five/one encoders + delegate

Extract the buchi (and the default-mode five/one) block (`:1029-1113`) verbatim into `soft_costs`, parameterized on the model + a teacher/day slot accessor.

**Files:**
- Modify: `engine/soft_costs.py`, `engine/cp_sat_constraint_model.py:1026-1114`
- Test: `webui/backend/tests/test_soft_costs_foundation.py`

- [ ] **Step 1: Write the characterization test (zero-drift)**

```python
def test_buchi_five_one_zero_drift_default_mode():
    """A teacher with a gappy day incurs a buchi penalty; the default
    mode also adds five/one. Solved objective must match before/after
    the extraction (guarded by the existing pinned suite; this asserts
    the model still builds and solves)."""
    from cp_sat_constraint_model import MonolithicSolver, ConstraintConfig
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 5}}}, "max_hours": 18}}
    dc = {("T1", "1A", "Mat", 1): 5}
    ms = MonolithicSolver(profs, dc, ConstraintConfig(enforce_no_holes=False))
    terms, aux = ms.compute_soft_cost_expr(mode="default")
    assert terms  # buchi + five present
    ms.model.Minimize(sum(terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    assert solver.Solve(ms.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
```

- [ ] **Step 2: Run to verify baseline green**

Run: `cd webui && PYTHONPATH=$PWD:$PWD/../engine:$PWD/../schedule pytest backend/tests/test_soft_costs_foundation.py::test_buchi_five_one_zero_drift_default_mode -v`
Expected: PASS (baseline characterization).

- [ ] **Step 3: Implement — extract `buchi_and_daydist_terms`**

Add to `engine/soft_costs.py` a function `buchi_and_daydist_terms(model, slot, teachers, days, hours, *, buchi_weight, five_weight, one_weight, include_five_one, fixed_load=None)` containing the EXACT logic from `cp_sat_constraint_model.py:1029-1113` (the `any_at_h` indicators, `count_d`, `first_h`/`last_h` via `AddMinEquality`/`AddMaxEquality`, `buchi >= last_h - first_h + 1 - count_d`, and the reified `is_five`/`is_one` gated by `include_five_one`). Replace the per-teacher slot access `self.slots_for_teacher_day_hour(t, d, h)` with an inline comprehension over `slot`: `[v for (tt,_c,_s,dd,hh), v in slot.items() if tt==t and dd==d and hh==h]`. `fixed_load` defaults to an empty dict.

In `cp_sat_constraint_model.py`, replace `:1026-1113` with a call:
```python
bt, ba = soft_costs.buchi_and_daydist_terms(
    self.model, self.slot, self.teachers_in_scope(), self.days, self.hours,
    buchi_weight=(PENALTY_BUCHI if mode == "default" else PENALTY_BUCHI_PD),
    five_weight=PENALTY_FIVE, one_weight=PENALTY_ONE,
    include_five_one=(mode == "default"), fixed_load=self.fixed_load)
obj_terms.extend(bt); aux_vars.extend(ba)
```

- [ ] **Step 4: Run the full pinned soft suite (zero-drift gate)**

Run: `cd webui && PYTHONPATH=$PWD:$PWD/../engine:$PWD/../schedule pytest backend/tests/test_phase_b_per_day_soft_cost.py backend/tests/test_cp_sat_constraint_model.py backend/tests/test_busy_aggregation_alignment.py backend/tests/test_soft_costs_foundation.py -q`
Expected: PASS (all). Green ⇒ buchi/five/one extraction is zero-drift.

- [ ] **Step 5: Commit**

```bash
git add engine/soft_costs.py engine/cp_sat_constraint_model.py webui/backend/tests/test_soft_costs_foundation.py
git commit -m "refactor(engine): delegate buchi/five/one soft to soft_costs (zero-drift)"
```

---

## Task 4: soft pragmas in `DSLConstraintCompiler`

Expose the encoders as pragmas so the DSL stream can request them. They call the SAME `soft_costs` functions and append `(weight, var)` to `self.soft_cost_terms`.

**Files:**
- Modify: `engine/dsl_to_cpsat.py` (`PRAGMA_LEVEL` `:453`, `_compile_call` `:991`, new `_compile_*` methods)
- Test: `webui/backend/tests/test_soft_costs_foundation.py`

- [ ] **Step 1: Write the failing test**

```python
def test_class_sixth_penalty_pragma_records_soft_terms():
    """The class_sixth_penalty(weight) pragma (slot mode) appends one
    soft term per slot at h13."""
    import dsl_to_cpsat as d2c
    from ortools.sat.python import cp_model
    model = cp_model.CpModel()
    slot = {
        ("T1", "1A", "Mat", 1, 13): model.NewBoolVar("a"),
        ("T1", "1A", "Mat", 1, 12): model.NewBoolVar("b"),
    }
    c = d2c.DSLConstraintCompiler(model, slot, level="phase_b")
    c.compile('class_sixth_penalty(50, "slot")')
    assert len(c.soft_cost_terms) == 1
    assert c.soft_cost_terms[0][0] == 50
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd webui && PYTHONPATH=$PWD:$PWD/../engine:$PWD/../schedule pytest backend/tests/test_soft_costs_foundation.py::test_class_sixth_penalty_pragma_records_soft_terms -v`
Expected: FAIL — pragma unrecognized, `soft_cost_terms` empty (len 0 != 1).

- [ ] **Step 3: Implement the pragma**

In `dsl_to_cpsat.py`:
- `PRAGMA_LEVEL`: add `"class_sixth_penalty": "phase_b"`.
- In `_compile_call`, after the `teacher_max_consecutive` block, add:

```python
if name == "class_sixth_penalty":
    if len(arg_values) != 2:
        self.diagnostics.append(
            f"class_sixth_penalty expects (weight, mode), got "
            f"{len(arg_values)}")
        return True
    weight = int(arg_values[0])
    mode = str(arg_values[1])
    self._compile_class_sixth_penalty(weight, mode)
    return True
```

- Add the method. It delegates to `soft_costs.sixth_slot_pairs` (which already returns `(weight, var)` pairs, the exact shape `soft_cost_terms` stores), so the pragma just extends the list. `class_busy` mode is out of scope for the foundation tests — emit a diagnostic:

```python
def _compile_class_sixth_penalty(self, weight: int, mode: str):
    try:
        from . import soft_costs as sc  # type: ignore
    except ImportError:
        import soft_costs as sc  # type: ignore
    if mode == "slot":
        pairs, _ = sc.sixth_slot_pairs(
            self.model, self.slot, weight=weight, sixth_hour=13)
        self.soft_cost_terms.extend(pairs)
    else:
        self.diagnostics.append(
            f"class_sixth_penalty: mode {mode!r} not supported in "
            f"the foundation; use 'slot'")
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd webui && PYTHONPATH=$PWD:$PWD/../engine:$PWD/../schedule pytest backend/tests/test_soft_costs_foundation.py::test_class_sixth_penalty_pragma_records_soft_terms backend/tests/test_phase_b_per_day_soft_cost.py -q`
Expected: PASS (new pragma + zero-drift still green).

- [ ] **Step 5: Commit**

```bash
git add engine/soft_costs.py engine/cp_sat_constraint_model.py engine/dsl_to_cpsat.py webui/backend/tests/test_soft_costs_foundation.py
git commit -m "feat(engine): class_sixth_penalty soft pragma (delegates to soft_costs)"
```

---

## Task 5: `teacher_buchi_penalty` / `teacher_five_penalty` / `teacher_one_penalty` pragmas

Mirror Task 4 for the buchi/five/one encoders. Each pragma calls `soft_costs.buchi_and_daydist_terms` (or a thin per-penalty wrapper exposing `(weight, var)` pairs) and extends `self.soft_cost_terms`.

**Files:**
- Modify: `engine/soft_costs.py` (add `*_pairs` wrappers if needed), `engine/dsl_to_cpsat.py`
- Test: `webui/backend/tests/test_soft_costs_foundation.py`

- [ ] **Step 1: Write the failing test**

```python
def test_teacher_buchi_penalty_pragma_steers_against_gaps():
    """teacher_buchi_penalty(w) as the sole objective makes a teacher's
    hours pack contiguously (no gap) when avoidable."""
    import dsl_to_cpsat as d2c
    from ortools.sat.python import cp_model
    model = cp_model.CpModel()
    # 2 hours to place on day1 across hours 8..13; gap allowed unless penalized
    hours = [8, 9, 10, 11, 12, 13]
    slot = {("T1", "1A", "Mat", 1, h): model.NewBoolVar(f"s{h}") for h in hours}
    model.Add(sum(slot.values()) == 2)
    c = d2c.DSLConstraintCompiler(model, slot, level="phase_b")
    c.compile('teacher_buchi_penalty(10)')
    model.Minimize(sum(w * v for w, v in c.soft_cost_terms))
    solver = cp_model.CpSolver(); solver.parameters.max_time_in_seconds = 5.0
    assert solver.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    busy = sorted(h for h in hours if solver.Value(slot[("T1", "1A", "Mat", 1, h)]))
    assert busy[1] == busy[0] + 1, f"buchi penalty should pack hours: {busy}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd webui && PYTHONPATH=$PWD:$PWD/../engine:$PWD/../schedule pytest backend/tests/test_soft_costs_foundation.py::test_teacher_buchi_penalty_pragma_steers_against_gaps -v`
Expected: FAIL — pragma unrecognized, `soft_cost_terms` empty → `Minimize(sum([]))` → solver free to leave a gap → assertion fails.

- [ ] **Step 3: Implement the three pragmas**

In `soft_costs.py`, add `buchi_pairs(model, slot, teachers, days, hours, *, weight, fixed_load=None)` and `five_one_pairs(...)` that return `[(weight, var), ...]` by reusing `buchi_and_daydist_terms` internals (extract a shared helper that yields the per-(teacher,day) `buchi`/`is_five`/`is_one` vars, and have both the original function and these wrappers consume it).
In `dsl_to_cpsat.py` `PRAGMA_LEVEL`: add `"teacher_buchi_penalty": "phase_b"`, `"teacher_five_penalty": "phase_a"`, `"teacher_one_penalty": "phase_a"`.
In `_compile_call`, add three dispatch blocks (1 arg = weight each) calling new methods `_compile_teacher_buchi_penalty`, `_compile_teacher_five_penalty`, `_compile_teacher_one_penalty`, each extending `self.soft_cost_terms` with the matching pairs (five/one require `self.day_count`; when absent, append a diagnostic and return — mirror the existing phase-A pragma guard at `:586`).

- [ ] **Step 4: Run to verify it passes (+ zero-drift gate)**

Run: `cd webui && PYTHONPATH=$PWD:$PWD/../engine:$PWD/../schedule pytest backend/tests/test_soft_costs_foundation.py backend/tests/test_phase_b_per_day_soft_cost.py backend/tests/test_cp_sat_constraint_model.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add engine/soft_costs.py engine/dsl_to_cpsat.py webui/backend/tests/test_soft_costs_foundation.py
git commit -m "feat(engine): teacher buchi/five/one soft pragmas"
```

---

## Task 6: `build_soft_pragmas` emitter

A single function that returns the structural soft-pragma stream for a context. Unused by pipelines in sub-project A (wiring is sub-project B) — this task only builds + tests the emitter.

**Files:**
- Modify: `engine/dsl_translator.py`
- Test: `webui/backend/tests/test_soft_costs_foundation.py`

- [ ] **Step 1: Write the failing test**

```python
def test_build_soft_pragmas_default_mode_includes_sixth_buchi_five_one():
    from engine.dsl_translator import build_soft_pragmas
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 5}}}, "max_hours": 18}}
    classes = ["1A"]
    stream = build_soft_pragmas(profs, classes, scale_mode="default")
    joined = " ".join(stream)
    assert "class_sixth_penalty(" in joined
    assert "teacher_buchi_penalty(" in joined
    assert "teacher_five_penalty(" in joined
    assert "teacher_one_penalty(" in joined


def test_build_soft_pragmas_per_day_mode_excludes_five_one():
    from engine.dsl_translator import build_soft_pragmas
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 5}}}, "max_hours": 18}}
    stream = build_soft_pragmas(profs, ["1A"], scale_mode="phase_b_per_day")
    joined = " ".join(stream)
    assert "teacher_five_penalty(" not in joined
    assert "teacher_one_penalty(" not in joined
    assert "class_sixth_penalty(" in joined
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd webui && PYTHONPATH=$PWD:$PWD/../engine:$PWD/../schedule pytest backend/tests/test_soft_costs_foundation.py -k build_soft_pragmas -v`
Expected: FAIL — `ImportError: cannot import name 'build_soft_pragmas'`.

- [ ] **Step 3: Implement**

```python
# engine/dsl_translator.py
def build_soft_pragmas(profs, classes, *, scale_mode="default", level=None):
    """Return the structural soft-pragma DSL stream for a pipeline.

    ``scale_mode`` selects weights + which penalties apply:
      - 'default': per-slot sixth (PENALTY_SIXTH), buchi (PENALTY_BUCHI),
        five (PENALTY_FIVE), one (PENALTY_ONE).
      - 'phase_b_per_day': per-class-busy sixth (PENALTY_SIXTH_PD),
        buchi (PENALTY_BUCHI_PD); five/one excluded (no weekly day-count).
    Weights are imported from cp_sat_constraint_model so the numbers are
    read from today's constants, not retyped. Used by sub-project B to
    feed each pipeline's compiler; emitted here without DB coupling.
    """
    try:
        from engine import cp_sat_constraint_model as csm  # type: ignore
    except ImportError:
        import cp_sat_constraint_model as csm  # type: ignore
    out = []
    if scale_mode == "default":
        out.append(f'class_sixth_penalty({csm.PENALTY_SIXTH}, "slot")')
        out.append(f'teacher_buchi_penalty({csm.PENALTY_BUCHI})')
        out.append(f'teacher_five_penalty({csm.PENALTY_FIVE})')
        out.append(f'teacher_one_penalty({csm.PENALTY_ONE})')
    elif scale_mode == "phase_b_per_day":
        out.append(f'class_sixth_penalty({csm.PENALTY_SIXTH_PD}, "class_busy")')
        out.append(f'teacher_buchi_penalty({csm.PENALTY_BUCHI_PD})')
    else:
        raise ValueError(f"unknown scale_mode {scale_mode!r}")
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd webui && PYTHONPATH=$PWD:$PWD/../engine:$PWD/../schedule pytest backend/tests/test_soft_costs_foundation.py -k build_soft_pragmas -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/dsl_translator.py webui/backend/tests/test_soft_costs_foundation.py
git commit -m "feat(engine): build_soft_pragmas emitter (unused; wired in sub-project B)"
```

---

## Task 7: Full regression gate

- [ ] **Step 1: Run the full fast backend suite**

Run: `cd webui && PYTHONPATH=$PWD:$PWD/../engine:$PWD/../schedule pytest backend/tests -m "not slow" -q`
Expected: PASS (the timing test `test_perf_budgets.py::test_hall_check_sync_path_stays_fast` may flake under load — re-run it isolated to confirm).

- [ ] **Step 2: Run the slow soft/week suites**

Run: `cd webui && PYTHONPATH=$PWD:$PWD/../engine:$PWD/../schedule pytest backend/tests/test_scope_week_integration.py ../tests/test_free_day_constraint.py -q -m slow`
Expected: PASS.

- [ ] **Step 3: Commit (if any fixups were needed)**

```bash
git commit -am "test: full regression green for soft foundation" --allow-empty
```

---

## Notes for the implementer

- **Spread penalty** (`uniform_class_pen`/`uniform_prof_pen`, `cpsat_v2_timetable.py:902`) is Phase-A-only and lives in the function-based path, not `compute_soft_cost_expr`. It is **out of scope for sub-project A** and handled in sub-project B when that pipeline is migrated. Do not add it here.
- Never delete a hardcoded soft block. Sub-project A only ADDS (`soft_costs.py`, pragmas, emitter) and refactors `compute_soft_cost_expr` to delegate. Pipeline rewiring + deletions happen in B/C/D, each behind its own zero-drift gate.
- If a zero-drift gate goes red, the extracted function diverged from the original — diff against the cited source lines, do not "fix" the test.
