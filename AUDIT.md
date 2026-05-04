# piTantum — Audit generale

Audit basato su lettura del codice, evidenze citate con `path:lineno`. Tutto
ciò che non ho potuto misurare è marcato esplicitamente *(non testato)*.
Sintesi degli scenari italiani applicata a un solo punto di osservazione: la
codebase com'è ora.

## Executive summary

1. **L'engine scala fino a ~80 classi documentate** dall'autore in
   `proposals/benchmarks.md`: big (30 cl) ~62s end-to-end, huge (50 cl)
   ~122s, superhuge (80 cl) ~903s — sono numeri suoi, su CP-SAT 8 worker.
   Per il liceo medio italiano (35 classi) la pipeline è realistica; per
   IIS grandi (60-80 classi) il tempo solver è già nell'ordine dei
   minuti.
2. **Due vincoli italiani importanti sono modellati a livello DB ma NON
   enforced dal solver**: compresenze (`CoTeachingRule`) e gruppi
   articolati (`StudyGroup` + `GroupSubjectHours`). Il solver li ignora.
   `Assignment.locked` è gestito con uno snapshot/restore *intorno* al
   solve (`optimization.py:484, 1797, 1835`), non come constraint nativo
   — funziona per una rerun mirata, ma non è una soluzione strutturale.
3. **Un layer di multi-tenancy esiste come scaffolding ma non è
   applicato**: `TenantMixin` è su 7 entità, header `X-Tenant-Id` letto,
   ma nessun router filtra le query per `tenant_id`. Allo stato attuale
   è un controllo di accesso *zero*.
4. **Frontend regge dimensioni medie ma manca virtualization**: tutte le
   tabelle (SortableQueryableList, GroupedEventsTable) renderizzano in
   DOM la pagina corrente; la matrice orario è single-entity
   (180 celle). 60 classi × 30 ore non vengono mai chieste tutte
   insieme: si naviga una classe alla volta.
5. **Il fix WAL di oggi ha eliminato il bottleneck di concorrenza
   reader/writer**, ma il problema più strutturale rimane: lo stesso
   processo che serve la UI ospita anche i thread CPU-bound del solver.
   In single-user dev funziona; in produzione multi-utente sarebbe
   meglio separare worker.

---

## Frontend — `webui/frontend`

**Stack**: SvelteKit + Svelte 5 + Tailwind + Vite. Build chunked per
route. Cytoscape ed echarts importati lazy
(`EntityGraph.svelte`, `EChart`).

### Cosa regge

- **Pattern tabella unificato**: `SortableQueryableList.svelte` è il
  workhorse di tutti i tab CRUD (teachers/classes/classrooms/...). Query
  DSL sul backend, paginazione 25/50/100/250/all, sort multi-livello,
  selezione con shift/ctrl+click, export xlsx/csv server-side.
- **Stores leggeri ma centrati**: `lib/stores.ts` espone `datasetState`
  (snapshot tabelle), `mutationCounter` con refresh debounced 120ms,
  `toast` con TTL, `networkOnline` con health-ping ogni 30s. Niente
  state management pesante.
- **Code-split delle dipendenze grosse**: cytoscape e echarts sono
  caricati on-demand. Il bundle iniziale resta proporzionale alla
  route visitata.

### Cosa fa scricchiolare l'UX a scala media-grande

- **Niente virtualization**: con 80 classi × 30 colonne in
  `GroupedEventsTable` (default `pageSize=100`), il DOM resta nei limiti
  *finché si pagina*. Ma se l'utente sceglie `pageSize=500` o "tutte"
  per fare bulk apply, il render rallenta visibilmente *(non testato di
  persona, inferito dal numero di colonne renderizzate per riga)*.
- **TanStack Query è in `package.json` ma non usata**
  (`lib/queries/index.ts:1-50` è scaffolding inerte). Tutti i ~50
  componenti chiamano `api.get/post/put/del()` direttamente. Manca la
  cache lato client → ogni navigazione fra tab rifa GET su endpoint
  che ritornerebbero la stessa cosa. Non rotto, solo subottimale.
- **Schedule è single-entity**: il componente
  `routes/schedule/+page.svelte` mostra 1 classe / 1 docente / 1 aula
  alla volta su griglia 6×30. Non c'è una view "tutto l'istituto" —
  per istituti grandi l'utente deve navigare entità per entità. Il
  drag-drop con `move-preview` è ben fatto, ma scoping per-entità.
- **A11y warning concentrate**: 269 warning in 6 file (BulkApplyModal,
  NewConstraintModal, PlaceEventModal, schedule/+page,
  AvailabilityMatrix, ClassroomGrid). Il pattern dominante è
  `<label>` senza `for=`. Nessun warning bloccante; problemi reali per
  screen reader e tabulazione tastiera, irrilevanti per il prof
  utente principale.

### Bulk operations

- `BulkApplyModal` (entities) e il nuovo `BulkEventsModal` (eventi
  /monitor, fatto oggi) seguono lo stesso flow dry-run → conflitti →
  skip|override. Nessun limite hardcoded sulle selezioni — accettano
  qualsiasi array. Il throughput è limitato dal backend, non dal
  client.

### Stampa / export

- Nessun `window.print()`. Tutti gli export passano dal backend con
  Content-Disposition: xlsx/csv generati server-side
  (`SortableQueryableList.svelte:319`, `schedule/+page.svelte:362`).
  PDF dell'orario via endpoint dedicato. Per scuole reali manca un
  layout "stampa orari classi" cumulato (tante pagine, una per
  classe/docente).

---

## Backend — `webui/backend`

**Stack**: FastAPI sync-first, SQLAlchemy 2 con `Mapped`, Alembic
(9 revisioni in `alembic/versions/`). Pydantic per le request/response
in `schemas.py` (~71 modelli).

### Cosa regge

- **Error handling globale strutturato**: 5 handler in
  `main.py:199-302` producono response coerenti
  `{detail, code, errors[], hint, request_id}`. Coperti da
  `tests/test_errors.py`.
- **TTL cache piccola ma corretta**: `utils/ttl_cache.py` (57 righe)
  thread-safe, mutation-aware via `bump_mutation()`. Usato su
  `dataset/state`, `monitor/summary`, `dataset/available-profiles`.
- **Pattern N+1 mitigato per design**: dove ho controllato
  (`schedule.py:164`, `monitor.py:64-90`) il codice fa "bulk load
  → dict by id" prima del loop, non lazy-load via relationship. Non
  ho trovato veri N+1 in hot path.
- **Run management con threading + buffering**: `run_manager.py` (314
  righe) gestisce thread bg per i diagnostic / optimize. Logs in ring
  buffer + threading.Condition per SSE.

### Cose che meritano attenzione

- **Multi-tenant scaffolding senza enforcement** *(critico)*. 7 entità
  hanno `tenant_id` con default 1, esiste `current_tenant_id()` che
  legge `X-Tenant-Id`, ma nessun router filtra per tenant. In pratica:
  qualunque header diventa il tenant del client, ma le query restano
  globali. Se la cosa rimane così e un giorno si abilita auth per
  due scuole sulla stessa istanza, leak immediato.
- **`Assignment.locked` non è un constraint del solver**
  (`optimization.py:484` lo dice esplicito: *"optimizer doesn't
  natively know about Assignment.locked"*). Funziona via snapshot
  pre-solve + restore post-solve (`_snapshot_locked_lessons`,
  `_restore_locked_lessons`). Per il caso "ho aggiunto un docente,
  rilancia ma non toccare le cattedre già piazzate" funziona
  praticamente, però la qualità della soluzione finale può degradare
  (il solver libera quelle ore, poi le riempi a forza, il resto si
  riassesta come può).
- **Run senza crash recovery**: se il processo muore con un thread
  attivo, la `Run` resta `running` in DB e nessuno la rimuove. Per
  dev pace, in produzione con riavvii frequenti è una pulizia
  manuale.
- **Run.solution_id senza index** *(piccolo)*: `models.py` linea 523
  circa, `Run.solution_id` non ha `index=True`. Le query di runs
  filter-by-solution sono O(N).
- **Paginazione adoption ad-hoc**: `utils/pagination.py:paginated_or_list`
  c'è ed è pulito, ma solo ~6 endpoint la usano (students, events,
  event-rows, incomplete-events). Il resto ritorna liste flat. A
  liceo piccolo va bene; a IIS grande
  `/api/teachers` (130 docenti) o `/api/curricula` (8 curricola)
  non sono comunque problematici. `/api/lessons` se mai esiste o
  esisterà sì.
- **`_apply_lightweight_migrations` (db.py:120-310) duplica
  Alembic**. Pragmatico in dev (utenti che non lanciano alembic),
  rischioso in prod multi-server (divergenza schema). Pattern da
  consolidare prima di un eventuale deploy multi-server.
- **Validazioni pesi numerici aperte**: i `weight` SOFT (es.
  `pref_no_buchi_weight`, `multi_class_pref_weight`) sono `Float`
  senza `ge=0`. Un -∞ per errore degrada subito l'objective. Test
  scoperto.

### Test

17 file in `tests/`. Coperti: auth, pagination, errors, DSL parsing,
TTL cache, perf budgets, multi-tenant scaffolding, dashboard io,
phase-A endpoints, telemetry. Non coperti: stress test bulk con N >
1000, run crash recovery, vincoli del solver vs casi italiani
(compresenze, gruppi articolati).

---

## Engine — `experiments/`

⚠️ Il motore vero e proprio sta in `experiments/`, non in `schedule/`
(che contiene `.pkl` e script storici). Il nome "experiments" è
fuorviante: è production code, secondo `webui/backend/optimization.py`
che lo importa.

### Cosa fa

CP-SAT a 2 fasi (`cpsat_v2_timetable.py:177, 531`):
- **Phase A** — assegna ore-cattedra per giorno. Variabili
  `day_count[(prof, class, subject, day)]` IntVar in [0, ore].
- **Phase B** — placement intra-day in 8..13. Variabili
  `slot[(prof, class, subject, hour)]` BoolVar.
- **Metaeuristiche post-solve** in `metaheuristics.py` (LNS / SA / TS
  / ILS, 928 righe) operano sulla soluzione completa con move
  operators che preservano la feasibility hard.

### Vincoli HARD codificati

| Vincolo | File:linea |
|---|---|
| Coverage `sum_d day_count == ore` | cpsat_v2_timetable.py:191 |
| Slot 8-13 fissi | cpsat_v2_timetable.py:32 (`HOURS=[8..13]`) |
| Uscita ≥ 12 (`cl_day_load in {0,4,5,6}`) | cpsat_v2_timetable.py:219 |
| Pairing matematica/italiano | cpsat_v2_timetable.py:370 |
| Coppia scienze motorie | cpsat_v2_timetable.py:380 |
| Max 5 ore/giorno per docente | cpsat_v2_timetable.py:72 |
| Free-day (HARD count) | cpsat_v2_timetable.py:283 |

Hall-witness check pre-solve (`diagnostics/hall_check.py`) elimina
infeasibilità banali prima di lanciare CP-SAT — ben fatto.

### Casi italiani: cosa è coperto e cosa no

| Caso | Stato | Note |
|---|---|---|
| Free day docente (HARD/SOFT) | ✅ | Phase A constraint + 3-way preferenza |
| Cattedra spezzata (`TeacherMandatoryFreeDay`) | ⚠️ Parziale | Solo "giorno intero off". Niente split-hour fra istituti. |
| Compresenze | ⚠️ Solo DB | `CoTeachingRule` esiste, *nessun grep di constraint corrispondente in cpsat_v2*. Il solver non sa di esse. |
| Gruppi articolati / sdoppiamenti | ⚠️ Solo DB | `StudyGroup` + `GroupSubjectHours` modellati, ma il solver non li vincola. |
| Palestra a settimane alterne | ❌ | No grep di `biweekly`, `alternate`, fractional hours. |
| Aule per piano / accessibilità | ❌ | Out-of-scope dichiarato (`docs/ui_guide.md:689`: "il check non modella le aule per scalabilità"). Classroom assignment è un passo separato post-solve. |
| Lock cattedre | ⚠️ Workaround | Snapshot/restore, non constraint nativo. |
| Alternanza scuola-lavoro | ❌ | Niente periodi di assenza programmata classe. |

### Performance documentata dall'autore

`proposals/benchmarks.md` — numeri suoi, su sua macchina, CP-SAT 8
worker, default budget Phase A = 30s, Phase B = 30s:

| profilo | classi | docenti | totale solve |
|---|---|---|---|
| big | 30 | ~74 | ~62s (30+32) |
| medium | 25 | ~83 | ~62s |
| huge | 50 | ~101 | ~122s (60+62) |
| superhuge | 80 | ~159 | ~903s (300+603) |

⚠️ La crescita non è lineare: 30→80 classi costa 14× il tempo (la
fase B è quella che esplode). Per IIS da 1500 studenti / 60-80 classi
si parla di 5-15 minuti di solver, non secondi. Il dev DB attuale
ha 10 classi, 20 docenti, 1220 lezioni — caso "small" stretto, non
rappresentativo.

### Re-runnabilità

Phase A e Phase B sono separate ma chiamate in pipeline — non c'è
un endpoint "rilancia solo Phase B con Phase A fissa" (potrebbe
esserci, non l'ho trovato esplicito). Le metaeuristiche in
`metaheuristics.py` *sono* il riassesto incrementale: prendono una
soluzione completa e cercano miglioramenti locali — questo è il
pattern "ho cambiato 3 cose, riassesta" già supportato.

### Diagnostics pre-solve

Quattro endpoint async (montecarlo, bipartite, correlations,
distributions) che il fix di oggi ha stabilizzato. Strumenti utili
per capire perché un dataset è infeasible PRIMA di sprecare 10 minuti
di solver — buona pratica.

---

## Miglioramenti prioritizzati

### Critici (bug latenti o limiti hard)

1. **Compresenze e gruppi articolati nel solver**. Sono uno dei
   motivi principali per cui un orario italiano è complicato. Stanno
   nel DB ma il solver non li vede → la soluzione finale può violare
   i vincoli reali della scuola e l'utente deve aggiustarla a mano.
   *Effort stimato: 1-2 settimane (constraint posting in Phase B,
   test su scuola con gruppi reali).*
2. **Multi-tenancy o si applica o si rimuove**. Lo scaffolding senza
   enforcement è peggio del non averlo: dà la falsa sensazione che
   l'isolamento esista. Se si vuole davvero supportare due scuole
   sulla stessa istanza, va aggiunto il filter su tutti i router (è
   un retrofit invasivo). *Effort: 1 settimana per il retrofit + 1
   settimana di test.* Se non è una direzione attuale, rimuovere il
   `TenantMixin` è 1 giorno e toglie un footgun.
3. **Run crash recovery**. Banale: a startup, marca come `error` ogni
   `Run` con `status='running'` senza thread attivo. *Effort: 1
   giorno.*
4. **Validazione bound sui weight SOFT**. `Field(..., ge=0)` su
   tutti i campi `_weight` evita un -∞ che annulla l'objective.
   *Effort: poche ore.*

### Architetturali (limitano l'evoluzione)

5. **Engine in `experiments/`**. È production code, il nome confonde
   chiunque arrivi sulla codebase. Dovrebbe stare in `engine/` o
   simile, con un `__init__.py` che espone la API pubblica.
   *Effort: mezza giornata di rinomine + import fix.*
6. **`_apply_lightweight_migrations` vs Alembic**. Decidere: o uno o
   l'altro. Per il momento il fallback è utile, ma rende le revisioni
   Alembic non autoritative. Consolidamento prima del deploy
   multi-server. *Effort: 2-3 giorni.*
7. **TanStack Query: usarla o rimuoverla**. Il pattern attuale
   "api.X diretta + mutationCounter + refresh debounced" funziona ma
   richiede invalidazione manuale. Adottare TanStack come single
   source of truth eliminerebbe ~30 useEffect-equivalent.
   *Effort: 1-2 settimane di porting incrementale, route per route.*
8. **Pagination uniforme su tutti i list endpoint**. Anche se oggi i
   volumi non lo richiedono, il pattern `paginated_or_list` è già
   pronto — applicarlo a tutti i `/api/*` list endpoint costa poco e
   ferma la classe di bug "list endpoint che esplode con tante
   righe". *Effort: 2-3 giorni.*
9. **Separare worker solver dal processo web**. CPU-bound nel
   processo che serve la UI è già un problema oggi (il fix WAL ne
   è la prova). Un `runner` separato che pesca jobs da una queue
   eliminerebbe il problema strutturalmente. *Effort: 1-2 settimane,
   architetturale, non urgente.*

### Quality of life

10. **View "tutto l'istituto" sull'orario**. Per il preside o per
    stampare gli orari di tutte le classi, oggi serve navigare 60
    volte. Una pagina `/schedule/all` con thumbnail per classe (clic
    → dettaglio) coprirebbe il caso "stampa cumulativa". *Effort:
    3-5 giorni.*
11. **Virtualization su tabelle grandi**. `GroupedEventsTable` con
    pageSize=500 inizia a sentire. svelte-virtual o equivalente,
    solo dove serve. *Effort: 2-3 giorni per integrare e testare.*
12. **Copia da anno scolastico precedente**. Casistica reale: a
    settembre il segretario duplica l'anno e modifica solo classi
    nuove / docenti aggiunti. Manca un workflow esplicito. *Effort:
    1 settimana (export → import + diff helper).*
13. **A11y cleanup**. 269 warning sono clusterizzate in 6 file —
    una pass mirata dimezza il numero. *Effort: 1-2 giorni.*
14. **Rimuovere TanStack Query dalle deps se si decide di non
    usarla** (vedi #7). Risparmia ~50KB nel bundle. *Effort: 5
    minuti.*
15. **Rinominare cartella `experiments/`** (vedi #5).

---

## Cose che NON ho potuto verificare

- Tempi reali del solver su DB grandi (il dev DB è 10 classi). I
  numeri vengono da `proposals/benchmarks.md` — fidiamoci dell'autore
  per ora, ma una ri-misura su hardware diverso sarebbe utile.
- UX di `GroupedEventsTable` con 60 classi × 30 colonne effettive
  (ho letto il codice, non ho lanciato il dev server).
- Comportamento del fix WAL sotto carico concorrente reale (test
  passa, ma "due utenti che modificano il dataset mentre gira un
  solver" non è coperto da test automatici).
- Robustezza dell'import/export con il dev DB attuale (4.2MB) vs un
  DB di scuola grande (probabilmente 50-100MB).

## Cosa ha già fatto oggi che era nell'audit

- Fix WAL per concorrenza reader/writer SQLite — risolto.
- BulkEventsModal su /monitor — coperto.
- Test perf con warmup + checkpoint — stabilizzato.
- Update test hall_check al nuovo contract async — fatto.
