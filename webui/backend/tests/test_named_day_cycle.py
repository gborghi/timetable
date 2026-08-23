"""Configured day IDs (not weekday names) must reach DSL + every optimiser.

The Tab Ore grid is a flat list of day entities. Codes/labels are
display-only (lun1, Gatto, …); the engine key is ``legacy_day_number``.
After ``_apply_working_hours_config`` every consumer that aliases
``cv2.DAYS`` must see that ID list, and DSL pragmas must accept an ID
outside 1..6.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile


def _seed_two_week_cycle(db_path: str) -> None:
    """lun-sab (legacy 1..6) + a second week lun2-sab2 (legacy 7..12)."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE working_days ("
            " id INTEGER PRIMARY KEY,"
            " tenant_id INTEGER NOT NULL DEFAULT 1,"
            " code VARCHAR(32) NOT NULL,"
            " label VARCHAR(64) NOT NULL,"
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
        week1 = [
            ("lun1", "Lunedì 1", 0, 1),
            ("mar1", "Martedì 1", 1, 2),
            ("mer1", "Mercoledì 1", 2, 3),
            ("gio1", "Giovedì 1", 3, 4),
            ("ven1", "Venerdì 1", 4, 5),
            ("sab1", "Sabato 1", 5, 6),
        ]
        week2 = [
            ("lun2", "Lunedì 2", 6, 7),
            ("mar2", "Martedì 2", 7, 8),
            ("mer2", "Mercoledì 2", 8, 9),
            ("gio2", "Giovedì 2", 9, 10),
            ("ven2", "Venerdì 2", 10, 11),
            ("sab2", "Sabato 2", 11, 12),
        ]
        for code, label, pos, legacy in week1 + week2:
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


_ANIMALS = (
    ("Gatto", "Gatto", 0, 1),
    ("Cane", "Cane", 1, 2),
    ("Volpe", "Volpe", 2, 3),
    ("Orso", "Orso", 3, 4),
    ("Lupo", "Lupo", 4, 5),
    ("Cervo", "Cervo", 5, 6),
    ("Aquila", "Aquila", 6, 7),
    ("Tigre", "Tigre", 7, 8),
    ("Lontra", "Lontra", 8, 9),
    ("Panda", "Panda", 9, 10),
)


def _seed_animal_calendar(db_path: str) -> None:
    """Ten days named after animals; IDs 1..10 are independent of the names."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE working_days ("
            " id INTEGER PRIMARY KEY,"
            " tenant_id INTEGER NOT NULL DEFAULT 1,"
            " code VARCHAR(32) NOT NULL,"
            " label VARCHAR(64) NOT NULL,"
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
        for code, label, pos, legacy in _ANIMALS:
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


def _restore(old: str | None, whc, cv2) -> None:
    if old is None:
        os.environ.pop("PITANTUM_DB_URL", None)
    else:
        os.environ["PITANTUM_DB_URL"] = old
    whc.reload()
    cv2._apply_working_hours_config()


def _boot(db_path: str):
    from backend import engine_paths  # noqa: F401
    import working_hours_config as whc  # type: ignore
    import cpsat_v2_timetable as cv2  # type: ignore
    old = _set_db_url(db_path)
    whc.reload()
    cv2._apply_working_hours_config()
    return whc, cv2, old


def test_loader_and_labels_see_twelve_named_days():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "cycle.db")
        _seed_two_week_cycle(db_path)
        whc, cv2, old = _boot(db_path)
        try:
            assert whc.get_days() == list(range(1, 13))
            labels = whc.get_day_labels()
            assert labels[1] == "Lunedì 1"
            assert labels[7] == "Lunedì 2"
            assert labels[12] == "Sabato 2"
            assert cv2.DAYS == list(range(1, 13))
            assert cv2.SLOTS_PER_DAY[7] == 6
            assert cv2.SLOTS_PER_DAY[12] == 6
        finally:
            _restore(old, whc, cv2)


def test_optimisers_alias_extended_DAYS():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "cycle.db")
        _seed_two_week_cycle(db_path)
        whc, cv2, old = _boot(db_path)
        try:
            import metaheuristics as meta  # type: ignore
            import decomposition_temporal as temporal  # type: ignore
            import lagrangian as lag  # type: ignore
            import decomposition_loop as dloop  # type: ignore
            assert meta.DAYS is cv2.DAYS
            assert temporal.DAYS is cv2.DAYS
            assert dloop.DAYS is cv2.DAYS
            assert list(meta.DAYS) == list(range(1, 13))
            assert 7 in cv2.DAYS
            # Lagrangian reads cv2.DAYS at call time (same module object).
            assert list(lag.cv2.DAYS) == list(range(1, 13))
        finally:
            _restore(old, whc, cv2)


def test_cg_helpers_default_days_follow_config():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "cycle.db")
        _seed_two_week_cycle(db_path)
        whc, cv2, old = _boot(db_path)
        try:
            import cg_helpers as cgh  # type: ignore
            profs = {
                "Rossi": {
                    "classi": {"1A": {"Storia": {"ore": 1}}},
                    "glibero": [],
                },
            }
            dc = {("Rossi", "1A", "Storia", 7): 1}
            pats = cgh._seed_patterns(profs, dc, max_per_teacher=1)
            keys = []
            for pat in pats.get("Rossi") or []:
                for k, v in pat.items():
                    if v and isinstance(k, tuple) and len(k) == 5:
                        keys.append(k)
            hours_on_day7 = [h for (_p, _c, _s, d, h) in keys if d == 7]
            assert hours_on_day7, f"CG seed should place the day-7 hour, got {pats}"
        finally:
            _restore(old, whc, cv2)


def test_dsl_pragma_accepts_day_7():
    from backend.utils import general_dsl as G

    lessons = [
        {"teacher": "T", "class": "1A", "subject": "Mat",
         "day": 7, "hour": 8, "classroom": "",
         "classroom_type": "", "classroom_kind": "",
         "classroom_tags": [], "classroom_plesso": None,
         "slot": (7, 8)},
    ]
    world = {
        "teachers": [{"name": "T"}],
        "classes": [{"name": "1A"}],
        "classrooms": [], "subjects": [], "curricula": [],
        "groups": [], "students": [], "assignments": [],
        "days": [{"index": d} for d in range(1, 13)],
        "hours": [{"index": h} for h in range(8, 14)],
        "slots": [{"day": d, "hour": h}
                  for d in range(1, 13) for h in range(8, 14)],
        "lessons": lessons,
    }
    # Teacher has a lesson on day 7 → unavailable_day(7) is False.
    tree = G.parse('teacher_unavailable_day("T", 7)')
    assert G.evaluate(tree, world) is False
    # No lesson on day 8 → True.
    tree = G.parse('teacher_unavailable_day("T", 8)')
    assert G.evaluate(tree, world) is True
    # Capacity on day 7: one hour placed, cap 1 → True.
    tree = G.parse('teacher_day_capacity("T", 7, 1)')
    assert G.evaluate(tree, world) is True
    tree = G.parse('teacher_day_capacity("T", 7, 0)')
    assert G.evaluate(tree, world) is False


def test_phase_a_and_b_place_on_lun2():
    """Lock 2 hours onto legacy day 7 (lun2) and solve A+B."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "cycle.db")
        _seed_two_week_cycle(db_path)
        whc, cv2, old = _boot(db_path)
        try:
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
                ("Rossi", "1A", "Storia", 7): 2,
                ("Bianchi", "1A", "Geografia", 7): 2,
            }
            dc = cv2.solve_phase_a(
                profs, classes, triples, class_profs,
                time_limit=8, workers=1, log=False,
                locked_day_count=locked,
            )
            assert dc[("Rossi", "1A", "Storia", 7)] == 2
            assert dc[("Bianchi", "1A", "Geografia", 7)] == 2
            for (_p, _c, _s, d), n in dc.items():
                if n:
                    assert d in cv2.DAYS
            sol, st = cv2.solve_phase_b_for_day(
                7, profs, classes, triples, class_profs, dc,
                time_limit=8, workers=1, log=False,
                enforce_no_holes=True,
            )
            assert sol is not None, f"phase B lun2 infeasible: {st}"
            placed = sorted(
                h for (_p, _cl, _s, d, h), v in sol.items()
                if v and d == 7
            )
            assert len(placed) == 4
            assert all(h in cv2.HOURS for h in placed)
        finally:
            _restore(old, whc, cv2)


def test_api_duplicate_cycle_then_engine_sees_mon2(client):
    r = client.post("/api/working-hours/duplicate-cycle")
    assert r.status_code == 200, r.text
    codes = [d["code"] for d in r.json()["days"]]
    assert "MON2" in codes
    mon2 = next(d for d in r.json()["days"] if d["code"] == "MON2")
    assert mon2["legacy_day_number"] == 7
    # Point the engine loader at the test DB (same process, in-memory
    # sqlite is NOT what working_hours_config reads). We only assert
    # the API contract here; the sqlite file tests cover the loader.
    assert r.json()["max_slots_per_day"] == 6
    client.post("/api/working-hours/reset")


def test_animal_calendar_loader_solver_and_dsl():
    """Ten animal-named days: IDs, not weekday names, drive the engine."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "animals.db")
        _seed_animal_calendar(db_path)
        whc, cv2, old = _boot(db_path)
        try:
            assert whc.get_days() == list(range(1, 11))
            labels = whc.get_day_labels()
            assert labels[1] == "Gatto"
            assert labels[7] == "Aquila"
            assert labels[10] == "Panda"
            # Rename must not change the ID.
            assert whc.get_day_label(7) == "Aquila"
            assert cv2.DAYS == list(range(1, 11))
            assert 7 in cv2.DAYS
            assert cv2.SLOTS_PER_DAY[10] == 6

            from backend.utils import general_dsl as G
            world = {
                "teachers": [{"name": "T"}],
                "classes": [{"name": "1A"}],
                "classrooms": [], "subjects": [], "curricula": [],
                "groups": [], "students": [], "assignments": [],
                "days": [{"index": d} for d in range(1, 11)],
                "hours": [{"index": h} for h in range(8, 14)],
                "slots": [{"day": d, "hour": h}
                          for d in range(1, 11) for h in range(8, 14)],
                "lessons": [{
                    "teacher": "T", "class": "1A", "subject": "Mat",
                    "day": 7, "hour": 8, "classroom": "",
                    "classroom_type": "", "classroom_kind": "",
                    "classroom_tags": [], "classroom_plesso": None,
                    "slot": (7, 8),
                }],
            }
            assert G.evaluate(G.parse('teacher_unavailable_day("T", 7)'),
                              world) is False
            assert G.evaluate(G.parse('teacher_unavailable_day("T", 10)'),
                              world) is True
        finally:
            _restore(old, whc, cv2)


def test_rename_animal_day_keeps_id(client):
    """Renaming Gatto → Micio must not change the numeric day ID."""
    days = client.get("/api/working-hours/days").json()
    mon = next(d for d in days if d["code"] == "MON")
    r = client.put(f"/api/working-hours/days/{mon['id']}",
                   json={"code": "Gatto", "label": "Gatto"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["legacy_day_number"] == mon["legacy_day_number"]
    assert body["id"] == mon["id"]
    assert body["code"] == "Gatto"
    client.post("/api/working-hours/reset")


def test_api_creates_animal_named_day(client):
    days = client.get("/api/working-hours/days").json()
    clone = days[0]["id"]
    r = client.post("/api/working-hours/days", json={
        "code": "Gatto",
        "label": "Gatto",
        "position": 20,
        "legacy_day_number": 20,
        "clone_slots_from": clone,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == "Gatto"
    assert body["label"] == "Gatto"
    assert body["legacy_day_number"] == 20
    assert len(body["slots"]) == 6
    # A lesson/pragma on a non-1..6 ID is accepted by the schema.
    from backend.schemas import CompresenzaHour, DisposizioneSlotPriority
    CompresenzaHour(day=20, hour=8)
    DisposizioneSlotPriority(day=20, hour=8, weight=5)
    client.delete(f"/api/working-hours/days/{body['id']}")
