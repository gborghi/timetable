"""Shared CP-SAT solver configuration for reproducible runs.

Every ``cp_model.CpSolver()`` in the engine is routed through
``configure_solver()`` right before ``Solve()`` so that runs are
reproducible. Previously no solver set ``random_seed`` and every solver
ran multi-worker with a wall-clock time limit -- so the SAME input could
flip feasible/infeasible across machines or reruns, which the audit
flagged as a support nightmare ("worked yesterday, fails today").

Two knobs (both env-driven, safe defaults):
  * ``PITANTUM_SOLVER_SEED`` -- integer seed applied to every solve
    (default 42). A fixed seed alone makes single-worker solves
    reproducible and materially reduces variance otherwise.
  * ``PITANTUM_DETERMINISTIC`` -- when truthy, force ONE search worker.
    Multi-worker CP-SAT is non-deterministic even with a fixed seed
    (workers race), so full reproducibility requires a single worker.
    Off by default because it trades throughput for determinism.

Applied *after* each call site's own ``parameters`` block (i.e.
immediately before ``Solve``) so the deterministic single-worker
override wins over the site's ``num_search_workers = workers``.
"""
from __future__ import annotations

import os


def solver_seed() -> int:
    """Fixed random seed for every solve (env-overridable)."""
    v = os.environ.get("PITANTUM_SOLVER_SEED", "").strip()
    if v:
        try:
            return int(v)
        except ValueError:
            pass
    return 42


def deterministic_mode() -> bool:
    """True when the operator opted into fully-deterministic solving."""
    return os.environ.get("PITANTUM_DETERMINISTIC", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def configure_solver(solver):
    """Apply reproducibility settings to a ``cp_model.CpSolver``.

    Call immediately before ``solver.Solve(...)`` so the deterministic
    override lands last. Returns the solver for convenience.
    """
    params = solver.parameters
    params.random_seed = solver_seed()
    if deterministic_mode():
        params.num_search_workers = 1
    return solver
