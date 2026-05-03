# Statistiche e diagnostica: capire l'orario che il programma ha prodotto

Una volta che piTantum ha generato un orario, viene voglia di
chiederselo: \`E un orario buono? Ci sono squilibri di carico fra i
docenti? Le materie sono distribuite bene nei giorni? La struttura
della scuola \`e tale da rendere il problema "facile" o "difficile"
da risolvere? Il tab **Statistiche e diagnostica** (`/diagnostics`)
risponde proprio a queste domande, attraverso cinque analisi
diverse che illuminano altrettanti aspetti dell'orario.

Sei nel posto giusto se sei un coordinatore d'orario o un
amministratore di sistema che vuole valutare la qualit\`a di una
soluzione, capire dove si nasconde il "rumore" residuo, o sapere
se conviene o no insistere con altre fasi di ottimizzazione.

Le analisi pesanti vengono lanciate come **run asincroni**:
compaiono nel tab Runs come una qualunque fase di ottimizzazione
e tornano qui come grafici quando sono pronte. Cos\`i puoi
lanciarle e fare altro nel frattempo.

> **Per chi sviluppa**: tutti gli endpoint vivono sotto
> `/api/diagnostics/`. La UI usa `<EChart>`
> (`webui/frontend/src/lib/components/EChart.svelte`, Apache
> ECharts ^6 lazy-loaded, tema `pitantum` con palette
> indaco/oro/avorio/terra-di-siena).

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

## Stress test + gestione infeasibility

Il pannello "Avvia check" (tab Vincoli) e' progettato per essere
tirato a fondo: un dataset di vincoli reali completo, includendo
combinazioni intenzionalmente infeasibili, deve essere risolvibile
in poche azioni dall'utente senza dover guardare il database o
toccare il DSL.

**Dataset di stress.** In `experiments/stress_constraints/<profilo>/`
si trovano sei profili (small/medium/big/huge/superhuge/mega) con
tre file ciascuno: `teacher_constraints.json`,
`classroom_constraints.json`, `relational_constraints.json`. Ogni
record ha id stabile, scope, owner_pattern (es. `first_teacher`,
`first_lab`, `gym`, `main_room`, `first_class_year_1`),
livello/peso, espressione DSL, e un flag
`intentionally_conflicting` con la lista dei record con cui
collide. I conflitti sono pensati per produrre core minimali
classici: enforce di slot esplicito vs hard "mai" sullo stesso
slot, vincoli incrociati teacher x classroom su orari sovrapposti,
preferenze contraddittorie sulla stessa risorsa.

**Loader.** `experiments/load_stress_constraints.py` risolve gli
owner_pattern contro il DB live (per ordine crescente di id) e
posta ciascun record su `/api/constraints` (lo stesso dispatcher
unificato che usa la UI). Il mapping `dataset_id -> db_id` viene
salvato in `loaded_<timestamp>.json`, cosi' un'esecuzione
successiva del feasibility-check sa quali righe DB corrispondono
ai conflitti dichiarati.

```
cd experiments
python load_stress_constraints.py --profile small --dry-run
python load_stress_constraints.py --profile small
```

**Workflow di risoluzione.** Una volta caricati i vincoli e
rilevata l'infeasibility, il pannello Vincoli espande in
automatico la sezione "Diagnosi infeasibility" con la lista dei
core, il grafo di Cytoscape e, per ogni membro, quattro bottoni:

1. **Rimuovi** -- elimina il vincolo dal DB (reversibile dallo
   Storico tramite re-creazione, anche se con id nuovo).
2. **Soften** -- chiede una penalty e trasforma HARD/ENFORCED in
   SOFT con quel peso. Il vincolo continua a essere considerato in
   Phase B, ma come termine dell'objective invece che come
   constraint hard.
3. **Disabilita temporaneamente** -- imposta `enabled=False` (o,
   se il modello non ha quel campo, abbassa il livello a
   ALLOWED). Il vincolo resta visibile nel DB ma e' inerte
   finche' non viene ri-abilitato.
4. **Modifica espressione** -- prompt con l'espressione corrente,
   permette di patcharla in-place (utile per typo o per restringere
   un "mai gio" a "mai gio8 AND mai gio9").

**Audit trail e revert.** Ogni azione scrive una riga in
`constraint_interventions` con before_json/after_json,
target_owner_label leggibile e timestamp. Lo Storico mostra
l'elenco in ordine cronologico inverso e per ciascun intervento
non revertito espone un bottone "Revert" che, in funzione
dell'azione originale, ricrea la riga (per remove) o ripristina i
campi (per soften/disable/edit). Il revert produce a sua volta una
riga di tipo "restore" linkata al record annullato via
`reverted_by_id`.

API rilevanti:

- `POST /api/constraints/feasibility-check` -- estrazione MUS
- `POST /api/constraints/apply-suggestion` -- batch atomico di
  remove/soften/disable/enable/edit
- `POST /api/constraints/revert` -- annulla per intervention_id
- `GET /api/constraints/interventions?limit=N` -- storico

Tutto cio' e' progettato per essere usato in tre modi: (a)
esplorazione interattiva da parte dell'utente, (b) suite di test
automatica che carica un profilo, fa partire `apply-suggestion`
con la rimozione suggerita e verifica che il modello diventi
feasible, (c) regressione su una serie di scenari di conflitto
classici per assicurarsi che l'estrattore di core continui a
identificare gli stessi minimal unsat cores attraverso le
versioni.

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
