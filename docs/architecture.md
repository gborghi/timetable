# Architecture (English summary)

piTantum is a three-tier system: a CP-SAT solver core
(`engine/`), a FastAPI + SQLite backend (`webui/backend/`), and
a SvelteKit frontend (`webui/frontend/`). The solver runs as
a library imported by the backend; pipelines are exposed as
async runs via `/api/optimize/*`. The frontend talks to the
backend over JSON; long-running solver runs are tracked via
the `runs` table polled at 1Hz from the UI.

Solver pipelines (in `engine/`):
- `cpsat_v2_assignment.py`: Phase A (teacher → class
  assignment).
- `cpsat_v2_timetable.py`: Phase A (timetabling, day_count) +
  Phase B (per-day slot placement). Native locks + C1/C2/C3
  constraints.
- `decomposition_temporal.py`: 6-day parallel decomposition.
- `decomposition_spectral_v2.py` (+ curriculum/metis): cluster
  classes, solve sub-problems, ricucitura.
- `column_generation.py`: master LP + diversified pattern
  enrichment + completion fallback. `mode="branch-and-price"`
  scaffold for future scalability work.
- `metaheuristics.py`, `alns.py`, `vns.py`, `lagrangian.py`:
  post-processing on a HARD-feasible seed solution.

For the formal description (in Italian) of every component,
read on. A full English translation of this document is
pending; see [`README.md`](../README.md) for the bilingual
project overview.

---

# Architettura: i tre piani del sistema piTantum

Per dare un'idea di insieme di com'e' fatto piTantum, si puo'
pensare al sistema come a un edificio a tre piani:

- al **piano terra** c'e' il "motore" matematico (CP-SAT, le
  metaeuristiche, le decomposizioni). E' la parte che, dato un
  problema d'orario, lo risolve;
- al **primo piano** c'e' il backend (FastAPI + SQLite) che traduce
  i dati della scuola nel linguaggio del motore, conserva tutto in
  un database, e offre un'API REST con cui dialogare;
- al **secondo piano** c'e' il frontend (SvelteKit) che mostra
  tutto in una web app navigabile dal browser.

Questa pagina descrive in dettaglio ognuno dei piani, le
tecnologie usate, come si parlano fra loro, e dove cercare i
sorgenti se vuoi mettere mano al codice.

> **Per chi sviluppa**: i tre layer corrispondono alle cartelle
> `experiments/`, `webui/backend/`, `webui/frontend/` del repo.

## Panoramica

Il progetto ha tre layer:

1. **Solver** (`experiments/`): pipeline CP-SAT (Google OR-Tools) con
   decomposizione spettrale per istanze grandi e cascata metaeuristica
   (LNS, Simulated Annealing, Tabu Search, Iterated Local Search).
2. **Web UI** (`webui/`): backend FastAPI su SQLite + frontend SvelteKit.
   La UI e' il punto di accesso quotidiano: gestisce CRUD, ottimizzazione,
   visualizzazione, drag-and-drop, assenze e supplenze.
3. **Legacy** (`schedule/`): script monolitici da cui il solver e' nato;
   mantenuti per riferimento storico.

```
   +---------------------+
   |  SvelteKit (Vite)   |  http://127.0.0.1:5173
   |  16 tabs, ~30 pages |
   +----------+----------+
              |
              | proxy /api/* -> :8000
              v
   +---------------------+
   |   FastAPI backend   |  http://127.0.0.1:8000
   |  18 routers, ~118   |
   |  endpoint REST      |
   +----------+----------+
              |
              | SQLAlchemy 2.0
              v
   +---------------------+
   |  SQLite             |  webui/data/timetable.db (~320 KB iniziale)
   |  ~30 tabelle        |
   +----------+----------+
              |
              | engine_io.py (pickle conversion)
              v
   +---------------------+
   |  CP-SAT engine      |  experiments/cpsat_v2_*.py
   |  + spectral decomp. |  experiments/decomposition_spectral_v2.py
   |  + metaheuristics   |  experiments/metaheuristics.py
   +---------------------+
```

## Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic 2,
  uvicorn, OR-Tools, NumPy, scikit-learn (per la decomposizione spettrale),
  Faker (per i mock).
- **Frontend**: SvelteKit (Svelte 4), Vite 5, Tailwind CSS, pure JS
  (niente TypeScript per ora).
- **DB**: SQLite via SQLAlchemy. Migrazioni idempotente nel codice
  (no Alembic): vedere `webui/backend/db.py::_apply_lightweight_migrations`.
- **Engine I/O**: pickle Python; `webui/backend/engine_io.py` converte
  fra DB e dict per il solver.

## Struttura cartelle

```
timetable/
+-- README.md                    -- landing page
+-- docs/                        -- manuale tecnico (questa cartella)
|   +-- README.md                -- indice
|   +-- architecture.md          -- questo file
|   +-- ...
|   +-- manual.tex               -- sorgente LaTeX
|   +-- manual.pdf               -- PDF compilato
+-- experiments/                 -- solver code + pickle snapshots
|   +-- cpsat_v2_assignment.py   -- Phase A
|   +-- cpsat_v2_timetable.py    -- Phase B (CP-SAT scheduler)
|   +-- decomposition_spectral_v2.py
|   +-- metaheuristics.py        -- LNS / SA / TS / ILS
|   +-- classroom_assignment.py  -- 3rd phase
|   +-- exporters.py
|   +-- run_full_pipeline.py
|   +-- run_meta_only.py
|   +-- big_mock_school.py       -- mock generator
|   +-- profs_*.pkl              -- per-profile snapshots
|   +-- school_*.pkl
|   +-- solution_timetable_*.pkl
|   +-- curricula.pkl
|   +-- output/
+-- schedule/                    -- legacy single-file prototypes
|   +-- mock_classes2.py         -- canonical curriculum-hours grids
|   +-- prog4.py                 -- last legacy iteration
|   +-- ...
+-- webui/
|   +-- start.bat                -- launcher Windows
|   +-- start.sh                 -- launcher Linux / macOS
|   +-- stop.sh                  -- stop helper Linux / macOS
|   +-- README.md                -- guida operativa locale
|   +-- backend/
|   |   +-- main.py              -- FastAPI app + lifespan
|   |   +-- db.py                -- engine + Base + migrazioni
|   |   +-- models.py            -- ORM (SQLAlchemy 2.0)
|   |   +-- schemas.py           -- Pydantic in/out
|   |   +-- engine_io.py         -- DB <-> pickle
|   |   +-- optimization.py      -- launcher per le 4 fasi
|   |   +-- run_manager.py       -- background runs + log streaming
|   |   +-- mock_classrooms.py   -- recipe per le aule auto
|   |   +-- mock_students.py     -- generatore Faker
|   |   +-- seed_curricula.py    -- seed indirizzi
|   |   +-- requirements.txt
|   |   +-- routers/             -- 18 router REST
|   |   |   +-- assignments.py
|   |   |   +-- bulk.py
|   |   |   +-- classes.py
|   |   |   +-- classrooms.py
|   |   |   +-- coteaching.py
|   |   |   +-- coverage.py
|   |   |   +-- curricula.py
|   |   |   +-- dataset.py
|   |   |   +-- groups.py
|   |   |   +-- imports.py
|   |   |   +-- logical.py
|   |   |   +-- monitor.py
|   |   |   +-- optimize.py
|   |   |   +-- schedule.py
|   |   |   +-- students.py
|   |   |   +-- subjects.py
|   |   |   +-- teachers.py
|   |   +-- utils/
|   |       +-- query_parser.py  -- DSL parser (campi/operatori/sort)
|   |       +-- list_query.py    -- adapter per entita'
|   |       +-- logic_parser.py  -- DNF parser per vincoli logici
|   +-- frontend/
|   |   +-- package.json
|   |   +-- vite.config.js
|   |   +-- svelte.config.js
|   |   +-- tailwind.config.js
|   |   +-- src/
|   |       +-- routes/          -- 16 pagine
|   |       |   +-- +layout.svelte    -- nav bar
|   |       |   +-- +page.svelte      -- Dashboard
|   |       |   +-- teachers/
|   |       |   +-- classes/
|   |       |   +-- curricula/
|   |       |   +-- students/
|   |       |   +-- groups/
|   |       |   +-- subjects/
|   |       |   +-- classrooms/
|   |       |   +-- coteaching/
|   |       |   +-- assignments/
|   |       |   +-- schedule/
|   |       |   +-- assenze-supplenze/
|   |       |   +-- monitor/
|   |       |   +-- constraints/
|   |       |   +-- optimize/
|   |       +-- lib/
|   |           +-- api.js            -- thin fetch wrapper
|   |           +-- stores.js         -- toast + dataset state
|   |           +-- constants.js
|   |           +-- components/
|   |               +-- Modal.svelte
|   |               +-- AvailabilityMatrix.svelte (5 stati)
|   |               +-- ClassroomGrid.svelte (5 stati)
|   |               +-- LogicalUnavailabilitiesPanel.svelte
|   |               +-- BulkApplyModal.svelte
|   |               +-- ImportButton.svelte
|   |               +-- SortableQueryableList.svelte
|   |               +-- RunLogPanel.svelte
|   |               +-- Toast.svelte
|   +-- data/
|   |   +-- timetable.db          -- ~320 KB iniziale; cresce con i dati
|   |   +-- runs/                 -- output dei job (log)
|   +-- docs/                     -- guide brevi user-facing
|   |   +-- bulk_operations.md
|   |   +-- classroom_generation.md
|   |   +-- constraints.md
|   |   +-- import_format.md
|   |   +-- logical_constraints.md
|   |   +-- move_preview.md
|   |   +-- query_examples.md
+-- proposals/                    -- design notes + benchmarks
|   +-- analysis.md
|   +-- benchmarks.md
+-- *.pdf                         -- reference papers (VLNS, spectral, ...)
+-- .gitattributes                -- *.sh eol=lf, *.bat eol=crlf
+-- .gitignore
```

## Avvio

### Windows

`start.bat` apre due finestre cmd separate per backend e frontend. Pre-flight:
- npm reachable (forza nel PATH le cartelle nodejs standard)
- venv esiste in `backend/.venv/Scripts/python.exe`
- `backend/main.py` e `frontend/package.json` presenti
- se `frontend/node_modules` manca, lancia `npm install`
- avvisa se le porte 8000 / 5173 sono gia' occupate

I path nello script sono **relativi** allo script stesso (`%~dp0`), quindi
funziona in qualunque cartella. Vedere il sorgente in
`webui/start.bat`.

### Linux / macOS

`start.sh` mirror dello script Windows. Per default avvia in **background**
(nohup, log in `webui/logs/`, PID in `webui/logs/pids`); con `-f` o
`--foreground` resta in foreground con trap su Ctrl+C che killa entrambi.

Auto-crea `backend/.venv` e fa `npm install` se mancano. Se python3 / npm
non sono nel PATH, stampa il comando di install per `apt` / `dnf` / `pacman`
/ `brew` o il link a nodejs.org.

`stop.sh` legge `webui/logs/pids`, manda SIGTERM (fallback SIGKILL dopo 3s)
ai due processi e ai loro figli (`pkill -P`); ha un fallback che killa
qualunque processo sia ancora in ascolto su 8000 / 5173 via `lsof`.

## Avvio manuale

```
cd webui/backend
.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# in un'altra shell
cd webui/frontend
npm run dev    # vite su 5173
```

## Lifecycle del backend

`webui/backend/main.py` definisce un `lifespan` che chiama `init_db()` allo
startup. `init_db()` fa:

1. `Base.metadata.create_all(bind=engine)` -- crea le tabelle mancanti.
2. `_apply_lightweight_migrations()` -- ALTER TABLE idempotenti per i
   campi aggiunti in versioni successive (esempio: `school_classes.curriculum_id`,
   `teachers.last_name/first_name/nickname`, `nickname` su student/class/group,
   `state` su `classroom_subject_preferences`, `kind` su
   `logical_unavailabilities` e `curriculum_logical_constraints`). Ogni
   ALTER e' guardato da `PRAGMA table_info` per non duplicare.

Non si usa Alembic: ogni migrazione futura va aggiunta a
`_apply_lightweight_migrations` con un check di idempotenza. Vedere
[extending.md](extending.md) per il pattern.

## Pre-fetch dei moduli engine

`backend/engine_paths.py` aggiunge `experiments/` al `sys.path` di Python
in modo che `import metaheuristics`, `import cpsat_v2_timetable`,
`import decomposition_spectral_v2`, ecc. funzionino senza pacchettizzare il
codice solver. I router che lanciano l'ottimizzazione fanno
`import metaheuristics as meta` lazily (dentro le funzioni) per non
appesantire il boot.

## Solver: vincoli italiani C1 + C2 + C3 e lock nativi

Aggiornamento 2026-05-04/05: l'engine ora modella nativamente in
CP-SAT cinque famiglie di vincoli specifici della scuola italiana
che prima erano solo schema-level o gestiti via snapshot/restore.

### Lock nativi (sostituiscono snapshot/restore)

`Assignment.locked = True` (toggle dalla UI) si traduce in vincoli
CP-SAT diretti:
- **Phase A** (`solve_phase_a`): per ogni `(prof, class, subject,
  day, n_locked)` derivato dai Lesson lockati, `day_count[(p, cl,
  subj, d)] >= n_lock`.
- **Phase B** (`solve_phase_b_for_day`): per ogni `(prof, class,
  subject, hour)` lockato, `slot[(p, cl, subj, h)] == 1`.

Pre-flight `validate_locks_vs_constraints` confronta i lock con
free_day del docente, max_hours_per_day della classe, vincoli HARD
di compresenza. Le violazioni sono restituite come 400 al POST
prima che la run parta. Pipeline supportate: tutte
(monolitica + temporale + spectral_v2 + curriculum + metis +
column_generation + ALNS/VNS/Lagrangian + classroom_assignment).

### C1 -- Compresenze (CoteachGroup)

Due varianti, entrambe enforced come vincoli CP-SAT:

**Shared** (lab di chimica con assistente, ecc.):
- IntVar `coday_count[(gid, d)]` in `[0, n_hours]`, sum_d == n_hours.
- `day_count[principal, X, S, d] >= coday_count[gid, d]`.
- `day_count[codoc, X, S, d] == coday_count[gid, d]`.
- Phase B: BoolVar `coslot[(gid, h)]`, sum_h == coday[d];
  `slot[member, X, S, h] >= coslot[(gid, h)]` per ogni member.
- Codoc triples escluse da `cl_day_load` e `ore_per_classe` (le ore
  vengono contate via il principal).

**Shadow** (sostegno DVA):
- `Assignment.is_support = True`.
- `slot[(sost, X, sost, h)] <= pr_per_cl_h[(X, h)]` -- la presenza
  del sostegno implica la classe gia' in lezione.
- Triple di sostegno escluse dal class-busy aggregator.

### C1 -- Potenziamento (Legge 107)

`Assignment.is_potenziamento = True`, `class_id = NULL`. Cattedra
senza-classe, ore schedulate ma non producono `Lesson`. Il prof
diventa prioritario nel tab `/assenze-supplenze`.
- IntVar `pot_day_count[(p, d)]` in `[0, MAX_PROF_HOURS_PER_DAY=5]`,
  sum_d == pot_total.
- `pot_day_count[(p, d)] + prof_day_load[(p, d)] <= 5` (cap
  giornaliero combinato cattedre + potenziamento).
- Cap settimanale HARD: 30 ore (5 ore/giorno x 6 giorni).
- Salvato in `dc_value` con chiave namespacata
  `("__pot__", prof, d)`.

### C2 -- Parallel groups intra-classe

`Assignment.parallel_group_id` lega N Assignments della stessa
classe da schedulare nello stesso slot (es. religione + alternativa
in 3B):
- Phase A: `day_count[m1, d] == day_count[m2, d]` per ogni d.
  Members[1:] esclusi da `cl_day_load` e `ore_per_classe`.
- Phase B: `slot[m1, h] == slot[m2, h]` per ogni h. Class-busy
  aggregator usa `parallel_subj_to_busy_key`: tutti i membri della
  parallela condividono la stessa busy_key, quindi la classe conta
  come busy ONCE anche con N membri.

### C3 -- Inter-class StudyGroup scheduling

Modello dati Opzione B (cfr. data_model.md):
- `Assignment.group_id` nullable (XOR con `class_id`).
- `CoteachGroup.group_id` nullable (XOR con `class_id`).
- `Lesson.group_name` nullable.

Solver:
- `engine_io.group_assignments_for_solver(db)` carica le
  Assignments con group_id, risolve `home_class_names` via
  `GroupMembership` + `Student.class_id`.
- Phase A: augmenta `triples` con `(teacher, group_name, subject,
  n_hours)`. Il `group_name` NON e' in `classes` (no `cl_day_load`,
  no HARD-2 sulla virtual class).
- Phase A vincolo per-day capacity:
  `cl_day_load[home_cl, d] + sum(group_day_count[g, d]) <= 6`
  su ogni classe-madre toccata. Sostegno-sul-gruppo escluso (segue
  un'altra lezione, non aggiunge slot).
- Phase A Hall-like fix: `prof_day_load <= max(cl_day_load)` e'
  saltato per profs con SOLO classi virtuali (altrimenti
  forzerebbe le loro ore a 0).
- Phase B: la triple di gruppo entra in `triples_active`. Il
  class-busy aggregator aggiunge il group_slot come `subj_busy_var`
  per OGNI classe-madre dei membri, sotto la busy_key
  `__grp__<group_name>__<subject>`. L'invariante
  `sum(subj_busy) == pr` garantisce che la classe-madre non faccia
  altre lezioni nello stesso slot.
- Phase B HARD-2 / no-holes: applicate solo alle classi-con-direct
  triples. Una classe toccata SOLO da gruppi e' esente.

### C3 -- Coteach + sostegno su gruppo

CoteachGroup.group_id (XOR class_id): le ore di compresenza si
applicano alla virtual class del gruppo. `coteach_groups_for_solver`
ritorna `class_name = group_name`; il modello CP-SAT esistente
(`coday_count`, `coslot`, principal/codoc) lavora invariato.

Sostegno con `is_support=True` + `group_id`: il prof segue lo
studente DVA dentro il gruppo.
- Phase A: `day_count[sost, G, sost, d] <= sum(non-support group
  day_counts on day d)` -- il prof puo' essere nel gruppo solo nei
  giorni in cui il gruppo si riunisce.
- Phase B: `slot[sost, G, sost, h] <= OR(slot[m, G, subj, h] for
  non-support members of G)` -- la shadow segue una lezione
  effettiva.
- Sostegno escluso sia dal class-busy aggregator che dal vincolo
  per-day capacity sui home_classes.

### Pipeline supportate per C3

Tutte le pipeline e i metodi di ottimizzazione propagano e
preservano i `group_assignments`. La tabella sotto distingue il
modo in cui ogni pipeline si comporta:

| Pipeline                 | C3 fully native | Note                            |
|--------------------------|-----------------|----------------------------------|
| monolitica (Phase B)     | si              | path canonico                    |
| decomposition_temporal   | si              | thread-through completo         |
| decomposition_spectral_v2| via mono        | force_mono_for_groups=True      |
| decomposition_curriculum | via mono        | come sopra (loop condiviso)     |
| decomposition_metis      | via mono        | come sopra (loop condiviso)     |
| column_generation        | si              | seed/diversified pattern + completion solver C3-aware |
| LNS / SA / TS / ILS      | si              | atomic moves + is_hard_feasible + CP repair C3-aware  |
| ALNS                     | si              | repair operators forwardano i C3 params               |
| VNS                      | si              | k-neighbourhoods forwardano i C3 params               |
| Lagrangian               | si              | inner SA refinement riceve i C3 params               |

`force_mono_for_groups`: quando `group_assignments` non e' vuoto,
`run_partitioned_pipeline` (usata da curriculum + metis e dal
fallback di spectral) fa partire `solve_monolithic_day` per ogni
giorno, usando la cache `dc_value` del master ma saltando le tre
fasi A/B/C che non modellano `group_slot` vars.

**CG**: `_seed_patterns` e `_diversified_seed` ora costruiscono
pattern anche per i prof di gruppo, fondendo `profs.classi` con i
triple-gruppo via `_profs_iter_with_groups`. Il `_completion_solver`
delega a `cv2.solve_phase_b_for_day` con tutti i C3 params.

**Metaeuristiche**: `metaheuristics._cp_repair` ha un fast-path
che, quando un qualunque C3 param e' presente, delega a
`cv2.solve_phase_b_for_day` con `locked_slots_for_day` impostati
sui placed-but-not-free. `is_hard_feasible` e' stato esteso con un
controllo opzionale `group_assignments=` che valida n_hours
coverage e mutua esclusione gruppo/classe-madre. Le mosse
atomiche (`_swap_two_lessons_same_prof`,
`_move_lesson_to_empty_slot`, `_swap_two_lessons_same_class`)
accettano `group_assignments` e rifiutano gli swap che
violerebbero gli invarianti di gruppo.
