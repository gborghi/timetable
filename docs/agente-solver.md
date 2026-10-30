# Agente solver — branch `solver-resta`

Chiusi solo i punti del solver che si collegavano senza inventare una
specifica. Nessun push su `main`. Nessun deploy manuale.

## Commit

| hash | cosa |
| --- | --- |
| `a502eb9` | Solver: il nucleo minimo usa i letterali `maxfree_`. |

Il commit di questo file arriva dopo, sulla stessa branch.

## Cosa è atterrato

Punto 7b. I letterali `maxfree_<docente>` c'erano già (`2b509ca`) ma
erano forzati con `ok == 1`, e il solve di produzione non chiedeva il
nucleo. Ora sono assumptions: `CpSolver.Solve` continua a imporli,
quindi l'insieme ammissibile non cambia. Se il modello vero è UNSAT,
Fase A, il solver monolitico e il percorso settimanale di produzione
chiedono `SufficientAssumptionsForInfeasibility` e, se il tetto è nel
nucleo, lo nominano nel messaggio di errore già esistente. Nessuna API
nuova. Con più worker il nucleo a volte torna vuoto: un secondo solve
a un worker, solo in quel caso e solo sull'UNSAT già dimostrato, lo
estrae.

Il percorso settimanale a pezzi non chiamava `MonolithicSolver.build()`,
quindi non compilava il pragma. Lo compila ora, come `build()` già
faceva. A preset spento (default) non aggiunge vincoli e gli ottimi non
cambiano. A preset acceso il modello settimanale rispetta la stessa
regola HARD che Fase A e `build()` già applicavano.

## Saltati, e perché

- **Punto 5, pesi UI.** Cercato una volta `kepler-verifica-fix-e-specifiche.md` sotto `/Users/g.borghi` e in Dropbox: non c'è. Senza la tabella non si collegano i pesi: cambierebbero gli ottimi.
- **Punto 8, resto.** Seed, `num_workers` e `dc_value` sono già in `93d77b6`. `add_nogood` vieta ancora un solo assegnamento. Lo snippet di Kepler sul vicinato non c'è: il vicinato non è stato allargato.
- **Punto 9, indicatori duplicati.** Non ho dimostrato che sia lo stesso vincolo due volte. Saltato: toglierlo senza quella prova può cambiare l'insieme ammissibile.
- **Punto 10.** `AddDecisionStrategy` non è stato sostituito con un vincolo lex-leader. In `working_hours_config.py` il fallback 6 giorni / ore 8–13 scatta solo se il DB non ha una config (tabella assente, vuota, o URL non SQLite). Non scavalca una config esplicita. Nessun bug da correggere.
- **Alternativa / cattedra IRC.** Non fatta. Manca la specifica didattica.
- **Test lenti rossi** su `93d77b6`, run [40858175621](https://github.com/gborghi/timetable/actions/runs/40858175621). Sei errori sono timeout (`pytest-timeout` >600s su liceo90, e `test_run_phase_b_reaches_full_coverage` non finisce in tempo). Tre fallimenti (`test_piccolo_phase_b_baseline`, `_then_alns`, `_then_vns`) sono `is_hard_feasible` falso, senza la riga dell'invariante violato nel log. Non è una regressione chiara sistemabile in due tentativi senza toccare gli ottimi. Saltati.
- **Split di `optimization.py` e `WeeklyCalendarView`.** Vietato in questo giro, e i punti 5, 8, 9 e 10 restano aperti.

## Test

Nella worktree, Python 3.12 di Homebrew, dipendenze nel venv
`.venv/` (non committato; il 3.12 di sistema non ha ortools):

```
PYTHONPATH=webui:engine:schedule:.venv/lib/python3.12/site-packages \
  /opt/homebrew/bin/python3.12 -m pytest webui/backend/tests -m 'not slow' --maxfail=5 -q
```

Esito: **1085 passed, 3 skipped, 61 deselected**, 415 s. I tre skip
sono preesistenti (modulo assente, psutil, percorso IntegrityError).

`webui/backend/tests/test_max_free_days.py`: 14 passed, compresi il
nucleo che nomina il docente e il messaggio di Fase A.

## Push

Solo `solver-resta`. Mai `main`.

https://github.com/gborghi/timetable/tree/solver-resta
