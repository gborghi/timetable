# API REST (sommario in italiano)

Tutte le azioni della UI passano da endpoint REST sotto
`/api/...`. Famiglie principali di risorse:

- `/api/teachers`, `/api/classes`, `/api/classrooms`,
  `/api/subjects`, `/api/curricula`, `/api/students`,
  `/api/groups` -- CRUD sulle entita' che il solver consuma.
- `/api/assignments` -- lettura + edit manuale della cattedra
  docente → classe; toggle lock (`/lock/<id>`).
- `/api/optimize/*` -- pipeline solver asincrone: `assignment`
  (Phase A), `phase-b`, `decomposition/<metodo>`,
  `meta/<stage>`, `cg`, `place-event`, `full-pipeline`.
  Ognuna restituisce un `run_id` interrogabile via
  `/api/optimize/runs/<id>`.
  - `POST /api/optimize/column-generation` -- asincrona, body
    `{time_budget_s, patterns_per_teacher, mode, granularity,
     branching_strategy, max_iterations, bp_max_iterations,
     pricer_time_limit, pricer_workers, parallel, log}`.
    - `mode`: `iterative-diversified` (default) |
      `branch-and-price` | `auto`.
    - `granularity` (per BP): `auto` | `teacher` |
      `teacher-day` | `teacher-class` |
      `teacher-class-subject` | `teacher-subject` | `class` |
      `class-day` | `day` | `curriculum`. Ognuna con un pricer
      CP-SAT dedicato (CP-SAT e' la minimizzazione fondamentale;
      il greedy fornisce solo un warm-start via
      `model.add_hint`).
    - `branching_strategy`: `ryan_foster` (albero ricorsivo
      completo con score di Achterberg, prune sul lower bound,
      `max_depth=20` / `max_nodes=1000`; Step 4 aggiunge
      pricing-in-nodes) | `variable` (placeholder no-op).
    - `bp_max_iterations` (default 8): tetto su round
      master+pricing.
    - `pricer_time_limit` (default 5.0s): per sotto-problema
      CP-SAT.
    - `pricer_workers` (default 2): worker di ricerca CP-SAT
      per sotto-problema.
    - Knob solo Python (non ancora in UI):
      `dual_stabilization` (default True), `dual_step_alpha`
      (0.2), `max_active_columns` (10000),
      `rc_smoothing_horizon` (20), `parallel_workers` (auto =
      `cpu_count() // 2`), `class_to_curriculum`.
- `/api/constraints/general` -- vincoli DSL
  (HARD/SOFT/PREFERRED/ENFORCED). `POST` salva una regola;
  `POST .../validate` valida senza persistere; `GET` elenca le
  regole. La stringa DSL e' parsata da
  `webui/backend/utils/general_dsl.py` e compilata a CP-SAT da
  `engine/dsl_to_cpsat.py` ogni volta che una pipeline solver
  viene lanciata con `via_dsl=True`.
- `/api/plessi/*` -- CRUD su plessi (sedi), regole di commuting
  ed entity policy.
  - `GET /api/plessi/validate` -- validazione pre-run;
    alimenta il badge live ``config OK / N anomalie''.
- `/api/monitor/*` -- listing degli event-row che alimentano la
  UI /monitor (event-rows, summary, conflicts).
- `/api/bulk/events/{dry-run,apply}` -- operazioni bulk da
  /monitor (set_classroom, clear_classroom, set_lock).
- `/api/dataset/{state,clear,mock,import-profile,upload-pickle}`
  -- ciclo di vita dei dati.
- `/api/diagnostics/*` -- statistica asincrona (montecarlo,
  bipartite, correlazioni, distribuzioni).
- `/api/health` -- liveness probe (200 OK + versione).

Schemi: `webui/backend/schemas.py` (Pydantic v2). OpenAPI JSON:
`GET /openapi.json`.

## Endpoint DSL nel dettaglio

La grammatica DSL e' descritta in `general_dsl.md`. In sintesi:

- `POST /api/constraints/general`: body
  `{label, expression, kind, weight?, scope?}` con
  `kind in ["hard", "soft", "preferred", "enforced"]`.
  Ritorna 201 con l'ID persistito, o 400 con errore di parser.
  Da Step 3+4 la stessa regola e' anche compilata a CP-SAT
  quando una pipeline solver gira con `via_dsl=True`; le
  HARD vincolano il modello up-front, le SOFT sono valutate
  post-hoc e contribuiscono allo score globale.
- `POST /api/constraints/general/validate`: body
  `{expression}`; ritorna stato del parser + lista di warning
  (numero di atomi, euristica di complessita', risoluzione
  delle sorgenti).
- `GET /api/constraints/general?scope=...`: elenca le regole;
  il filtro opzionale `scope` mira a una entity specifica
  (es. un docente o una classe).

I pragma canonici (`no_holes_class`,
`class_present_at_hour`, `class_day_load_in`,
`teacher_max_per_day`, `cattedra_max_per_day`,
`subject_pair_must`, `subject_pair_exists`, path
`l.classroom.plesso`, `consecutive`, `same_day`) sono tutti
accettati dallo stesso endpoint.

---

> **Nota**: questo documento e' il sommario in italiano. Il
> sommario in inglese vive in `api.md`. La trattazione estesa
> e' nel manuale LaTeX sotto `docs/manual/chapters/` (vedi
> `api_rest.tex`). Compila con `docs/build_manual.sh` per
> ottenere `manual.pdf` (italiano) e `manual_en.pdf`
> (inglese).
