r"""Esperimento di decomposizione del problema di scheduling per
clustering spettrale delle classi.

IDEA:
    1) Costruisci una matrice di adiacenza N x N tra classi pesando
       sul numero di docenti in comune.
    2) Clustering spettrale (Laplaciano normalizzato + k-means su
       prime K eigenvecs) -> partizione delle classi in K cluster.
    3) Trova i "docenti ponte" (insegnano in piu' di un cluster).
    4) Per ogni giorno, risolvi sequenzialmente una sotto-Phase-B
       per ciascun cluster, bloccando gli slot gia' occupati dai
       docenti ponte negli altri cluster.

SCOPO:
    Verificare se la decomposizione riduce in modo significativo il
    tempo di Phase B su problemi grandi (HUGE/SUPERHUGE), anche a
    costo di una perdita modesta di qualita' SOFT (buchi prof,
    seste ore) perche' ogni cluster ottimizza solo il proprio
    sotto-problema.

USO:
    python decomposition_spectral.py --profile huge \\
        [--k 4] [--time-cluster 30] [--time-a 180] [--write-xlsx]

Phase A (assegnazione giorno) non e' toccata: viene rieseguita
una sola volta e cachata in `phase_a_dc_<profile>.pkl`. Le run
successive caricano la cache.
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

# Riusa Phase A e i parametri base dal modello attuale, senza
# modificarlo.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cpsat_v2_timetable as cv2  # noqa: E402

DAYS = cv2.DAYS
HOURS = cv2.HOURS


# ============================================================
# 1. ADIACENZA + CLUSTERING SPETTRALE
# ============================================================

def build_adjacency(profs):
    """Calcola la matrice M[i,j] = numero di docenti comuni alle
    classi i e j. Diagonale = 0."""
    classes = sorted({c for p in profs.values() for c in p["classi"]})
    cl_idx = {c: i for i, c in enumerate(classes)}
    n = len(classes)
    teachers_per_class = defaultdict(set)
    for p, info in profs.items():
        for c in info["classi"]:
            teachers_per_class[c].add(p)
    M = np.zeros((n, n), dtype=np.int32)
    for i, ci in enumerate(classes):
        ti = teachers_per_class[ci]
        for j in range(i + 1, n):
            cj = classes[j]
            shared = len(ti & teachers_per_class[cj])
            M[i, j] = shared
            M[j, i] = shared
    return M, classes, cl_idx, teachers_per_class


def spectral_cluster(M, k):
    """Spectral clustering con Laplaciano normalizzato.
    Ritorna labels (vettore di interi 0..k-1) e i primi k+1
    autovalori per diagnostica.
    """
    n = M.shape[0]
    # Aggiungi un piccolo self-loop per evitare componenti isolate
    # con peso zero (se due classi sono completamente disgiunte).
    A = M.astype(float)
    d = A.sum(axis=1)
    # Evita div0
    d_safe = np.where(d > 0, d, 1.0)
    D_inv_sqrt = 1.0 / np.sqrt(d_safe)
    # L_norm = I - D^(-1/2) A D^(-1/2)
    L_norm = np.eye(n) - (A * D_inv_sqrt[:, None]) * D_inv_sqrt[None, :]
    # eigendecomposition (L_norm e' simmetrica)
    eigvals, eigvecs = np.linalg.eigh(L_norm)
    # primi k autovettori (autovalori piu' piccoli)
    embedding = eigvecs[:, :k]
    # normalizza righe (Ng-Jordan-Weiss)
    norms = np.linalg.norm(embedding, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embedding = embedding / norms
    # k-means sulle righe
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(embedding)
    return labels, eigvals[: k + 1]


def find_bridge_teachers(profs, classes, labels):
    """bridges[p] = set di cluster in cui il prof insegna.
    Restituisce solo i prof con > 1 cluster."""
    cl_to_label = {c: int(labels[i]) for i, c in enumerate(classes)}
    bridges = {}
    for p, info in profs.items():
        cls_set = set()
        for c in info["classi"]:
            cls_set.add(cl_to_label[c])
        if len(cls_set) > 1:
            bridges[p] = cls_set
    return bridges, cl_to_label


# ============================================================
# 2. PHASE B DECOMPOSTA
# ============================================================

def solve_cluster_day(
    cluster_classes, day, triples, dc_value, locked_slots,
    time_limit=30, workers=4,
):
    r"""Risolve Phase B per le `cluster_classes` nel giorno `day`.
    `locked_slots`: dict {(prof, hour): True} per slot gia' occupati
    da prof "ponte" in cluster precedenti dello stesso giorno; in
    questo cluster il prof non puo' essere assegnato a quegli slot.

    Restituisce (out, status). out = dict {(p, cl, subj, day, h): 0/1}.
    """
    model = cp_model.CpModel()
    triples_active = []
    for (p, cl, subj, ore) in triples:
        if cl not in cluster_classes:
            continue
        cnt = dc_value.get((p, cl, subj, day), 0)
        if cnt == 0:
            continue
        triples_active.append((p, cl, subj, cnt))

    if not triples_active:
        return {}, cp_model.OPTIMAL

    slot = {}
    for (p, cl, subj, cnt) in triples_active:
        for h in HOURS:
            slot[(p, cl, subj, h)] = model.NewBoolVar(
                f"s_{p}_{cl}_{subj}_{day}_{h}"
            )
        model.Add(
            sum(slot[(p, cl, subj, h)] for h in HOURS) == cnt
        )

    # No overlap prof + lock per i ponti
    profs_in_cluster = sorted({p for (p, _, _, _) in triples_active})
    for p in profs_in_cluster:
        for h in HOURS:
            keys = [
                slot[(p, cl, s, h)]
                for (pp, cl, s, _) in triples_active if pp == p
            ]
            if keys:
                model.Add(sum(keys) <= 1)
            if locked_slots.get((p, h), False):
                # Il prof e' gia' occupato in un altro cluster nello
                # stesso giorno: non puo' essere qui.
                for k in keys:
                    model.Add(k == 0)

    # No overlap classe + no holes + HARD (2)
    cls_in_day = sorted({cl for (_, cl, _, _) in triples_active})
    present_per_class = {}
    for cl in cls_in_day:
        present = []
        for h in HOURS:
            slot_keys = [
                slot[(p, cl, s, h)]
                for (p, cc, s, _) in triples_active if cc == cl
            ]
            pr = model.NewBoolVar(f"pr_{cl}_{day}_{h}")
            if slot_keys:
                model.AddMaxEquality(pr, slot_keys)
                model.Add(sum(slot_keys) == pr)
            else:
                model.Add(pr == 0)
            present.append(pr)
        present_per_class[cl] = present
        # HARD: no holes + ingresso a 8
        any_present = model.NewBoolVar(f"ap_{cl}_{day}")
        model.AddMaxEquality(any_present, present)
        model.Add(present[0] >= any_present)
        for i in range(len(present) - 1):
            model.Add(present[i + 1] <= present[i])
        # HARD (2): uscita non prima delle 12
        if 11 in HOURS:
            h11_idx = HOURS.index(11)
            model.Add(present[h11_idx] == 1)

    # SOFT (4): minimizza 6^a ora
    sixth_terms = []
    if 13 in HOURS:
        h13_idx = HOURS.index(13)
        sixth_terms = [
            present_per_class[cl][h13_idx] for cl in cls_in_day
        ]

    # SOFT (6): minimizza buchi prof (solo dentro il cluster)
    gap_terms = []
    for p in profs_in_cluster:
        present_p = []
        for h in HOURS:
            keys = [
                slot[(p, cl, s, h)]
                for (pp, cl, s, _) in triples_active if pp == p
            ]
            if not keys:
                pp_var = model.NewConstant(0)
            else:
                pp_var = model.NewBoolVar(f"pp_{p}_{day}_{h}")
                model.AddMaxEquality(pp_var, keys)
            present_p.append(pp_var)
        for hi in range(1, len(HOURS) - 1):
            earlier = present_p[:hi]
            later = present_p[hi + 1:]
            has_before = model.NewBoolVar(f"hb_{p}_{day}_{hi}")
            model.AddMaxEquality(has_before, earlier)
            has_after = model.NewBoolVar(f"ha_{p}_{day}_{hi}")
            model.AddMaxEquality(has_after, later)
            gap = model.NewBoolVar(f"gap_{p}_{day}_{hi}")
            model.AddBoolAnd(
                [present_p[hi].Not(), has_before, has_after]
            ).OnlyEnforceIf(gap)
            model.AddBoolOr(
                [present_p[hi], has_before.Not(), has_after.Not()]
            ).OnlyEnforceIf(gap.Not())
            gap_terms.append(gap)

    obj = []
    if sixth_terms:
        obj.append(5 * sum(sixth_terms))
    if gap_terms:
        obj.append(10 * sum(gap_terms))
    if obj:
        model.Minimize(sum(obj))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    solver.parameters.log_search_progress = False
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
# 3. PIPELINE COMPLETA
# ============================================================

def load_or_build_phase_a(profs, profile, time_a, workers, log):
    cache_path = os.path.join(HERE, f"phase_a_dc_{profile}.pkl")
    if os.path.exists(cache_path):
        print(f"[decomp] cache trovata: carico {cache_path}")
        with open(cache_path, "rb") as f:
            return pickle.load(f), 0.0
    print("[decomp] cache assente, eseguo Phase A interno...")
    classes, triples, class_profs = cv2.build_indices(profs)
    t0 = time.time()
    dc_value = cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=time_a, workers=workers, log=log,
    )
    elapsed = time.time() - t0
    with open(cache_path, "wb") as f:
        pickle.dump(dc_value, f)
    print(f"[decomp] cache scritta: {cache_path} ({elapsed:.1f}s)")
    return dc_value, elapsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True,
                        choices=["big", "medium", "huge", "superhuge",
                                 "small"])
    parser.add_argument("--k", type=int, default=4,
                        help="numero di cluster")
    parser.add_argument("--time-cluster", type=float, default=30.0,
                        help="time-limit CP-SAT per ogni (cluster, day)")
    parser.add_argument("--time-a", type=float, default=180.0,
                        help="time-limit Phase A se cache assente")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--write-xlsx", action="store_true",
                        help="scrive 2 xlsx in output/<profile>_decomp/")
    parser.add_argument("--log-phase-a", action="store_true")
    args = parser.parse_args()

    profs_path = os.path.join(HERE, f"profs_{args.profile}.pkl")
    school_path = os.path.join(HERE, f"school_{args.profile}.pkl")
    if not os.path.exists(profs_path):
        print(f"ERROR: {profs_path} non esiste. Esegui prima "
              f"cpsat_v2_assignment.py")
        return 1
    with open(profs_path, "rb") as f:
        profs = pickle.load(f)
    print(f"[decomp] profilo={args.profile}: {len(profs)} docenti, "
          f"{len(set(c for p in profs.values() for c in p['classi']))} classi")

    # 1) Adiacenza
    M, classes, cl_idx, teachers_per_class = build_adjacency(profs)
    n = len(classes)
    print(f"[decomp] matrice adiacenza {n}x{n} -- "
          f"max={M.max()} mean={M.mean():.1f} sparsity="
          f"{100.0*(M==0).sum()/M.size:.1f}%")

    # 2) Spectral clustering
    t0 = time.time()
    labels, eigvals = spectral_cluster(M, args.k)
    t_cluster = time.time() - t0
    print(f"[decomp] spectral clustering k={args.k}: {t_cluster:.2f}s")
    print(f"[decomp] primi {args.k+1} autovalori (gap = "
          f"K vs K+1 indica naturalezza della divisione): "
          f"{[f'{v:.4f}' for v in eigvals]}")
    cluster_sizes = {int(c): int((labels == c).sum()) for c in range(args.k)}
    print(f"[decomp] dimensioni cluster: {cluster_sizes}")

    # 3) Bridge teachers
    bridges, cl_to_label = find_bridge_teachers(profs, classes, labels)
    print(f"[decomp] docenti ponte: {len(bridges)}/{len(profs)} "
          f"({100.0 * len(bridges) / len(profs):.1f}%)")
    bridges_distribution = defaultdict(int)
    for p, cls in bridges.items():
        bridges_distribution[len(cls)] += 1
    print(f"[decomp] distribuzione (n_cluster_per_ponte): "
          f"{dict(sorted(bridges_distribution.items()))}")

    # Phase A interno (cache)
    dc_value, t_phase_a = load_or_build_phase_a(
        profs, args.profile, args.time_a, args.workers,
        args.log_phase_a,
    )

    # 4) Phase B decomposta sequenziale per giorno x cluster
    classes_per_cluster = defaultdict(set)
    for c, lbl in cl_to_label.items():
        classes_per_cluster[lbl].add(c)
    _, triples, _ = cv2.build_indices(profs)

    print("\n[decomp] inizio Phase B decomposta")
    full_solution = {}
    failed = []
    elapsed_b = 0.0
    # Ordina i cluster dal piu' PICCOLO al piu' grande. Il cluster
    # piccolo tipicamente ha la finestra di slot piu' stretta
    # (load=4 per molte classi) e va schedulato per primo: occupa
    # le sue ore "early" senza che i bridge le abbiano gia'
    # consumate. I cluster piu' grandi si adattano dopo.
    cluster_order = sorted(
        range(args.k),
        key=lambda k: len(classes_per_cluster[k]),
    )
    print(f"[decomp] ordine cluster (size ASC): {cluster_order}")
    for d in DAYS:
        # Per questo giorno: risolvi i K cluster sequenzialmente.
        # locked_slots e' accumulato fra cluster nello stesso giorno.
        locked_slots = {}                  # (prof, hour) -> True
        day_total_t = 0.0
        for k in cluster_order:
            cl_set = classes_per_cluster[k]
            t_kk = time.time()
            out, status = solve_cluster_day(
                cl_set, d, triples, dc_value, locked_slots,
                time_limit=args.time_cluster, workers=args.workers,
            )
            dt_kk = time.time() - t_kk
            day_total_t += dt_kk
            if out is None:
                print(f"[decomp] day={d} cluster={k}: INFEASIBLE "
                      f"({status})")
                failed.append((d, k))
                continue
            full_solution.update(out)
            # aggiorna lock dei docenti ponte per slot occupati in
            # questo cluster, in questo giorno
            for (p, cl, subj, day, h), v in out.items():
                if v == 1 and p in bridges:
                    locked_slots[(p, h)] = True
        elapsed_b += day_total_t
        # statistica giorno
        n_set = sum(1 for (_, _, _, dd, _), v in full_solution.items()
                    if v == 1 and dd == d)
        print(f"[decomp] day={d}: {day_total_t:.1f}s, {n_set} ore-classe "
              f"occupate")

    print(
        f"\n[decomp] TOTALE Phase B decomposta: {elapsed_b:.1f}s "
        f"({len(failed)} fallimenti)"
    )

    # 5) Verifica HARD
    print("\n[decomp] verifica vincoli HARD:")
    n_lessons = sum(1 for v in full_solution.values() if v == 1)
    fabbisogno = sum(
        meta["ore"] for p in profs.values()
        for cl, sm in p["classi"].items()
        for meta in sm.values()
    )
    print(f"  lezioni totali = {n_lessons} / fabbisogno = {fabbisogno}")
    present_cl = defaultdict(int)
    present_p = defaultdict(int)
    for (p, cl, subj, day, hour), v in full_solution.items():
        if v == 1:
            present_cl[(cl, day, hour)] += 1
            present_p[(p, day, hour)] += 1
    viol_holes = 0
    viol_ingress = 0
    viol_uscita = 0
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
    print(f"  HARD: classi con buchi={viol_holes}, "
          f"ingress non da 8={viol_ingress}, "
          f"uscita prima 12={viol_uscita}")
    print(f"  SOFT: 6^a ora occupate={sixth_count}, "
          f"buchi prof totali={total_buchi_prof}")

    # 6) Salvataggio soluzione
    out_pkl = os.path.join(HERE, f"solution_timetable_{args.profile}_decomp.pkl")
    with open(out_pkl, "wb") as f:
        pickle.dump(full_solution, f)
    print(f"[decomp] soluzione salvata in {out_pkl}")

    # 7) (opzionale) export xlsx
    if args.write_xlsx:
        from exporters import (
            export_class_schedules_to_xlsx,
            export_teacher_schedules_to_xlsx,
        )
        out_dir = os.path.join(HERE, "output", f"{args.profile}_decomp")
        export_class_schedules_to_xlsx(
            out_pkl, school_path, profs_path,
            os.path.join(out_dir, f"orario_classi_{args.profile}_decomp.xlsx"),
        )
        export_teacher_schedules_to_xlsx(
            out_pkl, school_path, profs_path,
            os.path.join(out_dir, f"orario_docenti_{args.profile}_decomp.xlsx"),
        )

    # 8) Riassunto finale
    print(f"\n[decomp] === RIASSUNTO {args.profile} ===")
    print(f"  k = {args.k}")
    print(f"  cluster sizes = {cluster_sizes}")
    print(f"  bridges = {len(bridges)}/{len(profs)}")
    print(f"  Phase A (cached or fresh) = "
          f"{'CACHE HIT' if t_phase_a == 0 else f'{t_phase_a:.1f}s'}")
    print(f"  Phase B decomposta = {elapsed_b:.1f}s "
          f"({len(failed)} cluster-day falliti)")
    print(f"  HARD viol = {viol_holes + viol_ingress + viol_uscita}")
    print(f"  SOFT 6^a ora = {sixth_count}, buchi prof = {total_buchi_prof}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
