# Verifica dei fix e specifiche

Specifica per i punti ancora aperti. Non modifica il motore.
I numeri sono solo quelli già nel codice o in `93d77b6`.
Base: `origin/main` (`55558a9`).

## Punto 5 — pesi UI nell'obiettivo

I pesi della UI entrano nell'obiettivo. I default sono già in
`webui/backend/models.py` (gli stessi valori sono in
`webui/backend/schemas.py`). Non si inventa un'altra tabella.

| campo | dove | default |
| --- | --- | --- |
| `pref_no_buchi_weight` | `Teacher` | 10 |
| `pref_no_five_weight` | `Teacher` | 30 |
| `pref_no_one_weight` | `Teacher` | 80 |
| `distribute_days_weight` | `Subject` | 0 |

`distribute_days_weight` a 0 significa spento: col default non aggiunge
nulla all'obiettivo.

Scala unica, già nel codice. Niente livelli lessicografici.

- buco = 10: `engine/metaheuristics.py`, `OBJECTIVE_WEIGHTS["buchi"]`.
  Gli stessi 10, 30 e 80 di buchi, five e one sono già in
  `OBJECTIVE_WEIGHTS`.
- `SCALE = 100`: `engine/cp_sat_constraint_model.py`.

I quattro pesi sono preset: default già selezionato, modificabile e
rimovibile. Non cablati nel motore.

## Punto 8 — seed, worker, vicinato

Già in `93d77b6` (`93d77b6e4cab710a602e05f708d9abdb78a8e94f`):

- seed: `engine/solver_config.py`, `configure_solver` imposta
  `random_seed`, anche sul percorso settimanale;
- `num_workers`: in quel commit `num_search_workers` è diventato
  `num_workers`;
- `dc_value`: `run_lns` lo ricava dalla soluzione migliore all'ingresso.

`add_nogood` (`engine/dsl_cp_gate.py`) resta il divieto di un solo
assegnamento: un `AddBoolOr` sulle variabili di slot, soddisfatto solo
se almeno una cambia. Non allargare il vicinato.

## Punto 9 — indicatori

Non tagliare indicatori senza prova che siano lo stesso vincolo due
volte. Senza quella prova il taglio può cambiare l'insieme ammissibile.

## Punto 10 — decisione di branching

Non sostituire `AddDecisionStrategy` con un vincolo lex-leader.

In Fase A (`engine/cpsat_v2_timetable.py`) la rottura di simmetria è
solo `AddDecisionStrategy` (`CHOOSE_FIRST`, `SELECT_MIN_VALUE`) sulle
variabili `day_count` ordinate per nome. Un vincolo lex-leader
cambierebbe le soluzioni ammesse.

Il fallback 6 giorni / ore 8–13 di `engine/working_hours_config.py`
(`_LEGACY_DAYS`, `_LEGACY_HOURS`) scatta solo se il DB non ha una
config. Non scavalca una config esplicita. Non è un bug da correggere
qui.

## Alternativa

Preset, in simultanea con IRC. Mai scritto nel codice del motore.

- Default già selezionato: aula di kind `alternativa`.
- Scelta, modificabile e rimovibile: aula fissa nominata, oppure altre
  aule libere.

Il default è un preset per chi non è esperto, non una costante del
solver. Oggi il commento di `Classroom.kind` in `models.py` elenca
`standard`, i laboratori, `palestra`, `biblioteca`, `aula_speciale`:
`alternativa` non è già un kind cablato.
