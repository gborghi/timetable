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


@pytest.fixture(scope="session", autouse=True)
def _ensure_live_db_schema():
    """Ensure the live (dev) DB at webui/data/timetable.db has the
    canonical schema before any test runs.

    Why: tests in test_perf_budgets.py, test_leaks.py and
    test_telemetry.py read/write the live DB directly (perf budgets
    are meant to reflect realistic data volumes, telemetry helpers
    use module-level SessionLocal). The FastAPI app calls init_db()
    in its lifespan context manager, but bare `TestClient(app)` (no
    `with`) does NOT fire lifespan -- so without this fixture, the
    live DB stays empty and those tests crash with
    "no such table: <X>".

    init_db() is idempotent (Base.metadata.create_all + light
    additive migrations), so running it once per session is safe
    even when the dev DB is already populated by a running uvicorn.
    """
    try:
        from backend.db import init_db
        init_db()
    except Exception:
        # If we can't init the live DB (locked by another process,
        # missing path, etc), let individual tests surface a
        # specific error rather than aborting the whole session.
        pass
    yield


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


@pytest.fixture
def temp_global_session(temp_db_url, monkeypatch):
    """Come `app_with_temp_db`, ma per il `SessionLocal` GLOBALE.

    `app_with_temp_db` isola solo la dependency `get_db`: basta per
    tutto cio' che passa dalle rotte. Non basta per l'orchestrazione dei
    run, che gira in un thread di background e apre le sessioni da
    `optimization.SessionLocal` / `run_manager.SessionLocal`, cioe' dal
    `SessionLocal` importato a modulo -- quello legato al DB REALE.

    Un test che chiami `run_phase_b` senza questa fixture non e' lento e
    basta: importa la scuola di prova nel DB di sviluppo con
    `replace=True` e ci cancella sopra i dati veri. E' successo.

    Ritorna la sessionmaker, cosi' il test puo' popolare il DB
    temporaneo con le stesse sessioni che vedra' il run.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend import db as backend_db
    from backend import models  # noqa: F401  -- registers tables
    from backend import optimization, run_manager

    test_engine = create_engine(
        temp_db_url,
        connect_args={"check_same_thread": False},
        future=True,
    )
    TestSession = sessionmaker(
        bind=test_engine, autoflush=False, autocommit=False, future=True
    )
    backend_db.Base.metadata.create_all(bind=test_engine)
    _apply_migrations_on(test_engine)

    # Tutti e tre i binding: `from .db import SessionLocal` ne ha fatto
    # una copia per modulo, e ripatchare solo `db` non basterebbe.
    monkeypatch.setattr(backend_db, "SessionLocal", TestSession)
    monkeypatch.setattr(optimization, "SessionLocal", TestSession)
    monkeypatch.setattr(run_manager, "SessionLocal", TestSession)
    try:
        yield TestSession
    finally:
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
        if insp.has_table("teachers") and not has_column(
                "teachers", "graduatoria_score"):
            conn.execute(text(
                "ALTER TABLE teachers ADD COLUMN graduatoria_score FLOAT"
            ))
        timestamped = ("subjects", "teachers", "school_classes",
                       "classrooms", "curricula", "students",
                       "study_groups")
        for tbl in timestamped:
            if not insp.has_table(tbl):
                continue
            for col in ("created_at", "updated_at"):
                if not has_column(tbl, col):
                    conn.execute(text(
                        f"ALTER TABLE {tbl} ADD COLUMN {col} DATETIME"
                    ))
                    conn.execute(text(
                        f"UPDATE {tbl} SET {col} = CURRENT_TIMESTAMP "
                        f"WHERE {col} IS NULL"
                    ))
            # tenant_id (Section 2.5 P3)
            if not has_column(tbl, "tenant_id"):
                conn.execute(text(
                    f"ALTER TABLE {tbl} ADD COLUMN tenant_id INTEGER "
                    f"NOT NULL DEFAULT 1"
                ))
                conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS "
                    f"ix_{tbl}_tenant_id ON {tbl} (tenant_id)"
                ))

        # Task C1 columns on assignments. The CoteachGroup table is
        # created by Base.metadata.create_all above; we only need
        # the new columns on `assignments`.
        if insp.has_table("assignments"):
            for col, ddl in (
                ("coteach_group_id",
                 "ALTER TABLE assignments ADD COLUMN "
                 "coteach_group_id INTEGER"),
                ("is_support",
                 "ALTER TABLE assignments ADD COLUMN "
                 "is_support INTEGER NOT NULL DEFAULT 0"),
                ("is_potenziamento",
                 "ALTER TABLE assignments ADD COLUMN "
                 "is_potenziamento INTEGER NOT NULL DEFAULT 0"),
                ("parallel_group_id",
                 "ALTER TABLE assignments ADD COLUMN "
                 "parallel_group_id INTEGER"),
                ("group_id",
                 "ALTER TABLE assignments ADD COLUMN "
                 "group_id INTEGER"),
            ):
                if not has_column("assignments", col):
                    conn.execute(text(ddl))
        if insp.has_table("coteach_groups"):
            if not has_column("coteach_groups", "group_id"):
                conn.execute(text(
                    "ALTER TABLE coteach_groups ADD COLUMN "
                    "group_id INTEGER"
                ))
        if insp.has_table("lessons"):
            if not has_column("lessons", "group_name"):
                conn.execute(text(
                    "ALTER TABLE lessons ADD COLUMN "
                    "group_name VARCHAR(120)"
                ))
        # PLESSI: classrooms.plesso_id (Plesso/CommutingRule/
        # EntityPolicy tables are created by Base.metadata.create_all
        # so they don't need an explicit migration here).
        if insp.has_table("classrooms") and not has_column(
                "classrooms", "plesso_id"):
            conn.execute(text(
                "ALTER TABLE classrooms ADD COLUMN plesso_id INTEGER"
            ))

        # Tab Ore default seed (mirrors db._apply_lightweight_migrations).
        if insp.has_table("working_days") and insp.has_table(
                "working_hour_slots"):
            existing = conn.execute(text(
                "SELECT COUNT(*) FROM working_days WHERE tenant_id = 1"
            )).scalar()
            if not existing:
                _DEFS = [
                    ("MON", "Lunedi",    0, 1),
                    ("TUE", "Martedi",   1, 2),
                    ("WED", "Mercoledi", 2, 3),
                    ("THU", "Giovedi",   3, 4),
                    ("FRI", "Venerdi",   4, 5),
                    ("SAT", "Sabato",    5, 6),
                ]
                for code, label, pos, legacy in _DEFS:
                    conn.execute(text(
                        "INSERT INTO working_days "
                        "(tenant_id, code, label, position, "
                        " legacy_day_number, is_active) "
                        "VALUES (1, :c, :l, :p, :ln, 1)"
                    ), {"c": code, "l": label, "p": pos, "ln": legacy})
                    day_id = conn.execute(text(
                        "SELECT id FROM working_days "
                        "WHERE tenant_id=1 AND code = :c"
                    ), {"c": code}).scalar()
                    for i in range(6):
                        h = 8 + i
                        conn.execute(text(
                            "INSERT INTO working_hour_slots "
                            "(day_id, slot_index, start_time, "
                            " end_time, label, legacy_hour_number) "
                            "VALUES (:d, :i, :s, :e, :ll, :lh)"
                        ), {
                            "d": day_id, "i": i,
                            "s": f"{h:02d}:00", "e": f"{h+1:02d}:00",
                            "ll": f"{i+1}ª ora", "lh": h,
                        })


@pytest.fixture
def client(app_with_temp_db):
    """A TestClient bound to the temp-db FastAPI app.

    Clears the global TTL cache between tests so /api/dataset/state and
    /api/monitor/summary recompute against the fresh tmp DB instead of
    serving stale counts from a previous test.
    """
    from fastapi.testclient import TestClient
    from backend.utils import ttl_cache
    ttl_cache.clear()
    app, _ = app_with_temp_db
    return TestClient(app)
