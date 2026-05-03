# DSL generico per i vincoli

> Linguaggio compatto, dichiarativo, totalmente componibile per esprimere
> vincoli **HARD / SOFT / PREFERITO / ENFORCED** su qualunque combinazione
> logica di predicati sul modello dei dati.

Implementazione: `webui/backend/utils/general_dsl.py` (parser
ricorsivo discendente + AST + evaluator post-hoc, ~250 LOC, no
dipendenze esterne). Esposto via `POST /api/constraints/general`,
testato live da `POST /api/constraints/general/validate` e
visibile dal modal **+ Nuovo vincolo DSL** del tab Vincoli.

---

## 1. Introduzione e filosofia

Prima del DSL generico il sistema aveva quattro sub-DSL specializzati,
ognuno con grammatica e parser propri:

| Sub-DSL          | File                    | Cosa esprimeva                            |
| ---------------- | ----------------------- | ----------------------------------------- |
| `query_parser`   | `utils/query_parser.py` | filtri DSL sulle liste (tab Aule, Docenti)|
| `logic_parser`   | `utils/logic_parser.py` | vincoli DNF logical (cella + disgiunzioni)|
| `objective_dsl`  | `utils/objective_dsl.py`| funzione obiettivo Phase A custom         |
| introspettivo    | scattered               | "vincoli che parlano di vincoli"          |

Ognuno copriva un caso d'uso ma erano scollegati: stessa grammatica
implementata 4 volte, stesso bug riprodotto 4 volte. Il **DSL
generico** unifica tutto sotto una sola grammatica con quattro
"sapori" di compilazione (LIST, LOGIC, OBJECTIVE, EVAL).

Principio: **un parser, molti compilatori**. La sintassi del
quantificatore `forall x in S where Filter: Body` e dei predicati
atomici (==, !=, <, in, ...) e' **identica** in tutti i contesti;
cambia solo il backend di traduzione.

Vantaggi:

- **Espressivit\`a**: possiamo modellare vincoli che i sub-DSL non
  potevano (es. composizione condizionata fra cattedre, vincoli
  "se-allora" cross-entit\`a, vincoli sulle distribuzioni).
- **Manutenibilit\`a**: un fix al parser si propaga a tutto.
- **UI unificata**: il modal "+ Nuovo vincolo DSL" e l'editor
  inline accettano la stessa sintassi che vedete in questa guida.

Il DSL e' interpretato **post-hoc**: parsea l'espressione e la
valuta DOPO che la pipeline (Phase A, Phase B, metaeuristiche) ha
prodotto una soluzione candidata. Le violazioni HARD vengono
rilevate dal `Feasibility Check` e bloccano la conferma; le
violazioni SOFT alimentano lo score globale dell'objective.

---

## 2. Grammatica BNF completa

```bnf
expr           ::= iff_expr
iff_expr       ::= implies_expr ( "<=>" implies_expr )*
implies_expr   ::= or_expr ( "=>" or_expr )*
or_expr        ::= and_expr ( ("OR"|"or") and_expr )*
and_expr       ::= not_expr ( ("AND"|"and") not_expr )*
not_expr       ::= ("NOT"|"not") not_expr | atom

atom           ::= quant_expr
                 | count_expr
                 | comparison
                 | call
                 | bool_lit
                 | "(" expr ")"

quant_expr     ::= ("forall" | "exists") IDENT "in" source
                   ["where" or_expr] ":" expr

count_expr     ::= "count" IDENT "in" source ["where" or_expr]
                   ( ":" comparison
                   | op value )

source         ::= IDENT                    # literal source name
                 | IDENT ("." IDENT)+       # path (resolved at runtime)

comparison     ::= value ( op value
                         | "in" "[" value ("," value)* "]"
                         | "in" path
                         | "not_in" "[" value ("," value)* "]"
                         | "not_in" path )

op             ::= "==" | "!=" | "<" | "<=" | ">" | ">="

value          ::= IDENT ( "." IDENT )*    # dotted reference
                 | NUM
                 | STRING
                 | BOOL
                 | function_call

function_call  ::= IDENT "(" [arg_list] ")"
arg_list       ::= arg ("," arg)*
arg            ::= IDENT "==" value          # keyword form
                 | value                      # positional

path           ::= IDENT ("." IDENT)*
bool_lit       ::= "true" | "false" | "True" | "False"
NUM            ::= -?\d+(\.\d+)?
STRING         ::= "..." | '...'
IDENT          ::= [A-Za-z0-9_]*[A-Za-z_][A-Za-z0-9_]*
                   # at least one letter; matches '1A', '3B_scientifico'
```

### Note di tokenizzazione

- `=` da solo viene normalizzato a `==` (per friendlyness con utenti
  abituati a SQL/Excel).
- Identificatori che iniziano con cifra ma contengono almeno una
  lettera (`1A`, `3B_scientifico`, `lun8`) sono tokenizzati come
  IDENT, NON come NUM. Cosi' `l.class == 1A` funziona senza
  virgolette.
- I commenti iniziano con `#` e vanno fino a fine riga.
- Stringhe tra virgolette `"..."` o `'...'` sono trattate
  letteralmente; usatele quando il valore contiene spazi o
  caratteri speciali, OPPURE quando il bare token sarebbe
  riservato (`"forall"`, `"in"`).

### Precedenze (dalla pi\`u bassa alla pi\`u alta)

```
<=>  (iff)
=>   (implies)
OR
AND
NOT
== != < <= > >= in not_in
. (member access)
```

Le parentesi `(...)` sovrascrivono qualunque precedenza.

---

## 3. Tipi di dato e valori

### Sorgenti iterabili (per `forall`, `exists`, `count`)

| Sorgente      | Tipo elemento                                 |
| ------------- | --------------------------------------------- |
| `lessons`     | lezioni della soluzione attiva                |
| `assignments` | cattedre (Assignment rows)                    |
| `teachers`    | docenti                                       |
| `classes`     | classi                                        |
| `classrooms`  | aule                                          |
| `students`    | studenti (con `tags[]` e `groups[]` precompilate) |
| `subjects`    | materie                                       |
| `curricula`   | indirizzi di studio                           |
| `groups`      | gruppi articolati                             |
| `slots`       | tutte le 36 (day, hour) della settimana       |
| `days`        | i 6 giorni (Lun..Sab)                         |
| `hours`       | le 6 ore (8..13)                              |

In aggiunta a queste sorgenti **letterali**, dalla v0.5 il DSL
accetta una **sorgente-path**: dopo `in` puoi mettere un attributo
puntato che, valutato in env, restituisce una lista. Esempio:

```dsl
# itera i gruppi a cui appartiene lo studente s
forall s in students where "BES" in s.tags:
    exists g in s.groups: g.name == "Sostegno"
```

### Tipi primitivi

- **int** / **float** (NUM)
- **string** (STRING quotato; oppure IDENT bare)
- **bool** (`true`, `false`)
- **list / set** (solo come risultato di un attributo o letterale `[...]`)

### Costanti / convenzioni

- I giorni sono interi 1..6 dove 1=Lunedi, 6=Sabato. Espressioni
  tipiche: `l.day != 6` (no sabato), `l.day == 1` (solo lunedi).
- Le ore sono interi 8..13 (la 6a ora e' 13).
- Identificatori "stringa" senza virgolette (`Borghi`, `1A`) sono
  trattati come stringhe — comodo per nomi senza spazi.

---

## 4. Predicati atomici

### Confronti

```text
l.hour == 8                   # uguaglianza
l.day != 6                    # disuguaglianza
c.year >= 4                   # numerico
t.name < "Z"                  # lessicografico
```

Quando un lato e' un dict-entit\`a (es. `forall t in teachers`,
`t` e' un dict `{name, group, max_hours, ...}`) e l'altro lato e'
uno scalare, il confronto cade sull'attributo `name`:
`l.teacher == t` equivale a `l.teacher == t.name`.

Se un lato e' una lista (es. `t.subject` ritorna la lista materie),
`==` e' un'abbreviazione per "appartenenza": `t.subject == "Fisica"`
equivale a `"Fisica" in t.subjects`.

### Operatori di insieme

```text
l.day in [1, 2, 3, 4, 5]                  # lista letterale
"matematica" in l.classroom.tags          # path che ritorna una lista
l.subject not_in ["Religione", "Educazionefisica"]
"BES" in s.tags
```

`in [a, b, c]` accetta una lista letterale. `in <path>` (senza
parentesi quadre) interpreta il lato destro come un attributo
puntato che deve risolvere a una lista a runtime.

### Funzioni di slot

```text
hour(l)                       # l'ora di una lezione/slot
day(l)                        # il giorno di una lezione/slot
same_day(s1, s2)              # true sse hanno lo stesso .day
consecutive(s1, s2)           # stesso giorno + ore adiacenti (|h1-h2|==1)
```

### Funzioni di entit\`a

```text
teacher(l)    classroom(l)    class(l)    subject(l)
```

Versione **funzionale** equivalente all'accesso `l.teacher`
ecc. Utile quando un linter vorrebbe sottolineare un campo
mancante; gli evaluator si comportano in modo identico.

### Selettore di lezione (`lesson(...)`)

```dsl
lesson(class==c.name, day==1, hour==8, subject==Matematica)
```

Restituisce `true` se ESISTE almeno una lezione che soddisfa tutti
i `key==value` passati. Equivalente sintattico-zucchero per
`exists l in lessons: l.<key1> == <v1> and l.<key2> == <v2> and ...`.

---

## 5. Quantificatori

### `forall`

```text
forall x in S [where filter]: predicate
```

Il `predicate` deve valere per OGNI `x` di `S` che soddisfa il
`filter`. Se anche solo un elemento lo viola, l'intero `forall`
ritorna `false`.

### `exists`

```text
exists x in S [where filter]: predicate
```

Esiste **almeno un** `x` per cui il predicato e' vero.

### `count`

```text
count x in S [where filter]: x op N
```

Oppure (forma equivalente senza i due punti):

```text
count x in S [where filter] op N
```

Dove `op` in `==, !=, <, <=, >, >=` e `N` e' un numero. Il count
**conta** quanti elementi soddisfano il filtro e applica
l'operatore al numero. Il body dopo `:` e' un confronto su `x`,
ma l'unica forma significativa e' la pseudo-variabile (vedi sotto).

### Annidamento

```dsl
forall t in teachers where t.subject == "Fisica":
    count l in lessons where l.teacher == t
                          and l.classroom.type == "lab_fisica":
        l == 1
```

Annidare `forall` e `count` e' la formula tipica per esprimere
"per ogni X, deve essere il caso che Y": quantificazione esterna
sull'aggregato + count sull'insieme dipendente.

---

## 6. Connettivi logici

```text
A and B                  # entrambi
A or B                   # almeno uno
not A                    # negazione
A => B                   # implicazione (se A allora B; equivalente a (not A) or B)
A <=> B                  # iff (entrambi veri o entrambi falsi)
```

Le parole chiave sono case-insensitive (`AND` == `and`).

### Esempio con implicazione

```dsl
# Se Rossi insegna a 3A allora anche Bianchi insegna a 3B
(exists l in lessons: l.teacher == Rossi and l.class == 3A)
=> (exists l in lessons: l.teacher == Bianchi and l.class == 3B)
```

---

## 7. Funzioni built-in

| Firma                     | Significato                                    |
| ------------------------- | ---------------------------------------------- |
| `lesson(k=v, ...)`        | True sse esiste una lezione con tutti i kwargs |
| `same_day(s1, s2)`        | `s1.day == s2.day`                             |
| `consecutive(s1, s2)`     | stesso giorno + ore adiacenti                  |
| `hour(slot_or_lesson)`    | restituisce `.hour`                            |
| `day(slot_or_lesson)`     | restituisce `.day`                             |
| `teacher(lesson)`         | restituisce `.teacher`                         |
| `class(lesson)`           | restituisce `.class`                           |
| `subject(lesson)`         | restituisce `.subject`                         |
| `classroom(lesson)`       | restituisce `.classroom`                       |

> **Nota**: aggregati statistici (`mean`, `stddev`, `min`, `max`,
> `sum`) sono nella roadmap ma non ancora implementati. Per
> simulare `sum` usa `count` con un filtro che includa solo gli
> elementi da contare.

---

## 8. Sintassi soft / hard

A differenza dei sub-DSL legacy (objective_dsl), il DSL generico
**non** ha la parola chiave `soft <peso>:` *all'interno*
dell'espressione: peso e livello sono campi del payload REST,
non parte della grammatica.

Quando crei un vincolo via `POST /api/constraints/general`:

```json
{
  "expression": "forall l in lessons where l.teacher == Rossi: l.day != 6",
  "label": "Rossi mai sabato",
  "level": "soft",        // hard | soft | preferred | enforced
  "weight": 50,
  "scope": "teacher",
  "owner_id": 12
}
```

Quando la tua espressione produce `false` (vincolo violato), il
runtime applica:

| `level`     | Effetto su violazione                                     |
| ----------- | --------------------------------------------------------- |
| `hard`      | Modello infeasible. Bloccato dal Feasibility Check.       |
| `soft`      | Aggiunge `weight` (positivo) allo score SOFT globale.     |
| `preferred` | Nessuna penalty; bonus `-weight` (negativo) se SODDISFATTO.|
| `enforced`  | Come `hard` ma semanticamente "deve valere".              |

Pesi normalizzati lato server: HARD/ENFORCED -> `weight=0`,
PREFERITO con peso positivo -> negativo, SOFT con peso negativo
-> positivo.

---

## 9. Aliasing e let (roadmap)

La keyword `let` e' lessata ma il parser non la consuma ancora.
Quando arriver\`a la sintassi sar\`a:

```text
let mate_classes = (forall c in classes where c.year >= 4: ...)
in mate_classes and (...)
```

**Workaround attuale**: ripetere la sotto-espressione, o splittare
in pi\`u vincoli salvati separatamente.

---

## 10. Galleria di esempi (30+ casi reali)

Tutti gli esempi qui sotto sono stati validati live contro il
parser corrente: copia-incolla qualunque blocco nell'editor
"Nuovo vincolo DSL" e dovr\`a essere accettato.

### 10.1 Vincoli docente

#### E1. Borghi non insegna mai in 1A alla 6a ora

```dsl
forall l in lessons where l.teacher == Borghi and l.class == 1A:
    l.hour != 13
```

Itera tutte le lezioni; per ogni lezione di Borghi nella 1A,
richiede ora diversa dalla 13 (= 6a ora).

#### E2. Borghi: max 4 ore al giorno (totali)

```dsl
forall d in days:
    count l in lessons where l.teacher == Borghi
                          and l.day == d.index: l <= 4
```

Per ognuno dei 6 giorni, conta le lezioni di Borghi quel giorno e
richiede al pi\`u 4. Pattern canonico per "max N ore/giorno".

#### E3. Lab fisica: ogni docente di fisica esattamente 1 ora a settimana

```dsl
forall t in teachers where t.subject == "Fisica":
    count l in lessons where l.teacher == t
                          and l.classroom.type == "lab_fisica":
        l == 1
```

Quantificazione esterna su tutti i docenti di Fisica + count
interno per slot in lab. Esempio canonico (firma di Giovanni).

#### E4. Tetto cattedra Inglese: max 18h/settimana

```dsl
forall t in teachers where t.subject == "Inglese":
    count l in lessons where l.teacher == t: l <= 18
```

Anche se la cattedra e' definita altrove (Phase A), questo vincolo
DSL convalida post-hoc che nessuna soluzione superi il monte ore.

#### E5. Rossi non lavora mai il sabato (HARD)

```dsl
forall l in lessons where l.teacher == Rossi and l.day == 6: false
```

Pattern "vincolo proibito": il body `false` significa che ogni
match e' una violazione. Per la versione SOFT con preferenza,
mettere `level=soft` nel payload.

#### E6. Rossi: al pi\`u 1 sesta ora a settimana

```dsl
count l in lessons where l.teacher == Rossi and l.hour == 13: l <= 1
```

`count` al top-level (senza `forall` esterno) conta su TUTTE le
lezioni nella soluzione. SOFT con weight=10 e' tipico.

#### E7. Tutti i docenti di A050: max 5 ore al giorno

```dsl
forall t in teachers where t.group == "A050":
    forall d in days:
        count l in lessons where l.teacher == t and l.day == d.index:
            l <= 5
```

Doppio annidamento: per ogni docente di una classe di concorso,
per ogni giorno, max 5 ore.

#### E8. Coupling Rossi 3A => Bianchi 3B

```dsl
(exists l in lessons: l.teacher == Rossi and l.class == 3A)
=> (exists l in lessons: l.teacher == Bianchi and l.class == 3B)
```

Implicazione: SE Rossi compare in 3A, ALLORA anche Bianchi deve
comparire in 3B. Esprime una relazione condizionale fra cattedre.

#### E9. Rossi non in palestra (mai)

```dsl
forall l in lessons where l.teacher == Rossi:
    l.classroom.type != "palestra"
```

Vincolo docente x kind-aula. `l.classroom.type` viene risolto via
indice pre-calcolato (alias `classroom_type`).

#### E10. Tutti i prof di mate: almeno una lezione di mattina

```dsl
forall t in teachers where t.subject == "Matematica":
    exists l in lessons where l.teacher == t: l.hour <= 9
```

Quantificazione mista forall/exists.

### 10.2 Vincoli classe

#### E11. La 1A non lavora il sabato

```dsl
forall l in lessons where l.class == 1A: l.day != 6
```

#### E12. Le prime: max 5 ore/giorno

```dsl
forall c in classes where c.year == 1:
    forall d in days:
        count l in lessons where l.class == c.name and l.day == d.index:
            l <= 5
```

Filtro sull'anno (`c.year == 1`) + max ore/giorno.

#### E13. Le quarte/quinte: due ore CONSECUTIVE di Mate alla settimana

```dsl
forall c in classes where c.year >= 4:
    exists s1 in slots: exists s2 in slots:
        consecutive(s1, s2)
        and lesson(class==c.name, day==s1.day, hour==s1.hour,
                    subject==Matematica)
        and lesson(class==c.name, day==s2.day, hour==s2.hour,
                    subject==Matematica)
```

Doppio `exists` su `slots` + `consecutive(s1, s2)`. Esempio del
potere espressivo del DSL (vincoli che i sub-DSL legacy non
potevano scrivere).

#### E14. Linguistico anno 1: niente sabato

```dsl
forall l in lessons where l.class.curriculum == Linguistico
                       and l.day == 6:
    false
```

#### E15. 1A: Religione solo nelle prime 4 ore

```dsl
forall l in lessons where l.class == 1A and l.subject == Religione:
    l.hour <= 11
```

### 10.3 Vincoli aula

#### E16. Lab Fisica: una sola lezione per slot (capienza)

```dsl
forall s in slots:
    count l in lessons where l.classroom == "Lab Fisica 1"
                          and l.day == s.day
                          and l.hour == s.hour:
        l <= 1
```

Quantificazione su tutti gli slot + count delle lezioni che
"occupano" l'aula in quello slot.

#### E17. Matematica solo in aule taggate "matematica"

```dsl
forall l in lessons where l.subject == Matematica:
    "matematica" in l.classroom.tags
```

Usa l'operatore `in` su un path (`l.classroom.tags`).

#### E18. Storia delle terze e oltre: aula con proiettore

```dsl
forall l in lessons where l.subject == Storia and l.class.year >= 3:
    "proiettore" in l.classroom.tags
```

#### E19. La palestra ospita SOLO Scienze motorie

```dsl
forall l in lessons where l.classroom.type == "palestra":
    l.subject == Scienzemotorie
```

#### E20. Lab chimica: max 2 lezioni concorrenti per slot

```dsl
forall s in slots:
    count l in lessons where l.classroom.type == "lab_chimica"
                          and l.day == s.day
                          and l.hour == s.hour:
        l <= 2
```

### 10.4 Vincoli materia

#### E21. Matematica distribuita: max 2 ore al giorno per classe

```dsl
forall c in classes:
    forall d in days:
        count l in lessons where l.class == c.name
                              and l.subject == Matematica
                              and l.day == d.index:
            l <= 2
```

Triplo annidamento (classe x giorno x materia). Distribuisce le
ore di mate su pi\`u giorni invece di concentrarle.

#### E22. Matematica preferibilmente entro la 5a ora

```dsl
forall l in lessons where l.subject == Matematica: l.hour <= 12
```

SOFT con weight=20 e' tipico: preferenza, non vincolo rigido.

#### E23. Educazione fisica solo in palestra

```dsl
forall l in lessons where l.subject == Educazionefisica:
    l.classroom.type == "palestra"
```

### 10.5 Vincoli gruppo / studenti

#### E24. Studenti BES devono essere in un gruppo "Sostegno"

```dsl
forall s in students where "BES" in s.tags:
    exists g in s.groups: g.name == "Sostegno"
```

Usa la sorgente-path `s.groups` per iterare i gruppi del singolo
studente. Verifica che almeno uno si chiami "Sostegno".

#### E25. Studenti con debito di mate quarto: gruppo "Recupero Matematica"

```dsl
forall s in students where "debito_matematica_4" in s.tags:
    exists g in s.groups: g.name == "Recupero Matematica"
```

#### E26. Studenti BES: nessuna lezione il sabato

```dsl
forall l in lessons:
    forall s in students where l.class == s.class
                            and "BES" in s.tags:
        l.day != 6
```

Doppio `forall` (lessons x students) + filtro su tag. Per ogni
slot della classe di uno studente BES, vieta il sabato.

### 10.6 Vincoli relazionali / coupling

#### E27. Rossi in Aula 12: solo Matematica

```dsl
forall l in lessons where l.teacher == Rossi and l.classroom == "Aula 12":
    l.subject == Matematica
```

Tre dimensioni (docente x aula x materia) in un unico vincolo.

#### E28. Se Rossi insegna in 3A, deve usare un lab fisica almeno una volta

```dsl
(exists l in lessons: l.teacher == Rossi and l.class == 3A)
=>
(exists l2 in lessons: l2.teacher == Rossi and l2.class == 3A
                   and l2.classroom.type == "lab_fisica")
```

Implicazione fra esistenze su due variabili distinte (`l`, `l2`).

#### E29. Inglese alle prime: max 3 ore/settimana per coppia (docente, classe)

```dsl
forall t in teachers where t.subject == "Inglese":
    forall c in classes where c.year == 1:
        count l in lessons where l.teacher == t and l.class == c.name:
            l <= 3
```

#### E30. Religione alle prime: mai prima ora

```dsl
forall l in lessons where l.subject == Religione and l.class.year == 1:
    l.hour != 8
```

---

## 11. Errori comuni e troubleshooting

### Parsing errors tipici

| Errore                                          | Causa                                                                |
| ----------------------------------------------- | -------------------------------------------------------------------- |
| `Atteso COLON, trovato OP (=)`                  | Hai usato `=` invece di `==` in un confronto post-`where`            |
| `Atteso IDENT, trovato BOOL`                    | Una parola riservata (es. `true`) in posizione non-valore            |
| `sorgente sconosciuta 'foo'`                    | Sorgente non in `_VALID_SOURCES` e non e' un path raggiungibile     |
| `Token sconosciuto a colonna N`                 | Carattere non riconosciuto (es. `&&`, `||`); usa `and`/`or`         |
| `oltre 1000000 atomi: probabile esplosione`    | Quantificatori troppo annidati su sorgenti grandi                   |

### Avvertenze sulla complessit\`a

Il validatore conta gli "atomi" totali della valutazione. Un
`forall x in S1: forall y in S2: predicate(x,y)` produce
`|S1| * |S2|` atomi. Esempio: con 90 docenti e 50 classi, un doppio
forall = 4'500 atomi (OK). Con 11000 lezioni dentro,
un `forall l in lessons: forall t in teachers: ...` = 990'000 atomi
(al limite del max).

Quando vedi un warning di "esplosione combinatoria":

1. Sposta i filtri specifici nel `where` interno per ridurre il
   set effettivamente iterato
2. Sostituisci un `forall ... forall ...` con un `count` annidato
3. Splitta il vincolo in due vincoli separati salvati indipendentemente

### Validazione `dry-run`

```http
POST /api/constraints/general/validate
Content-Type: application/json

{ "expression": "forall l in lessons where ..." }
```

Restituisce `{ok, errors[], warnings[], n_atoms}` SENZA salvare il
vincolo. Usalo per iterare velocemente.

L'editor del frontend usa lo stesso endpoint con debounce 500ms.

---

## 12. Reference completo: attributi delle entit\`a

Tutti gli attributi sono accessibili con `var.attr`. Un attributo
non disponibile produce `None` (interpretato come stringa vuota o
zero a seconda del contesto) e un warning di validazione.

### Lesson

| Attributo            | Tipo    | Esempio              |
| -------------------- | ------- | -------------------- |
| `teacher`            | str     | `l.teacher`          |
| `class`              | str     | `l.class`            |
| `subject`            | str     | `l.subject`          |
| `day`                | int 1-6 | `l.day`              |
| `hour`               | int 8-13| `l.hour`             |
| `classroom`          | str     | `l.classroom`        |
| `classroom.type`     | str     | `l.classroom.type`   |
| `classroom.tags`     | list[str]| `"lab" in l.classroom.tags` |
| `class.curriculum`   | str     | `l.class.curriculum` |
| `class.year`         | int     | `l.class.year`       |
| `slot`               | tuple   | (alias di (day,hour))|
| `group`              | str?    | nome gruppo se applicabile |

### Assignment

| Attributo  | Tipo  | Esempio       |
| ---------- | ----- | ------------- |
| `teacher`  | str   | `a.teacher`   |
| `class`    | str   | `a.class`     |
| `subject`  | str   | `a.subject`   |
| `hours`    | int   | `a.hours`     |
| `locked`   | bool  | `a.locked`    |

### Teacher

| Attributo           | Tipo       | Esempio                    |
| ------------------- | ---------- | -------------------------- |
| `name`              | str        | `t.name`                   |
| `group`             | str        | classe di concorso         |
| `max_hours`         | int        | `t.max_hours <= 18`        |
| `free_day`          | str?       | day name legacy            |
| `subject`           | list[str]  | `"Mate" in t.subject`      |
| `subjects`          | list[str]  | (alias di `subject`)       |
| `graduatoria_score` | float      | per ordinamento supplenze  |
| `completion_hours`  | int        |                            |
| `exemption_hours`   | int        |                            |

### SchoolClass

| Attributo     | Tipo  | Esempio              |
| ------------- | ----- | -------------------- |
| `name`        | str   | `c.name == "1A"`     |
| `year`        | int   | `c.year >= 4`        |
| `section`     | str?  | `c.section`          |
| `curriculum`  | str   | `c.curriculum`       |
| `n_students`  | int   |                      |

### Classroom

| Attributo  | Tipo        | Esempio                          |
| ---------- | ----------- | -------------------------------- |
| `name`     | str         |                                  |
| `kind`     | str         | `lab_fisica`, `palestra`, ...    |
| `type`     | str         | (alias di `kind`)                |
| `capacity` | int         |                                  |
| `tags`     | list[str]   | `"lab" in r.tags`                |

### Subject

| Attributo | Tipo | Esempio          |
| --------- | ---- | ---------------- |
| `name`    | str  | `s.name == "Mate"` |

### Curriculum

| Attributo | Tipo  | Esempio        |
| --------- | ----- | -------------- |
| `name`    | str   |                |
| `code`    | str   | `cu.code == "Scientifico"` |
| `score`   | float |                |

### Group

| Attributo | Tipo | Esempio              |
| --------- | ---- | -------------------- |
| `name`    | str  | `g.name == "Spagnolo"` |
| `kind`    | str  | `splitting | language | religion | support | other` |

### Student

| Attributo    | Tipo       | Esempio               |
| ------------ | ---------- | --------------------- |
| `id`         | int        |                       |
| `name`       | str        | full name             |
| `last_name`  | str        |                       |
| `first_name` | str        |                       |
| `class`      | str?       | classe di appartenenza|
| `tags`       | list[str]  | `"BES" in s.tags`     |
| `groups`     | list[dict] | `exists g in s.groups: ...` |

### Slot, Day, Hour

| Slot.day, .hour      | int                                        |
| Day.index, .name     | int 1-6, str ("Lunedi"..)                  |
| Hour.index           | int 8-13                                    |

---

## Endpoint REST riassuntivi

```
POST   /api/constraints/general/validate   { expression }
                                            -> { ok, errors[], warnings[], n_atoms }
GET    /api/constraints/general?scope=&owner_id=
POST   /api/constraints/general            { expression, label, level,
                                            weight, scope, owner_id? }
                                            -> 201 GeneralConstraintOut
PUT    /api/constraints/general/{id}       (stesso payload)
DELETE /api/constraints/general/{id}
POST   /api/constraints/general/check-all  -> { hard_violations[],
                                                soft_violations[],
                                                soft_penalty }
```

`check-all` viene chiamato dal Feasibility Check come parte della
verifica HARD; il `soft_penalty` viene aggiunto allo score globale
di Phase B nel computo SOFT post-soluzione.
