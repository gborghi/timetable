# PICKLE_DEPRECATED -- profilo `superhuge`

Da questo commit la fonte di verità per il profilo `superhuge` è
**`superhuge.sqlite`** (costruito da
`engine/scripts/build_profile_db.py`). I file `school_superhuge.pkl` /
`profs_superhuge.pkl` restano nel repository per finalità di audit
storico, ma:

- **non vengono più letti** dall'import di default in
  `webui/backend/optimization.py::import_engine_profile`. Il fallback
  pickle è attivo solo se lo SQLite non esiste in
  `engine/scripts/data/superhuge/`.
- non hanno mai contenuto i dati di vincolo (`TeacherUnavailability`,
  `CoteachGroup`, ecc.), che ora vivono nel SQLite generati con
  fixture deterministiche (seed=42).

Per rigenerare lo SQLite di questo profilo:

```
python -m engine.scripts.build_profile_db superhuge
```

## Snapshot stress (manifest)

| chiave | valore |
| --- | --- |
| schedule | `8-13 lun-ven + 14-17 mar/gio (mattina+pomeriggio)` |
| n_classes | 80 |
| n_teachers | 144 |
| n_classrooms | 122 |
| n_plessi | 4 |
| n_palestre | 4 |
| n_lab | 33 |
| n_aula_speciale | 5 |
| n_students range | 18–35 |
| capacity range | 20–80 |
| n_lessons | 2379 |

Per ogni tabella di vincoli:

| tabella | righe |
| --- | --- |
| teacher_unavailability | 172 |
| teacher_mandatory_free_day | 14 |
| class_unavailability | 2 |
| classroom_unavailability | 4 |
| coteach_group | 5 |
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
