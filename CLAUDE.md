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
# macOS / Linux one-shot (backend :8000 + frontend :5173, background):
webui/start.sh              # --foreground to keep both in the terminal
webui/stop.sh               # kills the PIDs in webui/logs/pids
# Windows equivalent:
webui\start.bat             # or start.ps1
```
`start.sh` bootstraps `webui/backend/.venv` and `frontend/node_modules` on first run
(~4 min); logs land in `webui/logs/{backend,frontend,pip,npm-install}.log`. Manual:
```
webui/backend/.venv/bin/python -m uvicorn backend.main:app --reload --port 8000   # run from webui/
cd webui/frontend && npm run dev
```

### Backend tests (pytest)
```
# from webui/  — PYTHONPATH must include webui + engine + schedule:
export PYTHONPATH="$PWD:$PWD/../engine:$PWD/../schedule"    # bash/zsh
$env:PYTHONPATH = "$PWD;$PWD\..\engine;$PWD\..\schedule"    # PowerShell
pytest backend/tests -m "not slow" -q          # fast suite (CI default)
pytest backend/tests -m slow                   # full CP-SAT pipeline tests (opt-in)
pytest backend/tests/test_foo.py::test_bar     # single test
```
The `slow` marker gates anything that invokes the real solver. Root `pyproject.toml`
mirrors `webui/backend/pytest.ini` so a bare `pytest` at repo root also finds the
backend suite. The top-level `tests/` dir (constraint unit tests + `tests/benchmarks/`)
injects `engine/` into `sys.path` itself — `pytest tests/test_capacity_constraint.py`
works from the repo root with no `PYTHONPATH`.

### Migrations
```
cd webui/backend && ./.venv/bin/alembic upgrade head        # apply (17 revisions)
./.venv/bin/alembic revision --autogenerate -m "msg"        # after editing models.py
```
`db.py::init_db()` runs `Base.metadata.create_all` at startup, so a *fresh* DB is
already canonical; Alembic matters for **existing** DBs. `create_all` only adds
missing tables, never columns — `db.py` carries hand-rolled SQLite ALTER fallbacks
mirroring specific revisions for dev DBs that never ran Alembic. Postgres has no
fallback: run `alembic upgrade head`.

### Environment variables
`PITANTUM_DB_URL` (default local SQLite), `PITANTUM_ENV` (`prod` turns API-key + CORS
into fail-fast), `PITANTUM_API_KEY`, `PITANTUM_CORS_ORIGINS`, `PITANTUM_LOG_LEVEL` /
`PITANTUM_LOG_JSON`, `PITANTUM_DEFAULT_TENANT_ID`, `PITANTUM_DB_POOL_SIZE` /
`PITANTUM_DB_MAX_OVERFLOW`, `PITANTUM_ALLOW_PICKLE_UPLOAD` (pickle ingest is off by
default — the `S301` ruff carve-out exists because of this gate).

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
npm test               # node:test unit suite — the explicit file list lives in package.json;
                       # a new *.test.mjs is NOT picked up until added there
npm run build          # vite build (CI gate)
npm run test:e2e       # Cypress (alias for test:e2e:cypress); Playwright also present
```
E2E needs both servers up. The supported way is the compose file, which gives the
backend an ephemeral SQLite DB in a tmpfs volume so the host DB isn't touched:
```
docker compose -f docker-compose.test.yml up -d     # wait for the backend healthcheck
cd webui/frontend && npm run test:e2e:cypress
docker compose -f docker-compose.test.yml down
```
~37 Cypress specs in `webui/frontend/cypress/e2e/`.

### CI gates
`.github/workflows/ci.yml` on every push + PR to main: `ruff check webui/` →
`pytest -m "not slow"` → `svelte-check` + `npm test` + `vite build` → buildx build of
both Dockerfiles (so a broken `COPY` path in a Dockerfile fails CI even when
everything else is green). E2E and the `slow` suite are **not** in CI.

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
the old `.pkl` path is a fallback (see `PICKLE_DEPRECATED.md` markers). Profiles are
`small | medium | big | huge | superhuge` (+ `mega`); rebuild them — this actually
runs Phase A per profile, so it is slow — with:
```
./scripts/rebuild_profiles.sh --profiles small,medium --skip-existing    # .ps1 on Windows
```
The generated artifacts are gitignored; a missing profile is why the dashboard's
"Importa modelli risolti" dropdown can come up empty on a fresh clone.

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

**The constraint DSL is the unification layer** — the single most load-bearing piece
of engine architecture, and the direction the codebase is converging on. Each of the
~10 special-purpose constraint tables (`TeacherUnavailability`, `CoteachGroup`,
`PlessoCommutingRule`, …) historically had its own hardcoded path inside
`cpsat_v2_timetable` / `classroom_assignment` / `plessi_constraints`. The DSL flattens
them into one stream:

```
ORM rows ──dsl_translator.*_to_dsl()──▶ DSL strings ──general_dsl parser──▶ AST
                                                                            │
                          dsl_to_cpsat ◀──── compilable fragment ───────────┤
                     (native CP-SAT constraints, HARD + SOFT)               │
                                                                            │
                          general_dsl eval ◀── everything else (post-hoc) ──┘
```
- `general_dsl.py` (in `engine/`, **not** webui — it was moved to kill a dual-module
  AST hazard; `webui/backend/utils/general_dsl.py` is the thin re-export) owns the
  recursive-descent grammar: quantifiers, `count`/`sum`, `=>`/`<=>`, and named
  convenience *pragmas*.
- `dsl_to_cpsat.py` compiles only the statically-decidable fragment. `*` `/` `%` and
  general `sum` aggregates are deliberately out of scope.
- `dsl_cp_gate.py` closes the gap: solve → `verify_dsl_hard` on the produced solution
  → `add_nogood` for the exact violating assignment → re-solve, bounded by
  `max_iters`. This is what makes a solver *completely* DSL-compliant even for rules
  the compiler can't model. Natively-compiled rules pass at iteration 0 for free.
- Phase A has its own objective compiler: `webui/backend/utils/objective_dsl.py` →
  `cpsat_assignment_dsl.py`.

When adding a constraint kind: write the `*_to_dsl` translator first, and only add a
native compilation path if the gate's refinement loop proves too slow. Adding a
hardcoded branch inside a solver reintroduces the N-solvers × N-constraints problem.
`docs/dsl_compliance.md` tracks the matrix of what is compiled vs. gated.

**Frontend ↔ backend.** Each `webui/frontend/src/routes/<page>` maps to a backend
router in `webui/backend/routers/<page>.py`. `src/lib/api.ts` is the client;
`pipeline_labels.js` / `constraint_levels.ts` mirror engine vocabulary. The
`/schedule` page is a drag-and-drop `WeeklyCalendarView` with soft-conflict preview;
`/ore` edits the school week and propagates live via `workingHoursStore`.

## Conventions

- **Branch hygiene:** only `main` may exist on `origin`. Cherry-pick work onto `main`
  and delete any service branch before pushing. (Do not push feature branches.)
- **Commits:** conventional-commit prefixes, scoped to the subsystem —
  `feat(dsl):`, `fix(constraint_compat):`, `refactor(engine):`, `perf(webui):`,
  `docs(log):`.
- **`log.md` is an append-only work log**, not a changelog. Each completed goal gets a
  dated section (what shipped, which tests, what was misread) committed as
  `docs(log): …`. `CHANGELOG.md` is the user-facing release history — different file,
  different audience.
- Multi-tenant: models carry `TenantMixin`; respect tenant scoping in queries.
- Backend API key + CORS fail-fast only in prod (`PITANTUM_ENV=prod`); dev defaults
  to localhost-permissive.
- The repo is bilingual: UI strings, launcher scripts, and the `*_it.md` / `README.it.md`
  docs are Italian; identifiers and most comments are English. Domain terms stay
  Italian in code (`cattedre`, `potenziamento`, `sostegno`, `plesso`, `svincolate`,
  `glibero`) — do not "translate" them. The English manual is partly auto-stubbed from
  the Italian chapters (`scripts/gen_en_stubs.py`), so `manual_en.pdf` chapters may be
  summaries pointing back at the Italian text rather than full translations.

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
- Classroom prefs: `ClassroomSubjectPreference` / `TeacherClassroomPreference` /
  `ClassroomClassPreference` (all 4-state; the last one also carries `is_home`)
  + tags (`ClassroomTag` ↔ `ClassroomTagAssignment`), `Student` tags likewise.

**Room assignment: two orthogonal axes.** Nothing in the engine assumes a subject
belongs in a particular kind of room — it has to be configured, and the two ways to
configure it point in *opposite* directions:
- `Classroom.subject_required` (from `ClassroomSubjectPreference.required`) restricts
  the **room**: "this lab only accepts these subjects". It does not force the subject
  anywhere.
- `Subject.required_kind` restricts the **subject**: "Scienze motorie must land in a
  room of kind `palestra`". This is the one that makes gyms/labs actually get used;
  a school that sets only the former will see its gym sit empty and PE happen in
  ordinary classrooms, with no error anywhere.

A third axis, orthogonal to both: **`Teacher.compresenza`** (`mai` default |
`sempre` | `oraria`, the last reading `teacher_compresenza_hours`). It declares
that a teacher *shares* a colleague's room instead of booking one — so the room
step treats that lesson as a **rider** attached to a host in the same
`(class, day, hour)` cell (`classroom_assignment.compresenza_map`). It is a
per-teacher property, deliberately **not** derived from `Assignment.is_support`,
because compresenza is the general shape (sostegno, potenziamento, codocenza,
madrelingua, ITP) and because the converse inference is invalid: same class at
the same hour does *not* imply the same room — Religione / Attività alternativa
really do split a class across two rooms. Without this, every shadow lesson
requested a second room and the room step went INFEASIBLE.

Crossing that is `SchoolClass.room_policy` — `fissa` (HARD: every hour in the class'
home room, with **automatic derogation** for subjects carrying a `required_kind`,
without which the preset is infeasible in any school that has a gym) / `ibrida`
(SOFT home bonus — the historical behaviour and the default) / `libera`. The preset
resolves against `ClassroomClassPreference` in `engine_io.room_pins_from_db`; an
explicit `enforced`/`forbidden` row wins over it. All of it lands as
`lesson["home_room"]` / `lesson["forbidden_rooms"]` in `classroom_assignment._can_host`,
so the CP-SAT path and the greedy fallback enforce it identically.

**Assignment (Phase A output) → `Assignment`** — one row per (teacher, class, subject).
Encodes the three Italian special shapes via flags/FKs:
- shared coteaching → N rows sharing `coteach_group_id` → `CoteachGroup` (`CoTeachingRule` is its **legacy** predecessor)
- sostegno → `is_support=True` + `student_id` (the **pupil** the teacher follows,
  not the class — a support teacher is assigned to a person; the class is derived
  from that pupil). No `Subject` row named "sostegno" is needed or wanted: the
  cattedra shadows the pupil's ordinary lessons. Uniqueness is
  `(teacher, class, subject, is_support, COALESCE(student_id, 0))`.
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
