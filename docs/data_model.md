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

For the long-form description of every column and the
SQLAlchemy ORM mapping, see the LaTeX manual chapter
`modello_dati.tex` (or the English summary
`chapters_en/modello_dati.tex`).

---

> **Note**: this document is now English-only. The full
> long-form Italian description that previously lived after this
> separator has moved to the LaTeX manual under
> `docs/manual/chapters/` (see `architettura.tex`,
> `api_rest.tex`, `modello_dati.tex`, etc.). Build the
> manual with `docs/build_manual.sh` to obtain
> `manual.pdf` (Italian) and `manual_en.pdf` (English).
