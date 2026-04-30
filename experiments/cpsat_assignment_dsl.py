r"""Phase A solver wrapper that exposes named CP-SAT variables to a
DSL-based objective.

Mirrors `cpsat_v2_assignment.solve_assignment` but instead of hard-
coded weights it accepts a DSL expression (a string) which gets
compiled to a linear objective via
`webui.backend.utils.objective_dsl.compile_to_objective`.

Used by the new "criterion / custom" workflow on Phase A
(/api/optimize/phase-a). The presets expose pre-made DSL strings;
"custom" lets the user paste their own.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any

from ortools.sat.python import cp_model


def _import_dsl():
    # Make the backend package importable when this file is invoked
    # standalone or via run_manager (which adds experiments/ to path
    # but not webui/).
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    webui_root = os.path.join(repo_root, "webui")
    if webui_root not in sys.path:
        sys.path.insert(0, webui_root)
    from backend.utils import objective_dsl as dsl  # noqa: WPS433
    return dsl


def solve_assignment_dsl(data: dict, dsl_expression: str,
                         time_limit_s: float = 60,
                         workers: int = 8, log: bool = True
                         ) -> tuple[dict, Any, int, dict]:
    """Same coverage HARD as `cpsat_v2_assignment.solve_assignment`,
    different objective: whatever the DSL expression compiles to.

    Returns `(cattedre, solver, status, metrics)`.

    `metrics` reports the values of the named scalar variables on
    the chosen solution so the UI can show "what the solver actually
    optimised" alongside the per-preset counters.
    """
    dsl = _import_dsl()

    classes = data["classes"]
    teachers = data["teachers"]
    cconcorso = data["cconcorsopersubject"]

    model = cp_model.CpModel()

    # === Variables (mirror of cpsat_v2_assignment) ====================
    assign: dict[tuple[int, str, int], Any] = {}
    for ci, cl in enumerate(classes):
        for subj in cl["subjects"]:
            for ti, t in enumerate(teachers):
                if t["group"] in cconcorso.get(subj, {}):
                    assign[(ci, subj, ti)] = model.NewBoolVar(
                        f"a_{ci}_{subj}_{ti}"
                    )

    # HARD: every (class, subject) covered by exactly 1 teacher.
    for ci, cl in enumerate(classes):
        for subj in cl["subjects"]:
            keys = [
                assign[(ci, subj, ti)]
                for ti, _ in enumerate(teachers)
                if (ci, subj, ti) in assign
            ]
            if not keys:
                raise RuntimeError(
                    f"Nessun docente compatibile per "
                    f"classe={cl['name']} materia={subj}"
                )
            model.Add(sum(keys) == 1)

    n_t = len(teachers)
    n_c = len(classes)
    teacher_max_hours = [t["max_hours"] for t in teachers]

    actual_hours = []
    for ti in range(n_t):
        terms = []
        for (ci, subj, tj), var in assign.items():
            if tj != ti:
                continue
            ore = classes[ci]["subjects"][subj]
            terms.append(ore * var)
        ah = model.NewIntVar(0, teacher_max_hours[ti], f"ah_{ti}")
        model.Add(ah == sum(terms))
        actual_hours.append(ah)

    # teacher_unused = max_hours - actual_hours (per teacher)
    teacher_unused = []
    for ti in range(n_t):
        u = model.NewIntVar(0, teacher_max_hours[ti], f"u_{ti}")
        model.Add(u == teacher_max_hours[ti] - actual_hours[ti])
        teacher_unused.append(u)

    # has_class[(ti, ci)] = OR(assign on that ti, ci)
    has_class: dict[tuple[int, int], Any] = {}
    for ti in range(n_t):
        for ci, cl in enumerate(classes):
            keys = [
                assign[(ci, subj, ti)]
                for subj in cl["subjects"]
                if (ci, subj, ti) in assign
            ]
            if not keys:
                continue
            b = model.NewBoolVar(f"hc_{ti}_{ci}")
            model.AddMaxEquality(b, keys)
            has_class[(ti, ci)] = b

    teacher_n_classes = []
    for ti in range(n_t):
        rel = [b for (tt, _ci), b in has_class.items() if tt == ti]
        n = model.NewIntVar(0, n_c, f"nclass_{ti}")
        if rel:
            model.Add(n == sum(rel))
        else:
            model.Add(n == 0)
        teacher_n_classes.append(n)

    curricula_top = sorted(
        {cl["curriculum"].split("_")[0] for cl in classes}
    )
    has_curr_keys: dict[tuple[int, str], list] = {}
    for ti in range(n_t):
        for ci, cl in enumerate(classes):
            top = cl["curriculum"].split("_")[0]
            keys = [
                assign[(ci, subj, ti)]
                for subj in cl["subjects"]
                if (ci, subj, ti) in assign
            ]
            if not keys:
                continue
            has_curr_keys.setdefault((ti, top), []).extend(keys)

    teacher_n_curricula = []
    for ti in range(n_t):
        rel_bools = []
        for top in curricula_top:
            keys = has_curr_keys.get((ti, top), [])
            if not keys:
                continue
            b = model.NewBoolVar(f"hcurr_{ti}_{top}")
            model.AddMaxEquality(b, keys)
            rel_bools.append(b)
        n = model.NewIntVar(0, len(curricula_top), f"ncurr_{ti}")
        if rel_bools:
            model.Add(n == sum(rel_bools))
        else:
            model.Add(n == 0)
        teacher_n_curricula.append(n)

    # teacher_weight[ti] = sum of (year + curriculum_score) of the
    # classes assigned to ti, used by some presets as a balancing
    # proxy.
    cur_score: dict[str, int] = {}
    for cl in classes:
        c = cl["curriculum"]
        cur_score.setdefault(c, int(cl.get("score", 1)))
    teacher_weight = []
    max_w = 0
    for ti in range(n_t):
        terms = []
        for (ci, subj, tj), var in assign.items():
            if tj != ti:
                continue
            cl = classes[ci]
            w = int(cl.get("year", 1)) + cur_score.get(cl["curriculum"], 1)
            terms.append(w * var)
        w_total = (sum(int(cl.get("year", 1))
                       + cur_score.get(cl["curriculum"], 1)
                       for cl in classes) + 1)
        max_w = max(max_w, w_total)
        ww = model.NewIntVar(0, max_w, f"tw_{ti}")
        model.Add(ww == sum(terms) if terms else 0)
        teacher_weight.append(ww)

    # Aggregated scalars (used by the DSL).
    total_unused = model.NewIntVar(0, 100000, "total_unused")
    model.Add(total_unused == sum(teacher_unused))
    total_n_classes_v = model.NewIntVar(0, 100000, "total_n_classes")
    model.Add(total_n_classes_v == sum(teacher_n_classes))
    total_n_curricula_v = model.NewIntVar(0, 100000, "total_n_curricula")
    model.Add(total_n_curricula_v == sum(teacher_n_curricula))
    total_weight_v = model.NewIntVar(0, 1_000_000, "total_weight")
    model.Add(total_weight_v == sum(teacher_weight))

    # Backward-compat scalars used by the "max full cattedre" preset.
    n_under_18_terms = []
    n_under_10_terms = []
    for ti in range(n_t):
        b18 = model.NewBoolVar(f"u18_{ti}")
        model.Add(actual_hours[ti] < 18).OnlyEnforceIf(b18)
        model.Add(actual_hours[ti] >= 18).OnlyEnforceIf(b18.Not())
        n_under_18_terms.append(b18)
        b10 = model.NewBoolVar(f"u10_{ti}")
        model.Add(actual_hours[ti] < 10).OnlyEnforceIf(b10)
        model.Add(actual_hours[ti] >= 10).OnlyEnforceIf(b10.Not())
        n_under_10_terms.append(b10)
    n_under_18 = model.NewIntVar(0, n_t, "n_under_18")
    n_under_10 = model.NewIntVar(0, n_t, "n_under_10")
    model.Add(n_under_18 == sum(n_under_18_terms) if n_under_18_terms else 0)
    model.Add(n_under_10 == sum(n_under_10_terms) if n_under_10_terms else 0)

    # === DSL compile =================================================
    ctx = dsl.CompileContext(
        model=model,
        n_teachers=n_t,
        teacher_hours=actual_hours,
        teacher_max_hours=teacher_max_hours,
        teacher_unused=teacher_unused,
        teacher_n_classes=teacher_n_classes,
        teacher_n_curricula=teacher_n_curricula,
        teacher_weight=teacher_weight,
        total_unused_capacity=total_unused,
        total_n_classes=total_n_classes_v,
        total_n_curricula=total_n_curricula_v,
        total_weight=total_weight_v,
        n_under_18=n_under_18,
        n_under_10=n_under_10,
    )
    obj_expr, direction = dsl.compile_to_objective(dsl_expression, ctx)

    if direction == "maximize":
        model.Maximize(obj_expr)
    else:
        model.Minimize(obj_expr)

    # === Solve =======================================================
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = workers
    solver.parameters.log_search_progress = log
    solver.parameters.linearization_level = 2
    solver.parameters.cp_model_probing_level = 2

    t0 = time.time()
    status = solver.Solve(model)
    elapsed = time.time() - t0
    print(f"\n[assignment-dsl] status={solver.StatusName(status)} "
          f"elapsed={elapsed:.1f}s")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("Nessuna soluzione trovata.")
    print(
        f"[assignment-dsl] objective={solver.ObjectiveValue():.0f} "
        f"unused={solver.Value(total_unused)} "
        f"n_classes_total={solver.Value(total_n_classes_v)} "
        f"n_curricula_total={solver.Value(total_n_curricula_v)} "
        f"weight_total={solver.Value(total_weight_v)} "
        f"under18={solver.Value(n_under_18)} "
        f"under10={solver.Value(n_under_10)}"
    )

    # Extract solution
    cattedre: dict = {}
    for (ci, subj, ti), var in assign.items():
        if solver.Value(var) == 1:
            tname = teachers[ti]["name"]
            cname = classes[ci]["name"]
            ore = classes[ci]["subjects"][subj]
            cattedre.setdefault(tname, {}).setdefault(cname, {})[subj] = ore

    # Coverage sanity check
    expected_pairs = sum(len(cl["subjects"]) for cl in classes)
    assigned_pairs = sum(
        len(sm) for c in cattedre.values() for sm in c.values()
    )
    if assigned_pairs != expected_pairs:
        raise RuntimeError(
            f"Hard constraint violato: {assigned_pairs}/"
            f"{expected_pairs} cattedre coperte"
        )

    metrics = {
        "objective": int(solver.ObjectiveValue()),
        "total_unused_capacity": int(solver.Value(total_unused)),
        "total_n_classes": int(solver.Value(total_n_classes_v)),
        "total_n_curricula": int(solver.Value(total_n_curricula_v)),
        "total_weight": int(solver.Value(total_weight_v)),
        "n_under_18": int(solver.Value(n_under_18)),
        "n_under_10": int(solver.Value(n_under_10)),
        "direction": direction,
        "elapsed_s": round(elapsed, 1),
    }
    return cattedre, solver, status, metrics
