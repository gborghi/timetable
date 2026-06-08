# Unified SOFT — Sub-project B2 (per-day table-soft enablement + free-day single owner) Plan

> **For agentic workers:** superpowers:subagent-driven-development. Implementer + reviewer. Steps `- [ ]`.

**Goal:** Light up the currently-dormant user/table soft (free-day preferences, soft unavailability, soft general/logical/coteach) on the per-day pipeline by flipping its DSL loader to `include_soft=True`, with the loader as the single free-day owner. Clean the dead `glib_pen` scaffolding.

**Background (investigated):** `build_phase_a_pragmas` emits only HARD pragmas → `glib_pen` is ALWAYS 0 in `solve_phase_a`. Per-day Phase-B loads the DSL with `include_soft=False`, so free-day + all table soft are dormant on per-day. Mono-week already applies them via the loader (`include_soft=True`, `optimization.py:893`). There is **no live double-count** — flipping per-day Phase-B to `include_soft=True` is safe and is exactly what enables the dormant soft. The `teacher_preferred_free_day_penalty` pragma is `level="both"` and reads `self.slot` in a slot context, so it compiles in the per-day Phase-B compiler.

**Test policy:** functional/contract tests sacred (solver runs, HARD-feasible, soft now applied + steers); outcome tests may be rewritten. Commit + push after each task.

**Risk / known limitation:** per-day decomposition solves each day independently, so cross-day preferences (free-day = "be free on ONE chosen day") can't be globally traded off — each day's solve only sees its own local penalty. This is a solver/constraint compatibility limitation, to be surfaced by the later solver-compat warning system, NOT a B2 bug. Soft *unavailability* (per-cell) is fully meaningful per-day.

---

## File Structure
- **Modify** `engine/cpsat_v2_timetable.py` — `solve_phase_b_for_day`: change the loader call `include_soft=False` → `include_soft=True`. Clean the dead `glib_pen` term in `solve_phase_a` (always 0).
- **Create** `webui/backend/tests/test_b2_per_day_table_soft.py` — functional tests that a soft rule reaches + steers a per-day solve.

---

## Task 1: enable table soft on per-day Phase-B + functional gate

**Files:**
- Modify: `engine/cpsat_v2_timetable.py`
- Test: `webui/backend/tests/test_b2_per_day_table_soft.py`

- [ ] **Step 1: Write the failing functional test**

A soft `TeacherUnavailability` (state="soft", high penalty) on an avoidable per-day slot must make `solve_phase_b_for_day(..., via_dsl=True, db=...)` place the teacher's hour elsewhere. Build an in-memory SQLite DB (mirror `test_week_soft_enablement.py`'s `_mem_db()` pattern: `from backend.db import Base; Base.metadata.create_all(engine)`), insert a Teacher + a soft `TeacherUnavailability` cell, then call `solve_phase_b_for_day` with `via_dsl=True, db=session` and a tiny `profs`/`dc_value` where the penalized slot is avoidable. Assert: (a) feasible placement (FUNCTIONAL, sacred), (b) the soft-penalized (day,hour) is avoided (steering). READ `solve_phase_b_for_day`'s real signature for the `via_dsl`/`db` params and the slot/hour mapping first.

Run → if free-day/table soft is dormant (include_soft=False), the soft rule is absent → the penalized slot may be used → steering assertion FAILS. Confirm that's the failure (not a crash).

- [ ] **Step 2: Implement — flip the loader**

In `solve_phase_b_for_day`, change the loader call from `include_soft=False` to `include_soft=True` (the line inside the `via_dsl` block: `rules = _dt.load_all_dsl_constraints(db, include_soft=True)`). Soft rules compile onto the same `_soft_compiler`; their `(weight,var)` pairs land in `compiler.soft_cost_terms`, which the objective already sums (from B1). So no objective rewiring is needed — the soft terms flow in automatically. Verify the compile loop still catches per-rule exceptions into `dsl_diagnostics` (rules incompatible with the per-day slot context degrade gracefully, do NOT crash).

- [ ] **Step 3: Clean dead `glib_pen`**

In `solve_phase_a` (`cpsat_v2_timetable.py:~886-905`): `glib_pen` is always 0 (`build_phase_a_pragmas` emits no soft). Either (a) drop the `+ 1 * glib_pen` term and the `glib_pen`/`glib_pen_terms` construction, updating the comment to note free-day is owned by the loader (consumed at Phase-B), OR (b) if `_compiler.soft_cost_terms` might carry future soft, keep the fold but fix the misleading comment. Prefer (a) for cleanliness UNLESS a test depends on the `glibpen` var name. Run `solve_phase_a` tests after.

- [ ] **Step 4: Verify**
- `pytest backend/tests/test_b2_per_day_table_soft.py -q` → pass (functional + steering).
- `pytest backend/tests/test_b1_per_day_soft_migration.py backend/tests/test_phase_b_per_day_soft_cost.py -q` → pass.
- `pytest backend/tests -k "scope_week or decomp or phase_b or dsl" -q -m "not slow"` → pass; rewrite any OUTCOME test that breaks because soft is now applied (note which + why).
- `pytest backend/tests/test_scope_week_integration.py -q -m slow` → pass (TS/LNS time-budget flakes re-run isolated).

- [ ] **Step 5: Commit + push**
```
git add -A
git commit -m "feat(engine): enable table soft on per-day pipeline (B2, loader single owner)"
git push origin main
```

---

## Task 2: regression sweep
- [ ] Full fast suite `pytest backend/tests -m "not slow" -q` green (perf flake isolated). Commit any fixups; push.

---

## Notes
- Do NOT touch the free-day weights (30/20/10) — they live in the loader (`dsl_translator.py:688-714`), the single owner.
- If flipping `include_soft=True` surfaces a soft rule that the per-day slot compiler genuinely cannot model (cross-day), it should already be caught into `dsl_diagnostics`. Capture an example in `log.md` Q4 — it's input for the solver-compat warning system.
