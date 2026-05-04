"""Seed the curricula table from the existing mock_classes2 module.

Idempotent: skips entirely if any Curriculum row already exists.

Usage (from webui/backend):
    .venv/Scripts/python.exe -m backend.seed_curricula
"""
from __future__ import annotations

import os
import pickle
import sys

from .db import SessionLocal, init_db
from . import models


# The canonical (curriculum, year) -> {subject: hours} grid lifted from
# schedule/mock_classes2.py. Keeping a copy here avoids dragging the
# mock module (which depends on Faker, ortools, numpy) into the seed
# path, and lets us serialize it independently as
# engine/scripts/curricula.pkl for engine consumption.
CURRICULUM_SUBJECT_HOURS: dict[tuple[str, int], dict[str, int]] = {
    ('Scientifico', 1): {'Matematica': 5, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese': 3, 'ConversazioneInglese': 1, 'Latino': 3, 'Italiano': 4, 'Fisica': 2, 'DisegnoArte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('Scientifico', 2): {'Matematica': 5, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese': 3, 'ConversazioneInglese': 1, 'Latino': 3, 'Italiano': 4, 'Fisica': 2, 'DisegnoArte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('Scientifico', 3): {'Matematica': 4, 'Scienzenaturali': 3, 'Storia': 2, 'Filosofia': 3, 'LinguaInglese': 3, 'Latino': 3, 'Italiano': 4, 'Fisica': 3, 'DisegnoArte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('Scientifico', 4): {'Matematica': 4, 'Scienzenaturali': 3, 'Storia': 2, 'Filosofia': 3, 'LinguaInglese': 3, 'Latino': 3, 'Italiano': 4, 'Fisica': 3, 'DisegnoArte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('Scientifico', 5): {'Matematica': 4, 'Scienzenaturali': 3, 'Storia': 2, 'Filosofia': 3, 'LinguaInglese': 3, 'Latino': 3, 'Italiano': 4, 'Fisica': 3, 'DisegnoArte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('ScienzeApplicate', 1): {'Matematica': 5, 'Scienzenaturali': 3, 'Geostoria': 3, 'LinguaInglese': 3, 'Latino': 3, 'Italiano': 4, 'Fisica': 2, 'DisegnoArte': 2, 'Scienzemotorie': 2, 'Religione': 1, 'Informatica': 2},
    ('ScienzeApplicate', 2): {'Matematica': 4, 'Scienzenaturali': 4, 'Geostoria': 3, 'LinguaInglese': 3, 'Latino': 3, 'Italiano': 4, 'Fisica': 2, 'DisegnoArte': 2, 'Scienzemotorie': 2, 'Religione': 1, 'Informatica': 2},
    ('ScienzeApplicate', 3): {'Matematica': 4, 'Scienzenaturali': 5, 'Storia': 2, 'Filosofia': 2, 'LinguaInglese': 3, 'Latino': 3, 'Italiano': 4, 'Fisica': 3, 'DisegnoArte': 2, 'Scienzemotorie': 2, 'Religione': 1, 'Informatica': 2},
    ('ScienzeApplicate', 4): {'Matematica': 4, 'Scienzenaturali': 5, 'Storia': 2, 'Filosofia': 2, 'LinguaInglese': 3, 'Latino': 3, 'Italiano': 4, 'Fisica': 3, 'DisegnoArte': 2, 'Scienzemotorie': 2, 'Religione': 1, 'Informatica': 2},
    ('ScienzeApplicate', 5): {'Matematica': 4, 'Scienzenaturali': 5, 'Storia': 2, 'Filosofia': 2, 'LinguaInglese': 3, 'Latino': 3, 'Italiano': 4, 'Fisica': 3, 'DisegnoArte': 2, 'Scienzemotorie': 2, 'Religione': 1, 'Informatica': 2},
    ('EconomicoSociale_FRA', 1): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese': 3, 'LinguaFrancese': 3, 'Italiano': 4, 'Scienzemotorie': 2, 'Religione': 1},
    ('EconomicoSociale_FRA', 2): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese': 3, 'LinguaFrancese': 3, 'Italiano': 4, 'Scienzemotorie': 2, 'Religione': 1},
    ('EconomicoSociale_FRA', 3): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia': 2, 'LinguaInglese': 3, 'LinguaFrancese': 3, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('EconomicoSociale_FRA', 4): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia': 2, 'LinguaInglese': 3, 'LinguaFrancese': 3, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('EconomicoSociale_FRA', 5): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia': 2, 'LinguaInglese': 3, 'LinguaFrancese': 3, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('EconomicoSociale_SPA', 1): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese': 3, 'LinguaSpagnola': 3, 'Italiano': 4, 'Scienzemotorie': 2, 'Religione': 1},
    ('EconomicoSociale_SPA', 2): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese': 3, 'LinguaSpagnola': 3, 'Italiano': 4, 'Scienzemotorie': 2, 'Religione': 1},
    ('EconomicoSociale_SPA', 3): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia': 2, 'LinguaInglese': 3, 'LinguaSpagnola': 3, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('EconomicoSociale_SPA', 4): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia': 2, 'LinguaInglese': 3, 'LinguaSpagnola': 3, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('EconomicoSociale_SPA', 5): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia': 2, 'LinguaInglese': 3, 'LinguaSpagnola': 3, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('EconomicoSociale_TED', 1): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese': 3, 'LinguaTedesca': 3, 'Italiano': 4, 'Scienzemotorie': 2, 'Religione': 1},
    ('EconomicoSociale_TED', 2): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese': 3, 'LinguaTedesca': 3, 'Italiano': 4, 'Scienzemotorie': 2, 'Religione': 1},
    ('EconomicoSociale_TED', 3): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia': 2, 'LinguaInglese': 3, 'LinguaTedesca': 3, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('EconomicoSociale_TED', 4): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia': 2, 'LinguaInglese': 3, 'LinguaTedesca': 3, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('EconomicoSociale_TED', 5): {'Scienzeumane': 3, 'DirittoEconomia': 3, 'Matematica': 3, 'Fisica': 2, 'Storia': 2, 'Filosofia': 2, 'LinguaInglese': 3, 'LinguaTedesca': 3, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('ScienzeUmane', 1): {'Scienzeumane': 4, 'DirittoEconomia': 2, 'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese': 3, 'Latino': 3, 'Italiano': 4, 'Scienzemotorie': 2, 'Religione': 1},
    ('ScienzeUmane', 2): {'Scienzeumane': 4, 'DirittoEconomia': 2, 'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese': 3, 'Latino': 3, 'Italiano': 4, 'Scienzemotorie': 2, 'Religione': 1},
    ('ScienzeUmane', 3): {'Scienzeumane': 5, 'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'Storia': 2, 'Filosofia': 3, 'LinguaInglese': 3, 'Latino': 2, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('ScienzeUmane', 4): {'Scienzeumane': 5, 'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'Storia': 2, 'Filosofia': 3, 'LinguaInglese': 3, 'Latino': 2, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('ScienzeUmane', 5): {'Scienzeumane': 5, 'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'Storia': 2, 'Filosofia': 3, 'LinguaInglese': 3, 'Latino': 2, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('Linguistico_FRA_SPA', 1): {'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese': 4, 'LinguaFrancese': 3, 'LinguaSpagnola': 3, 'Latino': 2, 'Italiano': 4, 'Scienzemotorie': 2, 'Religione': 1},
    ('Linguistico_FRA_SPA', 2): {'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese': 4, 'LinguaFrancese': 3, 'LinguaSpagnola': 3, 'Latino': 2, 'Italiano': 4, 'Scienzemotorie': 2, 'Religione': 1},
    ('Linguistico_FRA_SPA', 3): {'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'LinguaInglese': 3, 'LinguaFrancese': 4, 'LinguaSpagnola': 4, 'Storia': 2, 'Filosofia': 2, 'Latino': 2, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('Linguistico_FRA_SPA', 4): {'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'LinguaInglese': 3, 'LinguaFrancese': 4, 'LinguaSpagnola': 4, 'Storia': 2, 'Filosofia': 2, 'Latino': 2, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('Linguistico_FRA_SPA', 5): {'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'LinguaInglese': 3, 'LinguaFrancese': 4, 'LinguaSpagnola': 4, 'Storia': 2, 'Filosofia': 2, 'Latino': 2, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('Linguistico_FRA_TED', 1): {'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese': 4, 'LinguaFrancese': 3, 'LinguaTedesca': 3, 'Latino': 2, 'Italiano': 4, 'Scienzemotorie': 2, 'Religione': 1},
    ('Linguistico_FRA_TED', 2): {'Matematica': 3, 'Scienzenaturali': 2, 'Geostoria': 3, 'LinguaInglese': 4, 'LinguaFrancese': 3, 'LinguaTedesca': 3, 'Latino': 2, 'Italiano': 4, 'Scienzemotorie': 2, 'Religione': 1},
    ('Linguistico_FRA_TED', 3): {'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'LinguaInglese': 3, 'LinguaFrancese': 4, 'LinguaTedesca': 4, 'Storia': 2, 'Filosofia': 2, 'Latino': 2, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('Linguistico_FRA_TED', 4): {'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'LinguaInglese': 3, 'LinguaFrancese': 4, 'LinguaTedesca': 4, 'Storia': 2, 'Filosofia': 2, 'Latino': 2, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
    ('Linguistico_FRA_TED', 5): {'Matematica': 2, 'Scienzenaturali': 2, 'Fisica': 2, 'LinguaInglese': 3, 'LinguaFrancese': 4, 'LinguaTedesca': 4, 'Storia': 2, 'Filosofia': 2, 'Latino': 2, 'Italiano': 4, 'Arte': 2, 'Scienzemotorie': 2, 'Religione': 1},
}

CURRICULUM_SCORES: dict[str, int] = {
    'Scientifico': 3,
    'ScienzeApplicate': 1,
    'ScienzeUmane': -1,
    'EconomicoSociale_FRA': -2,
    'EconomicoSociale_SPA': -3,
    'EconomicoSociale_TED': -1,
    'Linguistico_FRA_SPA': 0,
    'Linguistico_FRA_TED': 1,
}

# Optional display names (kept ASCII per project policy)
CURRICULUM_NAMES: dict[str, str] = {
    'Scientifico': 'Liceo Scientifico',
    'ScienzeApplicate': 'Liceo Scientifico - Scienze Applicate',
    'ScienzeUmane': 'Liceo Scienze Umane',
    'EconomicoSociale_FRA': 'Liceo Economico-Sociale (FRA)',
    'EconomicoSociale_SPA': 'Liceo Economico-Sociale (SPA)',
    'EconomicoSociale_TED': 'Liceo Economico-Sociale (TED)',
    'Linguistico_FRA_SPA': 'Liceo Linguistico (FRA + SPA)',
    'Linguistico_FRA_TED': 'Liceo Linguistico (FRA + TED)',
}


def codes_from_grid() -> list[str]:
    return sorted({code for (code, _y) in CURRICULUM_SUBJECT_HOURS.keys()})


def seed(force: bool = False) -> dict:
    """Insert curricula + their hours into the DB. Returns a small report."""
    init_db()
    db = SessionLocal()
    inserted_curr = 0
    inserted_hours = 0
    skipped = []
    try:
        existing = {c.code: c for c in db.query(models.Curriculum).all()}
        if existing and not force:
            return {
                "ok": True,
                "skipped": True,
                "reason": ("la tabella curricula contiene gia "
                           f"{len(existing)} righe; passa force=True"
                           " per reinizializzare"),
                "n_existing": len(existing),
            }
        if force and existing:
            db.query(models.CurriculumSubjectHours).delete()
            db.query(models.Curriculum).delete()
            db.commit()
            existing = {}

        for code in codes_from_grid():
            c = models.Curriculum(
                code=code,
                name=CURRICULUM_NAMES.get(code, code),
                description=None,
                score=int(CURRICULUM_SCORES.get(code, 1)),
            )
            db.add(c)
            db.flush()
            inserted_curr += 1
            for (cc, year), grid in CURRICULUM_SUBJECT_HOURS.items():
                if cc != code:
                    continue
                for subj, hours in grid.items():
                    db.add(models.CurriculumSubjectHours(
                        curriculum_id=c.id, year=int(year),
                        subject=str(subj), hours_per_week=int(hours),
                    ))
                    inserted_hours += 1
        db.commit()
        # Best-effort: link existing classes to the new curricula by
        # matching the legacy `curriculum` string column.
        linked = 0
        codes_map = {c.code: c.id for c in db.query(models.Curriculum).all()}
        for cl in db.query(models.SchoolClass).all():
            if cl.curriculum and cl.curriculum_id is None:
                cid = codes_map.get(cl.curriculum)
                if cid is not None:
                    cl.curriculum_id = cid
                    linked += 1
        db.commit()
        return {
            "ok": True,
            "n_curricula": inserted_curr,
            "n_hours_rows": inserted_hours,
            "n_linked_existing_classes": linked,
            "skipped": skipped,
        }
    finally:
        db.close()


def export_pickle(path: str | None = None) -> str:
    """Dump (curricula, scores, hours) into engine/scripts/curricula.pkl so the
    engine can ingest indirizzi without going through the DB."""
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        target_dir = os.path.normpath(
            os.path.join(here, "..", "..", "engine", "scripts")
        )
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, "curricula.pkl")
    payload = {
        "curriculum_subject_hours": dict(CURRICULUM_SUBJECT_HOURS),
        "curriculum_scores": dict(CURRICULUM_SCORES),
        "curriculum_names": dict(CURRICULUM_NAMES),
    }
    with open(path, "wb") as f:
        pickle.dump(payload, f)
    return path


if __name__ == "__main__":
    force = "--force" in sys.argv
    rep = seed(force=force)
    print("seed report:", rep)
    p = export_pickle()
    print("pickle:", p)
