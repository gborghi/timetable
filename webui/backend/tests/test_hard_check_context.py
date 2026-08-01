"""Il contesto che `is_hard_feasible` deve ricevere per non mentire.

`metaheuristics.is_hard_feasible` accetta `support_assignments`,
`coteach_groups` e `parallel_groups` come keyword OPZIONALI con default
`None`. Ometterli non degrada il controllo: lo rende sbagliato. Il
sostegno e la compresenza stanno nella stessa cella della lezione del
titolare per definizione, quindi senza contesto il controllo
class-no-overlap li legge come doppia occupazione e dichiara infattibile
qualunque orario di una scuola che abbia anche un solo docente di
sostegno.

Non e' un dettaglio di reporting: lo stesso gate governa
`validate_and_apply_move`, per cui l'effetto pratico era che la modifica
manuale rifiutava OGNI spostamento in tutta la scuola.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def _profs_two_teachers():
    """Titolare + sostegno sulla stessa classe.

    Nessuna materia e' Matematica o Italiano: H_A pretende una doppia
    consecutiva settimanale per quelle due e qui interessa isolare il
    solo class-no-overlap. Le quattro ore consecutive da 8 servono
    invece per H1/H2/H3, che pretendono una giornata di classe compatta,
    che inizi alla prima ora e arrivi almeno alla quarta.
    """
    return {
        "Titolare": {"classi": {"1A": {"Storia": {"ore": 4}}},
                     "glibero": None},
        "Sostegno": {"classi": {"1A": {"Sostegno": {"ore": 4}}},
                     "glibero": None},
    }


def _sol_same_cell():
    """Il sostegno affianca il titolare, ora per ora, nella stessa cella."""
    sol = {}
    for h in (8, 9, 10, 11):
        sol[("Titolare", "1A", "Storia", 1, h)] = 1
        sol[("Sostegno", "1A", "Sostegno", 1, h)] = 1
    return sol


def test_support_without_context_reads_as_class_overlap():
    """Il comportamento sbagliato, fissato qui perche' e' la ragione
    d'essere di `_hard_check_ctx`: se un giorno questo test iniziasse a
    passare senza contesto, l'helper sarebbe diventato superfluo."""
    import metaheuristics as meta

    assert meta.is_hard_feasible(
        _sol_same_cell(), _profs_two_teachers(), verbose=False) is False


def test_support_with_context_is_feasible():
    import metaheuristics as meta

    assert meta.is_hard_feasible(
        _sol_same_cell(), _profs_two_teachers(), verbose=False,
        support_assignments=[{"teacher_name": "Sostegno",
                              "class_name": "1A",
                              "subject": "Sostegno"}]) is True


def test_hard_check_ctx_supplies_all_keys(app_with_temp_db):
    """Tutte le chiavi devono esserci: le quattro tabelle "legittimo
    doppio slot" (sostegno/compresenza/parallel/gruppi) + `class_flags`
    (08b: gli invariant per-classe che la card puo' rilassare) +
    `special_room_ctx` (finding 34: capienza palestra/lab). Ometterne
    una sposta quale situazione legittima viene letta come conflitto o
    disattiva un HARD."""
    from backend import optimization as opt

    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        ctx = opt._hard_check_ctx(db)
    assert set(ctx) == {"support_assignments", "coteach_groups",
                        "parallel_groups", "group_assignments",
                        "class_flags", "special_room_ctx"}


# ----------------------------------------------------------------------
# _class_busy_key_fn: i pre-controlli "veloci" di preview_moves_for_lesson
# ----------------------------------------------------------------------

def test_busy_key_none_for_support():
    """`None` = non occupa uno slot della classe."""
    from backend.optimization import _class_busy_key_fn

    key = _class_busy_key_fn({"support_assignments": [
        {"teacher_name": "S", "class_name": "1A", "subject": "Sostegno"}]})
    assert key("S", "1A", "Sostegno") is None
    # Stesso nome di materia ma altro docente: non e' quel sostegno.
    assert key("X", "1A", "Sostegno") == "Sostegno"


def test_busy_key_shared_by_coteach_pair():
    from backend.optimization import _class_busy_key_fn

    key = _class_busy_key_fn({"coteach_groups": [
        {"class_name": "1A", "subject": "Inglese"}]})
    assert key("Titolare", "1A", "Inglese") == key("Madrelingua", "1A",
                                                   "Inglese")


def test_busy_key_shared_by_parallel_members():
    from backend.optimization import _class_busy_key_fn

    key = _class_busy_key_fn({"parallel_groups": [
        {"class_name": "1A", "group_id": 7,
         "members": [{"subject": "Religione"},
                     {"subject": "Attivita alternativa"}]}]})
    assert key("A", "1A", "Religione") == key("B", "1A",
                                              "Attivita alternativa")


def test_busy_key_distinct_for_unrelated_subjects():
    from backend.optimization import _class_busy_key_fn

    key = _class_busy_key_fn({})
    assert key("A", "1A", "Storia") != key("B", "1A", "Fisica")
