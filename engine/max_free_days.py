"""Regola HARD opzionale: al massimo N giorni liberi se le ore
settimanali (lezioni + potenziamento) sono almeno S.

I numeri N e S non sono cablati nel motore. Il preset
«Docenti a orario pieno: al massimo 1 giorno libero» (N=1, S=18,
spento di default) è solo un dato che la UI passa al solver.
"""
from __future__ import annotations

from typing import Any

# Dato del preset, non una costante del modello CP-SAT.
PRESET = {
    "key": "full_time_max_free_days",
    "label": "Docenti a orario pieno: al massimo 1 giorno libero",
    "summary": (
        "Regola HARD, spenta di default. Per ogni docente con ore "
        "settimanali (lezioni più potenziamento) almeno pari alla soglia, "
        "al massimo N giorni senza alcuna ora. Il preset parte da N=1 e "
        "soglia 18, entrambi modificabili."
    ),
    "enabled_by_default": False,
    "max_free": 1,
    "threshold": 18,
}


def weekly_hours(info: dict | None, pot_hours: int = 0) -> int:
    """Ore settimanali di cattedra più potenziamento. Il potenziamento
    passato a parte si somma solo se non è già in ``info``."""
    info = info or {}
    hours = 0
    for subs in (info.get("classi") or {}).values():
        if not isinstance(subs, dict):
            continue
        for spec in subs.values():
            if isinstance(spec, dict):
                hours += int(spec.get("ore") or 0)
            elif isinstance(spec, (int, float)):
                hours += int(spec)
    stored = info.get("potenziamento_hours")
    if stored is None:
        hours += int(pot_hours or 0)
    else:
        hours += int(stored or 0)
    return hours


def rule_of(info: dict | None) -> dict | None:
    raw = (info or {}).get("max_free_if_hours")
    if not raw:
        return None
    return {
        "max_free": int(raw.get("max_free", PRESET["max_free"])),
        "threshold": int(raw.get("threshold", PRESET["threshold"])),
    }


def quote_name(name: str) -> str:
    escaped = str(name).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def pragma(name: str, max_free: int, threshold: int) -> str:
    return (
        f"teacher_max_free_days_above_hours("
        f"{quote_name(name)}, {int(max_free)}, {int(threshold)})"
    )


def stamp(profs: dict, *, max_free: int, threshold: int,
          exclude: set[str] | None = None,
          only: set[str] | None = None,
          pot_by_teacher: dict | None = None) -> None:
    """Scrive la regola sui docenti in ambito. Non tocca chi è escluso
    né, se ``only`` non è vuoto, chi non è nell'elenco."""
    exclude = exclude or set()
    pot_by_teacher = pot_by_teacher or {}
    for name, info in profs.items():
        if not isinstance(info, dict):
            continue
        if info.get("potenziamento_hours") is None:
            info["potenziamento_hours"] = int(pot_by_teacher.get(name, 0) or 0)
        if name in exclude:
            info.pop("max_free_if_hours", None)
            continue
        if only and name not in only:
            info.pop("max_free_if_hours", None)
            continue
        info["max_free_if_hours"] = {
            "max_free": int(max_free),
            "threshold": int(threshold),
        }


def precheck(profs: dict, *, days: list[int] | None = None) -> list[dict]:
    """Controlli aritmetici prima del solve. Lista vuota = nessun
    conflitto. Non risolve il modello."""
    errors: list[dict] = []
    for name, info in profs.items():
        if not isinstance(info, dict):
            continue
        rule = rule_of(info)
        if rule is None:
            continue
        hours = weekly_hours(info)
        if hours < rule["threshold"]:
            continue
        max_free = rule["max_free"]
        min_free = int(info.get("min_free_days") or 0)
        if min_free > max_free:
            errors.append({
                "teacher": name,
                "code": "min_free_exceeds_max",
                "message": (
                    f"{name}: almeno {min_free} giorni liberi e al "
                    f"massimo {max_free} con {hours} ore "
                    f"(soglia {rule['threshold']}) è impossibile"
                ),
            })
        caps = info.get("day_capacity") or {}
        full_off = [int(d) for d, n in caps.items() if int(n) <= 0]
        if len(full_off) > max_free:
            errors.append({
                "teacher": name,
                "code": "hard_unavailability",
                "message": (
                    f"{name}: indisponibilità HARD su {len(full_off)} "
                    f"giorni interi, la regola ne ammette al massimo "
                    f"{max_free}"
                ),
                "days": sorted(full_off),
            })
    return errors


def solution_respects(sol: dict, profs: dict,
                      days: list[int] | None = None) -> bool:
    """True se la soluzione rispetta la regola sui docenti a cui si
    applica. Un'ora di potenziamento (qualsiasi classe, anche
    ``__potenziamento__``) rende il giorno occupato. Chiavi della
    soluzione che non sono (docente, classe, materia, giorno, ora)
    si ignorano."""
    if not any(rule_of(info) for info in profs.values()
               if isinstance(info, dict)):
        return True
    if days is None:
        try:
            from . import metaheuristics as meta
        except ImportError:
            import metaheuristics as meta
        days = list(meta.DAYS)
    worked: dict[str, set[int]] = {}
    for key, val in (sol or {}).items():
        try:
            if int(val) != 1 or not isinstance(key, tuple) or len(key) < 4:
                continue
        except (TypeError, ValueError):
            continue
        teacher, day = key[0], key[3]
        worked.setdefault(str(teacher), set()).add(int(day))
    for name, info in profs.items():
        if not isinstance(info, dict):
            continue
        rule = rule_of(info)
        if rule is None:
            continue
        if weekly_hours(info) < rule["threshold"]:
            continue
        free = sum(1 for d in days if d not in worked.get(name, set()))
        if free > rule["max_free"]:
            return False
    return True


def parse_name_list(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {part.strip() for part in str(raw).split(",") if part.strip()}
