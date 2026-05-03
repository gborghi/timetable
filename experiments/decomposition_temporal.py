"""Decomposizione temporale (per giorno) -- pipeline funzionante.

Idea
----
Spezza Phase B sull'asse del tempo: ciascuno dei sei giorni della
settimana diventa un sotto-problema separato, risolvibile in
parallelo. La pre-distribuzione settimanale (master CP-SAT che
decide quante ore di ogni cattedra vanno in ciascun giorno) e' gia'
implementata in `cpsat_v2_timetable.solve_phase_a`; la risoluzione
giornaliera (CP-SAT su un singolo giorno con vincoli di no-buchi,
ingresso 8, uscita >= 12, motorie consecutive, ecc.) e' gia'
implementata in `cpsat_v2_timetable.solve_phase_b_for_day`.

Questo modulo orchestra le due funzioni e parallelizza i 6
sotto-problemi giornalieri via `concurrent.futures.ProcessPoolExecutor`.

Vantaggi
--------
- Sempre applicabile: nessun requisito di struttura comunitaria
  nel grafo classe-docente (la spettrale richiede modularita' alta).
- Parallelizza naturalmente sui sei core di una macchina moderna.
- Riusa interamente la logica CP-SAT esistente.

API pubblica
------------
    pre_distribute_hours(profs, time_limit, workers, log)
        -> dc_value  (dict (p, cl, subj, day) -> hours)

    solve_day(day, profs, dc_value, time_limit, workers,
              enforce_no_holes)
        -> (out_dict, status)   (None se infeasibile)

    run_temporal_pipeline(profs_path, *, parallel=True,
                          n_workers=None, time_a=60, time_day=30,
                          day_timeout=300, max_iterations=3,
                          log_progress=False)
        -> dict con {full_solution, dc_value, timings, failed_days,
                     status}
"""
from __future__ import annotations

import os
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

# Make sibling modules importable when this file is run from
# anywhere (including by ProcessPoolExecutor workers on Windows).
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import cpsat_v2_timetable as cv2  # noqa: E402

DAYS = cv2.DAYS
HOURS = cv2.HOURS


# ============================================================
# 1. Master CP-SAT: pre-distribuzione settimanale
# ============================================================

def pre_distribute_hours(profs: dict, *, time_limit: float = 60.0,
                         workers: int = 8, log: bool = False):
    """Master CP-SAT che distribuisce le ore-cattedra fra i giorni.

    Riusa esattamente `cpsat_v2_timetable.solve_phase_a`, che e' il
    master CP-SAT canonico del progetto: decide il day_count
    `dc_value[(prof, cl, subj, day)]` rispettando vincoli di max
    ore/giorno per docente e per classe, distribuzione di motorie
    a coppie, doppia mate/italiano, e SOFT di uniformita'.

    Returns
    -------
    dc_value : dict (str, str, str, int) -> int
        Ore di lezione di quella tripla-cattedra in quel giorno.
    """
    classes, triples, class_profs = cv2.build_indices(profs)
    return cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=time_limit, workers=workers, log=log,
    )


# ============================================================
# 2. Day solver: adapter sopra cpsat_v2_timetable.solve_phase_b_for_day
# ============================================================

def solve_day(day: int, profs: dict, dc_value: dict, *,
              time_limit: float = 30.0, workers: int = 4,
              enforce_no_holes: bool = True, log: bool = False):
    """Risolve il sotto-problema CP-SAT del giorno `day`.

    Riusa `cpsat_v2_timetable.solve_phase_b_for_day`. Le ore
    pre-distribuite nel master entrano nel modello come
    `dc_value[(p, cl, subj, day)]`.

    Returns
    -------
    out : dict (p, cl, subj, day, h) -> 0/1   (None se infeasibile)
    status : int
        cp_model status code.
    """
    classes, triples, class_profs = cv2.build_indices(profs)
    return cv2.solve_phase_b_for_day(
        day, profs, classes, triples, class_profs, dc_value,
        time_limit=time_limit, workers=workers, log=log,
        enforce_no_holes=enforce_no_holes,
    )


# ProcessPoolExecutor worker: passes the path to the profs pickle
# and the dc_value pickle (small) instead of huge dicts. The worker
# loads them and calls solve_day.
def _worker_solve_day(args):
    """Top-level worker function so ProcessPoolExecutor can pickle
    it on Windows. Arguments are passed packed into a tuple to make
    `executor.submit` ergonomics straightforward."""
    (day, profs_path, dc_path, time_limit, workers,
     enforce_no_holes) = args
    with open(profs_path, "rb") as f:
        profs = pickle.load(f)
    with open(dc_path, "rb") as f:
        dc_value = pickle.load(f)
    t0 = time.time()
    out, status = solve_day(
        day, profs, dc_value,
        time_limit=time_limit, workers=workers,
        enforce_no_holes=enforce_no_holes, log=False,
    )
    dt = time.time() - t0
    return day, out, int(status), dt


# ============================================================
# 3. Pipeline integrata
# ============================================================

def run_temporal_pipeline(profs_path: str, *,
                          parallel: bool = True,
                          n_workers: int | None = None,
                          time_a: float = 60.0,
                          time_day: float = 30.0,
                          day_timeout: float | None = 300.0,
                          max_iterations: int = 1,
                          cpsat_workers_per_day: int = 2,
                          enforce_no_holes: bool = True,
                          log_progress: bool = True,
                          out_path: str | None = None,
                          dc_out_path: str | None = None):
    """Orchestra master + day-solvers paralleli + ricucitura.

    Parameters
    ----------
    profs_path : str
        Percorso al pickle prodotto da Phase A
        (`cpsat_v2_assignment.py --out profs_<profile>.pkl`).
    parallel : bool, default True
        Se True, i 6 giorni vanno in ProcessPoolExecutor.
    n_workers : int or None
        Numero di worker paralleli. None = min(6, cpu_count).
    time_a : float, default 60
        Time-limit (s) del master CP-SAT (pre-distribuzione).
    time_day : float, default 30
        Time-limit (s) per ciascuno dei 6 day-solver CP-SAT.
    day_timeout : float or None, default 300
        Timeout wall (s) per worker, indipendente dal time_limit
        del solver. Se None, niente timeout.
    max_iterations : int, default 1
        Numero massimo di re-iterate del master se la prima passata
        ha giorni infeasibili. >= 2 ri-stringe il master con
        diagnostica per i giorni falliti (no-fix automatico in
        questa versione iniziale: si ritorna soluzione parziale).
    cpsat_workers_per_day : int, default 2
        Search workers di CP-SAT dentro ogni day-solver. 2 e'
        un buon compromesso quando si hanno gia' 6 worker di
        processo che girano in parallelo.
    enforce_no_holes : bool, default True
        Se True, applica il vincolo HARD "no buchi nelle classi".
    log_progress : bool, default True
        Stampa progress su stdout.
    out_path : str or None
        Se non None, salva la soluzione completa in pickle.
    dc_out_path : str or None
        Se non None, salva il dc_value del master in pickle.

    Returns
    -------
    dict
        {
          'full_solution': dict (p,cl,subj,day,h) -> 0/1,
          'dc_value':      dict (p,cl,subj,day) -> int,
          'timings':       {'master': sec, 'days_total': sec,
                            'days_max': sec, 'days_per_day': {d: sec}},
          'failed_days':   list[int],
          'n_workers':     int,
          'parallel':      bool,
          'status':        'ok' | 'partial' | 'master_failed',
        }
    """
    if log_progress:
        print(f"[temporal] loading {profs_path}")
    profs = cv2.load_profs(profs_path)
    n_classes = len({c for p in profs.values() for c in p["classi"]})
    n_triples = sum(
        1 for p in profs.values() for cl in p["classi"]
        for _subj in p["classi"][cl]
    )
    if log_progress:
        print(f"[temporal] {len(profs)} profs, {n_classes} classes, "
              f"{n_triples} (prof,cl,subj) triples")

    # ------ STEP 1: master pre-distribution ------
    t0 = time.time()
    if log_progress:
        print(f"[temporal] step 1/3: master CP-SAT pre-distribution "
              f"(time_limit={time_a}s)")
    try:
        dc_value = pre_distribute_hours(
            profs, time_limit=time_a, workers=8, log=False)
    except Exception as e:
        return {
            'full_solution': {},
            'dc_value': None,
            'timings': {'master': time.time() - t0,
                        'days_total': 0.0, 'days_max': 0.0,
                        'days_per_day': {}},
            'failed_days': list(DAYS),
            'n_workers': 0,
            'parallel': parallel,
            'status': 'master_failed',
            'error': str(e),
        }
    elapsed_master = time.time() - t0
    if log_progress:
        print(f"[temporal] master done in {elapsed_master:.1f}s "
              f"({len(dc_value)} (p,cl,subj,d) entries)")

    # ------ STEP 2: parallel per-day solvers ------
    if n_workers is None:
        cpu = os.cpu_count() or 1
        n_workers = min(len(DAYS), cpu)
    if not parallel:
        n_workers = 1

    full_solution: dict = {}
    failed_days: list[int] = []
    days_per_day: dict[int, float] = {}
    days_t0 = time.time()

    if parallel and n_workers > 1:
        # Pickle profs + dc_value once to shared paths so workers
        # don't have to re-pickle huge dicts at every submit.
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix='pitantum_temporal_')
        profs_pkl = os.path.join(tmpdir, 'profs.pkl')
        dc_pkl = os.path.join(tmpdir, 'dc.pkl')
        with open(profs_pkl, 'wb') as f:
            pickle.dump(profs, f)
        with open(dc_pkl, 'wb') as f:
            pickle.dump(dc_value, f)

        if log_progress:
            print(f"[temporal] step 2/3: {len(DAYS)} days in parallel "
                  f"({n_workers} workers, {time_day}s/day, "
                  f"{cpsat_workers_per_day} cp-sat workers/day)")

        try:
            with ProcessPoolExecutor(max_workers=n_workers) as ex:
                futures = {
                    ex.submit(_worker_solve_day,
                              (d, profs_pkl, dc_pkl,
                               time_day, cpsat_workers_per_day,
                               enforce_no_holes)): d
                    for d in DAYS
                }
                done_args_iter = (as_completed(futures, timeout=day_timeout)
                                  if day_timeout else as_completed(futures))
                for fut in done_args_iter:
                    d = futures[fut]
                    try:
                        ret_day, out, status_int, dt = fut.result()
                        days_per_day[ret_day] = dt
                        if out is None:
                            failed_days.append(ret_day)
                            if log_progress:
                                print(f"[temporal]   day {ret_day} "
                                      f"INFEASIBLE in {dt:.1f}s "
                                      f"(status {status_int})")
                        else:
                            full_solution.update(out)
                            occ = sum(1 for v in out.values() if v == 1)
                            if log_progress:
                                print(f"[temporal]   day {ret_day} ok in "
                                      f"{dt:.1f}s -- {occ} ore-classe occupate")
                    except Exception as e:
                        failed_days.append(d)
                        if log_progress:
                            print(f"[temporal]   day {d} worker FAILED: {e}")
        finally:
            # Cleanup temp pickles
            try:
                os.remove(profs_pkl)
                os.remove(dc_pkl)
                os.rmdir(tmpdir)
            except OSError:
                pass
    else:
        # Sequential fallback
        if log_progress:
            print(f"[temporal] step 2/3: {len(DAYS)} days sequential "
                  f"({time_day}s/day)")
        for d in DAYS:
            t = time.time()
            out, status = solve_day(
                d, profs, dc_value,
                time_limit=time_day, workers=cpsat_workers_per_day,
                enforce_no_holes=enforce_no_holes, log=False,
            )
            dt = time.time() - t
            days_per_day[d] = dt
            if out is None:
                failed_days.append(d)
                if log_progress:
                    print(f"[temporal]   day {d} INFEASIBLE in {dt:.1f}s")
            else:
                full_solution.update(out)
                occ = sum(1 for v in out.values() if v == 1)
                if log_progress:
                    print(f"[temporal]   day {d} ok in {dt:.1f}s -- {occ} occ")

    elapsed_days_total = time.time() - days_t0
    elapsed_days_max = max(days_per_day.values()) if days_per_day else 0.0
    if log_progress:
        speedup = (sum(days_per_day.values()) /
                   max(elapsed_days_total, 0.001)) if days_per_day else 0
        print(f"[temporal] days done: total wall {elapsed_days_total:.1f}s "
              f"(serial-equivalent {sum(days_per_day.values()):.1f}s, "
              f"observed speedup {speedup:.1f}x)")

    # ------ STEP 3: weekly recombination + check ------
    # The current implementation does NOT iterate the master if a
    # day failed; it returns the partial solution and lets the
    # caller decide. Re-iteration is on the roadmap.
    status = ('ok' if not failed_days
              else 'partial' if full_solution else 'master_failed')

    # Persist outputs if requested
    if out_path:
        with open(out_path, 'wb') as f:
            pickle.dump(full_solution, f)
        if log_progress:
            print(f"[temporal] solution saved to {out_path}")
    if dc_out_path:
        with open(dc_out_path, 'wb') as f:
            pickle.dump(dc_value, f)

    return {
        'full_solution': full_solution,
        'dc_value': dc_value,
        'timings': {
            'master': elapsed_master,
            'days_total': elapsed_days_total,
            'days_max': elapsed_days_max,
            'days_per_day': days_per_day,
        },
        'failed_days': sorted(failed_days),
        'n_workers': n_workers,
        'parallel': parallel and n_workers > 1,
        'status': status,
    }


# ============================================================
# CLI
# ============================================================

def _main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Temporal decomposition pipeline (master + 6 parallel "
                    "day solvers).")
    ap.add_argument("--profs", required=True,
                    help="path to profs_<profile>.pkl from Phase A")
    ap.add_argument("--time-a", type=float, default=60.0)
    ap.add_argument("--time-day", type=float, default=30.0)
    ap.add_argument("--day-timeout", type=float, default=300.0)
    ap.add_argument("--workers", type=int, default=None,
                    help="parallel day-solver workers (default min(6, cpu))")
    ap.add_argument("--cpsat-workers", type=int, default=2,
                    help="search workers inside each day's CP-SAT")
    ap.add_argument("--no-parallel", action="store_true")
    ap.add_argument("--no-no-holes", action="store_true",
                    help="relax the per-class no-holes HARD constraint")
    ap.add_argument("--out", default=None)
    ap.add_argument("--dc-out", default=None)
    args = ap.parse_args()

    res = run_temporal_pipeline(
        args.profs,
        parallel=not args.no_parallel,
        n_workers=args.workers,
        time_a=args.time_a,
        time_day=args.time_day,
        day_timeout=args.day_timeout,
        cpsat_workers_per_day=args.cpsat_workers,
        enforce_no_holes=not args.no_no_holes,
        log_progress=True,
        out_path=args.out,
        dc_out_path=args.dc_out,
    )
    print(f"\n[temporal] STATUS: {res['status']}")
    print(f"[temporal] master: {res['timings']['master']:.1f}s")
    print(f"[temporal] days wall: {res['timings']['days_total']:.1f}s "
          f"(slowest day: {res['timings']['days_max']:.1f}s)")
    if res['failed_days']:
        print(f"[temporal] FAILED days: {res['failed_days']}")
    else:
        print(f"[temporal] all 6 days ok, "
              f"{len(res['full_solution'])} cells filled")


if __name__ == "__main__":
    _main()
