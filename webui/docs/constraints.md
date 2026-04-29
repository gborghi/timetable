# Vincoli HARD e SOFT supportati dal webui

Questo documento elenca tutti i vincoli che la UI espone, distinguendo
fra HARD (la soluzione DEVE rispettarli) e SOFT (penalizzati nell'obiettivo).
I pesi sono valori interi - alzando un peso si "compra" piu\` ottimizzazione
su quella metrica a discapito delle altre.


## Domino docenti (`/teachers`)

### HARD
- Indisponibilita\` per slot (giorno, ora). Validato in fase di drag-and-drop.
- Giorni liberi obbligatori (per docenti part-time).
- Max ore consecutive in un giorno (default 5).
- Abilitazione (lista materie insegnate).
- Compatibilita\` con classi (lista bianca, opzionale).

### SOFT (pesi per docente)
- `pref_no_buchi_weight` (default 10) - penalita\` per ogni buco intra-giornata.
- `pref_no_five_weight`  (default 30) - penalita\` per giornate da 5 ore.
- `pref_no_one_weight`   (default 80) - penalita\` per giornate isolate da 1 ora.
- `preferred_days_csv`   - elenco giorni preferiti (peso fisso, se non rispettato).


## Domino classi (`/classes`)

### HARD (toggle individuali per classe)
- Ingresso obbligatorio alle 8:00.
- Uscita non prima delle 12:00.
- No buchi intra-giornata.
- Doppia ora consecutiva di Matematica (almeno una nella settimana).
- Doppia ora consecutiva di Italiano.
- Sc. motorie sempre a coppie consecutive.
- Max 6 ore al giorno.

### SOFT
- `soft_minimize_sixth_weight` (default 50) - penalita\` per ogni 6^a ora occupata.


## Domino materie (`/subjects`)

### SOFT (per materia)
- `distribute_days_weight`   - premia distribuzione su piu\` giorni.
- `dual_hours_weight`        - premia doppie ore consecutive.
- `no_sixth_hour_weight`     - penalizza piazzamento alla 6^a.
- `preferred_band_start/end/weight` - fascia oraria preferita (premiata).


## Domino aule (`/classrooms`)

### HARD
- Indisponibilita\` per slot.
- `subject_required` (su subject_prefs.required) - se l'aula ha materie
  required, accetta SOLO lezioni di quelle materie (lab tipici).
- `multi_class_max` - max numero di classi simultanee (1 per aula
  standard; 2 per palestre/biblioteche multi-classe).

### SOFT
- `multi_class_pref` - concorrenza preferita; sopra di essa si paga
  `multi_class_pref_weight` per ogni classe extra.
- `subject_prefs[].weight` - bonus quando la materia preferita finisce
  in questa aula.
- `class_prefs[].weight`   - bonus quando la classe preferita finisce
  in questa aula.
- `is_home` (su class_prefs) - bonus speciale "home room": nello step
  `Assegna aule` la classe sta nella sua aula salvo lab/palestra.


## Compresenze (`/coteaching`)

### HARD
- Quando `required = true`: per quella (classe, materia), TUTTI i docenti
  elencati in `teachers` insegnano nella stessa lezione, nello stesso slot.

### SOFT
- Quando `required = false`: penalita\` `weight` se la regola non viene
  rispettata dal solver (es. se il solver vorrebbe togliere un docente
  per liberare uno slot).


## Disponibilita\` oraria a 3 stati (matrice giorno x ora)

Per docenti, classi e aule la matrice giorno x ora ha tre stati:

- **verde** (`free`): la risorsa e\` disponibile, nessun vincolo (cella
  assente dalla tabella `*_unavailability`)
- **giallo** (`soft`): la risorsa puo\` essere assegnata ma con un costo
  SOFT pari a `soft_penalty` (default 100, modificabile da popover
  shift+click)
- **rosso** (`hard`): la risorsa NON puo\` essere assegnata in quello slot

UI: click cicla `free -> soft -> hard -> free`. Drag-and-drop applica
lo stesso stato a un blocco di celle. Shift+click su una cella gialla
apre un popover per cambiarne la penalita\`.

Auto-fill: il "giorno libero" del docente compila automaticamente le
6 celle di quel giorno come HARD; e\` un alias di "riga rossa per
quel giorno", quindi le due modifiche restano sincronizzate.

Importazione: i pickle di mock generation portano `free_day` per ogni
docente; viene tradotto al volo in 6 celle HARD esposte in `GET /api/teachers`
(senza essere persistite, finche\` l'utente non salva).


## Mosse manuali (drag-and-drop)

Quando l'utente sposta una lezione da uno slot all'altro:

1. Il backend ricostruisce la soluzione candidata.
2. Esegue `metaheuristics.is_hard_feasible(...)` su tutta la soluzione:
   - no overlap classe / docente
   - coverage intatta (somma ore == ore-cattedra)
   - ingresso 8 / no buchi / uscita >= 12
   - mat/ita/motorie come da regole sopra
3. Se HARD passa, calcola `compute_soft(...)` e mostra il delta SOFT.
4. La mossa viene rifiutata con messaggio chiaro se rompe un HARD,
   accettata altrimenti.


## Pesi globali (objective)

Sono in `experiments/metaheuristics.py` (`OBJECTIVE_WEIGHTS`):
- `sixth = 50`
- `buchi = 10`
- `five  = 30`
- `one   = 80`

Modificandoli si ricalibra l'aggressivita\` delle metaeuristiche.


## Note sul perimetro

Alcuni vincoli SOFT presenti nel webui (es. fascia preferita per materia,
home-room bonus, indisponibilita\` aule) non sono ancora "incollati" al
solver CP-SAT principale; sono pero\`:
- esibiti nei form CRUD,
- enforced live nel drag-and-drop (vincoli HARD),
- e usati dal nuovo modulo `experiments/classroom_assignment.py` per la
  step di assegnazione aule.

Il piano di evoluzione e\` di passarli come termini di obiettivo al
modulo `metaheuristics` (sia LNS sia SA/TS/ILS) man mano che diventano
prioritari per i casi reali.
