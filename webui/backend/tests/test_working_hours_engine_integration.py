"""End-to-end integration: customise the working-hours config via the
API, then verify the engine-side loader picks up the new values.

Scope
-----
The engine continues to use the legacy hardcoded DAYS=[1..6] /
HOURS=[8..13] inside cpsat_v2_timetable for the actual solver runs
(replacing those module-level constants is a v2 follow-up). What we
DO verify here is the contract between webui and engine -- the
``working_hours_config`` accessors return the customised values, so
once the solver is plumbed to call them, the change propagates
through transparently.

The ``working_hours_config`` module reads the SQLite DB directly,
bypassing SQLAlchemy. This test points it at a *real* SQLite file
(rather than the in-memory test session) so the loader's read path
is exercised.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile


def _seed_default(db_path: str) -> None:
    """Create the working_days + working_hour_slots tables and seed
    the canonical default. Mirrors the alembic + lightweight
    migration logic on a brand-new sqlite file."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE working_days ("
            " id INTEGER PRIMARY KEY,"
            " tenant_id INTEGER NOT NULL DEFAULT 1,"
            " code VARCHAR(8) NOT NULL,"
            " label VARCHAR(32) NOT NULL,"
            " position INTEGER NOT NULL,"
            " legacy_day_number INTEGER NOT NULL,"
            " is_active BOOLEAN NOT NULL DEFAULT 1)"
        )
        conn.execute(
            "CREATE TABLE working_hour_slots ("
            " id INTEGER PRIMARY KEY,"
            " day_id INTEGER NOT NULL,"
            " slot_index INTEGER NOT NULL,"
            " start_time VARCHAR(5) NOT NULL,"
            " end_time VARCHAR(5) NOT NULL,"
            " label VARCHAR(32),"
            " legacy_hour_number INTEGER NOT NULL,"
            " FOREIGN KEY(day_id) REFERENCES working_days(id))"
        )
        defaults = [
            ("MON", "Lunedi",    0, 1),
            ("TUE", "Martedi",   1, 2),
            ("WED", "Mercoledi", 2, 3),
            ("THU", "Giovedi",   3, 4),
            ("FRI", "Venerdi",   4, 5),
            ("SAT", "Sabato",    5, 6),
        ]
        for code, label, pos, legacy in defaults:
            cur = conn.execute(
                "INSERT INTO working_days "
                "(tenant_id, code, label, position,"
                " legacy_day_number, is_active) "
                "VALUES (1, ?, ?, ?, ?, 1)",
                (code, label, pos, legacy),
            )
            day_id = cur.lastrowid
            for i in range(6):
                h = 8 + i
                conn.execute(
                    "INSERT INTO working_hour_slots "
                    "(day_id, slot_index, start_time, end_time,"
                    " label, legacy_hour_number) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (day_id, i, f"{h:02d}:00", f"{h+1:02d}:00",
                     f"{i+1}ª ora", h),
                )
        conn.commit()


def _set_db_url(path: str) -> str | None:
    old = os.environ.get("PITANTUM_DB_URL")
    os.environ["PITANTUM_DB_URL"] = f"sqlite:///{path}"
    return old


def _restore_db_url(old: str | None) -> None:
    if old is None:
        os.environ.pop("PITANTUM_DB_URL", None)
    else:
        os.environ["PITANTUM_DB_URL"] = old


def _import_loader():
    from backend import engine_paths  # noqa: F401  (path shim)
    import working_hours_config as whc  # type: ignore
    return whc


def test_engine_picks_up_default_seed():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "wh.db")
        _seed_default(db_path)
        whc = _import_loader()
        old = _set_db_url(db_path)
        try:
            whc.reload()
            assert whc.get_days() == [1, 2, 3, 4, 5, 6]
            assert whc.get_hours() == [8, 9, 10, 11, 12, 13]
            assert whc.get_max_slots_per_day() == 6
            assert whc.is_uniform_slot_count() is True
            assert whc.get_slot_label(1, 0) == "08:00-09:00"
        finally:
            _restore_db_url(old)
            whc.reload()


def test_engine_drops_disabled_day():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "wh.db")
        _seed_default(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE working_days SET is_active=0 WHERE code='SAT'"
            )
            conn.commit()
        whc = _import_loader()
        old = _set_db_url(db_path)
        try:
            whc.reload()
            # SAT is no longer working -> get_days() reports 5 days.
            assert whc.get_days() == [1, 2, 3, 4, 5]
            # HOURS unchanged (mon..fri still have 6 slots).
            assert whc.get_hours() == [8, 9, 10, 11, 12, 13]
            assert whc.get_active_day_count() == 5
        finally:
            _restore_db_url(old)
            whc.reload()


def test_engine_picks_up_variable_slots_per_day():
    """Spec example: lun-ven 6 slots (8-14), sab 4 afternoon slots
    (14-18). The engine sees a UNIFORM HOURS array of length
    ``max_slots_per_day = 6`` and is_uniform_slot_count() returns
    False so callers can detect the heterogeneous layout."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "wh.db")
        _seed_default(db_path)
        with sqlite3.connect(db_path) as conn:
            sat_id = conn.execute(
                "SELECT id FROM working_days WHERE code='SAT'"
            ).fetchone()[0]
            conn.execute(
                "DELETE FROM working_hour_slots WHERE day_id=?",
                (sat_id,),
            )
            for i in range(4):
                h = 14 + i
                conn.execute(
                    "INSERT INTO working_hour_slots "
                    "(day_id, slot_index, start_time, end_time,"
                    " label, legacy_hour_number) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (sat_id, i, f"{h:02d}:00", f"{h+1:02d}:00",
                     f"{i+1}ª pomer.", h),
                )
            conn.commit()
        whc = _import_loader()
        old = _set_db_url(db_path)
        try:
            whc.reload()
            assert whc.get_days() == [1, 2, 3, 4, 5, 6]
            assert whc.get_max_slots_per_day() == 6
            assert whc.is_uniform_slot_count() is False
            # SAT slot 0 -> 14:00-15:00
            assert whc.get_slot_label(6, 0) == "14:00-15:00"
            # MON slot 0 still 08:00-09:00
            assert whc.get_slot_label(1, 0) == "08:00-09:00"
        finally:
            _restore_db_url(old)
            whc.reload()


def test_engine_falls_back_to_defaults_on_empty_table():
    """Empty working_days table -> legacy fallback so old DBs that
    haven't run the migration keep working."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "wh.db")
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE working_days ("
                " id INTEGER PRIMARY KEY,"
                " tenant_id INTEGER NOT NULL DEFAULT 1,"
                " code VARCHAR(8) NOT NULL,"
                " label VARCHAR(32) NOT NULL,"
                " position INTEGER NOT NULL,"
                " legacy_day_number INTEGER NOT NULL,"
                " is_active BOOLEAN NOT NULL DEFAULT 1)"
            )
        whc = _import_loader()
        old = _set_db_url(db_path)
        try:
            whc.reload()
            assert whc.get_days() == [1, 2, 3, 4, 5, 6]
            assert whc.get_hours() == [8, 9, 10, 11, 12, 13]
        finally:
            _restore_db_url(old)
            whc.reload()


def test_engine_loader_exposes_slots_per_day_map():
    """``get_slots_per_day_map()`` powers the CP-SAT slot-count
    constraint: it returns a mapping from each active legacy day
    number to its number of active slots."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "wh.db")
        _seed_default(db_path)
        # Drop SAT to 4 slots and disable WED entirely.
        with sqlite3.connect(db_path) as conn:
            sat_id = conn.execute(
                "SELECT id FROM working_days WHERE code='SAT'"
            ).fetchone()[0]
            conn.execute(
                "DELETE FROM working_hour_slots WHERE day_id=?",
                (sat_id,),
            )
            for i in range(4):
                h = 14 + i
                conn.execute(
                    "INSERT INTO working_hour_slots "
                    "(day_id, slot_index, start_time, end_time,"
                    " label, legacy_hour_number) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (sat_id, i, f"{h:02d}:00", f"{h+1:02d}:00",
                     f"{i+1}ª pomer.", h),
                )
            conn.execute(
                "UPDATE working_days SET is_active=0 WHERE code='WED'"
            )
            conn.commit()
        whc = _import_loader()
        old = _set_db_url(db_path)
        try:
            whc.reload()
            spd = whc.get_slots_per_day_map()
            # WED dropped, SAT has 4 slots, others 6.
            assert spd == {1: 6, 2: 6, 4: 6, 5: 6, 6: 4}
        finally:
            _restore_db_url(old)
            whc.reload()


def _seed_variable_slots(db_path: str) -> None:
    """5 active days (Mon-Fri); FRI has 4 slots, others 6."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE working_days ("
            " id INTEGER PRIMARY KEY,"
            " tenant_id INTEGER NOT NULL DEFAULT 1,"
            " code VARCHAR(8) NOT NULL,"
            " label VARCHAR(32) NOT NULL,"
            " position INTEGER NOT NULL,"
            " legacy_day_number INTEGER NOT NULL,"
            " is_active BOOLEAN NOT NULL DEFAULT 1)"
        )
        conn.execute(
            "CREATE TABLE working_hour_slots ("
            " id INTEGER PRIMARY KEY,"
            " day_id INTEGER NOT NULL,"
            " slot_index INTEGER NOT NULL,"
            " start_time VARCHAR(5) NOT NULL,"
            " end_time VARCHAR(5) NOT NULL,"
            " label VARCHAR(32),"
            " legacy_hour_number INTEGER NOT NULL,"
            " FOREIGN KEY(day_id) REFERENCES working_days(id))"
        )
        days = [
            ("MON", "Lunedi",    0, 1, 6),
            ("TUE", "Martedi",   1, 2, 6),
            ("WED", "Mercoledi", 2, 3, 6),
            ("THU", "Giovedi",   3, 4, 6),
            ("FRI", "Venerdi",   4, 5, 4),  # FRI: only 4 slots
        ]
        for code, label, pos, legacy, n_slots in days:
            cur = conn.execute(
                "INSERT INTO working_days "
                "(tenant_id, code, label, position,"
                " legacy_day_number, is_active) "
                "VALUES (1, ?, ?, ?, ?, 1)",
                (code, label, pos, legacy),
            )
            day_id = cur.lastrowid
            for i in range(n_slots):
                h = 8 + i
                conn.execute(
                    "INSERT INTO working_hour_slots "
                    "(day_id, slot_index, start_time, end_time,"
                    " label, legacy_hour_number) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (day_id, i, f"{h:02d}:00", f"{h+1:02d}:00",
                     f"{i+1}ª ora", h),
                )
        conn.commit()


def test_engine_solves_with_variable_slots_per_day():
    """End-to-end: with a 5-day config where FRI has only 4 slots,
    the CP-SAT solvers (Phase A + Phase B per-day) respect the
    per-day slot cap. The variable-slots constraint ensures Phase B
    cannot place lessons at hour indices 4-5 on FRI (h=12, h=13)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "wh.db")
        _seed_variable_slots(db_path)
        whc = _import_loader()
        old = _set_db_url(db_path)
        try:
            whc.reload()
            # Sanity: loader sees the 5-day variable layout.
            assert whc.get_days() == [1, 2, 3, 4, 5]
            assert whc.get_max_slots_per_day() == 6
            spd = whc.get_slots_per_day_map()
            assert spd == {1: 6, 2: 6, 3: 6, 4: 6, 5: 4}

            # Refresh the engine module-level constants from the
            # loader so DAYS / HOURS / SLOTS_PER_DAY pick up the
            # 5-day variable layout. metaheuristics, alns, vns,
            # column_generation, etc. all share the same list
            # references via module-level aliasing, so this single
            # mutate-in-place call propagates to every consumer.
            from backend import engine_paths  # noqa: F401
            import cpsat_v2_timetable as cv2  # type: ignore
            cv2._apply_working_hours_config()
            assert cv2.DAYS == [1, 2, 3, 4, 5]
            assert cv2.SLOTS_PER_DAY == {1: 6, 2: 6, 3: 6, 4: 6, 5: 4}

            import metaheuristics as meta  # type: ignore
            # Aliasing: meta.DAYS shares the cv2.DAYS list object.
            assert meta.DAYS is cv2.DAYS
            assert meta.HOURS is cv2.HOURS

            # Tiny scenario: 2 teachers, 1 class, each teaching a
            # 2-hour cattedra (engine caps each cattedra at 2h/day,
            # and each prof at 3h per (prof, class, day) -- so we
            # need 2 profs to land 4 hours in the same class on FRI).
            # No Mat/Ita/Motorie subjects keep the HARD pair logic
            # out of the picture; empty glibero suppresses the
            # free-day choice pragma. Phase A locks force all 4 hours
            # onto FRI so the Phase B variable-slot constraint is
            # exactly what is under test.
            profs = {
                "Rossi": {
                    "classi": {"1A": {"Storia": {"ore": 2}}},
                    "glibero": [],
                },
                "Bianchi": {
                    "classi": {"1A": {"Geografia": {"ore": 2}}},
                    "glibero": [],
                },
            }
            classes, triples, class_profs = cv2.build_indices(profs)
            locked = {
                ("Rossi", "1A", "Storia", 5): 2,
                ("Bianchi", "1A", "Geografia", 5): 2,
            }
            dc = cv2.solve_phase_a(
                profs, classes, triples, class_profs,
                time_limit=5, workers=1, log=False,
                locked_day_count=locked,
            )
            assert dc[("Rossi", "1A", "Storia", 5)] == 2, \
                f"phase A did not place Storia on FRI: {dc}"
            assert dc[("Bianchi", "1A", "Geografia", 5)] == 2, \
                f"phase A did not place Geografia on FRI: {dc}"

            sol_fri, st_b = cv2.solve_phase_b_for_day(
                5, profs, classes, triples, class_profs, dc,
                time_limit=5, workers=1, log=False,
                enforce_no_holes=True,
            )
            assert sol_fri is not None, \
                f"phase B day 5 (FRI, 4 slots) infeasible: {st_b}"
            # No lessons at h=12 or h=13 (slot indices 4, 5).
            for (p, cl, s, d, h), v in sol_fri.items():
                if v and d == 5:
                    assert h not in (12, 13), (
                        f"variable-slots constraint violated: "
                        f"lesson at FRI h={h}: ({p},{cl},{s})"
                    )
            # The 4 hours land on slots 8-11 (h=8, 9, 10, 11).
            placed = sorted(k[4] for k, v in sol_fri.items()
                            if v and k[3] == 5)
            assert placed == [8, 9, 10, 11], (
                f"expected 4 contiguous hours h=8..11 on FRI, "
                f"got {placed}"
            )
        finally:
            _restore_db_url(old)
            whc.reload()
            # Restore engine constants to legacy defaults so other
            # tests in the same session don't run on a stale 5-day
            # layout.
            from backend import engine_paths  # noqa: F401
            import cpsat_v2_timetable as cv2  # type: ignore
            cv2._apply_working_hours_config()
