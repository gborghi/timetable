"""Regola della «doppia» (due ore consecutive) come DATO, non come codice.

Unico punto da cui Fase A, Fase B, modello settimanale e validatore H_A
leggono la regola. Il preset di default riproduce il comportamento deciso
da Giovanni (01/11): «conta solo il prof non la materia... ma devono
essere materie di tutta la classe».

Regola (default):
  * scatta per ogni (docente, classe) in cui il docente ha almeno una
    materia «trigger» (Matematica, Italiano) insegnata a tutta la classe,
    con il flag di classe corrispondente attivo (dual_math / dual_italian);
  * le ore che contano sono quelle di TUTTE le materie che quel docente
    insegna a tutta la classe (``per_teacher_all_subjects``), escluse le
    materie di gruppo (``whole_class_only``: membri di gruppi paralleli
    come religione/alternativa, marcati ``"gruppo": True`` nei profs, e le
    materie in ``excluded_subjects``, es. sostegno);
  * se quelle ore sono almeno ``min_hours``, serve almeno un giorno con
    due ore consecutive del docente nella classe, su materie contate.

Il preset si puo' cambiare senza toccare il motore: file JSON indicato da
``TIMETABLE_DOUBLE_LESSON_PRESET`` oppure ``data/preset_doppia.json``
(stessi campi di ``DEFAULT``; i campi mancanti restano di default), oppure
``set_rule(...)`` da codice/test.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

DEFAULT: dict[str, Any] = {
    "key": "double_lesson",
    "label": "Doppia consecutiva (stesso docente)",
    "enabled": True,
    "trigger_subjects": ["Matematica", "Italiano"],
    "min_hours": 2,
    "per_teacher_all_subjects": True,
    "whole_class_only": True,
    # Materie non «di tutta la classe»: confronto per parole normalizzate
    # (minuscole, senza accenti e punteggiatura). Una voce esclude la
    # materia se le sue parole compaiono di seguito nel nome, l'ultima
    # anche come prefisso («AD0» prende «AD01»). Es.: «Sostegno (AD01)»,
    # «Religione cattolica», «IRC», «Mat. alternativa».
    "excluded_subjects": ["Sostegno", "AD0", "Religione", "IRC",
                          "Alternativa", "Materia alternativa"],
    # flag di classe che spengono la regola per una materia trigger
    "class_flags": {"Matematica": "dual_math", "Italiano": "dual_italian"},
}

_override: dict | None = None


def _key(name) -> str:
    try:
        from cpsat_v2_timetable import subject_key
    except ImportError:  # pragma: no cover
        from engine.cpsat_v2_timetable import subject_key
    return subject_key(name)


def _preset_path() -> Path:
    env = os.environ.get("TIMETABLE_DOUBLE_LESSON_PRESET")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data" / "preset_doppia.json"


def set_rule(rule: dict | None) -> None:
    """Imposta (o con None toglie) un override in memoria."""
    global _override
    _override = None if rule is None else dict(rule)


def get_rule() -> dict:
    rule = dict(DEFAULT)
    p = _preset_path()
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                rule.update(data)
        except (OSError, ValueError):
            pass
    if _override:
        rule.update(_override)
    return rule


def trigger_keys(rule: dict | None = None) -> dict[str, str | None]:
    """{chiave canonica della materia trigger -> flag di classe o None}."""
    rule = rule or get_rule()
    flags = rule.get("class_flags") or {}
    return {_key(s): flags.get(s) for s in rule.get("trigger_subjects") or []}


def is_whole_class(subj: str, spec, rule: dict | None = None,
                   group_subjects=()) -> bool:
    rule = rule or get_rule()
    if not rule.get("whole_class_only", True):
        return True
    if isinstance(spec, dict) and spec.get("gruppo"):
        return False
    if subj in group_subjects:
        return False
    return not is_excluded_name(subj, rule)


def _words(name) -> list[str]:
    s = unicodedata.normalize("NFKD", str(name).lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.findall(r"[a-z0-9]+", s)


def is_excluded_name(subj: str, rule: dict | None = None) -> bool:
    """Il nome della materia corrisponde a una voce di
    ``excluded_subjects`` (parole consecutive, ultima per prefisso)."""
    rule = rule or get_rule()
    w = _words(subj)
    if not w:
        return False
    for e in rule.get("excluded_subjects") or []:
        ew = _words(e)
        if not ew:
            continue
        n = len(ew)
        for i in range(len(w) - n + 1):
            if w[i:i + n - 1] == ew[:-1] and w[i + n - 1].startswith(ew[-1]):
                return True
        # anche il nome compatto («Scienzemotorie»-style) intero
        if _key(subj) == _key(e):
            return True
    return False


def mark_groups(profs: dict, parallel_groups=None,
                support_assignments=None) -> dict:
    """Segna ``"gruppo": True`` nei profs per le materie di gruppo
    dichiarate in ``parallel_groups`` (e nel sostegno). Da chiamare una
    volta prima di Fase A/B, modello settimanale e validatore, cosi' le
    quattro parti escludono gli stessi gruppi. Idempotente."""
    def _mark(t, cl, s):
        sd = ((profs.get(t) or {}).get("classi") or {}).get(cl, {}) \
            if isinstance(profs.get(t), dict) else {}
        spec = sd.get(s) if isinstance(sd, dict) else None
        if isinstance(spec, dict):
            spec["gruppo"] = True
    for pg in parallel_groups or []:
        for m in pg.get("members", []):
            _mark(m.get("teacher_name"), pg.get("class_name"),
                  m.get("subject"))
    for sa in support_assignments or []:
        _mark(sa.get("teacher_name"), sa.get("class_name"),
              sa.get("subject"))
    return profs


def counted_subjects(subjs: dict, trigger: str | None = None,
                     rule: dict | None = None, group_subjects=()) -> list:
    """Materie del docente nella classe che contano per la doppia."""
    rule = rule or get_rule()
    whole = [s for s, sd in subjs.items()
             if is_whole_class(s, sd, rule, group_subjects)]
    if rule.get("per_teacher_all_subjects", True) or trigger is None:
        return whole
    return [s for s in whole if _key(s) == trigger]


def _ore(sd) -> int:
    return int(sd.get("ore", 0)) if isinstance(sd, dict) else 0


def requirement(subjs: dict, cl: str, class_flags=None,
                rule: dict | None = None, group_subjects=(),
                class_enforces=None) -> list | None:
    """Materie da contare se (docente, classe) deve avere la doppia,
    altrimenti None. ``subjs`` = profs[docente]["classi"][classe]."""
    rule = rule or get_rule()
    if not rule.get("enabled", True) or not subjs:
        return None
    triggers = trigger_keys(rule)
    hit = []
    for s, sd in subjs.items():
        k = _key(s)
        if k not in triggers:
            continue
        if not is_whole_class(s, sd, rule, group_subjects):
            continue
        flag = triggers[k]
        if flag and class_enforces is not None and \
                not class_enforces(class_flags, cl, flag, True):
            continue
        hit.append(k)
    if not hit:
        return None
    if rule.get("per_teacher_all_subjects", True):
        counted = counted_subjects(subjs, None, rule, group_subjects)
    else:
        counted = [s for s in subjs
                   if _key(s) in hit
                   and is_whole_class(s, subjs[s], rule, group_subjects)]
    if sum(_ore(subjs[s]) for s in counted) < int(rule.get("min_hours", 2)):
        return None
    return counted


def requirement_for_subject(subjs: dict, want: str,
                            rule: dict | None = None) -> list | None:
    """Percorso «coppia dichiarata dai vincoli» (pragma
    ``subject_pair_exists``): stessa regola del preset (materie contate,
    esclusioni, ``min_hours``), con trigger la sola materia dichiarata."""
    rule = rule or get_rule()
    if not subjs:
        return None
    if not any(_key(s) == want and is_whole_class(s, sd, rule)
               for s, sd in subjs.items()):
        return None
    counted = counted_subjects(subjs, want, rule)
    if sum(_ore(subjs[s]) for s in counted) < int(rule.get("min_hours", 2)):
        return None
    return counted
