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
    LP-bound pruning, depth + node caps.
  - **Box-step dual stabilization** to smooth oscillating duals.
  - **Column management** with reduced-cost-age purge (default
    pool cap 10K columns, EWMA over 20 iterations).
  - **Parallel pricing** via `ProcessPoolExecutor` (default
    `cpu_count() // 2` workers).
- `metaheuristics.py`, `alns.py`, `vns.py`, `lagrangian.py`:
  post-processing on a HARD-feasible seed solution.

For the long-form description of every component see the
LaTeX manual; this Markdown file stays terse and in English so
it can be linked directly from PR reviews and code-search
results.

---

> **Note**: this document is now English-only. The full
> long-form Italian description that previously lived after this
> separator has moved to the LaTeX manual under
> `docs/manual/chapters/` (see `architettura.tex`,
> `api_rest.tex`, `modello_dati.tex`, etc.). Build the
> manual with `docs/build_manual.sh` to obtain
> `manual.pdf` (Italian) and `manual_en.pdf` (English).
