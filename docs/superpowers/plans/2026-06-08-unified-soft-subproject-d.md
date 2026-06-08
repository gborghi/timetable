# Unified SOFT — Sub-project D (metaheuristics honor DSL soft) Plan

> **For agentic workers:** superpowers:subagent-driven-development. Implementer + reviewer. Steps `- [ ]`.

**Goal:** Make the metaheuristic post-processors honor arbitrary user/DSL SOFT constraints, not just the hardcoded structural sixth/buchi/five/one. Today a meta runner can "improve" structural metrics while trampling a user's custom soft (e.g. soft unavailability, "avoid afternoons"). D closes that by having `compute_soft` add weighted penalties for violated DSL soft rules, evaluated through the EXISTING post-hoc DSL evaluator (`_build_world_from_sol` + `general_dsl.parse`/`evaluate_safe`) already used by `is_hard_feasible`.

**Why not a full dual-backend pragma system:** YAGNI. The post-hoc DSL evaluator IS the Python backend. Structural weights already come from the shared `OBJECTIVE_WEIGHTS` (no weight drift). So D = wire DSL soft into the Python scorer, reusing existing parts.

**Perf guard (critical):** `compute_soft` is called in every accept/reject loop. DSL rules MUST be PRE-PARSED once (cache `(tree, weight)` pairs) — never `parse()` per call. `compute_soft` builds the world + evaluates cached trees per call (comparable to `is_hard_feasible`'s cost), only when soft rules are present.

**Test policy:** functional/contract sacred (meta runners still return HARD-feasible; now also prefer DSL-soft-honoring solutions). Default path (no soft rules) is byte-identical (zero-drift). Weights flow from the rule dicts (general). Commit + push per task.

---

## File Structure
- **Modify** `engine/metaheuristics.py` — extend `compute_soft(sol, profs, soft_rules=None)`; thread `soft_rules` through the runner signatures (`run_lns/run_sa/run_tabu/run_ils/run_alns/run_vns/run_lagrangian`) to their inner-loop `compute_soft` calls.
- **Modify** `webui/backend/optimization.py::run_meta` — load DSL soft rules once (`load_all_dsl_constraints(db, include_soft=True)`, filter `not is_hard`), pre-parse, pass `soft_rules=` to the runners.
- **Create** `webui/backend/tests/test_d_meta_dsl_soft.py` — unit (compute_soft penalizes a violated soft rule) + functional (a meta run with a soft rule prefers honoring it; still HARD-feasible).

---

## Task 1: extend `compute_soft` with DSL soft scoring

**Files:** Modify `engine/metaheuristics.py`. Test: `webui/backend/tests/test_d_meta_dsl_soft.py`.

- [ ] **Step 1: failing unit test**
Pre-parse a soft rule (a `forall l in lessons where ...: false` soft-unavailability expr) into `(tree, weight)`; build two solutions, one that PLACES a lesson on the penalized slot and one that does not. Assert `compute_soft(sol_violating, profs, soft_rules=[(tree, W)])[0]` > `compute_soft(sol_ok, profs, soft_rules=[(tree, W)])[0]` by exactly `W` (the structural part is equal). Also assert `compute_soft(sol, profs)` (no soft_rules) is UNCHANGED vs today (zero-drift). Run → FAIL (signature has no `soft_rules`).

- [ ] **Step 2: implement**
Extend the signature to `compute_soft(sol, profs, soft_rules=None)`. Keep the existing structural block EXACTLY (sixth/buchi/five/one, `val`, `metrics`). Then, ONLY if `soft_rules`:
```python
if soft_rules:
    world = _build_world_from_sol(sol, profs)  # reuse existing builder
    try:
        from webui.backend.utils import general_dsl as _gd
    except ImportError:
        import sys as _sys, os as _os
        _root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from webui.backend.utils import general_dsl as _gd
    soft_pen = 0
    for tree, weight in soft_rules:
        try:
            ok, _err = _gd.evaluate_safe(tree, world)
        except Exception:
            continue  # unevaluable rule: skip (graceful)
        if not ok:                  # constraint violated
            soft_pen += int(weight)
    val += soft_pen
    metrics = dict(metrics, dsl_soft=soft_pen)
```
`soft_rules` is a list of `(parse_tree, weight)` — PRE-PARSED by the caller (never parse here). Default `None` → structural-only, identical to today.

Add a small public helper `parse_soft_rules(rules)` that turns `load_all_dsl_constraints` soft dicts into `[(parse_tree, weight), ...]` (parse each `r["expression"]`, skip `is_hard` / weight<=0 / parse failures), so callers pre-parse once. Use the same `general_dsl` import idiom.

- [ ] **Step 3: verify** `pytest backend/tests/test_d_meta_dsl_soft.py -q` (unit) + `pytest backend/tests/test_native_locks_meta.py -q` (existing meta tests unchanged — `compute_soft` default path zero-drift). → pass.

- [ ] **Step 4: commit + push** `git commit -m "feat(engine): compute_soft scores DSL soft rules (D core)"; git push origin main`

---

## Task 2: thread `soft_rules` through runners + `run_meta`

**Files:** Modify `engine/metaheuristics.py` (runner signatures + inner compute_soft calls), `webui/backend/optimization.py` (run_meta). Test: `webui/backend/tests/test_d_meta_dsl_soft.py`.

- [ ] **Step 1: failing functional test**
A meta run (use the fastest runner, e.g. `run_sa` with a tiny budget) over a small solution, with a soft rule passed via the new `soft_rules=` param, must (a) return a HARD-feasible solution [SACRED] and (b) end with the penalized slot avoided OR a lower DSL-soft penalty than the start (prefers honoring it). READ `run_sa`'s real signature + how the test should construct `sol/profs/dc_value` (mirror `test_native_locks_meta.py` setup). Run → FAIL (`run_sa` has no `soft_rules=`).

- [ ] **Step 2: implement**
Add `soft_rules=None` (keyword-only, after the existing `*,` block) to each runner: `run_lns, run_sa, run_tabu, run_ils, run_alns, run_vns, run_lagrangian`. In each runner, forward `soft_rules=soft_rules` to EVERY `compute_soft(...)` call inside it (initial best + inner accept/reject). For runners that delegate to others (e.g. `run_lagrangian` → `run_sa`, `run_ils` → tabu), forward the param down. Default `None` keeps every existing caller byte-identical.

In `optimization.py::run_meta` (inside the `with SessionLocal() as db:` block, where `profs` is built): load + pre-parse soft rules ONCE:
```python
soft_rules = None
try:
    try:
        from engine import dsl_translator as _dt
    except ImportError:
        import dsl_translator as _dt
    _all = _dt.load_all_dsl_constraints(db, include_soft=True)
    soft_rules = meta.parse_soft_rules(_all) or None
except Exception:
    soft_rules = None
```
Add `soft_rules=soft_rules` to the kwargs passed to each `meta.run_*` call (alongside `c3_kwargs`). Confirm `is_hard_feasible` HARD checks are unaffected (D only touches soft scoring).

- [ ] **Step 3: functional gate**
- `pytest backend/tests/test_d_meta_dsl_soft.py -q` → pass (functional + HARD-feasible).
- `pytest backend/tests/test_native_locks_meta.py backend/tests/test_groups_cg_meta.py -q` → pass (existing meta behavior unchanged on the default path).
- `pytest backend/tests -k "meta or lns or sa or tabu or ils or alns or vns or lagrangian" -q -m "not slow"` → pass; rewrite any OUTCOME test that shifts because soft is now scored (note each).
- A slow meta sanity if one exists; time-budget flakes re-run isolated.

- [ ] **Step 4: commit + push** `git commit -m "feat: meta runners honor DSL soft via run_meta (D)"; git push origin main`

---

## Task 3: cross-check + regression
- [ ] (optional) Cross-check test: build a solution, lock it into a per-day CP solve, and assert `compute_soft`'s structural `val` (sixth*W + buchi*W + ...) equals the CP objective's structural contribution for that solution — pinning that the Python and CP backends agree on the structural definitions. If too heavy, skip + note.
- [ ] Regression: `pytest backend/tests -k "meta" -q -m "not slow"` green. Commit + push.

---

## Notes
- PERF: world is rebuilt per `compute_soft` call when `soft_rules` present — acceptable for correctness (meta runs are time-budgeted; honoring user soft beats extra iterations). Incremental world updates are a future optimization — note in `log.md` if it materially slows runs.
- The structural scorer uses raw `OBJECTIVE_WEIGHTS` (no ×SCALE); DSL soft weights are the user's `soft_penalty`/free-day 30/20/10 — summed in the same integer space. Relative calibration is the user's choice (weights are general), not D's concern.
- Cross-day DSL soft (free-day) evaluated post-hoc over a COMPLETE week solution works correctly here (unlike per-day CP decomposition) — the meta scorer sees the whole week.
