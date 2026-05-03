# Workflow audit -- 2026-05-03

Audit in **sola lettura** dello stato attuale (commit `88bd76c`,
ramo `main`) di tutti gli stage del workflow visibili nell'UI o
nei modali, con focus sulle **aggiunte recenti (ultime 24-48 h)**.
Le feature consolidate da settimane non sono ricontrollate qui.

Convenzioni:
- Modulo Python: path relativo alla repo root.
- Funzione: nome simbolo nel modulo.
- Endpoint: rotta REST.
- Stato: V (verde, completo) | G (giallo, parziale o caveat) |
  R (rosso, stub o non funzionante).

## Tabella sintetica (aggiornata 2026-05-03 dopo i fix `b7bb776`)

| # | Stage | Modulo Python | Funzione principale | Endpoint REST | Stato | Note |
|---|---|---|---|---|---|---|
| 1 | Decomposizione temporale | `experiments/decomposition_temporal.py` | `run_temporal_pipeline` | `POST /api/optimize/decomposition/temporal` | V | Implementato in `88bd76c`. Smoke test su small (3.1x), medium (5.3x), big (4.6x), MEGA (5.9x), 6/6 days ok in ogni profilo. |
| 2 | Decomposizione METIS | `experiments/decomposition_metis.py` | `solve_with_metis_decomposition` | `POST /api/optimize/decomposition/metis` | V | Implementato in `14aea9a`. Solve loop riusa il pattern Stage A/B/C/mono via `decomposition_loop.run_partitioned_pipeline`. Fallback Python balanced-k-way quando `pymetis` manca (Windows). Smoke test small: 6/6 days ok, master 30s + days 1.9s. |
| 3 | Decomposizione per curriculum | `experiments/decomposition_curriculum.py` | `solve_with_curriculum_decomposition` | `POST /api/optimize/decomposition/curriculum` | V | Implementato in `14aea9a`. Stesso pattern. Smoke test small (Scientifico + ScienzeApplicate, 16/19 docenti come bridges): 6/6 days ok, master 30s + days 3.6s. |
| 4 | Combined (spectral + temporal) | -- | -- | `POST /api/optimize/decomposition/combined` | V | Decisione esplicita: NON e' un orchestrator dedicato. L'utente ticka entrambi `decomp_spectral` e `decomp_temporal` nella card Pipeline (card 9 del Workflow). L'endpoint `combined` ritorna 200 con un hint che spiega questo. Documentato in `docs/optimization_strategies.md`. |
| 5 | ALNS | `experiments/alns.py` | `run_alns` | `POST /api/optimize/meta/alns` | V | 6+ destroy operators e 3 repair operators reali. Selector adattivo via roulette wheel. Wirato in `optimization.run_meta('alns')`. |
| 6 | VNS | `experiments/vns.py` | `run_vns` | `POST /api/optimize/meta/vns` | V | 4 vicinati di dimensione crescente. Wirato in `run_meta('vns')`. |
| 7 | Lagrangian Relaxation | `experiments/lagrangian.py` | `run_lagrangian` | `POST /api/optimize/meta/lagrangian` | V | Subgradient ascent con SA refinement. Wirato in `run_meta('lagrangian')`. |
| 8 | Column Generation | `experiments/column_generation.py` | `run_column_generation` | `POST /api/optimize/column-generation` | V | Aggiornato in `b7bb776`: pipeline iterativa con master LP + diversified pattern enrichment + integer recovery + completion fallback day-by-day. Smoke test small: 4 iterazioni, 114 patterns, master obj=60, completion riempie i gap, 1662 celle, HARD=100%, 25.8s. La variante full branch-and-price con per-teacher CP-SAT sub-problems guidati dai duali resta in roadmap (esplicitato in `info["mode"] = "iterative-diversified"`). |
| 9 | Hall pre-check | `experiments/diagnostics/hall_check.py` (CLI) + `optimization.run_hall_check`/`run_diag_hall_check` | -- | `POST /api/optimize/hall-check` + `POST /api/diagnostics/hall-check` | V | Tre punti UI come da specifica (Phase A card, AdvancedTechniques, tab Diagnostica). Sync e async modes. |
| 10 | Monte Carlo Sensitivity | (interno a `optimization.py`) | `run_diag_montecarlo` | `POST /api/diagnostics/montecarlo` | V | Run async kind `diag_montecarlo`. Catalogo + parametri esposti dal frontend. Cronologia DB-backed (commit `06a78af`). |
| 11 | Bipartite analysis (modularity, betweenness, density) | (interno) | `run_diag_bipartite` | `POST /api/diagnostics/bipartite` | V | Run async kind `diag_bipartite`. |
| 12 | Correlazioni e regressioni | (interno) | `run_diag_correlations` | `POST /api/diagnostics/correlations` | V | OLS + Logit. Variable picker + custom models spec. |
| 13 | Distribuzioni e istogrammi | (interno) | `run_diag_distributions` | `POST /api/diagnostics/distributions` | V | Catalogo `/api/diagnostics/distributions/menu` + parametri per-key. KS-test, chi-square. |
| 14 | Telemetria runs (live) | -- | `_progress_ticker` + `tel.collector` | `GET /api/optimize/runs/{id}/telemetry` + `GET .../stream` (SSE) | V | Streaming SSE, non WebSocket; funzionalmente equivalente. Lazy loading sul frontend. |
| 15 | DSL generico unificato | `webui/backend/utils/general_dsl.py` | parser + evaluator + path-as-source | (interno, usato dai vincoli logici e Phase A custom criterion) | V | Parser hand-rolled, AST, evaluator. Path-as-source `s.groups` esteso (sessione precedente). 11 test unit passano. |
| 16 | Tag aule + tag studenti | tabelle DB `classroom_tags` + `student_tags` con join | -- | `GET/POST/PUT/DELETE /api/classroom-tags` + `/api/student-tags` | V | Pill colorate stabili per nome. Densita' tag aule ridotta in `9ebc6a4`. |
| 17 | Free-day prefs (docente, classe) | tabelle `teachers.free_day_pref_*`, `school_classes.free_day_pref_*` | -- | inclusi nei rispettivi router CRUD | V | 3 slot ordinati + count + flag HARD/SOFT, max_hours_per_day classe. |
| 18 | Graduatoria score + criterio Anzianita | `teachers.graduatoria_score` | preset `objective_dsl::"anzianita"` | `GET /api/optimize/phase-a/presets` | V | Preset DSL esposto fra i criteri Phase A. |
| 19 | Phase A teacher class/curriculum prefs | tabelle `teacher_class_preferences` + `teacher_curriculum_preferences` | usato in DSL di Phase A | -- | V | Pesi entry fra le preferenze Phase A; usati dai preset "balance_curricula" e "continuita". |
| 20 | Monitor Dissocia/Blocca/Piazza + tab Lockati | -- | endpoints `/monitor/dissociate`, `/monitor/lock`, `/place-event` | `POST /api/monitor/...` + `POST /api/optimize/place-event` | V | Multi-select toolbar. Tab Lockati (`lesson.locked == true`). Aggiunto in sessione precedente. |
| 21 | Vincoli logici DNF | `general_dsl` + `webui/backend/routers/logical.py` | -- | `POST /api/logical-unavailabilities/...` | V | HARD/SOFT/PREFERRED/ENFORCED. Predicate atoms `aula:`, `materia:`, `classe:`, `gruppo:`, `docente:`. |
| 22 | Import/Export DB + viste salvate | `webui/backend/routers/dashboard.py` + `saved_views.py` | -- | `/api/dashboard/export-db`, `/api/dashboard/import-db`, `/api/saved-views` | V | Card prominente Dashboard. Snapshot timestamped. SavedView per query DSL + sort. |
| 23 | Esporta xlsx/csv liste | `webui/backend/exports.py` | `?format=xlsx\|csv` su tutti i list endpoint | -- | V | 3 bottoni (xlsx / csv / tutto) sopra ogni tabella. UTF-8 BOM, header colorato, auto-fit. |
| 24 | Tab Documentazione frontend | -- | -- | -- | R | Non implementata. Pianificata; vedi audit precedente (`audit_2026-05-03.md`). |
| 25 | Navbar raggruppata in submenu | `webui/frontend/src/routes/+layout.svelte` | navGroups | -- | V | Implementata in `d842086`: 6 voci di primo livello, 3 dropdown (Anagrafica/Pianificazione/Esecuzione). |
| 26 | Stati 5-colori matrici + scorciatoie tastiera H/P/E/D/A/N | `keyboardConstraintMode.ts` | -- | -- | V | HARD/PREFERRED/ENFORCED/DISLIKED/ALLOWED/NEUTRAL. Pill colorate. PREFERITO -> PREFERRED standardizzato (`cc20751`). |
| 27 | Tab Statistiche/Diagnostica con cronologia | `webui/frontend/src/routes/diagnostics/+page.svelte` | -- | -- | V | DB-backed history per kind (mc/bp/co/ds), cronologia toggleable, charts ECharts. Aggiunto in `06a78af`. |
| 28 | Branding piTantum + Seneca | `branding/`, frontend layout, manuale | -- | -- | V | Logo, palette indaco/oro/Siena/avorio, epigrafe Seneca corretta in `af391d1`. Attribuzione 4 autori in `4b99dec`. |
| 29 | Decomposition auto-detect | `experiments/decomposition_auto.py` | `auto_detect_decomposition_strategy` | `GET /api/optimize/decomposition/recommend` | V | Modularita' + densita' -> raccomandazione strategia primaria + combine_with_temporal. Restituisce 200 con motivazione testuale. |
| 30 | Card Strategie di decomposizione (Workflow) | `webui/frontend/src/routes/optimize/+page.svelte` | -- | client di endpoints sopra | V | 4 sotto-card (3a-3d) + Suggerimento. 4 nuove righe pipeline reorderable. Aggiunto in `d02575d`/`b27fe8c`. |

## Aggiornamento post-audit

Tutti i Rossi (3) e il Giallo (1) sono stati chiusi nei commit
`14aea9a` (METIS + curriculum + combined hint) e `b7bb776` (CG
iterativo). Nessun endpoint 501 e nessun `NotImplementedError`
restano nel codice di progetto:

```
$ grep -rn "HTTPException(\s*501" webui/backend/ --include="*.py" \
    | grep -v ".venv"
(no output)

$ grep -rn "NotImplementedError" webui/backend/ experiments/ \
    --include="*.py" | grep -v ".venv"
(no output)
```

Stato finale (30/30 V):
- 26 stage gia' V dall'audit iniziale (CP-SAT + spectral + LNS +
  SA + TS + ILS + ALNS + VNS + Lagrangian + Hall + MC + bipartite
  + correlations + distributions + telemetry + DSL + tag + free-
  day prefs + graduatoria + Phase A class/curriculum prefs +
  Monitor + DNF + Import/Export DB + xlsx/csv export + navbar +
  5-stati + diagnostics + branding + auto-detect + Workflow card)
- 4 stage chiusi in questa sessione: METIS, per curriculum,
  Combined (hint), Column Generation (iterative + completion).

## Pendenze del working tree

Nessuna. Lo stash della sessione precedente e' stato applicato e
committato in `14aea9a`.
