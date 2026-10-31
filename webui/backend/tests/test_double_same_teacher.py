"""H_A del validatore (regola di Giovanni, 31/10): la doppia di Mat/Ita
basta che sia con lo stesso docente, non serve la stessa materia."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
for p in (os.path.join(REPO_ROOT, "webui"), os.path.join(REPO_ROOT, "engine"),
          REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import metaheuristics as meta  # noqa: E402

P = {"I": {"classi": {"1A": {"Italiano": {"ore": 2}, "Storia": {"ore": 2}}}}}
CF = {"1A": {"dual_math": False, "motorie_pairs": False,
             "exit_after_12": False, "entry_at_8": False}}


def _sol(lessons):
    return {("I", "1A", s, d, h): 1 for s, d, h in lessons}


def _ok(lessons):
    return meta.is_hard_feasible(_sol(lessons), P, verbose=True,
                                 class_flags=CF)


def test_italiano_storia_consecutive_is_valid_double():
    d0, d1, d2 = meta.DAYS[:3]
    h = meta.HOURS
    assert _ok([("Italiano", d0, h[0]), ("Storia", d0, h[1]),
                ("Italiano", d1, h[0]), ("Storia", d2, h[0])])


def test_no_consecutive_hours_of_teacher_is_invalid():
    d0, d1, d2, d3 = meta.DAYS[:4]
    h = meta.HOURS
    assert not _ok([("Italiano", d0, h[0]), ("Storia", d1, h[0]),
                    ("Italiano", d2, h[0]), ("Storia", d3, h[0])])
