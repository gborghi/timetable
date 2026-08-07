"""Pin the new SQLite-snapshot profile import path.

The build script ``webui/backend/scripts/build_profile_db.py`` produces a
self-contained SQLite per profile carrying anagrafica + the 14
constraint tables + WorkingDay/Slot + Lessons. This test imports
``small.sqlite`` into a fresh live DB and verifies every category
arrived: classes, classrooms, plessi, working_days, lessons, the
constraint tables, and the GeneralConstraint DSL fixtures.

The pickle fallback path is left intentionally unexercised here --
it's covered by the existing pickle import smoke tests, and this
file's purpose is to pin the SQLite -> live-DB migration shape.
"""
from __future__ import annotations

import os

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
SQLITE_SMALL = os.path.join(
    PROJECT_ROOT, "engine", "scripts", "data", "small", "small.sqlite")


@pytest.mark.skipif(not os.path.exists(SQLITE_SMALL),
                    reason=f"{SQLITE_SMALL} not built; "
                           f"run `python -m backend.scripts.build_profile_db "
                           f"small` first")
def test_import_small_sqlite_populates_anagrafica_and_constraints(
        app_with_temp_db):
    """Importing small.sqlite into a fresh live DB must populate:

    - anagrafica: subjects, teachers, classes, assignments
    - rooms / plessi: classrooms, plessi, plesso_commuting_rules,
      plesso_entity_policies, classroom_unavailability
    - 14 constraint tables: TeacherUnavailability, MandatoryFreeDay,
      CompatibleClass, ClassPreference, ClassUnavailability,
      ClassroomUnavailability, CoteachGroup, PlessoCommutingRule,
      PlessoEntityPolicy, LogicalUnavailability,
      CurriculumLogicalConstraint, GeneralConstraint
    - WorkingDay + WorkingHourSlot
    - Lessons (the post-Phase-B schedule)
    """
    _app, TestSession = app_with_temp_db
    from webui.backend import engine_io, models

    with TestSession() as db:
        counts = engine_io.import_profile_sqlite_into_db(
            db, SQLITE_SMALL, replace=True)

    # The build script seeds deterministic counts (seed=42); we don't
    # pin exact totals because future builds may grow the fixtures.
    # We only require "non-zero" for every category the manual chapter
    # claims is populated.
    must_have = (
        "subjects", "teachers", "school_classes", "assignments",
        "classrooms", "plessi", "plesso_commuting_rules",
        "plesso_entity_policies", "classroom_unavailability",
        "teacher_unavailability", "teacher_mandatory_free_days",
        "teacher_compatible_classes", "teacher_class_preferences",
        "class_unavailability", "coteach_groups",
        "logical_unavailabilities", "curriculum_logical_constraints",
        "general_constraints", "working_days", "working_hour_slots",
        "lessons",
    )
    for tbl in must_have:
        assert counts.get(tbl, 0) > 0, (
            f"{tbl}: expected >0 rows after sqlite import, "
            f"got counts.get({tbl!r}) = {counts.get(tbl, 0)}")

    # Sanity: the live DB now has the same counts.
    with TestSession() as db:
        n_classes = db.query(models.SchoolClass).count()
        n_classrooms = db.query(models.Classroom).count()
        n_lessons = db.query(models.Lesson).count()
        n_general = db.query(models.GeneralConstraint).count()
        n_working_days = db.query(models.WorkingDay).count()
    assert n_classes >= 5
    assert n_classrooms >= 5
    assert n_lessons > 0
    assert n_general >= 1
    assert n_working_days >= 5


@pytest.mark.skipif(not os.path.exists(SQLITE_SMALL),
                    reason="small.sqlite not built")
def test_import_small_sqlite_subject_required_kind_propagates(
        app_with_temp_db):
    """The build script writes Subject.required_kind for the special
    subjects (Educazione Fisica -> palestra etc.). After import, the
    column must be set on the live DB so engine_io.lessons_for_classroom_step
    can thread it into classroom_assignment."""
    _app, TestSession = app_with_temp_db
    from webui.backend import engine_io, models

    with TestSession() as db:
        engine_io.import_profile_sqlite_into_db(
            db, SQLITE_SMALL, replace=True)
        special = (db.query(models.Subject)
                     .filter(models.Subject.required_kind.is_not(None))
                     .all())
    # build_profile_db sets at least 2 subjects (EduF + Fisica or
    # Chimica or Informatica, depending on which ones are in the
    # pickled subject list). The test file ships a guard that the
    # count is >= 1 -- a stricter "exactly 2" would hard-pin the
    # subject inventory of the small profile and break on legitimate
    # data evolution.
    assert len(special) >= 1
    kinds = {s.required_kind for s in special}
    assert kinds.issubset({
        "palestra", "lab_fisica", "lab_chimica", "lab_informatica",
    })


@pytest.mark.skipif(not os.path.exists(SQLITE_SMALL),
                    reason="small.sqlite not built")
def test_import_small_sqlite_replace_working_hours_false(
        app_with_temp_db):
    """When replace_working_hours=False the live DB's existing
    WorkingDay/Slot rows survive the import (other tables still
    flip). Used by the UI when the user has customised /ore but
    wants to bring in a profile's anagrafica + constraints."""
    _app, TestSession = app_with_temp_db
    from webui.backend import engine_io, models

    # Seed a custom WorkingDay / Slot the test snapshot does NOT have:
    # add a Sunday so we can detect that it survives the import.
    with TestSession() as db:
        sun = models.WorkingDay(
            tenant_id=1, code="SUN", label="Domenica",
            position=6, legacy_day_number=7, is_active=True)
        db.add(sun); db.flush()
        db.add(models.WorkingHourSlot(
            day_id=sun.id, slot_index=0,
            start_time="09:00", end_time="10:00",
            label="custom 1^ ora", legacy_hour_number=9))
        db.commit()

    with TestSession() as db:
        engine_io.import_profile_sqlite_into_db(
            db, SQLITE_SMALL, replace=True,
            replace_working_hours=False)

    with TestSession() as db:
        sundays = (db.query(models.WorkingDay)
                     .filter(models.WorkingDay.code == "SUN")
                     .all())
        assert len(sundays) == 1, (
            "Sunday should survive import when replace_working_hours=False"
        )
