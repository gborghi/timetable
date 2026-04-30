"""Alembic environment for piTantum.

Resolves the SQLAlchemy URL from the running app (sqlite:///webui/data/
timetable.db) and binds Base.metadata so `alembic revision --autogenerate`
can diff the model against the live DB.

Usage from `webui/backend/`:
    .venv/Scripts/alembic upgrade head
    .venv/Scripts/alembic revision --autogenerate -m "msg"
    .venv/Scripts/alembic downgrade -1
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Make the backend package importable. Alembic invokes env.py from
# the directory containing alembic.ini (= webui/backend), so the
# parent (=webui) ends up on sys.path.
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
if WEBUI_DIR not in sys.path:
    sys.path.insert(0, WEBUI_DIR)

# Import the live engine to inherit its URL / dialect.
from backend.db import Base, DB_URL  # noqa: E402
import backend.models  # noqa: F401  -- registers tables on Base.metadata

config = context.config

# Override the URL in alembic.ini with the one the app actually uses,
# so devs don't have to keep them in sync.
config.set_main_option("sqlalchemy.url", DB_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,   # SQLite needs batch mode for ALTER
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,   # SQLite needs batch mode
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
