"""Day/hour grid defaults used by solvers and the move preview.

Prefer the Tab Ore config when a DB is available. These constants
match the legacy Italian-school defaults seeded by the lightweight
migration in db.py (Mon–Sat, 8:00–14:00).
"""
from __future__ import annotations

try:
    from working_hours_config import DEFAULT_DAYS as _WC_DAYS
    from working_hours_config import DEFAULT_HOURS as _WC_HOURS
except ImportError:
    _WC_DAYS = list(range(1, 7))
    _WC_HOURS = list(range(8, 14))

DAYS: list[int] = list(_WC_DAYS)
HOURS: list[int] = list(_WC_HOURS)

DAY_TO_INT = {
    "Monday": 1, "Tuesday": 2, "Wednesday": 3,
    "Thursday": 4, "Friday": 5, "Saturday": 6,
    "Lunedi": 1, "Martedi": 2, "Mercoledi": 3,
    "Giovedi": 4, "Venerdi": 5, "Sabato": 6,
}
