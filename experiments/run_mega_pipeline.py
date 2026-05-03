"""MEGA end-to-end pipeline driver: temporal decomposition + ALNS.

Run from the experiments/ directory:

    python run_mega_pipeline.py
"""
import sys
import time
import pickle
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import decomposition_temporal as dt
import metaheuristics as meta
import alns


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    profs_path = os.path.join(here, "profs_mega.pkl")
    out_path = os.path.join(here, "solution_mega_temporal_alns.pkl")
    dc_path = os.path.join(here, "dc_mega.pkl")

    print("=== MEGA temporal pipeline ===")
    t0 = time.time()
    result = dt.run_temporal_pipeline(
        profs_path,
        parallel=True, n_workers=6,
        time_a=300, time_day=120,
        day_timeout=900,
        cpsat_workers_per_day=2,
        enforce_no_holes=True,
        log_progress=True,
        out_path=out_path,
        dc_out_path=dc_path,
    )
    t_temporal = time.time() - t0
    print()
    print(f"temporal status: {result['status']}")
    print(f"temporal wall: {t_temporal:.1f}s")
    print(f"  master:      {result['timings']['master']:.1f}s")
    print(f"  days_total:  {result['timings']['days_total']:.1f}s")
    print(f"  failed days: {result['failed_days']}")

    if result["status"] != "ok":
        print("Pipeline non chiusa, esco.")
        return

    with open(profs_path, "rb") as f:
        profs = pickle.load(f)
    sol = result["full_solution"]
    dc_value = result["dc_value"]
    v0, m0 = meta.compute_soft(sol, profs)
    feasible = meta.is_hard_feasible(sol, profs, verbose=False)
    print(f"temporal: HARD_feasible={feasible}, SOFT obj={v0:.1f}")

    print()
    print("=== ALNS finishing (budget 1200s) ===")
    t0 = time.time()
    refined, _hist = alns.run_alns(
        sol, profs, dc_value, 1200,
        log=False, workers=4,
    )
    dt_alns = time.time() - t0
    v1, m1 = meta.compute_soft(refined, profs)
    feas1 = meta.is_hard_feasible(refined, profs, verbose=False)
    print(f"ALNS: {dt_alns:.0f}s, HARD_feasible={feas1}, SOFT obj={v1:.1f}")

    if feas1 and v1 <= v0:
        with open(out_path, "wb") as f:
            pickle.dump(refined, f)
        print(f"ALNS improvement: {v0:.1f} -> {v1:.1f} "
              f"(delta {v0 - v1:.1f}, {((v0 - v1) / v0 * 100):.1f}%)")
        final_sol = refined
        final_v = v1
    else:
        with open(out_path, "wb") as f:
            pickle.dump(sol, f)
        print("ALNS dropped (no improvement or infeasible)")
        final_sol = sol
        final_v = v0

    total = t_temporal + dt_alns
    print()
    print("=== Final summary ===")
    print(f"profile:        mega")
    print(f"classes:        100")
    print(f"teachers:       178")
    print(f"weekly hours:   2976")
    print(f"temporal wall:  {t_temporal:.0f}s")
    print(f"ALNS wall:      {dt_alns:.0f}s")
    print(f"TOTAL:          {total:.0f}s ({total / 60:.1f} min)")
    print(f"final SOFT obj: {final_v:.1f}")
    print(f"final cells:    {len(final_sol)}")
    print(f"saved:          {out_path}")


if __name__ == "__main__":
    main()
