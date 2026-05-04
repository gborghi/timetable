"""End-to-end integration: coteach × shadow × potenziamento × pipeline.

Marked @pytest.mark.slow. Each test invokes the engine entry-points
directly with a hand-built profs dict + the matching helper lists,
then checks the structural invariants of the resulting solution.
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


def _shared_school():
    """Principal/codoc on Chimica + 3 normal cattedre filling 3B's
    weekly hours (12 = 4+4+4 distributed 6+6 over two days)."""
    return {
        "ProfA": {"classi": {"3B": {"Chimica": {"ore": 4}}},
                  "glibero": [6, 5, 4]},
        "ProfB": {"classi": {"3B": {"Chimica": {"ore": 2}}},
                  "glibero": [6, 5, 4]},
        "ProfC": {"classi": {"3B": {"Italiano": {"ore": 4}}},
                  "glibero": [6, 5, 4]},
        "ProfD": {"classi": {"3B": {"Storia": {"ore": 4}}},
                  "glibero": [6, 5, 4]},
    }


def _shared_groups():
    return [{
        "group_id": 1, "class_name": "3B", "subject": "Chimica",
        "n_hours": 2, "required": True, "weight": 100.0,
        "teachers": ["ProfA", "ProfB"],
    }]


def _solve(profs, *, coteach_groups=None, support=None,
           pot=None, time_a=2, time_b=2):
    import cpsat_v2_timetable as cv2  # type: ignore
    classes_v, triples, class_profs = cv2.build_indices(profs)
    dc = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=time_a, workers=2, log=False,
        coteach_groups=coteach_groups,
        support_assignments=support,
        potenziamento_assignments=pot,
    )
    full = {}
    for d in cv2.DAYS:
        out, _ = cv2.solve_phase_b_for_day(
            d, profs, classes_v, triples, class_profs, dc,
            time_limit=time_b, workers=2, log=False,
            coteach_groups=coteach_groups,
            support_assignments=support,
        )
        if out:
            full.update(out)
    return dc, full


@pytest.mark.slow
def test_integration_shared_only():
    profs = _shared_school()
    dc, sol = _solve(profs, coteach_groups=_shared_groups())
    # 2 ProfB slots all coincide with ProfA's.
    for k, v in sol.items():
        if k[0] == "ProfB" and v == 1:
            assert sol.get(("ProfA", k[1], k[2], k[3], k[4])) == 1


@pytest.mark.slow
def test_integration_shared_plus_shadow():
    """Lab di chimica con compresenza + sostegno (DVA in 3B)."""
    profs = _shared_school()
    profs["ProfSost"] = {
        "classi": {"3B": {"sostegno": {"ore": 4}}},
        "glibero": [6, 5, 4],
    }
    sup = [{"teacher_name": "ProfSost", "class_name": "3B",
            "subject": "sostegno", "n_hours": 4}]
    dc, sol = _solve(profs, coteach_groups=_shared_groups(),
                     support=sup)
    # Compresenza intact.
    for k, v in sol.items():
        if k[0] == "ProfB" and v == 1:
            assert sol.get(("ProfA", k[1], k[2], k[3], k[4])) == 1
    # Sostegno: 4 hours, every one coinciding with a non-support
    # 3B lesson.
    n_sost = sum(v for (p, c, s, _, _), v in sol.items()
                 if p == "ProfSost" and c == "3B" and s == "sostegno")
    assert n_sost == 4
    for k, v in sol.items():
        if k[0] == "ProfSost" and v == 1:
            d, h = k[3], k[4]
            non_sup = [kk for kk, kv in sol.items()
                       if kk[1] == "3B" and kk[3] == d and kk[4] == h
                       and kk[2] != "sostegno" and kv == 1]
            assert non_sup, f"sost ({d},{h}) without coverage"


@pytest.mark.slow
def test_integration_shared_plus_potenziamento():
    """Compresenza + un prof con ore di potenziamento."""
    profs = _shared_school()
    profs["ProfPot"] = {"classi": {}, "glibero": [6, 5, 4]}
    pot = [{"teacher_name": "ProfPot", "subject": "Potenziamento",
            "n_hours": 6}]
    dc, _sol = _solve(profs, coteach_groups=_shared_groups(),
                       pot=pot)
    pot_total = sum(v for k, v in dc.items()
                    if isinstance(k, tuple) and len(k) == 3
                    and k[0] == "__pot__" and k[1] == "ProfPot")
    assert pot_total == 6


@pytest.mark.slow
def test_integration_shadow_plus_potenziamento():
    """Sostegno + potenziamento (no coteach)."""
    profs = {
        "ProfA": {"classi": {"3B": {"Mat": {"ore": 4}}},
                   "glibero": [6, 5, 4]},
        "ProfB": {"classi": {"3B": {"Ita": {"ore": 4}}},
                   "glibero": [6, 5, 4]},
        "ProfC": {"classi": {"3B": {"Sto": {"ore": 4}}},
                   "glibero": [6, 5, 4]},
        "ProfSost": {"classi": {"3B": {"sostegno": {"ore": 4}}},
                      "glibero": [6, 5, 4]},
        "ProfPot": {"classi": {}, "glibero": [6, 5, 4]},
    }
    sup = [{"teacher_name": "ProfSost", "class_name": "3B",
            "subject": "sostegno", "n_hours": 4}]
    pot = [{"teacher_name": "ProfPot", "subject": "Potenziamento",
            "n_hours": 4}]
    dc, sol = _solve(profs, support=sup, pot=pot)
    n_sost = sum(v for (p, c, s, _, _), v in sol.items()
                 if p == "ProfSost" and v == 1)
    assert n_sost == 4
    pot_total = sum(v for k, v in dc.items()
                    if isinstance(k, tuple) and len(k) == 3
                    and k[0] == "__pot__")
    assert pot_total == 4


@pytest.mark.slow
def test_integration_all_three_simultaneously():
    profs = _shared_school()
    profs["ProfSost"] = {
        "classi": {"3B": {"sostegno": {"ore": 4}}},
        "glibero": [6, 5, 4],
    }
    profs["ProfPot"] = {"classi": {}, "glibero": [6, 5, 4]}
    sup = [{"teacher_name": "ProfSost", "class_name": "3B",
            "subject": "sostegno", "n_hours": 4}]
    pot = [{"teacher_name": "ProfPot", "subject": "Potenziamento",
            "n_hours": 4}]
    dc, sol = _solve(profs,
                     coteach_groups=_shared_groups(),
                     support=sup, pot=pot)
    # Coteach hours total 4 (ProfA) + 2 (ProfB).
    a = sum(v for k, v in sol.items()
            if k[0] == "ProfA" and k[2] == "Chimica" and v == 1)
    b = sum(v for k, v in sol.items()
            if k[0] == "ProfB" and k[2] == "Chimica" and v == 1)
    assert a == 4 and b == 2
    # Sostegno covered.
    n_sost = sum(v for (p, _c, _s, _d, _h), v in sol.items()
                 if p == "ProfSost" and v == 1)
    assert n_sost == 4
    # Potenziamento total in dc.
    pot_total = sum(v for k, v in dc.items()
                    if isinstance(k, tuple) and len(k) == 3
                    and k[0] == "__pot__")
    assert pot_total == 4


@pytest.mark.slow
def test_integration_shared_infeasible_n_hours_too_high():
    """n_hours > principal weekly -> Phase A INFEASIBLE."""
    profs = _shared_school()
    bad = [{
        "group_id": 1, "class_name": "3B", "subject": "Chimica",
        "n_hours": 5,    # > 4 weekly -> infeasible
        "required": True, "weight": 100.0,
        "teachers": ["ProfA", "ProfB"],
    }]
    with pytest.raises(RuntimeError):
        _solve(profs, coteach_groups=bad)
