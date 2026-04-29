# experiments/ -- proof of concept e benchmark

Questa cartella contiene gli esperimenti che accompagnano
`proposals/analysis.md`. NIENTE qui dentro modifica i file
in `schedule/`. Tutti gli script sono "stand-alone" (vedi sezione
"Dipendenze" sotto).

## Cosa c'e\` qui

- `big_mock_school.py` -- generatore di un dataset "scuola grande"
  che riusa le funzioni pure-dati di `schedule/mock_classes2.py`
  (lo importa come modulo, non lo modifica). Cinque profili:
  `small` (~10 classi), `big` (~35 classi), `medium` (~40 classi),
  `huge` (~50 classi), `superhuge` (~80 classi, 16 sezioni x 5
  anni, 2000 studenti). Per default usa il **pool tight**:
  `sum(max_hours docenti) = fabbisogno x (1 + margin)` con
  `margin=0.15` (= +15%). Flag `--legacy-pool` per il generatore
  originale. Salva un pickle `school_<profile>.pkl`.

- `cpsat_v2_assignment.py` -- proof of concept del modello v2 per
  l'assegnazione prof->classe (cattedre). Un'unica risoluzione
  CP-SAT. **HARD: ogni (classe, materia) deve essere coperta da
  esattamente 1 docente; tutte le ore-classe vanno coperte**.
  **SOFT**: minimizza `unused_capacity` (capacita\` lato docenti
  non utilizzata) + `fewclasses` (spezzettamento) - `manycurricula`.
  Senza la "phase 4" quadratica del codice attuale (vedi
  `proposals/analysis.md` sez. 3 e 4.7). Lo script verifica
  esplicitamente la coverage con `assert` e stampa una riga
  `HARD coverage check: X/X (cl,subj) coperte ... -> OK`. Salva un
  pickle `profs_<profile>.pkl` nello stesso schema di
  `schedule/profs.pkl`.

- `cpsat_v2_timetable.py` -- proof of concept del modello v2 per
  l'orario settimanale, decomposto in due fasi:
  - **Phase A**: per ogni cattedra e giorno, quante ore (IntVar
    0..2). Bilanciamento + giorno libero + capacita\` per giorno.
  - **Phase B**: per ogni giorno, riempi le 6 ore con i Bool slot.
    No overlap, no holes, contiguita\`.
  Salva `solution_timetable_v2.pkl` (stesso schema di
  `solution_timetable.pkl`), compatibile con `stream2.py`.

- `minizinc_sketch.mzn` -- bozza MiniZinc della stessa Phase A,
  per chi vuole confrontare con backend Chuffed / OR-Tools (vedi
  `proposals/analysis.md` sez. 5.2).

- `exporters.py` -- modulo riusabile per esportare l'orario in
  Excel. Due funzioni:
  - `export_class_schedules_to_xlsx(...)` -> tab per classe,
    giorni in colonna, ore in riga, "Materia / Docente" in cella.
  - `export_teacher_schedules_to_xlsx(...)` -> tab per docente,
    nome+materie in testa, classe in cella.
  Lanciato come script (`python exporters.py`), produce gli xlsx
  per il caso HUGE in `output/huge/`. Uso programmatico:
  ```python
  from exporters import export_class_schedules_to_xlsx
  export_class_schedules_to_xlsx(
      "solution_timetable_superhuge.pkl",
      "school_superhuge.pkl",
      "profs_superhuge.pkl",
      "output/superhuge/orario_classi.xlsx",
  )
  ```
  Funziona con qualsiasi profilo: basta passare i path corretti.
  Dipendenza: `pip install openpyxl`.


## Dipendenze

```
pip install ortools faker
```

Per MiniZinc (opzionale): scarica MiniZinc IDE da
<https://www.minizinc.org/> e poi:

```
minizinc --solver Chuffed -p 8 minizinc_sketch.mzn data.dzn
```

Non e\` fornito un `data.dzn` perche\` la struttura dei dati e\`
specifica di Chuffed/OR-Tools backend; usalo come riferimento di
modellazione.


## Come eseguire la pipeline completa

Dalla cartella `experiments/`:

```bash
# 1) genera dataset "scuola grande"
python big_mock_school.py --profile big

# 2) risolvi assegnazione prof -> classe
python cpsat_v2_assignment.py --school school_big.pkl --time 30

# 3) costruisci l'orario settimanale (decomposto)
python cpsat_v2_timetable.py --profs profs_big.pkl \
    --time-a 30 --time-b 10
```

Output principale: `solution_timetable_v2.pkl`. Puoi visualizzarlo
con `streamlit run ../schedule/stream2.py` dopo aver:

1) copiato `experiments/profs_big.pkl` in `schedule/profs.pkl`,
2) copiato `experiments/solution_timetable_v2.pkl` in
   `schedule/solution_timetable.pkl`.

(Niente di tutto cio\` modifica il codice di `schedule/`, solo
i pkl di stato.)


> Benchmark estesi su HUGE / SUPERHUGE: vedi
> `proposals/benchmarks.md` per le tabelle complete e la diagnosi
> di scalabilita\`. Sotto solo un riassunto dei profili "small/big/
> medium".

## Risultati di benchmark (indicativi)

Eseguito sul portatile dell'autore (Windows 11, Python 3.13.13,
ortools 9.15, CPU consumer; 8 worker CP-SAT). Tempi in secondi e
status di terminazione:

### Assegnazione prof -> classe

| Profilo | classi | docenti | (cl,subj) | mock_classes2 v1 (4 fasi) | cpsat v2 (1 solve) |
| ------- | -----: | ------: | --------: | ------------------------: | -----------------: |
| small   |     10 |    ~25  |       ~120 | ~10s feasible, fase 4 ~30s| 2-3s feasible       |
| big     |     35 |    67   |        398 | fasi 1-3 ~60s totali, fase 4 NON converge in 60s | 10-30s feasible (qualita\` cresce con tempo) |
| medium  |     40 |    77   |        456 | analogo: fasi 1-3 ~80s, fase 4 NON converge | 30s feasible      |

In v2 con `--time 30`:
  - profilo `big`: deficit=167 (su 1206 max_hours teorici),
    fewclasses=310, manycurricula=208 (8 indirizzi totali).
  - profilo `medium`: deficit=188 (su 1386), fewclasses=373,
    manycurricula=254.

Con `--time 60` v2 OPTIMAL non si raggiunge ma la qualita\` e\`
visibilmente migliore (~5% in meno di deficit). Una run notturna
(time=600) avrebbe senso solo se vuoi spingere fino al provato
ottimo.

### Orario settimanale (timetable)

Tempi END-TO-END dell'intera pipeline v2 (Phase A + Phase B su 6
giorni):

| Profilo | classi | docenti | triples | Phase A (30s budget) | Phase B (somma 6 giorni) | Totale |
| ------- | -----: | ------: | ------: | -------------------: | -----------------------: | -----: |
| small   |     10 |    ~25  |     ~120 |               2-5s |                    <1s |  ~5s |
| big     |     35 |    67   |      398 |               30s |                    0.7s |  31s |
| medium  |     40 |    77   |      456 |               30s |                    0.9s |  31s |

Per confronto, `schedule/prog4.py` con `maxtimeinsec=160`,
`batch_size=100` e `num_search_workers=64` su un dataset di
taglia equivalente (35-40 classi):
  - solo i `check_feasibility` intermedi consumano 100+ secondi
    PER batch (10 chiamate * ~10s);
  - il solve finale rimane in stato UNKNOWN o FEASIBLE con
    `objective_bound` distante. Tempo wall-clock totale per
    esperienza dell'autore: 10+ minuti, e la qualita\` non e\`
    superiore alla v2 in 30s.

Note di lettura:
- "Phase B" su giorno medio termina in ~0.1-0.3 sec perche\` la sua
  taglia e\` ~70 triple x 6 ore = ~420 Bool, banale per CP-SAT.
- Quando Phase A produce una distribuzione "troppo tight" da
  imballare con `no_holes` strette, lo script applica un fallback
  che rilassa solo per quel giorno (vedi log "no-holes
  rilassato"). In produzione qui andrebbe un repair LNS: muovere
  un'ora ad altro giorno e riprovare.

Tutti i numeri sopra sono indicativi: il tuo hardware
(tipicamente 16-32 thread su workstation moderna) ridurra\`
ulteriormente i tempi.


## Limiti noti del proof of concept

Il PoC dimostra l'IDEA, non e\` produzione:

1. **Vincoli "consecutive Mat/Ginnastica"** non sono in v2 (sarebbero
   facili da aggiungere in Phase B come `AddBoolOr` su tutti i
   giorni).
2. **Penalita\` "buche del prof"** non e\` in v2 (in produzione: un
   passo finale che, dato l'orario completo, calcola il numero di
   buche per prof come metrica di accettazione, e applica swap LNS
   per ridurle).
3. **Hint cross-fase**: si potrebbe passare a Phase B il
   `dc_value` non solo come constraint ma come hint orario "centrale"
   (es. spalmare gli slot uniformemente). Aiuta la qualita\` ma
   non e\` necessario per la feasibility.
4. **Repair LNS automatico**: il fallback "rilassa no-holes" e\`
   un cerotto. La soluzione vera e\` un Large Neighborhood Search
   che fissa la maggior parte degli slot e ri-ottimizza una
   frazione (es. una giornata o un docente).
5. **"Equita\` cattedre"** in `cpsat_v2_assignment.py` e\` esclusa
   per progetto (vedi `proposals/analysis.md` sez. 4.7). Va
   reintegrata come local-search post-processing su una metrica
   semplice (varianza degli score).

Nessuno di questi limiti tocca le conclusioni della comparazione
con la v1 attuale: gli ordini di grandezza sono quelli mostrati
in tabella.
