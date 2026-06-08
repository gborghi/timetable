# Unified SOFT — Sub-project B1 (per-day Phase-B structural migration) Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Fresh implementer per task + spec review + code-quality review. Steps use `- [ ]`.

**Goal:** Make `cpsat_v2_timetable.solve_phase_b_for_day` source its structural soft (sixth + buchi) from the DSL pragma stream via its own `DSLConstraintCompiler`, deleting the inline `:1358-1367` objective. Behavior-preserving on objective VALUE.

**Architecture:** A's `build_soft_pragmas(scale_mode="phase_b_per_day")` emits `class_sixth_penalty(5,"class_busy")` + `teacher_buchi_penalty(10)`. The `class_busy` mode is currently a no-op stub — Task 1 implements it (delegating to `soft_costs.sixth_class_busy_terms` with a `self.slot`-derived busy callback). Task 2 builds the per-day slot compiler unconditionally, compiles that stream, and sets `objective = sum(w*v for compiler.soft_cost_terms)`. The loader stays `include_soft=False` (free-day stays single-sourced in Phase-A; B2 handles it).

**Tech:** Python, OR-Tools CP-SAT, pytest. Run from `webui/`; PowerShell: `Set-Location E:\giovanni\code\timetable\webui; $env:PYTHONPATH="$PWD;$PWD\..\engine;$PWD\..\schedule"; .\backend\.venv\Scripts\python -m pytest ...`.

**Zero-drift contract:** objective VALUE equality, NOT var structure. The legacy `gap_*` per-slot-hole encoding (one bool per interior empty slot) and `soft_costs.buchi` span−count encoding (`bch_*`, one IntVar per teacher-day) yield the same total. Weights match exactly: legacy `W_SIXTH_B=5`/`W_GAP=10` == `PENALTY_SIXTH_PD=5`/`PENALTY_BUCHI_PD=10`.

**Note (latitude granted by user):** tests may be broken/rewritten where restructuring requires it. Commit + push after each green task.

---

## File Structure

- **Modify** `engine/dsl_to_cpsat.py` — implement the `class_busy` branch in `_compile_class_sixth_penalty` (currently a diagnostic stub).
- **Modify** `engine/cpsat_v2_timetable.py` — `solve_phase_b_for_day`: build the slot-5 compiler unconditionally, compile `build_soft_pragmas(scale_mode="phase_b_per_day")`, set objective from `compiler.soft_cost_terms`; delete inline `sixth_terms`/`gap_terms`/`W_SIXTH_B`/`W_GAP`. Reuse the same compiler for the existing `via_dsl` hard-rule block.
- **Create** `webui/backend/tests/test_b1_per_day_soft_migration.py` — class_busy pragma unit test + value-based per-day zero-drift test.

---

## Task 1: implement the `class_busy` compile branch

**Files:**
- Modify: `engine/dsl_to_cpsat.py` (`_compile_class_sixth_penalty`)
- Test: `webui/backend/tests/test_b1_per_day_soft_migration.py`

- [ ] **Step 1: Write the failing test**

```python
# webui/backend/tests/test_b1_per_day_soft_migration.py
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
    model = cp_model.CpModel()
    slot = {
        ("TA", "1A", "Chim", 1, 13): model.NewBoolVar("a13"),
        ("TB", "1A", "Chim", 1, 13): model.NewBoolVar("b13"),
        ("TA", "1A", "Chim", 1, 12): model.NewBoolVar("a12"),
        ("TC", "1B", "Mat", 1, 13): model.NewBoolVar("c13"),
    }
    c = d2c.DSLConstraintCompiler(model, slot, level="phase_b")
    c.compile('class_sixth_penalty(5, "class_busy")')
    # 1A (TA+TB at h13) -> 1 aggregated term; 1B (TC at h13) -> 1 term.
    assert len(c.soft_cost_terms) == 2
    assert all(w == 5 for w, _v in c.soft_cost_terms)
```

- [ ] **Step 2: Run — expect FAIL** (today the `else` branch records a diagnostic, 0 terms):

`pytest backend/tests/test_b1_per_day_soft_migration.py::test_class_busy_mode_aggregates_one_term_per_class_at_h13 -v` → FAIL (`0 == 2`).

- [ ] **Step 3: Implement the branch**

In `engine/dsl_to_cpsat.py`, read the current `_compile_class_sixth_penalty`. Replace the non-`slot` `else` with a real `class_busy` branch. It must:
- derive `classes = sorted({k[1] for k in self.slot})`, `days = self._days_in_scope()`;
- define `busy_indicator_fn(cl, d, h)` returning `[v for (t, cc, s, dd, hh), v in self.slot.items() if cc == cl and dd == d and hh == h]` (every slot var for that class/day/hour — the per-class busy set);
- call `soft_costs.sixth_class_busy_terms(self.model, busy_indicator_fn, classes, days, weight=weight, sixth_hour=13)` which returns `(obj_terms_as_products, aux)`;
- BUT `soft_cost_terms` stores `(weight, var)` PAIRS, not products. `sixth_class_busy_terms` returns `weight*var` products. So instead add a sibling `sixth_class_busy_pairs` in `soft_costs.py` (mirroring `sixth_class_busy_terms` but appending `(weight, ind)` pairs), OR have the pragma reconstruct pairs. Cleanest: add `soft_costs.sixth_class_busy_pairs(model, busy_indicator_fn, classes, days, *, weight, sixth_hour=13)` returning `(pairs, aux)` that shares a private helper with `sixth_class_busy_terms` (extract `_sixth_class_busy_indicators` yielding the per-(cl,d) indicator var; both the products fn and the pairs fn consume it — same DRY pattern as `_buchi_daydist_vars`). The pragma calls the pairs variant and `self.soft_cost_terms.extend(pairs)`.

Keep the bad-mode (neither `slot` nor `class_busy`) diagnostic for any other string.

- [ ] **Step 4: Run — expect PASS**; also keep A-side green:

`pytest backend/tests/test_b1_per_day_soft_migration.py backend/tests/test_phase_b_per_day_soft_cost.py backend/tests/test_soft_costs_foundation.py -q` → all PASS.

- [ ] **Step 5: Commit**

```
git add engine/dsl_to_cpsat.py engine/soft_costs.py webui/backend/tests/test_b1_per_day_soft_migration.py
git commit -m "feat(engine): implement class_busy mode for class_sixth_penalty pragma (B1)"
```

---

## Task 2: migrate `solve_phase_b_for_day` objective to the pragma stream

**Files:**
- Modify: `engine/cpsat_v2_timetable.py` (`solve_phase_b_for_day`, the inline objective `:~1306-1367` + the `via_dsl` compiler block `:~1380-1419`)
- Test: `webui/backend/tests/test_b1_per_day_soft_migration.py`

- [ ] **Step 1: Write the value-based zero-drift test**

```python
def test_phase_b_per_day_objective_value_matches_legacy_on_tiny_fixture():
    """Solve a tiny single-day instance whose optimum placement is
    DETERMINED (4 contiguous hours), and assert the migrated objective
    value equals the hand-computed legacy cost.

    One class 1A, one teacher T1, 4 Mat hours on day 1, no_holes hard.
    Optimum placement = hours 8,9,10,11 (contiguous, no h13 used, no
    interior gap). Expected objective = 0 (no sixth-at-h13, no buchi).
    """
    import cpsat_v2_timetable as cv2
    cv2._apply_working_hours_config()  # ensure HOURS/DAYS from config
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 4}}}, "max_hours": 18}}
    dc_value = {("T1", "1A", "Mat", 1): 4}
    res = cv2.solve_phase_b_for_day(
        day=1, profs=profs, dc_value=dc_value)
    # solve_phase_b_for_day's return shape: confirm by reading the fn.
    # Assert it produced a feasible placement AND the objective value is 0
    # (the determined optimum pays no sixth/buchi penalty).
    assert res is not None
    # The 4 hours must be contiguous 8..11 (the only no_holes placement
    # that avoids h13 + gaps) -> objective 0.
    # (Extract placed (day,hour) from res; assert == {(1,8),(1,9),(1,10),(1,11)}.)
```

NOTE to implementer: **read `solve_phase_b_for_day`'s real signature + return shape first** (params: `day, profs, dc_value, ... via_dsl=..., db=...`; what it returns — solution dict? `(sol, status)`? objective?). Adapt the test to the real API. If the function does not currently expose the objective value, add a way to retrieve it (e.g. return the solver's `ObjectiveValue()` in the result, or expose a thin `_phase_b_objective_value` helper used by the test). A second fixture that DOES force a sixth/buchi cost (e.g. 6 hours → h13 used → sixth cost 5; or a placement with a forced gap → buchi 10) makes the test stronger — add it if the determined optimum is computable.

- [ ] **Step 2: Run — expect FAIL or baseline** (depends: if the legacy already yields 0 on this fixture the test passes pre-migration as a characterization guard; that is fine — it must STILL pass post-migration. If the API needs the objective exposed, it fails to import/attr first; wire that minimally.)

- [ ] **Step 3: Migrate**

In `solve_phase_b_for_day`:
1. **Lift the slot-5 compiler out of the `via_dsl` guard** so it is built unconditionally right before the objective:
```python
slot_5 = {(p, cl, s, day, h): v for (p, cl, s, h), v in slot.items()}
cfg5 = _csm.ConstraintConfig()
compiler = _d2c.DSLConstraintCompiler(model, slot_5, config=cfg5,
                                      classroom_for_slot=None, plessi_data=None)
```
   (import `_d2c`/`_csm` once, at the top of this region.)
2. **Compile the structural soft stream** and set the objective from it, REPLACING the inline `sixth_terms`/`gap_terms`/`W_SIXTH_B`/`W_GAP`/`Minimize` block:
```python
try:
    from . import dsl_translator as _dt  # type: ignore
except ImportError:
    import dsl_translator as _dt  # type: ignore
for _src in _dt.build_soft_pragmas(profs, list(cls_in_day),
                                   scale_mode="phase_b_per_day"):
    compiler.compile(_src)
soft_obj = [int(w) * v for (w, v) in compiler.soft_cost_terms]
if soft_obj:
    model.Minimize(sum(soft_obj))
```
3. **Reuse the SAME `compiler`** in the existing `via_dsl` hard-rule block (delete its now-duplicate `slot_5`/compiler construction; keep the `load_all_dsl_constraints(include_soft=False)` loop). The objective is set BEFORE the hard DSL rules are added — that's fine (hard rules don't touch the objective).
4. Delete `present_per_class`-based `sixth_terms` and the `gap_terms` loop ONLY if nothing else consumes them; if `present_per_class` is used elsewhere, keep its construction and just drop the objective wiring.

- [ ] **Step 4: Run the gate + per-day regression**

`pytest backend/tests/test_b1_per_day_soft_migration.py backend/tests/test_phase_b_per_day_soft_cost.py -q` → PASS.
Then a real per-day solve regression (slow): `pytest backend/tests/test_scope_week_integration.py -q -m slow` → PASS (or the known TS/LNS time-budget flakes only; re-run those isolated).

- [ ] **Step 5: Commit**

```
git add engine/cpsat_v2_timetable.py webui/backend/tests/test_b1_per_day_soft_migration.py
git commit -m "refactor(engine): per-day Phase-B objective from pragma stream (B1, value zero-drift)"
```

---

## Task 3: regression sweep + push

- [ ] **Step 1:** Fast backend suite: `pytest backend/tests -m "not slow" -q` → green (known `test_perf_budgets` timing flake re-run isolated).
- [ ] **Step 2:** Decomposition smoke (per-day reused by spectral/temporal): `pytest backend/tests -k "decomp or phase_b or scope_week" -q` → green.
- [ ] **Step 3:** Push:
```
git push origin main
```
(Pre-push hook only rebuilds the manual on top-level `docs/*.md` / `docs/*.tex` changes — B1 touches none, so no rebuild.)

---

## Notes for the implementer

- The `cls_in_day` variable already exists in `solve_phase_b_for_day` (used by the inline sixth). Pass it (as `classes`) to `build_soft_pragmas`; if its name differs, derive `classes = sorted({k[1] for k in slot})`.
- Do NOT flip the loader to `include_soft=True` here — that pulls free-day soft into Phase-B while Phase-A still counts `glib_pen` (double-count). B2 owns that.
- If a real per-day pinned test asserts the OLD `gap_*`/`sx_*` var structure, rewrite it to assert objective VALUE instead (user granted this latitude) — the encoding change is intentional and value-preserving.
- Keep `sixth_hour=13` hardcoded in the `class_busy` branch (grid-generality is B-gen).
