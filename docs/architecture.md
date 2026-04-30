# Architettura

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
