# Architettura (sommario in italiano)

piTantum e' un sistema a tre livelli: un core CP-SAT solver
(`engine/`), un backend FastAPI + SQLite (`webui/backend/`) e
un frontend SvelteKit (`webui/frontend/`). Il solver gira come
libreria importata dal backend; le pipeline sono esposte come
run asincroni via `/api/optimize/*`. Il frontend dialoga con
il backend in JSON; le run lunghe sono tracciate dalla tabella
`runs` interrogata a 1Hz dalla UI.

## Pipeline del solver (in `engine/`)

- `cpsat_v2_assignment.py`: Phase A (assegnazione docente →
  classe).
- `cpsat_v2_timetable.py`: Phase A (timetabling, `day_count`) +
  Phase B (collocamento slot per giorno). Lock nativi +
  vincoli C1/C2/C3.
- `cp_sat_constraint_model.py`: catalogo OO.
  `MonolithicSolver` e `PhaseBDaySolver` (Step 4) wrappano i
  path legacy e accettano `via_dsl=True` per modelli aumentati
  via DSL.
- `decomposition_temporal.py`: decomposizione parallela su 6
  giorni.
- `decomposition_spectral_v2.py` (+ varianti curriculum/metis):
  cluster di classi, sotto-problemi, ricucitura.
- `column_generation.py`: master LP + arricchimento
  diversificato di pattern + completion fallback. La modalita'
  `mode="branch-and-price"` e' wirata end-to-end con tutte le
  tecniche di scalabilita':
  - **9 pricer CP-SAT** alle granularita' `teacher`,
    `teacher-day`, `teacher-class`, `teacher-class-subject`,
    `teacher-subject`, `class`, `class-day`, `day`,
    `curriculum`. CP-SAT e' la minimizzazione FONDAMENTALE; il
    greedy serve solo come `model.add_hint` di warm-start.
  - **Due master LP**: variant 1 (uguaglianza per docente, per
    le granularita' `teacher-*`) e variant 2 (Dantzig-Wolfe
    con cover + class-overlap + teacher-overlap, per
    `class-*`, `day`, `curriculum`).
  - **Albero ricorsivo Ryan-Foster** con score di Achterberg
    e prune sul lower bound, cap a profondita' e numero di
    nodi. Step 4 aggiunge il pricing-in-nodes (CP-SAT
    rilanciato per nodo con i vincoli ramo applicati).
  - **Stabilizzazione duale box-step** che smussa duali
    oscillanti.
  - **Gestione colonne** con purge per RC age (cap default
    pool 10K, EWMA su 20 iter).
  - **Pricing parallelo** via `ProcessPoolExecutor` (default
    `cpu_count() // 2` worker).
- `dsl_to_cpsat.py` (Step 1+): compilatore generico DSL →
  CP-SAT. Stesso parser/AST dell'evaluator post-hoc, un solo
  backend usato da Mono / PhaseB / pricer / nodi RF.
- `dsl_translator.py` (Step 2/3): translator unificato dalle
  tabelle special-purpose (TeacherUnavailability,
  CoteachGroup, PlessoCommutingRule, ecc.) verso stringhe DSL
  canoniche. Include `seed_implicit_hardcoded(profs)` (Step
  3d-3e) che emette i HARD legacy hardcoded come DSL con
  zero-drift bit-per-bit.
- `metaheuristics.py`, `alns.py`, `vns.py`, `lagrangian.py`:
  post-processing su una soluzione seed HARD-feasible.

## Architettura a strati DSL → CP-SAT

Dopo gli Step 1–4 del piano multi-day, ogni sorgente di
vincoli passa attraverso un solo parser, un solo AST, un solo
compilatore:

```
UI → POST /api/constraints/general
                │
Tabelle DB ──→ dsl_translator ──→ stringhe DSL canoniche
                                          │
                                          v
                              general_dsl.parse() (AST)
                                          │
                                          v
                          DSLConstraintCompiler.compile()
                                          │
              ┌────────────┬───────────┼───────────┬──────────┐
              v            v           v           v          v
          Mono         PhaseB      BP pricer    RF nodi    evaluator
          Solver       DaySolver  (9 granul.)              post-hoc
          + DSL seed   + DSL aug                           (HARD/SOFT
                                                            score)
```

Proprieta' chiave:
- **Un solo compilatore**: stessa emissione di vincoli per
  ogni superficie del solver (Mono, Phase B per giorno,
  pricer di BP, nodi RF, evaluator post-hoc).
- **Zero-drift**: i HARD legacy hardcoded fanno il
  round-trip DSL in modo identico (regression-tested).
- **HARD up-front, SOFT post-hoc**: le clausole DSL HARD
  diventano vincoli CP-SAT prima della solve; le SOFT sono
  valutate post-hoc e contribuiscono allo score globale (la
  wiring del SOFT nell'obiettivo CP-SAT e' nei prossimi
  step).

Pragmas canonici riconosciuti dal compilatore:
`no_holes_class`, `class_present_at_hour`, `class_day_load_in`,
`teacher_max_per_day`, `cattedra_max_per_day`,
`subject_pair_must`, `subject_pair_exists`, path
`l.classroom.plesso`, predicati `consecutive(s1, s2)` e
`same_day(s1, s2)`.

---

> **Nota**: questo documento e' il sommario in italiano. Il
> sommario in inglese vive in `architecture.md`. La trattazione
> estesa e' nel manuale LaTeX sotto `docs/manual/chapters/`
> (vedi `architettura.tex`, `api_rest.tex`, `modello_dati.tex`,
> ecc.). Compila con `docs/build_manual.sh` per ottenere
> `manual.pdf` (italiano) e `manual_en.pdf` (inglese).
