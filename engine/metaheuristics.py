r"""Metaeuristiche di post-ottimizzazione per l'orario settimanale.

Tutte le funzioni operano su un dizionario "soluzione" del formato:
    sol: dict {(prof, classe, materia, day, hour): 0/1}

Mai violano i vincoli HARD seguenti (la verifica e\` fatta da
`is_hard_feasible`):
    H1) classi: niente buchi
    H2) classi: ingresso fisso alle 8
    H3) classi: uscita >= 12 (presente alla 4^a)
    H4) classi (>24h): niente giornate da 3 ore (implicato sotto
        H1+H2+H3 con load >= 4)
    H_A) Mat/Ita: in qualche giorno della settimana, doppia ora
         consecutiva del prof in classe
    H_B) Scienzemotorie: tutte le ore in coppie consecutive
    H_C) prof: max 5 ore consecutive in un giorno (= max 5 totali su
         6 slot, dato che no-holes obbligati)
    coverage: tutte le ore-cattedra coperte (se la sol parte feasible
        non e\` mai a rischio: nessuna mossa modifica day_count)

SOFT (da minimizzare):
    S4) numero di slot di 6^a ora occupati dalle classi
    S6) numero di buchi del docente nelle sue giornate di servizio
    SD) numero di prof con prof_day_load == 5
    SE) numero di prof con prof_day_load == 1

Pesi default in `OBJECTIVE_WEIGHTS`. La funzione `compute_soft` ritorna
sia il dict di metriche che il valore aggregato.

API principale:
    run_lns(sol, profs, dc_value, time_budget_s, ...)
    run_sa(sol, profs, dc_value, time_budget_s, ...)
    run_tabu(sol, profs, dc_value, time_budget_s, ...)
    run_ils(sol, profs, dc_value, time_budget_s, ...)
    run_cascade(sol, profs, dc_value, budgets, ...)

`profs` e `dc_value` (= Phase A) sono usati per: (a) verifica HARD
A/B (richiede di sapere chi e\` il prof di Mat/Ita/Mot per classe),
(b) lookup di cattedre/triple esistenti.
"""
from __future__ import annotations

import math
import os
import random
import sys
import time
from collections import defaultdict
from copy import deepcopy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cpsat_v2_timetable as cv2  # noqa: E402

DAYS = cv2.DAYS
HOURS = cv2.HOURS

OBJECTIVE_WEIGHTS = {
    "sixth": 50,
    "buchi": 10,
    "five": 30,
    "one": 80,
}


# ============================================================
# UTILITIES: solution representation + soft metric + HARD check
# ============================================================

def lessons_set(sol):
    """Ritorna lista di tuple (p, cl, subj, day, hour) con val=1."""
    return [k for k, v in sol.items() if v == 1]


def class_present(sol):
    """Index: (cl, day, hour) -> set di prof presenti (di solito 1)."""
    out = defaultdict(set)
    for (p, cl, subj, d, h), v in sol.items():
        if v == 1:
            out[(cl, d, h)].add(p)
    return out


def prof_present(sol):
    """Index: (p, day, hour) -> set di (cl, subj) presenti."""
    out = defaultdict(set)
    for (p, cl, subj, d, h), v in sol.items():
        if v == 1:
            out[(p, d, h)].add((cl, subj))
    return out


def class_day_hours(sol, cls_set):
    """Per ogni (cl, d): lista di hours occupate, ordinate."""
    cls_h = defaultdict(list)
    for (p, cl, subj, d, h), v in sol.items():
        if v == 1:
            cls_h[(cl, d)].append(h)
    out = {(cl, d): sorted(set(cls_h.get((cl, d), [])))
           for cl in cls_set for d in DAYS}
    return out


def prof_day_hours(sol, profs_set):
    pd_h = defaultdict(set)
    for (p, cl, subj, d, h), v in sol.items():
        if v == 1:
            pd_h[(p, d)].add(h)
    return {(p, d): sorted(pd_h.get((p, d), set()))
            for p in profs_set for d in DAYS}


def compute_soft(sol, profs, soft_rules=None):
    """Structural soft objective, optionally augmented with DSL SOFT rules.

    ``soft_rules`` (Subproject D) is an optional list of pre-parsed
    ``(tree, weight)`` pairs (see :func:`parse_soft_rules`). For every
    rule whose DSL expression is VIOLATED against the world derived from
    ``sol`` (``evaluate_safe`` returns ``ok=False``), ``weight`` is added
    to the objective. When ``soft_rules`` is falsy the function is
    byte-identical to the legacy structural-only path (zero-drift).
    """
    cls_set = sorted({c for p in profs.values() for c in p["classi"]})
    profs_set = sorted(profs.keys())
    cls_h = class_day_hours(sol, cls_set)
    pd_h = prof_day_hours(sol, profs_set)
    sixth = sum(1 for cl in cls_set for d in DAYS
                if 13 in cls_h.get((cl, d), []))
    buchi = 0
    five = 0
    one = 0
    for p in profs_set:
        for d in DAYS:
            hrs = pd_h.get((p, d), [])
            if not hrs:
                continue
            ld = len(hrs)
            if ld >= 2:
                buchi += hrs[-1] - hrs[0] + 1 - ld
            if ld == 5:
                five += 1
            if ld == 1:
                one += 1
    metrics = dict(sixth=sixth, buchi=buchi, five=five, one=one)
    val = (
        OBJECTIVE_WEIGHTS["sixth"] * sixth
        + OBJECTIVE_WEIGHTS["buchi"] * buchi
        + OBJECTIVE_WEIGHTS["five"] * five
        + OBJECTIVE_WEIGHTS["one"] * one
    )
    if soft_rules:
        soft_pen = 0
        try:
            try:
                from webui.backend.utils import (  # type: ignore
                    general_dsl as _gd)
            except ImportError:
                import sys as _sys
                _here = os.path.dirname(os.path.abspath(__file__))
                _root = os.path.dirname(_here)
                if _root not in _sys.path:
                    _sys.path.insert(0, _root)
                from webui.backend.utils import (  # type: ignore
                    general_dsl as _gd)
        except Exception:  # noqa: BLE001
            _gd = None
        if _gd is not None:
            world = _build_world_from_sol(sol, profs)
            for tree, weight in soft_rules:
                try:
                    ok, _ = _gd.evaluate_safe(tree, world)
                except Exception:  # noqa: BLE001
                    continue
                if not ok:
                    soft_pen += int(weight)
        val += soft_pen
        metrics = dict(metrics, dsl_soft=soft_pen)
    return val, metrics


def parse_soft_rules(rules):
    """Pre-parse DSL SOFT rule dicts into ``(tree, weight)`` pairs.

    ``rules`` is the list of dicts produced by
    ``dsl_translator.load_all_dsl_constraints`` (keys ``expression``,
    ``is_hard``, ``weight``, ``label``). HARD rules and rules with
    ``weight <= 0`` are skipped, as are any whose expression fails to
    parse. The returned list is consumable by ``compute_soft(...,
    soft_rules=...)``.
    """
    try:
        from webui.backend.utils import general_dsl as _gd  # type: ignore
    except ImportError:
        import sys as _sys
        _here = os.path.dirname(os.path.abspath(__file__))
        _root = os.path.dirname(_here)
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from webui.backend.utils import general_dsl as _gd  # type: ignore
    out = []
    for r in rules or []:
        if r.get("is_hard"):
            continue
        try:
            weight = int(r.get("weight", 0))
        except (TypeError, ValueError):
            continue
        if weight <= 0:
            continue
        expr = r.get("expression")
        if not expr:
            continue
        try:
            tree = _gd.parse(expr)
        except Exception:  # noqa: BLE001
            continue
        out.append((tree, weight))
    return out


def is_hard_feasible(sol, profs, verbose=False,
                     *, group_assignments=None,
                     coteach_groups=None,
                     parallel_groups=None,
                     support_assignments=None,
                     dsl_hard_expressions=None,
                     db=None):
    """Ritorna True se la soluzione rispetta tutti gli HARD.

    Task C1/C2/C3: optional checks for coteach (principal + codoc
    occupy the same slot but the class counts as busy ONCE),
    parallel intra-class (members share busy_key), sostegno
    (excluded from class-busy), and group_assignments
    (n_hours coverage + home_class busy mutual exclusion).

    DSL evaluation hook
    -------------------
    The canonical Phase B HARD checks (H1..H_C, coverage, coteach,
    parallel, support, groups) stay hardcoded -- they are the ground
    truth of the per-day Phase B problem and are mirrored 1:1 by
    ``cpsat_v2_timetable.solve_phase_b_for_day`` /
    ``cp_sat_constraint_model.PhaseBDaySolver``. On TOP of those,
    callers can supply DSL HARD rules to be evaluated against the
    solution dict via the post-hoc DSL evaluator.

    - ``dsl_hard_expressions``: list of DSL expression strings (as
      returned by ``dsl_translator.load_all_dsl_constraints``'s
      ``"expression"`` field). The function builds a sol/profs-derived
      ``world`` snapshot and evaluates each expression; returns False
      on the first violation.
    - ``db``: convenience -- when given (and
      ``dsl_hard_expressions`` is None), the function loads HARD DSL
      rules from the database via ``load_all_dsl_constraints`` and
      evaluates them against the in-memory solution. Skipped when
      both are absent (default), so the hardcoded behaviour is
      backward-compatible with every existing caller.
    """
    cls_set = sorted({c for p in profs.values() for c in p["classi"]})
    profs_set = sorted(profs.keys())
    # Build sets of (class, subject) keys whose multiple-Assignment
    # presence at the SAME slot is intentional (coteach + parallel
    # intra). For these the cl_count should treat all participants
    # as a single occupation.
    coteach_keys: set[tuple[str, str]] = set()
    for cg in (coteach_groups or []):
        coteach_keys.add((cg.get("class_name"), cg.get("subject")))
        # codocs may be on different (class, subject) but in C1
        # convention they all share (class_name, subject).
    parallel_busy_key: dict[tuple[str, str], str] = {}
    for pg in (parallel_groups or []):
        cl = pg.get("class_name")
        gid = pg.get("group_id")
        for m in pg.get("members", []):
            parallel_busy_key[(cl, m.get("subject"))] = (
                f"__par__{gid}")
    support_keys: set[tuple[str, str, str]] = set()
    for sa in (support_assignments or []):
        support_keys.add(
            (sa.get("teacher_name"), sa.get("class_name"),
             sa.get("subject"))
        )
    cls_h = class_day_hours(sol, cls_set)
    pd_h = prof_day_hours(sol, profs_set)

    # Class no-overlap: per (cl, d, h) max 1 occupazione, dove
    # principal+codoc di una compresenza condividono lo stesso slot
    # ma contano come UNA, e i membri di un parallel group intra
    # condividono la stessa busy_key. I sostegni sono esclusi dal
    # class-busy (segue la lezione, non aggiunge slot).
    cl_busy_keys: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    for (p, cl, subj, d, h), v in sol.items():
        if v != 1:
            continue
        if (p, cl, subj) in support_keys:
            continue                    # sostegno: not a class slot
        # Resolve busy_key for this (cl, subj):
        # - parallel intra members share __par__<gid>
        # - coteach (principal + codoc) share the subject (single)
        # - regular lessons use the subject string itself
        if (cl, subj) in parallel_busy_key:
            bkey = parallel_busy_key[(cl, subj)]
        elif (cl, subj) in coteach_keys:
            bkey = f"__cot__{cl}__{subj}"
        else:
            bkey = subj
        cl_busy_keys[(cl, d, h)].add(bkey)
    for k, keys in cl_busy_keys.items():
        if len(keys) > 1:
            if verbose:
                print(f"  CLASS-OVERLAP viol: {k} keys={keys}")
            return False

    # Prof no-overlap: per (p, d, h) max 1 lezione
    p_count = defaultdict(int)
    for (p, cl, subj, d, h), v in sol.items():
        if v == 1:
            p_count[(p, d, h)] += 1
    for k, c in p_count.items():
        if c > 1:
            if verbose:
                print(f"  PROF-OVERLAP viol: {k} count={c}")
            return False

    # Coverage: per ogni (p, cl, subj) la somma su (d, h) = ore.
    for p, info in profs.items():
        for cl, sm in info["classi"].items():
            for subj, meta in sm.items():
                got = sum(
                    sol.get((p, cl, subj, d, h), 0)
                    for d in DAYS for h in HOURS
                )
                if got != meta["ore"]:
                    if verbose:
                        print(f"  COVERAGE viol: ({p},{cl},{subj}) "
                              f"want {meta['ore']} got {got}")
                    return False

    # H1, H2, H3: classi.
    # We rebuild a sostegno/coteach/parallel-aware "class hours per
    # day" that mirrors what the solver enforces in Phase B
    # (sostegno is shadow, coteach members collapse to one slot,
    # parallel members share the slot, and group hours touching the
    # home class are counted as busy slots for that class).
    cls_hours_direct: dict[tuple[str, int], set[int]] = (
        defaultdict(set))
    cls_hours_groupextra: dict[tuple[str, int], set[int]] = (
        defaultdict(set))
    # Build the set of group-targeted (teacher, virtual_class, subj)
    # so we can tell apart "this is a regular lesson" from "this is
    # a group lesson". A regular (non-group) Assignment has a key
    # whose `cl` is in `cls_set`; a group lesson's `cl` is the
    # group_name (not in cls_set).
    grp_keys: set[tuple[str, str, str]] = set()
    home_by_grp: dict[tuple[str, str], list[str]] = {}
    if group_assignments:
        for ga in group_assignments:
            grp_keys.add(
                (ga["teacher_name"], ga["group_name"], ga["subject"]))
            home_by_grp[
                (ga["group_name"], ga["subject"])
            ] = list(ga.get("home_class_names", []))
    for (p, cl, subj, d, h), v in sol.items():
        if v != 1:
            continue
        if (p, cl, subj) in support_keys:
            continue
        if (p, cl, subj) in grp_keys:
            # Group lesson: register as group-extra for every home
            # class.
            for hc in home_by_grp.get((cl, subj), []):
                cls_hours_groupextra[(hc, d)].add(h)
            continue
        # Regular class lesson (or coteach/parallel member, which
        # share the slot in the same class anyway).
        cls_hours_direct[(cl, d)].add(h)
    for cl in cls_set:
        for d in DAYS:
            direct = cls_hours_direct.get((cl, d), set())
            extra = cls_hours_groupextra.get((cl, d), set())
            # H1/H2/H3 apply only when the class has direct triples
            # on this day; pure group-only days are exempt (matches
            # the solver's `cls_with_direct_triples` gate).
            if not direct:
                continue
            hrs = sorted(direct | extra)
            if hrs[0] != 8:
                if verbose: print(f"  H2 viol: {cl} d{d} hrs[0]={hrs[0]}")
                return False
            for i, h in enumerate(hrs):
                if h != hrs[0] + i:
                    if verbose: print(f"  H1 viol: {cl} d{d} hrs={hrs}")
                    return False
            if 11 not in hrs:
                if verbose: print(f"  H3 viol: {cl} d{d} hrs={hrs}")
                return False

    # H_C: prof max 5 ore consecutive (= max 5 totali in [8..13]
    # perche\` no-holes prof? Falso, il prof puo\` avere buchi. Ma
    # 6 ore in giornata = tutti 6 gli slot occupati = 6 consecutive
    # banner.)
    for p in profs_set:
        for d in DAYS:
            hrs = pd_h.get((p, d), [])
            if len(hrs) >= 6:
                if hrs == list(range(hrs[0], hrs[0] + 6)):
                    if verbose: print(f"  HC viol: prof {p} d{d}")
                    return False

    # H_A: Mat/Ita doppia consecutiva del prof in classe (almeno 1
    # nella settimana, qualunque materia stesso prof).
    for cl in cls_set:
        for subject in ("Matematica", "Italiano"):
            p = cv2.find_prof_subject(profs, cl, subject)
            if p is None or cl not in profs[p]["classi"]:
                continue
            tot = sum(profs[p]["classi"][cl][s]["ore"]
                      for s in profs[p]["classi"][cl])
            if tot < 2:
                continue
            ok = False
            for d in DAYS:
                pres = []
                for h in HOURS:
                    have = any(
                        sol.get((p, cl, s, d, h), 0) == 1
                        for s in profs[p]["classi"][cl]
                    )
                    pres.append(have)
                for i in range(len(pres) - 1):
                    if pres[i] and pres[i + 1]:
                        ok = True
                        break
                if ok:
                    break
            if not ok:
                if verbose: print(f"  HA viol: {subject} {p} in {cl}")
                return False

    # H_B: Scienzemotorie sempre a coppie. Per ogni (cl, d) le ore
    # del prof di motorie (in qualsiasi materia ma tipicamente
    # "Scienzemotorie") devono essere 0 o 2-consecutive.
    for cl in cls_set:
        p = cv2.find_prof_subject(profs, cl, "Scienzemotorie")
        if p is None:
            continue
        for d in DAYS:
            hrs = sorted(
                h for h in HOURS
                if sol.get((p, cl, "Scienzemotorie", d, h), 0) == 1
            )
            if not hrs:
                continue
            if len(hrs) != 2 or hrs[1] != hrs[0] + 1:
                if verbose: print(f"  HB viol: motorie {cl} d{d} hrs={hrs}")
                return False

    # Task C3: validate group_assignments invariants when provided.
    if group_assignments:
        for ga in group_assignments:
            t = ga["teacher_name"]
            gn = ga["group_name"]
            sub = ga["subject"]
            n = int(ga["n_hours"])
            got = sum(
                sol.get((t, gn, sub, d, h), 0)
                for d in DAYS for h in HOURS
            )
            if got != n:
                if verbose:
                    print(f"  C3 group COVERAGE viol: {t}/{gn}/"
                          f"{sub} want {n} got {got}")
                return False
        # Build the per-group home_class map and validate that each
        # group lesson slot doesn't collide with a regular lesson
        # in any home class.
        home_by_grp_subj: dict[tuple[str, str], list[str]] = {}
        for ga in group_assignments:
            home_by_grp_subj.setdefault(
                (ga["group_name"], ga["subject"]),
                ga.get("home_class_names", []))
        for (t, cl, subj, d, h), v in sol.items():
            if v != 1:
                continue
            home = home_by_grp_subj.get((cl, subj))
            if home is None:
                continue          # not a group lesson
            for home_cl in home:
                # is there another (non-group) lesson on this home
                # class at the same (d, h)?
                conflict = any(
                    sol.get((tt, home_cl, ss, d, h), 0) == 1
                    for tt in profs_set
                    for ss in profs.get(tt, {}).get(
                        "classi", {}).get(home_cl, {}).keys()
                )
                if conflict:
                    if verbose:
                        print(f"  C3 home-class busy viol: group "
                              f"{cl}/{subj} at ({d},{h}) but "
                              f"home {home_cl} also busy")
                    return False

    # ----- DSL HARD layer (DB-driven rules, opt-in) -----
    # Resolve the list of expressions to check. ``dsl_hard_expressions``
    # takes precedence; if absent and ``db`` is given, load HARD rules
    # from the DB via the unified loader. When both are absent the
    # block is a no-op (preserving zero-drift on every existing call
    # site that doesn't pass a DB).
    expressions = dsl_hard_expressions
    if expressions is None and db is not None:
        try:
            try:
                from . import dsl_translator as _dt  # type: ignore
            except ImportError:
                import dsl_translator as _dt  # type: ignore
            rules = _dt.load_all_dsl_constraints(
                db, include_soft=False)
            expressions = [r["expression"] for r in rules
                           if r.get("is_hard")]
        except Exception as exc:  # noqa: BLE001
            if verbose:
                print(f"  DSL load failed: {type(exc).__name__}:{exc}")
            expressions = []
    if expressions:
        try:
            try:
                from webui.backend.utils import (  # type: ignore
                    general_dsl as _gd)
            except ImportError:
                import sys as _sys
                _here = os.path.dirname(os.path.abspath(__file__))
                _root = os.path.dirname(_here)
                if _root not in _sys.path:
                    _sys.path.insert(0, _root)
                from webui.backend.utils import (  # type: ignore
                    general_dsl as _gd)
        except Exception as exc:  # noqa: BLE001
            if verbose:
                print(f"  DSL evaluator unavailable: "
                      f"{type(exc).__name__}:{exc}")
            return True
        world = _build_world_from_sol(
            sol, profs,
            group_assignments=group_assignments,
            coteach_groups=coteach_groups,
            parallel_groups=parallel_groups,
            support_assignments=support_assignments,
        )
        for expr in expressions:
            try:
                tree = _gd.parse(expr)
                ok, err = _gd.evaluate_safe(tree, world)
            except Exception as exc:  # noqa: BLE001
                if verbose:
                    print(f"  DSL parse failed: {expr!r} -> {exc}")
                continue
            if not ok:
                if verbose:
                    print(f"  DSL HARD viol: {expr!r}"
                          + (f" err={err}" if err else ""))
                return False

    return True


def _build_world_from_sol(sol, profs, *,
                           group_assignments=None,
                           coteach_groups=None,
                           parallel_groups=None,
                           support_assignments=None) -> dict:
    """Construct a ``world`` snapshot for the DSL post-hoc evaluator
    from an in-memory metaheuristic solution dict.

    The DSL evaluator (``general_dsl.evaluate``) consumes a dict with
    keys ``lessons``, ``teachers``, ``classes``, ``classrooms``,
    ``subjects``, ``days``, ``hours``, ``slots``, ``assignments``.
    Metaheuristics work without a DB session, so we only populate the
    parts that can be derived from ``sol`` + ``profs``: lessons (the
    placed slots), and the entity tables in their bare form.

    Classroom-level fields (``l.classroom``, ``l.classroom.type``,
    ``l.classroom.plesso``) are not available pre-classroom-assignment;
    DSL rules touching these will not match (the evaluator returns
    ``None`` for missing attributes which makes equality predicates
    false). That is consistent with the metaheuristics phase running
    before classroom assignment.
    """
    teacher_set = sorted(profs.keys())
    class_set = sorted({c for p in profs.values()
                        for c in p.get("classi", {})})
    subj_set = sorted({
        s
        for p in profs.values()
        for c in p.get("classi", {}).values()
        for s in c.keys()
    })
    # ``lessons`` from sol: every slot with v == 1 becomes a lesson dict
    # in the DSL world's expected shape. Group lessons (cl == group_name)
    # are filtered out so DSL rules indexed by class name don't match
    # the virtual group as a regular class.
    grp_keys: set[tuple[str, str, str]] = set()
    if group_assignments:
        for ga in group_assignments:
            grp_keys.add(
                (ga.get("teacher_name"),
                 ga.get("group_name"),
                 ga.get("subject")))
    lessons = []
    for (p, cl, subj, d, h), v in sol.items():
        if int(v) != 1:
            continue
        lessons.append({
            "teacher": p,
            "class": cl,
            "class_curriculum": "",
            "subject": subj,
            "day": int(d),
            "hour": int(h),
            "classroom": "",
            "classroom_type": "",
            "classroom_kind": "",
            "classroom_tags": [],
            "classroom_plesso": None,
            "slot": (int(d), int(h)),
            "_is_group": (p, cl, subj) in grp_keys,
        })
    # Assignments derived from profs: every (teacher, class, subject,
    # ore) cattedra.
    assignments = []
    for t, info in profs.items():
        for cl, sm in info.get("classi", {}).items():
            for s, meta in sm.items():
                assignments.append({
                    "teacher": t,
                    "class": cl,
                    "subject": s,
                    "hours": int(meta.get("ore", 0)),
                    "locked": False,
                })
    return {
        "teachers": [{"name": t, "group": "", "max_hours": 0,
                      "free_day": None, "graduatoria_score": 0,
                      "completion_hours": 0, "exemption_hours": 0,
                      "subject": [], "subjects": []}
                     for t in teacher_set],
        "classes": [{"name": c, "year": 0, "section": "",
                     "curriculum": "", "n_students": 0}
                    for c in class_set],
        "classrooms": [],
        "subjects": [{"name": s} for s in subj_set],
        "curricula": [],
        "students": [],
        "groups": [],
        "days": [{"index": d, "name": ""} for d in DAYS],
        "hours": [{"index": h} for h in HOURS],
        "slots": [{"day": d, "hour": h} for d in DAYS for h in HOURS],
        "assignments": assignments,
        "lessons": lessons,
    }


def deepcopy_sol(sol):
    return dict(sol)


def find_best_sol(sols, profs):
    best = None
    best_val = None
    for s in sols:
        v, _ = compute_soft(s, profs)
        if best_val is None or v < best_val:
            best_val, best = v, s
    return best, best_val


# ============================================================
# LNS: Large Neighborhood Search (uses CP-SAT)
# ============================================================

def _cp_repair(sol, profs, dc_value, free_keys, time_limit, workers=4,
               *,
               coteach_groups=None,
               support_assignments=None,
               parallel_groups=None,
               group_assignments=None,
               db=None,
               via_dsl=False,
               extra_dsl_expressions=None):
    """OO repair via ``PhaseBDaySolver``.

    The free variables are those whose 5-tuple key is in ``free_keys``;
    every other placed slot for the affected days is locked to its
    current value via ``locked_slots_for_day``. Each affected day is
    rebuilt by an independent ``PhaseBDaySolver.solve()`` call, which
    is the canonical OO entry point for the per-day Phase B problem
    (it composes over the legacy function for zero-drift but exposes
    the OO surface used uniformly across the DSL+OO paradigm).

    Coteach / sostegno / parallel / group assignments are forwarded
    through the solver's keyword arguments so the C3 invariants
    (slot-equality, group-home-class busy propagation, etc.) are
    enforced just as in the monolithic Phase B path.

    DSL augmentation: when ``db`` is given (or
    ``extra_dsl_expressions`` is non-empty) and ``via_dsl=True``,
    the solver pulls DB-side rules and any extra expressions through
    the DSL compiler as an additional HARD layer on top of the
    legacy hardcoded constraints. This is the single-source-of-truth
    path used by the rest of the DSL+OO pipeline (Phase B mono, BP
    pricers, ...). ``via_dsl=False`` (the default) keeps the legacy
    hardcoded behaviour with zero overhead.

    Returns ``(new_sol, success)``.
    """
    try:
        from . import cp_sat_constraint_model as _csm  # type: ignore
    except ImportError:
        import cp_sat_constraint_model as _csm  # type: ignore

    days_to_repair = sorted({k[3] for k in free_keys})
    new_sol = deepcopy_sol(sol)
    classes, triples, class_profs = cv2.build_indices(profs)

    for day in days_to_repair:
        free_in_day = {k for k in free_keys if k[3] == day}
        # Per-day locks: every placed (value==1) slot for this day
        # that is NOT in free_keys is forced to 1 by the day solver.
        locks_today = [
            (p, cl, s, h)
            for (p, cl, s, dd, h), v in new_sol.items()
            if dd == day and int(v) == 1
            and (p, cl, s, dd, h) not in free_in_day
        ]
        solver = _csm.PhaseBDaySolver(
            profs, dc_value, day,
            classes=classes, triples=triples,
            class_profs=class_profs,
            db=db,
            extra_dsl_expressions=list(extra_dsl_expressions or []),
        )
        out, _status = solver.solve(
            time_limit_s=float(time_limit),
            workers=int(workers),
            log=False,
            via_dsl=bool(via_dsl),
            locked_slots_for_day=locks_today,
            coteach_groups=coteach_groups,
            support_assignments=support_assignments,
            parallel_groups=parallel_groups,
            group_assignments=group_assignments,
        )
        if out is None:
            return None, False
        # Replace the day's slots with the new assignment.
        # ``PhaseBDaySolver.solve`` strips zero-valued entries, so we
        # zero out the day first and then update with the v==1 keys.
        for k in list(new_sol.keys()):
            if k[3] == day:
                new_sol[k] = 0
        new_sol.update(out)
    return new_sol, True


def neighborhood_one_day(sol, profs, day):
    """Free tutte le variabili di quel giorno."""
    return {k for k in sol if k[3] == day}


def neighborhood_one_prof_one_day(sol, profs, prof, day):
    """Free le variabili di un prof in un giorno."""
    return {k for k in sol if k[0] == prof and k[3] == day}


def neighborhood_one_prof_week(sol, profs, prof):
    """Free tutte le variabili di un prof in tutta la settimana."""
    return {k for k in sol if k[0] == prof}


def neighborhood_cluster_day(sol, profs, classes_in_cluster, day):
    """Free le variabili delle classi del cluster in un giorno."""
    return {k for k in sol if k[1] in classes_in_cluster and k[3] == day}


def run_lns(sol, profs, dc_value, time_budget_s,
            classes_clusters=None, log=True, workers=4,
            adaptive=True, locks=None,
            *,
            coteach_groups=None,
            support_assignments=None,
            parallel_groups=None,
            group_assignments=None,
            db=None,
            via_dsl=False,
            extra_dsl_expressions=None,
            soft_rules=None):
    """Esegui Large Neighborhood Search per `time_budget_s` secondi.

    Se `adaptive=True` (default), gli operator non sono scelti uniformi
    ma con probabilita' proporzionali al delta_soft medio che ognuno ha
    prodotto fin qui (algoritmo "score" classico per Adaptive LNS).
    Inizialmente tutti gli operator hanno punteggio uguale; dopo i primi
    successi/fallimenti lo schema bias-a verso chi paga di piu'.

    Se `locks` e' un set di tuple (p, cl, s, d, h), tali variabili
    NON vengono mai liberate dai destroy operator: restano fissate al
    valore corrente (== 1) e _cp_repair le tratta come constraint.

    Restituisce (best_sol, log_entries).
    """
    rng = random.Random(42)
    best = deepcopy_sol(sol)
    best_val, _ = compute_soft(best, profs, soft_rules=soft_rules)
    init_val = best_val
    profs_list = sorted(profs.keys())
    classes_list = sorted({c for p in profs.values() for c in p["classi"]})
    log_entries = []
    t_start = time.time()
    iter_count = 0

    # Adaptive scoring: per ogni operator memorizziamo
    #   total_delta: somma dei (best_val_pre - new_val) per i successi
    #   n_calls:     numero di chiamate (incluse le reject e infeasible)
    # Score = 1.0 + total_delta / max(n_calls, 1).
    # Se l'operator non ha mai migliorato, mantiene baseline 1.0.
    # Quando un operator e' >> degli altri, riceve piu' chiamate.
    op_stats = defaultdict(lambda: dict(total_delta=0, n_calls=0))

    def op_score(name):
        s = op_stats[name]
        if s["n_calls"] == 0:
            return 1.0
        return 1.0 + max(0, s["total_delta"]) / s["n_calls"]

    while time.time() - t_start < time_budget_s:
        iter_count += 1
        # Lista di operator disponibili
        ops = ["one_day", "prof_day", "prof_week"]
        if classes_clusters:
            ops.append("cluster_day")
        # Scegli operator: random pesato in modalita' adaptive
        if adaptive:
            weights = [op_score(o) for o in ops]
            op = rng.choices(ops, weights=weights, k=1)[0]
        else:
            op = rng.choice(ops)
        if op == "one_day":
            d = rng.choice(DAYS)
            free = neighborhood_one_day(best, profs, d)
            time_local = min(15, time_budget_s / 4)
        elif op == "prof_day":
            p = rng.choice(profs_list)
            d = rng.choice(DAYS)
            free = neighborhood_one_prof_one_day(best, profs, p, d)
            time_local = min(5, time_budget_s / 6)
        elif op == "prof_week":
            p = rng.choice(profs_list)
            free = neighborhood_one_prof_week(best, profs, p)
            time_local = min(20, time_budget_s / 4)
        else:                                      # cluster_day
            cluster_idx = rng.choice(list(classes_clusters.keys()))
            cl_set = classes_clusters[cluster_idx]
            d = rng.choice(DAYS)
            free = neighborhood_cluster_day(best, profs, cl_set, d)
            time_local = min(20, time_budget_s / 4)
        # Filter out locked keys: they must remain 1, the destroy
        # operators must not free them.
        if locks:
            free = {k for k in free if k not in locks}
        if not free:
            continue
        new_sol, ok = _cp_repair(
            best, profs, dc_value, free, time_local, workers=workers,
            coteach_groups=coteach_groups,
            support_assignments=support_assignments,
            parallel_groups=parallel_groups,
            group_assignments=group_assignments,
            db=db, via_dsl=via_dsl,
            extra_dsl_expressions=extra_dsl_expressions,
        )
        op_stats[op]["n_calls"] += 1
        if not ok:
            log_entries.append(
                (iter_count, op, "infeasible", best_val, best_val)
            )
            continue
        new_val, _ = compute_soft(new_sol, profs, soft_rules=soft_rules)
        if new_val < best_val:
            op_stats[op]["total_delta"] += (best_val - new_val)
            log_entries.append(
                (iter_count, op, "accept", best_val, new_val)
            )
            best = new_sol
            best_val = new_val
            if log:
                print(f"  [LNS iter {iter_count}] {op}: "
                      f"{log_entries[-1][3]} -> {new_val} (improvement)")
        else:
            log_entries.append(
                (iter_count, op, "reject", best_val, new_val)
            )
    if log:
        # Riassunto adaptive scores
        scores = {o: round(op_score(o), 1) for o in op_stats}
        calls = {o: op_stats[o]["n_calls"] for o in op_stats}
        print(f"  [LNS] {iter_count} iter, "
              f"obj {init_val} -> {best_val} "
              f"({100.0 * (init_val - best_val) / max(init_val, 1):.1f}% imp)"
              f" | calls={calls} scores={scores}")
    return best, log_entries


# ============================================================
# Mosse atomiche per SA / TS (preservano HARD)
# ============================================================

def _swap_two_lessons_same_prof(sol, profs, dc_value, rng, locks=None,
                                 *, group_assignments=None,
                                 dsl_hard_expressions=None):
    """Tenta uno swap di 2 slot dello stesso prof (cambia hour).
    Restituisce nuova_sol o None se non valida.

    `locks` (optional): set of (p, cl, s, d, h) tuples that must
    stay at value 1. Any swap touching a locked key is rejected.
    """
    profs_list = list(profs.keys())
    rng.shuffle(profs_list)
    for p in profs_list:
        for d in rng.sample(DAYS, len(DAYS)):
            occupied = [(k, v) for k, v in sol.items()
                        if k[0] == p and k[3] == d and v == 1]
            if len(occupied) < 2:
                continue
            (k1, _), (k2, _) = rng.sample(occupied, 2)
            if locks and (k1 in locks or k2 in locks):
                continue
            new_sol = dict(sol)
            new_sol[k1] = 0
            new_sol[k2] = 0
            new_k1 = (k1[0], k1[1], k1[2], k1[3], k2[4])
            new_k2 = (k2[0], k2[1], k2[2], k2[3], k1[4])
            new_sol[new_k1] = 1
            new_sol[new_k2] = 1
            if is_hard_feasible(
                    new_sol, profs,
                    group_assignments=group_assignments,
                    dsl_hard_expressions=dsl_hard_expressions):
                return new_sol
            return None
    return None


def _move_lesson_to_empty_slot(sol, profs, dc_value, rng, locks=None,
                                *, group_assignments=None,
                                dsl_hard_expressions=None):
    """Sposta una singola lezione (p, cl, s, d, h) a (p, cl, s, d, h')
    con h' libero per il prof e per la classe.

    `locks` (optional): a locked key is never moved."""
    occupied = [k for k, v in sol.items() if v == 1]
    rng.shuffle(occupied)
    for k in occupied[:50]:                    # limita tentativi
        if locks and k in locks:
            continue
        p, cl, s, d, h_old = k
        for h_new in rng.sample(HOURS, len(HOURS)):
            if h_new == h_old:
                continue
            new_k = (p, cl, s, d, h_new)
            if sol.get(new_k, 0) == 1:
                continue
            new_sol = dict(sol)
            new_sol[k] = 0
            new_sol[new_k] = 1
            if is_hard_feasible(
                    new_sol, profs,
                    group_assignments=group_assignments,
                    dsl_hard_expressions=dsl_hard_expressions):
                return new_sol
    return None


def _swap_two_lessons_same_class(sol, profs, dc_value, rng, locks=None,
                                  *, group_assignments=None,
                                  dsl_hard_expressions=None):
    """Swap fra due lezioni della stessa classe (potenzialmente prof
    diversi) in slot diversi nello stesso giorno.

    `locks` (optional): swaps touching a locked key are rejected."""
    cls_set = sorted({c for p in profs.values() for c in p["classi"]})
    rng.shuffle(cls_set)
    for cl in cls_set[:20]:
        for d in rng.sample(DAYS, len(DAYS)):
            occupied = [(k, v) for k, v in sol.items()
                        if k[1] == cl and k[3] == d and v == 1]
            if len(occupied) < 2:
                continue
            (k1, _), (k2, _) = rng.sample(occupied, 2)
            if locks and (k1 in locks or k2 in locks):
                continue
            new_sol = dict(sol)
            new_sol[k1] = 0
            new_sol[k2] = 0
            new_k1 = (k1[0], k1[1], k1[2], k1[3], k2[4])
            new_k2 = (k2[0], k2[1], k2[2], k2[3], k1[4])
            new_sol[new_k1] = 1
            new_sol[new_k2] = 1
            if is_hard_feasible(
                    new_sol, profs,
                    group_assignments=group_assignments,
                    dsl_hard_expressions=dsl_hard_expressions):
                return new_sol
    return None


ATOMIC_MOVES = [
    _swap_two_lessons_same_prof,
    _move_lesson_to_empty_slot,
    _swap_two_lessons_same_class,
]


# ============================================================
# Simulated Annealing
# ============================================================

def run_sa(sol, profs, dc_value, time_budget_s,
           T0=10.0, alpha=0.995, log=True, locks=None,
           *,
           coteach_groups=None,
           support_assignments=None,
           parallel_groups=None,
           group_assignments=None,
           db=None,
           dsl_hard_expressions=None,
           soft_rules=None):
    rng = random.Random(123)
    best = dict(sol)
    cur = dict(sol)
    best_val, _ = compute_soft(best, profs, soft_rules=soft_rules)
    cur_val = best_val
    init_val = best_val
    T = T0
    iter_count = 0
    n_acc = 0
    n_imp = 0
    t_start = time.time()
    while time.time() - t_start < time_budget_s:
        iter_count += 1
        move_fn = rng.choice(ATOMIC_MOVES)
        new_sol = move_fn(cur, profs, dc_value, rng, locks=locks,
                          group_assignments=group_assignments,
                          dsl_hard_expressions=dsl_hard_expressions)
        if new_sol is None:
            T *= alpha
            continue
        new_val, _ = compute_soft(new_sol, profs, soft_rules=soft_rules)
        delta = new_val - cur_val
        if delta < 0 or rng.random() < math.exp(-delta / max(T, 0.01)):
            cur = new_sol
            cur_val = new_val
            n_acc += 1
            if cur_val < best_val:
                best = dict(cur)
                best_val = cur_val
                n_imp += 1
        T *= alpha
    if log:
        print(f"  [SA] {iter_count} iter, accept={n_acc}, "
              f"improve={n_imp}, obj {init_val} -> {best_val} "
              f"({100.0 * (init_val - best_val) / max(init_val, 1):.1f}%)")
    return best


# ============================================================
# Tabu Search
# ============================================================

def run_tabu(sol, profs, dc_value, time_budget_s,
             tabu_size=80, log=True, locks=None,
             *,
             coteach_groups=None,
             support_assignments=None,
             parallel_groups=None,
             group_assignments=None,
             db=None,
             dsl_hard_expressions=None,
             soft_rules=None):
    rng = random.Random(456)
    best = dict(sol)
    cur = dict(sol)
    best_val, _ = compute_soft(best, profs, soft_rules=soft_rules)
    cur_val = best_val
    init_val = best_val
    tabu = []                                  # FIFO ring buffer di hash
    iter_count = 0
    no_improve = 0
    t_start = time.time()
    n_imp = 0
    while time.time() - t_start < time_budget_s:
        iter_count += 1
        # Genera fino a 30 candidati e prendi il migliore non-tabu
        candidates = []
        for _ in range(30):
            move_fn = rng.choice(ATOMIC_MOVES)
            new_sol = move_fn(cur, profs, dc_value, rng, locks=locks,
                              group_assignments=group_assignments,
                              dsl_hard_expressions=dsl_hard_expressions)
            if new_sol is None:
                continue
            new_val, _ = compute_soft(new_sol, profs, soft_rules=soft_rules)
            # Hash (semplice) della soluzione
            h = hash(frozenset(
                k for k, v in new_sol.items() if v == 1
            ))
            tabu_block = h in tabu
            # Aspirazione: ammessa se migliora il best
            if tabu_block and new_val >= best_val:
                continue
            candidates.append((new_val, h, new_sol))
        if not candidates:
            no_improve += 1
            if no_improve > 100:
                break
            continue
        candidates.sort(key=lambda x: x[0])
        new_val, h, new_sol = candidates[0]
        cur = new_sol
        cur_val = new_val
        tabu.append(h)
        if len(tabu) > tabu_size:
            tabu.pop(0)
        if cur_val < best_val:
            best = dict(cur)
            best_val = cur_val
            n_imp += 1
            no_improve = 0
        else:
            no_improve += 1
    if log:
        print(f"  [TS] {iter_count} iter, improve={n_imp}, "
              f"obj {init_val} -> {best_val} "
              f"({100.0 * (init_val - best_val) / max(init_val, 1):.1f}%)")
    return best


# ============================================================
# ILS = TS + perturbazione + TS
# ============================================================

def _perturb(sol, profs, dc_value, rng,
             classes_clusters=None, time_limit=15,
             *,
             coteach_groups=None,
             support_assignments=None,
             parallel_groups=None,
             group_assignments=None,
             db=None,
             via_dsl=False,
             extra_dsl_expressions=None):
    """Perturbazione: prendi una zona e usa CP-SAT per re-randomizzare
    (mantiene HARD)."""
    # Strategia: scegli un cluster random + 2 giorni random e libera
    if classes_clusters:
        cluster_idx = rng.choice(list(classes_clusters.keys()))
        cl_set = classes_clusters[cluster_idx]
        days_chosen = rng.sample(DAYS, 2)
        free = set()
        for d in days_chosen:
            free |= {
                k for k in sol
                if k[1] in cl_set and k[3] == d
            }
    else:
        days_chosen = rng.sample(DAYS, 2)
        free = {k for k in sol if k[3] in days_chosen}
    new_sol, ok = _cp_repair(
        sol, profs, dc_value, free, time_limit, workers=4,
        coteach_groups=coteach_groups,
        support_assignments=support_assignments,
        parallel_groups=parallel_groups,
        group_assignments=group_assignments,
        db=db, via_dsl=via_dsl,
        extra_dsl_expressions=extra_dsl_expressions,
    )
    return new_sol if ok else dict(sol)


def run_ils(sol, profs, dc_value, time_budget_s,
            classes_clusters=None, ts_budget_per_cycle=60,
            n_cycles=3, log=True, lns_kick=True,
            lns_kick_budget=8.0, locks=None,
            *,
            coteach_groups=None,
            support_assignments=None,
            parallel_groups=None,
            group_assignments=None,
            db=None,
            via_dsl=False,
            extra_dsl_expressions=None,
            dsl_hard_expressions=None,
            soft_rules=None):
    """Iterated Local Search.

    Sequenza per ogni ciclo:
      1. local_search = run_tabu (greedy with tabu list)
      2. perturb     = se `lns_kick=True`, run_lns su una porzione di
                       budget breve (default 8s); cosi' il "kick" e'
                       un mini-LNS a 2-3 iterazioni invece del singolo
                       _perturb (CP repair + 2 giorni). Cosi' ILS
                       beneficia dell'adaptive LNS scoring.
                       Se `lns_kick=False`, fallback al perturb
                       basico (CP repair su 2 giorni random).
    """
    rng = random.Random(789)
    best = dict(sol)
    best_val, _ = compute_soft(best, profs, soft_rules=soft_rules)
    init_val = best_val
    cur = dict(sol)
    t_start = time.time()
    cycle = 0
    while cycle < n_cycles and time.time() - t_start < time_budget_s:
        cycle += 1
        rem = time_budget_s - (time.time() - t_start)
        local_t = min(ts_budget_per_cycle, rem * 0.7)
        if log:
            print(f"  [ILS cycle {cycle}] TS for {local_t:.0f}s")
        cur = run_tabu(cur, profs, dc_value, local_t, log=False,
                       locks=locks,
                       coteach_groups=coteach_groups,
                       support_assignments=support_assignments,
                       parallel_groups=parallel_groups,
                       group_assignments=group_assignments,
                       db=db,
                       dsl_hard_expressions=dsl_hard_expressions,
                       soft_rules=soft_rules)
        cur_val, _ = compute_soft(cur, profs, soft_rules=soft_rules)
        if cur_val < best_val:
            best = dict(cur)
            best_val = cur_val
        rem = time_budget_s - (time.time() - t_start)
        if rem <= 0:
            break
        if lns_kick and rem >= lns_kick_budget:
            # LNS kick: 2-3 iterazioni di adaptive LNS = perturb piu'
            # ricco del semplice _perturb. Le mosse risultanti sono
            # ancora HARD-feasible per costruzione di _cp_repair.
            if log:
                print(f"  [ILS cycle {cycle}] LNS kick "
                      f"({lns_kick_budget:.0f}s)")
            cur, _ = run_lns(
                cur, profs, dc_value,
                min(lns_kick_budget, rem * 0.3),
                classes_clusters=classes_clusters,
                log=False, locks=locks,
                coteach_groups=coteach_groups,
                support_assignments=support_assignments,
                parallel_groups=parallel_groups,
                group_assignments=group_assignments,
                db=db, via_dsl=via_dsl,
                extra_dsl_expressions=extra_dsl_expressions,
                soft_rules=soft_rules,
            )
        else:
            if log:
                print(f"  [ILS cycle {cycle}] perturb")
            cur = _perturb(cur, profs, dc_value, rng,
                           classes_clusters=classes_clusters,
                           coteach_groups=coteach_groups,
                           support_assignments=support_assignments,
                           parallel_groups=parallel_groups,
                           group_assignments=group_assignments,
                           db=db, via_dsl=via_dsl,
                           extra_dsl_expressions=extra_dsl_expressions)
    if log:
        print(f"  [ILS] {cycle} cycles, obj {init_val} -> {best_val} "
              f"({100.0 * (init_val - best_val) / max(init_val, 1):.1f}%)")
    return best


# ============================================================
# Cascade orchestrator
# ============================================================

def run_cascade(sol, profs, dc_value, budgets,
                classes_clusters=None, log=True):
    r"""Esegue LNS -> SA -> TS -> ILS in cascata.
    `budgets`: dict con keys 'lns', 'sa', 'ts', 'ils' -> secondi.
    Restituisce (best_sol, history) dove history e\` lista di
    (stage_name, time_used, obj_value, metrics).
    """
    history = []
    cur = dict(sol)
    val0, m0 = compute_soft(cur, profs)
    history.append(("initial", 0.0, val0, m0))
    if log:
        print(f"[cascade] initial obj={val0} metrics={m0}")
    for stage in ("lns", "sa", "ts", "ils"):
        budget = budgets.get(stage, 0)
        if budget <= 0:
            continue
        t0 = time.time()
        if log:
            print(f"\n[cascade] === STAGE {stage.upper()} (budget {budget}s) ===")
        if stage == "lns":
            cur, _ = run_lns(cur, profs, dc_value, budget,
                             classes_clusters=classes_clusters, log=log)
        elif stage == "sa":
            cur = run_sa(cur, profs, dc_value, budget, log=log)
        elif stage == "ts":
            cur = run_tabu(cur, profs, dc_value, budget, log=log)
        elif stage == "ils":
            cur = run_ils(cur, profs, dc_value, budget,
                          classes_clusters=classes_clusters,
                          ts_budget_per_cycle=budget / 4,
                          n_cycles=3, log=log)
        dt = time.time() - t0
        val, m = compute_soft(cur, profs)
        history.append((stage, dt, val, m))
        if log:
            print(f"[cascade] {stage} done in {dt:.1f}s, obj={val} metrics={m}")
    return cur, history
