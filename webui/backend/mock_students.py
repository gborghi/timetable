"""Deterministic mock-student pool generator.

For each existing SchoolClass we synthesize `n_students` realistic
students using the same Faker library used for fake profs (see
schedule/mock_classes2.py). Birth dates are chosen so a student in year
N is roughly 13+N years old (Italian Liceo: 1st year ~14, 5th year ~19).

Idempotent: if a class already has at least one Student row and
`force=False`, the class is left untouched (avoids accidental
duplication when the user re-imports a profile).

Usage:
    from .mock_students import generate_students_for_db
    n = generate_students_for_db(db, seed=42)
"""
from __future__ import annotations

import datetime as dt
import random
from typing import Any

from sqlalchemy.orm import Session

from . import models


def _faker(seed: int):
    """Lazy Faker import + seeding. Returns a Faker instance pinned to
    Italian locale where available, falling back to default."""
    from faker import Faker
    try:
        fake = Faker("it_IT")
    except Exception:
        fake = Faker()
    Faker.seed(seed)
    random.seed(seed)
    return fake


def _birth_date_for_year(year_of_course: int, fake) -> dt.date:
    """Return a random plausible birth date for a Liceo student in year
    `year_of_course` (1..5). Italian school year starts in September, so
    we approximate using today's year minus (13 + year)."""
    today = dt.date.today()
    age = 13 + max(1, min(int(year_of_course), 5))
    try:
        return fake.date_of_birth(
            minimum_age=age, maximum_age=age + 1
        )
    except Exception:  # pragma: no cover
        # fallback: pick a random day inside the right calendar year
        target_year = today.year - age
        return dt.date(target_year, random.randint(1, 12),
                       random.randint(1, 28))


def _make_email(first: str, last: str, idx: int) -> str:
    """A throwaway @scuola.local email so the field has a value but
    won't clash with anyone real."""
    fn = "".join(c.lower() for c in first if c.isalpha())
    ln = "".join(c.lower() for c in last if c.isalpha())
    return f"{fn}.{ln}{idx:04d}@scuola.local"


def generate_students_for_db(db: Session, *, seed: int = 42,
                             default_per_class: int = 22,
                             force: bool = False) -> dict[str, Any]:
    """Populate the students table with one batch per existing class.

    Returns a small report. By default skips classes that already have
    students; pass `force=True` to wipe-and-regenerate.
    """
    fake = _faker(seed)
    classes = db.query(models.SchoolClass).order_by(
        models.SchoolClass.name).all()
    if not classes:
        return {"ok": False, "reason": "nessuna classe nel DB",
                "n_inserted": 0}
    existing_by_class: dict[int, int] = {}
    for cid, in db.query(
        models.Student.class_id
    ).filter(models.Student.class_id.isnot(None)).all():
        existing_by_class[cid] = existing_by_class.get(cid, 0) + 1

    if force:
        db.query(models.GroupMembership).delete()
        db.query(models.Student).delete()
        db.commit()
        existing_by_class = {}

    last_code = 0
    last_row = db.query(models.Student).order_by(
        models.Student.id.desc()).first()
    if last_row is not None and last_row.student_code \
            and last_row.student_code.startswith("STU"):
        try:
            last_code = int(last_row.student_code[3:])
        except Exception:
            last_code = 0

    n_inserted = 0
    n_skipped_classes = 0
    for cl in classes:
        if existing_by_class.get(cl.id, 0) > 0 and not force:
            n_skipped_classes += 1
            continue
        n = int(cl.n_students or default_per_class)
        for i in range(n):
            last_code += 1
            # Faker.first_name_male / female to keep gender consistent
            gender = random.choice(("M", "F"))
            try:
                first = (fake.first_name_male()
                         if gender == "M" else fake.first_name_female())
            except Exception:
                first = fake.first_name()
            last = fake.last_name()
            bd = _birth_date_for_year(cl.year, fake)
            db.add(models.Student(
                last_name=last,
                first_name=first,
                nickname=f"{last} {first}",
                birth_date=bd,
                gender=gender,
                email=_make_email(first, last, last_code),
                student_code=f"STU{last_code:05d}",
                class_id=cl.id,
            ))
            n_inserted += 1
    db.commit()
    return {
        "ok": True,
        "n_inserted": n_inserted,
        "n_classes_populated": len(classes) - n_skipped_classes,
        "n_classes_skipped": n_skipped_classes,
        "force": force,
    }
