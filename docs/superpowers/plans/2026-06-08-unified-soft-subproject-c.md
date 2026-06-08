# Unified SOFT — Sub-project C (branch-and-price / column generation) Plan

> **For agentic workers:** superpowers:subagent-driven-development. Implementer + reviewer. Steps `- [ ]`.

**Goal:** Route column-generation pricer soft (buchi/five/one) through the shared `engine/soft_costs.py` single source, deleting the divergent `_add_full_soft_cost_terms` reimplementation. Behavior-preserving on objective VALUE; functional gate = all 9 BP granularities still iterate + assemble HARD-feasible.

**Background (investigated):** `engine/column_generation.py::_add_full_soft_cost_terms` (lines 532-637) is a byte-for-byte copy of `soft_costs._buchi_daydist_vars`'s logic (any_at_h indicators, count_d, first_h/last_h via min/max, `buchi >= last-first+1-count`, reified is_five/is_one). It returns `[_PENALTY_FIVE*is_five, _PENALTY_ONE*is_one, _PENALTY_BUCHI*buchi]` per (teacher,day). Weights `_PENALTY_* = meta.OBJECTIVE_WEIGHTS[...] * _SCALE(100)` == the `PENALTY_*` in `cp_sat_constraint_model`. It is called by all 9 pricer subproblems with `cpsat_vars_by_t_d_h` (a `(t,d,h)->[BoolVar]` dict) + `fixed_load_by_t_d_h`. CG has NO `soft_costs` usage today. Sixth is handled SEPARATELY in each pricer's objective loop (`if h == _SIXTH_HOUR: obj.append(_PENALTY_SIXTH*v)`), out of scope for the main task.

**The shape mismatch:** `soft_costs._buchi_daydist_vars` takes a 5-tuple `slot` dict and internally does `[v for (tt,_,_,dd,hh),v in slot.items() if tt==t and dd==d and hh==h]`. CG already HAS that exact per-(t,d,h) list as `cpsat_vars_by_t_d_h[(t,d,h)]`. So we refactor the core to accept an ACCESSOR callback, and both worlds share it.

**Test policy:** functional/contract sacred (9 granularities iterate + HARD-feasible); exact objective values / var names may change. Weights flow as ARGUMENTS (no hardcoded weight in the shared encoder). Commit + push per task.

---

## File Structure
- **Modify** `engine/soft_costs.py` — refactor `_buchi_daydist_vars` to take a `vars_at` callback (`vars_at(t,d,h) -> list[BoolVar]`) instead of a `slot` dict; the slot-based public wrappers (`buchi_and_daydist_terms`, `buchi_pairs`, `five_one_pairs`) pass a slot-derived accessor (behavior-preserving). Add a thin public `buchi_daydist_terms_from_accessor(model, vars_at, teachers, days, hours, *, buchi_weight, five_weight, one_weight, include_five_one, fixed_load)` returning the `(obj_terms_products, aux)` shape CG needs.
- **Modify** `engine/column_generation.py` — replace `_add_full_soft_cost_terms`'s body to delegate to `soft_costs.buchi_daydist_terms_from_accessor`, passing `vars_at = lambda t,d,h: cpsat_vars_by_t_d_h.get((t,d,h), [])`, the CG weights, `include_five_one=True`, and `fixed_load_by_t_d_h`. Keep its signature + return contract (list of `weight*var` products) so the 9 call sites are untouched.
- **Test** `tests/test_bp_granularities.py` (functional gate) + a new `webui/backend/tests/test_c_cg_soft_unified.py` (unit: the accessor path equals the slot path on a fixture).

---

## Task 1: refactor `_buchi_daydist_vars` to a callback accessor (zero-drift)

**Files:** Modify `engine/soft_costs.py`. Test: `webui/backend/tests/test_c_cg_soft_unified.py`.

- [ ] **Step 1: characterization test** — append a test that calls the EXISTING slot-based `buchi_and_daydist_terms` on a small fixture and records `len(obj_terms)` + that the model solves; this guards the refactor. Run → passes (baseline).

- [ ] **Step 2: refactor** — change `_buchi_daydist_vars(model, slot, teachers, days, hours, *, include_five_one, fixed_load=None)` so its internal per-(t,d,h) var access goes through a callback. Concretely: add `_buchi_daydist_vars_acc(model, vars_at, teachers, days, hours, *, include_five_one, fixed_load=None)` containing the CURRENT body but replacing the slot comprehension with `cpsat_at_h[h] = list(vars_at(t, d, h))`. Make `_buchi_daydist_vars(model, slot, ...)` delegate to it with `vars_at = lambda t,d,h: [v for (tt,_c,_s,dd,hh),v in slot.items() if tt==t and dd==d and hh==h]`. The public `buchi_and_daydist_terms`/`buchi_pairs`/`five_one_pairs` keep their slot signatures (call the slot wrapper). Add public `buchi_daydist_terms_from_accessor(model, vars_at, teachers, days, hours, *, buchi_weight, five_weight, one_weight, include_five_one, fixed_load=None)` that calls `_buchi_daydist_vars_acc` and forms the `[buchi_weight*buchi, five_weight*is_five, one_weight*is_one]`-per-record product list (matching `_add_full_soft_cost_terms`'s `extra.append` ORDER: five, one, buchi — READ the original to match its exact append order).

- [ ] **Step 3: zero-drift gate** — `pytest backend/tests/test_phase_b_per_day_soft_cost.py backend/tests/test_cp_sat_constraint_model.py backend/tests/test_soft_costs_foundation.py backend/tests/test_b1_per_day_soft_migration.py -q` → all PASS (the slot wrappers are byte-equivalent).

- [ ] **Step 4: commit + push** `git commit -m "refactor(engine): soft_costs buchi core via accessor callback (C prep)"; git push origin main`

---

## Task 2: delegate `_add_full_soft_cost_terms` to the shared core

**Files:** Modify `engine/column_generation.py`. Test: `webui/backend/tests/test_c_cg_soft_unified.py`, `tests/test_bp_granularities.py`.

- [ ] **Step 1: equivalence test** — build a tiny `cpsat_vars_by_t_d_h` over a fresh CpModel; call BOTH the OLD `_add_full_soft_cost_terms` (capture before changing it — copy it into the test as `_legacy`) and the NEW soft_costs accessor path; assert the returned term COUNT and that both models solve to the same objective bound on a fixed tiny problem. (If copying legacy is awkward, assert the new path's term count == `3 * (#active teacher-days)` and weights are exactly {PENALTY_FIVE, PENALTY_ONE, PENALTY_BUCHI}.)

- [ ] **Step 2: implement** — replace `_add_full_soft_cost_terms`'s BODY with:
```python
try:
    from . import soft_costs as _sc
except ImportError:
    import soft_costs as _sc
def vars_at(t, d, h):
    return cpsat_vars_by_t_d_h.get((t, d, h), [])
terms, _aux = _sc.buchi_daydist_terms_from_accessor(
    model, vars_at, teachers, days, hours,
    buchi_weight=_PENALTY_BUCHI, five_weight=_PENALTY_FIVE,
    one_weight=_PENALTY_ONE, include_five_one=True,
    fixed_load=fixed_load_by_t_d_h)
return terms
```
Keep the function signature + return type identical so the 9 pricers are untouched. Keep `_PENALTY_*` as the passed weights (they ARE the presets). Confirm `buchi_daydist_terms_from_accessor`'s term order matches what callers expect (order only affects var indices, not the summed objective — but match anyway).

- [ ] **Step 3: functional gate** — `pytest tests/test_bp_granularities.py -q` → all 9 granularities iterate + HARD-feasible. Also `pytest backend/tests/test_c_cg_soft_unified.py -q`. If a CG benchmark test exists and is fast, run it.

- [ ] **Step 4: commit + push** `git commit -m "refactor(engine): column-generation pricer soft via soft_costs (C)"; git push origin main`

---

## Task 3: (optional) unify CG sixth + regression
- [ ] If time permits, route the per-pricer sixth loop (`if h == _SIXTH_HOUR: obj.append(_PENALTY_SIXTH*v)`) through `soft_costs.sixth_slot_pairs` over the pricer's slot vars, deleting the local `_SIXTH_HOUR`. Functional gate unchanged. Skippable — note in log if deferred.
- [ ] Regression: `pytest tests/test_bp_granularities.py -q` + `pytest backend/tests -k "column or bp or pricer" -q`. Commit + push.

---

## Notes
- The CG buchi uses `meta.OBJECTIVE_WEIGHTS*100` == `PENALTY_*` — same presets. After C, the weights are ARGUMENTS to the shared encoder (generality invariant preserved).
- Do NOT change pricer reduced-cost logic — only the soft-term construction.
- If a granularity's pricer passes a DIFFERENT `cpsat_vars_by_t_d_h`/`fixed_load` shape than expected, the accessor lambda still works (it's just `.get`). If any pricer breaks, capture which granularity + the shape in `log.md`.
