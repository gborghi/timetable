# Guida UI

La nav bar elenca tutte le sezioni; ognuna e' una route SvelteKit in
`webui/frontend/src/routes/`. Tutte le pagine "lista" condividono il
componente `SortableQueryableList` con DSL di filtro/ordinamento (vedere
sotto e [api.md](api.md) per i campi disponibili).

## Funzionalita' trasversali

### Query DSL e sort multi-livello

Ogni pagina lista ha:

- una barra **Query** che accetta espressioni come
  `group=A026 AND max_hours>=18`, `cognome startswith Ross`,
  `unavailable_on(martedi)`. Operatori: `= != < <= > >= contains
  startswith endswith in [...]`. Logica: `AND / OR / ()`. Funzioni
  per-entita' come `unavailable_on(day)`.
- **Sort multi-livello** (max 4 livelli): doppio-click sull'etichetta
  di una colonna per aggiungerla; click sulla freccia per invertire
  direzione; bottone "Reset sort" per pulire.
- Un pannello "Help" con la lista dei campi disponibili e qualche
  esempio.

I campi DSL per ogni entita' sono definiti in
`webui/backend/utils/list_query.py`.

### Multi-select con shift / ctrl

Sulle pagine `Docenti`, `Classi`, `Aule` la lista supporta:

- click semplice -> single-select (replace)
- Ctrl+click -> toggle
- Shift+click -> range
- "Seleziona tutto", "Deseleziona", checkbox header indeterminate

La selezione abilita il bottone "Vincolo collettivo" che apre il
`BulkApplyModal` (vedere [constraints.md](constraints.md)).

### Scorciatoie tastiera sulle matrici a colori

Su ogni matrice di celle a stati di colore (matrice disponibilita'
docenti / classi / aule, e la "ClassroomGrid" delle preferenze aula
nei modal di docenti e materie) tieni premuto un tasto e clicca per
impostare lo stato della cella **direttamente**, saltando il
click-cycle.

| Tasto | Su matrice oraria (free/soft/hard/preferred/enforced) | Su griglia aule (allowed/soft/preferred/forbidden/enforced) | Colore       |
| ----- | ---------------------------------------------------- | ----------------------------------------------------------- | ------------ |
| `H`   | HARD (non disponibile)                               | FORBIDDEN (vietata)                                         | rosso        |
| `P`   | PREFERRED (bonus)                                    | PREFERITA                                                   | blu          |
| `E`   | ENFORCED (deve essere occupata)                      | OBBLIGATORIA (deve essere quella)                           | verde scuro  |
| `D`   | SOFT positive (disliked)                             | SOFT positive                                               | giallo       |
| `A`   | FREE (libero, nessun vincolo)                        | ALLOWED (consentita)                                        | verde chiaro |
| `N`   | RESET (alias di A)                                   | RESET (alias di A)                                          | verde chiaro |

Click semplice senza tasto premuto = comportamento storico (cicla
tra gli stati nell'ordine definito dal componente).

Il modifier funziona **anche con il drag**: tieni premuto il tasto
prima di iniziare a trascinare e tutta la zona selezionata prende
quello stato.

Una **legenda compatta** appare in fondo alla matrice quando il
cursore vi entra sopra; la kbd del tasto attualmente premuto si
illumina di indaco. La legenda si nasconde quando esci dalla matrice
per non lasciare rumore visivo permanente.

Implementazione: `$lib/keyboardConstraintMode.ts` espone uno store
`heldKey` aggiornato da listener `keydown`/`keyup` ref-counted (una
sola coppia di listener globali anche se piu' matrici sono visibili
contemporaneamente). `$lib/components/KeyboardConstraintLegend.svelte`
e' il componente visivo.

### Excel/CSV import

Ogni pagina lista (Docenti, Classi, Materie, Aule, Indirizzi,
Studenti, Gruppi) ha un bottone "Importa Excel/CSV" + "Template".
Lo stesso endpoint `POST /api/import/{entity}` gestisce le 7 entita';
il template `GET /api/import/{entity}/template` scarica un .xlsx con
gli header attesi e una riga d'esempio. Modalita': `upsert`
(default), `append`, `replace`. Header alias italiani e inglesi
accettati. Vedere `webui/docs/import_format.md` per la specifica
completa.

## Tab per tab

### Dashboard (`/`)

Punto di partenza. Tre card:

1. **Importa profilo** -- combo `small` / `medium` / `big` / `huge` /
   `superhuge` + 3 checkbox per i pool aggiuntivi:
   - Indirizzi (curricula): seed + linkaggio classi
   - Aule: una per classe + lab/palestre/biblioteca proporzionali
   - Studenti: ~22 per classe (Faker, deterministico)
   + bottone "Rigenera solo aule" per la recipe di default.
2. **Genera scuola di test** -- mock dataset on-the-fly con
   `MockGenIn`: profilo, mode (`aggregated` / `tight` / `legacy`),
   `margin`, `base_max_hours`, opzionale `custom_curricula`.
3. **Stato corrente** -- 7 card-numero (Classi, Docenti, Materie,
   Aule, Studenti, Cattedre, Soluzioni) + info sulla soluzione
   attiva.

In basso il `RunLogPanel` streama via SSE i log dell'ultimo run.

#### Grafo della scuola (toggleable)

Sotto allo stato corrente c'e' una sezione "Grafo della scuola" con
bottone "Visualizza grafo" che espande/collassa un canvas Cytoscape.js
con layout force-directed (fcose). Due modalita' selezionabili tramite
segmented control:

- **Classi (nodi)**: ogni classe (es. "1A", "3B") e' un nodo;
  due classi sono collegate da un arco se condividono almeno un
  docente. Lo spessore dell'arco e' proporzionale al numero di docenti
  in comune (1 docente = sottile, 6+ = spesso). Tooltip al hover su
  un arco: lista dei docenti condivisi. Tooltip su un nodo:
  classe + indirizzo + lista completa docenti.
  *Utilita'*: vedere a colpo d'occhio quali classi sono "vicine"
  nel senso di condivisione di personale; identificare il nucleo di
  classi che condividono molti docenti (cluster naturali) e quali
  sono periferiche.

- **Docenti (nodi)**: ogni docente e' un nodo (etichetta:
  cognome + iniziale del nome); due docenti sono collegati se
  insegnano in almeno una classe in comune. Spessore = numero di
  classi condivise. Tooltip arco: lista classi in comune.
  Tooltip nodo: nome + materie + lista classi insegnate.
  *Utilita'*: visualizzare la rete del corpo docente, identificare
  i docenti "ponte" (highly-connected, insegnano in molte classi
  diverse) che sono fattori critici per la decomposizione spettrale.

I dati arrivano da `GET /api/dashboard/graph?mode=classes|teachers`.
La risposta e' cached server-side per 60s (TTL cache della Section
2.4 P1) e invalidata automaticamente da ogni mutazione (assignment,
docenti, classi). Lato client TanStack Query la riusa per tutta la
sessione.

Pan, zoom (rotellina) e drag-to-reposition dei nodi sono
supportati. La palette segue il branding piTantum: nodi indaco in
modalita' classi, nodi oro in modalita' docenti, archi terra di
Siena con opacita' 55% (scure quando hovered).

Performance: per il profilo `superhuge` (~80 classi / ~159 docenti)
il payload completo e' nell'ordine di 10-20KB; il rendering iniziale
con fcose e' ~1-2s, poi il grafo e' interattivo a 60fps.

### Docenti (`/teachers`)

CRUD docenti. Il modal di edit ha:

- input separati Cognome / Nome + Nickname (placeholder = "Cognome
  Nome"). Il `name` canonico e' calcolato automaticamente da
  `last_name + first_name` in `syncName()`.
- Matricola, Classe di concorso, Max ore-cattedra, Ore di
  completamento / esonero
- **Punteggio graduatoria** (opzionale, range tipico 0-300):
  punteggio in graduatoria provinciale del docente. Usato dal preset
  Phase-A "Anzianita' -> indirizzi pesanti" (vedere
  [objective_dsl.md](objective_dsl.md)).
- Giorno libero (select) + Max ore consecutive
- Materie insegnate (select multipla, scrolla nel `<select multiple>`
  con la lista globale delle materie)
- AvailabilityMatrix 5-stati per il docente (vedere
  [constraints.md](constraints.md))
- ClassroomGrid 5-stati per assegnare aule preferred / forbidden /
  enforced specifiche al docente
- LogicalUnavailabilitiesPanel per i vincoli logici DNF

#### Preferenze per Phase A (classi + indirizzi)

Sotto i pannelli sopra, separato da una riga di intestazione, c'e'
un blocco dedicato alle preferenze del docente per Phase A
(assegnazione docente -> classe). Sono SOLO per Phase A: l'orario
settimanale (Phase B) NON guarda questi vincoli.

Due grid 5-stati (riusano `EntityPreferenceGrid`, lo stesso
componente collassabile usato altrove):

- **Classi**: una casella per ogni classe della scuola. Stati:
  ALLOWED (default verde chiaro), DISLIKED giallo (soft penalty
  positiva, modificabile inline), PREFERRED blu (peso negativo),
  FORBIDDEN rosso (HARD: il docente NON puo' essere assegnato a
  quella classe), ENFORCED verde scuro (HARD: il docente DEVE
  insegnare in quella classe).
- **Indirizzi**: una casella per ogni curriculum (`Scientifico`,
  `Classico`, ...). Vincoli a livello di indirizzo: HARD su un
  indirizzo significa "questo docente non puo' essere assegnato
  a NESSUNA classe di quell'indirizzo".

Click cicla; le scorciatoie tastiera del progetto (`H`/`P`/`E`/`D`/
`A`/`N` + click) funzionano anche qui (vedere "Scorciatoie tastiera
sulle matrici a colori" sopra).

Le preferenze vengono salvate via due endpoint dedicati
(`PUT /api/teachers/{id}/class-preferences` e
`/curriculum-preferences`) chiamati AUTOMATICAMENTE dopo il PUT
principale del docente. Non serve fare nulla a parte premere
"Salva" sul modal.

### Classi (`/classes`)

CRUD classi. Modal di edit:

- Nome, Nickname (mostrato nell'orario), Anno, Sezione, Indirizzo
  (dropdown da `/api/curricula`) + bottone "Importa griglia" che
  popola la lista materie con il monte-ore dell'indirizzo per
  l'anno selezionato
- N. studenti, Note
- 7 toggle HARD (vedere [constraints.md](constraints.md))
- Peso minimizzazione 6a ora (SOFT)
- Tabella materie+ore con autocomplete sulle materie note
- AvailabilityMatrix 5-stati
- LogicalUnavailabilitiesPanel

### Indirizzi (`/curricula`)

CRUD indirizzi. Il modal ha due tab interne:

1. **Materie e ore per anno** -- selettore anno 1..5, tabella materie+ore
   per quell'anno; tot ore dell'anno mostrato in alto.
2. **Vincoli logici per anno** -- LogicalUnavailabilitiesPanel-like ma
   con un campo extra `year_filter` (NULL = tutti gli anni).

### Studenti (`/students`)

CRUD studenti. Modal: cognome, nome, nickname (default "Cognome
Nome"), data nascita, sesso, email, matricola, classe (dropdown),
note.

### Gruppi (`/groups`)

Type-C: gruppi articolati che possono pescare studenti da piu'
classi. Modal:

- Nome, nickname, Tipo (splitting / language / religion / support /
  other), descrizione
- Lista studenti del gruppo con filtro testuale (cognome / nome /
  classe / matricola); checkbox per ogni studente
- Tabella materie+ore del gruppo (autocomplete su materie note)

### Materie (`/subjects`)

CRUD materie. Modal:

- Nome (chiave), pretty_name, Note
- Pesi SOFT: distribute_days_weight, dual_hours_weight,
  no_sixth_hour_weight, fascia oraria preferita (start / end / weight)
- ClassroomGrid 5-stati per assegnare aule preferred / forbidden /
  enforced specifiche alla materia (es. Chimica enforced in lab_chimica)

Vista alternativa "Pesi cl. concorso" che gestisce
`subject_group_weights` (mapping subject -> classe-di-concorso ->
weight).

### Aule (`/classrooms`)

CRUD aule. Bottone "Genera aule" che lancia la recipe in
`mock_classrooms.py` (proporzionale alla scuola: 1 standard per
classe + N lab / palestre / biblioteche / aule speciali).

Modal:

- Nome / codice, Tipo (8 kinds), Capienza, Note
- Multi-class flag + multi_class_max + multi_class_pref +
  multi_class_pref_weight
- AvailabilityMatrix 5-stati
- Subject preferences (peso per materia, required toggle)
- Class preferences (home flag)
- LogicalUnavailabilitiesPanel

### Compresenze (`/coteaching`)

CRUD `coteaching_rules`. Per ogni `(class, subject)` definisce N
docenti contemporanei, `required` (HARD/SOFT), peso, lista esplicita
opzionale.

### Cattedre (`/assignments`)

Layout a card: una card per classe, lista materie+docente+ore.
Bottone "cambia" per ogni riga apre un modal:

- Docente: **dropdown filtrato per materia** (chiama
  `GET /api/assignments/teachers-for-subject?subject=X`). Ogni
  opzione mostra `Cognome Nome - assigned/max [SFORA: +Xh]` /
  `[pieno]` calcolato sulla mossa proposta.
- Lock: checkbox per impedire all'ottimizzatore di cambiare la cattedra.

In alto il bottone "Warnings cattedre" apre un pannello toggleable
che lista i docenti con coverage gap: SFORA il max (rosso), ore
mancanti (ambra), nessuna cattedra (ambra), ok (verde). Filtro
"solo problemi" / "tutti".

### Orario (`/schedule`)

Vista delle lezioni. Toggle in alto fra 4 viste, ognuna con sotto-toggle
matrice / lista:

- **per classe** -- selettore classe + matrice 6x6 (default) o tabella
  lista (1 riga per classe x 36 colonne slot)
- **per docente** -- analogo
- **per aula** -- selettore aula + matrice 6x6 (default) o tabella
  lista (l'esistente). Multi-occupancy (2+ lezioni nello stesso slot)
  evidenziata in rosso pallido.
- **per slot** -- form day + hour, lista lezioni in quello slot.

Nelle matrici classi/docenti ogni cella ha un dropdown aula con
coloring verde (libera) / rosso (occupata, disabled) /
grigio (nessuna). Drag-and-drop con preview live: trascina una
lezione su un altro slot, gli altri si colorano per mostrare
fattibilita' / delta SOFT (vedere [workflow.md](workflow.md)).

Bottoni di export in alto: xlsx classi, xlsx docenti, pdf classi,
pdf docenti.

In fondo: lista delle soluzioni salvate con bottone "attiva" e
"elimina".

### Assenze e supplenze (`/assenze-supplenze`)

Vista settimanale. In alto: date picker per la settimana
(default lunedi corrente) + bottoni "settimana prec.", "settimana
succ.", "oggi".

Tabella 6 colonne giorno x 6 righe ora. Le celle si colorano:

- bianco/grigio: niente assenze
- ambra: assenze ma nessuna ora persa
- rosso: ore scoperte
- verde: ore scoperte ma tutte coperte da supplenti

Click sull'**intestazione di un giorno** apre il modal "Assenze"
dove si selezionano i docenti assenti (con filtro testuale) e i
loro motivi. C'e' un bottone "Clear" sia inline nell'intestazione
sia nel modal che cancella TUTTE le assenze e le supplenze del giorno.

Click su una **cella** apre il modal cella: a sinistra le classi
scoperte (rosse o verdi se gia' coperte); a destra i docenti
disponibili (esclusi: assenti oggi, in giorno libero, gia'
impegnati, gia' usati come supplenti). Drag-and-drop di un docente
su una classe scoperta crea la supplenza. Quando tutte le scoperte
sono coperte, il bottone "Salva e chiudi" e' abilitato; chiudere
con scoperte residue chiede conferma.

### Monitor (`/monitor`)

Lista degli **eventi** a granularita' di lezione (un row per Lesson +
una placeholder row per ogni "ora mancante" di una cattedra). La
tabella e' identica per UX a docenti/classi/aule (vedere `Tab dati
master`): colonna ordinabile con doppio click sul nome (max 3
livelli), pill di sort, query DSL con Cerca/Reset, due dropdown di
raggruppamento + Toggle/Untoggle all per i nesting collapsibili.

#### Tabs in cima (segmented control)

Tre tab filtrano cosa mostrare; ognuno ANDed nella query DSL come
auxQuery, mentre la query digitata dall'utente resta separata e
filtra ulteriormente:

- **Tutti**: tutti gli eventi (placeholder + lezioni schedulate)
- **Incompleti** (rosso): equivalente a `completo = 0`
- **🔒 Lockati** (ambra): equivalente a `is_locked = 1`

Ogni tab mostra un count pill accanto al nome
(n_rows / n_rows_unscheduled / n_rows_locked dal `/api/monitor/summary`).

#### Azioni per riga

Cinque bottoni per ogni riga, modulati dallo stato:

- **Modifica** (default): per lezioni schedulate apre lo slot picker
  6x6; per placeholder apre AddLessonModal pre-fillato per
  schedulare quell'ora.
- **Dissocia** (amber): rimuove TUTTE le lezioni della cattedra
  preservando l'`Assignment`. La cattedra ritorna 'incomplete' con
  tutte le ore da riassegnare. Endpoint:
  `POST /api/monitor/event/{aid}/dissociate`.
- **🔒 Blocca / 🔓 Sblocca** (toggle): marca/smarca
  `Assignment.locked`. Una riga lockata mostra il lucchetto +
  bordo sinistro ambra. Le run successive di Phase B / metaeuristiche
  prendono uno snapshot delle lezioni lockate e le ripristinano
  alla fine, evictando eventuali lezioni che il solver ha messo
  negli stessi slot (post-hoc enforcement, non CP-SAT-nativo).
  Endpoint: `POST /api/monitor/event/{aid}/lock` body `{locked: bool}`.
- **Piazza** (primario): apre `PlaceEventModal` per piazzare le ore
  mancanti dell'evento (greedy HARD-feasible). Tre lock_mode:
  - `all_others_locked` (default): tutte le altre lezioni sono
    fisse; il placer fitta solo gli slot vuoti rimasti.
  - `same_class_or_teacher_movable`: le lezioni della classe o del
    docente coinvolti sono evictabili; il resto e' fisso.
  - `all_others_movable`: il placer puo' evictare qualunque lezione.
  Streaming del log via SSE come negli altri run del Workflow.
  Endpoint: `POST /api/optimize/place-event`.
- **Elimina** (rosso): elimina la riga (lesson) o l'intera cattedra
  (placeholder).

#### Multi-selezione + toolbar bulk

Checkbox in cima alla tabella + per riga (selectable=true). Quando
1+ righe sono selezionate compaiono nella toolbar:

- **Seleziona tutto / Deseleziona**
- **Dissocia selezionati** -> `/events/dissociate-batch`
- **Blocca selezionati** -> `/events/lock-batch` con toggle smart:
  se almeno una e' sbloccata blocca tutto, altrimenti sblocca tutto.
- **Piazza selezionati** -> apre `PlaceEventModal` per il set intero;
  il lock_mode si applica al set ("le altre" = tutto cio' che non
  e' selezionato).
- **Elimina selezionati** (rosso) -> conferma unica, batch DELETE.

#### Vincoli vs preserve

`Dissocia` rimuove le lezioni; `Blocca` le pinna; `Piazza` ricalcola
quelle mancanti. La combinazione tipica e' "Dissocia X -> click
Piazza con lock_mode=altri-lockati": tutti gli slot di X vengono
ricollocati senza toccare il resto della scuola (sub-secondi su
small/medium).

### Vincoli (`/constraints`)

Lista piatta di tutti i vincoli editabili: matrici di disponibilita',
vincoli logici (teacher/class/room/curriculum), preferenze
materia-aula e docente-aula non default, regole di compresenza.

#### Creazione di un nuovo vincolo (wizard)

In cima alla pagina, il bottone **`+ Nuovo vincolo`** apre un modal a
4 step che guida la creazione di qualunque tipo di vincolo
supportato dal modello dati, senza dover saltare fra le pagine
master di docente/classe/aula:

1. **Categoria + entita'**. Dropdown con scope `Docente`, `Classe`,
   `Aula`, `Indirizzo / Curriculum`, `Materia + Aula (preferenza)`,
   `Docente + Aula (preferenza)`. Per ognuno appare il select
   dell'entita' corrispondente (con search-friendly autosort).
2. **Livello**: radio fra HARD / SOFT (DISLIKED) / PREFERITO /
   ENFORCED / ALLOWED / FORBIDDEN, con codice colore standard. Il
   campo `peso` appare solo per SOFT e PREFERITO; per PREFERITO
   il valore viene negato automaticamente lato backend.
3. **Tipo di vincolo (kind)**, dipendente dallo scope:
   - `matrix_slot`: cella (giorno, ora) singola nella matrice di
     disponibilita'.
   - `logical`: espressione DNF in stile `(lun8 AND lun9) OR
     (mar8 AND mar9)`. Disponibile per docente / classe / aula /
     indirizzo (con `year_filter` opzionale).
   - `room_pref`: preferenza materia-aula o docente-aula (livello
     allowed / soft / preferred / forbidden / enforced).
   - `coteach`: compresenza per (classe, materia) con N >= 2 docenti
     (solo per scope `class`).
4. **Anteprima e conferma**: riepilogo in linguaggio naturale (es.
   "Docente Borghi: cella Mar 8:00 marcata 🟥 HARD"), payload tecnico
   esposto in un `<details>` per ispezione, e bottone "Crea vincolo"
   che POSTa al dispatcher unico `/api/constraints`. Dopo successo
   compare un banner di conferma + link "Crea un altro" per
   inserire vincoli a raffica senza chiudere/riaprire il modal.

Il modal usa **una sola route backend** (`POST /api/constraints`)
che dispatcha al modello giusto in base a `(scope, kind)` -- la
tabella `Vincoli` viene refresh-ata automaticamente al successo.

**Validazione progressiva**: il bottone "Avanti" e' disabilitato
finche' lo step non e' valido (es. `subject_room` richiede sia
l'aula sia la materia; `coteach` richiede n_teachers >= 2). I
livelli mostrati allo step 2 sono filtrati in base al kind dello
step 3 (le `room_pref` non accettano HARD ma `forbidden`/`allowed`).

Pill colorate per livello (HARD rosso / SOFT giallo / PREFERITO blu /
ENFORCED verde scuro / ALLOWED verde chiaro / FORBIDDEN rosso). Per
ogni riga: bottoni Modifica (modal con livello + peso + espressione
per i logici) e Elimina (DELETE generico).

In alto il bottone "Cerca conflitti" che chiama
`/api/monitor/conflicts` e apre un pannello toggleable con i
conflitti trovati (matrix HARD+ENFORCED, ENFORCED in giorno libero,
logical HARD/ENFORCED unsatisfiable). Ogni conflitto mostra il
`reason` umano e i vincoli coinvolti (con le loro pill colorate).

### Workflow (`/optimize`)

Lancia le 4 fasi di ottimizzazione (vedere [workflow.md](workflow.md)):

1. Phase A: Assegnazione docenti -> classi
2. Phase B: Scheduling con/senza decomposizione
3. Cascata metaeuristica (LNS / SA / TS / ILS) o lanci individuali
4. Assegnazione aule

Pulsante "Pipeline completa" che le incatena. Per ogni run, log
in tempo reale via Server-Sent Events; obiettivo + metriche
mostrati alla fine.
