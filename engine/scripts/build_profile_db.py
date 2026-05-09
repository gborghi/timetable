"""Build a self-contained SQLite snapshot of an engine profile.

Reads the historic ``school_<profile>.pkl`` + ``profs_<profile>.pkl``
anagrafica, generates a stress-grade scenario on top (plessi, special
rooms, custom WorkingDay/Slot schedule, fixtures across the 14
constraint tables) and dumps the whole thing to
``engine/scripts/data/<profile>/<profile>.sqlite``.

Usage
-----
    python -m engine.scripts.build_profile_db small
    python -m engine.scripts.build_profile_db --all

The output SQLite is the new source of truth for ``import_engine_profile``;
the pickles stay around for audit but are deprecated -- see
``engine/scripts/data/<profile>/PICKLE_DEPRECATED.md`` (created by
this script).

Determinism
-----------
Every stochastic step is seeded with ``seed=42`` so two runs of the
script produce the same SQLite. The manifest records the seed and
the per-profile counts (n_classes, n_rooms, n_constraints) so the
manual chapter "Architettura dati profili" can render the stress
table from a fresh run.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import random
import shutil
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
WEBUI = os.path.join(ROOT, "webui", "backend")
ENGINE = os.path.join(ROOT, "engine")
for p in (ROOT, ENGINE):
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------------------------------------------------------------
# Per-profile knobs
# ---------------------------------------------------------------------


PROFILES = ("small", "medium", "big", "huge", "superhuge", "mega")

# Plesso count per profile (proportional-ish: 2 -> 4).
N_PLESSI = {
    "small": 2, "medium": 2, "big": 3,
    "huge": 3, "superhuge": 4, "mega": 4,
}

# Per-profile working schedule. Each entry is a dict
# {day_index_0_based: [(slot_index, start_hh_mm, end_hh_mm, label,
#                       legacy_hour_number)]}.
# Day positions are 0..6 (MON..SUN). Inactive days are simply absent.
def _slots_8_14(legacy_offset: int = 0) -> list[tuple]:
    """6 hourly slots 8:00 -> 14:00, legacy_hour_number 8..13."""
    return [
        (i, f"{8+i:02d}:00", f"{9+i:02d}:00",
         f"{i+1}^ ora", 8 + i + legacy_offset)
        for i in range(6)
    ]


def _slots_8_13() -> list[tuple]:
    """5 hourly slots 8:00 -> 13:00, legacy_hour_number 8..12."""
    return [(i, f"{8+i:02d}:00", f"{9+i:02d}:00",
             f"{i+1}^ ora", 8 + i) for i in range(5)]


def _slots_8_12() -> list[tuple]:
    return [(i, f"{8+i:02d}:00", f"{9+i:02d}:00",
             f"{i+1}^ ora", 8 + i) for i in range(4)]


def _slots_huge() -> list[tuple]:
    """7:55 -> 13:55, 6 slots of 55min + 5min break baked into
    the gap between slot end and next slot start. legacy_hour_number
    8..13 to keep TeacherUnavailability rows portable."""
    out = []
    starts = ["07:55", "08:55", "09:55", "10:55", "11:55", "12:55"]
    ends = ["08:50", "09:50", "10:50", "11:50", "12:50", "13:50"]
    for i in range(6):
        out.append((i, starts[i], ends[i], f"{i+1}^ ora", 8 + i))
    return out


def _slots_pomeriggio() -> list[tuple]:
    """3 afternoon slots 14:00 -> 17:00 -- legacy_hour_number 14..16."""
    return [(i, f"{14+i:02d}:00", f"{15+i:02d}:00",
             f"{i+1}^ ora pom.", 14 + i) for i in range(3)]


def working_schedule(profile: str) -> list[dict[str, Any]]:
    """Return the WorkingDay rows for the profile (each with embedded
    slot definitions). The set of legacy_day_number values matches
    the rows the existing pickle constraints reference (1..6) so
    historical TeacherUnavailability / ClassUnavailability data can
    still attach without renumbering."""
    days_full = [
        ("MON", "Lunedi",    0, 1),
        ("TUE", "Martedi",   1, 2),
        ("WED", "Mercoledi", 2, 3),
        ("THU", "Giovedi",   3, 4),
        ("FRI", "Venerdi",   4, 5),
        ("SAT", "Sabato",    5, 6),
    ]
    if profile == "small":
        # 8-14 lun-sab (6 days, 6 slots)
        return [{"code": c, "label": l, "position": p,
                 "legacy_day_number": ld, "slots": _slots_8_14()}
                for (c, l, p, ld) in days_full]
    if profile == "medium":
        # 8-14 lun-ven, 8-12 sab
        out = []
        for (c, l, p, ld) in days_full[:5]:
            out.append({"code": c, "label": l, "position": p,
                        "legacy_day_number": ld,
                        "slots": _slots_8_14()})
        out.append({"code": "SAT", "label": "Sabato",
                    "position": 5, "legacy_day_number": 6,
                    "slots": _slots_8_12()})
        return out
    if profile == "big":
        # 8-14 lun-ven, 8-13 sab (5h)
        out = []
        for (c, l, p, ld) in days_full[:5]:
            out.append({"code": c, "label": l, "position": p,
                        "legacy_day_number": ld,
                        "slots": _slots_8_14()})
        out.append({"code": "SAT", "label": "Sabato",
                    "position": 5, "legacy_day_number": 6,
                    "slots": _slots_8_13()})
        return out
    if profile == "huge":
        # 7:55 -> 13:55 lun-sab, 55min slot, baked-in 5min breaks
        return [{"code": c, "label": l, "position": p,
                 "legacy_day_number": ld, "slots": _slots_huge()}
                for (c, l, p, ld) in days_full]
    if profile == "superhuge":
        # 8-13 lun-ven (5 slots) + 14-17 mar+gio (3 afternoon slots)
        out = []
        for (c, l, p, ld) in days_full[:5]:
            morning = _slots_8_13()
            if c in ("TUE", "THU"):
                # Pomeriggio extra: append slot_indexes 5..7,
                # legacy_hour_number 14..16
                pom = [(5 + i, t[1], t[2], t[3], t[4])
                       for i, t in enumerate(_slots_pomeriggio())]
                slots = morning + pom
            else:
                slots = morning
            out.append({"code": c, "label": l, "position": p,
                        "legacy_day_number": ld, "slots": slots})
        return out
    if profile == "mega":
        # 8-14 lun-ven + 8-13 sab + 14-17 mer (1 pomeriggio fisso)
        out = []
        for (c, l, p, ld) in days_full[:5]:
            morning = _slots_8_14()
            if c == "WED":
                pom = [(6 + i, t[1], t[2], t[3], t[4])
                       for i, t in enumerate(_slots_pomeriggio())]
                slots = morning + pom
            else:
                slots = morning
            out.append({"code": c, "label": l, "position": p,
                        "legacy_day_number": ld, "slots": slots})
        out.append({"code": "SAT", "label": "Sabato",
                    "position": 5, "legacy_day_number": 6,
                    "slots": _slots_8_13()})
        return out
    # default
    return [{"code": c, "label": l, "position": p,
             "legacy_day_number": ld, "slots": _slots_8_14()}
            for (c, l, p, ld) in days_full]


# ---------------------------------------------------------------------
# DB build pipeline
# ---------------------------------------------------------------------


def _resolve_profile_pkl(profile: str, filename: str) -> str | None:
    base = os.path.join(ENGINE, "scripts")
    for c in (
        os.path.join(base, "data", profile, filename),
        os.path.join(base, "output", profile, filename),
        os.path.join(base, filename),
    ):
        if os.path.exists(c):
            return c
    return None


def _output_paths(profile: str) -> tuple[str, str, str]:
    """Return (sqlite_path, manifest_path, deprecated_md_path)."""
    out_dir = os.path.join(ENGINE, "scripts", "data", profile)
    os.makedirs(out_dir, exist_ok=True)
    return (
        os.path.join(out_dir, f"{profile}.sqlite"),
        os.path.join(out_dir, "manifest.json"),
        os.path.join(out_dir, "PICKLE_DEPRECATED.md"),
    )


def build(profile: str, *, seed: int = 42, force: bool = False
          ) -> dict[str, Any]:
    """Build the SQLite snapshot for ``profile``. Returns the manifest
    dict and writes ``<profile>.sqlite``, ``manifest.json`` and
    ``PICKLE_DEPRECATED.md`` next to it.

    The DB is created via SQLAlchemy ``Base.metadata.create_all``
    against a process-local engine pinned at the target file. We
    intentionally do NOT touch ``webui/data/timetable.db`` -- the
    user's live DB stays untouched.
    """
    if profile not in PROFILES:
        raise SystemExit(f"unknown profile {profile!r}; "
                         f"choose one of {PROFILES}")

    sqlite_path, manifest_path, deprecated_path = _output_paths(profile)

    # Sanitize stale build artefacts so create_all builds the canonical
    # schema from scratch.
    if os.path.exists(sqlite_path):
        if not force:
            print(f"[{profile}] {sqlite_path} already exists; "
                  f"deleting (build always rebuilds)")
        for p in (sqlite_path, sqlite_path + "-wal", sqlite_path + "-shm"):
            try: os.remove(p)
            except FileNotFoundError: pass

    # Pin the DB URL BEFORE importing webui.backend.db so the engine
    # connects to the per-profile file. Same trick the test harness
    # uses.
    os.environ["PITANTUM_DB_URL"] = f"sqlite:///{sqlite_path}"

    # Lazy imports: must happen after env-var pin.
    from webui.backend import db as wdb
    from webui.backend import engine_io, models, mock_classrooms
    from webui.backend import seed_curricula
    wdb.init_db()

    rng = random.Random(seed)

    # ---- 1. Anagrafica from pickles ----
    school_pkl = _resolve_profile_pkl(profile, f"school_{profile}.pkl")
    if not school_pkl:
        raise FileNotFoundError(
            f"school_{profile}.pkl not found; cannot build SQLite")
    profs_pkl = _resolve_profile_pkl(profile, f"profs_{profile}.pkl")

    with open(school_pkl, "rb") as f:
        school = pickle.load(f)
    with wdb.SessionLocal() as db:
        engine_io.import_school_into_db(db, school, replace=True)
    print(f"[{profile}] anagrafica: "
          f"{len(school.get('classes', []))} classi, "
          f"{len(school.get('teachers', []))} docenti")

    if profs_pkl:
        with open(profs_pkl, "rb") as f:
            profs = pickle.load(f)
        with wdb.SessionLocal() as db:
            n_assn = engine_io.import_profs_into_db(db, profs)
        print(f"[{profile}] cattedre: {n_assn} assegnamenti")
    else:
        n_assn = 0
        print(f"[{profile}] cattedre: profs_{profile}.pkl missing -- skipped")

    # ---- 2. Curricula seed (idempotent) ----
    try:
        seed_curricula.seed(force=False)
    except Exception as exc:
        print(f"[{profile}] curricula seed skipped: {exc}")

    # Link curriculum_id by code -- mirrors what import_engine_profile
    # does at runtime so the DB ships in the same shape it would have
    # after a normal pickle import.
    with wdb.SessionLocal() as db:
        codes = {c.code: c.id for c in db.query(models.Curriculum).all()}
        linked = 0
        for cl in db.query(models.SchoolClass).all():
            if cl.curriculum and cl.curriculum_id is None:
                cid = codes.get(cl.curriculum)
                if cid is not None:
                    cl.curriculum_id = cid
                    linked += 1
        db.commit()
    print(f"[{profile}] curricula: {linked} classi collegate")

    # ---- 3. Plessi ----
    with wdb.SessionLocal() as db:
        # wipe any existing plessi so the seed is deterministic
        db.query(models.Plesso).delete()
        db.commit()
        n_plessi = N_PLESSI[profile]
        plesso_objs = []
        names = ["Sede Centrale", "Succursale Garibaldi",
                 "Plesso Marconi", "Plesso Leopardi"]
        codes = ["SC", "SG", "PM", "PL"]
        for i in range(n_plessi):
            p = models.Plesso(name=names[i], code=codes[i],
                              tenant_id=1)
            db.add(p)
            db.flush()
            plesso_objs.append(p)
        db.commit()
        plesso_ids = [p.id for p in plesso_objs]
    print(f"[{profile}] plessi: {n_plessi}")

    # ---- 4. Auto-generate classrooms + remap special rooms ----
    # Use the existing auto-generator first; it produces the right
    # number of standard rooms and a few labs for the school size.
    from webui.backend.optimization import auto_generate_classrooms
    summary = auto_generate_classrooms(overrides=None)
    print(f"[{profile}] aule auto: {summary.get('created', 0)} aule")

    # Now distribute aule across plessi + force a few special rooms.
    SPECIAL_KINDS = ["palestra", "lab_fisica", "lab_chimica",
                     "lab_informatica"]
    auditorium_kinds = ["aula_speciale"]
    with wdb.SessionLocal() as db:
        rooms = db.query(models.Classroom).order_by(models.Classroom.id).all()
        # Re-assign every room a plesso_id round-robin.
        for i, r in enumerate(rooms):
            r.plesso_id = plesso_ids[i % n_plessi]
        # Make sure we have at least one room of each special kind:
        existing_kinds = {r.kind for r in rooms}
        next_idx = 0
        for kk in SPECIAL_KINDS:
            if kk in existing_kinds:
                continue
            # Promote a standard room to this kind.
            for r in rooms:
                if r.kind == "standard":
                    r.kind = kk
                    if kk == "palestra":
                        r.capacity = 60
                    elif kk.startswith("lab"):
                        r.capacity = 24
                    break
        # Big profiles also get an auditorium.
        if profile in ("big", "huge", "superhuge", "mega"):
            for r in rooms:
                if r.kind == "standard":
                    r.kind = "aula_speciale"
                    r.capacity = 80
                    break
        # Set realistic capacities on standard rooms (20/24/28/30/35).
        std_caps = [20, 24, 28, 30, 35]
        for r in rooms:
            if r.kind == "standard":
                r.capacity = rng.choice(std_caps)
        db.commit()

    # ---- 5/6/7. n_students per class + force tight classes ----
    # truncated normal centred on 24, sigma 3.5, clamped to [18, 30].
    with wdb.SessionLocal() as db:
        classes = (db.query(models.SchoolClass)
                     .order_by(models.SchoolClass.id).all())
        for cl in classes:
            v = int(round(rng.gauss(24, 3.5)))
            cl.n_students = max(18, min(30, v))
        # Force 2 tight classes: pick the two largest standard
        # rooms in the DB and bump 2 classes to that capacity exactly.
        std_rooms = db.query(models.Classroom).filter(
            models.Classroom.kind == "standard").all()
        if std_rooms:
            biggest = max(r.capacity for r in std_rooms)
            tight = classes[: min(2, len(classes))]
            for cl in tight:
                cl.n_students = biggest   # exactly fits the largest standard
        db.commit()

    # ---- 8. WorkingDay + WorkingHourSlot ----
    with wdb.SessionLocal() as db:
        # Wipe defaults seeded by init_db lightweight migration.
        db.query(models.WorkingHourSlot).delete()
        db.query(models.WorkingDay).delete()
        db.commit()
        for entry in working_schedule(profile):
            wd = models.WorkingDay(
                tenant_id=1,
                code=entry["code"], label=entry["label"],
                position=entry["position"],
                legacy_day_number=entry["legacy_day_number"],
                is_active=True)
            db.add(wd); db.flush()
            for (idx, st, et, lbl, leg) in entry["slots"]:
                db.add(models.WorkingHourSlot(
                    day_id=wd.id, slot_index=idx,
                    start_time=st, end_time=et, label=lbl,
                    legacy_hour_number=leg))
        db.commit()

    # ---- 9. Stress fixtures (14 tables) ----
    fixtures = _seed_stress_fixtures(profile, rng, plesso_ids)

    # ---- 10. Subject.required_kind for special-room rules ----
    with wdb.SessionLocal() as db:
        # Educazione Fisica -> palestra, Fisica -> lab_fisica, etc.
        # The mapping is best-effort: we set required_kind only if a
        # matching subject row already exists in the DB.
        kind_map = {
            "Educazione Fisica": "palestra",
            "Scienze Motorie": "palestra",
            "Fisica": "lab_fisica",
            "Chimica": "lab_chimica",
            "Informatica": "lab_informatica",
        }
        n_req = 0
        for s in db.query(models.Subject).all():
            if s.name in kind_map:
                s.required_kind = kind_map[s.name]
                n_req += 1
        db.commit()
        fixtures["subject_required_kind"] = n_req

    # ---- 11. Lessons solution (best-effort: import existing pickle) ----
    sol_pkl = (_resolve_profile_pkl(
                  profile, f"solution_timetable_{profile}_optimized.pkl")
               or _resolve_profile_pkl(
                  profile, f"solution_{profile}_temporal_alns.pkl")
               or _resolve_profile_pkl(
                  profile, f"solution_timetable_{profile}.pkl"))
    n_lessons = 0
    sol_label = None
    sol_dict = None
    if sol_pkl:
        try:
            with open(sol_pkl, "rb") as f:
                sol_dict = pickle.load(f)
            sol_label = os.path.basename(sol_pkl)
        except Exception as exc:
            print(f"[{profile}] solution pickle load failed: {exc}")
            sol_dict = None
    if sol_dict is None:
        # Mega is shipped only as xlsx (the canonical pickle is gitignored).
        # Reuse the existing engine_io fallback so the SQLite carries
        # the same lessons the legacy pickle import would.
        xlsx_path = _resolve_profile_pkl(
            profile, f"orario_classi_{profile}.xlsx")
        if xlsx_path:
            try:
                sol_dict = engine_io.solution_dict_from_class_xlsx(xlsx_path)
                sol_label = os.path.basename(xlsx_path) + " (xlsx)"
            except Exception as exc:
                print(f"[{profile}] xlsx fallback failed: {exc}")
                sol_dict = None
    if sol_dict:
        try:
            with wdb.SessionLocal() as db:
                sid = engine_io.import_solution_into_db(
                    db, sol_dict,
                    name=f"profile_{profile}",
                    kind="imported",
                    obj_value=0.0, metrics={},
                    make_active=True,
                )
                n_lessons = (db.query(models.Lesson)
                               .filter(models.Lesson.solution_id == sid)
                               .count())
            print(f"[{profile}] solution: {n_lessons} lezioni from "
                  f"{sol_label}")
        except Exception as exc:
            print(f"[{profile}] solution import skipped: {exc}")
    else:
        print(f"[{profile}] solution: no pickle/xlsx -- DB ships "
              f"without lessons")

    # ---- 12. Manifest ----
    with wdb.SessionLocal() as db:
        manifest = {
            "profile": profile,
            "seed": seed,
            "schema_version": 1,
            "schedule_label": _schedule_label(profile),
            "n_classes": db.query(models.SchoolClass).count(),
            "n_teachers": db.query(models.Teacher).count(),
            "n_subjects": db.query(models.Subject).count(),
            "n_assignments": db.query(models.Assignment).count(),
            "n_plessi": db.query(models.Plesso).count(),
            "n_classrooms": db.query(models.Classroom).count(),
            "n_classrooms_palestra": db.query(models.Classroom).filter(
                models.Classroom.kind == "palestra").count(),
            "n_classrooms_lab": db.query(models.Classroom).filter(
                models.Classroom.kind.like("lab_%")).count(),
            "n_classrooms_auditorium": db.query(models.Classroom).filter(
                models.Classroom.kind == "aula_speciale").count(),
            "n_working_days": db.query(models.WorkingDay).count(),
            "n_working_hour_slots": db.query(
                models.WorkingHourSlot).count(),
            "n_lessons": n_lessons,
            "n_students_range": _range(db, models.SchoolClass.n_students),
            "capacity_range": _range(db, models.Classroom.capacity),
            "fixtures": fixtures,
        }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # ---- 13. PICKLE_DEPRECATED.md ----
    with open(deprecated_path, "w", encoding="utf-8") as f:
        f.write(_pickle_deprecated_md(profile, manifest))

    print(f"[{profile}] OK -> {sqlite_path}")
    print(f"[{profile}]    manifest: {manifest_path}")
    return manifest


def _range(db, col) -> dict[str, int]:
    """Return {min, max} for the column. 0/0 if the table is empty."""
    from sqlalchemy import func
    row = db.query(func.min(col), func.max(col)).first()
    return {"min": int(row[0] or 0), "max": int(row[1] or 0)}


def _schedule_label(profile: str) -> str:
    return {
        "small":     "8-14 lun-sab (60min)",
        "medium":    "8-14 lun-ven + 8-12 sab",
        "big":       "8-14 lun-ven + 8-13 sab",
        "huge":      "7:55-13:55 lun-sab (55min + 5min break)",
        "superhuge": "8-13 lun-ven + 14-17 mar/gio (mattina+pomeriggio)",
        "mega":      "8-14 lun-ven + 8-13 sab + 14-17 mer (pom. fisso)",
    }.get(profile, "?")


# ---------------------------------------------------------------------
# Stress fixtures across the 14 constraint tables
# ---------------------------------------------------------------------


def _seed_stress_fixtures(profile: str, rng: random.Random,
                          plesso_ids: list[int]) -> dict[str, int]:
    """Populate 14 constraint tables with deterministic stress data.

    Returns a counts dict for the manifest.
    """
    # Lazy imports so the module loads cleanly when the env-var pin
    # didn't happen yet (smoke tests).
    from webui.backend import db as wdb
    from webui.backend import models
    from sqlalchemy import select

    counts: dict[str, int] = {}
    with wdb.SessionLocal() as db:
        teachers = (db.query(models.Teacher)
                      .order_by(models.Teacher.id).all())
        classes = (db.query(models.SchoolClass)
                     .order_by(models.SchoolClass.id).all())
        rooms = (db.query(models.Classroom)
                   .order_by(models.Classroom.id).all())
        days = (db.query(models.WorkingDay)
                  .order_by(models.WorkingDay.position).all())
        # Use legacy day/hour numbers because the *_unavailability rows
        # store those (preserves compatibility with the engine).
        day_legacies = sorted({d.legacy_day_number for d in days})
        slot_legacies_by_day = {
            d.legacy_day_number: sorted({s.legacy_hour_number
                                          for s in d.slots})
            for d in days}

        # ---- 1. TeacherUnavailability ----
        # 10-20% docenti get 1 day blocked HARD + 2-3 SOFT slots
        n_t_unav = max(1, int(0.15 * len(teachers)))
        for t in rng.sample(teachers, n_t_unav):
            d_hard = rng.choice(day_legacies)
            already = set()   # (day, hour) tuples for this teacher
            for h in slot_legacies_by_day.get(d_hard, []):
                db.add(models.TeacherUnavailability(
                    teacher_id=t.id, day=d_hard, hour=h,
                    state="hard", soft_penalty=0,
                    reason="stress: HARD day blocked"))
                already.add((d_hard, h))
            # 2-3 SOFT first-or-last hour slots on a DIFFERENT day so
            # we don't collide with the HARD block above (would
            # violate uq_unavail_dh).
            other_days = [d for d in day_legacies if d != d_hard]
            for _ in range(rng.randint(2, 3)):
                if not other_days:
                    break
                d_soft = rng.choice(other_days)
                hours = slot_legacies_by_day.get(d_soft, [])
                if not hours:
                    continue
                h_soft = hours[0] if rng.random() < 0.5 else hours[-1]
                if (d_soft, h_soft) in already:
                    continue
                already.add((d_soft, h_soft))
                db.add(models.TeacherUnavailability(
                    teacher_id=t.id, day=d_soft, hour=h_soft,
                    state="soft", soft_penalty=rng.choice([5, 8, 10]),
                    reason="stress: SOFT first/last hour"))
        db.commit()
        counts["teacher_unavailability"] = (
            db.query(models.TeacherUnavailability).count())

        # ---- 2. TeacherMandatoryFreeDay ----
        n_mfd = max(1, int(0.10 * len(teachers)))
        seen_t = set()
        for t in rng.sample(teachers, n_mfd):
            if t.id in seen_t:
                continue
            seen_t.add(t.id)
            d = rng.choice(day_legacies)
            db.add(models.TeacherMandatoryFreeDay(
                teacher_id=t.id, day=d))
        db.commit()
        counts["teacher_mandatory_free_day"] = (
            db.query(models.TeacherMandatoryFreeDay).count())

        # ---- 2b. TeacherFreeDayPreference (3 priorities per teacher)
        # Each teacher gets a deterministic shuffle of day_legacies;
        # the first 3 days become priority 1, 2, 3 (weights 30, 20,
        # 10 respectively, applied by the DSL translator). Skip days
        # already occupied by a TeacherMandatoryFreeDay so the unique
        # (teacher_id, day) constraint never collides.
        if hasattr(models, "TeacherFreeDayPreference") and day_legacies:
            mfd_days_by_teacher = {}
            for r in db.query(models.TeacherMandatoryFreeDay).all():
                mfd_days_by_teacher.setdefault(
                    r.teacher_id, set()).add(int(r.day))
            for t in teachers:
                forbidden = mfd_days_by_teacher.get(t.id, set())
                pool = [d for d in day_legacies if d not in forbidden]
                rng.shuffle(pool)
                for pri, d in enumerate(pool[:3], start=1):
                    db.add(models.TeacherFreeDayPreference(
                        teacher_id=t.id, day=d, priority=pri))
            db.commit()
            counts["teacher_free_day_preference"] = (
                db.query(models.TeacherFreeDayPreference).count())

        # ---- 2c. Teacher.min_free_days distribution (70/25/5)
        # Stratified at-least-N HARD floor so the bench exercises the
        # generic pragma (not just N=1):
        #   70% teachers -> N=1 (CCNL default)
        #   25% teachers -> N=2 (part-time CCNL spezzato)
        #    5% teachers -> N=3 (very part-time)
        # Deterministic order via the same `rng` used for the rest of
        # the stress fixtures so the profile rebuild is reproducible.
        if hasattr(models.Teacher, "min_free_days") and teachers:
            n_total = len(teachers)
            n_two = round(0.25 * n_total)
            n_three = round(0.05 * n_total)
            # Cap n_three by feasibility hint: each teacher works on
            # 6 - N days. With max_hours=18 and 5 hours/day, N=3
            # means 15 hours over 3 days -- still feasible. We do not
            # auto-shrink here; if the post-build precheck flags the
            # profile as infeasible the caller can re-run with
            # --force-min-free-days-cap.
            shuffled_ids = [t.id for t in teachers]
            rng.shuffle(shuffled_ids)
            two_ids = set(shuffled_ids[:n_two])
            three_ids = set(shuffled_ids[n_two:n_two + n_three])
            for t in teachers:
                if t.id in three_ids:
                    t.min_free_days = 3
                elif t.id in two_ids:
                    t.min_free_days = 2
                else:
                    t.min_free_days = 1
            db.commit()
            from collections import Counter
            counts["min_free_days_distribution"] = dict(Counter(
                int(t.min_free_days)
                for t in db.query(models.Teacher).all()))

        # ---- 3. ClassUnavailability ----
        # Few classes blocked at the last slot of Monday. Dedup on
        # (class_id, day, hour) via a set so the unique index never
        # collides on small profiles where N is low.
        if classes and day_legacies:
            seen_cu: set = set()
            for cl in rng.sample(classes, min(2, len(classes))):
                d = day_legacies[0]   # Mondays
                hh = slot_legacies_by_day.get(d, [])
                if not hh:
                    continue
                key = (cl.id, d, hh[-1])
                if key in seen_cu:
                    continue
                seen_cu.add(key)
                db.add(models.ClassUnavailability(
                    class_id=cl.id, day=d, hour=hh[-1],
                    state="soft", soft_penalty=20,
                    reason="stress: classe non disponibile ultima ora lun"))
        db.commit()
        counts["class_unavailability"] = (
            db.query(models.ClassUnavailability).count())

        # ---- 4. ClassroomUnavailability ----
        if rooms and day_legacies:
            for r in rng.sample(rooms, min(2, len(rooms))):
                d = rng.choice(day_legacies)
                hh = slot_legacies_by_day.get(d, [])
                for h in rng.sample(hh, min(2, len(hh))):
                    db.add(models.ClassroomUnavailability(
                        classroom_id=r.id, day=d, hour=h,
                        state="hard", soft_penalty=0,
                        reason="stress: manutenzione"))
        db.commit()
        counts["classroom_unavailability"] = (
            db.query(models.ClassroomUnavailability).count())

        # ---- 5. CoteachGroup ----
        # 2-5 groups across classes -- mix kinds (only 'shared' is
        # actually supported per model docstring; we still mark
        # required True/False to exercise both paths).
        n_co = {"small": 2, "medium": 3, "big": 4,
                "huge": 4, "superhuge": 5, "mega": 5}[profile]
        co_made = 0
        for cl in rng.sample(classes, min(n_co, len(classes))):
            subj_rows = (db.query(models.ClassSubject)
                           .filter(models.ClassSubject.class_id == cl.id)
                           .all())
            if not subj_rows:
                continue
            sr = rng.choice(subj_rows)
            n_h = max(1, min(2, sr.hours_per_week // 2))
            req = rng.random() < 0.6   # mostly HARD
            try:
                db.add(models.CoteachGroup(
                    class_id=cl.id, subject=sr.subject,
                    n_hours=n_h, kind="shared",
                    required=req, weight=80.0))
                co_made += 1
            except Exception:
                pass
        db.commit()
        counts["coteach_group"] = (
            db.query(models.CoteachGroup).count())

        # ---- 6. PlessoCommutingRule ----
        # HARD rule: no commute first/last slot (kind-wide); SOFT
        # rule: penalty 10 per intra-day commute.
        if len(plesso_ids) >= 2:
            db.add(models.PlessoCommutingRule(
                tenant_id=1,
                from_plesso_id=plesso_ids[0],
                to_plesso_id=plesso_ids[1],
                entity_kind="teacher",
                entity_id=None,
                min_gap_hours=1,
                allowed_break_only=False,
                symmetric=True, priority=10,
                notes="stress: HARD min_gap_hours=1 between sites"))
            db.add(models.PlessoCommutingRule(
                tenant_id=1,
                from_plesso_id=plesso_ids[1],
                to_plesso_id=plesso_ids[0],
                entity_kind="class",
                entity_id=None,
                min_gap_hours=0,
                allowed_break_only=True,
                break_start_hour=10, break_end_hour=11,
                symmetric=True, priority=5,
                notes="stress: classe può spostarsi solo nell'intervallo"))
        db.commit()
        counts["plesso_commuting_rule"] = (
            db.query(models.PlessoCommutingRule).count())

        # ---- 7. PlessoEntityPolicy ----
        # 1-2 docenti vincolati HARD a un plesso, 1 classe HARD,
        # 2-3 docenti SOFT-prefer.
        if plesso_ids and teachers:
            for t in teachers[:2]:
                db.add(models.PlessoEntityPolicy(
                    tenant_id=1, entity_kind="teacher",
                    entity_id=t.id, policy="single_plesso_total",
                    plesso_id=plesso_ids[0], priority=10,
                    notes="stress: docente vincolato sede unica"))
        if plesso_ids and classes:
            db.add(models.PlessoEntityPolicy(
                tenant_id=1, entity_kind="class",
                entity_id=classes[0].id,
                policy="single_plesso_total",
                plesso_id=plesso_ids[0], priority=10,
                notes="stress: classe vincolata sede unica"))
        if len(plesso_ids) >= 2 and len(teachers) >= 5:
            for t in teachers[2:5]:
                db.add(models.PlessoEntityPolicy(
                    tenant_id=1, entity_kind="teacher",
                    entity_id=t.id, policy="single_plesso_per_day",
                    plesso_id=None, priority=2,
                    notes="stress: SOFT prefer single plesso per day"))
        db.commit()
        counts["plesso_entity_policy"] = (
            db.query(models.PlessoEntityPolicy).count())

        # ---- 8. TeacherCompatibleClass ----
        # 5-10 entries marking allowed classes for selected teachers.
        n_tcc = min(8, len(teachers), len(classes))
        for t in rng.sample(teachers, n_tcc):
            for cl in rng.sample(classes, min(2, len(classes))):
                try:
                    db.add(models.TeacherCompatibleClass(
                        teacher_id=t.id, class_name=cl.name))
                except Exception:
                    pass
        db.commit()
        counts["teacher_compatible_class"] = (
            db.query(models.TeacherCompatibleClass).count())

        # ---- 9. TeacherClassPreference ----
        # 5-10 entries with mixed states.
        states = ["allowed", "preferred", "soft", "forbidden", "enforced"]
        n_tcp = min(10, len(teachers), len(classes))
        seen_tcp = set()
        for t in rng.sample(teachers, n_tcp):
            cl = rng.choice(classes)
            key = (t.id, cl.name)
            if key in seen_tcp:
                continue
            seen_tcp.add(key)
            st = rng.choice(states)
            pen = (-20.0 if st == "preferred"
                   else 30.0 if st == "soft" else 0.0)
            db.add(models.TeacherClassPreference(
                teacher_id=t.id, class_name=cl.name,
                state=st, soft_penalty=pen))
        db.commit()
        counts["teacher_class_preference"] = (
            db.query(models.TeacherClassPreference).count())

        # ---- 10. LogicalUnavailability ----
        # 1 expression per profile -- DSL string.
        if teachers and day_legacies:
            t = teachers[0]
            d = day_legacies[1] if len(day_legacies) > 1 else day_legacies[0]
            db.add(models.LogicalUnavailability(
                entity_type="teacher", entity_id=t.id,
                expression=f"(d={d} and h<=2)",
                parsed_dnf_json="[]",
                is_hard=True, soft_penalty=0, kind="hard"))
        db.commit()
        counts["logical_unavailability"] = (
            db.query(models.LogicalUnavailability).count())

        # ---- 11. CurriculumLogicalConstraint ----
        curricula = db.query(models.Curriculum).all()
        if curricula:
            cur = curricula[0]
            db.add(models.CurriculumLogicalConstraint(
                curriculum_id=cur.id,
                year_filter=1, label="Mat e Ita non lo stesso giorno (1^)",
                expression="not(same_day(Matematica, Italiano))",
                parsed_dnf_json="[]",
                is_hard=True, soft_penalty=0, kind="hard"))
        db.commit()
        counts["curriculum_logical_constraint"] = (
            db.query(models.CurriculumLogicalConstraint).count())

        # ---- 12. GeneralConstraint (DSL) ----
        gc_examples = [
            ("max 2 hours per day for italian, cross-class",
             "forall l1, l2 in lessons where "
             "l1.subject==Italiano and l2.subject==Italiano and "
             "l1.class==l2.class and l1.day==l2.day: "
             "(l1.hour-l2.hour)<=2",
             "soft", 50),
            ("EduFisica only in palestra",
             "forall l in lessons where l.subject==\"Educazione Fisica\":"
             " l.classroom.kind==\"palestra\"",
             "hard", 0),
            ("Fisica solo in lab fisica",
             "forall l in lessons where l.subject==\"Fisica\":"
             " l.classroom.kind==\"lab_fisica\"",
             "hard", 0),
            ("no first hour for selected teacher",
             "forall l in lessons where l.teacher==\"DocenteX\":"
             " l.hour>=2",
             "soft", 30),
            ("lab classes only morning",
             "forall l in lessons where l.classroom.kind contains lab:"
             " l.hour<=5",
             "soft", 25),
        ]
        for (label, expr, level, weight) in gc_examples:
            db.add(models.GeneralConstraint(
                expression=expr, label=label, level=level,
                weight=weight, scope="global", owner_id=None,
                parsed_ast_json=None))
        db.commit()
        counts["general_constraint"] = (
            db.query(models.GeneralConstraint).count())

        # ---- 13. classroom_capacity_ok pragma -- meta marker only.
        # The pragma is a runtime DSL invocation, not a stored row.
        # We surface its presence in the manifest as a "1" so the
        # manual stress table can list it.
        counts["pragma_classroom_capacity_ok"] = 1

        # ---- 14. subject_required_kind: counted later in build()
        # because it lives on Subject, not its own table. Initialised
        # here to 0 to keep dict shape stable; build() overwrites.
        counts["subject_required_kind"] = 0
    return counts


def _pickle_deprecated_md(profile: str, manifest: dict) -> str:
    return f"""# PICKLE_DEPRECATED -- profilo `{profile}`

Da questo commit la fonte di verità per il profilo `{profile}` è
**`{profile}.sqlite`** (costruito da
`engine/scripts/build_profile_db.py`). I file `school_{profile}.pkl` /
`profs_{profile}.pkl` restano nel repository per finalità di audit
storico, ma:

- **non vengono più letti** dall'import di default in
  `webui/backend/optimization.py::import_engine_profile`. Il fallback
  pickle è attivo solo se lo SQLite non esiste in
  `engine/scripts/data/{profile}/`.
- non hanno mai contenuto i dati di vincolo (`TeacherUnavailability`,
  `CoteachGroup`, ecc.), che ora vivono nel SQLite generati con
  fixture deterministiche (seed=42).

Per rigenerare lo SQLite di questo profilo:

```
python -m engine.scripts.build_profile_db {profile}
```

## Snapshot stress (manifest)

| chiave | valore |
| --- | --- |
| schedule | `{manifest['schedule_label']}` |
| n_classes | {manifest['n_classes']} |
| n_teachers | {manifest['n_teachers']} |
| n_classrooms | {manifest['n_classrooms']} |
| n_plessi | {manifest['n_plessi']} |
| n_palestre | {manifest['n_classrooms_palestra']} |
| n_lab | {manifest['n_classrooms_lab']} |
| n_aula_speciale | {manifest['n_classrooms_auditorium']} |
| n_students range | {manifest['n_students_range']['min']}–{manifest['n_students_range']['max']} |
| capacity range | {manifest['capacity_range']['min']}–{manifest['capacity_range']['max']} |
| n_lessons | {manifest['n_lessons']} |

Per ogni tabella di vincoli:

| tabella | righe |
| --- | --- |
""" + "".join(
    f"| {k} | {v} |\n" for k, v in manifest['fixtures'].items()
) + """

`seed=42` -- una build successiva produrrà esattamente gli stessi
numeri.
"""


# ---------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Build a self-contained SQLite snapshot of an "
                    "engine profile (data + 14 constraint tables + "
                    "WorkingDay/Slot + manifest + deprecation note).")
    ap.add_argument("profile", nargs="?",
                    help=f"one of {PROFILES}")
    ap.add_argument("--all", action="store_true",
                    help="build every profile in turn")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing <profile>.sqlite")
    args = ap.parse_args()

    if args.all:
        # Each profile must run in its OWN process so the
        # PITANTUM_DB_URL env-var pin actually rebinds the
        # SQLAlchemy engine. Re-importing webui.backend.db inside the
        # same process keeps the cached module's engine bound to the
        # first profile, which would cause UNIQUE-constraint failures
        # on the second profile (rows from #1 still in the DB the
        # ORM is talking to).
        import subprocess
        manifests: list[dict] = []
        for p in PROFILES:
            print(f"\n=== {p} (subprocess) ===")
            cmd = [sys.executable, "-m", "engine.scripts.build_profile_db",
                   p, "--seed", str(args.seed)]
            if args.force:
                cmd.append("--force")
            r = subprocess.run(cmd, cwd=ROOT)
            mpath = os.path.join(ENGINE, "scripts", "data", p,
                                 "manifest.json")
            if r.returncode == 0 and os.path.exists(mpath):
                with open(mpath, "r", encoding="utf-8") as f:
                    manifests.append(json.load(f))
            else:
                print(f"[{p}] FAILED (rc={r.returncode})")
        idx_path = os.path.join(ENGINE, "scripts", "data",
                                "profiles_manifest.json")
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(manifests, f, indent=2, ensure_ascii=False)
        print(f"\n[ALL] manifest aggregato -> {idx_path}")
        return
    if not args.profile:
        ap.error("specify a profile or pass --all")
    build(args.profile, seed=args.seed, force=args.force)


if __name__ == "__main__":
    main()
