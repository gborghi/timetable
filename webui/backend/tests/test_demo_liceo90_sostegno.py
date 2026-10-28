"""Dati demo liceo90: il file del sostegno e' neutro e coerente.

Revisione didattica 28/10/2026 (Socrate, punto 3): niente nomi
stigmatizzanti ne' diagnosi (dato sanitario, GDPR art. 9), codice S00x,
e class_name / sostegno / ore_sostegno compilati, cosi' l'import crea
davvero le cattedre di sostegno.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from backend import models

FILES = Path(__file__).resolve().parents[2] / "data" / "vicepreside_liceo90" / "files"
ORDER = [("subjects", "01_materie"), ("teachers", "02_docenti"),
         ("classes", "03_classi"), ("students", "05_studenti_sostegno")]


def test_file_sostegno_neutro():
    import openpyxl
    ws = openpyxl.load_workbook(FILES / "05_studenti_sostegno.xlsx")["Dati"]
    rows = list(ws.iter_rows(values_only=True))
    hdr, body = rows[0], rows[1:]
    assert len(body) == 9
    for i, r in enumerate(body, 1):
        d = dict(zip(hdr, r))
        assert d["last_name"] == f"Studente S{i:02d}" and d["first_name"] == "Demo"
        assert d["student_code"] == f"S{i:03d}"
        assert not d["notes"] and not d["tags"]
        assert d["class_name"] and d["sostegno"] and int(d["ore_sostegno"]) > 0
    text = " ".join(str(c) for r in rows for c in r if c)
    for bad in ("Diversamente", "AlunnoH", "104", "BES", "disabilit"):
        assert bad not in text


def test_import_crea_le_cattedre_di_sostegno(app_with_temp_db):
    app, Session = app_with_temp_db
    client = TestClient(app)
    for entity, fname in ORDER:
        with open(FILES / f"{fname}.xlsx", "rb") as fh:
            r = client.post(f"/api/import/{entity}",
                            files={"file": (f"{fname}.xlsx", fh)},
                            data={"mode": "upsert"})
        assert r.status_code == 200, r.text
        assert not r.json()["errors"], (entity, r.json()["errors"][:3])
    with Session() as db:
        sup = db.query(models.Assignment).filter(
            models.Assignment.is_support == True).all()  # noqa: E712
        assert len(sup) == 9
        assert all(a.class_id and a.student_id and a.hours for a in sup)
        assert db.query(models.Subject).filter_by(
            name="Scienzemotorie").one().pretty_name == "Scienze motorie e sportive"
