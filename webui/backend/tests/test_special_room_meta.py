"""finding 34 (metaeuristiche): la capacita' delle aule speciali
(palestra/lab) e' un HARD anche nel post-processing.

Il CP-SAT di Phase B rispettava gia' la capienza palestra
(``build_special_room_ctx`` / ``add_special_room_capacity_phase_b``), ma le
metaeuristiche NON avevano alcun controllo: una mossa pura (SA/TS/ILS) o un
repair (LNS/ALNS) potevano spostare una lezione in uno slot dove il kind
era gia' pieno, reintroducendo l'overflow che poi rende INFEASIBLE
l'assegnazione aule. Questi test bloccano quel buco su tutto il ventaglio
di entry point.
"""
import inspect

import pytest

pytestmark = pytest.mark.filterwarnings("ignore")

import metaheuristics as M  # noqa: E402
import alns as _alns  # noqa: E402
import vns as _vns  # noqa: E402
import lagrangian as _lag  # noqa: E402
import cpsat_v2_timetable as cv2  # noqa: E402


# ctx = (subject -> required_kind, kind -> capienza)
_GYM_CTX = ({"Scienzemotorie": "palestra"}, {"palestra": 2})


def _flags_off(*classes):
    """Disattiva ogni invariant per-classe: cosi' solo H_room puo' bocciare."""
    off = {k: False for k in cv2.CLASS_FLAG_KEYS}
    return {c: dict(off) for c in classes}


def test_is_hard_feasible_rejects_gym_overflow():
    profs = {f"P{i}": {"classi": {f"C{i}": {"Scienzemotorie": {"ore": 2}}}}
             for i in range(3)}
    sol = {}
    for i in range(3):
        sol[(f"P{i}", f"C{i}", "Scienzemotorie", 1, 8)] = 1
        sol[(f"P{i}", f"C{i}", "Scienzemotorie", 1, 9)] = 1
    cf = _flags_off("C0", "C1", "C2")
    # 3 classi in palestra, 2 palestre -> infeasible
    assert not M.is_hard_feasible(sol, profs, class_flags=cf,
                                  special_room_ctx=_GYM_CTX)
    # stessa soluzione, 3 palestre -> feasible
    assert M.is_hard_feasible(
        sol, profs, class_flags=cf,
        special_room_ctx=({"Scienzemotorie": "palestra"}, {"palestra": 3}))
    # nessun ctx -> backward-compat (H_room non valutato)
    assert M.is_hard_feasible(sol, profs, class_flags=cf)


def test_coteach_same_class_counts_once():
    """Compresenza/sostegno nella STESSA classe occupano la palestra una
    volta sola: due docenti sulla stessa (classe, slot) non sono overflow."""
    profs = {
        "Tit": {"classi": {"C0": {"Scienzemotorie": {"ore": 1}}}},
        "Cod": {"classi": {"C0": {"Scienzemotorie": {"ore": 1}}}},
        "P1": {"classi": {"C1": {"Scienzemotorie": {"ore": 1}}}},
    }
    sol = {
        ("Tit", "C0", "Scienzemotorie", 1, 8): 1,
        ("Cod", "C0", "Scienzemotorie", 1, 8): 1,   # stessa classe C0
        ("P1", "C1", "Scienzemotorie", 1, 8): 1,
    }
    cf = _flags_off("C0", "C1")
    # 2 CLASSI distinte (C0, C1) in palestra, cap 2 -> feasible
    assert M.is_hard_feasible(sol, profs, class_flags=cf,
                              special_room_ctx=_GYM_CTX)


def test_same_class_swap_blocked_only_with_ctx():
    """Uno swap same-class che porterebbe una 3a classe in palestra piena
    viene rifiutato SSE si passa special_room_ctx; senza, passa."""
    import random
    profs = {
        "P0": {"classi": {"C0": {"Scienzemotorie": {"ore": 1}}}},
        "P1": {"classi": {"C1": {"Scienzemotorie": {"ore": 1}}}},
        "P2": {"classi": {"C2": {"Scienzemotorie": {"ore": 1},
                                 "Matematica": {"ore": 1}}}},
    }
    base = {
        ("P0", "C0", "Scienzemotorie", 1, 8): 1,   # palestra h8 (1/2)
        ("P1", "C1", "Scienzemotorie", 1, 8): 1,   # palestra h8 (2/2 pieno)
        ("P2", "C2", "Matematica", 1, 8): 1,       # C2 in aula normale h8
        ("P2", "C2", "Scienzemotorie", 1, 10): 1,  # C2 in palestra h10
    }
    cf = _flags_off("C0", "C1", "C2")

    def gym_at(sol, d, h):
        return sum(1 for (p, cl, s, dd, hh), v in sol.items()
                   if v and s == "Scienzemotorie" and dd == d and hh == h)

    # SENZA ctx: prima o poi lo swap C2 (Mat h8 <-> Motorie h10) passa e
    # crea 3 classi in palestra h8.
    saw_overflow = False
    for seed in range(40):
        out = M._swap_two_lessons_same_class(
            base, profs, {}, random.Random(seed), class_flags=cf)
        if out is not None and gym_at(out, 1, 8) == 3:
            saw_overflow = True
            break
    assert saw_overflow, "lo swap DEVE poter creare overflow senza il ctx"

    # CON ctx: nessun risultato accettato ha overflow palestra.
    for seed in range(40):
        out = M._swap_two_lessons_same_class(
            base, profs, {}, random.Random(seed),
            class_flags=cf, special_room_ctx=_GYM_CTX)
        if out is not None:
            assert gym_at(out, 1, 8) <= 2


def test_all_entrypoints_accept_special_room_ctx():
    """Ogni entry point delle metaeuristiche + ogni mossa/repair accetta
    special_room_ctx, cosi' `run_meta` puo' passarlo via **c3_kwargs senza
    TypeError."""
    fns = [
        M.run_lns, M.run_sa, M.run_tabu, M.run_ils, M._cp_repair, M._perturb,
        M.is_hard_feasible, M._swap_two_lessons_same_prof,
        M._move_lesson_to_empty_slot, M._swap_two_lessons_same_class,
        _alns.run_alns, _vns.run_vns, _lag.run_lagrangian,
    ]
    missing = [f"{f.__module__}.{f.__name__}" for f in fns
               if "special_room_ctx" not in inspect.signature(f).parameters]
    assert not missing, f"manca special_room_ctx in: {missing}"
