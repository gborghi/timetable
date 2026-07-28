r"""Monte Carlo sensitivity analysis on the SOFT objective.

Generates N feasible-ish solutions by RANDOMLY perturbing the
current active solution -- not by re-running CP-SAT from scratch
(which would be prohibitively expensive). Each perturbation is a
sequence of single-swap atomic moves applied to the active
solution, accepted only if HARD remains satisfied. The SOFT value
of each is collected.

If `std / mean < 0.05`, the active solution is interpreted as
"already near the locally-attainable optimum"; large variance
suggests room for metaheuristic improvement.

This is intentionally cheaper than full CP-SAT regeneration: with
N=100 random walks of ~30 moves each it runs in seconds even on
huge instances.
"""
from __future__ import annotations

import os
import random
import sys
from typing import Any

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import metaheuristics as meta  # type: ignore  # noqa: E402


def run_montecarlo(sol: dict, profs: dict, dc_value: dict,
                   *, n_samples: int = 100,
                   moves_per_sample: int = 30,
                   seed: int = 0,
                   progress_cb=None) -> dict[str, Any]:
    """Generate `n_samples` perturbations of `sol` and return SOFT
    statistics. If `progress_cb` is given it is called after each sample
    with the fraction completed in [0, 1] (used to drive the run's
    progress bar)."""
    rng = random.Random(seed)
    base_val, _ = meta.compute_soft(sol, profs)
    samples: list[float] = []

    for i in range(n_samples):
        cur = meta.deepcopy_sol(sol)
        for _ in range(moves_per_sample):
            mv = rng.choice(meta.ATOMIC_MOVES)
            try:
                nxt = mv(cur, profs, dc_value, rng)
            except Exception:
                nxt = None
            if nxt is not None and meta.is_hard_feasible(
                nxt, profs, verbose=False
            ):
                cur = nxt
        v, _ = meta.compute_soft(cur, profs)
        samples.append(float(v))
        if progress_cb is not None:
            try:
                progress_cb((i + 1) / n_samples)
            except Exception:
                pass

    if not samples:
        return {
            "ok": False, "n_samples": 0, "msg": "nessun sample generato",
        }
    samples_sorted = sorted(samples)
    mean = sum(samples) / len(samples)
    std = (sum((x - mean) ** 2 for x in samples) / len(samples)) ** 0.5

    def percentile(p: float) -> float:
        if not samples_sorted:
            return 0.0
        i = int(round((p / 100.0) * (len(samples_sorted) - 1)))
        return samples_sorted[max(0, min(i, len(samples_sorted) - 1))]

    coef_var = std / mean if mean > 1e-9 else 0.0
    return {
        "ok": True,
        "n_samples": len(samples),
        "base_val": float(base_val),
        "samples": samples,
        "mean": float(mean),
        "std": float(std),
        "min": float(min(samples)),
        "max": float(max(samples)),
        "p25": float(percentile(25)),
        "p50": float(percentile(50)),
        "p75": float(percentile(75)),
        "coefficient_of_variation": float(coef_var),
        "interpretation": (
            "Variabilita' bassa: soluzione attiva vicina all'ottimo "
            "locale; il margine di miglioramento col tuning e' limitato."
            if coef_var < 0.05
            else "Variabilita' elevata: la soluzione attuale ha "
                  "potenziale di miglioramento -- prova ALNS/VNS/TS."
        ),
    }


def run_montecarlo_from_db(db, *, n_samples: int = 100,
                           seed: int = 0,
                           progress_cb=None) -> dict[str, Any]:
    """Convenience wrapper: pulls the active solution from the DB and
    runs `run_montecarlo`. Returns the same structured report."""
    from backend import engine_io  # type: ignore
    profs = engine_io.profs_dict_from_db(db)
    active = engine_io.get_active_solution(db)
    if active is None:
        return {
            "ok": False, "n_samples": 0,
            "msg": "Nessuna soluzione attiva: lancia prima Phase B.",
        }
    sol = engine_io.lessons_to_solution_dict(db, active.id)
    # Reconstruct dc_value from sol
    from backend import optimization
    dc_value = optimization._restore_dc_from_solution(sol)
    return run_montecarlo(sol, profs, dc_value,
                           n_samples=n_samples, seed=seed,
                           progress_cb=progress_cb)
