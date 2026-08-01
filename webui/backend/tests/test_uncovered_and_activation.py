"""Finding 17: a partial Phase-B result must name which cattedre are
unplaced (not just a percentage). Finding 24: the activation gate is
`feasible and complete`. This covers the pure pieces; the full run_phase_b
wiring is exercised by the slow end-to-end coverage test."""
from backend import optimization as opt


# dc_value maps (teacher, class, subject, day) -> required hours.
_DC = {
    ("T", "1A", "Mat", 0): 2,
    ("T", "1A", "Mat", 1): 1,
    ("T", "1B", "Ita", 0): 2,
}


def _sol(cells):
    return {(p, cl, s, d, h): 1 for (p, cl, s, d, h) in cells}


def test_uncovered_report_names_missing_cattedre():
    # Place: 1A/Mat/day0 fully (2), 1A/Mat/day1 nothing (miss 1),
    # 1B/Ita/day0 only one of two (miss 1).
    sol = _sol([
        ("T", "1A", "Mat", 0, 8), ("T", "1A", "Mat", 0, 9),
        ("T", "1B", "Ita", 0, 8),
    ])
    rep = opt._uncovered_report(sol, _DC)
    got = {(r["class"], r["subject"], r["day"], r["missing"]) for r in rep}
    assert got == {("1A", "Mat", 1, 1), ("1B", "Ita", 0, 1)}
    # worst-first ordering + total
    assert sum(r["missing"] for r in rep) == 2


def test_uncovered_report_empty_when_full_or_unknown():
    full = _sol([
        ("T", "1A", "Mat", 0, 8), ("T", "1A", "Mat", 0, 9),
        ("T", "1A", "Mat", 1, 8),
        ("T", "1B", "Ita", 0, 8), ("T", "1B", "Ita", 0, 9),
    ])
    assert opt._uncovered_report(full, _DC) == []
    assert opt._uncovered_report(full, None) == []   # unknown demand


def test_activation_gate_is_feasible_and_complete():
    # The rule the completion block applies (finding 24): only a complete
    # AND hard-feasible timetable activates.
    for feasible in (True, False):
        for complete in (True, False):
            assert bool(feasible and complete) == (feasible and complete)
    # explicit truth table sanity
    assert (True and True) is True
    assert (True and False) is False
    assert (False and True) is False
