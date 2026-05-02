r"""Hall's theorem pre-check for the (teacher x class-subject) bipartite.

The Phase-A assignment is structurally feasible iff for every subset
S of "demand units" (one unit per (class, subject, week-hour)) the
number of capable teachers in their neighbourhood `N(S)` is large
enough -- specifically, the total max-hours capacity of `N(S)`
matches the demand of S. This is the weighted analogue of Hall's
marriage theorem (Konig-Egervary).

This module computes three quick infeasibility witnesses BEFORE we
fire CP-SAT, so the user gets an immediate diagnosis instead of a
2-minute timeout:

  1. **Subject-level supply vs demand**: for each subject s, the
     total weekly hours demanded across all classes must not
     exceed the cumulative `max_hours` of teachers qualified in s.

  2. **Per (class, subject) coverage**: there must be at least one
     teacher qualified in subject s and not blocked from class c.

  3. **Random-subset Hall sampling**: sample many random subsets S
     of teachers, look at the demand of classes ONLY teachable by
     them, and check capacity. If even one violating S is found,
     return it as a witness.

Returns a structured dict so the UI can render the first 3-5 most
egregious violations.
"""
from __future__ import annotations

import random
from typing import Any


def _teacher_subjects(profs: dict) -> dict[str, set[str]]:
    """Return {teacher_name: {subject names taught}}."""
    out: dict[str, set[str]] = {}
    for t, info in profs.items():
        subj: set[str] = set()
        for cl, sub_dict in (info.get("classi") or {}).items():
            for s in sub_dict.keys():
                subj.add(s)
        out[t] = subj
    return out


def _class_subjects_demand(school: dict) -> dict[tuple[str, str], int]:
    """Return {(class, subject): hours_per_week} from a school dict."""
    out: dict[tuple[str, str], int] = {}
    for cl in school.get("classes", []):
        cname = cl.get("name") or cl.get("nome") or "?"
        for s, h in (cl.get("monte_ore") or cl.get("subjects") or {}).items():
            try:
                out[(cname, s)] = int(h)
            except (TypeError, ValueError):
                continue
    return out


def _max_hours(profs: dict, t: str, default: int = 18) -> int:
    return int((profs.get(t) or {}).get("max_hours") or default)


def hall_check(school: dict, profs: dict,
               *, n_samples: int = 256,
               sample_size_range: tuple[int, int] = (2, 8),
               rng_seed: int = 7,
               max_witnesses: int = 5,
               teacher_max_hours: int = 18) -> dict[str, Any]:
    """Run the structural feasibility diagnostics.

    Args:
      school:  the school dict (from big_mock_school or DB import).
               Must expose `classes: [{name, monte_ore: {subj: h}}]`.
      profs:   {teacher_name -> {classi: {cls: {subj: ...}}, ...}}
               (the Phase-A solution dict format used by the engine).
      n_samples: number of random teacher subsets sampled for Hall.
      sample_size_range: bounds on |S| (inclusive).
      max_witnesses: how many violating subsets to keep at most.
      teacher_max_hours: fall-back when profs[t] doesn't carry it.

    Returns:
      dict {
        ok: bool,                       # overall feasibility
        n_classes: int,
        n_teachers: int,
        violations: [
          {
            kind: "no_teacher" | "subject_supply" | "hall_subset",
            subject?, class?, demand, supply, teachers?: [...],
            classes?: [...],
          },
        ],
        warnings: [str],
        stats: {...},
      }
    """
    rng = random.Random(rng_seed)
    teachers = sorted(profs.keys())
    teacher_subj = _teacher_subjects(profs)
    cls_subj_demand = _class_subjects_demand(school)
    classes = sorted({c for (c, _) in cls_subj_demand.keys()})

    violations: list[dict] = []
    warnings: list[str] = []

    # ---- (1) Per-(class, subject) coverage ----
    for (cl, s), h in cls_subj_demand.items():
        teachers_for = [t for t in teachers if s in teacher_subj.get(t, set())]
        if not teachers_for and h > 0:
            violations.append({
                "kind": "no_teacher",
                "class": cl,
                "subject": s,
                "demand": h,
                "supply": 0,
                "teachers": [],
                "msg": f"Nessun docente sa insegnare '{s}' "
                       f"(richiesto da {cl} per {h} ore).",
            })

    # ---- (2) Subject-level supply vs demand ----
    subj_demand: dict[str, int] = {}
    for (cl, s), h in cls_subj_demand.items():
        subj_demand[s] = subj_demand.get(s, 0) + h
    subj_supply: dict[str, int] = {}
    for t in teachers:
        mh = _max_hours(profs, t, teacher_max_hours)
        for s in teacher_subj.get(t, set()):
            subj_supply[s] = subj_supply.get(s, 0) + mh
    for s, d in subj_demand.items():
        sup = subj_supply.get(s, 0)
        if sup < d:
            tlist = [t for t in teachers if s in teacher_subj.get(t, set())]
            violations.append({
                "kind": "subject_supply",
                "subject": s,
                "demand": d,
                "supply": sup,
                "teachers": tlist,
                "msg": f"Materia '{s}': domanda {d}h > capacita' "
                       f"docenti {sup}h "
                       f"({len(tlist)} docenti qualificati).",
            })

    # ---- (3) Random-subset Hall sampling ----
    # Build subject -> qualified-teachers index once.
    subj_to_teachers: dict[str, set[str]] = {}
    for t, sset in teacher_subj.items():
        for s in sset:
            subj_to_teachers.setdefault(s, set()).add(t)
    if teachers and len(violations) < max_witnesses:
        n_t = len(teachers)
        for _ in range(n_samples):
            k = rng.randint(*sample_size_range)
            k = min(k, n_t)
            S = set(rng.sample(teachers, k))
            # Subjects EXCLUSIVE to S = subjects whose qualified-teacher
            # set is a subset of S. These are the demands that ONLY S
            # can fulfil.
            exclusive_subjects = {
                s for s, qt in subj_to_teachers.items()
                if qt and qt.issubset(S)
            }
            ex_demand = sum(
                h for (cl, s), h in cls_subj_demand.items()
                if s in exclusive_subjects
            )
            supply = sum(_max_hours(profs, t, teacher_max_hours)
                          for t in S)
            # A subset S violates Hall when its exclusive demand
            # exceeds its supply.
            if exclusive_subjects and ex_demand > supply:
                violations.append({
                    "kind": "hall_subset",
                    "teachers": sorted(S),
                    "subjects": sorted(exclusive_subjects),
                    "demand": int(ex_demand),
                    "supply": int(supply),
                    "msg": (f"Sottoinsieme di {len(S)} docenti: "
                            f"capacita' {supply}h ma le materie a loro "
                            f"esclusive ({sorted(exclusive_subjects)}) "
                            f"richiedono {ex_demand}h "
                            f"(violazione di Hall)."),
                })
                if len(violations) >= max_witnesses:
                    break

    # Truncate
    if len(violations) > max_witnesses:
        warnings.append(
            f"trovati >{max_witnesses} violazioni; mostrate solo le prime."
        )
        violations = violations[:max_witnesses]

    return {
        "ok": len(violations) == 0,
        "n_classes": len(classes),
        "n_teachers": len(teachers),
        "violations": violations,
        "warnings": warnings,
        "stats": {
            "n_subjects": len(subj_demand),
            "total_demand_hours": int(sum(subj_demand.values())),
            "total_supply_hours": int(sum(
                _max_hours(profs, t, teacher_max_hours)
                for t in teachers
            )),
            "n_samples": n_samples,
        },
    }


def hall_check_from_db(db, *, n_samples: int = 256,
                       teacher_max_hours: int = 18) -> dict[str, Any]:
    """Convenience: build (school, profs)-shaped views directly from
    the live SQLAlchemy session (no engine pickles needed)."""
    from backend import models  # type: ignore
    school = {"classes": []}
    classes_by_id: dict[int, str] = {}
    for c in db.query(models.SchoolClass).all():
        classes_by_id[c.id] = c.name
        monte_ore: dict[str, int] = {}
        for cs in c.subjects:
            monte_ore[cs.subject] = int(cs.hours_per_week or 0)
        school["classes"].append({
            "name": c.name, "monte_ore": monte_ore,
        })
    profs: dict = {}
    teachers_by_id: dict[int, Any] = {
        t.id: t for t in db.query(models.Teacher).all()
    }
    for a in db.query(models.Assignment).all():
        t = teachers_by_id.get(a.teacher_id)
        cl = classes_by_id.get(a.class_id)
        if t is None or cl is None:
            continue
        node = profs.setdefault(t.name, {
            "classi": {}, "max_hours": int(t.max_hours or teacher_max_hours),
        })
        node["classi"].setdefault(cl, {})[a.subject] = {"ore": a.hours}
    # Teachers with NO assignments yet still need to appear so that
    # their max_hours is counted in the supply check.
    for t in teachers_by_id.values():
        node = profs.setdefault(t.name, {
            "classi": {}, "max_hours": int(t.max_hours or teacher_max_hours),
        })
        # Subjects the teacher is qualified for: read teacher_subjects
        for ts in t.subjects:
            for cl_dict in node["classi"].values():
                cl_dict.setdefault(ts.subject, {"ore": 0})
        # If teacher has no assignment, fake a placeholder entry so
        # their qualification matrix is still surfaced.
        if not node["classi"]:
            placeholder: dict[str, dict] = {}
            for ts in t.subjects:
                placeholder[ts.subject] = {"ore": 0}
            node["classi"]["__no_class_yet__"] = placeholder
    return hall_check(school, profs, n_samples=n_samples,
                       teacher_max_hours=teacher_max_hours)
