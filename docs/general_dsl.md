# Scrivere vincoli con il linguaggio di piTantum

Questa pagina ti spiega come scrivere "regole" che l'orario deve
rispettare, usando il linguaggio dei vincoli di piTantum. Ti
servir\`a, per esempio, se sei un coordinatore d'orario o un
membro della commissione e vuoi dire al programma cose come "la
professoressa Rossi non lavora il sabato", "la palestra puo'
ospitare solo lezioni di scienze motorie", o "ogni docente di
fisica deve avere almeno un'ora a settimana in laboratorio".

Non serve saper programmare: l'idea \`e proprio che le regole si
scrivano come si direbbero a voce, con qualche piccolo
accorgimento di sintassi. Procediamo per esempi: ogni concetto
viene introdotto attraverso un caso pratico, e poi generalizzato.

> **Per gli sviluppatori**: la grammatica formale completa, gli
> attributi delle entit\`a riga per riga, e gli endpoint REST li
> trovi nelle Appendici A, B, C in fondo a questa pagina.

---

## Un esempio per partire: la prof Rossi non lavora il sabato

Mettiamo che la prof Rossi insegni matematica in tre classi e ci
abbia chiesto di averla libera il sabato. \`E una richiesta
comune. Vediamo come si esprime al programma.

Vogliamo dire: **per ogni** lezione che ha la prof Rossi come
docente, e che cade di sabato, **deve essere falsa** (cio\`e:
non deve esistere). In linguaggio del programma, scriviamo:

```dsl
forall l in lessons where l.teacher == Rossi and l.day == 6:
    false
```

Leggiamo lentamente. La parola \texttt{forall} significa "per ogni";
\texttt{l in lessons} significa "scegliamo una lezione qualunque,
chiamandola \texttt{l}, dall'elenco di tutte le lezioni"; il
\texttt{where} che segue \`e un filtro: ci interessano solo le
lezioni che hanno **due** caratteristiche: il docente \`e Rossi
(\texttt{l.teacher == Rossi}) **e** il giorno \`e il sabato
(\texttt{l.day == 6}, perch\'e in piTantum lunedi=1, martedi=2,
\dots, sabato=6). Per tutte le lezioni che soddisfano queste
condizioni, vogliamo che valga la regola dopo i due punti, che
in questo caso \`e \texttt{false}: cio\`e nessuna di quelle
lezioni deve esistere.

Equivalente: "non esiste alcuna lezione di Rossi il sabato".

Quando salvi questo vincolo nel pannello "+ Nuovo vincolo DSL"
del tab Vincoli, scegli che livello dargli:

- **HARD** \`e una regola assoluta: il programma non produrr\`a
  mai una soluzione che la viola. Se nessuna soluzione possibile
  rispetta tutte le regole HARD, il sistema te lo dice ("modello
  infeasible") e ti aiuta a capire chi sta confliggendo.
- **SOFT** \`e una preferenza pesata: la soluzione pu\`o anche
  violarla, ma per ogni violazione paga una penalit\`a (un peso
  che decidi tu). Il solver cerca di minimizzare la somma delle
  penalit\`a.
- **PREFERRED** \`e l'opposto del soft: nessuna penalit\`a se
  non si soddisfa, bonus se invece viene rispettato.
- **ENFORCED** \`e come HARD ma usato per regole strutturali
  che esprimono "questa cosa **deve** accadere" (mentre HARD di
  solito vuol dire "questa cosa **non** deve accadere").

Quindi se la prof Rossi *desidera* il sabato libero ma in fondo
non ne fa una richiesta vincolante, salva il vincolo come SOFT
con un peso (per esempio 50). Se invece \`e impegnata altrove
sabato e proprio non pu\`o esserci, salvalo HARD.

---

## Aggiungiamo dettaglio: massimo 4 ore al giorno

Adesso supponiamo che Rossi voglia che, **anche negli altri
giorni**, non le diamo mai pi\`u di 4 ore in un solo giorno. La
giornata \`e troppo pesante.

Adesso ci serve un concetto nuovo: **contare** le lezioni.
Vogliamo dire: per ogni giorno della settimana, le lezioni di
Rossi quel giorno devono essere al massimo 4. Si scrive cos\`i:

```dsl
forall d in days:
    count l in lessons where l.teacher == Rossi
                          and l.day == d.index: l <= 4
```

La struttura \`e: per ogni giorno \texttt{d} (i 6 giorni della
settimana), conta quante lezioni di Rossi cadono in quel giorno
e richiedi che siano al massimo 4. Il \texttt{count} \`e proprio
il "conteggio" — l'analogo di un foglio Excel in cui filtri per
nome docente e per giorno e leggi quanti righe sono rimaste.

Questo \`e il pattern pi\`u comune di tutti per esprimere un
limite di carico:

> "**Per ogni** unit\`a-base (giorno, classe, materia, slot, \dots)
> il **numero** di lezioni che soddisfano una certa condizione
> non deve superare N."

Quasi tutte le regole numeriche dell'orario si scrivono cos\`i,
cambiando solo l'unit\`a-base e la condizione del filtro.

---

## Pattern: ogni docente di una materia, esattamente 1 ora in
> laboratorio

Un caso classico: tutti i docenti di Fisica, durante la
settimana, devono avere **esattamente** un'ora in un'aula di
tipo laboratorio fisica. Sono tante regole, una per docente, e
non vogliamo scriverle a mano una per una. Anche qui usiamo
\texttt{forall}, ma stavolta scorriamo i **docenti**:

```dsl
forall t in teachers where t.subject == "Fisica":
    count l in lessons where l.teacher == t
                          and l.classroom.type == "lab_fisica":
        l == 1
```

Leggiamolo: per ogni docente \texttt{t} la cui materia
\`e "Fisica" (notate le virgolette: \`e una stringa con accenti
o meno, mettiamo le virgolette per chiarezza), conta le lezioni
che hanno \texttt{t} come docente e si tengono in un'aula di
tipo \texttt{lab\_fisica}. Quel conteggio deve essere uguale a 1.

Due piccole cose nuove:

- \texttt{t.subject} restituisce la **lista** delle materie del
  docente (un docente potrebbe insegnare due materie). Quando
  scrivi \texttt{t.subject == "Fisica"}, il programma intende:
  "Fisica appartiene a quella lista". \`E un'abbreviazione
  comoda; equivale a \texttt{"Fisica" in t.subjects}.
- \texttt{l.classroom.type} \`e il "tipo" dell'aula (standard,
  palestra, lab\_fisica, lab\_chimica, biblioteca, \dots).
  L'attributo \texttt{type} viene risolto automaticamente: il
  programma sa che ogni aula ha un tipo associato e lo legge
  dall'anagrafica delle aule.

Se anzich\'e *almeno* uno volessi *al massimo* uno, useresti
\texttt{l <= 1} invece di \texttt{l == 1}. Se volessi almeno
due, \texttt{l >= 2}.

---

## Quando ti serve la condizione "se\dots allora\dots"

A volte la regola non \`e "tutti fanno X" ma "se accade A,
allora deve accadere anche B". Esempio: se la prof Rossi ha
almeno una lezione in 3A, vogliamo che almeno una di quelle
lezioni sia in lab di fisica (perch\'e ha programmato un'attivit\`a
di laboratorio). Si scrive con la freccia \texttt{=>} (si legge
"implica" o "se\dots allora\dots"):

```dsl
(exists l in lessons:
    l.teacher == Rossi and l.class == 3A)
=>
(exists l2 in lessons:
    l2.teacher == Rossi and l2.class == 3A
    and l2.classroom.type == "lab_fisica")
```

Leggiamo: **se** esiste almeno una lezione di Rossi in 3A,
**allora** deve anche esistere almeno una lezione di Rossi in
3A che si tiene in lab di fisica. Notate che le due lezioni
non devono per forza essere la stessa: una pu\`o essere normale
e l'altra in lab. Per questo le abbiamo chiamate \texttt{l} e
\texttt{l2} (nomi diversi).

L'operatore \texttt{exists x in ...:} significa "esiste almeno
un \texttt{x} per cui vale\dots". \`E il fratello di
\texttt{forall}: dove \texttt{forall} chiede "vale per tutti?",
\texttt{exists} chiede "vale per qualcuno?".

---

## Le aule: capienza, tipo, etichette

I vincoli sulle aule sono semplici da esprimere. Tre esempi
tipici.

**Lab Fisica 1 ospita una sola classe per slot** (capienza
massima):

```dsl
forall s in slots:
    count l in lessons where l.classroom == "Lab Fisica 1"
                          and l.day == s.day
                          and l.hour == s.hour:
        l <= 1
```

Per ogni slot della settimana (i 36 \texttt{(giorno, ora)}
possibili), le lezioni che usano "Lab Fisica 1" in quel preciso
slot devono essere al massimo una.

**La palestra ospita solo Scienze motorie**:

```dsl
forall l in lessons where l.classroom.type == "palestra":
    l.subject == Scienzemotorie
```

Per ogni lezione che si tiene in un'aula di tipo palestra, la
materia deve essere Scienze motorie.

**Storia delle terze e oltre richiede aula con proiettore**.
piTantum supporta etichette libere ("tag") sulle aule, che il
coordinatore d'orario assegna manualmente o che il sistema
attribuisce automaticamente. Se hai etichettato alcune aule
come "proiettore", puoi pretendere che le lezioni di Storia
nelle classi 3, 4, 5 si tengano in una di quelle:

```dsl
forall l in lessons where l.subject == Storia
                       and l.class.year >= 3:
    "proiettore" in l.classroom.tags
```

L'operatore \texttt{in} dice "appartiene a"; \texttt{l.classroom.tags}
\`e la lista delle etichette dell'aula della lezione.

---

## Vincoli pi\`u intelligenti: ore consecutive

Capita di voler imporre che certe materie abbiano almeno una
volta a settimana **due ore consecutive** (per esempio per
matematica nelle classi del triennio, dove una verifica scritta
ha bisogno di pi\`u tempo).

```dsl
forall c in classes where c.year >= 4:
    exists s1 in slots: exists s2 in slots:
        consecutive(s1, s2)
        and lesson(class==c.name, day==s1.day,
                   hour==s1.hour, subject==Matematica)
        and lesson(class==c.name, day==s2.day,
                   hour==s2.hour, subject==Matematica)
```

Leggiamo: per ogni classe \texttt{c} del quarto e quinto anno,
deve esistere una coppia di slot \texttt{s1} e \texttt{s2}
**consecutivi** (cio\`e nella stessa giornata e con ore adiacenti)
in cui la classe abbia matematica in entrambi.

Il pezzo \texttt{lesson(class==c.name, day==..., hour==..., subject==Matematica)}
\`e una scorciatoia: equivale a "esiste una lezione che ha tutti
questi attributi". \`E pi\`u corto e leggibile della versione
con \texttt{exists} esplicito.

\texttt{consecutive(s1, s2)} \`e una funzione del programma che
restituisce vero se i due slot sono nello stesso giorno e
distanti esattamente un'ora.

---

## Tag sugli studenti: il caso BES

piTantum permette di attaccare etichette anche agli studenti, per
esempio per indicare bisogni educativi speciali (BES), debiti
formativi, partecipazione ad alternanza, status di studente-atleta.
Una volta etichettati, possiamo scrivere regole molto specifiche.

**Esempio**: tutti gli studenti con tag \texttt{BES} devono essere
inseriti in un gruppo chiamato "Sostegno":

```dsl
forall s in students where "BES" in s.tags:
    exists g in s.groups: g.name == "Sostegno"
```

Per ogni studente \texttt{s} la cui lista di tag contiene "BES",
deve esistere almeno un gruppo \texttt{g} di cui \`e membro che si
chiama "Sostegno".

Notate: \texttt{s.groups} \`e la lista dei gruppi di
appartenenza dello studente. Possiamo iterarla con
\texttt{exists g in s.groups} grazie a una piccola estensione del
linguaggio che permette di scorrere non solo "tutti i docenti" o
"tutte le lezioni", ma anche una lista raggiunta tramite un
attributo (\texttt{s.groups}, \texttt{l.classroom.tags}, ecc.).

**Esempio**: gli studenti BES non hanno mai lezione il sabato.
Visto che gli studenti non sono direttamente "in lezione" (sono
le classi a esserlo), la regola attraversa i due livelli:

```dsl
forall l in lessons:
    forall s in students where l.class == s.class
                            and "BES" in s.tags:
        l.day != 6
```

"Per ogni lezione, e per ogni studente di quella classe che ha il
tag BES, il giorno della lezione non deve essere sabato."

---

## Una galleria di trenta esempi

Sotto trovi una collezione di regole pronte all'uso, raggruppate
per tipo di destinatario (docente, classe, aula, materia,
gruppo, relazionali). Ogni esempio \`e stato testato
automaticamente sul motore corrente: copia-incolla nell'editor
del modal "+ Nuovo vincolo DSL" e funziona.

### Vincoli che riguardano un docente (10 esempi)

**E1. Borghi non insegna mai in 1A alla 6a ora.** Comodo per
prof che hanno gi\`a una richiesta specifica di "non in 6a per
quella classe".

```dsl
forall l in lessons where l.teacher == Borghi and l.class == 1A:
    l.hour != 13
```

**E2. Borghi: massimo 4 ore al giorno (totali).** Limite di
carico giornaliero.

```dsl
forall d in days:
    count l in lessons where l.teacher == Borghi
                          and l.day == d.index: l <= 4
```

**E3. Ogni docente di Fisica: esattamente 1 ora settimanale in
lab fisica.** Regola "di reparto" per i docenti di una stessa
materia.

```dsl
forall t in teachers where t.subject == "Fisica":
    count l in lessons where l.teacher == t
                          and l.classroom.type == "lab_fisica":
        l == 1
```

**E4. Tetto della cattedra di Inglese: 18 ore settimanali.**

```dsl
forall t in teachers where t.subject == "Inglese":
    count l in lessons where l.teacher == t: l <= 18
```

**E5. Rossi non lavora il sabato (HARD).**

```dsl
forall l in lessons where l.teacher == Rossi and l.day == 6: false
```

**E6. Rossi: al massimo 1 sesta ora a settimana.**

```dsl
count l in lessons where l.teacher == Rossi and l.hour == 13: l <= 1
```

**E7. Tutti i docenti della classe di concorso A050: max 5
ore/giorno.**

```dsl
forall t in teachers where t.group == "A050":
    forall d in days:
        count l in lessons where l.teacher == t
                              and l.day == d.index: l <= 5
```

**E8. Coupling: se Rossi insegna a 3A, allora anche Bianchi
deve insegnare a 3B.** Vincolo logico fra cattedre — utile per
allineamenti voluti dalla didattica.

```dsl
(exists l in lessons: l.teacher == Rossi and l.class == 3A)
=> (exists l in lessons: l.teacher == Bianchi and l.class == 3B)
```

**E9. Rossi non in palestra (mai).** Vincolo docente x tipo
aula.

```dsl
forall l in lessons where l.teacher == Rossi:
    l.classroom.type != "palestra"
```

**E10. Tutti i docenti di matematica: almeno una lezione di
mattina (entro la 9).**

```dsl
forall t in teachers where t.subject == "Matematica":
    exists l in lessons where l.teacher == t: l.hour <= 9
```

### Vincoli che riguardano una classe (5 esempi)

**E11. La 1A non lavora il sabato.**

```dsl
forall l in lessons where l.class == 1A: l.day != 6
```

**E12. Le prime: massimo 5 ore al giorno.**

```dsl
forall c in classes where c.year == 1:
    forall d in days:
        count l in lessons where l.class == c.name
                              and l.day == d.index: l <= 5
```

**E13. Quarte e quinte: due ore consecutive di matematica a
settimana.**

```dsl
forall c in classes where c.year >= 4:
    exists s1 in slots: exists s2 in slots:
        consecutive(s1, s2)
        and lesson(class==c.name, day==s1.day,
                   hour==s1.hour, subject==Matematica)
        and lesson(class==c.name, day==s2.day,
                   hour==s2.hour, subject==Matematica)
```

**E14. Indirizzo Linguistico anno 1: niente sabato.**

```dsl
forall l in lessons where l.class.curriculum == Linguistico
                       and l.day == 6: false
```

**E15. 1A: religione solo nelle prime 4 ore.**

```dsl
forall l in lessons where l.class == 1A and l.subject == Religione:
    l.hour <= 11
```

### Vincoli che riguardano un'aula (5 esempi)

**E16. Lab Fisica 1: una sola lezione per slot.**

```dsl
forall s in slots:
    count l in lessons where l.classroom == "Lab Fisica 1"
                          and l.day == s.day
                          and l.hour == s.hour: l <= 1
```

**E17. Matematica solo in aule taggate "matematica".**

```dsl
forall l in lessons where l.subject == Matematica:
    "matematica" in l.classroom.tags
```

**E18. Storia delle terze e oltre: aula con proiettore.**

```dsl
forall l in lessons where l.subject == Storia and l.class.year >= 3:
    "proiettore" in l.classroom.tags
```

**E19. La palestra ospita solo Scienze motorie.**

```dsl
forall l in lessons where l.classroom.type == "palestra":
    l.subject == Scienzemotorie
```

**E20. Lab chimica: massimo 2 lezioni concorrenti per slot
(due gruppi a "compresenza" se necessario).**

```dsl
forall s in slots:
    count l in lessons where l.classroom.type == "lab_chimica"
                          and l.day == s.day
                          and l.hour == s.hour: l <= 2
```

### Vincoli che riguardano una materia (3 esempi)

**E21. Matematica distribuita: massimo 2 ore al giorno per
classe.** Spalma le ore di mate su pi\`u giorni.

```dsl
forall c in classes:
    forall d in days:
        count l in lessons where l.class == c.name
                              and l.subject == Matematica
                              and l.day == d.index: l <= 2
```

**E22. Matematica preferibilmente entro la 5a ora.**

```dsl
forall l in lessons where l.subject == Matematica: l.hour <= 12
```

**E23. Educazione fisica solo in palestra.**

```dsl
forall l in lessons where l.subject == Educazionefisica:
    l.classroom.type == "palestra"
```

### Vincoli che riguardano gruppi e studenti (3 esempi)

**E24. Studenti BES devono essere in un gruppo "Sostegno".**

```dsl
forall s in students where "BES" in s.tags:
    exists g in s.groups: g.name == "Sostegno"
```

**E25. Studenti con debito di matematica al quarto anno:
gruppo "Recupero Matematica".**

```dsl
forall s in students where "debito_matematica_4" in s.tags:
    exists g in s.groups: g.name == "Recupero Matematica"
```

**E26. Studenti BES: nessuna lezione il sabato.**

```dsl
forall l in lessons:
    forall s in students where l.class == s.class
                            and "BES" in s.tags:
        l.day != 6
```

### Vincoli relazionali e di coupling (4 esempi)

**E27. Rossi in Aula 12: solo Matematica.** Combina docente,
aula, materia in una sola regola.

```dsl
forall l in lessons where l.teacher == Rossi and l.classroom == "Aula 12":
    l.subject == Matematica
```

**E28. Se Rossi insegna in 3A, deve usare lab fisica almeno una
volta.**

```dsl
(exists l in lessons: l.teacher == Rossi and l.class == 3A)
=>
(exists l2 in lessons: l2.teacher == Rossi and l2.class == 3A
                    and l2.classroom.type == "lab_fisica")
```

**E29. Inglese alle prime: max 3 ore/settimana per la coppia
(docente, classe).**

```dsl
forall t in teachers where t.subject == "Inglese":
    forall c in classes where c.year == 1:
        count l in lessons where l.teacher == t
                              and l.class == c.name: l <= 3
```

**E30. Religione alle prime: mai in 1a ora.**

```dsl
forall l in lessons where l.subject == Religione
                       and l.class.year == 1:
    l.hour != 8
```

---

## Avvertenze e consigli pratici

> **Attenzione: HARD pu\`o rendere infeasible.** Se metti tanti
> vincoli HARD, prima o poi alcuni si scontrano e nessuna soluzione
> li rispetta tutti. In quel caso piTantum te lo dice e ti aiuta
> a capire qual \`e il pacchetto minimo di vincoli "in
> conflitto" (la funzione "Pre-check fattibilit\`a" del tab
> Workflow). Tendenzialmente: HARD per vincoli normativi e
> contrattuali; SOFT per preferenze, anche forti.

> **Attenzione: scala combinatoria.** Quando annidi tanti
> \texttt{forall} e iteri su lezioni \times docenti \times slot,
> il numero di valutazioni cresce molto. piTantum ti avverte se
> superi un limite ragionevole (un milione di "atomi"). Quando
> succede, sposta i filtri pi\`u specifici nel \texttt{where}
> pi\`u esterno per ridurre il volume, oppure spezza il vincolo
> in due regole pi\`u semplici.

> **Suggerimento: prova prima con SOFT alto.** Se non sei sicuro
> che una regola sia rispettabile, salvala SOFT con un peso alto
> (es. 1000). Il solver tender\`a a rispettarla; se fallisce,
> vedi nel report SOFT quante violazioni ci sono e capisci se
> il vincolo era troppo stringente.

---

## Modificare un vincolo, validarlo, eliminarlo

Tutti i vincoli scritti in questo linguaggio sono gestiti dal
tab **Vincoli** della web app. Per ognuno puoi:

- **Vedere** il testo, il livello (HARD/SOFT/PREFERRED/ENFORCED),
  il peso, e a chi \`e applicato.
- **Modificare** (apri il modal, cambi il testo, premi Salva: una
  validazione live ti dice subito se la sintassi \`e corretta).
- **Eliminare** (con conferma).
- **Validare senza salvare**: nel modal "+ Nuovo vincolo DSL"
  trovi un pulsante "Convalida" che esegue il parser e ti dice
  se l'espressione ha senso.
- **Cercare**: il pannello "Ricerca" trova tutti i vincoli che
  menzionano un docente, una classe o un'aula precisa, ovunque
  siano stati creati.

---

## Glossario rapido

- **HARD** — vincolo che il programma non viola mai.
- **SOFT** — vincolo che il programma cerca di rispettare ma pu\`o
  violare pagando una penalit\`a.
- **PREFERRED** — preferenza che d\`a un bonus se rispettata, ma
  non penalizza se violata.
- **ENFORCED** — variante di HARD per vincoli "che devono
  esistere" (es. una lezione che deve esserci).
- **lezione** — una singola ora-lezione fisica nell'orario
  settimanale: docente \times classe \times materia \times
  giorno \times ora \times aula.
- **cattedra (assignment)** — l'assegnazione di un docente a una
  classe per una materia con un certo monte ore settimanale.
- **slot** — una coppia (giorno, ora). Un giorno tipico ha 6
  slot (8\textsuperscript{o}, 9\textsuperscript{o}, \dots,
  13\textsuperscript{o}); la settimana ne ha 36.
- **tag** — etichetta libera che il coordinatore attacca a
  un'aula o a uno studente per esprimere caratteristiche
  trasversali (es. "proiettore" su un'aula, "BES" su uno
  studente).
- **infeasible** — un modello \`e infeasible se non esiste
  alcuna soluzione che rispetti tutti i vincoli HARD.

Per il glossario completo del sistema vedi
[`docs/glossario.md`](glossario.md).

---

# Appendici tecniche

> Le sezioni seguenti sono per chi vuole comprendere la sintassi
> in modo formale o sviluppare integrazioni. Se non sei un
> programmatore, puoi tranquillamente saltarle.

## A. Grammatica BNF formale

Il parser \`e un ricorsivo discendente implementato in
`webui/backend/utils/general_dsl.py`. La grammatica formale (BNF
informale, in stile EBNF):

```bnf
expr           ::= iff_expr
iff_expr       ::= implies_expr ( "<=>" implies_expr )*
implies_expr   ::= or_expr     ( "=>"  or_expr )*
or_expr        ::= and_expr    ( ("OR"|"or") and_expr )*
and_expr       ::= not_expr    ( ("AND"|"and") not_expr )*
not_expr       ::= ("NOT"|"not") not_expr | atom

atom           ::= quant_expr | count_expr | comparison
                 | call | bool_lit | "(" expr ")"

quant_expr     ::= ("forall"|"exists") IDENT "in" source
                   ["where" or_expr] ":" expr

count_expr     ::= "count" IDENT "in" source ["where" or_expr]
                   ( ":" comparison | op value )

source         ::= IDENT
                 | IDENT ("." IDENT)+

comparison     ::= value ( op value
                         | "in" "[" value ("," value)* "]"
                         | "in" path
                         | "not_in" "[" value ("," value)* "]"
                         | "not_in" path )

op             ::= "==" | "!=" | "<" | "<=" | ">" | ">="
value          ::= IDENT ( "." IDENT )* | NUM | STRING
                 | BOOL | function_call

function_call  ::= IDENT "(" [arg_list] ")"
arg_list       ::= arg ("," arg)*
arg            ::= IDENT "==" value | value
```

Precedenze, dalla pi\`u bassa alla pi\`u alta:
`<=>`, `=>`, `OR`, `AND`, `NOT`, confronti (`==` `!=` `<` `<=` `>` `>=`
`in` `not_in`), accesso a membro (`.`). Le parentesi sovrascrivono.

### Note di tokenizzazione

- `=` da solo viene normalizzato a `==` (per friendlyness).
- Identificatori che iniziano con cifra ma contengono almeno una
  lettera (`1A`, `3B_scientifico`, `lun8`) sono trattati come
  IDENT.
- I commenti iniziano con `#` e vanno fino a fine riga.
- Stringhe quotate `"..."` o `'...'` sono letterali.

## B. Reference completo degli attributi per entit\`a

### Lesson (lezione concreta nell'orario)

| Attributo            | Tipo       | Esempio              |
| -------------------- | ---------- | -------------------- |
| `teacher`            | str        | `l.teacher`          |
| `class`              | str        | `l.class`            |
| `subject`            | str        | `l.subject`          |
| `day`                | int 1-6    | `l.day`              |
| `hour`               | int 8-13   | `l.hour`             |
| `classroom`          | str        | `l.classroom`        |
| `classroom.type`     | str        | `l.classroom.type`   |
| `classroom.tags`     | list[str]  | `"lab" in l.classroom.tags` |
| `class.curriculum`   | str        | `l.class.curriculum` |
| `class.year`         | int        | `l.class.year`       |

### Assignment (cattedra)

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
| `subject` / `subjects` | list[str] | `"Mate" in t.subject`   |
| `graduatoria_score` | float      |                            |

### SchoolClass

| Attributo     | Tipo  | Esempio              |
| ------------- | ----- | -------------------- |
| `name`        | str   | `c.name == "1A"`     |
| `year`        | int   | `c.year >= 4`        |
| `section`     | str?  |                      |
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

### Subject / Curriculum / Group / Student / Slot / Day / Hour

| Attributo         | Tipo       | Esempio              |
| ----------------- | ---------- | -------------------- |
| `Subject.name`    | str        | `s.name == "Mate"`   |
| `Curriculum.name`, `.code`, `.score` | str/float | `cu.code == "Scientifico"` |
| `Group.name`, `.kind` | str    | `g.kind == "language"` |
| `Student.id`, `.name`, `.last_name`, `.first_name`, `.class`, `.tags`, `.groups` | misti | `"BES" in s.tags` |
| `Slot.day`, `.hour` | int      |                      |
| `Day.index`, `.name` | int/str | `d.index`            |
| `Hour.index`      | int 8-13   |                      |

## C. Endpoint REST

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
