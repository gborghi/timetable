"""Nomi leggibili di materie e classi (solo visualizzazione)."""
from backend.display_names import pretty_subject, subject_display_name


def test_pretty_subject_codici_demo():
    assert pretty_subject("Scienzemotorie") == "Scienze motorie e sportive"
    assert pretty_subject("Geostoria") == "Storia e geografia"
    assert pretty_subject("DisegnoArte") == "Disegno e storia dell'arte"
    assert pretty_subject("Latino") == "Lingua e cultura latina"
    assert pretty_subject("DirittoEconomia") == "Diritto ed economia"
    assert pretty_subject("Religione") == (
        "Religione cattolica / Attività alternative")
    assert pretty_subject("Scienzenaturali") == "Scienze naturali"
    assert pretty_subject("Scienze naturali") == "Scienze naturali"


def test_pretty_subject_sconosciuta_resta_il_codice():
    assert pretty_subject("Robotica") == "Robotica"
    assert pretty_subject(None) == ""


def test_display_name_rispetta_il_pretty_name_utente():
    assert subject_display_name("Latino", "Latino (potenziato)") == \
        "Latino (potenziato)"
    # pretty_name == codice: default dei vecchi import, non una scelta
    assert subject_display_name("Latino", "Latino") == \
        "Lingua e cultura latina"
    assert subject_display_name("Latino", None) == "Lingua e cultura latina"
