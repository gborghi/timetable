# Operazioni collettive (bulk)

Ogni pagina di lista (Docenti, Classi, Aule, ...) supporta la selezione
multipla con `Ctrl+click` (singoli) o `Shift+click` (intervallo) e
l'applicazione di un vincolo a tutti i selezionati in una sola azione.

## Endpoint

    POST /api/bulk/{entity}/dry-run
        body: { entity_ids: [...], action: "...", payload: {...},
                on_conflict: "dry_run" }
        ->    { action, n_targets,
                candidates: [{id, name, reason: "ok"}],
                conflicts:  [{id, name, reason: "<motivo>"}] }

    POST /api/bulk/{entity}/apply
        body: { entity_ids: [...], action: "...", payload: {...},
                on_conflict: "override" | "skip" }
        ->    { ok, action, n_applied, n_overridden, n_skipped,
                messages, errors }

`{entity}` puo' essere uno di: `teachers`, `classes`, `classrooms`.

## Flusso UI

1. Selezioni N righe nella lista (Ctrl/Shift click).
2. Clicchi "Applica vincolo collettivo" -> si apre un pannello con la
   scelta dell'azione (vincolo logico, set field, slot di
   indisponibilita').
3. La UI invoca `dry-run` per scoprire chi avrebbe gia' un vincolo in
   conflitto.
4. Se ci sono conflitti, viene mostrata la lista delle entita' in
   conflitto con il motivo. Tu scegli:
   - **override**: applica comunque, sovrascrivendo il vincolo
     personale; oppure
   - **skip**: salta solo le entita' in conflitto, applica alle altre;
     oppure
   - **annulla**: niente viene salvato.
5. Confermando, la UI invoca `apply` con `on_conflict=override|skip` e
   mostra il riepilogo.

## Azioni supportate

### add_logical
Aggiunge una regola di indisponibilita' logica (vedi
[logical_constraints.md](logical_constraints.md)) a tutte le entita'
selezionate.

```json
{
  "action": "add_logical",
  "payload": {
    "expression": "lun8 AND lun9",
    "is_hard": true,
    "soft_penalty": 100
  }
}
```

Conflitto rilevato: una entita' ha gia' un vincolo logico con la stessa
expression letterale. (Vincoli con espressioni diverse non sono
considerati conflitti, anche se semanticamente equivalenti.)

### set_field
Imposta un campo singolo (boolean, numerico, stringa) sulle entita'.
Funziona per qualunque colonna del modello SQLAlchemy della tabella
target.

```json
{
  "action": "set_field",
  "payload": {
    "field": "max_consecutive",
    "value": 4
  }
}
```

Conflitto rilevato: il campo e' gia' valorizzato a un valore non vuoto
diverso. Override sovrascrive, skip lascia inalterato.

Esempi tipici:
- Docenti: `{ field: "free_day", value: "Saturday" }`
- Docenti: `{ field: "max_hours", value: 18 }`
- Classi:  `{ field: "hard_no_holes", value: true }`

### add_unavailability
Aggiunge una cella di disponibilita' HARD/SOFT a un certo `(day, hour)`
per tutte le entita' selezionate.

```json
{
  "action": "add_unavailability",
  "payload": {
    "day": 6,
    "hour": 12,
    "state": "hard",
    "soft_penalty": 100,
    "reason": "Riunione collegio docenti"
  }
}
```

Conflitto rilevato: la cella `(day, hour)` esiste gia' con stato
diverso (es. e' SOFT e tu chiedi HARD). Override aggiorna lo stato.

## Convenzioni

- L'ordine dei `entity_ids` non e' significativo.
- Le operazioni sono atomiche per chiamata: o tutte le entita'
  candidato-non-conflitto vengono applicate, oppure (se uno dei singoli
  apply genera errore) il batch si ferma e il commit avviene comunque
  per tutto cio' che e' andato a buon fine fino a quel punto, con il
  resto elencato in `errors`.
- I vincoli applicati via bulk sono identici a quelli creati uno per
  uno tramite la UI normale: visibili nel pannello "Vincoli logici"
  della singola entita', modificabili e rimovibili individualmente.
