"""SQLAlchemy engine + session factory + Base for the timetable webui.

Section 2.5 P2: the URL is now env-driven so Postgres can be plugged in
without code changes. SQLite remains the default for single-user dev.

To switch to Postgres:
  1. pip install psycopg[binary]    (already in requirements.txt)
  2. createdb pitantum               (or use docker-compose)
  3. set PITANTUM_DB_URL=postgresql+psycopg://user:pass@host:5432/pitantum
  4. cd webui/backend && ./.venv/Scripts/alembic upgrade head
  5. start.bat / uvicorn

The Alembic baseline (B9 commit 149575a) was generated against SQLite;
it uses `render_as_batch=True` which is a no-op on Postgres but keeps
SQLite ALTER TABLE working. No code change needed when switching.
"""
from __future__ import annotations

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(HERE, "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)


def _resolve_db_url() -> str:
    """Pick the DB URL in this order:
      1. PITANTUM_DB_URL env var (highest precedence; overrides
         everything -- used to point at Postgres or a test DB).
      2. SQLite at webui/data/timetable.db (default for dev).
    """
    env_url = os.environ.get("PITANTUM_DB_URL")
    if env_url:
        return env_url.strip()
    return f"sqlite:///{os.path.join(DATA_DIR, 'timetable.db')}"


DB_URL = _resolve_db_url()
DB_PATH = (
    DB_URL.replace("sqlite:///", "", 1)
    if DB_URL.startswith("sqlite:///")
    else None
)
IS_SQLITE = DB_URL.startswith("sqlite")

# Engine kwargs that differ between SQLite and Postgres / others:
# - SQLite needs `check_same_thread=False` because uvicorn worker
#   threads share the connection pool.
# - Postgres benefits from a configurable pool_size (env var). Default
#   matches uvicorn's default thread pool (8).
_engine_kwargs: dict = {"echo": False, "future": True}
if IS_SQLITE:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    pool_size = int(os.environ.get("PITANTUM_DB_POOL_SIZE", "8"))
    max_overflow = int(os.environ.get("PITANTUM_DB_MAX_OVERFLOW", "8"))
    _engine_kwargs["pool_size"] = pool_size
    _engine_kwargs["max_overflow"] = max_overflow
    _engine_kwargs["pool_pre_ping"] = True   # auto-reconnect on stale conns

engine = create_engine(DB_URL, **_engine_kwargs)


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, future=True
)


def get_db():
    """Yield a Session and guarantee rollback on uncaught exception.

    Section 2.9 P1: previously a router that raised mid-write left the
    session in an inconsistent state, and the next operation on the
    same session got a "transaction has been rolled back" error. With
    the explicit rollback, exceptions propagate cleanly to the global
    handlers in main.py without leaking state.

    Routers can still call `db.commit()` explicitly (most do); the
    rollback only fires if an unhandled exception bubbles up.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()


def init_db():
    """Create tables if missing. Imported here lazily to avoid cycles.

    Migration strategy (Section 2.7 P1):
    - Alembic is the canonical migration tool. New schema changes
      land as new alembic revisions in `webui/backend/alembic/versions`.
      Run `alembic upgrade head` from `webui/backend/` to apply them.
    - The legacy `_apply_lightweight_migrations()` runs on every
      startup as a safety net for users who don't run alembic; it's
      idempotent (PRAGMA table_info + IF NOT EXISTS) so it works
      alongside alembic.
    - For fresh DBs, `Base.metadata.create_all` builds the canonical
      schema directly; alembic_version is then stamped to head on
      first start (TODO: optional auto-stamp when DB is empty).
    """
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _apply_lightweight_migrations()


def _apply_lightweight_migrations() -> None:
    """Idempotent ALTER TABLE migrations.

    `Base.metadata.create_all` only creates missing TABLES; it does not
    add columns to existing tables. This function adds new columns when
    needed, querying `PRAGMA table_info` (or the equivalent
    information_schema view) to detect what is already there.

    Skipped entirely on non-SQLite engines: the canonical migration tool
    on Postgres is Alembic (`alembic upgrade head`), and SQL syntax
    differences (PRAGMA, AUTOINCREMENT, CREATE INDEX IF NOT EXISTS)
    aren't worth duplicating here. SQLite-specific safety net only.
    """
    if not IS_SQLITE:
        return

    from sqlalchemy import inspect, text

    insp = inspect(engine)

    def has_column(table: str, column: str) -> bool:
        if not insp.has_table(table):
            return False
        return any(c["name"] == column for c in insp.get_columns(table))

    with engine.begin() as conn:
        if insp.has_table("school_classes") \
                and not has_column("school_classes", "curriculum_id"):
            conn.execute(text(
                "ALTER TABLE school_classes ADD COLUMN curriculum_id INTEGER"
            ))
        # nickname columns and split-name columns
        nickname_targets = (
            "teachers", "students", "school_classes", "study_groups",
        )
        for tbl in nickname_targets:
            if insp.has_table(tbl) and not has_column(tbl, "nickname"):
                conn.execute(text(
                    f"ALTER TABLE {tbl} ADD COLUMN nickname VARCHAR(80)"
                ))
        if insp.has_table("teachers"):
            if not has_column("teachers", "last_name"):
                conn.execute(text(
                    "ALTER TABLE teachers ADD COLUMN last_name VARCHAR(80)"
                ))
            if not has_column("teachers", "first_name"):
                conn.execute(text(
                    "ALTER TABLE teachers ADD COLUMN first_name VARCHAR(80)"
                ))
        # state column on classroom_subject_preferences
        if insp.has_table("classroom_subject_preferences") \
                and not has_column("classroom_subject_preferences", "state"):
            conn.execute(text(
                "ALTER TABLE classroom_subject_preferences "
                "ADD COLUMN state VARCHAR(16) DEFAULT 'allowed'"
            ))
            # Backfill: required=True -> 'enforced'; weight>0 -> 'preferred'
            conn.execute(text(
                "UPDATE classroom_subject_preferences "
                "SET state = CASE WHEN required=1 THEN 'enforced' "
                "WHEN weight > 0 THEN 'preferred' ELSE 'allowed' END"
            ))
        # kind column on the two logical-constraint tables
        for tbl in ("logical_unavailabilities",
                    "curriculum_logical_constraints"):
            if insp.has_table(tbl) and not has_column(tbl, "kind"):
                conn.execute(text(
                    f"ALTER TABLE {tbl} ADD COLUMN kind VARCHAR(16) "
                    f"DEFAULT 'hard'"
                ))
                conn.execute(text(
                    f"UPDATE {tbl} SET kind = CASE "
                    f"  WHEN is_hard = 1 THEN 'hard' "
                    f"  WHEN soft_penalty < 0 THEN 'preferred' "
                    f"  ELSE 'soft' END"
                ))

        # Composite indexes on `lessons` (Section 2.2 P1). SQLite's
        # CREATE INDEX IF NOT EXISTS handles upgrades for existing DBs;
        # `metadata.create_all` on fresh DBs creates them via the
        # Index() declarations on the model.
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

        # created_at / updated_at on user-facing entities
        # (Section 2.2 P3). SQLite forbids non-constant defaults in
        # ALTER TABLE ADD COLUMN, so we add the columns nullable, then
        # backfill with CURRENT_TIMESTAMP. Existing rows get a sensible
        # value; future writes are populated by the ORM mixin.
        timestamped = (
            "subjects", "teachers", "school_classes", "classrooms",
            "curricula", "students", "study_groups",
        )
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

        # graduatoria_score on Teacher: nullable Float column used by
        # the Phase-A seniority criterion. Backfill not necessary
        # (NULL means "no score recorded").
        if insp.has_table("teachers") and not has_column(
                "teachers", "graduatoria_score"):
            conn.execute(text(
                "ALTER TABLE teachers ADD COLUMN graduatoria_score FLOAT"
            ))

        # Free-day preferences (Section: Giorni liberi). 3 ordered
        # preferences stored as JSON, plus a HARD count of required
        # free days per week.
        if insp.has_table("teachers") and not has_column(
                "teachers", "preferred_free_days_json"):
            conn.execute(text(
                "ALTER TABLE teachers ADD COLUMN "
                "preferred_free_days_json TEXT"
            ))
        if insp.has_table("teachers") and not has_column(
                "teachers", "required_free_days_count"):
            conn.execute(text(
                "ALTER TABLE teachers ADD COLUMN "
                "required_free_days_count INTEGER NOT NULL DEFAULT 1"
            ))

        # tenant_id on user-facing entities (Section 2.5 P3).
        # Defaults everything to tenant 1 -- the existing single school.
        for tbl in timestamped:
            if not insp.has_table(tbl):
                continue
            if not has_column(tbl, "tenant_id"):
                conn.execute(text(
                    f"ALTER TABLE {tbl} ADD COLUMN tenant_id INTEGER "
                    f"NOT NULL DEFAULT 1"
                ))
                conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS "
                    f"ix_{tbl}_tenant_id ON {tbl} (tenant_id)"
                ))
