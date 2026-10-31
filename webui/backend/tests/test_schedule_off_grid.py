"""/api/schedule/by-*: una lezione fuori dalla griglia non manda in 500
la pagina Orario (Liceo G3); viene elencata in ``off_grid``."""
from __future__ import annotations


def _seed(SessionLocal):
    from backend import models
    s = SessionLocal()
    try:
        sol = models.Solution(name="t", kind="manual", is_active=True)
        s.add(sol)
        s.flush()
        s.add_all([
            models.Lesson(solution_id=sol.id, teacher_name="TeaA",
                          class_name="1A", subject="Mat", day=1, hour=8,
                          classroom_name="R1"),
            # ora 1: fuori dalla griglia 8..13
            models.Lesson(solution_id=sol.id, teacher_name="TeaA",
                          class_name="1A", subject="Mat", day=1, hour=1,
                          classroom_name="R1"),
        ])
        s.commit()
    finally:
        s.close()


def test_views_skip_and_report_off_grid(client, app_with_temp_db):
    _, SessionLocal = app_with_temp_db
    _seed(SessionLocal)
    r = client.get("/api/schedule/by-class")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["hour"] for x in body["off_grid"]] == [1]
    assert body["grid"]["1A"]["1"]["8"]["subjects"] == ["Mat"]
    r = client.get("/api/schedule/by-teacher")
    assert r.status_code == 200, r.text
    assert len(r.json()["off_grid"]) == 1
    r = client.get("/api/schedule/by-room")
    assert r.status_code in (200, 404), r.text
