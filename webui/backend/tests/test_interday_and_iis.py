"""Inter-day hint / 2-day F&O helpers + INFEASIBLE explanation."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def test_hint_from_day_remaps_neighbour_occupancy():
    import decomposition_temporal as dec

    sol = {
        ("T", "1A", "Mat", 1, 8): 1,
        ("T", "1A", "Mat", 1, 9): 0,
        ("T", "1B", "Ita", 1, 10): 1,
    }
    hinted = dec.hint_from_day(sol, 2)
    assert hinted == {
        ("T", "1A", "Mat", 2, 8): 1,
        ("T", "1B", "Ita", 2, 10): 1,
    }
    assert dec.hint_from_day(None, 2) == {}
    assert dec.hint_from_day({}, 3) == {}


def test_explain_day_infeasibility_hall_and_format():
    import decomposition_temporal as dec

    # One teacher, two classes, 5 hours on a day whose classes only
    # have 2 hours of load each -> Hall (5 > max 2).
    profs = {
        "T": {"classi": {"1A": [("Mat", 5)], "1B": [("Ita", 2)]}},
    }
    dc = {
        ("T", "1A", "Mat", 1): 3,
        ("T", "1B", "Ita", 1): 2,
    }
    expl = dec.explain_day_infeasibility(profs, dc, 1)
    assert expl["day"] == 1
    assert expl["hall_violations"]
    assert expl["hall_violations"][0]["prof"] == "T"
    assert expl["hall_violations"][0]["prof_hours"] == 5
    line = dec.format_infeasibility(expl)
    assert line.startswith(" Causa:")
    assert "Hall" in line


def test_format_infeasibility_empty():
    import decomposition_temporal as dec

    assert dec.format_infeasibility(None) == ""
    assert dec.format_infeasibility({}) == ""
    assert dec.format_infeasibility({"summary": ""}) == ""


def test_explain_day_infeasibility_class_load_and_overload():
    import decomposition_temporal as dec

    # 6 hours on one class: load is legal (not 1/2/3) but exceeds
    # MAX_PROF_HOURS_PER_DAY (=5) -> prof_overload, no Hall (6 == 6).
    dc = {("T", "1A", "Mat", 2): 6}
    expl = dec.explain_day_infeasibility({}, dc, 2)
    assert expl["hall_violations"] == []
    assert expl["class_load_outliers"] == []
    assert expl["prof_overload"][0]["prof"] == "T"
    assert expl["prof_overload"][0]["total_hours_in_day"] == 6
    assert "HARD-C" in expl["summary"]

    # Isolated 2-hour class load is the 1/2/3 band.
    expl2 = dec.explain_day_infeasibility(
        {}, {("T", "1A", "Mat", 3): 2}, 3)
    assert expl2["class_load_outliers"][0]["class"] == "1A"
    assert expl2["class_load_outliers"][0]["day_load"] == 2
    assert "HARD-2" in expl2["summary"]


def test_explain_day_infeasibility_ignores_other_days_and_zeros():
    import decomposition_temporal as dec

    dc = {
        ("T", "1A", "Mat", 1): 3,
        ("T", "1B", "Ita", 1): 2,
        ("T", "1A", "Mat", 2): 5,
        ("T", "1C", "Sto", 1): 0,
    }
    expl = dec.explain_day_infeasibility({}, dc, 2)
    assert expl["hall_violations"] == []
    assert expl["prof_overload"] == []
    assert expl["class_load_outliers"] == []
    assert "Nessuna violazione strutturale" in expl["summary"]


def test_hint_from_day_skips_non_five_tuples_and_zeros():
    import decomposition_temporal as dec

    sol = {
        ("T", "1A", "Mat", 8): 1,          # 4-tuple, ignored
        ("T", "1A", "Mat", 1, 8): 0,       # zero, ignored
        ("T", "1A", "Mat", 1, 9): 1,
    }
    assert dec.hint_from_day(sol, 4) == {("T", "1A", "Mat", 4, 9): 1}


def test_fix_and_optimize_two_days_retries_neighbour(monkeypatch):
    import decomposition_temporal as dec

    calls = []

    def fake_solve(day, profs, dc_value, **kw):
        calls.append((day, bool(kw.get("warm_start"))))
        # First attempt on the failed day misses; neighbour re-solve
        # plus the retry both succeed.
        if day == 2 and len([c for c in calls if c[0] == 2]) == 1:
            return None, 3
        return {("T", "1A", "Mat", day, 8): 1}, 4

    monkeypatch.setattr(dec, "solve_day", fake_solve)
    sol_ok = {("T", "1A", "Mat", 1, 8): 1}
    new_ok, new_fail = dec.fix_and_optimize_two_days(
        1, 2, {}, {}, sol_ok, time_limit=1.0, workers=1)
    assert new_fail is not None
    assert new_ok is not None
    assert [c[0] for c in calls] == [2, 1, 2]
    assert all(c[1] for c in calls)
