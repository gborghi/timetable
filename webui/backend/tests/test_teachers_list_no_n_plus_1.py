"""`GET /api/teachers` deve costare un numero di query COSTANTE.

`test_perf_budgets` misura il tempo di parete, ed e' una rete a maglie
larghe: su una macchina scarica un N+1 da 543 query resta sotto il
budget e passa inosservato, mentre sotto carico esplode a 20s. E'
esattamente com'e' andata -- l'N+1 e' stato scambiato per rumore di
contesa finche' non si e' contato.

Qui contiamo. La soglia non e' il numero esatto (cambia se si aggiunge
una collezione, ed e' giusto che si possa) ma il fatto che NON cresca
col numero di docenti: e' la differenza fra `selectinload` /
precaricamento in blocco e una query per riga.
"""
from __future__ import annotations

import pytest
from sqlalchemy import event


def _seed_teachers(client, n: int, start: int = 0) -> None:
    """`n` docenti con TUTTE le collezioni che `_to_out` rilegge, cosi'
    che un eager-loading mancante si veda nel conteggio.

    Le priorita' di giorno libero non passano dal payload del docente:
    hanno una sotto-rotta dedicata, e vanno scritte con quella.
    """
    client.post("/api/classrooms", json={"name": "Aula 1", "capacity": 30})
    for i in range(start, start + n):
        r = client.post("/api/teachers", json={
            "name": f"Docente {i:03d}",
            "subjects": ["Matematica"],
            "classroom_prefs": [
                {"classroom_name": "Aula 1", "state": "preferred",
                 "weight": 1.0}],
            "compresenza": "oraria",
            "compresenza_hours": [{"day": 2, "hour": 9}],
            "mandatory_free_days": [5],
        })
        assert r.status_code in (200, 201), r.text
        tid = r.json()["id"]
        p = client.patch(f"/api/teachers/{tid}/free-day-preferences",
                         json={"preferences": [{"day": 3, "priority": 1}]})
        assert p.status_code == 200, p.text
        assert p.json(), "la sotto-rotta ha accettato e non ha scritto nulla"


@pytest.fixture
def count_queries(app_with_temp_db):
    """Conta le SELECT emesse dentro il blocco `with`."""
    _app, SessionLocal_test = app_with_temp_db
    engine = SessionLocal_test.kw["bind"]

    class _Counter:
        def __init__(self):
            self.n = 0

        def __enter__(self):
            self.n = 0
            event.listen(engine, "before_cursor_execute", self._on)
            return self

        def __exit__(self, *exc):
            event.remove(engine, "before_cursor_execute", self._on)
            return False

        def _on(self, conn, cursor, statement, params, ctx, many):
            self.n += 1

    return _Counter()


def test_teacher_list_query_count_does_not_grow_with_rows(client,
                                                          count_queries):
    """Dieci docenti e quaranta docenti devono costare (quasi) uguale.

    Con l'N+1 il rapporto era ~4x; senza, la differenza e' zero.
    """
    _seed_teachers(client, 10)
    with count_queries as c:
        assert client.get("/api/teachers").status_code == 200
    small = c.n

    _seed_teachers(client, 30, start=10)  # 40 in totale
    with count_queries as c:
        r = client.get("/api/teachers")
    assert r.status_code == 200
    assert len(r.json()) == 40
    big = c.n

    assert big <= small + 2, (
        f"{small} query su 10 docenti, {big} su 40: il costo cresce con "
        f"le righe, c'e' un N+1. Guarda `list_teachers` in "
        f"routers/teachers.py -- ogni collezione letta da `_to_out` "
        f"vuole un `selectinload`, e le `classroom_prefs` (che non sono "
        f"una relationship) vogliono `_classroom_prefs_by_teacher`."
    )


def test_teacher_list_stays_under_a_flat_ceiling(client, count_queries):
    """Soglia assoluta, per accorgersi anche del caso in cui l'N+1
    venga reintrodotto direttamente su una base gia' grande."""
    _seed_teachers(client, 25)
    with count_queries as c:
        assert client.get("/api/teachers").status_code == 200
    assert c.n < 25, f"{c.n} query per 25 docenti: sospetto N+1."


def test_single_teacher_endpoint_still_returns_classroom_prefs(client):
    """Il precaricamento in blocco vale solo per la lista: la rotta
    singola passa da `_classroom_prefs_for_teacher` e non deve aver
    perso il campo."""
    _seed_teachers(client, 1)
    tid = client.get("/api/teachers").json()[0]["id"]
    body = client.get(f"/api/teachers/{tid}").json()
    assert [p["classroom_name"] for p in body["classroom_prefs"]] == ["Aula 1"]
    assert body["free_day_priorities"] == [{"day": 3, "priority": 1}]
