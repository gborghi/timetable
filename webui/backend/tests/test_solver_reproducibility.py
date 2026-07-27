"""Reproducibility of CP-SAT solves (P1: reproducible seeds).

Before ``engine/solver_config.py`` no solver set ``random_seed`` and all
ran multi-worker with a wall-clock budget, so the SAME input could flip
feasible/infeasible or change objective across reruns/machines -- the
audit's "worked yesterday, fails today" support nightmare.

With ``PITANTUM_DETERMINISTIC=1`` (fixed seed + single search worker)
every solve of the same model must return the identical result, even
when the solve hits its time limit. This exercises the real solver, so
it carries the ``slow`` marker.
"""
from __future__ import annotations

import pytest


def _signature(cattedre):
    """Order-independent, hashable signature of a cattedre list."""
    out = []
    for c in cattedre:
        if isinstance(c, dict):
            out.append(tuple(sorted((k, repr(v)) for k, v in c.items())))
        else:
            out.append(repr(c))
    return sorted(out)


@pytest.mark.slow
def test_phase_a_is_reproducible_in_deterministic_mode(monkeypatch):
    monkeypatch.setenv("PITANTUM_DETERMINISTIC", "1")
    monkeypatch.setenv("PITANTUM_SOLVER_SEED", "42")

    import big_mock_school as bms
    import cpsat_v2_assignment as ca

    data = bms.build_dataset("small", tight=True)

    r1 = ca.solve_assignment(data, time_limit_s=8, workers=8, log=False)[0]
    r2 = ca.solve_assignment(data, time_limit_s=8, workers=8, log=False)[0]

    assert _signature(r1) == _signature(r2), (
        "deterministic mode must yield identical assignments across runs"
    )
    assert len(r1) > 0
