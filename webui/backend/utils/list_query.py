"""Field/function adapters for the query DSL, one per list entity."""
from __future__ import annotations

from typing import Any, Callable

from .query_parser import (
    QueryError,
    evaluate,
    parse_query,
    parse_sort,
    sort_records,
)


# ---------- Teachers ----------


def teacher_fields() -> dict[str, Callable[[Any], Any]]:
    """`record` is a dict (TeacherOut.model_dump()) augmented with extra
    keys: scheduled_hours, n_classes, soft_penalty_total."""
    return {
        "name": lambda r: r.get("name") or "",
        "cognome_nome": lambda r: r.get("name") or "",
        "matricola": lambda r: r.get("matricola") or "",
        "group": lambda r: r.get("group") or "",
        "classe_di_concorso": lambda r: r.get("group") or "",
        "max_hours": lambda r: r.get("max_hours", 0),
        "max_ore": lambda r: r.get("max_hours", 0),
        "ore_cattedra": lambda r: r.get("scheduled_hours", 0),
        "scheduled_hours": lambda r: r.get("scheduled_hours", 0),
        "free_day": lambda r: r.get("free_day") or "",
        "giorno_libero": lambda r: r.get("free_day") or "",
        "subjects": lambda r: ",".join(r.get("subjects", [])),
        "materia": lambda r: ",".join(r.get("subjects", [])).lower(),
        "n_classes": lambda r: r.get("n_classes", 0),
        "n_classi": lambda r: r.get("n_classes", 0),
        "soft_penalty_total": lambda r: r.get("soft_penalty_total", 0),
        "n_unavail": lambda r: len(r.get("unavailability", [])),
    }


def _day_to_int(day_arg) -> int | None:
    if isinstance(day_arg, (int, float)):
        return int(day_arg)
    if not isinstance(day_arg, str):
        return None
    map_ = {
        "lun": 1, "lunedi": 1, "monday": 1,
        "mar": 2, "martedi": 2, "tuesday": 2,
        "mer": 3, "mercoledi": 3, "wednesday": 3,
        "gio": 4, "giovedi": 4, "thursday": 4,
        "ven": 5, "venerdi": 5, "friday": 5,
        "sab": 6, "sabato": 6, "saturday": 6,
    }
    return map_.get(day_arg.strip().lower())


def teacher_funcs() -> dict[str, Callable[..., bool]]:
    def unavailable_on(record, *args) -> bool:
        if not args:
            return False
        d = _day_to_int(args[0])
        if d is None:
            return False
        cells = record.get("unavailability", []) or []
        if len(args) == 1:
            return any(int(c.get("day", 0)) == d
                       and c.get("state") == "hard" for c in cells)
        try:
            h = int(args[1])
        except Exception:
            return False
        return any(int(c.get("day", 0)) == d and int(c.get("hour", 0)) == h
                   and c.get("state") == "hard" for c in cells)

    def soft_on(record, *args) -> bool:
        if not args:
            return False
        d = _day_to_int(args[0])
        cells = record.get("unavailability", []) or []
        if d is None:
            return False
        if len(args) == 1:
            return any(int(c.get("day", 0)) == d
                       and c.get("state") == "soft" for c in cells)
        h = int(args[1])
        return any(int(c.get("day", 0)) == d and int(c.get("hour", 0)) == h
                   and c.get("state") == "soft" for c in cells)
    return {"unavailable_on": unavailable_on, "soft_on": soft_on}


# ---------- Classes ----------


def class_fields() -> dict[str, Callable[[Any], Any]]:
    return {
        "name": lambda r: r.get("name") or "",
        "year": lambda r: r.get("year", 0),
        "anno": lambda r: r.get("year", 0),
        "section": lambda r: r.get("section") or "",
        "sezione": lambda r: r.get("section") or "",
        "curriculum": lambda r: r.get("curriculum") or "",
        "indirizzo": lambda r: r.get("curriculum") or "",
        "n_students": lambda r: r.get("n_students", 0),
        "ore_totali": lambda r: sum(int(s.get("hours_per_week", 0))
                                    for s in r.get("subjects", [])),
        "n_subjects": lambda r: len(r.get("subjects", [])),
    }


def class_funcs() -> dict[str, Callable[..., bool]]:
    return teacher_funcs()  # same signatures (unavailable_on / soft_on)


# ---------- Classrooms ----------


def classroom_fields() -> dict[str, Callable[[Any], Any]]:
    return {
        "name": lambda r: r.get("name") or "",
        "kind": lambda r: r.get("kind") or "",
        "tipo": lambda r: r.get("kind") or "",
        "capacity": lambda r: r.get("capacity", 0),
        "capienza": lambda r: r.get("capacity", 0),
        "multi_class": lambda r: 1 if r.get("multi_class") else 0,
        "multi_classe": lambda r: 1 if r.get("multi_class") else 0,
    }


def classroom_funcs() -> dict[str, Callable[..., bool]]:
    return teacher_funcs()


# ---------- Subjects ----------


def subject_fields() -> dict[str, Callable[[Any], Any]]:
    return {
        "name": lambda r: r.get("name") or "",
        "pretty_name": lambda r: r.get("pretty_name") or "",
        "distribute_days_weight": lambda r: r.get("distribute_days_weight", 0),
        "dual_hours_weight": lambda r: r.get("dual_hours_weight", 0),
        "no_sixth_hour_weight": lambda r: r.get("no_sixth_hour_weight", 0),
    }


def subject_funcs() -> dict[str, Callable[..., bool]]:
    return {}


# ---------- Apply (filter + sort) ----------


# ---------- Curricula ----------


def curriculum_fields() -> dict[str, Callable[[Any], Any]]:
    return {
        "code": lambda r: r.get("code") or "",
        "codice": lambda r: r.get("code") or "",
        "name": lambda r: r.get("name") or "",
        "nome": lambda r: r.get("name") or "",
        "description": lambda r: r.get("description") or "",
        "score": lambda r: r.get("score", 0),
        "punteggio": lambda r: r.get("score", 0),
        "n_classes": lambda r: r.get("n_classes", 0),
        "n_classi": lambda r: r.get("n_classes", 0),
        "n_hours_rows": lambda r: len(r.get("hours", [])),
    }


def curriculum_funcs() -> dict[str, Callable[..., bool]]:
    return {}


# ---------- Students ----------


def student_fields() -> dict[str, Callable[[Any], Any]]:
    return {
        "last_name": lambda r: r.get("last_name") or "",
        "cognome": lambda r: r.get("last_name") or "",
        "first_name": lambda r: r.get("first_name") or "",
        "nome": lambda r: r.get("first_name") or "",
        "fullname": lambda r: ((r.get("last_name") or "") + " "
                               + (r.get("first_name") or "")).strip(),
        "class_name": lambda r: r.get("class_name") or "",
        "classe": lambda r: r.get("class_name") or "",
        "student_code": lambda r: r.get("student_code") or "",
        "matricola": lambda r: r.get("student_code") or "",
        "email": lambda r: r.get("email") or "",
        "gender": lambda r: r.get("gender") or "",
        "n_groups": lambda r: r.get("n_groups", 0),
    }


def student_funcs() -> dict[str, Callable[..., bool]]:
    return {}


# ---------- Study groups ----------


def group_fields() -> dict[str, Callable[[Any], Any]]:
    return {
        "name": lambda r: r.get("name") or "",
        "nome": lambda r: r.get("name") or "",
        "kind": lambda r: r.get("kind") or "",
        "tipo": lambda r: r.get("kind") or "",
        "description": lambda r: r.get("description") or "",
        "n_students": lambda r: r.get("n_students", 0),
        "n_studenti": lambda r: r.get("n_students", 0),
        "n_classes_touched": lambda r: r.get("n_classes_touched", 0),
        "n_classi_coinvolte": lambda r: r.get("n_classes_touched", 0),
        "n_subjects": lambda r: len(r.get("subject_hours", [])),
    }


def group_funcs() -> dict[str, Callable[..., bool]]:
    return {}


_FIELDS_FOR = {
    "teachers":   (teacher_fields, teacher_funcs),
    "classes":    (class_fields, class_funcs),
    "classrooms": (classroom_fields, classroom_funcs),
    "subjects":   (subject_fields, subject_funcs),
    "curricula":  (curriculum_fields, curriculum_funcs),
    "students":   (student_fields, student_funcs),
    "groups":     (group_fields, group_funcs),
}


def filter_and_sort(records: list[dict], entity: str,
                    q: str | None, sort: str | None) -> list[dict]:
    builder = _FIELDS_FOR.get(entity)
    if builder is None:
        return records
    fields_fn, funcs_fn = builder
    fields = fields_fn()
    funcs = funcs_fn()
    if q:
        ast = parse_query(q)
        records = [r for r in records if evaluate(ast, r, fields, funcs)]
    if sort:
        spec = parse_sort(sort)
        records = sort_records(records, spec, fields)
    return records
