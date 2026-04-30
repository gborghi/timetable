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


def _conflicts_at_slot(
    db: Session,
    active_id: int,
    teacher_name: str | None,
    class_name: str | None,
    classroom_name: str | None,
    day: int,
    hour: int,
    exclude_lesson_id: int | None = None,
) -> dict:
    """Return existing Lessons that conflict with a candidate placement
    at (day, hour). Detects three categories:
      - teacher_busy : same teacher already has a lesson in that slot
      - class_busy   : same class already has a lesson in that slot
      - room_busy    : same classroom already used in that slot
    """
    qry = db.query(models.Lesson).filter(
        models.Lesson.solution_id == active_id,
        models.Lesson.day == int(day),
        models.Lesson.hour == int(hour),
    )
    if exclude_lesson_id is not None:
        qry = qry.filter(models.Lesson.id != int(exclude_lesson_id))
    rows = qry.all()
    teacher_busy: list[models.Lesson] = []
    class_busy: list[models.Lesson] = []
    room_busy: list[models.Lesson] = []
    for r in rows:
        if teacher_name and r.teacher_name == teacher_name:
            teacher_busy.append(r)
        if class_name and r.class_name == class_name:
            class_busy.append(r)
        if (classroom_name and r.classroom_name == classroom_name
                and (classroom_name or "") != ""):
            room_busy.append(r)
    return {
        "teacher_busy": teacher_busy,
        "class_busy": class_busy,
        "room_busy": room_busy,
    }


def _summarise_conflicts(rows: list[models.Lesson]) -> list[dict]:
    return [
        {"lesson_id": r.id, "teacher_name": r.teacher_name,
         "class_name": r.class_name, "subject": r.subject,
         "day": r.day, "hour": r.hour,
         "classroom_name": r.classroom_name}
        for r in rows
    ]


# Backward-compat aliases for the resolution strategy.
_RESOLUTION_ALIASES = {
    "unassign": "delete",
    "optimize": "delete",
}


def _resolve_conflicts(
    db: Session,
    cinfo: dict,
    strategy: str,
) -> None:
    """Apply the chosen conflict resolution to the conflicting Lesson
    rows in `cinfo`. Mutates DB rows in-place; caller commits.

    `strategy` in {'unbind', 'delete'} (after alias normalisation).
    On 'unbind': teacher/class busy -> deleted (no per-attribute
    unbinding possible since the row IS the (teacher, class, day,
    hour) tuple). Room busy -> classroom_name set to NULL.
    On 'delete': all conflicting rows are deleted.
    """
    strategy = _RESOLUTION_ALIASES.get(strategy, strategy)
    deleted: set[int] = set()
    if strategy == "delete":
        for bucket in ("teacher_busy", "class_busy", "room_busy"):
            for r in cinfo[bucket]:
                if r.id in deleted:
                    continue
                deleted.add(r.id)
                db.delete(r)
    else:  # unbind
        # Teacher/class conflicts: must delete (no partial unbind).
        for bucket in ("teacher_busy", "class_busy"):
            for r in cinfo[bucket]:
                if r.id in deleted:
                    continue
                deleted.add(r.id)
                db.delete(r)
        # Room-only conflicts: clear classroom_name.
        for r in cinfo["room_busy"]:
            if r.id in deleted:
                continue
            r.classroom_name = None
    db.flush()


@router.post("/lesson", response_model=schemas.AddLessonOut)
def add_lesson(payload: schemas.AddLessonIn,
               db: Session = Depends(get_db)) -> dict:
    """Create a new Lesson cell at (day, hour) for an existing
    Assignment. Used by the empty-cell "+" buttons on /schedule
    matrix views.

    The (class, teacher, subject) triple MUST already correspond to an
    Assignment; if `subject` is omitted, we look up which Assignments
    link the (class, teacher) pair and pick the only matching subject
    (422 with the candidate list when ambiguous).
    """
    if payload.day not in DAYS or payload.hour not in HOURS:
        raise HTTPException(400, "day/hour fuori range")
    active = _active(db)

    cls = db.query(models.SchoolClass).filter(
        models.SchoolClass.name == payload.class_name).first()
    if cls is None:
        raise HTTPException(404, f"classe {payload.class_name!r} non trovata")
    t = db.query(models.Teacher).filter(
        models.Teacher.name == payload.teacher_name).first()
    if t is None:
        raise HTTPException(
            404, f"docente {payload.teacher_name!r} non trovato"
        )

    # Resolve subject via existing Assignment(s) for (class, teacher).
    candidate_subjects = [
        a.subject for a in db.query(models.Assignment).filter(
            models.Assignment.class_id == cls.id,
            models.Assignment.teacher_id == t.id,
        ).all()
    ]
    subject = payload.subject
    if subject is None:
        if len(candidate_subjects) == 0:
            raise HTTPException(
                422,
                {
                    "detail":
                        f"Nessuna cattedra fra {payload.class_name!r} e "
                        f"{payload.teacher_name!r}: crea prima la cattedra "
                        f"in Cattedre / Phase A.",
                    "code": "no_assignment",
                },
            )
        if len(candidate_subjects) > 1:
            raise HTTPException(
                422,
                {
                    "detail":
                        f"Materie multiple disponibili per "
                        f"({payload.class_name}, {payload.teacher_name}): "
                        f"{candidate_subjects}. Specifica `subject`.",
                    "code": "ambiguous_subject",
                    "candidates": candidate_subjects,
                },
            )
        subject = candidate_subjects[0]
    elif subject not in candidate_subjects:
        raise HTTPException(
            422,
            {
                "detail":
                    f"Cattedra inesistente: {payload.class_name!r}, "
                    f"{payload.teacher_name!r}, {subject!r}. "
                    f"Disponibili: {candidate_subjects}.",
                "code": "no_assignment",
            },
        )

    cinfo = _conflicts_at_slot(
        db, active.id,
        teacher_name=payload.teacher_name,
        class_name=payload.class_name,
        classroom_name=payload.classroom_name,
        day=payload.day,
        hour=payload.hour,
    )
    has_conflict = bool(
        cinfo["teacher_busy"] or cinfo["class_busy"] or cinfo["room_busy"]
    )
    conflict_payload = {
        "teacher_busy": _summarise_conflicts(cinfo["teacher_busy"]),
        "class_busy":   _summarise_conflicts(cinfo["class_busy"]),
        "room_busy":    _summarise_conflicts(cinfo["room_busy"]),
    }

    strategy = _RESOLUTION_ALIASES.get(
        payload.on_conflict, payload.on_conflict
    )

    if has_conflict and strategy in ("dry_run", "cancel"):
        return {
            "ok": False,
            "conflict": True,
            "details": conflict_payload,
        }
    if has_conflict and strategy in ("unbind", "delete"):
        _resolve_conflicts(db, cinfo, strategy)

    lesson = models.Lesson(
        solution_id=active.id,
        teacher_name=payload.teacher_name,
        class_name=payload.class_name,
        subject=subject,
        day=payload.day,
        hour=payload.hour,
        classroom_name=payload.classroom_name or None,
        cotaught_with=(",".join(payload.cotaught_with)
                       if payload.cotaught_with else None),
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return {
        "ok": True,
        "conflict": has_conflict,
        "resolution": strategy if has_conflict else None,
        "lesson_id": lesson.id,
        "details": conflict_payload,
    }


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
