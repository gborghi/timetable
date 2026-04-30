# Analisi e suggerimenti

Stato attuale del progetto + raccomandazioni di miglioramento, divise in
tre livelli (frontend, backend, engine). Le priorita' indicate sono:

- **P1**: alto impatto / costo basso o medio. Da fare presto.
- **P2**: impatto medio-alto, costo medio. Da pianificare.
- **P3**: nice-to-have, oppure scelte architetturali costose.

L'analisi e' fatta a sola lettura del codice. Niente di quanto segue e'
gia' implementato.

## Numeri di partenza

Conteggi rapidi sul tree corrente:

- **Frontend**: 14 pagine `+page.svelte` per **4 524 LoC** totali.
  Le tre pagine piu' grandi: `schedule/+page.svelte` (838 LoC),
  `assenze-supplenze` (482), `monitor` (471).
- **Componenti riusabili**: 9 in `lib/components/` (Modal,
  AvailabilityMatrix, ClassroomGrid, LogicalUnavailabilitiesPanel,
  BulkApplyModal, ImportButton, SortableQueryableList, RunLogPanel,
  Toast).
- **Backend**: 18 router per **5 026 LoC** totali. Top-3:
  `monitor.py` (843), `imports.py` (710), `coverage.py` (555).
- **Engine**: 4 moduli principali per **2 782 LoC**:
  `cpsat_v2_assignment.py` (380), `cpsat_v2_timetable.py` (820),
  `decomposition_spectral_v2.py` (731), `metaheuristics.py` (851).
- **Test**: zero test files (`test_*.py`, `*.spec.js`, `*.test.js`).

---

## Sezione 1: Frontend (SvelteKit / UI)

### 1.1 Struttura del codice

Pattern attuale: una `+page.svelte` per tab, contenente script + template +
stile. Nessun layer "service" o "page-model" intermedio. Le chiamate REST
sono in `lib/api.js` (thin fetch wrapper), gli store globali in
`lib/stores.js` (toast + dataset counters).

**Suggerimenti**

- **P1** -- estrarre i moduli "service" per ogni dominio (es.
  `lib/services/teachers.js`, `lib/services/coverage.js`) che contengono
  solo le chiamate API + helper di trasformazione. Le pagine diventano
  presentational. Questo abbatte la duplicazione (es. ogni pagina lista
  ha la stessa logica `reload(); flash('Errore: '+e.message)`).
- **P1** -- spezzare le 3-4 pagine sopra le 400 LoC. `schedule/+page.svelte`
  e' ~840 LoC con 4 viste, drag-drop, move-preview e dropdown aule:
  estrarre un `<ScheduleClassMatrix>`, `<ScheduleTeacherMatrix>`,
  `<ScheduleRoomMatrix>`, `<ScheduleListView>` e' lavoro mecccanico ma
  rende ogni pezzo testabile e riusabile.
- **P2** -- migrare a TypeScript. Il fetch wrapper restituisce `any`,
  i payload modal sono `any`, lo schema Pydantic backend non ha riflesso
  client. Generare client tipizzato dall'OpenAPI di FastAPI (`openapi-fetch`,
  `openapi-typescript`) elimina una classe di bug ed espone gli IDE.
- **P3** -- valutare Svelte 5 (runes mode). Migra la reattivita' a
  `$state` / `$derived`, scompare il pattern fragile
  `editing = JSON.parse(JSON.stringify(row))` (deep-clone manuale).

### 1.2 Reattivita' e state management

Le pagine usano spesso il pattern modal:

```js
let editing = null;
function edit(row) { editing = JSON.parse(JSON.stringify(row)); }
```

Il deep-clone via JSON e' fragile: rompe Date, perde Set/Map. Su payload
con date come Student (`birth_date`) c'e' gia' coercion implicita.

**Suggerimenti**

- **P1** -- usare `structuredClone(row)` dove serve un deep-clone (Node
  18+, browser moderni); altrimenti uno helper `cloneRow()` in
  `lib/utils.js` con conversioni esplicite (Date in/out ISO).
- **P1** -- introdurre uno store derivato per il dataset state che si
  aggiorna automaticamente dopo ogni mutazione (`refreshDataset` e' gia'
  presente ma viene chiamato manualmente in ogni pagina; centralizzare
  via subscription al `flash`/`mutation` evento).
- **P2** -- adottare un piccolo "query cache" tipo
  [TanStack Query](https://github.com/svalrog/svelte-query) per i GET di
  lista. Oggi ogni `listRef.reload()` e' una fetch fresca; un cache con
  invalidate-on-mutation rende le navigazioni istantanee e abilita
  optimistic updates.

### 1.3 Accessibilita'

**Stato attuale**: `grep aria-/role=` nel codice frontend ritorna **una
sola occorrenza**. Nessun `aria-label` sui bottoni icon-only (es. l'icona
🔒 / 🔓 in /assignments). Nessun `aria-live` sui toast. Non c'e' un
focus-trap nei Modal. La navigazione da tastiera nelle liste richiede
mouse (drag-and-drop pure mouse).

**Suggerimenti**

- **P1** -- audit ARIA: aggiungere `aria-label` a ogni bottone con solo
  emoji/icon, ruolo `dialog` + `aria-modal=true` + focus-trap nei Modal,
  `aria-live="polite"` al Toast container.
- **P2** -- contrast check: la palette Tailwind usata e' generalmente
  compliante AA, ma i pill `pill-amber` su sfondo `bg-amber-50` sono al
  limite. Passare il sito in axe / Lighthouse e fissare le 5-10 issue
  che vengono fuori.
- **P2** -- alternative tastiera al drag-and-drop: nelle matrici di
  /schedule, /monitor, /assenze-supplenze, aggiungere "click sorgente"
  + "click target" come fallback (gia' presente per il "sposta" in
  /schedule, replicare in /assenze).
- **P3** -- screen reader pass: alt text nelle figure, table headers
  scope=col/row, skip-link in cima alla nav.

### 1.4 Responsivita'

Tailwind e' configurato; le grid usano `md:` / `lg:` in alcune pagine
(`assignments`, `dashboard`), ma le matrici 6x6 e le liste
"36 colonne slot" (in `schedule` list view, `monitor`) sono
**non-responsive**: scrollano orizzontalmente e diventano illeggibili
sotto i ~900px.

**Suggerimenti**

- **P1** -- verificare ogni pagina su 375px (mobile) e 768px (tablet).
  Le pagine "list-table-wide" (schedule/list, classrooms/list) andrebbero
  ridotte a "card per row" sotto md.
- **P2** -- la matrice 6x6 (AvailabilityMatrix, slot picker monitor) puo'
  essere ridotta su mobile usando label compatti ("L M M G V S" come
  header, hour 8/9/10/11/12/13 in colonne). In alternativa, su mobile
  mostrare una sola colonna (giorno) alla volta con un selettore.
- **P3** -- prevedere PWA / installabile: manifest, icone, offline
  caching del bundle (la UI e' tutta single-domain, perfetto candidato).

### 1.5 Performance percepita

**Bundle size**: il build produce diversi chunk (max ~29 KB per
`shared.js` + ~9 KB per i piu' pesanti). Totale per la home ~127 KB
gzipped, ragionevole. Le pagine usano `await api.get(...)` su mount
senza skeleton: c'e' un breve flash bianco.

Liste lunghe non virtualizzate: il `/monitor` con 911 eventi (profilo
small importato) renderizza tutte le righe, ognuna con event listener
inline -> il DOM cresce. La pagina `assignments` rendera ~80 card per la
medium, ~250 per la huge.

**Suggerimenti**

- **P1** -- aggiungere **skeleton loaders** sulle pagine principali
  (`SortableQueryableList` puo' rendere N righe placeholder mentre
  `await reload()` e' in volo).
- **P1** -- mostrare un indicatore di "sto facendo qualcosa" sui bottoni
  durante POST/PUT (oggi la UI freeza muta finche' la response arriva).
  E' gia' implementato in alcuni punti (`disabled={busy}`), va
  generalizzato.
- **P2** -- virtualizzare le liste lunghe. `SortableQueryableList` su
  /monitor e /constraints diventa lenta sopra 1000 righe; integrare
  [svelte-virtual-list](https://github.com/sveltejs/svelte-virtual-list)
  o equivalente.
- **P2** -- pagine con `import` carica la lista intera al mount: per le
  pagine con >500 righe (Studenti su huge, Lezioni/Soluzione attiva)
  introdurre paginazione lato server (vedere sezione backend) e
  infinite-scroll lato client.
- **P3** -- code-splitting per route: SvelteKit gia' fa lazy-loading
  per route, ma componenti pesanti (es. `BulkApplyModal`,
  `LogicalUnavailabilitiesPanel`) potrebbero essere `import()`ati on
  demand.

### 1.6 Consistenza UX

La palette Tailwind e' coerente, ma le pill colorate hanno proliferato
con varianti inline (es. lo stile inline `style="background:#065f46;
color:#fff"` per ENFORCED). Niente design tokens espliciti.

Errori: tutti vanno a `flash('Errore: ' + e.message, 'error')`. Spesso
il messaggio e' un Pydantic dump non leggibile.

**Suggerimenti**

- **P1** -- design system minimale: spostare i 5 colori vincolo
  (HARD/SOFT/PREFERITO/ENFORCED/ALLOWED) in `tailwind.config.js` come
  classi custom (`bg-c-hard`, `bg-c-soft`, ...). Eliminare gli inline
  `style="..."`.
- **P1** -- error handler centralizzato in `api.js` che riconosce le
  4-5 forme di response error tipiche di FastAPI (`detail` string,
  `detail` array of validation errors, generic 500) e produce un
  messaggio leggibile.
- **P2** -- microcopy review: alcuni testi sono in italiano + inglese
  mescolati ("Cerca conflitti" / "dry-run"). Decidere lingua e
  uniformare.
- **P3** -- toast con azioni (es. "Cancellato. UNDO?") via stack di
  toast con TTL.

### 1.7 Robustezza

- I `try { await api.get(...) } catch { /* */ }` silenziano gli errori
  senza utente-feedback in vari punti (`let weights = []; try { weights
  = await api.get('/api/subjects/group-weights'); } catch { /* */ }`).
- Nessuna gestione del **disconnect**: se il backend va giu', la UI fa
  spinning forever sui bottoni `disabled={busy}`.
- Nessun **optimistic update**: ogni mutation aspetta la response prima
  di riflettere; per liste lunghe e' frizionante.
- Nessun **undo**: hai cancellato per errore una cattedra, fine.

**Suggerimenti**

- **P1** -- retry esponenziale per i 5xx (3 tentativi con backoff).
- **P1** -- network status banner: ping `/api/health` ogni 30 s, se
  offline mostra un banner persistente in alto.
- **P2** -- optimistic update sulle liste corte (CRUD: aggiungi la riga
  client-side, rollback su errore).
- **P2** -- soft-delete + "ripristina" entro 5 s tramite toast con
  azione UNDO.

### 1.8 Test

**Stato attuale**: nessun test frontend.

**Suggerimenti**

- **P1** -- introdurre Vitest con 5-10 test smoke iniziali sulle utility
  pure (`logic_parser` lato client se mai esistesse uno; per ora il
  parser e' solo backend, ma la classifying logic dei 5 stati
  `kindFromRule(r)` e' duplicata in 3-4 file: testarla in unit).
- **P2** -- Playwright per 3-5 test e2e: importa profilo small, naviga,
  edita un docente, runna phase A. Gira in CI.
- **P3** -- visual regression con Playwright + screenshot delle pagine
  chiave dopo ogni PR.

### 1.9 Code smells

- **Duplicazione modal-edit**: ogni pagina lista ha lo stesso pattern
  `editing = null + JSON.parse(JSON.stringify) + save() + flash`.
- **Magic numbers**: 5173, 8000, 22 (n_students default), 100/-100
  (penalty default), 8/9/.../13 (HOURS), 1/.../6 (DAYS) sparsi in vari
  file.
- **Componenti monolitici** gia' citati (`schedule/+page.svelte`).
- **Logica di stato inline**: la mappatura `kind -> color` esiste in
  almeno 4 file (LogicalUnavailabilitiesPanel, curricula/+page,
  constraints/+page, BulkApplyModal); centralizzare.

**Suggerimenti**

- **P1** -- creare un componente generico `<EntityListPage>` con slot
  per le colonne, l'editing modal, le actions. Astrazione pesante ma
  paga al primo nuovo CRUD page.
- **P1** -- estrarre `lib/constraint_levels.js` con
  `LEVELS = ['hard','soft','preferred','enforced','allowed']` +
  `kindFromRule(r)` + `levelClass(state)` + `levelLabel(state)`.

---

## Sezione 2: Backend (FastAPI / SQLAlchemy / SQLite)

### 2.1 Architettura

Layering attuale: **router -> ORM -> DB**, con `optimization.py` che
funge da "service layer" per i job lunghi e `engine_io.py` per la
conversione DB <-> pickle. Niente "service layer" intermedio per i
domini CRUD: la logica di business sta nei router (esempio: i 200+
righe di `monitor.py::_build_constraints` mescolano lookup DB,
serializzazione, e regole di policy).

**Suggerimenti**

- **P1** -- estrarre uno strato `services/` (es. `services/coverage.py`,
  `services/monitor.py`) con le funzioni "pure" (data shaping). I router
  diventano shim. Rende riusabile la stessa funzione da tasks
  (es. job di metriche notturne).
- **P2** -- tagliare `monitor.py` (843 LoC) in 3-4 moduli:
  `monitor/events.py`, `monitor/constraints.py`, `monitor/conflicts.py`,
  `monitor/lesson_moves.py`. Stesso per `imports.py` (710 LoC) -> uno
  modulo per entita'.

### 2.2 Modello dati

55 `index=True` dichiarazioni, 26 `ondelete=` (CASCADE / SET NULL): la
copertura indici / cascade e' decente.

**Punti deboli osservati**:

- **Ridondanza**: `Lesson.teacher_name`, `class_name`, `subject` sono
  stringhe (non FK). Se uno rinomina un docente, le Lesson rows non
  vengono aggiornate. Idem per `coteaching_rules.teacher_csv` e per
  `classroom_class_preferences.class_name`.
- **`ClassroomSubjectPreference.required` e `state`**: convivono;
  state e' la fonte di verita' nuova ma `required` e' tenuto in sync.
  Tecnicamente "data corruption invitation" se uno script bypassa
  la sincronizzazione.
- **Manca un index** su `lessons(solution_id, day, hour)` -- la
  composite key piu' usata in /schedule e /monitor; e su
  `lessons(teacher_name, day, hour)` e `(class_name, day, hour)`. Le
  query `_conflict_lessons` in monitor.py fanno scan.
- **JSON-in-text** (`metrics_json`, `params_json`, `parsed_dnf_json`):
  ok per ora, ma SQLAlchemy 2 supporta `JSON` type su SQLite con
  serializzazione automatica. Migrare semplifica.

**Suggerimenti**

- **P1** -- aggiungere indici composti:
  - `lessons(solution_id, day, hour)`
  - `lessons(solution_id, teacher_name, day, hour)`
  - `lessons(solution_id, class_name, day, hour)`
  - `lessons(solution_id, classroom_name, day, hour)`
  Misurare prima/dopo: i `_conflict_lessons` di monitor.py sono i
  candidati piu' caldi.
- **P1** -- consolidare `state` come unica fonte di verita' su
  `ClassroomSubjectPreference`; convertire `required` in property
  computata o eliminarlo dalla colonna.
- **P2** -- denormalizzare meno: `Lesson` potrebbe avere `teacher_id`,
  `class_id`, `classroom_id` come FK invece di nomi. Migrazione
  costosa, ma rende rinomi safe e taglia i bug invisibili.
- **P2** -- migrare `metrics_json` etc. al tipo `JSON` di SQLAlchemy.
- **P3** -- aggiungere `created_at`, `updated_at` su tutte le tabelle.
  Utile per audit log ed export incremental.

### 2.3 API design

**Pattern attuale**: REST con verbi standard, naming italiano misto a
inglese (es. `/api/coverage/week` ma `/api/assenze-supplenze` solo
frontend route). OpenAPI di default attivo (`/docs` Swagger UI).

**Carenze osservate**:

- **Nessuna paginazione** su nessuna lista. Su scuole grandi,
  `GET /api/students` ritorna tutti gli studenti (~2 000 righe per
  superhuge).
- **Filtering DSL** custom (`q=...`) e' bello ma non documentato in
  OpenAPI: la response schema e' generica `dict` nei nostri
  router (vedere `def list_students(...) -> ...` senza
  `response_model=`).
- **Error responses**: alcuni endpoint ritornano `{ok: bool, reason:
  str}` 200, altri `HTTPException(400, "...")`. Non e' uniforme.
- **/api/dataset/clear?scope=all** e' un "POST con effetto distruttivo"
  senza autorizzazione/conferma.
- **Naming misto**: `/api/coverage/week` vs `/api/schedule/by-class`
  (kebab vs ?). Non c'e' una guida di stile consistente.

**Suggerimenti**

- **P1** -- introdurre paginazione standard:
  `?limit=N&offset=M` su tutte le liste lunghe (`students`, `lessons`,
  `monitor/events`, `assignments`). Response `{items: [...],
  total: int}`.
- **P1** -- response schema esplicito per ogni endpoint: aggiungere
  `response_model=list[StudentOut]` ovunque, cosi' OpenAPI riflette la
  realta'.
- **P2** -- error response schema unificato con un Pydantic
  `ErrorResponse` (`{detail, code, field?, hint?}`) e un
  `@app.exception_handler(SQLAlchemyError)` globale che traduce
  IntegrityError ecc. in 400 leggibili.
- **P2** -- naming: scegliere e documentare (kebab-case sul URL,
  snake_case sui body).
- **P3** -- versioning `/api/v1/...` per quando serviranno breaking
  changes.

### 2.4 Performance

**N+1 osservati**: in `monitor.py::_build_events`, per ogni Assignment
`teachers_by_id.get(...)` in dict (cached) -- ok, gia' batched. Ma in
`assignments.py::list_assignments` il pattern `teachers = {t.id: t for
... .all()}` viene rifatto a ogni request. La pagina /assignments
chiama 2-3 endpoint a ogni reload (`by-class`, `loads`, eventualmente
`teachers-for-subject`): potrebbero essere uniti in un solo
"dashboard endpoint".

**Cache**: nessuna. Anche `dataset/state` (un count su 8 tabelle)
viene ricalcolato ad ogni request.

**Suggerimenti**

- **P1** -- introdurre `lru_cache` o un cache manuale TTL=30s su
  `dataset/state`, `monitor/summary`, `dataset/available-profiles`.
  Invalidate su mutation con un counter globale.
- **P2** -- batch endpoint per /assignments che ritorna in un solo
  payload `{by_class, loads, teachers_for_each_subject}`.
- **P2** -- profiling: istallare `pyinstrument` o `sqltap` e correre i
  3-4 endpoint piu' lenti su una huge import. Gli indici suggeriti
  in 2.2 dovrebbero rimuovere i candidati piu' caldi.
- **P3** -- response compression: `GZipMiddleware` su FastAPI.

### 2.5 Scalabilita'

**SQLite** funziona bene per single-tenant single-user. Tre limiti:

1. **Write contention**: con piu' utenti concorrenti, le scritture si
   serializzano su una pool da 1.
2. **Cross-process**: il backend e' un solo processo uvicorn; per due
   processi (gunicorn -w 4) servirebbe Postgres.
3. **Multi-tenant**: una sola scuola alla volta. Per gestirne piu' in
   parallelo, l'attuale "una DB SQLite" e' bottleneck.

**Sync DB**: il backend usa `Session` sincrona. Sotto carico le route
bloccanti tengono i thread del worker pool occupati.

**Suggerimenti**

- **P2** -- planning per Postgres: SQLAlchemy 2.0 supporta entrambi.
  Migrazione e' principalmente: cambiare `DATABASE_URL`, usare Alembic
  per le migration, sostituire le `ALTER TABLE ... ADD COLUMN` raw con
  Alembic versioning. Vedere 2.7.
- **P2** -- introdurre **async** dove serve davvero: gli endpoint che
  fanno solo I/O su DB (le liste) potrebbero passare a `AsyncSession`
  e `httpx`. Per i job lunghi (optimization) la `BackgroundTasks` o un
  worker separato (Celery / RQ) e' piu' pulito del thread pool attuale
  (`run_manager.py`).
- **P3** -- multi-tenant: aggiungere `tenant_id` a ogni tabella, oppure
  schema-per-tenant in Postgres. Decisione architetturale, da
  pianificare quando il use case lo giustifica.

### 2.6 Sicurezza

**Stato attuale**:
- Nessuna autenticazione / autorizzazione (tutto e' aperto).
- `CORSMiddleware(allow_origins=["*"], allow_credentials=False)`.
- `/api/dataset/clear` e gli endpoint di delete sono disponibili senza
  conferma server-side.
- Validazione input via Pydantic ok; SQLAlchemy ORM con parametri
  bindati protegge da SQL injection.
- Niente rate limiting.

Per uso localhost single-user e' accettabile. Per qualunque deployment
oltre, servono protezioni.

**Suggerimenti**

- **P1** -- autenticazione minima: API key in header (1 docente
  super-admin) gia' tagliata fuori il 99% dei rischi su LAN scolastica.
  Step successivo: OAuth con google_id_token o login/password
  + JWT.
- **P1** -- restringere CORS a `http://127.0.0.1:5173` quando in dev,
  via env var.
- **P2** -- autorizzazione (RBAC): role admin / docente / preside.
  L'admin puo' clear; il docente puo' solo modificare la sua
  unavailability.
- **P2** -- rate limiting su `/api/import/*` (caricamenti grandi) e
  sugli endpoint di optimization.
- **P3** -- audit log immutabile su tutti i mutation (chi ha cambiato
  cosa quando).

### 2.7 Migration strategy

**Stato attuale**: `_apply_lightweight_migrations()` in `db.py` con
ALTER TABLE idempotenti raw. Funziona oggi (~10 colonne aggiunte
finora) ma non scala:

- nessun history (sai cosa e' successo, non quando).
- nessuna possibilita' di downgrade.
- gestire un rename column richiede: ALTER + back-fill + drop colonna
  vecchia (SQLite non ha DROP COLUMN nativo prima di 3.35).

**Suggerimenti**

- **P1** -- introdurre **Alembic**. Generare la migration iniziale dal
  modello corrente (`alembic revision --autogenerate`) e dichiararla
  base. Ogni cambio schema e' una nuova revisione tracciata.
- **P2** -- mantenere idempotenza: gli schema esistenti devono
  attraversare la migration senza errori. Alembic supporta
  `op.add_column(..., existing_server_default=...)` con guard via
  `inspector`.

### 2.8 Logging e observability

`grep "import logging"` non torna risultati nei moduli backend.
`optimization.py` ha 28 `print()`. Niente structured logging, niente
metric collector, niente tracing.

**Suggerimenti**

- **P1** -- migrare i `print()` a `logging` standard library con un
  formatter JSON (per CloudWatch / Loki / Grafana). Anche solo livelli
  INFO/WARNING/ERROR sono un upgrade enorme.
- **P2** -- middleware per log structured della request (method, path,
  status, latency). FastAPI ha esempi ufficiali con `RequestLoggingMiddleware`.
- **P2** -- export metriche Prometheus: `/metrics` con counter di
  request, latency p50/p95, mutation count.
- **P3** -- distributed tracing (OpenTelemetry) -- utile solo se passi
  a multi-process / microservizi.

### 2.9 Error handling, idempotenza, retry

- **Mutation idempotenti**: alcuni POST ritornano 400 su retry, altri
  500. `POST /api/absences` con stesso (teacher, date) -> 400. Idempotency
  key non implementata.
- Nessun **retry** lato server (ok, e' il client che deve fare).
- `validate_and_apply_move` puo' lasciare il DB in stato parziale se
  l'engine crasha a meta' (osservazione: c'e' un `db.commit()` finale
  che riduce il rischio, ma alcune routes fanno `db.flush()` + lavoro +
  `db.commit()` non in transazione esplicita).

**Suggerimenti**

- **P1** -- avvolgere ogni endpoint mutation in `with db.begin():` o
  equivalente, garantendo rollback su eccezione.
- **P2** -- idempotency key (`Idempotency-Key` header) per i POST
  pesanti tipo `import-profile`.

### 2.10 Test

**Stato**: zero test backend.

**Suggerimenti**

- **P1** -- pytest con DB SQLite in-memory e fixture per
  `seed_curricula`. Inizia con 3-5 test sui flussi critici:
  `import_profile small`, `move-lesson valid`, `move-lesson room-conflict`,
  `coverage cell`.
- **P1** -- `httpx.AsyncClient` per smoke tests sui 10-15 endpoint
  cardine. Gira in CI.
- **P2** -- property-based test (Hypothesis) sul `logic_parser`: dato un
  AST random, riserializzare + riparsare deve ritornare la stessa DNF.
- **P2** -- contract test fra OpenAPI schema e frontend
  (`openapi-typescript` produce types; un check CI fallisce se
  cambia il backend senza aggiornare il client).

---

## Sezione 3: Engine CP-SAT / ottimizzatore

### 3.1 Modellazione

Phase A (`cpsat_v2_assignment.py`, 380 LoC) e' un set-cover con
HARD su (max_hours per docente, abilitazione materia,
classe-di-concorso). Phase B (`cpsat_v2_timetable.py`, 820 LoC) e'
multi-day scheduling con HARD locali (no overlap, no holes, max-6,
dual-mat/dual-ita) e SOFT con peso variabile.

**Carenze osservate**:

- **Nessun warm-start**: `grep AddHint` torna 0 occorrenze. Ogni run
  riparte da zero anche quando l'utente sposta una lezione.
- **Simmetrie non rotte**: piu' classi della stessa sezione/anno con la
  stessa cattedra producono soluzioni equivalenti per permutazione,
  costose da esplorare.
- **Vincoli logici DNF**: il backend li raccoglie ma il solver Phase B
  li onora solo via `evaluate_against_unavailable` chiamato in
  post-processing (`_logical_check_for_solution`). I literal HARD non
  sono Boolean variable nel CP-SAT model, sono check ex-post. Per le
  istanze grandi questo e' inefficiente: un solo HARD violato e
  l'intera soluzione e' rifiutata.

**Suggerimenti**

- **P1** -- aggiungere `model.AddHint(var, prev_value)` per i seed.
  Quando l'utente fa un drag-drop e poi clicca "ottimizza zona", il
  solver parte dalla soluzione corrente e i miglioramenti vengono
  trovati in secondi invece che minuti.
- **P1** -- internalizzare i logical HARD nel modello CP-SAT come
  `OnlyEnforceIf` su literal aggregati. Costo: ~30 righe in
  `cpsat_v2_timetable.py` se la DNF e' espressa come boolean
  combinations di SlotVar.
- **P2** -- simmetria-breaking via lex-leader: per le coppie di
  cattedre simmetriche, vincolare `var_a <= var_b` (o
  `model.AddDecisionStrategy` con var ordering).

### 3.2 Decomposizione spettrale

`decomposition_spectral_v2.py` (731 LoC) costruisce un grafo di
co-occupazione fra docenti, applica Laplaciano normalizzato, K-means.
Tre stage: bridges -> clusters -> ricucitura -> fallback monolitico.
Il numero di cluster K e' un parametro utente.

**Domande aperte**:

- Come si sceglie K? Oggi e' arbitrario (default 4 nello schema).
- Come si misura la qualita' del cluster? `n_bridges / n_internal`?
- Cosa succede su istanze con cattedre molto sbilanciate (un docente
  con 18 ore su 5 classi diverse)?

**Suggerimenti**

- **P2** -- auto-K con eigengap heuristic (cerca il "salto" nel
  spettro del Laplaciano).
- **P2** -- log delle metriche di partizione: `n_bridges`,
  `cluster_sizes`, `cut_ratio`. Oggi printate, andrebbero salvate per
  comparare run.
- **P3** -- sperimentare partizionamento alternativo (METIS) per le
  istanze >100 classi.

### 3.3 Metaeuristiche

Il modulo `metaheuristics.py` (851 LoC) ha LNS, SA, Tabu, ILS. La
cascata e' lanciata via `run_cascade(...)`. I budget sono parametri
utente.

**Calibrazione**: i default (`tabu_size=80`, `sa_T0=10`, `alpha=0.995`)
sembrano ragionevoli. Ma:

- Non c'e' **adaptive parameter control**: T0 fisso, neighborhood size
  fissa.
- Le 4 algoritmi sono indipendenti: nessun memetic algorithm
  (LNS che incorpora SA, ILS che usa LNS come local search).

**Suggerimenti**

- **P2** -- adaptive LNS: misurare il `delta_soft` medio per ogni tipo
  di neighborhood (`one_day` / `one_prof_one_day` /
  `cluster_day`), e dare piu' budget a quello che paga di piu'.
- **P2** -- ILS con LNS come kick (oggi usa swap perturbativi).
- **P3** -- portfolio approach: lanciare LNS, SA, TS in parallelo su
  thread separati e prendere il best.

### 3.4 Warm-start e re-ottimizzazione incrementale

Quando l'utente modifica manualmente una lezione (drag-and-drop in
/schedule), si potrebbe ri-ottimizzare la zona "intorno" alla mossa
senza rifare tutta Phase B. Oggi non c'e' un "re-optimize this slot
neighborhood" endpoint.

**Suggerimenti**

- **P1** -- endpoint `POST /api/optimize/repair-slot` che prende un
  `(teacher, day)` o `(class, day)` e lancia un LNS molto piccolo
  (5-10 secondi) sulla finestra coinvolta. Warm-start dalla soluzione
  attiva. Risultato: feedback "lo abbiamo migliorato di 5 punti SOFT".
- **P2** -- "auto-repair" dopo ogni drag-drop: se il move peggiora
  SOFT di > X punti, offrire un bottone "auto-fix in 5s" che lancia il
  repair-slot in background.

### 3.5 Parallelism

`solver.parameters.num_search_workers = workers` e' settato (default
8 in `solve_assignment`). La decomposizione spettrale lancia i cluster
**sequenzialmente** in `cpsat_v2_timetable.py` (`for cluster in ...`).

**Suggerimenti**

- **P2** -- parallelizzare i cluster: ognuno e' indipendente, perfect
  candidate per `concurrent.futures.ProcessPoolExecutor`. Speedup
  near-linear con #core.
- **P3** -- distribuire fra macchine: per istanze enormi, un cluster
  per macchina via Celery + risultati centralizzati. Lavoro grosso,
  fai solo se serve.

### 3.6 Qualita' delle soluzioni

`metrics_json` salva: `sixth, buchi, five, one`. Ogni run ha il suo
SOFT score, ma:

- Non c'e' un **lower bound** mostrato (es. da rilassamento LP) per
  capire quanto siamo lontani dall'ottimo.
- Non c'e' un **anytime UI**: durante il run, l'utente vede solo i log,
  non la curva del SOFT che migliora.

**Suggerimenti**

- **P2** -- mostrare nel `RunLogPanel` un grafico del SOFT score nel
  tempo (parsing dei log + plot live in Svelte).
- **P3** -- calcolare un LP-relaxation lower bound e mostrare il
  `gap = (UB - LB) / UB * 100`. Da dove cominciare? Forse da una
  versione del modello di Burke-Kingston-Pepper (paper presente in
  `1-s2.0-S1877050919318800-main.pdf`).

### 3.7 Robustezza ai vincoli "difficili"

Doppia ora mate/ita, motorie a coppie, vincoli logici DNF: gli abbiamo
implementati uno per uno. Funzionano sui mock; pero':

- Su scuole reali, `motorie_pairs=true` puo' rendere infeasible
  un'istanza se le palestre non bastano. Il diagnostic e' un `print`
  in `cpsat_v2_timetable.py`.

**Suggerimenti**

- **P1** -- "infeasibility explainer": dopo un fallimento, lanciare
  CP-SAT con `model.AssertExistOf` rilassato uno alla volta e
  identificare il vincolo "peso massimo" che blocca. Esporre come
  endpoint `POST /api/optimize/explain-infeasibility`.
- **P2** -- rilassamento automatico: dato che ogni HARD ha un toggle
  user, se il run fallisce, suggerire "prova con `hard_motorie_pairs=
  false` su 2A_Scientifico".

### 3.8 Scalabilita' (>100 classi)

I 5 profili attuali topano a "superhuge" (~80 classi). Una scuola
reale grande arriva a 60-80 classi, quindi siamo ai limiti. Oltre
(consorzi, plessi multipli) servirebbe:

**Suggerimenti**

- **P2** -- benchmark a 100/150/200 classi (crea un profilo `mega`).
  Misurare tempo Phase B + qualita'.
- **P2** -- decomposizione gerarchica: cluster di plessi (geografia)
  come outer partition, classi-doc come inner.
- **P3** -- alternative architetturali (vedere 3.10).

### 3.9 Diagnostic tools

Oggi: log testuali via SSE, `print()` per le infeasibilita'. Niente
strumento per "perche' questo slot non puo' avere questa lezione?".

**Suggerimenti**

- **P1** -- `POST /api/optimize/why-not?lesson=...&day=D&hour=H` che
  prova a inserire la lezione in quello slot e ritorna la lista dei
  vincoli HARD violati.
- **P2** -- visualizer in /monitor: hover su una cella scoperta -> popup
  con "questo slot non funziona perche': docente impegnato in
  altra classe, classe ha dual-mat in conflitto, ecc.".

### 3.10 Alternative architetturali (costose)

- **MIP puro** invece di CP-SAT: Gurobi/CPLEX/HiGHS sono piu' veloci
  su LP relaxation ma meno espressivi su vincoli logici. Per il phase
  A potrebbe valere la pena.
- **MiniZinc / Choco**: linguaggio dichiarativo, multiple solver
  backend. Lavoro di port stimato in 2-4 settimane.
- **Local search puro** (HyFlex / Optaplanner): per schools enormi,
  rinunciare alla completeness di CP-SAT e usare solo metaeuristiche
  con vicinati ricchi.

**Costo/beneficio**: oggi non urgente. Vale la pena solo se:
- ti trovi infeasibility frequenti -> piu' diagnostic tools (P1) prima.
- la scuola supera 150 classi -> rifare il modeling con MiniZinc puo'
  pagare.

---

## Roadmap suggerita

5 milestone in ordine di valore:

### M1 -- "Rinforzo backend" (1-2 settimane)
- P1 indici composti su `lessons` (immediate speedup)
- P1 paginazione standard sulle liste lunghe
- P1 logging strutturato (sostituisce print)
- P1 5-10 test pytest sui flussi critici
- P1 transazioni esplicite sugli endpoint mutation

### M2 -- "Quality of life UI" (1-2 settimane)
- P1 audit ARIA + focus-trap nei modal
- P1 design tokens per i 5 colori vincolo
- P1 skeleton loaders + busy state sui bottoni
- P1 error handler centralizzato in `api.js`
- P1 spezzare le 4 pagine sopra le 400 LoC

### M3 -- "Engine: warm-start + repair" (2-3 settimane)
- P1 `AddHint` warm-start per CP-SAT
- P1 endpoint `optimize/repair-slot` (LNS short-budget zona-ristretta)
- P1 endpoint `why-not` per diagnostic infeasibility
- P2 metric structured + grafico SOFT-over-time

### M4 -- "Production-ready" (3-4 settimane)
- P1 autenticazione minima (API key)
- P1 Alembic + migration history
- P2 Postgres path (env var + tested)
- P2 `AsyncSession` per gli endpoint read-heavy
- P2 RBAC base (admin / docente)

### M5 -- "Engine V2" (4+ settimane)
- P2 simmetria-breaking nel modello
- P2 internalizzare logical HARD nel CP-SAT model
- P2 cluster paralleli
- P2 adaptive LNS / ILS con LNS-kick
- P3 alternative MIP / MiniZinc per phase A

---

## Note finali

Questa analisi e' a sola lettura del codice. Niente di quanto descritto
sopra e' implementato. Le metriche LoC, gli indici dichiarati, i pattern
osservati sono al momento `9d8afd8` (HEAD).
