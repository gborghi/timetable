"""Preset di assegnazione aule: SchoolClass.room_policy +
lo stato a 4 valori di ClassroomClassPreference.

Copre i due livelli su cui la feature vive:
  - `_can_host` in engine/classroom_assignment.py, che e' dove il
    vincolo diventa HARD (test unitari, nessun DB);
  - il percorso reale DB -> engine_io -> CP-SAT, che e' l'unico modo
    di accorgersi se il preset non arriva fino al solver.

Il caso che vale davvero e' la deroga: senza di essa 'fissa' sarebbe
insoddisfacibile in qualunque scuola con una palestra, perche' Scienze
motorie chiederebbe insieme l'aula base e un'aula di tipo palestra.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def _lesson(subject="Italiano", *, cl="1A", required_kind="",
            home_room="", forbidden_rooms=()):
    return {
        "class": cl, "subject": subject, "day": 0, "hour": 0,
        "n_students": 25, "required_kind": required_kind,
        "home_room": home_room, "forbidden_rooms": forbidden_rooms,
    }


@pytest.fixture()
def db_session(app_with_temp_db):
    """Sessione sul DB temporaneo di `app_with_temp_db` (che e' anche
    l'unico posto dove lo schema viene creato per i test)."""
    _app, TestSession = app_with_temp_db
    s = TestSession()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def rooms():
    from classroom_assignment import _normalize_classroom  # type: ignore
    return {
        "base": _normalize_classroom(
            {"name": "Aula 1", "kind": "standard", "capacity": 30}),
        "altra": _normalize_classroom(
            {"name": "Aula 2", "kind": "standard", "capacity": 30}),
        "palestra": _normalize_classroom(
            {"name": "Palestra", "kind": "palestra", "capacity": 60}),
    }


# ---------------- _can_host ----------------


def test_fissa_esclude_le_altre_aule(rooms):
    from classroom_assignment import _can_host  # type: ignore
    L = _lesson(home_room="Aula 1")
    assert _can_host(rooms["base"], L)
    assert not _can_host(rooms["altra"], L)


def test_fissa_deroga_per_le_materie_con_aula_obbligatoria(rooms):
    """Senza questa deroga il preset sarebbe infattibile ovunque ci
    sia una palestra."""
    from classroom_assignment import _can_host  # type: ignore
    L = _lesson("Scienze motorie", required_kind="palestra",
                home_room="Aula 1")
    assert _can_host(rooms["palestra"], L)
    assert not _can_host(rooms["base"], L)


def test_ibrida_non_vincola(rooms):
    from classroom_assignment import _can_host  # type: ignore
    L = _lesson()
    assert _can_host(rooms["base"], L)
    assert _can_host(rooms["altra"], L)


def test_divieto_vince_anche_sulla_materia(rooms):
    """`forbidden` e' assoluto: non deroga nemmeno per required_kind,
    altrimenti un divieto su una palestra sarebbe inesprimibile."""
    from classroom_assignment import _can_host  # type: ignore
    L = _lesson("Scienze motorie", required_kind="palestra",
                forbidden_rooms={"Palestra"})
    assert not _can_host(rooms["palestra"], L)


# ---------------- DB -> engine_io -> CP-SAT ----------------


def _seed(db):
    from backend import models
    db.add_all([
        models.SchoolClass(name="1A", year=1, n_students=25,
                           room_policy="fissa"),
        models.SchoolClass(name="1B", year=1, n_students=25,
                           room_policy="ibrida"),
        models.Subject(name="Italiano"),
        models.Subject(name="Scienze motorie", required_kind="palestra"),
        models.Classroom(name="Aula 1", kind="standard", capacity=30),
        models.Classroom(name="Aula 2", kind="standard", capacity=30),
        models.Classroom(name="Palestra", kind="palestra", capacity=60,
                         multi_class=True, multi_class_max=2),
    ])
    db.commit()
    by_name = {r.name: r for r in db.query(models.Classroom).all()}
    db.add_all([
        models.ClassroomClassPreference(
            classroom_id=by_name["Aula 1"].id, class_name="1A",
            is_home=True, state="preferred"),
        models.ClassroomClassPreference(
            classroom_id=by_name["Aula 2"].id, class_name="1B",
            is_home=True, state="preferred"),
    ])
    sol = models.Solution(name="t", kind="phase_b", is_active=True)
    db.add(sol)
    db.flush()
    for cl in ("1A", "1B"):
        for d in range(2):
            for h in range(3):
                db.add(models.Lesson(
                    solution_id=sol.id, teacher_name="P1", class_name=cl,
                    subject=("Scienze motorie" if h == 2 else "Italiano"),
                    day=d, hour=h))
    db.commit()
    return sol.id


def test_pipeline_aule_rispetta_il_preset(db_session):
    from backend import engine_io
    from classroom_assignment import (  # type: ignore
        solve_classroom_assignment,
    )
    sid = _seed(db_session)
    pins = engine_io.room_pins_from_db(db_session)
    assert pins["pin"] == {"1A": "Aula 1"}
    assert pins["fissa_senza_aula"] == []

    lessons = engine_io.lessons_for_classroom_step(db_session, sid,
                                                   pins=pins)
    rooms_ = engine_io.classrooms_dicts_from_db(db_session)
    mapping, status = solve_classroom_assignment(lessons, rooms_,
                                                 time_limit_s=20)
    assert mapping is not None, status
    for (cl, subj, _d, _h), room in mapping.items():
        if cl != "1A":
            continue
        if subj == "Italiano":
            assert room == "Aula 1"
        else:
            assert room == "Palestra"


def test_fissa_senza_aula_base_degrada_a_ibrida(db_session):
    """Preset senza il dato che gli serve: si segnala e si prosegue,
    non si fa fallire il run."""
    from backend import engine_io, models
    _seed(db_session)
    db_session.query(models.ClassroomClassPreference).filter_by(
        class_name="1A").delete()
    db_session.commit()
    pins = engine_io.room_pins_from_db(db_session)
    assert pins["pin"] == {}
    assert pins["fissa_senza_aula"] == ["1A"]


def test_stato_esplicito_vince_sul_preset(db_session):
    from backend import engine_io, models
    _seed(db_session)
    room2 = db_session.query(models.Classroom).filter_by(
        name="Aula 2").one()
    db_session.add(models.ClassroomClassPreference(
        classroom_id=room2.id, class_name="1A", state="enforced"))
    db_session.commit()
    pins = engine_io.room_pins_from_db(db_session)
    assert pins["pin"]["1A"] == "Aula 2"


def test_divieto_arriva_al_solver(db_session):
    from backend import engine_io, models
    from classroom_assignment import (  # type: ignore
        solve_classroom_assignment,
    )
    sid = _seed(db_session)
    pref = db_session.query(models.ClassroomClassPreference).filter_by(
        class_name="1B").one()
    pref.state = "forbidden"
    db_session.commit()
    pins = engine_io.room_pins_from_db(db_session)
    assert pins["forbidden"] == {"1B": {"Aula 2"}}
    lessons = engine_io.lessons_for_classroom_step(db_session, sid,
                                                   pins=pins)
    rooms_ = engine_io.classrooms_dicts_from_db(db_session)
    mapping, status = solve_classroom_assignment(lessons, rooms_,
                                                 time_limit_s=20)
    assert mapping is not None, status
    assert all(room != "Aula 2"
               for (cl, _s, _d, _h), room in mapping.items()
               if cl == "1B")
    # Una riga 'forbidden' non deve nemmeno contribuire al bonus SOFT.
    aula2 = next(r for r in rooms_ if r["name"] == "Aula 2")
    assert "1B" not in aula2["class_pref_weight"]
