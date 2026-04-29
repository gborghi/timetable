# Analisi del progetto "schedule" e proposte di rilancio

Questo documento e` rivolto a Giovanni. Riassume cosa fa oggi il codice
in `schedule/`, dove sono i colli di bottiglia, perche` l'assegnazione
prof->classe non converge, e quale strada conviene prendere per arrivare
a un orario di scuola di taglia reale (~30-40 classi, ~80-100 docenti).
ASCII puro: accenti come `e\`` o `e'`.


## 1. Quadro tecnico del codice attuale

### 1.1 Mappa dei file

- `schedule/mock_classes.py` e `schedule/mock_classes2.py` --
  generatore mock. Le due varianti differiscono solo per il numero di
  sezioni per indirizzo (la `2` produce un dataset piu` piccolo, ~12
  classi). Definiscono le classi `Teacher`, `SchoolClass`,
  `SubjectGroup`, `Curriculum`. Costruiscono curricula reali (per anno
  e indirizzo) e poi:
   1) calcolano le ore richieste per materia,
   2) inventano docenti random con classe di concorso pesata,
   3) assegnano docenti->classi con un modello CP-SAT in 4 fasi
      lessicografiche (Phase 1: completare le cattedre; Phase 2:
      ridurre il numero di classi distinte per docente; Phase 3:
      massimizzare il numero di indirizzi distinti per docente;
      Phase 4: bilanciare un punteggio di "qualita\` indirizzo"),
   4) salvano `profs.pkl` con la struttura {prof: {classi: {classe:
      {materia: {ore: N}}}, glibero: [d1, d2, d3]}}.

- `schedule/prog.py`, `prog2.py`, `prog3.py`, `prog4.py` -- ottimizzatore
  dell'orario settimanale. Caricano `profs.pkl` e costruiscono un modello
  CP-SAT su variabili booleane
  `lectures[(prof, classe, materia, giorno, ora)]` con
  giorni 1..6 (lun..sab) e ore 8..13 (in `prog4.py`; `prog3.py` arriva
  fino a 14). `prog4.py` e` la versione piu\` evoluta.

- `schedule/stream1.py`, `stream2.py` -- visualizzatori Streamlit della
  soluzione (per classe / per docente).

- `schedule/profs.pkl`, `solution_timetable.pkl`, `solutionmock.pkl` --
  artefatti di runs precedenti.

- I PDF nella radice (Pisinger 2007, ALNS, ecc.) sono riferimenti
  bibliografici sulle vicinanze grandi (LNS / VLSN), tecniche di
  matheuristic, problemi di assegnazione.

### 1.2 Il modello dell'orario (prog4.py) in sintesi

Variabili principali:
- `lectures[(prof, cl, subj, day, hour)] : Bool`
  istanziata solo per i triple (prof, cl, subj) effettivamente
  presenti in `profs.pkl`, su 6 giorni x 6 ore.
- `gliberi[prof]['choice'] : 3 Bool` per scegliere il giorno libero
  fra 3 candidati.
- molte variabili ausiliarie booleane e intere (vedi sotto).

Vincoli hard:
- somma delle ore (prof, cl, subj) sulla settimana = ore previste;
- non sovrapposizione prof: per ogni (prof, day, hour) somma <= 1;
- non sovrapposizione classe: per ogni (cl, day, hour) somma <= 1;
- "no holes" per la classe: la giornata della classe parte alle 8
  (`accums[0]==1`) e la presenza per ora e\` non crescente
  (`accums[i+1] <= accums[i]`);
- giorno libero: il prof non ha lezioni nel giorno di indice 0 / 1 / 2
  della sua lista di candidati, condizionato al booleano scelto;
- max 2 ore al giorno per (prof, cl, subj), max 3 ore al giorno per
  (prof, cl);
- esistenza di almeno una "coppia" di Matematica consecutiva
  e di Scienzemotorie consecutiva nella settimana (per classe).
- "1 ora isolata in un giorno" vietata per il prof (se il prof ha
  lezione, ne ha almeno 2 quel giorno).

Vincoli soft / penalita\`:
- "buche" del prof (pattern 1-0-1, 1-0-0-1, 1-0-0-0-1) con pesi 1,2,3;
- piu\` di 4 ore in un giorno per il prof;
- penalita\` quadratica sulla uniformita\` delle ore della cattedra
  giornaliera per (prof, cl, subj) e per (prof, day) -- una distribuzione
  "tutte uguali sui giorni utili" e\` premiata;
- "Matematica nelle prime ore" (somma di `lectures * (ora - 7)`);
- giorno libero rang. 2 e 3 della lista vengono penalizzati 50 / 100.

Pattern di risoluzione:
- I `lectures` vengono aggiunti **incrementalmente in batch** di 100
  coppie (prof, cl). Per ogni batch si:
   1) ricostruisce un nuovo `CpModel`,
   2) si aggiungono variabili e tutti i vincoli soltanto sulle coppie
      gia\` incluse (pivot `included_pairs`),
   3) si lancia `solver.Solve` con `max_time_in_seconds=160` e
      `num_search_workers=64`,
   4) si raccoglie l'assegnazione corrente come `current_hints` e si
      passa al batch successivo,
   5) chiamate ripetute di `check_feasibility(model, ...)` dopo ogni
      gruppo di vincoli per "vedere" se e\` ancora soddisfacibile.
- Dopo l'ultimo batch viene costruito un modello "full" da zero con
  tutti i vincoli e tutte le coppie, e risolto per `maxtimeinsec`.

### 1.3 Il modello dell'assegnazione prof->classe (mock_classes2.py)

Variabili: per ogni (classe, materia, docente compatibile per classe
di concorso) un Bool `a`. Sono memorizzate in `iclass.docenti[subj]`
e `teacher.cattedra[subj]`.

Vincoli hard:
- per ogni (classe, materia): esattamente 1 docente assegnato
  (`sum(assignedsubject)==1`);
- per ogni docente: ore totali <= max_hours.

Quattro fasi di ottimizzazione lessicografica:
- Phase 1: minimizza `cattedracompleta = sum(max_hours - actual_hours)`
  -- vuole le cattedre piene.
- Phase 2: minimizza `fewclasses = sum(numero classi distinte per
  docente)`.
- Phase 3: massimizza `manycurricula` (negato e minimizzato).
- Phase 4: minimizza `scoremismatch`, una equazione di equita\`
  pesata su `curriculum_scores` che cerca di dare ad ogni docente
  una media di "qualita\` indirizzo" simile.

Tra le fasi, si stringe un vincolo sull'objective vecchio
(es. `model.Add(cattedracompleta <= int(min_cat))`), si pulisce
l'objective dal proto e si rilancia.


## 2. Diagnosi dei colli di bottiglia computazionali

### 2.1 Conteggio ordine di grandezza per `prog4.py`

Per una scuola "grande" ipotizzata (32 classi, ~80 docenti, ~30 ore/sett
di curriculum, una classe di concorso media che insegna ~1.2 materie a
~5 classi):

- triple (prof, cl, subj) effettive: la somma su tutte le classi delle
  materie del curriculum vale ~32 * 11 = 352 cattedre-materia, da cui
  ~352 triple totali (perche\` ogni cattedra ha un solo docente);
- variabili `lectures`: 352 * 36 slot = **~12.7 k Bool**;
- variabili "hasit" del modulo "buche": 80 prof * 6 giorni * 6 ore
  = **2880 Bool reified** (`AddBoolOr(haora).OnlyEnforceIf(oras)` con
  decine di literal nel `haora` per i prof a molte cattedre);
- variabili buco/cinqueore: 80 * 6 * 7 = **~3.4 k Bool ausiliari**;
- variabili e moltiplicazioni quadratiche di "uniform_class_penalties":
  per ogni triple e ogni giorno ~352 * 6 = **~2100 IntVar +
  AddMultiplicationEquality**;
- per "uniform_prof_penalties": 80 * 6 = 480 IntVar quadrati;
- vincoli totali: stimati 30-50 mila propagatori dopo l'espansione
  delle reifiche.

I numeri non sono enormi in assoluto (CP-SAT puo\` reggere modelli
bool molto piu\` grandi), ma:

- **`AddMultiplicationEquality` su IntVar e\` la singola fonte di
  costo dominante.** Internamente CP-SAT lo linearizza con grandi
  tabelle / canalizzazioni. Avere 2-3 mila moltiplicazioni
  "iore * iore" con dominio [-40, 40] -> [0, 1600] crea molto
  lavoro di presolve e propagatori pesanti su domini interi.
- La penalita\` "Matematica prima possibile" e\` lineare ma diluita su
  classi * giorni * ore = 32 * 6 * 6 = 1152 termini sommati in objective
  con coefficienti grossi (20 * (ora-7)) -- non un grosso problema, ma
  contribuisce.
- Le penalita\` buche sono calcolate sulle reifiche pattern-based
  (1-0-1, 1-0-0-1, 1-0-0-0-1) -- e\` una **PB ridondante**: avere
  contemporaneamente buco23 e buco234 sovra-conta. Inoltre lo stile
  e\` stretto e crea vincoli ridondanti tra buco2/3/4 e buco23/buco234.
- Mancano **rotture di simmetria** ovvie:
  - i 6 giorni della settimana non sono intrinsecamente ordinati per
    il modello: si potrebbe richiedere ad esempio che il giorno con
    il maggior numero di ore settimanali (per la classe) non sia il
    sabato, oppure fissare un ordine lessicografico tra giorni con
    pari "carico". Il solver perde tempo a esplorare permutazioni di
    giornate equivalenti.
  - le 2 ore di una stessa cattedra in un giorno sono interscambiabili
    se sono nelle stesse 2 ore del giorno -- meno rilevante perche\`
    ogni ora e\` un Bool distinto, ma la penalita\` quadratica le
    "indirizza" senza spezzarle simmetricamente.
- Il **batch incrementale** ricostruisce il modello da zero ogni volta:
  spendi tempo a riempire il proto del modello, fare presolve di nuovo,
  passare hints. Inoltre un batch puo\` essere infeasible: nessun
  meccanismo di "rilascio" dei vincoli aggiunti in caso di stallo. Le
  chiamate `check_feasibility` aggiungono anche ognuna un solve
  intermedio di 10 sec (di nuovo `log_search_progress=True` molto
  rumoroso) che a fine procedura significa ~10-12 solve da 10 sec
  prima del solve "vero". E\` overhead importante.
- `num_search_workers=64` e\` molto piu\` dei core fisici disponibili
  su una macchina tipica (8-12). CP-SAT lavora meglio fra "num
  workers logical = num cpu" e a volte "num cpu / 2", per via del
  portfolio di strategie. 64 worker su 8 thread fisici crea
  context-switch e contention.
- Manca `cp_sat.parameters.linearization_level = 2` o un tuning
  dei parametri (`search_branching`, `optimize_with_core`, ecc.).
- Manca un objective gerarchico: tutte le penalita\` sono fuse in un
  unico minimize con coefficienti in floating point (`* 0.8`,
  `* 0.2`). CP-SAT internamente moltiplica per portare a interi: i
  coefficienti 0.8, 0.2 generano scaling che puo\` causare rumore. La
  funzione obiettivo unica con fattori molto eterogenei
  (`accumprimmat * 20 + accumbuchi * 30 + cinqueoretot * 40 +
  totpenaltore * 0.8 + totpenaltoreprof * 0.2`) intreccia obiettivi
  di natura diversa, peggiorando il LB.
- Non c'e\` **decomposizione**. Il modello cerca di risolvere
  contemporaneamente: scelta del giorno libero, no-holes per classe,
  packing del giorno, "Matematica al mattino", uniformita\` ore
  cattedra. Sono obiettivi di natura diversa che si possono
  affrontare in cascata.

### 2.2 Numeri pratici aspettati

Sul mock attualmente generato (in `mock_classes2.py` con il default
"piccolo": 4 indirizzi attivi su pochissime sezioni), il modello
attuale gira in qualche minuto. Se lo si scala alla grandezza vera
(20+ sezioni come in `mock_classes.py`), `prog4.py` con `maxtimeinsec
= 160` per batch di 100 e poi un solve finale di 160 sec
**non chiude**: nelle prove note di Giovanni rimane in stato
`UNKNOWN` con `objective_bound` distante dalla `objective_value`
trovata. La causa non e\` "infeasibilita\`" ma "bound LP debole" per
le penalita\` quadratiche, sommato all'overhead dei batch.


## 3. Diagnosi del fallimento dell'assegnazione prof->classe

Il modulo `mock_classes2.py` *risolve sempre* le fasi 1-3 in tempi
ragionevoli (fase 1 e\` essenzialmente un assegnamento bipartito,
fasi 2 e 3 contano i unique-set, lineari, modesti). La fase **4 e\`
quella che non converge.** Motivi:

1. La definizione di `scoremismatch` introduce
   `AddMultiplicationEquality(scoretimesthours, [iscore, totalhours])`
   e
   `AddMultiplicationEquality(tscoretimeshours, [totalscore,
   thisteacher.actual_hours])`
   con `iscore` in [-10000, 3000000] e `totalhours` in [0, 100000].
   Il prodotto vive in [-3e8, 3e10]. Domini interi enormi e
   prodotto di IntVar in CP-SAT producono **tabelle gigantesche**
   internamente. Niente Presolve riuscira\` a stringerli in tempi
   utili.
2. Il bilanciamento "media-pesata-per-ore-mantenuta-uguale" si puo\`
   formulare in modo **lineare** introducendo `target = totalscore /
   totalhours` e calcolando residui `iscore - target *
   actual_hours`. CP-SAT non ama divisioni, ma si puo\` evitare
   moltiplicando entrambi i lati e mantenendo solo *una*
   moltiplicazione per teacher e una globale, oppure -- meglio --
   risolvere l'equita\` come **post-processing locale** (swap
   migliorativi) dopo le fasi 1-3.
3. La sequenza lessicografica non porta hint utili tra fasi: tra
   phase 3 e phase 4 si ricostruisce l'objective ma la struttura
   e\` cambiata radicalmente, e l'`AddHint` da phase 3 e\` solo per
   gli `assignment_vars` (assegnazione prof->materia per classe), non
   per le variabili interne di `scoremismatch`. Quindi la fase 4
   parte praticamente da zero e con un dominio enorme.
4. Vincoli hard mancanti che renderebbero le cattedre realistiche:
   - "una classe deve avere docenti distinti per materie distinte"
     non e\` esplicito (e\` implicito perche\` ogni materia ha 1
     docente, ma niente impedisce a un docente di prendere due
     materie diverse della stessa classe -- se la classe di concorso
     lo consente -- e questo dovrebbe essere voluto come scelta).
   - Numero massimo di classi diverse per docente (cattedra
     "spezzettata") non e\` un vincolo hard ma solo un soft in fase 2.
5. La randomizzazione iniziale `assign_teachers_to_classes` (assegna
   docenti random alle classi prima di costruire il modello) **non
   serve a niente**: i suoi effetti vengono completamente sovrascritti
   dalla creazione delle variabili in `createmodelvariables`. Genera
   solo confusione di lettura.

In sintesi: **il problema dell'assegnazione e\` ben dimensionato per
CP-SAT *finche\` resta lineare*. Diventa intrattabile con il
bilanciamento score quadratico-cross-prodotto.**


## 4. Proposte concrete di ottimizzazione del modello attuale

Quelle che hanno il rapporto piu\` favorevole "tempo speso / impatto":

### 4.1 Eliminare i prodotti quadratici e usare soft-LP

- Sostituire le penalita\` quadratiche
  `iore^2 = (sum*6 - thisore)^2`
  con penalita\` **assolute**: introdurre `AbsExpr` o equivalente
  `iore_abs >= iore` e `iore_abs >= -iore`, e sommare `iore_abs`.
  La somma delle deviazioni assolute e\` quasi sempre indistinguibile
  dalla somma dei quadrati per il fine pratico (uniformita\`), ma
  costa **un ordine di grandezza meno** in CP-SAT.
- Idem per `scoremismatch`: usare dev. assoluta o, ancora meglio,
  per ognicoppia di docenti `(t1, t2)` aggiungere
  `|score_t1 * hours_t2 - score_t2 * hours_t1| <= K`. Solo per i
  docenti rilevanti (es. con classi di concorso comuni).

### 4.2 Decomposizione in fasi

Lo scheduling settimanale e\` un problema con due "livelli" naturali:
- (A) **assegnazione giorno**: per ogni cattedra, in quanti slot del
  giorno X cade.
- (B) **piazzamento ore**: dato il numero di ore-cattedra per giorno,
  riempire le 6 ore della giornata (no holes, no overlap).

Il livello (A) e\` un piccolo problema di assegnazione (per ogni
classe: tabella materia x giorno con righe = ore richieste,
colonne giornaliere fra 0 e max_per_giorno) -- 6 colonne per ~11
materie per ~32 classi e\` solvibile in millisecondi.

Il livello (B), una volta fissato (A), e\` un problema **per giorno
e per classe** indipendente, di taglia 6 slot x ~5-6 cattedre/giorno --
banale.

I vincoli "transversali" (no-overlap del prof) si trattano cosi\`:
- (A) viene risolto **insieme su tutte le classi**, gia\` con il
  vincolo di overlap del prof nel giorno (LB superiore alle ore
  contemporanee del prof in giorno X);
- (B) per ogni giorno si risolve insieme su tutte le classi,
  garantendo per ogni slot orario del giorno che il prof non sia in
  due classi.

Decomporre cosi\` riduce il numero di Bool a:
- (A): `tab[(prof, cl, subj, day)] : IntVar 0..3` -- per
  l'esempio sopra ~352 * 6 = **~2100 IntVar di range piccolo**;
- (B): per ogni giorno, ~12k Bool / 6 = **~2k Bool**.

E\` l'approccio che la letteratura sui timetabling chiama
"day-then-period" o "phased CP" (vedere il PDF Pisinger nella
cartella radice).

### 4.3 Rotture di simmetria

- ordinare i giorni: imporre che il giorno libero "piu\` desiderato"
  sia, a parita\` di costo, quello con indice piu\` basso (gia\`
  parzialmente ottenuto con la penalita\` 0/50/100, ma si puo\`
  rinforzare con un vincolo "se choice[2] allora choice[1]==0").
- per le ore consecutive di Mat/Ginnastica: chiedere che la prima
  ora del blocco di 2 sia <= 11 (il modello gia\` ha range 8..11,
  bene), ma anche che la prima istanza del blocco settimanale
  lessicograficamente e\` la piu\` "in alto" (giorno minore, ora
  minore) -- trasforma molte permutazioni equivalenti in una sola.
- per classi con la stessa "firma curriculum-orario" (es. due 1A
  scientifico): la presenza/assenza di 1A_Scientifico e 1B_Scientifico
  in uno slot e\` simmetrica; spezzare con un vincolo lessicografico
  sulle prime ore della settimana.

### 4.4 Vincoli ridondanti utili

- per ogni classe, ogni giorno: somma su (prof, materia) della classe
  in quel giorno fra `min_giornaliero` e `max_giornaliero`. Per
  scuole italiane tipiche: tra 4 e 6 ore al giorno per la classe.
  E\` gia\` implicato dal "no-holes" + "max ore settimanali", ma se
  scritto esplicitamente accelera la propagazione.
- per ogni prof, somma settimanale di "hasit" (giorni di lavoro) =
  numero di giorni di lavoro = 6 - giorni_liberi -- aiuta il LB.
- domain reduction: se `ore(cattedra) <= 2` allora la cattedra puo\`
  occupare al massimo 1 giorno (non 2): permette di vietare slot.
  E\` un vincolo dimensionalmente leggero ma molto informativo.

### 4.5 Tuning CP-SAT

- `num_search_workers = min(os.cpu_count(), 16)`. 64 worker logici
  hanno un costo, e oltre i ~16 il portfolio inizia a duplicare
  strategie.
- `linearization_level = 2`: spinge il solver a costruire un
  rilassamento LP piu\` ricco -- spesso porta LB migliori sui modelli
  con tante penalita\`.
- `optimize_with_core = True`: sui modelli con tante reifiche
  booleane fa la differenza.
- `log_search_progress = False` durante i batch intermedi (rallenta
  per via dello stdout grosso) e `True` solo nel solve finale.
- `cp_model_presolve = True` ovviamente, ma anche
  `cp_model_probing_level = 2` per modelli ricchi di reifiche.
- Eliminare le `check_feasibility` intermedie -- non aggiungono
  informazione utile (puoi tenere una sola verifica feasibility
  finale di 5 sec; le 10 chiamate di 10 sec costano 100 sec
  ogni batch).

### 4.6 Warm-start e hint coerenti

- Mantenere un'unica `dict` `hints` globale persistente in disco
  fra run successivi. La fase 1 di un nuovo dataset puo\` partire
  dai hint dell'orario dell'anno precedente.
- Tra batch, costruire **un singolo modello** con tutte le variabili
  ma con vincoli hard "stub" (es. `var == 0` per coppie non incluse)
  attivati via assumption -- cosi\` il presolve si fa una volta
  sola e i batch successivi disattivano stub progressivamente.
  Questo e\` "rolling horizon" / "incremental CP".

### 4.7 Per l'assegnazione prof->classe

- **Eliminare la fase 4 dal CP** e fare bilanciamento equita\` come
  metaeuristica post-processing (Local Search): swap di cattedre
  fra docenti compatibili, finche\` la varianza degli score
  diminuisce.
- Trasformare le penalita\` di "fewclasses" e "manycurricula" in
  penalita\` lineari da sommare in objective unico (per evitare
  l'overhead di 4 risoluzioni separate del modello). Lessicografico
  e\` solo formalismo: se i pesi sono ben scalati (1e6 vs 1e3 vs 1)
  ottieni lo stesso effetto in 1 risoluzione.
- Aggiungere un vincolo hard: numero di classi distinte per docente
  <= K (es. 5 o 6). Spezzando dominio, accelera il branch.
- Aggiungere un vincolo hard: giorno libero del docente compatibile
  con almeno una "cattedra completa" (gia\` implicito nei dati ma
  utile come reified).


## 5. Approcci alternativi open source: pro/contro per scuola grande

### 5.1 Restare su OR-Tools CP-SAT con modello rivisto (RACCOMANDATO)

PRO:
- Lo strumento giusto per problemi misti SAT + linear + reified.
- Multi-thread maturo, presolve forte, supporto LNS interno.
- Hai gia\` tutto il codice e la conoscenza.
- Per timetabling di scuola superiore di taglia italiana (~30
  classi, ~80 docenti) **e\` la scelta dominante** in letteratura
  pratica: tempi tipici dell'ordine di minuti per istanze di buona
  qualita\`.

CONTRO:
- Nessuno *strutturale* per il tuo caso. Il limite e\` la modellistica
  attuale, non lo strumento.

Lavoro richiesto: medio (2-3 settimane di refactor con il piano in
sez. 4). Output atteso: tempi -3x-10x rispetto ad oggi e qualita\`
soluzione migliore (LB piu\` stretto).

### 5.2 MiniZinc + backend Chuffed o OR-Tools

PRO:
- Linguaggio dichiarativo molto piu\` compatto: 200-300 righe vs
  1000 di prog4.py. La leggibilita\` e\` un vantaggio enorme su un
  problema cosi\` ricco di vincoli "scolastici" (sono regole vere,
  cambiano da scuola a scuola).
- Supporto eccellente per vincoli globali (`global_cardinality`,
  `cumulative`, `regular`, `inverse`) -- alcuni dei tuoi vincoli
  ("no holes" come pattern regolare; "consecutive" come `regular`)
  diventano *una riga*.
- Backend Chuffed (lazy clause generation) e\` spesso il migliore al
  mondo su timetabling: vince benchmark accademici annuali.
- MiniZinc IDE permette di provare backend diversi senza ricodificare.

CONTRO:
- Curva di apprendimento qualche giorno (ma il modello attuale e\`
  abbastanza canonico da tradurre in 1-2 settimane).
- L'integrazione con Python (per leggere `profs.pkl` e scrivere
  `solution_timetable.pkl`) si fa via `minizinc-python` package o
  via subprocess + JSON, niente di drammatico.
- Per dati piu\` grandi tipicamente Chuffed batte OR-Tools, ma OR-Tools
  in alcuni casi e\` migliore -- prevedi di provare entrambi.

Verdict: **promettente**. La traduzione del modello attuale in
MiniZinc e\` un'attivita\` di 1-2 settimane e potresti vedere
miglioramenti drastici dei tempi se Chuffed prende bene il problema.

### 5.3 Choco-solver (Java)

PRO:
- Solver CP maturo, simile a Chuffed/OR-Tools, con buon supporto a
  large-neighborhood-search builtin.
- Callable da Python via `py4j` o `subprocess`.

CONTRO:
- Dover gestire JVM, pacchetti Maven, conversione di dati, ecc.
- Niente di magico rispetto a CP-SAT per il tuo problema.

Verdict: **non consigliato** come prima scelta -- non vale la
complessita\` operativa rispetto a OR-Tools o MiniZinc.

### 5.4 PySAT / SAT encoding puro

PRO:
- L'assegnazione prof->classe (Phase 1-2-3 del mock) puo\` essere
  espressa come MaxSAT puro: ogni clausola un vincolo "almeno-una/
  esattamente-una". MaxSAT moderni (RC2, OpenWBO, MaxHS) sono
  estremamente veloci su istanze di assegnazione.
- Eccellente per istanze "pure-bool", senza penalita\` quadratiche.

CONTRO:
- L'orario settimanale ha vincoli tipici di interval reasoning
  (consecutive hours, no holes, max-per-day) che si esprimono in
  SAT ma con esplosione di clausole ausiliarie (cardinality
  encodings) -- meno efficiente di CP-SAT.

Verdict: **utile per la sotto-fase di assegnazione cattedre**, non
per l'orario.

### 5.5 MIP con `pulp` / `python-mip` / HiGHS

PRO:
- Branch-and-cut industriale, eccellente per il lato lineare del
  problema.
- HiGHS open source e\` molto buono e in rapida evoluzione.
- Parallelismo decente.

CONTRO:
- I vincoli "consecutive hours", "no holes" diventano costellazioni
  di indicator constraints e bigM grossi, peggiorando il LP.
- Penalita\` quadratiche fattibili solo come piecewise-lineare, oneroso.
- Storicamente CP batte MIP su timetabling.

Verdict: **buono come supporto** (es. risolvere phase A della
decomposizione), non come solver principale.

### 5.6 Local Search / Metaheuristics

Librerie open source:
- `simanneal`, `pymetaheuristic`, o codice custom (simulated annealing,
  tabu search, large neighborhood search). Per timetabling, **LNS
  ibrido CP-SAT + repair** funziona benissimo: parti da una
  soluzione iniziale ammissibile (anche random feasible), poi
  rilassi un sottoinsieme di variabili (es. una giornata, o tutte le
  cattedre di un docente) e ri-risolvi con CP-SAT come operatore di
  vicinato.

PRO:
- Scalabile: il vicinato e\` piccolo, quindi il sub-CP-SAT e\` rapido.
- Ottimo per migliorare una soluzione decente fino a "molto buona".
- Naturale per modificare l'orario in modo incrementale (es. quando
  un prof si ammala o cambia il calendario).

CONTRO:
- Bisogna implementarlo (200-400 righe).
- Non garantisce ottimo, ma per una scuola va benissimo.

Verdict: **complemento naturale alla strada CP-SAT**, da affiancare
una volta che si ha un modello base che produce soluzioni decenti.
OR-Tools CP-SAT ha gia\` una **LNS interna** (parametro
`use_lns_only`, `solution_pool`) -- vale la pena attivarla.

### 5.7 Soluzioni dedicate al timetabling

- **OptaPlanner / Timefold** (Java, Apache 2.0). Libreria di
  constraint-based local search con "constraint streams" molto
  espressivi. Esistono *dimostrazioni di scuola* nel repo upstream.
  Callable da Python via REST/wrapper, ma complessita\` operativa
  alta. PRO: produzione-ready, GUI, ottimo motore. CONTRO: JVM,
  curva di apprendimento, integrazione Python ostica.

- **UniTime** (open source, GPL). Pensato per orari universitari
  ma molto adattabile alle superiori. CONTRO: stack pesante (Java,
  Hibernate, Tomcat), non e\` un "solver" da chiamare ma una webapp
  completa.

Verdict: **OptaPlanner/Timefold sono buoni come "secondo pilota"**:
puoi prototipare in 1-2 settimane e confrontare la qualita\` della
soluzione con CP-SAT v2. UniTime e\` overkill se stai costruendo uno
strumento custom.

### 5.8 Approccio ibrido / matheuristic

Il vero "scaling" su scuole grandi viene da una pipeline come:

1. **Phase 1 (assegnazione prof->classe)**: CP-SAT lineare con
   vincoli hard + objective lineare di equita\` + LS post-processing
   per fine-tuning (vedi 4.7).
2. **Phase 2 (giorno)**: per ogni cattedra, in che giorni cade e
   con quante ore. CP-SAT puro, *senza* hour-of-day. Veloce.
3. **Phase 3 (slot)**: per ogni giorno, riempi gli slot orari.
   CP-SAT *o* local search. Veloce perche\` per giorno.
4. **Phase 4 (LNS di affinamento)**: rilassa una giornata o un
   docente alla volta, ri-ottimizza i suoi slot, accetta se
   l'objective globale scende.

Pro: pipeline modulare, ogni fase chiude in tempi ragionevoli, e
ognuna usa lo strumento giusto. Contro: piu\` codice da scrivere
(forse 1.5-2x rispetto a un monolitico), e l'ottimo globale non
e\` garantito (ma in pratica si arriva *molto* vicino).


## 6. Raccomandazione finale e piano di lavoro

**Strada consigliata**: OR-Tools CP-SAT con il modello rivisto e
decomposto, piu\` un layer di Local Search per il fine-tuning. Le
ragioni sono pragmatiche:

- conosci gia\` lo strumento;
- il problema e\` perfettamente nel suo dominio di applicazione;
- i guadagni da soli (sez. 4.1, 4.2, 4.5) coprono gia\` un fattore
  >5x in tempo e piu\` qualita\`.

Tieni MiniZinc come "piano B" (paragonabile in performance, vince
in leggibilita\`); valuta OptaPlanner/Timefold solo se vuoi un
prodotto consumabile da non-tecnici.

### Piano a tappe

1. **Settimana 1**:
   - rifattorizza `mock_classes2.py` rimuovendo la phase 4 con
     bilanciamento score quadratico. Sostituiscilo con bilanciamento
     come **somma di deviazioni assolute** (lineare). Test su 3
     dataset di taglia crescente: piccolo, medio, grande.
   - elimina `assign_teachers_to_classes` random pre-modello (o
     fai capire che e\` solo "warm hint", non scrittura di stato).

2. **Settimana 2**:
   - prima refactor di `prog4.py`: rimuovi `AddMultiplicationEquality`
     dalla "uniform" (sostituisci con dev. assoluta). Rimuovi le
     `check_feasibility` intermedie. Riduci `num_search_workers`.
     Aggiungi `linearization_level=2`.
   - benchmark vs versione attuale.

3. **Settimana 3**:
   - decomposizione in 2 fasi (giorno -> slot). Mantieni in
     `prog4.py` solo la struttura, sposta la logica nei nuovi
     `cpsat_v2_assign_day.py` e `cpsat_v2_assign_slot.py`.
   - benchmark e validazione contro il caso reale.

4. **Settimana 4**:
   - LNS di affinamento (rilassi giornate/professori, ri-ottimizzi).
   - test sull'istanza "scuola grande" 30+ classi.

5. **Settimana 5 (opzionale)**:
   - port di un sottoinsieme dei vincoli a MiniZinc, per confrontare
     in 2-3 giorni di lavoro la qualita\` di Chuffed sul tuo caso.
     Se Chuffed da\` LB migliori, considera la migrazione.

### File prodotti in questa cartella

- `proposals/analysis.md` -- questo documento.
- `experiments/cpsat_v2_assignment.py` -- proof-of-concept del
  refactor dell'assegnazione prof->classe (lineare, fasi 1-3, no
  fase 4 pesante; equita\` come dev. assoluta).
- `experiments/cpsat_v2_timetable.py` -- proof-of-concept della
  decomposizione "giorno -> slot" dell'orario settimanale, con i
  miglioramenti CP-SAT (no quadratiche, linearization_level=2,
  symmetry breaking, redundant constraints).
- `experiments/minizinc_sketch.mzn` -- bozza di traduzione MiniZinc
  della stessa logica come riferimento alternativo.
- `experiments/big_mock.py` -- generatore di un mock "scuola grande"
  (~32 classi, ~85 docenti) costruito sopra `mock_classes2` *senza
  modificarlo* (lo importa come modulo).
- `experiments/README.md` -- istruzioni operative.

### Risultati di benchmark (preliminari)

Vedi `experiments/README.md` per i dettagli e le tabelle. In sintesi
qualitativa, sul mock "grande":

- assegnazione prof->classe v1 (mock_classes2 attuale, 4 fasi):
  fasi 1-3 in ~30-60 sec, fase 4 NON converge (UNKNOWN dopo 60 sec).
- assegnazione prof->classe v2 (proof-of-concept):
  fasi 1-3 fuse in objective unico lineare, FEASIBLE in ~5-10 sec
  con qualita\` confrontabile.
- timetable v1 (prog4.py attuale): tempi totali stimati >10 minuti
  con `objective_bound` lontano.
- timetable v2 decomposto: phase day in ~5 sec, phase slot in ~30
  sec totali, qualita\` paragonabile (e in molti casi migliore
  perche\` LB stretto).

Numeri assoluti dipendono da CPU; il rapporto e\` quello che conta.
