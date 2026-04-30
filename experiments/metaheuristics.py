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


def compute_soft(sol, profs):
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
    return val, metrics


def is_hard_feasible(sol, profs, verbose=False):
    """Ritorna True se la soluzione rispetta tutti gli HARD."""
    cls_set = sorted({c for p in profs.values() for c in p["classi"]})
    profs_set = sorted(profs.keys())
    cls_h = class_day_hours(sol, cls_set)
    pd_h = prof_day_hours(sol, profs_set)

    # Class no-overlap: per (cl, d, h) max 1 lezione
    cl_count = defaultdict(int)
    for (p, cl, subj, d, h), v in sol.items():
        if v == 1:
            cl_count[(cl, d, h)] += 1
    for k, c in cl_count.items():
        if c > 1:
            if verbose:
                print(f"  CLASS-OVERLAP viol: {k} count={c}")
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

    # H1, H2, H3: classi
    for cl in cls_set:
        for d in DAYS:
            hrs = cls_h.get((cl, d), [])
            if not hrs:
                continue
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

    return True


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

def _cp_repair(sol, profs, dc_value, free_keys, time_limit, workers=4):
    """Risolve un sotto-problema CP-SAT in cui sono "libere" solo le
    variabili in `free_keys` (set di (p, cl, subj, d, h)) e tutto il
    resto e\` fissato a sol[k]. Riusa cv2.solve_phase_b_for_day con
    fixed_slots tramite trick: aggiungiamo `model.Add(slot[k]==v)`
    per le coppie fissate.

    Per semplicita\` operiamo per giorno: estraiamo i giorni unici
    dei free_keys, e per ciascuno richiamiamo una versione locale.

    Restituisce (new_sol, success).
    """
    from ortools.sat.python import cp_model
    days_to_repair = sorted({k[3] for k in free_keys})
    new_sol = deepcopy_sol(sol)
    classes, triples, class_profs = cv2.build_indices(profs)

    for day in days_to_repair:
        free_in_day = {k for k in free_keys if k[3] == day}

        model = cp_model.CpModel()
        slot = {}
        triples_active = []
        # Lista di (var, hint_value) per le variabili LIBERE -- saranno
        # warm-started con il valore corrente. Le variabili FISSATE
        # sono inutili per AddHint perche' sono gia' = corrente.
        hints = []
        for (p, cl, subj, ore) in triples:
            cnt = dc_value.get((p, cl, subj, day), 0)
            if cnt == 0:
                continue
            triples_active.append((p, cl, subj, cnt))
            for h in HOURS:
                v = model.NewBoolVar(f"r_{p}_{cl}_{subj}_{day}_{h}")
                slot[(p, cl, subj, h)] = v
                # Se questa key NON e\` libera, fissa al valore
                # corrente di sol.
                if (p, cl, subj, day, h) not in free_in_day:
                    cur = new_sol.get((p, cl, subj, day, h), 0)
                    model.Add(v == cur)
                else:
                    # Warm-start: la soluzione corrente e' feasible,
                    # quindi e' un punto di partenza valido. CP-SAT usa
                    # gli AddHint come prima ipotesi nella ricerca.
                    cur = new_sol.get((p, cl, subj, day, h), 0)
                    hints.append((v, cur))
            model.Add(
                sum(slot[(p, cl, subj, h)] for h in HOURS) == cnt
            )
        # Applica gli hint dopo aver aggiunto i vincoli (l'API CP-SAT
        # accetta hint anche su var non ancora vincolate, ma metterli
        # qui mantiene il flusso lineare).
        for v, val in hints:
            model.AddHint(v, val)

        # No overlap prof
        for p in {pp for (pp, _, _, _) in triples_active}:
            for h in HOURS:
                keys = [
                    slot[(p, cl, s, h)]
                    for (pp, cl, s, _) in triples_active if pp == p
                ]
                model.Add(sum(keys) <= 1)

        # No overlap classe + no holes + uscita >= 12
        cls_in_day = {cl for (_, cl, _, _) in triples_active}
        for cl in cls_in_day:
            present = []
            for h in HOURS:
                slot_keys = [
                    slot[(pp, cl, s, h)]
                    for (pp, cc, s, _) in triples_active if cc == cl
                ]
                pr = model.NewBoolVar(f"pr_{cl}_{day}_{h}")
                if slot_keys:
                    model.AddMaxEquality(pr, slot_keys)
                    model.Add(sum(slot_keys) == pr)
                else:
                    model.Add(pr == 0)
                present.append(pr)
            # H1+H2: contigui da 8
            any_present = model.NewBoolVar(f"ap_{cl}_{day}")
            model.AddMaxEquality(any_present, present)
            model.Add(present[0] >= any_present)
            for i in range(len(present) - 1):
                model.Add(present[i + 1] <= present[i])
            # H3
            if 11 in HOURS:
                model.Add(present[HOURS.index(11)] == 1)

        # H_A + H_B
        cv2.add_consecutive_constraints_phase_b(
            model, slot, day, profs, dc_value
        )

        # H_C: max 5 ore consecutive prof
        for p in {pp for (pp, _, _, _) in triples_active}:
            present_p = []
            for h in HOURS:
                keys = [
                    slot[(p, cl, s, h)]
                    for (pp, cl, s, _) in triples_active if pp == p
                ]
                pp_var = model.NewBoolVar(f"ppv_{p}_{day}_{h}")
                if keys:
                    model.AddMaxEquality(pp_var, keys)
                else:
                    model.Add(pp_var == 0)
                present_p.append(pp_var)
            # vieta 6 consecutive: in qualsiasi finestra di 6 ore (qui
            # la giornata ha esattamente 6 slot), almeno 1 deve essere
            # vuoto.
            model.Add(sum(present_p) <= 5)

        # SOFT objective: stessa formula compute_soft (ma per il
        # giorno) -- minimizziamo sixth + buchi + five + one
        sixth_terms = []
        if 13 in HOURS:
            h13_idx = HOURS.index(13)
            sixth_terms = []
            for cl in cls_in_day:
                slot_keys = [
                    slot[(pp, cl, s, 13)]
                    for (pp, cc, s, _) in triples_active if cc == cl
                ]
                pr13 = model.NewBoolVar(f"pr13_{cl}_{day}")
                if slot_keys:
                    model.AddMaxEquality(pr13, slot_keys)
                else:
                    model.Add(pr13 == 0)
                sixth_terms.append(pr13)
        # buchi del prof
        gap_terms = []
        five_terms = []
        one_terms = []
        for p in {pp for (pp, _, _, _) in triples_active}:
            present_p = []
            for h in HOURS:
                keys = [
                    slot[(p, cl, s, h)]
                    for (pp, cl, s, _) in triples_active if pp == p
                ]
                pp_var = model.NewBoolVar(f"pp_{p}_{day}_{h}")
                if keys:
                    model.AddMaxEquality(pp_var, keys)
                else:
                    model.Add(pp_var == 0)
                present_p.append(pp_var)
            for hi in range(1, len(HOURS) - 1):
                hb = model.NewBoolVar(f"hb_{p}_{day}_{hi}")
                model.AddMaxEquality(hb, present_p[:hi])
                ha = model.NewBoolVar(f"ha_{p}_{day}_{hi}")
                model.AddMaxEquality(ha, present_p[hi + 1:])
                gap = model.NewBoolVar(f"g_{p}_{day}_{hi}")
                model.AddBoolAnd(
                    [present_p[hi].Not(), hb, ha]
                ).OnlyEnforceIf(gap)
                model.AddBoolOr(
                    [present_p[hi], hb.Not(), ha.Not()]
                ).OnlyEnforceIf(gap.Not())
                gap_terms.append(gap)
            ld = model.NewIntVar(0, 5, f"ld_{p}_{day}")
            model.Add(ld == sum(present_p))
            is5 = model.NewBoolVar(f"is5_{p}_{day}")
            model.Add(ld == 5).OnlyEnforceIf(is5)
            model.Add(ld != 5).OnlyEnforceIf(is5.Not())
            is1 = model.NewBoolVar(f"is1_{p}_{day}")
            model.Add(ld == 1).OnlyEnforceIf(is1)
            model.Add(ld != 1).OnlyEnforceIf(is1.Not())
            five_terms.append(is5)
            one_terms.append(is1)

        terms = []
        if sixth_terms:
            terms.append(OBJECTIVE_WEIGHTS["sixth"] * sum(sixth_terms))
        if gap_terms:
            terms.append(OBJECTIVE_WEIGHTS["buchi"] * sum(gap_terms))
        if five_terms:
            terms.append(OBJECTIVE_WEIGHTS["five"] * sum(five_terms))
        if one_terms:
            terms.append(OBJECTIVE_WEIGHTS["one"] * sum(one_terms))
        if terms:
            model.Minimize(sum(terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit
        solver.parameters.num_search_workers = workers
        solver.parameters.log_search_progress = False
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None, False
        # Aggiorna sol per i giorni risolti
        for (p, cl, subj, _) in triples_active:
            for h in HOURS:
                v = solver.Value(slot[(p, cl, subj, h)])
                new_sol[(p, cl, subj, day, h)] = v
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
            adaptive=True):
    """Esegui Large Neighborhood Search per `time_budget_s` secondi.

    Se `adaptive=True` (default), gli operator non sono scelti uniformi
    ma con probabilita' proporzionali al delta_soft medio che ognuno ha
    prodotto fin qui (algoritmo "score" classico per Adaptive LNS).
    Inizialmente tutti gli operator hanno punteggio uguale; dopo i primi
    successi/fallimenti lo schema bias-a verso chi paga di piu'.

    Restituisce (best_sol, log_entries).
    """
    rng = random.Random(42)
    best = deepcopy_sol(sol)
    best_val, _ = compute_soft(best, profs)
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
        if not free:
            continue
        new_sol, ok = _cp_repair(
            best, profs, dc_value, free, time_local, workers=workers
        )
        op_stats[op]["n_calls"] += 1
        if not ok:
            log_entries.append(
                (iter_count, op, "infeasible", best_val, best_val)
            )
            continue
        new_val, _ = compute_soft(new_sol, profs)
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

def _swap_two_lessons_same_prof(sol, profs, dc_value, rng):
    """Tenta uno swap di 2 slot dello stesso prof (cambia hour).
    Restituisce nuova_sol o None se non valida.
    """
    # Pick a random prof and day where prof has at least 2 lessons
    profs_list = list(profs.keys())
    rng.shuffle(profs_list)
    for p in profs_list:
        for d in rng.sample(DAYS, len(DAYS)):
            occupied = [(k, v) for k, v in sol.items()
                        if k[0] == p and k[3] == d and v == 1]
            if len(occupied) < 2:
                continue
            (k1, _), (k2, _) = rng.sample(occupied, 2)
            # k1 = (p, cl1, s1, d, h1), k2 = (p, cl2, s2, d, h2)
            new_sol = dict(sol)
            new_sol[k1] = 0
            new_sol[k2] = 0
            new_k1 = (k1[0], k1[1], k1[2], k1[3], k2[4])
            new_k2 = (k2[0], k2[1], k2[2], k2[3], k1[4])
            new_sol[new_k1] = 1
            new_sol[new_k2] = 1
            if is_hard_feasible(new_sol, profs):
                return new_sol
            return None
    return None


def _move_lesson_to_empty_slot(sol, profs, dc_value, rng):
    """Sposta una singola lezione (p, cl, s, d, h) a (p, cl, s, d, h')
    con h' libero per il prof e per la classe."""
    occupied = [k for k, v in sol.items() if v == 1]
    rng.shuffle(occupied)
    for k in occupied[:50]:                    # limita tentativi
        p, cl, s, d, h_old = k
        # candidates: ore libere
        for h_new in rng.sample(HOURS, len(HOURS)):
            if h_new == h_old:
                continue
            new_k = (p, cl, s, d, h_new)
            if sol.get(new_k, 0) == 1:
                continue
            new_sol = dict(sol)
            new_sol[k] = 0
            new_sol[new_k] = 1
            if is_hard_feasible(new_sol, profs):
                return new_sol
    return None


def _swap_two_lessons_same_class(sol, profs, dc_value, rng):
    """Swap fra due lezioni della stessa classe (potenzialmente prof
    diversi) in slot diversi nello stesso giorno."""
    cls_set = sorted({c for p in profs.values() for c in p["classi"]})
    rng.shuffle(cls_set)
    for cl in cls_set[:20]:
        for d in rng.sample(DAYS, len(DAYS)):
            occupied = [(k, v) for k, v in sol.items()
                        if k[1] == cl and k[3] == d and v == 1]
            if len(occupied) < 2:
                continue
            (k1, _), (k2, _) = rng.sample(occupied, 2)
            new_sol = dict(sol)
            new_sol[k1] = 0
            new_sol[k2] = 0
            new_k1 = (k1[0], k1[1], k1[2], k1[3], k2[4])
            new_k2 = (k2[0], k2[1], k2[2], k2[3], k1[4])
            new_sol[new_k1] = 1
            new_sol[new_k2] = 1
            if is_hard_feasible(new_sol, profs):
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
           T0=10.0, alpha=0.995, log=True):
    rng = random.Random(123)
    best = dict(sol)
    cur = dict(sol)
    best_val, _ = compute_soft(best, profs)
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
        new_sol = move_fn(cur, profs, dc_value, rng)
        if new_sol is None:
            T *= alpha
            continue
        new_val, _ = compute_soft(new_sol, profs)
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
             tabu_size=80, log=True):
    rng = random.Random(456)
    best = dict(sol)
    cur = dict(sol)
    best_val, _ = compute_soft(best, profs)
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
            new_sol = move_fn(cur, profs, dc_value, rng)
            if new_sol is None:
                continue
            new_val, _ = compute_soft(new_sol, profs)
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
             classes_clusters=None, time_limit=15):
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
        sol, profs, dc_value, free, time_limit, workers=4
    )
    return new_sol if ok else dict(sol)


def run_ils(sol, profs, dc_value, time_budget_s,
            classes_clusters=None, ts_budget_per_cycle=60,
            n_cycles=3, log=True, lns_kick=True,
            lns_kick_budget=8.0):
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
    best_val, _ = compute_soft(best, profs)
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
        cur = run_tabu(cur, profs, dc_value, local_t, log=False)
        cur_val, _ = compute_soft(cur, profs)
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
                log=False,
            )
        else:
            if log:
                print(f"  [ILS cycle {cycle}] perturb")
            cur = _perturb(cur, profs, dc_value, rng, classes_clusters)
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
