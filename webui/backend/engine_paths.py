"""Resolve the absolute path to the engine/ folder and inject it on
sys.path so the engine modules can be imported as plain top-level modules
(matching their original layout)."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.normpath(
    os.path.join(HERE, "..", "..", "engine")
)
SCHEDULE_DIR = os.path.normpath(
    os.path.join(HERE, "..", "..", "schedule")
)

if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)
if SCHEDULE_DIR not in sys.path:
    sys.path.insert(0, SCHEDULE_DIR)
