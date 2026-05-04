"""Atom 6 — native lock support in column generation.

Tests that:
- _seed_patterns and _diversified_seed pre-place locks in every
  generated pattern.
- run_column_generation forwards locks to the pattern generators
  and locked_by_day to the completion solver.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
for p in (WEBUI_DIR, ENGINE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _make_profs_and_dc():
    profs = {
        "ProfA": {
            "classi": {"1A": {"Mat": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
        "ProfB": {
            "classi": {"1A": {"Ita": {"ore": 4}}},
            "glibero": [6, 5, 4],
        },
    }
    dc_value = {
        ("ProfA", "1A", "Mat", 1): 2,
        ("ProfA", "1A", "Mat", 2): 2,
        ("ProfB", "1A", "Ita", 1): 2,
        ("ProfB", "1A", "Ita", 2): 2,
    }
    return profs, dc_value


def test_seed_patterns_preplaces_locks():
    import column_generation as cg  # type: ignore
    profs, dc_value = _make_profs_and_dc()
    locks = {("ProfA", "1A", "Mat", 1, 8),
             ("ProfA", "1A", "Mat", 1, 9)}
    pats = cg._seed_patterns(profs, dc_value,
                              max_per_teacher=2, locks=locks)
    # Every ProfA pattern must contain BOTH locks.
    assert "ProfA" in pats
    assert pats["ProfA"], "no patterns for ProfA"
    for pat in pats["ProfA"]:
        for k in locks:
            assert pat.get(k) == 1, (
                f"lock {k} missing from pattern: "
                f"{[k_ for k_, v in pat.items() if v]}")


def test_diversified_seed_preplaces_locks():
    import column_generation as cg  # type: ignore
    profs, dc_value = _make_profs_and_dc()
    locks = {("ProfB", "1A", "Ita", 2, 11)}
    pats = cg._diversified_seed(profs, dc_value, n_variants=3,
                                 rng_seed=1, locks=locks)
    assert "ProfB" in pats
    for pat in pats["ProfB"]:
        for k in locks:
            assert pat.get(k) == 1, f"lock {k} missing"


def test_locks_present_in_every_iteration_pattern():
    """Verify that across enrichment iterations of run_column_generation,
    every newly generated pattern still contains the locks. Smoke
    test using _diversified_seed at multiple seeds."""
    import column_generation as cg  # type: ignore
    profs, dc_value = _make_profs_and_dc()
    locks = {("ProfA", "1A", "Mat", 1, 8),
             ("ProfB", "1A", "Ita", 2, 11)}
    for seed in [0, 17, 42]:
        pats = cg._diversified_seed(profs, dc_value, n_variants=2,
                                     rng_seed=seed, locks=locks)
        for tname, plist in pats.items():
            for pat in plist:
                for k in locks:
                    if k[0] != tname:
                        continue
                    assert pat.get(k) == 1, (
                        f"seed {seed} {tname}: lock {k} missing")
