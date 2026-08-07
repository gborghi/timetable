# piTantum

[Italiano](README.it.md) | English

> 🤖 **Built with AI.** piTantum was designed and implemented with the
> assistance of artificial intelligence (Anthropic's Claude) — from the
> CP-SAT solver and constraint engine to the FastAPI backend and the
> SvelteKit frontend.

> *Omnia, Lucili, aliena sunt, tempus tantum nostrum est.*
> &mdash; Seneca, *Epistulae morales ad Lucilium*, I, 1

> "All, Lucilius, comes to us from others; only time is our own."

**piTantum** (alias **Tempus Tantum**) is a system for generating
and managing the weekly schedule of an Italian high school:
teacher-class assignments, weekly timetable optimization,
absence-and-substitution management, drag-and-drop with live
preview.

The name plays with the shape of the Greek letter **π**: the two
vertical strokes of the lowercase pi mirror the two **T**s of
**T**empus **T**antum. The Senecan verse summarises the program:
of time we have only what we organise now.

Three layers, one repo:

1. **Solver** (`engine/`) — a CP-SAT pipeline (Google OR-tools)
   with spectral decomposition for very large instances, plus a
   collection of metaheuristics (LNS, SA, TS, ILS, ALNS, VNS,
   Lagrangian, column generation) that run on top of the CP-SAT
   seed solution.
2. **Web UI** (`webui/`) — a FastAPI backend over SQLite plus a
   SvelteKit frontend that exposes every piece of data the solver
   consumes (teachers, classes, subjects, classrooms, curricula,
   students, study groups), runs the optimization steps end-to-end,
   and lets the user fine-tune constraints, drag lessons around
   the timetable, manage absences and substitutions, etc.
3. **Legacy notebooks and prototypes** (`schedule/`) — original
   single-file scripts the solver evolved from. Kept for reference.

## Recent changes (May 2026)

The April-May 2026 cycle landed three big UI features and a
typographic overhaul of the manual. See [`CHANGELOG.md`](CHANGELOG.md)
for the full list; the highlights:

- **`WeeklyCalendarView` everywhere**: the `/schedule` matrix is
  gone, replaced by a true drag-and-drop weekly calendar with
  soft-conflict preview, four per-lesson actions, and an
  unscheduled-pool sidebar.
- **Conflict modal on drop**: dropping on an occupied slot opens
  `ScheduleConflictModal` (Sostituisci / Annulla); the same
  modal serves logistic conflicts elsewhere in the UI.
- **Tab Ore**: visual editor of the school week (days and slots)
  with drag-create / resize / move / delete, three CSS cursors,
  inline edit popover, and live propagation to every calendar
  view via `workingHoursStore`.
- **Bulk actions on `/assignments`**: multi-select + five batch
  operations (delete, lock, unlock, change-teacher, set-flag) on
  one transactional backend round-trip.
- **Cypress E2E**: 34 specs covering every list page, every CRUD
  workflow, every dropdown of `/optimize`, and the new
  `/schedule` rebirth (drag-drop + 4 actions + pool + filter +
  soft-conflict).
- **Manual**: `docs/manual.pdf` (IT) and `docs/manual_en.pdf`
  (EN) restyled in vintage editorial — EB Garamond with
  old-style figures, Tschichold-style page geometry, Roman
  chapter numerals framed by `decofour` rosettes, three-line
  drop caps, italic running heads, fleurons in the foot.

## Italian-school constraints (C1+C2+C3)

- **Co-teaching (Italian: *compresenza*)**: shared (chemistry lab
  with assistant) and shadow (special-needs support teacher
  shadowing a class). C1.
- **Potenziamento** (Law 107/2015): class-less teacher hours used
  for substitutions and projects. C1.
- **Parallel intra-class groups** (e.g. religion vs. alternative
  ethics, taught at the same hour by different teachers): C2.
- **Inter-class study groups** (cross-class language splits,
  recovery groups, art electives): C3.
- **Native CP-SAT locks**: every locked Lesson is a hard
  constraint, propagated to all six pipelines (monolithic,
  decomposed temporal/spectral/curriculum/metis, column
  generation) and seven post-processors.

See [`docs/constraints.md`](docs/constraints.md) for the formal
modeling, [`docs/benchmarks/analysis.md`](docs/benchmarks/analysis.md)
for measured timing, and `README.it.md` for the original Italian
documentation that mirrors this file.

## Quick start

```
git clone https://github.com/gborghi/timetable
cd timetable/webui
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements.txt
start.bat            # opens backend (:8000) + frontend (:5173)
```

Then open http://127.0.0.1:5173 and use the Dashboard's "Importa
profilo" / "Genera mock" cards to seed a school.

For E2E test orchestration with Cypress + Playwright, see
[`webui/frontend/E2E_README.md`](webui/frontend/E2E_README.md).

## Tests

```
cd webui/backend
.venv/Scripts/python -m pytest                 # unit + integration
.venv/Scripts/python -m pytest -m "not slow"   # quick subset
.venv/Scripts/python tests/benchmarks/run_benchmarks.py --quick
```

E2E (require a running stack):

```
docker compose -f docker-compose.test.yml up -d
cd webui/frontend
npm run test:e2e:cypress
npm run test:e2e:playwright
docker compose -f docker-compose.test.yml down -v
```

The full feature list is large; see `proposals/analysis.md` and
`proposals/benchmarks.md` for the design rationale and the empirical
performance numbers across school sizes.

## Project origins

piTantum grew out of ideas by **Fernando Gargiulo**, **Giovanni Borghi**,
**Matteo Mariani** and **Stefano Bertozzi**. The project owes to them
the conceptual design of the scheduling method it implements, the
choice of the constraints that matter for the reality of Italian
schools, and the overall shape of the architecture. The technical
implementation was developed from those ideas.

## Documentation

- **[Installation guide](docs/installation.md)** -- cross-platform
  setup (Windows / Linux / macOS): prerequisites, official installers,
  clone commands, Apple Silicon notes, per-OS troubleshooting,
  install verification, updating, uninstalling. **Quick
  start** for each OS at the top of the file.
- **[Manual (PDF)](docs/manual.pdf)** -- a single monograph,
  written in a discursive style, accessible to non-technical readers
  yet rigorous where the content demands it. It covers the school
  timetabling problem, an overview of piTantum, the user interface,
  the constraint model, then every algorithmic method
  (CP-SAT, spectral decomposition, metaheuristics, Hall pre-check,
  Lagrangian relaxation, column generation, Monte Carlo,
  bipartite-graph analysis, applied statistics, DSL parser),
  the software architecture, the data model, the REST API, the
  extension guide, the benchmarks over the five profiles, and a
  lessons-learned section. LaTeX source in `docs/manual.tex` with the
  chapters in `docs/manual/chapters/` and the bibliography in
  `docs/manual/bibliography.bib`. Rebuild with
  `docs/build_manual.sh` (Linux/macOS/Git Bash) or
  `docs/build_manual.bat` (Windows). The pipeline is lualatex +
  biber + makeindex + lualatex (x2).
- **[docs/](docs/)** -- modular markdown reference:
  [installation](docs/installation.md) /
  [architecture](docs/architecture.md) /
  [data model](docs/data_model.md) /
  [constraints](docs/constraints.md) /
  [workflow](docs/workflow.md) /
  [UI guide](docs/ui_guide.md) /
  [objective DSL](docs/objective_dsl.md) /
  [API](docs/api.md) /
  [extending](docs/extending.md).
- **[webui/docs/](webui/docs/)** -- short user-facing guides linked
  from the UI itself (Excel import format, query syntax, bulk
  operations, classroom auto-generation, ...).

## Advanced features (Italian school constraints)

### Native lesson locks

An `Assignment` with `locked=True` (toggled in the UI) is translated
directly into a CP-SAT constraint (no longer via snapshot/restore).
Benefits:
- fail-fast: incompatible locks raise a 400 at POST time, not halfway
  through the run.
- propagated to every pipeline (monolithic Phase B, decomposed
  temporal/spectral_v2/curriculum/metis, column generation, ALNS,
  VNS, Lagrangian, classroom assignment).
- pre-flight `validate_locks_vs_constraints` checks the locks against
  the teacher's free_day, the class's max_hours_per_day, HARD
  co-teaching (compresenza) constraints, and so on.

### Co-teaching / compresenze (Task C1)

Two variants supported by `CoteachGroup`:

- **Shared** (e.g. a chemistry lab with an assistant): `n_hours` hours
  of a cattedra shared between the principal teacher (full cattedra)
  and one or more co-teachers (only the co-taught hours). Convention
  `members[0] = principal`. In the solver: `day_count[principal] >=
  coday[g, d]` and `day_count[codoc] == coday[g, d]`.
- **Shadow / sostegno**: a special-needs (sostegno) teacher shadowing
  a student. Modeled with `Assignment.is_support=True` and, by
  convention, subject `"sostegno"`. Constraint `slot[(sost, X, sost, h)]
  <= OR(slot[*, X, *, h] for non-support)`: the sostegno hour is present
  only where the class is already busy with another lesson, and does
  NOT count as an extra class-hour.

Italian example: `2C chemistry lab, 2h with co-teaching` ->
`CoteachGroup(class_id=2C, subject=Chimica, n_hours=2)` with
`Assignment(ProfChim, 2C, Chimica, hours=4)` and
`Assignment(ProfAss, 2C, Chimica, hours=2)`. The principal teaches
4h, the assistant only 2h, and those 2h coincide in the same slot.

### Potenziamento (Law 107)

A class-less cattedra: `Assignment.is_potenziamento=True` with
`class_id=NULL`. The hours are still scheduled (max 5/day) and the
teacher becomes a priority for substitutions in the
`/assenze-supplenze` tab (**POT** badge + purple border). HARD weekly
cap: 30 hours (5 hours/day x 6 days).

### Parallel groups intra-class (Task C2)

Typical case: `religione + alternativa` in the same class, same hour,
different teachers. Modeled with `Assignment.parallel_group_id`:
members of the same parallel share the slot, and the class counts as
busy **only once**. Example:
`Assignment(ProfRel, 3B, Religione, h=1, parallel_group_id=99)` +
`Assignment(ProfAlt, 3B, Alternativa, h=1, parallel_group_id=99)`.

### Inter-class StudyGroup scheduling (Task C3)

Groups that span several classes (e.g. **Spagnolo** with students
from 2A + 2B). Data model: the existing `StudyGroup` with
`GroupMembership` (students) + `GroupSubjectHours` (hours/subject).
Extended schema (Option B):
- `Assignment.group_id` nullable (XOR with `class_id`).
- `CoteachGroup.group_id` nullable (XOR with `class_id`) for group
  co-teaching.
- `Lesson.group_name` nullable for group-lessons in the results.

Solver:
- new tuples `(prof, group_name, subject, n_hours)` with `group_name`
  as a "virtual class label" not in `classes` (no `cl_day_load`,
  no HARD-2).
- per-day capacity constraint: `cl_day_load[home_cl, d] +
  sum(group_day_count[g, d]) <= 6` on every home class of the members.
- the Phase B class-busy aggregator extends `subj_busy` by adding
  `__grp__<gname>__<subj>` as a busy_key for each home class.
  The invariant `sum(subj_busy) == pr` guarantees the class does not
  hold other lessons in the group's slot.

Supported pipelines: monolithic + `decomposition_temporal`. The other
decomposed pipelines (`spectral_v2`, `curriculum`, `metis`,
`column_generation`) ignore `group_assignments` for now --
follow-up tracked in AUDIT.md.

Example: group "Spagnolo cross-class" with 5 students from 2A + 7 from
2B, 3h/week, ProfSpa: add `Assignment(teacher=ProfSpa,
class_id=NULL, group_id=<Spagnolo id>, subject="Spagnolo", hours=3)`.
The solver will schedule 3 hours in different slots; both 2A and 2B
will be "busy" in those slots (their students are physically in the
group).

### Pre-flight checks

`validate_coteach_sostegno_potenziamento` checks at *POST time*:
- co-teaching: principal hours >= n_hours, codoc hours == n_hours.
- sostegno: class_id must exist.
- potenziamento: class_id NULL, weekly total <= 30.
- group: XOR class_id/group_id, the group must have students, every
  student must have a home class, hours > 0.

Violations are returned as a 400 with a specific list, not as a silent
INFEASIBLE at the end of the run.

## Brand assets

Logos, banners, icons and screenshots live in [`branding/`](branding/).
Each subfolder includes a `grok_prompts.md` with copy-paste-ready
prompts for generating the final assets via Grok. There are also
**working SVG placeholders** that ship with the repo, so the UI stays
brand-coherent from the first launch.

Palette: deep indigo (`#1e3a5f`), warm gold (`#c9a23a`), burnt sienna
(`#9c4a1c`), ivory (`#f7f1de`). Exposed via the CSS variables
`--brand-{primary,secondary,accent,bg,fg}` in
`webui/frontend/src/app.css`.

## Quickstart (Windows)

Prerequisites:

- Python 3.11+ (Microsoft Store build is fine)
- Node.js LTS (https://nodejs.org/en/download)

```
git clone https://github.com/gborghi/timetable
cd timetable\webui
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
start.bat
```

`start.bat` opens two console windows:

- backend: uvicorn at http://127.0.0.1:8000
- frontend: vite dev server at http://127.0.0.1:5173

Open http://127.0.0.1:5173 in a browser and start with the
**Dashboard** card "Importa un profilo gia calcolato": pick `small`
and check the three pool checkboxes (curricula, classrooms, students).
The import seeds about 220 students, 17 classrooms, 8 indirizzi and
113 prof-class assignments in roughly 5 seconds, then loads an
already-optimized timetable solution. From there you can browse
every other tab.

If `node_modules` is missing, the launcher runs `npm install` once
(~150 MB). If the venv is missing, the launcher prints the exact
command to create it.

## Web UI tour

The nav bar lists every concept exposed:

- **Dashboard** — import / mock-generate / state overview.
- **Docenti** — teachers with split last/first name, nickname,
  availability matrix (5 states: free / yellow soft / red hard /
  blue preferred / dark-green enforced), classroom preference grid
  (5 states: allowed / yellow soft / blue preferred / red forbidden /
  dark-green enforced), free-day handling, logical disjunctive
  unavailability constraints, max-hours, classes-of-concorso pool.
- **Classi** — classes; same availability+classroom pattern as
  teachers, plus subject hours per class, indirizzo dropdown, SOFT
  weight on the 6th hour, etc.
- **Indirizzi** — study tracks (Liceo Scientifico, Linguistico, ...)
  with a per-year subject-hours grid and indirizzo-level logical
  constraints, optionally restricted to a single year of course.
- **Studenti** — students. Imported in bulk per profile (Faker-
  driven, deterministic) or via Excel/CSV.
- **Gruppi** — articulated study groups (cross-class), e.g. seconda
  lingua, IRC vs alternativa, recupero. Type-C semantics: members
  can come from any combination of classes.
- **Materie** — subjects, with a subject-classroom grid (same 5
  states as the teacher grid) and the subject-group-weight matrix
  (classe-di-concorso assignment).
- **Aule** — classrooms with kind / capacity / multi-class flags,
  per-class home preferences, per-subject preferences, and the
  same 5-state availability matrix as teachers and classes.
- **Compresenze** — co-teaching rules.
- **Cattedre** — assignments (teacher x class x subject hours).
  Multi-row select unlocks **bulk operations**: delete, lock /
  unlock, change-teacher, set-flag — each a single transactional
  `POST /api/assignments/bulk-*` round-trip.
- **Workflow** — multi-step run launcher (assignment, phase B
  decomposition, LNS / SA / TS / ILS).
- **Orario** — final timetable view, now powered by the
  `WeeklyCalendarView` Svelte component in `mode=schedule`:
  drag-and-drop with live HARD-feasibility check, SOFT delta
  preview, four per-lesson actions (Edit / Move / Unbind /
  Delete), and an unscheduled-pool sidebar for lessons without
  a slot. Drop on an occupied slot opens the canonical
  `ScheduleConflictModal` with a binary **Sostituisci /
  Annulla** choice (replace or cancel).
- **Tab Ore** — visual editor of working days and hour slots:
  draw a slot by dragging top-down, resize from the bottom edge,
  move by grabbing the body, delete with a click. Three CSS
  cursors (`grab` / `grabbing` / `ns-resize`) signal drag state;
  saves propagate live to every other calendar view via the
  shared `workingHoursStore`. `POST /api/working-hours/reset`
  restores the default Mon-Sat 8-14 60-minute layout.
- **Assenze e supplenze** — week-grid view: click a column header
  to add absent teachers for that day, click a cell to assign
  substitutes via drag-drop. Cells turn red when uncovered and
  green when covered.

Every list page (teachers, classes, subjects, classrooms, curricula,
students, groups) supports:

- a query DSL (`group=A026 AND max_hours>=18`, `cognome startswith
  Ross`, `unavailable_on(martedi)`, ...) with per-entity field
  catalogues
- multi-level sort (up to 4 levels)
- multi-row select via Ctrl/Shift click
- bulk apply with conflict detection (override / skip / dry-run) for
  add_logical, set_field, add_unavailability
- Excel/CSV import with downloadable template; documentation in
  `webui/docs/import_format.md`

## Solver pipeline

1. **Assignment**: greedy + CP-SAT to map `prof -> class -> subject`
   with hour quotas; respects classe-di-concorso, max hours, free
   days, mandatory free days, compatibility lists.
2. **Phase B (decomposition)**: spectral graph clustering of the
   assignment graph splits the school into k loosely-coupled sub-
   instances, each solved independently by CP-SAT, then re-stitched
   ("ricucitura") with a global pass.
3. **Metaheuristics**: LNS / SA / TS / ILS run on top of the
   decomposed solution. The objective covers SOFT preferences
   (no holes per teacher day, no isolated 1- or 5-hour days,
   distribution across the week, dual-hour pairs, no 6th hour, ...).
4. **Classroom assignment**: a separate CP-SAT step maps
   (class, subject, slot) -> classroom honoring kind constraints,
   home rooms, subject-classroom preferences, and multi-class rules.
5. **Live editing**: drag-and-drop in the Orario page does an
   incremental check of every HARD constraint and a delta-eval of
   every SOFT preference; the user is told whether the move is
   feasible and how the objective shifts.

## Constraint language

Per-cell availability has 5 states (free / soft / hard / preferred /
enforced). Logical constraints are disjunctive expressions over slot
literals or richer **predicate atoms**:

```
mai aula:LabFisica@mar
aula:LabInformatica@lun OR aula:LabInformatica@gio
mai materia:Religione@lun8
gruppo:IRC OR gruppo:Alternativa
NOT (mer3 AND mer4)
```

Four kinds: HARD / SOFT / PREFERRED / ENFORCED. Documentation in
`webui/docs/logical_constraints.md`. The slot-only portion is fully
honored by the solver today; predicate-atom enforcement is partial
and described in the same doc.

### General DSL

For arbitrary constraints over any combination of teachers, classes,
classrooms, subjects, groups, students, days and hours, there is a
**general DSL** (one parser, many compilers) with quantifiers
`forall` / `exists` / `count`, atomic predicates, logical connectives,
built-in functions (`lesson()`, `consecutive()`, `same_day()`,
...), and path-sources (e.g. `exists g in s.groups`).

Typical examples:

```
# Every Physics teacher must have exactly 1 hour per week
# in a lab_fisica-type classroom
forall t in teachers where t.subject == "Fisica":
    count l in lessons where l.teacher == t
                          and l.classroom.type == "lab_fisica":
        l == 1

# BES students must belong to a Sostegno group
forall s in students where "BES" in s.tags:
    exists g in s.groups: g.name == "Sostegno"
```

Full reference + a gallery of 30+ examples in
[`docs/general_dsl.md`](docs/general_dsl.md) and in the chapter
"DSL generico per i vincoli" of the [Manual](docs/manual.pdf).

## Demo profiles: SQLite is the source of truth

Six demo profiles (`small`, `medium`, `big`, `huge`, `superhuge`,
`mega`) ship as self-contained SQLite files under
`engine/scripts/data/<profile>/<profile>.sqlite`. Each one carries
the full anagrafica + the 14 constraint tables + WorkingDay/Slot
+ Lessons, generated deterministically by
`engine/scripts/build_profile_db.py` with `seed=42`. Importing a
profile from the dashboard now reads the SQLite directly (the
legacy `school_*.pkl` / `profs_*.pkl` pair is kept as historic
fallback only — see the `PICKLE_DEPRECATED.md` note in each
profile folder).

To rebuild a single profile or all six:

```sh
python -m engine.scripts.build_profile_db small
python -m engine.scripts.build_profile_db --all
```

A `manifest.json` is written alongside each SQLite with row
counts per table; the aggregated index lives at
`engine/scripts/data/profiles_manifest.json`. The Manual chapter
"Architettura dati dei profili" documents the schema and the
per-profile stress table.

## Repository layout

```
engine/      solver code (CP-SAT, decomposition, metaheuristics,
               exporters); per-profile SQLite snapshots under
               `engine/scripts/data/<profile>/<profile>.sqlite`
               (small, medium, big, huge, superhuge, mega).
webui/         FastAPI backend + SvelteKit frontend + docs.
schedule/      legacy single-file prototypes (kept for reference).
proposals/     design notes and benchmark results.
*.pdf          reference papers (VLNS, spectral methods,
               combinatorial optimization).
```

## Development notes

- The webui DB is a single SQLite file at `webui/data/timetable.db`.
  Idempotent migrations live in `webui/backend/db.py` and are run on
  every backend boot — no Alembic, intentionally.
- Pickle snapshots (`engine/scripts/*.pkl`) are the engine's I/O
  format; the webui converts to/from them via
  `webui/backend/engine_io.py`.
- Excel/CSV import templates can be downloaded from each list page
  in the UI (button "Template").
- See `proposals/benchmarks.md` for measured running times on the
  five mock profiles.

## License

Private project; no public license.
