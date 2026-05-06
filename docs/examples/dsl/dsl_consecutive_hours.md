# DSL example: consecutive hours / ore consecutive

## 🇮🇹 Caso d'uso

La classe **3A** di un Liceo Scientifico deve avere
**3 ore consecutive di Matematica** in qualche giorno della
settimana, perche' il coordinatore vuole un blocco lungo per
l'analisi reale (non spezzato in tre lezioni separate). In
contrasto, le 2 ore di **Scienze motorie** della 3A devono
essere **staccate** (mai due ore consecutive nello stesso
giorno), perche' la palestra ha pochi turni disponibili e
lasciare un blocco da due ore impegnerebbe risorse che servono
ad altre classi.

I due vincoli si specificano da due regole DSL distinte. Sono
indipendenti l'una dall'altra.

### Path UI

Tab **Vincoli** → modale **+ Nuovo vincolo DSL**. Salva due
regole separate (entrambe `hard`):

- ``3A: 3 ore consecutive di Mate``
- ``3A: motoria mai consecutiva``

### DSL: 3 ore consecutive di Matematica

```
exists d in days:
    exists h in hours where h <= 11:
        exists l1 in lessons where l1.class == "3A"
            and l1.subject == "Matematica"
            and l1.day == d and l1.hour == h:
        exists l2 in lessons where l2.class == "3A"
            and l2.subject == "Matematica"
            and l2.day == d and l2.hour == h + 1:
        exists l3 in lessons where l3.class == "3A"
            and l3.subject == "Matematica"
            and l3.day == d and l3.hour == h + 2:
            true
```

Versione equivalente che usa il predicato `consecutive`
(introdotto in Step 3a) -- piu' breve ma logicamente identica:

```
exists s1 in slots: exists s2 in slots: exists s3 in slots:
    consecutive(s1, s2) and consecutive(s2, s3)
    and lesson(class=="3A", day==s1.day,
               hour==s1.hour, subject=="Matematica")
    and lesson(class=="3A", day==s2.day,
               hour==s2.hour, subject=="Matematica")
    and lesson(class=="3A", day==s3.day,
               hour==s3.hour, subject=="Matematica")
```

### DSL: motoria mai consecutiva

```
forall d in days:
    forall h in hours where h <= 12:
        not (
            exists l1 in lessons where l1.class == "3A"
                and l1.subject == "Scienzemotorie"
                and l1.day == d and l1.hour == h
            and
            exists l2 in lessons where l2.class == "3A"
                and l2.subject == "Scienzemotorie"
                and l2.day == d and l2.hour == h + 1
        )
```

### Output CP-SAT

Per **mate consecutive** il compilatore introduce, per ogni
finestra di 3 ore consecutive in ciascun giorno, una variabile
booleana ``win[d, h]`` legata a ``slot_3A_mate_d_h
∧ slot_3A_mate_d_{h+1} ∧ slot_3A_mate_d_{h+2}``, e impone
``Or(win[d, h] for d, h: h<=11) >= 1``. CP-SAT linearizza l'AND
con vincoli ausiliari (3 implicazioni per ``win = 1`` e una
per ``win = 0``).

Per **motoria mai consecutiva** il compilatore aggiunge invece
un solo vincolo per ogni coppia di ore adiacenti dello stesso
giorno: ``slot_3A_mot_d_h + slot_3A_mot_d_{h+1} <= 1``. Niente
variabile ausiliaria; e' la stessa formulazione che il legacy
`add_motorie_pair` con `mode=forbid_pair` produrrebbe.

Nota su `consecutive`: quando il predicato e' usato all'interno
di un `forall` o `exists` con argomenti staticamente legati al
quantificatore, il compilatore lo valuta a tempo di
compilazione (controllo $|h_1 - h_2| = 1 \wedge d_1 = d_2$);
quando uno degli argomenti e' un'espressione runtime non
risolvibile staticamente, il compilatore emette il diagnostico
``consecutive: dynamic args -- not yet supported in CP-SAT
backend``.

---

## 🇬🇧 Use case

Class **3A** of a science high school must have **3 consecutive
hours of Mathematics** on some weekday, because the coordinator
wants a long block for real analysis (not split into three
separate one-hour lessons). In contrast, the 2 hours of
**Physical Education** for 3A must be **non-consecutive** on
every day (never adjacent), because the gym has few free slots
and a 2-hour block would tie up resources needed by other
classes.

The two constraints are expressed as two separate DSL rules,
independent of each other.

### UI path

Tab **Constraints** → modal **+ New DSL constraint**. Save two
separate rules (both `hard`):

- "3A: 3 consecutive hours of Math"
- "3A: PE never consecutive"

### DSL: 3 consecutive hours of Math

```
exists d in days:
    exists h in hours where h <= 11:
        exists l1 in lessons where l1.class == "3A"
            and l1.subject == "Matematica"
            and l1.day == d and l1.hour == h:
        exists l2 in lessons where l2.class == "3A"
            and l2.subject == "Matematica"
            and l2.day == d and l2.hour == h + 1:
        exists l3 in lessons where l3.class == "3A"
            and l3.subject == "Matematica"
            and l3.day == d and l3.hour == h + 2:
            true
```

Equivalent shorter form using the `consecutive` predicate
(introduced in Step 3a):

```
exists s1 in slots: exists s2 in slots: exists s3 in slots:
    consecutive(s1, s2) and consecutive(s2, s3)
    and lesson(class=="3A", day==s1.day,
               hour==s1.hour, subject=="Matematica")
    and lesson(class=="3A", day==s2.day,
               hour==s2.hour, subject=="Matematica")
    and lesson(class=="3A", day==s3.day,
               hour==s3.hour, subject=="Matematica")
```

### DSL: PE never consecutive

```
forall d in days:
    forall h in hours where h <= 12:
        not (
            exists l1 in lessons where l1.class == "3A"
                and l1.subject == "Scienzemotorie"
                and l1.day == d and l1.hour == h
            and
            exists l2 in lessons where l2.class == "3A"
                and l2.subject == "Scienzemotorie"
                and l2.day == d and l2.hour == h + 1
        )
```

### CP-SAT output

For **consecutive math** the compiler introduces, for each
3-hour window of each day, a boolean ``win[d, h]`` tied to
``slot_3A_math_d_h ∧ slot_3A_math_d_{h+1}
∧ slot_3A_math_d_{h+2}`` and imposes ``Or(win[d, h] for d, h:
h<=11) >= 1``. CP-SAT linearises the AND with auxiliary
constraints (three implications for ``win = 1``, one for
``win = 0``).

For **non-consecutive PE** the compiler adds a single
constraint per adjacent-hour pair on each day:
``slot_3A_pe_d_h + slot_3A_pe_d_{h+1} <= 1``. No auxiliary
variable; it is the same formulation produced by the legacy
`add_motorie_pair` with `mode=forbid_pair`.

Note on `consecutive`: when the predicate is used inside a
`forall`/`exists` with arguments statically bound to the
quantifier, the compiler evaluates it at compile time (the
check is $|h_1 - h_2| = 1 \wedge d_1 = d_2$); when one argument
is a runtime expression not statically resolvable the compiler
emits the diagnostic ``consecutive: dynamic args -- not yet
supported in CP-SAT backend``.
