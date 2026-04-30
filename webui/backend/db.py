"""SQLAlchemy engine + session factory + Base for the timetable webui."""
from __future__ import annotations

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(HERE, "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "timetable.db")
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False},
    echo=False,
    future=True,
)


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
    """Idempotent ALTER TABLE migrations for SQLite.

    `Base.metadata.create_all` only creates missing TABLES; it does not
    add columns to existing tables. This function adds new columns when
    needed, querying `PRAGMA table_info` to detect what is already there.
    """
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
