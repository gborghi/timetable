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

The Italian source reference follows below; full English
translation is pending.

---

# API REST: come dialogare con piTantum dall'esterno

Tutto quello che la web app fa (creare un docente, lanciare il
solver, scaricare l'orario in xlsx) passa attraverso una serie di
indirizzi web — gli "endpoint" REST. Questa pagina elenca i piu'
importanti raggruppati per area, ed e' utile se vuoi:

- integrare piTantum con un altro sistema (per esempio importare
  automaticamente le anagrafiche dal registro elettronico);
- scrivere uno script per esportare i dati a fine anno;
- capire come la web app comunica con il backend.

Se invece vuoi solo usare piTantum dall'interfaccia web, puoi
ignorare questa pagina: la UI fa gi\`a tutte queste chiamate per
te.

> **Per chi sviluppa**: tutti gli endpoint sono sotto `/api/`. Il
> backend espone ~118 route totali. Per la specifica completa di
> request/response vedere le Pydantic schemas in
> `webui/backend/schemas.py` e i singoli router in
> `webui/backend/routers/`.

## Pattern generale

Ogni risorsa CRUD ha la stessa forma:

| Verbo  | Path                        | Descrizione                |
| ------ | --------------------------- | -------------------------- |
| GET    | `/api/<entity>`             | lista (q + sort)           |
| GET    | `/api/<entity>/{id}`        | dettaglio                  |
| POST   | `/api/<entity>`             | create                     |
| PUT    | `/api/<entity>/{id}`        | replace                    |
| DELETE | `/api/<entity>/{id}`        | delete                     |

`q` e' la stringa DSL del filtro; `sort` e' `field,asc:field2,desc`.

## Anagrafiche e CRUD

### Teachers
`/api/teachers` -- list / get / post / put / delete. Embed in body:
`subjects[]`, `unavailability[]`, `mandatory_free_days[]`,
`compatible_classes[]`, `classroom_prefs[]`. Vedere
`schemas.TeacherIn` / `TeacherOut`.

Sub-endpoint: `/api/teachers/{id}/logical-unavailabilities` (CRUD su
LogicalUnavailability filtrato per `entity_type=teacher`).

### Classes
`/api/classes`. Embed: `subjects[]`, `unavailability[]`. Sub:
`/api/classes/{id}/logical-unavailabilities`.

### Tecniche di ottimizzazione avanzate
Vedere `docs/optimization_strategies.md`.

- `POST /api/optimize/meta/{stage}` -- stage in
  `{lns, sa, ts, ils, alns, vns, lagrangian}`. Body: `MetaRunIn`
  esteso con campi specifici per ALNS (`alns_T0`, `alns_alpha`,
  `alns_destroy[]`, `alns_repair[]`), VNS (`vns_neighbourhoods[]`),
  Lagrangian (`lagrangian_max_iter`, `lagrangian_tolerance`,
  `lagrangian_alpha_0`).
- `POST /api/optimize/column-generation` -- async, body
  `{time_budget_s, patterns_per_teacher, mode, granularity,
   branching_strategy, max_iterations, bp_max_iterations,
   pricer_time_limit, pricer_workers, parallel, log}`.
  - `mode`: `iterative-diversified` (default) | `branch-and-price`
    | `auto`.
  - `granularity` (per BP): `auto` | `teacher` | `teacher-day` |
    `teacher-class` | `teacher-class-subject` | `teacher-subject`
    | `class` | `class-day` | `day` | `curriculum`. Each
    granularity has a dedicated CP-SAT pricer (CP-SAT is the
    fundamental minimisation; greedy supplies a `model.add_hint`
    warm-start only).
  - `branching_strategy`: `ryan_foster` (full recursive
    branching tree with Achterberg pair score, LP-bound prune,
    max_depth=20 / max_nodes=1000) | `variable` (no-op
    placeholder).
  - `bp_max_iterations` (default 8): cap on master+pricing
    rounds.
  - `pricer_time_limit` (default 5.0s): per CP-SAT sub-problem.
  - `pricer_workers` (default 2): CP-SAT search workers per
    sub-problem.
  - The engine additionally accepts (Python-only, not yet in the
    UI) `dual_stabilization` (default True), `dual_step_alpha`
    (0.2), `max_active_columns` (10000), `rc_smoothing_horizon`
    (20), `parallel_workers` (auto = `cpu_count() // 2`),
    `class_to_curriculum`.
- `POST /api/optimize/hall-check` -- back-compat alias di
  `/api/diagnostics/hall-check`.

### Diagnostica
- `POST /api/diagnostics/hall-check` -- pre-check Hall (sync).
- `POST /api/diagnostics/montecarlo` -- sensitivity MC.
- `POST /api/diagnostics/bipartite` -- modularita / betweenness /
  densita.
- `POST /api/diagnostics/correlations` -- 3 regressioni
  (statsmodels).
- `POST /api/diagnostics/distributions` -- 5 distribuzioni +
  KS / chi-quadro.

### Run telemetry
- `GET /api/optimize/runs/{id}/telemetry?limit=&offset=&phase=`
  -- serie temporale dei sample registrati dai moduli solver.
  Ogni entry: `{step, timestamp_s, phase, payload}`.
- `GET /api/optimize/runs/{id}/summary` -- aggregato per phase +
  serie objective pronta per ECharts.

### Bulk import (xlsx / csv)
- `POST /api/import/{entity}` -- multipart upload. Form:
  `file` (xlsx/csv), `mode` in `upsert|append|replace`,
  `sheet` (xlsx only). Restituisce `ImportReport(n_total_rows,
  n_inserted, n_updated, n_skipped, errors[])`.
  Entita' supportate: `teachers, subjects, classes, classrooms,
  curricula, students, groups`.
- `GET /api/import/{entity}/template` -- xlsx con 3 fogli
  (`Istruzioni`, `Esempi`, `Dati`). Dati e' il foglio che la
  POST legge per default.

Campi nuovi supportati negli importer:
  - **teachers**: `graduatoria_score`,
    `required_free_days_count`, `preferred_free_days_json`
  - **classes**: `max_hours_per_day`,
    `required_free_days_count`, `preferred_free_days_json`
  - **classrooms**: `tags` (CSV)
  - **students**: `tags` (CSV)

### Dashboard: Import/Export DB
- `GET /api/dashboard/export-db?schema_only=<bool>` -- restituisce
  un .zip con `database.db` (raw SQLite, quando applicabile),
  `tables/<t>.csv` per ogni tabella e `metadata.json` (contiene
  `schema_version`, `exported_at`, `tables`, `row_counts`,
  `csv_sha256`). Se `schema_only=true`, omette i CSV (utile come
  template per un'altra scuola).
- `POST /api/dashboard/import-db` -- multipart upload del .zip;
  sostituisce il DB live (SQLite-only). Salva una copia
  `timetable.db.pre_import_backup` accanto al DB. Verifica che
  metadata.json abbia `kind == "pitantum-db-export"`.
- `POST /api/dashboard/snapshot/create` -- salva uno snapshot
  timestampato in `webui/data/snapshots/` (stesso formato del
  GET export-db).
- `GET /api/dashboard/snapshot/list` -- lista snapshot:
  `[{filename, size_bytes, modified_at}]`.
- `POST /api/dashboard/snapshot/restore/{filename}` -- ripristina
  lo snapshot indicato.
- `DELETE /api/dashboard/snapshot/{filename}` -- elimina uno
  snapshot.

### Saved views
- `GET /api/saved-views?entity=<entity>` -- lista viste salvate
  (filtrabile per entita').
- `POST /api/saved-views` -- body
  `{entity, name, dsl_query?, sort_levels: [{column, direction}]}`.
  409 se esistente.
- `PUT /api/saved-views/{id}` -- aggiorna nome / dsl_query /
  sort_levels / description.
- `DELETE /api/saved-views/{id}` -- elimina.

Entita' valide: teachers, classes, classrooms, subjects, students,
groups, curricula, constraints, monitor.

### Esportazione liste

Tutti gli endpoint di lista qui sotto (`/api/teachers`,
`/api/classes`, `/api/classrooms`, `/api/subjects`,
`/api/students`, `/api/groups`, `/api/curricula`) accettano un
parametro `format=xlsx|csv` che sostituisce la risposta JSON con
un file binario:

- `format=xlsx` -- workbook openpyxl (header colorato, auto-fit
  colonne)
- `format=csv`  -- UTF-8 con BOM (Excel italiano), separatore `,`,
  CRLF, RFC 4180

I filtri `q=` e `sort=` sono applicati prima dell'export, quindi
il file rispecchia esattamente la vista che l'utente sta
guardando. Filename automatico:
`<entita>_YYYYMMDD_HHMMSS.<ext>`.

### Classrooms
`/api/classrooms`. Embed: `subject_prefs[]` (ClassroomSubjectPreference),
`class_prefs[]` (ClassroomClassPreference, con `is_home`),
`unavailability[]`, `tags[]` (lista di nomi tag in minuscolo). Sub:
`/api/classrooms/{id}/logical-unavailabilities`,
`/api/classrooms/suggested-counts` (counts proporzionali per la
mock recipe), `/api/classrooms/auto-generate` (run recipe).

Sul POST/PUT, `tags: list[str]` viene riconciliato con la tabella
`classroom_tags`: i nomi sconosciuti vengono creati al volo
(`name` viene normalizzato a lowercase), quelli rimossi dal payload
hanno l'assignment cancellato. La cardinalita' e' M-N: un tag puo'
appartenere a tante aule e una aula puo' avere tanti tag.

### Classroom tags
- `GET /api/classroom-tags` -- lista globale; ogni voce include
  `n_classrooms` (aule che usano il tag), utile per warning prima
  della cancellazione.
- `POST /api/classroom-tags` -- body `{name: string, description?:
  string}`. 409 se gia' esistente.
- `PUT /api/classroom-tags/{id}` -- rinomina o aggiorna descrizione;
  cambia il nome anche per tutte le aule che lo referenziano (i join
  vanno per id, non per stringa).
- `DELETE /api/classroom-tags/{id}` -- cascata: rimuove gli
  `ClassroomTagAssignment` collegati.

### Subjects
`/api/subjects`. Embed: `classroom_prefs[]`. Sub:
`/api/subjects/group-weights` (GET / PUT bulk replace dei
`subject_group_weights`).

### Curricula
`/api/curricula`. Embed: `hours[]` (CurriculumSubjectHours). Sub:
`/api/curricula/{id}/logical-constraints` (CRUD).

### Students, Groups
`/api/students`, `/api/groups`. Standard CRUD. Groups embedda
`student_ids[]` e `subject_hours[]`.

`POST/PUT /api/students` accetta `tags: list[str]`, riconciliato
con `student_tags` (i nomi sconosciuti vengono creati lower-case
al volo). `GET /api/students` espone `tags[]` per ogni studente.

Sub-endpoint:
- `GET /api/students/by-tags?any_of=BES,DSA&all_of=tag1,tag2` --
  ritorna gli studenti che matchano il filtro tag. Usato dal
  pannello "Precompila da tag" della scheda gruppi.

### Student tags
- `GET /api/student-tags` -- lista globale; ogni voce include
  `n_students` (conteggio).
- `POST /api/student-tags` -- body `{name, description?}`.
  409 se esistente.
- `PUT /api/student-tags/{id}` -- rinomina e/o aggiorna descrizione.
- `DELETE /api/student-tags/{id}` -- cascata: rimuove gli
  `StudentTagAssignment` collegati.

### Assignments (cattedre)
`/api/assignments` -- list flat. `/api/assignments/by-class` --
group by class (chiavi sintetiche `__potenziamento__` per le
cattedre Legge 107 e `__group_<group_name>__` per le cattedre
Task C3 agganciate a uno StudyGroup). `PUT /api/assignments/manual`
(ManualAssignmentIn) -- modifica un'assegnazione e valida HARD.
`POST /api/assignments/lock/{id}` -- toggle locked.
`DELETE /api/assignments/{id}`.

**ManualAssignmentIn (estesa per C3)**:
```json
{
  "class_name": "2A" | "",   // richiesto se target_kind='class'
  "subject": "Matematica",
  "teacher_name": "Rossi",
  "locked": true,
  "target_kind": "class" | "group",   // default 'class'
  "group_name": "_GruppoSpa_" | null, // richiesto se target_kind='group'
  "hours": 3 | null            // richiesto se target_kind='group'
}
```
Quando `target_kind='group'`:
- `class_id` dell'Assignment risultante e' NULL.
- `group_id` punta a `StudyGroup` con `name == group_name`.
- `hours` viene preso dal payload (per le cattedre-classe le ore
  vengono prese da `class_subjects.hours_per_week`).
- Vincolo XOR validato sia client-side (modale `/assignments`)
  che server-side (`optimization.manual_assignment`).

**Output esteso** (`new_assignment`):
```json
{
  "id": 42, "teacher_id": 7, "teacher_name": "Rossi",
  "class_id": null, "class_name": null,
  "group_id": 3, "group_name": "_GruppoSpa_",
  "subject": "Spagnolo", "hours": 3, "locked": false
}
```

`GET /api/assignments/teachers-for-subject?subject=NAME` -- ritorna
i docenti abilitati con load corrente (`assigned_hours`, `max_hours`,
`available_hours`, `is_over`). Usato dal dropdown "cambia".

`GET /api/assignments/loads` -- summary per docente con status `ok`
/ `over` / `under` / `empty`. Usato dal pannello warnings.

### CoTeaching
`/api/coteaching` -- CRUD su `coteaching_rules` (LEGACY).
La nuova entita' canonica e' `coteach_groups` (Task C1+C3): gestita
attraverso il form `/assignments` quando i membri vengono aggiunti
con `coteach_group_id` settato. Una `CoteachGroup` puo' avere come
target una classe (`class_id`) oppure uno StudyGroup (`group_id`,
Task C3, XOR con class_id).

### Groups (StudyGroup, Task C3)
`/api/groups` -- CRUD su `study_groups`. Endpoint:
- `GET /api/groups` -- lista. Filtri DSL come per altri tab,
  pagination, sort. Restituisce `n_students` e `n_classes_touched`.
- `GET /api/groups/{id}` -- dettaglio singolo con `student_ids[]`,
  `subject_hours[]`.
- `POST /api/groups` (StudyGroupIn) -- crea.
- `PUT /api/groups/{id}` -- aggiorna (sostituisce `student_ids`
  e `subject_hours`).
- `DELETE /api/groups/{id}` -- cascade delete su memberships e
  subject_hours.

**StudyGroupIn**:
```json
{
  "name": "Spagnolo 2A+2B",
  "nickname": "ESP",
  "kind": "language",
  "description": "Seconda lingua, gruppo articolato cross-class",
  "student_ids": [12, 47, 88, ...],
  "subject_hours": [{"subject": "Spagnolo", "hours_per_week": 3}]
}
```

Per agganciare una cattedra al gruppo: `PUT /api/assignments/manual`
con `target_kind='group'`, `group_name=<name>`, `hours=N`. Il solver
schedulera' le N ore con il vincolo classi-madre busy.

## Dataset / mock / import

### Profilo / mock
- `GET /api/dataset/state` -- counts globali.
- `GET /api/dataset/available-profiles` -- lista profili snapshot in
  `experiments/` con flags `has_profs`, `has_optimized_solution`,
  `has_decomposed_solution`.
- `POST /api/dataset/import-profile` (ImportPickleIn): importa un
  pickle di profilo + opzionalmente seed di curricula, aule, studenti.
- `POST /api/dataset/mock` (MockGenIn): genera scuola mock fresca.
- `POST /api/dataset/upload-pickle?kind=school|profs|solution` con
  multipart file.
- `POST /api/dataset/clear?scope=all|solutions|assignments` -- wipe.

### Excel/CSV import
- `POST /api/import/{entity}` con multipart `file` + form `mode`.
  `entity` in {teachers, subjects, classes, classrooms, curricula,
  students, groups}.
- `GET /api/import/{entity}/template` -- scarica xlsx template.

## Vincoli

### Logical (per teacher / class / classroom)
- `GET /api/{teachers|classes|classrooms}/{id}/logical-unavailabilities`
- `POST /api/{...}/{id}/logical-unavailabilities` (LogicalUnavIn:
  `expression`, `kind`, `is_hard`, `soft_penalty`)
- `PUT /api/{...}/{id}/logical-unavailabilities/{rule_id}`
- `DELETE /api/{...}/{id}/logical-unavailabilities/{rule_id}`
- `POST /api/logic/validate` -- test-parse helper.

### Curriculum logical
- `GET /api/curricula/{cid}/logical-constraints`
- `POST /api/curricula/{cid}/logical-constraints`
  (CurriculumLogicalConstraintIn: + `year_filter`, `label`)
- `PUT  /api/curricula/{cid}/logical-constraints/{rid}`
- `DELETE /api/curricula/{cid}/logical-constraints/{rid}`

### Bulk operations
- `POST /api/bulk/{entity}/dry-run` (BulkRequest:
  `entity_ids[]`, `action`, `payload`, `on_conflict`) -- ritorna
  candidates / conflicts.
- `POST /api/bulk/{entity}/apply` -- persiste con
  `on_conflict=override|skip`.

`entity` in {teachers, classes, classrooms}. `action` in
{`add_logical`, `set_field`, `add_unavailability`}.

## Schedule / orario

- `GET /api/schedule/by-class` -- `{classes:[], grid:{class:{day:{hour:cell}}}}`
- `GET /api/schedule/by-teacher` -- analogo per docente
- `GET /api/schedule/by-room` -- `{rooms:[], rooms_meta:{}, grid}`
- `GET /api/schedule/by-slot?day=D&hour=H`
- `GET /api/schedule/free-now?day=D&hour=H` (legacy, sostituita da
  /api/coverage)
- `PUT /api/schedule/move-lesson` (MoveLessonIn:
  `teacher_name`, `class_name`, `subject`, `src_day`, `src_hour`,
  `dst_day`, `dst_hour`) -- valida e applica drag-drop. Risposta
  MoveLessonOut con `accepted`, `reason`, `obj_before/after`,
  `delta`, `metrics_*`, `room_cleared`, `cleared_room`.
- `POST /api/schedule/move-preview` (`{lesson_id}` o `{src}` +
  `candidate_slots`) -- ritorna risultati per i 36 slot.
- `PUT /api/schedule/lesson/{lesson_id}/classroom?classroom_name=NAME`
- `POST /api/schedule/solutions/{id}/activate`
- `DELETE /api/schedule/solutions/{id}`
- Export: `/api/schedule/export/xlsx-classes`, `xlsx-teachers`,
  `pdf-classes`, `pdf-teachers`.

## Coverage (assenze e supplenze)

- `GET /api/coverage/week?week_start=YYYY-MM-DD` -- matrice 6x6 con
  status e counts.
- `GET /api/coverage/cell?date=...&day=D&hour=H` -- uncovered + available.
- `GET /api/absences?date=...&week_start=...`
- `POST /api/absences` (AbsenceIn)
- `DELETE /api/absences/by-id/{aid}`
- `DELETE /api/absences?date=YYYY-MM-DD` -- clear giornata.
- `POST /api/substitutions` (SubstituteIn)
- `DELETE /api/substitutions/{sid}`

## Optimization

Tutti questi sono async: ritornano `{run_id}` e il client poll/streama
i log via `/api/optimize/runs/{run_id}/stream` (SSE).

- `POST /api/optimize/assignment` (AssignmentRunIn)
- `POST /api/optimize/phase-b` (PhaseBRunIn)
- `POST /api/optimize/lns | sa | ts | ils` (MetaRunIn)
- `POST /api/optimize/full` (FullPipelineIn)
- `POST /api/optimize/classroom-assignment` (ClassroomAssignRunIn)
- `POST /api/optimize/place-event` (PlaceEventIn:
  `event_ids: [int]`, `lock_mode: "all_others_locked" |
  "same_class_or_teacher_movable" | "all_others_movable"`,
  `prefer_pref?: bool`) -- greedy HARD-feasible placer per le
  cattedre selezionate. Usato da "Piazza" / "Piazza selezionati"
  in /monitor.
- `GET /api/optimize/runs` -- lista
- `GET /api/optimize/runs/{id}` -- dettaglio
- `GET /api/optimize/runs/{id}/stream` -- SSE log streaming

## Monitor / vincoli

- `GET /api/monitor/events` -- una riga per Assignment con info di
  completezza (assigned_hours, missing_hours, missing_room,
  group_name, missing_group, is_complete, status). Filtra/ordina
  via DSL.
- `GET /api/monitor/event-rows?q=...&sort=...` -- granularita' di
  lezione: una riga per ogni Lesson schedulata + una placeholder
  per ogni "ora mancante" di cattedra. Espone `is_locked`,
  `is_scheduled`, `is_complete`, `day_name`, etc. Driver del
  /monitor con tabs Tutti/Incompleti/Lockati e dei controlli
  multi-livello sort + DSL query.
- `GET /api/monitor/incomplete-events` -- shortcut sui placeholder.
- `GET /api/monitor/summary` -- counts globali, incluso `n_rows`,
  `n_rows_unscheduled`, `n_rows_locked` per i tab badge.
- `GET /api/monitor/event/{aid}/lessons` -- dettaglio lezioni di
  una cattedra.
- `PUT /api/monitor/event/{aid}/lesson/{lid}` (LessonReassignIn:
  `day?`, `hour?`, `classroom_name?`, `on_conflict`) -- sposta
  una singola lezione. `on_conflict` in
  {`dry_run`, `cancel`, `unbind`, `delete`} (alias retro-compat
  `unassign` / `optimize` mappano a `delete`).
- `POST /api/monitor/event` (AddEventIn) -- crea una nuova cattedra
  (con possibile lezione iniziale) anche con `force=true` per
  forzare la creazione di una lezione orfana se la cattedra esiste
  gia' di un altro docente.
- `POST /api/monitor/event/{aid}/dissociate` -- elimina TUTTE le
  lezioni di una cattedra preservando l'Assignment.
- `POST /api/monitor/events/dissociate-batch` body
  `{event_ids: [int]}` -- versione bulk.
- `POST /api/monitor/event/{aid}/lock` body `{locked: bool}` --
  set/unset Assignment.locked. Le run di Phase B / metaeuristiche
  snapshot+restore le lezioni lockate.
- `POST /api/monitor/events/lock-batch` body
  `{event_ids: [int], locked?: bool}`. Se `locked` e' omesso, il
  backend computa il toggle: lock all if any unlocked, else
  unlock all.
- `DELETE /api/monitor/lesson/{lesson_id}` -- elimina una singola
  Lesson preservando la cattedra.
- `DELETE /api/monitor/event/{aid}` -- elimina la cattedra E tutte
  le sue lezioni.
- `GET /api/monitor/constraints` -- lista flat di tutti i vincoli
  editabili.
- `GET /api/monitor/conflicts` -- detector best-effort di conflitti.
- `DELETE /api/monitor/constraints/{kind}/{id}` -- cancella la
  underlying row (kind in {teacher_cell, class_cell, room_cell,
  logical_teacher, logical_class, logical_classroom,
  logical_curriculum, coteach, subject_room_pref,
  teacher_room_pref}).
- `PUT /api/monitor/constraints/{kind}/{id}` (ConstraintPatchIn:
  `level?`, `weight?`, `expression?`, `reason?`,
  `owner_id?`, `secondary_owner_id?`, `subject?`).

### Unified constraint creation

- `POST /api/constraints/feasibility-check` body
  `{time_limit_s?: float = 30}` -- esegue l'analisi MUS dei vincoli
  HARD/ENFORCED. Risposta:
  ```
  {
    feasible: bool | null,            # null = solver inconclusivo
    n_constraints: int,
    n_assignments: int,
    time_s: float,
    cores: [
      {
        id: int,
        kind: "matrix_hard_enforced" | "cpsat_unsat_core" | ...,
        reason: str,
        members: [
          { db_kind: str, db_id: int, level: str, scope: str,
            owner_name: str, detail: str },
          ...
        ],
      }, ...
    ],
    suggested_removal: [
      { db_kind, db_id, level, scope, owner_name, detail, reason },
      ...
    ],
  }
  ```
- `POST /api/constraints/delete-batch` body
  `{items: [{kind: str, id: int}, ...]}` -- bulk delete. Skip
  silenzioso su kind sconosciuti / id mancanti; ritorna
  `{deleted, skipped}`.
- `POST /api/constraints` (`ConstraintCreateIn`) -- dispatcher unico
  per creare vincoli da zero. Usato dal wizard "Nuovo vincolo" in
  `/constraints`. Payload polimorfo:
  ```
  {
    scope:    "teacher"|"class"|"classroom"|"curriculum"|
              "subject_room"|"teacher_room",
    kind:     "matrix_slot"|"logical"|"room_pref"|"coteach",
    level:    "hard"|"soft"|"preferred"|"enforced"|"allowed"|"forbidden",
    weight?:  int,
    owner_id?: int,                  # entita' principale (id)
    owner_id_2?: int,                # solo per teacher_room
    # matrix_slot
    day?: int, hour?: int, reason?: str,
    # logical
    expression?: str, label?: str, year_filter?: int,
    # subject_room / coteach
    subject?: str,
    # coteach
    n_teachers?: int, teacher_csv?: str,
  }
  ```
  Dispatch:
  - `(teacher|class|classroom, matrix_slot)` -> `*Unavailability`
  - `(teacher|class|classroom, logical)` -> `LogicalUnavailability`
  - `(curriculum, logical)` -> `CurriculumLogicalConstraint`
  - `(subject_room, room_pref)` -> `ClassroomSubjectPreference`
  - `(teacher_room, room_pref)` -> `TeacherClassroomPreference`
  - `(class, coteach)` -> `CoTeachingRule`

  Risposta: `{ok, kind, id, scope, detail}`. Se la combinazione
  esiste gia' (e.g. una cella matrix_slot per lo stesso slot), il
  dispatcher fa upsert (modifica i campi mantenendo l'id).

## Esempi curl

```bash
# stato dataset
curl http://127.0.0.1:8000/api/dataset/state

# import small con tutti i pool
curl -X POST -H "Content-Type: application/json" \
  -d '{"profile":"small","use_optimized":true,
       "import_curricula":true,"import_classrooms":true,
       "import_students":true}' \
  http://127.0.0.1:8000/api/dataset/import-profile

# aggiungi vincolo logico HARD a un docente
curl -X POST -H "Content-Type: application/json" \
  -d '{"expression":"mai aula:LabFisica@mar","kind":"hard"}' \
  http://127.0.0.1:8000/api/teachers/15/logical-unavailabilities

# bulk dry-run su 3 classi
curl -X POST -H "Content-Type: application/json" \
  -d '{"entity_ids":[1,2,3],"action":"add_logical",
       "payload":{"expression":"lun8 AND lun9","is_hard":true,
                  "soft_penalty":100},
       "on_conflict":"dry_run"}' \
  http://127.0.0.1:8000/api/bulk/classes/dry-run

# coverage settimana
curl 'http://127.0.0.1:8000/api/coverage/week?week_start=2026-04-27'

# event lessons
curl http://127.0.0.1:8000/api/monitor/event/1/lessons
```
