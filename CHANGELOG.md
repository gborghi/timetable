# Changelog

All notable changes to piTantum.

The format follows [Keep a Changelog](https://keepachangelog.com)
loosely; commit hashes refer to the canonical history on `main`.

## [Unreleased]

### Documentation

- **Vintage editorial restyle of the manual (IT + EN)**.
  EB Garamond with old-style figures, Tschichold-style page
  geometry (inner 2.8 cm, outer 4.2 cm, ornamented foot), Roman
  chapter numerals framed by `decofour` rosettes (from
  `fourier-orns`), three-line drop caps with the opening text in
  small caps, italic automark running heads (chapter on verso,
  section on recto), fleurons enclosing the page number at the
  foot, native KOMA-Script chapter format. New title page in
  Aldine cover style with thick + thin rules, Senecan epigraph,
  module stemma, year in Roman numerals.
- **New chapter "Calendario settimanale, Tab Ore e operazioni
  in massa"** (IT) / "Weekly calendar, working-hours tab, bulk
  operations" (EN), covering `WeeklyCalendarView`, the conflict
  modal, the Ore tab, the live `workingHoursStore` and bulk
  actions on `/assignments`.
- **New chapter "Qualita end-to-end"** (IT/EN) on the Cypress
  suite, conventions, lessons learned.

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
