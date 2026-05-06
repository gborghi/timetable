# Data model (English summary)

Core entities (SQLAlchemy 2.0 models in
`webui/backend/models.py`):

- `Teacher`, `SchoolClass`, `Subject`, `Classroom`, `Curriculum`,
  `Student`.
- `Assignment` (teacher → class/group cattedra; carries `locked`,
  `coteach_group_id`, `is_support`, `is_potenziamento`,
  `parallel_group_id`, `group_id`).
- `CoteachGroup` (Task C1: shared compresenza grouping; can
  target a `class_id` or a `group_id` -- XOR).
- `StudyGroup` + `GroupMembership` + `GroupSubjectHours`
  (Task C3: cross-class study groups).
- `Solution`, `Lesson` (per-slot output of the solver;
  `Lesson.group_name` for C3).
- `*Unavailability`, `*Preference` matrices (5-state:
  allowed/soft/hard/preferred/enforced).
- `LogicalUnavailability`, `CurriculumLogicalConstraint`,
  `GeneralConstraint` (4-kind DSL constraints: hard / soft /
  preferred / enforced).
- `Run` (async run row with `status`, `metrics_json`,
  `current_step`).
- `SubjectGroupWeight` (Phase A objective inputs).
- `Plesso`, `PlessoCommutingRule`, `PlessoEntityPolicy`
  (multi-site campuses; commuting rules and entity policies
  consumed by the classroom-assignment solver).

## Constraint sources fed into the DSL pipeline

After Steps 2–3 of the multi-day plan, the
`engine/dsl_translator.py` module translates each special-
purpose constraint table into canonical DSL strings:

| Source table | Translator | DSL form |
|---|---|---|
| `TeacherUnavailability` | `teacher_unavailability_to_dsl` | `forall l in lessons where l.teacher==X and l.day==D and l.hour==H: false` |
| `ClassUnavailability` | `class_unavailability_to_dsl` | analogous, `l.class==X` |
| `ClassroomUnavailability` | `classroom_unavailability_to_dsl` | analogous, `l.classroom==X` |
| `TeacherMandatoryFreeDay` | `teacher_mandatory_free_day_to_dsl` | `count l in lessons where l.teacher==X and l.day==D == 0` |
| `CoteachGroup` | `coteach_group_to_dsl` | multi-clause: per-teacher `count == n_hours` + slot equality with the principal |
| `PlessoCommutingRule` | `plesso_commuting_rule_to_dsl` | `forall l1 .. l1.classroom.plesso==P_A: forall l2 .. l2.classroom.plesso==P_B and consecutive(l1.slot, l2.slot): false` |
| (legacy hardcoded HARDs) | `seed_implicit_hardcoded(profs)` | canonical pragmas: `no_holes_class`, `class_present_at_hour`, `class_day_load_in`, `teacher_max_per_day`, `cattedra_max_per_day`, `subject_pair_must`, `subject_pair_exists` |

The translator preserves a stable emission order so the CP-SAT
model construction order is reproducible run-to-run. Once
translated to DSL, every constraint flows through the single
`DSLConstraintCompiler` (see `architecture.md`), reaching
`MonolithicSolver`, `PhaseBDaySolver`, every BP pricer and
every Ryan-Foster node uniformly.

For the long-form description of every column and the
SQLAlchemy ORM mapping, see the LaTeX manual chapter
`modello_dati.tex` (or the English summary
`chapters_en/modello_dati.tex`). The Italian summary lives in
`data_model_it.md`.

---

> **Note**: this document is the English-language summary. The
> Italian summary lives in `data_model_it.md`. The full
> long-form Italian description is in the LaTeX manual under
> `docs/manual/chapters/`. Build the manual with
> `docs/build_manual.sh` to obtain `manual.pdf` (Italian) and
> `manual_en.pdf` (English).
