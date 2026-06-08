# Unified SOFT constraints via the DSL — design spec

**Date:** 2026-06-08
**Status:** Draft for review
**Decision inputs:** Full single-source (DSL owns *all* soft) · Zero-drift (behavior-preserving refactor).

## 1. Problem

SOFT penalties are implemented three+ times across the codebase, with no
single source of truth. This causes:

- **Dormant soft** — table/user-driven soft (soft unavailability cells,
  free-day preferences, soft general/logical/coteach rules) only reaches
  the objective on the week-mono path (`include_soft=True`, added in
  commit `9252ee0`). The per-day, decomposition, BP/CG, and metaheuristic
  paths still ignore it.
- **Double-count hazard** — free-day soft exists in *two* sources: the
  Phase-A hardcoded `glib_pen` (via `build_phase_a_pragmas` →
  `teacher_preferred_free_day_penalty`) AND the DSL loader
  (`load_all_dsl_constraints(include_soft=True)`, section 4c). Naively
  enabling `include_soft` on the per-day path penalizes free-day twice.
- **Divergent implementations** — structural soft (sixth/buchi/five/one)
  is coded in `cp_sat_constraint_model.compute_soft_cost_expr` (two
  modes), in `cpsat_v2_timetable` (Phase-A objective), in
  `column_generation._add_full_soft_cost_terms`, and again in Python in
  `metaheuristics.compute_soft`. Each must be kept in lockstep by hand.

## 2. Goals & non-goals

**Goals**
- One source of truth for every soft penalty: a DSL **soft-pragma**
  stream. Each pipeline's soft objective = `sum(compiler.soft_cost_terms)`.
- Eliminate double-counting *by construction* (one source ⇒ can't double).
- **Zero-drift**: the unified objective must equal today's objective
  term-for-term and weight-for-weight. The ~100 pinned solver tests stay
  green; new zero-drift tests assert `new == old` per pipeline.
- Enable the currently-dormant table/user soft on *all* pipelines as a
  natural consequence (single source feeds everyone).

**Non-goals**
- No weight re-tuning. Per-phase scale differences (per-slot sixth `=50`
  vs per-class-busy `PENALTY_SIXTH_PD=5`; five/one only in phase-A) are
  preserved exactly — they are intentional, not bugs.
- No new soft penalty *types* beyond what exists today.
- No change to HARD-constraint handling (already unified via
  `dsl_translator` + `DSLConstraintCompiler`).

## 3. Current soft inventory (the zero-drift contract)

Canonical weights live in `metaheuristics.OBJECTIVE_WEIGHTS`
(`{sixth, buchi, five, one}`); CP objectives use `×SCALE (=100)`.

| Penalty | Where today | Encoding to reproduce exactly |
|---|---|---|
| Sixth (slot) | `compute_soft_cost_expr` mode=`default` (`:1004`) | per slot var at `h=SIXTH_HOUR(13)`, weight `PENALTY_SIXTH` |
| Sixth (class-busy) | mode=`phase_b_per_day` (`:1011`) | per class-busy indicator at h13, weight `PENALTY_SIXTH_PD=5` |
| Buchi | `compute_soft_cost_expr` (`:1027`) | per (teacher,day) gap count, `PENALTY_BUCHI` / `PENALTY_BUCHI_PD=10` |
| Five | mode=`default` (`:1112`) | per (teacher,day) day_count==5 indicator, `PENALTY_FIVE` (phase-A) |
| One | mode=`default` (`:1113`) | per (teacher,day) day_count==1 indicator, `PENALTY_ONE` (phase-A) |
| Uniform spread | `cpsat_v2_timetable` Phase-A obj (`:902`) | `4*uniform_class_pen + 3*uniform_prof_pen` (abs hour-deviation) |
| Free-day pref | `teacher_preferred_free_day_penalty` pragma → `glib_pen` (`:886`) | 30/20/10 per priority, busy-day indicator (phase-A) — **already a pragma** |
| Soft unavailability | `dsl_translator` §1-3 + compiler reify | `forall ... : false` is_hard=False, weight=soft_penalty — **already DSL** |
| Soft general/logical/coteach | `dsl_translator` + compiler | **already DSL** |
| CG soft | `column_generation._add_full_soft_cost_terms` | mirrors the above for master/pricers |
| Meta scorer | `metaheuristics.compute_soft` (`:113`) | Python: `sixth/buchi/five/one × OBJECTIVE_WEIGHTS` (no SCALE) |

## 4. Architecture

### 4.1 Soft-pragma vocabulary
Add **soft pragmas** to `DSLConstraintCompiler` (`PRAGMA_LEVEL` +
`_compile_call` + a `_compile_*` method each), every one reifying its
violation into a BoolVar/IntVar and appending `(weight, var)` to
`soft_cost_terms` (the existing SOFT mechanism):

| Pragma | Level | Reproduces |
|---|---|---|
| `class_sixth_penalty(weight, mode)` | phase_b | sixth (slot or class_busy by `mode`) |
| `teacher_buchi_penalty(weight)` | phase_b | per-(teacher,day) gaps |
| `teacher_five_penalty(weight)` | phase_a | day_count==5 |
| `teacher_one_penalty(weight)` | phase_a | day_count==1 |
| `teacher_uniform_spread_penalty(weight)` / `class_uniform_spread_penalty(weight)` | phase_a | abs hour-deviation |
| `teacher_preferred_free_day_penalty(...)` | both | free-day (exists) |

Soft-unavailability / general / logical / coteach already compile via the
generic `forall ... : false` + `is_hard=False` path — no new pragma.

### 4.2 Single emitter
New `build_soft_pragmas(profs, classes, *, scale_mode, level)` (in
`dsl_translator`, beside `build_phase_a_pragmas`) returns the structural
soft-pragma stream for a context. `scale_mode ∈ {default, phase_b_per_day}`
selects the sixth/buchi flavor + which of five/one/spread apply. Weights
sourced from `meta.OBJECTIVE_WEIGHTS × SCALE` (or the PD constants),
so the numbers are *read from today's constants*, not retyped.

`load_all_dsl_constraints(..., include_soft=True)` remains the single
source for *table/user* soft. **Free-day preferences move to exactly one
owner**: emitted by the loader (§4c) and REMOVED from
`build_phase_a_pragmas`, so they have a single source regardless of
pipeline (kills the double-count root cause).

### 4.3 Per-pipeline objective assembly
Every CP pipeline converges on:
```
soft_terms = compiler.soft_cost_terms          # structural + free-day + table soft
model.Minimize(sum(w * v for (w, v) in soft_terms) + <hard-derived terms if any>)
```
Hardcoded soft blocks (`compute_soft_cost_expr` bodies, the Phase-A
inline objective, `_add_full_soft_cost_terms`) are deleted once their
pipeline is migrated and its zero-drift test passes.

### 4.4 Metaheuristic scorer
`metaheuristics.compute_soft` is replaced by a Python evaluator that
walks the same soft-pragma stream, each pragma carrying a Python
cost-fn alongside its CP method (Option-2 dual backend, introduced only
in sub-project D). Zero-drift vs the current `compute_soft` scores.

## 5. Sub-project decomposition (each: own spec→plan→build→commit)

- **A — Foundation.** Soft-pragma vocabulary + compiler CP methods +
  `build_soft_pragmas` emitter. Pure addition; no pipeline rewiring.
  Zero-drift *unit* tests: each pragma's emitted CP terms == the matching
  hardcoded block on fixtures. Ship behind unused emitter.
- **B — CP pipelines.** Migrate mono-week (`MonolithicSolver`), per-day
  (`cpsat_v2_timetable.solve_phase_b_for_day`), and the decomposition
  stages to source soft from the stream; delete hardcoded CP soft; move
  free-day to the loader. Per-pipeline zero-drift (objective value equal
  on the small/medium fixtures) + enable table soft everywhere.
- **C — BP / column-generation.** Route pricers (`PricerSolver`
  subclasses) + master through the stream; delete
  `_add_full_soft_cost_terms`. Zero-drift on CG benchmark rows.
- **D — Metaheuristics.** Dual-backend pragmas (Python cost-fn); replace
  `compute_soft`; zero-drift on LNS/SA/TS/ILS/ALNS/VNS/Lagrangian scores.

Order is strict: A unblocks B; B before C (CG reuses the CP stream);
D last (hardest, separate evaluator).

## 6. Testing strategy

- **Zero-drift harness** (primary gate): for a fixture, solve the model
  the old way and the new way under a fixed seed + time-limit on the
  small + medium profiles and assert the **objective value is equal**.
  Where a cheaper symbolic check is feasible (same `(weight, var)`
  multiset before solving), add it as a fast pre-check — but the
  solved-value equality is the binding contract.
- Reuse the existing `test_dsl_seed_legacy.py` pattern (proven zero-drift
  for HARD) as the template.
- Every migrated pipeline keeps its existing pinned tests green — those
  are the real regression gate.

## 7. Risks

- **Hidden weight/shape mismatch** between a pragma and the block it
  replaces → caught by zero-drift tests before the hardcoded block is
  deleted (never delete before green).
- **Phase-var availability**: five/one/spread need `day_count` IntVars;
  the compiler already gates phase-A pragmas via `PRAGMA_LEVEL` +
  diagnostics when `day_count` is absent — reuse that.
- **Metaheuristic divergence (D)**: the Python scorer must match
  `compute_soft` exactly incl. ordering; highest-risk, isolated last.
- **Blast radius**: ~100 pinned tests. Mitigation: zero-drift + strict
  A→D ordering + migrate-one-pipeline-at-a-time, each its own commit.

## 8. Sub-project A — done (carry-forward to B)

Sub-project A shipped (commits `3b30d42`..`0700984`, base `dfee46f`):
`engine/soft_costs.py` is now the single source for sixth/buchi/five/one;
`compute_soft_cost_expr` delegates all of them (zero-drift, pinned suites
green); the four soft pragmas (`class_sixth_penalty`,
`teacher_buchi_penalty`, `teacher_five_penalty`, `teacher_one_penalty`)
and the `build_soft_pragmas` emitter exist but are **intentionally
unwired**. Final holistic review verdict: **ready-with-notes**. Three
items B must handle first (none are A-scope defects — they are the
deferred wiring decisions):

1. **`class_busy` sixth pragma is a no-op today.**
   `build_soft_pragmas(scale_mode="phase_b_per_day")` emits
   `class_sixth_penalty(PENALTY_SIXTH_PD, "class_busy")`, but
   `_compile_class_sixth_penalty` only implements `mode=="slot"` —
   `class_busy` records a diagnostic and adds **no terms**. Before B
   relies on the per-day emitter, either implement the `class_busy`
   compile branch (delegating to `soft_costs.sixth_class_busy_terms`,
   which needs the per-(class,day) busy-indicator callback the
   ConstraintModel supplies) **or** wire the per-day pipeline straight
   to `sixth_class_busy_terms`.
2. **The `default` stream spans two `PRAGMA_LEVEL`s.** sixth/buchi are
   `phase_b`; five/one are `phase_a`. The compiler's level gate skips a
   pragma whose level ≠ the compiler's `level` unless `level="both"`.
   So feed `build_soft_pragmas(scale_mode="default")` at **`level="both"`**
   (or split by level). `build_soft_pragmas`' own `level=` param is
   currently accepted-but-inert — give it meaning when wiring.
3. **`phase_a` label on slot-derived five/one is a misnomer.** Unlike
   other phase-A pragmas, five/one derive `count_d` from `self.slot`
   (byte-identity with the ConstraintModel's slot-derived count), not
   from `day_count` IntVars; their guard correctly checks `self.slot`.
   This contradicts §7's earlier assumption that five/one "need
   `day_count` IntVars" — that assumption is **superseded**. When B
   migrates pipelines, either relabel these `phase_b`/`both` or document
   why slot-derived penalties keep a `phase_a` tag.

Also still pending from §4.2: **free-day preference must move to a single
owner** (loader §4c) and be REMOVED from `build_phase_a_pragmas` — the
double-count root cause. Untouched in A; do it in B with its own
zero-drift gate.
