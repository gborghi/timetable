# Architecture (English summary)

piTantum is a three-tier system: a CP-SAT solver core
(`engine/`), a FastAPI + SQLite backend (`webui/backend/`), and
a SvelteKit frontend (`webui/frontend/`). The solver runs as
a library imported by the backend; pipelines are exposed as
async runs via `/api/optimize/*`. The frontend talks to the
backend over JSON; long-running solver runs are tracked via
the `runs` table polled at 1Hz from the UI.

Solver pipelines (in `engine/`):
- `cpsat_v2_assignment.py`: Phase A (teacher → class
  assignment).
- `cpsat_v2_timetable.py`: Phase A (timetabling, day_count) +
  Phase B (per-day slot placement). Native locks + C1/C2/C3
  constraints.
- `cp_sat_constraint_model.py`: OO catalogue.
  `MonolithicSolver` and `PhaseBDaySolver` (Step 4) wrap the
  legacy paths and accept `via_dsl=True` for DSL-augmented
  models.
- `decomposition_temporal.py`: 6-day parallel decomposition.
- `decomposition_spectral_v2.py` (+ curriculum/metis): cluster
  classes, solve sub-problems, ricucitura.
- `column_generation.py`: master LP + diversified pattern
  enrichment + completion fallback. `mode="branch-and-price"`
  is fully wired with all scalability techniques:
  - **9 CP-SAT pricers** at granularities `teacher`,
    `teacher-day`, `teacher-class`, `teacher-class-subject`,
    `teacher-subject`, `class`, `class-day`, `day`, `curriculum`.
    Each pricer is the FUNDAMENTAL minimisation; greedy supplies
    a `model.add_hint` warm-start only.
  - **Two master LPs**: variant 1 (per-teacher equality, used for
    `teacher-*` granularities) and variant 2 (Dantzig-Wolfe with
    cover + class-overlap + teacher-overlap inequalities, used
    for `class-*`, `day`, `curriculum`).
  - **Ryan-Foster recursive tree** with Achterberg pair score and
    LP-bound pruning, depth + node caps. Step 4 adds
    pricing-in-nodes (CP-SAT re-solved per node with branch
    decisions applied).
  - **Box-step dual stabilization** to smooth oscillating duals.
  - **Column management** with reduced-cost-age purge (default
    pool cap 10K columns, EWMA over 20 iterations).
  - **Parallel pricing** via `ProcessPoolExecutor` (default
    `cpu_count() // 2` workers).
- `dsl_to_cpsat.py` (Step 1+): generic DSL → CP-SAT compiler.
  Same parser/AST as the post-hoc evaluator, single backend
  used by Mono / PhaseB / pricers / RF nodes.
- `dsl_translator.py` (Step 2/3): unified translator from
  special-purpose constraint tables (TeacherUnavailability,
  CoteachGroup, PlessoCommutingRule, etc.) to canonical DSL
  strings. Includes `seed_implicit_hardcoded(profs)` (Step
  3d-3e) which emits the legacy hardcoded HARDs as DSL with
  bit-for-bit zero-drift.
- `metaheuristics.py`, `alns.py`, `vns.py`, `lagrangian.py`:
  post-processing on a HARD-feasible seed solution.

## DSL → CP-SAT layered architecture

After Steps 1–4 of the multi-day plan, every constraint
source funnels through one parser, one AST, and one compiler:

```
UI → POST /api/constraints/general
                │
DB tables ──→ dsl_translator ──→ canonical DSL strings
                                       │
                                       v
                            general_dsl.parse() (AST)
                                       │
                                       v
                       DSLConstraintCompiler.compile()
                                       │
              ┌────────────┬───────────┼───────────┬──────────┐
              v            v           v           v          v
          Mono          PhaseB     BP pricer   RF nodes   post-hoc
          Solver        DaySolver  (9 grans)              evaluator
          + DSL seed    + DSL aug                         (HARD/SOFT
                                                           score)
```

Properties:
- **One compiler**: same constraint emission for every solver
  surface — Mono, Phase B per-day, BP pricers, RF tree nodes,
  post-hoc evaluator.
- **Zero-drift**: legacy hardcoded HARDs round-trip through DSL
  identically (regression-tested).
- **HARD up-front, SOFT post-hoc**: HARD DSL clauses become
  CP-SAT constraints before solve; SOFT DSL clauses are
  evaluated post-hoc and contribute to the global score (CP-SAT
  objective wiring is planned for upcoming steps).

Canonical-pattern pragmas recognised by the compiler:
`no_holes_class`, `class_present_at_hour`, `class_day_load_in`,
`teacher_max_per_day`, `cattedra_max_per_day`,
`subject_pair_must`, `subject_pair_exists`,
`l.classroom.plesso` paths, `consecutive(s1, s2)`,
`same_day(s1, s2)`.

For the long-form description of every component see the
LaTeX manual; this Markdown file stays terse and in English so
it can be linked directly from PR reviews and code-search
results. The Italian summary lives in `architecture_it.md`.

---

> **Note**: this document is the English-language summary. The
> Italian summary lives in `architecture_it.md`. The full
> long-form Italian description is in the LaTeX manual under
> `docs/manual/chapters/` (see `architettura.tex`,
> `api_rest.tex`, `modello_dati.tex`, etc.). Build the
> manual with `docs/build_manual.sh` to obtain
> `manual.pdf` (Italian) and `manual_en.pdf` (English).
