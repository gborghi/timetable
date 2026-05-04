# Stress constraint datasets

Datasets aggiuntivi di vincoli DSL pensati per stressare il
solver e per testare lo strumento di diagnosi dell'infeasibility
(`/api/constraints/feasibility-check` + `FeasibilityPanel`).

## Struttura

Una sottocartella per profilo (`small`, `medium`, `big`, `huge`,
`superhuge`, `mega`). Per ciascun profilo, tre file:

- `teacher_constraints.json` -- vincoli su docenti
  (indisponibilita' DNF, compresenza, max ore consecutive,
  preferenze giorno libero, ecc.)
- `classroom_constraints.json` -- vincoli su aule
  (manutenzione, multi-class condizionata, vicinanza)
- `relational_constraints.json` -- vincoli che attraversano
  scope (prof X mai a classe Y in 6a ora, materia Z in mattinata,
  gruppi cross-class)

Ogni file e' un JSON con la struttura:

```json
{
  "profile": "small",
  "category": "teacher",
  "constraints": [
    {
      "id": "small_t_001",
      "kind": "logical_teacher",
      "scope": "teacher",
      "owner_pattern": "Borghi G.",
      "level": "hard",
      "expression": "...",
      "intentionally_conflicting": false,
      "conflict_with": null,
      "description": "..."
    },
    ...
  ]
}
```

I record con `intentionally_conflicting: true` formano coppie
(o triple) che, applicati insieme, rendono il modello
infeasible. Il loader li carica in DB; il pannello di
feasibility-check deve identificarli come membri dello stesso
unsatisfiable core.

## Uso

```bash
cd experiments
# Carica nel DB della webapp (richiede backend attivo)
python load_stress_constraints.py --profile small
# Lancia diagnosi dal frontend (tab Vincoli) oppure via API:
curl -X POST http://127.0.0.1:8000/api/constraints/feasibility-check \
     -H "Content-Type: application/json" \
     -d '{"time_limit_s": 30}'
```

## Quanti vincoli

Per ogni profilo il dataset contiene un numero di vincoli che
scala con la dimensione della scuola, di cui circa il 10%
deliberatamente in conflitto con altri (coppie HARD vs ENFORCED
sullo stesso slot, oppure due regole su scope diversi che
contendono la stessa risorsa).

| Profilo    | teacher | classroom | relational | tot | conflict pairs |
|------------|--------:|----------:|-----------:|----:|---------------:|
| small      |       8 |         5 |          5 |  18 |              3 |
| medium     |      13 |         8 |          8 |  29 |              4 |
| big        |      30 |        17 |         17 |  64 |              4 |
| huge       |      66 |        33 |         31 | 130 |             10 |
| superhuge  |     132 |        66 |         62 | 260 |             20 |
| mega       |     286 |       132 |        126 | 544 |             44 |

I dataset di small e medium sono curati a mano (conflitti
significativi e descrizioni in italiano per ogni record). Quelli
di big/huge/superhuge/mega sono generati proceduralmente da
`generate_stress_constraints.py --all` (riproducibile via
`--seed`); il pattern dei conflitti e' lo stesso (HARD "mai SLOT"
vs ENFORCED "SLOT" sullo stesso owner).

## Note di tracciabilita'

I conflitti sono documentati con riferimento incrociato fra
`conflict_with` field: un constraint A con
`intentionally_conflicting: true, conflict_with: ["small_t_002"]`
significa che A contraddice il constraint con id
`small_t_002` quando entrambi sono attivi. Il
`feasibility-check` deve identificare A e small_t_002 come
membri dello stesso core.
