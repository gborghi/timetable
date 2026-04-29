r"""Pipeline completa: decomposizione spettrale + metaeuristiche.

Sequenza:
    1. Carica profs + school pickles.
    2. Spectral clustering.
    3. Phase A interno (cache se disponibile).
    4. Stage A bridges + Stage B clusters + Stage C ricucitura +
       fallback monolitico.
    5. Cascata metaeuristica: LNS -> SA -> TS -> ILS.
    6. Verifica HARD finale + statistiche SOFT prima/dopo.
    7. Esporta xlsx con suffisso `_optimized`.

Uso:
    python run_full_pipeline.py --profile huge \
        [--budget-lns 300] [--budget-sa 120] [--budget-ts 120] \
        [--budget-ils 240]
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cpsat_v2_timetable as cv2  # noqa: E402
import decomposition_spectral_v2 as dec  # noqa: E402
import metaheuristics as meta  # noqa: E402
from exporters import (                          # noqa: E402
    export_class_schedules_to_xlsx,
    export_teacher_schedules_to_xlsx,
)


def run_decomposition(profs, profile, k, args):
    """Esegue le 4 fasi della decomposizione e restituisce
    (full_solution, classes_per_cluster, dc_value, timing)."""
    M, classes, _ = dec.build_adjacency(profs)
    labels, _ = dec.spectral_cluster(M, k)
    bridges, cl_to_label = dec.find_bridges(profs, classes, labels)
    classes_per_cluster = defaultdict(set)
    for c, lbl in cl_to_label.items():
        classes_per_cluster[lbl].add(c)
    print(
        f"[pipe] cluster sizes={dict((int(c), len(cs)) for c, cs in classes_per_cluster.items())}, "
        f"bridges={len(bridges)}/{len(profs)}"
    )
    dc_value, t_pa = dec.load_or_build_phase_a(
        profs, profile, args.time_a, args.workers, args.log
    )
    _, triples, _ = cv2.build_indices(profs)
    bridges_set = set(bridges.keys())

    print(f"\n[pipe] === STAGE A (bridges) ===")
    bridge_solutions = {}
    a_failed = []
    t0 = time.time()
    for d in dec.DAYS:
        out, status = dec.stage_a_bridges(
            d, profs, bridges_set, triples, dc_value,
            args.time_bridges, args.workers
        )
        if out is None:
            a_failed.append(d)
        else:
            bridge_solutions[d] = out
    t_sa = time.time() - t0
    print(f"[pipe] stage A: {t_sa:.1f}s, {len(a_failed)} giorni falliti")

    print(f"[pipe] === STAGE B (cluster internals) ===")
    cluster_solutions = {}
    b_failed = defaultdict(set)
    t0 = time.time()
    for d in dec.DAYS:
        if d not in bridge_solutions:
            continue
        for k_id in sorted(classes_per_cluster,
                            key=lambda k: -len(classes_per_cluster[k])):
            cl_set = classes_per_cluster[k_id]
            if not cl_set:
                continue
            out, status = dec.stage_b_cluster_internals(
                cl_set, d, profs, bridges_set, triples, dc_value,
                bridge_solutions[d], args.time_cluster, args.workers
            )
            if out is None:
                b_failed[d].add(k_id)
            else:
                cluster_solutions[(k_id, d)] = out
    t_sb = time.time() - t0
    n_b_fail = sum(len(s) for s in b_failed.values())
    print(f"[pipe] stage B: {t_sb:.1f}s, {n_b_fail} cluster-day falliti")

    full_solution = {}
    for d in dec.DAYS:
        if d in bridge_solutions:
            full_solution.update(bridge_solutions[d])
        for k_id in classes_per_cluster:
            if (k_id, d) in cluster_solutions:
                full_solution.update(cluster_solutions[(k_id, d)])

    print(f"[pipe] === STAGE C (ricucitura) ===")
    days_C = sorted(set(b_failed.keys()) | set(a_failed))
    c_failed = []
    t0 = time.time()
    for d in days_C:
        succ = {}
        for k_id in classes_per_cluster:
            if k_id in b_failed.get(d, set()):
                continue
            if (k_id, d) in cluster_solutions:
                succ.update(cluster_solutions[(k_id, d)])
        out, status = dec.stage_c_ricucitura(
            d, profs, bridges_set, triples, dc_value, succ,
            args.time_ricucitura, args.workers
        )
        if out is None:
            c_failed.append(d)
        else:
            full_solution = {
                k: v for k, v in full_solution.items() if k[3] != d
            }
            full_solution.update(out)
    t_sc = time.time() - t0
    print(f"[pipe] stage C: {t_sc:.1f}s, {len(c_failed)} falliti")

    print(f"[pipe] === MONOLITHIC fallback ===")
    m_failed = []
    t0 = time.time()
    for d in c_failed:
        out, status = dec.solve_monolithic_day(
            d, profs, triples, dc_value,
            args.time_mono, args.workers
        )
        if out is None:
            m_failed.append(d)
        else:
            full_solution = {
                k: v for k, v in full_solution.items() if k[3] != d
            }
            full_solution.update(out)
    t_mono = time.time() - t0
    print(f"[pipe] mono: {t_mono:.1f}s, {len(m_failed)} ANCORA falliti")

    timing = dict(
        phase_a=t_pa, stage_a=t_sa, stage_b=t_sb,
        stage_c=t_sc, mono=t_mono,
    )
    return full_solution, classes_per_cluster, dc_value, timing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--time-a", type=float, default=180.0)
    parser.add_argument("--time-bridges", type=float, default=60.0)
    parser.add_argument("--time-cluster", type=float, default=30.0)
    parser.add_argument("--time-ricucitura", type=float, default=120.0)
    parser.add_argument("--time-mono", type=float, default=240.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--log", action="store_true")
    parser.add_argument("--budget-lns", type=float, default=120.0)
    parser.add_argument("--budget-sa", type=float, default=60.0)
    parser.add_argument("--budget-ts", type=float, default=60.0)
    parser.add_argument("--budget-ils", type=float, default=120.0)
    parser.add_argument("--no-meta", action="store_true",
                        help="salta lo stage metaeuristico (per test)")
    args = parser.parse_args()

    profs_path = os.path.join(HERE, f"profs_{args.profile}.pkl")
    school_path = os.path.join(HERE, f"school_{args.profile}.pkl")
    with open(profs_path, "rb") as f:
        profs = pickle.load(f)
    print(f"[pipe] profilo={args.profile}: {len(profs)} docenti, "
          f"{len(set(c for p in profs.values() for c in p['classi']))} classi")

    t_pipeline_start = time.time()

    # Decomposizione (produce soluzione iniziale feasible)
    sol, classes_per_cluster, dc_value, timing = run_decomposition(
        profs, args.profile, args.k, args
    )
    t_decomp = (
        timing["stage_a"] + timing["stage_b"] +
        timing["stage_c"] + timing["mono"]
    )

    val0, metrics0 = meta.compute_soft(sol, profs)
    print(f"\n[pipe] === Decomposizione: obj={val0} metrics={metrics0}, "
          f"time decomp = {t_decomp:.1f}s ===")

    # Verifica feasibility iniziale
    print("[pipe] verifica HARD post-decomp...")
    if not meta.is_hard_feasible(sol, profs, verbose=True):
        print("[pipe] WARNING: soluzione iniziale viola qualche HARD!")

    # Cascade metaeuristica
    history = [("initial", 0.0, val0, metrics0)]
    if not args.no_meta:
        budgets = dict(
            lns=args.budget_lns,
            sa=args.budget_sa,
            ts=args.budget_ts,
            ils=args.budget_ils,
        )
        sol, history = meta.run_cascade(
            sol, profs, dc_value, budgets,
            classes_clusters=dict(classes_per_cluster), log=True
        )
        history = [("initial", 0.0, val0, metrics0)] + [
            h for h in history if h[0] != "initial"
        ]

    val_final, metrics_final = meta.compute_soft(sol, profs)
    print(f"\n[pipe] === Final: obj={val_final} metrics={metrics_final} ===")

    # Verifica HARD finale
    print("[pipe] verifica HARD post-meta...")
    if not meta.is_hard_feasible(sol, profs, verbose=True):
        print("[pipe] WARNING: soluzione finale viola qualche HARD!")
    else:
        print("[pipe] OK soluzione finale rispetta tutti gli HARD")

    # Salva soluzione
    out_pkl = os.path.join(
        HERE, f"solution_timetable_{args.profile}_optimized.pkl"
    )
    with open(out_pkl, "wb") as f:
        pickle.dump(sol, f)
    print(f"[pipe] salvato {out_pkl}")

    # Esporta xlsx
    out_dir = os.path.join(HERE, "output", args.profile)
    out_classi = os.path.join(
        out_dir, f"orario_classi_{args.profile}_optimized.xlsx"
    )
    out_doc = os.path.join(
        out_dir, f"orario_docenti_{args.profile}_optimized.xlsx"
    )
    export_class_schedules_to_xlsx(out_pkl, school_path, profs_path, out_classi)
    export_teacher_schedules_to_xlsx(out_pkl, school_path, profs_path, out_doc)

    # Storia per benchmarks
    print(f"\n[pipe] === HISTORY ({args.profile}) ===")
    for stage, dt, val, m in history:
        print(f"  {stage:10s}: t={dt:7.1f}s obj={val:6d} metrics={m}")

    # Salva history
    hist_path = os.path.join(
        HERE, f"history_{args.profile}.pkl"
    )
    with open(hist_path, "wb") as f:
        pickle.dump(history, f)

    t_pipeline_total = time.time() - t_pipeline_start
    print(f"\n[pipe] TOTALE pipeline: {t_pipeline_total:.1f}s")


if __name__ == "__main__":
    sys.exit(main())
