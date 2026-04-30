"""pytest fixtures for backend tests.

CRITICAL: tests run on an isolated SQLite file (or in-memory) and never
touch `webui/data/timetable.db` (the dev / running-server DB). Each
test gets a fresh DB, schema applied via `Base.metadata.create_all` +
the lightweight migrations.

The FastAPI TestClient is built per-test with `dependency_overrides[get_db]`
pointing at the isolated session, so the running uvicorn instance on
port 8000 is NEVER contacted.
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

# Make the backend package importable regardless of cwd.
HERE = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(PARENT_DIR)
if WEBUI_DIR not in sys.path:
    sys.path.insert(0, WEBUI_DIR)


@pytest.fixture
def temp_db_url(tmp_path):
    """A fresh sqlite:/// URL on a tmp_path file."""
    db_file = tmp_path / "timetable_test.db"
    return f"sqlite:///{db_file}"


@pytest.fixture
def app_with_temp_db(temp_db_url, monkeypatch):
    """Returns (app, SessionLocal_test) bound to a tmp DB.

    The fixture builds a fresh SQLAlchemy engine on `temp_db_url`,
    runs `Base.metadata.create_all`, applies the lightweight
    migrations, then overrides FastAPI's `get_db` dependency.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Build a private engine -- DO NOT touch the real one in db.py.
    test_engine = create_engine(
        temp_db_url,
        connect_args={"check_same_thread": False},
        future=True,
    )
    TestSession = sessionmaker(
        bind=test_engine, autoflush=False, autocommit=False, future=True
    )

    # Import models AFTER patching paths so Base.metadata is populated.
    from backend import db as backend_db  # noqa: E402
    from backend import models  # noqa: F401  -- registers tables

    # Create schema on the test engine.
    backend_db.Base.metadata.create_all(bind=test_engine)

    # Apply the lightweight migrations against the test engine. The
    # function in db.py is bound to the global engine; we re-implement
    # the same logic against `test_engine` so the test DB ends up in
    # the same shape as a real one. (We deliberately do not monkey-patch
    # the global `engine`; that would leak into the running server's
    # state if some import side-effect persists.)
    _apply_migrations_on(test_engine)

    # Now override the FastAPI app's `get_db` to return a TestSession.
    from backend.main import app

    def _override_get_db():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[backend_db.get_db] = _override_get_db
    try:
        yield app, TestSession
    finally:
        app.dependency_overrides.pop(backend_db.get_db, None)
        test_engine.dispose()


def _apply_migrations_on(engine):
    """Mirror of db._apply_lightweight_migrations against an arbitrary
    engine (so the test DB has all the post-migration columns)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)

    def has_column(table, column):
        if not insp.has_table(table):
            return False
        return any(c["name"] == column for c in insp.get_columns(table))

    with engine.begin() as conn:
        if insp.has_table("school_classes") and not has_column(
                "school_classes", "curriculum_id"):
            conn.execute(text(
                "ALTER TABLE school_classes ADD COLUMN curriculum_id INTEGER"
            ))
        for tbl in ("teachers", "students", "school_classes", "study_groups"):
            if insp.has_table(tbl) and not has_column(tbl, "nickname"):
                conn.execute(text(
                    f"ALTER TABLE {tbl} ADD COLUMN nickname VARCHAR(80)"
                ))
        if insp.has_table("teachers"):
            for col in ("last_name", "first_name"):
                if not has_column("teachers", col):
                    conn.execute(text(
                        f"ALTER TABLE teachers ADD COLUMN {col} VARCHAR(80)"
                    ))
        if insp.has_table("classroom_subject_preferences") and not has_column(
                "classroom_subject_preferences", "state"):
            conn.execute(text(
                "ALTER TABLE classroom_subject_preferences "
                "ADD COLUMN state VARCHAR(16) DEFAULT 'allowed'"
            ))
        for tbl in ("logical_unavailabilities",
                    "curriculum_logical_constraints"):
            if insp.has_table(tbl) and not has_column(tbl, "kind"):
                conn.execute(text(
                    f"ALTER TABLE {tbl} ADD COLUMN kind VARCHAR(16) "
                    f"DEFAULT 'hard'"
                ))
        if insp.has_table("lessons"):
            for stmt in (
                "CREATE INDEX IF NOT EXISTS ix_lessons_sol_day_hour "
                "ON lessons (solution_id, day, hour)",
                "CREATE INDEX IF NOT EXISTS ix_lessons_sol_teacher_day_hour "
                "ON lessons (solution_id, teacher_name, day, hour)",
                "CREATE INDEX IF NOT EXISTS ix_lessons_sol_class_day_hour "
                "ON lessons (solution_id, class_name, day, hour)",
                "CREATE INDEX IF NOT EXISTS ix_lessons_sol_room_day_hour "
                "ON lessons (solution_id, classroom_name, day, hour)",
            ):
                conn.execute(text(stmt))


@pytest.fixture
def client(app_with_temp_db):
    """A TestClient bound to the temp-db FastAPI app."""
    from fastapi.testclient import TestClient
    app, _ = app_with_temp_db
    return TestClient(app)
