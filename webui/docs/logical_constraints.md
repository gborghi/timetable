# Vincoli logici di indisponibilita

Oltre alla matrice 3-stati cella-per-cella, docenti, classi e aule
possono avere **vincoli disgiuntivi**: espressioni con AND/OR/NOT su
slot orari, che lasciano al solver la liberta\` di scegliere quale ramo
onorare.


## Grammatica

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

Anche `&` (AND), `|` (OR), `!` (NOT) sono accettati. `mai` e' alias di
`NOT` (zucchero sintattico).

### Predicate atoms (sintassi estesa)

Oltre agli slot puri (`lun8`, `mar3`, ecc.) sono ammessi atomi con
"semantica":

- `aula:NOME` -- l'entita' usa quella aula in qualunque slot
- `aula:NOME@mar` -- l'entita' usa quella aula il martedi (a qualunque ora)
- `aula:NOME@mar4` -- l'entita' usa quella aula martedi 4a ora (= 11:00)
- `materia:NOME`, `classe:NOME`, `gruppo:NOME`, `docente:NOME` --
  analoghi su materia, classe, gruppo, docente

Esempi composti:

- `mai aula:LabFisica@mar` -- mai in laboratorio di fisica il martedi
- `aula:LabInformatica@lun OR aula:LabInformatica@gio` -- almeno una
  delle due opzioni
- `mai materia:Religione@lun8` -- mai religione lunedi alle 8

> **Nota di enforcement**: gli atomi predicate vengono parserizzati e
> persistiti correttamente, e l'editing UI li mostra. L'enforcement
> dentro il solver e' **parziale**: i predicati su `aula:`/`materia:`
> entrano in gioco durante la fase di assegnazione aule, mentre gli
> atomi puramente temporali (slot) sono onorati gia' dal solver di
> phase B. I literal predicate sono esposti via
> `iter_predicate_literals` per integrazioni custom.

L'espressione viene parsificata in **DNF** (Disjunctive Normal Form):
una lista di clausole, ognuna lista di literal `{day, hour, negate,
predicate_kind?, predicate_name?}`. Il vincolo e\` soddisfatto se
**almeno una clausola** e\` "fully active", ossia tutti i suoi literal
valgono nello scheduling.

## Tipi di vincolo (kind)

Ogni regola ha un `kind` discriminatore:

- `hard` (rosso) -- DEVE essere soddisfatto
- `soft` (giallo) -- se violato paga `+penalty` nell'obiettivo
- `preferred` (blu) -- se soddisfatto da `+(-bonus)` (= riduzione obj)
- `enforced` (verde scuro) -- come hard ma forza la presenza positiva:
  almeno uno dei blocchi della DNF deve coincidere con un'ora di
  lezione attiva (utile per "questo docente DEVE avere un'ora qui")


## Semantica

- Un literal positivo `lun8` vale "il target e\` indisponibile (ha
  un'occupazione/blocco) in `lun ore 8:00`".
- Un literal `NOT lun8` vale il contrario: "il target e\` libero in
  `lun 8:00`".
- HARD: lo scheduling DEVE soddisfare il vincolo. Se nessuna clausola
  e\` fully active, l'orario e\` rifiutato (drag-drop / move-preview).
- SOFT: penalita\` `soft_penalty` aggiunta all'obiettivo se nessuna
  clausola e\` fully active.


## Esempi pratici

### Docenti

| Espressione | Senso |
|---|---|
| `(lun8 AND lun9) OR (mar8 AND mar9)` | impegno fisso 2 ore: lunedi 8-9 OPPURE martedi 8-9 |
| `gio11 OR gio12 OR gio13` | almeno un'ora del giovedi pomeriggio occupata |
| `NOT (mer3 AND mer4)` | il mercoledi 3-4 NON sia bloccato (forza disponibilita) |

### Classi

| Espressione | Senso |
|---|---|
| `mer4 AND mer5 AND mer6` | mercoledi pomeriggio sempre senza lezione (gita ricorrente) |
| `(mer4 AND mer5) OR (gio4 AND gio5)` | attivita` pomeridiana che alterna tra mer e gio |

### Aule

| Espressione | Senso |
|---|---|
| `gio4 AND gio5 AND gio6` | lab indisponibile gio pomeriggio (manutenzione) HARD |
| `(lun13 AND mar13)` | aula fuori uso le ultime ore lun e mar |


## API REST

Endpoint paralleli per le tre entita\`. `<entity>` e\` uno fra
`teachers`, `classes`, `classrooms`.

| Metodo | Path | Descrizione |
|---|---|---|
| GET    | `/api/<entity>/{id}/logical-unavailabilities` | lista regole |
| POST   | `/api/<entity>/{id}/logical-unavailabilities` | aggiunge una regola |
| PUT    | `/api/<entity>/{id}/logical-unavailabilities/{rule_id}` | aggiorna |
| DELETE | `/api/<entity>/{id}/logical-unavailabilities/{rule_id}` | elimina |
| POST   | `/api/logic/validate` | parsifica un'espressione test (no DB) |

Body POST/PUT:

```jsonc
{
  "expression": "(lun8 AND lun9) OR (mar8 AND mar9)",
  "is_hard": true,
  "soft_penalty": 100        // ignorato se is_hard
}
```

Response:

```jsonc
{
  "id": 1,
  "entity_type": "teacher",
  "entity_id": 15,
  "expression": "(lun8 AND lun9) OR (mar8 AND mar9)",
  "pretty": "(lun8 AND lun9) OR (mar8 AND mar9)",
  "clauses": [
    [{"day":1,"hour":8,"negate":false},
     {"day":1,"hour":9,"negate":false}],
    [{"day":2,"hour":8,"negate":false},
     {"day":2,"hour":9,"negate":false}]
  ],
  "is_hard": true,
  "soft_penalty": 100
}
```


## Persistenza

Tabella unica `logical_unavailabilities` con campi:
`id, entity_type, entity_id, expression, parsed_dnf_json, is_hard,
soft_penalty`. La forma "parsed" viene serializzata come JSON al salvataggio
e usata dal drag-drop validator.


## Integrazione con l'ottimizzazione

- **Drag-and-drop / move-preview** (gia\` attivo): ogni mossa simulata
  ricostruisce l'insieme `unavail_set` per docente/classe/aula a partire
  da:
    - le celle 3-stati HARD
    - le lezioni effettivamente assegnate (uno slot occupato e\`
      "indisponibile" lato risorsa)
  Per ogni regola si verifica se almeno una clausola e\` "fully active".
  - HARD violato -> mossa rossa (rifiutata).
  - SOFT non soddisfatto -> il delta SOFT include `soft_penalty`.

- **CP-SAT (Phase B)**: i vincoli disgiuntivi NON sono ancora propagati
  al solver principale (il motore in `experiments/` non e\` modificato).
  Effetto pratico: il solver puo\` produrre un orario che viola un
  vincolo logico HARD. Il drag-drop validator pero\` impedisce mosse
  manuali che lo violerebbero, e la metaeuristica LNS puo\` essere
  usata per "ripulire" la soluzione iniziale.

  **Roadmap**: passaggio diretto al CP-SAT come Bool `clause_active[c]`
  per ogni clausola con `OR(clause_active) >= 1` (HARD) o termine
  `(1 - OR(clause_active)) * penalty` nell'obiettivo (SOFT). Si fa in
  un nuovo modulo `experiments/logical_extension.py` senza toccare i
  motori esistenti.


## Grammatica errori comuni

- `lunedi 8` (con spazio) non e\` ammesso: usa `lunedi8`.
- `lun 7` non e\` ammesso (ore valide: 1..6 ordinali, 8..13 assolute).
- Operatori case-insensitive: `AND` = `and` = `&`.
- Le parentesi sono obbligatorie per disambiguare la precedenza tra AND/OR.
