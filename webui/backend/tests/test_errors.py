"""Tests for the unified ErrorResponse shape and global exception
handlers."""
from __future__ import annotations


def test_404_has_canonical_shape(client):
    r = client.get("/api/teachers/999999")
    assert r.status_code == 404
    body = r.json()
    assert body.get("code") == "not_found"
    assert "detail" in body
    # Backward-compatible alias
    assert "error" in body
    # request_id may be None in test mode; presence of the key is enough
    assert "request_id" in body


def test_validation_error_lists_fields(client):
    r = client.post("/api/teachers", json={"max_hours": "not_a_number"})
    assert r.status_code == 422
    body = r.json()
    assert body.get("code") == "validation_error"
    errors = body.get("errors")
    assert isinstance(errors, list)
    assert any("max_hours" in (e.get("field") or "") for e in errors)


def test_duplicate_returns_canonical_error(client):
    """Subjects.name has a unique constraint. Inserting twice should
    surface a canonical ErrorResponse (the existing router pre-checks
    and raises HTTPException(400, 'subject already exists'); both
    400-pre-check and 409-IntegrityError paths must produce the
    canonical shape with `code`)."""
    payload = {"name": "DupSubject"}
    r1 = client.post("/api/subjects", json=payload)
    assert r1.status_code in (200, 201)
    r2 = client.post("/api/subjects", json=payload)
    assert r2.status_code in (400, 409), (
        f"expected 400 or 409 on duplicate, got {r2.status_code}: "
        f"{r2.text}"
    )
    body = r2.json()
    assert "code" in body
    assert body["code"] in ("validation_error", "integrity_error",
                            "http_error", "conflict")
    assert "detail" in body


def test_unknown_route_canonical(client):
    r = client.get("/api/this-does-not-exist")
    assert r.status_code == 404
    body = r.json()
    # Starlette's bare 404 still has the canonical shape thanks to the
    # HTTPException handler.
    assert "detail" in body


def test_request_id_header_present(client):
    r = client.get("/api/health")
    assert "X-Request-Id" in r.headers
    rid = r.headers["X-Request-Id"]
    assert len(rid) >= 8
