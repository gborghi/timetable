# Modello dati

Tutto vive in `webui/backend/models.py` (SQLAlchemy 2.0). La persistenza
e' SQLite (`webui/data/timetable.db`). Le migrazioni idempotenti sono
in `webui/backend/db.py::_apply_lightweight_migrations`.

## Tabelle principali

### Anagrafiche

- **subjects** -- materie. SOFT preferences: `distribute_days_weight`,
  `dual_hours_weight`, `no_sixth_hour_weight`, `preferred_band_*`.
- **teachers** -- docenti. Campi name (chiave engine, unique),
  `last_name`, `first_name`, `nickname` (display nell'orario);
  `matricola`, `group` (classe di concorso), `max_hours`,
  `completion_hours`, `exemption_hours`,
  `graduatoria_score` (Float nullable, range tipico 0-300, usato dal
  preset Phase-A "Anzianita'"), `free_day` (string, day name; legacy
  single-day field), `preferred_free_days_json` (TEXT JSON, fino a 3
  preferenze ordinate `[{day:1..6, is_hard:bool, soft_penalty:int|null}]`;
  HARD blocca le 6 ore del giorno via auto-fill in
  `teacher_unavailability`, SOFT applica `soft_penalty` per ora
  occupata), `required_free_days_count` (INT 0-6, default 1, HARD:
  numero esatto di giorni liberi a settimana — CCNL italiano = 1),
  `max_consecutive`, `pref_no_buchi_weight`, `pref_no_five_weight`,
  `pref_no_one_weight`, `preferred_days_csv`. Relazioni:
  `teacher_subjects`, `teacher_unavailability`,
  `teacher_mandatory_free_days`, `teacher_compatible_classes`,
  `teacher_class_preferences`, `teacher_curriculum_preferences`.
- **school_classes** (free-day fields, oltre ai base):
  - `preferred_free_days_json` -- TEXT JSON con lista di max 3
    preferenze ordinate `[{day:1..6, is_hard:bool, soft_penalty:int|null}]`.
    HARD blocca le 6 ore del giorno via auto-fill della matrice
    `class_unavailability`; SOFT applica `soft_penalty` per ora
    occupata.
  - `required_free_days_count` -- INTEGER, default 0, range 0-6.
    HARD: numero esatto di giorni liberi a settimana per la
    classe. Default 0 (le classi italiane lavorano lun-sab).
  - `max_hours_per_day` -- INTEGER, default 5, range 1-7.
    HARD: massimo numero di ore in un singolo giorno. Sostituisce
    il vecchio default fisso. Aumentare a 6 o 7 quando la classe
    ha giorni liberi da compensare.

- **school_classes** -- classi. `name` (e.g. "1A_Scientifico"),
  `nickname` (display), `year`, `section`, `curriculum` (string legacy),
  `curriculum_id` (FK opzionale a curricula -- normalizzazione),
  `n_students`, 7 boolean HARD-toggles (no buchi, max 6 ore/giorno,
  doppia mat, doppia ita, motorie a coppie, ingresso 8, uscita post-12)
  + `soft_minimize_sixth_weight`. Relazioni: `class_subjects`,
  `class_unavailability`, `coteaching_rules`.
- **classrooms** -- aule. `kind` (standard / lab_chimica / lab_fisica /
  lab_informatica / lab_linguistico / palestra / biblioteca /
  aula_speciale), `capacity`, flag `multi_class` con
  `multi_class_max` e `multi_class_pref` (per palestre/biblioteche).
  Relazioni: `classroom_subject_preferences`,
  `classroom_class_preferences`, `classroom_unavailability`,
  `classroom_tag_assignments`.
- **classroom_tags** -- etichette globali (many-to-many con `classrooms`
  via `classroom_tag_assignments`). `name` UNIQUE in minuscolo,
  `description` opzionale. Esempi: `lab`, `fisica`, `matematica`,
  `scientifico`, `proiettore`. Esposti dalla DSL come
  `l.classroom.tags` (lista) e tramite il predicato
  `has_tag(<name>)` nelle liste; vedi `general_dsl.md`.
- **classroom_tag_assignments** -- riga di join `(classroom_id, tag_id)`,
  UNIQUE su `(classroom_id, tag_id)`, ON DELETE CASCADE da entrambi i
  lati.
- **curricula** -- indirizzi di studio (Scientifico, Linguistico, ITIS, ...).
  `code` (machine name), `name` (display), `description`, `score`
  (peso ingegnerizzato dal motore mock). Relazioni:
  `curriculum_subject_hours` (la "matrice oraria" per anno),
  `curriculum_logical_constraints`.
- **students** -- studenti. Identita' `(last_name, first_name, birth_date)`
  unica, `student_code` opzionale, `class_id` FK opzionale,
  `nickname` opzionale.
- **study_groups** -- gruppi articolati (type-C: studenti da una o piu'
  classi, raggruppati per certe materie). `kind` in {splitting / language
  / religion / support / other}. Relazioni: `group_memberships`,
  `group_subject_hours`.

### Assegnazione

- **class_subjects** -- ore-per-materia di una specifica classe
  (denormalizza un curriculum_subject_hours quando l'utente vuole
  override per-classe). Unique `(class_id, subject)`.
- **curriculum_subject_hours** -- griglia canonica di un indirizzo:
  Unique `(curriculum_id, year, subject)`. Esempio per Scientifico
  anno 1: Matematica 5, Italiano 4, ...
- **teacher_subjects** -- abilitazioni per materia.
- **subject_group_weights** -- mapping `subject -> classe-di-concorso ->
  weight`. Riproduce in DB il `cconcorsopersubject` dei pickle storici.
- **assignments** -- *cattedre*: una riga per `(teacher, class, subject)`
  con `hours` e `locked`. Unique `(class_id, subject)`.

### Disponibilita' / vincoli

- **teacher_unavailability**, **class_unavailability**,
  **classroom_unavailability** -- celle (day, hour) con `state` in
  {hard, soft, preferred, enforced}, `soft_penalty` int signed (positive
  per soft, negative per preferred, ignorato per hard/enforced).
- **logical_unavailabilities** -- vincoli disgiuntivi DNF, comuni a
  teacher / class / classroom. Discriminatore `entity_type`. Campo
  `kind` in {hard, soft, preferred, enforced}; `expression` testuale,
  `parsed_dnf_json` per il solver.
- **curriculum_logical_constraints** -- analoghi ai logical, ma a
  livello di indirizzo, opzionalmente filtrati per `year_filter`.
- **classroom_subject_preferences** -- preferenza materia <-> aula con
  `state` in {allowed, soft, preferred, forbidden, enforced}, `weight`
  signed. Backwards-compat: il campo `required` resta in sync con
  `state == enforced`.
- **teacher_classroom_preferences** -- preferenza docente <-> aula con
  stessi 5 stati.
- **teacher_class_preferences** -- *Phase-A only*: preferenza
  docente <-> classe specifica. 5 stati (allowed / soft / preferred /
  forbidden / enforced) + `soft_penalty` Float. Unique `(teacher_id,
  class_name)`. HARD `forbidden` esclude la classe dalle assegnabili
  per quel docente; HARD `enforced` impone almeno una materia
  compatibile della classe a quel docente. Non influisce su Phase B.
- **teacher_curriculum_preferences** -- *Phase-A only*: come sopra
  ma a livello di indirizzo (`curriculum_code`). HARD `forbidden`
  esclude TUTTE le classi di quell'indirizzo dal docente.
- **coteaching_rules** -- compresenze: per `(class, subject)` la
  lezione e' co-tenuta da `n_teachers` docenti, `required` (HARD/SOFT),
  `weight`, `teacher_csv` opzionale.

### Soluzioni e scheduling

- **solutions** -- una riga per soluzione salvata. `obj_value`,
  `metrics_json`, `is_active`, `kind` (phase_b / lns / sa / ts / ils /
  manual / imported).
- **lessons** -- una riga per ora di lezione `(solution_id, teacher_name,
  class_name, subject, day, hour)` con `classroom_name` opzionale e
  `cotaught_with` (CSV di docenti aggiuntivi).
- **day_counts** -- cache della Phase A: conteggio per
  `(solution, teacher, class, subject, day)`. Usato dal repair durante
  il drag-and-drop.

### Assenze e supplenze (modulo coverage)

- **absences** -- una riga per `(teacher_id, date)` con `reason`, `notes`.
- **substitute_assignments** -- supplente assegnato a uno specifico
  `(date, day, hour, class_name)` per coprire il buco di un docente
  assente.

### Run / log

- **runs** -- ogni job di ottimizzazione. `kind` (mock / import /
  assignment / phase_b / lns / sa / ts / ils / full / export),
  `status` (pending / running / done / failed), `params_json`,
  `progress`, `obj_value`, `metrics_json`, `error`.
- **run_logs** -- log linee per run, indicizzato per `seq`, streamabile
  via SSE.

### Misc

- **app_state** -- key/value singleton (impostazioni app).

## Relazioni rilevanti

```
   subjects ----+
                |
                v
   teachers <-- teacher_subjects ---- subject_group_weights
       |
       +--+ teacher_unavailability
       +--+ teacher_mandatory_free_days
       +--+ teacher_compatible_classes
       +--+ teacher_classroom_preferences ---- classrooms
       |
       v
   assignments
       ^
       |
   school_classes ---- curricula
       |        \
       |         \--- curriculum_subject_hours
       |         \--- curriculum_logical_constraints
       |
       +--+ class_subjects
       +--+ class_unavailability
       +--+ coteaching_rules
       +--+ classroom_class_preferences (home)
       +--+ students -> group_memberships -> study_groups -> group_subject_hours
       |
       v
   solutions
       |
       +--+ lessons
       +--+ day_counts

   logical_unavailabilities (discriminator entity_type)
   classroom_subject_preferences (state-based)
   absences -> substitute_assignments
   runs -> run_logs
```

## Migrazioni idempotenti

`init_db()` (in `db.py`) fa:

```python
Base.metadata.create_all(bind=engine)   # crea tabelle nuove
_apply_lightweight_migrations()         # ALTER TABLE idempotenti
```

`_apply_lightweight_migrations` aggiunge colonne nuove a tabelle gia'
esistenti, sotto guard `PRAGMA table_info`. Pattern:

```python
if insp.has_table("school_classes") \
        and not has_column("school_classes", "curriculum_id"):
    conn.execute(text(
        "ALTER TABLE school_classes ADD COLUMN curriculum_id INTEGER"
    ))
```

Ad oggi la migrazione gestisce: `school_classes.curriculum_id`,
`teachers.last_name/first_name`, `nickname` su {teachers, students,
school_classes, study_groups}, `state` su `classroom_subject_preferences`
(con back-fill da `required`/`weight`), `kind` su
`logical_unavailabilities` e `curriculum_logical_constraints` (con
back-fill da `is_hard` + segno di `soft_penalty`).

Quando aggiungi una colonna nuova, segui lo stesso pattern: il DB
preesistente sopravvive senza interventi manuali.

## Formato pickle dell'engine

`webui/backend/engine_io.py` converte fra DB e pickle. Le tre forme
principali:

```python
school = {
  'profile':   str,
  'classes':   [{name, year, section, curriculum, subjects:{subj:ore}}],
  'teachers':  [{name, group, max_hours, free_day, weights:{subj:int}}],
  'cconcorsopersubject': {subj: {group: weight}},
  'curriculum_scores':   {curriculum: int},
  'curricula':           [...],   # full grid + score (added)
  'students':            [...],   # mock students (added)
  'groups':              [...],   # study groups (added)
}
profs = {
  teacher_name: {
    'classi':  {class_name: {subject: {'ore': N}}},
    'glibero': [d1, d2, d3]    # giorni liberi (1..6)
  }
}
solution = {(prof, class, subj, day, hour): 0|1}
```

Le funzioni chiave: `school_dict_from_db`, `profs_dict_from_db`,
`cattedre_from_assignments`, `import_school_into_db`,
`import_profs_into_db`, `import_solution_into_db`,
`replace_solution_lessons` (preserva classroom_name/cotaught_with su
sostituzione, vedi [workflow.md](workflow.md) per il caso del move).

## File pickle a riposo

In `experiments/` ci sono snapshot per i 5 profili:

- `school_<profile>.pkl` -- school dict
- `profs_<profile>.pkl` -- profs dict
- `solution_timetable_<profile>.pkl` -- soluzione raw Phase B
- `solution_timetable_<profile>_decomposed.pkl` -- post-decomposizione
- `solution_timetable_<profile>_optimized.pkl` -- post metaeuristiche
- `phase_a_dc_<profile>.pkl` -- day counts della Phase A
- `history_<profile>.pkl` -- pickle di history per la metaeuristica
- `curricula.pkl` -- esportato da `seed_curricula.py`

Questi pickle sono il deliverable storico del solver (precede la
webapp); la dashboard "Importa profilo" li converte in DB rows.

## Vincoli di unicita' importanti

- `subjects.name` UNIQUE
- `teachers.name` UNIQUE
- `school_classes.name` UNIQUE
- `classrooms.name` UNIQUE
- `curricula.code` UNIQUE
- `students(last_name, first_name, birth_date)` UNIQUE
  (si ammettono omonimi se la data di nascita differisce)
- `assignments(class_id, subject)` UNIQUE
  (al massimo una cattedra per coppia)
- `class_subjects(class_id, subject)` UNIQUE
- `curriculum_subject_hours(curriculum_id, year, subject)` UNIQUE
- `teacher_unavailability(teacher_id, day, hour)` UNIQUE
- ...e analoghi per le altre matrici.

Le UNIQUE sono enforced a livello SQLAlchemy + a livello router con
checks pre-insert per messaggi di errore parlanti (es. "esiste gia' un
docente con questo nome").
