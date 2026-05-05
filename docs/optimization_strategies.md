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

API: `POST /api/optimize/column-generation`. Accetta:
- `mode`: 'iterative-diversified' (default) | 'branch-and-price'
  | 'auto'
- `granularity` (per BP): 'auto' | 'teacher' | 'teacher-day' |
  'teacher-class' | 'teacher-class-subject' | 'teacher-subject' |
  'class' | 'class-day' | 'day' | 'curriculum'
- `branching_strategy`: 'ryan_foster' | 'variable'
- `max_iterations`, `bp_max_iterations`, `pricer_time_limit`,
  `pricer_workers`, `parallel`

Il valore `granularity='auto'` viene risolto server-side in base
al numero di classi della scuola attiva: <15 classi -> 'teacher',
15-30 -> 'teacher-day', 30-50 -> 'teacher-class', 50-80 -> 'class',
>80 -> 'curriculum'. Gli altri 4 valori (`teacher-class-subject`,
`teacher-subject`, `class-day`, `day`) sono accessibili solo
manualmente.

### Branch-and-Price completo (mode='branch-and-price')

Tutte e 9 le granularita' sono ora wirate end-to-end (UI -> schema
-> router -> backend -> engine -> CP-SAT pricer). L'engine usa due
master LP a seconda della granularita':

- **Master variant 1** (`_solve_master`, scipy.linprog HiGHS):
  per le 4 granularita' teacher-based (`teacher`, `teacher-day`,
  `teacher-class`, `teacher-class-subject`, `teacher-subject`).
  Vincolo `sum_p x[t,p] = 1` per ogni docente: il pricer emette
  un pattern settimanale completo per il docente, dove SOLO la
  fetta della granularita' (es. la classe per `teacher-class`) e'
  ottimizzata da CP-SAT, il resto e' greedy-piazzato come contesto.
- **Master variant 2** (`_solve_master_dw`, Dantzig-Wolfe puro):
  per le 4 granularita' multi-docente (`class`, `class-day`,
  `day`, `curriculum`). Niente equality per docente; al posto:
  - **cover** `sum_col x*placed_col(t,cl,s,d) >= demand(t,cl,s,d)`
  - **class no-overlap** `sum_col x*occupies(cl,d,h) <= 1`
  - **teacher no-overlap** `sum_col x*occupies(t,d,h) <= 1`
  Il pricer emette un pattern parziale (multi-docente) che il
  master combina via set-packing greedy nel recovery integer.

#### Pricing loop con tutte le tecniche di scalabilita'

```
seed columns (iterative-diversified) ---+
                                        |
                                        v
                            +------- Master LP solve ----+
                            |     (variant 1 o variant 2) |
                            |                             |
        +--- duali stabilizzati (box-step) ---------------+
        |     pi_blend = (1-alpha)*pi_stable + alpha*pi_raw
        |     alpha=0.2, pi_stable aggiornato ogni iter
        v
   Pricing parallelo (ProcessPoolExecutor, cpu//2 worker)
        |   per ogni key di granularita' indipendente:
        |     greedy warm-start hint via model.add_hint
        |     CP-SAT SEMPRE invocato (mai sostituito da greedy)
        |     se rc < -eps: nuova colonna -> pool
        v
   Column management: rc EWMA su 20 iter
        |   se pool > 10K colonne attive:
        |     drop colonne con rc_avg piu' positivo (eccetto
        |     seed e colonne con x>0)
        |     re-solve master sul pool ridotto
        v
   Loop fino a no-improving-column o budget esaurito.
   
   Ryan-Foster branching tree (best-first, LP-bound prune):
     1. trova pair (i,j) di slot (cl,d,h) frazionari (Achterberg)
     2. branch "together": colonne devono coprire BOTH o NEITHER
     3. branch "apart": nessuna colonna copre BOTH
     4. ricorsivo, max_depth=20, max_nodes=1000
   
   Integer recovery (greedy set-packing) -> sol_dict
   HARD-feasibility check; fallback a completion solver giorno-per-
   giorno se assembly non chiude.
```

#### CP-SAT come minimizzazione fondamentale

Per OGNI granularita', il sub-problem CP-SAT e' la minimizzazione
fondamentale; il greedy serve esclusivamente come `model.add_hint`
warm-start (acceleratore). Se CP-SAT non trova soluzione feasible
entro il time-limit, il pricer ritorna `(None, 0.0)`: il greedy
NON viene promosso a colonna in nessuna circostanza.

Variabili e vincoli per ogni granularita' (tutti i pricer
condividono il pattern: BoolVar per slot, cattedra-hours equality,
no-overlap sui slot in scope, integer-scaled `-lam*slot +
penalty_sixth` come obiettivo):

| Granularita' | Variabili CP-SAT | Cosa ottimizza il pricer |
|---|---|---|
| `teacher-class` | slot[(s,d,h)] per s in subjects(t,cl) | tutti i slot di t in una classe |
| `teacher-class-subject` | slot[(d,h)] per (t,cl,s) | una sola cattedra |
| `teacher-subject` | slot[(cl,d,h)] per cl in classes(t,s) | (t,*,subj,*,*) |
| `teacher-day` | slot[(cl,s,h)] per (cl,s) in catt(t,day) | un giorno del docente |
| `class` | slot[(t,s,d,h)] per (t,s) in catt(cl) | settimana intera della classe |
| `class-day` | slot[(t,s,h)] per (t,s) in catt(cl,day) | un giorno della classe |
| `day` | slot[(t,cl,s,h)] tutti i (t,cl,s) del giorno | un giorno globale (multi-classe) |
| `curriculum` | slot[(t,cl,s,d,h)] per cl in curriculum_id | settimana intera dell'indirizzo |

#### Tecniche di scalabilita' per MEGA (100 classi)

Tutte e 4 implementate e attive di default:

1. **Ryan-Foster recursive tree**
   (`_run_ryan_foster_tree`):
   best-first node exploration con heap su LP-bound, pruning per
   bound-vs-incumbent, max_depth=20, max_nodes=1000.
   Achterberg pair score `s*(1-s)` su pair di slot (cl,d,h)
   stessa-classe.

2. **Box-step dual stabilization** (`_blend_duals`):
   pi_blend = (1-alpha)*pi_stable + alpha*pi_raw con alpha=0.2.
   Applicata sia al master variant 1 (lambda_cover, mu_teacher)
   che al variant 2 (lambda_cover, mu_class, mu_teacher).

3. **Column management** (`_maybe_purge_pool_dw`): EWMA del
   reduced cost per colonna su 20 iter; quando il pool eccede
   10K colonne, drop delle peggiori (rc_avg piu' positivo)
   eccetto colonne in basis (x>0) e seed columns.

4. **Parallel pricing** (`ProcessPoolExecutor`): default workers
   = `os.cpu_count() // 2`, capped at n_keys. Fall-back graceful
   a sequential se il pickle/spawn fallisce.

#### Performance characteristics (numeri misurati)

Smoke su `small` (10 classi, 19 docenti): 4 iter, 114 pattern
finali, master obj=60, completion ha riempito i gap, 1662 celle,
HARD-feasible al 100%, 25.8s wall.

Benchmark sintetico MEGA-style (vedi
`tests/benchmarks/test_bp_mega.py`):

| Scala | Classi | Docenti | Cattedre | t_BP | HARD | obj | RF nodi |
|---|---|---|---|---|---|---|---|
| mega_50 | 50 | 48 | 200 | 1.93s | si | -- | 1 |
| mega_100 | 100 | 100 | 400 | 5.22s | si | 0.0 | 1 |

Lo scenario sintetico e' strutturalmente facile (ogni cattedra
e' un blocco di 4 ore in un singolo giorno), quindi il LP master
trova subito la soluzione integer. Su istanze reali con
distribuzione giornaliera meno regolare la pipeline spende piu'
tempo per iterazione, ma gli obiettivi 30-min/60-min restano i
target di calibrazione.

### Auto-detect della granularita' (nella UI)

L'UI espone una opzione `auto` (default) che il backend
risolve in base al numero di classi della scuola attiva:

- **< 30 classi** -> `teacher`. Il catalogo settimanale per
  docente e' piccolo abbastanza da coprire bene lo spazio.
- **30-80 classi** -> `class`. Il catalogo per-classe scala
  meglio mentre quelli per-docente esplodono.
- **> 80 classi** con curricula ben definiti -> `curriculum`.
  Sfrutta la struttura bloccata della scuola.
- **`day`** non e' mai default ma resta selezionabile per
  esperimenti.

Per il MEGA (100 classi) l'auto-detect propone `curriculum`,
che e' la scelta naturale dato che gli 8 indirizzi della
scuola hanno pool di docenti largamente disgiunti.

### Riferimenti

- Dantzig & Wolfe 1960, *Decomposition principle for linear
  programs*. L'articolo che inaugura la decomposizione
  Dantzig-Wolfe.
- Desrosiers & Lubbecke 2005, *A Primer in Column Generation*.
  Riferimento moderno e accessibile.
- Ryan & Foster 1981, *An integer programming approach to
  scheduling*. Lo schema di branching che porta il loro nome.
- Vanderbeck & Wolsey 2010, *Reformulation and decomposition of
  integer programs*. Trattamento sistematico della decomposizione
  block-angular su cui si basa la granularita' per curriculum.

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
