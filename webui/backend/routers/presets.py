"""Preset come dati: lettura e salvataggio dei file in ``data/``.

Il preset aula di Alternativa vive in ``data/preset_alternativa.json``
(letto dal passo aule del motore). Qui l'interfaccia lo legge e lo
salva nella forma del componente ``AlternativaRoomPreset``; nessuna
regola nuova entra nel motore.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from engine import classroom_assignment as _ca
except ImportError:  # engine/ direttamente su sys.path
    import classroom_assignment as _ca

router = APIRouter(prefix="/api/presets", tags=["presets"])

# Modi del componente UI <-> id delle modalita nel file.
_UI_TO_FILE = {"alternativa": "aula_di_alternativa", "fissa": "aula_fissa",
               "libere": "aule_libere"}
_FILE_TO_UI = {v: k for k, v in _UI_TO_FILE.items()}


class AlternativaPresetIO(BaseModel):
    active: bool = True
    mode: Literal["alternativa", "fissa", "libere"] = "alternativa"
    kind: Literal["alternativa"] = "alternativa"
    roomName: str = Field(default="", max_length=120)
    freeRooms: list[str] = Field(default_factory=list, max_length=200)


def _read_raw() -> dict:
    p = _ca.preset_alternativa_path()
    if not p.is_file():
        raise HTTPException(404, "preset_alternativa.json assente in data/")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        raise HTTPException(500, f"preset_alternativa.json illeggibile: {e}")


def _to_ui(raw: dict) -> AlternativaPresetIO:
    modes = {m.get("id"): m for m in raw.get("modalita") or []
             if isinstance(m, dict)}
    chosen = raw.get("modalita_scelta") or "aula_di_alternativa"
    fissa = modes.get("aula_fissa") or {}
    libere = modes.get("aule_libere") or {}
    return AlternativaPresetIO(
        active=bool(raw.get("attivo")),
        mode=_FILE_TO_UI.get(chosen, "alternativa"),
        roomName=str(fissa.get("home_room") or ""),
        freeRooms=[str(x) for x in libere.get("aule") or []],
    )


@router.get("/alternativa-aula", response_model=AlternativaPresetIO)
def get_alternativa_preset():
    return _to_ui(_read_raw())


@router.put("/alternativa-aula", response_model=AlternativaPresetIO)
def put_alternativa_preset(body: AlternativaPresetIO):
    raw = _read_raw()
    chosen = _UI_TO_FILE[body.mode]
    raw["attivo"] = bool(body.active)
    raw["modalita_scelta"] = chosen
    for m in raw.get("modalita") or []:
        if not isinstance(m, dict):
            continue
        m["selezionata"] = m.get("id") == chosen
        if m.get("id") == "aula_fissa":
            m["home_room"] = body.roomName.strip()
        if m.get("id") == "aule_libere":
            m["aule"] = [r.strip() for r in body.freeRooms if r.strip()]
    p = _ca.preset_alternativa_path()
    # Copia di sicurezza prima di riscrivere il dato.
    shutil.copy2(p, p.with_suffix(".json.bak"))
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, p)
    return _to_ui(raw)
