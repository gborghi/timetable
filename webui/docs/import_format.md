# Importazione da Excel / CSV

Ogni tabella della webui supporta l'import bulk da file Excel (.xlsx) o
CSV / TSV. L'endpoint e' uno solo:

    POST /api/import/{entity}    multipart/form-data
        file=<.xlsx|.csv|.tsv>
        mode=upsert | replace | append   (default: upsert)

Per ottenere un template precompilato con gli header attesi e una riga di
esempio:

    GET  /api/import/{entity}/template

Dal frontend basta cliccare il pulsante "Importa" presente sopra ogni
lista. Il browser scarica il template, tu lo riempi col foglio di calcolo
e lo carichi.

## Modalita' di import

- **upsert** (default): le righe gia' presenti nel DB (matchate sul
  campo identificativo) vengono aggiornate, le nuove inserite.
- **replace**: la tabella viene SVUOTATA e poi popolata col file. Usalo
  con cautela; cancella anche le righe collegate (es. ClassSubject quando
  importi classi in modalita' replace).
- **append**: come upsert, ma errori non bloccano il batch successivo.

## Convenzioni generali

- La PRIMA riga e' sempre l'header. I nomi colonna sono case-insensitive,
  spazi e underscore sono interscambiabili (`Cognome` = `cognome` =
  `last_name`).
- Sono accettati alias italiani e inglesi (vedi tabella per ogni entita').
- Celle vuote vengono trattate come null. Le righe interamente vuote
  vengono ignorate (non contano nei conteggi).
- I valori booleani accettati: `true`, `1`, `si`, `vero`, `x`, `on` (case
  insensitive). Tutto il resto e' falso.
- Le date vanno in ISO `YYYY-MM-DD` o come date nativa di Excel.
- Il delimitatore CSV viene auto-rilevato (`, ; \t |`).

## Schema per entita'

### teachers — Docenti

| Colonna           | Alias italiani         | Tipo   | Note                                  |
| ----------------- | ---------------------- | ------ | ------------------------------------- |
| name              | nome, cognome_nome     | str*   | obbligatorio. Identificativo          |
| matricola         | code                   | str    |                                       |
| group             | gruppo, classe_di_concorso, cdc | str |                            |
| max_hours         | max_ore, ore_max       | int    | default 18                            |
| completion_hours  | ore_completamento      | int    |                                       |
| exemption_hours   | ore_esonero            | int    |                                       |
| free_day          | giorno_libero          | str    | "Saturday" / "Sabato" ecc.            |
| max_consecutive   | max_consecutive_ore    | int    | default 5                             |
| subjects          | materie                | csv    | virgola-separati, es. "Mat,Fisica"    |
| notes             | note                   | str    |                                       |

Campo identificativo: `name`. Le materie esistenti per quel docente
vengono SOSTITUITE dal valore della colonna `subjects`.

### subjects — Materie

| Colonna                  | Alias                | Tipo  | Note          |
| ------------------------ | -------------------- | ----- | ------------- |
| name                     | nome, materia        | str*  | obbligatorio  |
| pretty_name              | nome_esteso          | str   |               |
| distribute_days_weight   | peso_distribuzione   | float | default 0     |
| dual_hours_weight        | peso_doppia          | float | default 0     |
| no_sixth_hour_weight     | peso_no_6ora         | float | default 0     |
| notes                    | note                 | str   |               |

Campo identificativo: `name`.

### classes — Classi

Una classe puo' occupare PIU' RIGHE del file: una riga per coppia
`(name, subject)`. Tutte le righe con lo stesso `name` vengono unite.

| Colonna         | Alias                     | Tipo  | Note                          |
| --------------- | ------------------------- | ----- | ----------------------------- |
| name            | nome, classe              | str*  | obbligatorio (es. "1A")       |
| year            | anno                      | int   | 1..5                          |
| section         | sezione                   | str   | "A", "B"...                   |
| curriculum      | indirizzo, curriculum_code| str   | code dell'indirizzo           |
| n_students      | studenti                  | int   |                               |
| subject         | materia                   | str   | la materia (una per riga)     |
| hours_per_week  | ore, ore_settimanali      | int   | ore della materia             |
| notes           | note                      | str   |                               |

Se `curriculum` matcha il `code` di un Curriculum esistente, viene anche
collegato `curriculum_id`.

### classrooms — Aule

| Colonna           | Alias              | Tipo | Note          |
| ----------------- | ------------------ | ---- | ------------- |
| name              | nome, aula         | str* | obbligatorio  |
| kind              | tipo               | str  | standard / lab_chimica / lab_fisica / lab_informatica / lab_linguistico / palestra / biblioteca / aula_speciale |
| capacity          | capienza           | int  | default 30    |
| multi_class       | multi_classe       | bool | default no    |
| multi_class_max   | multi_classe_max   | int  | default 1     |
| notes             | note               | str  |               |

### curricula — Indirizzi di studio

Una riga per coppia `(code, year, subject)`. Tutte le righe con lo stesso
`code` vengono unite per formare il monte-ore per anno.

| Colonna         | Alias                       | Tipo | Note                |
| --------------- | --------------------------- | ---- | ------------------- |
| code            | codice, curriculum, indirizzo | str* | machine name ("Scientifico", "ITIS_INFO" ecc.) |
| name            | nome                        | str  | display name        |
| description     | descrizione                 | str  |                     |
| score           | punteggio                   | int  | default 1           |
| year            | anno                        | int* | 1..5                |
| subject         | materia                     | str* |                     |
| hours_per_week  | ore, ore_settimanali        | int  | ore alla settimana  |

Esempio (3 righe per definire le 3 materie del primo anno):

| code         | name              | year | subject     | hours_per_week |
| ------------ | ----------------- | ---- | ----------- | -------------- |
| Scientifico  | Liceo Scientifico | 1    | Matematica  | 5              |
| Scientifico  |                   | 1    | Fisica      | 2              |
| Scientifico  |                   | 1    | Italiano    | 4              |

### students — Studenti

| Colonna       | Alias                 | Tipo | Note                     |
| ------------- | --------------------- | ---- | ------------------------ |
| last_name     | cognome               | str* | obbligatorio             |
| first_name    | nome                  | str* | obbligatorio             |
| birth_date    | data_nascita          | date | YYYY-MM-DD               |
| gender        | sesso                 | str  | M / F / other            |
| email         |                       | str  |                          |
| student_code  | matricola, codice     | str  | id esterno               |
| class_name    | classe, class         | str  | nome classe (es. "1A")   |
| notes         | note                  | str  |                          |

Identificativo composito: `(last_name, first_name, birth_date)`.

### groups — Gruppi articolati

Una riga per coppia `(name, subject)`. Le righe con lo stesso `name`
vengono unite; i `student_codes` vengono accumulati (deduplicati).

| Colonna        | Alias                         | Tipo | Note                       |
| -------------- | ----------------------------- | ---- | -------------------------- |
| name           | nome, group, gruppo           | str* | identificativo del gruppo  |
| kind           | tipo                          | str  | splitting/language/religion/support |
| description    | descrizione                   | str  |                            |
| subject        | materia                       | str  | materia che il gruppo fa   |
| hours_per_week | ore                           | int  |                            |
| student_codes  | matricole, students           | csv  | codici-virgola-separati    |
| notes          | note                          | str  |                            |

Gli studenti referenziati per `student_code` devono gia' esistere nel DB
(tabella students). Se non trovati, vengono riportati negli `errors`
del report ma il resto dell'import procede.

## Risposta dell'endpoint

Tutti gli import restituiscono un `ImportReport`:

```json
{
  "ok": true,
  "entity": "teachers",
  "n_inserted": 12,
  "n_updated": 3,
  "n_skipped": 1,
  "n_total_rows": 16,
  "messages": [],
  "errors": ["riga 14: name mancante"]
}
```

Il pulsante "Importa" nel frontend mostra un toast con il riepilogo e,
se ci sono errori, li elenca.
