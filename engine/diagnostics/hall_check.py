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


def _engine_day_caps() -> tuple[int, int]:
    """Read the per-day caps straight from the engine so this pre-check
    can never drift from what the solver actually enforces."""
    try:
        from cpsat_v2_timetable import (  # type: ignore
            MAX_PER_DAY_PROF_CL, MAX_PER_DAY_TRIPLE,
        )
    except ImportError:  # pragma: no cover - path-injection fallback
        from engine.cpsat_v2_timetable import (  # type: ignore
            MAX_PER_DAY_PROF_CL, MAX_PER_DAY_TRIPLE,
        )
    return int(MAX_PER_DAY_PROF_CL), int(MAX_PER_DAY_TRIPLE)


def per_teacher_day_capacity_check(
        db, *, working_days: int, max_witnesses: int = 10,
) -> tuple[list[dict], list[str]]:
    """Structural, solve-free feasibility of each cattedra against the
    per-day caps and the mandatory-free-day floor.

    This is the three-line check the audit (findings 14/18/30) asked for:
    a cattedra that asks more hours than the caps physically allow on the
    days the teacher is present is INFEASIBLE *by construction*, and no
    amount of solver time will fix it. Catching it here — with the
    teacher's name and what to change — spares the school a 35-minute run
    that ends in an unexplained INFEASIBLE.

    The arithmetic per (teacher, class):
        placeable_hours <= MAX_PER_DAY_PROF_CL * (working_days - min_free_days)
    and per cattedra (teacher, class, subject):
        hours          <= MAX_PER_DAY_TRIPLE  * (working_days - min_free_days)

    We do NOT special-case sostegno: the caps and the free-day floor are
    general defaults. A full-time support teacher who genuinely works all
    six days simply has `min_free_days = 0` — correct modelling of reality,
    and exactly what the message tells the school to set.
    """
    from collections import defaultdict
    from backend import models  # type: ignore

    max_prof_cl, max_triple = _engine_day_caps()
    violations: list[dict] = []
    warnings: list[str] = []

    teachers_by_id = {t.id: t for t in db.query(models.Teacher).all()}
    classes_by_id = {c.id: c.name for c in db.query(models.SchoolClass).all()}

    tc_hours: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    tcs_hours: dict[tuple, int] = defaultdict(int)
    for a in db.query(models.Assignment).all():
        cl = classes_by_id.get(a.class_id)
        if a.teacher_id not in teachers_by_id or cl is None:
            # class_id NULL = potenziamento (no fixed class): the per-class
            # cap does not bind, skip it rather than guess a class.
            continue
        h = int(getattr(a, "hours", 0) or 0)
        if h <= 0:
            continue
        tc_hours[a.teacher_id][cl] += h
        tcs_hours[(a.teacher_id, cl, a.subject)] += h

    flagged_tc: set[tuple[int, str]] = set()
    for tid, per_class in tc_hours.items():
        t = teachers_by_id[tid]
        mfd = int(getattr(t, "min_free_days", 1) or 0)
        avail = max(0, int(working_days) - mfd)
        for cl, h in per_class.items():
            cap = max_prof_cl * avail
            if h > cap:
                flagged_tc.add((tid, cl))
                violations.append({
                    "kind": "per_day_capacity",
                    "teacher": t.name, "class": cl,
                    "demand": h, "supply": cap,
                    "msg": (
                        f"{t.name}: {h}h sulla classe {cl}, ma con max "
                        f"{max_prof_cl} ore/giorno e {mfd} giorno/i "
                        f"libero/i su {working_days} restano {avail} giorni "
                        f"utili -> capienza {cap}h. La cattedra e' "
                        f"impossibile per costruzione: riduci min_free_days, "
                        f"distribuisci le ore su piu' classi, o alza il "
                        f"tetto ore/giorno."
                    ),
                })

    for (tid, cl, subj), h in tcs_hours.items():
        if (tid, cl) in flagged_tc:
            continue  # already reported at the (teacher, class) level
        t = teachers_by_id[tid]
        mfd = int(getattr(t, "min_free_days", 1) or 0)
        avail = max(0, int(working_days) - mfd)
        cap = max_triple * avail
        if h > cap:
            violations.append({
                "kind": "per_day_cattedra_capacity",
                "teacher": t.name, "class": cl, "subject": subj,
                "demand": h, "supply": cap,
                "msg": (
                    f"Cattedra {t.name} / {cl} / {subj}: {h}h con max "
                    f"{max_triple} ore/giorno per cattedra su {avail} "
                    f"giorni utili -> capienza {cap}h. Riduci min_free_days "
                    f"o spezza la cattedra."
                ),
            })

    if len(violations) > max_witnesses:
        warnings.append(
            f"trovate {len(violations)} cattedre infeasibili per i tetti "
            f"giornalieri; mostrate solo le prime {max_witnesses}."
        )
        violations = violations[:max_witnesses]
    return violations, warnings


def special_room_capacity_check(
        db, *, working_days: int, hours_per_day: int = 6,
) -> list[dict]:
    """Necessary condition for gym/lab feasibility (finding 34).

    Weekly hours of every subject that requires a room `kind` must fit the
    weekly capacity of rooms of that kind:

        sum_class hours(subject with required_kind=R)
            <= (sum_room multi_class_max for kind R) * working_days * hours_per_day

    This is only a *necessary* structural bound -- it catches gross
    over-subscription, not the distributional overflow (7 classes in one
    slot) that the Phase-B constraint handles. Both matter: the Phase-B
    cap can't help a school that simply has more PE hours than any gym
    schedule could hold, and this check names that up front.
    """
    from collections import defaultdict
    from backend import models  # type: ignore

    subj_kind = {
        s.name: s.required_kind
        for s in db.query(models.Subject).all()
        if getattr(s, "required_kind", None)
    }
    if not subj_kind:
        return []
    kind_cap: dict[str, int] = defaultdict(int)
    for r in db.query(models.Classroom).all():
        k = getattr(r, "kind", None)
        if k in set(subj_kind.values()):
            kind_cap[k] += int(getattr(r, "multi_class_max", 1) or 1)
    demand: dict[str, int] = defaultdict(int)
    for cs in db.query(models.ClassSubject).all():
        k = subj_kind.get(cs.subject)
        if k is not None:
            demand[k] += int(getattr(cs, "hours_per_week", 0) or 0)
    slots = max(1, int(working_days) * int(hours_per_day))
    out: list[dict] = []
    for k, dem in demand.items():
        cap = kind_cap.get(k, 0) * slots
        if dem > cap:
            out.append({
                "kind": "special_room_capacity",
                "room_kind": k, "demand": dem, "supply": cap,
                "msg": (
                    f"Aule di tipo '{k}': domanda {dem}h/settimana ma "
                    f"capienza {kind_cap.get(k, 0)} classi x {slots} slot "
                    f"= {cap}h. Nessun orario puo' collocare tutte le ore: "
                    f"aggiungi aule di tipo '{k}' o riduci le ore che lo "
                    f"richiedono."
                ),
            })
    return out


def _part_time_advisory(db) -> str | None:
    """Finding 20: warn that the DEFAULT solver preset ('day' scope,
    phase_a_mode='always') pins Phase A's day distribution as a HARD
    equality on Phase B, while Phase A itself does not see teacher
    unavailability. Any school with HARD availability limits can hit an
    INFEASIBLE-in-presolve that reads as a mystery. Point at the remedy.
    """
    from backend import models  # type: ignore
    try:
        n_unav = (db.query(models.TeacherUnavailability)
                  .filter(models.TeacherUnavailability.state == "hard")
                  .count())
    except Exception:
        n_unav = 0
    try:
        n_free = db.query(models.TeacherMandatoryFreeDay).count()
    except Exception:
        n_free = 0
    if n_unav + n_free == 0:
        return None
    return (
        f"{n_unav} celle di indisponibilita' HARD e {n_free} giorni liberi "
        f"obbligatori. Nel preset predefinito (scope 'day', phase_a_mode "
        f"'always') la Fase A non li vede e ne impone comunque la "
        f"distribuzione alla Fase B: se la generazione chiude INFEASIBLE "
        f"in presolve, usa il preset 'part-time / sostegno' (scope 'week', "
        f"phase_a_mode 'soft_hint'), che lascia al solver ridistribuire le "
        f"ore rispettando le indisponibilita' vere."
    )


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
    res = hall_check(school, profs, n_samples=n_samples,
                     teacher_max_hours=teacher_max_hours)

    # --- (4) Per-teacher per-day arithmetic feasibility (findings 14/18/30).
    # The aggregate demand/supply check above answered "ok" to a problem
    # that was infeasible for 10 individual teachers; this closes that gap.
    from backend import models  # type: ignore
    try:
        n_wd = (db.query(models.WorkingDay)
                .filter(models.WorkingDay.is_active.is_(True))
                .count())
    except Exception:
        n_wd = 0
    working_days = n_wd if n_wd > 0 else 6
    try:
        cap_viol, cap_warn = per_teacher_day_capacity_check(
            db, working_days=working_days)
        res["violations"].extend(cap_viol)
        res["warnings"].extend(cap_warn)
    except Exception as e:  # never let the pre-check crash the run
        res["warnings"].append(f"per-teacher capacity check saltato: {e}")

    try:
        res["violations"].extend(
            special_room_capacity_check(db, working_days=working_days))
    except Exception as e:
        res["warnings"].append(f"special-room capacity check saltato: {e}")

    advisory = _part_time_advisory(db)
    if advisory:
        res["warnings"].append(advisory)

    # `ok` must reflect the per-teacher violations too, or the report
    # would still greenlight an impossible problem (the exact trap of
    # finding 18).
    res["ok"] = len(res["violations"]) == 0
    res["stats"]["working_days"] = working_days
    return res
