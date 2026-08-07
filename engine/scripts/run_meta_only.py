r"""Esegue SOLO la cascata metaeuristica su una soluzione decomposta
gia\` calcolata (cachata in solution_timetable_<profile>_decomposed.pkl).

Utile per separare la misura della parte meta dal costo della
decomposizione + Phase A (gia\` cachato).

Uso:
    python run_meta_only.py --profile huge \\
        [--budget-lns 300] [--budget-sa 60] [--budget-ts 60] \\
        [--budget-ils 240]

Output:
    - solution_timetable_<profile>_optimized.pkl
    - history_<profile>.pkl
    - output/<profile>/orario_{classi,docenti}_<profile>_optimized.xlsx
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import decomposition_spectral_v2 as dec  # noqa: E402
import metaheuristics as meta  # noqa: E402
from exporters import (  # noqa: E402
    export_class_schedules_to_xlsx,
    export_teacher_schedules_to_xlsx,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--k", type=int, default=4,
                        help="K per ricostruire i cluster classes (per LNS)")
    parser.add_argument("--budget-lns", type=float, default=120.0)
    parser.add_argument("--budget-sa", type=float, default=60.0)
    parser.add_argument("--budget-ts", type=float, default=60.0)
    parser.add_argument("--budget-ils", type=float, default=120.0)
    args = parser.parse_args()

    profs_path = os.path.join(HERE, f"profs_{args.profile}.pkl")
    school_path = os.path.join(HERE, f"school_{args.profile}.pkl")
    decomp_pkl = os.path.join(
        HERE, f"solution_timetable_{args.profile}_decomposed.pkl"
    )
    dc_pkl = os.path.join(HERE, f"phase_a_dc_{args.profile}.pkl")

    with open(profs_path, "rb") as f:
        profs = pickle.load(f)
    with open(decomp_pkl, "rb") as f:
        sol = pickle.load(f)
    with open(dc_pkl, "rb") as f:
        dc_value = pickle.load(f)

    print(f"[meta_only] profilo={args.profile}: {len(profs)} docenti")

    # Ricostruisci cluster classes per LNS / ILS
    M, classes, _ = dec.build_adjacency(profs)
    labels, _ = dec.spectral_cluster(M, args.k)
    classes_per_cluster = defaultdict(set)
    for i, c in enumerate(classes):
        classes_per_cluster[int(labels[i])].add(c)

    val0, m0 = meta.compute_soft(sol, profs)
    print(f"[meta_only] initial: obj={val0} metrics={m0}")

    if not meta.is_hard_feasible(sol, profs, verbose=False):
        print("[meta_only] WARNING: soluzione iniziale non feasible!")

    budgets = dict(
        lns=args.budget_lns,
        sa=args.budget_sa,
        ts=args.budget_ts,
        ils=args.budget_ils,
    )
    sol2, history = meta.run_cascade(
        sol, profs, dc_value, budgets,
        classes_clusters=dict(classes_per_cluster), log=True
    )

    val_final, m_final = meta.compute_soft(sol2, profs)
    print(f"\n[meta_only] === Final: obj={val_final} metrics={m_final} ===")

    if not meta.is_hard_feasible(sol2, profs, verbose=True):
        print("[meta_only] WARNING: HARD violato dopo metaeuristica!")
    else:
        print("[meta_only] OK HARD rispettato")

    out_pkl = os.path.join(
        HERE, f"solution_timetable_{args.profile}_optimized.pkl"
    )
    with open(out_pkl, "wb") as f:
        pickle.dump(sol2, f)
    hist_path = os.path.join(HERE, f"history_{args.profile}.pkl")
    with open(hist_path, "wb") as f:
        pickle.dump(history, f)

    out_dir = os.path.join(HERE, "output", args.profile)
    out_classi = os.path.join(
        out_dir, f"orario_classi_{args.profile}_optimized.xlsx"
    )
    out_doc = os.path.join(
        out_dir, f"orario_docenti_{args.profile}_optimized.xlsx"
    )
    export_class_schedules_to_xlsx(
        out_pkl, school_path, profs_path, out_classi
    )
    export_teacher_schedules_to_xlsx(
        out_pkl, school_path, profs_path, out_doc
    )

    print(f"\n[meta_only] === HISTORY {args.profile} ===")
    for stage, dt, val, m in history:
        print(f"  {stage:10s}: t={dt:7.1f}s obj={val:6d} metrics={m}")


if __name__ == "__main__":
    sys.exit(main())
