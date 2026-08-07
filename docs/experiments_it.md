# Esperimenti e Benchmark — due scuole da 90 classi

Questo documento raccoglie gli esperimenti su **due modelli di liceo da 90
classi, plesso unico** (stessi sei indirizzi, 187 docenti, settimana di 6
giorni lun–sab con base di 5 ore 8:00–13:00 estendibile a una 6ª ora fino alle
14:00). Per ciascuno riporta cosa era **previsto** e cosa è stato **ottenuto**,
con le statistiche misurate. Tutte le soluzioni sono hard-feasible salvo dove
indicato.

> Realizzato con l'intelligenza artificiale (Claude di Anthropic), come il
> resto di piTantum.

## Modello A — `liceo90` (aula della classe)

Il modello italiano tradizionale: **la classe ha un'aula-casa, i docenti si
spostano.** Obiettivo: dimostrare che con la **turnazione del biennio** (ogni
classe del primo biennio è libera un giorno/settimana, il giorno lo sceglie il
solver, vincolo HARD) più il **gym-sharing** (una classe in palestra libera la
sua aula) e il **sostegno in compresenza** (il docente di sostegno resta
nell'aula della classe), una scuola può usare **meno aule che classi**.

| metrica | previsto | ottenuto |
|---|---|---|
| aule ordinarie per 90 classi | < 90 possibile con la turnazione | **84 standard + 3 palestre = 87 < 90** |
| lezioni non piazzate | 0 | **0** |
| classi del biennio con giorno libero | 36/36 | **36/36** |
| 1ª scelta giorno libero soddisfatta | ≥ 80% (target) | **98–99%** |
| PE contemporanee (3 palestre × 2) | ≤ 6/slot | **6/slot** (spread forzato) |

### Soft `room_pool` — minimizzare le aule per classe
Aggiungendo un termine soft che minimizza le aule DISTINTE occupate da ciascuna
classe nella settimana (una classe deve cambiare aula il meno possibile):

| | media aule/classe | max | coppie (classe,aula) | fuori |
|---|---|---|---|---|
| senza pool | **25.31** | 30 | 2278 | 0 |
| con pool | **~2.4–2.6** | 9 | 233 | 0 |

Riduzione ~10×: ogni classe si stabilizza sulla sua aula ordinaria + la palestra.

## Esperimenti di decomposizione (step aule, orario fisso)

Le aule sono una risorsa a livello di **settimana**. Abbiamo confrontato
l'assegnazione globale con la decomposizione dello step-aule per giorno
(temporale), sullo stesso piazzamento:

| approccio | media aule/classe | max | coppie | fuori | tempo |
|---|---|---|---|---|---|
| **Globale** (tutto insieme) | **2.59** | 9 | 233 | 0 | 122 s |
| Temporale, naive (per-giorno indipendente) | 6.83 | 10 | 615 | 0 | 182 s |
| Temporale, consenso (per-giorno + aula-casa) | 5.26 | 13 | 473 | 0 | 183 s |

**Risultato.** Decomporre le aule per giorno **gonfia il pool di 2.6×** (2.59 →
6.83): ogni giorno sceglie le aule in isolamento, perdendo l'accoppiamento
inter-giorno. Il consenso lo recupera solo in parte. Lo step-aule globale è
economico e quasi-ottimo, quindi resta globale.

## Joint monolitico settimanale (aule + orario insieme, niente decomposizione)

Inserendo le variabili-aula in un unico modello settimanale monolitico per 90
classi:

- **2.803.896 variabili-aula**, ~10 GB di RAM.
- Dopo ~16 min: **`best: inf`** — nessuna soluzione ammissibile trovata.

**Risultato.** Conferma l'avvertimento nel codice ("va in UNKNOWN intorno alle
90 classi"): il modello completamente joint monolitico non scala a 90 classi.
La decomposizione temporale/spettrale + uno step-aule globale separato risolve
la stessa scuola in ~2–3 min a 0 fuori.

## Decomposizione per curriculum — da rotta a feasible

Decomporre per indirizzo (curriculum) inizialmente **non produceva soluzione**:
i solve per-giorno fallivano istantaneamente (0.4 s) su 3–5 giorni su 6. Cause
radice e correzioni (tutte committate):

1. **Phase A ignorava la capienza per-slot delle aule speciali** → allocava
   troppe ore di una materia con `required_kind` (PE) a un giorno che le
   palestre non potevano ospitare → per-giorno INFEASIBLE. Fix: un cap HARD
   per-(kind, giorno) in Phase A (constraint-driven, nessun nome cablato).
2. **La turnazione biennio non veniva passata** alla Phase A di
   curriculum/metis → tutte le 90 classi presenti ogni giorno → aule piene.
   Fix: threading di `class_free_days`.
3. **Nessun recovery** quando un giorno falliva. Fix: retry limitato che
   abbassa il tetto di carico del giorno fallito, forzando la ridistribuzione.

| | prima | dopo |
|---|---|---|
| giorni risolti | 3/6 → 5/6 → **6/6** | **6/6** |
| copertura | nessuna | **2763 lezioni, piena** |
| biennio libero | — | **36/36** |
| hard-feasible | no | **sì** |

## Modello B — `liceo90doc` (aula del docente)

Il paradigma inverso: **il docente resta in (poche aule della) sua AREA
disciplinare, gli studenti si spostano.** Le aule sono partizionate in 7 pool
d'area (via `required_kind`); un termine soft `teacher_room_pool` minimizza le
aule distinte per docente; le classi sono `room_policy = libera`; il sostegno è
compresenza.

### Previsto vs ottenuto (numero di aule)

| | valore |
|---|---|
| floor teorico (ore-area / 30 slot base) | **85** aule d'area |
| floor teorico (/ 36 slot) | 70 |
| **ottenuto a copertura PIENA** | **106** aule d'area + 2 lab + 3 palestre |

### Tentativi di scendere sotto 106 — tutti perdono copertura

| approccio | aule d'area | copertura |
|---|---|---|
| Separato (piazza → ri-assegna nei pool d'area) | **106** | **100%** ✅ |
| Joint cap-hard (spettrale) | 92 | 87% ❌ |
| Joint cap-hard (monolitico per-giorno) | 96 | 88% ❌ |
| Joint + **bilanciamento soft**, cap larghi | (156) | 88% ❌ |

**Risultato.** Ri-solvere l'orario sotto i vincoli d'area fa perdere ~12% di
copertura in **ogni** variante — il collo di bottiglia è la copertura, non lo
spreading (il termine di bilanciamento ha spostato il picco appena: 106 → 105).
La causa è il fortissimo **accoppiamento tra aree**: **162 docenti su 187
insegnano in più aree**, più la turnazione biennio e le materie appaiate,
lasciando troppo poca libertà per spalmare *e* coprire tutto. Quindi **106 aule
d'area è il floor pratico a copertura piena** — il prezzo strutturale del "ogni
docente sempre nella sua area". Il floor teorico 85 è irraggiungibile.

### Metriche a 106 (modello finale)

| metrica | ottenuto |
|---|---|
| copertura | **piena (2763 lezioni)**, 0 fuori, hard-feasible |
| **aule per DOCENTE** | **media 1.95, max 9** — 89/187 in una sola aula, 60 in due |
| docenti assegnati fuori dalla loro area | **0** |
| aule per CLASSE | media **13.37** (gli studenti si spostano di continuo) |
| palestre | **3** bastano (PE ≤ 6/slot) |

## Sintesi — previsto vs ottenuto

| affermazione | previsto | ottenuto |
|---|---|---|
| aule < classi (modello classe) | sì, con turnazione | **87 aule / 90 classi, 0 fuori** |
| minimizzazione aule per-classe | forte | **25.3 → ~2.5 aule/classe** |
| aule decomponibili per giorno | peggio (coupling settimanale) | **2.59 → 6.83 (2.6× peggio)** |
| joint monolitico @ 90 classi | intrattabile | **2.8 M variabili, best: inf** |
| decomposizione curriculum | sistemabile | **6/6 giorni, copertura piena** |
| floor aule modello docente | 85 teorico | **106 a copertura piena** |
| docente fermo | poche aule | **1.95 aule/docente, 0 fuori-area** |

Entrambi i modelli risolti sono caricabili nell'app (*Importa modelli risolti*
→ `liceo90`, `liceo90doc`).
