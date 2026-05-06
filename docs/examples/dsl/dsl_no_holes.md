# DSL example: no holes / no buchi

## 🇮🇹 Caso d'uso

La classe **3B** del Liceo Scientifico ha un orario denso e
deve evitare i buchi. ``Niente buchi'' significa che, per ogni
giornata in cui la 3B ha lezione, le ore occupate devono essere
contigue: se la classe ha la prima ora alle 8 e l'ultima alle
12, allora anche le ore intermedie (9, 10, 11) devono avere
una lezione assegnata. Una giornata libera (zero ore) e'
ammessa, una giornata con buchi no.

Tipicamente questo vincolo nasce per due motivi:

- gli studenti minorenni non possono ``uscire e rientrare''
  per legge in molte regioni;
- una classe con un buco si dovrebbe trovare un'aula libera
  per studio assistito, e l'aula raramente c'e'.

### Path UI

Tab **Vincoli** → modale **+ Nuovo vincolo DSL**. Compila:

- *Etichetta*: ``3B no buchi``
- *Tipo*: ``hard``
- *Espressione*: la stringa DSL qui sotto.

Premi **Valida**, poi **Salva**.

### DSL canonico

```
no_holes_class("3B")
```

### DSL verboso (equivalente)

Senza il pragma canonico, la stessa semantica si esprime con un
`forall` annidato che, per ogni giorno e per ogni terna di ore
$(h_1, h_2, h_3)$ con $h_1 < h_2 < h_3$, vieta la situazione
``occupato in $h_1$, libero in $h_2$, occupato in $h_3$'':

```
forall d in days:
    forall h1 in hours: forall h2 in hours: forall h3 in hours:
        (h1 < h2 and h2 < h3
         and exists l in lessons where l.class == "3B"
              and l.day == d and l.hour == h1
         and (count l in lessons where l.class == "3B"
              and l.day == d and l.hour == h2 == 0)
         and exists l in lessons where l.class == "3B"
              and l.day == d and l.hour == h3)
        => false
```

Il pragma canonico produce una **catena non-crescente di
booleani** molto piu' compatta: per ogni $h$ in 8..13, una
variabile $b_{d,h} = 1$ se la classe e' occupata in $(d, h)$;
poi il vincolo $b_{d,h-1} \geq b_{d,h} \wedge b_{d,h+1}$
applicato in modo opportuno.

### Output CP-SAT (cosa emette il compilatore)

Per ciascun giorno $d \in \{1, ..., 6\}$ il compilatore aggiunge
al modello:

- una variabile booleana ``busy[3B, d, h]`` per ogni $h \in
  \{8, ..., 13\}$, riassunto della disgiunzione delle ``slot''
  della 3B in quell'ora.
- ``busy[3B, d, 8] >= busy[3B, d, 9]`` quando ``busy[3B, d, 8]
  = 0`` e ``busy[3B, d, 9] = 1`` (la classe non puo' iniziare
  in ritardo se non c'era prima... la formulazione standard
  e' la **chain non-crescente** che CP-SAT applica come
  AddImplication nella forma ``slot_at_h2 → slot_at_h1`` per
  $h_1 < h_2$).

L'encoding finale equivale a quello legacy di
`add_class_no_holes`. Verificato in
`tests/test_dsl_canonical_patterns.py::test_no_holes_zero_drift`.

---

## 🇬🇧 Use case

Class **3B** of the science high school has a dense schedule
and must avoid gaps. "No gaps" means that on every day where
3B has any lesson the busy hours must be contiguous: if the
class has its first hour at 8:00 and its last at 12:00, then
hours 9, 10 and 11 must all be busy too. A fully free day (zero
hours) is allowed; a day with gaps is not.

This rule typically comes from two reasons:

- minors cannot legally "leave and come back" mid-day in many
  regions;
- a class with a gap would need an empty classroom for assisted
  study, which is rarely available.

### UI path

Tab **Constraints** → modal **+ New DSL constraint**. Fill in:

- *Label*: "3B no gaps"
- *Kind*: `hard`
- *Expression*: the DSL string below.

Click **Validate**, then **Save**.

### Canonical DSL

```
no_holes_class("3B")
```

### Verbose DSL (equivalent)

Without the canonical pragma the same semantics requires nested
`forall` that, for every day and every triple of hours
$(h_1, h_2, h_3)$ with $h_1 < h_2 < h_3$, forbid the case "busy
at $h_1$, free at $h_2$, busy at $h_3$":

```
forall d in days:
    forall h1 in hours: forall h2 in hours: forall h3 in hours:
        (h1 < h2 and h2 < h3
         and exists l in lessons where l.class == "3B"
              and l.day == d and l.hour == h1
         and (count l in lessons where l.class == "3B"
              and l.day == d and l.hour == h2 == 0)
         and exists l in lessons where l.class == "3B"
              and l.day == d and l.hour == h3)
        => false
```

The canonical pragma yields a **non-increasing chain of
booleans** that is far more compact: for every $h$ in 8..13 a
boolean ``busy[3B, d, h] = 1`` if the class is busy at
$(d, h)$, then the chain implication ``slot_at_h_2 →
slot_at_h_1`` for $h_1 < h_2$.

### CP-SAT output (what the compiler emits)

For each day $d \in \{1, \ldots, 6\}$ the compiler adds:

- a boolean ``busy[3B, d, h]`` for each $h$ in 8..13, the
  disjunction of 3B's slot variables at that hour;
- ``AddImplication(slot_at_h_2, slot_at_h_1)`` for every
  $h_1 < h_2$ within the day, enforcing that if a later hour is
  busy then every earlier hour is busy too.

The final encoding equals the legacy `add_class_no_holes`.
Validated by
`tests/test_dsl_canonical_patterns.py::test_no_holes_zero_drift`.
