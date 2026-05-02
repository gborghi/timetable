r"""Correlation + regression analyses on the active solution.

Three relationships are computed:

  1. **Teacher hour-load vs gap count**: linear regression of the
     number of holes in a teacher's weekly schedule on their total
     hours. Hypothesis: heavier teachers have more gaps.

  2. **Teacher #subjects vs SOFT contribution**: linear regression
     of a teacher's contribution to the global SOFT score on the
     number of distinct subjects they teach. Hypothesis: cross-
     subject teachers stir the optimizer's penalty more.

  3. **Class saturation vs P(6th-hour scheduled)**: logistic
     regression of "the class has at least one 6th-hour slot" on
     the class's weekly hour-load.

Each output includes coefficients, standard errors, p-values, R^2
(or pseudo-R^2 for logit), and an auto-generated Italian textual
interpretation.
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


def _per_teacher_metrics(sol: dict, profs: dict
                          ) -> list[tuple[str, int, int, int, float]]:
    """Returns rows (teacher, hours, n_subjects, gap_count,
    soft_contribution)."""
    import metaheuristics as meta  # type: ignore
    out: list[tuple[str, int, int, int, float]] = []
    teachers = sorted(profs.keys())
    for t in teachers:
        ttuples = [k for k, v in sol.items() if v and k[0] == t]
        hours = len(ttuples)
        n_subjects = len({k[2] for k in ttuples})
        # Gaps: per day, holes in [min..max]
        gaps_total = 0
        for d in meta.DAYS:
            day_hours = sorted({k[4] for k in ttuples if k[3] == d})
            if not day_hours:
                continue
            span = max(day_hours) - min(day_hours) + 1
            gaps_total += span - len(day_hours)
        # Soft contribution proxy: 5-load + 1-load + sixth + buchi
        five = 0
        one = 0
        sixth = 0
        for d in meta.DAYS:
            day_hours = [k[4] for k in ttuples if k[3] == d]
            ld = len(day_hours)
            if ld == 5:
                five += 1
            if ld == 1:
                one += 1
            sixth += sum(1 for h in day_hours if h == 13)
        soft = (
            meta.OBJECTIVE_WEIGHTS["five"] * five
            + meta.OBJECTIVE_WEIGHTS["one"] * one
            + meta.OBJECTIVE_WEIGHTS["sixth"] * sixth
            + meta.OBJECTIVE_WEIGHTS["buchi"] * gaps_total
        )
        out.append((t, hours, n_subjects, gaps_total, float(soft)))
    return out


def _per_class_metrics(sol: dict
                        ) -> list[tuple[str, int, bool]]:
    """Returns rows (class, hours_per_week, has_sixth_hour)."""
    out: list[tuple[str, int, bool]] = []
    classes = sorted({k[1] for k in sol if sol[k]})
    for c in classes:
        cklist = [k for k, v in sol.items() if v and k[1] == c]
        hours = len(cklist)
        has_sixth = any(k[4] == 13 for k in cklist)
        out.append((c, hours, has_sixth))
    return out


def run(sol: dict, profs: dict) -> dict[str, Any]:
    import numpy as np
    import statsmodels.api as sm

    teacher_rows = _per_teacher_metrics(sol, profs)
    class_rows = _per_class_metrics(sol)

    out: dict[str, Any] = {"ok": True, "models": []}

    if teacher_rows:
        X = np.array([[r[1]] for r in teacher_rows], dtype=float)  # hours
        y = np.array([r[3] for r in teacher_rows], dtype=float)    # gaps
        Xc = sm.add_constant(X)
        try:
            model = sm.OLS(y, Xc).fit()
            coef = float(model.params[1])
            p = float(model.pvalues[1])
            out["models"].append({
                "name": "load_vs_gaps",
                "label": "Carico orario docente vs # buchi",
                "kind": "OLS",
                "n": len(teacher_rows),
                "coef": coef,
                "stderr": float(model.bse[1]),
                "p_value": p,
                "r2": float(model.rsquared),
                "interpretation": _interpret(
                    coef, p,
                    "carico orario", "numero di buchi",
                    "I docenti con piu' ore tendono ad avere "
                    "piu' buchi nell'orario",
                    "I docenti con piu' ore hanno meno buchi",
                ),
                "scatter": [
                    {"x": float(r[1]), "y": float(r[3])}
                    for r in teacher_rows
                ],
            })
        except Exception as e:  # noqa: BLE001
            out["models"].append({"name": "load_vs_gaps",
                                   "error": str(e)})

        # Subjects vs SOFT contribution
        X = np.array([[r[2]] for r in teacher_rows], dtype=float)
        y = np.array([r[4] for r in teacher_rows], dtype=float)
        Xc = sm.add_constant(X)
        try:
            model = sm.OLS(y, Xc).fit()
            coef = float(model.params[1])
            p = float(model.pvalues[1])
            out["models"].append({
                "name": "subjects_vs_soft",
                "label": "Numero materie docente vs SOFT contribution",
                "kind": "OLS",
                "n": len(teacher_rows),
                "coef": coef,
                "stderr": float(model.bse[1]),
                "p_value": p,
                "r2": float(model.rsquared),
                "interpretation": _interpret(
                    coef, p,
                    "numero di materie", "contribuzione SOFT",
                    "Docenti multidisciplinari hanno SOFT score "
                    "piu' alto",
                    "Docenti multidisciplinari hanno SOFT piu' basso",
                ),
                "scatter": [
                    {"x": float(r[2]), "y": float(r[4])}
                    for r in teacher_rows
                ],
            })
        except Exception as e:  # noqa: BLE001
            out["models"].append({"name": "subjects_vs_soft",
                                   "error": str(e)})

    if class_rows:
        X = np.array([[r[1]] for r in class_rows], dtype=float)
        y = np.array([1.0 if r[2] else 0.0 for r in class_rows])
        if (y.sum() > 0) and (y.sum() < len(y)):
            Xc = sm.add_constant(X)
            try:
                logit = sm.Logit(y, Xc).fit(disp=False, maxiter=100)
                coef = float(logit.params[1])
                p = float(logit.pvalues[1])
                out["models"].append({
                    "name": "saturation_vs_sixth",
                    "label": "Saturazione classe vs P(6a ora)",
                    "kind": "Logit",
                    "n": len(class_rows),
                    "coef": coef,
                    "stderr": float(logit.bse[1]),
                    "p_value": p,
                    "pseudo_r2": float(logit.prsquared),
                    "interpretation": _interpret(
                        coef, p,
                        "saturazione classe", "probabilita' di 6a ora",
                        "Le classi con piu' ore settimanali hanno "
                        "probabilita' maggiore di lezione in 6a ora",
                        "Le classi con piu' ore settimanali hanno "
                        "MENO 6a ora",
                    ),
                    "scatter": [
                        {"x": float(r[1]), "y": 1.0 if r[2] else 0.0}
                        for r in class_rows
                    ],
                })
            except Exception as e:  # noqa: BLE001
                out["models"].append({"name": "saturation_vs_sixth",
                                       "error": str(e)})
        else:
            out["models"].append({
                "name": "saturation_vs_sixth",
                "label": "Saturazione classe vs P(6a ora)",
                "warn": ("Tutte le classi hanno (o non hanno) la "
                          "6a ora: regressione logistica non "
                          "applicabile."),
            })

    return out


def run_from_db(db) -> dict[str, Any]:
    from backend import engine_io  # type: ignore
    profs = engine_io.profs_dict_from_db(db)
    active = engine_io.get_active_solution(db)
    if active is None:
        return {"ok": False, "msg": "Nessuna soluzione attiva."}
    sol = engine_io.lessons_to_solution_dict(db, active.id)
    return run(sol, profs)
