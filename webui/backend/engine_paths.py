"""Resolve the absolute path to the experiments/ folder and inject it on
sys.path so the engine modules can be imported as plain top-level modules
(matching their original layout)."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXPERIMENTS_DIR = os.path.normpath(
    os.path.join(HERE, "..", "..", "experiments")
)
SCHEDULE_DIR = os.path.normpath(
    os.path.join(HERE, "..", "..", "schedule")
)

if EXPERIMENTS_DIR not in sys.path:
    sys.path.insert(0, EXPERIMENTS_DIR)
if SCHEDULE_DIR not in sys.path:
    sys.path.insert(0, SCHEDULE_DIR)
