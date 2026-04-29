"""Pydantic schemas (request/response). Kept compact: most CRUD endpoints
just expose the SQLAlchemy field set without further nesting."""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------- Subject ----------


class SubjectBase(BaseModel):
    name: str
    pretty_name: str | None = None
    notes: str | None = None
    distribute_days_weight: float = 0.0
    dual_hours_weight: float = 0.0
    no_sixth_hour_weight: float = 0.0
    preferred_band_start: int | None = None
    preferred_band_end: int | None = None
    preferred_band_weight: float = 0.0


class SubjectIn(SubjectBase):
    pass


class SubjectOut(SubjectBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# ---------- Teacher ----------


class UnavailabilitySlot(BaseModel):
    """3-state availability cell. state in {'hard','soft'}; absence == free."""
    day: int
    hour: int
    state: str = "hard"
    soft_penalty: int = 100
    reason: str | None = None


class TeacherBase(BaseModel):
    name: str
    last_name: str | None = None
    first_name: str | None = None
    nickname: str | None = None
    matricola: str | None = None
    group: str | None = None
    max_hours: int = 18
    completion_hours: int = 0
    exemption_hours: int = 0
    free_day: str | None = None
    max_consecutive: int = 5
    notes: str | None = None
    pref_no_buchi_weight: float = 10.0
    pref_no_five_weight: float = 30.0
    pref_no_one_weight: float = 80.0
    preferred_days_csv: str | None = None


class TeacherIn(TeacherBase):
    subjects: list[str] = Field(default_factory=list)
    unavailability: list[UnavailabilitySlot] = Field(default_factory=list)
    mandatory_free_days: list[int] = Field(default_factory=list)
    compatible_classes: list[str] = Field(default_factory=list)


class TeacherOut(TeacherBase):
    id: int
    subjects: list[str] = Field(default_factory=list)
    unavailability: list[UnavailabilitySlot] = Field(default_factory=list)
    mandatory_free_days: list[int] = Field(default_factory=list)
    compatible_classes: list[str] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


# ---------- Class ----------


class ClassSubjectIn(BaseModel):
    subject: str
    hours_per_week: int


class ClassBase(BaseModel):
    name: str
    nickname: str | None = None
    year: int = 1
    section: str | None = None
    curriculum: str | None = None
    curriculum_id: int | None = None
    n_students: int = 20
    notes: str | None = None
    hard_entry_at_8: bool = True
    hard_exit_after_12: bool = True
    hard_no_holes: bool = True
    hard_dual_math: bool = True
    hard_dual_italian: bool = True
    hard_motorie_pairs: bool = True
    hard_max_6_per_day: bool = True
    soft_minimize_sixth_weight: float = 50.0


class ClassIn(ClassBase):
    subjects: list[ClassSubjectIn] = Field(default_factory=list)
    unavailability: list[UnavailabilitySlot] = Field(default_factory=list)


class ClassOut(ClassBase):
    id: int
    subjects: list[ClassSubjectIn] = Field(default_factory=list)
    unavailability: list[UnavailabilitySlot] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


# ---------- Subject group weight ----------


class SubjectGroupWeightIn(BaseModel):
    subject: str
    group_name: str
    weight: int = 1


class SubjectGroupWeightOut(SubjectGroupWeightIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


# ---------- Assignment ----------


class AssignmentIn(BaseModel):
    teacher_name: str
    class_name: str
    subject: str
    hours: int
    locked: bool = False


class AssignmentOut(BaseModel):
    id: int
    teacher_name: str
    class_name: str
    subject: str
    hours: int
    locked: bool
    model_config = ConfigDict(from_attributes=True)


# ---------- Solution / Lessons ----------


class LessonOut(BaseModel):
    teacher_name: str
    class_name: str
    subject: str
    day: int
    hour: int


class SolutionOut(BaseModel):
    id: int
    name: str
    kind: str
    obj_value: float
    metrics: dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    created_at: dt.datetime
    notes: str | None = None


# ---------- Run ----------


class RunOut(BaseModel):
    id: int
    kind: str
    name: str
    profile: str | None
    params: dict[str, Any]
    status: str
    progress: float
    obj_value: float | None
    metrics: dict[str, Any]
    error: str | None
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    created_at: dt.datetime
    solution_id: int | None


# ---------- Mock generation request ----------


class MockGenIn(BaseModel):
    """Built-in profile or custom curriculum dictionary."""
    profile: str = "small"
    mode: str = "aggregated"  # aggregated | tight | legacy
    margin: float = 0.05
    custom_curricula: dict[str, int] | None = None
    base_max_hours: int = 18
    """If profile == 'custom', custom_curricula must be a mapping
    curriculum-name -> n_sections; one class per (year 1..5, section)
    will be generated."""


# ---------- Optimization run requests ----------


class AssignmentRunIn(BaseModel):
    time_limit_s: float = 30.0
    workers: int = 8
    log: bool = True


class PhaseBRunIn(BaseModel):
    k: int = 4
    time_a: float = 60.0
    time_bridges: float = 30.0
    time_cluster: float = 20.0
    time_ricucitura: float = 60.0
    time_mono: float = 120.0
    workers: int = 8
    log: bool = False
    use_decomposition: bool = True


class MetaRunIn(BaseModel):
    """LNS / SA / TS / ILS step."""
    budget_s: float = 60.0
    workers: int = 4
    log: bool = True
    # ILS-only:
    n_cycles: int = 3
    ts_budget_per_cycle: float = 20.0
    # SA-only:
    sa_T0: float = 10.0
    sa_alpha: float = 0.995
    # TS-only:
    tabu_size: int = 80


class FullPipelineIn(BaseModel):
    profile: str = "small"
    workers: int = 8
    time_assign: float = 30.0
    phase_b: PhaseBRunIn = Field(default_factory=PhaseBRunIn)
    budget_lns: float = 60.0
    budget_sa: float = 30.0
    budget_ts: float = 30.0
    budget_ils: float = 60.0


class ImportPickleIn(BaseModel):
    profile: str = "small"
    use_optimized: bool = True
    """When true and an optimized pkl exists, import it as the active
    solution. Otherwise import the decomposed pkl."""
    # Extra "pool" data to import alongside school + profs:
    import_curricula: bool = True
    """Seed indirizzi (idempotent) and link curriculum_id on each class."""
    import_classrooms: bool = True
    """Auto-generate classrooms via the standard recipe (one per class +
    proportional labs/palestre/biblioteca)."""
    import_students: bool = True
    """Generate fake students for each class using Faker, sized after
    `n_students` on each class."""
    students_seed: int = 42
    """Random seed for the student generator (deterministic output)."""


# ---------- Schedule view filters ----------


class FreeNowOut(BaseModel):
    day: int
    hour: int
    free_teachers: list[dict[str, Any]] = Field(default_factory=list)
    free_classes: list[dict[str, Any]] = Field(default_factory=list)
    busy_teachers: list[dict[str, Any]] = Field(default_factory=list)
    busy_classes: list[dict[str, Any]] = Field(default_factory=list)


class MoveLessonIn(BaseModel):
    teacher_name: str
    class_name: str
    subject: str
    src_day: int
    src_hour: int
    dst_day: int
    dst_hour: int


class MoveLessonOut(BaseModel):
    accepted: bool
    reason: str
    obj_before: float | None = None
    obj_after: float | None = None
    delta: float | None = None
    metrics_before: dict[str, Any] = Field(default_factory=dict)
    metrics_after: dict[str, Any] = Field(default_factory=dict)


# ---------- Manual assignment override validation ----------


class ManualAssignmentIn(BaseModel):
    """Replace the teacher of a (class, subject) pair. Hours come from the
    class subject definition."""
    class_name: str
    subject: str
    teacher_name: str
    locked: bool = True


class ManualAssignmentOut(BaseModel):
    accepted: bool
    reason: str
    new_assignment: AssignmentOut | None = None


# ---------- Classrooms ----------


class ClassroomSubjectPrefIn(BaseModel):
    subject: str
    weight: float = 10.0
    required: bool = False


class ClassroomClassPrefIn(BaseModel):
    class_name: str
    weight: float = 20.0
    is_home: bool = False


class ClassroomBase(BaseModel):
    name: str
    kind: str = "standard"
    capacity: int = 30
    multi_class: bool = False
    multi_class_max: int = 1
    multi_class_pref: int = 1
    multi_class_pref_weight: float = 10.0
    notes: str | None = None


class ClassroomIn(ClassroomBase):
    subject_prefs: list[ClassroomSubjectPrefIn] = Field(default_factory=list)
    class_prefs: list[ClassroomClassPrefIn] = Field(default_factory=list)
    unavailability: list[UnavailabilitySlot] = Field(default_factory=list)


class ClassroomOut(ClassroomBase):
    id: int
    subject_prefs: list[ClassroomSubjectPrefIn] = Field(default_factory=list)
    class_prefs: list[ClassroomClassPrefIn] = Field(default_factory=list)
    unavailability: list[UnavailabilitySlot] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


# ---------- Co-teaching ----------


class CoTeachingIn(BaseModel):
    class_name: str
    subject: str
    required: bool = True
    weight: float = 100.0
    n_teachers: int = 2
    teachers: list[str] = Field(default_factory=list)


class CoTeachingOut(BaseModel):
    id: int
    class_name: str
    subject: str
    required: bool
    weight: float
    n_teachers: int
    teachers: list[str]


# ---------- Classroom assignment run ----------


class ClassroomAssignRunIn(BaseModel):
    time_limit_s: float = 30.0
    workers: int = 4
    log: bool = True
    prefer_home: bool = True
    """If true, assign each non-lab lesson to the class's home room."""


# ---------- Mock generation: extra parameters for classrooms ----------


class LogicalUnavIn(BaseModel):
    """A logical (disjunctive) unavailability constraint."""
    expression: str
    is_hard: bool = True
    soft_penalty: int = 100


class LogicalUnavOut(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    expression: str
    pretty: str
    clauses: list[list[dict[str, Any]]] = Field(default_factory=list)
    is_hard: bool
    soft_penalty: int


class LogicValidateIn(BaseModel):
    expression: str


class LogicValidateOut(BaseModel):
    ok: bool
    expression: str
    pretty: str | None = None
    clauses: list[list[dict[str, Any]]] | None = None
    error: str | None = None


# ---------- Curricula (indirizzi) ----------


class CurriculumSubjectHoursIn(BaseModel):
    year: int
    subject: str
    hours_per_week: int = 0


class CurriculumLogicalConstraintIn(BaseModel):
    year_filter: int | None = None
    label: str | None = None
    expression: str
    is_hard: bool = True
    soft_penalty: int = 100


class CurriculumLogicalConstraintOut(BaseModel):
    id: int
    curriculum_id: int
    year_filter: int | None
    label: str | None
    expression: str
    pretty: str
    clauses: list[list[dict[str, Any]]] = Field(default_factory=list)
    is_hard: bool
    soft_penalty: int


class CurriculumBase(BaseModel):
    code: str
    name: str
    description: str | None = None
    notes: str | None = None
    score: int = 1


class CurriculumIn(CurriculumBase):
    hours: list[CurriculumSubjectHoursIn] = Field(default_factory=list)


class CurriculumOut(CurriculumBase):
    id: int
    hours: list[CurriculumSubjectHoursIn] = Field(default_factory=list)
    n_classes: int = 0
    model_config = ConfigDict(from_attributes=True)


# ---------- Students ----------


class StudentBase(BaseModel):
    last_name: str
    first_name: str
    nickname: str | None = None
    birth_date: dt.date | None = None
    gender: str | None = None
    email: str | None = None
    student_code: str | None = None
    class_id: int | None = None
    notes: str | None = None


class StudentIn(StudentBase):
    pass


class StudentOut(StudentBase):
    id: int
    class_name: str | None = None
    n_groups: int = 0
    model_config = ConfigDict(from_attributes=True)


# ---------- Study groups ----------


class GroupSubjectHoursIn(BaseModel):
    subject: str
    hours_per_week: int = 1


class StudyGroupBase(BaseModel):
    name: str
    nickname: str | None = None
    kind: str = "splitting"
    description: str | None = None
    notes: str | None = None


class StudyGroupIn(StudyGroupBase):
    student_ids: list[int] = Field(default_factory=list)
    subject_hours: list[GroupSubjectHoursIn] = Field(default_factory=list)


class StudyGroupOut(StudyGroupBase):
    id: int
    student_ids: list[int] = Field(default_factory=list)
    subject_hours: list[GroupSubjectHoursIn] = Field(default_factory=list)
    n_students: int = 0
    n_classes_touched: int = 0
    model_config = ConfigDict(from_attributes=True)


# ---------- Excel/CSV import ----------


class ImportReport(BaseModel):
    """Result of an Excel/CSV import. Inserted/updated/skipped counts and
    a list of human-readable messages for the user."""
    ok: bool
    entity: str
    n_inserted: int = 0
    n_updated: int = 0
    n_skipped: int = 0
    n_total_rows: int = 0
    messages: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class MockClassroomsIn(BaseModel):
    """Auto-generate classrooms for the current school. The recipe scales
    proportionally with the number of classes in the DB; any field left
    None below falls back to the proportional default. The user fills the
    UI form with the suggested counts (returned by GET
    /api/classrooms/suggested-counts) and tweaks them before clicking
    Generate."""
    n_lab_chimica: int | None = None
    n_lab_fisica: int | None = None
    n_lab_informatica: int | None = None
    n_lab_linguistico: int | None = None
    n_palestra: int | None = None
    n_biblioteca: int | None = None
    n_aula_speciale: int | None = None
