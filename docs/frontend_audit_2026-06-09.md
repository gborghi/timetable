# Frontend WebUI Audit — 2026-06-09

Read-only audit of `webui/frontend` (SvelteKit, Svelte 5 runes, Tailwind, TanStack
Query) + the xlsx import surface. Three axes: functional use-case coverage,
constraint (vincoli) xlsx-upload feasibility, and CSS/JS quality.

---

## 1. Functional coverage & gaps

20 user-facing routes, **all** mapped to a backend router; no dangling routes.

### Route → router map
`/`→dashboard+dataset · `/classes`→classes · `/teachers`→teachers ·
`/subjects`→subjects · `/classrooms`→classrooms · `/curricula`→curricula ·
`/groups`→groups · `/students`→students · `/plessi`→plessi ·
`/assignments`→assignments · `/ore`→working_hours · `/constraints`→constraints ·
`/coteaching`→coteaching · `/schedule`→schedule+lessons · `/optimize`→optimize ·
`/runs`+`/runs/[id]`→optimize(SSE) · `/monitor`→monitor+lessons+bulk_events ·
`/diagnostics`→diagnostics · `/assenze-supplenze`→coverage · `/import`→imports.

### Highest-priority findings
- **`/import` is a non-functional shell (HIGH).** Backend `imports.py` is complete
  (openpyxl, 7 entities, templates, upsert/replace/append) but the page offers no
  usable picker/preview/dry-run/conflict-resolution. Biggest ROI fix.
- **`/constraints` DSL editor (HIGH).** Free-text, no syntax highlight / live
  validate / autocomplete; feasibility check is an async run, too slow to be
  actionable inline.
- **`/schedule` drag-drop depth (MED-HIGH).** No swap/merge, no batch move, no
  undo; soft-conflict preview is visual-only (outline+badge), no drill-down list
  of which constraint broke and by how much. Drop-conflict modal only offers
  delete-all-or-cancel.
- **Phase B knobs unexplained (MED).** `cp_sat_scope` (per-giorno vs settimana),
  `phase_a_mode` (always/skip/soft_hint), decomposition strategies — buried in
  tiny prose. (Addressed by the tooltip work, this date.)
- **`/optimize` pipeline not persisted (MED).** Drag-reorder + per-step toggles are
  in-memory; reload loses them.

### Missing end-to-end use-cases
1. Bulk data import / migration (frontend) — CRITICAL for onboarding.
2. Conflict resolution during scheduling (drill-down, swap, retime) — HIGH.
3. Absence → substitution cascade (no auto-move / substitute suggestion) — MED.
4. Phase-A preference dry-run / preview — MED.
5. Schedule locking + versioning in the schedule view (lock only in /monitor) — MED.
6. Multi-plesso integration in /schedule (filter/highlight by site) — MED-LOW.
7. Feasibility status surfaced on dashboard / optimize, not only /constraints — MED.
8. Keyboard navigation in the schedule editor — LOW-MED.

### Cross-cutting gaps
- **States:** empty-states missing on most lists; loading/skeletons absent; API
  errors toast but don't block resubmit.
- **Undo:** snapshot+toast-undo only on Classes & Teachers; Assignments / Lessons /
  Constraints have none. Pattern is inconsistent (snapshot-undo vs confirm-delete).
- **Bulk ops:** powerful but no "affected rows" preview before apply; per-row
  confirm on bulk delete (N modals for N rows).
- **A11y:** status pills are color-only (colorblind risk); tables lack
  role=grid/columnheader; focus outline weak in dark theme; drag-drop mouse-only.
- **Help:** domain glossary (Potenziamento, Compresenza, Cattedra, Vincolo) never
  spelled out; tooltips sparse.
- **Persistence:** sort state, pipeline order, collapsible-section state all reset
  on reload.

---

## 2. Vincoli via xlsx — FEASIBLE (foundation exists)

### Existing xlsx pipelines
- **Entity bulk-import** `POST /api/import/{teachers|subjects|classes|classrooms|
  curricula|students|groups}` — `imports.py`, openpyxl, sheet `Dati` (or first),
  CSV/TSV fallback, Italian+English header aliases, upsert/replace/append,
  `ImportReport{ok,n_inserted,n_updated,n_skipped,errors[]}`, template generator
  `GET /api/import/{entity}/template`. **No `vincoli` entity yet.**
- **Constraint import/export ALREADY EXISTS (partial):**
  `POST /api/dashboard/constraints/import-file` (json **or** xlsx) → normalizes each
  record → same dispatcher as the manual UI (`constraints.create_constraint`);
  `GET /api/dashboard/constraints/export?format=json|xlsx`. Frontend:
  `ConstraintsImportExportCard.svelte` (drag-drop .json/.xlsx + export + wipe).
  **This is the base to build the richer language on.**

### Constraint surface
- **DSL** (`engine/general_dsl.py`): boolean logic + `forall/exists/count/sum in
  <source> [where]:`; sources lessons/assignments/teachers/classes/classrooms/
  subjects/curricula/groups/students/days/hours/slots. Pragmas: `no_holes_class`,
  `no_same_class_consecutive_days`, `slot_after_hour_penalty`,
  `teacher_max_hours_after`, `class_present_at_hour(_all)`, `teacher_max_per_day`,
  `cattedra_max_per_day`, `teacher_max_consecutive`, `teacher_at_least_n_free_days`,
  `teacher_preferred_free_day_penalty`, `teacher_mandatory_free_day`,
  `subject_pair_must/exists`, `class_day_load_in`, `subject_day_count_in`,
  `free_day_choice_3way`, …
- **ORM tables**: TeacherUnavailability / ClassUnavailability /
  ClassroomUnavailability (state hard|soft + soft_penalty), TeacherMandatoryFreeDay
  (HARD), TeacherFreeDayPreference (priority 1..3), LogicalUnavailability,
  CurriculumLogicalConstraint, GeneralConstraint (scope+level+weight), CoteachGroup,
  Classroom/Teacher prefs, PlessoCommutingRule, PlessoEntityPolicy.
- `dsl_translator.load_all_dsl_constraints(db, include_soft)` already aggregates ORM
  rows → DSL strings. Creation path: `POST /api/constraints` polymorphic dispatcher
  + `POST /api/constraints/general` (+ `/general/validate`).

### Proposed xlsx constraint language
**Single `Vincoli` sheet + `tipo_vincolo` discriminator + `raw_dsl` escape-hatch row**
(plus `Istruzioni`/`Esempi` sheets, matching the entity-template convention).

Columns: `tipo_vincolo | entita | nome | materia | giorno | ora_da | ora_a | valore
| livello | peso | dsl | note`.

`tipo_vincolo` vocabulary: `indisponibilita`, `giorno_libero`, `pref_giorno_libero`,
`max_ore_giorno`, `max_consecutive`, `no_pomeriggio`, `no_giorni_consecutivi`,
`no_buchi`, `presenza_ora`, `indisp_aula`, `pref_aula_materia`, `pref_aula_docente`,
`compresenza`, `pendolarismo_plesso`, `politica_plesso`, **`raw_dsl`**.

Example:

| tipo_vincolo | entita | nome | materia | giorno | ora_da | ora_a | valore | livello | peso | dsl | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| indisponibilita | docente | Rossi Mario | | ven | 8 | 13 | | hard | | | impegni |
| giorno_libero | docente | Bianchi Anna | | mer | | | | hard | | | part-time |
| pref_giorno_libero | docente | Verdi Luca | | sab | | | | preferred | 30 | | 1ª scelta |
| max_ore_giorno | docente | Rossi Mario | | | | | 5 | hard | | | |
| no_pomeriggio | classe | 1A | | | | | 12 | soft | 50 | | no dopo 12 |
| no_giorni_consecutivi | classe | 3B | | | | | | hard | | | |
| compresenza | classe | 4A | Scienze | | | | 2 | hard | | | lab |
| raw_dsl | globale | | | | | | | hard | | `forall t in teachers: teacher_max_consecutive(t.name, 4)` | tetto |

### Row → DSL/ORM mapping
- Resolve `nome`→owner_id (reuse `_resolve_owner_by_name`).
- ORM-insert types (via `POST /api/constraints` dispatcher): `indisponibilita`
  (expand `[ora_da..ora_a]` → TeacherUnavailability rows), `indisp_aula`,
  `pref_aula_*`, `compresenza` (CoteachGroup n_teachers=valore), `giorno_libero`,
  `pref_giorno_libero`.
- DSL types (via `POST /api/constraints/general`, using dsl_translator emitters so
  the string is guaranteed parseable): `max_ore_giorno`→`teacher_max_per_day`,
  `max_consecutive`→`teacher_max_consecutive`, `no_pomeriggio`→
  `slot_after_hour_penalty`, `no_giorni_consecutivi`→
  `no_same_class_consecutive_days`, `no_buchi`→`no_holes_class`,
  `presenza_ora`→`class_present_at_hour`, `raw_dsl`→verbatim.
- Plesso types need a small new sub-dispatcher → PlessoCommutingRule /
  PlessoEntityPolicy (the `/api/constraints` dispatcher doesn't cover them).
- Weight sign already centralized in `_normalise_weight`.

### Validation & warnings
1. Structural (parse-time): unknown tipo, bad livello, giorno∉1..6/lun..sab,
   ora∉8..13, missing required col per type, unresolved nome → per-row errors[].
2. DSL: `general_dsl.parse`+`validate` for raw_dsl + emitted pragmas.
3. **Solver-compat:** feed compile diagnostics to
   `engine/constraint_compat.summarize(pipeline=...)` → structured warnings[]
   ("rule not modeled by per-day CP; run a metaheuristic post-pass").
4. Optional post-import feasibility check (`/api/constraints/feasibility-check`).

### Implementation plan (effort)
1. `_vincoli_parser.py` (new) — workbook→rows, tipo→ORM/DSL mapper, range expansion,
   validation. **M.**
2. Endpoints `POST .../import-vincoli` + `GET .../template-vincoli` (3-sheet xlsx). **S–M.**
3. Plesso sub-dispatcher. **S.**
4. constraint_compat warning wiring. **S.**
5. Frontend "Vincoli (xlsx)" tab (extend ConstraintsImportExportCard) + warnings render. **S.**
6. Docs in `webui/docs/import_format.md`. **S.**

Most building blocks already exist; this is a controlled-vocabulary front over
`_create_constraint_via_dispatcher` + the dsl_translator emitters.

---

## 3. CSS / JS quality

### Styling system
- **Good:** Tailwind tokens (`ink`/`accent`/`brand`), `app.css` component layer
  (`.btn*`, `.card`, `.field`, `.pill*`, focus-ring), dark mode via CSS vars, skip
  link + sr-only.
- **Issues:** (a) **no shared `Button.svelte`** — button markup copy-pasted across
  50+ files, 348 `on:click`, no uniform loading/aria/focus; (b) **hardcoded inline
  hex colors** bypass tokens (GroupedEventsTable, RoomDropdown, FeasibilityPanel,
  EChart, DiagnosticResult) → drift + no dark mode; (c) repeated magic class strings;
  (d) EChart theme hardcoded, not token-driven.

### Buttons — improvements (ranked)
1. **`Button.svelte`** (variant primary/secondary/danger/icon, `loading` spinner,
   `disabled`, `ariaLabel`, always-on focus-ring). HIGH.
2. Migrate inline colors → Tailwind/semantic tokens. HIGH.
3. Loading spinners on async buttons (import/mock/run). MED.
4. Enforce focus-visible on all icon buttons. MED.
5. Icon-button + subtle variants. LOW.

### Dashboard — improvements
- No skeleton loaders (pills linger on stale values during refetch).
- RunLogPanel auto-scroll hijacks the user's manual scroll-up (only scroll if
  already at bottom).
- Cytoscape graph layout blocks UI 1–2s with no progress indicator.
- Aggressive 1.5s polling floor; header pills wrap awkwardly on tablet (`text-xs`,
  no `sm:` breakpoint).

### JS/Svelte
- TanStack Query: good (central keys, mutation-counter invalidation). 20+
  independent `createQuery` calls (noisy but cache-deduped).
- Polling/SSE timer can accumulate on rapid `runId` change (cleanup only on destroy)
  → use `$effect.pre` with explicit teardown.
- Drag-over handlers un-throttled (100×/s) on large timetables; no list
  virtualization (pagination caps at 250 but a 250-row drag is a 50–100ms paint).

### A11y + responsive
- Modal focus-trap + Esc good; dropdowns close on mouseleave only (no keyboard
  blur-close). Status via color only. `sm:` breakpoint nearly unused. Timetable grid
  640px min-width scrolls on phones. Drag-drop is mouse-only (no touch).

### Top quick wins
1. `Button.svelte` (HIGH).  2. Inline-color → token migration (HIGH).
3. Dashboard skeleton loaders (MED).  4. RunLogPanel scroll-preserve (MED).
5. Throttle drag-over (MED).  6. Empty-state banners (LOW).  7. `sm:` header pills.
8. Graph render spinner.  9. Refactor polling timers.  10. Keyboard-shortcut hints
   in WeeklyCalendarView.

---

## Suggested sequencing
1. **Tooltips + glossary** (this date) — cheap, fixes the "unexplained enums/terms"
   gap app-wide.
2. **`Button.svelte` + inline-color migration** — unblocks 50+ later UI fixes.
3. **`/import` page made functional** + **Vincoli xlsx language** — biggest
   onboarding ROI; backend mostly ready.
4. **Schedule drag-drop depth** (swap/undo/conflict drill-down).
5. Empty/loading/error-state pass + undo consistency.
