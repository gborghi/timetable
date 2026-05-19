# Audit del manuale piTantum -- retrofit con flow doc-coauthoring

Data: 2026-05-19
Branch: claude/manual-retrofit (worktree)
Base commit: `e88e98d` (precedente giro di riscrittura didattica).

Questo report integra e rimpiazza
`report_manual_audit.md` del giro precedente. Documenta il secondo
giro, condotto applicando in ordine le skill richieste:
doc-coauthoring -> writing-style -> humanizer -> ux-copy ->
design-critique -> overflow check -> compile.

## Sintesi numerica

| Metrica | Base (e88e98d) | Dopo retrofit | Delta |
|---|---|---|---|
| Pagine PDF | 315 | 325 | +10 |
| Dimensione PDF | 1.6 MB | 1.65 MB | +0.05 MB |
| Capitoli totali | 31 | 32 | +1 |
| `guida_ui.tex` linee | 856 | 863 | +7 (glosse) |
| `getting_started.tex` linee | 367 | 367 | 0 (em-dash sostituiti) |
| `panoramica_pitantum.tex` linee | 370 | 370 | 0 |
| `workflow_tipici.tex` linee | 305 | 305 | 0 |
| `formato_dati.tex` linee | 0 | 487 | +487 (nuovo) |
| Sample PNG | 7 | 10 | +3 |
| Compile errors | 0 | 0 | -- |
| Reference undefined | 0 | 0 | -- |
| Overflow visibili (>50pt) nei capitoli toccati | 1 (TikZ) | 0 | -1 |

## Step A. Outline

File: `outline_manual_didattico.md`.

Definisce obiettivo della riscrittura, pubblico (primario:
coordinatori, vicepresidi, segreterie; secondario: sviluppatori
che integrano dati), audit del draft pre-esistente, il capitolo
nuovo da scrivere (`formato_dati.tex` con sette schemi + schema
vincoli + ImportReport), i filtri da applicare (humanizer,
ux-copy, design-critique), i punti caldi dell'overflow tipografico,
l'ordine operativo e la definition of done.

L'outline ha guidato la priorita' degli step seguenti: prima il
contenuto mancante (Formato dati), poi le rifiniture, infine la
verifica.

## Step B. Audit del draft + capitolo nuovo

Audit del draft pre-esistente contro l'outline: i quattro
capitoli toccati nel giro precedente (panoramica, getting_started,
guida_ui, workflow_tipici) coprono panoramica, quick start,
sequenza di tab, procedure step-by-step. Mancanza identificata:
la specifica formale del formato CSV/Excel di import. Lacuna
verificata leggendo il codice di `webui/backend/routers/imports.py`
e il documento `webui/docs/import_format.md`: il sistema accetta
sette entita' (teachers, subjects, classes, classrooms, curricula,
students, groups) tramite endpoint unificato, ma il manuale non
ne riportava lo schema.

### Nuovo capitolo `formato_dati.tex`

Posizionato in `manual.tex` come capitolo 6 (dopo
`getting_started`, prima di `terminologia_didattica`). Logica:
una volta partito il sistema con il profilo di test, il lettore
vuole caricare i suoi dati e ha bisogno della specifica delle
colonne, prima di leggere il modello dati interno.

Sette sezioni:

1. Un endpoint, sette entita'. Glossa `endpoint` come "indirizzo
   HTTP che il browser chiama dietro le quinte quando premi un
   bottone della web app".
2. Convenzioni generali (header normalizzato, alias italiani/
   inglesi, booleani accettati, formato date, delimitatore CSV
   autorilevato, modalita' upsert/append/replace).
3. I sette schemi: una sottosezione per entita', ciascuna con
   tabella `Colonna | Alias | Tipo | Note`, mini-esempio CSV
   incollabile, identificativo, errori tipici.
4. Schema dei file di vincoli (`POST /api/dashboard/constraints/
   import-file`) con tabella record + esempio JSON.
5. ImportReport: struttura della risposta, lettura della UI,
   tabella dei campi.
6. Errori tipici: riquadro `erroricomunibox` con 7 casi
   (intestazioni non riconosciute, date in formato italiano,
   accenti rovinati, dipendenze tra entita', righe vuote
   silenziose, modalita' replace distruttiva, limite di
   upload).

Estensione: 487 linee, 9 tabelle, 7 esempi inline, 1
`erroricomunibox` ricco, 1 `avvertenzabox`, 1 `biblioparvabox`
finale con rimando al file canonico
`webui/docs/import_format.md`.

## Step C. Humanizer pass

Eseguito su tutti i cinque capitoli toccati (panoramica,
getting_started, guida_ui, workflow_tipici, formato_dati).

Pattern cacciati e risultati:

| Pattern | Occorrenze trovate | Azione |
|---|---|---|
| Em-dash (`---`) | 2 (getting_started lines 9, 194) | Sostituiti con virgole |
| Promotional language (intuitiv\*, potent\*, robust\*, all'avanguardia\*) | 0 | -- |
| Superficial -ing (permettendo di, consentendo di, garantendo che) | 0 | -- |
| Inflated symbolism (rappresenta, incarna, simboleggia) | 2 (uso tecnico) | Mantenuti (riferiti a pill colorate, valenza tecnica) |
| Vague attributions (alcuni esperti, molti utenti) | 0 | -- |
| Negative parallelism (non solo X ma anche Y) | 0 | -- |
| Filler (vale la pena, importante sottolineare) | 0 | -- |
| Hedge words (tipicamente, in particolare, in pratica, sostanzialmente) | 7 | 4 nel pre-esistente (panoramica), 3 nei nuovi -- revisti caso per caso, mantenuti dove descrittivi |
| Self-reference (questo capitolo, questa sezione) | 2 | Accettabile (intro di capitolo) |

Nessun rewrite distruttivo del testo, solo correzioni puntuali.
Il giro precedente aveva gia' rispettato la voce
Calvino-Buzzati-Borghi; questo giro ha rimosso le poche scorie
residue.

## Step D. UX-copy pass

Titoli di sezione: tutti sotto 40 caratteri tranne i sei
"Procedura N: <imperativo>" di `workflow_tipici.tex`, lasciati
volontariamente lunghi per favorire la navigazione dall'indice
analitico.

Callout (14 `\paragraph{Suggerimento.}` / `\paragraph{Attenzione.}`
nei capitoli nuovi): tutti nella forma sintetica
imperativo/indicativo presente, lunghezza media 25 parole, max
40 parole.

Didascalie di figure e tabelle (9 nuove nel capitolo
`formato_dati`, 1 in `guida_ui`): pattern uniforme "Cosa
rappresenta + come si legge", niente formule introduttive del
tipo "Questa figura mostra".

## Step E. Design-critique novice-reader

Letto come docente alla prima esperienza. Termini tecnici che
restavano senza definizione alla prima occorrenza e che sono
stati glossati:

- `endpoint` -- glossa inserita in `formato_dati.tex` sez. 6.1
  ("indirizzo HTTP che il browser chiama dietro le quinte
  quando premi un bottone della web app").
- `AST` -- rimosso da `guida_ui.tex` sez. Vincoli, sostituito
  con "albero sintattico".
- `SSE` -- rimosso da `guida_ui.tex` sez. Workflow, sostituito
  con "il pannello si aggiorna da solo, riga per riga, senza
  che tu debba ricaricare la pagina".
- `CRUD` -- rimosso da `guida_ui.tex` sez. Tag, sostituito con
  "piccolo pannello per rinominare o eliminare".

Termini gia' glossati nel manuale (verifica positiva): `pipeline`
(prologo + getting_started), `Hard/Soft/Preferred`
(terminologia + vincoli), `snapshot` (guida_ui dashboard),
`drag-and-drop` (guida_ui orario), `DSL` (guida_ui convenzioni).

## Step F. Overflow check

### Caso bloccante corretto

`guida_ui.tex` sezione 24.1 "Mappa delle sedici tab": la
figura TikZ con cinque famiglie in colonna sforava di circa
2.5 cm la `\textwidth`, con la quinta colonna ("5. Risultato")
e le sue tab tagliate al margine destro. Verifica visiva via
`pdftocairo` pagina 212.

Fix applicato:

```latex
\resizebox{\textwidth}{!}{%
\begin{tikzpicture}[node distance=0.55cm and 0.45cm,
  fam/.style={..., minimum width=2.8cm, ...},
  tab/.style={..., minimum width=2.2cm, ...},
  ...
\end{tikzpicture}%
}
```

Ricompilato e verificato visualmente
(`07_guida_ui_mappa_tab_p212.png`): tutte e cinque le famiglie e
tutte le 16 tab visibili dentro la `\textwidth`.

### Casi non bloccanti

Overfull hbox segnalati dal log:

| Magnitudine | Provenienza | Azione |
|---|---|---|
| 269 pt | `manual/benchmarks/charts_generated.tex` (autogenerato) | Fuori scope. Non toccato. |
| 100-160 pt | benchmark legacy chapters | Fuori scope |
| 5-50 pt | testi pre-esistenti capitoli tecnici | Fuori scope |
| > 5 pt nei 5 capitoli toccati | -- | 0 occorrenze |
| < 5 pt nei 5 capitoli toccati | -- | drift microtype, trascurabile |

Verifica fatta con awk sul log lualatex (tracking del file
sorgente al momento dell'overflow).

### Verifiche visive

Estratti 10 PNG di pagine campione dei contenuti modificati o
nuovi (vedi sez. Sample PNG). Tutti i diagrammi, tabelle, listing
visualmente entro margine; nessun testo tagliato.

## Step G. Compile finale

Pipeline `bash docs/build_manual.sh --it` (lualatex + biber +
makeindex + 2 passi lualatex). Risultato:

- `docs/manual.pdf`: 325 pagine, 1.65 MB.
- 0 errori LaTeX.
- 0 reference undefined.
- 0 citation undefined.
- 0 multiply-defined label introdotti dal giro corrente (i pochi
  residui sono pre-esistenti nei benchmark legacy).

## Step H. Sample PNG

Dieci pagine campione in `manual_audit_samples/`, DPI 130:

| File | Pagina | Contenuto |
|---|---|---|
| `00_panoramica_callout_p27.png` | 27 | Apertura cap. 1 con ideabox "Per i lettori impazienti" |
| `01_panoramica_cosa_fa_p28.png` | 28 | Cosa fa il sistema (sez. 1.1) |
| `02_per_iniziare_p52.png` | 52 | Apertura cap. 5 "Per iniziare" |
| `03_errori_comuni_p53.png` | 53 | Erroricomunibox ampliato (9 casi) |
| `04_formato_dati_intro_p57.png` | 57 | Apertura cap. 6 "Formato dati" |
| `05_formato_dati_tabelle_p60.png` | 60 | Tabelle schema teachers/subjects + esempi |
| `06_formato_dati_vincoli_p63.png` | 63 | Schema groups + schema vincoli + JSON di esempio |
| `07_guida_ui_mappa_tab_p212.png` | 212 | Mappa delle 16 tab TikZ (dopo fix resize) |
| `08_guida_ui_dashboard_p215.png` | 215 | Sezione Dashboard (didascalica) |
| `09_procedure_tipiche_p225.png` | 225 | Apertura cap. 25 "Procedure tipiche" |

## Differenze dal giro precedente

Il primo giro (commit `e88e98d`) aveva prodotto la riscrittura
didattica di `guida_ui.tex`, il nuovo `workflow_tipici.tex`,
l'ideabox di apertura panoramica e nove casi `erroricomunibox`
in `getting_started.tex`. Mancava una specifica formale del
formato dati di ingresso, alcune glosse erano omesse per il
lettore novice, e la figura TikZ "Mappa delle sedici tab"
sforava il `\textwidth`.

Il secondo giro (questo) ha aggiunto il capitolo `formato_dati`,
glossato i termini residui, sistemato l'overflow della mappa-tab,
rifinito em-dash residui in `getting_started`. Le differenze sono
chirurgiche; il corpo dei capitoli del primo giro resta valido.

## Open follow-up

Stessi del giro precedente, ancora aperti:

1. Screenshots reali dell'interfaccia (richiede istanza in
   esecuzione, non disponibile nel worktree).
2. Allineamento della versione inglese (`chapters_en/`).
3. Audit dell'indice analitico per consistenza voci.
4. Tradurre il nuovo `formato_dati.tex` in `chapters_en/`.

Nuovi follow-up emersi:

5. La tabella autogenerata `charts_generated.tex` sfora di 269 pt
   (pre-esistente, fuori scope). Sarebbe da rilanciare lo script
   `gen_charts.py` con un layout ridotto o usare `landscape` sui
   suoi blocchi piu' larghi.
