"""Conversion between the DB model (rich constraints) and the engine
pickles (slim structures consumed by experiments/*.py).

The engine works on three pickle shapes:

    school = {
        'profile':   str,
        'classes':   [{name, year, section, curriculum, subjects: {subj: ore}}],
        'teachers':  [{name, group, max_hours, free_day, weights: {subj:int}}],
        'cconcorsopersubject': {subj: {group: weight}},
        'curriculum_scores':   {curriculum: int}
    }
    profs = {
        teacher_name: {
            'classi':  {class_name: {subject: {'ore': N}}},
            'glibero': [d1, d2, d3]
        }
    }
    solution = {(prof, class, subj, day, hour): 0|1}

This module hides those details from the rest of the backend.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pickle
import random
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from . import models

DAY_MAP = {
    "Monday": 1, "Tuesday": 2, "Wednesday": 3,
    "Thursday": 4, "Friday": 5, "Saturday": 6,
    # Italian aliases (mock generator emits English; users can pick Italian)
    "Lunedi": 1, "Lunedi'": 1, "Martedi": 2, "Martedi'": 2,
    "Mercoledi": 3, "Mercoledi'": 3, "Giovedi": 4, "Giovedi'": 4,
    "Venerdi": 5, "Venerdi'": 5, "Sabato": 6,
}
DAY_NAME_IT = {1: "Lun", 2: "Mar", 3: "Mer", 4: "Gio", 5: "Ven", 6: "Sab"}


# ---------- DB -> pickles ----------


def school_dict_from_db(db: Session) -> dict[str, Any]:
    """Build the dict that big_mock_school.py would serialize as
    school_<profile>.pkl."""
    # Build a code -> Curriculum map so we can fall back to the indirizzo
    # monte-ore when a class has no per-class subject overrides yet.
    curr_by_id = {c.id: c for c in db.query(models.Curriculum).all()}
    curr_by_code = {c.code: c for c in curr_by_id.values()}
    curr_hours: dict[int, dict[int, dict[str, int]]] = {}
    for h in db.query(models.CurriculumSubjectHours).all():
        curr_hours.setdefault(h.curriculum_id, {})\
            .setdefault(h.year, {})[h.subject] = h.hours_per_week

    classes_dump = []
    for cl in db.query(models.SchoolClass).order_by(models.SchoolClass.name).all():
        # subjects: use per-class rows when present; otherwise fall back to
        # the curriculum monte-ore for the relevant year
        subjects = {s.subject: s.hours_per_week for s in cl.subjects}
        if not subjects and cl.curriculum_id and cl.curriculum_id in curr_hours:
            subjects = dict(curr_hours[cl.curriculum_id].get(cl.year, {}))
        curr_code = None
        if cl.curriculum_id and cl.curriculum_id in curr_by_id:
            curr_code = curr_by_id[cl.curriculum_id].code
        elif cl.curriculum:
            curr_code = cl.curriculum
        classes_dump.append({
            "name": cl.name,
            "year": cl.year,
            "section": cl.section,
            "curriculum": curr_code,
            "subjects": subjects,
        })
    teachers_dump = []
    for t in db.query(models.Teacher).order_by(models.Teacher.name).all():
        teachers_dump.append({
            "name": t.name,
            "group": t.group or "",
            "max_hours": t.max_hours,
            "free_day": t.free_day or "Saturday",
            "weights": {ts.subject: 1 for ts in t.subjects},
            "graduatoria_score": t.graduatoria_score,
        })
    cconc = defaultdict(dict)
    for row in db.query(models.SubjectGroupWeight).all():
        cconc[row.subject][row.group_name] = row.weight
    # curriculum_scores: prefer the score column from curricula, fall back
    # to first-segment of legacy `curriculum` string for unmapped classes.
    curriculum_scores: dict[str, int] = {}
    for c in curr_by_id.values():
        curriculum_scores[c.code] = int(c.score or 1)
    for cl in db.query(models.SchoolClass).all():
        if cl.curriculum and cl.curriculum.split("_")[0] not in curriculum_scores:
            curriculum_scores[cl.curriculum.split("_")[0]] = 1
    # curricula: full grid + score, included so the engine can know about
    # indirizzi without having to re-derive them from class names.
    curricula_dump = []
    for c in curr_by_id.values():
        curricula_dump.append({
            "code": c.code,
            "name": c.name,
            "score": int(c.score or 1),
            "hours": {y: dict(ss) for y, ss in
                      curr_hours.get(c.id, {}).items()},
        })
    # students + study groups (not strictly needed by the solver yet, but
    # piped through so future engine versions can see them in one shot)
    students_dump = []
    classes_by_id = {cl.id: cl for cl in
                     db.query(models.SchoolClass).all()}
    for st in db.query(models.Student).order_by(
            models.Student.last_name, models.Student.first_name).all():
        students_dump.append({
            "id": st.id,
            "last_name": st.last_name,
            "first_name": st.first_name,
            "class_name": (classes_by_id[st.class_id].name
                           if st.class_id and st.class_id in classes_by_id
                           else None),
            "student_code": st.student_code,
        })
    groups_dump = []
    for g in db.query(models.StudyGroup).order_by(models.StudyGroup.name).all():
        member_ids = [m.student_id for m in g.members]
        groups_dump.append({
            "name": g.name,
            "kind": g.kind,
            "student_ids": member_ids,
            "subjects": {h.subject: h.hours_per_week
                         for h in g.subject_hours},
        })
    return {
        "profile": "webui",
        "classes": classes_dump,
        "teachers": teachers_dump,
        "cconcorsopersubject": dict(cconc),
        "curriculum_scores": curriculum_scores,
        "curricula": curricula_dump,
        "students": students_dump,
        "groups": groups_dump,
    }


def profs_dict_from_db(db: Session) -> dict[str, Any]:
    """Build profs_<profile>.pkl content from the active assignments."""
    rng = random.Random(123)
    days = list(range(1, 7))
    # Use teacher.free_day for the primary free day
    out: dict[str, Any] = {}
    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    classes = {c.id: c for c in db.query(models.SchoolClass).all()}
    for a in db.query(models.Assignment).all():
        t = teachers.get(a.teacher_id)
        cl = classes.get(a.class_id)
        if t is None or cl is None:
            continue
        node = out.setdefault(t.name, {"classi": {}, "glibero": []})
        node["classi"].setdefault(cl.name, {})[a.subject] = {"ore": a.hours}
    # glibero
    for tname, info in out.items():
        t = next((x for x in teachers.values() if x.name == tname), None)
        if t is None:
            continue
        primary = DAY_MAP.get(t.free_day or "Saturday", 6)
        rest = [d for d in days if d != primary]
        rng.shuffle(rest)
        info["glibero"] = [primary, rest[0], rest[1]]
    return out


def cattedre_from_assignments(db: Session) -> dict[str, dict[str, dict[str, int]]]:
    """teacher_name -> {class_name -> {subject -> ore}}"""
    out: dict[str, dict[str, dict[str, int]]] = {}
    teachers = {t.id: t.name for t in db.query(models.Teacher).all()}
    classes = {c.id: c.name for c in db.query(models.SchoolClass).all()}
    for a in db.query(models.Assignment).all():
        tn = teachers.get(a.teacher_id)
        cn = classes.get(a.class_id)
        if tn is None or cn is None:
            continue
        out.setdefault(tn, {}).setdefault(cn, {})[a.subject] = a.hours
    return out


# ---------- Pickles -> DB ----------


def import_school_into_db(db: Session, school: dict[str, Any],
                          replace: bool = True) -> None:
    """Replace classes + teachers + subject group weights with values from
    a school pickle dict (as produced by big_mock_school.build_dataset)."""
    if replace:
        for tbl in (
            models.Assignment,
            models.Lesson,
            models.DayCount,
            models.Solution,
            models.ClassSubject,
            models.SchoolClass,
            models.TeacherSubject,
            models.TeacherUnavailability,
            models.TeacherMandatoryFreeDay,
            models.TeacherCompatibleClass,
            models.Teacher,
            models.SubjectGroupWeight,
            models.Subject,
        ):
            db.query(tbl).delete()
        db.commit()

    # Subject rows
    subj_names: set[str] = set()
    for cl in school.get("classes", []):
        for s in cl.get("subjects", {}):
            subj_names.add(s)
    for t in school.get("teachers", []):
        for s in t.get("weights", {}):
            subj_names.add(s)
    for s in subj_names:
        db.add(models.Subject(name=s, pretty_name=s))
    db.flush()

    # Class rows
    for cl in school.get("classes", []):
        sc = models.SchoolClass(
            name=cl["name"],
            year=cl.get("year", 1),
            section=cl.get("section"),
            curriculum=cl.get("curriculum"),
            n_students=cl.get("n_students", 22),
        )
        db.add(sc)
        db.flush()
        for subj, ore in (cl.get("subjects") or {}).items():
            db.add(models.ClassSubject(
                class_id=sc.id, subject=subj, hours_per_week=int(ore)
            ))

    # Teacher rows
    for t in school.get("teachers", []):
        full = t["name"]
        # Best-effort split: Faker default emits "First Last" in en_US, while
        # Italian Faker emits "Last First" or "First Last" depending on the
        # locale's _format. Heuristic: rsplit on the LAST whitespace and treat
        # the right side as last_name; if there's only one token, leave them
        # as None.
        parts = str(full).rsplit(" ", 1)
        if len(parts) == 2:
            first_n, last_n = parts[0], parts[1]
        else:
            first_n, last_n = None, None
        tt = models.Teacher(
            name=full,
            last_name=last_n, first_name=first_n,
            nickname=None,
            group=t.get("group"),
            max_hours=int(t.get("max_hours", 18)),
            free_day=t.get("free_day"),
        )
        db.add(tt)
        db.flush()
        weights = t.get("weights") or {}
        for subj in weights:
            db.add(models.TeacherSubject(teacher_id=tt.id, subject=subj))

    # Subject group weight table
    for subj, gmap in (school.get("cconcorsopersubject") or {}).items():
        for g, w in gmap.items():
            db.add(models.SubjectGroupWeight(
                subject=subj, group_name=g, weight=int(w)
            ))
    db.commit()


def import_assignments_into_db(db: Session,
                               cattedre: dict[str, dict[str, dict[str, int]]]
                               ) -> int:
    """Replace existing assignments with the given mapping. Returns count."""
    db.query(models.Assignment).delete()
    db.commit()
    teachers = {t.name: t.id for t in db.query(models.Teacher).all()}
    classes = {c.name: c.id for c in db.query(models.SchoolClass).all()}
    n = 0
    for tname, cmap in cattedre.items():
        if tname not in teachers:
            # Auto-create teacher if missing (defensive: imported pickle
            # may carry teachers not in DB)
            t = models.Teacher(name=tname, max_hours=18)
            db.add(t)
            db.flush()
            teachers[tname] = t.id
        for cname, sm in cmap.items():
            if cname not in classes:
                continue
            for subj, ore in sm.items():
                db.add(models.Assignment(
                    teacher_id=teachers[tname],
                    class_id=classes[cname],
                    subject=subj,
                    hours=int(ore),
                ))
                n += 1
    db.commit()
    return n


def import_profs_into_db(db: Session, profs: dict[str, Any]) -> int:
    """Import a profs.pkl dict: each entry has classi -> class -> subject ->
    {'ore': N} and glibero. Updates teacher.free_day and assignments."""
    teachers = {t.name: t for t in db.query(models.Teacher).all()}
    classes = {c.name: c.id for c in db.query(models.SchoolClass).all()}
    db.query(models.Assignment).delete()
    db.commit()
    n = 0
    inv_day = {v: k for k, v in DAY_MAP.items()
               if not k.endswith("'") and "Lun" not in k}
    for tname, info in profs.items():
        t = teachers.get(tname)
        if t is None:
            t = models.Teacher(name=tname, max_hours=18)
            db.add(t)
            db.flush()
            teachers[tname] = t
        glib = info.get("glibero") or []
        if glib and not t.free_day:
            t.free_day = inv_day.get(glib[0], "Saturday")
        for cname, sm in (info.get("classi") or {}).items():
            cid = classes.get(cname)
            if cid is None:
                continue
            for subj, meta in sm.items():
                db.add(models.Assignment(
                    teacher_id=t.id,
                    class_id=cid,
                    subject=subj,
                    hours=int(meta.get("ore", 0)),
                ))
                n += 1
    db.commit()
    return n


def import_solution_into_db(db: Session, solution_dict: dict,
                            name: str, kind: str = "imported",
                            obj_value: float = 0.0,
                            metrics: dict | None = None,
                            make_active: bool = True) -> int:
    """Persist a (p,cl,subj,day,hour) -> 0/1 dict as a Solution row + many
    Lesson rows. Returns the new solution id."""
    sol = models.Solution(
        name=name,
        kind=kind,
        obj_value=float(obj_value),
        metrics_json=json.dumps(metrics or {}),
        is_active=False,
        created_at=dt.datetime.utcnow(),
    )
    db.add(sol)
    db.flush()
    for k, v in solution_dict.items():
        if v != 1:
            continue
        try:
            p, cl, subj, day, hour = k
        except Exception:
            continue
        db.add(models.Lesson(
            solution_id=sol.id,
            teacher_name=p,
            class_name=cl,
            subject=subj,
            day=int(day),
            hour=int(hour),
        ))
    db.commit()
    if make_active:
        set_active_solution(db, sol.id)
    return sol.id


def set_active_solution(db: Session, solution_id: int) -> None:
    db.query(models.Solution).update({"is_active": False})
    sol = db.get(models.Solution, solution_id)
    if sol is not None:
        sol.is_active = True
    db.commit()


def get_active_solution(db: Session) -> models.Solution | None:
    return db.query(models.Solution).filter(
        models.Solution.is_active == True  # noqa: E712
    ).first()


def lessons_to_solution_dict(db: Session, solution_id: int
                             ) -> dict[tuple, int]:
    out: dict[tuple, int] = {}
    rows = db.query(models.Lesson).filter(
        models.Lesson.solution_id == solution_id
    ).all()
    for r in rows:
        out[(r.teacher_name, r.class_name, r.subject, r.day, r.hour)] = 1
    return out


def replace_solution_lessons(db: Session, solution_id: int,
                             solution_dict: dict[tuple, int]) -> None:
    """Carry over classroom_name/co-teachers from previous Lesson rows when
    keys still match — this preserves manual room edits across small SOFT
    repairs (the keys are stable in (p, cl, subj, d, h))."""
    prev = db.query(models.Lesson).filter(
        models.Lesson.solution_id == solution_id
    ).all()
    prev_by_key = {
        (l.teacher_name, l.class_name, l.subject, l.day, l.hour):
        (l.classroom_name, l.cotaught_with) for l in prev
    }
    db.query(models.Lesson).filter(
        models.Lesson.solution_id == solution_id
    ).delete()
    db.commit()
    for k, v in solution_dict.items():
        if v != 1:
            continue
        p, cl, subj, day, hour = k
        room, cot = prev_by_key.get((p, cl, subj, day, hour),
                                    (None, None))
        db.add(models.Lesson(
            solution_id=solution_id,
            teacher_name=p,
            class_name=cl,
            subject=subj,
            day=int(day),
            hour=int(hour),
            classroom_name=room,
            cotaught_with=cot,
        ))
    db.commit()


# ---------- Classrooms ----------


def classrooms_dicts_from_db(db: Session) -> list[dict]:
    """Materialize classrooms with all their constraints, ready to feed
    classroom_assignment.solve_classroom_assignment()."""
    out: list[dict] = []
    for r in db.query(models.Classroom).all():
        unav = {(u.day, u.hour) for u in r.unavailability}
        subj_req = {sp.subject for sp in r.subject_prefs if sp.required}
        subj_pref = {sp.subject: sp.weight for sp in r.subject_prefs}
        cls_pref = {cp.class_name: cp.weight for cp in r.class_prefs}
        is_home_for = {cp.class_name for cp in r.class_prefs if cp.is_home}
        out.append({
            "name": r.name,
            "kind": r.kind,
            "capacity": r.capacity,
            "multi_class": r.multi_class,
            "multi_class_max": r.multi_class_max,
            "multi_class_pref": r.multi_class_pref,
            "multi_class_pref_weight": r.multi_class_pref_weight,
            "unavailability": unav,
            "subject_required": subj_req,
            "subject_pref_weight": subj_pref,
            "class_pref_weight": cls_pref,
            "is_home_for": is_home_for,
        })
    return out


def lessons_for_classroom_step(db: Session, solution_id: int) -> list[dict]:
    """Convert lessons in the active solution to the shape expected by
    classroom_assignment."""
    out = []
    for l in db.query(models.Lesson).filter(
        models.Lesson.solution_id == solution_id
    ).all():
        co = []
        if l.cotaught_with:
            co = [s.strip() for s in l.cotaught_with.split(",") if s.strip()]
        out.append({
            "teacher": l.teacher_name,
            "co_teachers": co,
            "class": l.class_name,
            "subject": l.subject,
            "day": l.day,
            "hour": l.hour,
        })
    return out


def apply_room_mapping(db: Session, solution_id: int,
                       mapping: dict[tuple, str]) -> int:
    """Updates Lesson.classroom_name from a (class, subject, day, hour)
    -> classroom_name dict. Returns the number of rows updated."""
    n = 0
    for l in db.query(models.Lesson).filter(
        models.Lesson.solution_id == solution_id
    ).all():
        key = (l.class_name, l.subject, l.day, l.hour)
        if key in mapping:
            l.classroom_name = mapping[key]
            n += 1
    db.commit()
    return n
