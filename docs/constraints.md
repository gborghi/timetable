# Vincoli

Il sistema usa una tassonomia uniforme di **5 stati** sia per le matrici
di disponibilita' (cella per cella) sia per le preferenze di aula. I
vincoli logici disgiuntivi (DNF) hanno **4 kind** (allowed non si applica
qui).

## I 5 stati / 4 kind

| Stato      | Colore       | Semantica                                         |
| ---------- | ------------ | ------------------------------------------------- |
| ALLOWED    | verde chiaro | default (solo per le grid materia<->aula e docente<->aula); nessuna contribuzione all'obiettivo |
| SOFT       | giallo       | penalita' positiva quando lo slot e' usato (`+penalty` aggiunto all'obiettivo, che e' minimizzato) |
| HARD       | rosso        | il solver deve evitare questo slot (per matrici), oppure il vincolo logico DEVE essere soddisfatto |
| PREFERRED  | blu          | bonus negativo quando lo slot e' usato / il vincolo logico e' soddisfatto (`-bonus` riduce l'obiettivo); incoraggia |
| ENFORCED   | verde scuro  | il solver DEVE far accadere questo slot / soddisfare il vincolo. Per le matrici significa "presence required"; per i logical significa "DNF must be satisfied AND mappata su lezioni attive" |

Per le matrici di disponibilita' di docenti / classi / aule il flusso di
ciclo cliccando su una cella e':

```
free (verde) -> soft (giallo) -> hard (rosso) -> preferred (blu) -> enforced (verde scuro) -> free
```

Le celle gialle e blu mostrano un input numerico per editare la penalita'
(positiva sul giallo, negativa sul blu, sign-clamp automatico al
salvataggio).

Per le grid materia<->aula e docente<->aula il ciclo e':

```
allowed (verdino) -> soft (giallo) -> preferred (blu) -> forbidden (rosso, HARD) -> enforced (verde scuro) -> allowed
```

## Matrici di disponibilita' 5-stati

Implementate nel componente `AvailabilityMatrix.svelte`. Tre tabelle
backend usano la stessa struttura: `teacher_unavailability`,
`class_unavailability`, `classroom_unavailability`. La colonna `state`
e' una stringa, `soft_penalty` e' un Integer signed.

### Sincronizzazione con free_day del docente

Quando il docente ha `free_day` settato (es. "Saturday"), tutte e 6 le
ore di quel giorno vengono mostrate come HARD nella matrice automaticamente
(senza essere persistite -- sono "auto" cells). Se l'utente edita la
matrice manualmente e tutte le ore di un giorno diventano HARD, il
backend deduce il free_day; viceversa cambiando il free_day rimuove le
auto-cells del vecchio giorno e le aggiunge nel nuovo. Vedere
`webui/backend/routers/teachers.py::_autofill_free_day_cells`.

### Mapping CP-SAT

In `webui/backend/optimization.py::_availability_constraints` ogni
tabella si traduce in:

- `<entity>_hard`: set `(name, day, hour)` -- vincolo HARD,
  forbidden_assignment nel solver.
- `<entity>_soft`: dict `(name, day, hour) -> penalty`. Sia `state==soft`
  che `state==preferred` finiscono qui: la differenza e' nel SEGNO
  della penalty. Il solver minimizza la somma SOFT, quindi un
  contributo negativo riduce l'obiettivo (= bonus).
- `<entity>_enforced`: set `(name, day, hour)` -- per ora raccolto, da
  cablare nel CP-SAT model come `presence_required`. La UI lo accetta
  gia' e lo persiste, l'enforcement strong nel solver e' pianificato
  come step successivo.

## Vincoli logici (DNF)

### Sintassi

```
expr     := or_expr
or_expr  := and_expr ('OR' and_expr)*
and_expr := not_expr ('AND' not_expr)*
not_expr := ('NOT' | 'mai') not_expr | atom
atom     := slot | predicate | '(' expr ')'
slot     := <giorno_codice><ora>
predicate:= <kind> ':' <name> ('@' <giorno_codice> <ora>?)?
kind     := aula | materia | classe | gruppo | docente | prof
giorno   := lun|mar|mer|gio|ven|sab     (anche
            lunedi|martedi|...|sabato, monday|tuesday|...)
ora      := 1..6   (ordinale, 1=08:00, 2=09:00, ..., 6=13:00)
            | 8..13 (assoluta)
```

Sono accettati `&` (AND), `|` (OR), `!` (NOT). `mai` e' alias di `NOT`
(zucchero sintattico che fluisce attraverso `_push_not` con DeMorgan).

L'espressione e' parsata in **DNF**: lista di clausole, ciascuna
lista di literal `{day, hour, negate, predicate_kind?, predicate_name?}`.
Il vincolo e' soddisfatto se almeno una clausola e' interamente attiva.

### Predicate atoms (sintassi estesa)

```
aula:LabFisica           -- l'entita' usa l'aula a qualunque slot
aula:LabFisica@mar       -- ... il martedi a qualunque ora
aula:LabFisica@mar4      -- ... martedi 4a ora (= 11:00)
materia:Religione@lun8   -- lezione di religione lunedi alle 8
classe:1A_Scientifico    -- riferimento alla classe
gruppo:IRC               -- riferimento al gruppo
docente:Rossi.M          -- riferimento al docente
```

I literal predicate vengono parsati e persistiti correttamente; nel
DB stanno nel campo `parsed_dnf_json`. Il solver per ora li tratta
"otticamente": `evaluate_against_unavailable` li skip-a (assume satisfied)
in modo che la portion slot-only del DNF guidi comunque il solver. Per
applicare i predicate atoms in modo strong serve l'integrazione con la
fase di assegnazione aule. La funzione `iter_predicate_literals` espone
gli atomi opachi al codice client che vuole onorarli.

### Esempi pratici

Per docenti:

```
lun8 AND lun9                                   -- libero per due ore consec.
(lun8 AND lun9) OR (mar8 AND mar9)              -- libero per due ore in uno dei due giorni
gio11 OR gio12 OR gio13                         -- almeno una di queste tre libera
NOT (mer3 AND mer4)                             -- non entrambi insieme
mai aula:LabFisica@mar                          -- mai in laboratorio fisica martedi
mai materia:Religione@lun8                      -- mai religione lunedi 8
aula:LabInformatica@lun OR aula:LabInformatica@gio
```

Per classi:

```
mer4 AND mer5 AND mer6
(mer4 AND mer5) OR (gio4 AND gio5)
mai aula:Palestra@gio
aula:LabInformatica@mar OR aula:LabInformatica@gio
```

Per aule:

```
gio4 AND gio5 AND gio6
(lun13 AND mar13)
mai materia:Religione
gruppo:IRC OR gruppo:Alternativa
```

### Mapping a CP-SAT

Per ogni regola con `kind in {hard, soft, preferred, enforced}` e con
DNF `[clause1, clause2, ...]`:

- HARD: il solver impone almeno una clausola fully active.
- SOFT: se nessuna clausola e' fully active, paga `+soft_penalty`.
- PREFERRED: se almeno una clausola e' fully active, ottiene
  `+soft_penalty` (negativo, quindi reduce dell'obiettivo).
- ENFORCED: come HARD ma con la semantica "presence required" -- almeno
  uno degli slot della DNF deve coincidere con un'ora di lezione attiva
  per quell'entita'.

Vedere `optimization.py::_logical_violation_summary` e
`_logical_check_for_solution`.

## Vincoli HARD a toggle (per classe)

In `school_classes` ci sono 7 boolean che toggleano vincoli HARD strutturali:

- `hard_entry_at_8` -- la prima ora deve essere alle 8
- `hard_exit_after_12` -- l'ultima ora non prima delle 12
- `hard_no_holes` -- niente buchi nella giornata
- `hard_dual_math` -- doppia ora consecutiva di matematica
- `hard_dual_italian` -- doppia ora di italiano
- `hard_motorie_pairs` -- scienze motorie a coppie consecutive
- `hard_max_6_per_day` -- max 6 ore di lezione/giorno

Il soft `soft_minimize_sixth_weight` regola il peso della 6a ora
(minimizzata). Tutti questi vivono come campi sulla riga della classe;
la UI li espone nel modal di edit della classe.

## Vincoli sull'aula

`classrooms` ha:

- `multi_class` boolean -- se l'aula puo' ospitare piu' classi nello stesso slot
  (palestre, biblioteche)
- `multi_class_max` -- HARD upper bound sulla concorrenza
- `multi_class_pref` -- SOFT preferred concurrency (es. 1 anche se HARD permette 2)
- `multi_class_pref_weight` -- peso del SOFT

Le preferenze materia<->aula in `classroom_subject_preferences` e
docente<->aula in `teacher_classroom_preferences` rispondono al ciclo a
5 stati (allowed / soft / preferred / forbidden / enforced). Sono
gestite dal `ClassroomGrid.svelte` riusato in /subjects e /teachers.

## Operazioni bulk con detection conflitti

Da una lista (Docenti / Classi / Aule), Ctrl+click o Shift+click
selezionano piu' righe; il bottone "Vincolo collettivo" apre il modal
`BulkApplyModal` che supporta tre azioni:

- **add_logical** -- aggiungi un vincolo logico a tutte le entita' selezionate
- **set_field** -- setta un campo (es. `free_day = Saturday`)
- **add_unavailability** -- aggiungi una cella (day, hour, state) alla matrice

Il flusso e' a 3 step:

1. Click "Verifica conflitti" -> dry-run sul backend
   (`POST /api/bulk/{entity}/dry-run`). Restituisce `candidates`
   (entita' senza conflitto) e `conflicts` (entita' con un vincolo
   pre-esistente che potrebbe entrare in conflitto).
2. Se ci sono conflitti, l'utente sceglie `override` (forza) o `skip`
   (lascia stare le conflittuali).
3. Click "Applica" -> POST a `/apply` che persiste con la strategia scelta.

## Conflict detection nei /constraints

Il tab Vincoli ha un bottone "Cerca conflitti" che fa
`GET /api/monitor/conflicts`. Il detector best-effort segnala:

- **matrix_hard_enforced** -- stessa cella `(entity, day, hour)` marcata
  sia HARD sia ENFORCED (semantica contraddittoria).
- **enforced_on_free_day** -- una cella ENFORCED del docente cade nel
  suo free_day.
- **logical_unsatisfiable** -- un vincolo logico HARD/ENFORCED la cui
  DNF non e' soddisfacibile dato l'insieme degli HARD slot dell'owner.

Ogni conflitto e' presentato con `kind`, `reason` parlante, e la lista
dei vincoli coinvolti (ognuno con la sua pill colorata).

## Vincoli Italian-school (C1 + C2 + C3)

Sezione aggiunta 2026-05-04/05. Tre famiglie di vincoli specifici della
scuola italiana, tutti enforced come constraint CP-SAT nativi (non piu'
gestiti via snapshot/restore).

### C1.1 -- Compresenze "shared" (lab, dual-teacher)

Caso d'uso: laboratorio di chimica del 2C, 4 ore alla settimana, di cui
2 in compresenza con l'assistente di laboratorio.

**Modello dati**:
```
CoteachGroup(class_id=2C, subject="Chimica", n_hours=2, kind="shared",
             required=True)
Assignment(teacher=ProfChim, class_id=2C, subject="Chimica", hours=4,
           coteach_group_id=<id>)
Assignment(teacher=ProfAss,  class_id=2C, subject="Chimica", hours=2,
           coteach_group_id=<id>)
```

**Convenzione**: `members[0]` (ordinati per hours desc, name tiebreak)
e' il **principal** -- la sua cattedra completa il monte ore. Gli altri
sono **codoc** -- la loro Assignment e' esattamente n_hours.

**CP-SAT** (Phase A + B):
- IntVar `coday_count[gid, d]` in `[0, n_hours]`, sum_d == n_hours.
- `day_count[principal, gcl, gsub, d] >= coday_count[gid, d]` (le ore
  di compresenza sono un sotto-insieme delle ore del principal).
- `day_count[codoc, gcl, gsub, d] == coday_count[gid, d]` (codoc fa
  ESATTAMENTE le ore di compresenza).
- Codoc triples escluse da `cl_day_load` e `ore_per_classe` (le ore
  vengono gia' contate via il principal).
- Phase B: `coslot[gid, h]` BoolVar, sum_h == coday[gid, d];
  `slot[member, gcl, gsub, h] >= coslot[gid, h]` per ogni member.

**Pre-flight**: principal hours >= n_hours; codoc hours == n_hours.

### C1.2 -- Compresenze "shadow" (sostegno DVA)

Caso d'uso: prof di sostegno che segue uno studente in 2A.

**Modello dati**:
```
Assignment(teacher=ProfSost, class_id=2A, subject="sostegno",
           hours=18, is_support=True)
```

**Semantica**: il sostegno **non aggiunge** ore-classe; segue le ore
gia' presenti.

**CP-SAT** (Phase B): per ogni `(prof_sost, X, sostegno, h)`,
`slot[(sost, X, sost, h)] <= pr_per_cl_h[(X, h)]` dove `pr_per_cl_h`
e' la BoolVar "X e' occupata in slot h". Se `pr` non esiste (X non
ha lezioni quel giorno), `slot[sost, X, sost, h] == 0`.

Le triple di sostegno sono escluse da `cl_day_load` e dal
class-busy aggregator (no double-count).

### C1.3 -- Potenziamento (Legge 107)

Caso d'uso: docenti dell'organico potenziato che non hanno una
cattedra fissa, usabili per progetti, supplenze, recupero.

**Modello dati**:
```
Assignment(teacher=ProfPot, class_id=NULL, subject="Potenziamento",
           hours=10, is_potenziamento=True)
```

**Semantica**: le ore vengono schedulate ma non producono `Lesson`
class-bound. Il prof e' prioritario nel tab `/assenze-supplenze`
(badge **POT**, bordo viola, primo nella lista dei sostituti).

**CP-SAT** (Phase A): IntVar `pot_day_count[prof, d]` in
`[0, MAX_PROF_HOURS_PER_DAY]`, sum_d == pot_hours_total.
`pot_day_count[prof, d] + prof_day_load[prof, d] <= 5` (cap giornaliero).
Salvato in `dc_value` con chiave `("__pot__", prof, d)` per Phase B.

**Pre-flight**: `class_id` deve essere NULL; cap settimanale 30 ore
(5 ore/giorno x 6 giorni).

### C2 -- Parallel groups intra-class

Caso d'uso: religione + alternativa in 3B, stessa ora, prof diversi,
classe occupata UNA volta sola.

**Modello dati**:
```
Assignment(teacher=ProfRel, class_id=3B, subject="Religione",
           hours=1, parallel_group_id=99)
Assignment(teacher=ProfAlt, class_id=3B, subject="Alternativa",
           hours=1, parallel_group_id=99)
```

**CP-SAT**:
- Phase A: members del gruppo hanno `day_count[m1, d] == day_count[m2, d]`
  per ogni d. Members[1:] esclusi da `cl_day_load` e `ore_per_classe`
  (il primo "porta" la classe, gli altri ride-along).
- Phase B: `slot[m1, h] == slot[m2, h]` per ogni h. Class-busy
  aggregator usa `parallel_subj_to_busy_key`: tutti i membri della
  parallela hanno la stessa busy_key, quindi la classe conta come
  busy ONCE anche con N membri.

### C3 -- Inter-class StudyGroup scheduling

Caso d'uso: gruppo "Spagnolo" con 5 studenti da 2A + 7 da 2B,
3 ore/settimana, ProfSpa. Le ore di gruppo NON sono lezioni di 2A o
di 2B (gli studenti sono fisicamente in un'aula diversa), ma 2A e 2B
non possono fare lezione regolare in quegli slot (i loro studenti del
gruppo non ci sono).

**Modello dati** (Opzione B: due colonne separate, XOR a livello app):
```
StudyGroup(name="Spagnolo", kind="language")
GroupMembership(group_id=<id>, student_id=<id>) x 12  # i 5+7 membri
GroupSubjectHours(group_id=<id>, subject="Spagnolo", hours_per_week=3)
Assignment(teacher=ProfSpa, class_id=NULL, group_id=<id>,
           subject="Spagnolo", hours=3)
```

`Assignment.class_id` rimane (legacy alias, NULL per i gruppi).
`Assignment.group_id` nullable, FK a `study_groups`. XOR a livello
applicazione: `_preflight_lock_check` rifiuta se entrambi sono
valorizzati. Stesso pattern su `CoteachGroup.group_id` (compresenze
su gruppo) e su `Lesson.group_name` (lezione-gruppo nei risultati).

**CP-SAT**:
- Phase A: la triple `(ProfSpa, "Spagnolo", "Spagnolo", 3)` viene
  augmentata a `triples` con `class_name = group_name`. Il group_name
  NON e' in `classes`, quindi non c'e' `cl_day_load` ne'
  `ore_per_classe` per il gruppo.
- Phase A vincolo per-day capacity: per ogni classe-madre `cl_h`
  toccata da almeno un gruppo `g`,
  `cl_day_load[cl_h, d] + sum(group_day_count[g, d]) <= 6`. Senza
  questo, Phase B sarebbe infeasible quando curriculum + gruppo
  superano 6 slot/giorno.
- Phase A Hall-like fix: il bound `prof_day_load <= max(cl_day_load)`
  e' saltato per i prof che insegnano SOLO ore di gruppo (altrimenti
  forzerebbe le loro ore a 0).
- Phase B: la triple di gruppo entra normalmente in `triples_active`.
  Il class-busy aggregator aggiunge il group_slot come subj_busy_var
  per OGNI classe-madre dei membri, sotto la busy_key
  `__grp__<group_name>__<subject>`. L'invariante `sum(subj_busy) == pr`
  garantisce che la classe-madre non faccia altre lezioni nello
  stesso slot.
- Phase B HARD-2 / no-holes: applicate solo alle classi-con-direct
  triples. Una classe toccata SOLO da gruppi (caso degenere) non
  prende il vincolo "esci alle 12" -- il gruppo e' un add-on.

**Pre-flight**: XOR class_id/group_id, gruppo deve avere almeno
uno studente, ogni studente deve avere classe-madre, hours > 0.

**Pipeline supportate**: monolitica + `decomposition_temporal`.
Le altre decomposte (`spectral_v2`, `curriculum`, `metis`,
`column_generation`) ignorano `group_assignments` per ora -- la
plumbing dei parametri attraverso le 5 pipeline restanti e' un
follow-up tracciato in AUDIT.md.
