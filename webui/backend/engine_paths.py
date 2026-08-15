"""Centralized path resolution utilities for piTantum.

This module provides a single source of truth for all filesystem path resolution
across the codebase. All path operations should use these functions instead of
inline ``os.path.dirname(__file__)`` or ``sys.path.insert()`` calls.

Key principles:
- Use pathlib.Path instead of os.path strings
- Centralize ALL path resolution here
- No direct sys.path manipulation outside this module
- Environment-aware paths via PITANTUM_* env vars

Usage:
    from .engine_paths import get_engine_dir, get_data_dir, get_runs_dir
    engine_root = get_engine_dir()
    data_root = get_data_dir()
    runs_root = get_runs_dir()
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Core directory resolution using pathlib
HERE = Path(__file__).resolve().parent
WEBUI_DIR = HERE.parent  # webui/
ROOT_DIR = WEBUI_DIR.parent  # timetable/
ENGINE_DIR_RAW = ROOT_DIR / "engine"  # Raw engine directory


def get_engine_dir() -> Path:
    """Return the engine/ directory as pathlib.Path."""
    return ENGINE_DIR_RAW


def get_webui_dir() -> Path:
    """Return the webui/ directory as pathlib.Path."""
    return WEBUI_DIR


def get_root_dir() -> Path:
    """Return the timetable/ project root as pathlib.Path."""
    return ROOT_DIR


def get_data_dir() -> Path:
    """Return the data storage directory.
    
    Priority:
    1. PITANTUM_DATA_DIR env var if set
    2. webui/data/ relative to project root
    """
    env_dir = os.getenv("PITANTUM_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return ROOT_DIR / "webui" / "data"


def get_runs_dir() -> Path:
    """Return the optimization runs directory.
    
    Priority:
    1. PITANTUM_RUNS_DIR env var if set (recommended for isolation)
    2. Default to /tmp/pitantum-runs/<hash> for production safety
    3. Fallback to webui/data/runs/ (not recommended for multi-process)
    
    WARNING: Using webui/data/runs/ when multiple processes share the same
    filesystem can cause run file collisions between production and simulation.
    """
    env_dir = os.getenv("PITANTUM_RUNS_DIR")
    if env_dir:
        return Path(env_dir)
    
    # Production-safe default: temp directory
    default_runs_dir = Path("/tmp/pitantum-runs")
    if default_runs_dir.exists():
        return default_runs_dir
    
    # Legacy fallback only if no alternative available
    legacy_dir = ROOT_DIR / "webui" / "data" / "runs"
    return legacy_dir


def get_tests_dir() -> Path:
    """Return the tests/ directory as pathlib.Path."""
    return ROOT_DIR / "tests"


def ensure_engine_on_path() -> None:
    """Ensure the engine/ directory is on sys.path for flat imports.
    
    This should ONLY be called from here or from initialization code.
    After calling this, engine modules can be imported directly without
    package prefixes (maintaining backward compatibility).
    
    The function uses PYTHONPATH environment variable when possible instead
    of modifying sys.path at runtime.
    """
    engine_dir_str = str(ENGINE_DIR_RAW.resolve())
    
    # Check PYTHONPATH first (better practice than runtime sys.path modification)
    python_path = os.environ.get("PYTHONPATH", "")
    if python_path and ENGINE_DIR_RAW.name not in python_path:
        os.environ["PYTHONPATH"] = f"{ENGINE_DIR_RAW}{os.pathsep}{python_path}"
    
    # Fallback to sys.path if needed
    if engine_dir_str not in sys.path:
        sys.path.insert(0, engine_dir_str)


# Backward-compatible module-level side-effect for legacy importers
# New code should call ensure_engine_on_path() explicitly
ensure_engine_on_path()
