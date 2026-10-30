"""Il preset Alternativa è un dato, non una regola del motore."""
import json
from pathlib import Path

PRESET = (
    Path(__file__).resolve().parents[3] / "data" / "preset_alternativa.json"
)


def test_preset_alternativa_tre_modalita_modificabili():
    dato = json.loads(PRESET.read_text(encoding="utf-8"))
    assert dato["attivo"] is True
    assert dato["rimovibile"] is True
    assert dato["modalita_scelta"] == "aula_di_alternativa"
    scelte = {m["id"]: m for m in dato["modalita"]}
    assert set(scelte) == {
        "aula_di_alternativa",
        "aula_fissa",
        "aule_libere",
    }
    default = scelte["aula_di_alternativa"]
    assert default["selezionata"] is True
    assert default["required_kind"]
    assert default["home_room"] == ""
    assert scelte["aula_fissa"]["selezionata"] is False
    assert scelte["aula_fissa"]["home_room"] == ""
    assert scelte["aule_libere"]["required_kind"] == ""
    assert scelte["aule_libere"]["home_room"] == ""
    assert sum(1 for m in dato["modalita"] if m["selezionata"]) == 1
