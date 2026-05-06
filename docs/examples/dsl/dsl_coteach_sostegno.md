# DSL example: coteach + sostegno DVA / compresenza chimica + sostegno

## 🇮🇹 Caso d'uso

In una **classe 2C** di un Liceo Scientifico cohabitano due
esigenze che generano vincoli simultanei:

1. **Compresenza di Chimica**. Il laboratorio di chimica
   prevede 4 ore settimanali, di cui 2 in compresenza fra il
   docente principale (ProfChim) e l'assistente di laboratorio
   (ProfAss). Le 2 ore di compresenza occupano gli stessi slot
   per entrambi i docenti.

2. **Sostegno DVA**. La classe ha uno studente con
   disabilita' (DVA) e il docente di sostegno ProfBianchi ha
   una cattedra da 18 ore. Il sostegno deve seguire le ore in
   cui la 2C ha lezione con un altro docente (non aggiunge
   ore proprie alla 2C).

I due vincoli si esprimono come regole DSL distinte; il
sistema applica la pi\`u stringente.

### Path UI: compresenza

Tab **Coteaching** → **Nuovo gruppo**:

- *Class*: 2C
- *Subject*: Chimica
- *N hours*: 2
- *Kind*: shared
- *Required*: si

Tab **Cattedre**:
- ProfChim: 4 ore di Chimica in 2C (cattedra principale).
- ProfAss: 2 ore di Chimica in 2C, ``coteach_group_id`` =
  id del gruppo creato sopra.

### Path UI: sostegno

Tab **Cattedre** → **Nuova cattedra**:

- *Teacher*: ProfBianchi
- *Class*: 2A (la classe del DVA)
- *Subject*: Sostegno
- *Hours*: 18
- *is_support*: si

### DSL: compresenza

La helper
``engine/dsl_translator.py::coteach_group_to_dsl(class, subj,
teachers, n_hours, required)`` emette per il gruppo (2C,
Chimica, [ProfChim, ProfAss], 2, True):

```
count l in lessons where l.class == "2C"
                      and l.subject == "Chimica"
                      and l.teacher == "ProfChim" == 2
```

```
count l in lessons where l.class == "2C"
                      and l.subject == "Chimica"
                      and l.teacher == "ProfAss" == 2
```

```
forall l1 in lessons where l1.class == "2C"
                       and l1.subject == "Chimica"
                       and l1.teacher == "ProfChim":
    forall l2 in lessons where l2.class == "2C"
                           and l2.subject == "Chimica"
                           and l2.teacher == "ProfAss":
        same_day(l1.slot, l2.slot)
```

Note:

- la prima clausola fissa il count delle ore di compresenza
  per il principal a 2 (delle 4 totali, le altre 2 sono
  ``solo principal'');
- la seconda fissa il count del codoc a 2;
- la terza enforce slot equality fra le coppie di slot del
  gruppo (la coppia con stesso ``same_day`` deve trovare slot
  identici, perche' quando la compresenza e' attiva entrambi
  i docenti sono nella stessa cella).

### DSL: sostegno (vincolo essenziale)

```
forall l in lessons where l.teacher == "ProfBianchi"
                       and l.subject == "Sostegno":
    exists l2 in lessons where l2.class == "2A"
                          and l2.day == l.day
                          and l2.hour == l.hour
                          and l2.teacher != "ProfBianchi":
        true
```

Letto in italiano: ``ogni lezione di ProfBianchi in 2A deve
coesistere con una lezione di un altro docente nella stessa
ora''. Implicito: il prof di sostegno non genera ore proprie
nell'orario della classe.

### Output CP-SAT

Per la compresenza il compilatore introduce una variabile
booleana ``coteach[2C, Chimica, d, h]`` per ogni slot
candidato; vincola ``slot_ProfChim_2C_Chimica_d_h ==
slot_ProfAss_2C_Chimica_d_h`` per quelle 2 ore (slot equality
``Equal`` in CP-SAT). Il count diventa ``Sum(slot_principal_d_h
for d, h) == 2``.

Per il sostegno, ``slot_ProfBianchi_Sostegno_d_h ==
Or(slot_t_2A_*_d_h for t != ProfBianchi)`` esprime
``ProfBianchi puo' essere a 2A in (d, h) solo se la 2A ha
lezione con un altro docente in (d, h)''. Aggiunto in CP-SAT
con AddBoolOr ed AddImplication.

### Nota: SOFT + DSL

Se ``required=False`` la helper emette le stesse clausole ma
con kind ``soft``. Lo stato attuale (vedi
[dsl_soft_constraints.md](./dsl_soft_constraints.md)): la
SOFT viene archiviata come label informativo nel modello
CP-SAT ma il costo di violazione e' calcolato post-hoc, non
nell'obiettivo CP-SAT.

---

## 🇬🇧 Use case

In a single **class 2C** of a science high school two needs
co-occur and generate simultaneous constraints:

1. **Chemistry coteaching**. The chemistry lab requires 4
   hours per week, 2 of which are coteach between the main
   teacher (ProfChim) and the lab assistant (ProfAss). The
   coteach hours occupy the same slots for both teachers.

2. **DVA support**. The class has a student with disabilities
   (DVA) and the support teacher ProfBianchi has an 18-hour
   cattedra. Support must follow the hours when 2C has lesson
   with a different teacher (it does not add hours of its
   own to 2C).

The two constraints are expressed as separate DSL rules; the
system enforces the strictest one.

### UI path: coteach

Tab **Coteaching** → **New group**:

- *Class*: 2C
- *Subject*: Chimica
- *N hours*: 2
- *Kind*: shared
- *Required*: yes

Tab **Cattedre**:
- ProfChim: 4 hours of Chimica in 2C (main cattedra).
- ProfAss: 2 hours of Chimica in 2C, ``coteach_group_id`` set
  to the id of the group created above.

### UI path: support

Tab **Cattedre** → **New cattedra**:

- *Teacher*: ProfBianchi
- *Class*: 2A (the DVA student's class)
- *Subject*: Sostegno
- *Hours*: 18
- *is_support*: yes

### DSL: coteach

The helper
``engine/dsl_translator.py::coteach_group_to_dsl(class, subj,
teachers, n_hours, required)`` for the group (2C, Chimica,
[ProfChim, ProfAss], 2, True) emits:

```
count l in lessons where l.class == "2C"
                      and l.subject == "Chimica"
                      and l.teacher == "ProfChim" == 2
```

```
count l in lessons where l.class == "2C"
                      and l.subject == "Chimica"
                      and l.teacher == "ProfAss" == 2
```

```
forall l1 in lessons where l1.class == "2C"
                       and l1.subject == "Chimica"
                       and l1.teacher == "ProfChim":
    forall l2 in lessons where l2.class == "2C"
                           and l2.subject == "Chimica"
                           and l2.teacher == "ProfAss":
        same_day(l1.slot, l2.slot)
```

Notes:

- the first clause fixes the principal's coteach hour count to
  2 (out of 4 total; the other 2 are "principal only");
- the second fixes the codoc's count to 2;
- the third enforces slot equality between coteach pairs so
  that whenever the coteach is active both teachers are in
  the same cell.

### DSL: support (essential constraint)

```
forall l in lessons where l.teacher == "ProfBianchi"
                       and l.subject == "Sostegno":
    exists l2 in lessons where l2.class == "2A"
                          and l2.day == l.day
                          and l2.hour == l.hour
                          and l2.teacher != "ProfBianchi":
        true
```

In English: "every ProfBianchi lesson in 2A must coexist with
another teacher's lesson at the same hour". Implicit: the
support teacher does not generate own hours in the class
schedule.

### CP-SAT output

For coteach the compiler introduces a boolean
``coteach[2C, Chimica, d, h]`` for every candidate slot;
imposes ``slot_ProfChim_2C_Chimica_d_h ==
slot_ProfAss_2C_Chimica_d_h`` for those 2 hours (slot equality
``Equal``). The count becomes
``Sum(slot_principal_d_h for d, h) == 2``.

For support, ``slot_ProfBianchi_Sostegno_d_h ==
Or(slot_t_2A_*_d_h for t != ProfBianchi)`` expresses
"ProfBianchi can be in 2A at (d, h) only if 2A has a lesson
with a different teacher at (d, h)". Wired in CP-SAT with
AddBoolOr and AddImplication.

### Note: SOFT + DSL

If ``required=False`` the helper emits the same clauses with
kind ``soft``. Current status (see
[dsl_soft_constraints.md](./dsl_soft_constraints.md)): SOFT is
archived as an informational label in the CP-SAT model but
the violation cost is computed post-hoc, not in the CP-SAT
objective.
