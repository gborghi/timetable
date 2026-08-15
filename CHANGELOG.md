# Changelog

All notable changes to piTantum.

The format follows [Keep a Changelog](https://keepachangelog.com)
loosely; commit hashes refer to the canonical history on `main`.

## [Unreleased]

### Added

- **Thoroughness selector in Phase B** (`fast | balanced | thorough | maximum`).
  Maps to CP-SAT `relative_gap_limit` (0.15/0.05/0.01/0) and
  `cp_model_probing_level` (0/1/2/2). Lets users trade quality for speed.
- **Smart parameter recommendations** (`GET /api/optimize/parameters/recommend`).
  Analyses the current DB (class count, teachers, assignments, constraints,
  rooms) and suggests time limits, workers, thoroughness, decomposition, and
  room-capacity settings. Frontend button "Carica parametri consigliati" in the
  Phase B card auto-populates the form.
- **Phase A special-room capacity ("palestre fissate")**. `build_special_room_ctx`
  now feeds into `solve_phase_a` so per-day PE distribution respects gym capacity
  (e.g. 3 gyms × 2 classes = max 6 PE slots/hour) before Phase B runs.

### Changed

- **`respect_room_capacity` constraint uses `multi_class_max ≤ 1` filter** instead
  of hardcoded `kind == "standard"` — area-based room kinds (liceo90doc) are now
  correctly counted as standard rooms.
- **Inverted indices in CP-SAT model**: `_tdh`, `_cdh`, `_cdh_detail` dicts provide
  O(1) lookup for `slots_for_teacher_day_hour` and `slots_for_class_day_hour`,
  replacing O(N) full-dict scans during model construction.
- **Tight IntVar domains**: `n_five`, `n_one`, `freeday_pref_pen`, `uniform_pen`
  bounds are computed from actual data (term count, triples, assignments) instead
  of hardcoded constants.

### Fixed

- **Temporal decomposition broken after August changes**: Phase A was distributing
  PE hours without respecting gym capacity, causing per-day INFEASIBLE. Fixed by
  moving special-room capacity constraint from Phase B to Phase A. Result: 100%
  coverage on 90-class model (was 66–83%).
- **Phase B gap limit restored**: `relative_gap_limit=0.02` on per-day solves
  prevents the solver from chasing soft-penalty optimality and timing out before
  finding any feasible solution. Critical for non-deterministic 8-worker runs.
- **`cg_helpers._seed_patterns` NameError**: extracted function referenced `DAYS`
  and `HOURS` globals from `column_generation.py`. Fixed by adding `days` and
  `hours` parameters.
- **Frontend `crypto.randomUUID` polyfill** for HTTP origins (Tailscale IPs):
  `static/polyfills.js` provides a `getRandomValues`-based fallback loaded as a
  classic blocking `<script>` before any module code.

### Documentation

- **Guida vicepreside** (`webui/data/vicepreside_liceo90/index.html`) updated with
  thoroughness selector, smart parameter recommendations, Phase A palestra fix,
  and parameter table.
- `docs/workflow.md`: new sections on smart parameters, thoroughness,
  `respect_room_capacity`, and special-room capacity in Phase A.
- `docs/optimization_strategies.md` + `docs/optimization_strategies_en.md`: new
  "Parametri del solver Phase B" / "Phase B solver parameters" section.
- `docs/ui_guide.md`: expanded `/optimize` section with Phase B parameters,
  thoroughness, and decomposition alternatives.
- `docs/experiments.md`: temporal decomposition section rewritten with the fix
  story, gap limit rationale, and gyms-first approach explanation.

## 2026-05 cycle (Web UI rebirth)

### Added

- `feat(webui): WeeklyCalendarView mode=schedule with drag-drop
  + soft-conflict preview` (commit 876755b).
- `feat(webui): /schedule rewrite with WeeklyCalendarView
  (drag-drop, 4 actions, pool unscheduled)` (commit c3d3706).
- `test(e2e): /schedule WeeklyCalendarView complete coverage
  (drag-drop + 4 actions + pool + filter + soft-conflict)`
  (commit 84e7345).
- `feat(schedule): conflict modal on drop replace-or-cancel`
  (commit 59ba4a8). The canonical `ScheduleConflictModal`
  exposes prop `showUnbind=false` and `deleteLabel="Sostituisci"`
  for the drop-on-occupied flow.
- `feat(backend): /api/lessons/{id}/{move,unschedule,delete} +
  unscheduled pool` (commit 29f0ae3). Each endpoint accepts
  `on_conflict ∈ {dry_run, fail, delete, unbind}`; 409 returns
  `conflicts.{teacher_busy, class_busy, room_busy}`.
- `feat(webui): bulk actions on /assignments — multi-select +
  5 actions + Cypress` (commit 16f882a).
- `feat(backend): bulk assignments endpoints
  (delete/lock/change-teacher/set-flag)` (commit e6314eb).
- `feat(webui): Tab Ore + WeeklyCalendarView reusable component`
  (commit b3236ab).
- `feat(webui): WeeklyCalendarView edit mode (drag-to-create
  slots, resize, move, delete)` (commit 3236b10).
- `feat(webui): Tab Ore uses WeeklyCalendarView in edit mode for
  visual slot configuration` (commit 811fe3d).
- `feat(ore): per-slot Modifica/Cancella buttons + drop key
  hints` (commit d11e396).

### Changed

- `ux(ore): inline edit popover on top, grab/grabbing cursors,
  plain-text actions` (commit d4bc873). Three CSS cursors
  (`grab`, `grabbing`, `ns-resize`) signal drag state. The
  inline edit popover floats above the cell, never below.
- `fix(weekly-calendar): live propagation of /ore changes to
  every grid` (commit e0b76bc). `workingHoursStore` is the
  single shared source; saves in `/ore` redraw every
  `WeeklyCalendarView` instance without page reload.
- `feat(engine): CP-SAT constraints for variable slots per day`
  (commit 7254392). The engine no longer assumes 6 fixed hours.
- `refactor(engine): migrate DAYS/HOURS hardcoded to
  working_hours_config loader` (commit bf6cfa2).
- `fix(import): resolve pickle paths for
  engine/scripts/data/<profile>/ layout + populate optimize
  dropdown` (commit 4194b5b).
- `fix(webui): dashboard import dropdown loads precomputed
  databases reliably` (commit 9e99a50).

### Fixed

- `fix(ore): namespace-import was masking api.get / cypress:
  15/15 green` (commit 5c1ba34). Switched
  `import * as api` → `import { api }` after a homonymous local
  variable shadowed the namespace at runtime.

### Tests

- 34 Cypress E2E specs (`webui/frontend/cypress/e2e/*.cy.ts`)
  covering: `teachers`, `classes`, `subjects`, `classrooms`,
  `plessi`, `curricula`, `students`, `groups`, `coteaching`,
  `assignments` (CRUD + bulk + lock), `constraints` (smoke +
  workflow with DSL editor / 4-step wizard / bulk delete),
  `optimize` (dropdowns + Phase B + advanced + launch),
  `schedule` (calendar + workflow), `monitor` (smoke +
  workflow), `absences`, `dashboard`, `navbar_completeness`,
  `navigation`, `critical_workflows`, `logistics_conflict_pill`,
  `minor_tabs_smoke`, `smoke`.

### Engine and constraints (recap from earlier in 2026)

The 2026-Q1 engine work, already shipped before the May cycle,
remains the foundation:

- DSL + OO unification: `ConstraintModel`, `MonolithicSolver`,
  `DayCountModel`, `PhaseBDaySolver`, 14 pragma directives,
  `scope=week`, `phase_a_mode ∈ {skip, soft_hint, always}`.
- Plesso commute SOFT/HARD constraints (commute time between
  campuses tracked per teacher per slot).
- Branch-and-Price with 9 granularities, Ryan-Foster branching,
  dual stabilization.

See `docs/optimization_strategies.md` and the manual chapters
"Tecniche di ottimizzazione avanzate" and "Metodo DSL" for the
full treatment.
