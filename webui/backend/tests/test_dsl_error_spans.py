"""DSL tokenizer spans + /general/validate error_spans for the editor squiggle."""
from __future__ import annotations


def test_dsl_error_carries_pos_on_unknown_token():
    import general_dsl as G

    src = "forall l in lessons: l.teacher @ Borghi"
    try:
        G.parse(src)
        raise AssertionError("expected DSLError")
    except G.DSLError as e:
        assert e.pos is not None
        assert src[e.pos] == "@"
        assert e.end == e.pos + 1
        assert "Token sconosciuto" in str(e)


def test_validate_endpoint_returns_error_spans(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, _ = app_with_temp_db
    client = TestClient(app)
    expr = "forall l in lessons: l.teacher @ Borghi"
    r = client.post("/api/constraints/general/validate",
                    json={"expression": expr})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["errors"]
    assert body["error_spans"]
    span = body["error_spans"][0]
    assert expr[span["start"]] == "@"
    assert span["end"] == span["start"] + 1


def test_validate_ok_has_empty_spans(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, _ = app_with_temp_db
    client = TestClient(app)
    r = client.post("/api/constraints/general/validate", json={
        "expression": (
            "forall l in lessons where l.teacher == Borghi: l.hour != 6"
        ),
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["error_spans"] == []


def test_validate_syntax_error_without_unknown_token(app_with_temp_db):
    """A parse failure that is not an unknown token still returns ok=False."""
    from fastapi.testclient import TestClient

    app, _ = app_with_temp_db
    client = TestClient(app)
    r = client.post("/api/constraints/general/validate",
                    json={"expression": "forall l in lessons"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["errors"]