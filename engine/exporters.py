r"""Modulo riusabile di export dell'orario settimanale (Excel + LaTeX).

API
===

    export_class_schedules_to_xlsx(...)
    export_teacher_schedules_to_xlsx(...)
    export_global_teacher_board_to_xlsx(...)
    export_schedules_to_latex(...)
    compile_latex(tex_path) -> pdf_path | None

Gli xlsx e il .tex condividono la stessa palette per materia (allineata
al calendario web), lo stesso font e le stesse dimensioni carattere.

Entrambe le famiglie xlsx/latex leggono:
- `solution_pickle_path`: dict[(prof, classe, materia, day, hour) -> 0/1]
- `school_pickle_path`  : dict prodotto da `big_mock_school.py`
                          (campi: classes, teachers, ...). Usato per
                          arricchire gli header (curriculum della classe,
                          classe-di-concorso del docente, max_hours).
- `profs_pickle_path`   : dict prof -> {classi: {cl: {subj: {ore}}},
                          glibero: [d1,d2,d3]}.

Producono un singolo file in `output_path`. Non rilanciano alcun
solver: sono solo trasformazione di dati.

Edge case gestiti:
- nomi tab Excel > 31 char: troncati a 28 + "..."; collisioni di nome
  dopo troncamento: suffisso numerico "~1", "~2", ... mantenendo la
  lunghezza max 31.
- caratteri Excel proibiti `[]:*?/\' sostituiti con "-".
- docente con piu' materie nella stessa classe: nel tab del docente
  la cella mostra "<classe>\n(<materia>)" se ambiguo.
- docente con piu' materie totali: header "Materie:" elenca tutte.
- compresenza nello stesso slot (non dovrebbe mai accadere visto il
  vincolo hard no-overlap, ma e' difensivo): cella prefissata
  "*CONFLICT*" e l'evento viene loggato (numero totale a fine).

Utilizzabili anche da CLI -- vedi il blocco `if __name__ ...` in fondo.
"""
from __future__ import annotations

import os
import pickle
import re
import shutil
import subprocess

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins


# --------------------------- costanti di stile ---------------------------

DAY_NAMES: dict[int, str] = {
    1: "Lun", 2: "Mar", 3: "Mer", 4: "Gio", 5: "Ven", 6: "Sab",
}


def _day_label(d: int) -> str:
    """Configured calendar label, falling back to the lun–sab preset."""
    try:
        import working_hours_config as _whc  # type: ignore
        label = _whc.get_day_label(int(d), default="")
        if label:
            return label
    except Exception:
        pass
    return DAY_NAMES.get(d, str(d))
EMPTY_PLACEHOLDER = "-"

# Calibri is the Excel default and prints cleanly; sizes are shared
# with the LaTeX generator so a paper copy of either format matches.
FONT_NAME = "Calibri"
TITLE_SIZE = 16
SUBTITLE_SIZE = 10
HEADER_SIZE = 10
CELL_SIZE = 9
GLOBAL_CELL_SIZE = 8
LEGEND_SIZE = 8

# Same 10 hues as webui/frontend/src/lib/calendar_helpers.mjs PALETTE
# (hex without '#'). Colour is keyed on the subject name so a materia
# keeps one tint across class tabs, teacher tabs, the global board
# and the LaTeX boards.
SUBJECT_PALETTE: list[dict[str, str]] = [
    {"bg": "DBEAFE", "bd": "2563EB", "fg": "1E3A8A"},  # blue
    {"bg": "DCFCE7", "bd": "16A34A", "fg": "14532D"},  # green
    {"bg": "FEE2E2", "bd": "DC2626", "fg": "7F1D1D"},  # red
    {"bg": "FEF3C7", "bd": "D97706", "fg": "78350F"},  # amber
    {"bg": "F3E8FF", "bd": "9333EA", "fg": "581C87"},  # violet
    {"bg": "CCFBF1", "bd": "0D9488", "fg": "134E4A"},  # teal
    {"bg": "FFE4E6", "bd": "E11D48", "fg": "881337"},  # rose
    {"bg": "E0E7FF", "bd": "4F46E5", "fg": "3730A3"},  # indigo
    {"bg": "FEF9C3", "bd": "CA8A04", "fg": "713F12"},  # yellow
    {"bg": "CFFAFE", "bd": "0891B2", "fg": "155E75"},  # cyan
]


def hash_str(s: str) -> int:
    """FNV-1a 32-bit, same as calendar_helpers.mjs hashStr."""
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def subject_style(subject: str) -> dict[str, str]:
    """Deterministic {bg, bd, fg} for a subject name."""
    key = (subject or "").strip()
    if not key:
        return SUBJECT_PALETTE[0]
    return SUBJECT_PALETTE[hash_str(key) % len(SUBJECT_PALETTE)]


_HEADER_FILL = PatternFill(
    start_color="4472C4", end_color="4472C4", fill_type="solid"
)
_HEADER_FONT = Font(
    name=FONT_NAME, bold=True, color="FFFFFF", size=HEADER_SIZE,
)
_TITLE_FONT = Font(
    name=FONT_NAME, bold=True, size=TITLE_SIZE, color="1E3A8A",
)
_SUBTITLE_FONT = Font(
    name=FONT_NAME, italic=True, color="555555", size=SUBTITLE_SIZE,
)
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
_LEFT = Alignment(horizontal="left", vertical="center")
_THIN = Side(border_style="thin", color="999999")
_CELL_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_EMPTY_FILL = PatternFill(
    start_color="F2F2F2", end_color="F2F2F2", fill_type="solid"
)
_CONFLICT_FILL = PatternFill(
    start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"
)
_CELL_FONT = Font(name=FONT_NAME, size=CELL_SIZE)
_EMPTY_FONT = Font(name=FONT_NAME, size=CELL_SIZE, color="888888")
_CONFLICT_FONT = Font(
    name=FONT_NAME, bold=True, color="9C0006", size=CELL_SIZE,
)
_LEGEND_FONT = Font(name=FONT_NAME, size=LEGEND_SIZE)

_FORBIDDEN_TAB_CHARS = re.compile(r"[\[\]:\*\?/\\]")


# --------------------------- helpers ---------------------------

def _safe_sheet_name(name: str, used: set[str]) -> str:
    """Ritorna un nome di tab Excel valido (<=31 char, no chars vietati)
    e non duplicato."""
    cleaned = _FORBIDDEN_TAB_CHARS.sub("-", name).strip() or "Sheet"
    if len(cleaned) > 31:
        base = cleaned[:28] + "..."
    else:
        base = cleaned
    candidate = base
    i = 1
    while candidate in used:
        suffix = f"~{i}"
        keep = 31 - len(suffix)
        candidate = (base[:keep] if len(base) > keep else base) + suffix
        i += 1
    used.add(candidate)
    return candidate


def _load_pickles(solution_path, school_path, profs_path):
    with open(solution_path, "rb") as f:
        sol = pickle.load(f)
    with open(school_path, "rb") as f:
        school = pickle.load(f)
    with open(profs_path, "rb") as f:
        profs = pickle.load(f)
    return sol, school, profs


def _classes_index(school) -> dict[str, dict]:
    """Indice nome_classe -> dict del classroom dump."""
    return {c["name"]: c for c in school.get("classes", [])}


def _teachers_index(school) -> dict[str, dict]:
    """Indice nome_docente -> dict del teacher dump (group, max_hours...)."""
    return {t["name"]: t for t in school.get("teachers", [])}


def _days_hours(sol) -> tuple[list[int], list[int]]:
    days = sorted({k[3] for k in sol})
    hours = sorted({k[4] for k in sol})
    return days, hours


def _write_grid_header(ws, days, header_row: int):
    cell = ws.cell(row=header_row, column=1, value="Ora")
    cell.fill = _HEADER_FILL
    cell.font = _HEADER_FONT
    cell.alignment = _CENTER
    cell.border = _CELL_BORDER
    for i, d in enumerate(days):
        c = ws.cell(row=header_row, column=2 + i,
                    value=_day_label(d))
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
        c.alignment = _CENTER
        c.border = _CELL_BORDER


def _write_hour_column(ws, hours, start_row: int):
    for i, h in enumerate(hours):
        ord_label = f"{i + 1}^a ({h:02d}:00)"
        c = ws.cell(row=start_row + i, column=1, value=ord_label)
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
        c.alignment = _CENTER
        c.border = _CELL_BORDER


def _fill_cell(ws, row, col, text: str, conflict: bool = False,
               subject: str | None = None, *, font_size: int | None = None):
    c = ws.cell(row=row, column=col, value=text)
    c.alignment = _CENTER
    c.border = _CELL_BORDER
    size = font_size if font_size is not None else CELL_SIZE
    if conflict:
        c.fill = _CONFLICT_FILL
        c.font = Font(
            name=FONT_NAME, bold=True, color="9C0006", size=size,
        )
    elif text == EMPTY_PLACEHOLDER or not text:
        c.fill = _EMPTY_FILL
        c.font = Font(name=FONT_NAME, size=size, color="888888")
    else:
        pal = subject_style(subject or "")
        c.fill = PatternFill(
            start_color=pal["bg"], end_color=pal["bg"], fill_type="solid",
        )
        c.font = Font(name=FONT_NAME, size=size, color=pal["fg"], bold=True)


def _autosize(ws, days, *, header_row: int, hour_row_count: int,
              col_a_width: float = 14, col_other_width: float = 26,
              header_h: float = 26, body_h: float = 36):
    ws.column_dimensions["A"].width = col_a_width
    for i in range(len(days)):
        ws.column_dimensions[get_column_letter(2 + i)].width = col_other_width
    for r in range(1, header_row + 1):
        ws.row_dimensions[r].height = header_h
    for r in range(header_row + 1, header_row + 1 + hour_row_count):
        ws.row_dimensions[r].height = body_h


def _write_subject_legend(ws, subjects, *, start_row: int, start_col: int = 1):
    """One small coloured swatch + name per subject, starting at start_row."""
    if not subjects:
        return start_row
    label = ws.cell(row=start_row, column=start_col, value="Legenda materie")
    label.font = Font(
        name=FONT_NAME, italic=True, size=LEGEND_SIZE, color="555555",
    )
    row = start_row + 1
    col = start_col
    for i, subj in enumerate(subjects):
        pal = subject_style(subj)
        c = ws.cell(row=row, column=col, value=subj)
        c.fill = PatternFill(
            start_color=pal["bg"], end_color=pal["bg"], fill_type="solid",
        )
        c.font = Font(name=FONT_NAME, size=LEGEND_SIZE, color=pal["fg"])
        c.alignment = _CENTER
        c.border = _CELL_BORDER
        col += 1
        if col > start_col + 5:
            col = start_col
            row += 1
    return row + 1


def _subjects_in_sol(sol) -> list[str]:
    return sorted({k[2] for k in sol if k[2]})


# --------------------------- funzioni pubbliche ---------------------------

def export_class_schedules_to_xlsx(
    solution_pickle_path: str,
    school_pickle_path: str,
    profs_pickle_path: str,
    output_path: str,
) -> None:
    """Crea un .xlsx con un tab per classe.

    Colonne = giorni della settimana (Lun..Sab in base al mock).
    Righe = ore della giornata (1^a, 2^a, ..., con orario assoluto).
    Celle = "Materia / Docente" o "-" se la classe non ha lezione.
    """
    sol, school, profs = _load_pickles(
        solution_pickle_path, school_pickle_path, profs_pickle_path
    )
    cls_idx = _classes_index(school)
    days, hours = _days_hours(sol)
    classes = sorted({c for p in profs.values() for c in p["classi"]})

    wb = Workbook()
    wb.remove(wb.active)
    used = set()
    n_conflicts = 0

    for cl in classes:
        sheet_name = _safe_sheet_name(cl, used)
        ws = wb.create_sheet(title=sheet_name)
        cls_meta = cls_idx.get(cl, {})
        curriculum = cls_meta.get("curriculum", "")

        # Header informativo
        ws.cell(row=1, column=1, value=f"Classe: {cl}").font = _TITLE_FONT
        ws.merge_cells(start_row=1, start_column=1,
                       end_row=1, end_column=1 + len(days))
        if curriculum:
            ws.cell(row=2, column=1,
                    value=f"Indirizzo: {curriculum}").font = _SUBTITLE_FONT
            ws.merge_cells(start_row=2, start_column=1,
                           end_row=2, end_column=1 + len(days))
        header_row = 4

        _write_grid_header(ws, days, header_row=header_row)
        _write_hour_column(ws, hours, start_row=header_row + 1)

        for di, day in enumerate(days):
            for hi, hour in enumerate(hours):
                lessons = []
                for prof, info in profs.items():
                    if cl not in info["classi"]:
                        continue
                    for subj in info["classi"][cl]:
                        if sol.get((prof, cl, subj, day, hour), 0) == 1:
                            lessons.append((subj, prof))
                row = header_row + 1 + hi
                col = 2 + di
                if not lessons:
                    _fill_cell(ws, row, col, EMPTY_PLACEHOLDER)
                elif len(lessons) == 1:
                    subj, prof = lessons[0]
                    _fill_cell(
                        ws, row, col, f"{subj} / {prof}", subject=subj,
                    )
                else:
                    n_conflicts += 1
                    text = "*CONFLICT* " + " ; ".join(
                        f"{s}/{p}" for s, p in lessons
                    )
                    _fill_cell(ws, row, col, text, conflict=True)

        _autosize(ws, days, header_row=header_row,
                  hour_row_count=len(hours))
        # freeze: blocca l'header e la colonna ore
        ws.freeze_panes = ws.cell(row=header_row + 1, column=2).coordinate
        class_subjects = sorted({
            s for p in profs.values()
            if cl in p.get("classi", {})
            for s in p["classi"][cl]
        })
        _write_subject_legend(
            ws, class_subjects,
            start_row=header_row + 2 + len(hours),
        )

    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    wb.save(output_path)
    print(
        f"[exporters] {output_path}: "
        f"{len(wb.sheetnames)} tab classi, "
        f"{n_conflicts} conflitti rilevati"
    )


def export_teacher_schedules_to_xlsx(
    solution_pickle_path: str,
    school_pickle_path: str,
    profs_pickle_path: str,
    output_path: str,
) -> None:
    r"""Crea un .xlsx con un tab per docente.

    Header del tab (righe 1-3): nome docente, materie insegnate, totali.
    Colonne = giorni; righe = ore; celle = nome della classe.
    Se il docente insegna piu' materie nella stessa classe, la cella
    riporta "<classe>\n(<materia>)" per disambiguare.
    """
    sol, school, profs = _load_pickles(
        solution_pickle_path, school_pickle_path, profs_pickle_path
    )
    teachers_idx = _teachers_index(school)
    days, hours = _days_hours(sol)

    wb = Workbook()
    wb.remove(wb.active)
    used = set()
    n_conflicts = 0

    for prof in sorted(profs.keys()):
        sheet_name = _safe_sheet_name(prof, used)
        ws = wb.create_sheet(title=sheet_name)
        info = profs[prof]
        meta = teachers_idx.get(prof, {})
        group = meta.get("group", "")
        max_hours = meta.get("max_hours", "?")

        subj_set = sorted({
            s for cl, sm in info["classi"].items() for s in sm
        })
        n_classes = len(info["classi"])
        tot_ore = sum(
            v["ore"] for cl, sm in info["classi"].items()
            for v in sm.values()
        )

        # Header info
        title = f"Docente: {prof}"
        if group:
            title += f"   (cl. concorso {group})"
        ws.cell(row=1, column=1, value=title).font = _TITLE_FONT
        ws.merge_cells(start_row=1, start_column=1,
                       end_row=1, end_column=1 + len(days))
        ws.cell(row=2, column=1,
                value=f"Materie insegnate: "
                      f"{', '.join(subj_set) if subj_set else '(nessuna)'}"
                ).font = _SUBTITLE_FONT
        ws.merge_cells(start_row=2, start_column=1,
                       end_row=2, end_column=1 + len(days))
        ws.cell(
            row=3, column=1,
            value=f"Classi: {n_classes} | "
                  f"Ore assegnate: {tot_ore} | "
                  f"Disponibilita\' max: {max_hours}"
        ).font = _SUBTITLE_FONT
        ws.merge_cells(start_row=3, start_column=1,
                       end_row=3, end_column=1 + len(days))
        header_row = 5

        _write_grid_header(ws, days, header_row=header_row)
        _write_hour_column(ws, hours, start_row=header_row + 1)

        for di, day in enumerate(days):
            for hi, hour in enumerate(hours):
                lessons = []
                for cl in info["classi"]:
                    for subj in info["classi"][cl]:
                        if sol.get((prof, cl, subj, day, hour), 0) == 1:
                            lessons.append((cl, subj))
                row = header_row + 1 + hi
                col = 2 + di
                if not lessons:
                    _fill_cell(ws, row, col, EMPTY_PLACEHOLDER)
                elif len(lessons) == 1:
                    cl, subj = lessons[0]
                    if len(info["classi"][cl]) > 1:
                        text = f"{cl}\n({subj})"
                    else:
                        text = cl
                    _fill_cell(ws, row, col, text, subject=subj)
                else:
                    n_conflicts += 1
                    text = "*CONFLICT* " + " ; ".join(
                        f"{c}/{s}" for c, s in lessons
                    )
                    _fill_cell(ws, row, col, text, conflict=True)

        _autosize(
            ws, days,
            header_row=header_row, hour_row_count=len(hours),
            col_other_width=22,
        )
        ws.freeze_panes = ws.cell(row=header_row + 1, column=2).coordinate
        _write_subject_legend(
            ws, subj_set,
            start_row=header_row + 2 + len(hours),
        )

    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    wb.save(output_path)
    print(
        f"[exporters] {output_path}: "
        f"{len(wb.sheetnames)} tab docenti, "
        f"{n_conflicts} conflitti rilevati"
    )


def export_global_teacher_board_to_xlsx(
    solution_pickle_path: str,
    school_pickle_path: str,
    profs_pickle_path: str,
    output_path: str,
) -> None:
    """One sheet: rows = teachers, columns = day×hour, cell = class.

    Sized for A3 landscape print. Colour is still keyed on the subject
    so the same materia keeps the same tint as the per-class / per-
    teacher workbooks.
    """
    sol, school, profs = _load_pickles(
        solution_pickle_path, school_pickle_path, profs_pickle_path
    )
    days, hours = _days_hours(sol)
    teachers = sorted(profs.keys())
    slots = [(d, h) for d in days for h in hours]

    wb = Workbook()
    ws = wb.active
    ws.title = "Tabellone docenti"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.page_margins = PageMargins(
        left=0.4, right=0.4, top=0.5, bottom=0.5,
    )
    ws.print_title_rows = "1:2"
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    ws.cell(row=1, column=1, value="Tabellone globale docenti").font = _TITLE_FONT
    n_cols = 1 + len(slots)
    if n_cols > 1:
        ws.merge_cells(start_row=1, start_column=1,
                       end_row=1, end_column=n_cols)
    ws.cell(
        row=2, column=1,
        value="Ogni casella: classe (colore = materia). Stampa A3 orizzontale.",
    ).font = _SUBTITLE_FONT
    if n_cols > 1:
        ws.merge_cells(start_row=2, start_column=1,
                       end_row=2, end_column=n_cols)

    header_row = 4
    corner = ws.cell(row=header_row, column=1, value="Docente")
    corner.fill = _HEADER_FILL
    corner.font = _HEADER_FONT
    corner.alignment = _CENTER
    corner.border = _CELL_BORDER
    for i, (d, h) in enumerate(slots):
        label = f"{_day_label(d)}\n{h:02d}"
        c = ws.cell(row=header_row, column=2 + i, value=label)
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
        c.alignment = _CENTER
        c.border = _CELL_BORDER

    n_conflicts = 0
    for ti, prof in enumerate(teachers):
        row = header_row + 1 + ti
        name_cell = ws.cell(row=row, column=1, value=prof)
        name_cell.font = Font(
            name=FONT_NAME, bold=True, size=CELL_SIZE,
        )
        name_cell.alignment = Alignment(
            horizontal="left", vertical="center", wrap_text=True,
        )
        name_cell.border = _CELL_BORDER
        name_cell.fill = PatternFill(
            start_color="D9E1F2", end_color="D9E1F2", fill_type="solid",
        )
        info = profs[prof]
        for si, (day, hour) in enumerate(slots):
            lessons = []
            for cl in info["classi"]:
                for subj in info["classi"][cl]:
                    if sol.get((prof, cl, subj, day, hour), 0) == 1:
                        lessons.append((cl, subj))
            col = 2 + si
            if not lessons:
                _fill_cell(
                    ws, row, col, EMPTY_PLACEHOLDER,
                    font_size=GLOBAL_CELL_SIZE,
                )
            elif len(lessons) == 1:
                cl, subj = lessons[0]
                _fill_cell(
                    ws, row, col, cl, subject=subj,
                    font_size=GLOBAL_CELL_SIZE,
                )
            else:
                n_conflicts += 1
                text = " / ".join(c for c, _s in lessons)
                _fill_cell(
                    ws, row, col, text, conflict=True,
                    font_size=GLOBAL_CELL_SIZE,
                )

    ws.column_dimensions["A"].width = 22
    slot_w = 5.5 if len(slots) > 24 else 7.0
    for i in range(len(slots)):
        ws.column_dimensions[get_column_letter(2 + i)].width = slot_w
    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 16
    ws.row_dimensions[header_row].height = 28
    for ti in range(len(teachers)):
        ws.row_dimensions[header_row + 1 + ti].height = 16
    ws.freeze_panes = ws.cell(row=header_row + 1, column=2).coordinate
    _write_subject_legend(
        ws, _subjects_in_sol(sol),
        start_row=header_row + 2 + len(teachers),
    )

    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    wb.save(output_path)
    print(
        f"[exporters] {output_path}: tabellone globale "
        f"{len(teachers)} docenti × {len(slots)} slot, "
        f"{n_conflicts} conflitti"
    )


# --------------------------- LaTeX ---------------------------

_LATEX_SPECIALS = str.maketrans({
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
})


def _tex_escape(s: str) -> str:
    return str(s).translate(_LATEX_SPECIALS)


def _tex_color_defs() -> str:
    lines = []
    for i, pal in enumerate(SUBJECT_PALETTE):
        lines.append(
            rf"\definecolor{{subjbg{i}}}{{HTML}}{{{pal['bg']}}}"
        )
        lines.append(
            rf"\definecolor{{subjfg{i}}}{{HTML}}{{{pal['fg']}}}"
        )
    return "\n".join(lines)


def _tex_subj_idx(subject: str) -> int:
    key = (subject or "").strip()
    if not key:
        return 0
    return hash_str(key) % len(SUBJECT_PALETTE)


def _tex_cell(text: str, subject: str | None = None,
              conflict: bool = False, empty: bool = False) -> str:
    body = _tex_escape(text)
    if conflict:
        return (
            r"\cellcolor{conflictbg}\textcolor{conflictfg}"
            rf"{{\bfseries {body}}}"
        )
    if empty or text == EMPTY_PLACEHOLDER:
        return r"\cellcolor{emptybg}\textcolor{emptyfg}{-}"
    idx = _tex_subj_idx(subject or "")
    return (
        rf"\cellcolor{{subjbg{idx}}}\textcolor{{subjfg{idx}}}"
        rf"{{\bfseries {body}}}"
    )


def _tex_hour_label(i: int, hour: int) -> str:
    return rf"{i + 1}\textsuperscript{{a}} ({hour:02d}:00)"


def _tex_preamble(*, paper: str = "a4paper",
                  landscape: bool = True,
                  cell_pt: int = CELL_SIZE,
                  margin: str = "12mm") -> str:
    geo = paper
    if landscape:
        geo += ",landscape"
    geo += f",margin={margin}"
    return rf"""\documentclass[10pt]{{article}}
\usepackage[T1]{{fontenc}}
\usepackage[utf8]{{inputenc}}
\usepackage{{lmodern}}
\usepackage[italian]{{babel}}
\usepackage{{xcolor}}
\usepackage{{colortbl}}
\usepackage{{longtable}}
\usepackage{{array}}
\usepackage{{booktabs}}
\usepackage{{geometry}}
\usepackage{{fancyhdr}}
\usepackage{{microtype}}
\geometry{{{geo}}}
\pagestyle{{fancy}}
\fancyhf{{}}
\fancyhead[L]{{\small\sffamily piTantum -- orario}}
\fancyhead[R]{{\small\sffamily\thepage}}
\renewcommand{{\headrulewidth}}{{0.3pt}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\tabcolsep}}{{3pt}}
\renewcommand{{\arraystretch}}{{1.25}}
\definecolor{{headerbg}}{{HTML}}{{4472C4}}
\definecolor{{emptybg}}{{HTML}}{{F2F2F2}}
\definecolor{{emptyfg}}{{HTML}}{{888888}}
\definecolor{{conflictbg}}{{HTML}}{{FFC7CE}}
\definecolor{{conflictfg}}{{HTML}}{{9C0006}}
{_tex_color_defs()}
\newcommand{{\cellf}}[1]{{\sffamily\fontsize{{{cell_pt}}}{{{cell_pt + 2}}}\selectfont #1}}
\newcommand{{\hdrf}}[1]{{\sffamily\bfseries\color{{white}}\fontsize{{{HEADER_SIZE}}}{{{HEADER_SIZE + 2}}}\selectfont #1}}
"""


def _tex_legend(subjects: list[str]) -> str:
    if not subjects:
        return ""
    bits = [r"\noindent{\sffamily\itshape\small Legenda materie:}\par\vspace{2pt}"]
    chips = []
    for subj in subjects:
        idx = _tex_subj_idx(subj)
        chips.append(
            rf"\fcolorbox{{subjfg{idx}}}{{subjbg{idx}}}"
            rf"{{\sffamily\scriptsize\textcolor{{subjfg{idx}}}"
            rf"{{\,{_tex_escape(subj)}\,}}}}"
        )
    bits.append(" ".join(chips))
    bits.append(r"\par\vspace{6pt}")
    return "\n".join(bits)


def _tex_grid(days, hours, cell_fn, *,
              hour_header: str = "Ora") -> str:
    """``cell_fn(day, hour) -> already-escaped cell TeX``."""
    n = len(days)
    colspec = "|c|" + "c|" * n
    lines = [rf"\begin{{longtable}}{{{colspec}}}"]
    lines.append(r"\hline")
    head = [rf"\cellcolor{{headerbg}}\hdrf{{{_tex_escape(hour_header)}}}"]
    for d in days:
        head.append(
            rf"\cellcolor{{headerbg}}\hdrf{{{_tex_escape(_day_label(d))}}}"
        )
    lines.append(" & ".join(head) + r" \\")
    lines.append(r"\hline\endfirsthead")
    lines.append(r"\hline")
    lines.append(" & ".join(head) + r" \\")
    lines.append(r"\hline\endhead")
    for hi, hour in enumerate(hours):
        row = [
            rf"\cellcolor{{headerbg}}\hdrf{{{_tex_hour_label(hi, hour)}}}"
        ]
        for day in days:
            row.append(rf"\cellf{{{cell_fn(day, hour)}}}")
        lines.append(" & ".join(row) + r" \\")
        lines.append(r"\hline")
    lines.append(r"\end{longtable}")
    return "\n".join(lines)


def export_schedules_to_latex(
    solution_pickle_path: str,
    school_pickle_path: str,
    profs_pickle_path: str,
    output_path: str,
) -> str:
    """Write a .tex with every class board and every teacher board.

    A4 landscape. The global teacher × day-hour A3 board is a
    separate document (``export_global_teacher_board_to_latex``)
    so paper size stays honest. Returns the path written.
    """
    sol, school, profs = _load_pickles(
        solution_pickle_path, school_pickle_path, profs_pickle_path
    )
    cls_idx = _classes_index(school)
    teachers_idx = _teachers_index(school)
    days, hours = _days_hours(sol)
    classes = sorted({c for p in profs.values() for c in p["classi"]})
    all_subjects = _subjects_in_sol(sol)

    parts: list[str] = [_tex_preamble(paper="a4paper", landscape=True)]
    parts.append(r"\begin{document}")
    parts.append(r"\sffamily")
    parts.append(r"{\LARGE\bfseries Orario settimanale\par}")
    parts.append(
        r"{\color{gray}\small Caselle colorate per materia; "
        r"stesso schema cromatico di Excel e del calendario web.\par}"
    )
    parts.append(r"\vspace{4pt}")
    parts.append(_tex_legend(all_subjects))

    # ---- classi ----
    parts.append(r"\clearpage\section*{Orari delle classi}")
    for cl in classes:
        cls_meta = cls_idx.get(cl, {})
        curriculum = cls_meta.get("curriculum", "")
        parts.append(rf"\subsection*{{Classe {_tex_escape(cl)}}}")
        if curriculum:
            parts.append(
                rf"{{\color{{gray}}\small Indirizzo: "
                rf"{_tex_escape(curriculum)}\par}}"
            )

        def _class_cell(day, hour, _cl=cl):
            lessons = []
            for prof, info in profs.items():
                if _cl not in info["classi"]:
                    continue
                for subj in info["classi"][_cl]:
                    if sol.get((prof, _cl, subj, day, hour), 0) == 1:
                        lessons.append((subj, prof))
            if not lessons:
                return _tex_cell(EMPTY_PLACEHOLDER, empty=True)
            if len(lessons) == 1:
                subj, prof = lessons[0]
                return _tex_cell(f"{subj} / {prof}", subject=subj)
            text = "*CONFLICT* " + " ; ".join(
                f"{s}/{p}" for s, p in lessons
            )
            return _tex_cell(text, conflict=True)

        parts.append(_tex_grid(days, hours, _class_cell))
        class_subjects = sorted({
            s for p in profs.values()
            if cl in p.get("classi", {})
            for s in p["classi"][cl]
        })
        parts.append(_tex_legend(class_subjects))
        parts.append(r"\clearpage")

    # ---- docenti ----
    parts.append(r"\section*{Orari dei docenti}")
    for prof in sorted(profs.keys()):
        info = profs[prof]
        meta = teachers_idx.get(prof, {})
        group = meta.get("group", "")
        title = f"Docente: {prof}"
        if group:
            title += f"  (cl. concorso {group})"
        parts.append(rf"\subsection*{{{_tex_escape(title)}}}")
        subj_set = sorted({
            s for cl, sm in info["classi"].items() for s in sm
        })
        if subj_set:
            parts.append(
                rf"{{\color{{gray}}\small Materie: "
                rf"{_tex_escape(', '.join(subj_set))}\par}}"
            )

        def _teacher_cell(day, hour, _prof=prof, _info=info):
            lessons = []
            for cl in _info["classi"]:
                for subj in _info["classi"][cl]:
                    if sol.get((_prof, cl, subj, day, hour), 0) == 1:
                        lessons.append((cl, subj))
            if not lessons:
                return _tex_cell(EMPTY_PLACEHOLDER, empty=True)
            if len(lessons) == 1:
                cl, subj = lessons[0]
                if len(_info["classi"][cl]) > 1:
                    text = f"{cl} ({subj})"
                else:
                    text = cl
                return _tex_cell(text, subject=subj)
            text = "*CONFLICT* " + " ; ".join(
                f"{c}/{s}" for c, s in lessons
            )
            return _tex_cell(text, conflict=True)

        parts.append(_tex_grid(days, hours, _teacher_cell))
        parts.append(_tex_legend(subj_set))
        parts.append(r"\clearpage")

    parts.append(r"\end{document}")
    tex = "\n".join(parts) + "\n"
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(tex)
    print(f"[exporters] {output_path}: LaTeX "
          f"{len(classes)} classi, {len(profs)} docenti")
    return output_path


def export_global_teacher_board_to_latex(
    solution_pickle_path: str,
    school_pickle_path: str,
    profs_pickle_path: str,
    output_path: str,
) -> str:
    """A3-landscape .tex: rows = teachers, columns = day×hour, cell = class."""
    sol, school, profs = _load_pickles(
        solution_pickle_path, school_pickle_path, profs_pickle_path
    )
    days, hours = _days_hours(sol)
    all_subjects = _subjects_in_sol(sol)
    slots = [(d, h) for d in days for h in hours]
    n = len(slots)
    colspec = "|l|" + "c|" * n

    parts: list[str] = [
        _tex_preamble(
            paper="a3paper", landscape=True, cell_pt=GLOBAL_CELL_SIZE,
            margin="8mm",
        ),
        r"\begin{document}",
        r"\sffamily",
        r"{\LARGE\bfseries Tabellone globale docenti\par}",
        r"{\color{gray}\small Ogni casella riporta la classe; "
        r"il colore e' quello della materia. "
        r"Stampa A3 orizzontale.\par}",
        r"\vspace{4pt}",
        _tex_legend(all_subjects),
        rf"\setlength{{\tabcolsep}}{{1.4pt}}",
        rf"\renewcommand{{\arraystretch}}{{1.05}}",
        rf"\begin{{longtable}}{{{colspec}}}",
        r"\hline",
    ]
    head = [r"\cellcolor{headerbg}\hdrf{Docente}"]
    for d, h in slots:
        day_s = _tex_escape(_day_label(d))
        head.append(
            rf"\cellcolor{{headerbg}}\hdrf{{\shortstack{{{day_s}\\{h:02d}}}}}"
        )
    parts.append(" & ".join(head) + r" \\")
    parts.append(r"\hline\endfirsthead")
    parts.append(r"\hline")
    parts.append(" & ".join(head) + r" \\")
    parts.append(r"\hline\endhead")
    for prof in sorted(profs.keys()):
        info = profs[prof]
        row = [rf"\cellcolor{{headerbg}}\hdrf{{{_tex_escape(prof)}}}"]
        for day, hour in slots:
            lessons = []
            for cl in info["classi"]:
                for subj in info["classi"][cl]:
                    if sol.get((prof, cl, subj, day, hour), 0) == 1:
                        lessons.append((cl, subj))
            if not lessons:
                row.append(_tex_cell(EMPTY_PLACEHOLDER, empty=True))
            elif len(lessons) == 1:
                cl, subj = lessons[0]
                row.append(_tex_cell(cl, subject=subj))
            else:
                row.append(_tex_cell(
                    " / ".join(c for c, _s in lessons),
                    conflict=True,
                ))
        parts.append(" & ".join(row) + r" \\")
        parts.append(r"\hline")
    parts.append(r"\end{longtable}")
    parts.append(r"\end{document}")
    tex = "\n".join(parts) + "\n"
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(tex)
    print(f"[exporters] {output_path}: LaTeX A3 "
          f"{len(profs)} docenti × {n} slot")
    return output_path


def compile_latex(tex_path: str, *,
                  engine: str | None = None,
                  timeout_s: int = 90) -> str | None:
    """Compile ``tex_path`` with pdflatex (or ``engine``).

    Two passes so longtable headers settle. Returns the .pdf path on
    success, or None if no compiler is on PATH / the run failed.
    Side-effect files (.aux/.log) stay next to the .tex.
    """
    tex_path = os.path.abspath(tex_path)
    if not os.path.isfile(tex_path):
        raise FileNotFoundError(tex_path)
    exe = engine or shutil.which("pdflatex") or shutil.which("lualatex")
    if not exe:
        print("[exporters] nessun compilatore LaTeX (pdflatex/lualatex)")
        return None
    workdir = os.path.dirname(tex_path)
    name = os.path.basename(tex_path)
    cmd = [
        exe, "-interaction=nonstopmode", "-halt-on-error",
        "-file-line-error", name,
    ]
    last = None
    for _pass in range(2):
        try:
            last = subprocess.run(
                cmd, cwd=workdir, capture_output=True, text=True,
                timeout=timeout_s,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"[exporters] compile_latex failed: {e}")
            return None
        if last.returncode != 0:
            tail = (last.stdout or "")[-800:]
            print(f"[exporters] {exe} exit {last.returncode}: {tail}")
            return None
    pdf = os.path.splitext(tex_path)[0] + ".pdf"
    if not os.path.isfile(pdf):
        print("[exporters] compile_latex: PDF non prodotto")
        return None
    print(f"[exporters] compilato {pdf}")
    return pdf


# --------------------------- esempio CLI ---------------------------

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    profile = "huge"
    out_dir = os.path.join(here, "output", profile)

    sol_path = os.path.join(here, f"solution_timetable_{profile}.pkl")
    school_path = os.path.join(here, f"school_{profile}.pkl")
    profs_path = os.path.join(here, f"profs_{profile}.pkl")

    export_class_schedules_to_xlsx(
        sol_path, school_path, profs_path,
        os.path.join(out_dir, f"orario_classi_{profile}.xlsx"),
    )
    export_teacher_schedules_to_xlsx(
        sol_path, school_path, profs_path,
        os.path.join(out_dir, f"orario_docenti_{profile}.xlsx"),
    )
    export_global_teacher_board_to_xlsx(
        sol_path, school_path, profs_path,
        os.path.join(out_dir, f"orario_globale_{profile}.xlsx"),
    )
    export_schedules_to_latex(
        sol_path, school_path, profs_path,
        os.path.join(out_dir, f"orario_{profile}.tex"),
    )
    export_global_teacher_board_to_latex(
        sol_path, school_path, profs_path,
        os.path.join(out_dir, f"orario_globale_{profile}.tex"),
    )
