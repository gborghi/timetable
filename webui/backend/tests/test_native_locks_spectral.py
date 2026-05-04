"""Atom 2 — native lock constraints in spectral_v2 decomposition.

Tests that the 4 stages of decomposition_spectral_v2 (stage_a_bridges,
stage_b_cluster_internals, stage_c_ricucitura, solve_monolithic_day)
plus their orchestrator decomposition_loop.run_partitioned_pipeline
honour the native lock parameter `locked_slots_for_day`.

Hand-built mini scenario (3 profs, 2 classes) with deterministic
cluster split: ProfA bridges 1A and 1B; ProfB and ProfC are
internal to one cluster each.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _make_profs():
    return {
        "ProfA": {                       # bridges both classes
            "classi": {"1A": {"Mat": {"ore": 4}},
                        "1B": {"Mat": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfB": {                       # internal to "1A only"
            "classi": {"1A": {"Ita": {"ore": 4}},
                        "1B": {"Ita": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfC": {                       # internal
            "classi": {"1A": {"Sto": {"ore": 2}},
                        "1B": {"Sto": {"ore": 2}}},
            "glibero": [6, 5, 4],
        },
    }


def _build_partition_one_cluster(profs):
    """Trivial partition: all classes in 1 cluster, no bridges. This
    keeps the test focused on the lock semantics across stages.
    Stage A is a no-op (bridges set is empty); stage B handles all
    triples in the single cluster."""
    import numpy as np
    classes = sorted({c for p in profs.values() for c in p["classi"]})
    labels = np.zeros(len(classes), dtype=int)
    bridges: set[str] = set()
    return labels, classes, bridges


def _run_loop(profs, *, locked_dc=None, locked_by_day=None):
    import decomposition_loop as dl  # type: ignore
    labels, classes, bridges = _build_partition_one_cluster(profs)
    return dl.run_partitioned_pipeline(
        profs, labels, classes, bridges,
        time_a=2, time_bridges=2, time_cluster=2,
        time_ricucitura=2, time_mono=2,
        workers=2, log=False,
        locked_day_count=locked_dc,
        locked_by_day=locked_by_day,
    )


def test_spectral_loop_lock_respected_by_stage_b():
    profs = _make_profs()
    locked_dc = {("ProfA", "1A", "Mat", 2): 2}
    locked_by_day = {2: [("ProfA", "1A", "Mat", 8),
                          ("ProfA", "1A", "Mat", 9)]}
    res = _run_loop(profs, locked_dc=locked_dc,
                     locked_by_day=locked_by_day)
    sol = res["full_solution"]
    assert res["status"] in ("ok", "partial"), res["status"]
    # Locks honoured.
    assert sol[("ProfA", "1A", "Mat", 2, 8)] == 1
    assert sol[("ProfA", "1A", "Mat", 2, 9)] == 1
    # Total Mat hours preserved.
    n = sum(v for (p, c, s, _, _), v in sol.items()
            if p == "ProfA" and c == "1A" and s == "Mat")
    assert n == 4


def test_spectral_loop_infeasible_lock_phase_a():
    profs = _make_profs()
    locked_dc = {("ProfA", "1A", "Mat", 2): 3}  # > MAX_PER_DAY_TRIPLE
    with pytest.raises(RuntimeError) as exc_info:
        _run_loop(profs, locked_dc=locked_dc)
    msg = str(exc_info.value)
    assert "INFEASIBLE" in msg or "infeasible" in msg.lower()
    assert "lock" in msg.lower()


def test_stage_a_bridges_with_real_bridges():
    """When ProfA is a bridge, a lock on ProfA-(any class) is
    enforced by Stage A and propagated into Stage B via
    bridge_in_slot. We exercise the function directly to make
    sure the bridge filter in stage_a_bridges does not drop the
    lock."""
    import cpsat_v2_timetable as cv2  # type: ignore
    import decomposition_spectral_v2 as dec  # type: ignore
    profs = _make_profs()
    classes_v, triples, _class_profs = cv2.build_indices(profs)
    locked_dc = {("ProfA", "1A", "Mat", 2): 2}
    dc_value = cv2.solve_phase_a(
        profs, classes_v, triples, _class_profs,
        time_limit=2, workers=2, log=False,
        locked_day_count=locked_dc,
    )
    bridges_set = {"ProfA"}
    locked_d2 = [("ProfA", "1A", "Mat", 8),
                  ("ProfA", "1A", "Mat", 9)]
    out, _status = dec.stage_a_bridges(
        2, profs, bridges_set, triples, dc_value,
        time_limit=2, workers=2,
        locked_slots_for_day=locked_d2,
    )
    assert out is not None
    assert out[("ProfA", "1A", "Mat", 2, 8)] == 1
    assert out[("ProfA", "1A", "Mat", 2, 9)] == 1
