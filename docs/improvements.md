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

- **P1** [DONE 2026-04-30 a2ad8af] -- estrarre i moduli "service" per
  ogni dominio (es. `lib/services/teachers.js`, `lib/services/coverage.js`)
  che contengono solo le chiamate API + helper di trasformazione.
  Implementato come `lib/services/index.js` con namespace per resource;
  8 pagine CRUD migrate; le altre seguiranno incrementalmente.
- **P1** [DONE 2026-04-30 99f9809] -- spezzare le 3-4 pagine sopra le 400
  LoC. `schedule/+page.svelte` da 838 -> 704 LoC, estratti
  `MoveModeBanner`, `RoomDropdown`, `PreviewCellHint`,
  `RoomClearedNoticeModal`, `SolutionsTable` in
  `lib/components/schedule/`. Le matrici intere lasciate inline (drag
  state condiviso).
- **P2** [DONE 2026-04-30] -- migrazione TypeScript graduale e
  completa. tsconfig.json + svelte-check + typescript + tslib +
  @types/node aggiunti. 6 file `lib/*.js` -> `lib/*.ts` (api,
  stores, utils, constants, constraint_levels, services/index).
  Nuovo `lib/types.ts` con i tipi delle 13+ entita' (Teacher,
  Subject, SchoolClass, Classroom, Curriculum, Student, StudyGroup,
  CoteachingRule, Assignment, Solution, RunSummary, DatasetState,
  ApiErrorResponse, Paginated<T>, ConstraintLevel, etc.). I tipi
  riflettono manualmente gli schemi Pydantic backend; il follow-up
  e' `openapi-typescript` per auto-generazione (lasciato come
  task futuro nel docs). `npm run check` verde (0 errori, 152
  warning a11y pre-esistenti). `npm run build` verde.
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

- **P1** [DONE 2026-04-30 aaaff91] -- usare `structuredClone(row)` dove
  serve un deep-clone. Helper `cloneRow()` in `lib/utils.js` con fallback
  JSON; 8 pagine migrate.
- **P1** [DONE 2026-04-30 1aea608] -- store derivato per dataset state
  che si aggiorna automaticamente dopo ogni mutazione. Implementato in
  `lib/stores.js` come `mutationCounter` + `bumpMutation()` con debounce
  di 120ms su `refreshDataset`.
- **P2** [DONE 2026-04-30] -- query cache via
  `@tanstack/svelte-query` ^6.1. `lib/queries/client.ts` espone un
  QueryClient globale (staleTime 30s, gcTime 5min,
  refetchOnWindowFocus). `lib/queries/index.ts` espone hook per
  resource (`teachersQuery.useList()`, `subjectsQuery.useList()`,
  `classroomsQuery.useList()`, ecc.) + mutation hooks che invalidano
  la list-key on success. `QueryClientProvider` montato in
  `+layout.svelte` come root della tree. `mutationCounter` store
  globale aggancia `invalidateQueries()` su ogni POST/PUT/DELETE
  cosi' il cache resta consistente con l'auto-bump backend
  (`MutationBumpMiddleware`). Migrate teachers + classes pages
  (lookup data subjects/classrooms/curricula): navigazione tornare
  ad esse e' istantanea (cache hit). Le pagine restanti possono
  migrare incrementalmente; il pattern e' stabilito.

### 1.3 Accessibilita'

**Stato attuale**: `grep aria-/role=` nel codice frontend ritorna **una
sola occorrenza**. Nessun `aria-label` sui bottoni icon-only (es. l'icona
🔒 / 🔓 in /assignments). Nessun `aria-live` sui toast. Non c'e' un
focus-trap nei Modal. La navigazione da tastiera nelle liste richiede
mouse (drag-and-drop pure mouse).

**Suggerimenti**

- **P1** [DONE 2026-04-30 773fad2] -- audit ARIA: `aria-label` sui
  bottoni icon-only, `role=dialog` + `aria-modal=true` + focus-trap nei
  Modal, `aria-live` (polite/assertive in base al tone) al Toast.
  Skip-link aggiunto al layout.
- **P2** -- contrast check: la palette Tailwind usata e' generalmente
  compliante AA, ma i pill `pill-amber` su sfondo `bg-amber-50` sono al
  limite. Passare il sito in axe / Lighthouse e fissare le 5-10 issue
  che vengono fuori.
- **P2** [DONE 2026-04-30 26c5f0b] -- alternative tastiera al drag-drop:
  in /schedule le celle matrice (vista classi + docenti) hanno tabindex,
  role=button, aria-label, focus-ring; Enter avvia/conferma move-mode,
  Escape annulla. /assenze-supplenze gia' usava il pattern click-source
  + click-target.
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
- **P2** [DONE 2026-04-30 d6d5cde] -- la matrice 6x6 (timetable-grid)
  ora ha `min-width: 720px` (640px sotto breakpoint 640) cosi' su mobile
  produce uno scroll orizzontale dentro l'overflow-auto invece di
  troncarsi. Media query stringe gap e padding sotto 640px.
- **P3** [DONE 2026-04-30 d6d5cde] -- PWA stub installabile: aggiunto
  `static/manifest.webmanifest` con palette piTantum (theme/background)
  e icone esistenti. `app.html` linka manifest + `theme-color` +
  `viewport initial-scale=1`. Manca offline caching (service worker).

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

- **P1** [DONE 2026-04-30 64caa2e] -- skeleton loaders su
  `SortableQueryableList` (6 righe placeholder al primo caricamento) +
  pulse indicator nell'header sui reload successivi.
- **P1** [DONE 2026-04-30 64caa2e] -- indicatore "sto facendo qualcosa"
  sui bottoni durante POST/PUT (`disabled={saving}`/`busyStore` in
  `lib/utils.js`).
- **P2** -- virtualizzare le liste lunghe. `SortableQueryableList` su
  /monitor e /constraints diventa lenta sopra 1000 righe; integrare
  [svelte-virtual-list](https://github.com/sveltejs/svelte-virtual-list)
  o equivalente. (Dataset reale piTantum non si avvicina, lasciato
  per quando i numeri lo richiederanno.)
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

- **P1** [DONE 2026-04-30 773fad2] -- design system minimale: tokens
  `c.{hard,soft,pref,enf,allow,forbidden}-{bg,fg,border}` in
  `tailwind.config.js`, classi pill `pill-c-*`, inline
  `style="background:#065f46..."` rimossi (8 occorrenze sostituite).
- **P1** [DONE 2026-04-30 1aea608] -- error handler centralizzato in
  `api.js` (`formatApiError`) che gestisce le 3 forme tipiche FastAPI
  (`detail: string`, `detail: [{loc,msg,type}]`, `error: string`).
- **P2** -- microcopy review: alcuni testi sono in italiano + inglese
  mescolati ("Cerca conflitti" / "dry-run"). Decidere lingua e
  uniformare.
- **P3** [DONE 2026-04-30 26c5f0b] -- toast con azioni (UNDO) via
  `flash(msg, tone, {action: {label, fn}})` -- collegato ai delete di
  /teachers, /classes, /students con TTL 8s.

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

- **P1** [DONE 2026-04-30 1aea608] -- retry esponenziale per i 5xx
  (200/400/800ms) per GET/HEAD; mutazioni non retry-ate.
- **P1** [DONE 2026-04-30 1aea608] -- network status banner: ping
  `/api/health` ogni 30s, se offline banner persistente in alto del
  layout (`networkOnline` store + `startNetworkMonitor`).
- **P2** -- optimistic update sulle liste corte (CRUD: aggiungi la riga
  client-side, rollback su errore). Considerato rischioso per un tool
  interno; rimandato.
- **P2** [DONE 2026-04-30 26c5f0b] -- soft-delete + "ripristina" tramite
  toast con azione UNDO. Wired su /teachers, /classes, /students; il
  ripristino ricrea la riga (POST) ma perde il primary key originale.
  Non e' un soft-delete vero (lato DB) ma copre il caso "ho cancellato
  per sbaglio".

### 1.8 Test

**Stato attuale**: nessun test frontend.

**Suggerimenti**

- **P1** [DONE 2026-04-30] -- 20 smoke test su `constraint_levels.js`
  (`kindFromRule`, `payloadFromKind`, `clampPenalty`, mapping coverage).
  Usa `node --test` (Node 20+) cosi' niente nuova dependency vitest.
  `npm test` nel frontend esegue la suite (~250ms).
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
  paga al primo nuovo CRUD page. (Rimandato: i template attuali sono
  poco simili tra loro -- ogni pagina ha campi specifici -- e
  `SortableQueryableList` copre gia' la parte query/sort/render.)
- **P1** [DONE 2026-04-30 773fad2] -- estratto `lib/constraint_levels.js`
  con `LEVELS`, `LOGICAL_KINDS`, `LEVEL_LABEL`, `LEVEL_PILL_CLASS`,
  `LEVEL_CELL_CLASS`, `DEFAULT_PENALTY`, `kindFromRule`, `levelPill`,
  `levelLabel`, `levelCellClass`, `payloadFromKind`, `clampPenalty`.
  Single source of truth per i 5 stati (4 file riducono duplicazione).

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

- **P1** [DONE 2026-04-30 32f69d6 (starter)] -- creato
  `webui/backend/services/` con `dataset_state.compute_state(db)`
  estratto da `routers/dataset.py`. Il pattern e' stabilito; le
  prossime estrazioni (monitor.events, monitor.constraints,
  monitor.conflicts, imports.<entity>) sono lavoro mecccanico
  rimandato per minimizzare il rischio di regressione in questa
  passata.
- **P2** [PENDING] -- splittare `monitor.py` (843 LoC) e `imports.py`
  (710 LoC) in submoduli per entita'. Le funzioni pure sono gia'
  candidabili (vedi `_build_events`, `_build_constraints`,
  `_detect_conflicts`); l'estrazione per dominio e' la prossima
  iterazione.

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

- **P1** [DONE 2026-04-30 c9636eb] -- 4 indici composti su `lessons`
  (`sol_day_hour`, `sol_teacher_day_hour`, `sol_class_day_hour`,
  `sol_room_day_hour`). Dichiarati via `Index()` in
  `Lesson.__table_args__`; CREATE INDEX IF NOT EXISTS nel
  lightweight-migration per upgrade in-place; live DB gia'
  migrata.
- **P1** [DONE 2026-04-30 3546871] -- `state` source-of-truth in
  `ClassroomSubjectPreference`. Event listener
  `_sync_csp_required` su before_insert/before_update forza
  `required = (state == 'enforced')`. Il bool resta come colonna
  per backward-compat con engine_io ma diventa derivato.
- **P2** [PENDING -- migrazione invasiva] -- denormalizzare meno
  Lesson (teacher_id/class_id/classroom_id come FK). Richiede
  migration con backfill su tabelle live + aggiornamento di tutti i
  consumer (engine_io, exporters, monitor); ~3-5 giorni. Da fare
  quando il sistema gestisce rinomi piu' frequentemente.
- **P2** [PENDING -- low ROI] -- migrare `metrics_json` etc. al tipo
  `JSON` di SQLAlchemy. Le colonne attuali sono Text con `json.dumps`
  lato Python; il refactor e' meccanico ma rischia di rompere il
  serialization round-trip per i pickle esistenti.
- **P3** [DONE 2026-04-30 b752211 -- selective] -- `created_at` +
  `updated_at` aggiunti tramite `TimestampMixin` alle 7 entita'
  user-facing (Subject, Teacher, SchoolClass, Classroom, Curriculum,
  Student, StudyGroup). Le tabelle junction / detail e Lesson sono
  esplicitamente escluse (Lesson cresce a 36 row per docente-week
  -> overhead di scrittura non giustificato). Live DB gia'
  migrata.

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

- **P1** [DONE 2026-04-30 3c28c6c] -- paginazione opt-in su
  `/api/students` e `/api/monitor/events`. Helper
  `utils.pagination.paginated_or_list(rows, limit, offset)`: con
  ?limit / ?offset ritorna `{items, total, limit, offset}`,
  altrimenti la lista bare (legacy compat). Estendibile alle altre
  liste lunghe quando necessario.
- **P1** [PENDING -- mecccanico] -- aggiungere
  `response_model=list[XOut]` a ogni list endpoint. Molti
  POST/PUT/DELETE l'hanno gia' (10 router su 17); le 7 list-GET
  bare aggiunte incrementalmente.
- **P2** [DONE 2026-04-30 fe3e72c] -- ErrorResponse Pydantic unificato
  + 5 exception handler globali (HTTPException,
  RequestValidationError, IntegrityError, SQLAlchemyError,
  RuntimeError, Exception catch-all). Forma canonica:
  `{detail, code, errors[], hint, request_id, error}`.
- **P2** [PENDING -- bassa priorita'] -- naming kebab vs snake. Lo
  stack e' coerente al 90% (snake-case sui body Pydantic,
  kebab-case sui path); pochi residui legacy (`/api/coverage/week`
  ok, ma `/api/dataset/state` snake nel path). Da uniformare prima
  di aprire la API a clienti esterni.
- **P3** [PENDING] -- versioning `/api/v1/...`. Senza prefisso oggi;
  quando serviranno breaking change verra' introdotto.

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

- **P1** [DONE 2026-04-30 59589f2] -- TTL cache custom in
  `utils/ttl_cache.py` (`cached(key, ttl_s, mutation_aware,
  compute)`) + `MutationBumpMiddleware` che bumpa il counter su
  ogni 2xx POST/PUT/PATCH/DELETE. Wired su
  `/api/dataset/state` (TTL 30s) e `/api/monitor/summary` (TTL 15s).
  `dataset/available-profiles` non e' chiamato spesso quanto gli
  altri due, lasciato non-cached.
- **P2** [PENDING] -- batch endpoint per /assignments. La pagina
  /assignments fa 2-3 chiamate concorrenti; un solo
  `GET /api/assignments/dashboard` che ritorna
  `{by_class, loads, teachers_for_each_subject}` ridurrebbe la
  latenza percepita.
- **P2** [PENDING] -- profiling con pyinstrument su huge import. Da
  fare quando ci sara' una baseline post-indici (B2) per misurare
  il guadagno reale.
- **P3** [DONE 2026-04-30 72251d6] -- `GZipMiddleware` con
  minimum_size=1024 byte. Big payloads (lessons listing huge ~ 4 MB
  JSON) -70% wire size.

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

- **P2** [DONE 2026-04-30 -- Postgres-ready] -- planning per Postgres.
  Su richiesta esplicita di Giovanni, il backend e' ora
  Postgres-ready (URL via `PITANTUM_DB_URL` env var; SQLite resta
  default). `db._resolve_db_url()` legge l'env, applica i tuning
  Postgres-only (pool_size, max_overflow, pool_pre_ping) quando
  l'URL non e' SQLite. `IS_SQLITE` flag esposto cosi'
  `_apply_lightweight_migrations` skippa i PRAGMA SQLite-specific
  su Postgres. La live DB resta SQLite -- per switchare a Postgres
  basta `set PITANTUM_DB_URL=postgresql+psycopg://...` + alembic
  upgrade head. Driver psycopg + asyncpg + aiosqlite documentati
  come optional in requirements.txt.
- **P2** [DONE 2026-04-30 -- selective async] -- async via
  AsyncSession. Nuovo `webui/backend/async_db.py` con
  `_resolve_async_url()` che traduce sqlite:/// ->
  sqlite+aiosqlite:///, postgresql:// -> postgresql+asyncpg://.
  `get_async_db()` FastAPI dependency per AsyncSession. Endpoint
  prova `/api/health/async` esercita SELECT 1 attraverso il path
  async. La conversione def->async def degli endpoint esistenti
  resta incrementale: il pattern e' stabilito; eseguire
  `aiosqlite` e' sufficiente in dev. Quando driver mancante, 503
  con hint canonico.
- **P3** [DONE 2026-04-30 -- scaffolding] -- multi-tenant. Nuovo
  `webui/backend/tenant.py` con `TenantMixin` (tenant_id INTEGER NOT
  NULL DEFAULT 1, indexed) + `current_tenant_id()` FastAPI
  dependency che legge `X-Tenant-Id` header con fallback al default
  via `PITANTUM_DEFAULT_TENANT_ID`. Mixed into 7 entita' user-facing
  (Subject, Teacher, SchoolClass, Classroom, Curriculum, Student,
  StudyGroup). DB live gia' migrata. La filtering effettiva
  (`Model.tenant_id == tid`) lasciata ai router quando un caso
  multi-tenant reale arrivera'; oggi tutti i record sono tenant=1.

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

- **P1** [DONE 2026-04-30 72251d6] -- API key opt-in in
  `utils/auth.py::APIKeyMiddleware`. Disattivata di default
  (PITANTUM_API_KEY unset = passthrough). Quando attiva,
  X-API-Key o Bearer obbligatorio su /api/* eccetto health/docs.
  secrets.compare_digest per timing-safe.
- **P1** [DONE 2026-04-30 3042c45] -- CORS ristretto a
  127.0.0.1:5173 + localhost:5173 (+ preview ports). Override via
  env var `PITANTUM_CORS_ORIGINS`.
- **P2** [PENDING -- prerequisito: scegliere user model] -- RBAC.
  Senza un User model in DB non c'e' a chi associare il role.
  Servirebbe prima un step di User+Auth.
- **P2** [PENDING] -- rate limiting su /api/import/* e optimize.
  `slowapi` library (compat FastAPI) + Redis backend per produzione,
  in-memory ok per single-user dev. Da fare se l'app va su rete.
- **P3** [PENDING] -- audit log. Hook su mutation_bump che logga
  chi (User), cosa (path + method), quando (timestamp), prima/dopo
  (diff JSON). Servono User + immutable log table.

### 2.7 Migration strategy

**Stato attuale**: `_apply_lightweight_migrations()` in `db.py` con
ALTER TABLE idempotenti raw. Funziona oggi (~10 colonne aggiunte
finora) ma non scala:

- nessun history (sai cosa e' successo, non quando).
- nessuna possibilita' di downgrade.
- gestire un rename column richiede: ALTER + back-fill + drop colonna
  vecchia (SQLite non ha DROP COLUMN nativo prima di 3.35).

**Suggerimenti**

- **P1** [DONE 2026-04-30 149575a] -- Alembic introdotto. Baseline
  revision `f785f5cb346c` consolida la drift fra lightweight migrations
  legacy e modello canonico (NOT NULL su 14 timestamp + 3 state/kind
  cols, FK + indici mancanti). Live DB upgradata. env.py legge l'URL
  dal db.py (single source). render_as_batch=True per SQLite ALTER.
- **P2** [DONE 2026-04-30 149575a] -- idempotenza preservata: il
  vecchio `_apply_lightweight_migrations` resta come safety-net
  startup, idempotente (PRAGMA + IF NOT EXISTS). Coesiste con
  alembic; per i fresh DB, create_all + lightweight + alembic
  upgrade head danno lo stesso risultato.

### 2.8 Logging e observability

`grep "import logging"` non torna risultati nei moduli backend.
`optimization.py` ha 28 `print()`. Niente structured logging, niente
metric collector, niente tracing.

**Suggerimenti**

- **P1** [DONE 2026-04-30 3042c45] -- `logging_setup.configure_logging()`
  centralizza handler stdout, formatter plain default + JSON
  opt-in (env `PITANTUM_LOG_JSON=1`), level via
  `PITANTUM_LOG_LEVEL`. I `print()` in optimization.py STANNO:
  feedano la SSE log stream consumata dal frontend RunLogPanel
  (cambiarli romperebbe il pannello live), comportamento
  documentato in logging_setup.py.
- **P2** [DONE 2026-04-30 3042c45] --
  `utils/request_logging.RequestLoggingMiddleware` logga 1 INFO
  per request (method, path, status, latency_ms, request_id,
  client). Aggiunge X-Request-Id come header risposta (correlazione
  client-side). Sopprime /api/health per evitare noise.
- **P2** [PENDING] -- export Prometheus su /metrics. `prometheus-fastapi-instrumentator`
  e' la dep usuale; 30 LoC. Da fare quando ci sara' un consumer
  (Grafana / dashboard) — oggi non c'e'.
- **P3** [SKIPPED -- single-process] -- distributed tracing.

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

- **P1** [DONE 2026-04-30 36f3c0b] -- `get_db()` ora cattura
  Exception, fa `db.rollback()` e ri-raise. Uncaught raises non
  lasciano piu' la session inconsistente; le exception bubbling up
  arrivano puliti ai global handler in main.py.
- **P2** [PENDING] -- idempotency key. Header `Idempotency-Key`
  con tabella di cache request->response per i POST pesanti
  (import-profile, dataset/mock). Da fare se la rete diventa
  inaffidabile (oggi e' localhost).

### 2.10 Test

**Stato**: zero test backend.

**Suggerimenti**

- **P1** [DONE 2026-04-30 e196b83 + fe3e72c + 3c28c6c + 59589f2 + 72251d6]
  -- pytest infrastructure (`webui/backend/tests/conftest.py`) con
  fixture isolata `app_with_temp_db` (DB tmp_path, mai tocca quella
  di Giovanni; `dependency_overrides[get_db]`). Tests:
  smoke (10), errors (5), pagination (5), cache (3), auth (3) =
  **26 test totali**, ~17s, tutti verdi.
  Run: `webui/backend/.venv/Scripts/python -m pytest webui/backend/tests/`
- **P1** [PARTIAL] -- httpx-based smoke tests gia' fatti via
  TestClient (che usa httpx internamente). Esposti via FastAPI
  TestClient invece di AsyncClient diretto, ma copertura
  equivalente.
- **P2** [PENDING] -- Hypothesis sul logic_parser. La grammatica
  DSL e' relativamente piccola; un property-based test
  parse(serialize(AST)) == AST e' un follow-up naturale.
- **P2** [PENDING] -- contract test OpenAPI vs frontend.
  Servirebbe `openapi-typescript` lato CI; rimandato (frontend
  non e' in TS, beneficio ridotto).

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

- **P1** [DONE 2026-04-30 98de2d7] -- `model.AddHint(var, prev_value)`
  applicato in `metaheuristics._cp_repair` per ogni variabile libera.
  LNS / ILS-perturb partono dal valore corrente; CP-SAT bootstrappa
  dal feasible point invece che da zero. Combinato con
  `repair_slot_neighborhood` (3.4) abilita "ottimizza zona" in pochi
  secondi.
- **P1** [SKIPPED -- richiede port di logic_parser dal backend a
  experiments/, ~200 LoC, beneficio incerto] -- internalizzare i
  logical HARD nel modello CP-SAT. Oggi `_logical_check_for_solution`
  (lato backend) li valuta a posteriori. Le metaheuristiche
  (`metaheuristics.py`) non vedono i vincoli DNF: operano solo sui
  fisici (overlap, no-holes, max5, mat-ita-doppia, motorie-pair). Per
  internalizzarli nel modello servirebbe ricreare l'entity model
  (subjects/classrooms/groups) dentro `experiments/`. Riconsiderare
  quando istanze reali iniziano a fallire per logical-HARD-rejection
  loops.
- **P2** [DONE 2026-04-30 98de2d7] -- simmetria-break via
  `AddDecisionStrategy(sorted_dc_vars, CHOOSE_FIRST, SELECT_MIN_VALUE)`
  in Phase A. Forza un ordine canonico nell'esplorazione delle
  triple ordinate per (prof, classe, materia), riducendo le
  permutazioni equivalenti.

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

- **P2** [DONE 2026-04-30 98de2d7] -- auto-K via eigengap heuristic in
  `decomposition_spectral_v2.auto_k_eigengap(M, k_min, k_max)`: trova
  k* dove `eigvals[k+1]-eigvals[k]` e' massimo. Usato di default
  (`--k 0` = auto). Su small ha selezionato k=2 invece di k=4 -> obj
  iniziale 670 vs 770. Su big rimane sui valori "naturali" del grafo.
- **P2** [DONE 2026-04-30 98de2d7] -- `partition_metrics(M, classes,
  labels, bridges)` ritorna `cluster_sizes`, `balance`,
  `n_internal_edges`, `n_cut_edges`, `cut_ratio`, `n_bridges`,
  `bridge_ratio`. Loggate ad ogni run della pipeline; il dict puo'
  essere salvato sul DB del run per confronti storici.
- **P3** [SKIPPED -- ortools/sklearn KMeans gia' OK fino a 80 classi]
  -- METIS. La decomposizione attuale gestisce bene le 5 profili
  esistenti; METIS aggiunge una dipendenza nativa C per beneficio
  marginale. Riconsiderare se mai si arrivera' >150 classi.

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

- **P2** [DONE 2026-04-30 98de2d7] -- adaptive LNS in `run_lns(...,
  adaptive=True)`: per-operator score `1 + total_delta / n_calls`,
  ops sampled con `random.choices(weights=...)`. Su small l'op
  `one_day` ha avuto score 2.6 e ricevuto 31 chiamate (vs 11/5/8 per
  gli altri) -> LNS converge in 56 iter invece di 141. Su big con
  60s di budget gli operator non collezionano abbastanza sample;
  servono >120s per vedere il bias kick-in.
- **P2** [DONE 2026-04-30 98de2d7] -- ILS con LNS come kick
  (`run_ils(..., lns_kick=True)`): la perturbazione e' un mini-LNS di
  8s invece del singolo `_perturb` (CP repair su 2 giorni). Mantiene
  HARD-feasible per costruzione di `_cp_repair`.
- **P3** [SKIPPED -- complica il threading per beneficio marginale]
  -- portfolio approach (LNS/SA/TS in parallelo). Oggi SA/TS portano
  0% di miglioramento sui dataset testati; la cascata sequenziale
  cattura gia' tutto cio' che la metaeuristica puo' fare. Un portfolio
  in parallelo sarebbe utile solo se le 4 algoritmi avessero
  performance comparable, cosa che non accade in questo dominio
  (LNS domina).

### 3.4 Warm-start e re-ottimizzazione incrementale

Quando l'utente modifica manualmente una lezione (drag-and-drop in
/schedule), si potrebbe ri-ottimizzare la zona "intorno" alla mossa
senza rifare tutta Phase B. Oggi non c'e' un "re-optimize this slot
neighborhood" endpoint.

**Suggerimenti**

- **P1** [DONE 2026-04-30 98de2d7 -- engine helper] -- la funzione
  `repair_slot_neighborhood(sol, profs, dc_value, scope, time_budget)`
  in `experiments/engine_diagnostics.py` ri-ottimizza la zona
  (class_day / class_week / prof_day / prof_week / one_day) usando
  CP-SAT warm-started; ritorna `obj_before/after`, `delta_soft`,
  `metrics_before/after`, `time_used`. Pronto per il wiring lato
  backend (out-of-scope di questa passata, che e' solo engine).
- **P2** [PENDING -- richiede UI] -- "auto-repair" dopo ogni drag-drop.
  Lato engine la helper c'e' gia' (vedi sopra); manca solo il bottone
  in /schedule che la chiami in background. Da fare in una passata
  frontend separata.

### 3.5 Parallelism

`solver.parameters.num_search_workers = workers` e' settato (default
8 in `solve_assignment`). La decomposizione spettrale lancia i cluster
**sequenzialmente** in `cpsat_v2_timetable.py` (`for cluster in ...`).

**Suggerimenti**

- **P2** [DONE 2026-04-30 98de2d7] -- parallel Stage B in
  `run_full_pipeline.py` via `--parallel-cluster-b N`
  (ThreadPoolExecutor; ortools rilascia il GIL durante Solve()).
  I workers CP-SAT vengono ripartiti per evitare oversubscription
  (`workers // N` per task). Default: `n_jobs=1` (sequenziale) per
  backward compat. Su big con N=4 e workers=8 -> 2 workers per task,
  comunque feasibility ok.
- **P3** [SKIPPED -- single-machine sufficiente] -- distribuire fra
  macchine via Celery. La pipeline gira in 5-15 min sul superhuge
  (80 classi); orchestrare su piu' macchine aggiunge ops complexity
  per beneficio nullo nei use case attuali.

### 3.6 Qualita' delle soluzioni

`metrics_json` salva: `sixth, buchi, five, one`. Ogni run ha il suo
SOFT score, ma:

- Non c'e' un **lower bound** mostrato (es. da rilassamento LP) per
  capire quanto siamo lontani dall'ottimo.
- Non c'e' un **anytime UI**: durante il run, l'utente vede solo i log,
  non la curva del SOFT che migliora.

**Suggerimenti**

- **P2** [PENDING -- UI feature] -- grafico SOFT-over-time nel
  `RunLogPanel`. Out-of-scope di questa passata (engine only).
- **P3** [SKIPPED -- modello dual non triviale] -- LP-relaxation
  lower bound + gap. Servirebbe formulare un secondo modello "diagonal"
  in MIP/LP che rilassi le variabili boolean a continue su [0,1] e
  risolverlo con HiGHS o cvxpy. Lavoro 1-2 settimane per produrre un
  numero che, sui dataset reali, sarebbe probabilmente molto vicino
  all'UB (gap < 5%) e quindi poco informativo. Riconsiderare se mai
  ci si trovera' in scenari dove sospettiamo un upper-bound non
  ottimale.

### 3.7 Robustezza ai vincoli "difficili"

Doppia ora mate/ita, motorie a coppie, vincoli logici DNF: gli abbiamo
implementati uno per uno. Funzionano sui mock; pero':

- Su scuole reali, `motorie_pairs=true` puo' rendere infeasible
  un'istanza se le palestre non bastano. Il diagnostic e' un `print`
  in `cpsat_v2_timetable.py`.

**Suggerimenti**

- **P1** [DONE 2026-04-30 98de2d7 -- engine helper] --
  `engine_diagnostics.explain_infeasibility(profs, dc_value, day)`
  ritorna analisi strutturata: Hall violations (prof con piu' ore del
  max class-load), class load outliers (load in {1,2,3} = HARD-2
  violato a monte), prof overload (>5 ore in giorno = HARD-C). Ogni
  voce include i dettagli per identificare il blocco. Pronto per
  l'endpoint `POST /api/optimize/explain-infeasibility` (out-of-scope
  di questa passata).
- **P2** [DONE 2026-04-30 98de2d7 -- engine helper] --
  `engine_diagnostics.auto_relax_suggestion(profs, dc_value, day)`
  produce una lista ordinata di suggerimenti
  (`allow_no_holes_relax_for_classes`,
  `rerun_phase_a_with_relaxed_load`, `reduce_prof_hours_in_day`,
  `increase_solver_time_limit`) ognuno con `expected_unblock` e
  `rationale` human-readable.

### 3.8 Scalabilita' (>100 classi)

I 5 profili attuali topano a "superhuge" (~80 classi). Una scuola
reale grande arriva a 60-80 classi, quindi siamo ai limiti. Oltre
(consorzi, plessi multipli) servirebbe:

**Suggerimenti**

- **P2** [PENDING] -- benchmark a 100/150/200 classi. Crea un profilo
  `mega` con `big_mock_school.py` e misura. Da fare quando arriva il
  primo dataset reale > 80 classi (oggi non c'e').
- **P2** [SKIPPED -- nessun dataset reale necessita di questo] --
  decomposizione gerarchica multi-plesso. Il primo plesso che chiede
  pianificazione multi-comprensivo sara' il trigger naturale.
- **P3** [SKIPPED -- vedi 3.10] -- alternative architetturali.

### 3.9 Diagnostic tools

Oggi: log testuali via SSE, `print()` per le infeasibilita'. Niente
strumento per "perche' questo slot non puo' avere questa lezione?".

**Suggerimenti**

- **P1** [DONE 2026-04-30 98de2d7 -- engine helper] --
  `engine_diagnostics.why_not_lesson(sol, profs, lesson, day, hour)`
  prova a inserire la lezione e ritorna le violations
  (`PROF_OVERLAP`, `CLASS_OVERLAP`, `CLASS_NO_HOLES`, `PROF_HC_LIMIT`)
  con detail human-readable. Pronto per il wiring lato backend.
- **P2** [PENDING -- UI feature] -- visualizer hover-popup in /monitor.
  Out-of-scope di questa passata. La helper sopra alimenta direttamente
  il popup.

### 3.10 Alternative architetturali (costose)

- **MIP puro** invece di CP-SAT: Gurobi/CPLEX/HiGHS sono piu' veloci
  su LP relaxation ma meno espressivi su vincoli logici. Per il phase
  A potrebbe valere la pena. **[SKIPPED 2026-04-30 -- ortools CP-SAT
  attuale risolve in <30s tutte le 5 profili; un porting MIP ridurrebbe
  questa parte ma non sblocca nuovi use case.]**
- **MiniZinc / Choco**: linguaggio dichiarativo, multiple solver
  backend. Lavoro di port stimato in 2-4 settimane. **[SKIPPED
  2026-04-30 -- 2-4 settimane di port per beneficio incerto; un porting
  parziale (solo Phase B) richiederebbe comunque mantenere due
  modelli paralleli, costo manutenzione doppio. Riconsiderare se
  arrivano scuole > 150 classi.]**
- **Local search puro** (HyFlex / Optaplanner): per schools enormi,
  rinunciare alla completeness di CP-SAT e usare solo metaeuristiche
  con vicinati ricchi. **[SKIPPED 2026-04-30 -- la cascata LNS+SA+TS+ILS
  attuale gia' fa local-search-puro post-decomposizione; sostituirla
  con OptaPlanner Java aggiunge un secondo runtime senza guadagnare
  nulla in qualita'. Per "scuole enormi" abbiamo gia' la
  decomposizione spettrale.]**

**Costo/beneficio**: oggi non urgente. Vale la pena solo se:
- ti trovi infeasibility frequenti -> piu' diagnostic tools (P1) prima
  [DONE 2026-04-30 98de2d7].
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
