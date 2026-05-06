# DSL example: plesso commuting / spostamento fra plessi

## 🇮🇹 Caso d'uso

L'IIS ``Galileo'' e' distribuito su due edifici:

- **Plesso 1 -- Sede Centrale** (centro citta');
- **Plesso 2 -- Succursale Via Garibaldi** (a 1 km di
  distanza, raggiungibile in $\sim$15 minuti a piedi).

Tre regole di commuting si applicano:

1. **Gap 0**: nessun vincolo. Default per la maggior parte
   dei docenti che insegnano in entrambi i plessi senza
   limiti.
2. **Gap 1 ora**: tra una lezione in Centrale e una in
   Garibaldi (o viceversa) deve passare almeno un'ora di
   buco. Vale per i docenti anziani con difficolta' di
   spostamento.
3. **Gap solo durante la pausa pranzo**: fra le 12 e le 13
   c'e' una pausa naturale (mensa); il cambio di plesso e'
   ammesso solo se cade dentro questa finestra. Vale per
   alcuni docenti specifici.

In questo esempio mostriamo la regola **gap 1 ora,
kind=teacher, kind-wide** (vale per tutti i docenti).

### Path UI

Tab **Plessi** → sezione **Commuting Rules** → bottone
**Aggiungi regola**. Compila:

- *From plesso*: Centrale (id 1)
- *To plesso*: Garibaldi (id 2)
- *Entity kind*: teacher
- *Entity ID*: (lascia vuoto: kind-wide)
- *Min gap hours*: 1
- *Symmetric*: si

Quando salvi, la regola e' visibile nel modulo
``commuting_rules`` e applicata dal solver di
classroom-assignment.

### DSL canonico (helper-generated)

La helper
``engine/dsl_translator.py::plesso_commuting_rule_to_dsl(rule)``
emette automaticamente le seguenti due clausole DSL (per la
direzione Centrale → Garibaldi e per la direzione
simmetrica):

```
forall l1 in lessons where l1.classroom.plesso == 1:
    forall l2 in lessons where l2.classroom.plesso == 2
                          and l2.teacher == l1.teacher
                          and consecutive(l1.slot, l2.slot):
        false
```

```
forall l1 in lessons where l1.classroom.plesso == 2:
    forall l2 in lessons where l2.classroom.plesso == 1
                          and l2.teacher == l1.teacher
                          and consecutive(l1.slot, l2.slot):
        false
```

### DSL verboso (forma esplicita per ora-per-ora)

Senza il path `l.classroom.plesso` (introdotto in Step 3a) la
stessa regola richiederebbe di enumerare le aule appartenenti
a ciascun plesso e scriverle nel `where`:

```
forall l1 in lessons
    where l1.classroom in ["A1", "A2", "A3", "B1", "B2"]:
    forall l2 in lessons
        where l2.classroom in ["G1", "G2", "G3", "G4"]
          and l2.teacher == l1.teacher
          and l2.day == l1.day
          and l2.hour == l1.hour + 1:
        false
```

E' verboso, fragile (l'aggiunta di una nuova aula richiede di
aggiornare la stringa) e perde la simmetria che il path
risolve trasparentemente.

### Output CP-SAT

Il compilatore risolve l'aula assegnata di ogni lezione tramite
la mappa ``classroom_for_slot``, che il solver di
classroom-assignment ha calcolato in pipeline. Per ogni
``(l1, l2)`` candidato:

- se uno degli argomenti di ``consecutive(l1.slot, l2.slot)``
  ha valore noto, il vincolo si riduce a una proibizione di
  coppia di slot specifici. CP-SAT lo emette come
  ``slot_l1 + slot_l2 <= 1``.
- se entrambi gli slot sono indecisi, il compilatore emette
  un AddBoolOr che linearizza la non-coesistenza.

Su un benchmark `huge` (50 classi, 95 docenti) la regola
``gap 1 ora kind-wide`` produce circa 8\,000 vincoli pairwise:
zero impatto sul tempo di Phase B (sovrastruttura $\sim$10 ms)
e vincolo HARD trattato dal CP-SAT come parte naturale del
modello.

### Nota su `entity_kind != "teacher"`

La helper attualmente supporta solo
``entity_kind="teacher"``. Per ``class`` e ``group`` lancia
``NotImplementedError``: l'iterazione cambia (l1/l2 ancorati
alla classe o al gruppo) e va aggiunta in modo incrementale,
seguendo la suite di test
``tests/test_plesso_commuting_to_dsl.py``.

---

## 🇬🇧 Use case

Liceo "Galileo" runs across two buildings:

- **Plesso 1 -- Main Site** (city centre);
- **Plesso 2 -- Branch Via Garibaldi** (1 km away,
  $\sim$15-minute walk).

Three commuting rules apply:

1. **Gap 0**: no constraint. Default for most teachers who
   work across both sites without restrictions.
2. **Gap 1 hour**: between a lesson at Main and one at
   Garibaldi (or vice versa) at least one empty hour must
   sit between them. Applies to older teachers with mobility
   difficulties.
3. **Lunch-break only**: between 12 and 13 there is a natural
   break (cafeteria); a site change is allowed only if it
   falls inside that window. Applies to specific teachers.

This example shows rule **gap 1 hour, kind=teacher,
kind-wide** (every teacher).

### UI path

Tab **Plessi** → **Commuting Rules** → button **Add rule**.
Fill in:

- *From plesso*: Main (id 1)
- *To plesso*: Garibaldi (id 2)
- *Entity kind*: teacher
- *Entity ID*: (leave empty for kind-wide)
- *Min gap hours*: 1
- *Symmetric*: yes

When saved the rule appears in the ``commuting_rules`` module
and is applied by the classroom-assignment solver.

### Canonical DSL (helper-generated)

The helper
``engine/dsl_translator.py::plesso_commuting_rule_to_dsl(rule)``
automatically emits the following two DSL clauses (for the
Main → Garibaldi direction and its symmetric counterpart):

```
forall l1 in lessons where l1.classroom.plesso == 1:
    forall l2 in lessons where l2.classroom.plesso == 2
                          and l2.teacher == l1.teacher
                          and consecutive(l1.slot, l2.slot):
        false
```

```
forall l1 in lessons where l1.classroom.plesso == 2:
    forall l2 in lessons where l2.classroom.plesso == 1
                          and l2.teacher == l1.teacher
                          and consecutive(l1.slot, l2.slot):
        false
```

### Verbose DSL (explicit hour-by-hour form)

Without the `l.classroom.plesso` path (introduced in Step 3a)
the same rule would require enumerating each plesso's rooms in
the `where`:

```
forall l1 in lessons
    where l1.classroom in ["A1", "A2", "A3", "B1", "B2"]:
    forall l2 in lessons
        where l2.classroom in ["G1", "G2", "G3", "G4"]
          and l2.teacher == l1.teacher
          and l2.day == l1.day
          and l2.hour == l1.hour + 1:
        false
```

That form is verbose, fragile (adding a new classroom requires
updating the string) and loses the symmetry the path resolves
transparently.

### CP-SAT output

The compiler resolves each lesson's assigned classroom through
the ``classroom_for_slot`` map computed by the
classroom-assignment solver. For every candidate ``(l1, l2)``:

- if one argument of ``consecutive(l1.slot, l2.slot)`` has a
  known value the constraint reduces to a forbidden specific
  slot pair, emitted as ``slot_l1 + slot_l2 <= 1``;
- if both slots are undecided the compiler emits an
  AddBoolOr linearising non-coexistence.

On a `huge` benchmark (50 classes, 95 teachers) the
``gap 1 hour kind-wide`` rule produces about 8\,000 pairwise
constraints: zero Phase B impact ($\sim$10 ms overhead) and
the rule is treated by CP-SAT as a natural part of the model.

### Note on `entity_kind != "teacher"`

The helper currently supports ``entity_kind="teacher"`` only.
For ``class`` and ``group`` it raises ``NotImplementedError``:
the iteration changes (l1/l2 anchored to the class or group)
and is being added incrementally, with tests in
``tests/test_plesso_commuting_to_dsl.py``.
