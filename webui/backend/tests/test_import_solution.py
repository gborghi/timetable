"""Regression coverage for `/api/dataset/import-profile`: importing the
``mega`` demo profile must populate Lessons (so /schedule isn't empty).

What we exercise here:

  1. ``engine_io.solution_dict_from_class_xlsx`` correctly parses the
     committed ``engine/scripts/output/mega/orario_classi_mega.xlsx``
     into a non-empty solution dict.
  2. End-to-end: import school_mega.pkl + profs_mega.pkl + the xlsx
     fallback, then GET /api/lessons returns >0 rows tied to the
     active solution -- the exact contract the calendar UI relies on.

We bypass the threaded run wrapper and call the engine_io helpers
against the test SessionLocal directly. The threading layer is
exercised separately by the live system; here we want a
deterministic, no-network, no-uvicorn assertion that the import
data flow ends with `Lesson` rows visible to /api/lessons.
"""
from __future__ import annotations

import os
import pickle

import pytest

ROOT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."
))
MEGA_DIR = os.path.join(ROOT, "engine", "scripts", "data", "mega")
MEGA_OUT = os.path.join(ROOT, "engine", "scripts", "output", "mega")
SCHOOL_PKL = os.path.join(MEGA_DIR, "school_mega.pkl")
PROFS_PKL = os.path.join(MEGA_DIR, "profs_mega.pkl")
CLASSES_XLSX = os.path.join(MEGA_OUT, "orario_classi_mega.xlsx")


pytestmark = pytest.mark.skipif(
    not (os.path.exists(SCHOOL_PKL)
         and os.path.exists(PROFS_PKL)
         and os.path.exists(CLASSES_XLSX)),
    reason="mega demo artifacts missing (run scripts/rebuild_profiles)",
)


def test_solution_dict_from_class_xlsx_parses_mega():
    """The xlsx parser must return a populated dict shaped like a
    `solution_*.pkl` for the committed mega export."""
    from backend import engine_io
    sol = engine_io.solution_dict_from_class_xlsx(CLASSES_XLSX)
    assert isinstance(sol, dict)
    assert len(sol) > 0, "expected mega xlsx to produce >0 lessons"
    # Spot-check the tuple shape: (teacher, class, subject, day, hour)
    sample_key = next(iter(sol))
    assert len(sample_key) == 5, f"unexpected key shape: {sample_key!r}"
    teacher, klass, subj, day, hour = sample_key
    assert all(isinstance(x, str) for x in (teacher, klass, subj))
    assert isinstance(day, int) and 1 <= day <= 6
    assert isinstance(hour, int) and hour >= 1
    # All values are 1 (presence flag)
    assert set(sol.values()) == {1}
    # mega has 100 classes; at least a few hundred populated cells
    assert len(sol) >= 1000, (
        f"mega solution looks incomplete: only {len(sol)} cells"
    )


def test_import_mega_populates_lessons_endpoint(app_with_temp_db, client):
    """Full import flow: school + profs + xlsx-derived solution end up
    as Lesson rows on the active solution, and /api/lessons surfaces
    them. This is the regression check for "importo mega ma /schedule
    e vuoto"."""
    from backend import engine_io

    _, TestSession = app_with_temp_db

    with open(SCHOOL_PKL, "rb") as f:
        school = pickle.load(f)
    with open(PROFS_PKL, "rb") as f:
        profs = pickle.load(f)

    with TestSession() as db:
        engine_io.import_school_into_db(db, school, replace=True)
    with TestSession() as db:
        n_assignments = engine_io.import_profs_into_db(db, profs)
    assert n_assignments > 0, "profs import yielded no assignments"

    sol = engine_io.solution_dict_from_class_xlsx(CLASSES_XLSX)
    assert sol, "xlsx fallback returned an empty solution"

    with TestSession() as db:
        sid = engine_io.import_solution_into_db(
            db, sol,
            name="Imported mega (orario_classi_mega.xlsx)",
            kind="imported",
            obj_value=0.0,
            metrics={},
            make_active=True,
        )
        assert sid > 0

    # Active solution is what /api/lessons keys off of, so make sure
    # exactly one row carries is_active=True before hitting the API.
    from backend import models
    with TestSession() as db:
        active_count = db.query(models.Solution).filter(
            models.Solution.is_active.is_(True)
        ).count()
        assert active_count == 1

    r = client.get("/api/lessons")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "lessons" in body
    lessons = body["lessons"]
    # The mega xlsx has ~3000 cells across 100 classes; even a partial
    # parse must produce hundreds of rows.
    assert len(lessons) >= 1000, (
        f"/api/lessons returned only {len(lessons)} rows"
    )
    # Sanity-check the row shape the calendar UI consumes.
    first = lessons[0]
    for key in ("id", "solution_id", "teacher_name", "class_name",
                "subject", "day", "hour"):
        assert key in first, f"missing key {key!r} in {first!r}"
    # solution_id of every returned row matches the active sid we
    # just set.
    assert {l["solution_id"] for l in lessons} == {sid}
