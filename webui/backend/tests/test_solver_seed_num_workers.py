"""Seed e num_workers (Kepler, punto 8.1).

* nessun sorgente del motore o del backend usa piu' il parametro deprecato
  ``num_search_workers``: tutti usano ``num_workers``, cosi'
  ``configure_solver`` (che in modalita' deterministica mette 1 worker)
  vale davvero;
* il percorso settimanale chiama ``configure_solver``;
* con ``PITANTUM_DETERMINISTIC=1`` due solve uguali danno lo stesso orario.
"""
from __future__ import annotations

import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
for p in (REPO_ROOT / "webui", REPO_ROOT / "engine"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def test_no_num_search_workers_in_sources():
    offenders = []
    for base in (REPO_ROOT / "engine", REPO_ROOT / "webui" / "backend"):
        for f in base.rglob("*.py"):
            if "tests" in f.parts:
                continue
            if "parameters.num_search_workers" in f.read_text(
                    encoding="utf-8", errors="ignore"):
                offenders.append(str(f.relative_to(REPO_ROOT)))
    assert not offenders, offenders


def test_week_path_calls_configure_solver():
    src = (REPO_ROOT / "webui" / "backend" / "optimization.py").read_text(
        encoding="utf-8")
    i = src.index("cp_solver.parameters.max_time_in_seconds = float(time_mono)")
    j = src.index("status = cp_solver.Solve(solver.model", i)
    assert "_solvercfg.configure_solver(cp_solver)" in src[i:j]


def test_deterministic_mode_same_schedule(monkeypatch):
    import cp_sat_constraint_model as csm
    monkeypatch.setenv("PITANTUM_DETERMINISTIC", "1")
    P = {"M": {"classi": {"1A": {"Matematica": {"ore": 4}}},
               "min_free_days": 1}}
    for i in range(5):
        P[f"T{i}"] = {"classi": {"1A": {f"S{i}": {"ore": 5}}},
                      "min_free_days": 1}
    out = []
    for _ in range(2):
        s = csm.MonolithicSolver(P, dc_value=None,
                                 config=csm.ConstraintConfig(locks=[]),
                                 scope=None)
        res = s.solve(time_limit_s=5, workers=8)
        sol = res[0] if isinstance(res, tuple) else res
        out.append(sorted(k for k, v in (sol or {}).items() if v))
    assert out[0] and out[0] == out[1]
