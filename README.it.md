# piTantum

**Nota:** Questo README è un riassunto in italiano. Il README canonico è in inglese: [English](README.md).

> 🤖 **Realizzato con l'intelligenza artificiale.** piTantum è stato
> progettato e implementato con l'assistenza dell'intelligenza artificiale
> (Claude di Anthropic) — dal solver CP-SAT e il motore dei vincoli al
> backend FastAPI e al frontend SvelteKit.

> *Omnia, Lucili, aliena sunt, tempus tantum nostrum est.*
> &mdash; Seneca, *Epistulae morales ad Lucilium*, I, 1

> "Tutto, Lucilio, ci viene da altri; soltanto il tempo e' nostro."

**piTantum** (alias **Tempus Tantum**) e' un sistema di generazione
e gestione dell'orario scolastico per un Liceo italiano:
assegnazioni docenti-classi, ottimizzazione dell'orario settimanale,
gestione di assenze e supplenze, drag-and-drop con preview live.

Il nome gioca sulla forma della lettera greca **&pi;**: i due tratti
verticali della pi minuscola ricordano le due **T** di **T**empus
**T**antum. Il senso del verso senechiano sintetizza il programma:
del tempo non se ne ha altro che quello che si organizza adesso.

Tre layer, in un unico repo:

1. **Solver** (`engine/`) — a CP-SAT pipeline (Google OR-tools)
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

## Origini del progetto

piTantum nasce da idee di **Fernando Gargiulo**, **Giovanni Borghi**,
**Matteo Mariani** e **Stefano Bertozzi**. Il progetto deve a loro
il disegno concettuale del metodo di scheduling implementato, la
scelta dei vincoli rilevanti per la realta' delle scuole italiane
e l'impostazione complessiva dell'architettura. L'implementazione
tecnica e' stata sviluppata a partire da queste idee.

## Documentation

- **[Installation guide](docs/installation.md)** -- cross-platform
  setup (Windows / Linux / macOS): prerequisiti, installer ufficiali,
  comandi di clone, note Apple Silicon, troubleshooting per OS,
  verifica installazione, aggiornamento, disinstallazione. **Quick
  start** per ciascun OS in cima al file.
- **[Manuale (PDF)](docs/manual.pdf)** -- una monografia unica,
  scritta in stile discorsivo, accessibile a chi non e' tecnico ma
  rigorosa quando il contenuto lo richiede. Copre il problema del
  timetabling scolastico, la panoramica di piTantum, l'interfaccia
  utente, il modello a vincoli, e poi tutti i metodi algoritmici
  (CP-SAT, decomposizione spettrale, metaeuristiche, Hall pre-check,
  rilassamento lagrangiano, generazione di colonne, Monte Carlo,
  analisi del grafo bipartito, statistica applicata, DSL parser),
  l'architettura software, il modello dati, le API REST, la guida
  all'estensione, i benchmark sui cinque profili e una sezione di
  lessons learned. Sorgente LaTeX in `docs/manual.tex` con i
  capitoli in `docs/manual/chapters/` e la bibliografia in
  `docs/manual/bibliography.bib`. Ricompila con
  `docs/build_manual.sh` (Linux/macOS/Git Bash) o
  `docs/build_manual.bat` (Windows). La pipeline e' lualatex +
  biber + makeindex + lualatex (x2).
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

## Funzionalita' avanzate (Italian school constraints)

### Lock nativi nelle lezioni

Una `Assignment` con `locked=True` (toggle nella UI) viene tradotta
direttamente in un vincolo CP-SAT (non piu' tramite snapshot/restore).
Vantaggi:
- fail-fast: lock incompatibili sollevano un 400 al POST, non a meta'
  della run.
- propagati a tutte le pipeline (Phase B monolitica, decomposta
  temporal/spectral_v2/curriculum/metis, column generation, ALNS,
  VNS, Lagrangian, classroom assignment).
- pre-flight `validate_locks_vs_constraints` confronta i lock con
  free_day del docente, max_hours_per_day della classe, vincoli HARD
  di compresenza ecc.

### Compresenze (Task C1)

Due varianti supportate da `CoteachGroup`:

- **Shared** (es. lab di chimica con assistente): `n_hours` ore di
  un cattedra condivisa fra il docente principale (cattedra completa)
  e uno o piu' co-docenti (solo le ore di compresenza). Convenzione
  `members[0] = principal`. Nel solver: `day_count[principal] >=
  coday[g, d]` e `day_count[codoc] == coday[g, d]`.
- **Shadow / sostegno**: prof di sostegno DVA che segue uno studente.
  Modellato con `Assignment.is_support=True` e subject convenzionalmente
  `"sostegno"`. Vincolo `slot[(sost, X, sost, h)] <= OR(slot[*, X, *, h]
  for non-support)`: l'ora di sostegno e' presente solo dove la classe
  e' gia' occupata da un'altra lezione, e NON conta come ora-classe
  aggiuntiva.

Esempio Italiano: `2C lab di chimica 2h con compresenza` ->
`CoteachGroup(class_id=2C, subject=Chimica, n_hours=2)` con
`Assignment(ProfChim, 2C, Chimica, hours=4)` e
`Assignment(ProfAss, 2C, Chimica, hours=2)`. Il principale insegna
4h, l'assistente solo 2h, e quelle 2h coincidono nello stesso slot.

### Potenziamento (Legge 107)

Cattedra senza classe: `Assignment.is_potenziamento=True` con
`class_id=NULL`. Le ore vengono comunque schedulate (max 5/giorno) e
il docente diventa prioritario per le supplenze nel tab
`/assenze-supplenze` (badge **POT** + bordo viola). Cap settimanale
HARD: 30 ore (5 ore/giorno x 6 giorni).

### Parallel groups intra-class (Task C2)

Casi tipici: `religione + alternativa` nella stessa classe, stessa ora,
docenti diversi. Modellato con `Assignment.parallel_group_id`:
membri della stessa parallela condividono lo slot, la classe conta
come busy **una sola volta**. Esempio:
`Assignment(ProfRel, 3B, Religione, h=1, parallel_group_id=99)` +
`Assignment(ProfAlt, 3B, Alternativa, h=1, parallel_group_id=99)`.

### Inter-class StudyGroup scheduling (Task C3)

Gruppi che attraversano piu' classi (es. **Spagnolo** con studenti
da 2A + 2B). Modello dati: `StudyGroup` esistente con
`GroupMembership` (studenti) + `GroupSubjectHours` (ore/materia).
Schema esteso (Opzione B):
- `Assignment.group_id` nullable (XOR con `class_id`).
- `CoteachGroup.group_id` nullable (XOR con `class_id`) per
  compresenze su gruppo.
- `Lesson.group_name` nullable per le lezioni-gruppo nei risultati.

Solver:
- nuove triple `(prof, group_name, subject, n_hours)` con `group_name`
  come "virtual class label" non in `classes` (no `cl_day_load`,
  no HARD-2).
- vincolo per-day capacity: `cl_day_load[home_cl, d] +
  sum(group_day_count[g, d]) <= 6` su ogni classe-madre dei membri.
- Phase B class-busy aggregator estende le subj_busy aggiungendo
  `__grp__<gname>__<subj>` come busy_key per ogni classe-madre.
  L'invariante `sum(subj_busy) == pr` garantisce che la classe non
  faccia altre lezioni nello slot del gruppo.

Pipeline supportate: monolitica + `decomposition_temporal`. Le altre
pipeline decomposte (`spectral_v2`, `curriculum`, `metis`,
`column_generation`) ignorano `group_assignments` per il momento --
follow-up tracciato in AUDIT.md.

Esempio: gruppo "Spagnolo cross-class" con 5 studenti da 2A + 7 da 2B,
3h/settimana, ProfSpa: aggiungi `Assignment(teacher=ProfSpa,
class_id=NULL, group_id=<id Spagnolo>, subject="Spagnolo", hours=3)`.
Il solver schedulera' 3 ore in slot diversi; sia 2A che 2B saranno
"occupate" in quegli slot (i loro studenti sono fisicamente nel
gruppo).

### Pre-flight checks

`validate_coteach_sostegno_potenziamento` controlla a *POST time*:
- compresenza: principal hours >= n_hours, codoc hours == n_hours.
- sostegno: class_id deve esistere.
- potenziamento: class_id NULL, totale settimanale <= 30.
- gruppo: XOR class_id/group_id, gruppo deve avere studenti, ogni
  studente deve avere classe-madre, hours > 0.

Le violazioni sono restituite come 400 con elenco specifico, non come
INFEASIBLE silenzioso a fine run.

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
"DSL generico per i vincoli" del [Manuale](docs/manual.pdf).

## Repository layout

```
engine/      solver code (CP-SAT, decomposition, metaheuristics,
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
- Pickle snapshots (`engine/scripts/*.pkl`) are the engine's I/O
  format; the webui converts to/from them via
  `webui/backend/engine_io.py`.
- Excel/CSV import templates can be downloaded from each list page
  in the UI (button "Template").
- See `proposals/benchmarks.md` for measured running times on the
  five mock profiles.

## License

Private project; no public license.
