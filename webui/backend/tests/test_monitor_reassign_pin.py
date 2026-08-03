"""PUT /api/monitor/event/{aid}/lesson/{lid} must treat a per-slot pin
(`Lesson.locked`) exactly like /schedule's drag-and-drop does: ask before
spending it, then land the move UNPINNED.

Before this, /monitor mutated `target.day/hour` in place, so the pin
survived and quietly relocated to a slot the school never chose -- the
same user moving the same lesson got opposite semantics on the two pages.

The boundary that matters: `locked` pins the (day, hour), so only a
RE-TIME needs confirmation. Re-rooming in place leaves the pin alone.
"""
from __future__ import annotations


def _seed(SessionLocal):
    """One pinned lesson + one pinned lesson of the same teacher parked
    at (1, 10) so a re-time onto it produces a teacher conflict whose
    victim is itself pinned."""
    from backend import models

    s = SessionLocal()
    try:
        teaA = models.Teacher(name="TeaA")
        cls1A = models.SchoolClass(name="1A", n_students=25)
        cls1B = models.SchoolClass(name="1B", n_students=25)
        s.add_all([teaA, cls1A, cls1B])
        s.flush()

        s.add_all([
            models.Classroom(name="R1", kind="standard", capacity=30,
                             multi_class=False),
            models.Classroom(name="R2", kind="standard", capacity=30,
                             multi_class=False),
        ])
        a1 = models.Assignment(class_id=cls1A.id, teacher_id=teaA.id,
                               subject="Mat", hours=2, locked=False)
        s.add(a1)
        sol = models.Solution(name="t", kind="manual", is_active=True)
        s.add(sol)
        s.flush()

        pinned = models.Lesson(solution_id=sol.id, teacher_name="TeaA",
                               class_name="1A", subject="Mat",
                               day=1, hour=8, classroom_name="R1",
                               locked=True)
        # Same teacher, elsewhere in the week, also pinned.
        blocker = models.Lesson(solution_id=sol.id, teacher_name="TeaA",
                                class_name="1B", subject="Mat",
                                day=1, hour=10, classroom_name="R2",
                                locked=True)
        s.add_all([pinned, blocker])
        s.flush()
        s.commit()
        return {"asg_id": a1.id, "pinned_id": pinned.id,
                "blocker_id": blocker.id}
    finally:
        s.close()


def _lesson(SessionLocal, lid):
    from backend import models
    s = SessionLocal()
    try:
        return s.get(models.Lesson, lid)
    finally:
        s.close()


def _url(ids):
    return ("/api/monitor/event/" + str(ids["asg_id"])
            + "/lesson/" + str(ids["pinned_id"]))


def test_retiming_a_pinned_lesson_asks_first(client, app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    ids = _seed(SessionLocal)

    r = client.put(_url(ids), json={"day": 2, "hour": 9,
                                    "on_conflict": "dry_run"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is False
    assert out["needs_unlock"] is True
    # Refused, not applied: still pinned, still where it was.
    lot = _lesson(SessionLocal, ids["pinned_id"])
    assert (lot.day, lot.hour, lot.locked) == (1, 8, True)


def test_confirmed_retime_moves_and_unpins(client, app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    ids = _seed(SessionLocal)

    r = client.put(_url(ids), json={"day": 2, "hour": 9, "unlock": True,
                                    "on_conflict": "dry_run"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True
    assert out["unlocked"] is True
    lot = _lesson(SessionLocal, ids["pinned_id"])
    assert (lot.day, lot.hour) == (2, 9)
    # The pin named the OLD slot; it does not follow the lesson.
    assert lot.locked is False


def test_rerooming_in_place_keeps_the_pin(client, app_with_temp_db):
    """`locked` pins the slot, not the room -- so changing only the
    classroom needs no confirmation and must NOT spend the pin."""
    _, SessionLocal = app_with_temp_db
    ids = _seed(SessionLocal)

    r = client.put(_url(ids), json={"classroom_name": "R2",
                                    "on_conflict": "dry_run"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert "needs_unlock" not in out
    assert out["ok"] is True
    assert out["unlocked"] is False
    lot = _lesson(SessionLocal, ids["pinned_id"])
    assert lot.classroom_name == "R2"
    assert (lot.day, lot.hour, lot.locked) == (1, 8, True)


def test_unpinned_lesson_needs_no_confirmation(client, app_with_temp_db):
    """Zero-drift for the ordinary case: nothing to ask, nothing to
    unlock, and `unlocked` stays False so the UI says nothing."""
    _, SessionLocal = app_with_temp_db
    ids = _seed(SessionLocal)
    from backend import models
    s = SessionLocal()
    try:
        s.get(models.Lesson, ids["pinned_id"]).locked = False
        s.commit()
    finally:
        s.close()

    r = client.put(_url(ids), json={"day": 2, "hour": 9,
                                    "on_conflict": "dry_run"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert "needs_unlock" not in out
    assert out["ok"] is True
    assert out["unlocked"] is False
    lot = _lesson(SessionLocal, ids["pinned_id"])
    assert (lot.day, lot.hour, lot.locked) == (2, 9, False)


def test_both_conflict_summarisers_report_the_pin():
    """`ScheduleConflictModal` is shared by /monitor and /schedule, and a
    missing `locked` key is invisible: `r.locked` is merely undefined, so
    the '[bloccata]' marker silently never renders. Keep the two
    summarisers in step so that can't happen unnoticed."""
    from backend import models
    from backend.routers.monitor import _summarise_lessons
    from backend.routers.schedule import _summarise_conflicts

    rows = [models.Lesson(id=1, teacher_name="T", class_name="1A",
                          subject="Mat", day=1, hour=8,
                          classroom_name="R1", locked=True)]
    a = _summarise_lessons(rows)[0]
    b = _summarise_conflicts(rows)[0]
    assert a.keys() == b.keys()
    assert a["locked"] is True and b["locked"] is True


def test_conflict_details_flag_a_pinned_victim(client, app_with_temp_db):
    """Both resolutions destroy the conflicting lesson, so the dry-run
    report has to say when that lesson is itself pinned."""
    _, SessionLocal = app_with_temp_db
    ids = _seed(SessionLocal)

    # (1, 10) holds the pinned blocker of the same teacher.
    r = client.put(_url(ids), json={"day": 1, "hour": 10, "unlock": True,
                                    "on_conflict": "dry_run"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is False and out["conflict"] is True
    busy = out["details"]["teacher_busy"]
    assert [b["lesson_id"] for b in busy] == [ids["blocker_id"]]
    assert busy[0]["locked"] is True
    # Reported only -- nothing was touched.
    assert _lesson(SessionLocal, ids["blocker_id"]) is not None
    lot = _lesson(SessionLocal, ids["pinned_id"])
    assert (lot.day, lot.hour, lot.locked) == (1, 8, True)
