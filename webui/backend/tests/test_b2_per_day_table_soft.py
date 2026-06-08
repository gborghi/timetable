"""B2: table SOFT (soft unavailability, free-day prefs, soft general/logical)
must reach the *per-day* Phase-B pipeline.

Historically ``solve_phase_b_for_day`` loaded its DB DSL stream through
``load_all_dsl_constraints(db, include_soft=False)``, so every SOFT table
row was dropped on the per-day / decomposition paths -- only the
mono-week solver (``include_soft=True``) honored them. Sub-project B2
flips the per-day loader to ``include_soft=True`` AND forwards each rule's
``is_hard`` / ``weight`` to the shared compiler so SOFT rows compile to
weighted ``soft_cost_terms`` (the objective already sums those, from B1).

These tests pin the contract: a SOFT ``TeacherUnavailability`` on an
avoidable per-day slot (a) keeps the solve HARD-feasible and (b) steers
the placement away from the penalized cell.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
WEBUI = os.path.normpath(os.path.join(HERE, "..", ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
for p in (ENGINE, WEBUI, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


def _mem_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.db import Base
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _tiny_day_fixture(n_hours: int):
    """One class 1A, one teacher T1, ``n_hours`` Mat hours on day 1.

    Returns ``(profs, classes, triples, class_profs, dc_value)`` ready
    to feed ``solve_phase_b_for_day``. Mirrors the B1 fixture."""
    import cpsat_v2_timetable as cv2  # type: ignore
    cv2._apply_working_hours_config()
    profs = {
        "T1": {
            "classi": {"1A": {"Mat": {"ore": n_hours}}},
            "glibero": [6, 5, 4],
        },
    }
    classes, triples, class_profs = cv2.build_indices(profs)
    dc_value = {("T1", "1A", "Mat", 1): n_hours}
    return profs, classes, triples, class_profs, dc_value


def test_per_day_soft_unavailability_steers_away_from_penalized_slot():
    """SACRED functional + steering contract.

    Setup: 1A has 5 Mat hours on day 1 with no-holes RELAXED (so a slot
    may be skipped). The only structural HARD floor is presence at h11.
    The *natural* (no-soft) optimum places the 5 hours on
    {8,9,10,11,12}: occupying h13 would cost the sixth-hour penalty
    (weight 5), so the solver avoids h13 and the 5th hour lands on h12.

    A SOFT ``TeacherUnavailability`` on (day1, h12) with weight 100 makes
    that natural slot expensive; with no-holes relaxed the solver can now
    drop h12 and pay the cheaper sixth-hour penalty (5) by using h13
    instead.

    Asserts:
      (a) feasible non-empty placement  [FUNCTIONAL, sacred]
      (b) the penalized (day1, h12) is NOT used  [steering]

    Before B2 (include_soft=False) the soft rule is dropped => the natural
    {8,9,10,11,12} placement is kept => (b) FAILS.
    """
    import cpsat_v2_timetable as cv2  # type: ignore
    from backend import models

    db = _mem_db()
    t = models.Teacher(name="T1", min_free_days=0, max_consecutive=6)
    db.add(t)
    db.commit()
    db.add(models.TeacherUnavailability(
        teacher_id=t.id, day=1, hour=12, state="soft", soft_penalty=100))
    db.commit()

    profs, classes, triples, class_profs, dc_value = _tiny_day_fixture(5)
    out, status = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc_value,
        time_limit=8, workers=2, log=False,
        enforce_no_holes=False,
        via_dsl=True, db=db)

    # (a) FUNCTIONAL: feasible, non-empty placement.
    assert out is not None, status
    placed = {h for (p, cl, s, d, h), v in out.items() if v}
    assert placed, "expected a non-empty placement"
    # The HARD floor: class present at h11.
    assert 11 in placed, placed
    # Exactly 5 hours placed.
    assert len(placed) == 5, placed

    # (b) STEERING: the soft-penalized (day1, h12) must be avoided; the
    # 5th hour lands on h13 (pays sixth=5 < soft=100).
    assert 12 not in placed, (
        f"soft-penalized slot (d1,h12) should be avoided: {sorted(placed)}")


def test_per_day_soft_unavailability_on_only_slot_stays_feasible():
    """A SOFT rule landing on a HARD-required cell must NOT be promoted to
    HARD: the solve stays FEASIBLE and pays the penalty.

    1A has 5 Mat hours; presence at h11 is HARD-required (unconditional,
    even with no-holes relaxed). A SOFT ``TeacherUnavailability`` on
    (day1, h11) cannot be honored without breaking feasibility; a
    correctly-compiled SOFT rule keeps the model feasible (the cell is
    used, the penalty is paid) instead of being promoted to HARD."""
    import cpsat_v2_timetable as cv2  # type: ignore
    from backend import models

    db = _mem_db()
    t = models.Teacher(name="T1", min_free_days=0, max_consecutive=6)
    db.add(t)
    db.commit()
    db.add(models.TeacherUnavailability(
        teacher_id=t.id, day=1, hour=11, state="soft", soft_penalty=1000))
    db.commit()

    profs, classes, triples, class_profs, dc_value = _tiny_day_fixture(5)
    out, status = cv2.solve_phase_b_for_day(
        1, profs, classes, triples, class_profs, dc_value,
        time_limit=8, workers=2, log=False,
        enforce_no_holes=False,
        via_dsl=True, db=db)

    assert out is not None, (
        f"a SOFT rule must not be promoted to HARD; got {status}")
    placed = {h for (p, cl, s, d, h), v in out.items() if v}
    assert 11 in placed, (
        f"HARD-required h11 must stay used despite the soft penalty: "
        f"{sorted(placed)}")
