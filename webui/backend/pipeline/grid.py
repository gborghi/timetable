"""Day/hour grid defaults used by solvers and the move preview.

Prefer the Tab Ore config when a DB is available. These constants
match the legacy Italian-school defaults seeded by the lightweight
migration in db.py (Mon–Sat, 8:00–14:00).
"""
from __future__ import annotations

try:
    from working_hours_config import get_days as _get_days
    from working_hours_config import get_hours as _get_hours
    from working_hours_config import DEFAULT_DAYS, DEFAULT_HOURS
except ImportError:
    DEFAULT_DAYS = [1, 2, 3, 4, 5, 6]
    DEFAULT_HOURS = [8, 9, 10, 11, 12, 13]
    def _get_days():
        return list(DEFAULT_DAYS)
    def _get_hours():
        return list(DEFAULT_HOURS)

DAYS: list[int] = list(_get_days())
HOURS: list[int] = list(_get_hours())

DAY_TO_INT = {
    "Monday": 1, "Tuesday": 2, "Wednesday": 3,
    "Thursday": 4, "Friday": 5, "Saturday": 6,
    "Lunedi": 1, "Martedi": 2, "Mercoledi": 3,
    "Giovedi": 4, "Venerdi": 5, "Sabato": 6,
}


def refresh() -> tuple[list[int], list[int]]:
    """Reload DAYS/HOURS from the configured calendar (empty = lun–sab)."""
    days = list(_get_days()) or list(DEFAULT_DAYS)
    hours = list(_get_hours()) or list(DEFAULT_HOURS)
    DAYS[:] = days
    HOURS[:] = hours
    return days, hours
