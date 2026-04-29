"""Absences and substitutions ("Assenze e supplenze").

Given the active timetable solution, the user records per-date absences
and assigns substitute teachers for the uncovered (class, day, hour)
slots. Endpoints:

  GET    /api/coverage/week?week_start=YYYY-MM-DD
         -> per-day, per-(day,hour) summary: counts of absent / uncovered
            / covered / available teachers.

  GET    /api/coverage/cell?date=YYYY-MM-DD&day=D&hour=H
         -> uncovered lessons in that slot + available teachers + which
            substitutes are already assigned.

  GET    /api/absences?date=YYYY-MM-DD
         -> list of absences on that date (ids + teacher info).

  POST   /api/absences  body=AbsenceIn
  DELETE /api/absences/{id}
  DELETE /api/absences?date=YYYY-MM-DD          (clear day)

  POST   /api/substitutions  body=SubstituteIn
  DELETE /api/substitutions/{id}

A teacher is considered AVAILABLE on (date, day, hour) iff:
  - is not absent on that date
  - their declared free_day is not the current day-of-week
  - they have no lesson on that (day, hour) in the active solution
  - they are not already a substitute somewhere else on (date, day, hour)
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models, engine_io
from ..db import get_db

router = APIRouter(tags=["coverage"])


DAY_NAME_TO_INT = {
    "Monday": 1, "Tuesday": 2, "Wednesday": 3,
    "Thursday": 4, "Friday": 5, "Saturday": 6,
    "Lunedi": 1, "Martedi": 2, "Mercoledi": 3,
    "Giovedi": 4, "Venerdi": 5, "Sabato": 6,
    "Lun": 1, "Mar": 2, "Mer": 3, "Gio": 4, "Ven": 5, "Sab": 6,
}


def _date_to_day_of_week(d: dt.date) -> int:
    """ISO weekday 1=Mon .. 7=Sun -> our 1..6 (Sat=6); Sundays clamped to 6."""
    iso = d.isoweekday()
    return min(iso, 6)


def _free_day_int(t: models.Teacher) -> int | None:
    if not t.free_day:
        return None
    return DAY_NAME_TO_INT.get(t.free_day)


# ---------- request/response shapes ----------


class AbsenceIn(BaseModel):
    teacher_id: int
    date: dt.date
    reason: str | None = None
    notes: str | None = None


class AbsenceOut(BaseModel):
    id: int
    teacher_id: int
    teacher_name: str
    teacher_display: str
    date: dt.date
    reason: str | None
    notes: str | None


class SubstituteIn(BaseModel):
    date: dt.date
    day: int
    hour: int
    class_name: str
    subject: str | None = None
    original_teacher_name: str
    substitute_teacher_id: int


class SubstituteOut(BaseModel):
    id: int
    date: dt.date
    day: int
    hour: int
    class_name: str
    subject: str | None
    original_teacher_name: str
    substitute_teacher_id: int | None
    substitute_teacher_name: str | None
    substitute_teacher_display: str | None


class CellSummary(BaseModel):
    day: int
    hour: int
    n_absent_teachers: int = 0
    n_uncovered: int = 0
    n_covered: int = 0
    n_available_teachers: int = 0
    status: str = "ok"  # ok | red | green | mixed


class DaySummary(BaseModel):
    date: dt.date
    day: int
    n_absences: int = 0
    n_uncovered: int = 0
    n_covered: int = 0
    cells: list[CellSummary] = Field(default_factory=list)
    absences: list[AbsenceOut] = Field(default_factory=list)


class WeekCoverageOut(BaseModel):
    week_start: dt.date
    week_end: dt.date
    has_active_solution: bool
    days: list[DaySummary] = Field(default_factory=list)


class UncoveredLesson(BaseModel):
    class_name: str
    subject: str | None
    original_teacher_name: str
    original_teacher_display: str
    substitute_id: int | None = None
    substitute_teacher_id: int | None = None
    substitute_teacher_name: str | None = None
    substitute_teacher_display: str | None = None


class AvailableTeacher(BaseModel):
    id: int
    name: str
    display: str
    group: str | None
    subjects: list[str] = Field(default_factory=list)
    scheduled_hours: int = 0
    max_hours: int = 0


class CoverageCellDetail(BaseModel):
    date: dt.date
    day: int
    hour: int
    uncovered: list[UncoveredLesson] = Field(default_factory=list)
    available: list[AvailableTeacher] = Field(default_factory=list)
    status: str = "ok"


# ---------- helpers ----------


def _teacher_display(t: models.Teacher) -> str:
    if t.nickname:
        return t.nickname
    if t.last_name and t.first_name:
        return f"{t.last_name} {t.first_name}"
    return t.name


def _abs_to_out(a: models.Absence, teacher_by_id: dict[int, models.Teacher]
                ) -> AbsenceOut:
    t = teacher_by_id.get(a.teacher_id)
    return AbsenceOut(
        id=a.id, teacher_id=a.teacher_id,
        teacher_name=t.name if t else f"#{a.teacher_id}",
        teacher_display=_teacher_display(t) if t else f"#{a.teacher_id}",
        date=a.date, reason=a.reason, notes=a.notes,
    )


def _sub_to_out(s: models.SubstituteAssignment,
                teacher_by_id: dict[int, models.Teacher]) -> SubstituteOut:
    t = teacher_by_id.get(s.substitute_teacher_id) if s.substitute_teacher_id \
        else None
    return SubstituteOut(
        id=s.id, date=s.date, day=s.day, hour=s.hour,
        class_name=s.class_name, subject=s.subject,
        original_teacher_name=s.original_teacher_name,
        substitute_teacher_id=s.substitute_teacher_id,
        substitute_teacher_name=t.name if t else None,
        substitute_teacher_display=_teacher_display(t) if t else None,
    )


# ---------- /api/absences ----------


@router.get("/api/absences", response_model=list[AbsenceOut])
def list_absences(date: dt.date | None = Query(None),
                  week_start: dt.date | None = Query(None),
                  db: Session = Depends(get_db)):
    qry = db.query(models.Absence)
    if date is not None:
        qry = qry.filter(models.Absence.date == date)
    elif week_start is not None:
        end = week_start + dt.timedelta(days=6)
        qry = qry.filter(models.Absence.date >= week_start,
                         models.Absence.date <= end)
    rows = qry.order_by(models.Absence.date, models.Absence.id).all()
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    return [_abs_to_out(a, teachers) for a in rows]


@router.post("/api/absences", response_model=AbsenceOut)
def create_absence(payload: AbsenceIn, db: Session = Depends(get_db)):
    if db.get(models.Teacher, payload.teacher_id) is None:
        raise HTTPException(404, "docente inesistente")
    existing = db.query(models.Absence).filter(
        models.Absence.teacher_id == payload.teacher_id,
        models.Absence.date == payload.date,
    ).first()
    if existing is not None:
        raise HTTPException(400, "assenza gia registrata per questo "
                            "docente in questa data")
    a = models.Absence(
        teacher_id=payload.teacher_id, date=payload.date,
        reason=payload.reason, notes=payload.notes,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    return _abs_to_out(a, teachers)


@router.delete("/api/absences/by-id/{aid}")
def delete_absence(aid: int, db: Session = Depends(get_db)):
    a = db.get(models.Absence, aid)
    if a is None:
        raise HTTPException(404, "assenza non trovata")
    # Cascade-clean: remove any substitute assignments tied to the
    # (date, original_teacher_name) tuple, since they no longer apply.
    t = db.get(models.Teacher, a.teacher_id)
    if t is not None:
        db.query(models.SubstituteAssignment).filter(
            models.SubstituteAssignment.date == a.date,
            models.SubstituteAssignment.original_teacher_name == t.name,
        ).delete()
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.delete("/api/absences")
def clear_day_absences(date: dt.date = Query(...),
                       db: Session = Depends(get_db)):
    """Wipe all absences and substitutions for a specific date."""
    n_abs = db.query(models.Absence).filter(
        models.Absence.date == date
    ).delete()
    n_sub = db.query(models.SubstituteAssignment).filter(
        models.SubstituteAssignment.date == date
    ).delete()
    db.commit()
    return {"ok": True, "n_absences_deleted": int(n_abs),
            "n_substitutions_deleted": int(n_sub)}


# ---------- /api/substitutions ----------


@router.post("/api/substitutions", response_model=SubstituteOut)
def create_substitution(payload: SubstituteIn,
                        db: Session = Depends(get_db)):
    sub_t = db.get(models.Teacher, payload.substitute_teacher_id)
    if sub_t is None:
        raise HTTPException(404, "docente supplente inesistente")
    # idempotent: replace existing assignment for same slot
    row = db.query(models.SubstituteAssignment).filter(
        models.SubstituteAssignment.date == payload.date,
        models.SubstituteAssignment.day == payload.day,
        models.SubstituteAssignment.hour == payload.hour,
        models.SubstituteAssignment.class_name == payload.class_name,
    ).first()
    if row is None:
        row = models.SubstituteAssignment(
            date=payload.date, day=payload.day, hour=payload.hour,
            class_name=payload.class_name, subject=payload.subject,
            original_teacher_name=payload.original_teacher_name,
            substitute_teacher_id=payload.substitute_teacher_id,
        )
        db.add(row)
    else:
        row.subject = payload.subject
        row.original_teacher_name = payload.original_teacher_name
        row.substitute_teacher_id = payload.substitute_teacher_id
    db.commit()
    db.refresh(row)
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    return _sub_to_out(row, teachers)


@router.delete("/api/substitutions/{sid}")
def delete_substitution(sid: int, db: Session = Depends(get_db)):
    row = db.get(models.SubstituteAssignment, sid)
    if row is None:
        raise HTTPException(404, "supplenza non trovata")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ---------- /api/coverage ----------


def _compute_coverage_for_date(db: Session, date: dt.date,
                               *, build_cells: bool = True
                               ) -> dict[str, Any]:
    """Returns a dict shape used by both week and cell endpoints."""
    active = engine_io.get_active_solution(db)
    teachers = db.query(models.Teacher).order_by(models.Teacher.name).all()
    teacher_by_id = {t.id: t for t in teachers}
    teacher_by_name = {t.name: t for t in teachers}

    day = _date_to_day_of_week(date)

    # absences for the day
    abs_rows = db.query(models.Absence).filter(
        models.Absence.date == date
    ).all()
    absent_teacher_ids = {a.teacher_id for a in abs_rows}
    absent_teacher_names = {teacher_by_id[a.teacher_id].name
                            for a in abs_rows if a.teacher_id in teacher_by_id}

    # substitutions on this date
    sub_rows = db.query(models.SubstituteAssignment).filter(
        models.SubstituteAssignment.date == date
    ).all()
    sub_by_slot: dict[tuple, models.SubstituteAssignment] = {}
    for s in sub_rows:
        sub_by_slot[(s.day, s.hour, s.class_name)] = s

    # solution lessons: only the day-of-week column we care about
    lessons_in_day: list[models.Lesson] = []
    if active is not None:
        lessons_in_day = db.query(models.Lesson).filter(
            models.Lesson.solution_id == active.id,
            models.Lesson.day == day,
        ).all()

    # busy_teacher_per_slot: who is teaching at (day, hour) in solution
    busy_by_slot: dict[tuple, set[str]] = {}
    for l in lessons_in_day:
        busy_by_slot.setdefault((l.day, l.hour), set()).add(l.teacher_name)

    # uncovered per slot: lessons whose teacher is absent and no substitute
    uncovered_by_slot: dict[tuple, list[models.Lesson]] = {}
    covered_by_slot: dict[tuple, list[models.Lesson]] = {}
    for l in lessons_in_day:
        if l.teacher_name not in absent_teacher_names:
            continue
        key = (l.day, l.hour, l.class_name)
        if sub_by_slot.get(key) is not None:
            covered_by_slot.setdefault((l.day, l.hour), []).append(l)
        else:
            uncovered_by_slot.setdefault((l.day, l.hour), []).append(l)

    # who is acting as substitute (per slot)
    sub_acting_by_slot: dict[tuple, set[int]] = {}
    for s in sub_rows:
        if s.substitute_teacher_id is not None:
            sub_acting_by_slot.setdefault(
                (s.day, s.hour), set()
            ).add(s.substitute_teacher_id)

    cells: list[CellSummary] = []
    if build_cells:
        for hour in range(8, 14):  # 8..13 inclusive (6 ore)
            slot = (day, hour)
            uncov = uncovered_by_slot.get(slot, [])
            cov = covered_by_slot.get(slot, [])
            n_absent = sum(
                1 for tn in (l.teacher_name for l in lessons_in_day
                             if l.hour == hour)
                if tn in absent_teacher_names
            )
            available = _available_teachers(
                teachers, day, hour, absent_teacher_ids,
                busy_by_slot.get(slot, set()),
                sub_acting_by_slot.get(slot, set()),
                teacher_by_name,
            )
            if uncov:
                status = "red"
            elif cov:
                status = "green"
            elif n_absent:
                status = "mixed"
            else:
                status = "ok"
            cells.append(CellSummary(
                day=day, hour=hour,
                n_absent_teachers=n_absent,
                n_uncovered=len(uncov),
                n_covered=len(cov),
                n_available_teachers=len(available),
                status=status,
            ))

    return {
        "date": date,
        "day": day,
        "active": active,
        "teachers": teachers,
        "teacher_by_id": teacher_by_id,
        "teacher_by_name": teacher_by_name,
        "absences": abs_rows,
        "absent_teacher_ids": absent_teacher_ids,
        "absent_teacher_names": absent_teacher_names,
        "subs_by_slot": sub_by_slot,
        "sub_rows": sub_rows,
        "sub_acting_by_slot": sub_acting_by_slot,
        "lessons_in_day": lessons_in_day,
        "uncovered_by_slot": uncovered_by_slot,
        "covered_by_slot": covered_by_slot,
        "busy_by_slot": busy_by_slot,
        "cells": cells,
    }


def _available_teachers(teachers: list[models.Teacher],
                        day: int, hour: int,
                        absent_teacher_ids: set[int],
                        busy_names: set[str],
                        sub_acting_ids: set[int],
                        teacher_by_name: dict[str, models.Teacher]
                        ) -> list[models.Teacher]:
    out = []
    for t in teachers:
        if t.id in absent_teacher_ids:
            continue
        if t.id in sub_acting_ids:
            continue
        if t.name in busy_names:
            continue
        free_d = _free_day_int(t)
        if free_d is not None and free_d == day:
            continue
        out.append(t)
    return out


@router.get("/api/coverage/week", response_model=WeekCoverageOut)
def coverage_week(week_start: dt.date = Query(...),
                  db: Session = Depends(get_db)):
    active = engine_io.get_active_solution(db)
    out = WeekCoverageOut(
        week_start=week_start,
        week_end=week_start + dt.timedelta(days=5),
        has_active_solution=active is not None,
    )
    teachers_by_id = {t.id: t for t in db.query(models.Teacher).all()}
    for offset in range(6):  # Mon..Sat
        d = week_start + dt.timedelta(days=offset)
        info = _compute_coverage_for_date(db, d, build_cells=True)
        n_uncov = sum(c.n_uncovered for c in info["cells"])
        n_cov = sum(c.n_covered for c in info["cells"])
        out.days.append(DaySummary(
            date=d,
            day=info["day"],
            n_absences=len(info["absences"]),
            n_uncovered=n_uncov,
            n_covered=n_cov,
            cells=info["cells"],
            absences=[_abs_to_out(a, teachers_by_id)
                      for a in info["absences"]],
        ))
    return out


@router.get("/api/coverage/cell", response_model=CoverageCellDetail)
def coverage_cell(date: dt.date = Query(...),
                  day: int = Query(..., ge=1, le=6),
                  hour: int = Query(..., ge=8, le=13),
                  db: Session = Depends(get_db)):
    info = _compute_coverage_for_date(db, date, build_cells=False)
    if info["day"] != day:
        # The user explicitly asked for a (date, day) pair where the day
        # does not match the date's day-of-week. We still answer using the
        # provided day so the UI can navigate sandbox-style if needed.
        pass
    teacher_by_id = info["teacher_by_id"]
    teacher_by_name = info["teacher_by_name"]
    slot = (day, hour)
    uncov_lessons = info["uncovered_by_slot"].get(slot, []) \
        + info["covered_by_slot"].get(slot, [])
    out = CoverageCellDetail(date=date, day=day, hour=hour)
    for l in uncov_lessons:
        sub = info["subs_by_slot"].get((day, hour, l.class_name))
        sub_t = (teacher_by_id.get(sub.substitute_teacher_id)
                 if sub and sub.substitute_teacher_id else None)
        orig = teacher_by_name.get(l.teacher_name)
        out.uncovered.append(UncoveredLesson(
            class_name=l.class_name,
            subject=l.subject,
            original_teacher_name=l.teacher_name,
            original_teacher_display=(_teacher_display(orig)
                                      if orig else l.teacher_name),
            substitute_id=sub.id if sub else None,
            substitute_teacher_id=(sub.substitute_teacher_id
                                   if sub else None),
            substitute_teacher_name=(sub_t.name if sub_t else None),
            substitute_teacher_display=(_teacher_display(sub_t)
                                        if sub_t else None),
        ))
    # available teachers
    teacher_total: dict[str, int] = {}
    if info["active"] is not None:
        for l in db.query(models.Lesson).filter(
            models.Lesson.solution_id == info["active"].id
        ).all():
            teacher_total[l.teacher_name] = teacher_total.get(
                l.teacher_name, 0
            ) + 1
    avail = _available_teachers(
        info["teachers"], day, hour, info["absent_teacher_ids"],
        info["busy_by_slot"].get(slot, set()),
        info["sub_acting_by_slot"].get(slot, set()),
        teacher_by_name,
    )
    for t in avail:
        out.available.append(AvailableTeacher(
            id=t.id, name=t.name,
            display=_teacher_display(t),
            group=t.group,
            subjects=[ts.subject for ts in t.subjects],
            scheduled_hours=teacher_total.get(t.name, 0),
            max_hours=t.max_hours,
        ))
    # status
    if any(u.substitute_teacher_id is None for u in out.uncovered):
        out.status = "red"
    elif out.uncovered:
        out.status = "green"
    else:
        out.status = "ok"
    return out
