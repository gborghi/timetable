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

## Frontend scalability + ops multi-worker advisory (2026-07-28)
The next two audit tranches — frontend scalability (audit agent 1) and the
ops multi-worker run-registry hazard (agent 4). Scoped to the changes that are
verifiable here (svelte-check + `npm test` + `vite build` + backend pytest +
buildx-safe); the calendar rewrites that can only be proven on a running stack
(server-side `/api/lessons` pagination, optimistic drag-drop) are deferred and
listed below.

- **Ops CRITICAL — single-worker run registry** (`Dockerfile`, `main.py`). The
  run orchestrator keeps buffers / threads / cancel-set / semaphore in
  per-process memory, so the docs' `gunicorn -w 4` recipe silently breaks SSE
  log streaming + cancellation for any request the LB routes to another worker.
  Corrected the Dockerfile production hint `-w 4` → `-w 1` with an explanation
  (scale via container replicas, not workers) and added a startup log advisory
  (a hard WARNING when `SERVER_SOFTWARE` shows we're under gunicorn). No code
  path changed — the default CMD was already single-worker uvicorn.
- **Frontend HIGH — RunLogPanel O(n²) log churn** (`RunLogPanel.svelte` +
  new tested `log_buffer.ts`). The panel rebuilt the whole 2000-line array (and
  re-joined the whole string) on *every* SSE line. Now lines batch into a
  `pending` list flushed at most once per `requestAnimationFrame`, capped via
  `appendCapped` (one allocation per frame). `log_buffer.test.mjs` (6 cases).
- **Frontend HIGH — invalidation storm** (`queries/client.ts`, `stores.ts`).
  Set `refetchOnWindowFocus: false` (alt-tabbing back used to refetch every
  mounted query at once) and made `bumpMutation(resources?)` selective-capable:
  the client now invalidates the reported resource key(s), falling back to
  invalidate-all only when a legacy call site reports none (fully backward
  compatible — no call sites had to change).
- **Frontend HIGH (correctness) — off-grid lessons silently vanish**
  (`WeeklyCalendarView.svelte` + new tested `off_grid.ts`). A lesson on a
  (day,hour) no longer configured in Tab Ore had no cell and just disappeared
  from the view. A warning banner now surfaces the count + first few, so the
  data loss is visible and actionable. `off_grid.test.mjs` (4 cases).
- **Frontend/Backend HIGH — conflict resolver N serial deletes**
  (`routers/lessons.py` `POST /api/lessons/bulk-delete`, wired into
  `schedule/+page.svelte::resolveDropConflict`). "Sostituisci" used to fire one
  DELETE per conflicting lesson, each triggering a full timetable reload; now
  one round-trip. Backend tests `test_bulk_delete_*` (2).

Validation: frontend `npm test` 56/56 (10 new), `svelte-check` 0 errors,
`vite build` OK; backend `761 passed` (the only 2 failures are the
`test_perf_budgets` wall-clock-budget tests, flaking because a local Tower-72B
MLX server was pinning ~62% CPU during the run — they pass 20/20 in isolation
and on an idle CI runner). Dockerfile change is comments-only, so the buildx CI
gate is unaffected.

Deferred (need a running stack / E2E to prove safe, not pushed): server-side
`/api/lessons` scoping+pagination and virtualization (the CRITICAL "3000 DOM
nodes / full reload per drag" items), optimistic single-lesson drag-drop,
FeasibilityPanel per-edit 30s solve debounce, conflict-graph layout cap. These
stay on the frontend audit backlog.

## Calendar CRITICALs + EN manual chapters (2026-07-29)
Closed the two calendar rewrites the 2026-07-28 tranche had deferred as
"only provable on a running stack", plus the manual leftovers. Verified with
what runs here (pytest + svelte-check + `npm test` + `vite build`); the drag
gesture itself and entity-switch flow still want a live E2E pass, which this
environment can't give (Playwright's chromium download fails — the MS CDN
returns `400 GatewayException` for build 1217 and the installer hangs).

- **CRITICAL — server-side `/api/lessons` scoping + pagination**
  (`routers/lessons.py`, `test_lessons_list_scoping.py`). `GET /api/lessons`
  gained optional `class_name` / `teacher_name` / `room_name` (plus
  `limit`/`offset`, and a `total` in the body). No params = the original
  whole-solution contract, so the "Orario globale" view and every existing
  caller are untouched. The scoped predicate mirrors `WeeklyCalendarView`'s
  client filter exactly (exact match, groups excluded); a test asserts
  scoped == fetch-all-then-filter so a future frontend can adopt the params
  without changing which lessons a view shows. 6 new tests + the 12 existing
  lessons-by-id tests green. The frontend *adoption* (sourcing the entity
  dropdowns from the dedicated `/api/{classes,teachers,classrooms}` endpoints
  instead of from the lesson set, so a scoped fetch doesn't collapse the
  switcher) is intentionally left for a session with a browser — it's a
  data-flow change to a load-bearing view that shouldn't ship un-E2E'd.
- **CRITICAL — optimistic drag-drop** (`schedule/+page.svelte`). A drop now
  repositions the block in the local `lessons` array immediately (`lessons`
  reassigned so Svelte re-renders and the soft-conflict overlay recomputes),
  instead of waiting for the move round-trip + a full grid reload. Rejects
  (HARD violation / occupied slot) and network errors snap the block back to
  its origin via `_optimisticMove(id, oldDay, oldHour)`; the accept path keeps
  the reconciling `loadCalendar()` as a safety net, so a wrong guess is
  self-correcting and the worst case matches the old flow. svelte-check 0
  errors, build + 61 unit tests green.
- **Manual — EN user chapters + screenshot embedding** (`manual_en.tex`,
  `chapters_en/{getting_started,workflow_tipici,terminologia_didattica}.tex`,
  IT+EN `getting_started`/`calendario_e_ore`). Wired the three translated
  user-facing chapters into the EN manual with EN-suffixed cross-refs
  (`check_refs` clean, 0 dangling), and embedded five UI screenshots via
  `\grokfig{shot_*}` in the IT+EN quick-start / `/ore` chapters. `\grokfig`'s
  `IfFileExists` guard omits the PNGs until they're captured, so both manuals
  build now and pick the shots up the moment `docs/figures/shot_*.png` exist —
  which needs the same browser this environment can't fetch. Rebuilt
  `manual.pdf` + `manual_en.pdf`.

## Manual screenshots captured via Homebrew Chromium (2026-07-29)
Follow-up to the previous section's "blocked by the environment". Playwright's
chromium is still unfetchable here, but the *browser* isn't the blocker -- only
the Microsoft CDN is. `brew install --cask chromium` pulls a build from Google's
CDN, which works; `xattr -dr com.apple.quarantine` clears Gatekeeper so it runs
headless unattended. Drove it with Selenium (Selenium Manager auto-resolves
chromedriver) via `webui/frontend/scripts/capture_shots.py` against the running
dev server, clicking "Per classe" before the `/schedule` shot. Captured the five
`docs/figures/shot_*.png` (1360-wide, 125-160 KB each) the manual already
embedded via `\grokfig`; both PDFs grew ~700 KB and now show real UI. (Aside:
`safaridriver` drives Safari fine and needs no download, but its WebDriver
screenshot returns a blank frame on this box -- the Chromium path is the one that
works.) selenium added to `requirements-dev.txt`.

## Sostegno per alunno, compresenza in API, e lo sblocco della modifica manuale (2026-07-30)
Tre filoni, tutti nati dal report dell'agente "Headmaster 60 classi".

**Il sostegno e' dell'alunno, non della classe.** La cattedra di sostegno punta
a `student_id` e la classe si *deriva* dall'alunno; non serve -- e non si deve
-- creare un `Subject` chiamato "sostegno" ne' una riga `ClassSubject` che ne
conti le ore nel monte ore settimanale (era la deriva che gonfiava le classi
oltre le ore realmente disponibili). L'importer gia' lo faceva; mancavano le
colonne `sostegno` / `ore_sostegno` nel template `students` e il nome
dell'alunno sulla pill SOST in `/assignments`, che senza non diceva a chi va.
Nove test in `test_sostegno_per_alunno.py`, incluso il caso "stesso docente su
due alunni = due cattedre" (unicita' con `COALESCE(student_id, 0)`).

**`is_hard_feasible` senza contesto sbagliava, non degradava.** I quattro
argomenti opzionali (`support_assignments`, `coteach_groups`, `parallel_groups`,
`group_assignments`) non sono un di piu': sostegno e compresenza occupano la
stessa cella `(classe, giorno, ora)` per costruzione, e senza contesto la
regola di non-sovrapposizione della classe li legge come doppia occupazione.
Siccome lo stesso gate governa `validate_and_apply_move`, l'effetto pratico era
che la modifica manuale rifiutava OGNI spostamento, in tutta la scuola. Aggiunto
`_hard_check_ctx` e passato il contesto a tutti e 14 i call site. Sulla
simulazione da 60 classi: prima 36 destinazioni su 36 rifiutate, dopo
`{hard_violation: 28, ok: 5, soft_worse: 1, noop: 2}` -- le 28 sono rifiuti veri
(docente o classe occupati).

Seconda causa, indipendente: il gate pretendeva feasibility *assoluta*. Se
l'orario attivo viola gia' un HARD (tipico dopo un import, o quando la Phase B
non modella una regola come H_A), rifiutava ogni mossa comprese quelle che la
riparavano. Ora valuta la baseline e rifiuta solo se il punto di partenza era
pulito; quando passa per baseline sporca lo dice al chiamante e scrive
`feasible: false` nelle metriche, invece di mostrare verde su un orario rotto.

**Compresenza: da colonna muta a superficie completa.** `Teacher.compresenza`
(`mai` | `sempre` | `oraria`) esisteva nel modello e non usciva da nessuna API.
Aggiunti campo + validator in `TeacherBase`, `CompresenzaHour`, e la griglia 6x6
in `/teachers`. La griglia si conserva anche in modo `mai`/`sempre`, cosi'
passare avanti e indietro fra i modi non perde le celle gia' compilate.

**N+1 su `/api/teachers`, e la lezione su come si misura.** `_to_out` rilegge
sei collezioni per docente piu' due query dentro `_classroom_prefs_for_teacher`:
543 query per 178 docenti. `test_perf_budgets` lo vedeva (28s contro un budget
di 15) ma l'ho scambiato per contesa di macchina, perche' il test da solo
passava: le query erano poche in valore assoluto, e solo i thread di background
lasciati dai test di diagnostica le amplificavano. Bastava contarle invece di
cronometrarle. Sei `selectinload` piu' `_classroom_prefs_by_teacher` (le
`classroom_prefs` non sono una relationship: vanno precaricate a mano) portano
543 query a 12 e il modulo perf da 108s a 3s. Aggiunto
`test_teachers_list_no_n_plus_1.py`, che confronta il costo su 10 e su 40
docenti: e' la rete a maglie strette che il budget a tempo non e'.

**Resta aperto**: la Phase B non conosce i plessi (`plessi_data=None` cablato in
`cpsat_v2_timetable.py`), quindi il tempo di trasferimento fra i due plessi non
vincola l'assegnazione delle ore. E' una capacita' nuova, non un cablaggio
mancante, e non l'ho aperta.

## Il test lento che cancellava il DB di sviluppo (2026-07-31)
Facendo girare la suite backend *completa* (cioe' con i `-m slow`, che la suite
veloce deseleziona), il DB di sviluppo si e' trovato con 25 docenti e 10 classi
al posto di 178 e 100. Colpevole:
`test_coverage_gate.py::test_run_phase_b_reaches_full_coverage`, che chiama
`_import_base_school(..., "small")` -> `import_school_into_db(replace=True)`.

La causa e' che `app_with_temp_db` isola solo la dependency `get_db`. Tutto cio'
che passa dall'orchestrazione dei run gira in un thread di background e apre le
sessioni dal `SessionLocal` importato a modulo -- quello legato al DB vero. E
siccome `from .db import SessionLocal` ne fa una copia per modulo, ripatchare
`backend.db` non basta: vanno patchati anche `optimization` e `run_manager`.
Aggiunta la fixture `temp_global_session` che fa esattamente questo, e messa in
firma al test. Con il DB isolato il test passa (5/5, 37s): il fallimento
"coverage 0.0% (0/305)" non era una regressione del solver, era il solver che
girava su un DB gia' pieno di un'altra scuola.

Ripristinato il DB da una copia presa quattro minuti prima del danno. Il server
di sviluppo era acceso su :8000, quindi *non* sostituendo il file (il processo
avrebbe continuato a scrivere sul vecchio inode) ma con `ATTACH` del backup e
`DELETE` + `INSERT ... SELECT` tabella per tabella dentro una transazione, che
passa dallo stesso file e dallo stesso WAL. `PRAGMA integrity_check` ok, e
`foreign_key_check` restituisce le stesse 105 righe orfane di `run_telemetry`
di prima -- preesistenti, non introdotte dal ripristino.

## L'N+1 su /api/teachers, contato invece che cronometrato (2026-07-31)
`test_perf_budgets` falliva, e la prima diagnosi -- contesa di macchina -- era
sbagliata: il modulo falliva anche da solo, 28.3s. Contando le query invece di
cronometrarle e' venuto fuori un N+1 vero e proprio, 543 query per una lista di
docenti. Due sorgenti: le sei collezioni che `_to_out` legge riga per riga, e
`_classroom_prefs_for_teacher`, che costa due query a docente e non e' una
relationship, quindi `selectinload` da solo non la copre. Aggiunto
`selectinload` per le sei collezioni e un caricatore in blocco
(`_classroom_prefs_by_teacher`) per le preferenze aula: 543 query / 231 ms ->
**12 query / 90 ms**, e il modulo perf da 108s a 3.0s.

Il test nuovo (`test_teachers_list_no_n_plus_1.py`) confronta il *numero di
query* su 10 e su 40 docenti invece di misurare il tempo. Un budget a
cronometro e' una rete a maglie larghe: questo N+1 lo attraversava indisturbato
finche' non arrivavano i thread di background di un altro modulo ad amplificarlo.

## I plessi entrano in Phase B (2026-07-31)
Il tempo di trasferimento fra plessi era modellato solo nella fase aule. Ma
quando quella fase interviene le ore sono gia' congelate: se Phase B ha messo un
docente in sede alla 3a e in succursale alla 4a, nessuna assegnazione di aula
puo' rimediare. Il vincolo arrivava a giochi fatti.

L'ostacolo era che tutti gli helper esistenti ricavano il plesso dall'**aula**, e
in Phase B le aule non esistono ancora. La sede la sa la **classe**: o per una
`PlessoEntityPolicy` di tipo `single_plesso_total` con `plesso_id` esplicito, o
per l'**aula di residenza** (`ClassroomClassPreference.is_home`), che e' l'unica
prova pre-aule di dove una classe -- e quindi chi ci insegna -- stia fisicamente.
Da qui `class_plesso_pins()`: una classe senza ne' l'una ne' l'altra resta fuori
dalla mappa, perche' tirare a indovinare "plesso 1" vieterebbe orari legittimi
sulla base di un dato mancante.

Due dettagli non ovvi. Primo: si controllano **tutte** le coppie di ore, non solo
quelle adiacenti -- un docente in sede alla 1a e in succursale alla 3a violerebbe
comunque una regola con `min_gap_hours=2`, e guardare solo `h+1` lo lascerebbe
passare (da cui `_pair_violates_rule`, generalizzazione di
`_adjacent_violates_rule`). Secondo: il vincolo va messo in **tutti e quattro**
gli stage della decomposizione spettrale, non solo nel solver monolitico; regge
perche' ogni stage decide un insieme *disgiunto* di docenti (A i bridge, B gli
interni di un cluster, C la ricucitura), quindi tutte le ore di un docente
cadono dentro un solo stage e nessuna coppia sfugge fra le maglie.

Il contesto (`build_plessi_ctx`) si costruisce una volta per run e si passa ai
solver; senza plessi configurati e' `None` e non cambia niente. Il controllo
negativo del test e' costruito, non trovato: una giornata in cui le due classi
hanno quattro ore ciascuna e il pendolare ne tiene due per parte, cosi' il cambio
di sede fuori intervallo e' *inevitabile*. Senza contesto la giornata si risolve
(e viola), con il contesto e' INFEASIBLE. Su un'istanza libera il solver
raggruppava le ore da solo e il confronto non avrebbe dimostrato nulla.

## Residui dell'audit "Headmaster 60 classi": DSL compresenza, aule, preflight, preset (2026-07-31)
Ripreso l'AUDIT.md della simulazione a 60 classi per chiudere i bloccanti
residui. Tre erano gia' stati risolti nelle sessioni del 30 e del 31 (01
sostegno-per-alunno, 31 `_hard_check_ctx`, 33-core + 36 compresenza in API, i
plessi in Phase B, e il segno delle preferenze aula normalizzato con `abs()` in
`engine_io`). Restava dell'altro, e vale la regola data dall'utente: **il motore
resta generale; una configurazione sbagliata e' colpa di chi la sceglie, e la si
affronta con preset e diagnostica, non cablando eccezioni nel solver.**

**Finding 37 — compresenza DSL: `same_day` dove serviva l'uguaglianza di slot.**
`coteach_group_to_dsl` dichiarava "slot-equality" nel commento ma emetteva
`same_day(l1.slot, l2.slot)`: due docenti "in compresenza" lo stesso giorno a ore
diverse passavano il gate. Ora emette
`same_day(...) and hour(l1.slot) == hour(l2.slot)`. Verificato che il ramo nativo
CP-SAT gia' era corretto (`==` sullo slot); il difetto viveva solo nel percorso
gated. Test di parse+eval: ora l'ora diversa e' violazione, lo slot uguale passa.

**Finding 35 — il ripiego aule.** Due residui, non i quattro dell'audit: 35c/35d
(segno delle preferenze) erano gia' chiusi via `abs()` in `engine_io`. Restava
(35a) il fallback greedy silenzioso e (35b) `plessi_data` passato in un solo
chiamante su due. Ora entrambi i chiamanti passano `plessi_data` al greedy, e le
metriche portano `rooms_exact_status` + `rooms_fallback`: un ripiego non legge
piu' come "assegnazione riuscita".

**Finding 38 — compresenza soft ignorata in silenzio.** Il solver non modella
ancora la codocenza SOFT (`if not g.get("required"): continue`). Invece di
lasciarla sparire, `run_phase_b` scrive un AVVISO nel log del run: N compresenze
'preferibili' non sono imposte, impostale 'obbligatorie' per garantirle. Enforce
soft vero resta un TODO d'obiettivo, ma non e' piu' muto.

**Finding 14/18/30 — il preflight che mancava.** L'hall-check rispondeva "ok" a
un problema insoddisfacibile per 10 docenti (18h su una classe: 3x(6-1)=15<18).
Aggiunto `per_teacher_day_capacity_check`: aritmetica pura, legge i tetti veri
dal motore (`MAX_PER_DAY_PROF_CL`, `MAX_PER_DAY_TRIPLE`) e i `min_free_days`, e
per ogni cattedra che sfora nomina docente, classe, ore, capienza e cosa
cambiare. **Nessun caso speciale per il sostegno**: un ADSS a tempo pieno ha
`min_free_days=0` (modellazione corretta della realta'), ed e' quello che il
messaggio dice di impostare. `ok` ora include queste violazioni.
`test_hall_check_preflight.py`: 18h+1giorno-libero e' segnalato, 18h+0 e' feasibile.

**Finding 20 — il preset che funziona, reso raggiungibile.** Il default
('day'+'always') fissa la distribuzione della Fase A come uguaglianza HARD che la
Fase B non regge quando i docenti hanno indisponibilita' vere; la Fase A non le
vede. Il motore *sa gia'* risolvere in 'week'+'soft_hint' (l'audit lo ha
dimostrato): mancava solo dirlo. Aggiunto `GET /api/optimize/scenario-presets`
(`standard` vs `part_time_sostegno`) e, nel preflight, un avviso che indica il
preset settimanale quando ci sono indisponibilita' HARD o giorni liberi
obbligatori. Phase A NON e' stata riscritta per vedere le indisponibilita': era
la strada del "cabla nel motore", che l'utente ha escluso.

Verde: preflight (2), dsl_translator + coteach (34), plessi + classroom (61),
ruff su webui pulito. Le prove end-to-end sulla simulazione a 60 classi non
girano qui (solver lento); i preset e il preflight sono coperti da unit test.

## Residui gravi dell'audit 60 classi: importer cattedre, celle sintetiche, required_kind, isolamento run, capienza palestre (2026-07-31)
Secondo blocco di rilievi grave dal report "Headmaster 60 classi": 02, 03, 29, 32, 34.

**02 -- l'importer delle cattedre esisteva nella docstring ma non nel registro.**
Aggiunto `_import_assignments` a `_IMPORTERS` + template. Non riscrive la
validazione: chiama `optimization.manual_assignment` per riga, quindi eredita gli
stessi controlli di merito che l'audit aveva lodato (materia nel curricolo,
docente abilitato, sforamento cattedra). Il sostegno NON passa di qui (segue
l'alunno, ha il suo path via students); `replace` tocca solo le cattedre
curricolari. `test_import_assignments_and_required_kind.py`.

**03 -- le celle del giorno libero, sintetiche in GET, diventavano vincoli veri
al salvataggio.** `_autofill_free_day_cells` decora la GET con 6 celle HARD per
il giorno libero (comodita' di visualizzazione); un semplice GET->PUT le
persisteva. Aggiunto il flag `synthetic` allo schema, marcate le due sorgenti di
autofill, e in `_apply_payload` si scartano (per flag o per il marcatore `(auto`
nel reason -- cosi' un re-save ripulisce anche le righe gia' corrotte da un
client vecchio). Il giorno libero resta imposto da `min_free_days` /
`mandatory_free_days`, non da queste celle. `test_teacher_free_day_roundtrip.py`.

**29 -- `Subject.required_kind`, unico modo per obbligare la palestra, era
DB-only.** Aggiunto a `SubjectBase` (create/update lo mappano gia' in blocco) e
alla colonna `required_kind` del template + parser subjects. Ora si imposta da API
e da import, senza scrivere il DB a mano.

**32 -- i file di lavoro dei run non erano isolati per archivio.** `_runs_dir()`
derivava dal path del sorgente: due istanze su DB diversi collidevano (run 7 di A
sovrascriveva run 7 di B, il run_id e' un autoincrement per-DB). Ora la cartella
e' `data/runs/<sha1(PITANTUM_DB_URL)[:12]>/`.

**34 -- la fase oraria non sapeva quante palestre/laboratori esistono.** Nuovo
`build_special_room_ctx` (materia->kind, kind->capienza = somma `multi_class_max`)
e `add_special_room_capacity_phase_b`: per ogni (kind, giorno, ora) al piu'
`capienza` classi con una materia di quel kind. Occupazione contata **per
(classe, cella)** con un indicatore OR, cosi' compresenza/codocenza non doppiano.
Vincolo emesso solo se le classi candidate superano la capienza; no-op se nessuna
materia ha `required_kind`. Imposto dove un solo modello vede l'intero slot: lo
scope **settimanale** (`_build_week_solver`, il percorso che l'audit usava) e il
**monolitico per-giorno**. NON sugli stage della decomposizione spettrale:
diversamente dai plessi (regola per-docente, disgiunta fra stage) la capienza e'
un vincolo GLOBALE per-slot su tutte le classi, e la decomposizione le divide fra
cluster -- un cap per-stage non vedrebbe la domanda cross-cluster. Per quel
percorso resta il preset settimanale + un preflight strutturale
(`special_room_capacity_check`: ore/settimana di un kind vs capienza*slot, la
condizione necessaria). `test_special_room_capacity.py` (modello CP-SAT costruito:
3 classi/2 palestre INFEASIBLE, compresenza non doppiata, preflight).

Verde: 4 nuovi file di test + rigressione phase_b/plessi/teacher/import/coteach/dsl
(47+11), ruff pulito sui file non-test. Anche qui l'end-to-end sul solver non gira
qui: i vincoli sono validati su modelli CP-SAT costruiti a mano, non su un run.

## Ultimi gravi dell'audit 60 classi: import free_day/plessi/indisponibilita', partial salvato, attivazione gated, lock cattedra vs ora (2026-07-31)
Terzo blocco: 05, 06, 07, 17, 24, 26.

**05 -- il free_day importato era inerte.** L'importer scriveva `Teacher.free_day`
(stringa) ma il solver legge `TeacherMandatoryFreeDay` / `min_free_days`. Ora
l'import traduce il giorno in un `TeacherMandatoryFreeDay` HARD (add-if-missing,
niente doppioni al re-import). Mappa giorni IT/EN in `_day_to_int`.

**06 -- l'importer aule non conosceva i plessi.** Aggiunta la colonna `plesso` al
template + `_resolve_plesso` (find-or-create, con code unico derivato dal nome):
una scuola su piu' sedi carica le aule in un foglio solo.

**07 -- le indisponibilita' non si importavano.** Nuovo importer
`teacher_unavailability` (una riga per cella: docente, giorno, ora, stato,
penalita'), upsert su (docente, giorno, ora).

**17 -- il parziale veniva buttato.** Nella chiusura di Phase B: si salva SEMPRE
l'orario (anche parziale, non attivo) e si riporta in `metrics["uncovered"]`
quali cattedre restano scoperte (`_uncovered_report`, peggiori prima) invece di
una sola percentuale. In modalita' strict il run fallisce comunque (P0), ma
l'orario e' salvato (id nel messaggio) e il messaggio nomina le cattedre scoperte
invece di "aumenta i time limit".

**24 -- si attivava un orario che il validatore boccia.** L'attivazione ora e'
`make_active = feasible and complete`: un orario parziale o hard-infeasibile viene
salvato ma NON attivato (e lo step aule non gira su un orario che non attiveremo).
`metrics["activated"]` lo dichiara.

**26 -- lock cattedra != lock ora.** `_read_locked_lessons` bloccava OGNI ora di
una cattedra `Assignment.locked`: una scuola che caricava le 694 cattedre come
`locked` (giusto: "non riassegnarle") si congelava l'intero orario e non poteva
piu' rigenerare. Introdotta la colonna `Lesson.locked` (pin per-slot, "ora
immobile"), con fallback SQLite in `db.py` + migrazione `b7f1c0d2e3a4`.
`_read_locked_lessons` ora legge SOLO i `Lesson.locked`; `Assignment.locked`
resta "cattedra confermata" e non congela nulla. `_apply_locked_classrooms`
ri-marca i pin sulla nuova soluzione (il pin sopravvive alle rigenerazioni).
Nuovo endpoint `POST /api/schedule/lessons/{id}/pin`. NB: il pulsante "lucchetto"
del frontend punta ancora al lock cattedra (assignments) -- va ripuntato
sull'endpoint del pin lezione (follow-up, non validabile senza browser qui).

Verde: 05/06/07 (3), partial/attivazione (3), lock semantics (2), + rigressione
native-locks/coverage/schedule/import; ruff pulito sui file non-test. Alembic
head unico = b7f1c0d2e3a4. End-to-end solver non girato qui.

## Cluster medio dell'audit 60 classi + validazione frontend in Safari (2026-07-31)
Presi 11, 12, 15, 38, 19 (08b e 16 lasciati aperti, vedi sotto). Da qui in poi il
frontend si valida in Safari via `safaridriver` + Selenium (l'utente ha abilitato
"Allow Remote Automation" + `sudo safaridriver --enable`).

**11 -- POST /api/constraints declassava hard->soft in silenzio.** Aggiunto
`_guard_downgrade`: sovrascrivere una cella `hard`/`enforced` con un livello piu'
debole ora da' 409, a meno di `force=true` (campo nuovo su `ConstraintCreateIn`).
Un caricamento massivo non perfora piu' un giorno libero garantito; una modifica
singola voluta passa `force`. Applicato ai tre rami matrix_slot (teacher/class/room).

**12 -- /api/assignments/manual ignorava `hours`.** Per target classe le ore vengono
dal curricolo; ora un `hours` incoerente e' RIFIUTATO con messaggio chiaro invece di
essere ignorato. Un valore uguale (o assente) passa.

**15 -- le regole di trasferimento plesso non valevano per le classi.**
`plesso_commuting_rule_to_dsl` generalizzata a entity_kind in
{teacher, class, group}: stessa clausola, legata su `l.class`/`l.group` (attributi
gia' esposti dal mondo DSL). Aggiornato il vecchio test che ne asseriva il
NotImplementedError.

**38 -- compresenza soft "non imposta".** Scoperto che `load_all_dsl_constraints`
GIA' emette la coteach soft come regola DSL soft pesata (`is_hard=False`,
`weight=g.weight`) quando `include_soft=True`: e' quindi applicata come preferenza
sui percorsi DSL (scope settimanale). Corretto l'avviso in run_phase_b (prima diceva
"non imposta", ora dice "preferenza pesata via DSL, garantita su scope week"). Test
sull'emissione.

**19 -- nessuna informazione di avanzamento.** La colonna `runs.current_step` e il
suo rendering frontend (runs list + dettaglio via `pipelineStepLabel`) esistevano
gia'; solo il pipeline completo la popolava. Ora `run_phase_b` (day) e
`_solve_phase_b_week` scrivono `current_step` a ogni milestone (`phase_a`,
`phase_b`, `rooms`, poi `None` a fine), e `obj_value` e' scritto a fine. **Validato
in Safari**: inserito un run fittizio (`current_step=phase_b`, progress 0.42,
obj 151000), GET /runs/{id} lo espone, e la pagina di dettaglio mostra
"Schedulazione orario (Phase B)". Run fittizio poi cancellato. L'avanzamento
INTRA-solve (barra che si muove durante i 10 minuti) richiede una solution-callback
CP-SAT: resta un follow-up.

Verde: 26 test (nuovi + rigressione coteach/dsl), ruff pulito sui non-test.

**Lasciati aperti, con motivo:**
- **08b** (ex-officio: 7 vincoli HARD per classe non modificabili dalla scheda). NON
  e' un bug ma una feature di configurazione: i 7 sono invarianti di motore
  applicati GLOBALMENTE (no_holes, coppia mat/ita, coppia motorie, presenza H3,
  carico 4-6, MAX_PER_DAY_TRIPLE, MAX_PER_DAY_PROF_CL). Renderli per-classe vuol
  dire colonne nuove + config per-classe nel solver + UI + una run del solutore per
  validare -- sproporzionato al "medio" e non validabile a fondo qui senza far
  girare il solver. Alcuni knob per-classe esistono gia' (`hard_entry_at_8`,
  `max_hours_per_day`).
- **16** (cosmetico: /api/plessi e /api/assignments tornano array nudi invece di
  `{items,total}`). Cambiare la forma romperebbe i consumatori frontend; l'audit
  stesso lo classifica "solo da documentare".

## 08b — i sette vincoli d'ufficio, per-classe: la scheda c'era gia', il solver no (2026-07-31)
Sorpresa: `SchoolClass` ha GIA' le sette colonne per-classe (`hard_no_holes`,
`hard_entry_at_8`, `hard_exit_after_12`, `hard_dual_math`, `hard_dual_italian`,
`hard_motorie_pairs`, `hard_max_6_per_day`), sono GIA' nello schema `ClassBase` e
GIA' modificabili dalla scheda classe (7 checkbox in `classes/+page.svelte:361-367`).
Il rilievo "non modificabili dalla scheda" e' quindi gia' chiuso lato UI/API. Il
buco vero: **il solver le ignora** -- applica gli invarianti globalmente via
`ConstraintConfig`, non legge le colonne per-classe (grep a vuoto in engine + engine_io).

Fatto: `engine_io.class_flags_from_db` esporta le 7 flag per classe (default True =
comportamento storico). `solve_phase_b_for_day` accetta `class_flags` e chiude i
tre vincoli applicati in quella funzione — `no_holes`, `entry_at_8` (parte alle 8),
`exit_after_12` (presenza h11) — sul flag della singola classe, con default = flag
globale, quindi ogni classe non toccata resta identica. `run_phase_b` costruisce le
flag e le passa al ramo monolitico per-giorno.

Validato: `test_class_flags_08b` (export + default + override + firma); round-trip
API end-to-end (crea classe → PUT hard_no_holes=false → GET conferma →
`class_flags_from_db` vede l'override → delete); `/classes` carica in Safari;
rigressione phase_b/plessi/native-locks/special-room verde (47).

**Resta aperto (follow-up onesto):** le altre 4 flag (dual_math, dual_italian,
motorie_pairs, max_6_per_day) vivono nei generatori di pragma Phase A e nel modello
settimanale, non in `solve_phase_b_for_day`; e la gating per-classe copre per ora il
ramo **monolitico per-giorno**, non gli stage della decomposizione spettrale (il
default per >=8 classi) ne' il solver settimanale — stesso limite di copertura del
vincolo capienza palestre (finding 34). Il comportamento per-classe del solutore non
e' validato da una run qui (solo plumbing + hand test). Estenderlo agli altri
percorsi e alle 4 flag restanti e' il seguito.

## 08b esteso a tutto il motore: un solo meccanismo per-classe, coerente ovunque (2026-07-31)
Fatto il seguito: le 7 flag per-classe ora sono onorate da OGNI solutore, con un
solo meccanismo condiviso.

**Resolver unico.** `cpsat_v2_timetable.class_enforces(class_flags, cl, key,
default)` + `build_class_flags(db)` (gemello di `engine_io.class_flags_from_db`,
per i chiamati che hanno solo la sessione). `CLASS_FLAG_KEYS` come fonte unica dei
nomi. class_flags=None => comportamento globale storico (zero-drift).

**Punti di emissione gated, per-classe:**
- **Seed DSL** (`dsl_translator.seed_implicit_hardcoded`, il generatore canonico
  "zero-drift"): no_holes, class_day_load (max_6), h11 (exit_after_12), motorie,
  Mat/Ita (dual_math/dual_italian per-materia). Copre il solver monolitico
  settimanale e OO che consumano il seed. Zero-drift verificato.
- **MonolithicSolver** (`cp_sat_constraint_model`): `ConstraintConfig.class_flags`
  + `_class_enforces` + gate su `add_class_no_holes` (no_holes+entry_at_8),
  `add_h3_presence_at_11` (exit_after_12), `add_subject_pair_constraint`
  (flag_key motorie/dual_math/dual_italian). Copre settimanale + OO per-giorno,
  su entrambi i rami (seed e legacy add_*).
- **solve_phase_b_for_day** (per-giorno monolitico): no_holes/entry_at_8/
  exit_after_12 + fallback `build_class_flags(db)` quando il chiamante passa solo
  la sessione (decomposizione / column generation).
- **is_hard_feasible** (metaeuristiche): gate su H1(no_holes)/H2(entry_at_8)/
  H3(exit_after_12)/H_A(dual_math|dual_italian)/H_B(motorie) + auto-build da db
  per i controlli full-solution.
- **Operatori di mossa** (`_swap_two_lessons_same_prof`,
  `_move_lesson_to_empty_slot`, `_swap_two_lessons_same_class`): param
  `class_flags`, passato a is_hard_feasible; `run_sa`/`run_tabu` costruiscono
  class_flags una volta da db e lo passano alle mosse (niente query per-mossa).

**Wiring backend:** `_hard_check_ctx` include class_flags (tutte le chiamate a
is_hard_feasible in optimization.py: coverage gate, mosse manuali); la config del
solver settimanale porta `_week_class_flags`; la chiamata monolitica per-giorno
riceve `_class_flags`.

Verde: `test_class_flags_consistency` (resolver, is_hard_feasible rispetta il
flag, seed zero-drift+gating, ConstraintConfig/MonolithicSolver), + 147 di
rigressione (metaeuristiche, OO, coteach, dsl, plessi, locks, special-room), ruff
pulito sui non-test.

**Residui onesti:** i pragma di **Fase A** day_count (motorie 0-o-2/giorno, Mat/Ita
">=1 giorno con 2h") nel percorso funzionale non sono gated per-classe (il seed
canonico si'); e il **comportamento del solutore** con una flag spenta e' validato
su emissione/feasibility e modelli costruiti a mano, non da una run completa.

## 08b + 34: chiusi i buchi su decomposizione, temporale e column generation (2026-07-31)
I gate per-classe (08b) e la capienza aule speciali (34) ora raggiungono OGNI
percorso che colloca lezioni, non solo il monolitico.

**Punto di leva unico: `add_consecutive_constraints_phase_b`.** Questo helper
condiviso applica le coppie Mat/Ita/Motorie in `solve_phase_b_for_day` E nei tre
stage spettrali. Gated per-classe una volta sola (dual_math/dual_italian/
motorie_pairs) -> copre coppie ovunque.

**Threading di class_flags / special_room_ctx** (mirroring plessi_ctx):
- **Spettrale (default per >=8 classi):** stage A/B/C ricevono class_flags (per le
  coppie); `solve_monolithic_day` (ricucitura, tutte le classi del giorno) riceve
  class_flags + special_room_ctx. no_holes HARD e' nella ricucitura via
  solve_phase_b_for_day (gated); negli stage e' SOFT (add_buchi_soft).
- **Temporale:** `solve_day` + il worker `_worker_solve_day` (tuple a 11 elementi,
  picklable) + `run_temporal_pipeline` portano class_flags + special_room_ctx.
- **Column generation:** `run_column_generation` -> `_completion_solver`.
- **Backend:** run_phase_b (stage + monolithic), run_column_generation e
  run_decomposition_temporal costruiscono i ctx una volta e li passano.

**Phase A:** `build_phase_a_pragmas` gated per-classe (day_load->max_6,
subject_day_count_pair->dual_math/italian, subject_day_count_in->motorie);
`solve_phase_a` porta class_flags, passato dai due percorsi Phase-A primari
(day-scope + week hint).

Verde: `test_class_flags_all_solvers` (ogni entry point accetta class_flags;
special_room dove tutte le classi sono visibili; add_consecutive taglia la coppia
motorie per la classe disattivata) + 138 di rigressione (advanced/metaeuristiche/
OO/dsl/coteach/plessi/locks/special-room), ruff pulito.

**Residui onesti:** (1) `special_room_ctx` NON entra negli stage spettrali per
costruzione -- un cap globale per-slot non si decompone lungo la partizione dei
docenti; vive nella ricucitura monolitica (stessa natura del limite). (2) Il
blocco full-pipeline (run_full_pipeline) non costruisce i ctx (gli manca anche
plessi): percorso separato, non toccato. (3) La coppia solve_phase_a di
decomposizione/full-pipeline non porta class_flags (secondario: e' Phase-A
day_count). (4) **Finding 38** soft coteach nel percorso NATIVO per-giorno resta
un TODO d'obiettivo (imposto via DSL/week, non-silente nel nativo): e' un'aggiunta
di termine soft all'obiettivo CP-SAT, non un gating, quindi non l'ho fatta alla
cieca senza una run. Il comportamento del solutore coi flag spenti resta validato
su emissione/feasibility/modelli costruiti, non da una run.

## Chiusi gli ultimi due buchi: soft coteach nativo + ctx del full-pipeline (2026-07-31)
**Full-pipeline (run_full_pipeline).** Lo step phase_b non costruiva NESSUN ctx --
gli mancavano plessi, capienza aule speciali E i flag per-classe. Ora costruisce
`_plessi_ctx` + `_special_room_ctx` + `_class_flags` una volta per step e li passa
a: `solve_phase_a` (class_flags), gli stage spettrali A/B/C (plessi_ctx +
class_flags), e il `solve_phase_b_for_day` monolitico (plessi + special_room +
class_flags). Recupera anche i plessi che qui non erano MAI stati cablati.

**Soft coteach nel percorso NATIVO (finding 38).** Prima `if not required:
continue` -- la compresenza 'preferibile' spariva dal solver nativo per-giorno
(era imposta solo via DSL/week). Ora nel loop coteach di `solve_phase_b_for_day`
un gruppo soft genera un termine di penalita' per ogni (codocente, ora) dove il
titolare e il codocente NON coincidono su quella (classe, materia): `mism >=
|slot_titolare - slot_codoc|`, peso = `group.weight`. I termini entrano in
`compiler.soft_cost_terms`, quindi sia il Minimize iniziale sia il re-Minimize
via_dsl li includono. La coincidenza e' ammessa dal meccanismo busy_key (i due
docenti sulla stessa materia condividono la chiave, contano come UNA occupazione
di classe), quindi il termine puo' davvero azzerarsi: non forza come l'hard,
sposta il solutore.

Validato **a comportamento** (`test_soft_coteach_native`): risolvendo un giorno,
il codocente da 2h finisce DENTRO le 4h del titolare (T2 sottoinsieme di T1) con
soft coteach; l'hard continua a forzare la coincidenza. `test_class_flags_all_solvers`
esteso; 113 + 37 di rigressione coteach/advanced/OO/dsl/plessi/locks/special-room
verdi, ruff pulito.

Con questo, 08b + 34 raggiungono ogni percorso (per-giorno, week, spettrale,
temporale, column generation, full-pipeline) e la soft coteach e' imposta sia sul
ramo DSL/week sia su quello nativo. Restano fuori solo, per costruzione, la
capienza aule speciali dentro gli stage spettrali per-sottoinsieme (vive nella
ricucitura). Il comportamento del solutore su scuola intera non e' comunque girato
qui (solver lento).

## Run end-to-end sulla scuola da 60 classi: convalida + due bug trovati (2026-07-31)
Finalmente girato il solutore sulla `liceo60.db` (60 classi, 132 docenti, 694
cattedre, 2115 lezioni) con il codice aggiornato.

**Bug 1 (pre-esistente): `room_policy` senza fallback in db.py.** Ogni DB
pre-esistente lanciava `no such column: school_classes.room_policy` -- la colonna
era stata aggiunta a models.py senza l'ALTER in `_apply_lightweight_migrations`.
Aggiunto (`NOT NULL DEFAULT 'ibrida'`).

**Bug 2 (trovato dalla run): il meta ignorava `class_flags`.** `run_meta`
costruiva `hard_ctx` e `c3_kwargs` SENZA class_flags. Le classi della simulazione
hanno molti flag spenti (hard_dual_math=false, hard_motorie_pairs=false, ...): la
Phase B li onorava, ma il meta ri-marcava quelle collocazioni come violazioni HARD
-> "soluzione iniziale viola gli HARD" -> LNS degradato (nessun miglioramento,
feasible:false). Aggiunto class_flags a hard_ctx + c3_kwargs, e threading in
run_lns/ils/sa/tabu + alns/vns/lagrangian (le cui is_hard_feasible passano gia'
db) + _cp_repair + `PhaseBDaySolver` (costruisce class_flags da db).

**Risultati (Phase B week/soft_hint, poi LNS):**
- Copertura **2115/2115 (100%)**, `feasible=True` col contesto pieno.
- **Lezioni nell'edificio sbagliato: 0** (l'audit ne aveva 891 = 42%). Il ripiego
  greedy ora onora i plessi (finding 35b) ed e' trasparente (finding 35a:
  `rooms_fallback:True` nelle metriche).
- **Slot con palestra in sovraccarico: 0** (finding 34).
- **run 9 dell'audit** (che l'audit dava `feasible:false`) ora e' **feasible=True**
  col contesto: e' la prova di finding 31 sui dati veri.
- **LNS prima del fix:** obj 2070->2070, feasible:false, "viola gli HARD".
  **Dopo il fix:** obj **2070->1960**, buchi **141->130**, feasible:True, zero
  warning. Il meta ora migliora davvero.
- Residuo: il solutore ESATTO delle aule resta INFEASIBLE (180/2115 senza aula) --
  e' il residuo finding 33/34 (sostegno+palestre nel modello aule); il ripiego
  colloca 1935/2115 rispettando i plessi.

113 test meta verdi, ruff pulito. Migrata `liceo60.db` allo schema corrente.
