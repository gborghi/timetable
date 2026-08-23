"""HARD-feasibility context shared by runners and the move gate.

Keeps `is_hard_feasible` aligned with the solver: sostegno, coteach,
parallel groups, class flags, special-room capacity, HARD DSL rules.
"""
from __future__ import annotations

from typing import Any

from .. import engine_io, models
from ..db import SessionLocal


def _load_dsl_hard_expressions(db) -> list[str] | None:
    """Load HARD DSL rule expression STRINGS from the DB.

    Symmetric to the SOFT path (``meta.parse_soft_rules`` on the same
    ``load_all_dsl_constraints`` dump): collects every rule with
    ``is_hard=True`` and returns its raw ``expression`` string. Returns
    ``None`` (not an empty list) when there are no HARD DSL rules, so
    every runner receives the default ``dsl_hard_expressions=None`` and
    behaves byte-identically to the pre-wiring path (zero-drift).

    IMPORTANT: STRINGS, not parsed trees, cross the module boundary.
    ``is_hard_feasible`` re-parses them with metaheuristics' OWN
    ``general_dsl`` import, so there is no dual-module AST hazard (unlike
    the SOFT trees, which must be produced via ``meta.parse_soft_rules``).
    """
    try:
        try:
            from engine import dsl_translator as _dt  # type: ignore
        except ImportError:
            import dsl_translator as _dt  # type: ignore
        _all = _dt.load_all_dsl_constraints(db, _models=models, include_soft=True)
        exprs = [r["expression"] for r in _all
                 if r.get("is_hard") and r.get("expression")]
        return exprs or None
    except Exception:
        return None


def _build_special_room_ctx_safe(db):
    """`cv2.build_special_room_ctx(db)` senza propagare eccezioni.

    Ritorna ``(subj_kind, kind_cap)`` o ``None`` (nessuna aula speciale da
    vincolare / errore di lettura). Usato da `_hard_check_ctx` per dare a
    `is_hard_feasible` la stessa vista di capacita' aule speciali che ha il
    CP-SAT di Phase B (finding 34)."""
    try:
        import cpsat_v2_timetable as cv2  # type: ignore
        return cv2.build_special_room_ctx(db)
    except Exception:
        return None


def _hard_check_ctx(db) -> dict[str, Any]:
    """Le tabelle che `is_hard_feasible` deve vedere per NON sbagliare.

    Senza queste, il controllo class-no-overlap conta come "due lezioni
    nella stessa cella" tre situazioni che sono invece legittime e
    volute:

    - **sostegno**: il docente segue l'alunno dentro la lezione del
      titolare, non aggiunge uno slot alla classe;
    - **compresenza** (`coteach_groups`): titolare + codocente occupano
      lo stesso slot ma la classe e\\` occupata UNA volta sola;
    - **parallel intra-classe**: i membri condividono la stessa
      `busy_key`.

    Il default di `is_hard_feasible` e\\` `None` per tutti e tre, quindi
    un chiamante che li omette dichiara infattibile qualunque orario di
    una scuola che abbia anche solo un docente di sostegno -- e siccome
    lo stesso controllo governa `validate_and_apply_move`, l'effetto e\\`
    che la modifica manuale rifiuta OGNI spostamento. I loader sono
    letture secche su tabelle piccole: si ricaricano ad ogni chiamata
    invece di tenerli in cache, cosi\\` una modifica alle cattedre e\\`
    visibile subito.

    Ritorna un dict di kwargs da espandere con `**`.
    """
    try:
        return {
            "support_assignments": engine_io.support_assignments_from_db(db),
            "coteach_groups": engine_io.coteach_groups_for_solver(db),
            "parallel_groups": engine_io.parallel_groups_for_solver(db),
            "group_assignments": engine_io.group_assignments_for_solver(db),
            # 08b: so is_hard_feasible doesn't flag a class as violating an
            # invariant the school deliberately turned off on its card.
            "class_flags": engine_io.class_flags_from_db(db),
            # finding 34: capacita' aule speciali (palestra/lab). Cosi' una
            # modifica manuale che mette piu' classi in palestra di quante
            # ce ne siano viene rifiutata, coerentemente col CP-SAT e con
            # le metaeuristiche. None quando non c'e' nulla da vincolare.
            "special_room_ctx": _build_special_room_ctx_safe(db),
            # Audit H2: without the DB DSL HARD rules the validator is
            # blind to every GeneralConstraint / LogicalUnavailability /
            # per-cell unavailability (expressed as DSL), so a decomposition
            # or meta run that drops one still reported feasible=True and
            # (audit H1) activated a rule-violating timetable. Feed the same
            # HARD expressions the week gate uses; is_hard_feasible evaluates
            # them post-hoc on the produced solution. None when there are
            # none, keeping the historical fast path.
            "dsl_hard_expressions": _load_dsl_hard_expressions(db),
        }
    except Exception:
        # Meglio il comportamento storico che nessun controllo HARD.
        return {}


def _class_busy_key_fn(ctx: dict[str, Any]):
    """Da `(docente, classe, materia)` alla chiave di occupazione classe.

    Ritorna `None` per le lezioni che NON occupano uno slot della classe
    (il sostegno), e una chiave uguale per le lezioni che occupano lo
    STESSO slato -- compresenza e parallel intra. Due lezioni sono in
    conflitto solo se hanno chiavi diverse ed entrambe non-`None`.

    Replica la logica di `metaheuristics.is_hard_feasible` perche\\` i
    pre-controlli "veloci" di `what_if_move` la anticipano: senza questa
    funzione rifiutavano la mossa PRIMA di arrivare al controllo
    completo, rendendo inutile passargli il contesto.
    """
    support_keys = {(sa.get("teacher_name"), sa.get("class_name"),
                     sa.get("subject"))
                    for sa in (ctx.get("support_assignments") or [])}
    coteach_keys = {(cg.get("class_name"), cg.get("subject"))
                    for cg in (ctx.get("coteach_groups") or [])}
    parallel_key: dict[tuple, str] = {}
    for pg in (ctx.get("parallel_groups") or []):
        cl = pg.get("class_name")
        for m in pg.get("members", []):
            parallel_key[(cl, m.get("subject"))] = (
                f"__par__{pg.get('group_id')}")

    def _key(teacher: str, cl: str, subj: str) -> str | None:
        if (teacher, cl, subj) in support_keys:
            return None
        if (cl, subj) in parallel_key:
            return parallel_key[(cl, subj)]
        if (cl, subj) in coteach_keys:
            return f"__cot__{cl}__{subj}"
        return subj

    return _key


def _hard_check_ctx_fresh() -> dict[str, Any]:
    """`_hard_check_ctx` per i chiamanti che non hanno una sessione aperta."""
    try:
        with SessionLocal() as db:
            return _hard_check_ctx(db)
    except Exception:
        return {}
