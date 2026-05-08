# PICKLE_DEPRECATED -- profilo `huge`

Da questo commit la fonte di verità per il profilo `huge` è
**`huge.sqlite`** (costruito da
`engine/scripts/build_profile_db.py`). I file `school_huge.pkl` /
`profs_huge.pkl` restano nel repository per finalità di audit
storico, ma:

- **non vengono più letti** dall'import di default in
  `webui/backend/optimization.py::import_engine_profile`. Il fallback
  pickle è attivo solo se lo SQLite non esiste in
  `engine/scripts/data/huge/`.
- non hanno mai contenuto i dati di vincolo (`TeacherUnavailability`,
  `CoteachGroup`, ecc.), che ora vivono nel SQLite generati con
  fixture deterministiche (seed=42).

Per rigenerare lo SQLite di questo profilo:

```
python -m engine.scripts.build_profile_db huge
```

## Snapshot stress (manifest)

| chiave | valore |
| --- | --- |
| schedule | `7:55-13:55 lun-sab (55min + 5min break)` |
| n_classes | 50 |
| n_teachers | 90 |
| n_classrooms | 76 |
| n_plessi | 3 |
| n_palestre | 3 |
| n_lab | 20 |
| n_aula_speciale | 3 |
| n_students range | 18–35 |
| capacity range | 20–80 |
| n_lessons | 1488 |

Per ogni tabella di vincoli:

| tabella | righe |
| --- | --- |
| teacher_unavailability | 108 |
| teacher_mandatory_free_day | 9 |
| class_unavailability | 2 |
| classroom_unavailability | 4 |
| coteach_group | 4 |
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
