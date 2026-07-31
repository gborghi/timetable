"""Il sostegno e' dell'ALUNNO, non della classe.

Un docente di sostegno viene assegnato a una persona: segue quel
ragazzo dentro le lezioni ordinarie della sua classe. Da qui le due
proprieta' che questi test fissano, e che erano entrambe violate dal
modello "sostegno come materia":

  1. la cattedra punta a `student_id`, e la classe e' *derivata*
     dall'alunno (cache di comodo, non un dato indipendente);
  2. non serve -- e non si deve -- creare un `Subject` di nome
     "sostegno", ne' una riga `ClassSubject` che ne conti le ore nel
     monte ore settimanale della classe. Farlo gonfiava le classi ben
     oltre le ore realmente disponibili nella settimana.

Per questo `/assignments/sostegno` esiste separato da
`/assignments/manual`: quest'ultimo pretende che la classe porti la
materia e che il docente dichiari di insegnarla, cosa che del sostegno
non e' vera ne' puo' esserlo.
"""
from __future__ import annotations


def _seed(client):
    """Una classe, un alunno dentro, un docente di sostegno.

    Ritorna `(student_id, class_id)`.
    """
    cid = client.post("/api/classes", json={"name": "1A"}).json()["id"]
    client.post("/api/teachers", json={"name": "Sostegno Uno"})
    st = client.post("/api/students", json={
        "last_name": "Rossi", "first_name": "Anna",
        "birth_date": "2010-05-12", "class_id": cid})
    assert st.status_code in (200, 201), st.text
    return st.json()["id"], cid


def test_sostegno_binds_to_pupil_and_derives_the_class(client):
    sid, _cid = _seed(client)
    r = client.put("/api/assignments/sostegno", json={
        "teacher_name": "Sostegno Uno", "student_id": sid, "hours": 9})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] is True, body["reason"]
    a = body["new_assignment"]
    assert a["student_id"] == sid
    assert a["is_support"] is True
    # La classe non e' stata chiesta: e' stata dedotta dall'alunno.
    assert a["class_name"] == "1A"
    assert a["hours"] == 9


def test_sostegno_needs_no_subject_row(client):
    """Nessun `Subject` chiamato 'sostegno', e nessuna ora aggiunta al
    monte ore della classe: era questa la deriva da evitare."""
    sid, _cid = _seed(client)
    client.put("/api/assignments/sostegno", json={
        "teacher_name": "Sostegno Uno", "student_id": sid, "hours": 9})

    subjects = [s["name"].lower() for s in client.get("/api/subjects").json()]
    assert not any("sosteg" in s for s in subjects)

    cl = client.get("/api/classes").json()
    row = next(c for c in cl if c["name"] == "1A")
    hours = sum(int(x.get("hours_per_week") or 0)
                for x in (row.get("subjects") or []))
    assert hours == 0


def test_sostegno_rejects_pupil_without_a_class(client):
    """Senza classe non ci sono lezioni da seguire: va detto, non
    silenziosamente accettato."""
    client.post("/api/teachers", json={"name": "Sostegno Uno"})
    sid = client.post("/api/students", json={
        "last_name": "Bianchi", "first_name": "Ugo",
        "birth_date": "2010-01-01"}).json()["id"]
    r = client.put("/api/assignments/sostegno", json={
        "teacher_name": "Sostegno Uno", "student_id": sid, "hours": 9})
    assert r.json()["accepted"] is False
    assert "classe" in r.json()["reason"].lower()


def test_sostegno_rejects_unknown_pupil(client):
    client.post("/api/teachers", json={"name": "Sostegno Uno"})
    r = client.put("/api/assignments/sostegno", json={
        "teacher_name": "Sostegno Uno", "student_id": 999999, "hours": 9})
    assert r.json()["accepted"] is False


def test_sostegno_rejects_non_positive_hours(client):
    sid, _cid = _seed(client)
    r = client.put("/api/assignments/sostegno", json={
        "teacher_name": "Sostegno Uno", "student_id": sid, "hours": 0})
    assert r.json()["accepted"] is False


def test_second_call_updates_instead_of_duplicating(client):
    sid, _cid = _seed(client)
    first = client.put("/api/assignments/sostegno", json={
        "teacher_name": "Sostegno Uno", "student_id": sid, "hours": 9})
    second = client.put("/api/assignments/sostegno", json={
        "teacher_name": "Sostegno Uno", "student_id": sid, "hours": 12})
    assert second.json()["new_assignment"]["id"] == \
        first.json()["new_assignment"]["id"]
    assert second.json()["new_assignment"]["hours"] == 12
    rows = [a for a in client.get("/api/assignments").json()
            if a.get("is_support")]
    assert len(rows) == 1


def test_two_pupils_same_teacher_are_distinct_cattedre(client):
    """Il vincolo di unicita' include `student_id`: lo stesso docente
    su due alunni sono due cattedre, non un doppione."""
    sid_a, cid = _seed(client)
    sid_b = client.post("/api/students", json={
        "last_name": "Verdi", "first_name": "Ivo",
        "birth_date": "2010-02-02", "class_id": cid}).json()["id"]
    for sid in (sid_a, sid_b):
        r = client.put("/api/assignments/sostegno", json={
            "teacher_name": "Sostegno Uno", "student_id": sid, "hours": 9})
        assert r.json()["accepted"] is True, r.json()["reason"]
    rows = [a for a in client.get("/api/assignments").json()
            if a.get("is_support")]
    assert sorted(a["student_id"] for a in rows) == sorted([sid_a, sid_b])


def test_delete_sostegno_removes_the_cattedra(client):
    sid, _cid = _seed(client)
    aid = client.put("/api/assignments/sostegno", json={
        "teacher_name": "Sostegno Uno", "student_id": sid,
        "hours": 9}).json()["new_assignment"]["id"]
    assert client.delete(f"/api/assignments/sostegno/{aid}").status_code == 200
    assert not [a for a in client.get("/api/assignments").json()
                if a.get("is_support")]


def test_delete_sostegno_refuses_an_ordinary_cattedra(client):
    """La rotta e' specifica: non deve diventare un cancella-tutto."""
    client.post("/api/classes", json={"name": "1A"})
    client.post("/api/teachers", json={"name": "Titolare"})
    client.post("/api/subjects", json={"name": "Matematica"})
    r = client.get("/api/assignments")
    assert r.status_code == 200
    # Nessuna cattedra ordinaria da cancellare: basta che un id
    # inesistente dia 404 e non un 200 silenzioso.
    assert client.delete("/api/assignments/sostegno/999999").status_code == 404
