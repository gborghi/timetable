"""Coverage / disposizione / schedule-grid iterate configured day IDs.

A custom animal calendar must drive the shipped helpers, not a
hardcoded lun–sab 1..6.
"""
from __future__ import annotations

import datetime as dt

from backend import models
from backend.disposizione import (
    DISPOSIZIONE_CLASS,
    DISPOSIZIONE_SUBJECT,
    _grid,
    place_disposizione_hours,
)
from backend.routers import coverage as coverage_mod
from backend.routers import schedule as schedule_mod


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


def _replace_calendar_with_animals(session) -> list[int]:
    session.query(models.WorkingHourSlot).delete()
    session.query(models.WorkingDay).delete()
    session.commit()
    ids: list[int] = []
    for code, label, pos, legacy in _ANIMALS:
        d = models.WorkingDay(
            tenant_id=1,
            code=code,
            label=label,
            position=pos,
            legacy_day_number=legacy,
            is_active=True,
        )
        session.add(d)
        session.flush()
        for i in range(6):
            h = 8 + i
            session.add(models.WorkingHourSlot(
                day_id=d.id,
                slot_index=i,
                start_time=f"{h:02d}:00",
                end_time=f"{h + 1:02d}:00",
                label=f"{i + 1}ª ora",
                legacy_hour_number=h,
            ))
        ids.append(legacy)
    session.commit()
    return ids


def test_coverage_week_iterates_animal_day_ids(client, app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    s = SessionLocal()
    try:
        day_ids = _replace_calendar_with_animals(s)
        t = models.Teacher(name="Rossi", max_hours=18)
        cls = models.SchoolClass(name="1A", n_students=20)
        s.add_all([t, cls])
        s.flush()
        sol = models.Solution(name="t", kind="test", is_active=True, obj_value=0)
        s.add(sol)
        s.flush()
        s.add(models.Lesson(
            solution_id=sol.id, teacher_name="Rossi",
            class_name="1A", subject="Mat", day=7, hour=8,
        ))
        s.commit()
    finally:
        s.close()

    week = dt.date(2026, 9, 14)
    r = client.get(f"/api/coverage/week?week_start={week.isoformat()}")
    assert r.status_code == 200, r.text
    body = r.json()
    got = [d["day"] for d in body["days"]]
    assert got == day_ids
    assert 7 in got
    assert 10 in got
    assert len(got) == 10
    # Hours on each day come from the configured slots, not range(8,14) only.
    hours = [c["hour"] for c in body["days"][0]["cells"]]
    assert hours == [8, 9, 10, 11, 12, 13]


def test_coverage_cell_accepts_animal_day_id(client, app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    s = SessionLocal()
    try:
        _replace_calendar_with_animals(s)
        t = models.Teacher(name="Rossi", max_hours=18)
        s.add(t)
        s.flush()
        sol = models.Solution(name="t", kind="test", is_active=True, obj_value=0)
        s.add(sol)
        s.commit()
    finally:
        s.close()

    week = dt.date(2026, 9, 14)
    r = client.get(
        f"/api/coverage/cell?date={week.isoformat()}&day=7&hour=8"
    )
    assert r.status_code == 200, r.text
    assert r.json()["day"] == 7
    assert r.json()["hour"] == 8


def test_disposizione_grid_uses_session_day_ids(app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    s = SessionLocal()
    try:
        day_ids = _replace_calendar_with_animals(s)
        days, hours = _grid(s)
        assert days == day_ids
        assert hours == [8, 9, 10, 11, 12, 13]
        out = place_disposizione_hours(
            {}, {"Rossi": 1}, days=days, hours=hours,
        )
        placed_days = {k[3] for k in out if k[1] == DISPOSIZIONE_CLASS}
        assert placed_days <= set(day_ids)
        assert placed_days  # at least one hour landed
    finally:
        s.close()


def test_schedule_refresh_grid_sees_animal_ids(app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    s = SessionLocal()
    try:
        day_ids = _replace_calendar_with_animals(s)
        days, hours, labels = schedule_mod._refresh_grid(s)
        assert days == day_ids
        assert hours == [8, 9, 10, 11, 12, 13]
        assert labels[1] == "Gatto"
        assert labels[7] == "Aquila"
        assert labels[10] == "Panda"
        # Coverage helper shares the same session list.
        assert coverage_mod._configured_days(s) == day_ids
    finally:
        s.close()
        schedule_mod._refresh_grid()


def test_coverage_helpers_default_to_lun_sab(app_with_temp_db):
    """Empty-config fallback (and the default seed) stay lun–sab 1..6."""
    _, SessionLocal = app_with_temp_db
    s = SessionLocal()
    try:
        days = coverage_mod._configured_days(s)
        hours = coverage_mod._configured_hours(s)
        assert days == [1, 2, 3, 4, 5, 6]
        assert hours == [8, 9, 10, 11, 12, 13]
    finally:
        s.close()


def test_engine_io_reads_animal_ids_not_range_1_7(app_with_temp_db):
    """profs / world / free-day resolution must see the session calendar."""
    from backend import engine_io

    _, SessionLocal = app_with_temp_db
    s = SessionLocal()
    try:
        day_ids = _replace_calendar_with_animals(s)
        days, hours = engine_io.configured_days_hours(s)
        assert days == day_ids
        assert hours == [8, 9, 10, 11, 12, 13]
        assert engine_io.resolve_free_day("Aquila", s) == 7
        assert engine_io.resolve_free_day("7", s) == 7
        assert engine_io.resolve_free_day("Saturday", s) == 6
        assert engine_io.free_day_wire_value(7) == "7"
        assert engine_io.free_day_wire_value(6) == "Saturday"

        t = models.Teacher(name="Rossi", max_hours=18, free_day="Aquila")
        cls = models.SchoolClass(name="1A", n_students=20)
        s.add_all([t, cls])
        s.flush()
        s.add(models.Assignment(
            teacher_id=t.id, class_id=cls.id, subject="Mat", hours=2,
        ))
        s.commit()
        profs = engine_io.profs_dict_from_db(s)
        assert profs["Rossi"]["glibero"][0] == 7
        world = engine_io.build_world(s)
        world_days = [d["index"] for d in world["days"]]
        assert world_days == day_ids
        assert world["days"][6]["name"] == "Aquila"
    finally:
        s.close()


def test_dsl_translator_fallback_follows_loader():
    """Empty WorkingDay table: fallback is get_days(), not a second 1..6."""
    import os
    import sqlite3
    import tempfile

    from backend import engine_paths  # noqa: F401
    import working_hours_config as whc  # type: ignore
    import dsl_translator as dt

    class _Empty:
        def query(self, _m):
            return self

        def all(self):
            return []

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "animals.db")
        from backend.tests.test_named_day_cycle import _seed_animal_calendar
        _seed_animal_calendar(db_path)
        old = os.environ.get("PITANTUM_DB_URL")
        os.environ["PITANTUM_DB_URL"] = f"sqlite:///{db_path}"
        try:
            whc.reload()
            by_day = dt._configured_hours_by_day(_Empty(), object())
            assert set(by_day) == set(range(1, 11))
            assert by_day[7] == set(range(8, 14))
            assert by_day[10] == set(range(8, 14))
        finally:
            if old is None:
                os.environ.pop("PITANTUM_DB_URL", None)
            else:
                os.environ["PITANTUM_DB_URL"] = old
            whc.reload()


def test_teacher_preferred_free_days_persist_animal_id(client, app_with_temp_db):
    """PUT /api/teachers keeps preferred_free_days on a custom day ID."""
    _, SessionLocal = app_with_temp_db
    s = SessionLocal()
    try:
        _replace_calendar_with_animals(s)
    finally:
        s.close()

    created = client.post("/api/teachers", json={
        "name": "Rossi",
        "max_hours": 18,
        "preferred_free_days": [
            {"day": 7, "is_hard": True, "soft_penalty": None},
        ],
        "min_free_days": 2,
    })
    assert created.status_code in (200, 201), created.text
    body = created.json()
    days = [p["day"] for p in body["preferred_free_days"]]
    assert 7 in days, body
    assert body["min_free_days"] == 2

    got = client.get(f"/api/teachers/{body['id']}")
    assert got.status_code == 200, got.text
    assert 7 in [p["day"] for p in got.json()["preferred_free_days"]]


def test_teacher_free_day_preferences_patch_accepts_animal_id(
        client, app_with_temp_db):
    """PATCH /api/teachers/{id}/free-day-preferences accepts Aquila=7."""
    _, SessionLocal = app_with_temp_db
    s = SessionLocal()
    try:
        _replace_calendar_with_animals(s)
    finally:
        s.close()

    created = client.post("/api/teachers", json={"name": "Bianchi", "max_hours": 18})
    assert created.status_code in (200, 201), created.text
    tid = created.json()["id"]

    r = client.patch(
        f"/api/teachers/{tid}/free-day-preferences",
        json={"preferences": [{"day": 7, "priority": 1}]},
    )
    assert r.status_code == 200, r.text
    assert r.json() == [{"day": 7, "priority": 1}]

    listed = client.get(f"/api/teachers/{tid}/free-day-preferences")
    assert listed.status_code == 200, listed.text
    assert listed.json() == [{"day": 7, "priority": 1}]

    s = SessionLocal()
    try:
        import dsl_translator as dt
        rows = dt.load_all_dsl_constraints(
            s, _models=models, include_soft=True)
        prefs = [r for r in rows
                 if r.get("source") == "teacher_free_day_preference"]
        assert any(
            ", 7," in r.get("expression", "") for r in prefs
        ), prefs
    finally:
        s.close()


def test_class_preferred_free_days_persist_animal_id(client, app_with_temp_db):
    """POST /api/classes keeps preferred_free_days on a custom day ID."""
    _, SessionLocal = app_with_temp_db
    s = SessionLocal()
    try:
        _replace_calendar_with_animals(s)
    finally:
        s.close()

    created = client.post("/api/classes", json={
        "name": "1A",
        "preferred_free_days": [
            {"day": 7, "is_hard": True, "soft_penalty": None},
        ],
        "required_free_days_count": 1,
    })
    assert created.status_code in (200, 201), created.text
    body = created.json()
    assert 7 in [p["day"] for p in body["preferred_free_days"]], body

    got = client.get(f"/api/classes/{body['id']}")
    assert got.status_code == 200, got.text
    assert 7 in [p["day"] for p in got.json()["preferred_free_days"]]


def test_disposizione_priorities_keep_animal_day_id(client, app_with_temp_db):
    """PUT /api/coverage/disposizione stores a weight on day ID 7."""
    from backend.disposizione import parse_slot_priorities

    _, SessionLocal = app_with_temp_db
    s = SessionLocal()
    try:
        _replace_calendar_with_animals(s)
        t = models.Teacher(name="ProfD", max_hours=18, disposizione_hours=1)
        s.add(t)
        sol = models.Solution(name="t", kind="test", is_active=True, obj_value=0)
        s.add(sol)
        s.commit()
    finally:
        s.close()

    raw = '[{"day": 7, "hour": 8, "weight": 20}]'
    parsed = parse_slot_priorities(raw)
    assert parsed[(7, 8)] == 20

    r = client.put("/api/coverage/disposizione", json={
        "eligibility": "all",
        "slot_priorities": [{"day": 7, "hour": 8, "weight": 20}],
    })
    assert r.status_code == 200, r.text
    weights = {(p["day"], p["hour"]): p["weight"]
               for p in r.json()["slot_priorities"]}
    assert weights[(7, 8)] == 20

    echoed = client.get("/api/coverage/disposizione")
    assert echoed.status_code == 200, echoed.text
    echoed_w = {(p["day"], p["hour"]): p["weight"]
                for p in echoed.json()["slot_priorities"]}
    assert echoed_w[(7, 8)] == 20


def test_default_seed_still_rejects_unknown_day_id(client):
    """Lun–sab preset: day 7 is not a configured ID, so writes fail/drop."""
    created = client.post("/api/teachers", json={
        "name": "Verdi",
        "max_hours": 18,
        "preferred_free_days": [
            {"day": 7, "is_hard": True, "soft_penalty": None},
            {"day": 6, "is_hard": True, "soft_penalty": None},
        ],
    })
    assert created.status_code in (200, 201), created.text
    days = [p["day"] for p in created.json()["preferred_free_days"]]
    assert 6 in days
    assert 7 not in days

    r = client.patch(
        f"/api/teachers/{created.json()['id']}/free-day-preferences",
        json={"preferences": [{"day": 7, "priority": 1}]},
    )
    assert r.status_code == 400, r.text
    assert "configured calendar ID" in r.text
