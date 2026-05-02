r"""Distribution / histogram diagnostics.

Computes any subset of the available distributions on the active
solution. Driven by an OPTIONAL spec dict so the caller can turn
on/off individual distributions and tweak per-distribution
parameters (number of bins, subject filter, etc.).

Available distributions (key -> what it produces):

  - "teacher_loads"               teacher hour-load histogram
  - "class_loads_per_day"         per-day class hour-load
  - "subject_slot_heatmap"        subjects x (day,hour) heatmap
  - "classroom_occupancy_per_slot" lessons concurrently in a slot

Plus goodness-of-fit tests:

  - "ks_uniform_teacher_loads"    KS-test teacher loads vs uniform
  - "chi2_class_loads_per_day"    chi-square per-day uniformity

Spec dict shape (all optional; missing keys = include with
defaults; back-compat with previous unparameterised call):

    {
      "include": ["teacher_loads", "subject_slot_heatmap", ...],
      "params": {
        "teacher_loads": {"bins": 12},
        "subject_slot_heatmap": {
            "subjects_filter": ["Matematica", "Italiano"],
            "subjects_top_n": null,
        },
        ...
      }
    }
"""
from __future__ import annotations

import os
import sys
from typing import Any

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# Catalog of distribution kinds. Used by the UI to render a
# "Personalizza" form (which boxes to tick + which params to expose).
DISTRIBUTION_CATALOG: list[dict[str, Any]] = [
    {
        "key": "teacher_loads",
        "label": "Carico orario docenti (istogramma)",
        "params": [
            {"key": "bins", "label": "# bin", "type": "int",
             "default": 12, "min": 3, "max": 60},
        ],
    },
    {
        "key": "class_loads_per_day",
        "label": "Carico classi per giorno (6 serie)",
        "params": [
            {"key": "classes_filter",
             "label": "Restringi a classi (CSV)",
             "type": "csv", "default": ""},
        ],
    },
    {
        "key": "subject_slot_heatmap",
        "label": "Matrice materia x slot",
        "params": [
            {"key": "subjects_filter",
             "label": "Restringi a materie (CSV)",
             "type": "csv", "default": ""},
            {"key": "subjects_top_n",
             "label": "Top-N materie per ore (0 = tutte)",
             "type": "int", "default": 0, "min": 0, "max": 100},
        ],
    },
    {
        "key": "classroom_occupancy_per_slot",
        "label": "Lezioni concorrenti per slot",
        "params": [],
    },
    {
        "key": "ks_uniform_teacher_loads",
        "label": "Test KS: carichi docenti vs uniforme",
        "params": [],
    },
    {
        "key": "chi2_class_loads_per_day",
        "label": "Test chi-quadro: carichi per giorno",
        "params": [],
    },
]


def available_distributions() -> dict[str, Any]:
    """UI menu: list of available distribution kinds + their params."""
    return {"distributions": DISTRIBUTION_CATALOG}


def _hist(values: list[float], bins: int = 12
          ) -> tuple[list[float], list[int]]:
    if not values:
        return [], []
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-9:
        return [lo, hi], [len(values)]
    bins = max(1, int(bins))
    step = (hi - lo) / bins
    edges = [lo + i * step for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        idx = min(bins - 1, int((v - lo) / step))
        counts[idx] += 1
    return edges, counts


def _csv_to_list(s: Any) -> list[str]:
    if isinstance(s, list):
        return [str(x).strip() for x in s if str(x).strip()]
    if isinstance(s, str):
        return [t.strip() for t in s.split(",") if t.strip()]
    return []


def run(sol: dict, profs: dict,
        spec: dict | None = None) -> dict[str, Any]:
    """Compute the requested distributions.

    spec keys:
      - "include": list of distribution keys to include. If missing
        or empty, all are included (back-compat).
      - "params": dict of per-distribution parameter overrides.
    """
    import metaheuristics as meta  # type: ignore
    from scipy import stats

    spec = spec or {}
    include = set(spec.get("include") or [])
    if not include:
        include = {d["key"] for d in DISTRIBUTION_CATALOG}
    params: dict[str, dict] = spec.get("params") or {}

    out: dict[str, Any] = {"ok": True, "spec_used": {
        "include": sorted(include), "params": params,
    }}

    # ----- 1) teacher_loads -----
    teacher_loads = []
    if ("teacher_loads" in include
            or "ks_uniform_teacher_loads" in include):
        teacher_loads = [
            sum(1 for k, v in sol.items() if v and k[0] == t)
            for t in sorted(profs.keys())
        ]
    if "teacher_loads" in include:
        bins = int((params.get("teacher_loads") or {}).get("bins") or 12)
        edges, counts = _hist([float(x) for x in teacher_loads],
                                bins=bins)
        out["teacher_loads"] = {
            "label": "Distribuzione carico orario docenti",
            "values": teacher_loads,
            "bin_edges": edges,
            "bin_counts": counts,
            "bins": bins,
        }

    # ----- 2) class_loads_per_day -----
    per_day_per_class: dict[int, list[int]] = {d: [] for d in meta.DAYS}
    classes_in_use: list[str] = []
    if ("class_loads_per_day" in include
            or "chi2_class_loads_per_day" in include):
        classes_all = sorted({k[1] for k in sol if sol[k]})
        cls_filter = _csv_to_list(
            (params.get("class_loads_per_day") or {}).get("classes_filter")
        )
        classes_in_use = (
            [c for c in classes_all if c in cls_filter]
            if cls_filter else classes_all
        )
        for c in classes_in_use:
            for d in meta.DAYS:
                per_day_per_class[d].append(
                    sum(1 for k, v in sol.items()
                        if v and k[1] == c and k[3] == d)
                )
    if "class_loads_per_day" in include:
        out["class_loads_per_day"] = {
            "label": "Carico orario classi per giorno",
            "days": list(meta.DAYS),
            "classes": classes_in_use,
            "series": [
                {"day": d, "values": per_day_per_class[d]}
                for d in meta.DAYS
            ],
        }

    # ----- 3) subject_slot_heatmap -----
    if "subject_slot_heatmap" in include:
        slots = [(d, h) for d in meta.DAYS for h in meta.HOURS]
        sp = params.get("subject_slot_heatmap") or {}
        subjects_filter = set(_csv_to_list(sp.get("subjects_filter")))
        top_n = int(sp.get("subjects_top_n") or 0)
        # Tally hours per subject (for top-n filter)
        subj_hours: dict[str, int] = {}
        for k, v in sol.items():
            if not v:
                continue
            subj_hours[k[2]] = subj_hours.get(k[2], 0) + 1
        all_subjects = sorted(subj_hours.keys())
        subjects = all_subjects
        if subjects_filter:
            subjects = [s for s in all_subjects if s in subjects_filter]
        if top_n > 0:
            subjects = sorted(subjects,
                               key=lambda s: -subj_hours.get(s, 0))[:top_n]
            subjects = sorted(subjects)
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
            "n_subjects_total": len(all_subjects),
            "n_subjects_shown": len(subjects),
        }

    # ----- 4) classroom_occupancy_per_slot -----
    if "classroom_occupancy_per_slot" in include:
        slots = [(d, h) for d in meta.DAYS for h in meta.HOURS]
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

    # ----- 5) Goodness-of-fit tests -----
    out["tests"] = {}
    if ("ks_uniform_teacher_loads" in include
            and len(teacher_loads) >= 5
            and max(teacher_loads) > min(teacher_loads)):
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
    if "chi2_class_loads_per_day" in include:
        daily_totals = [
            sum(per_day_per_class[d]) for d in meta.DAYS
        ]
        if sum(daily_totals) > 0:
            try:
                expected = [sum(daily_totals) / len(meta.DAYS)] * len(meta.DAYS)
                chi2_stat, chi2_p = stats.chisquare(daily_totals,
                                                     f_exp=expected)
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


def run_from_db(db, spec: dict | None = None) -> dict[str, Any]:
    from backend import engine_io  # type: ignore
    profs = engine_io.profs_dict_from_db(db)
    active = engine_io.get_active_solution(db)
    if active is None:
        return {"ok": False, "msg": "Nessuna soluzione attiva."}
    sol = engine_io.lessons_to_solution_dict(db, active.id)
    return run(sol, profs, spec=spec)
