"""Graph builders for the Dashboard "Network" panel.

Two modes:
  - mode='classes':  nodes = SchoolClass, edges weighted by # of shared teachers
  - mode='teachers': nodes = Teacher,    edges weighted by # of shared classes

Both use the Assignment table (one row per teacher-class-subject triple)
as the source of incidence.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from .. import models


def _teacher_label(t: models.Teacher) -> str:
    """Compact label for a teacher node."""
    if t.last_name and t.first_name:
        return f"{t.last_name} {t.first_name[0]}."
    if t.last_name:
        return t.last_name
    return t.name or f"#{t.id}"


def _teacher_meta(t: models.Teacher, subjects: list[str],
                  classes: list[str]) -> dict:
    return {
        "name": t.name,
        "last_name": t.last_name,
        "first_name": t.first_name,
        "group": t.group,
        "subjects": sorted(set(subjects)),
        "classes": sorted(set(classes)),
        "n_classes": len(set(classes)),
    }


def _class_meta(cl: models.SchoolClass, teachers: list[str],
                subjects: list[str]) -> dict:
    return {
        "year": cl.year,
        "section": cl.section,
        "curriculum": cl.curriculum,
        "n_students": cl.n_students,
        "teachers": sorted(set(teachers)),
        "subjects": sorted(set(subjects)),
        "n_teachers": len(set(teachers)),
    }


def build_graph(db: Session, mode: str) -> dict[str, Any]:
    """Returns a `{nodes, edges, mode, n_nodes, n_edges}` dict.

    Empty DB -> empty arrays. Disconnected nodes (a class with no
    assignments yet, a teacher with no class) ARE included so the
    Dashboard surfaces them as isolated dots.
    """
    if mode not in ("classes", "teachers"):
        raise ValueError(f"unknown graph mode: {mode}")

    teachers = {t.id: t for t in db.query(models.Teacher).all()}
    classes = {c.id: c for c in db.query(models.SchoolClass).all()}
    assignments = db.query(models.Assignment).all()

    # Build incidence:
    #   class_id -> set of (teacher_id, subject)
    #   teacher_id -> set of (class_id, subject)
    cls_to_team: dict[int, set[tuple[int, str]]] = defaultdict(set)
    tea_to_cls: dict[int, set[tuple[int, str]]] = defaultdict(set)
    for a in assignments:
        cls_to_team[a.class_id].add((a.teacher_id, a.subject))
        tea_to_cls[a.teacher_id].add((a.class_id, a.subject))

    if mode == "classes":
        nodes = []
        for cid, cl in sorted(classes.items(), key=lambda kv: kv[1].name):
            tids = [t for t, _ in cls_to_team.get(cid, set())]
            t_names = [
                teachers[t].name for t in tids if t in teachers
            ]
            subjs = [s for _, s in cls_to_team.get(cid, set())]
            nodes.append({
                "id": f"c{cid}",
                "label": cl.name,
                "kind": "class",
                "meta": _class_meta(cl, t_names, subjs),
            })

        # For each unordered pair of classes (cA, cB), count distinct
        # teachers in (cls_to_team[cA] ∩ cls_to_team[cB])(ignoring subject).
        cls_ids = sorted(classes.keys())
        edges: list[dict] = []
        for i, ca in enumerate(cls_ids):
            ta = {t for t, _ in cls_to_team.get(ca, set())}
            if not ta:
                continue
            for cb in cls_ids[i + 1:]:
                tb = {t for t, _ in cls_to_team.get(cb, set())}
                shared = ta & tb
                if not shared:
                    continue
                shared_names = sorted(
                    teachers[t].name for t in shared if t in teachers
                )
                edges.append({
                    "source": f"c{ca}",
                    "target": f"c{cb}",
                    "weight": len(shared),
                    "shared": shared_names,
                })
        return {
            "mode": "classes",
            "nodes": nodes,
            "edges": edges,
            "n_nodes": len(nodes),
            "n_edges": len(edges),
        }

    # mode == 'teachers'
    nodes = []
    for tid, t in sorted(teachers.items(),
                         key=lambda kv: (kv[1].last_name or kv[1].name or "")):
        cls_ids_for_t = [c for c, _ in tea_to_cls.get(tid, set())]
        cls_names = [
            classes[c].name for c in cls_ids_for_t if c in classes
        ]
        subjs = [s for _, s in tea_to_cls.get(tid, set())]
        nodes.append({
            "id": f"t{tid}",
            "label": _teacher_label(t),
            "kind": "teacher",
            "meta": _teacher_meta(t, subjs, cls_names),
        })

    tea_ids = sorted(teachers.keys())
    edges = []
    for i, ta in enumerate(tea_ids):
        ca = {c for c, _ in tea_to_cls.get(ta, set())}
        if not ca:
            continue
        for tb in tea_ids[i + 1:]:
            cb = {c for c, _ in tea_to_cls.get(tb, set())}
            shared = ca & cb
            if not shared:
                continue
            shared_names = sorted(
                classes[c].name for c in shared if c in classes
            )
            edges.append({
                "source": f"t{ta}",
                "target": f"t{tb}",
                "weight": len(shared),
                "shared": shared_names,
            })
    return {
        "mode": "teachers",
        "nodes": nodes,
        "edges": edges,
        "n_nodes": len(nodes),
        "n_edges": len(edges),
    }
