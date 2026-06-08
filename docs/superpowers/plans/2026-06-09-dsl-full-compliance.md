# Full DSL Compliance Across All Solvers — Plan

> **For agentic workers:** superpowers:subagent-driven-development. Implementer + reviewer. Steps `- [ ]`.

**Goal:** Make every solver accept as much DSL as intrinsically possible; make the MONOLITHIC weekly CP-SAT COMPLETELY DSL-compliant (honors any checkable hard DSL); document motivations where a method intrinsically cannot. The metaheuristic is already completely general (MetaGeneral, `7dc46de`).

**Mechanism:** A CP solver compiles every rule `DSLConstraintCompiler` can model (broad fragment — per-slot reif, nested-forall-static forbid-pairs, named pragmas, count/implies/or/not). For hard DSL it could NOT compile, a post-solve **verify + no-good-refine** loop guarantees the final solution honors it: evaluate all hard DSL on the solution via the post-hoc evaluator; if any violated, add a no-good cut (forbid that exact assignment) and re-solve, bounded by `max_iters`; if still violated at the bound, surface a structured warning (constraint can't be satisfied within budget — motivation). Natively-compiled constraints pass verification on iteration 0 (one cheap check, no extra solve).

**Test policy:** functional/contract sacred. Default path (no hard DSL) byte-identical (no refinement, no extra solve). Commit + push per task.

---

## File Structure
- **Create** `engine/dsl_cp_gate.py` — pure-ish helper: `verify_dsl_hard(sol, profs, hard_exprs) -> list[str]` (violated), `add_nogood(model, slot, sol)`, `solve_with_dsl_refinement(solver, hard_exprs, profs, *, max_iters, time_limit_s, workers) -> (sol, status, unsatisfied)`. Uses `metaheuristics._build_world_from_sol` + `general_dsl` (via metaheuristics' import — dual-module safe).
- **Modify** `engine/cp_sat_constraint_model.py` (`MonolithicSolver`) — add an opt-in refinement entry (a method `solve_dsl_compliant(hard_exprs, profs, ...)` or a flag) that runs the gate.
- **Modify** `webui/backend/optimization.py` — the week orchestration loads hard DSL + calls the compliant solve; surfaces unsatisfied warnings (via `constraint_compat`) to RunLog.
- **Create** `docs/dsl_compliance.md` — per-method compliance matrix + motivations.
- **Tests** — `webui/backend/tests/test_dsl_cp_gate.py`.

---

## Task 1: `engine/dsl_cp_gate.py` + verify/no-good/refine

**Files:** Create `engine/dsl_cp_gate.py`. Test: `webui/backend/tests/test_dsl_cp_gate.py`.

- [ ] **Step 1: failing tests**
```python
def test_verify_dsl_hard_flags_violation():
    import dsl_cp_gate as g
    profs = {"T1": {"classi": {"1A": {"Mat": {"ore": 2}}}, "max_hours": 18}}
    sol = {("T1","1A","Mat",1,8):1, ("T1","1A","Mat",1,9):1}
    expr = 'forall l in lessons where l.teacher == "T1" and l.day == 1 and l.hour == 8: false'
    assert g.verify_dsl_hard(sol, profs, [expr]) == [expr]      # violated (T1 at 1,8)
    sol2 = {("T1","1A","Mat",1,9):1, ("T1","1A","Mat",1,10):1}
    assert g.verify_dsl_hard(sol2, profs, [expr]) == []          # satisfied

def test_add_nogood_forbids_exact_assignment():
    import dsl_cp_gate as g
    from ortools.sat.python import cp_model
    m = cp_model.CpModel()
    slot = {("T1","1A","Mat",1,8): m.NewBoolVar("a"),
            ("T1","1A","Mat",1,9): m.NewBoolVar("b")}
    # force the "bad" point a=1,b=0, then no-good it -> must change
    sol = {("T1","1A","Mat",1,8):1, ("T1","1A","Mat",1,9):0}
    g.add_nogood(m, slot, sol)
    # adding a constraint that pins exactly the bad point must now be infeasible
    m.Add(slot[("T1","1A","Mat",1,8)] == 1); m.Add(slot[("T1","1A","Mat",1,9)] == 0)
    s = cp_model.CpSolver(); assert s.Solve(m) == cp_model.INFEASIBLE
```
Run → FAIL (module missing).

- [ ] **Step 2: implement `engine/dsl_cp_gate.py`**
```python
from __future__ import annotations

def _gd():
    # use metaheuristics' general_dsl resolution to avoid dual-module AST hazard
    try:
        from webui.backend.utils import general_dsl as gd  # type: ignore
    except ImportError:
        import os, sys
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _root not in sys.path:
            sys.path.insert(0, _root)
        from webui.backend.utils import general_dsl as gd  # type: ignore
    return gd

def _build_world(sol, profs):
    try:
        from . import metaheuristics as mh  # type: ignore
    except ImportError:
        import metaheuristics as mh  # type: ignore
    return mh._build_world_from_sol(sol, profs)

def verify_dsl_hard(sol, profs, hard_exprs):
    """Return the list of hard-DSL expression strings VIOLATED by sol."""
    if not hard_exprs:
        return []
    gd = _gd()
    world = _build_world(sol, profs)
    violated = []
    for e in hard_exprs:
        try:
            ok, _err = gd.evaluate_safe(gd.parse(e), world)
        except Exception:
            continue  # unparseable/unevaluable: cannot verify -> skip (warned elsewhere)
        if not ok:
            violated.append(e)
    return violated

def add_nogood(model, slot, sol):
    """Forbid the EXACT current assignment over the slot vars."""
    lits = []
    for k, v in slot.items():
        on = int(sol.get(k, 0)) == 1
        lits.append(v.Not() if on else v)
    if lits:
        model.AddBoolOr(lits)

def solve_with_dsl_refinement(solver, hard_exprs, profs, *,
                              max_iters=8, time_limit_s=10.0, workers=8):
    """Solve `solver` (a MonolithicSolver-like with .model/.slot/.solve);
    iteratively forbid solutions that violate an un-compiled hard-DSL rule
    until all hold or `max_iters` exhausted. Returns (sol, status, unsatisfied)
    where `unsatisfied` is the list of still-violated expr strings (empty =
    fully compliant)."""
    last_sol, last_status = None, None
    for _ in range(max(1, int(max_iters))):
        sol, status = solver.solve(time_limit_s=time_limit_s, workers=workers)
        last_sol, last_status = sol, status
        if sol is None:
            return None, status, []          # infeasible/no solution
        violated = verify_dsl_hard(sol, profs, hard_exprs)
        if not violated:
            return sol, status, []           # fully compliant
        add_nogood(solver.model, solver.slot, sol)
    return last_sol, last_status, verify_dsl_hard(last_sol, profs, hard_exprs)
```
(Confirm `MonolithicSolver.solve` signature is `solve(self, *, time_limit_s, workers)` or `solve(self, time_limit_s=..., workers=...)` — adapt the call. Confirm `.model` and `.slot` exist.)

- [ ] **Step 3: verify** `pytest backend/tests/test_dsl_cp_gate.py -q` → pass.
- [ ] **Step 4: commit + push** `git commit -m "feat(engine): dsl_cp_gate verify + no-good refinement helper"; git push origin main`

---

## Task 2: make MonolithicSolver completely DSL-compliant

**Files:** Modify `engine/cp_sat_constraint_model.py` (`MonolithicSolver`), `webui/backend/optimization.py` (week orchestration). Test: `webui/backend/tests/test_dsl_cp_gate.py`.

- [ ] **Step 1: failing functional test**
Build a MonolithicSolver on a tiny instance (mirror `test_week_soft_enablement.py`), give it a HARD DSL expr that the COMPILER cannot model natively but the post-hoc evaluator can (find one that compiles to a diagnostic — e.g. a `forall over a non-lessons source`, or a dynamic nested body). Call `dsl_cp_gate.solve_with_dsl_refinement(ms, [expr], profs, ...)`. Assert: returns a HARD-feasible solution that SATISFIES the expr (verify_dsl_hard returns []), OR (if genuinely unsatisfiable with the rest) returns the expr in `unsatisfied` — and in NEITHER case crashes. Prefer a SATISFIABLE expr (e.g. `'forall l in lessons where l.teacher == "T1" and l.day == 1 and l.hour == 13: false'` — forbid T1 at the 6th hour; satisfiable by placing elsewhere) so the refinement DEMONSTRABLY enforces it: assert the result places no T1 lesson at (1,13). Construct so the un-refined solver WOULD sometimes use (1,13) — i.e. without the gate the constraint is not guaranteed.
Run → confirm the refinement enforces it.

- [ ] **Step 2: wire MonolithicSolver**
Add a method `solve_dsl_compliant(self, hard_exprs, profs, *, max_iters=8, time_limit_s=10.0, workers=8)` that delegates to `dsl_cp_gate.solve_with_dsl_refinement(self, hard_exprs, profs, ...)`. In `optimization.py`'s week path (`_solve_phase_b_week` / `_apply_dsl_rules_to_week_solver` region), after building the solver + loading DSL: collect the HARD expression strings (`[r["expression"] for r in load_all_dsl_constraints(db, include_soft=True) if r.get("is_hard")]`), and if non-empty, solve via `solve_dsl_compliant(hard_exprs, profs, ...)` instead of plain `solve()`; surface the returned `unsatisfied` via `constraint_compat.summarize(["compile_failed:"+e ... ], pipeline="week_cpsat")` to RunLog/result. Default (no hard DSL) → plain solve, byte-identical.

- [ ] **Step 3: functional gate** `pytest backend/tests/test_dsl_cp_gate.py backend/tests/test_week_soft_enablement.py -q` → pass. `pytest backend/tests -k "week or monolith or scope_week" -q -m "not slow"` → pass. Slow week test if present.
- [ ] **Step 4: commit + push** `git commit -m "feat(engine): MonolithicSolver completely DSL-compliant via refinement"; git push origin main`

---

## Task 3: per-day / decomposition + CG/BP compliance + motivations

**Files:** Modify (as tractable) `engine/cpsat_v2_timetable.py`, `engine/column_generation.py`. Create `docs/dsl_compliance.md`.

- [ ] **Step 1: per-day** — `solve_phase_b_for_day` already compiles DSL + collects diagnostics (Task-1 sink). Per-day solves ONE day, so cross-day hard DSL cannot be verified within a single day. MOTIVATION: per-day decomposition is day-scoped; cross-day/global hard DSL is enforced at the assembled-week level by the week refinement (Task 2) or the metaheuristic pass. Document. (Optionally: after the full week is assembled from per-day solves, run `verify_dsl_hard` on the assembled week and warn.)

- [ ] **Step 2: CG/BP** — pricers are per-column; a global/cross-column hard DSL cannot be modeled inside a single pricer. MOTIVATION: branch-and-price decomposes by column; constraints spanning multiple columns/the whole timetable are not visible to a pricer's subproblem. Mitigation: after the master assembles a full integer solution, run `verify_dsl_hard` on it and surface warnings (and/or hand off to the metaheuristic universal solver for enforcement). Implement the post-assembly verification + warning IF the assembly seam is clear; otherwise document the motivation + the meta-handoff path.

- [ ] **Step 3: `docs/dsl_compliance.md`** — a table: each method (mono-week, per-day, decomp spectral/temporal/curriculum/metis, column-generation, branch-and-price, metaheuristics) × {compiles natively | refined post-solve | post-hoc verified+warned | fully general}. For each gap, a 1-2 sentence MOTIVATION (intrinsic reason). State plainly: the metaheuristic is the completely-general solver; the monolithic week is completely-compliant via refinement; per-day/decomp/CG/BP are maximally-compliant within their decomposition limits, with cross-cutting DSL enforced at assembly or via the meta pass.

- [ ] **Step 4: commit + push** `git commit -m "docs+feat: DSL compliance matrix + per-method motivations + CG/BP post-assembly verify"; git push origin main`

---

## Task 4: `no_same_class_consecutive_days(cl)` shorthand pragma

**Files:** `webui/backend/utils/general_dsl.py` (builtin/pragma expansion) + `engine/dsl_to_cpsat.py` (compile) + a test.
- [ ] Add the pragma so `no_same_class_consecutive_days("1A")` expands to / compiles as the nested-forall forbid-pair (the capability already exists; this is the convenience form). Evaluator: register it as a canonical pattern (like the other pragmas at general_dsl.py:1142-1221). Compiler: emit forbid-pair constraints for lessons of that class on consecutive days (mirror the existing nested-forall-static path / `test_dsl_to_cpsat.py:333-369`). Test both the post-hoc eval and the CP compile. Commit + push.

---

## Notes
- `verify_dsl_hard` uses the post-hoc evaluator — it can check ANY grammar expression, so the refinement gate is general (not limited to the compilable fragment).
- No-good = forbid the exact full assignment: correct + bounded by `max_iters`. For pathological constraints it may exhaust the budget → reported in `unsatisfied` with a motivation (the honest "couldn't fully comply" signal). Document the perf tradeoff: refinement only triggers when an UN-compiled hard rule is violated; natively-compiled rules pass at iteration 0.
- Keep everything frontend-agnostic in `engine/`; surfacing to RunLog is the webui orchestration's job.
