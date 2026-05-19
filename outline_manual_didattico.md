# Outline -- Manuale didattico piTantum (riscrittura mirata)

Stato del manuale al commit base `e88e98d`: 315 pagine, 31 capitoli. Tre
parti narrative (Per iniziare, Modello dati, Vincoli), tre parti
tecniche (Il DSL, Solver, Interfaccia e workflow), una parte
benchmark, un'appendice. La riscrittura si concentra esclusivamente
sulle parti che un utente non sviluppatore tocca davvero.

## Obiettivo della riscrittura

Portare un coordinatore d'orario alla prima esperienza dal nulla a un
orario verificato in browser senza dover leggere il codice. Strumenti
di lettura: indice analitico, riquadri editoriali, mappa visuale
delle tab, procedure passo-passo, tabelle di formato dati.

## Pubblico

Primario: coordinatori d'orario, vicepresidi, segreterie didattiche.
Hanno familiarita' con Excel e con il modulo classico dell'orario;
non con Python, non con SQL, non con CP-SAT.

Secondario: sviluppatori che integrano dati propri (file Excel di
una scuola che usa un altro sistema), che hanno bisogno della
specifica esatta del formato di import.

## Audit del draft pre-esistente

I capitoli sotto sono gia' stati riscritti (commit `e88e98d`). Vanno
rivisti con i tre filtri (humanizer, ux-copy, design-critique) e
verificati per overflow tipografico.

1. `panoramica_pitantum.tex` -- apertura con `ideabox` "Per i
   lettori impazienti". Buono come orientamento iniziale; controllare
   che la lista "Dove iniziare la lettura" abbia rimandi sempre
   verificati.
2. `getting_started.tex` -- ampliato `erroricomunibox` da 3 a 9 casi.
   Controllare che i casi nuovi non abbiano AI-pattern (rule-of-three,
   triplet rituali).
3. `guida_ui.tex` -- riscrittura completa, 856 linee. Sezione per
   tab; controllare la sezione "Mappa delle sedici tab" per overflow
   TikZ; verificare didascalia figura.
4. `workflow_tipici.tex` -- nuovo capitolo, 6 procedure.
   Controllare ogni listing inline per overflow orizzontale.
5. `manual.tex` -- wire del nuovo capitolo dentro la parte
   "Interfaccia e workflow".

## Capitolo nuovo da scrivere

### `formato_dati.tex` -- "Formato dei dati di ingresso"

Posizionamento: cap. successivo a `getting_started`, prima della
parte "Modello dati". Logica: una volta partito il sistema con il
profilo di test, il lettore vuole caricare i SUOI dati e ha bisogno
della specifica esatta delle colonne.

Sezioni previste:

1. **Endpoint unico, sette entita'**. Descrizione di
   `POST /api/import/{entity}` e di
   `GET /api/import/{entity}/template`; il bottone "Importa Excel/CSV"
   della UI usa quegli stessi endpoint.
2. **Convenzioni generali**. Header normalizzato (case-insensitive,
   underscore/spazi interscambiabili), alias italiano/inglese, valori
   booleani accettati, formato date ISO, autodelimiter CSV, riga vuota
   ignorata.
3. **Tre modalita'**: `upsert` (default), `replace` (distruttivo),
   `append`.
4. **Sette schemi**. Una sottosezione per ciascuna entita':
   teachers, subjects, classes, classrooms, curricula, students,
   groups. Per ciascuna: tabella `colonna | alias | tipo | note`,
   mini-fixture inline (3-5 righe), identificativo della riga,
   errori tipici. Aggiungere `assignments` e `subject_group_weights`
   come due sottosezioni minori in coda (l'endpoint le accetta ma il
   workflow tipico non le passa via file).
5. **Schema dei vincoli**. Sotto-sezione separata per i file di
   vincoli (`POST /api/dashboard/constraints/import-file`): record
   con `kind`, `scope`, `owner_name`, `level`, `expression`,
   `soft_penalty?`, `description?`. Esempio JSON, esempio xlsx.
6. **Risposta dell'endpoint -- ImportReport**. Tabella dei campi:
   `ok`, `entity`, `n_inserted`, `n_updated`, `n_skipped`,
   `n_total_rows`, `messages`, `errors`. Esempio JSON. Come leggere
   gli errori nel pannello UI.
7. **Errori tipici**. Riquadro `erroricomunibox`: header rinominato
   in modo non riconoscibile, valore boolean scritto come "no"
   invece di "false", date in formato italiano `dd/mm/yyyy` che
   diventano `null`, accenti rovinati su CSV non UTF-8, riferimenti
   a entita' inesistenti (es. studente con `class_name=1A` mentre
   1A non esiste ancora).

Estensione attesa: 350-450 linee, 6-8 mini-tabelle, 4-6 esempi
inline, 1 `erroricomunibox` ricco.

## Filtri da applicare a tutti i capitoli toccati

### C. Humanizer

Pattern da cacciare (lista da Wikipedia "Signs of AI writing" +
istinto editoriale Borghi):

- *Rule of three*: triplette ritmate non motivate da contenuto.
- *Inflated symbolism*: "rappresenta", "incarna", "simboleggia"
  applicati a entita' tecniche.
- *Promotional language*: "potente", "robusto", "intuitivo",
  "all'avanguardia".
- *Superficial -ing analyses*: "permettendo di", "consentendo di",
  "garantendo che".
- *Vague attributions*: "alcuni esperti", "molti utenti", "spesso
  si dice".
- *Em-dash overuse*: ammessi due punti e parentesi tonde; gli em-dash
  vanno sostituiti da virgole o punti.
- *Negative parallelism*: "non solo X, ma anche Y" usato a tappeto.
- *Filler phrases*: "vale la pena notare che", "e' importante
  sottolineare".

### D. UX-copy

- Titoli sezione: max 6-7 parole, sostantivi concreti,
  evita le forme passive ("Come si configura X" -> "Configurare X").
- Callout `\paragraph{Suggerimento.}`: imperativo o indicativo
  presente, max 30 parole.
- Callout `\paragraph{Attenzione.}`: sintomo concreto + conseguenza
  concreta, max 25 parole.
- Didascalie figura/tabella: 1 frase di apertura (cosa rappresenta)
  + 1 frase di lettura (come la si legge). No "questa figura mostra".

### E. Design-critique novice-reader

Lista di cose che un docente alla prima lettura NON puo' sapere e
che devono essere esplicitate alla prima occorrenza:

- *SQLite*: non e' "un database" generico, e' un file.
- *Endpoint*: e' una URL che il browser chiama.
- *DSL*: linguaggio di interrogazione, non un acronimo da gergo.
- *Hard/Soft/Preferred*: gia' coperto in cap. vincoli, ma va
  richiamato in ogni callout che ne usa il termine.
- *Pipeline*: e' il calcolo dell'orario, non un termine astratto.
- *Match*: e' "corrispondenza".
- *Snapshot*: e' "punto di salvataggio".

### F. Overflow tipografico

Punti caldi noti:

- `guida_ui.tex` sez. 23.1 -- figura TikZ "Mappa delle sedici tab".
  Cinque colonne in larghezza, da verificare con `\textwidth`.
- `guida_ui.tex` sez. 23.12 (Cattedre) -- listing in pseudo-codice
  con `[SFORA: +Xh]` a fine riga, potenziale break.
- `workflow_tipici.tex` sez. 24.1 -- `esempiobox` con tre vincoli
  DSL inline; controlla che le frasi DSL non escano.
- Tutte le tabelle del nuovo capitolo `formato_dati.tex`:
  obbligatorio `\begin{tabular}` con `\resizebox` di sicurezza.

## Ordine operativo definitivo

A. **Outline** (questo file) -- fatto.
B. **Audit draft + nuovo capitolo** `formato_dati.tex`.
C. **Humanizer** sui 5 capitoli toccati.
D. **UX-copy** su titoli, callout, didascalie.
E. **Design-critique novice-reader** finale.
F. **Overflow check** -- compile, sample PNG di pagine sospette,
   fix.
G. **Compile pulito** lualatex + biber + makeindex + lualatex x 2.
H. **Sample PNG + report**.
I. **Commit + push origin main + delete service branch**.

## Definition of Done

- 0 errori LaTeX, 0 reference undefined.
- 0 listing/tabella che sfora `\textwidth`.
- 7 schemi entita' + 1 schema vincoli completi nel nuovo capitolo.
- 0 occorrenze di em-dash nei capitoli toccati (ricerca testuale).
- Almeno 8 PNG di sample che coprono tutti i nuovi contenuti.
- Report finale aggiornato con sezione "Cambiamenti del giro
  retrofit", una sotto-sezione per ciascun pass (humanizer,
  ux-copy, design-critique, overflow).
