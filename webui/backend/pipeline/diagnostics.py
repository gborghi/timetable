"""Async (and one sync) diagnostic runners.

Hall, Monte Carlo, bipartite, correlations, distributions. Results
land in /runs via run_manager so the Diagnostica tab can poll them.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from ..db import SessionLocal
from ..run_manager import create_run, start_thread, update_run


def _ensure_engine_scripts_on_path() -> None:
    """Hall check lives under engine/ (package) and historically also
    under engine/scripts. get_engine_dir() is already on sys.path via
    engine_paths; this is a no-op kept so the import style stays
    `from diagnostics import ...`.
    """
    from ..engine_paths import ensure_engine_on_path
    ensure_engine_on_path()


def run_hall_check(*, n_samples: int = 256,
                   teacher_max_hours: int = 18) -> dict[str, Any]:
    """Synchronous Hall's theorem pre-check. Returns the diagnostic
    dict directly (no run_id thread): the operation is < 100 ms even
    on superhuge schools so a sync API is fine.

    Kept for back-compat. New code should prefer
    `run_diag_hall_check` which spawns an async run consistent with
    the other diagnostics.
    """
    _ensure_engine_scripts_on_path()
    from diagnostics import hall_check as hc  # type: ignore
    with SessionLocal() as db:
        return hc.hall_check_from_db(
            db, n_samples=n_samples,
            teacher_max_hours=teacher_max_hours,
        )


def run_diag_hall_check(*, n_samples: int = 256,
                         teacher_max_hours: int = 18) -> int:
    """Async Hall pre-check: same algorithm as `run_hall_check` but
    spawned as a run (kind='diag_hall'). Used by the /diagnostics
    tab so the result lands in /runs alongside the other
    diagnostics."""
    _ensure_engine_scripts_on_path()

    def _go() -> dict:
        from diagnostics import hall_check as hc  # type: ignore
        with SessionLocal() as db:
            return hc.hall_check_from_db(
                db, n_samples=n_samples,
                teacher_max_hours=teacher_max_hours,
            )
    return run_diagnostic_async(
        "diag_hall",
        f"Hall pre-check (N={n_samples})",
        _go,
    )


def run_diagnostic_async(kind: str, label: str,
                          producer: Callable[..., dict]) -> int:
    """Generic helper: spawn a /runs entry whose target() invokes
    `producer()` (a 0-arg function returning a JSON-serializable
    diagnostic result) and stores the result in `metrics`. The
    front-end polls /api/optimize/runs/{id} and, on done, reads
    `metrics` (which `serialize_run` already exposes).

    Used by Monte Carlo / bipartite / correlations / distributions:
    these can take seconds-to-tens-of-seconds, so they are no
    longer surfaced as sync endpoints.
    """
    params = {"kind": kind, "label": label}
    rid = create_run(kind, label, None, params)

    def target(rid_inner: int):
        update_run(rid_inner, progress=0.05)
        # Long diagnostics (Monte Carlo) can pass fine-grained progress by
        # accepting a 1-arg callback `progress_cb(frac)` with frac in [0,1];
        # we map it onto the run's [0.05, 0.95] band and throttle DB writes
        # to ~1% steps. Producers that take no argument keep working as-is.
        last = [0.05]

        def on_progress(frac: float) -> None:
            try:
                f = max(0.0, min(1.0, float(frac)))
            except Exception:
                return
            p = 0.05 + 0.90 * f
            if p - last[0] >= 0.01 or f >= 1.0:
                last[0] = p
                update_run(rid_inner, progress=round(p, 3))

        try:
            takes_cb = len(inspect.signature(producer).parameters) >= 1
        except (TypeError, ValueError):
            takes_cb = False
        result = producer(on_progress) if takes_cb else producer()
        update_run(rid_inner, progress=0.95,
                    metrics=result if isinstance(result, dict)
                            else {"result": result})

    start_thread(rid, target)
    return rid


def run_diag_montecarlo(*, n_samples: int = 100,
                         seed: int = 0) -> int:
    _ensure_engine_scripts_on_path()

    def _go(progress_cb=None) -> dict:
        from diagnostics import montecarlo_sensitivity as mc  # type: ignore
        with SessionLocal() as db:
            return mc.run_montecarlo_from_db(
                db, n_samples=n_samples, seed=seed,
                progress_cb=progress_cb,
            )
    return run_diagnostic_async(
        "diag_montecarlo",
        f"Sensitivity Monte Carlo (N={n_samples})",
        _go,
    )


def run_diag_bipartite(*, mode: str = "classes") -> int:
    _ensure_engine_scripts_on_path()

    def _go() -> dict:
        from diagnostics import bipartite_analysis as ba  # type: ignore
        with SessionLocal() as db:
            return ba.analyze_from_db(db, mode=mode)
    return run_diagnostic_async(
        "diag_bipartite",
        f"Analisi bipartito ({mode})",
        _go,
    )


def run_diag_correlations(*, models_spec: list[dict] | None = None
                           ) -> int:
    _ensure_engine_scripts_on_path()

    def _go() -> dict:
        from diagnostics import correlations as co  # type: ignore
        with SessionLocal() as db:
            return co.run_from_db(db, models_spec=models_spec)
    label = "Correlazioni e regressioni"
    if models_spec:
        label += f" ({len(models_spec)} modell{'i' if len(models_spec) != 1 else 'o'} custom)"
    return run_diagnostic_async(
        "diag_correlations",
        label,
        _go,
    )


def run_diag_distributions(*, spec: dict | None = None) -> int:
    _ensure_engine_scripts_on_path()

    def _go() -> dict:
        from diagnostics import distributions as ds  # type: ignore
        with SessionLocal() as db:
            return ds.run_from_db(db, spec=spec)
    label = "Distribuzioni e goodness-of-fit"
    if spec and spec.get("include"):
        label += f" ({len(spec['include'])} sel)"
    return run_diagnostic_async(
        "diag_distributions",
        label,
        _go,
    )
