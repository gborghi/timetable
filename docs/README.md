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
| [constraints.md](constraints.md)           | i 5 stati dei vincoli (HARD / SOFT / PREFERRED / ENFORCED / ALLOWED), matrice di disponibilita', vincoli logici DSL, predicate atoms, mapping CP-SAT |
| [workflow.md](workflow.md)                 | pipeline di ottimizzazione: Phase A assegnazione, Phase B con decomposizione spettrale, cascata metaeuristica LNS / SA / TS / ILS, classroom assignment, drag-and-drop con preview |
| [ui_guide.md](ui_guide.md)                 | guida tab per tab della webui: Dashboard, Docenti, Classi, Indirizzi, Studenti, Gruppi, Materie, Aule, Compresenze, Cattedre, Orario, Assenze e supplenze, Monitor, Vincoli, Workflow |
| [api.md](api.md)                           | reference REST: gruppi di endpoint, formati request/response, esempi curl |
| [extending.md](extending.md)               | come aggiungere un nuovo tipo di vincolo, una nuova tabella, una nuova pagina UI |
| [experiments.md](experiments.md) ([IT](experiments_it.md)) | esperimenti e benchmark: due scuole da 90 classi (aula-classe `liceo90` vs aula-docente `liceo90doc`), decomposizioni temporale/curriculum/joint, statistiche previsto vs ottenuto |

## Ricompilare il manuale PDF

`docs/manual.pdf` segue gli stessi `.md` di questo indice. Per
rigenerarlo dopo aver modificato `manual.tex`:

```
# Linux / macOS / Git Bash:
docs/build_manual.sh
# Windows:
docs\build_manual.bat
```

La pipeline e' `lualatex -> biber -> makeindex -> lualatex x2`,
con cleanup degli aux files. Aggiungi `--quick` per saltare i
passi 2-3 quando stai iterando velocemente.

Per rigenerare il PDF automaticamente prima di ogni `git push`:

```
git config core.hooksPath .githooks
```

Il pre-push hook controlla se `manual.tex` o un .md sotto
`docs/` e' cambiato rispetto a `@{u}`, ricompila il PDF, lo
committa e poi prosegue. Lo skip una tantum:
`PITANTUM_SKIP_PDF=1 git push`.

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
