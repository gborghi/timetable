# Generazione automatica delle aule

Il backend offre una "ricetta" deterministica per popolare la lista
aule a partire dal numero di classi presenti nel DB. La ricetta scala
proporzionalmente, e ogni conteggio puo\` essere modificato dalla UI
prima della generazione.


## Regole di default

Per ciascun tipo di aula:

| tipo            | regola                              | minimo |
|-----------------|-------------------------------------|--------|
| standard        | 1 per classe (la "home" della classe) | n.a. |
| lab_fisica      | ~ 1 ogni 10 classi                  | 1     |
| lab_chimica     | ~ 1 ogni 10 classi                  | 1     |
| lab_informatica | ~ 1 ogni 8 classi (piu\` richiesto)  | 1     |
| lab_linguistico | ~ 1 ogni 12 classi                  | 1     |
| palestra        | ~ 1 ogni 18 classi                  | 1     |
| biblioteca      | 1 fissa fino a 60 classi, poi +1 ogni 60 | 1 |
| aula_speciale   | ~ 1 ogni 20 classi                  | 1     |

I divisori vivono in `webui/backend/mock_classrooms.py:DEFAULT_DIVISORS`
e sono modificabili a un solo punto. Il calcolo arrotonda half-up
(`round`).


## Esempi

Per profili tipici:

| profilo    | classi | std | fisica | chim | info | ling | pal | bib | spec | totale |
|------------|-------:|----:|-------:|-----:|-----:|-----:|----:|----:|-----:|-------:|
| small      |     10 |  10 |     1  |   1  |   1  |   1  |  1  |  1  |   1  |    16  |
| medium     |     25 |  25 |     2  |   2  |   3  |   2  |  1  |  1  |   1  |    37  |
| big        |     35 |  35 |     4  |   4  |   4  |   3  |  2  |  1  |   2  |    55  |
| huge       |     50 |  50 |     5  |   5  |   6  |   4  |  3  |  1  |   2  |    76  |
| superhuge  |     80 |  80 |     8  |   8  |  10  |   7  |  4  |  1  |   4  |   122  |

(Numeri calcolati con `round()`; la UI mostra il "totale aule se
generate" subito sotto il form.)


## Come usare la generazione dalla UI

1. Importa o genera una scuola (Dashboard).
2. Vai su **Aule** -&gt; clicca "Genera aule...".
3. Si apre il pannello "Parametri generazione aule" pre-popolato con i
   conteggi suggeriti per la dimensione corrente del DB. Ogni campo
   include la regola di default in piccolo.
4. Modifica i campi che vuoi (es. metti 0 lab_chimica se la tua scuola
   non ha laboratori di chimica) e clicca "Genera aule".
5. La generazione **sostituisce** l'eventuale lista aule precedente.


## API

- `GET /api/classrooms/suggested-counts`
  Ritorna `{n_classes, counts: {...}, total_classrooms_if_applied,
  rules: {...}}`. La UI lo chiama all'apertura del pannello.

- `POST /api/classrooms/auto-generate`
  Body opzionale con i campi `n_lab_*`, `n_palestra`, `n_biblioteca`,
  `n_aula_speciale` (tutti `int | null`). Null = usa il default
  proporzionale; un intero = override esplicito.

- Risposta: `{ok, created, counts_used, n_classes}`.


## Personalizzazione single-aula

Dopo la generazione automatica puoi sempre ritoccare singoli campi
(materie ammesse, capienza, multi-classe, indisponibilita\`, classi
affezionate) editando l'aula sulla pagina /classrooms.
