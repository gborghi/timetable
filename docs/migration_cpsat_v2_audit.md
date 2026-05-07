# `cpsat_v2_timetable.py` migration audit (Family-by-family)

Snapshot of the current state at HEAD `b267e5b` of every constraint family
in `engine/cpsat_v2_timetable.py`, vs the available infrastructure on
`engine/cp_sat_constraint_model.py` (`ConstraintModel` /
`MonolithicSolver`) + `engine/dsl_translator.py` +
`engine/dsl_to_cpsat.py` (DSL pragmas).

## Architectural note (read first)

`cpsat_v2_timetable.py` carries TWO solvers with **different variable
shapes**:

| Solver | Variables | Used by |
|---|---|---|
| `solve_phase_a` | `day_count[(p,cl,subj,d)]` IntVar in `[0..2]` | weekly day-distribution |
| `solve_phase_b_for_day` | `slot[(p,cl,subj,h)]` BoolVar (one day at a time) | per-day hour placement |

`ConstraintModel` / `MonolithicSolver` / DSL pragmas are built around
**slot Bool** variables (5-tuple `(t,cl,s,d,h)`). They are a natural fit
for Phase B; Phase A's IntVar-based formulation has **no equivalent
DSL pragma family today**.

This means the families flagged below as "Phase A only" cannot be
replaced 1-for-1 by the existing DSL pragmas: doing so would require
either (a) building IntVar-based DSL pragmas (new infrastructure), or
(b) replacing Phase A entirely with a slot-Bool monolithic solver
(architectural change with significant performance impact, since Phase A
exists FOR scaling).

## Audit table

| # | Family | Where (today) | Variable shape | DSL pragma exists? | ConstraintModel method exists? | Migration complexity |
|---|---|---|---|---|---|---|
| 1 | `cl_day_load ∈ {0,4,5,6}` | `solve_phase_a` lines 392-401 | IntVar `cl_day_load[(cl,d)]` | YES `class_day_load_in` (slot-based) | partial | **Phase A blocker** -- DSL pragma operates on slot Bools, not day_count IntVars |
| 2 | Mat/Ita pair "≥1 day with ≥2 hours" | `solve_phase_a` lines 613-644 | IntVar `day_count` aggregation | YES `subject_pair_exists` (slot-based, per-day) | `add_math_italian_pair` (slot-based, per-day) | **Phase A semantics differ** -- Phase A enforces "at least one day across the week"; DSL pragma is per-day "if ≥2 hours that day, then consecutive pair" |
| 3 | Motorie pair `{0, 2}` | `solve_phase_a` lines 646-657 | IntVar `day_count` | YES `subject_pair_must` (slot-based, per-day) | `add_motorie_pair` (slot-based, per-day) | **Phase A side**: just a day-count constraint, not a pair constraint. Phase B side covered by `add_motorie_pair`. |
| 4 | Hall bound `prof_day_load ≤ max_c cl_day_load` | `solve_phase_a` lines 685-732 | IntVar `prof_day_load` + `cl_day_load` | NO | NO | **Phase A only** -- requires day-count semantics (no slot-Bool equivalent) |
| 5 | Free_day choice (3-way) | `solve_phase_a` lines 510-529 | reified BoolVar over `day_count == 0` | NO | NO | **Phase A only** -- Phase B doesn't see "day-off"; Phase A's free_day_choice is intrinsic to the day-distribution |
| 6 | No_holes intra-day | `solve_phase_b_for_day` lines 1090-1097 | slot Bool, per-day | YES `no_holes_class` | YES `add_class_no_holes` | **Achievable** -- proven zero-drift via `test_dsl_seed_legacy.py::test_seed_no_holes_zero_drift` |
| 7 | H11 presence | `solve_phase_b_for_day` lines 1105-1107 | slot Bool, per-day | YES `class_present_at_hour` | YES `add_h3_presence_at_11` | **Achievable** -- proven zero-drift via `test_dsl_seed_legacy.py::test_seed_h11_zero_drift` |
| 8 | Sixth-hour soft + 5/1 penalties | Phase A (`n_sixth_hour`/`n_five`/`n_one`) + Phase B (`W_SIXTH_B`/`W_GAP`) | IntVar reified | partial -- via `compute_soft_cost_expr` on MonolithicSolver | YES `compute_soft_cost_expr` (full per-week canonical formulas with weights `*100`) | **Objective drift** -- MonolithicSolver uses per-week scaled weights `(50,10,30,80) × 100`; Phase B per-day uses `(W_SIXTH_B=5, W_GAP=10)` and skips `five`/`one`. Cannot drop-in. |
| 9 | Mat/Ita first hours preference | NOT IMPLEMENTED in Phase B today | n/a | n/a | n/a | This family is mentioned in the migration brief but the legacy code does not enforce it. Out of scope. |

### Already migrated (ConstraintModel native methods, NOT DSL pragmas):
| Family | Phase B status | OO method | Migration |
|---|---|---|---|
| Coteaching groups (HARD) | hardcoded lines 951-978 | `add_coteach_groups` | available |
| Sostegno (DVA) shadow | hardcoded lines 1117-1148 | `add_support_assignments` | available |
| Potenziamento (cattedra senza classe) | not in Phase B (in Phase A) | `add_potenziamento_assignments` | Phase A-side |
| Parallel groups intra-class | hardcoded lines 980-996 | `add_parallel_groups_intra_class` | available |
| Parallel groups inter-class (StudyGroup) | hardcoded lines 899-916 + 1054-1063 | `add_parallel_groups_inter_class` | available |
| Locks | hardcoded lines 935-946 | `add_locks` | available |

## Test landscape (zero-drift oracle)

- Files referencing `solve_phase_b_for_day` / `PhaseBDaySolver`: 11
- Sampled-suite baseline (HARD-constraint behavior tests):
  `test_phase_b_oo_wrapper`, `test_dsl_seed_legacy`,
  `test_dsl_canonical_pragmas`, `test_cp_sat_constraint_model`,
  `test_native_locks`, `test_coteach_*`, `test_parallel_groups_intra`,
  `test_groups_inter_class`, `test_groups_coteach_sostegno` =
  **111 tests, all passing at HEAD**.

## Structural verdict

The migration plan as stated cannot be completed in a single session
without architectural work that exceeds the family-by-family
incremental scope:

1. **Families 1, 4, 5 (Phase A IntVar-based)**: blocked by lack of
   IntVar-based DSL pragma infrastructure. Replacing Phase A's
   `cl_day_load`/`prof_day_load`/`day_count` IntVars with slot-Bool
   formulations would require either rebuilding Phase A as a slot-Bool
   monolithic solver (kills the Phase A scaling story) or adding a new
   IntVar-pragma family to the DSL compiler (significant new
   infrastructure: parser support, compiler emit paths, zero-drift
   tests).

2. **Family 2 (Mat/Ita "≥1 day with ≥2 hours")**: this is a
   *cross-day* constraint that does not factorize per-day. The Phase B
   per-day DSL pragma `subject_pair_exists` enforces a *different*
   constraint (per-day "if ≥2 hours, then consecutive pair"). Both are
   valuable but not interchangeable.

3. **Family 8 (objective drift)**: MonolithicSolver's
   `compute_soft_cost_expr` uses canonical per-week weights
   `OBJECTIVE_WEIGHTS × SCALE` and includes `five`/`one` penalties.
   Phase B's per-day objective uses `W_SIXTH_B=5 + W_GAP=10` only.
   Replacing Phase B's objective with MonolithicSolver's would change
   optimal solutions and break tests that pin specific schedules.

4. **Families 6, 7 (slot-Bool families on Phase B)**: **achievable**.
   The DSL pragmas `no_holes_class` and `class_present_at_hour` are
   proven byte-equivalent to the legacy `add_*` methods via
   `test_dsl_seed_legacy.py`. Migrating Phase B to invoke them via
   the compiler preserves the HARD feasible set; the per-day
   objective is left intact, so soft cost is unchanged.

## Path forward

Realistic single-session scope:

- **Phase B HARD constraints via DSL seed (Families 6 + 7)**: factor
  out the hardcoded `present[h+1] <= present[h]` chain and the
  `present[h11] == 1` enforcement into a DSL-seed compilation step
  inside `solve_phase_b_for_day`. Default unchanged; opt-in via a
  new flag (`hard_via_dsl=True`). This isolates the migration from
  the objective-drift risk.

- **Phase A migration (Families 1-5)**: out of scope for this
  session. Requires a separate workstream to either (a) build
  IntVar DSL pragmas or (b) replace Phase A with a slot-Bool
  monolithic solver.

- **Family 8 (objective)**: out of scope until MonolithicSolver
  grows a "per-day Phase B" soft-cost mode that mirrors
  Phase B's `W_SIXTH_B + W_GAP` formula; alternative is a new
  `PhaseBSolver` subclass with overridden `compute_soft_cost_expr`.
