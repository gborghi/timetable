r"""Engine diagnostic + repair helpers.

Tre funzioni ad alto livello che la UI puo' chiamare (via backend):

  1. repair_slot_neighborhood(sol, profs, dc_value, scope, time_budget)
     Ri-ottimizza una piccola "zona" della soluzione (es. una sola
     classe in un giorno, oppure un docente per tutta la settimana)
     usando LNS warm-started dalla soluzione attiva. Risultato:
     soluzione potenzialmente migliore con stessi HARD ok.

  2. explain_infeasibility(profs, dc_value, day)
     Quando Phase B fallisce su un giorno, ritorna una analisi
     strutturata: violazioni del vincolo Hall (prof-hours > max
     class-load), classi con cl_day_load nel range proibito, ecc.

  3. why_not_lesson(sol, profs, lesson, target_day, target_hour)
     Prova a mettere `lesson` in (target_day, target_hour); ritorna la
     lista degli HARD violati che impediscono la mossa.

Tutte e tre sono pure funzioni del solver state. Non scrivono pickle,
non fanno I/O di rete. Il backend si aggancera' a queste API quando il
P1 di sezione 3.4 (frontend "ottimizza zona") sara' implementato lato
UI -- per il momento sono callable dai test e da script ad-hoc.
"""
from __future__ import annotations

import os
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import cpsat_v2_timetable as cv2  # noqa: E402
import metaheuristics as meta  # noqa: E402

DAYS = cv2.DAYS
HOURS = cv2.HOURS


# ============================================================
# 1) repair_slot_neighborhood
# ============================================================

def _free_keys_for_scope(sol, scope):
    r"""Calcola free_keys per una scope:

      scope = {'kind': 'class_day',  'class': 'X', 'day': 3}
            | {'kind': 'class_week', 'class': 'X'}
            | {'kind': 'prof_day',   'prof': 'P', 'day': 3}
            | {'kind': 'prof_week',  'prof': 'P'}
            | {'kind': 'one_day',    'day': 3}
    """
    kind = scope["kind"]
    if kind == "class_day":
        cl, d = scope["class"], scope["day"]
        return {k for k in sol if k[1] == cl and k[3] == d}
    if kind == "class_week":
        cl = scope["class"]
        return {k for k in sol if k[1] == cl}
    if kind == "prof_day":
        p, d = scope["prof"], scope["day"]
        return {k for k in sol if k[0] == p and k[3] == d}
    if kind == "prof_week":
        p = scope["prof"]
        return {k for k in sol if k[0] == p}
    if kind == "one_day":
        d = scope["day"]
        return {k for k in sol if k[3] == d}
    raise ValueError(f"Unknown scope kind: {kind}")


def repair_slot_neighborhood(sol, profs, dc_value, scope,
                             time_budget_s=10, workers=4):
    r"""Ri-ottimizza la zona descritta da `scope` usando un singolo
    CP-SAT repair (warm-started) e ritorna un dict:

      {
        'ok':            True/False,
        'sol':           nuova soluzione (oppure None),
        'obj_before':    SOFT della soluzione iniziale (full),
        'obj_after':     SOFT della soluzione finale (full),
        'delta_soft':    obj_before - obj_after (positivo = miglioramento),
        'metrics_before': {...},
        'metrics_after':  {...},
        'time_used':     secondi spesi nel solve,
      }
    """
    free_keys = _free_keys_for_scope(sol, scope)
    if not free_keys:
        return dict(ok=False, sol=None, obj_before=None,
                    obj_after=None, delta_soft=0,
                    metrics_before=None, metrics_after=None,
                    time_used=0.0,
                    reason="empty scope (nessuna lezione coinvolta)")
    obj_before, m_before = meta.compute_soft(sol, profs)
    t0 = time.time()
    new_sol, ok = meta._cp_repair(
        sol, profs, dc_value, free_keys, time_budget_s,
        workers=workers,
    )
    elapsed = time.time() - t0
    if not ok:
        return dict(ok=False, sol=None, obj_before=obj_before,
                    obj_after=None, delta_soft=0,
                    metrics_before=m_before, metrics_after=None,
                    time_used=elapsed,
                    reason="CP-SAT repair infeasible")
    obj_after, m_after = meta.compute_soft(new_sol, profs)
    return dict(
        ok=True, sol=new_sol,
        obj_before=obj_before, obj_after=obj_after,
        delta_soft=obj_before - obj_after,
        metrics_before=m_before, metrics_after=m_after,
        time_used=elapsed,
    )


# ============================================================
# 2) explain_infeasibility
# ============================================================

def explain_infeasibility(profs, dc_value, day):
    r"""Analisi strutturata di perche' Phase B sta fallendo per `day`.

    Ritorna un dict:
      {
        'day':              day,
        'hall_violations':  [{prof, prof_hours, max_class_load,
                              n_classes, classes:[...]}],
        'class_load_outliers': [{class, day_load}],
        'prof_overload':    [{prof, total_hours_in_day}],
        'summary':          'human readable string',
      }

    Riusa la logica di `cv2._diagnose_phaseb_infeasibility` ma in forma
    strutturata invece di stampe.
    """
    classes, triples, _ = cv2.build_indices(profs)
    # Calcola riempimenti per (prof, day) e (class, day).
    prof_classes_day = defaultdict(set)
    prof_hours_day = defaultdict(int)
    cl_load_day = defaultdict(int)
    for (p, cl, subj, ore) in triples:
        cnt = dc_value.get((p, cl, subj, day), 0)
        if cnt > 0:
            prof_classes_day[p].add(cl)
            prof_hours_day[p] += cnt
            cl_load_day[cl] += cnt

    hall_violations = []
    for p, cls in prof_classes_day.items():
        if not cls:
            continue
        max_load = max(cl_load_day[c] for c in cls)
        if prof_hours_day[p] > max_load:
            hall_violations.append(dict(
                prof=p,
                prof_hours=prof_hours_day[p],
                max_class_load=max_load,
                n_classes=len(cls),
                classes=sorted(cls),
            ))

    # Class load outlier: l'engine ammette solo {0, 4, 5, 6} via Phase A
    # AddAllowedAssignments. Un valore in {1,2,3} = bug a monte.
    class_load_outliers = [
        dict(**{"class": cl}, day_load=load)
        for cl, load in cl_load_day.items()
        if load in (1, 2, 3)
    ]

    # Prof overload: > MAX_PROF_HOURS_PER_DAY (=5)
    prof_overload = [
        dict(prof=p, total_hours_in_day=h)
        for p, h in prof_hours_day.items()
        if h > cv2.MAX_PROF_HOURS_PER_DAY
    ]

    summary_parts = []
    if hall_violations:
        summary_parts.append(
            f"{len(hall_violations)} violazioni Hall (prof con piu' "
            f"ore del max-load delle sue classi)"
        )
    if class_load_outliers:
        summary_parts.append(
            f"{len(class_load_outliers)} classi con load 1/2/3 (HARD-2 "
            f"violato a monte)"
        )
    if prof_overload:
        summary_parts.append(
            f"{len(prof_overload)} docenti con > "
            f"{cv2.MAX_PROF_HOURS_PER_DAY} ore in un giorno (HARD-C)"
        )
    if not summary_parts:
        summary_parts.append(
            "Nessuna violazione strutturale evidente. "
            "Causa probabile: combinatoria slot+coppie consecutive "
            "(motorie / mat-ita doppia), oppure no-holes troppo stretto."
        )
    summary = " | ".join(summary_parts)

    return dict(
        day=day,
        hall_violations=hall_violations,
        class_load_outliers=class_load_outliers,
        prof_overload=prof_overload,
        summary=summary,
    )


# ============================================================
# 3) why_not_lesson
# ============================================================

def why_not_lesson(sol, profs, lesson, target_day, target_hour):
    r"""Spiega perche' una lezione non puo' (o puo') essere messa in un
    determinato slot.

    `lesson` e' una tupla (prof, classe, subject) -- non c'e' bisogno
    di lesson_id perche' i SOFT/HARD di "stay HARD-feasible" guardano
    solo l'identita' (prof,cl,subj) della cella.

    Ritorna:
      {
        'ok':          True/False,
        'violations':  [{rule, detail}],
        'fixable_by':  [{action, description}],   # opzionale
      }
    """
    p, cl, subj = lesson
    violations = []

    # Vincolo 1: il prof deve essere libero in (target_day, target_hour)
    for (pp, cc, ss, dd, hh), v in sol.items():
        if v != 1:
            continue
        if dd != target_day or hh != target_hour:
            continue
        if pp == p and (cc, ss) != (cl, subj):
            violations.append(dict(
                rule="PROF_OVERLAP",
                detail=f"il docente {p} sta gia' insegnando "
                       f"{ss} a {cc} in d{dd} h{hh}",
            ))
        if cc == cl and pp != p:
            violations.append(dict(
                rule="CLASS_OVERLAP",
                detail=f"la classe {cl} ha gia' una lezione con "
                       f"{pp}/{ss} in d{dd} h{hh}",
            ))

    # Vincolo 2: classe HARD-2 (ingresso 8, uscita >= 12) -- se questo
    # slot e' OUT di una giornata aperta della classe, e' un buco.
    cls_hours = sorted(
        hh for (pp, cc, ss, dd, hh), v in sol.items()
        if v == 1 and cc == cl and dd == target_day
    )
    if cls_hours:
        if target_hour < cls_hours[0] or target_hour > cls_hours[-1] + 1:
            if target_hour != cls_hours[0] - 1:
                violations.append(dict(
                    rule="CLASS_NO_HOLES",
                    detail=f"la classe {cl} in d{target_day} ha lezioni "
                           f"in {cls_hours}; mettere h{target_hour} "
                           f"crea un buco",
                ))

    # Vincolo 3: H_C -- prof max 5 ore consecutive (= max 5 totali nel
    # giorno con no-holes; ma puo' avere buchi).
    prof_hours_day = sorted(
        hh for (pp, cc, ss, dd, hh), v in sol.items()
        if v == 1 and pp == p and dd == target_day
    )
    if len(prof_hours_day) >= 5:
        # con 6 ore (tutti gli slot) nel giorno -> overload H_C
        violations.append(dict(
            rule="PROF_HC_LIMIT",
            detail=f"il docente {p} ha gia' {len(prof_hours_day)} ore "
                   f"in d{target_day}, aggiungere h{target_hour} "
                   f"saturerebbe la giornata (HARD-C)",
        ))

    return dict(
        ok=len(violations) == 0,
        violations=violations,
    )


# ============================================================
# 4) auto_relax_suggestion (P2.6)
# ============================================================

def auto_relax_suggestion(profs, dc_value, day):
    r"""Quando explain_infeasibility ritorna violazioni, suggerisce
    QUALE vincolo "soft-toggle" rilassare per primo per sbloccare il
    giorno.

    Ritorna lista di tuple ordinata per priorita' (alto = molto utile):
      [
        {action: 'disable_motorie_pairs_for_class', class: 'X',
         expected_unblock: True, rationale: '...'},
        {action: 'allow_no_holes_relax', day: 3,
         expected_unblock: True, rationale: '...'},
        ...
      ]
    """
    expl = explain_infeasibility(profs, dc_value, day)
    suggestions = []
    if expl["hall_violations"]:
        # La causa piu' frequente: prof con piu' ore di quante una sua
        # classe puo' tenerne aperta. Rilassare no-holes per quella
        # classe puo' aiutare.
        for v in expl["hall_violations"][:3]:
            suggestions.append(dict(
                action="allow_no_holes_relax_for_classes",
                classes=v["classes"],
                day=day,
                expected_unblock=True,
                rationale=(
                    f"Il docente '{v['prof']}' ha {v['prof_hours']} ore "
                    f"in d{day} ma le sue {v['n_classes']} classi "
                    f"saturano a max {v['max_class_load']} ore. "
                    f"Rilassare no-holes per quelle classi crea slot "
                    f"liberi alle prime/ultime ore."
                ),
            ))
    if expl["class_load_outliers"]:
        suggestions.append(dict(
            action="rerun_phase_a_with_relaxed_load",
            classes=[o["class"] for o in expl["class_load_outliers"]],
            expected_unblock=True,
            rationale=(
                "Phase A ha prodotto cl_day_load in {1,2,3} per "
                "alcune classi: violazione di HARD-2 a monte. "
                "Bisogna ri-runnare Phase A con `--allow-light-days`."
            ),
        ))
    if expl["prof_overload"]:
        for v in expl["prof_overload"][:3]:
            suggestions.append(dict(
                action="reduce_prof_hours_in_day",
                prof=v["prof"],
                day=day,
                expected_unblock=False,    # solver puo' gia' clipparlo
                rationale=(
                    f"Il docente '{v['prof']}' ha {v['total_hours_in_day']} "
                    f"ore in d{day} (> {cv2.MAX_PROF_HOURS_PER_DAY} "
                    f"= HARD-C). Ridistribuire alcune ore ad altri "
                    f"giorni."
                ),
            ))
    if not suggestions:
        suggestions.append(dict(
            action="increase_solver_time_limit",
            day=day,
            expected_unblock=False,
            rationale=(
                "Nessuna violazione strutturale evidente. Il solver "
                "potrebbe semplicemente non aver trovato soluzione nel "
                "tempo dato; aumentare --time-mono."
            ),
        ))
    return suggestions
