"""`GET /api/optimize/parameters/recommend` non deve andare in 500.

Prima contava `m.CoteachingRule`, che non esiste (il modello e'
`CoTeachingRule`): AttributeError -> 500 a ogni apertura di /optimize e
box dei parametri consigliati sparito senza messaggio (review Liceo #4).
"""


def test_recommend_parameters_ok_on_empty_db(client):
    r = client.get("/api/optimize/parameters/recommend")
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("time_a", "time_mono", "workers", "thoroughness"):
        assert key in body, body
