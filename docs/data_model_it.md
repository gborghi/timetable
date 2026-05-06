# Modello dati (sommario in italiano)

Entita' principali (modelli SQLAlchemy 2.0 in
`webui/backend/models.py`):

- `Teacher`, `SchoolClass`, `Subject`, `Classroom`,
  `Curriculum`, `Student`.
- `Assignment` (cattedra docente → classe/gruppo; porta
  `locked`, `coteach_group_id`, `is_support`,
  `is_potenziamento`, `parallel_group_id`, `group_id`).
- `CoteachGroup` (Task C1: gruppo di compresenza condivisa;
  punta a `class_id` o `group_id` -- XOR).
- `StudyGroup` + `GroupMembership` + `GroupSubjectHours`
  (Task C3: gruppi di studio inter-classe).
- `Solution`, `Lesson` (output del solver per slot;
  `Lesson.group_name` per C3).
- `*Unavailability`, `*Preference` (matrici a 5 stati:
  allowed/soft/hard/preferred/enforced).
- `LogicalUnavailability`, `CurriculumLogicalConstraint`,
  `GeneralConstraint` (vincoli DSL nei 4 kind: hard / soft /
  preferred / enforced).
- `Run` (riga di run asincrona con `status`, `metrics_json`,
  `current_step`).
- `SubjectGroupWeight` (input obiettivo Phase A).
- `Plesso`, `PlessoCommutingRule`, `PlessoEntityPolicy`
  (sedi multiple; commuting rule ed entity policy consumate
  dal solver di classroom-assignment).

## Sorgenti dei vincoli che alimentano la pipeline DSL

Dopo gli Step 2–3 del piano multi-day, il modulo
`engine/dsl_translator.py` traduce ogni tabella di vincoli
special-purpose in stringhe DSL canoniche:

| Tabella sorgente | Translator | Forma DSL |
|---|---|---|
| `TeacherUnavailability` | `teacher_unavailability_to_dsl` | `forall l in lessons where l.teacher==X and l.day==D and l.hour==H: false` |
| `ClassUnavailability` | `class_unavailability_to_dsl` | analogo, `l.class==X` |
| `ClassroomUnavailability` | `classroom_unavailability_to_dsl` | analogo, `l.classroom==X` |
| `TeacherMandatoryFreeDay` | `teacher_mandatory_free_day_to_dsl` | `count l in lessons where l.teacher==X and l.day==D == 0` |
| `CoteachGroup` | `coteach_group_to_dsl` | multi-clausola: per docente `count == n_hours` + uguaglianza di slot col principal |
| `PlessoCommutingRule` | `plesso_commuting_rule_to_dsl` | `forall l1 .. l1.classroom.plesso==P_A: forall l2 .. l2.classroom.plesso==P_B and consecutive(l1.slot, l2.slot): false` |
| (HARD legacy hardcoded) | `seed_implicit_hardcoded(profs)` | pragma canonici: `no_holes_class`, `class_present_at_hour`, `class_day_load_in`, `teacher_max_per_day`, `cattedra_max_per_day`, `subject_pair_must`, `subject_pair_exists` |

Il translator preserva un ordine di emissione stabile, quindi
l'ordine di costruzione del modello CP-SAT e' riproducibile
run-to-run. Una volta tradotto in DSL, ogni vincolo passa per
il singolo `DSLConstraintCompiler` (vedi `architecture_it.md`)
raggiungendo `MonolithicSolver`, `PhaseBDaySolver`, ogni
pricer di BP e ogni nodo Ryan-Foster in modo uniforme.

Per la trattazione estesa di ogni colonna e il mapping ORM
SQLAlchemy, vedi il capitolo `modello_dati.tex` del manuale
LaTeX (o il sommario inglese
`chapters_en/modello_dati.tex`).

---

> **Nota**: questo documento e' il sommario in italiano. Il
> sommario in inglese vive in `data_model.md`. La trattazione
> estesa e' nel manuale LaTeX sotto `docs/manual/chapters/`.
> Compila con `docs/build_manual.sh` per ottenere `manual.pdf`
> (italiano) e `manual_en.pdf` (inglese).
