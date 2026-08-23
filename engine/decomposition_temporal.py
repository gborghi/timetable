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
import multiprocessing as _mp
from concurrent.futures import ProcessPoolExecutor, as_completed


def _pool_ctx():
    """Force a ``fork`` start method for the per-day pool where available.

    macOS/Windows default to ``spawn``, which re-imports the caller's
    ``__main__`` -- that raises "an attempt has been made to start a new
    process before the current process has finished its bootstrapping phase"
    whenever the engine is driven from an unguarded script or test (the webui
    backend, a proper module, is unaffected, but drivers/harnesses trip on
    it). ``fork`` copies the already-bootstrapped parent, sidestepping the
    re-import. Falls back to the platform default when fork is unavailable.
    """
    try:
        if "fork" in _mp.get_all_start_methods():
            return _mp.get_context("fork")
    except Exception:  # noqa: BLE001
        pass
    return None

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
                         workers: int = 8, log: bool = False,
                         locked_day_count: dict | None = None,
                         coteach_groups: list | None = None,
                         group_assignments: list | None = None,
                         class_day_load_allowed: dict | None = None,
                         class_free_days: dict | None = None):
    """Master CP-SAT che distribuisce le ore-cattedra fra i giorni.

    Riusa esattamente `cpsat_v2_timetable.solve_phase_a`, che e' il
    master CP-SAT canonico del progetto: decide il day_count
    `dc_value[(prof, cl, subj, day)]` rispettando vincoli di max
    ore/giorno per docente e per classe, distribuzione di motorie
    a coppie, doppia mate/italiano, e SOFT di uniformita'.

    Se `locked_day_count` e' valorizzato, e' un dict
    `(prof, class, subject, day) -> int` che impone un FLOOR sul
    numero di ore di quella cattedra nel giorno indicato.

    Se `coteach_groups` e' valorizzato, e' la lista di dict consumata
    da solve_phase_a per imporre i vincoli di compresenza.

    Returns
    -------
    dc_value : dict (str, str, str, int) -> int
        Ore di lezione di quella tripla-cattedra in quel giorno.
    """
    classes, triples, class_profs = cv2.build_indices(profs)
    return cv2.solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=time_limit, workers=workers, log=log,
        locked_day_count=locked_day_count,
        coteach_groups=coteach_groups,
        group_assignments=group_assignments,
        class_day_load_allowed=class_day_load_allowed,
        class_free_days=class_free_days,
    )


# ============================================================
# 2. Day solver: adapter sopra cpsat_v2_timetable.solve_phase_b_for_day
# ============================================================

def solve_day(day: int, profs: dict, dc_value: dict, *,
              time_limit: float = 30.0, workers: int = 4,
              enforce_no_holes: bool = True, log: bool = False,
              locked_slots_for_day: list | None = None,
              coteach_groups: list | None = None,
              group_assignments: list | None = None,
              special_room_ctx=None,
              class_flags=None,
              total_room_capacity=None,
              support_assignments: list | None = None,
              parallel_groups: list | None = None,
              plessi_ctx=None,
              dsl_hard_expressions: list | None = None,
              warm_start=None,
              room_slot_penalties=None):
    """Risolve il sotto-problema CP-SAT del giorno `day`.

    Riusa `cpsat_v2_timetable.solve_phase_b_for_day`. Le ore
    pre-distribuite nel master entrano nel modello come
    `dc_value[(p, cl, subj, day)]`.

    Se `locked_slots_for_day` e' valorizzato, e' un iterable di
    tuple `(prof, class, subject, hour)` che devono valere 1 nel
    risultato (sono i lock nativi).

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
        locked_slots_for_day=locked_slots_for_day,
        coteach_groups=coteach_groups,
        support_assignments=support_assignments,
        parallel_groups=parallel_groups,
        group_assignments=group_assignments,
        special_room_ctx=special_room_ctx,
        class_flags=class_flags,
        total_room_capacity=total_room_capacity,
        plessi_ctx=plessi_ctx,
        via_dsl=bool(dsl_hard_expressions),
        dsl_hard_expressions=dsl_hard_expressions or None,
        warm_start=warm_start,
        room_slot_penalties=room_slot_penalties,
    )


def hint_from_day(sol: dict | None, target_day: int) -> dict:
    """Map a neighbour day's occupancy onto ``target_day`` as a warm start.

    Same (teacher, class, subject, hour) cells, new day. Empty / None
    yields {}. Best-effort: CP-SAT may ignore the hint.
    """
    if not sol:
        return {}
    out = {}
    for k, v in sol.items():
        if not v:
            continue
        if len(k) != 5:
            continue
        p, cl, subj, _d, h = k
        out[(p, cl, subj, target_day, h)] = 1
    return out


def explain_day_infeasibility(profs, dc_value, day) -> dict:
    """Human-readable IIS-ish report for a failed Phase B day.

    Hall (prof hours that day exceed the busiest class they teach),
    class load in {1,2,3} (HARD-2 band), prof overload (> max hours
    per day). Computed from ``dc_value`` so it does not depend on
    ``engine/scripts`` being importable or on the full ``profs``
    shape. ``profs`` is accepted for API compatibility.
    """
    del profs  # unused; kept so call sites stay (profs, dc, day)
    from collections import defaultdict
    prof_classes_day = defaultdict(set)
    prof_hours_day = defaultdict(int)
    cl_load_day = defaultdict(int)
    for key, cnt in (dc_value or {}).items():
        if not cnt:
            continue
        if len(key) != 4:
            continue
        p, cl, _subj, d = key
        if d != day:
            continue
        prof_classes_day[p].add(cl)
        prof_hours_day[p] += int(cnt)
        cl_load_day[cl] += int(cnt)

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

    class_load_outliers = [
        dict(**{"class": cl}, day_load=load)
        for cl, load in cl_load_day.items()
        if load in (1, 2, 3)
    ]
    max_prof = getattr(cv2, "MAX_PROF_HOURS_PER_DAY", 5)
    prof_overload = [
        dict(prof=p, total_hours_in_day=h)
        for p, h in prof_hours_day.items()
        if h > max_prof
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
            f"{len(prof_overload)} docenti con > {max_prof} ore in un "
            f"giorno (HARD-C)"
        )
    if not summary_parts:
        summary_parts.append(
            "Nessuna violazione strutturale evidente. "
            "Causa probabile: combinatoria slot+coppie consecutive "
            "(motorie / mat-ita doppia), oppure no-holes troppo stretto."
        )
    return dict(
        day=day,
        hall_violations=hall_violations,
        class_load_outliers=class_load_outliers,
        prof_overload=prof_overload,
        summary=" | ".join(summary_parts),
    )


def format_infeasibility(expl: dict) -> str:
    """One-line suffix for a Phase B INFEASIBLE RuntimeError / log."""
    if not expl:
        return ""
    s = expl.get("summary") or ""
    return f" Causa: {s}" if s else ""


def days_from_room_penalties(penalties: dict | None) -> set[int]:
    """Days that carry a room-λ (hour-only keys have no day)."""
    out: set[int] = set()
    for k in (penalties or {}):
        if isinstance(k, tuple) and len(k) == 2:
            out.add(int(k[0]))
    return out


def refine_days_with_room_penalties(
        sol: dict, profs: dict, dc_value: dict,
        room_slot_penalties: dict | None, *,
        locked_by_day: dict | None = None,
        time_limit: float = 30.0, workers: int = 4,
        **solve_kw) -> tuple[dict, dict]:
    """Re-solve the days named by ``room_slot_penalties`` with λ in
    the soft objective, warm-started from the incumbent.

    Days without a (day, hour) key are left untouched. A failed
    re-solve keeps the incumbent day. Returns ``(new_sol, info)``.
    """
    info = {
        "retried_days": [],
        "replaced_days": [],
        "failed_days": [],
        "accepted": False,
    }
    days = days_from_room_penalties(room_slot_penalties)
    if not sol or not days:
        return sol, info
    locks = locked_by_day or {}
    merged = dict(sol)
    any_replaced = False
    for d in sorted(days):
        info["retried_days"].append(int(d))
        warm = {k: v for k, v in sol.items()
                if v and len(k) == 5 and k[3] == d}
        out, _st = solve_day(
            d, profs, dc_value,
            locked_slots_for_day=locks.get(d),
            warm_start=warm or None,
            room_slot_penalties=room_slot_penalties,
            time_limit=time_limit, workers=workers,
            **solve_kw)
        if out is None:
            info["failed_days"].append(int(d))
            continue
        for k in list(merged):
            if len(k) == 5 and k[3] == d:
                del merged[k]
        merged.update(out)
        info["replaced_days"].append(int(d))
        any_replaced = True
    info["accepted"] = any_replaced
    return merged, info


def fix_and_optimize_two_days(
        d_ok: int, d_fail: int, profs: dict, dc_value: dict,
        sol_ok: dict, *,
        time_limit: float = 30.0, workers: int = 4,
        enforce_no_holes: bool = True,
        locked_by_day: dict | None = None,
        **solve_kw) -> tuple[dict | None, dict | None]:
    """2-day fix-and-optimize: re-solve the failed day using the
    neighbour as a warm start; if that still fails, re-solve the
    neighbour (hinted by its own incumbent) then retry the failed day.

    Returns ``(new_sol_ok, new_sol_fail)``. Either may be None.
    """
    kw = dict(solve_kw)
    kw.setdefault("time_limit", time_limit)
    kw.setdefault("workers", workers)
    kw.setdefault("enforce_no_holes", enforce_no_holes)
    locks = locked_by_day or {}
    out_fail, _ = solve_day(
        d_fail, profs, dc_value,
        locked_slots_for_day=locks.get(d_fail),
        warm_start=hint_from_day(sol_ok, d_fail),
        **kw)
    if out_fail is not None:
        return sol_ok, out_fail
    out_ok, _ = solve_day(
        d_ok, profs, dc_value,
        locked_slots_for_day=locks.get(d_ok),
        warm_start=sol_ok,
        **kw)
    if out_ok is None:
        out_ok = sol_ok
    out_fail, _ = solve_day(
        d_fail, profs, dc_value,
        locked_slots_for_day=locks.get(d_fail),
        warm_start=hint_from_day(out_ok, d_fail),
        **kw)
    return out_ok, out_fail


# ProcessPoolExecutor worker: passes the path to the profs pickle
# and the dc_value pickle (small) instead of huge dicts. The worker
# loads them and calls solve_day.
def _worker_solve_day(args):
    """Top-level worker function so ProcessPoolExecutor can pickle
    it on Windows. Arguments are packed into a variable-length
    tuple for backward compat:
      - 6 elements: legacy (no locks, no coteach)
      - 7 elements: + locked_slots_for_day
      - 8 elements: + coteach_groups
    """
    special_room_ctx = None
    class_flags = None
    total_room_capacity = None
    support_assignments = None
    parallel_groups = None
    plessi_ctx = None
    dsl_hard_expressions = None
    if len(args) == 16:
        (day, profs_path, dc_path, time_limit, workers,
         enforce_no_holes, locked_slots_for_day,
         coteach_groups, group_assignments,
         special_room_ctx, class_flags,
         support_assignments, parallel_groups, plessi_ctx,
         dsl_hard_expressions, total_room_capacity) = args
    elif len(args) == 15:
        (day, profs_path, dc_path, time_limit, workers,
         enforce_no_holes, locked_slots_for_day,
         coteach_groups, group_assignments,
         special_room_ctx, class_flags,
         support_assignments, parallel_groups, plessi_ctx,
         dsl_hard_expressions) = args
    elif len(args) == 14:
        (day, profs_path, dc_path, time_limit, workers,
         enforce_no_holes, locked_slots_for_day,
         coteach_groups, group_assignments,
         special_room_ctx, class_flags,
         support_assignments, parallel_groups, plessi_ctx) = args
    elif len(args) == 11:
        (day, profs_path, dc_path, time_limit, workers,
         enforce_no_holes, locked_slots_for_day,
         coteach_groups, group_assignments,
         special_room_ctx, class_flags) = args
    elif len(args) == 9:
        (day, profs_path, dc_path, time_limit, workers,
         enforce_no_holes, locked_slots_for_day,
         coteach_groups, group_assignments) = args
    elif len(args) == 8:
        (day, profs_path, dc_path, time_limit, workers,
         enforce_no_holes, locked_slots_for_day,
         coteach_groups) = args
        group_assignments = None
    elif len(args) == 7:
        (day, profs_path, dc_path, time_limit, workers,
         enforce_no_holes, locked_slots_for_day) = args
        coteach_groups = None
        group_assignments = None
    else:
        (day, profs_path, dc_path, time_limit, workers,
         enforce_no_holes) = args
        locked_slots_for_day = None
        coteach_groups = None
        group_assignments = None
    with open(profs_path, "rb") as f:
        profs = pickle.load(f)
    with open(dc_path, "rb") as f:
        dc_value = pickle.load(f)
    t0 = time.time()
    out, status = solve_day(
        day, profs, dc_value,
        time_limit=time_limit, workers=workers,
        enforce_no_holes=enforce_no_holes, log=False,
        locked_slots_for_day=locked_slots_for_day,
        coteach_groups=coteach_groups,
        group_assignments=group_assignments,
        special_room_ctx=special_room_ctx,
        class_flags=class_flags,
        total_room_capacity=total_room_capacity,
        support_assignments=support_assignments,
        parallel_groups=parallel_groups,
        plessi_ctx=plessi_ctx,
        dsl_hard_expressions=dsl_hard_expressions,
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
                          dc_out_path: str | None = None,
                          locked_day_count: dict | None = None,
                          locked_by_day: dict | None = None,
                          coteach_groups: list | None = None,
                          group_assignments: list | None = None,
                          special_room_ctx=None,
                          class_flags=None,
                          total_room_capacity=None,
                          class_day_load_allowed=None,
                          class_free_days=None,
                          support_assignments=None,
                          parallel_groups=None,
                          plessi_ctx=None,
                          dsl_hard_expressions=None):
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
            profs, time_limit=time_a, workers=8, log=False,
            locked_day_count=locked_day_count,
            coteach_groups=coteach_groups,
            group_assignments=group_assignments,
            class_day_load_allowed=class_day_load_allowed,
            class_free_days=class_free_days)
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
            with ProcessPoolExecutor(max_workers=n_workers,
                                     mp_context=_pool_ctx()) as ex:
                futures = {
                    ex.submit(_worker_solve_day,
                              (d, profs_pkl, dc_pkl,
                               time_day, cpsat_workers_per_day,
                               enforce_no_holes,
                               (locked_by_day or {}).get(d, None),
                               coteach_groups,
                               group_assignments,
                               special_room_ctx,
                               class_flags,
                               support_assignments,
                               parallel_groups,
                               plessi_ctx,
                               dsl_hard_expressions,
                               total_room_capacity)): d
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
        prev_day = None
        prev_out = None
        day_kw = dict(
            time_limit=time_day, workers=cpsat_workers_per_day,
            enforce_no_holes=enforce_no_holes, log=False,
            coteach_groups=coteach_groups,
            group_assignments=group_assignments,
            special_room_ctx=special_room_ctx,
            class_flags=class_flags,
            total_room_capacity=total_room_capacity,
            support_assignments=support_assignments,
            parallel_groups=parallel_groups,
            plessi_ctx=plessi_ctx,
            dsl_hard_expressions=dsl_hard_expressions,
        )
        for d in DAYS:
            t = time.time()
            out, status = solve_day(
                d, profs, dc_value,
                locked_slots_for_day=(locked_by_day or {}).get(d, None),
                warm_start=hint_from_day(prev_out, d),
                **day_kw)
            dt = time.time() - t
            days_per_day[d] = dt
            if out is None and prev_out is not None and prev_day is not None:
                if log_progress:
                    print(f"[temporal]   day {d} INFEASIBLE; "
                          f"2-day F&O with day {prev_day}")
                new_prev, out = fix_and_optimize_two_days(
                    prev_day, d, profs, dc_value, prev_out,
                    locked_by_day=locked_by_day,
                    **day_kw)
                if new_prev is not None and new_prev is not prev_out:
                    for k in list(full_solution):
                        if len(k) == 5 and k[3] == prev_day:
                            del full_solution[k]
                    full_solution.update(new_prev)
                    prev_out = new_prev
            if out is None:
                failed_days.append(d)
                expl = explain_day_infeasibility(profs, dc_value, d)
                if log_progress:
                    print(f"[temporal]   day {d} INFEASIBLE in {dt:.1f}s"
                          f"{format_infeasibility(expl)}")
            else:
                full_solution.update(out)
                occ = sum(1 for v in out.values() if v == 1)
                if log_progress:
                    print(f"[temporal]   day {d} ok in {dt:.1f}s -- {occ} occ")
                prev_day, prev_out = d, out

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
