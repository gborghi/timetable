# Query DSL: linguaggio + esempi

Tutti gli endpoint di lista (`/api/teachers`, `/api/classes`,
`/api/classrooms`, `/api/subjects`) accettano due parametri opzionali:

- `q=<espressione>`   filtro
- `sort=<spec>`       ordinamento multi-livello (vedi sotto)


## Sintassi del filtro

```
expr  := term (('AND'|'OR') term)*
term  := func | ident op value | '(' expr ')'
op    := = | != | < | <= | > | >= | contains | startswith | endswith | in [a,b,...]
```

I valori possono essere numeri (`18`), parole (`A026`, `Saturday`), stringhe
quotate (`"con spazi"`), liste per `in` (`[a, b]`).

`AND`, `OR` sono case-insensitive. Gli operatori parola (`contains`,
`startswith`, `endswith`, `in`) sono case-insensitive nel matching.


## Funzioni speciali

- `unavailable_on(giorno)`         ->  almeno una cella HARD su quel giorno
- `unavailable_on(giorno, ora)`    ->  cella HARD specifica
- `soft_on(giorno)` / `soft_on(giorno, ora)` -> stessa cosa per SOFT

Giorni accettati: `lun/lunedi/monday`, `mar/martedi/tuesday`, ...
(insensitive).


## Sort multi-livello

```
sort=field1,asc:field2,desc:field3
```

Esempio: `sort=group,asc:name,asc` ordina prima per cl. concorso, poi
alfabetico per nome (livelli stabili).

### Interazione UI (componente `SortableQueryableList`)

- **Doppio click** sul nome di una colonna -> aggiunge la colonna come
  nuovo livello di sort (massimo 4 livelli). Il livello compare come
  badge numerato (1, 2, 3, 4) accanto al nome.
- **Doppio click** su una colonna gia\` nel sort -> la rimuove e i
  livelli successivi vengono rinumerati automaticamente.
- **Singolo click** sulla freccia ▲/▼ accanto al nome -> inverte la
  direzione (asc <-> desc) di quel livello.
- Bottone **Reset sort** sopra la tabella -> svuota tutti i livelli e
  torna all'ordine di default del backend (alfabetico per nome).
- Bottone **Reset query** sopra la tabella -> svuota la barra di
  ricerca e ricarica la lista completa.

I due bottoni di reset sono indipendenti: uno tocca solo i filtri,
l'altro solo l'ordinamento.


## Esempi pronti per il copia-incolla

### Docenti (`/teachers`)

| Esempio | Significato |
|---|---|
| `group = A026` | tutti i prof di matematica |
| `classe_di_concorso in [A026, A027]` | mat e mate-fisica |
| `cognome_nome startswith B` | cognome inizia per B |
| `materia contains italiano` | docenti che insegnano Italiano |
| `max_ore >= 18 AND group = A026` | mat con cattedra piena |
| `free_day = wednesday` | mercoledi libero |
| `unavailable_on(saturday)` | almeno un'ora HARD-bloccata di sabato |
| `unavailable_on(martedi, 11)` | bloccato martedi 11:00 |
| `soft_penalty_total > 50` | penalita soft cumulata > 50 |
| `n_classes > 5` | docenti con piu\` di 5 classi |

### Classi (`/classes`)

| Esempio | Significato |
|---|---|
| `anno = 3 AND ore_totali > 30` | terze con piu\` di 30h |
| `indirizzo contains scientifico` | scientifici |
| `name in [1A_Scientifico, 1B_Scientifico]` | due specifiche |
| `name startswith 1` | tutte le prime |

### Aule (`/classrooms`)

| Esempio | Significato |
|---|---|
| `tipo = palestra` | tutte le palestre |
| `tipo in [lab_fisica, lab_chimica]` | lab fisica + chimica |
| `capienza >= 25 AND tipo contains lab` | lab con >=25 posti |
| `multi_classe = 1` | aule a piu\` classi (palestre/biblioteche) |
| `has_tag(matematica)` | aule con il tag `matematica` |
| `tag(scientifico) AND tipo = standard` | home rooms del scientifico |
| `tags contains lab` | aule con almeno un tag che contiene "lab" |

### Studenti (`/students`)

| Esempio | Significato |
|---|---|
| `cognome startswith Ross` | tutti i Rossi/Rossini/... |
| `classe = 1A` | studenti della 1A |
| `gender = F` | studentesse |
| `n_groups > 0` | studenti in almeno un gruppo articolato |
| `has_tag(BES)` | studenti BES |
| `tag(debito_matematica_4) AND classe startswith 4` | quarte con debito di mate |

### Materie (`/subjects`)

| Esempio | Significato |
|---|---|
| `name startswith Mat` | Matematica, ... |
| `no_sixth_hour_weight > 50` | materie penalizzate fortemente in 6^a ora |
| `name in [Italiano, Matematica]` | due specifiche |


## Esempi via REST (curl)

```bash
# Sort + filter combinati
curl -s 'http://127.0.0.1:8000/api/teachers?q=group%3DA017&sort=name,asc'

# Multi-livello: per cl. concorso, poi per nome
curl -s 'http://127.0.0.1:8000/api/teachers?sort=group,asc:name,asc'

# Filtro funzionale
curl -s 'http://127.0.0.1:8000/api/teachers?q=unavailable_on(saturday,11)'

# Aule lab di fisica/chimica
curl -s 'http://127.0.0.1:8000/api/classrooms?q=tipo%20in%20%5Blab_fisica%2Clab_chimica%5D'
```


## Aggiungere campi nuovi

I getter sono in `webui/backend/utils/list_query.py`, una `dict[str, fn]`
per entita\`. Aggiungi una entry `"campo_nome": lambda r: r.get("...")` e
sara\` immediatamente disponibile per filtro e sort.
