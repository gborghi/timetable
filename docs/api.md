# API REST reference

Tutti gli endpoint sono sotto `/api/`. Il backend espone ~118 route
totali. Questo documento elenca i piu' rilevanti, raggruppati per
modulo. Per la specifica completa di request/response vedere le
Pydantic schemas in `webui/backend/schemas.py` e i singoli router in
`webui/backend/routers/`.

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

### Classrooms
`/api/classrooms`. Embed: `subject_prefs[]` (ClassroomSubjectPreference),
`class_prefs[]` (ClassroomClassPreference, con `is_home`),
`unavailability[]`. Sub:
`/api/classrooms/{id}/logical-unavailabilities`,
`/api/classrooms/suggested-counts` (counts proporzionali per la
mock recipe), `/api/classrooms/auto-generate` (run recipe).

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

### Assignments (cattedre)
`/api/assignments` -- list flat. `/api/assignments/by-class` --
group by class. `PUT /api/assignments/manual` (ManualAssignmentIn) --
modifica un'assegnazione e valida HARD. `POST /api/assignments/lock/{id}`
-- toggle locked. `DELETE /api/assignments/{id}`.

`GET /api/assignments/teachers-for-subject?subject=NAME` -- ritorna
i docenti abilitati con load corrente (`assigned_hours`, `max_hours`,
`available_hours`, `is_over`). Usato dal dropdown "cambia".

`GET /api/assignments/loads` -- summary per docente con status `ok`
/ `over` / `under` / `empty`. Usato dal pannello warnings.

### CoTeaching
`/api/coteaching` -- CRUD su `coteaching_rules`.

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
