"""Nomi leggibili per materie e classi, solo per la visualizzazione.

I codici interni (``Scienzemotorie``, ``1A_Scientifico``) restano le
chiavi usate da DSL, solver, import e lock: qui si decide soltanto come
mostrarli. Le denominazioni delle materie seguono i quadri orari dei
licei (DPR 89/2010, allegati); un ``pretty_name`` scritto a mano
dall'utente vince sempre su questa tabella.
"""
from __future__ import annotations

import re

# chiave = codice normalizzato (minuscolo, senza spazi/underscore/trattini)
_SUBJECTS: dict[str, str] = {
    "arte": "Storia dell'arte",
    "storiadellarte": "Storia dell'arte",
    "disegnoarte": "Disegno e storia dell'arte",
    "disegnoestoriadellarte": "Disegno e storia dell'arte",
    "conversazioneinglese": "Conversazione in lingua inglese",
    "conversazionefrancese": "Conversazione in lingua francese",
    "conversazionespagnolo": "Conversazione in lingua spagnola",
    "conversazionetedesco": "Conversazione in lingua tedesca",
    "dirittoeconomia": "Diritto ed economia",
    "filosofia": "Filosofia",
    "fisica": "Fisica",
    "geostoria": "Storia e geografia",
    "storiaegeografia": "Storia e geografia",
    "greco": "Lingua e cultura greca",
    "latino": "Lingua e cultura latina",
    "informatica": "Informatica",
    "italiano": "Lingua e letteratura italiana",
    "inglese": "Lingua e cultura inglese",
    "linguainglese": "Lingua e cultura inglese",
    "francese": "Lingua e cultura francese",
    "linguafrancese": "Lingua e cultura francese",
    "spagnolo": "Lingua e cultura spagnola",
    "linguaspagnola": "Lingua e cultura spagnola",
    "tedesco": "Lingua e cultura tedesca",
    "linguatedesca": "Lingua e cultura tedesca",
    "matematica": "Matematica",
    "religione": "Religione cattolica / Attività alternative",
    "alternativa": "Attività alternative all'IRC",
    "attivitaalternative": "Attività alternative all'IRC",
    "scienzemotorie": "Scienze motorie e sportive",
    "scienzenaturali": "Scienze naturali",
    "scienzeumane": "Scienze umane",
    "storia": "Storia",
    "sostegno": "Sostegno",
}


def _norm(code: str) -> str:
    return re.sub(r"[\s_\-'’]+", "", code or "").lower()


def pretty_subject(code: str | None) -> str:
    """Nome leggibile di una materia; il codice stesso se sconosciuto."""
    if not code:
        return ""
    return _SUBJECTS.get(_norm(code), code)


def subject_display_name(code: str, pretty_name: str | None) -> str:
    """``pretty_name`` se l'utente ne ha scritto uno vero, altrimenti la
    tabella. Un pretty_name uguale al codice (default degli import
    vecchi) non conta come scelta dell'utente."""
    if pretty_name and pretty_name.strip() and pretty_name != code:
        return pretty_name
    return pretty_subject(code)
