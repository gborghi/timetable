# Report — Purge duplicazioni capitolo avanzato + Sync EN

Sessione: 2026-05-19, branch `claude/jolly-goldstine-c6c100`.
Lavoro autonomo (caveman, no conferme). Backup `.bak_pre_*` per ogni file toccato.

## 1. Scope

Due fasi:

1. **Purge IT** — `docs/manual/chapters/tecniche_di_ottimizzazione_avanzate.tex` purgato delle tecniche già spiegate nei capitoli dedicati (CP-SAT, Hall, spettrale, metaeuristiche, lagrangian, workflow).
2. **Sync EN** — Allineamento di `docs/manual/chapters_en/tecniche_di_ottimizzazione_avanzate.tex` al purge IT + refresh degli stub EN `panoramica_pitantum.tex` e `guida_ui.tex` per riflettere i recenti aggiornamenti IT (`e88e98d`, `e8e9fe7`).

## 2. Tabella duplicazione → azione

| Sezione (cap. avanzato IT, pre-purge) | Già spiegato in | Azione presa |
|---|---|---|
| §1 Adaptive Large Neighborhood Search (ALNS) | `metodo_metaeuristiche.tex` §"Adaptive LNS: scolpire con scalpelli adattivi" | RIMOSSA — descrizione cancellata, signpost iniziale rimanda al cap. dedicato |
| §2 Variable Neighborhood Search (VNS) | `metodo_metaeuristiche.tex` §"Variable Neighborhood Search: cambiare obiettivo" | RIMOSSA — idem |
| §3 Hall's theorem pre-check | `metodo_hall.tex` (intero capitolo) | RIMOSSA — idem |
| §4 Column Generation e BP avanzato (bullet overview) | trattato in profondità nella sezione "BP: anatomia" più sotto + intro in `metodo_lagrangian.tex` §"Column Generation: il catalogo immobiliare" | RIMOSSO il sommario duplicato; i contenuti restano nella sezione "BP anatomia" (con maggiore profondità) |
| §4 "Numeri misurati MEGA" (statsbox) | inedito, ma posizionato fuori contesto | SPOSTATO nella sezione "BP: anatomia → Numeri misurati" |
| §5 Lagrangian Relaxation | `metodo_lagrangian.tex` §"Rilassamento lagrangiano: dualizzare i ponti" | RIMOSSA — idem |
| §6 BP MVP scaffold Step 4 | inedito | RIMASTO come sotto-sezione di "BP anatomia" (`\subsection{PhaseBDaySolver: wrapper OO sulla legacy}`) |
| §7 Phase A: modello matematico day count | inedito (formalizzazione mate del `DayCountModel`) | RIMASTO integralmente |
| §8 Phase B: 4 algoritmi decomp confronto (tabella+descrizioni+"Quando scegliere") | `metodo_spettrale.tex` §"Tre alternative alla decomposizione spettrale" | RIMOSSE descrizioni metodi + tabella pro/contro + sottosezione "Quando scegliere". RIMASTI: grafico wall-clock `fig_decomp_methods`, Proposizione+proof sul bound di Cheeger (matematica non ripetuta altrove) |
| §9 `cp_sat_scope=week`: il modello monolitico (spiegazione) | `workflow_di_ottimizzazione.tex` §"Scope del solver CP-SAT" | RIMOSSA spiegazione. RIMASTI: i numeri di esercizio (statsbox: variabili boolean, RAM, wall) — utili per dimensionare risorse |
| §10 Branch-and-Price: anatomia di una iterazione | unico (deep dive: master LP, 9 granularità, RF tree, dual stab, EWMA, parallel pricing, pricing-in-nodes) | RIMASTO integralmente, arricchito con sottosezione `PhaseBDaySolver` (dal vecchio §6) e statsbox "Numeri misurati" (dal vecchio §4) |
| §11 Metaeuristiche: matrice di scelta (tabella 7 metodi descrittiva) | `metodo_metaeuristiche.tex` (ogni metodo ha già sezione dedicata) + §"Quale scegliere" | RIMOSSA la tabella descrittiva. RIMASTI: figura tightness-band, formula tightness score, criterio decisionale empirico (contenuto unico) |

## 3. Conta righe

| File | Pre | Post | Δ |
|---|---|---|---|
| `manual/chapters/tecniche_di_ottimizzazione_avanzate.tex` (IT) | 670 | 528 | **−142** |
| `manual/chapters_en/tecniche_di_ottimizzazione_avanzate.tex` (EN) | 507 | 434 | **−73** |
| `manual/chapters_en/panoramica_pitantum.tex` (EN refresh) | 8 | 51 | **+43** |
| `manual/chapters_en/guida_ui.tex` (EN refresh) | 47 | 55 | **+8** |

PDF deltas:

| Manuale | Pages pre | Pages post |
|---|---|---|
| `manual.pdf` (IT) | 325 | **323** |
| `manual_en.pdf` (EN) | n/d | **141** |

(Pre IT misurato a regime sul prior commit `e8e9fe7`; post sulla build finale post-purge.)

## 4. Cosa resta nel capitolo avanzato (IT + EN)

Solo materiale veramente "avanzato", senza casa altrove:

1. **Phase A: il modello matematico del *day count*** — definizione formale `DayCountModel` (variabili intere `dc[t,c,s,d]`, vincoli di coverage/per-class/per-teacher, funzione obiettivo) + tabella 5 pragma di Phase A.
2. **Phase B: il bound di Cheeger sui ponti** — proposizione + proof (bound di Cheeger su `λ₂(L_sym)`), riferimento al cap. spettrale per il contesto.
3. **`cp_sat_scope=week`: numeri di esercizio** — statsbox dimensionamento (variabili, RAM, wall).
4. **Branch-and-Price: anatomia di una iterazione** — sezione corposa con sottosezioni: Master LP DW, Pricer CP-SAT a 9 granularità, `PhaseBDaySolver` wrapper OO, Ryan-Foster recursive tree (pseudocodice + teorema di terminazione), Box-step dual stabilization, Column management EWMA, Parallel pricing, Pricing-in-nodes, Numeri misurati (MEGA sintetico + reale).
5. **Il criterio della tightness** — formula `tightness = Σh_t / (|T|·6·6·ρ)`, banda di dispersione metaeuristica, soglie operative (0.4 / 0.6 / 0.8).

## 5. Capitoli EN aggiornati

| Capitolo EN | Stato pre | Stato post | Tipo |
|---|---|---|---|
| `tecniche_di_ottimizzazione_avanzate.tex` | traduzione completa (507 righe) | traduzione completa, purgata in parallelo al IT (434 righe) | full sync |
| `panoramica_pitantum.tex` | stub 8 righe (sola footer) | stub didascalico 51 righe con "For impatient readers" + "What the system does" + "Three layers" + footer | refresh summary |
| `guida_ui.tex` | stub 47 righe con sola sezione Ore | stub didascalico 55 righe con elenco delle 16 tab raggruppate in 5 famiglie + sezione Ore + footer | refresh summary |
| `workflow_di_ottimizzazione.tex` | 44 righe (già aggiornato a BP V1 / scope week / Phase A modes) | invariato — già in sync | nessuna azione |
| altri stub EN (`getting_started`, `formato_dati`, `workflow_tipici`, `terminologia_didattica`, `qualita_ui`) | non esistono nel manuale EN (frontespizio dichiara esplicitamente l'edizione ridotta) | n/a | nessuna azione richiesta |

## 6. Sample PNGs

Tutte in `docs/manual_audit_samples_purge/` (42 file totali, 100 dpi):

- `it_advanced_pre-*.png` — pagine 183–199 del manuale IT pre-purge (17 pagine).
- `it_advanced_post-*.png` — pagine 183–193 del manuale IT post-purge (11 pagine; **6 pagine in meno** sul solo capitolo avanzato).
- `en_advanced-*.png` — pagine 89–98 del manuale EN post-sync.
- `en_panoramica-018.png` — pagina EN dopo refresh del summary di `panoramica_pitantum`.
- `en_guida_ui-089.png` + `-090.png` — pagine EN dopo refresh del summary di `guida_ui`.

## 7. Backup

Tutti i file toccati hanno il loro `.bak_pre_*` accanto:

- `manual/chapters/tecniche_di_ottimizzazione_avanzate.tex.bak_pre_purge_dup`
- `manual/chapters_en/tecniche_di_ottimizzazione_avanzate.tex.bak_pre_purge_dup`
- `manual/chapters_en/panoramica_pitantum.tex.bak_pre_sync`
- `manual/chapters_en/guida_ui.tex.bak_pre_sync`

## 8. Compilazione

`docs/build_manual.sh` (lualatex × 2 + biber + makeindex × 2):

- `manual.pdf` 1 635 228 bytes, 323 pagine, build pulita.
- `manual_en.pdf` 700 706 bytes, 141 pagine, build pulita.

Nessun errore, nessun overfull warning aggiuntivo rispetto allo stato pre-purge.
