# Workflow di ottimizzazione

La generazione di un orario completo passa per 4 fasi sequenziali.
La pagina **Workflow** (`/optimize`) le espone come pulsanti
indipendenti; il pulsante "Pipeline completa" le incatena in modo
seamless.

## Schema delle fasi

```
   +---------------+    +---------------+    +-----------------+    +---------------+
   |  Phase A      | -> |  Phase B      | -> |  Metaeuristiche | -> |  Aule         |
   |  assignment   |    |  scheduling   |    |  LNS+SA+TS+ILS  |    |  classroom    |
   |  CP-SAT       |    |  + decomp.    |    |                 |    |  assignment   |
   |               |    |  spettrale    |    |                 |    |  CP-SAT       |
   +---------------+    +---------------+    +-----------------+    +---------------+
       |                    |                    |                       |
       v                    v                    v                       v
   assignments          lessons               lessons                lessons.classroom
   (cattedre)           (con day, hour)       (perturbate           (con room)
                                              + migliorate)

```

## Phase A: assegnazione docenti -> classi (cattedre)

**Modulo**: `experiments/cpsat_v2_assignment.py`. **Lancio**:
`POST /api/optimize/assignment` con `{time_limit_s, workers, log}`.

Input: l'insieme di `(class, subject, hours_per_week)` letto da
`class_subjects` e/o `curriculum_subject_hours` + le abilitazioni
docente in `teacher_subjects` + la classe-di-concorso preference in
`subject_group_weights`.

Output: la tabella `assignments` (`teacher x class x subject` con
`hours`). E' un problema di covering: ogni `(class, subject)` riceve
un docente abilitato, rispettando max-hours per docente, classi-di-
concorso e le compatibility lists `teacher_compatible_classes`.

## Phase B: scheduling (orario settimanale)

**Modulo**: `experiments/cpsat_v2_timetable.py` +
`experiments/decomposition_spectral_v2.py`. **Lancio**:
`POST /api/optimize/phase-b` con i 5 budget temporali e il flag
`use_decomposition`.

Input: la tabella `assignments` + `school_classes` (con i HARD-toggles)
+ matrici di disponibilita' + vincoli logici.

Output: la tabella `lessons`, una riga per ora di lezione
`(teacher, class, subject, day, hour)` per ogni slot della settimana.

### Decomposizione spettrale

Per istanze grandi (medium e oltre), il problema CP-SAT integrale e'
intrattabile entro tempi ragionevoli. La pipeline calcola un grafo di
co-occupazione fra docenti (chi insegna nelle stesse classi crea
conflitti di slot), ne fa un'embedding spettrale via Laplaciano
normalizzato, e usa K-means su quell'embedding per partizionare in
`k` cluster loosely-coupled.

Ogni cluster diventa una sub-istanza CP-SAT independente:

```
  decomposizione (k cluster)
       |
       +--> CP-SAT cluster 1   (time_cluster s)
       +--> CP-SAT cluster 2
       +--> ...
       +--> CP-SAT cluster k
       |
       v
  bridges step (time_bridges s):
       fissa i cluster, risolve solo i bordi (lezioni che attraversano
       i confini di partizione)
       |
       v
  ricucitura (time_ricucitura s):
       full-CPSAT con tutto il problema, partendo dalla soluzione
       stitched -- fixa quasi tutto, lascia liberi solo gli slot
       sub-ottimali per fini SOFT
       |
       v
  fallback monolitico (time_mono s, opzionale):
       se la ricucitura non chiude, lancia un CP-SAT monolitico fresco
```

Vedere `proposals/analysis.md` per il rationale e
`proposals/benchmarks.md` per i tempi misurati sui 5 profili.

## Phase B+: cascata metaeuristica

**Modulo**: `experiments/metaheuristics.py`. **Lancio**:
`POST /api/optimize/{lns,sa,ts,ils}` (uno per algoritmo) o
`POST /api/optimize/full` per la cascata.

Sulla soluzione di Phase B applica ognuno di:

- **LNS** (Large Neighborhood Search) -- destroy-and-repair su
  finestre `(teacher, day)` o `(class, day)`; ogni iterazione fa
  freeze del 60-70% delle lezioni e CP-SAT-risolve il resto.
- **SA** (Simulated Annealing) -- perturbazioni single-swap accettate
  con probabilita' Metropolis a temperatura `T0` decrescente con
  fattore `alpha`.
- **TS** (Tabu Search) -- best-improvement local search con tabu
  list di mosse recenti (default size 80).
- **ILS** (Iterated Local Search) -- alterna `n_cycles` di TS con
  `kick` perturbativi (random 4-opt fra i giorni).

Ognuno migliora il SOFT score (somma pesata di: holes per teacher,
isolated 1- and 5-hour days, weekly distribution, dual-hour pairs,
no 6th hour, banded preferences su materie). Il SOFT include anche
la contribuzione delle matrici di disponibilita' SOFT/PREFERRED e
dei logical SOFT/PREFERRED (vedere
`optimization.py::availability_soft_penalty` e
`_logical_check_for_solution`).

## Phase 4: assegnazione aule

**Modulo**: `experiments/classroom_assignment.py`. **Lancio**:
`POST /api/optimize/rooms`.

Input: la tabella `lessons` (gia' temporalmente fissata) + le
classroom rules: `kind`, `capacity`, `multi_class`, `multi_class_max`,
preferenze materia<->aula, classe<->aula (home), docente<->aula.

Output: `lessons.classroom_name` popolato.

E' un MIP/CP-SAT separato perche' la fase B opera senza vincoli di
aula (semplifica il modello principale); le room HARD-unavailability
matrix e i `forbidden`/`enforced` di
`classroom_subject_preferences` entrano qui.

### Aule "PRIMA" / "DOPO" / "INSIEME" all'orario

Il passo aule e' indipendente per default: lo step 8 puo' essere
eseguito **prima** dell'orario (ad es. per fissare a mano un
sottoinsieme di assegnamenti palestra/laboratorio) oppure **dopo**
la pipeline (default).

Per risolvere aule e orario **insieme**, ciascuno degli step che
producono una soluzione (Phase B sulla card 3, e ognuna delle
metaeuristiche LNS/SA/TS/ILS sulla card 4-7) espone un toggle
**"Ottimizza aule insieme a questo step"**: quando attivo, dopo che
quello step ha persistito la nuova soluzione attiva, il backend
esegue `_apply_rooms_to_solution(sid, ...)` sulla stessa soluzione
con i parametri `rooms_time_limit_s` / `rooms_prefer_home`. Le
metriche delle aule (`rooms_assigned`, `rooms_total_lessons`,
eventualmente `rooms_error`) confluiscono nel run del passo padre.

La pipeline (card 9) NON ha un proprio toggle per le aule: presenta
invece una lista **trascinabile** (drag-and-drop) e **tickabile** dei
sei step `phase_a / phase_b / lns / sa / ts / ils`. L'utente decide
quali eseguire e in che ordine; ogni passo che entra nella pipeline
porta con se' la propria decisione su "ottimizza aule" presa sulla
relativa card. Cosi' la schedulazione monolitica orario+aula resta
fuori scope (per scalabilita' del CP-SAT), ma il toggle per-step
permette di intercalare l'assegnazione aule dove serve, senza
duplicare configurazione.

Il backend riceve `FullPipelineIn { steps: list[str], phase_b:
PhaseBRunIn, meta_optimize_rooms: bool, ... }` e dispatcha ogni
chiave in `steps` in ordine; phase_b consuma il proprio
`optimize_rooms`, le quattro metaeuristiche condividono il
`meta_optimize_rooms` (un solo toggle per la card 4-7).

## Drag-and-drop con preview live

Nel tab Orario (`/schedule`), trascinando una lezione su un altro
slot la UI fa due chiamate:

1. `POST /api/schedule/move-preview` con `lesson_id`. Il backend
   simula la mossa per **tutte** le 36 (day, hour) e per ognuna
   restituisce uno status:
   - `ok` con `delta_soft <= 0` -- mossa accettabile, eventualmente
     migliorativa (verde se delta < 0, verde chiaro se delta = 0)
   - `soft_worse` con `delta_soft > 0` -- mossa accettabile ma peggiora
     il SOFT (giallo)
   - `hard_violation` con `reason` -- vincolo HARD violato (rosso)
   - `noop` -- slot di origine
2. La griglia disegna gli slot colorati. L'utente droppa la lezione,
   la UI invia `PUT /api/schedule/move-lesson` con `(src, dst)`. Il
   backend valida e persiste.

### Room-follows-lesson

Il move-preview NON considera l'aula nel calcolo HARD: il backend
tratta l'aula come "soft constraint" per il move. Se la nuova
posizione e' compatibile con docente / classe ma l'aula attuale e'
gia' occupata o HARD-unavailable in destination, il backend:

1. Sposta la lezione.
2. Lascia l'aula libera sul nuovo slot solo se non c'e' conflitto.
3. Se c'e' conflitto, **rimuove l'aula** dalla lezione spostata e
   risponde con `room_cleared=true, cleared_room=<nome>`.
4. La UI in `/schedule` apre un Modal che spiega cosa e' successo e
   chiede di scegliere una nuova aula dal dropdown (che mostra in
   verde le aule libere e in rosso quelle occupate -- vedere
   `isRoomBusy`).

Vedere `optimization.py::validate_and_apply_move`.

## Slot picker matriciale (Monitor)

Nel tab Monitor (`/monitor`), espandendo una cattedra si vedono le
singole lezioni; cliccando il bottone Giorno/Ora si apre un modal con
una matrice 6x6 dove ogni cella e' colorata in base alla disponibilita'
del docente / classe / aula della lezione corrente:

- verde: free (docente e classe liberi)
- rosso: HARD (docente o classe gia' impegnati)
- ambra: aula occupata da un'altra lezione
- azzurro: slot attuale

Click su una cella libera fa un dry-run via
`PUT /api/monitor/event/{aid}/lesson/{lid}` con `on_conflict=dry_run`.
Se ci sono conflitti, apre un secondo Modal con 3 opzioni:

- **Annulla** -- nessun cambio.
- **Disassegna le lezioni in conflitto** -- cancella le Lesson rows in
  conflitto (riappaiono come ore mancanti nel Monitor) e applica.
- **Disassegna e ottimizza dopo** -- come sopra, ma l'utente sa che
  deve rilanciare il workflow per ricoprire le ore liberate.

Se la lezione da spostare e' **bloccata nel suo slot** (`Lesson.locked`,
il "pin" impostato da `/schedule`), lo spostamento non parte: la
risposta e' `{"ok": false, "needs_unlock": true}` e la UI chiede
conferma prima di procedere. Confermando, la lezione si sposta e
**resta sbloccata**: il pin nominava quell'ora, ed e' l'ora che e'
cambiata. Cambiare solo l'aula lasciando giorno e ora invariati non
tocca il pin e non chiede nulla. Stessa semantica del drag-and-drop di
`/schedule`.
