# piTantum - documentation index

> *Omnia, Lucili, aliena sunt, tempus tantum nostrum est.*
> &mdash; Seneca, *Ep.*, I, 1

Manuale tecnico e di riferimento del progetto **piTantum** (alias
**Tempus Tantum**, codename interno: `timetable`). La documentazione
e' organizzata in sette file tematici + un'analisi di miglioramento;
per una versione PDF stampabile con copertina e indice, vedere
[manual.pdf](manual.pdf).

| File                                       | Contenuto |
| ------------------------------------------ | --------- |
| [architecture.md](architecture.md)         | architettura webapp (FastAPI + SvelteKit + SQLite), avvio, struttura cartelle, launcher start.bat / start.sh / stop.sh |
| [data_model.md](data_model.md)             | schema SQLAlchemy (tutte le tabelle e relazioni), strategie di migrazione idempotente, formato pickle dell'engine |
| [constraints.md](constraints.md)           | i 5 stati dei vincoli (HARD / SOFT / PREFERITO / ENFORCED / ALLOWED), matrice di disponibilita', vincoli logici DSL, predicate atoms, mapping CP-SAT |
| [workflow.md](workflow.md)                 | pipeline di ottimizzazione: Phase A assegnazione, Phase B con decomposizione spettrale, cascata metaeuristica LNS / SA / TS / ILS, classroom assignment, drag-and-drop con preview |
| [ui_guide.md](ui_guide.md)                 | guida tab per tab della webui: Dashboard, Docenti, Classi, Indirizzi, Studenti, Gruppi, Materie, Aule, Compresenze, Cattedre, Orario, Assenze e supplenze, Monitor, Vincoli, Workflow |
| [api.md](api.md)                           | reference REST: gruppi di endpoint, formati request/response, esempi curl |
| [extending.md](extending.md)               | come aggiungere un nuovo tipo di vincolo, una nuova tabella, una nuova pagina UI |

## Avvio rapido

```
git clone https://github.com/gborghi/timetable
cd timetable/webui
# Windows
start.bat
# Linux / macOS
./start.sh
```

Backend FastAPI su http://127.0.0.1:8000, frontend Vite/SvelteKit su
http://127.0.0.1:5173. La pagina iniziale e' la Dashboard; per cominciare,
importa un profilo gia' calcolato (small / medium / big / huge / superhuge).

## File user-facing in webui/docs/

I file in [webui/docs/](../webui/docs/) sono guide brevi linkate dalla UI
stessa; coprono dettagli operativi come il formato Excel di import, la
sintassi delle query, le operazioni bulk. Sono complementari ai file qui
nella cartella docs/ (che invece sono riferimento tecnico).
