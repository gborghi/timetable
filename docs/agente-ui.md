# Agente UI — etichette, 2026-10-30

Branch `ui-etichette`. Non è stato toccato `main`. Il solver e
`WeeklyCalendarView` (struttura) non sono stati cambiati: nel calendario
sono cambiate solo le parole della legenda.

## Commit

| hash | cosa |
| --- | --- |
| `eb780c1` | Stati e tipi dei run in italiano, con le parole già scritte (Fase A/B, in coda, in corso, titoli delle diagnostiche). |
| `931a980` | Livelli dei vincoli: le glosse già scritte al posto di HARD/SOFT e delle sigle sorelle. I valori inviati al solver non cambiano. |
| `0718b06` | Voci di menu dalle chiavi i18n. Workflow, Runs e Import bulk diventano Ottimizza, Esecuzioni e Importa. |

Questo file è l'ultimo commit.

## Collegati

Conteggio vero delle etichette il cui testo visibile è passato
dall'inglese (o dal codice tecnico) all'italiano già presente nel
frontend: **36**. Non è il 31 di Atlas: quella lista non c'era, e non
l'ho riempita.

Stati dei run (5): `pending` → in coda, `running` → in corso,
`done` → completato, `failed` → fallito, `cancelled` → annullato.
Le pillole «success» / «error» usano le stesse due parole
(completato / fallito).

Tipi dei run (8): Fase A, Fase B, Pre-check fattibilità (Hall),
Monte Carlo, Analisi bipartito, Correlazioni e regressioni,
Distribuzioni, Orario parziale. I quattro `phase_b_*` di
decomposizione usano le etichette già in `pipeline_labels`.

Intestazioni dei run (6): Obiettivo, Fase, Campioni, passo,
run asincrono, Avanzamento. «Feasible (Hall OK)» → «Fattibile (Hall ok)».

Livelli (6): Obbligatorio, Penalizzato, Preferenza, Imposto,
Consentito, Vietato. Nella matrice di disponibilità il rosso resta
«non disponibile», non «obbligatorio»: lì HARD voleva dire un'altra
cosa. Penalty → Penalità. Infeasible / feasible → non fattibile /
fattibile. RESET → azzera.

Menu (3): Workflow → Ottimizza, Runs → Esecuzioni, Import bulk → Importa.
Le altre chiavi di `locales/it.ts` (Docenti, Classi, Indirizzi,
Compresenze, Eventi, Statistiche, Assenze e supplenze, …) sono
collegate alla barra: il testo visibile era già quello giusto, e non
l'ho riportato a Curricula, Coteaching o Monitor.

## Saltati, e perché

- **Dashboard.** La chiave i18n è essa stessa «Dashboard». «Panoramica»
  è solo l'inizio del suggerimento, non un'etichetta di menu già usata.
  Rinominarla sarebbe stato un nome nuovo.
- **`imported`.** Nessuna etichetta italiana già scritta per quel kind.
  In tabella resta il codice, nel tooltip.
- **LNS, ALNS, SA, TS, VNS, ILS, Column Generation, Lagrangian.**
  Nel frontend ci sono solo le sigle e le espansioni inglesi. Il
  glossario ha le descrizioni, ma non è una stringa morta della UI.
  Non ho inventato «ricerca a grande vicinato» e simili. Nelle etichette
  della pipeline ho tolto solo il parentetico inglese dove non c'era
  un italiano già scritto (Adaptive LNS, Variable Neighbourhood Search).
- **`supply`** accanto a «domanda» nelle card Hall. Non c'è «offerta»
  già scritta.
- **`common.*` in `locales/it.ts` (11 chiavi: Salva, Annulla, Elimina,
  Conferma, Modifica, Crea, Cerca, Caricamento, Errore, Nessun elemento,
  Azioni).** Il markup ha già quelle parole in italiano, sparpagliate.
  Collegarle non cambia il testo e tocca decine di file. Restano chiavi
  non usate.
- **Query DSL** (`kind = phase_b`, `stato = done`). Sono il linguaggio
  che il backend accetta, non etichette. Gli esempi restano.

## Verifica

In `webui/frontend`, prima del push:

- `npm ci --no-audit --no-fund`: ok (308 pacchetti).
- `npm run check`: 0 errori, 0 avvisi.
- `npm test`: 108 passati, 0 falliti.
- `npm run build`: ok (`adapter-static`, sito in `build`).

Nessun tentativo fallito, nessun revert.

## Push

Solo `ui-etichette`, non `main`.

https://github.com/gborghi/timetable/tree/ui-etichette
