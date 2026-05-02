# Statistiche e diagnostica

Il tab `/diagnostics` aggrega tutte le analisi statistiche
sull'istanza corrente (modello + soluzione attiva). Tutti gli
endpoint vivono sotto `/api/diagnostics/`. La UI usa il wrapper
`<EChart>` (`webui/frontend/src/lib/components/EChart.svelte`,
ECharts ^6 lazy-loaded, tema `pitantum` con palette
indaco/oro/avorio/terra-di-siena).

## 1. Pre-check fattibilita' (Hall's theorem)

POST `/api/diagnostics/hall-check`. Vedere
`docs/optimization_strategies.md` sezione 3 per dettagli.

Output:
```json
{
  "ok": true,
  "n_classes": 50, "n_teachers": 90,
  "violations": [
    {"kind": "no_teacher", "subject": "Greek",
     "msg": "Nessun docente sa insegnare 'Greek'..."}
  ],
  "stats": {
    "n_subjects": 20,
    "total_demand_hours": 1488,
    "total_supply_hours": 1569,
    "n_samples": 256
  }
}
```

## 2. Sensitivity Monte Carlo

POST `/api/diagnostics/montecarlo` con `n_samples` (default 100).

Genera N perturbazioni feasible della soluzione attiva applicando
sequenze di mosse atomiche random (swap-prof, move-empty,
swap-class) accettate solo se HARD resta soddisfatto. Per
ciascuna calcola il valore SOFT.

Output:
- `mean`, `std`, `min`, `max`, `p25`, `p50`, `p75`
- `coefficient_of_variation = std / mean`
- `interpretation`:
  - se CV < 0.05 -> soluzione corrente vicina all'ottimo locale
  - altrimenti -> potenziale di miglioramento via metaeuristiche

UI: card con statistiche numeriche + istogramma ECharts della
distribuzione SOFT, mark-line sulla media e sul valore base.

## 3. Analisi grafica del bipartito

POST `/api/diagnostics/bipartite` con `mode` in
`{"classes", "teachers"}`. Calcola tre metriche su networkx:

- **Densita'** = `2|E| / (|V|(|V|-1))`. Bassa => cluster ben
  separati (la spettrale aiuta); alta => grafo quasi cricca.
- **Modularita' (Newman-Girvan)** della partizione greedy:
  alta => spectral decomposition trae beneficio massimo.
- **Betweenness centrality** dei top-K nodi: identifica i
  critical-path nodes (docenti-ponte).

Output: tre card affiancate con valore numerico, interpretazione
testuale auto-generata e top-K betweenness. La visualizzazione
del grafo annotato e' delegata al pannello "Grafo della scuola"
gia' presente sulla Dashboard (Cytoscape).

## 4. Correlazioni e regressioni

POST `/api/diagnostics/correlations`. Tre regressioni su
`statsmodels`:

1. **OLS load_vs_gaps**: numero di buchi `~ teacher_hours`
2. **OLS subjects_vs_soft**: contribuzione SOFT `~ #materie`
3. **Logit saturation_vs_sixth**: P(6a ora) `~ class hours`

Output per ciascun modello: `coef`, `stderr`, `p_value`, `r2` (o
`pseudo_r2` per logit), `interpretation` testuale italiana
auto-generata. Scatter plot ECharts per ogni modello.

## 5. Distribuzioni

POST `/api/diagnostics/distributions`. Cinque distribuzioni +
goodness-of-fit:

- Carico orario docenti (istogramma)
- Carico orario classi per giorno (6 serie)
- Materia x slot (heatmap 20x36)
- Lezioni concorrenti per slot
- KS-test (carichi docenti vs uniforme)
- chi-quadro (carichi giornalieri uniformi?)

UI: due grafici principali (istogramma carichi docenti, heatmap
materia x slot) + lista test con interpretazione.

## Run telemetry

Ogni run produce una serie temporale in `run_telemetry`
(`run_id, step, timestamp_s, phase, payload_json`). I moduli del
solver pushano via il context manager
`utils.telemetry.collector(run_id, phase=...)`. Il run detail
page (`/runs/[id]`) la rispecchia con un grafico objective vs
tempo (linea per phase, ECharts), tabella per-stage e bottone
"Esporta telemetria".

API:
- `GET /api/optimize/runs/{id}/telemetry?limit=&offset=&phase=`
- `GET /api/optimize/runs/{id}/summary` (aggregato per phase +
  serie objective gia' pronta per ECharts)
