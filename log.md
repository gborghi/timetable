# Unified-SOFT + General-Constraints — autonomous work log

Running log of decisions, open questions, and problems while implementing the
full A→D lifecycle of the unified-soft-via-DSL effort **and** the broader
generality mandate. Maintained autonomously (user set a no-supervision goal
2026-06-08). Newest entries at the bottom of each section.

## North-star goal (verbatim intent)

- Implement the full A→D lifecycle of unified soft-cost sourcing (spec:
  `docs/superpowers/specs/2026-06-08-unified-soft-dsl-design.md`).
- Soft **and hard** constraints implemented in backend+engine in the MOST
  GENERAL way. **The engine must be frontend-agnostic.** The frontend→engine
  translator (`dsl_translator`) may carry presets / specific pragmas, but the
  engine (`general_dsl` parser + `dsl_to_cpsat` compiler + `soft_costs`) must
  be completely general: any constraint the user can express in the DSL should
  compile and run — including cross-day shapes like *"do not have hours with
  the same class on consecutive days."*
- When a constraint cannot be honored by a chosen solver/pipeline, the engine
  must **not silently drop it**: raise a structured warning naming *which
  constraints* are incompatible with *which solver*, and surface a
  suggestion (revise constraints, or revise method). Frontend may render this
  as a modal.
- TDD throughout. Zero-drift for behavior-preserving refactors; explicit
  behavior-change slices get their own gates.

## Roadmap (sequencing)

- **A — DONE** (commits `3b30d42`..`3da2e07`). `soft_costs.py` single source;
  `compute_soft_cost_expr` delegates; 4 soft pragmas + `build_soft_pragmas`
  emitter (unwired). Carry-forwards recorded in spec §8.
- **B1** — zero-drift: per-day Phase-B (`solve_phase_b_for_day`) sources
  sixth+buchi from the pragma stream via its compiler (implements the
  `class_busy` compile branch = carry-forward #1; default `level="both"` =
  #2). Structural-only; loader stays `include_soft=False` (no free-day
  double-count). `sixth_hour` parameterized through `build_soft_pragmas`
  (default legacy) for B-gen forward-compat. Gate: `test_phase_b_per_day_soft_cost`.
- **B2** — free-day single-owner: remove Phase-A hardcoded `glib_pen`, make
  the loader (`teacher_preferred_free_day_penalty`) the sole source; flip
  per-day loader `include_soft=True` → enables dormant table soft on per-day.
  Atomic, zero-drift on objective value.
- **B-gen** — general grid-relative time-threshold soft family:
  `slot_after_hour_penalty(weight, threshold)` ("avoid afternoons"),
  `teacher_max_hours_after(weight, threshold, cap)` ("max 1h after 15:00"),
  generalized last/Nth-slot; the fixed sixth-hour penalty becomes a special
  case. Behavior change, own gate. Thresholds are config-driven slot codes.
- **B3** — decomposition cleanup (`decomposition_spectral_v2.add_buchi_soft`
  → shared `soft_costs`); confirm temporal/curriculum/metis delegate.
- **C** — BP / column generation: route pricers + master through the stream;
  delete `_add_full_soft_cost_terms`. (`column_generation.py` has its own
  `_SIXTH_HOUR=13` + per-teacher buchi calls.)
- **D** — metaheuristics: replace `metaheuristics.compute_soft` (Python
  post-hoc scorer) with a walker over the same soft stream (dual backend).
- **GEN/HARD** — general hard-constraint capability + cross-day predicates in
  the DSL (e.g. no-same-class-consecutive-days) + **solver-compatibility
  warning system** (structured "constraint X unsupported by pipeline Y" +
  suggestion). This is the broadest deliverable; scoped after the soft
  lifecycle so the single-stream plumbing exists to hang it on.

## Decisions log

- 2026-06-08: B decomposed into B1/B2/B3 (+ B-gen). Mono-week already clean
  (sources soft from `soft_costs` + loader `dsl_soft_cost_terms`); no B work.
- 2026-06-08: B1 boundary = slot-based Phase-B only (NOT the day-count Phase-A
  objective). Phase-A spread/day-count-five/one are a different encoding
  family; their migration + free-day go to B2.
- 2026-06-08: B1 mechanism = pragma stream via compiler (`objective =
  sum(compiler.soft_cost_terms)`), not direct `soft_costs` calls — establishes
  per-day plumbing B2 reuses.
- 2026-06-08: Grid generality is a behavior change → separate B-gen slice;
  B1 stays strictly zero-drift (`sixth_hour=13` preserved).
- 2026-06-08 (user directive): TEST POLICY — functionality/contract tests
  must NEVER break (solver runs, solution HARD-feasible, pragma compiles,
  soft applied via stream, diagnostics raised on incompatibility). Specific-
  OUTCOME tests (exact placements, exact objective values, exact var counts)
  MAY break and be rewritten. So gates are functional-first; value-equality
  is a secondary characterization, not a hard gate.
- 2026-06-08 (user directive): WEIGHTS must be general. Engine already
  satisfies this — every pragma takes `weight` as an argument; no weight
  policy is hardcoded inside `soft_costs`/`dsl_to_cpsat`. The `PENALTY_*`
  constants live only in `cp_sat_constraint_model` and are injected by the
  TRANSLATOR (`build_soft_pragmas`) as presets. Frontend may emit any weight.
  INVARIANT to preserve going forward: never bake a weight into an engine
  encoder; always pass it through the pragma/DSL.
- 2026-06-08 (user directive): may break+rewrite tests as restructuring
  needs; commit + push regularly; implement-agents + review-agents split
  (subagent-driven-development) — already the active pattern.

## Open questions / problems (resolve or revisit)

- Q1 (B1) — RESOLVED: `test_phase_b_per_day_soft_cost.py` pins
  `compute_soft_cost_expr(mode="phase_b_per_day")` (the ConstraintModel
  METHOD, A-side), NOT `cpsat_v2_timetable.solve_phase_b_for_day`. B1 touches
  the latter, which has NO existing objective test. So that suite is not the
  B1 gate (stays green trivially). B1 needs a NEW **value-based** gate:
  solve a tiny fixture (determined optimum, e.g. 4 contiguous hours) through
  the migrated `solve_phase_b_for_day` and assert the objective value equals
  the hand-computed legacy cost (sixth class-busy ×5 + buchi holes ×10).
  Structure-based assertion is wrong here — buchi encoding changes
  (`gap_*` per-slot → `bch_*` span−count) but objective value is identical.
- DECISION (2026-06-08): `sixth_hour` parameterization deferred from B1 to
  B-gen (where grid-generality lands). B1 keeps the `class_busy` pragma at
  hardcoded `sixth_hour=13` (matches slot mode) to stay minimal + zero-drift.
- Q2 (B-gen): "max one hour after 15:00" capped-count encoding — confirm a
  clean reuse of the buchi per-teacher/day slot scaffolding vs a fresh count.
- Q3 (GEN/HARD): Does `general_dsl` already support cross-day quantifiers
  (predicates relating slots on day d and d+1)? If not, the parser/AST needs a
  temporal-relation primitive before "no-same-class-consecutive-days" compiles.
- Q4 (solver-compat): Where do pipelines currently swallow un-compilable DSL
  rules? (`solve_phase_b_for_day` catches `compile` exceptions into
  `dsl_diagnostics` — that is the seam to turn into structured warnings.)
  Need a uniform "constraint capability matrix" per pipeline.
