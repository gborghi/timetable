# REST API (English summary)

All UI actions are mediated by REST endpoints under `/api/...`.
Major resource families:

- `/api/teachers`, `/api/classes`, `/api/classrooms`,
  `/api/subjects`, `/api/curricula`, `/api/students`,
  `/api/groups` -- CRUD on the entities the solver consumes.
- `/api/assignments` -- read + manual edit of the teacher →
  class cattedra; lock toggles (`/lock/<id>`).
- `/api/optimize/*` -- async solver pipelines: `assignment`
  (Phase A), `phase-b`, `decomposition/<method>`, `meta/<stage>`,
  `cg`, `place-event`, `full-pipeline`. Each returns a `run_id`
  to poll via `/api/optimize/runs/<id>`.
  - `POST /api/optimize/column-generation` -- async, body
    `{time_budget_s, patterns_per_teacher, mode, granularity,
     branching_strategy, max_iterations, bp_max_iterations,
     pricer_time_limit, pricer_workers, parallel, log}`.
    - `mode`: `iterative-diversified` (default) |
      `branch-and-price` | `auto`.
    - `granularity` (per BP): `auto` | `teacher` |
      `teacher-day` | `teacher-class` |
      `teacher-class-subject` | `teacher-subject` | `class` |
      `class-day` | `day` | `curriculum`. Each has a dedicated
      CP-SAT pricer (CP-SAT is the fundamental minimisation;
      greedy supplies a `model.add_hint` warm-start only).
    - `branching_strategy`: `ryan_foster` (full recursive
      tree with Achterberg pair score, LP-bound prune,
      `max_depth=20` / `max_nodes=1000`) | `variable`
      (no-op placeholder).
    - `bp_max_iterations` (default 8): cap on master+pricing
      rounds.
    - `pricer_time_limit` (default 5.0s): per CP-SAT
      sub-problem.
    - `pricer_workers` (default 2): CP-SAT search workers
      per sub-problem.
    - Python-only knobs (not yet in the UI): `dual_stabilization`
      (default True), `dual_step_alpha` (0.2),
      `max_active_columns` (10000), `rc_smoothing_horizon` (20),
      `parallel_workers` (auto = `cpu_count() // 2`),
      `class_to_curriculum`.
- `/api/monitor/*` -- event-row listings powering the /monitor
  UI (event-rows, summary, conflicts).
- `/api/bulk/events/{dry-run,apply}` -- bulk operations from
  /monitor (set_classroom, clear_classroom, set_lock).
- `/api/dataset/{state,clear,mock,import-profile,upload-pickle}`
  -- data lifecycle.
- `/api/diagnostics/*` -- async statistics (montecarlo,
  bipartite, correlations, distributions).
- `/api/health` -- liveness probe (200 OK + version).

Schemas: `webui/backend/schemas.py` (Pydantic v2). OpenAPI JSON:
`GET /openapi.json`.


---

> **Note**: this document is now English-only. The full
> long-form Italian description that previously lived after this
> separator has moved to the LaTeX manual under
> `docs/manual/chapters/` (see `architettura.tex`,
> `api_rest.tex`, `modello_dati.tex`, etc.). Build the
> manual with `docs/build_manual.sh` to obtain
> `manual.pdf` (Italian) and `manual_en.pdf` (English).
