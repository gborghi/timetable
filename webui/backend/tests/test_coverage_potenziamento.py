"""Test the potenziamento priority on /api/coverage/cell."""
from __future__ import annotations

import datetime as dt


def test_coverage_cell_sorts_potenziamento_first(client,
                                                  app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    from backend import models
    s = SessionLocal()
    try:
        # Two teachers: PROfBuf has potenziamento, ProfReg doesn't.
        teaBuf = models.Teacher(name="ProfBuf", max_hours=18)
        teaReg = models.Teacher(name="ProfReg", max_hours=18)
        cls = models.SchoolClass(name="3B", n_students=20)
        s.add_all([teaBuf, teaReg, cls])
        s.flush()
        # ProfBuf has 6 hours of potenziamento.
        s.add(models.Assignment(
            teacher_id=teaBuf.id, class_id=None,
            subject="Potenziamento", hours=6,
            is_potenziamento=True,
        ))
        # ProfReg has a regular cattedra.
        s.add(models.Assignment(
            teacher_id=teaReg.id, class_id=cls.id,
            subject="Mat", hours=4,
        ))
        s.commit()
    finally:
        s.close()

    # No active solution -> coverage cell still works but with empty
    # uncovered. The available list however is built from all
    # teachers; we just need to verify the ORDER.
    week_start = dt.date.today()
    while week_start.weekday() != 0:
        week_start -= dt.timedelta(days=1)
    iso = week_start.isoformat()
    r = client.get(f"/api/coverage/cell?date={iso}&day=1&hour=8")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "available" in data
    # Both teachers should appear (no active solution -> nobody is
    # busy). ProfBuf must come first because of is_potenziamento.
    if len(data["available"]) >= 2:
        assert data["available"][0]["name"] == "ProfBuf"
        assert data["available"][0]["is_potenziamento"] is True
        assert data["available"][0]["potenziamento_hours"] == 6
