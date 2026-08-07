"""Resolve the absolute path to the engine/ folder and inject it on
sys.path so the engine modules can be imported as plain top-level modules
(matching their original layout).

Call ``ensure_engine_on_path()`` early, before any engine imports.
The module-level call below keeps backward compatibility for existing
importers that ``from . import engine_paths`` after optimization.py:19.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.normpath(
    os.path.join(HERE, "..", "..", "engine")
)


def ensure_engine_on_path() -> None:
    """Inject engine/ onto sys.path so flat imports work."""
    if ENGINE_DIR not in sys.path:
        sys.path.insert(0, ENGINE_DIR)


# Backward-compatible module-level side-effect: existing importers that
# ``from . import engine_paths  # noqa: F401`` rely on the path injection
# happening at import time. New code should call ``ensure_engine_on_path()``
# explicitly instead.
ensure_engine_on_path()
