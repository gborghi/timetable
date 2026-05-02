# DSL generico per i vincoli

Linguaggio compatto per esprimere vincoli HARD/SOFT su qualunque
combinazione logica di predicati sul modello dei dati. Implementato
in `webui/backend/utils/general_dsl.py` (parser + AST + evaluator
post-hoc), esposto via `POST /api/constraints/general` e dal modal
"+ Nuovo vincolo DSL" del tab Vincoli.

## Grammatica BNF (informale)

```
expr        := iff_expr
iff_expr    := implies_expr ( '<=>' implies_expr )*
implies_expr:= or_expr ( '=>' or_expr )*
or_expr     := and_expr ( ('OR'|'or') and_expr )*
and_expr    := not_expr ( ('AND'|'and') not_expr )*
not_expr    := ('NOT'|'not') not_expr | atom
atom        := quant | count_expr | comparison | call
             | bool_lit | '(' expr ')'

quant       := ('forall'|'exists') ident 'in' source
                ['where' expr] ':' expr
count_expr  := 'count' ident 'in' source ['where' expr] op value

comparison  := value ( op | 'in' '[' value (',' value)* ']'
                          | 'not_in' '[' ... ']' ) value
op          := '==' | '!=' | '<' | '<=' | '>' | '>='
value       := ident ('.' ident)* | number | string
             | function_call
function_call := ident '(' [arg_list] ')'
arg_list    := arg ( ',' arg )*
arg         := ident '==' value | value     # name==value also OK
bool_lit    := 'true' | 'false'
```

Note di tokenizzazione:
- `=` da solo viene normalizzato a `==` (per friendlyness).
- Identificatori che iniziano con cifra ma contengono almeno una
  lettera (es. `1A`, `3B_scientifico`, `lun8`) sono accettati come
  IDENT (cosi' `l.class == 1A` funziona senza virgolette).
- Commenti: tutto dopo `#` fino a fine riga.

## Sorgenti (collezioni iterabili)

I quantificatori e `count` iterano su una di queste sorgenti
(`source` nel BNF):

| Sorgente      | Tipo elemento                         |
|---------------|---------------------------------------|
| `lessons`     | lezioni della soluzione attiva        |
| `assignments` | cattedre (Assignment rows)            |
| `teachers`    | docenti                               |
| `classes`     | classi                                |
| `classrooms`  | aule                                  |
| `students`    | studenti (con `tags[]` e `groups[]`)  |
| `subjects`    | materie                               |
| `curricula`   | indirizzi di studio                   |
| `groups`      | gruppi articolati                     |
| `slots`       | tutte le 36 (day, hour) della settimana |
| `days`        | i 6 giorni (Lun..Sab)                 |
| `hours`       | le 6 ore (8..13)                      |

## Attributi delle entita'

Tutti gli attributi sono accessibili con `var.attr`. Attributi
non presenti producono un warning di validazione ma non bloccano
l'esecuzione (saranno trattati come `None`).

| Entita'    | Attributi                                              |
|------------|--------------------------------------------------------|
| lesson     | teacher, class, subject, day, hour, classroom, slot, group |
| lesson     | + class.curriculum (alias diretto, pre-resolved)       |
| assignment | teacher, class, subject, hours, locked                 |
| teacher    | name, group, max_hours, free_day, graduatoria_score, completion_hours, exemption_hours |
| class      | name, year, section, curriculum, n_students            |
| classroom  | name, kind, type, capacity, tags                       |
| student    | id, name, last_name, first_name, class, tags, groups   |
| subject    | name                                                   |
| curriculum | name, code, score                                      |
| group      | name, kind                                             |
| slot       | day, hour                                              |
| day        | index, name                                            |
| hour       | index                                                  |

## Funzioni built-in

| Firma                 | Significato                                         |
|-----------------------|-----------------------------------------------------|
| `lesson(k=v, ...)`    | True sse esiste una lezione con tutti i kwargs      |
| `same_day(s1, s2)`    | True sse `s1.day == s2.day`                         |
| `consecutive(s1, s2)` | True sse stesso giorno e ore consecutive            |
| `hour(slot)`          | restituisce l'ora di uno slot/lezione               |
| `day(slot)`           | restituisce il giorno                               |
| `teacher(lesson)`     | restituisce il docente della lezione                |
| `class(lesson)`       | restituisce la classe                               |
| `subject(lesson)`     | restituisce la materia                              |
| `classroom(lesson)`   | restituisce l'aula                                  |

## Esempi commentati

### Vincoli su un singolo docente

```
# 1) Borghi non insegna mai in 1A alla 6a ora
forall l in lessons where l.teacher == Borghi and l.class == 1A: l.hour != 6

# 2) Borghi: max 4 ore al giorno (totali)
forall d in days: count l in lessons where l.teacher == Borghi
                                        and l.day == d.index: l <= 4

# 3) Borghi: max 2 ore al giorno per Scientifico (curriculum-aware)
forall d in days: count l in lessons where l.teacher == Borghi
    and l.day == d.index and l.class.curriculum == Scientifico: l <= 2
```

### Vincoli su una classe / un curriculum

```
# 4) Le classi del 4o e 5o anno hanno almeno 2 ore CONSECUTIVE di Mate
forall c in classes where c.year >= 4:
    exists s1 in slots: exists s2 in slots:
        consecutive(s1, s2)
        and lesson(class=c.name, day=s1.day, hour=s1.hour, subject=Mate)
        and lesson(class=c.name, day=s2.day, hour=s2.hour, subject=Mate)

# 5) L'indirizzo Linguistico anno 1 non ha mai lezione il sabato
forall l in lessons where l.class.curriculum == Linguistico
                       and l.day == 6: false
```

### Vincolo lab fisica (firma di Giovanni)

Esempio canonico richiesto da Giovanni: ogni docente di Fisica
deve avere ESATTAMENTE un'ora alla settimana in un'aula di tipo
`lab_fisica`.

```
forall t in teachers where t.subject == "Fisica":
    count l in lessons where l.teacher == t
                          and l.classroom.type == "lab_fisica": l == 1
```

Note operative:

- `t.subject` ritorna la **lista** delle materie del docente; il
  confronto `==` con uno scalare e' un'abbreviazione per "la
  stringa appartiene alla lista". Equivalente: `"Fisica" in
  t.subjects`.
- `l.teacher == t` confronta il docente della lezione con il
  docente del `forall`. Quando un lato e' una entity dict con
  `name`, il confronto cade sul `.name`. Si puo' anche scrivere
  `l.teacher == t.name` (esplicito).
- `l.classroom.type` viene risolto via il name -> kind index
  pre-calcolato in `build_world`. Forme equivalenti:
  `l.classroom_type` o `l.classroom_kind` (alias diretti).
- Versione SOFT: aggiungere `level=soft` con `weight=N` nel
  payload; le violazioni contribuiscono al SOFT score globale
  per ogni docente che NON soddisfa il count==1.
- Versione `exists` (zucchero per `count >= 1`):
    `forall t in teachers where t.subject == "Fisica":
        exists l in lessons where l.teacher == t
            and l.classroom.type == "lab_fisica": true`

### Vincoli su un'aula

```
# 6) Lab Fisica: una sola lezione per slot (capienza)
forall s in slots:
    count l in lessons where l.classroom == LabFisica
                          and l.day == s.day
                          and l.hour == s.hour: l <= 1
```

### Tag delle aule

Le aule possono avere etichette libere (many-to-many con
`classroom_tags`). Ogni tag e' una stringa minuscola condivisa fra
tutte le aule che lo dichiarano. Si interrogano con il path
`l.classroom.tags` (lista) oppure tramite l'operatore `in`:

```
# 6.bis) Tutte le ore di Matematica devono stare in un'aula taggata
#        come "matematica" (gli ambienti standard generati dal mock
#        ricevono questo tag automaticamente).
forall l in lessons where l.subject == Matematica:
    "matematica" in l.classroom.tags

# 6.ter) Le aule taggate "proiettore" sono richieste per Storia delle
#        terze e quarte
forall l in lessons where l.subject == Storia and l.class.year >= 3:
    "proiettore" in l.classroom.tags
```

Per le query sulla **lista aule** (tab Aule, NOT general DSL) si
usa il predicato compatto `has_tag(<name>)`, ad esempio
`has_tag(scientifico) AND tipo = standard`. Vedi
`docs/query_examples.md`.

### Tag degli studenti

Parallelo al sistema delle aule. Casi d'uso tipici:

- `BES`, `DSA`              - bisogni educativi
- `debito_matematica_4`     - studenti delle quarte con debito
- `pcto_ditta_X`            - alternanza presso un'azienda
- `studente_atleta`         - flessibilita' sportiva

```
# Tutti gli studenti con debito di matematica in quarta devono
# appartenere al gruppo "Recupero Matematica 4 anno".
forall s in students where "debito_matematica_4" in s.tags:
    exists g in s.groups: g.name == "Recupero Matematica 4 anno"

# Gli studenti BES non hanno mai lezione il sabato (HARD).
forall l in lessons:
    forall s in students where l.class == s.class
                            and "BES" in s.tags:
        l.day != 6
```

I tag NON sostituiscono i gruppi: i gruppi restano l'unita'
operativa di scheduling. Quando crei un nuovo gruppo dalla scheda
"Gruppi", trovi il pannello "Precompila da tag" che aggiunge in
massa i membri matchando `any_of` o `all_of` su una lista di tag.

### Implicazioni e relazioni fra cattedre

```
# 7) Se Rossi insegna a 3A allora anche Bianchi insegna a 3B
(exists l in lessons: l.teacher == Rossi and l.class == 3A)
=> (exists l in lessons: l.teacher == Bianchi and l.class == 3B)
```

## Semantica HARD / SOFT / PREFERITO

Quando l'espressione restituisce `false` (vincolo violato):

- `level=hard`     - violazione HARD: il modello e' infeasible.
                     Surfacciato in Feasibility Check + Cerca conflitti;
                     blocca la convalida HARD post-Phase-B.
- `level=soft`     - aggiunge `weight` (positivo) allo score SOFT
                     globale. Non blocca la soluzione ma la rende
                     piu' costosa nell'objective.
- `level=preferred`- nessuna penalty; il bonus `-weight` (negativo)
                     viene accreditato solo quando il vincolo E'
                     soddisfatto.
- `level=enforced` - come `hard` ma semanticamente "il vincolo deve
                     valere" (trattato a livello modello come HARD).

I pesi sono normalizzati lato server: HARD/ENFORCED -> `weight=0`,
PREFERITO con peso positivo viene flippato a negativo, SOFT con
peso negativo viene flippato a positivo.

## Limitazioni note

- L'evaluator e' **post-hoc**: parsea e valuta l'espressione DOPO che
  Phase B / metaeuristiche hanno prodotto una soluzione. Non e'
  un compilatore CP-SAT diretto: la convergenza dipende dal solver
  che ottimizza i vincoli built-in (matrix HARD, logical, coteach,
  ecc.). Il DSL generico aggiunge invece un livello di
  "convalida + penalty post-hoc" che la pipeline rispetta come parte
  del check HARD finale e dello score SOFT.
- **Complessita'** quadratica per `forall x in S1: forall y in S2:`
  -> `|S1| * |S2|` valutazioni dell'espressione interna. Il
  validatore alza un errore oltre 10^6 atomi. Per vincoli pesanti
  preferire `count` con un singolo `forall`.
- **Sorgenti che richiedono una soluzione attiva**: `lessons`
  produce 0 elementi senza una soluzione caricata. Vincoli
  `forall l in lessons: ...` sono vacuamente veri in quel caso.
- **Identificatori "stringhe"**: usare `Borghi` o `1A` senza
  virgolette li tratta come stringhe. Per evitare ambiguita' su
  parole riservate, mettile fra virgolette: `"forall"`.

## Endpoint REST

```
POST   /api/constraints/general/validate   { expression, ... }
                                            -> { ok, errors[], warnings[], n_atoms }
GET    /api/constraints/general?scope=&owner_id=
POST   /api/constraints/general            { expression, label?, level,
                                            weight, scope, owner_id? }
                                            -> 201 GeneralConstraintOut
PUT    /api/constraints/general/{id}       (stesso payload)
DELETE /api/constraints/general/{id}
POST   /api/constraints/general/check-all  -> { hard_violations[],
                                               soft_violations[],
                                               soft_penalty }
```

Il check-all viene chiamato dal panel Feasibility Check come parte
della verifica HARD; il soft_penalty contributo viene aggiunto allo
score globale di Phase B nel computo SOFT post-soluzione.

## Ricerca dei vincoli (cross-source)

Un vincolo che cita Rossi puo' vivere in tante posti: la sua scheda
docente, una scheda aula ("Lab Fisica non puo' avere Rossi al
pomeriggio"), un vincolo logico DNF, un vincolo DSL generico
salvato globalmente. Il pannello **🔍 Ricerca** nel tab Vincoli
trova tutti i vincoli che <em>menzionano</em> un'entita' specifica,
a prescindere da dove sono stati creati.

Endpoint backend: `GET /api/constraints/search`. Parametri:

| Param         | Tipo                            | Descrizione                                                              |
|---------------|---------------------------------|--------------------------------------------------------------------------|
| entity_type   | str                             | teacher / class / classroom / subject / curriculum / group              |
| entity_id     | int                             | id dell'entita' (oppure stringa per subject)                             |
| text          | str                             | substring case-insensitive su detail / expression / owner_name           |
| levels        | str CSV                         | hard,soft,preferred,enforced,allowed,forbidden                           |
| kinds         | str CSV                         | teacher_cell,class_cell,room_cell,logical_*,subject_room_pref,coteach,general_dsl,... |

Ritorna una lista di constraint dict, ognuno con:

- `kind`         tipo del vincolo (teacher_cell / logical_class / general_dsl / ...)
- `origin`       scheda di creazione tipica (`teacher` / `class` / ...)
- `scope`        ambito (italianizzato: docente / classe / aula ...)
- `owner_id`, `owner_name`, `level`, `weight`, `detail`, `expression`
- `mentions`     lista di `{entity_type, entity_id}` che il vincolo
                 menziona (rilevati da owner_id strutturati + da
                 token-matching nel testo dell'espressione)

### Come funziona la rilevazione "menzioni"

Per ogni constraint, il backend calcola un set `mentions` di
coppie `(entity_type, entity_id)`:

1. **Strutturate** dall'`owner_id`/FK del row stesso. Sempre
   accurate.
2. **Testuali** dalla scansione regex dell'espressione DSL salvata:
   ogni token alfanumerico viene cercato in un name index globale
   `lower(name) -> [(entity_type, id, display)]` che include nomi,
   cognomi, nickname dei docenti, codici e nomi di indirizzi e
   classi/aule. Best-effort: token ambigui (es. "1A" se sia classe
   sia, ipoteticamente, materia) matchano tutti i candidati.

Per i vincoli DSL generici i token vengono estratti dall'intero
testo dell'espressione, non solo dalla pillola di scope. Cosi'
`forall l in lessons where l.teacher == Rossi: l.day != 6`
viene marcato come "menziona Rossi" anche se salvato globalmente.

### Esempi di query

```
# Tutti i vincoli che coinvolgono il docente Rossi (id 12)
GET /api/constraints/search?entity_type=teacher&entity_id=12

# Vincoli HARD che coinvolgono Lab Fisica (id 5) -- niente
# preferenze SOFT/PREFERRED ma anche logical_* hard
GET /api/constraints/search?entity_type=classroom&entity_id=5
   &levels=hard,enforced

# Cerca testualmente "Mate" nei dettagli/espressioni
GET /api/constraints/search?text=Mate

# Solo vincoli DSL generici che coinvolgono il curriculum Scientifico (id 1)
GET /api/constraints/search?entity_type=curriculum&entity_id=1
   &kinds=general_dsl
```

Il pannello UI fa lo stesso ma con dropdown per il tipo + il select
delle entita' precaricate. Per ogni risultato compare la pill
"tab: <origine>" che indica dove il vincolo era stato creato
originariamente, e un bottone ✕ Rimuovi (DELETE
`/api/constraints/general/{id}` per i DSL, /api/monitor/constraints/{kind}/{id}
per gli altri).

## Esempi nel modal "Nuovo vincolo DSL"

Il modal include un dropdown "Esempi" che pre-riempie l'editor
con ognuno degli 7 esempi di sopra. La validazione e' live
(debounce 500ms) tramite `POST /general/validate`.
