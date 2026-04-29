# Spostamento manuale di una lezione (move-preview)

L'utente puo\` selezionare una lezione e vedere immediatamente, sulla
griglia, **dove puo\`** spostarla:

- **verde**: mossa accettata, SOFT migliora o invariato (delta &lt;= 0)
- **giallo**: mossa accettata ma peggiorerebbe il SOFT (delta &gt; 0,
  mostrato in cella + tooltip)
- **rosso**: mossa NON consentita, viola almeno un vincolo HARD
  (motivo nel tooltip)

Click su una cella verde o gialla applica la mossa. Click su una rossa
mostra un toast con il motivo. `Esc` o click su "X" annulla la
modalita\`.


## Backend

### `POST /api/schedule/move-preview`

Body (uno dei due):

```jsonc
{ "lesson_id": 18 }                       // identifica la lezione via DB
// oppure
{ "src": { "teacher_name": "Mario Rossi",
           "class_name": "1A_Scientifico",
           "subject": "Matematica",
           "day": 1, "hour": 8 } }
```

Opzionale `candidate_slots`:

```jsonc
{ "lesson_id": 18,
  "candidate_slots": [{"day":1,"hour":9}, {"day":2,"hour":10}, ...] }
```

Default = tutti i 36 slot della settimana (6 giorni x 6 ore).

Risposta:

```jsonc
{
  "src": { "teacher_name": "...", "class_name": "...",
           "subject": "...", "day": 1, "hour": 8 },
  "results": [
    { "day": 1, "hour": 8,  "status": "noop",
      "reason": "slot di origine", "delta_soft": 0 },
    { "day": 1, "hour": 9,  "status": "hard_violation",
      "reason": "docente Mario Rossi occupato in altro slot",
      "delta_soft": null },
    { "day": 1, "hour": 10, "status": "soft_worse",
      "reason": null, "delta_soft": 30 },
    { "day": 1, "hour": 11, "status": "ok",
      "reason": null, "delta_soft": -12 }
  ]
}
```

I `status` possibili:

| status | significato |
|---|---|
| `ok`             | mossa OK; `delta_soft` &lt;= 0 (miglioramento o invariato) |
| `soft_worse`     | mossa OK ma `delta_soft` &gt; 0 |
| `hard_violation` | mossa NON ammessa (motivo in `reason`) |
| `noop`           | slot di origine (no move) o stessa lezione gia\` presente |


### `PUT /api/schedule/move-lesson`

Validazione + applicazione della mossa. Stesso payload dell'old API.
Difensivo: il backend rivalida HARD anche se il client ha mandato uno
slot rosso (defense in depth).


## Performance

Per ogni candidato la simulazione fa:

1. check 3-state availability HARD su (docente, classe, aula) - O(1)
2. quick overlap check su (docente, classe) - O(N_lezioni)
3. `metaheuristics.is_hard_feasible` - O(N_lezioni) per controlli di
   integrita\` globali (no-buchi, dual mat/ita, motorie, max consecutive)
4. `compute_soft` per calcolare il delta - O(N_lezioni)

Su istanza `small` (305 lezioni) le 36 simulazioni terminano in <100 ms
end-to-end. Su istanza `superhuge` (~3000 lezioni) ci si aspetta
~1 secondo.


## Scelta degli slot per la simulazione

Default: tutti i 36 slot. La UI puo\` ottimizzare passando solo slot
"plausibili" (es. solo quelli non occupati per la classe), ma il
backend gestisce comunque tutto in modo idempotente.
