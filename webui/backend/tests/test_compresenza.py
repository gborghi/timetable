"""Compresenza: la proprieta' per-docente e il suo effetto sulle aule.

Due livelli, come per `test_room_policy.py`:

  - il round-trip API su `Teacher.compresenza` + `compresenza_hours`,
    che e' l'unico modo per accorgersi se la feature resta irraggiungibile
    dall'utente (il modello puo' essere perfetto e la UI non avere campo);
  - `compresenza_map` in engine/classroom_assignment.py, dove la
    compresenza diventa davvero "una sola aula invece di due".

Il punto che vale e' che la regola NON e' cablata su `is_support`: una
compresenza e' due docenti nella stessa aula qualunque ne sia la natura
(sostegno, potenziamento, codocenza, madrelingua, ITP), e per contro
"stessa classe alla stessa ora" NON implica "stessa aula" -- Religione /
Attivita' alternativa spezzano davvero la classe in due locali. Serve
percio' una dichiarazione esplicita per docente, ed e' quella che questi
test verificano arrivare fino al solver.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------

def test_compresenza_defaults_to_mai(client):
    r = client.post("/api/teachers", json={"name": "Rossi Anna"})
    assert r.status_code == 200, r.text
    assert r.json()["compresenza"] == "mai"
    assert r.json()["compresenza_hours"] == []


def test_compresenza_round_trip_with_hours(client):
    created = client.post("/api/teachers", json={"name": "Bianchi Luca"}).json()
    tid = created["id"]
    payload = {
        "name": "Bianchi Luca",
        "compresenza": "oraria",
        "compresenza_hours": [{"day": 2, "hour": 9},
                              {"day": 1, "hour": 8}],
    }
    r = client.put(f"/api/teachers/{tid}", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["compresenza"] == "oraria"
    # Il router ordina per (giorno, ora): la UI disegna una griglia e
    # un ordine instabile la farebbe sfarfallare ad ogni salvataggio.
    assert body["compresenza_hours"] == [{"day": 1, "hour": 8},
                                         {"day": 2, "hour": 9}]
    assert client.get(f"/api/teachers/{tid}").json()["compresenza_hours"] == [
        {"day": 1, "hour": 8}, {"day": 2, "hour": 9}]


def test_compresenza_hours_survive_mode_change(client):
    """Passare a 'sempre' non deve cancellare la griglia gia' compilata."""
    tid = client.post("/api/teachers", json={"name": "Verdi Ida"}).json()["id"]
    client.put(f"/api/teachers/{tid}", json={
        "name": "Verdi Ida", "compresenza": "oraria",
        "compresenza_hours": [{"day": 3, "hour": 10}]})
    r = client.put(f"/api/teachers/{tid}", json={
        "name": "Verdi Ida", "compresenza": "sempre",
        "compresenza_hours": [{"day": 3, "hour": 10}]})
    assert r.json()["compresenza"] == "sempre"
    assert r.json()["compresenza_hours"] == [{"day": 3, "hour": 10}]


def test_compresenza_rejects_unknown_mode(client):
    r = client.post("/api/teachers", json={"name": "Neri Ugo",
                                       "compresenza": "qualche_volta"})
    assert r.status_code == 422


def test_compresenza_hours_deduplicated(client):
    """L'unicita' e' (docente, giorno, ora): un doppione nel payload
    non deve far esplodere l'insert con un IntegrityError."""
    tid = client.post("/api/teachers", json={"name": "Gialli Ivo"}).json()["id"]
    r = client.put(f"/api/teachers/{tid}", json={
        "name": "Gialli Ivo", "compresenza": "oraria",
        "compresenza_hours": [{"day": 1, "hour": 8},
                              {"day": 1, "hour": 8}]})
    assert r.status_code == 200, r.text
    assert r.json()["compresenza_hours"] == [{"day": 1, "hour": 8}]


# ----------------------------------------------------------------------
# engine: compresenza_map
# ----------------------------------------------------------------------

def _L(cl, subj, d, h, *, shares=False):
    return {"class": cl, "subject": subj, "day": d, "hour": h,
            "n_students": 25, "required_kind": "", "home_room": "",
            "forbidden_rooms": (), "shares_room": shares}


def test_rider_attaches_to_host_in_same_cell():
    from classroom_assignment import compresenza_map

    host = _L("1A", "Matematica", 1, 8)
    rider = _L("1A", "Sostegno", 1, 8, shares=True)
    riders = compresenza_map([host, rider])
    assert list(riders.values()) == [("1A", "Matematica", 1, 8)]
    assert ("1A", "Sostegno", 1, 8) in riders


def test_rider_alone_in_cell_is_promoted_to_host():
    """Senza ospite la lezione un'aula la deve chiedere, altrimenti
    resterebbe senza."""
    from classroom_assignment import compresenza_map

    riders = compresenza_map([_L("1A", "Sostegno", 1, 8, shares=True)])
    assert riders == {}


def test_non_rider_lessons_keep_their_own_room():
    """Il caso Religione / Attivita' alternativa: stessa classe, stessa
    ora, ma due aule diverse. Senza `shares_room` niente si fonde."""
    from classroom_assignment import compresenza_map

    a = _L("1A", "Religione", 1, 8)
    b = _L("1A", "Attivita alternativa", 1, 8)
    assert compresenza_map([a, b]) == {}


def test_rider_does_not_attach_across_cells():
    from classroom_assignment import compresenza_map

    host = _L("1A", "Matematica", 1, 8)
    rider = _L("1A", "Sostegno", 2, 9, shares=True)
    assert compresenza_map([host, rider]) == {}
