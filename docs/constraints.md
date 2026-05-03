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
