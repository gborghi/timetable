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
from ..disposizione import (
    apply_disposizione_to_active,
    config_to_out,
    get_or_create_config,
    is_disposizione_lesson,
)
from .. import schemas
from ..tenant import current_tenant_id

router = APIRouter(tags=["coverage"])

try:
    from working_hours_config import get_days as _get_days
    from working_hours_config import get_hours as _get_hours
    from working_hours_config import get_day_labels as _get_day_labels
    from working_hours_config import DEFAULT_DAYS, DEFAULT_HOURS
except ImportError:
    DEFAULT_DAYS = [1, 2, 3, 4, 5, 6]
    DEFAULT_HOURS = [8, 9, 10, 11, 12, 13]
    def _get_days():
        return list(DEFAULT_DAYS)
    def _get_hours():
        return list(DEFAULT_HOURS)
    def _get_day_labels():
        return {1: "Lun", 2: "Mar", 3: "Mer", 4: "Gio", 5: "Ven", 6: "Sab"}


def _configured_days(db: Session | None = None) -> list[int]:
    """Active day IDs in display order.

    Prefer the request session (same DB the API just mutated). Fall
    back to the engine loader, then to the lun–sab preset.
    """
    if db is not None:
        try:
            rows = (
                db.query(models.WorkingDay)
                .filter(models.WorkingDay.is_active.is_(True))
                .order_by(models.WorkingDay.position)
                .all()
            )
            ids = [int(r.legacy_day_number) for r in rows
                   if r.legacy_day_number is not None]
            if ids:
                return ids
        except Exception:
            pass
    return list(_get_days()) or list(DEFAULT_DAYS)


def _configured_hours(db: Session | None = None) -> list[int]:
    if db is not None:
        try:
            days = (
                db.query(models.WorkingDay)
                .filter(models.WorkingDay.is_active.is_(True))
                .order_by(models.WorkingDay.position)
                .all()
            )
            for d in days:
                hours = [
                    int(s.legacy_hour_number) for s in (d.slots or [])
                    if s.legacy_hour_number is not None
                ]
                if hours:
                    return hours
        except Exception:
            pass
    return list(_get_hours()) or list(DEFAULT_HOURS)


DAY_NAME_TO_INT = {
    "Monday": 1, "Tuesday": 2, "Wednesday": 3,
    "Thursday": 4, "Friday": 5, "Saturday": 6,
    "Lunedi": 1, "Martedi": 2, "Mercoledi": 3,
    "Giovedi": 4, "Venerdi": 5, "Sabato": 6,
    "Lun": 1, "Mar": 2, "Mer": 3, "Gio": 4, "Ven": 5, "Sab": 6,
}


def _date_to_day_of_week(d: dt.date) -> int:
    """Map a civil date onto a configured day ID.

    Default lun–sab calendars keep the historical ISO weekday mapping
    (Mon=1 … Sat=6, Sunday clamped to Saturday). Custom calendars
    (animal names, 10-day cycles, …) are a flat list of IDs: the
    date is projected onto that list by weekday index, wrapping if
    the calendar is shorter than six days and clamping if longer.
    """
    days = _configured_days()
    if not days:
        return 1
    iso = d.isoweekday()  # 1=Mon .. 7=Sun
    idx = min(iso, 6) - 1
    if idx < 0:
        idx = 0
    if idx >= len(days):
        idx = len(days) - 1
    return int(days[idx])


def _free_day_int(t: models.Teacher, db: Session | None = None) -> int | None:
    if not t.free_day:
        return None
    try:
        from ..engine_io import resolve_free_day
        found = resolve_free_day(t.free_day, db)
        if found is not None:
            return found
    except Exception:
        pass
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
    n_disposizione_teachers: int = 0
    n_hole_teachers: int = 0
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
    original_teacher_subjects: list[str] = Field(default_factory=list)
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
    is_potenziamento: bool = False
    potenziamento_hours: int = 0
    is_disposizione: bool = False
    is_hole: bool = False
    kind: str = "free"  # disposizione | hole | free
    matches_lesson_subject: bool = False
    matches_absent_subjects: bool = False


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
                               *, build_cells: bool = True,
                               day: int | None = None
                               ) -> dict[str, Any]:
    """Returns a dict shape used by both week and cell endpoints."""
    active = engine_io.get_active_solution(db)
    teachers = db.query(models.Teacher).order_by(models.Teacher.name).all()
    teacher_by_id = {t.id: t for t in teachers}
    teacher_by_name = {t.name: t for t in teachers}

    if day is None:
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

    # busy_teacher_per_slot: who is teaching at (day, hour) in solution.
    # Disposizione standby is NOT busy: those teachers stay available
    # for substitutions (that is the point of the hour).
    busy_by_slot: dict[tuple, set[str]] = {}
    disp_by_slot: dict[tuple, set[str]] = {}
    teaching_hours: dict[str, set[int]] = {}
    for l in lessons_in_day:
        if is_disposizione_lesson(l.class_name, l.subject):
            disp_by_slot.setdefault((l.day, l.hour), set()).add(l.teacher_name)
            continue
        busy_by_slot.setdefault((l.day, l.hour), set()).add(l.teacher_name)
        teaching_hours.setdefault(l.teacher_name, set()).add(l.hour)

    # uncovered per slot: lessons whose teacher is absent and no substitute
    uncovered_by_slot: dict[tuple, list[models.Lesson]] = {}
    covered_by_slot: dict[tuple, list[models.Lesson]] = {}
    for l in lessons_in_day:
        if is_disposizione_lesson(l.class_name, l.subject):
            continue
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
        for hour in _configured_hours(db):
            slot = (day, hour)
            uncov = uncovered_by_slot.get(slot, [])
            cov = covered_by_slot.get(slot, [])
            n_absent = sum(
                1 for l in lessons_in_day
                if l.hour == hour
                and l.teacher_name in absent_teacher_names
                and not is_disposizione_lesson(l.class_name, l.subject)
            )
            available = _available_teachers(
                teachers, day, hour, absent_teacher_ids,
                busy_by_slot.get(slot, set()),
                sub_acting_by_slot.get(slot, set()),
                teacher_by_name, db,
            )
            avail_names = {t.name for t in available}
            n_disp = len(disp_by_slot.get(slot, set()) & avail_names)
            n_hole = sum(
                1 for t in available
                if _is_hole_hour(teaching_hours.get(t.name, set()), hour)
                and t.name not in disp_by_slot.get(slot, set())
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
                n_disposizione_teachers=n_disp,
                n_hole_teachers=n_hole,
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
        "disp_by_slot": disp_by_slot,
        "teaching_hours": teaching_hours,
        "cells": cells,
    }


def _is_hole_hour(hours: set[int], hour: int) -> bool:
    """True when ``hour`` sits in a gap between the teacher's first
    and last real lesson of the day (not itself a lesson)."""
    if not hours or hour in hours:
        return False
    return min(hours) < hour < max(hours)


def _available_teachers(teachers: list[models.Teacher],
                        day: int, hour: int,
                        absent_teacher_ids: set[int],
                        busy_names: set[str],
                        sub_acting_ids: set[int],
                        teacher_by_name: dict[str, models.Teacher],
                        db: Session | None = None,
                        ) -> list[models.Teacher]:
    out = []
    for t in teachers:
        if t.id in absent_teacher_ids:
            continue
        if t.id in sub_acting_ids:
            continue
        if t.name in busy_names:
            continue
        free_d = _free_day_int(t, db)
        if free_d is not None and free_d == day:
            continue
        out.append(t)
    return out


@router.get("/api/coverage/week", response_model=WeekCoverageOut)
def coverage_week(week_start: dt.date = Query(...),
                  db: Session = Depends(get_db)):
    active = engine_io.get_active_solution(db)
    day_ids = _configured_days(db)
    n_days = max(len(day_ids), 1)
    out = WeekCoverageOut(
        week_start=week_start,
        week_end=week_start + dt.timedelta(days=n_days - 1),
        has_active_solution=active is not None,
    )
    teachers_by_id = {t.id: t for t in db.query(models.Teacher).all()}
    for offset, day_id in enumerate(day_ids):
        d = week_start + dt.timedelta(days=offset)
        info = _compute_coverage_for_date(
            db, d, build_cells=True, day=int(day_id),
        )
        info_day = int(day_id)
        n_uncov = sum(c.n_uncovered for c in info["cells"])
        n_cov = sum(c.n_covered for c in info["cells"])
        cells = list(info["cells"])
        out.days.append(DaySummary(
            date=d,
            day=info_day,
            n_absences=len(info["absences"]),
            n_uncovered=n_uncov,
            n_covered=n_cov,
            cells=cells,
            absences=[_abs_to_out(a, teachers_by_id)
                      for a in info["absences"]],
        ))
    return out


@router.get("/api/coverage/cell", response_model=CoverageCellDetail)
def coverage_cell(date: dt.date = Query(...),
                  day: int = Query(..., ge=1, le=400),
                  hour: int = Query(..., ge=0, le=23),
                  db: Session = Depends(get_db)):
    info = _compute_coverage_for_date(
        db, date, build_cells=False, day=day,
    )
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
            original_teacher_subjects=([ts.subject for ts in orig.subjects]
                                       if orig else []),
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
            if is_disposizione_lesson(l.class_name, l.subject):
                continue
            teacher_total[l.teacher_name] = teacher_total.get(
                l.teacher_name, 0
            ) + 1
    avail = _available_teachers(
        info["teachers"], day, hour, info["absent_teacher_ids"],
        info["busy_by_slot"].get(slot, set()),
        info["sub_acting_by_slot"].get(slot, set()),
        teacher_by_name, db,
    )
    # Potenziamento (Legge 107) priority: teachers with at least
    # one is_potenziamento Assignment are buffer profs available
    # for substitutions. Surface their pot hours and put them
    # first in the list.
    pot_hours_by_teacher: dict[int, int] = {}
    for a in db.query(models.Assignment).filter(
        models.Assignment.is_potenziamento == True  # noqa: E712
    ).all():
        pot_hours_by_teacher[a.teacher_id] = (
            pot_hours_by_teacher.get(a.teacher_id, 0)
            + int(a.hours or 0))
    disp_names = info.get("disp_by_slot", {}).get(slot, set())
    teaching_hours = info.get("teaching_hours", {})
    lesson_subjects = {
        (u.subject or "").strip()
        for u in out.uncovered if (u.subject or "").strip()
    }
    absent_subjects: set[str] = set()
    for u in out.uncovered:
        absent_subjects.update(u.original_teacher_subjects or [])
    avail_entries = []
    for t in avail:
        is_disp = t.name in disp_names
        is_hole = (not is_disp) and _is_hole_hour(
            teaching_hours.get(t.name, set()), hour)
        if is_disp:
            kind = "disposizione"
        elif is_hole:
            kind = "hole"
        else:
            kind = "free"
        t_subjects = [ts.subject for ts in t.subjects]
        t_subj_set = {s for s in t_subjects if s}
        avail_entries.append(AvailableTeacher(
            id=t.id, name=t.name,
            display=_teacher_display(t),
            group=t.group,
            subjects=t_subjects,
            scheduled_hours=teacher_total.get(t.name, 0),
            max_hours=t.max_hours,
            is_potenziamento=t.id in pot_hours_by_teacher,
            potenziamento_hours=pot_hours_by_teacher.get(t.id, 0),
            is_disposizione=is_disp,
            is_hole=is_hole,
            kind=kind,
            matches_lesson_subject=bool(t_subj_set & lesson_subjects),
            matches_absent_subjects=bool(t_subj_set & absent_subjects),
        ))
    # Sort: official disposizione first, then hole hours (covering
    # then is less annoying), then potenziamento, then lighter load.
    avail_entries.sort(
        key=lambda e: (
            0 if e.is_disposizione else 1,
            0 if e.is_hole else 1,
            0 if e.is_potenziamento else 1,
            -e.potenziamento_hours,
            e.scheduled_hours,
        ))
    out.available = avail_entries
    # status
    if any(u.substitute_teacher_id is None for u in out.uncovered):
        out.status = "red"
    elif out.uncovered:
        out.status = "green"
    else:
        out.status = "ok"
    return out


# ---------- disposizione (standby hours) ----------


@router.get("/api/coverage/disposizione",
            response_model=schemas.DisposizioneConfigOut)
def get_disposizione_config(db: Session = Depends(get_db),
                            tenant_id: int = Depends(current_tenant_id)):
    row = get_or_create_config(db, tenant_id)
    placed = 0
    active = engine_io.get_active_solution(db)
    if active is not None:
        placed = db.query(models.Lesson).filter(
            models.Lesson.solution_id == active.id,
            models.Lesson.class_name == "__disposizione__",
        ).count()
    return config_to_out(row, placed_hours=placed)


@router.put("/api/coverage/disposizione",
            response_model=schemas.DisposizioneConfigOut)
def put_disposizione_config(payload: schemas.DisposizioneConfigIn,
                            db: Session = Depends(get_db),
                            tenant_id: int = Depends(current_tenant_id)):
    import json as _json
    row = get_or_create_config(db, tenant_id)
    row.max_total_hours = payload.max_total_hours
    row.eligibility = payload.eligibility
    if payload.slot_priorities:
        row.slot_priorities_json = _json.dumps([
            {"day": p.day, "hour": p.hour, "weight": p.weight}
            for p in payload.slot_priorities
        ])
    else:
        row.slot_priorities_json = None
    db.commit()
    db.refresh(row)
    stats = apply_disposizione_to_active(db)
    return config_to_out(row, placed_hours=int(stats.get("placed_hours", 0)))


@router.post("/api/coverage/disposizione/place")
def place_disposizione_now(db: Session = Depends(get_db)):
    """Re-place disposizione hours on the active solution.

    Used after changing per-teacher quotas, or to restore the
    optimizer placement after a manual move.
    """
    return apply_disposizione_to_active(db)
