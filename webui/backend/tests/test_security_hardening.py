"""Regression tests for the security hardening landed in the
post-audit roadmap (Round 1).

Covers:
  * `profile` field whitelist on ImportPickleIn / MockGenIn (path traversal).
  * `/api/dataset/upload-pickle` disabled by default (RCE surface).
  * `/api/dashboard/import-db` rejects oversize / zip-bomb payloads.
  * `IntegrityError` -> 409 response no longer leaks raw SQL / column
    names in the `hint` field.
"""
from __future__ import annotations

import io
import os
import pickle
import zipfile

import pytest


# ---------- profile whitelist ----------

@pytest.mark.parametrize("bad_profile", [
    "../../etc/passwd",
    "..",
    "../../../engine",
    "/etc/passwd",
    "small/../../other",
    "small\x00",
    "small;rm -rf",
    "small$(whoami)",
    "a" * 64,
])
def test_import_profile_rejects_traversal(client, bad_profile):
    r = client.post("/api/dataset/import-profile",
                    json={"profile": bad_profile})
    # 422 = pydantic validation failure (the field validator we added).
    assert r.status_code == 422, (
        f"expected 422 for profile={bad_profile!r}, got "
        f"{r.status_code}: {r.text}"
    )


@pytest.mark.parametrize("ok_profile", [
    "small", "medium", "big", "huge", "superhuge", "mega",
])
def test_import_profile_accepts_whitelist(client, ok_profile):
    """Known profile names must still pass validation (404 expected
    because the test DB has no engine fixtures, but NOT 422)."""
    r = client.post("/api/dataset/import-profile",
                    json={"profile": ok_profile})
    # The request body validates; the route may then 404 because the
    # backing pkl/sqlite isn't present in CI.
    assert r.status_code != 422, (
        f"valid profile {ok_profile!r} rejected by validator: {r.text}"
    )


@pytest.mark.parametrize("bad_profile", [
    "../engine", "..", "small/.."
])
def test_mock_generation_rejects_traversal(client, bad_profile):
    r = client.post("/api/dataset/mock",
                    json={"profile": bad_profile})
    assert r.status_code == 422


# ---------- upload-pickle disabled by default ----------

def test_upload_pickle_disabled_by_default(client, monkeypatch):
    """RCE-prone endpoint must be 403 unless explicitly enabled."""
    monkeypatch.delenv("PITANTUM_ALLOW_PICKLE_UPLOAD", raising=False)
    monkeypatch.delenv("PITANTUM_API_KEY", raising=False)
    payload = pickle.dumps({"classes": [], "teachers": []})
    r = client.post(
        "/api/dataset/upload-pickle?kind=school",
        files={"file": ("school.pkl", payload, "application/octet-stream")},
    )
    assert r.status_code == 403
    assert "disabilitato" in r.text.lower() or "disable" in r.text.lower()


def test_upload_pickle_requires_api_key_even_when_flag_set(client, monkeypatch):
    """The flag alone isn't enough -- the endpoint must also be
    protected by the API-key middleware (i.e. PITANTUM_API_KEY set)."""
    monkeypatch.setenv("PITANTUM_ALLOW_PICKLE_UPLOAD", "1")
    monkeypatch.delenv("PITANTUM_API_KEY", raising=False)
    payload = pickle.dumps({"classes": [], "teachers": []})
    r = client.post(
        "/api/dataset/upload-pickle?kind=school",
        files={"file": ("school.pkl", payload, "application/octet-stream")},
    )
    assert r.status_code == 403


def test_upload_pickle_rejects_unknown_kind(client, monkeypatch):
    """Even when enabled, unknown `kind` values are 400 before any
    pickle.loads call -- defence in depth."""
    monkeypatch.setenv("PITANTUM_ALLOW_PICKLE_UPLOAD", "1")
    monkeypatch.setenv("PITANTUM_API_KEY", "test-key")
    payload = pickle.dumps({})
    r = client.post(
        "/api/dataset/upload-pickle?kind=evil",
        files={"file": ("x.pkl", payload, "application/octet-stream")},
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 400


# ---------- import-db size + zip-bomb limits ----------

def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    """Build an in-memory zip containing the given (name -> data) entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_import_db_rejects_empty(client):
    r = client.post(
        "/api/dashboard/import-db",
        files={"file": ("empty.zip", b"", "application/zip")},
    )
    assert r.status_code == 400


def test_import_db_rejects_zip_bomb(client):
    """A zip with a tiny compressed footprint that inflates >50x the
    uploaded size must be refused before _restore_zip touches the
    filesystem.
    """
    big_payload = b"\x00" * (5 * 1024 * 1024)  # 5 MiB of zeros (super-compressible)
    blob = _zip_bytes({"database.db": big_payload, "metadata.json": b"{}"})
    # Verify our fixture is actually a zip-bomb (inflation ratio > 50x):
    assert len(big_payload) / max(len(blob), 1) > 50, (
        "fixture not compressed enough to trigger the ratio check"
    )
    r = client.post(
        "/api/dashboard/import-db",
        files={"file": ("bomb.zip", blob, "application/zip")},
    )
    assert r.status_code == 413, (
        f"expected 413 zip-bomb rejection, got {r.status_code}: {r.text}"
    )


def test_import_db_rejects_oversize(client):
    """Anything beyond 256 MiB is refused outright. We don't actually
    upload that much: instead we monkeypatch the limit lower for the
    test so the assertion is fast.
    """
    from backend.routers import dashboard as dash
    original = dash._IMPORT_DB_MAX_BYTES
    try:
        dash._IMPORT_DB_MAX_BYTES = 1024  # 1 KiB cap for the test
        # 2 KiB random-ish bytes (won't compress under 1 KiB)
        big = os.urandom(2048)
        r = client.post(
            "/api/dashboard/import-db",
            files={"file": ("big.zip", big, "application/zip")},
        )
        assert r.status_code == 413
    finally:
        dash._IMPORT_DB_MAX_BYTES = original


def test_import_db_rejects_invalid_zip(client):
    """A blob that isn't a zip at all surfaces a clean 400, not a 500."""
    r = client.post(
        "/api/dashboard/import-db",
        files={"file": ("not-a-zip.zip", b"hello world",
                         "application/zip")},
    )
    assert r.status_code == 400


# ---------- IntegrityError 409 doesn't leak schema ----------

def test_integrity_error_hint_is_generic(client):
    """Trigger a unique-constraint violation and verify the response
    `hint` is the generic mapping, not the raw SQL error text.
    """
    payload = {"name": "DupSubjectSchemaLeak"}
    r1 = client.post("/api/subjects", json=payload)
    assert r1.status_code in (200, 201)
    r2 = client.post("/api/subjects", json=payload)
    if r2.status_code != 409:
        # Some routes pre-check and 400 instead of letting the DB raise.
        # That path is fine -- we only constrain the 409 branch.
        pytest.skip("router pre-checks duplicates (no IntegrityError path)")
    body = r2.json()
    hint = (body.get("hint") or "").lower()
    # The raw SQL/SQLAlchemy text contains these markers; the sanitised
    # hint must NOT.
    assert "unique constraint" not in hint
    assert "subjects.name" not in hint
    assert "sqlite" not in hint
    assert "psycopg" not in hint
