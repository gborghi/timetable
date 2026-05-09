# PICKLE_DEPRECATED -- profilo `medium`

Da questo commit la fonte di verità per il profilo `medium` è
**`medium.sqlite`** (costruito da
`engine/scripts/build_profile_db.py`). I file `school_medium.pkl` /
`profs_medium.pkl` restano nel repository per finalità di audit
storico, ma:

- **non vengono più letti** dall'import di default in
  `webui/backend/optimization.py::import_engine_profile`. Il fallback
  pickle è attivo solo se lo SQLite non esiste in
  `engine/scripts/data/medium/`.
- non hanno mai contenuto i dati di vincolo (`TeacherUnavailability`,
  `CoteachGroup`, ecc.), che ora vivono nel SQLite generati con
  fixture deterministiche (seed=42).

Per rigenerare lo SQLite di questo profilo:

```
python -m engine.scripts.build_profile_db medium
```

## Snapshot stress (manifest)

| chiave | valore |
| --- | --- |
| schedule | `8-14 lun-ven + 8-12 sab` |
| n_classes | 25 |
| n_teachers | 48 |
| n_classrooms | 37 |
| n_plessi | 2 |
| n_palestre | 1 |
| n_lab | 9 |
| n_aula_speciale | 1 |
| n_students range | 18–35 |
| capacity range | 20–60 |
| n_lessons | 745 |

Per ogni tabella di vincoli:

| tabella | righe |
| --- | --- |
| teacher_unavailability | 54 |
| teacher_mandatory_free_day | 4 |
| teacher_free_day_preference | 144 |
| min_free_days_distribution | {2: 12, 1: 34, 3: 2} |
| class_unavailability | 2 |
| classroom_unavailability | 4 |
| coteach_group | 3 |
| plesso_commuting_rule | 2 |
| plesso_entity_policy | 6 |
| teacher_compatible_class | 16 |
| teacher_class_preference | 10 |
| logical_unavailability | 1 |
| curriculum_logical_constraint | 1 |
| general_constraint | 5 |
| pragma_classroom_capacity_ok | 1 |
| subject_required_kind | 2 |


`seed=42` -- una build successiva produrrà esattamente gli stessi
numeri.
