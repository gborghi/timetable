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
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create tables if missing. Imported here lazily to avoid cycles."""
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
