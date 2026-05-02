r"""Correlation + regression analyses on the active solution.

Two-tier API:

  - **High level**: `run(sol, profs, models_spec=None)` accepts an
    optional list of model specs. When `models_spec` is None, the
    canonical 3-model panel is computed (same as before).

  - **Low level (for the UI)**: `available_variables()` returns
    metadata about all variables the caller can pick (units of
    observation = rows, plus per-row scalar/boolean fields). The
    UI uses this to drive a "build your own regression" form.

A model spec is a dict:

    {
      "kind": "ols" | "logit",
      "x":    "<variable name>",
      "y":    "<variable name>",
      "label": "<optional human-readable name>",
      "scope": "teachers" | "classes",   # which row set
    }

Both x and y must come from the same `scope` (the row set they
share); cross-scope models would mix teachers with classes which
makes no statistical sense.
"""
from __future__ import annotations

import os
import sys
from typing import Any

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _interpret(coef: float, p: float, label_x: str, label_y: str,
               sign_pos: str, sign_neg: str) -> str:
    if p > 0.10:
        return (f"{label_y} non e' significativamente correlato a "
                f"{label_x} (p={p:.3f}).")
    direction = sign_pos if coef > 0 else sign_neg
    sig = "p < 0.001" if p < 0.001 else f"p = {p:.3f}"
    return f"{direction} ({sig}, coef={coef:.3f})."


# ---------- Per-row variable extractors ----------

def _per_teacher_rows(sol: dict, profs: dict) -> list[dict]:
    """One dict per teacher with all extractable scalar variables."""
    import metaheuristics as meta  # type: ignore
    out: list[dict] = []
    teachers = sorted(profs.keys())
    for t in teachers:
        ttuples = [k for k, v in sol.items() if v and k[0] == t]
        hours = len(ttuples)
        n_subjects = len({k[2] for k in ttuples})
        n_classes = len({k[1] for k in ttuples})
        # Gaps
        gaps_total = 0
        for d in meta.DAYS:
            day_hours = sorted({k[4] for k in ttuples if k[3] == d})
            if not day_hours:
                continue
            span = max(day_hours) - min(day_hours) + 1
            gaps_total += span - len(day_hours)
        # SOFT proxy contribution
        five = 0; one = 0; sixth = 0
        days_active = 0
        for d in meta.DAYS:
            day_hours = [k[4] for k in ttuples if k[3] == d]
            ld = len(day_hours)
            if ld > 0:
                days_active += 1
            if ld == 5: five += 1
            if ld == 1: one += 1
            sixth += sum(1 for h in day_hours if h == 13)
        soft = (
            meta.OBJECTIVE_WEIGHTS["five"] * five
            + meta.OBJECTIVE_WEIGHTS["one"] * one
            + meta.OBJECTIVE_WEIGHTS["sixth"] * sixth
            + meta.OBJECTIVE_WEIGHTS["buchi"] * gaps_total
        )
        max_h = int((profs.get(t) or {}).get("max_hours") or 18)
        out.append({
            "name": t,
            "teacher_hours": hours,
            "teacher_n_subjects": n_subjects,
            "teacher_n_classes": n_classes,
            "teacher_gap_count": gaps_total,
            "teacher_days_active": days_active,
            "teacher_soft_contribution": float(soft),
            "teacher_load_ratio": (hours / max_h) if max_h > 0 else 0.0,
            "teacher_has_5_load": int(five > 0),
            "teacher_has_1_load": int(one > 0),
        })
    return out


def _per_class_rows(sol: dict) -> list[dict]:
    """One dict per class with all extractable scalar variables."""
    out: list[dict] = []
    classes = sorted({k[1] for k in sol if sol[k]})
    for c in classes:
        cklist = [k for k, v in sol.items() if v and k[1] == c]
        hours = len(cklist)
        has_sixth = any(k[4] == 13 for k in cklist)
        n_subjects = len({k[2] for k in cklist})
        n_teachers = len({k[0] for k in cklist})
        # Try to extract year from name like "1A" / "3B_Scientifico"
        year = None
        if c and c[0].isdigit():
            try: year = int(c[0])
            except ValueError: pass
        out.append({
            "name": c,
            "class_hours": hours,
            "class_n_subjects": n_subjects,
            "class_n_teachers": n_teachers,
            "class_has_sixth_hour": int(has_sixth),
            "class_year": year,
        })
    return out


# ---------- Variable metadata for the UI ----------

# Each scope maps to {var_name: {label, type}}.
# type: 'continuous' (good for OLS as x or y), 'binary' (good for
#       Logit y), 'integer' (continuous-like for OLS).
VARIABLES: dict[str, dict[str, dict[str, str]]] = {
    "teachers": {
        "teacher_hours":            {"label": "Ore docente", "type": "integer"},
        "teacher_n_subjects":       {"label": "# materie",   "type": "integer"},
        "teacher_n_classes":        {"label": "# classi",    "type": "integer"},
        "teacher_gap_count":        {"label": "# buchi",     "type": "integer"},
        "teacher_days_active":      {"label": "# giorni di servizio", "type": "integer"},
        "teacher_soft_contribution":{"label": "SOFT contribution", "type": "continuous"},
        "teacher_load_ratio":       {"label": "Carico / max_hours", "type": "continuous"},
        "teacher_has_5_load":       {"label": "Ha 5-load (giorno pieno)", "type": "binary"},
        "teacher_has_1_load":       {"label": "Ha 1-load (giorno solo)",  "type": "binary"},
    },
    "classes": {
        "class_hours":           {"label": "Ore settimanali",    "type": "integer"},
        "class_n_subjects":      {"label": "# materie",          "type": "integer"},
        "class_n_teachers":      {"label": "# docenti",          "type": "integer"},
        "class_has_sixth_hour":  {"label": "Ha 6a ora (binary)", "type": "binary"},
        "class_year":            {"label": "Anno (1..5)",        "type": "integer"},
    },
}


def available_variables() -> dict[str, Any]:
    """Used by the UI: returns the menu of variable picks per scope."""
    return {
        "scopes": ["teachers", "classes"],
        "variables_by_scope": {
            scope: [
                {"key": k, **v}
                for k, v in VARIABLES[scope].items()
            ]
            for scope in VARIABLES
        },
    }


# ---------- Default models (back-compat) ----------

DEFAULT_MODELS: list[dict[str, str]] = [
    {"kind": "ols", "scope": "teachers",
     "x": "teacher_hours", "y": "teacher_gap_count",
     "label": "Carico orario docente vs # buchi"},
    {"kind": "ols", "scope": "teachers",
     "x": "teacher_n_subjects", "y": "teacher_soft_contribution",
     "label": "Numero materie docente vs SOFT contribution"},
    {"kind": "logit", "scope": "classes",
     "x": "class_hours", "y": "class_has_sixth_hour",
     "label": "Saturazione classe vs P(6a ora)"},
]


# ---------- Model fitter ----------

def _fit_one(model: dict, rows: list[dict]) -> dict:
    """Fit one OLS or Logit model on the row set."""
    import numpy as np
    import statsmodels.api as sm

    spec_kind = (model.get("kind") or "ols").lower()
    x_var = model.get("x")
    y_var = model.get("y")
    label = model.get("label") or f"{y_var} ~ {x_var} ({spec_kind})"
    if not x_var or not y_var:
        return {"name": label, "label": label,
                 "error": "x e/o y mancanti"}

    xs: list[float] = []
    ys: list[float] = []
    for r in rows:
        xv = r.get(x_var)
        yv = r.get(y_var)
        if xv is None or yv is None:
            continue
        try:
            xs.append(float(xv))
            ys.append(float(yv))
        except (TypeError, ValueError):
            continue

    n = len(xs)
    base = {
        "name": f"{x_var}_vs_{y_var}",
        "label": label,
        "kind": "OLS" if spec_kind == "ols" else "Logit",
        "scope": model.get("scope"),
        "x": x_var, "y": y_var,
        "x_label": (VARIABLES.get(model.get("scope") or "", {})
                     .get(x_var, {}).get("label") or x_var),
        "y_label": (VARIABLES.get(model.get("scope") or "", {})
                     .get(y_var, {}).get("label") or y_var),
        "n": n,
    }
    if n < 3:
        base["error"] = f"troppi pochi punti (n={n})"
        return base

    try:
        X = np.array([[v] for v in xs], dtype=float)
        y_arr = np.array(ys, dtype=float)
        Xc = sm.add_constant(X)
        if spec_kind == "logit":
            if not (set(ys) <= {0.0, 1.0}):
                base["error"] = ("Logit richiede y binaria 0/1; "
                                  f"valori distinti: {sorted(set(ys))[:5]}...")
                return base
            if y_arr.sum() == 0 or y_arr.sum() == len(y_arr):
                base["warn"] = ("y costante (tutti 0 o tutti 1): "
                                "Logit non identificabile.")
                return base
            res = sm.Logit(y_arr, Xc).fit(disp=False, maxiter=100)
            base["coef"] = float(res.params[1])
            base["stderr"] = float(res.bse[1])
            base["p_value"] = float(res.pvalues[1])
            base["pseudo_r2"] = float(getattr(res, "prsquared", 0.0))
        else:  # OLS
            res = sm.OLS(y_arr, Xc).fit()
            base["coef"] = float(res.params[1])
            base["stderr"] = float(res.bse[1])
            base["p_value"] = float(res.pvalues[1])
            base["r2"] = float(res.rsquared)
        # Auto interpretation
        base["interpretation"] = _interpret(
            base["coef"], base["p_value"],
            base["x_label"], base["y_label"],
            f"All'aumentare di {base['x_label']}, "
            f"{base['y_label']} aumenta",
            f"All'aumentare di {base['x_label']}, "
            f"{base['y_label']} diminuisce",
        )
    except Exception as e:  # noqa: BLE001
        base["error"] = str(e)[:200]
        return base

    base["scatter"] = [
        {"x": x, "y": y} for (x, y) in zip(xs, ys)
    ]
    return base


# ---------- Public API ----------

def run(sol: dict, profs: dict,
        models_spec: list[dict] | None = None) -> dict[str, Any]:
    """Compute the requested models. If `models_spec` is None, uses
    DEFAULT_MODELS (back-compat with the previous 3-model panel).
    Otherwise expects a list of `{kind, scope, x, y, label?}`.
    """
    teacher_rows = _per_teacher_rows(sol, profs)
    class_rows = _per_class_rows(sol)
    rows_by_scope = {
        "teachers": teacher_rows,
        "classes":  class_rows,
    }

    specs = models_spec if models_spec else DEFAULT_MODELS
    out: dict[str, Any] = {
        "ok": True,
        "models_spec": specs,
        "models": [],
        "row_counts": {
            "teachers": len(teacher_rows),
            "classes": len(class_rows),
        },
    }
    for spec in specs:
        scope = spec.get("scope") or "teachers"
        rows = rows_by_scope.get(scope, [])
        out["models"].append(_fit_one(spec, rows))
    return out


def run_from_db(db, models_spec: list[dict] | None = None) -> dict[str, Any]:
    from backend import engine_io  # type: ignore
    profs = engine_io.profs_dict_from_db(db)
    active = engine_io.get_active_solution(db)
    if active is None:
        return {"ok": False, "msg": "Nessuna soluzione attiva."}
    sol = engine_io.lessons_to_solution_dict(db, active.id)
    return run(sol, profs, models_spec=models_spec)
