"""Endpoint del preset aula di Alternativa: legge e salva il file in data/."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _tmp_data(tmp_path, monkeypatch):
    shutil.copy2(REPO / "data" / "preset_alternativa.json", tmp_path)
    monkeypatch.setenv("PITANTUM_DATA_DIR", str(tmp_path))
    return tmp_path / "preset_alternativa.json"


def test_get_reads_file(client, tmp_path, monkeypatch):
    _tmp_data(tmp_path, monkeypatch)
    r = client.get("/api/presets/alternativa-aula")
    assert r.status_code == 200
    assert r.json()["mode"] == "alternativa"
    assert r.json()["active"] is True


def test_put_saves_to_data_and_engine_reads_it(client, tmp_path, monkeypatch):
    p = _tmp_data(tmp_path, monkeypatch)
    body = {"active": True, "mode": "fissa", "kind": "alternativa",
            "roomName": "Aula 12", "freeRooms": []}
    r = client.put("/api/presets/alternativa-aula", json=body)
    assert r.status_code == 200, r.text
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["modalita_scelta"] == "aula_fissa"
    fissa = [m for m in raw["modalita"] if m["id"] == "aula_fissa"][0]
    assert fissa["home_room"] == "Aula 12" and fissa["selezionata"]
    assert p.with_suffix(".json.bak").is_file()
    import classroom_assignment as ca
    assert ca.load_preset_alternativa()["modalita_scelta"] == "aula_fissa"


def test_put_off_turns_engine_preset_off(client, tmp_path, monkeypatch):
    _tmp_data(tmp_path, monkeypatch)
    r = client.put("/api/presets/alternativa-aula",
                   json={"active": False, "mode": "alternativa"})
    assert r.status_code == 200
    import classroom_assignment as ca
    assert ca.load_preset_alternativa() is None


def test_put_rejects_unknown_mode(client, tmp_path, monkeypatch):
    _tmp_data(tmp_path, monkeypatch)
    r = client.put("/api/presets/alternativa-aula", json={"mode": "boh"})
    assert r.status_code == 422
