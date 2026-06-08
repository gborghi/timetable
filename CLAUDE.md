# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**piTantum** (alias *Tempus Tantum*) generates and manages the weekly timetable of an
Italian high school. Three layers in one repo:

1. **`engine/`** — the solver. A two-phase CP-SAT pipeline (Google OR-Tools) plus
   decomposition strategies (temporal / spectral / curriculum / metis / column
   generation) and metaheuristic post-processors (LNS, SA, TS, ILS, ALNS, VNS,
   Lagrangian). Flat top-level modules, imported by the backend.
2. **`webui/backend/`** — FastAPI over SQLite (SQLAlchemy + Alembic). Owns the rich
   data model, drives the solver, streams run logs over SSE.
3. **`webui/frontend/`** — SvelteKit (Svelte 5 runes) + Tailwind + TanStack Query,
   built static via `adapter-static`.

`schedule/` holds the original single-file prototypes the engine evolved from — kept
for reference, **never modified** by engine code. `proposals/`, `docs/` are docs.

## Commands

All Python commands run from **`webui/`** with the three import roots on `PYTHONPATH`.

### Run the app (dev)
```
# Windows one-shot (two cmd windows, backend :8000 + frontend :5173):
webui\start.bat
# Manual backend:
webui\backend\.venv\Scripts\python -m uvicorn backend.main:app --reload --port 8000   # run from webui/
# Manual frontend:
cd webui/frontend && npm run dev
```

### Backend tests (pytest)
```
# from webui/  — PYTHONPATH must include webui + engine + schedule:
$env:PYTHONPATH = "$PWD;$PWD\..\engine;$PWD\..\schedule"   # PowerShell
pytest backend/tests -m "not slow" -q          # fast suite (CI default)
pytest backend/tests -m slow                   # full CP-SAT pipeline tests (opt-in)
pytest backend/tests/test_foo.py::test_bar     # single test
```
The `slow` marker gates anything that invokes the real solver. Root `pyproject.toml`
mirrors `webui/backend/pytest.ini` so a bare `pytest` at repo root also finds the
backend suite. There is also a top-level `tests/` dir (constraint unit tests +
`tests/benchmarks/`) run directly.

### Lint
```
ruff check webui/        # the ONLY linted tree
```
`engine/`, `schedule/`, `proposals/`, `tests/`, `webui/frontend/`, and Alembic
versions are **excluded by design** (intentional star-imports / numpy-flavoured
legacy style). Ruleset is `F` + `S` only; many `S*` checks are carved out — see the
`pyproject.toml` comments before "fixing" a finding it already ignores.

### Frontend
```
cd webui/frontend
npm run check          # svelte-kit sync + svelte-check (CI gate)
npm test               # node:test unit suite (constraint_levels + calendar_layout)
npm run build          # vite build (CI gate)
npm run test:e2e       # Cypress (alias for test:e2e:cypress); Playwright also present
```

### Docs / manual
The LaTeX manual (`docs/manual.pdf` IT, `docs/manual_en.pdf` EN) is rebuilt by a
**pre-push git hook** (`.githooks/pre-push`) whenever `docs/**.tex` or `docs/**.md`
change. Install once: `git config core.hooksPath .githooks`. Skip a single push with
`PITANTUM_SKIP_PDF=1 git push`. Build manually via `docs/build_manual.sh|.bat`;
audit dangling refs with `scripts/check_refs.sh`.

## Architecture notes (the non-obvious wiring)

**Import-path injection.** `webui/backend/engine_paths.py` prepends `engine/` and
`schedule/` to `sys.path` so engine modules import as flat names (`import alns`,
not `engine.alns`). `optimization.py` imports `engine_paths` **before** any engine
module — keep that ordering. CI replicates it via `PYTHONPATH`.

**DB ⇄ engine conversion.** The SQLAlchemy model (`models.py`) is the rich source of
truth and deliberately encodes more constraints than the solver honors (the extra
ones are enforced live during drag-and-drop instead). `engine_io.py` down-converts
DB state into three slim pickle shapes the engine consumes:
- `school` = classes + teachers + scoring tables
- `profs`  = per-teacher class/subject assignment + free days (`glibero`)
- `solution` = `{(prof, class, subj, day, hour): 0|1}`

Canonical demo data is now a per-profile SQLite snapshot under
`engine/scripts/data/<profile>/<profile>.sqlite` (built by `engine.scripts.build_profile_db`);
the old `.pkl` path is a fallback (see `PICKLE_DEPRECATED.md` markers).

**Run orchestration.** `optimization.py` exposes high-level steps (mock-gen →
assignment → timetable → post-process); each returns a `run_id` and executes in a
worker thread via `run_manager.py`. Threads (not processes) because the work is
CPU-bound OR-Tools/numpy — they give cooperative cancel + live stdout capture for
SSE streaming, not true parallelism. `run_manager` batches log writes through a
daemon writer thread and reaps stale buffers (don't reintroduce per-line `SessionLocal`
+ `COUNT(*)`).

**Locks are hard constraints.** Every locked `Lesson` propagates as a CP-SAT hard
constraint across all solver pipelines and post-processors. Touching constraint
modeling means touching all of them consistently.

**Frontend ↔ backend.** Each `webui/frontend/src/routes/<page>` maps to a backend
router in `webui/backend/routers/<page>.py`. `src/lib/api.ts` is the client;
`pipeline_labels.js` / `constraint_levels.ts` mirror engine vocabulary. The
`/schedule` page is a drag-and-drop `WeeklyCalendarView` with soft-conflict preview;
`/ore` edits the school week and propagates live via `workingHoursStore`.

## Conventions

- **Branch hygiene:** only `main` may exist on `origin`. Cherry-pick work onto `main`
  and delete any service branch before pushing. (Do not push feature branches.)
- Multi-tenant: models carry `TenantMixin`; respect tenant scoping in queries.
- Backend API key + CORS fail-fast only in prod (`PITANTUM_ENV=prod`); dev defaults
  to localhost-permissive.

## Engine pipeline-selection map

The solver is a **two-phase pipeline** wrapped by entry points in `optimization.py`,
each spawning a `Run`. The canonical chain:

```
mock/import → assignment (Phase A: prof→class cattedre) → timetable (Phase B) → [metaheuristics] → [rooms]
   ↑ run_mock_generation / imports     ↑ run_assignment        ↑ run_phase_b       ↑ run_meta      ↑ run_classroom_assignment
```

- **Phase A** = `cpsat_v2_assignment` — assigns teachers to (class, subject). HARD
  full coverage; SOFT minimize unused capacity + fragmentation.
- **Phase B** = `cpsat_v2_timetable` — places cattedre into (day, hour). Itself
  two-stage internally (Phase A day-counts, then per-day slot fill).

**Phase B knobs** (`run_phase_b`), with enforced cross-field rules:
| `cp_sat_scope` | `phase_a_mode` | meaning |
|---|---|---|
| `day` (default) | must be `always` | per-day decomposition, inner day-count solve |
| `week` | `skip` or `soft_hint` (never `always`) | monolithic week solve, day-count as hint or omitted |
`use_decomposition=True` (default) splits classes via spectral clusters before the
per-day solve; `False` is the monolithic path. **Both** feed locks natively (see
Locking below).

### Locking (unified)

Locked `Lesson`/`Assignment` rows are honored as **true hard constraints in every
path** — there is no snapshot/restore anywhere:
- **All CP-SAT solves** (monolithic week, monolithic per-day, decomposed spectral
  stages A/B/C + ricucitura + day fallback, temporal, curriculum, metis, column
  generation) receive the locked slots and emit `model.Add(slot[(p,c,s,d,h)] == 1)`,
  plus per-cattedra-day "lock-floors" inside Phase A (`solve_phase_a`).
- **Metaheuristics** (lns/sa/ts/ils/alns/vns/lagrangian) are local search, not CP
  models, so they get a **forbidden-key set** instead: `locks=` is the set of locked
  `(p,c,s,d,h)` tuples; every move operator rejects moves that touch a locked key and
  LNS-destroy excludes them from the free pool. With the no-double-booking
  feasibility invariant this is equivalent to a hard lock.

`_read_locked_lessons` only **reads** the current locked set; `_apply_locked_classrooms`
re-decorates room metadata onto solver-placed locked lessons. Do not reintroduce a
"restore" step.

**Decomposition strategy selection.** `decomposition_auto.auto_detect_decomposition_strategy(profs)`
builds the class-class adjacency graph (edge weight = shared teachers) and picks by
two metrics — this drives the UI "Suggerimento" tooltip, **not** an automatic switch:
| condition | strategy | module |
|---|---|---|
| modularity Q > 0.30 | `spectral` (natural curriculum clusters) | `decomposition_spectral_v2` |
| else density ρ > 0.60 | `metis` (dense, forced balanced cut) | `decomposition_metis` |
| else | `curriculum` (partition by indirizzo) | `decomposition_curriculum` |
All three combine with **temporal** decomposition (`decomposition_temporal`, parallel
over the 6 days) — orthogonal, always recommended. Each has its own
`run_decomposition_*` entry point.

**Metaheuristic post-processors** (`run_meta(stage, ...)`) operate on the *active
solution*; `stage` dispatches to `metaheuristics.run_*`:
`lns | sa | ts | ils | alns | vns | lagrangian`. Column generation is separate
(`run_column_generation`). All receive the locked-lesson key set via `locks=` so
moves never disturb a locked cell.

**Full pipeline** (`run_full_pipeline`) runs an **ordered, user-chosen** `steps`
list from:
`{hall_check, phase_a, phase_b, cg, decomp_spectral, decomp_temporal, decomp_metis,
decomp_curriculum, lns, alns, sa, ts, vns, ils, lagrangian, rooms}`.
Two normalization rules: `decomp_spectral` is rewritten to `phase_b` +
`use_decomposition=True`; and **at most one scheduler token** (`phase_b` /
`decomp_temporal` / `decomp_metis` / `decomp_curriculum`) runs — the first wins, later
ones are dropped with a warning (never two competing schedulers back-to-back).

## Data model (ER sketch)

SQLite via SQLAlchemy (`models.py`, ~30 tables). All user-facing top entities mix in
`TenantMixin` (multi-tenant scoping) + `TimestampMixin`. Clusters:

**Core inputs**
- `Subject`, `Teacher`, `SchoolClass`, `Classroom`, `Curriculum`, `Student`,
  `StudyGroup` — the editable domain. Hours live in satellites: `ClassSubject`,
  `CurriculumSubjectHours`, `GroupSubjectHours`.
- `Teacher` fans out to many constraint satellites: `TeacherSubject` (can-teach),
  `TeacherUnavailability` / `ClassUnavailability` / `ClassroomUnavailability`
  (3-state hard/soft per (day,hour) cell), `TeacherMandatoryFreeDay`,
  `TeacherFreeDayPreference`, `TeacherCompatibleClass`, and **Phase-A-only**
  `TeacherClassPreference` / `TeacherCurriculumPreference` (5-state taxonomy:
  allowed/preferred/soft/forbidden/enforced).
- Classroom prefs: `ClassroomSubjectPreference` / `TeacherClassroomPreference`
  (4-state) + `ClassroomClassPreference` (home room) + tags
  (`ClassroomTag` ↔ `ClassroomTagAssignment`), `Student` tags likewise.

**Assignment (Phase A output) → `Assignment`** — one row per (teacher, class, subject).
Encodes the three Italian special shapes via flags/FKs:
- shared coteaching → N rows sharing `coteach_group_id` → `CoteachGroup` (`CoTeachingRule` is its **legacy** predecessor)
- sostegno → `is_support=True`
- potenziamento → `is_potenziamento=True`, `class_id=NULL`
- inter-class → `group_id` → `StudyGroup` (**XOR** with `class_id`)
- intra-class parallel → shared `parallel_group_id` (same slot, class counts once)

**Timetable (Phase B output) → `Solution` 1—N `Lesson`** — one active `Solution`
(`is_active`); each `Lesson` is one occupied (teacher, class|group, subject, day,
hour) cell with hot composite indexes. `UnscheduledLesson` holds "svincolate"
lessons (the pool sidebar); `DayCount` caches Phase-A counts for drag-drop validation.

**Constraints (cross-cutting)**
- `LogicalUnavailability` (per-entity DNF expression), `CurriculumLogicalConstraint`
  (curriculum-wide DNF, resolves to many classes), `GeneralConstraint` (global DSL,
  evaluated post-hoc on the active solution). All carry the hard/soft/preferred/
  enforced `kind`.
- `Plesso` (campus) + `PlessoCommutingRule` (movement between two sites) +
  `PlessoEntityPolicy` (single-plesso-per-day / total). `Classroom.plesso_id` locates
  rooms.

**Runs & ops**
- `Run` 1—N `RunLog` (live SSE log) + 1—N `RunTelemetry` (per-stage time series).
- `Absence` + `SubstituteAssignment` drive the substitution UI against the active
  solution. `ConstraintIntervention` is the audit trail for FeasibilityPanel edits.
- `WorkingDay` 1—N `WorkingHourSlot` = the **Tab Ore** school-week definition;
  `position`/`slot_index` are the engine's `day_idx`/`hour_idx`, with
  `legacy_day_number` (1..6) / `legacy_hour_number` (8..13) bridging old
  `*_unavailability` rows.

**Watch-outs.** `ClassroomSubjectPreference.required` is a *derived* column kept in
sync with `state` by a SQLAlchemy `before_insert/before_update` event — set
`state='enforced'`, never write `required`. Several XOR invariants
(`class_id`/`group_id` on `Assignment`, `CoteachGroup`; class-vs-group on `Lesson`)
are enforced at the application layer, not by DB constraints.
