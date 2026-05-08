# PICKLE_DEPRECATED -- profilo `small`

Da questo commit la fonte di verità per il profilo `small` è
**`small.sqlite`** (costruito da
`engine/scripts/build_profile_db.py`). I file `school_small.pkl` /
`profs_small.pkl` restano nel repository per finalità di audit
storico, ma:

- **non vengono più letti** dall'import di default in
  `webui/backend/optimization.py::import_engine_profile`. Il fallback
  pickle è attivo solo se lo SQLite non esiste in
  `engine/scripts/data/small/`.
- non hanno mai contenuto i dati di vincolo (`TeacherUnavailability`,
  `CoteachGroup`, ecc.), che ora vivono nel SQLite generati con
  fixture deterministiche (seed=42).

Per rigenerare lo SQLite di questo profilo:

```
python -m engine.scripts.build_profile_db small
```

## Snapshot stress (manifest)

| chiave | valore |
| --- | --- |
| schedule | `8-14 lun-sab (60min)` |
| n_classes | 10 |
| n_teachers | 20 |
| n_classrooms | 17 |
| n_plessi | 2 |
| n_palestre | 1 |
| n_lab | 4 |
| n_aula_speciale | 1 |
| n_students range | 20–35 |
| capacity range | 20–60 |
| n_lessons | 305 |

Per ogni tabella di vincoli:

| tabella | righe |
| --- | --- |
| teacher_unavailability | 25 |
| teacher_mandatory_free_day | 2 |
| class_unavailability | 2 |
| classroom_unavailability | 4 |
| coteach_group | 2 |
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
