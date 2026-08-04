"""The "Piazza" greedy placer must not double-book.

`run_place_event` classifies every existing lesson as frozen or
movable, but only ever DELETED the target cattedra's own lessons: a
movable lesson belonging to anybody else was left in the solution and
left out of the occupancy sets, so the placer cheerfully wrote a
second lesson into its cell. `/schedule`'s by-class view renders two
lessons in one (class, day, hour) as co-teaching, so the resulting
double-booked teacher was invisible to the school.

Also pinned here: eviction is a last resort (an empty slot always wins
over displacing somebody), and `Lesson.locked` outranks `lock_mode`.

No CP-SAT anywhere -- the placer is pure greedy, so these stay fast.
"""
from __future__ import annotations

import threading
import time

import pytest


@pytest.fixture(autouse=True)
def _fresh_run_slots():
    """Isolate these tests from a leaked admission slot.

    `run_place_event` runs in a background thread gated by the global
    `run_manager._RUN_SLOTS` semaphore (`BoundedSemaphore(1)` by default).
    A prior test in the full suite that starts a run and does not wait for
    it leaves that single slot held, so the placer here would queue behind
    it and `_wait` would time out -- these tests pass in isolation but flake
    at suite scale. Give each test its own ample, fresh pool and restore the
    original afterwards; the placer is greedy and sub-second, so extra
    nominal capacity is harmless (each test has its own temp DB anyway)."""
    from backend import run_manager
    saved = run_manager._RUN_SLOTS
    run_manager._RUN_SLOTS = threading.BoundedSemaphore(8)
    try:
        yield
    finally:
        run_manager._RUN_SLOTS = saved


def _wait(rid, timeout=30):
    from backend import models, optimization
    for _ in range(timeout * 10):
        with optimization.SessionLocal() as s:
            r = s.get(models.Run, rid)
            if r and r.status in ("done", "failed", "cancelled"):
                return r.status, r.error or ""
        time.sleep(0.1)
    raise AssertionError(f"run {rid} did not finish")


def _seed(*, other_hours=(), pin_target=None, target_hours=2):
    """A two-teacher school: TeaA/1A/Mat is the "Piazza" target,
    TeaB/1A/Ita already occupies `other_hours` of the same class.

    Sharing the class is what makes TeaB movable under
    `same_class_or_teacher_movable` and what makes a collision a real
    double-booking rather than two unrelated lessons.
    """
    from backend import models, optimization

    with optimization.SessionLocal() as s:
        teaA = models.Teacher(name="TeaA")
        teaB = models.Teacher(name="TeaB")
        cls = models.SchoolClass(name="1A", n_students=20)
        s.add_all([teaA, teaB, cls])
        s.flush()

        a = models.Assignment(class_id=cls.id, teacher_id=teaA.id,
                              subject="Mat", hours=target_hours)
        s.add(a)
        sol = models.Solution(name="t", kind="manual", is_active=True)
        s.add(sol)
        s.flush()

        for (d, h) in other_hours:
            s.add(models.Lesson(solution_id=sol.id, teacher_name="TeaB",
                                class_name="1A", subject="Ita",
                                day=d, hour=h))
        if pin_target is not None:
            d, h = pin_target
            s.add(models.Lesson(solution_id=sol.id, teacher_name="TeaA",
                                class_name="1A", subject="Mat",
                                day=d, hour=h, locked=True))
        s.commit()
        return a.id, sol.id


def _lessons(sid):
    from backend import models, optimization
    with optimization.SessionLocal() as s:
        return [(r.teacher_name, r.class_name, r.subject, r.day, r.hour,
                 bool(r.locked))
                for r in s.query(models.Lesson).filter(
                    models.Lesson.solution_id == sid).all()]


def _double_booked(rows):
    """(owner|class, day, hour) cells holding more than one lesson."""
    seen: dict[tuple, int] = {}
    for (t, c, _subj, d, h, _lk) in rows:
        for who in (("T", t, d, h), ("C", c, d, h)):
            seen[who] = seen.get(who, 0) + 1
    return {k: n for k, n in seen.items() if n > 1}


def test_placer_never_double_books_a_movable_lesson(temp_global_session):
    """The whole week is busy except two cells, and every lesson is
    movable. The placer must end up with a conflict-free solution --
    before the fix it wrote its two hours straight on top of TeaB."""
    from backend import optimization

    # Fill hours 8 and 9 of every day for TeaB/1A. Those are exactly the
    # first cells the greedy scan reaches, so the old "take the first
    # slot that isn't frozen" rule landed both target hours on top of
    # TeaB even though 24 cells were free further down the day.
    busy = [(d, h) for d in range(1, 7) for h in (8, 9)]
    aid, sid = _seed(other_hours=busy)

    rid = optimization.run_place_event([aid],
                                       lock_mode="all_others_movable")
    status, err = _wait(rid)
    assert status == "done", err

    rows = _lessons(sid)
    assert _double_booked(rows) == {}, rows
    mat = [r for r in rows if r[2] == "Mat"]
    assert len(mat) == 2, rows


def test_eviction_is_a_last_resort(temp_global_session):
    """A free slot always beats displacing somebody: with the week
    wide open, nothing gets evicted even though everything could be."""
    from backend import optimization

    aid, sid = _seed(other_hours=[(1, 8), (1, 9)])

    rid = optimization.run_place_event([aid],
                                       lock_mode="all_others_movable")
    status, err = _wait(rid)
    assert status == "done", err

    rows = _lessons(sid)
    assert _double_booked(rows) == {}, rows
    # TeaB untouched.
    ita = sorted((r[3], r[4]) for r in rows if r[2] == "Ita")
    assert ita == [(1, 8), (1, 9)], rows


def test_eviction_happens_when_there_is_no_free_slot(temp_global_session):
    """Fully packed week + all_others_movable: the placer now has to
    displace, and the displaced lesson is really gone rather than
    silently sharing the cell."""
    from backend import optimization

    busy = [(d, h) for d in range(1, 7) for h in range(8, 14)]
    aid, sid = _seed(other_hours=busy)

    rid = optimization.run_place_event([aid],
                                       lock_mode="all_others_movable")
    status, err = _wait(rid)
    assert status == "done", err

    rows = _lessons(sid)
    assert _double_booked(rows) == {}, rows
    assert len([r for r in rows if r[2] == "Mat"]) == 2
    # 36 cells, 2 taken over: exactly 2 evictions, no more.
    assert len([r for r in rows if r[2] == "Ita"]) == len(busy) - 2


def test_a_pinned_lesson_is_never_evicted(temp_global_session):
    """`Lesson.locked` outranks lock_mode -- the placer works around a
    pinned lesson instead of deleting it."""
    from backend import models, optimization

    busy = [(d, h) for d in range(1, 7) for h in range(8, 14)]
    aid, sid = _seed(other_hours=busy)
    with optimization.SessionLocal() as s:
        victim = s.query(models.Lesson).filter(
            models.Lesson.day == 1, models.Lesson.hour == 8).one()
        victim.locked = True
        s.commit()

    rid = optimization.run_place_event([aid],
                                       lock_mode="all_others_movable")
    status, err = _wait(rid)
    assert status == "done", err

    rows = _lessons(sid)
    assert _double_booked(rows) == {}, rows
    assert ("TeaB", "1A", "Ita", 1, 8, True) in rows


def test_a_pinned_target_hour_stays_and_counts(temp_global_session):
    """A pin on one of the target's OWN hours means that hour is
    already placed: it survives the wipe and "Piazza" only tops up the
    remaining hour."""
    from backend import optimization

    aid, sid = _seed(pin_target=(3, 11), target_hours=2)

    rid = optimization.run_place_event([aid],
                                       lock_mode="all_others_locked")
    status, err = _wait(rid)
    assert status == "done", err

    rows = _lessons(sid)
    assert _double_booked(rows) == {}, rows
    mat = sorted((r[3], r[4], r[5]) for r in rows if r[2] == "Mat")
    assert len(mat) == 2, rows
    assert (3, 11, True) in mat
