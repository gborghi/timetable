"""Finding 08b: the seven ex-officio HARD class invariants are per-class
toggles on SchoolClass (already editable from the class card + API). This
pins that engine_io exports them so the solver can gate per class, and
that they default True (unchanged behaviour for untouched classes)."""
from backend import engine_io, models


def test_class_flags_default_true(app_with_temp_db):
    _app, Session = app_with_temp_db
    with Session() as db:
        db.add(models.SchoolClass(name="1A"))
        db.commit()
        flags = engine_io.class_flags_from_db(db)
    assert flags["1A"] == {
        "no_holes": True, "entry_at_8": True, "exit_after_12": True,
        "dual_math": True, "dual_italian": True, "motorie_pairs": True,
        "max_6_per_day": True,
    }


def test_class_flags_reflect_overrides(app_with_temp_db):
    _app, Session = app_with_temp_db
    with Session() as db:
        db.add(models.SchoolClass(name="1B", hard_no_holes=False,
                                  hard_motorie_pairs=False))
        db.commit()
        flags = engine_io.class_flags_from_db(db)
    assert flags["1B"]["no_holes"] is False
    assert flags["1B"]["motorie_pairs"] is False
    assert flags["1B"]["entry_at_8"] is True   # untouched stays on


def test_solve_phase_b_for_day_accepts_class_flags():
    """The per-day solver signature accepts class_flags without breaking
    the default (None) path -- the plumbing is wired."""
    import inspect

    import cpsat_v2_timetable as cv2
    sig = inspect.signature(cv2.solve_phase_b_for_day)
    assert "class_flags" in sig.parameters
    assert sig.parameters["class_flags"].default is None
