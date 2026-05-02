# Tecniche di ottimizzazione

Questo file descrive le strategie post-Phase-A disponibili in
piTantum, oltre alle metaeuristiche classiche LNS / SA / TS / ILS
gia' presenti.

Tutti i moduli vivono in `experiments/` e sono esposti via
endpoint REST nel router `webui/backend/routers/optimize.py`. La
UI principale e' la card "Tecniche avanzate" nel tab `/optimize`,
che rispecchia gli stessi parametri configurabili.

## 1. Adaptive Large Neighborhood Search (ALNS)

`experiments/alns.py`. Evoluzione del LNS classico:

- **6 destroy operators**: `random_window`, `day_cluster`,
  `worst_fit_day`, `teacher_day`, `classroom_day`,
  `single_class_week`.
- **3 repair operators**: `cp_sat_window`, `greedy_by_soft`,
  `bfs_fill_back`.
- **Selettore adattivo (roulette wheel)** sopra punteggi
  esponenzialmente decadenti: ogni operator ha un `score` che
  sale quando produce miglioramenti e scende altrimenti; alla
  prossima iterazione la coppia (destroy, repair) viene scelta
  con probabilita' proporzionale al prodotto degli score.
- **Acceptance SA-like**: temperatura T che decresce
  geometricamente (`T_{i+1} = alpha * T_i`); le mosse peggiorative
  sono accettate con probabilita' `exp(-delta / T)`.

Quando usarlo: in alternativa o in aggiunta al LNS classico,
soprattutto quando la sola formula deterministica del LNS si
inceppa su minimi locali. Nel pipeline integrato sostituisce o
segue il LNS (entrambi possono essere ON insieme).

API: `POST /api/optimize/meta/alns` con `budget_s`, `alns_T0`,
`alns_alpha`, opzionali `alns_destroy[]` / `alns_repair[]` per
limitare il pool di operator.

## 2. Variable Neighborhood Search (VNS)

`experiments/vns.py`. Strategia di intensificazione fine:

- **Vicinato 1 (1-swap)**: scambia due lezioni dello stesso prof
- **Vicinato 2 (2-swap)**: due 1-swap incatenati
- **Vicinato 3 (3-chain)**: catena di 3 spostamenti che si chiudono
- **Vicinato 4 (k-opt)**: catena di k mosse atomiche, k in [4..6]

Per ogni vicinato un budget di iterazioni `(400, 200, 100, 40)`;
il primo improvement strictly accettato fa ripartire dal
vicinato 1. Quando un'intera passata 1->4 non trova nulla, la
ricerca termina.

Quando usarlo: tipicamente come **rifinitura** dopo TS o ILS.
Default OFF nella pipeline integrata: attivare per qualita'
massima quando il budget lo permette.

API: `POST /api/optimize/meta/vns` con `budget_s`, opzionale
`vns_neighbourhoods[]`.

## 3. Hall's theorem pre-check

`experiments/diagnostics/hall_check.py`. Diagnostico
SINCRONO eseguibile prima di Phase A. Tre controlli:

1. **Per (class, subject) coverage**: verifica che ogni materia
   richiesta abbia almeno un docente qualificato.
2. **Subject-level supply vs demand**: per ogni materia, somma
   delle ore richieste vs somma `max_hours` dei docenti
   qualificati.
3. **Hall sampling random-subset**: campiona N sottoinsiemi `S`
   di docenti (default 256) e verifica che la domanda delle
   materie ESCLUSIVE a `S` (cioe' insegnabili solo da docenti in
   `S`) sia coperta dalla capacita' di `S`. Una violazione
   restituisce il sottoinsieme come witness.

Tre punti di esposizione UI:

- bottone "Pre-check fattibilita' strutturale" nella card Phase A
- riga nella card "Tecniche avanzate"
- sezione 1 del tab `/diagnostics`

API: `POST /api/diagnostics/hall-check` con `n_samples`,
`teacher_max_hours`. Restituisce sincronamente
`{ok, n_classes, n_teachers, violations[], stats, warnings}`.

Nella pipeline integrata e' uno step **tickable (default ON)**
che, se trova violazioni, **interrompe** la pipeline prima di
buttare tempo su un solver infeasible.

## 4. Column Generation (Dantzig-Wolfe)

`experiments/column_generation.py`. Decomposizione per scuole
molto grandi (>200 classi):

- **Master LP** (scipy.linprog HiGHS): seleziona patterns
  pre-computati di "settimana docente" per coprire la domanda di
  Phase A.
- **Sotto-problema per docente**: genera nuovi pattern in
  funzione delle variabili duali del master.
- **Iterazione**: master -> duali -> nuovi pattern -> master,
  fino a convergenza (nessun pattern con reduced cost negativo).

Lo skeleton attuale fa 1 iterazione e usa un seed-pattern
generator deterministico (rotazione di start hour per produrre
`patterns_per_teacher` varianti). Il master LP risolve un
program di selezione binaria rilassata; la soluzione integrale
si ottiene per arrotondamento per docente.

Default OFF nella pipeline (utile solo per istanze grandi).

API: `POST /api/optimize/column-generation` (asincrono, crea un
run con `kind='cg'`).

## 5. Lagrangian Relaxation con subgradient ascent

`experiments/lagrangian.py`. Decomposizione per cluster + duale
sui ponti inter-cluster:

- **Setup**: identifica i ponti (docenti che insegnano in piu'
  cluster spettrali).
- **Master**: aggiorna i moltiplicatori `lambda_b` via
  `lambda_{k+1} = max(0, lambda_k + alpha_k * g_k)` con
  `alpha_k = alpha_0 / (1 + k)` (schedule diminuente classico).
- **Sub**: per ogni cluster, raffinamento via SA dato il
  vettore lambda corrente.

Lo skeleton converge in `max_iter` iterazioni o quando
`max(|lambda_change|) < tolerance`. Default OFF nella pipeline.

API: `POST /api/optimize/meta/lagrangian` con `budget_s`,
`lagrangian_max_iter`, `lagrangian_tolerance`,
`lagrangian_alpha_0`.

## Pipeline integrata: ordine consigliato

```
hall_check  (ON, diagnostico)
phase_a     (ON, assegnazione cattedre)
phase_b     (ON, scheduling principale)
cg          (OFF, alternativa per istanze grandi)
lns         (ON, classic LNS)
alns        (ON, adaptive LNS)
sa          (ON, simulated annealing)
ts          (ON, tabu search)
vns         (OFF, rifinitura)
lagrangian  (OFF, avanzato)
ils         (ON, iterated local search)
rooms       (OFF, indipendente)
```

Tutti gli step sono trascinabili e tickabili nella card "9)
Pipeline completa" del tab `/optimize`.
