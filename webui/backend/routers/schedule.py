"""Schedule views, drag&drop validation, free-now tool, exports."""
from __future__ import annotations

import io
import json
import os
import pickle
import tempfile
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from .. import models, schemas, engine_io, optimization
from ..db import get_db
from .. import engine_paths  # noqa: F401  (sys.path for engine modules)

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

DAYS = list(range(1, 7))
HOURS = list(range(8, 14))
DAY_NAMES_IT = {1: "Lun", 2: "Mar", 3: "Mer", 4: "Gio", 5: "Ven", 6: "Sab"}


def _active(db: Session) -> models.Solution:
    a = engine_io.get_active_solution(db)
    if a is None:
        raise HTTPException(404, "no active solution; run Phase B first")
    return a


@router.get("/solutions")
def list_solutions(db: Session = Depends(get_db)):
    rows = db.query(models.Solution).order_by(
        models.Solution.created_at.desc()
    ).all()
    return [
        {
            "id": s.id, "name": s.name, "kind": s.kind,
            "obj_value": s.obj_value, "metrics": s.metrics,
            "is_active": s.is_active,
            "created_at": s.created_at.isoformat(),
            "notes": s.notes,
        } for s in rows
    ]


@router.post("/solutions/{sol_id}/activate")
def activate(sol_id: int, db: Session = Depends(get_db)):
    s = db.get(models.Solution, sol_id)
    if s is None:
        raise HTTPException(404, "solution not found")
    engine_io.set_active_solution(db, sol_id)
    return {"ok": True}


@router.delete("/solutions/{sol_id}")
def delete_solution(sol_id: int, db: Session = Depends(get_db)):
    s = db.get(models.Solution, sol_id)
    if s is None:
        raise HTTPException(404, "solution not found")
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.get("/by-class")
def view_by_class(class_name: str | None = None,
                  db: Session = Depends(get_db)):
    """Returns a dict class_name -> day -> hour -> {teacher, subject, room}."""
    a = _active(db)
    q = db.query(models.Lesson).filter(models.Lesson.solution_id == a.id)
    if class_name:
        q = q.filter(models.Lesson.class_name == class_name)
    rows = q.all()
    classes = sorted({l.class_name for l in rows})
    grid: dict[str, dict[int, dict[int, dict | None]]] = {
        c: {d: {h: None for h in HOURS} for d in DAYS} for c in classes
    }
    for l in rows:
        cell = grid[l.class_name][l.day][l.hour]
        # If two lessons share the same slot it's a co-teaching:
        if cell is None:
            grid[l.class_name][l.day][l.hour] = {
                "teachers": [l.teacher_name],
                "subjects": [l.subject],
                "classroom": l.classroom_name,
                "lesson_id": l.id,
            }
        else:
            cell["teachers"].append(l.teacher_name)
            if l.subject not in cell["subjects"]:
                cell["subjects"].append(l.subject)
            if cell.get("classroom") is None:
                cell["classroom"] = l.classroom_name
    return {
        "days": DAYS, "hours": HOURS, "day_names": DAY_NAMES_IT,
        "classes": classes, "grid": grid,
        "obj_value": a.obj_value, "metrics": a.metrics,
    }


@router.get("/by-teacher")
def view_by_teacher(teacher: str | None = None,
                    db: Session = Depends(get_db)):
    a = _active(db)
    q = db.query(models.Lesson).filter(models.Lesson.solution_id == a.id)
    if teacher:
        q = q.filter(models.Lesson.teacher_name == teacher)
    rows = q.all()
    teachers = sorted({l.teacher_name for l in rows})
    grid: dict[str, dict[int, dict[int, dict | None]]] = {
        t: {d: {h: None for h in HOURS} for d in DAYS} for t in teachers
    }
    for l in rows:
        cell = grid[l.teacher_name][l.day][l.hour]
        if cell is None:
            grid[l.teacher_name][l.day][l.hour] = {
                "class_name": l.class_name,
                "subject": l.subject,
                "classroom": l.classroom_name,
                "lesson_id": l.id,
            }
        else:
            cell["class_name"] += "+" + l.class_name
    return {
        "days": DAYS, "hours": HOURS, "day_names": DAY_NAMES_IT,
        "teachers": teachers, "grid": grid,
        "obj_value": a.obj_value, "metrics": a.metrics,
    }


@router.get("/by-slot")
def view_by_slot(day: int = Query(..., ge=1, le=6),
                 hour: int = Query(..., ge=8, le=13),
                 db: Session = Depends(get_db)):
    a = _active(db)
    rows = db.query(models.Lesson).filter(
        models.Lesson.solution_id == a.id,
        models.Lesson.day == day,
        models.Lesson.hour == hour,
    ).all()
    return {
        "day": day, "hour": hour,
        "lessons": [
            {
                "lesson_id": l.id,
                "teacher": l.teacher_name,
                "class_name": l.class_name,
                "subject": l.subject,
                "classroom": l.classroom_name,
            }
            for l in rows
        ],
    }


@router.get("/by-room")
def view_by_room(db: Session = Depends(get_db)):
    """Returns room_name -> day -> hour -> [{class, subject, teacher}, ...]."""
    a = _active(db)
    rooms = {r.name: r for r in db.query(models.Classroom).all()}
    rows = db.query(models.Lesson).filter(
        models.Lesson.solution_id == a.id,
    ).all()
    out: dict[str, dict[int, dict[int, list]]] = {}
    for r in rooms:
        out[r] = {d: {h: [] for h in HOURS} for d in DAYS}
    for l in rows:
        if not l.classroom_name:
            continue
        out.setdefault(l.classroom_name,
                       {d: {h: [] for h in HOURS} for d in DAYS})
        out[l.classroom_name][l.day][l.hour].append({
            "lesson_id": l.id,
            "teacher": l.teacher_name,
            "class_name": l.class_name,
            "subject": l.subject,
        })
    return {
        "days": DAYS, "hours": HOURS, "day_names": DAY_NAMES_IT,
        "rooms": sorted(out.keys()),
        "rooms_meta": {
            r.name: {"kind": r.kind, "capacity": r.capacity,
                     "multi_class": r.multi_class,
                     "multi_class_max": r.multi_class_max}
            for r in db.query(models.Classroom).all()
        },
        "grid": out,
    }


@router.get("/free-now", response_model=schemas.FreeNowOut)
def free_now(day: int = Query(..., ge=1, le=6),
             hour: int = Query(..., ge=8, le=13),
             db: Session = Depends(get_db)):
    a = _active(db)
    busy_teachers: dict[str, dict] = {}
    busy_classes: dict[str, dict] = {}
    rows = db.query(models.Lesson).filter(
        models.Lesson.solution_id == a.id,
        models.Lesson.day == day,
        models.Lesson.hour == hour,
    ).all()
    for l in rows:
        busy_teachers[l.teacher_name] = {
            "name": l.teacher_name,
            "class_name": l.class_name,
            "subject": l.subject,
            "classroom": l.classroom_name,
        }
        busy_classes[l.class_name] = {
            "name": l.class_name,
            "teacher": l.teacher_name,
            "subject": l.subject,
            "classroom": l.classroom_name,
        }
    # Compute weekly load per teacher to surface "still has capacity" info
    teacher_total: dict[str, int] = defaultdict(int)
    teacher_subjects: dict[str, set] = defaultdict(set)
    for l in db.query(models.Lesson).filter(
        models.Lesson.solution_id == a.id
    ).all():
        teacher_total[l.teacher_name] += 1
        teacher_subjects[l.teacher_name].add(l.subject)
    teachers = db.query(models.Teacher).order_by(models.Teacher.name).all()
    classes = db.query(models.SchoolClass).order_by(
        models.SchoolClass.name
    ).all()
    free_t = []
    busy_t = []
    for t in teachers:
        info = {
            "name": t.name, "group": t.group,
            "subjects": [ts.subject for ts in t.subjects],
            "max_hours": t.max_hours,
            "scheduled_hours": teacher_total.get(t.name, 0),
            "covered_subjects": sorted(teacher_subjects.get(t.name, set())),
        }
        if t.name in busy_teachers:
            info.update(busy_teachers[t.name])
            busy_t.append(info)
        else:
            free_t.append(info)
    free_c = []
    busy_c = []
    for c in classes:
        info = {"name": c.name, "year": c.year,
                "curriculum": c.curriculum}
        if c.name in busy_classes:
            info.update(busy_classes[c.name])
            busy_c.append(info)
        else:
            free_c.append(info)
    return schemas.FreeNowOut(
        day=day, hour=hour,
        free_teachers=free_t, busy_teachers=busy_t,
        free_classes=free_c, busy_classes=busy_c,
    )


@router.put("/move-lesson")
def move_lesson(payload: schemas.MoveLessonIn,
                db: Session = Depends(get_db)) -> dict:
    """Drag and drop validation: HARD enforcement + SOFT delta."""
    src = (payload.teacher_name, payload.class_name, payload.subject,
           payload.src_day, payload.src_hour)
    dst = (payload.teacher_name, payload.class_name, payload.subject,
           payload.dst_day, payload.dst_hour)
    out = optimization.validate_and_apply_move(db, src, dst)
    return out


@router.post("/move-preview")
def move_preview(payload: dict, db: Session = Depends(get_db)):
    """Given a lesson_id (or src tuple), simulate the move to ALL 36
    candidate slots in the week (or a subset if `candidate_slots` is set)
    and return per-slot status + delta SOFT. No persistence."""
    lesson_id = payload.get("lesson_id")
    src = None
    active = engine_io.get_active_solution(db)
    if lesson_id is not None and active is not None:
        l = db.get(models.Lesson, int(lesson_id))
        if l is not None:
            src = (l.teacher_name, l.class_name, l.subject, l.day, l.hour)
    if src is None and "src" in payload:
        s = payload["src"]
        src = (s["teacher_name"], s["class_name"], s["subject"],
               int(s["day"]), int(s["hour"]))
    if src is None:
        raise HTTPException(400, "lesson_id o src richiesto")
    cand = payload.get("candidate_slots")
    if cand is not None:
        cand = [(int(c["day"]), int(c["hour"])) for c in cand]
    results = optimization.preview_moves_for_lesson(db, src, cand)
    return {"src": {"teacher_name": src[0], "class_name": src[1],
                    "subject": src[2], "day": src[3], "hour": src[4]},
            "results": results}


@router.put("/lesson/{lesson_id}/classroom")
def set_lesson_classroom(lesson_id: int, classroom_name: str | None = None,
                         db: Session = Depends(get_db)):
    l = db.get(models.Lesson, lesson_id)
    if l is None:
        raise HTTPException(404, "lesson not found")
    # HARD: room must exist (or be None) and not be already used in the same
    # slot beyond multi_class_max
    if classroom_name:
        room = db.query(models.Classroom).filter(
            models.Classroom.name == classroom_name
        ).first()
        if room is None:
            raise HTTPException(404, "classroom not found")
        # Check unavailability
        if any(u.day == l.day and u.hour == l.hour
               for u in room.unavailability):
            raise HTTPException(
                400,
                f"L'aula {classroom_name} non e\` disponibile in "
                f"giorno {l.day} ora {l.hour}"
            )
        # Check concurrent classes
        siblings = db.query(models.Lesson).filter(
            models.Lesson.solution_id == l.solution_id,
            models.Lesson.day == l.day,
            models.Lesson.hour == l.hour,
            models.Lesson.classroom_name == classroom_name,
            models.Lesson.id != lesson_id,
        ).all()
        distinct_classes = {s.class_name for s in siblings} | {l.class_name}
        cap = room.multi_class_max if room.multi_class else 1
        if len(distinct_classes) > cap:
            raise HTTPException(
                400,
                f"Aula {classroom_name} satura: {len(distinct_classes)} "
                f"classi nello stesso slot, max {cap}"
            )
    l.classroom_name = classroom_name
    db.commit()
    return {"ok": True}


# ---------------- Exports ----------------


def _write_pickles(db: Session, tmpdir: str) -> tuple[str, str, str]:
    """Materialize school/profs/solution pickles for the current DB state.
    Returns (school_path, profs_path, solution_path)."""
    school = engine_io.school_dict_from_db(db)
    profs = engine_io.profs_dict_from_db(db)
    a = _active(db)
    sol = engine_io.lessons_to_solution_dict(db, a.id)
    school_p = os.path.join(tmpdir, "school.pkl")
    profs_p = os.path.join(tmpdir, "profs.pkl")
    sol_p = os.path.join(tmpdir, "solution.pkl")
    with open(school_p, "wb") as f:
        pickle.dump(school, f)
    with open(profs_p, "wb") as f:
        pickle.dump(profs, f)
    with open(sol_p, "wb") as f:
        pickle.dump(sol, f)
    return school_p, profs_p, sol_p


@router.get("/export/xlsx-classes")
def export_xlsx_classes(db: Session = Depends(get_db)):
    import exporters  # type: ignore
    tmpdir = tempfile.mkdtemp(prefix="webui_export_")
    school_p, profs_p, sol_p = _write_pickles(db, tmpdir)
    out_path = os.path.join(tmpdir, "orario_classi.xlsx")
    exporters.export_class_schedules_to_xlsx(
        sol_p, school_p, profs_p, out_path
    )
    return FileResponse(
        out_path, filename="orario_classi.xlsx",
        media_type=("application/"
                    "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )


@router.get("/export/xlsx-teachers")
def export_xlsx_teachers(db: Session = Depends(get_db)):
    import exporters  # type: ignore
    tmpdir = tempfile.mkdtemp(prefix="webui_export_")
    school_p, profs_p, sol_p = _write_pickles(db, tmpdir)
    out_path = os.path.join(tmpdir, "orario_docenti.xlsx")
    exporters.export_teacher_schedules_to_xlsx(
        sol_p, school_p, profs_p, out_path
    )
    return FileResponse(
        out_path, filename="orario_docenti.xlsx",
        media_type=("application/"
                    "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )


@router.get("/export/pdf-classes")
def export_pdf_classes(db: Session = Depends(get_db)):
    """Render the per-class grid as a PDF using reportlab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                     Paragraph, Spacer, PageBreak)
    from reportlab.lib.styles import getSampleStyleSheet
    a = _active(db)
    rows = db.query(models.Lesson).filter(
        models.Lesson.solution_id == a.id
    ).all()
    classes = sorted({l.class_name for l in rows})
    by_cl: dict = defaultdict(lambda: defaultdict(dict))
    for l in rows:
        by_cl[l.class_name][l.day][l.hour] = (
            f"{l.subject} / {l.teacher_name}"
            + (f"\n[{l.classroom_name}]" if l.classroom_name else "")
        )
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        topMargin=20, leftMargin=20, rightMargin=20,
    )
    styles = getSampleStyleSheet()
    flow: list = []
    for cn in classes:
        flow.append(Paragraph(f"<b>Classe {cn}</b>", styles["Title"]))
        header = ["Ora"] + [DAY_NAMES_IT[d] for d in DAYS]
        data = [header]
        for h in HOURS:
            row = [f"{h}:00"]
            for d in DAYS:
                row.append(by_cl[cn].get(d, {}).get(h, ""))
            data.append(row)
        t = Table(data, colWidths=[60] + [110] * len(DAYS), repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#D9E1F2")),
        ]))
        flow.append(t)
        flow.append(Spacer(1, 12))
        flow.append(PageBreak())
    if flow and isinstance(flow[-1], PageBreak):
        flow.pop()
    doc.build(flow)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="orario_classi.pdf"'},
    )


@router.get("/export/pdf-teachers")
def export_pdf_teachers(db: Session = Depends(get_db)):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                     Paragraph, Spacer, PageBreak)
    from reportlab.lib.styles import getSampleStyleSheet
    a = _active(db)
    rows = db.query(models.Lesson).filter(
        models.Lesson.solution_id == a.id
    ).all()
    teachers = sorted({l.teacher_name for l in rows})
    by_t: dict = defaultdict(lambda: defaultdict(dict))
    for l in rows:
        by_t[l.teacher_name][l.day][l.hour] = (
            f"{l.class_name}"
            + (f" ({l.subject})" if l.subject else "")
            + (f"\n[{l.classroom_name}]" if l.classroom_name else "")
        )
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        topMargin=20, leftMargin=20, rightMargin=20,
    )
    styles = getSampleStyleSheet()
    flow: list = []
    for tn in teachers:
        flow.append(Paragraph(f"<b>Docente {tn}</b>", styles["Title"]))
        header = ["Ora"] + [DAY_NAMES_IT[d] for d in DAYS]
        data = [header]
        for h in HOURS:
            row = [f"{h}:00"]
            for d in DAYS:
                row.append(by_t[tn].get(d, {}).get(h, ""))
            data.append(row)
        t = Table(data, colWidths=[60] + [110] * len(DAYS), repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#D9E1F2")),
        ]))
        flow.append(t)
        flow.append(Spacer(1, 12))
        flow.append(PageBreak())
    if flow and isinstance(flow[-1], PageBreak):
        flow.pop()
    doc.build(flow)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="orario_docenti.pdf"'},
    )
