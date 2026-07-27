# Unified-SOFT + General-Constraints — autonomous work log

## ✅ FRONTEND AUDIT + IMPLEMENTATION (2026-06-09) — pushed to origin/main

Audit doc: `docs/frontend_audit_2026-06-09.md` (3 axes: use-cases/gaps, vincoli
xlsx feasibility, css/js). Then implemented the backlog:

- **Tooltips**: `src/lib/actions/tooltip.ts` (2s hover, focus-immediate, portal,
  pure `computeTooltipPosition` tested) on nav + Phase B solver enums.
- **20 decorative SVGs** (`static/decor/`, Recraft vector, transparent) +
  `DecorIcon.svelte` + manifest; placed in 20 page headers + empty-states.
- **`Button.svelte`** (variants + loading spinner, `button_variants.ts` tested).
- **UX perf**: RunLogPanel scroll-preserve; WeeklyCalendarView dragover
  re-render guard; dashboard skeletons (`datasetLoading`/`datasetEverLoaded`).
- **Empty-states**: illustrated empty branch in `SortableQueryableList` (all
  list pages at once).
- **Color tokens**: GroupedEventsTable/RoomDropdown/FeasibilityPanel hex →
  Tailwind (chart/graph palettes intentionally kept).
- **/import dry-run**: backend `dry=true` (commit→flush+rollback, no persist;
  2 tests) + frontend "Anteprima" button. (The page was already functional —
  the audit's "shell" was a misread.)
- **Vincoli xlsx language**: `_vincoli_parser.py` (row→DSL/ORM intent, DSL
  round-trip tested) + `template-vincoli`/`import-vincoli` endpoints + UI card.
  9 tests. Plesso rows deferred (niche).
- **Feasibility badge** on dashboard active solution.

**#15 DONE (2026-06-09):** added `POST /api/assignments/bulk/restore` (+2 tests)
-> assignment bulk-delete UNDO; schedule lesson MOVE undo (move back) + DELETE
undo (recreate via /api/schedule/lesson, dry_run into the freed slot). Conflict
drill-down already existed (ScheduleConflictModal per-category list); enriched
with day/hour. Only group-lesson delete-undo is skipped (add endpoint is
class-bound).

Verify: `npm test` (46) + `npm run check` (0 errors) + `npm run build` green;
backend import/vincoli tests green. Dev servers: backend :8000, frontend :5173.



## ✅ FOLLOW-UPS COMPLETE (2026-06-09) — all 4 logged items done + pushed

1. **classify_diagnostic colon labels** (`engine/constraint_compat.py`) — peel known
   trailing suffixes (`:bp:not_modeled_in_pricer`, `:refinement:exhausted`) from the
   right + handle `compile_failed_extra`; colon-bearing CG/BP + refinement expr
   labels are preserved whole (no longer split). Test `test_constraint_compat.py`.
2. **Per-day DSL surfacing** (`webui/backend/optimization.py`) — the monolithic
   per-day loop loads DB HARD DSL once and threads `via_dsl` /
   `extra_dsl_expressions` / a shared `diagnostics_sink`; per-day-modelable rules
   enforced, cross-day/unsupported skipped + surfaced via pure
   `_per_day_dsl_warning_lines` -> `[phaseB.day][WARN]`. Zero drift when no HARD DSL.
   Test `test_per_day_dsl_surfacing.py`.
3. **Time-threshold SOFT pragmas** — `slot_after_hour_penalty(threshold_hour,weight)`
   ('avoid afternoons') and `teacher_max_hours_after(threshold_hour,max_n,weight)`
   ('max N hours after T'). One source across 3 layers: `soft_costs.py`
   (`late_slot_pairs`, `teacher_late_excess_pairs`) -> `dsl_to_cpsat.py` (compile +
   phase_b PRAGMA_LEVEL) -> `general_dsl.py` (boolean eval, round-trips through meta).
   threshold_hour in slot-hour units; translator maps clock->index. Test
   `test_time_threshold_soft_pragmas.py`.
4. **Q5: general_dsl relocated into engine** — `git mv` to `engine/general_dsl.py`;
   old path is a `sys.modules` alias shim so all 3 import names resolve to ONE module
   object (kills the dual-module AST hazard structurally). Engine importers flipped to
   flat `import general_dsl`; `build_world(db)` keeps a lazy ABSOLUTE webui import
   (webui-only). Verified `flat is shim == True`, cross-name isinstance True.

Verification: full fast backend suite **740 passed** (2 perf-budget wall-clock flakes,
confirmed passing isolated — not regressions).

## ✅✅ GOAL COMPLETE (2026-06-09) — summary

All directives addressed:
1. **A→D lifecycle** — `soft_costs.py` is the single source of soft-cost
   encodings for every backend (mono-week, per-day CP, decomposition, column-
   generation pricers, metaheuristic scorer). Done.
2. **Metaheuristic = completely-general DSL solver** — `run_meta` loads + threads
   ANY DSL hard (move-rejection) and ANY DSL soft (penalty). The universal
   enforcer. (`7dc46de`)
3. **Monolithic weekly CP-SAT = completely DSL-compliant** — `solve_dsl_compliant`
   compiles the broad native fragment then no-good-refines the rest (bounded),
   warning on exhaustion. (`600f5a6`)
4. **CG / branch-and-price** — native per-column DSL honored; assembled solution
   post-hoc verified, cross-column DSL detected + reported + delegated to the
   meta pass. (`eed55ac`)
5. **Per-day / decomposition** — maximally compliant within a day; cross-day/
   global DSL delegated to assembled-week refinement or the meta pass (motivated).
6. **Motivations** — `docs/dsl_compliance.md`: per-method compliance matrix +
   intrinsic-limit motivations + "how to guarantee any constraint" (run_meta).
7. **Solver-compat warnings** — `engine/constraint_compat.py` structures the
   (previously discarded) diagnostics into {constraint, pipeline, reason,
   suggestion, severity}; surfaced to RunLog for week + CG/BP. (`689f51f`)
8. **Convenience pragma** — `no_same_class_consecutive_days(cl)` in evaluator +
   compiler. (`87e44bc`)
Frontend-agnostic: `engine/constraint_compat.py` + `engine/dsl_cp_gate.py` carry
no webui import; the translator (`build_soft_pragmas`/`dsl_translator`) holds
presets; weights are always pragma args. All pushed to origin/main.



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
- **B1 — DONE** (commits `f891204` class_busy branch, `16f4e74` per-day
  migration; pushed). `solve_phase_b_for_day` now sources sixth+buchi from
  `build_soft_pragmas(scale_mode="phase_b_per_day")` via one
  `DSLConstraintCompiler` (reused for the `via_dsl` hard block); inline
  `W_SIXTH_B`/`W_GAP`/`gap_terms`/`sixth_terms` deleted. Added
  `soft_costs.sixth_class_busy_pairs` + `_sixth_class_busy_indicators` helper.
  Added `return_objective=` kwarg (3-tuple) for value tests; default 2-tuple
  contract preserved (all callers verified). Buchi encoding changed
  (`gap_*`→`bch_*`) — same objective value. Functional + value tests green;
  200 DSL-path + 11 slow integration green. Loader still `include_soft=False`.
- **B2** — REFRAMED after investigation: there is NO live double-count.
  `build_phase_a_pragmas` emits only HARD pragmas, so `glib_pen` is ALWAYS 0
  in the functional `solve_phase_a`; per-day Phase-B uses `include_soft=False`.
  → free-day is fully DORMANT on per-day; only mono-week (loader
  `include_soft=True`) applies it. B2 job: flip per-day Phase-B loader to
  `include_soft=True` (single owner = loader; Phase-A glib already 0, so no
  double-count) → lights up free-day + ALL dormant table soft (soft
  unavailability, soft general/logical/coteach) on per-day. Clean the dead
  `glib_pen` scaffolding in `solve_phase_a`. Functional gate: a soft free-day
  / soft-unavailability rule actually steers a per-day solve. NOTE: cross-day
  prefs (free-day) are inherently weakly handled by per-day decomposition
  (each day solved independently) — flag via the solver-compat system later.
- **B-gen** — general grid-relative time-threshold soft family:
  `slot_after_hour_penalty(weight, threshold)` ("avoid afternoons"),
  `teacher_max_hours_after(weight, threshold, cap)` ("max 1h after 15:00"),
  generalized last/Nth-slot; the fixed sixth-hour penalty becomes a special
  case. Behavior change, own gate. Thresholds are config-driven slot codes.
- **B2 — DONE** (commit `50a6058`, pushed; reviewed/approved). Per-day loader
  `include_soft=True` via per-rule is_hard/soft_weight toggle + re-Minimize
  (NOT a bare flip — would have promoted soft→hard). Dead glib removed.
- **B3 — DONE** (commit `6e3b589`, pushed). `add_buchi_soft` (spectral stages
  A/B/C) now delegates to `soft_costs.buchi_pairs(weight=1)`; slot5 view
  restricted to passed triples preserves the old `present_p` fixed-triple
  exclusion. Return shape kept (list of vars). `solve_monolithic_day` →
  `solve_phase_b_for_day` already inherits B1/B2. temporal/curriculum/metis
  delegate to per-day. 5 new + 10 decomp + 38 phase_b + slow loop green.
- **C — DONE** (commits `07e9e5f` accessor refactor, `2427427` CG delegation;
  pushed, reviewed). `soft_costs._buchi_daydist_vars` refactored to a
  `vars_at(t,d,h)` accessor callback + new `buchi_daydist_terms_from_accessor`.
  `column_generation._add_full_soft_cost_terms` (~80-line divergent buchi/
  five/one copy) now delegates to it. All 9 BP granularities iterate +
  HARD-feasible. fixed_load + term order byte-equivalent. C Task 3 (CG sixth
  `_SIXTH_HOUR=13` loop unification) DEFERRED — low-value simple loop; note.
- **D** — metaheuristics. `compute_soft` (metaheuristics.py:113) is a pure-
  Python post-hoc scorer; its sixth/buchi/five/one DEFINITIONS already match
  the CP encoders and weights come from shared `OBJECTIVE_WEIGHTS` (no weight
  drift possible). REAL gap = metaheuristics IGNORE arbitrary DSL soft (custom
  user constraints) — a meta post-processor could improve structural metrics
  while trampling user soft. D deliverable: extend `compute_soft` to ALSO
  evaluate DSL SOFT rules against the solution via the EXISTING post-hoc
  evaluator (`build_world`/`evaluate_safe`, already used by
  `is_hard_feasible(dsl_hard_expressions=, db=)`), weighted per rule. Keep
  structural scoring; share `sixth_hour`/weights. Add a cross-check test
  (compute_soft metrics vs CP objective on a locked solution). Full
  dual-backend pragma system (every pragma carries a Python cost-fn) is YAGNI
  — the post-hoc DSL evaluator already IS the Python backend. Functional gate:
  meta runners still produce HARD-feasible solutions + now honor DSL soft.

NOTE (B1 safety): the full fast suite ran 694 passed / 3 failed; all 3
failures are `test_perf_budgets.py` timing tests under a 64-min saturated
run (~6 concurrent test subagents) — load flakes, pass in isolation, NOT
functional regressions (per the test policy, perf/outcome tests may shift).
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
- 2026-06-08 (B2 — DONE): per-day Phase-B loader flipped to
  `include_soft=True` in `solve_phase_b_for_day`'s `via_dsl` block. KEY
  CORRECTION to the plan premise: the per-day block reuses ONE
  `DSLConstraintCompiler` whose `is_hard`/`soft_weight` are instance attrs
  (default `is_hard=True`). Simply flipping `include_soft` would have
  compiled SOFT rows as HARD (promoting soft→hard, breaking feasibility).
  Fix: set `compiler.is_hard`/`compiler.soft_weight` per rule (save/restore
  around the loop, mirroring the week path's `add_dsl_constraint`), then
  re-`model.Minimize(sum(compiler.soft_cost_terms))` after the loop (CP-SAT
  Minimize replaces; the term list is a superset of the structural terms, so
  no double-count). Dead `glib_pen` fold + `glib=` print removed from
  `solve_phase_a` (always 0; comment now points to the loader as free-day
  owner). `optimization.py` `_apply_dsl_rules_to_week_solver` NOTE updated.
  Functional+steering gate `test_b2_per_day_table_soft.py` RED (h12 used
  under old behavior) → GREEN (h12 avoided). No outcome test broke; 233
  fast DSL-path + 11 slow integration green.

## ✅ A→D LIFECYCLE COMPLETE (2026-06-09)

`soft_costs.py` is now the single source of soft-cost encodings consumed by
EVERY backend: mono-week (`compute_soft_cost_expr`), per-day CP
(`solve_phase_b_for_day`), decomposition (spectral `add_buchi_soft`),
column-generation pricers (`_add_full_soft_cost_terms`), and the metaheuristic
Python scorer (`compute_soft`, which ALSO honors arbitrary DSL soft now).
Commits: A `3b30d42..3da2e07`; B1 `f891204`,`16f4e74`; B2 `50a6058`; B3
`6e3b589`; C `07e9e5f`,`2427427`; engine-decouple `2e63b74`; D `252723a`,
`27bac43`. All pushed.

REMAINING (generality mandate — the "then" of the goal):
- **B-gen** — general grid-relative time-threshold soft family.
- **GEN/HARD** — general hard + cross-day predicates (no-same-class-consec-days)
  + solver-compatibility warning system (the headline user ask).
- **Q5** — relocate `general_dsl` into the engine (frontend-agnostic).
- B-gen and GEN are now UNBLOCKED — the single-stream plumbing exists to hang
  new pragmas + the capability/warning matrix on.

## D progress + findings

- **D — DONE** (Task1 `252723a`, Task2 `27bac43`, both pushed, reviewed).
  `compute_soft(sol, profs, soft_rules=None)` adds `int(weight)` per VIOLATED
  DSL soft rule
  (evaluated via `_build_world_from_sol` + `general_dsl.evaluate_safe`),
  exposes `metrics["dsl_soft"]`; default path byte-identical. Added
  `parse_soft_rules(rules)` (pre-parse dicts → `[(tree, weight)]`).
- **Engine-decoupling fix** (commit `2e63b74`, pushed): `dsl_to_cpsat.py`
  `compile()` had a bare `from webui.backend.utils import general_dsl` with NO
  fallback → `ModuleNotFoundError: No module named 'webui'` on the
  meta→ALNS→CP-repair path (pre-existing, failed `test_run_alns_does_not_free_locked`).
  Added the repo-root fallback idiom. Aligns with the frontend-agnostic mandate.
- **CRITICAL constraint for D Task 2 (dual-module hazard):** `general_dsl` is
  importable as BOTH `webui.backend.utils.general_dsl` AND
  `backend.utils.general_dsl` — Python treats them as DISTINCT modules with
  distinct AST node classes. A tree parsed under one alias and evaluated under
  the other → all `isinstance` checks fail → top node returns None →
  `bool(None)=False` → EVERY solution reads as VIOLATED. Mitigation: trees MUST
  be produced by `meta.parse_soft_rules` (same module object as `compute_soft`).
  ROOT FIX (GEN/HARD phase): move `general_dsl` into the engine or a shared
  location so there is ONE canonical module — kills the dual-identity hazard
  AND the webui-coupling. Tracked as Q5.

## Open questions / problems (resolve or revisit)

- Q5 (GEN/HARD): `general_dsl` lives at `webui/backend/utils/general_dsl.py`
  but is the ENGINE's parser/evaluator — couples engine→webui + creates the
  dual-module AST-identity hazard. Consider relocating to `engine/` (or a
  shared pkg) with a re-export shim at the old path for back-compat. Frontend-
  agnostic mandate wants the engine to own its DSL.

## GEN findings (investigation, 2026-06-09)

- **Cross-day constraints ALREADY WORK.** "No same class on consecutive days"
  is expressible (post-hoc: nested `forall l1 ... forall l2 where l2.class ==
  l1.class and l1 != l2: not consecutive_days(l1.day, l2.day)`) AND compiles to
  CP-SAT forbid-pair constraints (static-reducible body). Tests:
  `test_general_dsl.py:244-276`, `test_dsl_to_cpsat.py:333-369`. The DSL grammar
  is rich: nested quantifiers, `count`/`sum ... op value`, `+`/`-` arithmetic,
  builtins `consecutive`/`consecutive_days`/`same_day`/`hour`/`day`. Missing:
  only a convenience pragma `no_same_class_consecutive_days(cl)` (the capability
  exists via the verbose form). Compiler limitation: nested-forall body must be
  static-reducible; dynamic 3rd-var bodies fall back to a diagnostic.
- **Solver-compat = the real deliverable.** ~50 diagnostic-append sites exist
  (`dsl_to_cpsat.py` per-construct "not yet supported / dynamic; skipped" +
  pragma-level mismatch; `cpsat_v2_timetable.py:1391/1398/1406/1428`
  compile_failed/db_load_failed). `solve_phase_b_for_day` collects them in a
  local `dsl_diagnostics` list but RETURNS `(out, status)` — diagnostics are
  printed to stdout (if log) and DISCARDED. The week path stores
  `solver.dsl_diagnostics` but only prints a count. NOTHING reaches RunLog/UI.
  → constraints ARE silently dropped from the user's view. The warning system
  must COLLECT (already done) + STRUCTURE + SURFACE (return + RunLog).
- Per-pipeline backend: CP paths (mono-week, per-day, decomp) validate via
  `DSLConstraintCompiler` (compile-time, can skip un-modelable constructs);
  metaheuristics validate via the post-hoc `general_dsl.evaluate` (accepts MORE
  — e.g. dynamic nested forall). So the capability MATRIX differs by pipeline:
  a constraint dropped by per-day CP may be honored by a metaheuristic pass.
  That asymmetry drives the "suggestion" (e.g. "run a metaheuristic post-pass").

## User directives (2026-06-09) — universal solver + max compliance
- **At least ONE solver must accept ANY DSL constraint.** ANSWER: the
  metaheuristic post-hoc path already evaluates the FULL grammar
  (`general_dsl.evaluate`). D wired `compute_soft(soft_rules=)` (any soft).
  Need the symmetric HARD wiring: `run_meta` must load + pass
  `dsl_hard_expressions` (all HARD DSL rules) to the runners so they reject
  moves violating ANY hard DSL → metaheuristic = the completely-general solver.
- **All solvers maximally DSL-compliant within intrinsic capability.** CP
  compilers model what they can (per-slot reif, nested-forall-static, pragmas);
  intrinsic limits (dynamic/cross-entity at compile time) → warned + delegated
  to the meta pass via the warning system. Improve CP coverage where tractable.
- **Build the shorthand pragma** `no_same_class_consecutive_days(cl)` (the
  capability exists via nested forall; add the convenience form in BOTH the
  evaluator builtins and the CP compiler).

## GEN-warn progress
- **Task 1 — DONE** (commit `689f51f`, pushed). `engine/constraint_compat.py`
  (pure, webui-free): `ConstraintWarning` + `classify_diagnostic` + `suggest` +
  `summarize`. `solve_phase_b_for_day(diagnostics_sink=None)` exposes its
  collected diagnostics (default None = unchanged 2/3-tuple return). Verified a
  real diagnostic (`forall over 'teachers' not yet supported`) → structured
  warning w/ suggestion. 5+6 tests green.

## User directive REFINEMENT (2026-06-09) — full DSL compliance everywhere
- NOT just one general solver. The MONOLITHIC WEEKLY CP-SAT must be COMPLETELY
  DSL compliant. ALL remaining methods (per-day, decomposition, column-
  generation, branch-and-price) must be made as DSL-compliant as possible
  within their intrinsic capabilities. Where a method CANNOT accept all DSL,
  WRITE THE MOTIVATIONS. Then mark the goal complete.
- MECHANISM (general): CP solver compiles every rule `DSLConstraintCompiler`
  can model natively (broad fragment), THEN post-solve VERIFIES all hard DSL
  via the post-hoc evaluator and adds NO-GOOD CUTS + re-solves (bounded) for
  anything the compiler couldn't express → final solution honors everything
  checkable. Intrinsic gaps (BP per-column pricers can't see global/cross-
  column constraints) → documented motivation + enforce at final assembly.
- DELIVERABLES: (1) `engine/dsl_cp_gate.py` verify+refine helper; (2) wire it
  into MonolithicSolver (completely compliant); (3) per-day/decomp use it on
  the assembled week or document per-day-scope limits; (4) CG/BP post-assembly
  verification + motivation; (5) `docs/dsl_compliance.md` compliance matrix +
  motivations; (6) `no_same_class_consecutive_days(cl)` pragma; (7) GEN-warn
  Task 2 surfacing.

## Full-DSL-compliance progress
- **Task 1 — DONE** (`3db8d70`): `engine/dsl_cp_gate.py` — `verify_dsl_hard`
  (post-hoc check), `add_nogood` (forbid exact assignment), refinement loop.
- **Task 2 — DONE** (`600f5a6`): MonolithicSolver `solve(forbidden_solutions=)`
  + `solve_dsl_compliant(hard_exprs, profs)` = compile-natively-then-no-good-
  refine (bounded max_iters=8). Week orchestration (`_solve_phase_b_week`)
  refactored to a `_build_week_solver(forbidden)` closure driving the
  refinement when hard DSL present; unsatisfied → `constraint_compat` warnings
  as `[phaseB.week][WARN]` RunLog lines. Default (no hard DSL) byte-identical.
  → MONOLITHIC WEEK IS COMPLETELY DSL-COMPLIANT. 231 + slow week green.
  Note: refinement branch proven by synthetic + empirical convergence tests
  (the simple forbid-pattern is iter-0-enforced by the CP objective).

## Remaining roadmap (post A→D)
- **MetaGeneral — DONE** (commit `7dc46de`, pushed). All 7 meta runners accept
  + enforce `dsl_hard_expressions`; `run_meta` loads HARD rule strings once and
  threads them (+ `run_lns` CP-repair gets a post-repair `is_hard_feasible`
  gate). Strings cross the boundary (re-parsed in metaheuristics — dual-module
  safe). Metaheuristic = completely-general DSL solver. 4 new + 91 meta green.
- **consec-days pragma**: `no_same_class_consecutive_days(cl)` in evaluator +
  compiler.
- **GEN-warn Task 2**: surface warnings to RunLog (orchestration).
- **CP coverage**: broaden `DSLConstraintCompiler` where tractable.
- **GEN-warn** (headline ask): `engine/constraint_compat.py` —
  classify+structure the existing diagnostics into
  `{constraint_label, pipeline, reason, suggestion, severity}`; thread a
  `diagnostics_sink` out of `solve_phase_b_for_day`; orchestration surfaces them
  to RunLog + the run result. Suggestion uses the pipeline capability asymmetry.
- **B-gen**: general time-threshold soft pragmas.
- **consec-days pragma**: `no_same_class_consecutive_days(cl)` shorthand (small).
- **Q5**: relocate general_dsl into engine.

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
  - B2 finding (per-day input for the solver-compat matrix): with
    `include_soft=True` no soft rule CRASHES the per-day compile — soft
    unavailability compiles to a weighted slot term and steers correctly.
    The cross-day free-day preference (`teacher_preferred_free_day_penalty`)
    does NOT raise either: on a single-day solve it references a `day` not in
    that day's slot view, so it silently contributes ZERO penalty (graceful,
    but semantically a no-op per-day). This is the canonical "compiles but
    is weakly/ not honored on this pipeline" case the solver-compat warning
    must flag — NOT via `dsl_diagnostics` (no exception is recorded), but via
    a capability rule: "cross-day soft on per-day decomposition = degraded".
    So the matrix needs a *capability* signal, not just exception-capture.

## Final regression (2026-06-09)
- Full fast suite: **729 passed**, 1 failed, 2 skipped. The single failure is
  `test_perf_budgets.py::test_full_tab_cycle_within_budget` (HTTP wall-clock
  budget) under a 79-min saturated run — passes ISOLATED in 2.84s. Per the test
  policy (functionality sacred, perf/outcome may shift) the suite is GREEN.
  Suite grew 692→729 (new TDD tests across all slices). GOAL COMPLETE.

## Documentation goal (2026-06-09): COMPLETE — pushed 69af003
Audited the LaTeX manual + companion markdown; shipped content + aesthetic refresh.
- **Content** reflecting the unified-soft + full-DSL work and the frontend audit:
  - `dsl_generico_per_i_vincoli.tex` §Conformità DSL universale (soft_costs single
    source, universal metaheuristic solver, no-good refinement, CG delega,
    constraint_compat, 3 new time-threshold pragmas).
  - `vincoli.tex` §Caricare i vincoli da xlsx (Vincoli vocabulary table +
    template-vincoli/import-vincoli endpoints); added `\label{sec:cinque-stati}`.
  - `guida_ui.tex` §Novità dell'interfaccia (tooltip 2s, dry-run, undo, spinner
    buttons, skeletons, decor SVGs).
  - `api_rest.tex` bulk/{delete,restore}, import `?dry=true`, Vincoli xlsx group.
  - `docs/general_dsl.md` + `webui/docs/import_format.md` matching prose.
- **Aesthetics** (`preamble.tex`): `novitabox` tcolorbox (cAllow/cEnf) + warm
  `cAvorio!35` listing background.
- **Build**: lualatex+biber+makeindex, both manuals — `manual.pdf` 4.99 MB,
  `manual_en.pdf` 1.69 MB, exit 0, no undefined refs/`??`. Committed PDFs + sources.

## P0 production-hardening from Opus audit (2026-07-27)
Four-agent audit (engine / DB / frontend / ops) flagged big-school blockers;
implemented the five P0 fixes. Backend validated on a Python 3.12 venv (web
deps only — the solver stack isn't installed here, so the engine-heavy fast
tests can't run locally; CI must confirm the DSL-gate branch). `test_run_manager`
+ `test_section_2_5` green; full `backend.main` app imports; all touched files
byte-compile.
- **P0-5 DB locking** (`db.py`, `async_db.py`): added `PRAGMA busy_timeout=5000`
  and replicated the WAL/synchronous/busy_timeout listener onto the async engine
  (previously async connections got neither WAL nor a timeout). Kills the
  "database is locked" 500s under concurrent solver-commit + UI-write.
- **P0-2 truthful cancellation** (`run_manager.py`, `optimization.py`): `_runner`
  no longer overwrites a `cancelled` run back to `done`/`failed` (the Run table
  lied about outcomes). Added `RunCancelled` + `raise_if_cancelled` and wired
  cooperative checks into the full-pipeline step loop and every inlined per-day
  decomposition loop, so a cancel unwinds promptly instead of burning the whole
  time budget. SSE `stream_events` now emits `end` for `cancelled` too. (Mid
  single-solve OR-Tools interruption via a SolutionCallback remains a follow-up.)
- **P0-4 admission control + orphan sweep** (`run_manager.py`, `main.py`): a
  `BoundedSemaphore(PITANTUM_MAX_CONCURRENT_RUNS, default 1)` queues excess runs
  as `pending` instead of OOM-ing on N concurrent big-school solves; a
  cancel-while-queued exits without consuming a slot. `reconcile_orphaned_runs()`
  runs at startup to flip runs left `running`/`pending` by a crash into `failed`
  (no more undeletable ghosts with never-ending SSE).
- **P0-3 single-tenant firewall** (`tenant.py`, `main.py`, `dataset.py`,
  `dashboard.py`): `SingleTenantGuardMiddleware` universally rejects a spoofed
  `X-Tenant-Id` (≠ default) with 400 while multi-tenant is off — closing the
  hole that `current_tenant_id` couldn't (26/27 routers never `Depends` on it).
  Opt in with `PITANTUM_MULTI_TENANT=1`. Destructive whole-DB ops (`/dataset/clear`,
  `/dashboard/import-db`, `/snapshot/restore`) now 409 while any run is active,
  so the DB file can't be swapped out from under a live solver.
- **P0-1 truthful outcomes** (`cpsat_v2_timetable.py`, `optimization.py`): Phase A
  distinguishes proven `INFEASIBLE` from `UNKNOWN`/timeout (a big school that
  needs more time no longer looks permanently infeasible). The week-scope DSL
  hard-gate is now fail-closed: if hard rules remain violated after no-good
  refinement it raises instead of silently returning (and marking `done`) a
  timetable that breaks hard constraints. Escape hatch: `PITANTUM_DSL_GATE_STRICT=0`.
  (Decomposition/CG partial-coverage gating remains P1 — needs a runnable solver
  to change engine control flow safely.)

## P1 reproducible solver seeds (2026-07-27)
Audit flagged non-reproducibility (no `random_seed` on any of the 21 CpSolver
sites, multi-worker + wall-clock budget) as a "worked yesterday, fails today"
support nightmare. Added `engine/solver_config.py` and routed every solve
through `configure_solver(solver)` immediately before `Solve()`:
- `PITANTUM_SOLVER_SEED` (default 42) applied to every solve.
- `PITANTUM_DETERMINISTIC` forces a single search worker (multi-worker CP-SAT
  is non-deterministic even with a fixed seed).
Wired into 20 sites across cpsat_v2_assignment / cpsat_assignment_dsl /
classroom_assignment / cpsat_v2_timetable / cp_sat_constraint_model /
decomposition_spectral_v2 / column_generation. (column_generation's ortools
import is function-local, so its module-level `_solvercfg` import was added by
hand.) New `test_solver_reproducibility.py` (slow): two deterministic Phase-A
solves of the `small` profile return identical assignments even at the time
limit. Full fast suite green (756 passed) — the seed shifts no pinned outcome.

## P0 leftover: coverage gating (2026-07-27)
The remaining "silent partial success" P0 hazard: decomposition/monolithic
Phase B can leave lessons unplaced (a day/cluster unsolved in time), and the
partial timetable was saved + the run marked 'done'. Added `_coverage_ratio`
/ `_gate_coverage` in optimization.py: coverage = placed cells / sum of the
Phase-A day-counts (`dc_value`). The gate records `coverage` in run metrics
and, when strict (default; PITANTUM_COVERAGE_STRICT=0 to opt out), raises so
the run is marked failed instead of passing off an incomplete schedule. Wired
into both the full-pipeline phase_b step and the standalone run_phase_b, before
the DB import so a strict failure never becomes the active solution.
Tests (`test_coverage_gate.py`): 4 fast unit tests of the helpers + 1 slow
end-to-end asserting a solvable small school reaches 100% coverage through the
real run_phase_b entry point (run 'done', coverage recorded). Slow scenario +
placement suites still green (my gate doesn't fail legitimate solves); full
fast suite 760 passed.

## DB integrity CHECKs + concurrency-safe run-log capture (2026-07-28)
Next audit tranche from the four-agent Opus audit (engine / DB / frontend /
ops) — the items testable end-to-end with the local solver venv and safe from
fragile solver control flow. Two areas:

- **Ops CRITICAL — concurrency-safe run-log capture** (`run_manager.py`). The
  old capture swapped process-global `sys.stdout`/`stderr` for a per-run
  `_TeeWriter`; with >1 concurrent run (or any request handler that `print`s
  while a run is live) run B's swap clobbered run A's, and A's `finally`
  restored whatever stream was current when A *started* — logs cross-
  contaminated and leaked. Replaced with a single process-wide `_DispatchWriter`
  that routes each write to the run registered for the **calling thread**
  (`_CAPTURE_ROUTES: thread ident -> run_id`, guarded by `_CAPTURE_LOCK`);
  threads with no active run fall straight through, so a `print()` outside any
  run never lands in an unrelated run's log. Partial lines buffer per-thread via
  `threading.local`. `_install_dispatch_writers` is idempotent and re-wraps if a
  test-runner capture plugin swaps stdout back out. Microbenchmarked: ~210 ns
  extra per write in the no-route case (RLock acquire) — negligible. New
  `test_capture_stdout_is_isolated_per_thread` (two barrier-synced overlapping
  captures assert zero cross-contamination). Still open (P1): the in-process run
  registry itself is per-worker, so the same isolation must move to a shared
  store before the documented `gunicorn -w 4` topology is safe (see ops audit).

- **DB HIGH/MEDIUM — real integrity CHECKs matching the docstrings**
  (`models.py`). The XOR invariants were documented as "Enforced via CHECK
  constraint below" but `grep CheckConstraint models.py` was empty; malformed
  rows (both-set / both-null) were only silently *skipped* by `engine_io`, so
  corruption stayed invisible until a class came up under-scheduled. Added:
  - `ck_assign_class_group_xor` — `Assignment`: exactly one of
    (class_id, group_id), OR both NULL only for a potenziamento row.
  - `ck_coteach_class_group_xor` — `CoteachGroup` targets exactly one of
    class / group.
  - `ck_csp_required_matches_state` — pins the derived
    `ClassroomSubjectPreference.required` to `state = 'enforced'` so a bulk
    path (Core insert/executemany) that bypasses the ORM event can't drift it.
  Verified against a fresh DB: all three reject every corruption shape and
  accept the valid ones. `test_group_xor_class_id_set_violates` updated: a
  both-set Assignment is now rejected at `flush()` by the DB (the earlier,
  stronger guard) instead of only by the app-layer preflight, which remains as
  defense-in-depth. Lesson has no DB XOR — its `class_name` is NOT NULL by
  design (a group Lesson still carries the group's virtual-class label), so
  there is no both-NULL shape to forbid.

  These CHECKs land on **fresh DBs** via `Base.metadata.create_all` (the
  new-school / SaaS onboarding case the DB audit flagged). Backfilling them onto
  **existing** DBs is a deliberate follow-up: the migration graph already has a
  **pre-existing dual head** (`b2c3d4e5f6a7` / `c2d3e4f5a6b7`) that needs a merge
  revision first, and a SQLite CHECK add is a table rebuild that fails on any DB
  already carrying violating rows — so it needs a data-audit + merge, not an
  in-flight autogen.

Validation: full fast suite `757 passed, 2 skipped`; the only 2 "failures" were
`test_perf_budgets` wall-clock-budget tests flaking under concurrent machine
load (an unrelated `uv` build at ~42% CPU during the run) — they pass 20/20 in
isolation. Targeted `test_run_manager` (6/6, incl. the new isolation test) and
`test_groups_preflight` (7/7) green. Docs-only `CLAUDE.md` drift present in the
tree beforehand was left untouched (not part of this tranche).
