# Timetable WebUI

Interfaccia web per il motore di ottimizzazione orario in `experiments/`.
Backend FastAPI + Python venv; frontend SvelteKit + Tailwind. Persistenza
locale su SQLite (`webui/data/timetable.db`).


## Cosa offre

- CRUD completo: docenti, classi, materie, **aule**, **compresenze**, cattedre.
- Workflow di ottimizzazione a 9 step (genera mock, importa pickle, assegna
  docenti -> classi, schedula orario con decomposizione spettrale, LNS, SA, TS,
  ILS, assegna aule, pipeline completa).
- Visualizzazione orario per classe / docente / aula / slot, con
  drag-and-drop manuale validato (HARD live + delta SOFT).
- Export xlsx (riusa `experiments/exporters.py`) e PDF (reportlab).
- Tool "Chi e\` libero?" per supplenze al volo.
- Log live degli step di ottimizzazione via SSE.


## Prerequisiti

- **Python >= 3.10** (test fatto con 3.13).
- **Node.js >= 18** (consigliato LTS). Se manca, scaricalo da
  <https://nodejs.org/> oppure (su Windows con winget) lancia:
  ```
  winget install OpenJS.NodeJS.LTS
  ```
- Su Windows la cartella `experiments/` deve restare al suo posto, accanto
  a `webui/` (lo sa il backend tramite path relativi).


## Verifica installazione

Apri un nuovo terminale (cmd o PowerShell) e controlla che siano disponibili:

```
python --version       (atteso: 3.10 o superiore)
node --version         (atteso: v18 o superiore; v24.x va benissimo)
npm --version          (atteso: 10.x o superiore)
```

Output sul sistema testato (riferimento):

```
Python 3.13.13
v24.15.0
11.12.1
```

Se uno dei tre non risponde, vai alla sezione "Prerequisiti" o "Troubleshooting".


## Setup una tantum

Apri PowerShell oppure cmd nella cartella del progetto (la radice che
contiene `webui/` e `experiments/`).

### Backend

```
cd webui\backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Se gia\` lanciato lo step "installa dipendenze backend" da Claude, hai
gia\` `.venv` pronto -- saltalo.

### Frontend

```
cd webui\frontend
npm install
```

`npm install` scarica `node_modules/` (~150 MB; al primo lancio impiega
qualche minuto).


## Avvio quotidiano

### Modo veloce (Windows)

Doppio-clic su `webui\start.bat` (oppure `start.ps1` da PowerShell).

Si aprono **tre finestre**:

1. **Quella del lancio**: stampa lo stato dei controlli (Node trovato,
   venv presente, node_modules presente, porte libere) e poi attende un
   tasto. Puoi chiuderla quando i server sono pronti — i due figli vivono
   da soli.
2. **"Timetable backend"** (cmd): qui scorre il log di Uvicorn / ortools.
3. **"Timetable frontend"** (cmd): qui scorre il log di Vite / SvelteKit.

Aspetta ~10 secondi che entrambi siano pronti, poi apri:

- Backend  -> <http://127.0.0.1:8000/api/health>
- Frontend -> <http://127.0.0.1:5173>  (apri **questo** nel browser)

**Per fermare i server**: chiudi le finestre "Timetable backend" e
"Timetable frontend" (oppure premi `Ctrl+C` in ciascuna).

Se al lancio compare un avviso "porta gia\` in uso", c'e\` un'istanza
precedente ancora attiva. Chiudi le sue finestre prima di rilanciare.

### Modo manuale

Apri **due terminali** distinti.

Terminale 1 (backend):
```
cd webui
backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Terminale 2 (frontend):
```
cd webui\frontend
npm run dev
```

Apri <http://127.0.0.1:5173>.

### Come fermare

Premi `Ctrl+C` in ciascuna finestra, oppure chiudile.


## Cosa cliccare per primo

Apri <http://127.0.0.1:5173> nel browser e prova in quest'ordine:

1. <http://127.0.0.1:5173/> - Dashboard, contatori dataset.
2. <http://127.0.0.1:5173/teachers> - lista docenti (20 dal mock small importato).
3. <http://127.0.0.1:5173/classes> - lista classi.
4. <http://127.0.0.1:5173/classrooms> - aule (16 generate dal recipe).
5. <http://127.0.0.1:5173/optimize> - workflow 9-step.
6. <http://127.0.0.1:5173/schedule> - orario (vista per classe / docente / aula / slot, drag-drop attivo).
7. <http://127.0.0.1:5173/free-now> - tool "chi e libero?".

Se il database e\` vuoto, parti dalla Dashboard e premi "Importa profilo small" oppure "Genera scuola di test".


## Flusso tipico (5 minuti)

1. Vai su **Dashboard**.
2. "Importa un profilo gia\` calcolato" -> scegli `small` -> Importa.
   In ~10 secondi viene caricata una scuola da 10 classi + 20 docenti +
   la soluzione gia\` ottimizzata.
3. Click "Genera aule per profilo" (default `small`): popola 16 aule
   (1 per classe + lab + palestra + biblioteca).
4. Vai su **Workflow** -> step 8 "Assegna aule" -> Avvia. In pochi
   secondi ogni lezione riceve un'aula.
5. Vai su **Orario**.
   - Cambia vista: per classe / per docente / per aula / per slot.
   - Trascina una cella su un altro slot: il backend valida HARD live
     e mostra il delta SOFT.
6. Esporta in xlsx (classi e docenti) o in PDF dai bottoni in alto.
7. Tool "Chi e\` libero?" per vedere chi e\` libero in un dato slot.

Per uno scenario "from scratch" senza pickle:
1. Dashboard -> "Genera scuola di test" (small / medium / big / huge / superhuge).
2. **Workflow** -> 2) "Assegnazione docenti -> classi" -> Avvia.
3. **Workflow** -> 3) "Schedulazione orario (Phase B)" -> Avvia.
4. (Opz.) 4-7 metaeuristiche per migliorare la SOFT.
5. Genera aule (Dashboard) e poi 8) "Assegna aule".


## Modifica dati a mano

- **Docenti** (`/teachers`): vincoli HARD (indisponibilita\`, giorni
  liberi obbligatori, max consecutive) e pesi SOFT.
- **Classi** (`/classes`): toggle dei vincoli HARD per classe + pesi
  SOFT, lista materie e ore settimanali.
- **Aule** (`/classrooms`): tipo, capienza, multi-classe, materie
  ammesse (anche HARD), classi affezionate, indisponibilita\`.
- **Compresenze** (`/coteaching`): regole "in questa lezione vanno N
  docenti", HARD o SOFT con peso.
- **Cattedre** (`/assignments`): cambia il docente per (classe, materia)
  con validazione live (capienza, abilitazione, esistenza). Lock per
  fissare un'assegnazione.


## Persistenza

- DB: `webui/data/timetable.db` (SQLite). Cancellalo per ripartire da zero,
  oppure dalla Dashboard premi **Reset DB**.
- Output runs: `webui/data/runs/<run-id>/` contiene pickle di stato
  intermedi (school, profs, dc_value, solution).


## Vincoli supportati

Vedi `webui/docs/constraints.md` per l'elenco esaustivo (HARD + SOFT
con peso default e descrizione).


## Troubleshooting

### "Address already in use" sulla 8000 o 5173

Qualcuno e\` gia\` in ascolto. Da PowerShell:

```
Get-Process | Where-Object { $_.MainWindowTitle -match 'Timetable' } | Stop-Process
```

Oppure `netstat -ano | findstr :8000` per scoprire il PID e poi
`Stop-Process -Id <pid>`.

### `ModuleNotFoundError: No module named 'backend'`

Stai lanciando uvicorn dalla cartella sbagliata. Devi essere in
`webui/`, non in `webui/backend/`.

### `start.bat` "non sembra fare nulla"

Sintomi tipici: doppio-click sul file, una finestra cmd lampeggia un
attimo, e poi piu\` niente; nessuna finestra "Timetable backend" o
"Timetable frontend" sembra apparire.

**Cause possibili**, in ordine di probabilita\`:

1. **PATH non aggiornato dopo install di Node.** L'installer Node aggiunge
   `C:\Program Files\nodejs` al PATH macchina, ma Esplora Risorse e i
   suoi figli (cmd lanciate da doppio-click) leggono il PATH al momento
   del proprio avvio. Se Esplora Risorse era gia\` aperto prima
   dell'installazione di Node, il doppio-click su `start.bat` produce
   una cmd con PATH vecchio. **`start.bat` rimedia a questo gia\` da
   solo**, aggiungendo `C:\Program Files\nodejs` esplicitamente; ma se
   Node e\` installato in una path inusuale, lo script non lo trova e
   lo segnala.

   *Soluzione:* riavvia Esplora Risorse (apri Task Manager,
   trova "Esplora Risorse" o "Windows Explorer", clic destro
   "Riavvia"), oppure semplicemente fai logout / login.

2. **Doppio-click ha aperto e chiuso la finestra principale.** Lo script
   fa un `pause` finale, quindi la finestra principale dovrebbe restare
   aperta finche\` premi un tasto. Se l'hai chiusa subito, il messaggio
   ti scappa. Riapri manualmente: clicca con tasto destro -&gt; "Modifica"
   per leggere il contenuto, oppure apri un cmd e lancialo a mano:
   `cd webui  &  start.bat`.

3. **Porte 8000 / 5173 gia\` in uso.** Se un altro `start.bat` e\`
   ancora attivo, le finestre figlie nuove falliscono il bind. Lo
   script segnala "porta gia\` in uso" prima di lanciare. *Soluzione:*
   chiudi le finestre "Timetable backend" / "Timetable frontend"
   delle istanze precedenti.

4. **Il venv Python non esiste.** Lo script mostra l'errore con il
   comando preciso da lanciare per crearlo (vedi sezione Setup).

5. **`node_modules` non esiste.** Lo script lancia `npm install`
   automaticamente; aspetta 2-4 minuti e vedrai progressi a video.

Se anche dopo questi controlli `start.bat` non avvia i server, lancia
i due comandi a mano in due finestre cmd separate (vedi "Modo manuale"
sotto): l'output di errore sara\` immediatamente visibile.


### `npm is not recognized` (o `npm: command not found`, `node: command not found`)

Node.js non e\` installato (oppure non e\` in PATH). Soluzione:

1. Scarica l'installer **Windows MSI LTS** da:
   <https://nodejs.org/en/download>
2. Esegui l'installer. Lascia la spunta **"Add to PATH"** (default).
3. **Chiudi e riapri** la finestra del terminale (e Esplora Risorse, se hai
   start.bat aperto): la variabile PATH si aggiorna SOLO nei nuovi processi.
4. Verifica: in un nuovo cmd, `node --version` e `npm --version` devono
   stampare versioni (es. `v20.x.x`).
5. Vai in `webui\frontend` e lancia `npm install` (~150 MB, 2-4 minuti).
6. Rilancia `start.bat`.

Lo `start.bat` controlla la presenza di npm e ti guida con un messaggio
chiaro se manca.

### Frontend si lamenta di proxy verso 8000

Verifica che il backend sia in esecuzione su 127.0.0.1:8000.
Health check: <http://127.0.0.1:8000/api/health> (deve rispondere
`{"status":"ok"}`).

### Una run di ottimizzazione resta "running"

Le run girano in thread Python; ortools puo\` impiegare minuti su
istanze grandi (huge / superhuge). Il log live arriva via SSE; se il
log si blocca, controlla nel terminale del backend per eccezioni.


## Architettura

```
webui/
  backend/
    main.py            FastAPI app
    db.py              SQLAlchemy engine/session
    models.py          tabelle ORM
    schemas.py         Pydantic
    engine_io.py       conversione DB <-> pickle del motore
    optimization.py    wrappers per i moduli in experiments/
    classroom_assignment.py via experiments/classroom_assignment.py
    mock_classrooms.py recipe aule
    run_manager.py     thread + SSE log streaming
    routers/           endpoint REST
  frontend/
    src/routes/        pagine SvelteKit (1 cartella per pagina)
    src/lib/api.js     client REST + SSE
    src/lib/components Toast, RunLogPanel, Modal
    src/app.css        Tailwind layer
  data/
    timetable.db       SQLite
    runs/<id>/         pickle intermedi
  docs/constraints.md  documentazione vincoli
  start.bat / start.ps1 launcher
```

Il backend importa i moduli `experiments/*.py` direttamente, senza
modificarli. Tutta la logica di solver / metaeuristiche / spectral
clustering / decomposizione resta in `experiments/`. Il modulo
`experiments/classroom_assignment.py` e\` un'aggiunta nuova,
indipendente dai moduli esistenti.


## Sviluppo

- Hot-reload backend: aggiungi `--reload` a uvicorn.
- Hot-reload frontend: gia\` attivo via Vite.
- API doc: <http://127.0.0.1:8000/docs> (Swagger generato da FastAPI).
