# piTantum

> *Omnia, Lucili, aliena sunt, tempus tantum nostrum est.*
> &mdash; Seneca, *Epistulae morales ad Lucilium*, I, 1

> "Tutto, Lucilio mio, ci appartiene di altri; soltanto il tempo e'
> nostro."

**piTantum** (alias **Tempus Tantum**) e' un sistema di generazione
e gestione dell'orario scolastico per un Liceo italiano:
assegnazioni docenti-classi, ottimizzazione dell'orario settimanale,
gestione di assenze e supplenze, drag-and-drop con preview live.

Il nome gioca sulla forma della lettera greca **&pi;**: i due tratti
verticali della pi minuscola ricordano le due **T** di **T**empus
**T**antum. Il senso del verso senechiano sintetizza il programma:
del tempo non se ne ha altro che quello che si organizza adesso.

Tre layer, in un unico repo:

1. **Solver** (`experiments/`) — a CP-SAT pipeline (Google OR-tools)
   with spectral decomposition for very large instances, plus a
   collection of metaheuristics (LNS, SA, TS, ILS) that run on top of
   the CP-SAT seed solution.
2. **Web UI** (`webui/`) — a FastAPI backend over SQLite plus a
   SvelteKit frontend that exposes every piece of data the solver
   consumes (teachers, classes, subjects, classrooms, indirizzi,
   students, study groups), runs the optimization steps end-to-end,
   and lets the user fine-tune constraints, drag lessons around the
   timetable, manage absences and substitutions, etc.
3. **Legacy notebooks and prototypes** (`schedule/`) — original
   single-file scripts that the solver evolved from. Kept for
   reference.

The full feature list is large; see `proposals/analysis.md` and
`proposals/benchmarks.md` for the design rationale and the empirical
performance numbers across school sizes.

## Documentation

- **[Installation guide](docs/installation.md)** -- cross-platform
  setup (Windows / Linux / macOS): prerequisiti, installer ufficiali,
  comandi di clone, note Apple Silicon, troubleshooting per OS,
  verifica installazione, aggiornamento, disinstallazione. **Quick
  start** per ciascun OS in cima al file.
- **Tre manuali in PDF** (la documentazione e' divisa in due
  parti per adattarsi a pubblici diversi):
  - **[Manuale generale (PDF, ~19 pagine)](docs/manual_generale.pdf)**
    --- per chi vuole iniziare a usare $\pi$Tantum: dirigenti
    scolastici, coordinatori d'orario, docenti utenti. Tono
    discorsivo, casi d'uso pratici, niente jargon.
  - **[Appendici tecniche (PDF, ~20 pagine)](docs/appendici_tecniche.pdf)**
    --- per sviluppatori e curiosi tecnici: architettura,
    modello dati, API REST, grammatica DSL, strategie di
    ottimizzazione, diagnostica, guida all'estensione.
  - **[Manuale completo (PDF, ~41 pagine)](docs/manual_completo.pdf)**
    --- entrambi i volumi in un unico documento.
  Tutti compilati con la pipeline lualatex+biber+makeindex+lualatex.
  Sorgenti `.tex` in `docs/manual_generale.tex`,
  `docs/appendici_tecniche.tex`, `docs/manual_completo.tex` (con
  capitoli condivisi in `docs/manual/chapters/`); ricompila con
  `docs/build_manual.sh` (Linux/macOS/Git Bash) o
  `docs/build_manual.bat` (Windows).
- **[docs/](docs/)** -- modular markdown reference:
  [installation](docs/installation.md) /
  [architecture](docs/architecture.md) /
  [data model](docs/data_model.md) /
  [constraints](docs/constraints.md) /
  [workflow](docs/workflow.md) /
  [UI guide](docs/ui_guide.md) /
  [objective DSL](docs/objective_dsl.md) /
  [API](docs/api.md) /
  [extending](docs/extending.md).
- **[webui/docs/](webui/docs/)** -- short user-facing guides linked
  from the UI itself (Excel import format, query syntax, bulk
  operations, classroom auto-generation, ...).

## Brand assets

Loghi, banner, icone e screenshot vivono in [`branding/`](branding/).
Ogni sottocartella include un `grok_prompts.md` con prompt
copia-incolla pronti per generare gli asset definitivi via Grok.
Sono inoltre presenti degli **placeholder SVG funzionanti** che
ship-ano con il repo: la UI rimane brand-coherent dal primo avvio.

Palette: indaco profondo (`#1e3a5f`), oro caldo (`#c9a23a`), terra
di Siena (`#9c4a1c`), avorio (`#f7f1de`). Esposta via CSS variables
`--brand-{primary,secondary,accent,bg,fg}` in
`webui/frontend/src/app.css`.

## Quickstart (Windows)

Prerequisites:

- Python 3.11+ (Microsoft Store build is fine)
- Node.js LTS (https://nodejs.org/en/download)

```
git clone https://github.com/gborghi/timetable
cd timetable\webui
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
start.bat
```

`start.bat` opens two console windows:

- backend: uvicorn at http://127.0.0.1:8000
- frontend: vite dev server at http://127.0.0.1:5173

Open http://127.0.0.1:5173 in a browser and start with the
**Dashboard** card "Importa un profilo gia calcolato": pick `small`
and check the three pool checkboxes (curricula, classrooms, students).
The import seeds about 220 students, 17 classrooms, 8 indirizzi and
113 prof-class assignments in roughly 5 seconds, then loads an
already-optimized timetable solution. From there you can browse
every other tab.

If `node_modules` is missing, the launcher runs `npm install` once
(~150 MB). If the venv is missing, the launcher prints the exact
command to create it.

## Web UI tour

The nav bar lists every concept exposed:

- **Dashboard** — import / mock-generate / state overview.
- **Docenti** — teachers with split last/first name, nickname,
  availability matrix (5 states: free / yellow soft / red hard /
  blue preferred / dark-green enforced), classroom preference grid
  (5 states: allowed / yellow soft / blue preferred / red forbidden /
  dark-green enforced), free-day handling, logical disjunctive
  unavailability constraints, max-hours, classes-of-concorso pool.
- **Classi** — classes; same availability+classroom pattern as
  teachers, plus subject hours per class, indirizzo dropdown, SOFT
  weight on the 6th hour, etc.
- **Indirizzi** — study tracks (Liceo Scientifico, Linguistico, ...)
  with a per-year subject-hours grid and indirizzo-level logical
  constraints, optionally restricted to a single year of course.
- **Studenti** — students. Imported in bulk per profile (Faker-
  driven, deterministic) or via Excel/CSV.
- **Gruppi** — articulated study groups (cross-class), e.g. seconda
  lingua, IRC vs alternativa, recupero. Type-C semantics: members
  can come from any combination of classes.
- **Materie** — subjects, with a subject-classroom grid (same 5
  states as the teacher grid) and the subject-group-weight matrix
  (classe-di-concorso assignment).
- **Aule** — classrooms with kind / capacity / multi-class flags,
  per-class home preferences, per-subject preferences, and the
  same 5-state availability matrix as teachers and classes.
- **Compresenze** — co-teaching rules.
- **Cattedre** — assignments (teacher x class x subject hours).
- **Workflow** — multi-step run launcher (assignment, phase B
  decomposition, LNS / SA / TS / ILS).
- **Orario** — final timetable view, drag-and-drop with live
  HARD-feasibility check + SOFT delta preview.
- **Assenze e supplenze** — week-grid view: click a column header
  to add absent teachers for that day, click a cell to assign
  substitutes via drag-drop. Cells turn red when uncovered and
  green when covered.

Every list page (teachers, classes, subjects, classrooms, curricula,
students, groups) supports:

- a query DSL (`group=A026 AND max_hours>=18`, `cognome startswith
  Ross`, `unavailable_on(martedi)`, ...) with per-entity field
  catalogues
- multi-level sort (up to 4 levels)
- multi-row select via Ctrl/Shift click
- bulk apply with conflict detection (override / skip / dry-run) for
  add_logical, set_field, add_unavailability
- Excel/CSV import with downloadable template; documentation in
  `webui/docs/import_format.md`

## Solver pipeline

1. **Assignment**: greedy + CP-SAT to map `prof -> class -> subject`
   with hour quotas; respects classe-di-concorso, max hours, free
   days, mandatory free days, compatibility lists.
2. **Phase B (decomposition)**: spectral graph clustering of the
   assignment graph splits the school into k loosely-coupled sub-
   instances, each solved independently by CP-SAT, then re-stitched
   ("ricucitura") with a global pass.
3. **Metaheuristics**: LNS / SA / TS / ILS run on top of the
   decomposed solution. The objective covers SOFT preferences
   (no holes per teacher day, no isolated 1- or 5-hour days,
   distribution across the week, dual-hour pairs, no 6th hour, ...).
4. **Classroom assignment**: a separate CP-SAT step maps
   (class, subject, slot) -> classroom honoring kind constraints,
   home rooms, subject-classroom preferences, and multi-class rules.
5. **Live editing**: drag-and-drop in the Orario page does an
   incremental check of every HARD constraint and a delta-eval of
   every SOFT preference; the user is told whether the move is
   feasible and how the objective shifts.

## Constraint language

Per-cell availability has 5 states (free / soft / hard / preferred /
enforced). Logical constraints are disjunctive expressions over slot
literals or richer **predicate atoms**:

```
mai aula:LabFisica@mar
aula:LabInformatica@lun OR aula:LabInformatica@gio
mai materia:Religione@lun8
gruppo:IRC OR gruppo:Alternativa
NOT (mer3 AND mer4)
```

Four kinds: HARD / SOFT / PREFERRED / ENFORCED. Documentation in
`webui/docs/logical_constraints.md`. The slot-only portion is fully
honored by the solver today; predicate-atom enforcement is partial
and described in the same doc.

### DSL generico (general DSL)

Per vincoli arbitrari su qualunque combinazione di docenti, classi,
aule, materie, gruppi, studenti, giorni, ore, c'e' un **DSL
generico** (un parser, molti compilatori) con quantificatori
`forall` / `exists` / `count`, predicati atomici, connettivi
logici, funzioni built-in (`lesson()`, `consecutive()`, `same_day()`,
...), sorgenti-path (es. `exists g in s.groups`).

Esempi tipici:

```
# Ogni docente di Fisica deve avere esattamente 1 ora a settimana
# in un'aula di tipo lab_fisica
forall t in teachers where t.subject == "Fisica":
    count l in lessons where l.teacher == t
                          and l.classroom.type == "lab_fisica":
        l == 1

# Studenti BES devono appartenere a un gruppo Sostegno
forall s in students where "BES" in s.tags:
    exists g in s.groups: g.name == "Sostegno"
```

Reference completo + galleria di 30+ esempi in
[`docs/general_dsl.md`](docs/general_dsl.md) e nel capitolo
"DSL generico per i vincoli" delle Appendici tecniche
([`docs/appendici_tecniche.pdf`](docs/appendici_tecniche.pdf)).

## Repository layout

```
experiments/   solver code (CP-SAT, decomposition, metaheuristics,
               exporters); pickled snapshots per profile (small,
               medium, big, huge, superhuge).
webui/         FastAPI backend + SvelteKit frontend + docs.
schedule/      legacy single-file prototypes (kept for reference).
proposals/     design notes and benchmark results.
*.pdf          reference papers (VLNS, spectral methods,
               combinatorial optimization).
```

## Development notes

- The webui DB is a single SQLite file at `webui/data/timetable.db`.
  Idempotent migrations live in `webui/backend/db.py` and are run on
  every backend boot — no Alembic, intentionally.
- Pickle snapshots (`experiments/*.pkl`) are the engine's I/O
  format; the webui converts to/from them via
  `webui/backend/engine_io.py`.
- Excel/CSV import templates can be downloaded from each list page
  in the UI (button "Template").
- See `proposals/benchmarks.md` for measured running times on the
  five mock profiles.

## License

Private project; no public license.
