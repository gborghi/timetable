r"""Distribution / histogram diagnostics.

Five distributions are computed and bundled with goodness-of-fit
tests where applicable:

  1. Teacher hour-load (active solution)
  2. Class hour-load per day  (6 series, one per weekday)
  3. Subject x slot heatmap   (matrix: rows = subjects, cols = 36 slots)
  4. Classroom occupancy per slot
  5. KS-test of teacher loads against a uniform reference, +
     chi-square goodness-of-fit on the per-day class distribution

Output: JSON-friendly dicts with bins / counts / matrix-rows ready
to feed an ECharts component on the frontend.
"""
from __future__ import annotations

import os
import sys
from typing import Any

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _hist(values: list[float], bins: int = 12
          ) -> tuple[list[float], list[int]]:
    if not values:
        return [], []
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-9:
        return [lo, hi], [len(values)]
    step = (hi - lo) / bins
    edges = [lo + i * step for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        idx = min(bins - 1, int((v - lo) / step))
        counts[idx] += 1
    return edges, counts


def run(sol: dict, profs: dict) -> dict[str, Any]:
    import metaheuristics as meta  # type: ignore
    from scipy import stats

    out: dict[str, Any] = {"ok": True}

    # --- 1) Teacher hour-load distribution ---
    teacher_loads = [
        sum(1 for k, v in sol.items() if v and k[0] == t)
        for t in sorted(profs.keys())
    ]
    edges, counts = _hist([float(x) for x in teacher_loads])
    out["teacher_loads"] = {
        "label": "Distribuzione carico orario docenti",
        "values": teacher_loads,
        "bin_edges": edges,
        "bin_counts": counts,
    }

    # --- 2) Class hour-load per day ---
    classes = sorted({k[1] for k in sol if sol[k]})
    per_day_per_class: dict[int, list[int]] = {d: [] for d in meta.DAYS}
    for c in classes:
        for d in meta.DAYS:
            per_day_per_class[d].append(
                sum(1 for k, v in sol.items()
                    if v and k[1] == c and k[3] == d)
            )
    out["class_loads_per_day"] = {
        "label": "Carico orario classi per giorno",
        "days": list(meta.DAYS),
        "series": [
            {"day": d, "values": per_day_per_class[d]}
            for d in meta.DAYS
        ],
    }

    # --- 3) Subject x slot heatmap ---
    subjects = sorted({k[2] for k in sol if sol[k]})
    slots = [(d, h) for d in meta.DAYS for h in meta.HOURS]
    matrix = []
    for s in subjects:
        row = [
            sum(1 for k, v in sol.items()
                if v and k[2] == s and k[3] == d and k[4] == h)
            for (d, h) in slots
        ]
        matrix.append({"subject": s, "row": row})
    out["subject_slot_heatmap"] = {
        "label": "Matrice materia x slot",
        "slots": [f"D{d}-H{h}" for (d, h) in slots],
        "matrix": matrix,
    }

    # --- 4) Classroom occupancy per slot ---
    # Approximation: count concurrently-busy lessons per slot.
    occupancy = [
        sum(1 for k, v in sol.items()
            if v and k[3] == d and k[4] == h)
        for (d, h) in slots
    ]
    out["classroom_occupancy_per_slot"] = {
        "label": "Lezioni concorrenti per slot",
        "slots": [f"D{d}-H{h}" for (d, h) in slots],
        "values": occupancy,
    }

    # --- 5) Goodness-of-fit tests ---
    out["tests"] = {}
    if len(teacher_loads) >= 5 and max(teacher_loads) > min(teacher_loads):
        try:
            ks_stat, ks_p = stats.kstest(
                teacher_loads,
                "uniform",
                args=(min(teacher_loads),
                       max(teacher_loads) - min(teacher_loads)),
            )
            out["tests"]["ks_teacher_loads_vs_uniform"] = {
                "statistic": float(ks_stat),
                "p_value": float(ks_p),
                "interpretation": (
                    "Carichi docenti compatibili con distribuzione "
                    "uniforme (p>=0.05)"
                    if ks_p >= 0.05
                    else "Carichi docenti significativamente non "
                          "uniformi (p<0.05)."
                ),
            }
        except Exception:
            pass
    # Chi-square on per-day class loads (sum across classes by day)
    daily_totals = [
        sum(per_day_per_class[d]) for d in meta.DAYS
    ]
    if sum(daily_totals) > 0:
        try:
            expected = [sum(daily_totals) / len(meta.DAYS)] * len(meta.DAYS)
            chi2_stat, chi2_p = stats.chisquare(daily_totals, f_exp=expected)
            out["tests"]["chi2_class_loads_per_day"] = {
                "statistic": float(chi2_stat),
                "p_value": float(chi2_p),
                "expected": expected,
                "observed": daily_totals,
                "interpretation": (
                    "Carico per giorno coerente con distribuzione "
                    "uniforme (p>=0.05)"
                    if chi2_p >= 0.05
                    else "Distribuzione non uniforme: alcuni giorni "
                          "sono significativamente piu' carichi (p<0.05)"
                ),
            }
        except Exception:
            pass

    return out


def run_from_db(db) -> dict[str, Any]:
    from backend import engine_io  # type: ignore
    profs = engine_io.profs_dict_from_db(db)
    active = engine_io.get_active_solution(db)
    if active is None:
        return {"ok": False, "msg": "Nessuna soluzione attiva."}
    sol = engine_io.lessons_to_solution_dict(db, active.id)
    return run(sol, profs)
