"""Ore di disposizione: reuse of coverage/substitutions + post-solve place."""
from __future__ import annotations

import datetime as dt

from backend.disposizione import (
    DISPOSIZIONE_CLASS,
    DISPOSIZIONE_SUBJECT,
    is_disposizione_key,
    place_disposizione_hours,
    teacher_quotas,
)


def test_place_skips_busy_slots_and_prefers_saturday():
    sol = {
        ("Rossi", "1A", "Mat", 6, 8): 1,
        ("Rossi", "1A", "Mat", 1, 9): 1,
    }
    out = place_disposizione_hours(
        sol, {"Rossi": 2, "Bianchi": 1},
        days=[1, 6], hours=[8, 9],
    )
    rossi = {(d, h) for (p, cl, s, d, h), v in out.items()
             if v == 1 and p == "Rossi" and is_disposizione_key((p, cl, s))}
    bianchi = {(d, h) for (p, cl, s, d, h), v in out.items()
               if v == 1 and p == "Bianchi" and is_disposizione_key((p, cl, s))}
    assert (6, 8) not in rossi          # already teaching
    assert (6, 9) in rossi              # next Saturday slot
    assert (1, 8) in rossi              # Monday first hour
    assert bianchi == {(6, 8)}          # highest-weight free slot
    assert out[("Rossi", "1A", "Mat", 6, 8)] == 1


def test_school_cap_and_under_contract_eligibility(client, app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    from backend import models
    s = SessionLocal()
    try:
        full = models.Teacher(name="FullLoad", max_hours=4, disposizione_hours=3)
        spare = models.Teacher(name="Spare", max_hours=18, disposizione_hours=3)
        cls = models.SchoolClass(name="1A", n_students=20)
        s.add_all([full, spare, cls])
        s.flush()
        s.add(models.Assignment(
            teacher_id=full.id, class_id=cls.id, subject="Mat", hours=4,
        ))
        s.add(models.Assignment(
            teacher_id=spare.id, class_id=cls.id, subject="Ita", hours=2,
        ))
        s.commit()
        all_q = teacher_quotas(s, "all", max_total_hours=None)
        assert all_q == {"FullLoad": 3, "Spare": 3}
        under = teacher_quotas(s, "under_contract", max_total_hours=None)
        assert under == {"Spare": 3}
        capped = teacher_quotas(s, "all", max_total_hours=2)
        assert sum(capped.values()) == 2
        assert set(capped) <= {"FullLoad", "Spare"}
    finally:
        s.close()


def test_coverage_cell_flags_disp_free_and_hole(client, app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    from backend import models
    s = SessionLocal()
    try:
        disp = models.Teacher(name="ProfDisp", max_hours=18, disposizione_hours=1)
        hole = models.Teacher(name="ProfHole", max_hours=18)
        free = models.Teacher(name="ProfFree", max_hours=18)
        cls = models.SchoolClass(name="1A", n_students=20)
        s.add_all([disp, hole, free, cls])
        s.flush()
        sol = models.Solution(name="t", kind="test", is_active=True, obj_value=0)
        s.add(sol)
        s.flush()
        s.add(models.Lesson(
            solution_id=sol.id, teacher_name="ProfDisp",
            class_name=DISPOSIZIONE_CLASS, subject=DISPOSIZIONE_SUBJECT,
            day=1, hour=9,
        ))
        s.add(models.Lesson(
            solution_id=sol.id, teacher_name="ProfHole",
            class_name="1A", subject="Mat", day=1, hour=8,
        ))
        s.add(models.Lesson(
            solution_id=sol.id, teacher_name="ProfHole",
            class_name="1A", subject="Mat", day=1, hour=10,
        ))
        s.commit()
    finally:
        s.close()

    week = dt.date(2026, 9, 14)  # Monday
    r = client.get(f"/api/coverage/cell?date={week.isoformat()}&day=1&hour=9")
    assert r.status_code == 200, r.text
    by_name = {t["name"]: t for t in r.json()["available"]}
    assert by_name["ProfDisp"]["is_disposizione"] is True
    assert by_name["ProfDisp"]["kind"] == "disposizione"
    assert by_name["ProfHole"]["is_hole"] is True
    assert by_name["ProfHole"]["kind"] == "hole"
    assert by_name["ProfFree"]["kind"] == "free"
    assert by_name["ProfFree"]["is_disposizione"] is False
    names = [t["name"] for t in r.json()["available"]]
    assert names.index("ProfDisp") < names.index("ProfHole") < names.index("ProfFree")

    w = client.get(f"/api/coverage/week?week_start={week.isoformat()}")
    assert w.status_code == 200
    mon = w.json()["days"][0]
    cell9 = next(c for c in mon["cells"] if c["hour"] == 9)
    assert cell9["n_disposizione_teachers"] >= 1
    assert cell9["n_hole_teachers"] >= 1


def test_coverage_cell_flags_same_subject_as_absent(client, app_with_temp_db):
    """Disposizione is subject-agnostic; coverage still flags same-subject
    teachers so the substitutions pane can filter them."""
    _, SessionLocal = app_with_temp_db
    from backend import models
    s = SessionLocal()
    try:
        absent = models.Teacher(name="ProfAssente", max_hours=18)
        mate = models.Teacher(name="ProfMate", max_hours=18)
        ita = models.Teacher(name="ProfIta", max_hours=18)
        cls = models.SchoolClass(name="1A", n_students=20)
        s.add_all([absent, mate, ita, cls])
        s.flush()
        s.add_all([
            models.TeacherSubject(teacher_id=absent.id, subject="Mat"),
            models.TeacherSubject(teacher_id=absent.id, subject="Fis"),
            models.TeacherSubject(teacher_id=mate.id, subject="Mat"),
            models.TeacherSubject(teacher_id=ita.id, subject="Ita"),
        ])
        s.add(models.Absence(teacher_id=absent.id, date=dt.date(2026, 9, 14)))
        sol = models.Solution(name="t", kind="test", is_active=True, obj_value=0)
        s.add(sol)
        s.flush()
        s.add(models.Lesson(
            solution_id=sol.id, teacher_name="ProfAssente",
            class_name="1A", subject="Mat", day=1, hour=8,
        ))
        s.commit()
    finally:
        s.close()

    r = client.get("/api/coverage/cell?date=2026-09-14&day=1&hour=8")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["uncovered"]
    assert data["uncovered"][0]["subject"] == "Mat"
    assert set(data["uncovered"][0]["original_teacher_subjects"]) == {"Mat", "Fis"}
    by_name = {t["name"]: t for t in data["available"]}
    assert by_name["ProfMate"]["matches_lesson_subject"] is True
    assert by_name["ProfMate"]["matches_absent_subjects"] is True
    assert by_name["ProfIta"]["matches_lesson_subject"] is False
    assert by_name["ProfIta"]["matches_absent_subjects"] is False


def test_disposizione_config_api_and_place(client, app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    from backend import models
    s = SessionLocal()
    try:
        t = models.Teacher(name="ProfD", max_hours=18, disposizione_hours=2)
        s.add(t)
        sol = models.Solution(name="t", kind="test", is_active=True, obj_value=0)
        s.add(sol)
        s.commit()
    finally:
        s.close()

    r = client.get("/api/coverage/disposizione")
    assert r.status_code == 200, r.text
    assert r.json()["eligibility"] == "all"

    r = client.put("/api/coverage/disposizione", json={
        "max_total_hours": 1,
        "eligibility": "all",
        "slot_priorities": [{"day": 6, "hour": 8, "weight": 20}],
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["max_total_hours"] == 1
    assert data["placed_hours"] == 1

    s = SessionLocal()
    try:
        rows = s.query(models.Lesson).filter(
            models.Lesson.class_name == DISPOSIZIONE_CLASS
        ).all()
        assert len(rows) == 1
        assert rows[0].teacher_name == "ProfD"
        assert rows[0].subject == DISPOSIZIONE_SUBJECT
        assert rows[0].classroom_name is None
    finally:
        s.close()
