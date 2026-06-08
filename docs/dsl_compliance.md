# DSL Compliance Across Solvers

The engine accepts user constraints — both **hard** (must hold) and **soft**
(penalized) — through a single grammar, `general_dsl` (the "general DSL").
A rule is just an expression string such as:

```text
forall l in lessons where l.teacher == "Rossi" and l.day == 1: false
count(l in lessons where l.class == "1A" and l.subject == "Mat") <= 2
```

stored in the DB with a `kind` (hard / soft / preferred / enforced). This
document states, for **each solving method**, how completely it honors DSL
constraints, and gives the **motivation** for every intrinsic limit.

The single most important fact up front:

> **The metaheuristic post-pass (`run_meta`) is the universal DSL enforcer.**
> It evaluates *any* grammar expression on the finished timetable: hard rules
> reject any move that would violate them, soft rules add a penalty. Whatever
> a faster method cannot natively model, the metaheuristic guarantees. See
> ["How to guarantee any constraint"](#how-to-guarantee-any-constraint-is-enforced).

---

## Two mechanisms the engine uses for DSL

1. **Native compilation** (`dsl_to_cpsat.DSLConstraintCompiler`). The CP-SAT
   solvers compile every rule in a broad fragment directly into the model:
   per-slot `forall … : false` reification, nested-`forall`-over-static
   forbid-pairs (e.g. *no same class on consecutive days*), named pragmas, and
   `count` / `implies` / `or` / `not`. Rules outside that fragment (dynamic
   3rd-variable bodies, non-`lessons` sources, dynamic `count` right-hand
   sides) are **diagnosed and skipped**, not silently dropped — the diagnostic
   is collected on `MonolithicSolver.dsl_diagnostics`.

2. **Post-hoc verification** (`dsl_cp_gate.verify_dsl_hard`). The general DSL
   evaluator can check **any** grammar expression against a finished solution.
   This drives (a) the monolithic week's no-good refinement loop, (b) the
   column-generation post-assembly gate, and (c) the metaheuristic's
   move-rejection. Diagnostics that survive are turned into structured warnings
   by `constraint_compat.summarize` and surfaced to the run log.

---

## Compliance matrix

| Method | Soft DSL | Hard DSL — natively compiled | Hard DSL — full-enforcement mechanism | Completeness |
|---|---|---|---|---|
| **Monolithic weekly CP-SAT** | ✅ compiled + scored | ✅ broad fragment | ✅ **complete** — compile + post-solve verify + no-good refine (bounded) | **Complete** (any checkable hard rule honored, or reported if unsatisfiable within budget) |
| **Per-day CP-SAT** | ✅ within a day | ✅ broad fragment, **day-scoped** | ⚠️ per-day rules enforced natively; cross-day/global rules delegated to assembled-week refinement or `run_meta` | **Complete within one day** |
| **Decomposition — spectral** | ✅ within a day | ✅ day-scoped (delegates to per-day) | ⚠️ same as per-day (cross-cluster/cross-day → assembly / `run_meta`) | **Complete within one day** |
| **Decomposition — temporal** | ✅ within a day | ✅ day-scoped | ⚠️ each day solved independently → cross-day → assembly / `run_meta` | **Complete within one day** |
| **Decomposition — curriculum** | ✅ within a day | ✅ day-scoped | ⚠️ cross-curriculum/cross-day → assembly / `run_meta` | **Complete within one day** |
| **Decomposition — metis** | ✅ within a day | ✅ day-scoped | ⚠️ cross-partition/cross-day → assembly / `run_meta` | **Complete within a partition/day** |
| **Column generation / branch-and-price** | ✅ scored on assembled sol | ✅ within a single column's scope | ⚠️ **detect + report + delegate** — assembled solution verified post-hoc; un-modeled cross-column hard DSL reported; enforced by `run_meta` | **Complete within a column** |
| **Metaheuristics** (LNS / SA / TS / ILS / ALNS / VNS / Lagrangian) | ✅ **any** rule, via penalty | n/a (not a CP model) | ✅ **completely general** — post-hoc eval rejects any move violating any hard rule | **Complete (universal)** |

Legend: ✅ honored · ⚠️ partial / delegated · "complete within X" = honors
every DSL rule whose scope fits inside X; rules spanning a wider scope are
enforced by the assembled-week refinement or the metaheuristic pass.

---

## Per-method detail and motivations

### Monolithic weekly CP-SAT — *completely compliant*

The single-model week solve (`cp_sat_constraint_model.MonolithicSolver`)
compiles the broad fragment natively. For every hard rule the compiler could
**not** model, `solve_dsl_compliant(hard_exprs, profs, …)` runs the
`dsl_cp_gate` refinement: solve → verify all hard DSL on the result → if any is
violated, add a **no-good cut** forbidding that exact assignment and re-solve,
bounded by `max_iters`.

- Natively-compiled rules pass verification on iteration 0 (one cheap check, no
  extra solve), so the default path stays byte-identical when there is no
  un-compiled hard DSL.
- **Motivation for the bound:** a pathological hard rule could force the loop to
  walk many distinct assignments and exhaust `max_iters`. When that happens the
  still-violated rules are returned as `unsatisfied` and surfaced as a structured
  warning (`constraint_compat`, pipeline `week_cpsat`) — the honest "couldn't
  fully comply within budget" signal — instead of silently shipping a violating
  timetable. In practice this is rare: any rule the compiler handles is already
  satisfied at iteration 0.

### Metaheuristics — *completely general (the universal enforcer)*

`metaheuristics.run_*` (LNS, SA, TS, ILS, ALNS, VNS, Lagrangian) are local
search over an already-feasible solution, not CP models. They enforce DSL
**post-hoc**:

- **Hard DSL** — `is_hard_feasible(sol, profs, dsl_hard_expressions=…)`
  evaluates every hard expression on the candidate world; any move that would
  produce a violating solution is **rejected**. Combined with the
  no-double-booking feasibility invariant this is equivalent to a hard
  constraint.
- **Soft DSL** — `compute_soft(sol, profs, soft_rules=…)` adds the weight of
  every violated soft rule to the objective.

Because the evaluator accepts **any** grammar expression — including the
dynamic / non-`lessons` / dynamic-`count` forms no CP compiler can model — the
metaheuristic is the **fallback that can enforce anything**. This is why every
other method's "completeness gap" is closed by handing off to `run_meta`.

### Per-day CP-SAT and decomposition — *maximally compliant within one day*

`solve_phase_b_for_day` compiles DSL and collects diagnostics exactly like the
monolithic solver, but it solves **one day in isolation**. The decomposition
strategies (spectral / temporal / curriculum / metis) all delegate their
per-day subproblem to `solve_phase_b_for_day`.

- **What is honored natively:** any DSL rule whose scope fits inside a single
  day — per-slot unavailability, within-day forbid-pairs, per-day counts, etc.
- **Motivation for the limit:** a per-day subproblem **cannot see other days**.
  A whole-week or cross-day hard rule — e.g. a teacher's *free day*, or *no same
  class on two consecutive days* — is invisible inside one day's model, so it
  cannot be modeled there. (Temporal decomposition makes this explicit: the six
  days are solved in parallel, each blind to the others.)
- **How the gap is closed:** cross-day / global hard DSL is enforced after the
  week is assembled — either by the **monolithic week refinement** (run the week
  solve with `solve_dsl_compliant`) or by a **metaheuristic post-pass**. Both
  see the whole week and therefore the cross-day rules. The assembled week can
  also be run through `verify_dsl_hard` to *report* any residual cross-day
  violation before the meta pass enforces it.

### Column generation / branch-and-price — *maximally compliant within a column*

`column_generation.run_column_generation` is a Dantzig–Wolfe scheme: a master
LP selects from a catalog of **columns** (per-teacher / per-class / per-day /
… patterns — 9 pricer granularities), and per-column CP-SAT **pricers**
generate new patterns from the current duals. A Ryan–Foster branch-and-price
tree sits on top.

- **What is honored natively:** any DSL whose scope fits inside a single
  column — the pricer that builds a teacher's (or class's, or day's) pattern
  models the rules confined to that scope.
- **Motivation for the limit:** a pricer's subproblem **only sees its own
  column's scope** — one teacher, or one class, or one day. A hard rule that
  **couples multiple columns** (two teachers, two classes) or constrains the
  **whole timetable** cannot be expressed inside any single pricer, because the
  variables it would reference live in other columns the pricer never sees.
- **Detect + report + delegate (implemented):** after the master assembles the
  final integer solution, `run_column_generation` runs
  `dsl_cp_gate.verify_dsl_hard(assembled_sol, profs, hard_exprs)` when the
  caller passes `dsl_hard_expressions=`. Each violation becomes a
  `compile_failed:<expr>:bp:not_modeled_in_pricer` diagnostic, summarized via
  `constraint_compat.summarize(…, pipeline="branch_and_price")`, stored on
  `info["dsl_unsatisfied"]` / `info["dsl_warnings"]`, and logged. The webui
  orchestration (`optimization.run_column_generation`) loads the hard DSL while
  the DB session is open and threads it in, then surfaces the warnings to the
  run log. This is **additive**: the solution is unchanged; the gate only adds
  reporting. **Enforcement** of the reported cross-column rules is delegated to
  a metaheuristic post-pass.
- **Zero-drift default:** with `dsl_hard_expressions=None` (the default) the
  whole gate block is skipped and behaviour is byte-identical to before.

---

## How to guarantee any constraint is enforced

Whatever the chosen scheduler cannot natively model, run the **metaheuristic
post-pass** on the active solution:

```python
run_meta(stage="lns", …)   # or sa | ts | ils | alns | vns | lagrangian
```

`run_meta` loads every DSL rule from the DB while the session is open
(hard expression strings + pre-parsed soft trees) and threads them into the
chosen algorithm. From then on:

- **every hard DSL rule** is enforced by move-rejection (`is_hard_feasible`),
- **every soft DSL rule** is scored into the objective (`compute_soft`).

This is the universal guarantee: regardless of which fast method produced the
timetable (per-day, decomposition, or column generation), a metaheuristic pass
brings it into full DSL compliance — or, if a hard rule is genuinely
unsatisfiable given the rest, surfaces that as a warning rather than shipping a
violating schedule.

---

## Summary

| Statement | Status |
|---|---|
| Monolithic weekly CP-SAT honors any checkable hard DSL | ✅ complete (compile + refine, bounded) |
| Metaheuristics enforce any hard DSL and score any soft DSL | ✅ complete (universal) |
| Per-day / decomposition honor day-scoped DSL | ✅ complete within a day |
| Per-day / decomposition honor cross-day/global DSL | ⚠️ via assembled-week refinement or `run_meta` |
| Column generation / branch-and-price honor per-column DSL | ✅ complete within a column |
| Column generation / branch-and-price honor cross-column/global DSL | ⚠️ detect + report (post-assembly) + enforce via `run_meta` |
