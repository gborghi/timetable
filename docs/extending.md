# Estendere il sistema

Il progetto e' pensato per essere modificabile in piccoli pezzi:
ogni layer e' isolato e i pattern sono ripetuti per ogni entita'.
Questo documento elenca i pattern piu' comuni per aggiungere
funzionalita'.

## Aggiungere una nuova tabella + CRUD

1. Modello in `webui/backend/models.py`. Pattern:
   ```python
   class MyEntity(Base):
       __tablename__ = "my_entities"
       id: Mapped[int] = mapped_column(Integer, primary_key=True)
       name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
       ...
   ```
2. Pydantic in `schemas.py` (`MyEntityIn`, `MyEntityOut`).
3. Router nuovo in `routers/my_entity.py`. Copia un router esistente
   come template (es. `subjects.py` per uno semplice; `teachers.py`
   per uno con relazioni embed).
4. Includi il router in `main.py`:
   ```python
   from backend.routers import my_entity
   app.include_router(my_entity.router)
   ```
5. Adapter DSL in `utils/list_query.py`:
   ```python
   def my_entity_fields():
       return {
           "name": lambda r: r.get("name") or "",
           "nome": lambda r: r.get("name") or "",
       }
   def my_entity_funcs():
       return {}
   _FIELDS_FOR["my_entities"] = (my_entity_fields, my_entity_funcs)
   ```
6. Nel router GET list:
   ```python
   try:
       return filter_and_sort(out, "my_entities", q, sort)
   except QueryError as e:
       raise HTTPException(400, f"Errore query: {e}")
   ```
7. Frontend: nuova route `webui/frontend/src/routes/my-entities/+page.svelte`.
   Riusa `SortableQueryableList` con un endpoint, un modal per il
   create/edit, e un blocco columns/help.
8. Aggiungi una voce in `webui/frontend/src/routes/+layout.svelte`
   per la nav.

## Migrazione idempotente

Se aggiungi una colonna a una tabella **esistente** (non un'intera
nuova tabella), aggiorna `webui/backend/db.py::_apply_lightweight_migrations`:

```python
if insp.has_table("my_table") and not has_column("my_table", "new_field"):
    conn.execute(text(
        "ALTER TABLE my_table ADD COLUMN new_field VARCHAR(64)"
    ))
    # opzionale: back-fill
    conn.execute(text(
        "UPDATE my_table SET new_field = ... WHERE ..."
    ))
```

Il check `has_column` lo fa idempotente.

## Aggiungere un nuovo tipo di vincolo

### Vincolo per-cella

Se vuoi un nuovo tipo di matrice di disponibilita' (per esempio per
una nuova entita'), copia il pattern di `TeacherUnavailability`:
unique `(entity_id, day, hour)`, columns `state`, `soft_penalty`,
`reason`. Aggiorna:

- `models.py` (nuova classe ORM)
- `schemas.py` (UnavailabilitySlot e' gia' generico)
- router della nuova entita'
- `optimization.py::_availability_constraints` per propagare al solver
- `routers/monitor.py::_build_constraints` se vuoi che il vincolo
  appaia nel tab Vincoli
- `routers/bulk.py::ENTITY_UNAV_MODEL` se vuoi supportare bulk

### Vincolo logico (DNF)

I vincoli logici esistono gia' per teacher / class / classroom /
curriculum. Per una nuova entita':

- aggiungi `entity_type` al `LogicalUnavailability` enum (oppure usa
  una tabella separata se i metadati differiscono molto, come per
  CurriculumLogicalConstraint).
- aggiorna `routers/logical.py::ENTITY_MODEL` e `ENTITY_TYPE`.
- modifica `routers/monitor.py::_build_constraints`.
- nel solver (`optimization.py::_logical_constraints`,
  `_logical_check_for_solution`), aggiungi il branch.

### Nuovo kind / level

Se vuoi un kind nuovo (es. "advisory") oltre ai 4 attuali:

- aggiungi il valore alla colonna `kind` di
  `LogicalUnavailability` / `CurriculumLogicalConstraint`.
- aggiorna `_normalise_kind` nei due router (logical / curricula).
- aggiorna il solver: `_logical_violation_summary`,
  `_logical_check_for_solution`.
- aggiorna le componenti UI (`LogicalUnavailabilitiesPanel`,
  `BulkApplyModal`, `/curricula`, `/constraints`): aggiungi il radio
  + una pill colorata.

## Aggiungere un campo Pydantic + UI

1. Aggiungi il campo al modello SQLAlchemy.
2. Aggiungi il campo a `schemas.MyEntityIn` / `MyEntityOut` (default
   sensato per backwards-compat).
3. Aggiorna il router `_apply` / `_to_out` per propagare il campo.
4. Aggiorna la migrazione per gli storage esistenti.
5. Frontend: aggiungi l'input al modal di edit + l'eventuale colonna
   alla lista + l'eventuale alias DSL in `list_query.py`.

## Aggiungere un endpoint di bulk operation

- aggiungi un'azione a `routers/bulk.py::_detect_conflict` /
  `_apply_one`.
- nel frontend aggiorna `BulkApplyModal` (lista azioni + payload form
  + eventuale conflict-modal).

## Aggiungere un parser custom per i vincoli logici

Il parser e' in `webui/backend/utils/logic_parser.py`. Per aggiungere
un nuovo tipo di atom o un nuovo operatore:

- estendi la regex `_TOKEN_RE` con un nuovo gruppo.
- aggiungi il branch nel tokenizer (`_tokenize`).
- estendi la grammatica nel parser (`_Parser`) per le nuove regole.
- aggiorna `_push_not` / `_to_dnf` se l'operatore richiede De Morgan
  particolari.
- aggiorna `_lit_to_str` / `dnf_to_pretty` per il rendering.
- aggiorna `evaluate_against_unavailable` per la valutazione.

## Aggiungere uno step di ottimizzazione

`webui/backend/optimization.py` e' il dispatcher. Pattern per un
nuovo job:

```python
def my_new_step(...):
    params = dict(...)
    run_id = create_run("my_step", "Nome leggibile", profile, params)

    def target(rid: int):
        # carica dati, lancia solver, persiste
        update_run(rid, progress=0.5)
        ...
        update_run(rid, solution_id=sid, obj_value=v, metrics=m)
        update_run(rid, progress=1.0)

    start_thread(run_id, target)
    return run_id
```

Esponi via `routers/optimize.py` con un endpoint POST. Frontend in
`/optimize` (workflow page) per il bottone di lancio + log streaming
via `RunLogPanel` (SSE).

## Aggiungere il supporto Excel/CSV per una nuova entita'

In `webui/backend/routers/imports.py`:

1. Aggiungi una funzione `_import_my_entity(db, rows, mode)` che
   parsa i dict-rows e fa upsert.
2. Registrala in `_IMPORTERS`.
3. Aggiungi un template a `_TEMPLATES` con la lista di header e
   una riga di esempio.
4. Aggiorna `webui/docs/import_format.md` con la documentazione del
   formato.

Il bottone `ImportButton` nel frontend e' generico; basta passare
`entity="my_entities"`.

## Aggiungere uno stato a una matrice / grid

Se vuoi un 6o stato sulla matrice di disponibilita':

1. `routers/{teachers,classes,classrooms}.py::_apply` - estendi la
   tupla `("hard","soft","preferred","enforced")` con il nuovo valore.
2. `optimization.py::_availability_constraints` - aggiungi il branch
   per il nuovo state (e propaga al solver come hai bisogno).
3. `AvailabilityMatrix.svelte`:
   - aggiungi il valore al `nextState` cycle
   - aggiungi le classi CSS al template
   - aggiungi un input numerico se serve, con sign-clamp
   - aggiorna la legenda.
4. `BulkApplyModal.svelte` - aggiungi l'opzione al select state.
5. `routers/bulk.py::_detect_conflict` / `_apply_one` - se rilevante.

## Testing

Non c'e' una test suite formale. Per smoke-testare end-to-end ho
usato:

- Backend boot pulito: `uvicorn backend.main:app` per qualche secondo,
  guarda `app.routes` count e che importi senza errori.
- Live curl: vedere [api.md](api.md) per esempi.
- Frontend `vite build` deve passare clean.

Quando si aggiunge codice nuovo:

- Verifica che il backend boot ancora pulito.
- Esegui un curl e-2-e sul nuovo endpoint con dati realistici.
- `npm run build` sul frontend.
- Eventualmente migrazione idempotente: rilancia su un DB esistente
  per confermare zero data loss.
