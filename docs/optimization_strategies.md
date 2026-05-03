# Tecniche di ottimizzazione: cosa sono, quando servono

Quando piTantum produce un orario, non lo fa in un solo passo.
Il programma ha a disposizione una piccola "cassetta degli
attrezzi" di strategie diverse: alcune costruiscono la prima
soluzione da zero, altre la migliorano dopo, altre ancora
servono solo per controllare a tavolino se il problema \`e
risolvibile prima di partire. Questa pagina ti spiega ciascuno
strumento attraverso un'analogia concreta, e ti dice quando
conviene attivarlo.

Sei nel posto giusto se sei un coordinatore d'orario o un
amministratore di sistema che si chiede: "che cos'\`e questa
'ALNS' che vedo nel tab Workflow? Devo lasciarla accesa? E il
'pre-check Hall' a cosa serve?"

Tutte le tecniche descritte qui sono attivabili dal tab
**Workflow** (`/optimize`) della web app, nella card "Tecniche
avanzate". Per ognuna trovi la stessa configurazione anche
nella pipeline integrata, dove decidi quali stage eseguire e
in quale ordine.

> **Per gli sviluppatori**: i moduli vivono in `experiments/`
> e sono esposti via REST in `webui/backend/routers/optimize.py`.
> La sezione finale "Per chi sviluppa" elenca file e endpoint.

## 1. ALNS — il LNS che impara da solo cosa funziona

**Analogia**: immagina di scolpire una statua. Il LNS classico
\`e come avere uno scalpello e darti regole fisse: "ogni volta,
togli un pezzo grosso da una zona a caso e ricostruiscilo".
L'**ALNS** \`e lo stesso processo, ma con sei scalpelli diversi
(uno taglia righe orizzontali, uno verticali, uno cluster di
classi vicine, ecc.) e tre modi di ricostruire. Dopo qualche
iterazione lo scultore impara: "quando uso lo scalpello a
righe orizzontali, dieci volte su dieci la statua viene
peggio; quando uso quello a cluster, sette volte su dieci
viene meglio". Da quel momento in poi tende a usare lo
scalpello buono.

**Quando usarla**: appena hai una soluzione iniziale (dopo Phase
B) e hai 1-2 minuti di tempo per migliorarla. Sostituisce o
segue il LNS classico. Default ON.

### Dettaglio tecnico

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

## 2. VNS — la rifinitura che ti porta sull'ottimo locale

**Analogia**: dopo che hai scolpito grossolanamente la statua
con LNS/ALNS, vuoi rifinirla. Il VNS prende in mano una serie
di lime di precisione sempre pi\`u fini: prima prova a scambiare
due lezioni vicine; se non basta, scambia due paia; poi tre in
catena; poi quattro o cinque. Quando ha finito tutto il giro
senza riuscire a migliorare, si ferma — significa che sei arrivato
a un ottimo locale.

**Quando usarla**: alla fine del ciclo di metaeuristiche, dopo
TS o ILS. Non sostituisce LNS/SA/TS: \`e una rifinitura
finale. Default OFF (la accendi quando vuoi spremere il
massimo a costo di pi\`u tempo).

### Dettaglio tecnico

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

## 3. Hall pre-check — capire SUBITO se il problema \`e
> risolvibile

**Analogia**: prima di partire per un viaggio in macchina ti
fermi a controllare il livello della benzina. Se vedi che il
serbatoio \`e vuoto, non parti — eviti di restare a piedi a met\`a
strada. Il **Hall pre-check** \`e l'equivalente per piTantum:
controlla in pochi millisecondi se i docenti che hai a
disposizione hanno *abbastanza ore complessive* per coprire
tutte le ore richieste dalle classi. Se non bastano, te lo
dice subito invece di lasciarti aspettare 10 minuti per scoprire
che il modello \`e infeasible.

\`E un controllo strutturale, non risolve nulla: solo ti
risparmia tempo quando il modello \`e gi\`a perso in partenza.

**Quando usarla**: sempre prima di Phase A, soprattutto in
mezzo all'anno scolastico quando hai modificato cattedre o
aggiunto vincoli che potrebbero aver reso il problema
impossibile. Default ON nel pipeline.

### Dettaglio tecnico

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

## 4. Column Generation — per scuole grandi-grandi

**Analogia**: invece di pianificare l'orario di tutta la scuola
in un colpo solo, costruisci un "catalogo di settimane-tipo"
per ciascun docente (es. tre o quattro varianti che mostrano
come potrebbe andare la settimana di prof Rossi). Poi un
secondo programma sceglie quale settimana-tipo prendere per
ogni docente in modo che tutti i pezzi si incastrino. Se la
combinazione non basta, generi nuove settimane-tipo e ripeti.

\`E come scegliere un appartamento dal catalogo dell'agenzia
immobiliare: invece di cercare in tutte le case esistenti,
guardi solo quelle in catalogo, e se nessuna va bene chiedi
all'agente di tirare fuori altri annunci.

**Quando usarla**: solo per scuole molto grandi (>200 classi).
Per istanze normali la pipeline standard \`e pi\`u veloce.
Default OFF.

### Dettaglio tecnico (stato attuale, commit `b7bb776`)

`experiments/column_generation.py`. Versione attuale --
**iterative-diversified**, che e' un pre-passo verso il vero
Branch-and-Price ma non ne ha ancora la completezza:

- **Master LP** (scipy.linprog HiGHS): seleziona pattern di
  settimana-docente per coprire la domanda di Phase A.
- **Pattern enrichment iterativo**: ogni iterazione aggiunge
  `patterns_per_teacher` nuove varianti per docente (random
  shuffles + hour offsets), rilancia il master, accetta se
  l'obiettivo migliora. Default 5 iterazioni, time budget
  120s.
- **Integer recovery**: per ogni docente, il pattern con peso
  LP piu' alto viene scelto.
- **Completion fallback**: se l'unione dei pattern scelti non
  copre interamente la demand, viene eseguito un Phase B
  giorno-per-giorno from scratch sullo stesso `dc_value`.
  Cosi' la CG e' una **strict superset** di Phase B: se
  converge, vince la sua soluzione (tipicamente migliore SOFT);
  se non converge, degrada a Phase B standard invece di
  ritornare `None`.

Smoke test su `small` (10 classi, 19 docenti): 4 iter, 114
pattern finali, master obj=60, completion ha riempito i gap,
1662 celle, HARD-feasible al 100%, 25.8s wall.

API: `POST /api/optimize/column-generation`. Accetta
`granularity` ('teacher'|'class'|'day'), `branching_strategy`
('ryan_foster'|'variable'), `max_iterations`, `parallel` --
ma oggi solo `granularity='teacher'` corrisponde a un percorso
implementato; gli altri valori vengono accettati con un
warning di log e mappati a 'teacher'.

### Cosa serve per il vero Branch-and-Price (roadmap)

La specifica completa data da Giovanni richiede:

1. **Master LP** ristrutturato: invece dell'attuale
   "ogni pattern di docente t copre tutta la domanda di t"
   (che rende i duali su (t, cl, subj, d) invarianti per i
   pattern dello stesso docente), il master deve permettere
   pattern parziali e accumulare la copertura via somma.
2. **Sub-problema CP-SAT con duali** per ciascuna granularita':
   - `teacher`: variabili `x[(cl, subj, d, h)]`, obiettivo
     `cost_pattern - lambda_t - sum_(cl,subj,d) mu * coverage`,
     vincoli di no-overlap docente.
   - `class`: variabili per ciascuna lezione della classe,
     vincoli di copertura monte ore.
   - `day`: variabili per il giorno, vincoli di non-overlap
     classe e docente, obiettivo guidato dai duali.
3. **Iterative pricing loop**: master -> duali -> sub-CP-SAT
   in parallelo -> nuovi pattern con reduced cost negativo ->
   master, fino a convergenza.
4. **Variable branching**: scegli `x_p` con `0 < x_p < 1`,
   crea due rami (`x_p = 0` e `x_p = 1`), ricorri.
5. **Ryan-Foster branching**: scegli (i, j) elementi tali che
   `sum_{p covers both} x_p` sia frazionario; due rami "i e j
   sempre insieme" / "i e j mai insieme". Stato di branching
   da gestire con merge/separate hash maps.
6. **Branch-and-bound tree**: ricorsione con bound tracking,
   pruning quando il bound del nodo e' peggiore della miglior
   intera trovata.

Stima realistica: 5-10 giorni di engineering OR focalizzato per
chiudere correttamente. La struttura di `experiments/column_generation.py`
e' pronta a essere estesa con un secondo path
(`mode="branch-and-price"`), ma il refactor del master e' la
parte invasiva.

Riferimenti: Dantzig & Wolfe 1960; Desrosiers & Lubbecke 2005,
*A Primer in Column Generation*; Ryan & Foster 1981;
Vanderbeck & Wolsey 2010.

Default OFF nella pipeline (utile solo per istanze grandi).

## 5. Lagrangian Relaxation — divide e impacca

**Analogia**: la scuola \`e divisa in piccoli gruppi di classi che
hanno pochi docenti in comune (i "cluster" prodotti dalla
decomposizione spettrale). Per la maggior parte dei docenti,
ognuno lavora dentro un solo cluster e si pu\`o pianificare il
suo orario senza guardare cosa fa il resto della scuola. Per i
"docenti-ponte" (che insegnano in pi\`u cluster) c'\`e per\`o un
problema di coordinamento: non possono essere in due cluster
diversi nello stesso slot. Il **Lagrangian** affronta proprio
questo: introduce un costo "fittizio" sui ponti, lo aggiusta
iterativamente per spingere il modello a rispettare il vincolo
naturale, e finch\'e i ponti restano coerenti la pianificazione
parallela dei cluster funziona.

**Quando usarla**: scuole medio-grandi con molti cluster ben
separati. Default OFF (avanzato; per la maggior parte dei casi
LNS+ALNS+SA+TS sono sufficienti).

### Dettaglio tecnico

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

## Le altre metaeuristiche (LNS classico, SA, TS, ILS)

Le quattro metaeuristiche "storiche" del solver sono sempre
disponibili, attive di default nel pipeline e si combinano bene
fra loro.

- **LNS (Large Neighborhood Search)**. Il padre dell'ALNS:
  distrugge una porzione della soluzione e la ricostruisce con
  CP-SAT. Pi\`u "rigido" dell'ALNS perch\'e non sceglie da solo
  quale zona attaccare.

- **SA (Simulated Annealing)**. Analogia: una palla di acciaio
  fusa che si raffredda. Quando \`e calda, si muove molto e
  accetta anche peggioramenti (per scappare da minimi locali);
  raffreddandosi diventa sempre pi\`u selettiva e finisce per
  posarsi nel pozzo pi\`u profondo che ha trovato.

- **TS (Tabu Search)**. Analogia: un esploratore che tiene un
  taccuino delle ultime mosse fatte e si vieta di ripeterle per
  un po'. Cos\`i esce dai loop in cui altrimenti gli capiterebbe
  di fare A->B->A->B in continuazione.

- **ILS (Iterated Local Search)**. Alterna fasi di "ricerca
  locale tranquilla" con scossoni periodici (perturbazioni)
  per esplorare zone diverse dello spazio.

## Decomposizione: spezzare il problema in parti

Tre nuovi metodi di decomposizione si affiancano alla
decomposizione spettrale gi\`a esistente. Sono ortogonali fra
loro: si possono combinare in pipeline a pi\`u stadi
(spettrale + temporale, METIS + temporale, eccetera) per
ottenere il massimo speedup.

### Decomposizione temporale (per giorno)

La decomposizione temporale spezza il problema lungo l'asse
del tempo invece che lungo le entit\`a. Ciascuno dei sei
giorni della settimana diventa un sotto-problema separato,
risolvibile in parallelo. Una piccola fase di
pre-distribuzione decide quante ore di ciascuna cattedra
vanno in ciascun giorno (rispettando i vincoli settimanali
come la doppia ora di matematica e il tetto di ore per
classe), e poi sei istanze CP-SAT lavorano una per giorno
sulle ore cos\`i pre-distribuite. Il vantaggio principale \`e
che il metodo \`e \emph{sempre applicabile}: non richiede
una struttura comunitaria nel grafo classe-docente, e
parallelizza naturalmente su sei core di una macchina
moderna. \`E pensato per scuole dense, dove la decomposizione
spettrale fatica perch\'e i cluster non emergono. Modulo:
`experiments/decomposition_temporal.py`.

### Decomposizione METIS (k-way multilevel partitioning)

METIS \`e una libreria classica per il partizionamento di
grafi che produce partizioni $k$-bilanciate minimizzando
il taglio. Funziona bene su grafi densi senza struttura
comunitaria evidente, dove la decomposizione spettrale
restituisce cluster artificiali. \`E configurabile con il
numero di partizioni $K$ (default $K = \sqrt{n_{\text{classes}}}$)
e la tolleranza di sbilanciamento (default 5\%). Richiede la
libreria Python `pymetis`, installabile con `pip install
pymetis`; in mancanza, il sistema segnala chiaramente
all'utente che deve installarla o scegliere un metodo
alternativo. Modulo: `experiments/decomposition_metis.py`.

### Decomposizione per curriculum

La decomposizione per curriculum sfrutta direttamente
l'informazione gi\`a codificata nel campo `curriculum_id`
delle classi: ogni indirizzo (Liceo Scientifico, ITIS
Informatica, eccetera) diventa un cluster, e i docenti che
insegnano in pi\`u indirizzi sono i ponti. \`E la
decomposizione pi\`u prevedibile e interpretabile, perch\'e
ogni cluster corrisponde a un'organizzazione che il
coordinatore conosce bene; in compenso ignora la connettivit\`a
effettiva del grafo e produce ponti pi\`u numerosi quando i
docenti circolano molto fra indirizzi. \`E pensata per
scuole con indirizzi ben definiti e con poca circolazione
inter-indirizzo dei docenti. L'utente pu\`o accorpare
manualmente curricula con poche classi per evitare cluster
troppo piccoli. Modulo:
`experiments/decomposition_curriculum.py`.

### Auto-detect della strategia migliore

Il modulo `experiments/decomposition_auto.py` espone la
funzione `auto_detect_decomposition_strategy(profs)` che
calcola due metriche descrittive del grafo bipartito
classe-docente (modularit\`a di Newman-Girvan e densit\`a) e
suggerisce la strategia di decomposizione migliore. Se la
modularit\`a \`e alta (sopra 0.30) consiglia la decomposizione
spettrale, perch\'e il grafo presenta cluster naturali; se la
densit\`a \`e alta (sopra 0.60) consiglia METIS, perch\'e il
grafo \`e denso e privo di cluster spontanei; in tutti gli
altri casi consiglia la decomposizione per curriculum. In
ogni caso suggerisce di combinare la scelta primaria con la
decomposizione temporale, che parallelizza ortogonalmente
sui sei giorni della settimana. La raccomandazione
restituita \`e un dataclass `DecompositionRecommendation` con
strategia, flag combinatorio, le due metriche e una
motivazione testuale leggibile dall'utente.

L'endpoint REST `GET /api/optimize/decomposition/recommend`
espone questa funzione al frontend, che la usa per mostrare
un tooltip "Suggerimento" nella card delle decomposizioni del
tab Workflow.

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
