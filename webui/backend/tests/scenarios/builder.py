"""Scenario framework for end-to-end school tests.

Wraps the existing seed scripts (`big_mock_school` + `seed_curricula`)
into a coherent `Scenario` object whose construction is parameterized
by a `ScenarioConfig` dataclass. Factory helpers for the 3 canonical
schools (liceo_piccolo, liceo_medio, istituto_tecnico) are exposed
alongside knobs for constraint density (compresenze, sostegno,
potenziamento, parallel intra, group inter) and for logistics
(classroom assignment mode, capacities, lab kinds, multi-class
rooms).

Design goals:
  - **Reuse, don't duplicate**: every scenario starts from a profile
    in `big_mock_school.PROFILES` (small / medium / big / huge / mega)
    and adds C1/C2/C3 layers on top; we never re-implement curriculum
    grids or teacher generators.
  - **Solvable by construction**: the default densities are tuned so
    Phase A + Phase B fits in <5min on the medium profile. Tests can
    override densities for stress / infeasibility cases.
  - **Idempotent**: builders accept a clean DB and populate it from
    scratch; running on a non-empty DB clears the relevant tables
    via `engine_io.import_school_into_db(replace=True)`.
"""
from __future__ import annotations

import os
import random
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

# Path bootstrap: the engine + schedule modules live outside webui.
HERE = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HERE)
BACKEND_DIR = os.path.dirname(TESTS_DIR)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
SCHEDULE_DIR = os.path.join(REPO_ROOT, "schedule")
for p in (WEBUI_DIR, ENGINE_DIR, SCHEDULE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


# ----------------------------------------------------------------------
# Config + meta
# ----------------------------------------------------------------------

@dataclass
class ScenarioConfig:
    """All knobs that control a scenario's shape.

    `profile` selects the underlying big_mock_school profile. The
    other fields layer on top: pickling vs DB-bound, the Scenario
    class persists everything to the bound Session.
    """
    profile: str = "small"
    margin: float = 0.25
    rng_seed: int = 42
    phase_a_time_limit: float = 15.0

    # C1: compresenze
    coteach_class_n: int = 0
    coteach_n_hours_each: int = 2

    # C1: sostegno (DVA)
    sostegno_n: int = 0
    sostegno_hours_each: int = 9

    # C1: potenziamento (Legge 107)
    pot_n: int = 0
    pot_hours_each: int = 4

    # C2: parallel intra-class (religione/alternativa)
    parallel_intra_n: int = 0

    # C3: study groups inter-class
    study_groups_n: int = 0
    study_group_hours: int = 3
    study_group_students: int = 10

    # Logistics: classroom assignment style
    # "open" -- classes don't have a home classroom; the solver is
    #          free to assign any compatible room.
    # "per_class" -- each class gets a home classroom.
    # "per_subject" -- subject -> classroom prefs are HARD/preferred
    #                  for math, italian, lab subjects.
    classroom_assignment_mode: str = "open"

    # Capacity distribution: when "varied", classes get n_students
    # in [16, 32]; rooms get capacity in [20, 36]. Default
    # "uniform_22" leaves the default 22.
    student_count_distribution: str = "uniform_22"

    # Lab availability (created post-import as extra Classroom rows).
    n_lab_chimica: int = 0
    n_lab_fisica: int = 0
    n_lab_biologia: int = 0
    n_lab_informatica: int = 0
    n_palestre: int = 0
    palestra_multi_class: bool = True


@dataclass
class ScenarioMeta:
    """Counts produced by the builder. Tests can use this to assert
    that the requested density was achieved (e.g. coteach_class_n
    might be capped if there aren't enough lab Assignments available)."""

    profile: str = ""
    n_classes: int = 0
    n_teachers: int = 0
    n_subjects: int = 0
    n_assignments: int = 0
    n_coteach_groups_class: int = 0
    n_sostegno_class: int = 0
    n_potenziamento: int = 0
    n_parallel_intra: int = 0
    n_study_groups: int = 0
    n_group_assignments: int = 0
    n_classrooms: int = 0
    n_classroom_subject_prefs: int = 0
    notes: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------
# Atomic builders (private)
# ----------------------------------------------------------------------

def _import_base_school(db, profile: str, margin: float
                         ) -> tuple[int, int]:
    import big_mock_school as bms                # type: ignore
    from backend import engine_io
    school = bms.build_dataset(profile, tight=True, margin=margin,
                                mode="tight")
    engine_io.import_school_into_db(db, school, replace=True)
    db.commit()
    return len(school["classes"]), len(school["teachers"])


def _run_phase_a_in_proc(db, time_limit: float) -> int:
    from backend import engine_io, models
    import cpsat_v2_assignment as ca             # type: ignore

    data = engine_io.school_dict_from_db(db)
    if not data["classes"] or not data["teachers"]:
        return 0
    cattedre, _solver, status = ca.solve_assignment(
        data, time_limit_s=time_limit, workers=4, log=False,
    )
    teachers = {t.name: t for t in db.query(models.Teacher).all()}
    classes = {c.name: c for c in db.query(models.SchoolClass).all()}
    db.query(models.Assignment).delete()
    db.flush()
    n = 0
    # cattedre shape: {teacher_name: {class_name: {subject: hours}}}
    for tname, by_class in cattedre.items():
        t = teachers.get(tname)
        if t is None or not isinstance(by_class, dict):
            continue
        for clname, by_subj in by_class.items():
            c = classes.get(clname)
            if c is None or not isinstance(by_subj, dict):
                continue
            for subj, ore in by_subj.items():
                db.add(models.Assignment(
                    teacher_id=t.id, class_id=c.id,
                    subject=subj, hours=int(ore), locked=False,
                ))
                n += 1
    db.commit()
    return n


def _add_coteach_class(db, n: int, *, n_hours_each: int,
                        rng: random.Random) -> int:
    from backend import models
    lab_subjects = ["Fisica", "Chimica", "Scienzenaturali",
                     "Biologia", "Matematica", "Informatica"]
    candidates = []
    for a in db.query(models.Assignment).all():
        if a.subject in lab_subjects and a.hours >= n_hours_each + 1:
            candidates.append(a)
    rng.shuffle(candidates)
    teachers_by_id = {t.id: t for t in db.query(models.Teacher).all()}
    teachers = list(teachers_by_id.values())
    placed = 0
    for principal_a in candidates:
        if placed >= n:
            break
        existing = db.query(models.CoteachGroup).filter(
            models.CoteachGroup.class_id == principal_a.class_id,
            models.CoteachGroup.subject == principal_a.subject,
        ).first()
        if existing is not None:
            continue
        codoc_candidates = [
            t for t in teachers
            if t.id != principal_a.teacher_id
            and any(ts.subject == principal_a.subject
                    for ts in t.subjects)
        ]
        if not codoc_candidates:
            continue
        codoc = rng.choice(codoc_candidates)
        cg = models.CoteachGroup(
            class_id=principal_a.class_id,
            subject=principal_a.subject,
            n_hours=n_hours_each, kind="shared",
            required=True, weight=100.0,
        )
        db.add(cg)
        db.flush()
        principal_a.coteach_group_id = cg.id
        db.add(models.Assignment(
            teacher_id=codoc.id, class_id=principal_a.class_id,
            subject=principal_a.subject,
            hours=n_hours_each, locked=False,
            coteach_group_id=cg.id,
        ))
        placed += 1
    db.commit()
    return placed


def _add_sostegno_class(db, n: int, *, hours_each: int,
                         rng: random.Random) -> int:
    from backend import models
    classes = list(db.query(models.SchoolClass).all())
    rng.shuffle(classes)
    teachers = list(db.query(models.Teacher).all())
    rng.shuffle(teachers)
    placed = 0
    teacher_idx = 0
    for cl in classes[:n]:
        if teacher_idx >= len(teachers):
            break
        t = teachers[teacher_idx]
        teacher_idx += 1
        db.add(models.Assignment(
            teacher_id=t.id, class_id=cl.id,
            subject="sostegno", hours=hours_each,
            locked=False, is_support=True,
        ))
        placed += 1
    db.commit()
    return placed


def _add_potenziamento(db, n: int, *, hours_each: int,
                        rng: random.Random) -> int:
    from backend import models
    teachers = list(db.query(models.Teacher).all())
    rng.shuffle(teachers)
    placed = 0
    for t in teachers[:n]:
        db.add(models.Assignment(
            teacher_id=t.id, class_id=None,
            subject="Potenziamento", hours=hours_each,
            locked=False, is_potenziamento=True,
        ))
        placed += 1
    db.commit()
    return placed


def _add_parallel_intra(db, n: int, *,
                         rng: random.Random) -> int:
    """Mark `n` classes' Religione/Alternativa as a parallel intra
    group. The Phase A assignment may already have produced a
    Religione Assignment for these classes; we DELETE it and replace
    with two parallel-tied Assignments (Religione + Alternativa).
    Classes with no existing Religione Assignment are skipped (the
    big_mock curricula always include Religione 1h, but defensive).
    """
    from backend import models
    classes = list(db.query(models.SchoolClass).all())
    rng.shuffle(classes)
    teachers = list(db.query(models.Teacher).all())
    if not teachers:
        return 0
    placed = 0
    next_pid = 1000
    for cl in classes:
        if placed >= n:
            break
        # Find the existing Religione Assignment (if any)
        rel_existing = db.query(models.Assignment).filter(
            models.Assignment.class_id == cl.id,
            models.Assignment.subject == "Religione",
        ).first()
        if rel_existing is None:
            continue                    # no Religione triple to convert
        # Pick the alternative teacher: a teacher OTHER than the
        # Religione one. The big_mock teacher pool typically has many
        # idle profs at small profiles; any will do.
        t_rel_id = rel_existing.teacher_id
        candidates = [t for t in teachers if t.id != t_rel_id]
        if not candidates:
            continue
        t_alt = rng.choice(candidates)
        # Delete the existing Religione (it had no parallel_group_id)
        # and re-create both with the same parallel_group_id.
        db.delete(rel_existing)
        db.flush()
        db.add(models.Assignment(
            teacher_id=t_rel_id, class_id=cl.id,
            subject="Religione", hours=1, locked=False,
            parallel_group_id=next_pid,
        ))
        # Alternativa gets a brand-new (subject) row for the same
        # class. The unique constraint is (teacher, class, subject,
        # is_support) so we just need a different subject string.
        db.add(models.Assignment(
            teacher_id=t_alt.id, class_id=cl.id,
            subject="Alternativa", hours=1, locked=False,
            parallel_group_id=next_pid,
        ))
        next_pid += 1
        placed += 1
    db.commit()
    return placed


def _add_study_groups(db, n: int, *,
                       students_per_group: int, hours: int,
                       rng: random.Random) -> tuple[int, int]:
    from backend import models
    subjects = ["Spagnolo", "Tedesco", "Recupero", "Approfondimento"]
    classes = list(db.query(models.SchoolClass).all())
    teachers = list(db.query(models.Teacher).all())
    if len(classes) < 2 or not teachers:
        return 0, 0
    n_grp = 0
    n_grp_a = 0
    for i in range(n):
        subj = subjects[i % len(subjects)]
        gname = f"_GR_{subj}_{i}"
        if db.query(models.StudyGroup).filter(
                models.StudyGroup.name == gname).first():
            continue
        sg = models.StudyGroup(name=gname, kind="splitting")
        db.add(sg)
        db.flush()
        c1, c2 = rng.sample(classes, 2)
        for cl in (c1, c2):
            existing_n = db.query(models.Student).filter(
                models.Student.class_id == cl.id).count()
            need = max(0, (students_per_group // 2) - existing_n)
            for k in range(need):
                db.add(models.Student(
                    first_name=f"Stu{i}_{k}",
                    last_name=f"Cl{cl.id}",
                    class_id=cl.id,
                ))
            db.flush()
        members_c1 = (db.query(models.Student)
                       .filter(models.Student.class_id == c1.id)
                       .limit(students_per_group // 2).all())
        members_c2 = (db.query(models.Student)
                       .filter(models.Student.class_id == c2.id)
                       .limit(students_per_group // 2).all())
        for s in members_c1 + members_c2:
            db.add(models.GroupMembership(group_id=sg.id,
                                            student_id=s.id))
        db.add(models.GroupSubjectHours(
            group_id=sg.id, subject=subj,
            hours_per_week=hours,
        ))
        t = rng.choice(teachers)
        db.add(models.Assignment(
            teacher_id=t.id, class_id=None, group_id=sg.id,
            subject=subj, hours=hours, locked=False,
        ))
        n_grp += 1
        n_grp_a += 1
    db.commit()
    return n_grp, n_grp_a


def _add_classrooms(db, *,
                     n_lab_chimica: int, n_lab_fisica: int,
                     n_lab_biologia: int, n_lab_informatica: int,
                     n_palestre: int, palestra_multi_class: bool,
                     student_count_distribution: str,
                     rng: random.Random) -> tuple[int, int]:
    """Layer additional Classrooms on top of whatever big_mock
    produced (typically 0). Each lab gets `kind` set to its name
    so ClassroomSubjectPreference for that subject can target it.
    Returns (n_classrooms_added, n_subject_prefs_added).
    """
    from backend import models
    n_added = 0
    n_prefs = 0

    def _add(name, kind, capacity, multi_class=False, multi_max=1,
             multi_pref=1):
        nonlocal n_added
        existing = db.query(models.Classroom).filter(
            models.Classroom.name == name).first()
        if existing:
            return
        db.add(models.Classroom(
            name=name, kind=kind,
            capacity=capacity, multi_class=multi_class,
            multi_class_max=multi_max,
            multi_class_pref=multi_pref,
        ))
        n_added += 1

    for i in range(n_lab_chimica):
        _add(f"LabChim{i+1}", "lab_chimica", 24)
    for i in range(n_lab_fisica):
        _add(f"LabFis{i+1}", "lab_fisica", 24)
    for i in range(n_lab_biologia):
        _add(f"LabBio{i+1}", "lab_biologia", 22)
    for i in range(n_lab_informatica):
        _add(f"LabInf{i+1}", "lab_informatica", 26)
    for i in range(n_palestre):
        _add(f"Palestra{i+1}", "palestra", 60,
             multi_class=palestra_multi_class,
             multi_max=2 if palestra_multi_class else 1,
             multi_pref=2 if palestra_multi_class else 1)
    db.flush()

    # Wire subject -> lab kind preferences (HARD ENFORCED for lab
    # subjects so the assigner gives them lab rooms).
    rooms_by_kind: dict[str, list[models.Classroom]] = {}
    for r in db.query(models.Classroom).all():
        rooms_by_kind.setdefault(r.kind, []).append(r)

    def _pref(subject: str, kind: str, state: str = "preferred",
              weight: float = 1.0):
        nonlocal n_prefs
        for r in rooms_by_kind.get(kind, []):
            existing = db.query(
                models.ClassroomSubjectPreference).filter(
                models.ClassroomSubjectPreference.classroom_id == r.id,
                models.ClassroomSubjectPreference.subject == subject,
            ).first()
            if existing:
                continue
            db.add(models.ClassroomSubjectPreference(
                classroom_id=r.id, subject=subject,
                state=state, weight=weight,
            ))
            n_prefs += 1
    if n_lab_chimica:
        _pref("Chimica", "lab_chimica", "preferred", 5.0)
    if n_lab_fisica:
        _pref("Fisica", "lab_fisica", "preferred", 5.0)
    if n_lab_biologia:
        _pref("Biologia", "lab_biologia", "preferred", 5.0)
        _pref("Scienzenaturali", "lab_biologia", "preferred", 3.0)
    if n_lab_informatica:
        _pref("Informatica", "lab_informatica", "preferred", 5.0)
    if n_palestre:
        _pref("Scienzemotorie", "palestra", "enforced", 10.0)

    # Vary student/room capacity if requested.
    if student_count_distribution == "varied":
        for cl in db.query(models.SchoolClass).all():
            cl.n_students = rng.choice([16, 22, 25, 28, 32])
        for r in db.query(models.Classroom).all():
            if r.kind not in ("palestra",):
                r.capacity = rng.choice([20, 25, 28, 30, 35])
    db.commit()
    return n_added, n_prefs


# ----------------------------------------------------------------------
# Public Scenario class + factory functions
# ----------------------------------------------------------------------

class Scenario:
    """A built scenario: holds the config, the meta, and the db
    Session it was built into. Also provides a `solver_inputs()`
    helper that returns the (profs, coteach, support, pot, par,
    grp) tuple used by every test assertion."""

    def __init__(self, db, config: ScenarioConfig, meta: ScenarioMeta):
        self.db = db
        self.config = config
        self.meta = meta

    def solver_inputs(self):
        from backend import engine_io
        profs = engine_io.profs_dict_from_db(self.db)
        coteach = engine_io.coteach_groups_for_solver(self.db) or None
        support = engine_io.support_assignments_from_db(self.db) or None
        pot = engine_io.potenziamento_assignments_from_db(self.db) or None
        par = engine_io.parallel_groups_for_solver(self.db) or None
        grp = engine_io.group_assignments_for_solver(self.db) or None
        return profs, coteach, support, pot, par, grp

    @classmethod
    def build(cls, db, config: ScenarioConfig) -> "Scenario":
        meta = ScenarioMeta(profile=config.profile)
        n_cl, n_t = _import_base_school(
            db, config.profile, config.margin)
        meta.n_classes = n_cl
        meta.n_teachers = n_t
        meta.n_assignments = _run_phase_a_in_proc(
            db, config.phase_a_time_limit)
        if config.coteach_class_n > 0:
            meta.n_coteach_groups_class = _add_coteach_class(
                db, config.coteach_class_n,
                n_hours_each=config.coteach_n_hours_each,
                rng=random.Random(config.rng_seed + 100))
        if config.sostegno_n > 0:
            meta.n_sostegno_class = _add_sostegno_class(
                db, config.sostegno_n,
                hours_each=config.sostegno_hours_each,
                rng=random.Random(config.rng_seed + 200))
        if config.pot_n > 0:
            meta.n_potenziamento = _add_potenziamento(
                db, config.pot_n,
                hours_each=config.pot_hours_each,
                rng=random.Random(config.rng_seed + 300))
        if config.parallel_intra_n > 0:
            meta.n_parallel_intra = _add_parallel_intra(
                db, config.parallel_intra_n,
                rng=random.Random(config.rng_seed + 400))
        if config.study_groups_n > 0:
            n_grp, n_grp_a = _add_study_groups(
                db, config.study_groups_n,
                students_per_group=config.study_group_students,
                hours=config.study_group_hours,
                rng=random.Random(config.rng_seed + 500))
            meta.n_study_groups = n_grp
            meta.n_group_assignments = n_grp_a
        if (config.n_lab_chimica or config.n_lab_fisica
                or config.n_lab_biologia or config.n_lab_informatica
                or config.n_palestre):
            n_room, n_pref = _add_classrooms(
                db,
                n_lab_chimica=config.n_lab_chimica,
                n_lab_fisica=config.n_lab_fisica,
                n_lab_biologia=config.n_lab_biologia,
                n_lab_informatica=config.n_lab_informatica,
                n_palestre=config.n_palestre,
                palestra_multi_class=config.palestra_multi_class,
                student_count_distribution=(
                    config.student_count_distribution),
                rng=random.Random(config.rng_seed + 600))
            meta.n_classrooms = n_room
            meta.n_classroom_subject_prefs = n_pref

        from backend import models
        meta.n_subjects = db.query(models.Subject).count()
        meta.notes.append(
            f"profile={meta.profile} cl={meta.n_classes} "
            f"t={meta.n_teachers} a={meta.n_assignments} "
            f"cot={meta.n_coteach_groups_class} "
            f"sos={meta.n_sostegno_class} pot={meta.n_potenziamento} "
            f"par={meta.n_parallel_intra} "
            f"grp={meta.n_study_groups} "
            f"rooms+={meta.n_classrooms}"
        )
        return cls(db, config, meta)


# ----------------------------------------------------------------------
# Canonical school factories. Densities tuned so Phase A + Phase B
# fits in <5min on a developer machine.
# ----------------------------------------------------------------------

def liceo_piccolo(**overrides) -> ScenarioConfig:
    """Liceo piccolo: small profile (~10 classes, 25 teachers).
    Conservative C1/C2/C3 mix: solvable in ~30s."""
    base = ScenarioConfig(
        profile="small",
        margin=0.25,
        phase_a_time_limit=15.0,
        coteach_class_n=3, coteach_n_hours_each=2,
        sostegno_n=1, sostegno_hours_each=6,
        pot_n=0,
        parallel_intra_n=0,
        study_groups_n=0,
        n_lab_chimica=1, n_lab_fisica=1, n_lab_informatica=0,
        n_palestre=1,
        student_count_distribution="uniform_22",
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def liceo_medio(**overrides) -> ScenarioConfig:
    """Liceo medio: medium profile (~25 classes, ~57 teachers).
    Mid C1/C2/C3 mix: solvable in ~2min."""
    base = ScenarioConfig(
        profile="medium",
        margin=0.30,
        phase_a_time_limit=30.0,
        coteach_class_n=3, coteach_n_hours_each=2,
        sostegno_n=2, sostegno_hours_each=6,
        pot_n=1, pot_hours_each=4,
        parallel_intra_n=4,
        study_groups_n=1, study_group_hours=2,
        study_group_students=6,
        n_lab_chimica=2, n_lab_fisica=2, n_lab_biologia=1,
        n_lab_informatica=1, n_palestre=2,
        student_count_distribution="uniform_22",
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def istituto_tecnico(**overrides) -> ScenarioConfig:
    """ITP-like: big profile (~35 classes, ~74 teachers) with
    denser lab + compresenza mix simulating a tecnico/professionale.
    Solvable in ~5min."""
    base = ScenarioConfig(
        profile="big",
        margin=0.35,
        phase_a_time_limit=45.0,
        coteach_class_n=6, coteach_n_hours_each=2,
        sostegno_n=3, sostegno_hours_each=6,
        pot_n=2, pot_hours_each=4,
        parallel_intra_n=6,
        study_groups_n=2, study_group_hours=2,
        study_group_students=8,
        n_lab_chimica=3, n_lab_fisica=3, n_lab_biologia=2,
        n_lab_informatica=4, n_palestre=2,
        palestra_multi_class=True,
        student_count_distribution="varied",
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


# Legacy name kept for backward compat with existing WIP test.
def build_scenario(db, kind: str, **kwargs) -> ScenarioMeta:
    factories = {
        "liceo_piccolo": liceo_piccolo,
        "liceo_medio": liceo_medio,
        "istituto_tecnico": istituto_tecnico,
    }
    if kind not in factories:
        raise ValueError(f"Unknown scenario: {kind!r}; "
                          f"available: {list(factories)}")
    cfg = factories[kind](**kwargs)
    sc = Scenario.build(db, cfg)
    return sc.meta
