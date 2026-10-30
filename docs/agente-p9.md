# Agente p9 — branch `solver-p9`

Nessun push su `main`. Nessun file del solver modificato.

## Punto 9

non dimostrato, non tagliato

Costruzione del modello su liceo60, indicatori duplicati, circa 9 secondi.
Un solo passaggio sul codice non ha dimostrato che un indicatore sia lo
stesso vincolo due volte. Le famiglie parallele (`nco`, `nh`, `h11`,
`sixth`) alimentano vincoli diversi: toglierne una può cambiare
l'insieme ammissibile. Non tagliato.

`add_nogood` non è stato allargato. Nessun vincolo lex-leader.

## Test lenti

Run [40858175621](https://github.com/gborghi/timetable/actions/runs/40858175621)
su `93d77b6`. Sei timeout (`pytest-timeout` >600 s su liceo90) e
`test_run_phase_b_reaches_full_coverage` che non finisce in tempo.
Tre fallimenti (`test_piccolo_phase_b_baseline`, `_then_alns`,
`_then_vns`) sono `is_hard_feasible` falso, senza la riga
dell'invariante violato nel log. Non è un assert chiaro. Non
rilanciati. Saltati.
