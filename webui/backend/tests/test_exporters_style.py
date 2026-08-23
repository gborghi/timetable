"""Subject-coloured xlsx / LaTeX timetable export + A3 global board."""
from __future__ import annotations

import os
import pickle
import shutil
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)


def _mini(tmp_path):
    """Tiny school: 2 teachers, 2 classes, 2 subjects, 3 placed lessons."""
    school = {
        "classes": [
            {"name": "1A", "curriculum": "Liceo"},
            {"name": "1B", "curriculum": "Liceo"},
        ],
        "teachers": [
            {"name": "Rossi", "group": "A027", "max_hours": 18},
            {"name": "Bianchi", "group": "A012", "max_hours": 18},
        ],
    }
    profs = {
        "Rossi": {
            "classi": {"1A": {"Matematica": {"ore": 2}}},
            "glibero": [],
        },
        "Bianchi": {
            "classi": {
                "1A": {"Italiano": {"ore": 1}},
                "1B": {"Italiano": {"ore": 1}},
            },
            "glibero": [],
        },
    }
    sol = {
        ("Rossi", "1A", "Matematica", 1, 8): 1,
        ("Rossi", "1A", "Matematica", 1, 9): 1,
        ("Bianchi", "1A", "Italiano", 2, 8): 1,
        ("Bianchi", "1B", "Italiano", 2, 8): 1,
    }
    school_p = tmp_path / "school.pkl"
    profs_p = tmp_path / "profs.pkl"
    sol_p = tmp_path / "sol.pkl"
    school_p.write_bytes(pickle.dumps(school))
    profs_p.write_bytes(pickle.dumps(profs))
    sol_p.write_bytes(pickle.dumps(sol))
    return str(sol_p), str(school_p), str(profs_p)


def test_subject_style_is_stable_and_palette_aligned():
    import exporters as ex

    a = ex.subject_style("Matematica")
    b = ex.subject_style("Matematica")
    c = ex.subject_style("Italiano")
    assert a == b
    assert a["bg"] != c["bg"]
    assert a["bg"] in {p["bg"] for p in ex.SUBJECT_PALETTE}
    # Same FNV-1a 32-bit as calendar_helpers.mjs hashStr.
    assert ex.hash_str("") == 2166136261
    h = 2166136261
    for ch in "Mat":
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    assert ex.hash_str("Mat") == h
    assert ex.subject_style("Mat") == ex.SUBJECT_PALETTE[h % 10]


def test_xlsx_class_cells_use_subject_fill_and_font(tmp_path):
    import exporters as ex
    from openpyxl import load_workbook

    sol_p, school_p, profs_p = _mini(tmp_path)
    out = tmp_path / "classi.xlsx"
    ex.export_class_schedules_to_xlsx(sol_p, school_p, profs_p, str(out))
    wb = load_workbook(out)
    assert "1A" in wb.sheetnames
    ws = wb["1A"]
    # header row 4, Lun col 2, first hour row 5 -> Rossi / Matematica
    cell = ws.cell(row=5, column=2)
    assert "Matematica" in str(cell.value)
    pal = ex.subject_style("Matematica")
    fill_hex = (cell.fill.start_color.rgb or "")[-6:].upper()
    assert fill_hex == pal["bg"]
    assert cell.font.name == ex.FONT_NAME
    assert int(cell.font.size) == ex.CELL_SIZE
    assert (cell.font.color.rgb or "")[-6:].upper() == pal["fg"]
    # empty slot stays grey (Mar 9: no 1A lesson)
    empty = ws.cell(row=6, column=3)
    assert empty.value == "-"
    assert (empty.fill.start_color.rgb or "")[-6:].upper() == "F2F2F2"
    # title font
    assert int(ws.cell(row=1, column=1).font.size) == ex.TITLE_SIZE
    # round-trip: coloured xlsx still parses
    from backend import engine_io
    parsed = engine_io.solution_dict_from_class_xlsx(str(out))
    assert ("Rossi", "1A", "Matematica", 1, 8) in parsed or any(
        k[0] == "Rossi" and k[2] == "Matematica" for k in parsed
    )


def test_xlsx_teacher_and_global_board(tmp_path):
    import exporters as ex
    from openpyxl import load_workbook

    sol_p, school_p, profs_p = _mini(tmp_path)
    t_out = tmp_path / "docenti.xlsx"
    g_out = tmp_path / "globale.xlsx"
    ex.export_teacher_schedules_to_xlsx(sol_p, school_p, profs_p, str(t_out))
    ex.export_global_teacher_board_to_xlsx(sol_p, school_p, profs_p, str(g_out))

    tw = load_workbook(t_out)
    assert "Rossi" in tw.sheetnames
    rcell = tw["Rossi"].cell(row=6, column=2)  # header_row=5, Lun 8
    assert rcell.value == "1A"
    pal = ex.subject_style("Matematica")
    assert (rcell.fill.start_color.rgb or "")[-6:].upper() == pal["bg"]
    assert rcell.font.name == ex.FONT_NAME

    gw = load_workbook(g_out)
    ws = gw.active
    assert int(ws.page_setup.paperSize) == 8  # openpyxl A3
    assert ws.page_setup.orientation == "landscape"
    # row 5 = first teacher (Bianchi, sorted), col 2 = Lun 8
    # Bianchi has no Monday 8 lesson
    names = [ws.cell(row=r, column=1).value for r in range(5, 8)]
    assert "Rossi" in names
    rossi_row = names.index("Rossi") + 5
    # slots are (day,hour) sorted: (1,8) is first data col
    gcell = ws.cell(row=rossi_row, column=2)
    assert gcell.value == "1A"
    assert (gcell.fill.start_color.rgb or "")[-6:].upper() == pal["bg"]
    assert int(gcell.font.size) == ex.GLOBAL_CELL_SIZE


def test_latex_contains_palette_fonts_and_boards(tmp_path):
    import exporters as ex

    sol_p, school_p, profs_p = _mini(tmp_path)
    tex_p = tmp_path / "orario.tex"
    a3_p = tmp_path / "globale.tex"
    ex.export_schedules_to_latex(sol_p, school_p, profs_p, str(tex_p))
    ex.export_global_teacher_board_to_latex(sol_p, school_p, profs_p, str(a3_p))
    tex = tex_p.read_text(encoding="utf-8")
    a3 = a3_p.read_text(encoding="utf-8")
    assert r"\documentclass" in tex
    assert r"\sffamily" in tex
    assert "subjbg0" in tex and "subjfg0" in tex
    assert "Matematica" in tex
    assert "Italiano" in tex
    assert "Classe 1A" in tex
    assert "Docente: Rossi" in tex
    assert r"\cellcolor" in tex
    assert r"\fontsize" in tex
    assert "a3paper" in a3
    assert "landscape" in a3
    assert "Tabellone globale" in a3
    assert "Rossi" in a3 and "1A" in a3
    # subject colour index is the same helper used by xlsx
    idx = ex._tex_subj_idx("Matematica")
    pal = ex.subject_style("Matematica")
    assert pal == ex.SUBJECT_PALETTE[idx]


@pytest.mark.skipif(not shutil.which("pdflatex"), reason="pdflatex missing")
def test_compile_latex_produces_pdf(tmp_path):
    import exporters as ex

    sol_p, school_p, profs_p = _mini(tmp_path)
    tex_p = tmp_path / "orario.tex"
    ex.export_schedules_to_latex(sol_p, school_p, profs_p, str(tex_p))
    pdf = ex.compile_latex(str(tex_p), timeout_s=60)
    assert pdf is not None
    assert os.path.isfile(pdf)
    assert os.path.getsize(pdf) > 1000


def _seed_export_db(SessionLocal):
    from backend import models

    s = SessionLocal()
    try:
        tea = models.Teacher(name="Rossi", max_hours=18)
        cls = models.SchoolClass(name="1A", n_students=20)
        s.add_all([tea, cls])
        s.flush()
        s.add(models.TeacherSubject(teacher_id=tea.id, subject="Matematica"))
        s.add(models.Assignment(
            class_id=cls.id, teacher_id=tea.id,
            subject="Matematica", hours=2,
        ))
        sol = models.Solution(name="t", kind="manual", is_active=True)
        s.add(sol)
        s.flush()
        s.add(models.Lesson(
            solution_id=sol.id, teacher_name="Rossi",
            class_name="1A", subject="Matematica", day=1, hour=8,
        ))
        s.commit()
    finally:
        s.close()


def test_export_endpoints_xlsx_and_latex(app_with_temp_db):
    from fastapi.testclient import TestClient

    app, SessionLocal = app_with_temp_db
    _seed_export_db(SessionLocal)
    client = TestClient(app)

    r = client.get("/api/schedule/export/xlsx-classes")
    assert r.status_code == 200, r.text
    assert "spreadsheetml" in r.headers["content-type"]
    assert r.content[:2] == b"PK"

    r = client.get("/api/schedule/export/xlsx-global")
    assert r.status_code == 200, r.text
    assert r.content[:2] == b"PK"

    r = client.get("/api/schedule/export/latex")
    assert r.status_code == 200, r.text
    body = r.content.decode("utf-8")
    assert r"\documentclass" in body
    assert "Matematica" in body
    assert "1A" in body

    r = client.get("/api/schedule/export/latex-global")
    assert r.status_code == 200, r.text
    body = r.content.decode("utf-8")
    assert "a3paper" in body
    assert "Rossi" in body
