# Audit del manuale piTantum -- riscrittura didattica

Data: 2026-05-19
Branch: claude/silly-ritchie-efd66f (worktree)
Scope: rendere il manuale utilizzabile da un coordinatore d'orario alla prima esperienza con la web app.

## Sintesi numerica

| Metrica | Prima | Dopo | Delta |
|---|---|---|---|
| Pagine PDF (manual.pdf) | 311 | 315 | +4 |
| Dimensione PDF | 1.5 MB | 1.6 MB | +0.1 MB |
| Capitoli totali (cap.) | 30 | 31 | +1 |
| `guida_ui.tex` (linee) | 315 | 856 | +541 |
| `getting_started.tex` (linee) | 344 | 367 | +23 |
| `panoramica_pitantum.tex` (linee) | 346 | 370 | +24 |
| `workflow_tipici.tex` (linee) | 0 | 305 | +305 |

## File toccati

### Modificati con backup

- `docs/manual/chapters/guida_ui.tex` -- riscrittura completa (vedi sezione successiva). Backup: `guida_ui.tex.bak_pre_manual_didattico`.
- `docs/manual/chapters/getting_started.tex` -- ampliato il riquadro `erroricomunibox` finale da 3 a 9 casi. Backup: `getting_started.tex.bak_pre_manual_didattico`.
- `docs/manual/chapters/panoramica_pitantum.tex` -- aggiunto `ideabox` "Per i lettori impazienti" all'apertura del capitolo (cosa fa il sistema in 3 paragrafi + dove iniziare la lettura). Backup: `panoramica_pitantum.tex.bak_pre_manual_didattico`.
- `docs/manual.tex` -- inserito `\input{manual/chapters/workflow_tipici}` nella parte "Interfaccia e workflow". Backup: `manual.tex.bak_pre_manual_didattico`.

### Modificati senza backup (fix minore)

- `docs/manual/chapters/diagnostica_statistica.tex` -- aggiunta riga `\label{ch:diagnostica_statistica}` (mancava). Necessaria per il `cref` da `workflow_tipici.tex`.

### Aggiunti

- `docs/manual/chapters/workflow_tipici.tex` -- nuovo capitolo, sei procedure step-by-step (scuola da zero, import da Excel, rilancio pipeline, edit manuale, gestione supplenza, archivio).

### Artefatti di audit

- `manual_audit_samples/` -- sette PNG di pagine campione del PDF finale.
- `docs/manual.pdf` -- PDF compilato (lualatex + biber + makeindex + 3 passi lualatex).

## Cosa e' cambiato, sezione per sezione

### 1. Apertura del manuale -- `panoramica_pitantum.tex`

Inserito in cima al cap. 1 un `ideabox` (titolo "Intuizione") con tre voci sintetiche:

- *Per i lettori impazienti*: cosa fa il sistema in 3 frasi (input, output, interfaccia, tempo da zero a primo orario);
- *Per chi e' pensato*: utenti primari (coordinatori, vicepresidi, segreterie) e secondari (sviluppatori);
- *Dove iniziare la lettura*: salto diretto a `getting_started` (cap. 5), `guida_ui` (cap. 23) o `workflow_tipici` (cap. 24).

Effetto: un lettore alle prime armi capisce in venti secondi se il manuale fa per lui e dove andare a leggere il pezzo utile, senza dover scorrere trenta pagine di filosofia editoriale.

### 2. Quick start -- `getting_started.tex`

Il capitolo era gia' didattico (clonazione, dipendenze, due processi, import small, prima pipeline). Toccato solo l'`erroricomunibox` finale: da 3 casi a 9.

I sei casi aggiunti:

1. *Porta 5173 gia' in uso* -- come fermare un dev-server orfano (`stop.sh`, Task Manager Windows).
2. *Browser apre pagina bianca* -- diagnosi via console F12 e `GET /api/health`.
3. *Pipeline completata ma orario vuoto* -- come distinguere fallimento silenzioso da successo.
4. *Cambio matrice ma nessun effetto* -- ricordo che le matrici agiscono solo al successivo lancio di pipeline.

Linguaggio: tutti i casi sono nella forma "*sintomo*" + diagnosi specifica + comando puntuale.

### 3. Guida visuale all'interfaccia -- `guida_ui.tex` (riscrittura totale)

Versione precedente: 315 linee, scritta come ref tecnico per developer, organizzata per *feature trasversale* (Query DSL, multi-select, viste salvate, import/export) seguita da una mezza-pagina per tab. Difficile da usare per un docente che chiede "che cosa fa la tab Cattedre?".

Versione nuova: 856 linee, organizzata per *pagina dell'interfaccia*, con una sezione dedicata per ciascuna delle sedici tab.

Struttura nuova:

1. *Mappa delle sedici tab* (sez. 23.1) -- figura TikZ a colonne che raggruppa le tab in cinque famiglie (Inizio / Anagrafica / Vincoli / Calcolo / Risultato) con freccia tra famiglie, e sotto ogni famiglia l'elenco delle tab che le appartengono. Funziona da indice visuale.
2. *Convenzioni che si ripetono ovunque* (sez. 23.2) -- query DSL, sort, multi-select, import, export, viste salvate, tag. Spiegate una volta sola, con esempi concreti (`name contains rossi`, `kind in [lab_fisica, lab_chimica]`).
3. *Una sezione per ogni tab* (sez. 23.3 -- 23.17) -- Dashboard, Plessi, Docenti, Classi, Indirizzi, Studenti, Gruppi, Materie, Aule, Cattedre, Compresenze, Ore, Vincoli, Workflow, Runs, Orario, Monitor, Assenze/supplenze, Diagnostica, Import bulk.

Pattern ricorrente di ogni sezione tab:

- frase di apertura: a cosa serve la pagina;
- elenco dei campi/bottoni con descrizione operativa (cosa fa, cosa succede dopo);
- riquadro *Suggerimento* o *Esempio* concreto;
- riquadro *Attenzione* dove c'e' rischio di sbaglio (es. cambio griglia oraria dopo aver inserito matrici).

Riquadro finale `erroricomunibox` con quattro casi: lista vuota dopo import, bottone Salva grigio, righe scartate dall'import, drag-and-drop che non risponde.

### 4. Procedure tipiche -- `workflow_tipici.tex` (nuovo)

Sei procedure step-by-step, numerate, in lingua naturale. Ciascuna parte da uno scenario reale e termina con un risultato verificabile:

1. *Una scuola da zero* (8 passi: griglia oraria, anagrafica, cattedre, indisponibilita', snapshot, pre-check, pipeline, visualizzazione/rifinitura).
2. *Importare dati da Excel di un'altra scuola* (5 passi: template, rinomina colonne, import upsert, lettura report, ripeti per i sette fogli).
3. *Rilanciare la pipeline dopo un cambio di vincoli* (6 passi: snapshot di partenza, nuovi vincoli, pre-check, pipeline, confronto, eventuale ripristino).
4. *Editare a mano una singola lezione* (5 passi: vista per classe, drag-and-drop, lettura colori, scelta aula alternativa, export).
5. *Gestire una supplenza giornaliera* (6 passi: tab assenze, click giornata, spunta assenti, click celle rosse, drag supplenti, export bollettino).
6. *Esportare e archiviare l'orario* (3 passi: XLSX, DB completo, JSON dei vincoli).

Ogni procedura include almeno un `esempiobox`, un `erroricomunibox` o un `casostudiobox` con una situazione reale. Lessico Calvino-Buzzati-Borghi: frasi corte (12-22 parole), niente em-dash, niente anglicismi gratuiti dove esiste l'italiano (*procedura* invece di *workflow* nei titoli, *passo* invece di *step*).

## Audit di user-friendliness -- punti verificati

### Cosa abbiamo controllato

- Ogni termine tecnico ha una prima definizione esplicita. *Cattedra*, *plesso*, *gruppo articolato*, *cattedra di concorso*, *graduatoria_score*, *vincolo Hard/Soft/Preferred/Allowed/Enforced* -- tutti definiti in `terminologia_didattica.tex` (cap. 6) e ridefiniti operativamente nelle sezioni di `guida_ui.tex` in cui appaiono.
- Ogni operazione e' verificabile. I `Passo N` di `workflow_tipici.tex` chiudono ciascuno con un effetto osservabile ("compare un banner verde", "la cella diventa verde", "il pannello Cost si aggiorna").
- Ogni richiamo a tab/bottoni usa il nome che l'utente vede sullo schermo ("Workflow", "Salva snapshot", "Pipeline completa"), non il nome del file Svelte o dell'endpoint.
- Ogni concetto avanzato ha un escape: la sezione "Workflow" della `guida_ui` rimanda al cap. 13 per la teoria; le procedure rimandano alla diagnostica statistica e alle tecniche avanzate per i casi non coperti.
- Cinque riquadri `erroricomunibox` in tre capitoli diversi coprono i casi: setup ambiente, primo lancio, scuole da zero, import, edit manuale.

### Lessico modificato (esempi tipici)

| Prima (gergo dev/inglese) | Dopo (italiano didattico) |
|---|---|
| workflow tipico | procedura |
| step | passo |
| feature | funzione, funzionalita' |
| log streaming SSE | pannello di log in diretta |
| dropdown | menu' a tendina (alcune occorrenze) |
| frontend / backend | mantenuti dove tecnicamente necessari, glossati alla prima occorrenza |

### Riquadri editoriali usati

- `ideabox` (Intuizione) -- per orientamento iniziale, sintesi per il lettore impaziente.
- `esempiobox` -- esempi concreti incollabili (comando shell, DSL, scenario).
- `erroricomunibox` -- catalogo dei "perche' non funziona". Sempre nella forma *sintomo* + *causa* + *azione*.
- `avvertenzabox` -- "Attenzione" per operazioni distruttive (replace, cambio griglia).
- `casostudiobox` -- scenari reali (Liceo Galileo) per ancorare le procedure.
- `biblioparvabox` -- "Per approfondire", rimandi a capitoli specialistici.

## Compilazione

Pipeline standard del repo: `bash docs/build_manual.sh --it` (lualatex + biber + makeindex + 2 passi lualatex). Tempo totale ~ 45 secondi su macchina locale.

Output: `docs/manual.pdf`, 315 pagine, 1.6 MB. Zero `LaTeX Error`; zero `Reference undefined`; warning residui sono pre-esistenti (label benchmark duplicate dovute al doppio include dei capitoli legacy, fuori scope).

## Sample PNG

Sette pagine campione in `manual_audit_samples/`:

- `00_panoramica_callout_p27.png` -- apertura cap. 1 con il nuovo callout "Per i lettori impazienti / Per chi e' pensato / Dove iniziare la lettura".
- `01_panoramica_cosa_fa_p28.png` -- sez. 1.1 "Cosa fa il sistema".
- `02_per_iniziare_p52.png` -- apertura cap. 5 "Per iniziare".
- `03_errori_comuni_p53.png` -- riquadro `erroricomunibox` ampliato (9 casi).
- `04_guida_ui_mappa_tab_p202.png` -- diagramma TikZ "Mappa delle sedici tab" + apertura della sezione "Convenzioni che si ripetono ovunque".
- `05_guida_ui_dashboard_p205.png` -- sez. "Dashboard: la porta d'ingresso".
- `06_procedure_tipiche_p215.png` -- apertura cap. 24 "Procedure tipiche".

Le PNG sono a 130 DPI, dimensione tipica ~ 200 KB ciascuna.

## Branch policy

Tutto il lavoro e' su `claude/silly-ritchie-efd66f` (worktree). Niente push, niente merge, niente cherry-pick verso main. Decisione Giovanni: il merge su main e' responsabilita' tua, non automatica.

## Cosa NON e' stato fatto (per scelta o per scope)

- *Screenshot reali dell'interfaccia*: il sistema non era in esecuzione e nel repo non esistono screenshot pre-confezionati. La nuova `guida_ui` usa un diagramma TikZ astratto della mappa-tab; i singoli pannelli sono descritti a parole. Aggiungere screenshot reali e' un follow-up che richiede un'istanza in esecuzione e un giro guidato di cattura.
- *Indice analitico aggiornato*: gli `\index{...}` nuovi sono stati inseriti (Interfaccia utente, UI!guida, Tab!mappa, Workflow!tipico, Procedure, Casi d'uso); restano da rivedere le voci preesistenti che sono diventate stub dopo lo spostamento di contenuto.
- *Versione inglese (`manual_en.tex`)*: non toccata. Le modifiche dei capitoli IT non hanno controparte EN. Se serve allineare, va programmato a parte.
- *Capitoli teorici*: `metodo_cpsat`, `metodo_spettrale`, `metodo_lagrangian`, eccetera, restano tecnici come prima. Lo scope era la parte user-facing.

## Suggerimenti per il prossimo giro (non urgenti)

1. *Screenshots reali*: aprire il dev server, navigare le sedici tab, salvare uno screenshot per tab in `docs/manual/figures/ui/`, e sostituire l'occorrenza "vedi sez. 23.X" con `\includegraphics` annotato.
2. *Indice analitico*: rilanciare un audit di `\index{...}` su tutto il manuale, con regole di consistenza ("Tab!Dashboard" vs "Dashboard, tab").
3. *Allineamento EN*: tradurre `workflow_tipici.tex` e le modifiche a `guida_ui.tex` nella cartella `chapters_en/`.
4. *Glossario in coda al manuale*: il manuale gia' ha `glossario_discorsivo` in appendice; vale la pena uno spell-check finale per verificare che ogni termine usato nelle procedure sia voce del glossario.
