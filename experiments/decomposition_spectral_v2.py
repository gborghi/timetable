r"""Decomposizione spettrale v2 -- pipeline a chiusura completa.

Differenze chiave rispetto a `decomposition_spectral.py` (v1):
- Stage A: i docenti PONTE vengono schedulati PRIMA in tutti i giorni
  (un sotto-CP-SAT per giorno con solo i bridges).
- Stage B: per ogni cluster, schedula gli internals con i bridges
  fissati (per ogni giorno).
- Stage C: se uno o piu\` cluster falliscono in Stage B, "ricucitura":
  fissa gli internals dei cluster RIUSCITI, libera bridges e
  internals dei cluster falliti, ri-risolve solo per quel giorno.
- Fallback monolitico per i giorni dove anche Stage C fallisce.

Pipeline garantisce **chiusura completa** dell'orario salvo
infeasibility intrinseca dei dati di Phase A.

USO:
    python decomposition_spectral_v2.py --profile huge \\
        [--k 4] [--time-bridges 60] [--time-cluster 30] \\
        [--time-ricucitura 120] [--time-mono 240] [--write-xlsx]

Phase A (assegnazione giorno) e\` in cache `phase_a_dc_<profile>.pkl`.
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
import time
from collections import defaultdict

import numpy as np
from sklearn.cluster import KMeans
from ortools.sat.python import cp_model

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cpsat_v2_timetable as cv2  # noqa: E402

DAYS = cv2.DAYS
HOURS = cv2.HOURS


# ============================================================
# CLUSTERING & BRIDGES
# ============================================================

def build_adjacency(profs):
    classes = sorted({c for p in profs.values() for c in p["classi"]})
    teachers_per_class = defaultdict(set)
    for p, info in profs.items():
        for c in info["classi"]:
            teachers_per_class[c].add(p)
    n = len(classes)
    M = np.zeros((n, n), dtype=np.int32)
    for i, ci in enumerate(classes):
        ti = teachers_per_class[ci]
        for j in range(i + 1, n):
            shared = len(ti & teachers_per_class[classes[j]])
            M[i, j] = M[j, i] = shared
    return M, classes, teachers_per_class


def spectral_cluster(M, k):
    A = M.astype(float)
    d = A.sum(axis=1)
    d_safe = np.where(d > 0, d, 1.0)
    inv_sqrt = 1.0 / np.sqrt(d_safe)
    L = np.eye(len(M)) - (A * inv_sqrt[:, None]) * inv_sqrt[None, :]
    eigvals, eigvecs = np.linalg.eigh(L)
    embedding = eigvecs[:, :k]
    nrm = np.linalg.norm(embedding, axis=1, keepdims=True)
    nrm[nrm == 0] = 1
    embedding = embedding / nrm
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    return km.fit_predict(embedding), eigvals[: k + 1]


def find_bridges(profs, classes, labels):
    cl_to_label = {c: int(labels[i]) for i, c in enumerate(classes)}
    bridges = {}
    for p, info in profs.items():
        cls_set = {cl_to_label[c] for c in info["classi"]}
        if len(cls_set) > 1:
            bridges[p] = cls_set
    return bridges, cl_to_label


# ============================================================
# UTILITIES
# ============================================================

def compute_cl_day_load(triples, dc_value, day):
    out = defaultdict(int)
    for (p, cl, subj, ore) in triples:
        v = dc_value.get((p, cl, subj, day), 0)
        if v:
            out[cl] += v
    return out


def add_buchi_soft(model, triples_active, slot, day, prefix):
    """Aggiunge variabili "buchi del prof" e ritorna la lista di gap."""
    gap_terms = []
    profs_active = sorted({pp for (pp, _, _, _) in triples_active})
    for p in profs_active:
        present_p = []
        for h in HOURS:
            keys = [
                slot[(p, cl, s, h)]
                for (pp, cl, s, _) in triples_active if pp == p
                and (p, cl, s, h) in slot
            ]
            if keys:
                pp_var = model.NewBoolVar(f"{prefix}_pp_{p}_{day}_{h}")
                model.AddMaxEquality(pp_var, keys)
            else:
                pp_var = model.NewConstant(0)
            present_p.append(pp_var)
        for hi in range(1, len(HOURS) - 1):
            earlier = present_p[:hi]
            later = present_p[hi + 1:]
            hb = model.NewBoolVar(f"{prefix}_hb_{p}_{day}_{hi}")
            model.AddMaxEquality(hb, earlier)
            ha = model.NewBoolVar(f"{prefix}_ha_{p}_{day}_{hi}")
            model.AddMaxEquality(ha, later)
            gap = model.NewBoolVar(f"{prefix}_gap_{p}_{day}_{hi}")
            model.AddBoolAnd(
                [present_p[hi].Not(), hb, ha]
            ).OnlyEnforceIf(gap)
            model.AddBoolOr(
                [present_p[hi], hb.Not(), ha.Not()]
            ).OnlyEnforceIf(gap.Not())
            gap_terms.append(gap)
    return gap_terms


# ============================================================
# STAGE A: bridges only
# ============================================================

def stage_a_bridges(day, profs, bridges, triples, dc_value,
                    time_limit, workers, log=False):
    cl_day_load = compute_cl_day_load(triples, dc_value, day)
    model = cp_model.CpModel()
    slot = {}
    triples_active = []
    for (p, cl, subj, ore) in triples:
        if p not in bridges:
            continue
        cnt = dc_value.get((p, cl, subj, day), 0)
        if cnt == 0:
            continue
        triples_active.append((p, cl, subj, cnt))
        L = cl_day_load.get(cl, 0)
        for h in HOURS:
            v = model.NewBoolVar(f"sa_{p}_{cl}_{subj}_{day}_{h}")
            slot[(p, cl, subj, h)] = v
            if L == 0 or h - 8 >= L:
                model.Add(v == 0)
        model.Add(sum(slot[(p, cl, subj, h)] for h in HOURS) == cnt)

    profs_active = {pp for (pp, _, _, _) in triples_active}
    for p in profs_active:
        for h in HOURS:
            keys = [
                slot[(p, cl, s, h)]
                for (pp, cl, s, _) in triples_active if pp == p
            ]
            model.Add(sum(keys) <= 1)

    cls_active = {cl for (_, cl, _, _) in triples_active}
    for cl in cls_active:
        for h in HOURS:
            keys = [
                slot[(p, cl, s, h)]
                for (p, cc, s, _) in triples_active if cc == cl
            ]
            model.Add(sum(keys) <= 1)

    # HARD A/B: Mat/Ita doppia consecutiva, Motorie a coppie.
    cv2.add_consecutive_constraints_phase_b(
        model, slot, day, profs, dc_value
    )

    gap_terms = add_buchi_soft(model, triples_active, slot, day, "A")
    if gap_terms:
        model.Minimize(sum(gap_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    solver.parameters.log_search_progress = log
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, status
    out = {
        (p, cl, subj, day, h): solver.Value(slot[(p, cl, subj, h)])
        for (p, cl, subj, _) in triples_active
        for h in HOURS
    }
    return out, status


# ============================================================
# STAGE B: cluster internals with bridges fixed
# ============================================================

def stage_b_cluster_internals(cluster_classes, day, profs, bridges,
                              triples, dc_value, bridge_solution,
                              time_limit, workers, log=False):
    cl_day_load = compute_cl_day_load(triples, dc_value, day)
    bridge_in_slot = defaultdict(int)
    for (p, cl, subj, d, h), v in bridge_solution.items():
        if v == 1 and cl in cluster_classes:
            bridge_in_slot[(cl, h)] += 1

    model = cp_model.CpModel()
    slot = {}
    triples_active = []
    for (p, cl, subj, ore) in triples:
        if p in bridges:
            continue
        if cl not in cluster_classes:
            continue
        cnt = dc_value.get((p, cl, subj, day), 0)
        if cnt == 0:
            continue
        triples_active.append((p, cl, subj, cnt))
        L = cl_day_load.get(cl, 0)
        for h in HOURS:
            v = model.NewBoolVar(f"sb_{p}_{cl}_{subj}_{day}_{h}")
            slot[(p, cl, subj, h)] = v
            if L == 0 or h - 8 >= L:
                model.Add(v == 0)
        model.Add(sum(slot[(p, cl, subj, h)] for h in HOURS) == cnt)

    profs_active = {pp for (pp, _, _, _) in triples_active}
    for p in profs_active:
        for h in HOURS:
            keys = [
                slot[(p, cl, s, h)]
                for (pp, cl, s, _) in triples_active if pp == p
            ]
            model.Add(sum(keys) <= 1)

    # Class fill: per (cl, h) in [8..8+L-1]:
    #   bridge_count(cl, h) + sum_internal(cl, h) == 1
    # Per h fuori: 0 (gia\` forzato).
    for cl in cluster_classes:
        L = cl_day_load.get(cl, 0)
        if L == 0:
            continue
        for h in HOURS:
            internal_keys = [
                slot[(pp, cl, s, h)]
                for (pp, cc, s, _) in triples_active if cc == cl
            ]
            b_val = bridge_in_slot.get((cl, h), 0)
            if h - 8 < L:
                model.Add(b_val + sum(internal_keys) == 1)
            else:
                model.Add(b_val + sum(internal_keys) == 0)

    # HARD A/B: applicato ai prof internal del cluster (i bridges
    # sono fissati e gli stessi vincoli sono stati gia\` applicati
    # in Stage A).
    cv2.add_consecutive_constraints_phase_b(
        model, slot, day, profs, dc_value
    )

    gap_terms = add_buchi_soft(model, triples_active, slot, day, "B")
    if gap_terms:
        model.Minimize(sum(gap_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    solver.parameters.log_search_progress = log
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, status
    out = {
        (p, cl, subj, day, h): solver.Value(slot[(p, cl, subj, h)])
        for (p, cl, subj, _) in triples_active
        for h in HOURS
    }
    return out, status


# ============================================================
# STAGE C: ricucitura giornaliera
# ============================================================

def stage_c_ricucitura(day, profs, bridges, triples, dc_value,
                       fixed_internal_solution,
                       time_limit, workers, log=False):
    """Variabili: bridges (tutti) + internals NON in fixed_solution.
    Constraints: gli internals fissati hanno slot[k] == valore."""
    cl_day_load = compute_cl_day_load(triples, dc_value, day)

    # Determina quali (p, cl, subj) sono "fissati"
    fixed_triples_set = {
        (p, cl, subj)
        for (p, cl, subj, dd, h), v in fixed_internal_solution.items()
        if dd == day
    }

    model = cp_model.CpModel()
    slot = {}
    triples_active = []          # tutti i triple su day
    for (p, cl, subj, ore) in triples:
        cnt = dc_value.get((p, cl, subj, day), 0)
        if cnt == 0:
            continue
        triples_active.append((p, cl, subj, cnt))
        L = cl_day_load.get(cl, 0)
        is_fixed = (
            (p, cl, subj) in fixed_triples_set and p not in bridges
        )
        for h in HOURS:
            v = model.NewBoolVar(f"sc_{p}_{cl}_{subj}_{day}_{h}")
            slot[(p, cl, subj, h)] = v
            if L == 0 or h - 8 >= L:
                model.Add(v == 0)
            if is_fixed:
                fixed_val = fixed_internal_solution.get(
                    (p, cl, subj, day, h), 0
                )
                model.Add(v == fixed_val)
        if not is_fixed:
            model.Add(
                sum(slot[(p, cl, subj, h)] for h in HOURS) == cnt
            )
        # Se is_fixed, somma e\` gia\` cnt per costruzione

    profs_active = {pp for (pp, _, _, _) in triples_active}
    for p in profs_active:
        for h in HOURS:
            keys = [
                slot[(p, cl, s, h)]
                for (pp, cl, s, _) in triples_active if pp == p
            ]
            model.Add(sum(keys) <= 1)

    # Per ogni (cl, h in [8..8+L-1]): somma di tutti = 1
    for cl in cl_day_load:
        L = cl_day_load[cl]
        for h in HOURS:
            keys = [
                slot[(pp, cl, s, h)]
                for (pp, cc, s, _) in triples_active if cc == cl
            ]
            if h - 8 < L:
                model.Add(sum(keys) == 1)
            else:
                model.Add(sum(keys) == 0)

    # HARD A/B: applicato all'intero giorno (Stage C ha tutti i prof
    # in slot, quindi i vincoli sono pienamente espressi).
    cv2.add_consecutive_constraints_phase_b(
        model, slot, day, profs, dc_value
    )

    # SOFT: buchi prof (sui non-fissati)
    free_triples = [
        (p, cl, subj, cnt)
        for (p, cl, subj, cnt) in triples_active
        if p in bridges or (p, cl, subj) not in fixed_triples_set
    ]
    gap_terms = add_buchi_soft(model, free_triples, slot, day, "C")
    if gap_terms:
        model.Minimize(sum(gap_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    solver.parameters.log_search_progress = log
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, status
    out = {
        (p, cl, subj, day, h): solver.Value(slot[(p, cl, subj, h)])
        for (p, cl, subj, _) in triples_active
        for h in HOURS
    }
    return out, status


# ============================================================
# MONOLITHIC FALLBACK per giorno
# ============================================================

def solve_monolithic_day(day, profs, triples, dc_value,
                         time_limit, workers, log=False):
    classes, _, class_profs = cv2.build_indices(profs)
    out, status = cv2.solve_phase_b_for_day(
        day, profs, classes, triples, class_profs, dc_value,
        time_limit=time_limit, workers=workers, log=log,
        enforce_no_holes=True,
    )
    return out, status


# ============================================================
# PIPELINE COMPLETA
# ============================================================

def load_or_build_phase_a(profs, profile, time_a, workers, log):
    cache = os.path.join(HERE, f"phase_a_dc_{profile}.pkl")
    if os.path.exists(cache):
        print(f"[v2] Phase A cache hit: {cache}")
        with open(cache, "rb") as f:
            return pickle.load(f), 0.0
    print("[v2] Phase A cache miss; eseguo...")
    classes, triples, class_profs = cv2.build_indices(profs)
    t0 = time.time()
    dc_value = cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=time_a, workers=workers, log=log,
    )
    elapsed = time.time() - t0
    with open(cache, "wb") as f:
        pickle.dump(dc_value, f)
    print(f"[v2] Phase A scritta in {cache} ({elapsed:.1f}s)")
    return dc_value, elapsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True,
                        choices=["small", "big", "medium", "huge",
                                 "superhuge"])
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--time-bridges", type=float, default=60.0,
                        help="time-limit per giorno per Stage A bridges")
    parser.add_argument("--time-cluster", type=float, default=30.0,
                        help="time-limit per (cluster, day) Stage B")
    parser.add_argument("--time-ricucitura", type=float, default=120.0,
                        help="time-limit per giorno Stage C")
    parser.add_argument("--time-mono", type=float, default=240.0,
                        help="time-limit per giorno fallback monolitico")
    parser.add_argument("--time-a", type=float, default=180.0,
                        help="se Phase A cache miss, time-limit Phase A")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--write-xlsx", action="store_true")
    parser.add_argument("--log", action="store_true")
    args = parser.parse_args()

    profs_path = os.path.join(HERE, f"profs_{args.profile}.pkl")
    school_path = os.path.join(HERE, f"school_{args.profile}.pkl")
    if not os.path.exists(profs_path):
        print(f"ERROR: {profs_path} non esiste.")
        return 1

    with open(profs_path, "rb") as f:
        profs = pickle.load(f)
    print(f"[v2] profilo={args.profile}: {len(profs)} docenti, "
          f"{len(set(c for p in profs.values() for c in p['classi']))} classi")

    # 1) Adiacenza + clustering
    M, classes, _ = build_adjacency(profs)
    n = len(classes)
    print(f"[v2] adiacenza {n}x{n} max={M.max()} mean={M.mean():.1f}")
    t0 = time.time()
    labels, eigvals = spectral_cluster(M, args.k)
    t_cluster = time.time() - t0
    print(f"[v2] spectral clustering k={args.k}: {t_cluster:.2f}s")
    cluster_sizes = {int(c): int((labels == c).sum())
                     for c in range(args.k)}
    print(f"[v2] dimensioni cluster: {cluster_sizes}")
    bridges, cl_to_label = find_bridges(profs, classes, labels)
    print(f"[v2] docenti ponte: {len(bridges)}/{len(profs)} "
          f"({100.0 * len(bridges) / len(profs):.1f}%)")

    classes_per_cluster = defaultdict(set)
    for c, lbl in cl_to_label.items():
        classes_per_cluster[lbl].add(c)

    # 2) Phase A interno (cached)
    dc_value, t_phase_a = load_or_build_phase_a(
        profs, args.profile, args.time_a, args.workers, args.log
    )

    _, triples, _ = cv2.build_indices(profs)
    bridges_set = set(bridges.keys())

    # ============================================================
    # 3) Stage A: bridges per giorno
    # ============================================================
    print(f"\n[v2] === STAGE A (bridges only) ===")
    bridge_solutions = {}        # day -> {(p,cl,s,d,h):0/1}
    a_failed = []
    t_stage_a_total = 0.0
    for d in DAYS:
        t0 = time.time()
        out, status = stage_a_bridges(
            d, profs, bridges_set, triples, dc_value,
            args.time_bridges, args.workers, log=False
        )
        dt = time.time() - t0
        t_stage_a_total += dt
        if out is None:
            print(f"[stageA] day={d} INFEASIBLE in {dt:.1f}s")
            a_failed.append(d)
        else:
            bridge_solutions[d] = out
            n_set = sum(1 for v in out.values() if v == 1)
            print(f"[stageA] day={d} ok in {dt:.1f}s, "
                  f"{n_set} ore-bridge piazzate")

    # ============================================================
    # 4) Stage B: per cluster x day, internals con bridges fissati
    # ============================================================
    print(f"\n[v2] === STAGE B (cluster internals, bridges fixed) ===")
    cluster_solutions = {}        # (cluster_id, day) -> {...}
    b_failed = defaultdict(set)   # day -> set of cluster_ids
    t_stage_b_total = 0.0
    t_stage_b_max_per_day = 0.0
    cluster_order = sorted(
        range(args.k), key=lambda k: -len(classes_per_cluster[k])
    )
    for d in DAYS:
        if d not in bridge_solutions:
            continue
        t_day = 0.0
        for k_id in cluster_order:
            cl_set = classes_per_cluster[k_id]
            if not cl_set:
                continue
            t0 = time.time()
            out, status = stage_b_cluster_internals(
                cl_set, d, profs, bridges_set, triples, dc_value,
                bridge_solutions[d], args.time_cluster, args.workers,
                log=False
            )
            dt = time.time() - t0
            t_day += dt
            t_stage_b_total += dt
            if out is None:
                print(f"[stageB] day={d} cluster={k_id} INFEASIBLE "
                      f"in {dt:.1f}s")
                b_failed[d].add(k_id)
            else:
                cluster_solutions[(k_id, d)] = out
        if t_day > t_stage_b_max_per_day:
            t_stage_b_max_per_day = t_day
        print(f"[stageB] day={d} totale {t_day:.1f}s, "
              f"falliti={sorted(b_failed.get(d, set()))}")

    # Combina la soluzione corrente
    full_solution = {}
    for d in DAYS:
        if d in bridge_solutions:
            full_solution.update(bridge_solutions[d])
        for k_id in range(args.k):
            if (k_id, d) in cluster_solutions:
                full_solution.update(cluster_solutions[(k_id, d)])

    # ============================================================
    # 5) Stage C: ricucitura per giorni con cluster falliti
    # ============================================================
    print(f"\n[v2] === STAGE C (ricucitura) ===")
    days_needing_C = sorted(set(b_failed.keys()) | set(a_failed))
    if not days_needing_C:
        print("[stageC] nessun giorno da ricucire")
    c_failed = []
    t_stage_c_total = 0.0
    for d in days_needing_C:
        # Internals fissati = solo dei cluster RIUSCITI in quel giorno
        succ_internals = {}
        for k_id in range(args.k):
            if k_id in b_failed.get(d, set()):
                continue
            if (k_id, d) in cluster_solutions:
                succ_internals.update(cluster_solutions[(k_id, d)])
        t0 = time.time()
        out, status = stage_c_ricucitura(
            d, profs, bridges_set, triples, dc_value, succ_internals,
            args.time_ricucitura, args.workers, log=False
        )
        dt = time.time() - t0
        t_stage_c_total += dt
        if out is None:
            print(f"[stageC] day={d} INFEASIBLE in {dt:.1f}s")
            c_failed.append(d)
        else:
            print(f"[stageC] day={d} ricucito in {dt:.1f}s")
            # Sostituisci tutto il giorno
            full_solution = {
                k: v for k, v in full_solution.items() if k[3] != d
            }
            full_solution.update(out)

    # ============================================================
    # 6) Monolithic fallback per i giorni dove anche Stage C fallisce
    # ============================================================
    print(f"\n[v2] === MONOLITHIC FALLBACK ===")
    m_failed = []
    t_stage_m_total = 0.0
    for d in c_failed:
        t0 = time.time()
        out, status = solve_monolithic_day(
            d, profs, triples, dc_value,
            args.time_mono, args.workers, log=False
        )
        dt = time.time() - t0
        t_stage_m_total += dt
        if out is None:
            print(f"[mono] day={d} ANCHE MONOLITHIC INFEASIBLE in "
                  f"{dt:.1f}s; soluzione PARZIALE per quel giorno")
            m_failed.append(d)
        else:
            print(f"[mono] day={d} risolto monolitico in {dt:.1f}s")
            full_solution = {
                k: v for k, v in full_solution.items() if k[3] != d
            }
            full_solution.update(out)
    if not c_failed:
        print("[mono] nessun giorno richiede fallback monolitico")

    # ============================================================
    # 7) Verifica HARD + statistiche SOFT
    # ============================================================
    print(f"\n[v2] === VERIFICA HARD + SOFT ===")
    n_lessons = sum(1 for v in full_solution.values() if v == 1)
    fabbisogno = sum(
        meta["ore"] for p in profs.values()
        for cl, sm in p["classi"].items()
        for meta in sm.values()
    )
    present_cl = defaultdict(int)
    present_p = defaultdict(int)
    for (p, cl, subj, day, hour), v in full_solution.items():
        if v == 1:
            present_cl[(cl, day, hour)] += 1
            present_p[(p, day, hour)] += 1
    viol_holes = viol_ingress = viol_uscita = 0
    sixth_count = 0
    for cl in classes:
        for d in DAYS:
            hrs = [h for h in HOURS if present_cl.get((cl, d, h), 0)]
            if not hrs:
                continue
            if hrs[0] != 8:
                viol_ingress += 1
            for i, h in enumerate(hrs):
                if h != hrs[0] + i:
                    viol_holes += 1
                    break
            if not present_cl.get((cl, d, 11), 0):
                viol_uscita += 1
            if present_cl.get((cl, d, 13), 0):
                sixth_count += 1
    total_buchi_prof = 0
    for p in profs:
        for d in DAYS:
            hrs = [h for h in HOURS if present_p.get((p, d, h), 0)]
            if len(hrs) >= 2:
                total_buchi_prof += hrs[-1] - hrs[0] + 1 - len(hrs)
    print(f"  lezioni totali = {n_lessons} / fabbisogno = {fabbisogno} "
          f"({100.0*n_lessons/fabbisogno:.1f}%)")
    print(f"  HARD: classi con buchi={viol_holes}, "
          f"ingress non da 8={viol_ingress}, "
          f"uscita prima 12={viol_uscita}")
    print(f"  SOFT: 6^a ora occupate={sixth_count}, "
          f"buchi prof totali={total_buchi_prof}")

    # ============================================================
    # 8) Salva e (opz) export xlsx
    # ============================================================
    out_pkl = os.path.join(
        HERE, f"solution_timetable_{args.profile}_decomposed.pkl"
    )
    with open(out_pkl, "wb") as f:
        pickle.dump(full_solution, f)
    print(f"\n[v2] soluzione salvata in {out_pkl}")

    if args.write_xlsx:
        from exporters import (
            export_class_schedules_to_xlsx,
            export_teacher_schedules_to_xlsx,
        )
        out_dir = os.path.join(HERE, "output", args.profile)
        os.makedirs(out_dir, exist_ok=True)
        out_classi = os.path.join(
            out_dir, f"orario_classi_{args.profile}_decomposed.xlsx"
        )
        out_doc = os.path.join(
            out_dir, f"orario_docenti_{args.profile}_decomposed.xlsx"
        )
        export_class_schedules_to_xlsx(
            out_pkl, school_path, profs_path, out_classi
        )
        export_teacher_schedules_to_xlsx(
            out_pkl, school_path, profs_path, out_doc
        )

    # ============================================================
    # 9) Riassunto finale
    # ============================================================
    print(f"\n[v2] === RIASSUNTO {args.profile} ===")
    print(f"  k = {args.k}, cluster_sizes = {cluster_sizes}")
    print(f"  bridges = {len(bridges)}/{len(profs)} "
          f"({100.0*len(bridges)/len(profs):.1f}%)")
    print(f"  Phase A interno = "
          f"{'CACHE HIT' if t_phase_a == 0 else f'{t_phase_a:.1f}s'}")
    print(f"  spectral clustering = {t_cluster:.2f}s")
    print(f"  Stage A bridges = {t_stage_a_total:.1f}s "
          f"({len(a_failed)} giorni falliti)")
    print(f"  Stage B clusters = {t_stage_b_total:.1f}s totali "
          f"(max/day={t_stage_b_max_per_day:.1f}s); "
          f"{sum(len(s) for s in b_failed.values())} cluster-day falliti")
    print(f"  Stage C ricucitura = {t_stage_c_total:.1f}s "
          f"({len(days_needing_C)} giorni; {len(c_failed)} falliti)")
    print(f"  Monolithic fallback = {t_stage_m_total:.1f}s "
          f"({len(c_failed) - len(m_failed)} risolti, "
          f"{len(m_failed)} ANCORA falliti)")
    total_phase_b = (
        t_stage_a_total + t_stage_b_total + t_stage_c_total + t_stage_m_total
    )
    print(f"  TOTALE Phase B (decomposta) = {total_phase_b:.1f}s")
    print(f"  COVERAGE: {100.0*n_lessons/fabbisogno:.1f}% "
          f"(HARD violations: {viol_holes + viol_ingress + viol_uscita})")
    print(f"  SOFT: {sixth_count} 6^a ore, {total_buchi_prof} buchi prof")

    return 0 if not m_failed else 2


if __name__ == "__main__":
    sys.exit(main())
