"""Decomposizione temporale (per giorno).

Idea
----
Invece di scomporre il problema sulle entita' (classi o docenti),
lo si scompone sull'asse del tempo. Ciascuno dei sei giorni della
settimana diventa un sotto-problema separato, eseguibile in
parallelo. Una fase di pre-distribuzione (Phase B-pre) decide
quante ore di ciascuna cattedra vanno in ciascun giorno,
rispettando i vincoli settimanali (es. doppia ora di matematica,
motorie a coppie, max ore per la classe per giorno). Poi la fase
per giorno (Phase B-day) piazza materialmente le ore nei sei
slot del giorno.

Vantaggi
--------
- Ortogonale rispetto alla decomposizione spettrale: e' sempre
  applicabile, anche su grafi densi dove la spettrale fallisce.
- Parallelizza naturalmente su sei core (uno per giorno).
- I vincoli "intra-giornalieri" (no buchi, ingresso 8, uscita
  >= 12, motorie consecutive) sono interamente locali al
  sotto-problema giornaliero.

Limiti
------
- I vincoli "inter-giornalieri" (es. distribuzione settimanale
  di una materia, doppia mate in giorni diversi) richiedono il
  master di pre-distribuzione, che a sua volta deve essere
  risolto come piccolo CP-SAT.
- Se il master sbaglia la pre-distribuzione, alcuni giorni
  diventano infeasibili e occorre iterare.

API
---
Il modulo espone:

    pre_distribute_hours(profs, dc_value, days, max_hours_per_day)
        -> dict (event, day) -> hours_assigned

    solve_day(day, profs, hours_assigned_for_day, time_limit)
        -> day_solution dict (slot -> lesson)

    feedback_to_master(day_solutions, infeasible_days)
        -> nuova pre_distribution suggerita
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable


DAYS = ("lun", "mar", "mer", "gio", "ven", "sab")


def pre_distribute_hours(
    profs: dict,
    dc_value: dict,
    days: Iterable[str] = DAYS,
    max_hours_per_day_per_class: int = 6,
    max_hours_per_day_per_teacher: int = 6,
):
    """Master CP-SAT che distribuisce le ore-cattedra fra i giorni.

    Per ogni evento (classe, materia, docente) decide quante ore
    vanno in ciascun giorno, in modo da:

    - Coprire integralmente l'ore_attese di ciascun evento.
    - Rispettare il tetto di ore/giorno per ogni classe.
    - Rispettare il tetto di ore/giorno per ogni docente.
    - (Opzionale) tendere all'equilibrio fra giorni per stessa
      classe e stessa materia (SOFT).

    Parameters
    ----------
    profs : dict
        Output di Phase A (mappa nome_docente -> info).
    dc_value : dict
        Mappa (classe, materia) -> ore_attese settimanali.
    days : iterable of str
        Giorni da considerare (default sei giorni feriali).
    max_hours_per_day_per_class : int
        Tetto HARD di ore per classe per giorno.
    max_hours_per_day_per_teacher : int
        Tetto HARD di ore per docente per giorno.

    Returns
    -------
    dict
        Mappa (event_key, day) -> hours_assigned (int).
        event_key e' la tupla (docente, classe, materia).

    Notes
    -----
    L'implementazione del master CP-SAT e' identica nello
    schema a quella usata in `cpsat_v2_assignment` per la
    distribuzione classe/giorno, ma con la dimensione "giorno"
    al posto di "classe". Vedi roadmap.
    """
    raise NotImplementedError(
        "Master CP-SAT pre-distribuzione: stessa struttura di "
        "cpsat_v2_assignment._add_uniform_class_day_constraints "
        "ma con asse 'giorno' come variabile da bilanciare. "
        "Implementazione in roadmap."
    )


def solve_day(
    day: str,
    profs: dict,
    hours_assigned_for_day: dict,
    *,
    time_limit: float = 30.0,
):
    """Risolve il sotto-problema di un singolo giorno.

    Riusa interamente la logica di `cpsat_v2_timetable` per la
    fase B (no buchi, ingresso 8, uscita >= 12, motorie
    consecutive nello stesso giorno, ecc.) ma applicandola a un
    solo giorno della settimana, con le ore gia' pre-assegnate
    dalla pre-distribuzione.

    Returns
    -------
    dict
        slot (1..6) -> list di (classe, materia, docente).
    """
    raise NotImplementedError(
        "Wiring con cpsat_v2_timetable.solve_b_for_day(): vedi "
        "roadmap in docs/optimization_strategies.md, sezione "
        "'Decomposizione temporale'."
    )


def feedback_to_master(
    day_solutions: dict[str, dict],
    infeasible_days: list[str],
) -> dict:
    """Restituisce una nuova pre-distribuzione che muove ore via
    dai giorni infeasibili verso quelli con margine.

    Si applica quando uno o piu' giorni della prima iterazione
    risultano infeasibili. La logica greedy e': trova le coppie
    (event, day) tali che il day e' infeasibile, e prova a
    spostarle verso un day con margine >= 1 ora.

    Returns
    -------
    dict
        Stesso formato di pre_distribute_hours, con ore migrate.
    """
    raise NotImplementedError(
        "Feedback loop master/slave: vedi roadmap. La logica "
        "greedy e' descritta nel docstring sopra; manca solo il "
        "wiring."
    )


def run_temporal_pipeline(profs, dc_value, *, time_pre=30.0, time_day=30.0,
                          max_iterations=3, parallel_workers=6):
    """Pipeline end-to-end della decomposizione temporale.

    Coordina pre_distribute_hours -> 6 solve_day in parallelo ->
    eventuale feedback_to_master e re-iterazione, fino a
    soluzione completa o esaurimento delle iterazioni.
    """
    raise NotImplementedError("Pipeline coordinator: vedi roadmap.")
