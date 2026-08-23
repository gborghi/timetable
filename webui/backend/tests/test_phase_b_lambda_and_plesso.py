"""Second Phase B λ pass + Lagrangian teacher-plesso cut helpers."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def test_days_from_room_penalties_only_pairs():
    import decomposition_temporal as dec

    assert dec.days_from_room_penalties(None) == set()
    assert dec.days_from_room_penalties({}) == set()
    assert dec.days_from_room_penalties({8: 10, 9: 20}) == set()
    assert dec.days_from_room_penalties({(1, 8): 80, (3, 9): 40, 8: 10}) == {1, 3}


def test_refine_days_noop_without_day_keys():
    import decomposition_temporal as dec

    sol = {("T", "1A", "Mat", 1, 8): 1}
    out, info = dec.refine_days_with_room_penalties(
        sol, {}, {}, {8: 10},
    )
    assert out is sol
    assert info["accepted"] is False
    assert info["retried_days"] == []


def test_clusters_from_plesso_pins_needs_two_sites():
    import lagrangian as lag

    assert lag.clusters_from_plesso_pins(None) == {}
    assert lag.clusters_from_plesso_pins({"1A": 1, "1B": 1}) == {}
    out = lag.clusters_from_plesso_pins({"1A": 1, "1B": 2, "1C": 2})
    assert out == {1: {"1A"}, 2: {"1B", "1C"}}
    # Unpinned classes land in a trailing cluster so they are not dropped.
    out2 = lag.clusters_from_plesso_pins(
        {"1A": 1, "1B": 2}, all_classes=["1A", "1B", "1C"],
    )
    assert out2[1] == {"1A"}
    assert out2[2] == {"1B"}
    assert {"1C"} in out2.values()


def test_run_lagrangian_auto_plesso_cut_is_documented():
    import lagrangian as lag

    profs = {
        "Bridge": {
            "classi": {
                "1A": {"Mat": {"ore": 1}},
                "1B": {"Mat": {"ore": 1}},
            },
            "max_hours": 18,
            "min_free_days": 0,
        },
    }
    sol = {
        ("Bridge", "1A", "Mat", 1, 8): 1,
        ("Bridge", "1B", "Mat", 1, 8): 1,
    }
    dc = {
        ("Bridge", "1A", "Mat", 1): 1,
        ("Bridge", "1B", "Mat", 1): 1,
    }
    # Two pins + a commuting teacher: cluster_source must be plesso
    # even with no caller partition. Groups are absent so it is not a
    # groups no-op. The reconstruction may or may not be accepted; we
    # only pin the cut.
    _best, info = lag.run_lagrangian(
        sol, profs, dc,
        time_budget_s=2.0, max_iter=1, log=False,
        class_to_plesso={"1A": 10, "1B": 20},
        class_flags={"1A": {"entry_at_8": False, "no_holes": False,
                            "exit_after_12": False},
                     "1B": {"entry_at_8": False, "no_holes": False,
                            "exit_after_12": False}},
    )
    assert info["cluster_source"] == "plesso"
    assert info["mode"] != "noop_no_clusters"


def test_retry_unplaced_skips_when_nothing_to_do():
    from backend.pipeline.rooms import retry_unplaced_days_with_lambda

    base = {"rooms_unplaced": 0, "room_slot_penalties": {(1, 8): 80}}
    assert retry_unplaced_days_with_lambda(
        1, base, time_limit_s=1, workers=1, prefer_home=True,
    ) is base
    base2 = {"rooms_unplaced": 2, "room_slot_penalties": {8: 80}}
    out = retry_unplaced_days_with_lambda(
        1, base2, time_limit_s=1, workers=1, prefer_home=True,
    )
    assert out is base2
