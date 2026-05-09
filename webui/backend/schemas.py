"""Pydantic schemas (request/response). Kept compact: most CRUD endpoints
just expose the SQLAlchemy field set without further nesting."""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------- Error response (Section 2.3 P2) ----------


class ErrorDetail(BaseModel):
    """A single error item. Used by ErrorResponse.errors[]."""
    msg: str
    field: str | None = Field(
        default=None,
        description="Path to the offending field, if known "
                    "(e.g. 'body.max_hours')",
    )
    type: str | None = Field(
        default=None,
        description="Error category (e.g. 'value_error', "
                    "'integrity_error', 'not_found')",
    )


class ErrorResponse(BaseModel):
    """Uniform error envelope returned by global exception handlers.

    Frontend `formatApiError()` already understands `{detail: string}`,
    `{detail: [{loc, msg, type}]}` (FastAPI/Pydantic native), and
    `{error: string}`. This `ErrorResponse` is the new canonical shape;
    the previous shapes remain accepted for backward compatibility.
    """
    detail: str = Field(description="Human-readable summary")
    code: str | None = Field(
        default=None,
        description="Stable machine code (e.g. 'integrity_error', "
                    "'not_found', 'validation_error', 'internal_error')",
    )
    errors: list[ErrorDetail] | None = Field(
        default=None,
        description="Per-field details for validation errors",
    )
    hint: str | None = Field(
        default=None,
        description="Optional next-step suggestion shown to the user",
    )
    request_id: str | None = Field(
        default=None,
        description="Correlation id from the X-Request-Id header",
    )


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


class SubjectClassroomPrefIn(BaseModel):
    classroom_name: str
    state: str = "allowed"   # allowed | preferred | forbidden | enforced
    weight: float = 10.0


class SubjectIn(SubjectBase):
    classroom_prefs: list[SubjectClassroomPrefIn] = Field(default_factory=list)


class SubjectOut(SubjectBase):
    id: int
    classroom_prefs: list[SubjectClassroomPrefIn] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


# ---------- Teacher ----------


class UnavailabilitySlot(BaseModel):
    """3-state availability cell. state in {'hard','soft'}; absence == free."""
    day: int
    hour: int
    state: str = "hard"
    soft_penalty: int = 100
    reason: str | None = None


class FreeDayPref(BaseModel):
    """One ordered preference for a free day. Up to 3 entries allowed
    in `preferred_free_days`. day=1..6 (Lun..Sab); is_hard=True means
    the day is fully blocked; SOFT means the model pays soft_penalty
    for every busy hour on that day."""
    day: int
    is_hard: bool = True
    soft_penalty: int | None = 100


class FreeDayPriorityPref(BaseModel):
    """One row of the new TeacherFreeDayPreference table.

    `priority` in {1, 2, 3} maps to weights {30, 20, 10}: the 1st
    choice costs the most to ignore so the solver honors it first.
    Universal HARD "every teacher >= 1 free day per week" is enforced
    independently of this list."""
    day: int
    priority: int


class FreeDayPrioritiesIn(BaseModel):
    """PATCH payload for /api/teachers/{id}/free-day-preferences.

    Replaces the teacher's full set of priority preferences. Empty
    list clears them. Server enforces day in 1..6, priority in 1..3,
    no duplicate days, no duplicate priorities."""
    preferences: list[FreeDayPriorityPref] = Field(default_factory=list)


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
    graduatoria_score: float | None = Field(
        default=None,
        description="Punteggio in graduatoria provinciale (0-300). "
                    "Usato dal preset Phase-A 'seniority' per allineare "
                    "anzianita' e indirizzi pesanti."
    )
    free_day: str | None = None
    # New: structured up-to-3 ordered free-day preferences.
    preferred_free_days: list[FreeDayPref] = Field(default_factory=list)
    # HARD floor on the number of free days per week (>= N).
    # Default 1 (italian CCNL). Per-teacher overrides support 2 or 3.
    min_free_days: int = 1
    max_consecutive: int = 5
    notes: str | None = None
    pref_no_buchi_weight: float = 10.0
    pref_no_five_weight: float = 30.0
    pref_no_one_weight: float = 80.0
    preferred_days_csv: str | None = None


class TeacherClassroomPrefIn(BaseModel):
    classroom_name: str
    state: str = "allowed"   # allowed | preferred | forbidden | enforced
    weight: float = 10.0


class TeacherIn(TeacherBase):
    subjects: list[str] = Field(default_factory=list)
    unavailability: list[UnavailabilitySlot] = Field(default_factory=list)
    mandatory_free_days: list[int] = Field(default_factory=list)
    compatible_classes: list[str] = Field(default_factory=list)
    classroom_prefs: list[TeacherClassroomPrefIn] = Field(default_factory=list)


class TeacherOut(TeacherBase):
    id: int
    subjects: list[str] = Field(default_factory=list)
    unavailability: list[UnavailabilitySlot] = Field(default_factory=list)
    mandatory_free_days: list[int] = Field(default_factory=list)
    compatible_classes: list[str] = Field(default_factory=list)
    classroom_prefs: list[TeacherClassroomPrefIn] = Field(default_factory=list)
    # New: 3-priority free-day preference table rows. Sorted by priority.
    free_day_priorities: list[FreeDayPriorityPref] = Field(
        default_factory=list)
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
    n_students: int = 25
    notes: str | None = None
    hard_entry_at_8: bool = True
    hard_exit_after_12: bool = True
    hard_no_holes: bool = True
    hard_dual_math: bool = True
    hard_dual_italian: bool = True
    hard_motorie_pairs: bool = True
    hard_max_6_per_day: bool = True
    soft_minimize_sixth_weight: float = 50.0
    # Free-day fields (analoghi a Teacher).
    preferred_free_days: list[FreeDayPref] = Field(default_factory=list)
    required_free_days_count: int = 0
    max_hours_per_day: int = 5


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
    # New: criterion / DSL controls. When `criterion="custom"` the
    # `custom_expression` is used; otherwise it must match a preset
    # key (see backend.utils.objective_dsl.PRESETS).
    criterion: str = "balance_weight"
    custom_expression: str | None = None


class ObjectiveValidateIn(BaseModel):
    expression: str


class ObjectiveValidateOut(BaseModel):
    ok: bool
    direction: str | None = None
    errors: list[str] = Field(default_factory=list)


class ObjectivePresetOut(BaseModel):
    key: str
    label: str
    summary: str
    expression: str


# ---------- Teacher class / curriculum preferences (Phase-A only) ----


class TeacherClassPrefIn(BaseModel):
    class_name: str
    state: str = "allowed"
    soft_penalty: float = 0.0


class TeacherClassPrefOut(TeacherClassPrefIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


class TeacherCurriculumPrefIn(BaseModel):
    curriculum_code: str
    state: str = "allowed"
    soft_penalty: float = 0.0


class TeacherCurriculumPrefOut(TeacherCurriculumPrefIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


# ---------- Add-lesson (schedule) ------------------------------------


class AddLessonIn(BaseModel):
    """Create a new Lesson cell at (day, hour). Used by the empty-cell
    "+" buttons on the per-class / per-teacher / per-room / per-slot
    schedule views.

    Conflict resolution semantics:
      * dry_run -> never write; return the conflict description.
      * cancel  -> abort and return the conflict (no write).
      * unbind  -> on room conflicts, clear `classroom_name` of the
                   conflicting lesson(s) so the room frees up. On
                   teacher/class conflicts, falls back to `delete`
                   because there's no per-attribute unbinding for
                   those (a Lesson IS a (teacher, class, day, hour)
                   tuple). Then write the new lesson.
      * delete  -> delete the conflicting Lesson rows entirely (those
                   Assignments lose hours and surface as incomplete in
                   /api/monitor/events). Then write the new lesson.

    Backward-compat: `unassign` and `optimize` are accepted as
    aliases of `delete` (used to be the names in the older monitor
    flow).
    """
    class_name: str
    teacher_name: str
    subject: str | None = Field(
        default=None,
        description="If omitted and the (class, teacher) pair has "
                    "exactly one matching Assignment, that subject is "
                    "used; otherwise 422 with the candidate list.",
    )
    classroom_name: str | None = None
    day: int
    hour: int
    on_conflict: str = "dry_run"
    cotaught_with: list[str] = Field(default_factory=list)


class AddLessonOut(BaseModel):
    ok: bool
    conflict: bool = False
    no_change: bool = False
    resolution: str | None = None
    lesson_id: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


# ---------- Add-event (monitor) --------------------------------------


class AddEventIn(BaseModel):
    """Create a new Assignment (event) optionally with one initial
    Lesson at a given time. If day/hour are omitted, the Assignment
    is created as "incomplete" (no Lesson rows yet) and surfaces in
    the red panel of the Monitor tab.

    `force=False` (default): if (class, subject) already has a
    cattedra owned by another teacher, the call returns
    `warning='cattedra_clash'` with details and does NOT write.
    The frontend then asks the user; if they confirm, the same call
    is repeated with `force=True`.

    `force=True`: skip Assignment creation/check entirely and create
    the Lesson alone (only valid when day+hour are given). The
    Lesson is "orphan" -- it exists in the solution but does not
    have a corresponding cattedra. Use this when the user is sure
    they want the event regardless of cattedra ownership.
    """
    class_name: str
    teacher_name: str
    subject: str
    hours: int = 1
    classroom_name: str | None = None
    day: int | None = None
    hour: int | None = None
    locked: bool = False
    on_conflict: str = "dry_run"
    force: bool = False


class AddEventOut(BaseModel):
    ok: bool
    conflict: bool = False
    warning: str | None = None
    assignment_id: int | None = None
    lesson_id: int | None = None
    resolution: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


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
    # Per-step rooms toggle: when True, after Phase B persists the
    # solution the classroom-assignment step is run inline so that
    # gym/lab capacity is solved jointly with the timetable.
    optimize_rooms: bool = False
    rooms_time_limit_s: float = 30.0
    rooms_prefer_home: bool = True
    # Phase 3 -- monolithic solver scope.
    #   "day"  (default, legacy): per-day decomposition, optionally
    #          spectral. Phase A always runs to produce day_count.
    #   "week": single CP-SAT call covering the whole week via
    #          ``MonolithicSolver(scope=None)``. Phase A behaviour is
    #          controlled by ``phase_a_mode`` below.
    cp_sat_scope: str = "day"
    # Phase 3 -- Phase A interaction with the monolithic solver.
    #   "always":   run Phase A and feed dc_value as HARD per-day
    #               equality (legacy day-mode requires this).
    #   "skip":     skip Phase A; the week solver picks its own
    #               day distribution. Only valid with cp_sat_scope="week".
    #   "soft_hint": run Phase A, then push dc_value as ``model.AddHint``
    #               on the week solver's day_count_for_hint vars (warm
    #               start, not enforced). Only valid with cp_sat_scope="week".
    phase_a_mode: str = "always"

    @model_validator(mode="after")
    def _validate_scope_and_phase_a_mode(self) -> "PhaseBRunIn":
        if self.cp_sat_scope not in ("day", "week"):
            raise ValueError(
                f"cp_sat_scope must be 'day' or 'week', "
                f"got {self.cp_sat_scope!r}")
        if self.phase_a_mode not in ("always", "skip", "soft_hint"):
            raise ValueError(
                f"phase_a_mode must be 'always' / 'skip' / 'soft_hint', "
                f"got {self.phase_a_mode!r}")
        # Cross-field rules:
        # - day-mode always runs Phase A (the legacy path needs dc_value)
        # - week-mode + phase_a_mode='always' is meaningless (the week
        #   solver picks its own day distribution; forcing Phase A's
        #   dc_value as HARD equality would defeat the point of week
        #   scope and just reproduce day-mode semantics).
        if self.cp_sat_scope == "day" and self.phase_a_mode != "always":
            raise ValueError(
                "cp_sat_scope='day' requires phase_a_mode='always' "
                "(the legacy per-day pipeline needs Phase A's dc_value)")
        if (self.cp_sat_scope == "week"
                and self.phase_a_mode == "always"):
            raise ValueError(
                "cp_sat_scope='week' is incompatible with "
                "phase_a_mode='always': the week solver decides its own "
                "day distribution, so Phase A's dc_value would either "
                "be ignored or collapse week-mode back to day-mode. "
                "Use phase_a_mode='skip' or 'soft_hint' instead.")
        return self


class MetaRunIn(BaseModel):
    """LNS / SA / TS / ILS / ALNS / VNS step."""
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
    # ALNS-only:
    alns_T0: float = 5.0
    alns_alpha: float = 0.995
    alns_destroy: list[str] | None = None
    alns_repair: list[str] | None = None
    # VNS-only:
    vns_neighbourhoods: list[str] | None = None
    # Lagrangian-only:
    lagrangian_max_iter: int = 8
    lagrangian_tolerance: float = 1e-2
    lagrangian_alpha_0: float = 1.0
    # Per-step rooms toggle (same semantics as PhaseBRunIn): if True
    # the rooms step runs on the new active solution at the end.
    optimize_rooms: bool = False
    rooms_time_limit_s: float = 30.0
    rooms_prefer_home: bool = True


# Default ordering of the pipeline. The frontend lets the user reorder
# and untick items; only the enabled keys (in user-defined order) are
# sent back.
DEFAULT_PIPELINE_STEPS = ["phase_a", "phase_b", "lns", "alns", "sa",
                          "ts", "vns", "ils"]
PIPELINE_STEP_KEYS = {"phase_a", "phase_b", "lns", "alns", "sa", "ts",
                       "vns", "ils", "rooms", "hall_check", "cg",
                       "lagrangian"}


class HallCheckIn(BaseModel):
    """Inputs for the synchronous Hall's theorem pre-check."""
    n_samples: int = 256
    teacher_max_hours: int = 18


class ColumnGenerationIn(BaseModel):
    """Inputs for the async Column Generation run.

    `mode` selects the top-level scheme:
        'iterative-diversified' (default, master LP + diversified
        pattern enrichment + completion fallback);
        'branch-and-price' (real Dantzig-Wolfe with per-granularity
        CP-SAT pricing, see `granularity`);
        'auto' (resolves to 'branch-and-price' for small schools,
        'iterative-diversified' otherwise).

    `granularity` selects the sub-problem unit when mode is
    branch-and-price (or auto resolved to it). Supported values:
        'auto', 'teacher', 'teacher-day', 'teacher-class',
        'teacher-class-subject', 'teacher-subject', 'class',
        'class-day', 'day', 'curriculum'.
    'auto' is resolved server-side from the number of classes in
    the active school. Granularities not yet wired in the engine
    fall back to 'teacher' with a log warning.

    `branching_strategy`: 'ryan_foster' or 'variable'. Used only
    when `mode='branch-and-price'`.
    """
    time_budget_s: float = 60.0
    patterns_per_teacher: int = 3
    mode: str = "iterative-diversified"
    # 'iterative-diversified' | 'branch-and-price' | 'auto'
    granularity: str = "auto"
    # 'auto' | 'teacher' | 'teacher-day' | 'teacher-class' |
    # 'teacher-class-subject' | 'teacher-subject' | 'class' |
    # 'class-day' | 'day' | 'curriculum'
    branching_strategy: str = "ryan_foster"  # 'ryan_foster' | 'variable'
    max_iterations: int = 5
    bp_max_iterations: int = 8
    pricer_time_limit: float = 5.0
    pricer_workers: int = 2
    parallel: bool = True
    log: bool = True


class PlaceEventIn(BaseModel):
    """Run the greedy event-placer on a list of cattedre. Used by
    the per-row "Piazza" button (and bulk-piazza) in /monitor.

    `lock_mode`:
      all_others_locked              every other lesson is treated as
                                     fixed; only the targets get
                                     re-placed in free slots.
      same_class_or_teacher_movable  lessons of the targets' classes
                                     or teachers can be evicted; the
                                     rest is fixed.
      all_others_movable             nothing fixed -- the placer can
                                     evict anything.
    """
    event_ids: list[int]
    lock_mode: str = "all_others_locked"
    prefer_pref: bool = False


class PlaceEventOut(BaseModel):
    run_id: int


class GeneralConstraintIn(BaseModel):
    expression: str
    label: str | None = None
    level: str = "hard"
    weight: int = 100
    scope: str = "global"
    owner_id: int | None = None


class GeneralConstraintOut(BaseModel):
    id: int
    expression: str
    label: str | None = None
    level: str
    weight: int
    scope: str
    owner_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class GeneralConstraintValidateOut(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    n_atoms: int = 0


class ConstraintCreateIn(BaseModel):
    """Polymorphic creation payload for the unified
    POST /api/constraints endpoint. The (scope, kind) pair drives the
    dispatch:

      (teacher | class | classroom, matrix_slot)  -> *Unavailability
      (teacher | class | classroom, logical)      -> LogicalUnavailability
      (curriculum, logical)                       -> CurriculumLogicalConstraint
      (subject_room, room_pref)                   -> ClassroomSubjectPreference
      (teacher_room, room_pref)                   -> TeacherClassroomPreference
      (class, coteach)                            -> CoTeachingRule

    `level` carries the 5-state taxonomy: hard / soft / preferred /
    enforced / allowed / forbidden (the last two only valid on
    classroom/teacher room preferences). `weight` is the SOFT penalty
    (positive = SOFT cost; negative = PREFERRED bonus); ignored for
    HARD/ENFORCED/ALLOWED.

    Optional fields are only consumed for specific (scope, kind)
    combinations; the endpoint returns 400 on missing required fields.
    """
    scope: str
    kind: str
    level: str = "hard"
    weight: int | None = None

    # Owner identity (one or two depending on kind)
    owner_id: int | None = None
    owner_id_2: int | None = None

    # matrix_slot
    day: int | None = None
    hour: int | None = None
    reason: str | None = None

    # logical
    expression: str | None = None
    label: str | None = None
    year_filter: int | None = None

    # subject-tagged constraints (room_pref by subject, coteach...)
    subject: str | None = None

    # coteach
    n_teachers: int | None = None
    teacher_csv: str | None = None


class ConstraintCreateOut(BaseModel):
    ok: bool
    kind: str
    id: int
    scope: str
    detail: str | None = None


class FullPipelineIn(BaseModel):
    profile: str = "small"
    workers: int = 8
    time_assign: float = 30.0
    phase_b: PhaseBRunIn = Field(default_factory=PhaseBRunIn)
    budget_lns: float = 60.0
    budget_sa: float = 30.0
    budget_ts: float = 30.0
    budget_ils: float = 60.0
    # User-defined step list (ordered). Only keys present here are run
    # and they run in this order. Each phase_b/meta step independently
    # honours its own `optimize_rooms` flag (carried inside `phase_b`
    # for step 3, and in the meta-budget defaults for 4-7 -- the
    # frontend collapses all four meta cards onto one shared toggle).
    steps: list[str] = Field(default_factory=lambda: list(DEFAULT_PIPELINE_STEPS))
    # When the meta toggle "optimize rooms" is on, every meta step in
    # the pipeline runs the rooms helper inline after itself.
    meta_optimize_rooms: bool = False
    meta_rooms_time_limit_s: float = 30.0
    meta_rooms_prefer_home: bool = True


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
    # Set when the lesson's classroom had to be cleared after the move
    # because the old room was occupied or HARD-unavailable at dst.
    room_cleared: bool = False
    cleared_room: str | None = None


# ---------- Manual assignment override validation ----------


class ManualAssignmentIn(BaseModel):
    """Replace the teacher of a (class, subject) or (group, subject)
    pair. Hours come from the class subject definition (for class
    target) or from `hours` (for group target).

    target_kind defaults to 'class' for backward-compat. When
    target_kind='group' the payload must include `group_name` AND
    `hours`; class_name is ignored."""
    class_name: str = ""
    subject: str
    teacher_name: str
    locked: bool = True
    target_kind: str = "class"  # 'class' | 'group'
    group_name: str | None = None
    hours: int | None = None  # required when target_kind='group'


class ManualAssignmentOut(BaseModel):
    accepted: bool
    reason: str
    new_assignment: AssignmentOut | None = None


# ---------- Bulk Assignments ----------


class BulkAssignmentIdsIn(BaseModel):
    """Generic bulk operation payload addressing a list of
    Assignment ids. Used by /api/assignments/bulk/{action} endpoints
    where the action determines what to do with the selected rows."""
    ids: list[int]


class BulkAssignmentLockIn(BaseModel):
    ids: list[int]
    locked: bool = True


class BulkAssignmentChangeTeacherIn(BaseModel):
    """Reassign every selected (class|group, subject) pair to a new
    teacher. The teacher must be qualified for each subject in the
    selection or the row is reported in `errors`."""
    ids: list[int]
    teacher_name: str


class BulkAssignmentSetFlagIn(BaseModel):
    """Toggle a boolean flag (is_potenziamento, is_support) on every
    selected row."""
    ids: list[int]
    flag: str  # 'is_potenziamento' | 'is_support'
    value: bool


class BulkAssignmentResultOut(BaseModel):
    """Summary of a bulk operation. `errors` contains per-row issues
    (unknown id, teacher not qualified, etc.) so the UI can surface
    a partial-success toast without rolling back."""
    ok: bool
    n_applied: int
    n_skipped: int
    errors: list[str] = []


# ---------- Classrooms ----------


class ClassroomSubjectPrefIn(BaseModel):
    subject: str
    weight: float = 10.0
    required: bool = False
    state: str = "allowed"  # allowed | preferred | forbidden | enforced


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
    plesso_id: int | None = None
    # Free-form tags ("lab", "fisica", "matematica", "scientifico", ...).
    # Stored as a many-to-many on the backend; surfaced as a list of
    # tag-name strings in the API for simplicity.
    tags: list[str] = Field(default_factory=list)


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


# ---------- Plessi (school sites) ----------


class PlessoBase(BaseModel):
    name: str
    code: str
    address: str | None = None
    notes: str | None = None


class PlessoIn(PlessoBase):
    pass


class PlessoOut(PlessoBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class PlessoCommutingRuleBase(BaseModel):
    from_plesso_id: int
    to_plesso_id: int
    entity_kind: str   # 'teacher' | 'class' | 'group'
    entity_id: int | None = None
    min_gap_hours: int = 0
    allowed_break_only: bool = False
    break_start_hour: int | None = None
    break_end_hour: int | None = None
    symmetric: bool = True
    priority: int = 0
    notes: str | None = None


class PlessoCommutingRuleIn(PlessoCommutingRuleBase):
    pass


class PlessoCommutingRuleOut(PlessoCommutingRuleBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class PlessoEntityPolicyBase(BaseModel):
    entity_kind: str   # 'teacher' | 'class'
    entity_id: int | None = None
    policy: str = "any"   # 'any' | 'single_plesso_per_day' | 'single_plesso_total'
    plesso_id: int | None = None
    priority: int = 0
    notes: str | None = None


class PlessoEntityPolicyIn(PlessoEntityPolicyBase):
    pass


class PlessoEntityPolicyOut(PlessoEntityPolicyBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class ClassroomTagIn(BaseModel):
    name: str
    description: str | None = None


class ClassroomTagOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    n_classrooms: int = 0
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
    """A logical (disjunctive) unavailability constraint.

    `kind` carries the 4-way classification (hard/soft/preferred/enforced).
    `is_hard` is kept for backwards compatibility — when not provided
    explicitly it is derived from kind.
    """
    expression: str
    is_hard: bool = True
    soft_penalty: int = 100
    kind: str = "hard"   # hard | soft | preferred | enforced


class LogicalUnavOut(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    expression: str
    pretty: str
    clauses: list[list[dict[str, Any]]] = Field(default_factory=list)
    is_hard: bool
    soft_penalty: int
    kind: str = "hard"


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
    kind: str = "hard"


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
    kind: str = "hard"


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
    tags: list[str] = Field(default_factory=list)


class StudentIn(StudentBase):
    pass


class StudentOut(StudentBase):
    id: int
    class_name: str | None = None
    n_groups: int = 0
    model_config = ConfigDict(from_attributes=True)


class StudentTagIn(BaseModel):
    name: str
    description: str | None = None


class StudentTagOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    n_students: int = 0
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


# ---------- Saved views ----------


class SortLevel(BaseModel):
    column: str
    direction: str = "asc"


class SavedViewBase(BaseModel):
    entity: str
    name: str
    dsl_query: str | None = None
    sort_levels: list[SortLevel] = Field(default_factory=list)
    description: str | None = None


class SavedViewIn(SavedViewBase):
    pass


class SavedViewOut(SavedViewBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# ---------- Tab Ore (working hours config) ----------


class WorkingHourSlotIn(BaseModel):
    slot_index: int = Field(ge=0,
                            description="0-based engine hour_idx")
    start_time: str = Field(min_length=4, max_length=5,
                            description="HH:MM, e.g. '08:00'")
    end_time: str = Field(min_length=4, max_length=5,
                          description="HH:MM, e.g. '09:00'")
    label: str | None = None
    legacy_hour_number: int = Field(ge=0, le=23,
                                    description="0..23 (default = "
                                                "start hour for legacy "
                                                "TeacherUnavailability)")


class WorkingHourSlotOut(WorkingHourSlotIn):
    id: int
    day_id: int
    model_config = ConfigDict(from_attributes=True)


class WorkingDayIn(BaseModel):
    code: str = Field(min_length=2, max_length=8,
                      description="MON | TUE | ... | SUN")
    label: str = Field(min_length=1, max_length=32)
    position: int = Field(ge=0, le=6,
                          description="0-based engine day_idx")
    legacy_day_number: int = Field(ge=1, le=7,
                                   description="1..7 (MON..SUN) -- "
                                               "kept for legacy "
                                               "*_unavailability rows")
    is_active: bool = True


class WorkingDayPatch(BaseModel):
    code: str | None = None
    label: str | None = None
    position: int | None = None
    legacy_day_number: int | None = None
    is_active: bool | None = None


class WorkingDayOut(WorkingDayIn):
    id: int
    slots: list[WorkingHourSlotOut] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class WorkingDaySlotsReplace(BaseModel):
    """Body for PUT /api/working-hours/days/{id}/slots: replaces the
    full list of slots for a day in a single transaction. Slots are
    re-indexed by their order in the list (slot_index field is
    ignored on input -- the server uses the array position)."""
    slots: list[WorkingHourSlotIn]


class WorkingHoursConfigOut(BaseModel):
    """GET /api/working-hours/config -- aggregated structure for the
    frontend (Ore tab + WeeklyCalendarView). All days, in position
    order; each day carries its slots in slot_index order. Includes
    derived fields max_slots_per_day and uniform_slot_count for the
    calendar grid layout."""
    days: list[WorkingDayOut]
    max_slots_per_day: int = Field(
        description="max(len(day.slots)) across active days; the "
                    "engine uses this as the uniform HOURS length"
    )
    uniform_slot_count: bool = Field(
        description="True iff every active day has the same number "
                    "of slots (engine integration is simplest in "
                    "this case)"
    )
