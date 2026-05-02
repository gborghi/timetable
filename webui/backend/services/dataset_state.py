"""dataset/state aggregation as a pure function on Session.

Used by:
- /api/dataset/state (TTL-cached, see routers/dataset.py)
- (future) cron / background task that emits dataset metrics
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import engine_io, models


def compute_state(db: Session) -> dict:
    """9-COUNT scan + active solution lookup. Cheap individually but
    queried frequently from the layout header."""
    n_classes = db.query(models.SchoolClass).count()
    n_teachers = db.query(models.Teacher).count()
    n_subjects = db.query(models.Subject).count()
    n_assignments = db.query(models.Assignment).count()
    n_rooms = db.query(models.Classroom).count()
    n_solutions = db.query(models.Solution).count()
    n_curricula = db.query(models.Curriculum).count()
    n_students = db.query(models.Student).count()
    n_groups = db.query(models.StudyGroup).count()
    active = engine_io.get_active_solution(db)
    # last imported profile (mock or pickle), used by the Workflow tab
    # to default its run labels to the right name.
    last_profile_row = db.query(models.AppState).filter(
        models.AppState.key == "last_profile"
    ).first()
    last_profile = last_profile_row.value if last_profile_row else None
    return {
        "classes": n_classes,
        "teachers": n_teachers,
        "subjects": n_subjects,
        "assignments": n_assignments,
        "classrooms": n_rooms,
        "solutions": n_solutions,
        "curricula": n_curricula,
        "students": n_students,
        "groups": n_groups,
        "last_profile": last_profile,
        "active_solution": (
            None if active is None else {
                "id": active.id,
                "name": active.name,
                "kind": active.kind,
                "obj_value": active.obj_value,
                "metrics": active.metrics,
            }
        ),
    }
