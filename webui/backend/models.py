"""SQLAlchemy ORM models for the timetable webui.

The data model intentionally encodes more constraints than the optimization
engine can currently honor. Constraints not yet supported by the solver are
still enforced live during drag-and-drop edits, so the user gets immediate
feedback even on rules the solver ignores.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .tenant import TenantMixin


# ---------- value-object helpers ----------


class JSONColumn(Text):
    """Text column carrying JSON strings."""


def utcnow() -> dt.datetime:
    # tz-naive UTC: SQLAlchemy default DateTime is tz-naive on SQLite,
    # so we strip the timezone for storage compatibility.
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    """Adds `created_at` (default now) and `updated_at` (default now,
    auto-updated on PUT). Section 2.2 P3.

    Mixed into the user-facing top-level entities (Subject, Teacher,
    SchoolClass, Classroom, Student, StudyGroup, Curriculum). Existing
    DBs are auto-upgraded by the lightweight migration in db.py.
    """
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


# ---------- Subjects ----------


class Subject(TenantMixin, TimestampMixin, Base):
    __tablename__ = "subjects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    pretty_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SOFT preferences encoded directly on the subject row
    distribute_days_weight: Mapped[float] = mapped_column(Float, default=0.0)
    dual_hours_weight: Mapped[float] = mapped_column(Float, default=0.0)
    no_sixth_hour_weight: Mapped[float] = mapped_column(Float, default=0.0)
    preferred_band_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preferred_band_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preferred_band_weight: Mapped[float] = mapped_column(Float, default=0.0)


# ---------- Teachers ----------


class Teacher(TenantMixin, TimestampMixin, Base):
    __tablename__ = "teachers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True,
                                      comment="full canonical name; "
                                      "engine key. Defaults to "
                                      "'<last_name> <first_name>'.")
    last_name: Mapped[str | None] = mapped_column(String(80), nullable=True,
                                                  index=True)
    first_name: Mapped[str | None] = mapped_column(String(80), nullable=True,
                                                   index=True)
    nickname: Mapped[str | None] = mapped_column(
        String(80), nullable=True,
        comment="abbreviated name shown in the timetable view; defaults "
                "to '<last_name> <first_name>' when displayed."
    )
    matricola: Mapped[str | None] = mapped_column(String(40), nullable=True)
    group: Mapped[str | None] = mapped_column(String(40), nullable=True,
                                              comment="classe di concorso")
    max_hours: Mapped[int] = mapped_column(Integer, default=18)
    completion_hours: Mapped[int] = mapped_column(Integer, default=0)
    exemption_hours: Mapped[int] = mapped_column(Integer, default=0)
    graduatoria_score: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="Punteggio in graduatoria provinciale (range tipico "
                "0-300). Usato dal preset 'seniority' di Phase A per "
                "assegnare i docenti piu' anziani agli indirizzi a "
                "peso maggiore."
    )
    free_day: Mapped[str | None] = mapped_column(String(16), nullable=True,
                                                 comment="day name (Italian); "
                                                 "legacy single-day free-day "
                                                 "field. Superseded by "
                                                 "`preferred_free_days_json` "
                                                 "for new code, kept for "
                                                 "backwards compat with "
                                                 "older mock pickles.")
    # Up to 3 preferred-free-day entries with per-day HARD/SOFT level
    # and SOFT penalty. Stored as JSON to avoid a new satellite table:
    # [{"day": 1..6, "is_hard": bool, "soft_penalty": int|None}, ...].
    preferred_free_days_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON list of up to 3 free-day preferences, each "
                "{day: 1..6, is_hard: bool, soft_penalty: int|None}. "
                "Day numbering 1=Lun .. 6=Sab."
    )
    # Exact number of free days per week (HARD). Default 1 (italian
    # CCNL norm). 0 = teacher works every day, 6 = teacher never
    # teaches (theoretical).
    required_free_days_count: Mapped[int] = mapped_column(
        Integer, default=1,
        comment="HARD: numero esatto di giorni liberi a settimana."
    )
    max_consecutive: Mapped[int] = mapped_column(Integer, default=5,
                                                 comment="HARD: max ore "
                                                 "consecutive nel giorno")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SOFT prefs as numeric weights
    pref_no_buchi_weight: Mapped[float] = mapped_column(Float, default=10.0)
    pref_no_five_weight: Mapped[float] = mapped_column(Float, default=30.0)
    pref_no_one_weight: Mapped[float] = mapped_column(Float, default=80.0)
    # Comma-separated list of preferred days (e.g., Lun,Mar)
    preferred_days_csv: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    # Relationships
    subjects: Mapped[list["TeacherSubject"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )
    unavailability: Mapped[list["TeacherUnavailability"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )
    mandatory_free_days: Mapped[list["TeacherMandatoryFreeDay"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )
    compatible_classes: Mapped[list["TeacherCompatibleClass"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )
    # Phase-A only preferences (Section: workflow extensions). The
    # solver maps state to HARD/SOFT terms in the assignment model.
    class_preferences: Mapped[list["TeacherClassPreference"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )
    curriculum_preferences: Mapped[
        list["TeacherCurriculumPreference"]
    ] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )


class TeacherSubject(Base):
    __tablename__ = "teacher_subjects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(String(64))
    teacher: Mapped["Teacher"] = relationship(back_populates="subjects")
    __table_args__ = (
        UniqueConstraint("teacher_id", "subject", name="uq_teacher_subj"),
    )


class TeacherUnavailability(Base):
    """3-state availability constraint for a (day, hour) cell.

    `state` is one of:
      - "hard": cell is HARD unavailable (red)  — teacher MUST NOT work then
      - "soft": cell is SOFT non-preferred (yellow) — assignment penalised
                by `soft_penalty` units in the SOFT objective

    Free (green) cells are absent from the table.
    """
    __tablename__ = "teacher_unavailability"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[int] = mapped_column(Integer)
    hour: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(8), default="hard",
                                       comment="hard | soft")
    soft_penalty: Mapped[int] = mapped_column(Integer, default=100,
                                              comment="cost when state=soft")
    reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    teacher: Mapped["Teacher"] = relationship(back_populates="unavailability")
    __table_args__ = (
        UniqueConstraint("teacher_id", "day", "hour", name="uq_unavail_dh"),
    )


class TeacherMandatoryFreeDay(Base):
    """HARD: teacher must have 0 hours on this day (e.g. part-time)."""
    __tablename__ = "teacher_mandatory_free_days"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[int] = mapped_column(Integer)
    teacher: Mapped["Teacher"] = relationship(back_populates="mandatory_free_days")


class TeacherCompatibleClass(Base):
    """Optional explicit compatibility constraint: teacher allowed only on
    these classes. If none, all classes accepted (subject to subject match)."""
    __tablename__ = "teacher_compatible_classes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    class_name: Mapped[str] = mapped_column(String(40))
    teacher: Mapped["Teacher"] = relationship(back_populates="compatible_classes")


class TeacherClassPreference(Base):
    """Phase-A only: how the teacher relates to each class.

    state: 'allowed' (default) | 'preferred' | 'soft' | 'forbidden' |
           'enforced'
    soft_penalty: numeric weight for 'soft' (positive) and
                  'preferred' (negative); 0 for the HARD states.

    Distinct from TeacherCompatibleClass which is a HARD allow-list:
    here we have the full 5-state taxonomy + per-row penalty, and
    these preferences are applied as HARD/SOFT terms in the Phase-A
    DSL solver only -- they do NOT affect Phase B scheduling."""
    __tablename__ = "teacher_class_preferences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    class_name: Mapped[str] = mapped_column(String(40), index=True)
    state: Mapped[str] = mapped_column(
        String(16), default="allowed",
        comment="allowed | preferred | soft | forbidden | enforced"
    )
    soft_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    teacher: Mapped["Teacher"] = relationship(
        back_populates="class_preferences"
    )
    __table_args__ = (
        UniqueConstraint("teacher_id", "class_name",
                         name="uq_tcp_teacher_class"),
    )


class TeacherCurriculumPreference(Base):
    """Phase-A only: how the teacher relates to each curriculum
    (indirizzo). Same 5-state taxonomy as TeacherClassPreference, but
    keyed on `curriculum_code` -- a HARD here means "this teacher
    cannot be assigned to ANY class of this curriculum"."""
    __tablename__ = "teacher_curriculum_preferences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    curriculum_code: Mapped[str] = mapped_column(String(40), index=True)
    state: Mapped[str] = mapped_column(
        String(16), default="allowed",
        comment="allowed | preferred | soft | forbidden | enforced"
    )
    soft_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    teacher: Mapped["Teacher"] = relationship(
        back_populates="curriculum_preferences"
    )
    __table_args__ = (
        UniqueConstraint("teacher_id", "curriculum_code",
                         name="uq_tcurp_teacher_curriculum"),
    )


# ---------- Classes ----------


class SchoolClass(TenantMixin, TimestampMixin, Base):
    __tablename__ = "school_classes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    nickname: Mapped[str | None] = mapped_column(
        String(80), nullable=True,
        comment="abbreviation shown in the timetable; defaults to name"
    )
    year: Mapped[int] = mapped_column(Integer, default=1)
    section: Mapped[str | None] = mapped_column(String(8), nullable=True)
    curriculum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    curriculum_id: Mapped[int | None] = mapped_column(
        ForeignKey("curricula.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="Optional FK to normalized indirizzi (curricula). The string "
                "`curriculum` column is kept as fallback for legacy rows."
    )
    n_students: Mapped[int] = mapped_column(Integer, default=20)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # HARD constraints (toggles)
    hard_entry_at_8: Mapped[bool] = mapped_column(Boolean, default=True)
    hard_exit_after_12: Mapped[bool] = mapped_column(Boolean, default=True)
    hard_no_holes: Mapped[bool] = mapped_column(Boolean, default=True)
    hard_dual_math: Mapped[bool] = mapped_column(Boolean, default=True)
    hard_dual_italian: Mapped[bool] = mapped_column(Boolean, default=True)
    hard_motorie_pairs: Mapped[bool] = mapped_column(Boolean, default=True)
    hard_max_6_per_day: Mapped[bool] = mapped_column(Boolean, default=True)
    # SOFT
    soft_minimize_sixth_weight: Mapped[float] = mapped_column(Float, default=50.0)
    # Free-day fields (analoghi a Teacher). Up to 3 ordered preferences
    # stored as JSON; HARD count enforced exactly. The default is 0 ->
    # the class works all 6 days (Italian norm).
    preferred_free_days_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON list of up to 3 free-day preferences "
                "[{day:1..6, is_hard:bool, soft_penalty:int|None}]."
    )
    required_free_days_count: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="HARD: numero esatto di giorni liberi a settimana "
                "per la classe. Default 0 (lavora tutti i giorni)."
    )
    # Max ore/giorno: rilassa il default hardcoded di 5 nel modello.
    # range tipico 4-7. Aumentare oltre 5 quando la classe ha giorni
    # liberi da compensare con piu' ore negli altri giorni.
    max_hours_per_day: Mapped[int] = mapped_column(
        Integer, default=5,
        comment="HARD: massimo numero di ore al giorno (sostituisce "
                "il vecchio default fisso di 5)."
    )
    subjects: Mapped[list["ClassSubject"]] = relationship(
        back_populates="school_class", cascade="all, delete-orphan"
    )


class ClassSubject(Base):
    __tablename__ = "class_subjects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("school_classes.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(String(64))
    hours_per_week: Mapped[int] = mapped_column(Integer, default=0)
    school_class: Mapped["SchoolClass"] = relationship(back_populates="subjects")
    __table_args__ = (
        UniqueConstraint("class_id", "subject", name="uq_class_subj"),
    )


# ---------- Subject group / compatibility table ----------


class SubjectGroupWeight(Base):
    """Maps subject -> classe-di-concorso -> weight. Mirrors
    cconcorsopersubject in the engine pickles."""
    __tablename__ = "subject_group_weights"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(64), index=True)
    group_name: Mapped[str] = mapped_column(String(40), index=True)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("subject", "group_name", name="uq_subj_group"),
    )


# ---------- Cattedre / Assignment (prof -> class -> subject -> ore) ----------


class Assignment(Base):
    """Result of the prof->class assignment step. One row per
    (teacher, class, subject) triple. Hours come from the matching class
    subject row; we replicate them here for fast reads and to allow
    targeted manual overrides.

    Three special-case shapes (Task C1):
    - Shared coteaching: N rows with same (class_id, subject) and a
      shared `coteach_group_id` pointing at the rule that ties them.
    - Sostegno (shadow): `is_support=True`, `subject="sostegno"`. The
      teacher follows the class -- placed in slots where the class
      already has a non-support lesson; doesn't add to class-busy.
    - Potenziamento: `is_potenziamento=True`, `class_id=NULL`. The
      teacher's hours get scheduled but produce no class-bound
      Lesson; available for substitutions and flexible coteaching.
    """
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    class_id: Mapped[int | None] = mapped_column(
        ForeignKey("school_classes.id", ondelete="CASCADE"),
        nullable=True, index=True,
        comment="NULL only for is_potenziamento=True rows"
    )
    subject: Mapped[str] = mapped_column(String(64))
    hours: Mapped[int] = mapped_column(Integer, default=0)
    locked: Mapped[bool] = mapped_column(Boolean, default=False,
                                         comment="true => cannot be changed "
                                         "by the optimizer")
    coteach_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("coteach_groups.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="non-NULL: this Assignment is part of a shared "
                "coteaching group; n_hours of its `hours` are taught "
                "together with the other members"
    )
    is_support: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True,
        comment="true: prof di sostegno; subject is conventionally "
                "'sostegno'; the teacher follows the class' lessons"
    )
    is_potenziamento: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True,
        comment="true: ore di potenziamento (Legge 107); class_id is "
                "NULL; hours are scheduled but produce no Lesson row"
    )
    parallel_group_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True,
        comment="Task C2: Assignments with the same parallel_group_id "
                "and same class_id are taught in parallel (e.g. "
                "religione + alternativa): they occupy the same slot "
                "but the class counts as busy ONCE."
    )
    # Task C3: a class-less Assignment can target a StudyGroup
    # (Spagnolo cross-class, Recupero matematica). Invariant XOR:
    # exactly one of (class_id, group_id) is non-null, OR both are
    # null when is_potenziamento=True. Enforced via CHECK constraint
    # below + application-layer validation.
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("study_groups.id", ondelete="CASCADE"),
        nullable=True, index=True,
        comment="Task C3: target StudyGroup. XOR with class_id."
    )
    teacher: Mapped["Teacher"] = relationship()
    school_class: Mapped["SchoolClass"] = relationship()
    study_group: Mapped["StudyGroup | None"] = relationship()
    coteach_group: Mapped["CoteachGroup | None"] = relationship(
        back_populates="assignments"
    )
    # Drop the old uq_assign_cl_subj: shared coteaching needs N rows
    # for the same (class_id, subject), each with a distinct
    # teacher_id. The pragma-style unique below covers the same
    # invariant for the cattedre-normali case (one teacher per
    # (class, subj, support-flag)) without forbidding shared shape.
    __table_args__ = (
        UniqueConstraint("teacher_id", "class_id", "subject",
                         "is_support",
                         name="uq_assign_t_cl_subj_sup"),
    )


# ---------- Solutions / lessons ----------


class Solution(Base):
    """A timetable solution. Multiple solutions can be stored; one is
    marked active and used for views."""
    __tablename__ = "solutions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(40),
                                      comment="phase_b/lns/sa/ts/ils/manual")
    obj_value: Mapped[float] = mapped_column(Float, default=0.0)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    lessons: Mapped[list["Lesson"]] = relationship(
        back_populates="solution", cascade="all, delete-orphan"
    )

    @property
    def metrics(self) -> dict[str, Any]:
        try:
            return json.loads(self.metrics_json or "{}")
        except Exception:
            return {}


class Lesson(Base):
    """A single (teacher, class, subject, day, hour) cell. Only stored if
    occupied (=1); empties are derived from absence.
    classroom_name is optional: filled by the classroom assignment step or
    manually edited."""
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    solution_id: Mapped[int] = mapped_column(
        ForeignKey("solutions.id", ondelete="CASCADE"), index=True
    )
    teacher_name: Mapped[str] = mapped_column(String(120), index=True)
    class_name: Mapped[str] = mapped_column(String(40), index=True)
    # Task C3: a Lesson can target a StudyGroup instead of a class.
    # When `group_name` is non-NULL the lesson belongs to that group;
    # `class_name` is then the conventional label of the group's
    # virtual class (typically equal to `group_name` for display).
    # XOR enforced at the application layer.
    group_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True,
        comment="Task C3: non-NULL when this lesson is for a "
                "StudyGroup instead of a class. XOR with the "
                "class-bound shape."
    )
    subject: Mapped[str] = mapped_column(String(64))
    day: Mapped[int] = mapped_column(Integer)
    hour: Mapped[int] = mapped_column(Integer)
    classroom_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    cotaught_with: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="comma-separated list of additional teacher names sharing "
                "this lesson"
    )
    solution: Mapped["Solution"] = relationship(back_populates="lessons")

    # Composite indexes covering the hot lookup patterns used by
    # /schedule, /monitor, /coverage and the conflict scanner. Section
    # 2.2 P1 of docs/improvements.md.
    __table_args__ = (
        Index("ix_lessons_sol_day_hour",
              "solution_id", "day", "hour"),
        Index("ix_lessons_sol_teacher_day_hour",
              "solution_id", "teacher_name", "day", "hour"),
        Index("ix_lessons_sol_class_day_hour",
              "solution_id", "class_name", "day", "hour"),
        Index("ix_lessons_sol_room_day_hour",
              "solution_id", "classroom_name", "day", "hour"),
    )


class DayCount(Base):
    """Cached Phase-A day counts for the active solution. Used by repair /
    drag-drop validation if available."""
    __tablename__ = "day_counts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    solution_id: Mapped[int] = mapped_column(
        ForeignKey("solutions.id", ondelete="CASCADE"), index=True
    )
    teacher_name: Mapped[str] = mapped_column(String(120))
    class_name: Mapped[str] = mapped_column(String(40))
    subject: Mapped[str] = mapped_column(String(64))
    day: Mapped[int] = mapped_column(Integer)
    count: Mapped[int] = mapped_column(Integer, default=0)


# ---------- Runs ----------


class Run(Base):
    """A unit of optimization work. Tracks status, parameters, and cumulative
    log. Logs are appended live to the run_logs table."""
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True,
                                      comment="mock/import/assignment/"
                                      "phase_b/lns/sa/ts/ils/full/export")
    name: Mapped[str] = mapped_column(String(120))
    profile: Mapped[str | None] = mapped_column(String(40), nullable=True)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="pending",
                                        index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    obj_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Free-form short label of the current activity. The full pipeline
    # writes here the step it's about to execute (e.g. "phase_a", "lns",
    # "decomp_temporal") so the runs tab can display "in corso: phase_a"
    # under the progress bar. Cleared (NULL) on terminal status.
    current_step: Mapped[str | None] = mapped_column(
        String(48), nullable=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    solution_id: Mapped[int | None] = mapped_column(
        ForeignKey("solutions.id"), nullable=True
    )


class RunLog(Base):
    __tablename__ = "run_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    text: Mapped[str] = mapped_column(Text)


# ---------- Settings (singleton row of misc app state) ----------


class GeneralConstraint(Base):
    """User-defined HARD/SOFT constraint expressed in the general DSL.

    The expression is parsed and evaluated post-hoc on the active
    solution snapshot (see utils.general_dsl). HARD violations cause
    the solution to be flagged infeasible; SOFT violations add `weight`
    to the global soft-penalty score.
    """
    __tablename__ = "general_constraints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expression: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    level: Mapped[str] = mapped_column(String(16), default="hard",
                                       comment="hard|soft|preferred|enforced")
    weight: Mapped[int] = mapped_column(Integer, default=100,
                                         comment="SOFT penalty (sign-flipped "
                                         "negative for PREFERRED).")
    scope: Mapped[str] = mapped_column(String(24), default="global",
                                        comment="global|teacher|class|"
                                        "classroom|group|subject|curriculum")
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True,
                                                  comment="FK-like reference "
                                                  "into the right entity table; "
                                                  "NULL for scope=global.")
    parsed_ast_json: Mapped[str | None] = mapped_column(Text, nullable=True,
                                                         comment="JSON cache of "
                                                         "the parsed AST.")


class AppState(Base):
    __tablename__ = "app_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")


# ---------- Classrooms (aule) ----------


class Classroom(TenantMixin, TimestampMixin, Base):
    __tablename__ = "classrooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(
        String(32), default="standard",
        comment="standard / lab_chimica / lab_fisica / lab_informatica / "
                "lab_linguistico / palestra / biblioteca / aula_speciale"
    )
    capacity: Mapped[int] = mapped_column(Integer, default=30)
    multi_class: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="true if multiple classes can share this room in the same slot"
    )
    multi_class_max: Mapped[int] = mapped_column(
        Integer, default=1,
        comment="HARD: when multi_class is true, max simultaneous classes"
    )
    multi_class_pref: Mapped[int] = mapped_column(
        Integer, default=1,
        comment="SOFT: preferred concurrency (e.g. 1 even if HARD allows 2)"
    )
    multi_class_pref_weight: Mapped[float] = mapped_column(Float, default=10.0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Relationships
    subject_prefs: Mapped[list["ClassroomSubjectPreference"]] = relationship(
        back_populates="classroom", cascade="all, delete-orphan"
    )
    class_prefs: Mapped[list["ClassroomClassPreference"]] = relationship(
        back_populates="classroom", cascade="all, delete-orphan"
    )
    unavailability: Mapped[list["ClassroomUnavailability"]] = relationship(
        back_populates="classroom", cascade="all, delete-orphan"
    )
    tag_assignments: Mapped[list["ClassroomTagAssignment"]] = relationship(
        back_populates="classroom", cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ClassroomTag(Base):
    """Lightweight label that can be attached to classrooms (many-to-many).

    Examples in mock-generated data:
      - 'lab', 'fisica', 'chimica', 'informatica', 'linguistico'
      - 'palestra', 'biblioteca', 'studio'
      - 'matematica', 'italiano', 'storia', 'inglese'  (compatibility tags)
      - curriculum tags: 'scientifico', 'classico', 'linguistico', 'itis'

    Used by:
      - the constraint DSL: `"matematica" in l.classroom.tags`
      - the classroom list filter (DSL predicate `has_tag(<name>)`)
      - the room-assignment heuristic (prefer rooms whose tags overlap
        the lesson's subject)
    """
    __tablename__ = "classroom_tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignments: Mapped[list["ClassroomTagAssignment"]] = relationship(
        back_populates="tag", cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ClassroomTagAssignment(Base):
    """Join row: classroom <-> tag. Pure association without extra
    payload. Use a UNIQUE on (classroom_id, tag_id) so the same tag
    can't be applied twice to the same room."""
    __tablename__ = "classroom_tag_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classroom_id: Mapped[int] = mapped_column(
        ForeignKey("classrooms.id", ondelete="CASCADE"), index=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("classroom_tags.id", ondelete="CASCADE"), index=True
    )
    classroom: Mapped["Classroom"] = relationship(
        back_populates="tag_assignments"
    )
    tag: Mapped["ClassroomTag"] = relationship(
        back_populates="assignments"
    )
    __table_args__ = (
        UniqueConstraint("classroom_id", "tag_id",
                          name="uq_classroom_tag"),
    )


class ClassroomSubjectPreference(Base):
    """4-state subject<->classroom preference.

    state: 'allowed'   - default; the subject can be held in the room (no
                         contribution to the objective)
           'preferred' - SOFT bonus when used (negative weight by convention,
                         but the sign is kept on the `weight` column)
           'forbidden' - HARD: subject cannot be in this room
           'enforced'  - HARD: subject MUST be in a room of this kind
                         (legacy `required=True` maps here)
    `state` is the SOURCE OF TRUTH; the legacy boolean `required` is kept
    only for backward-compat with engine_io (which still reads it). A
    SQLAlchemy event listener keeps `required` in sync with `state` on
    every insert/update so callers cannot drift the two apart. Section
    2.2 P1 of docs/improvements.md."""
    __tablename__ = "classroom_subject_preferences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classroom_id: Mapped[int] = mapped_column(
        ForeignKey("classrooms.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(
        String(16), default="allowed",
        comment="allowed | preferred | forbidden | enforced -- source of truth"
    )
    weight: Mapped[float] = mapped_column(Float, default=10.0)
    required: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="DERIVED: kept in sync with `state` via the event "
                "listener below. Do not write to it directly; set "
                "`state='enforced'` instead."
    )
    classroom: Mapped["Classroom"] = relationship(back_populates="subject_prefs")
    __table_args__ = (
        UniqueConstraint("classroom_id", "subject", name="uq_room_subj"),
    )


def _sync_csp_required(mapper, connection, target):
    """Auto-sync `required` from `state` on every insert/update.

    'enforced' -> required=True, anything else -> required=False.
    This keeps the legacy column consistent without forcing every
    caller to remember to update both fields.
    """
    target.required = (target.state == "enforced")


event.listen(ClassroomSubjectPreference, "before_insert",
             _sync_csp_required)
event.listen(ClassroomSubjectPreference, "before_update",
             _sync_csp_required)


class TeacherClassroomPreference(Base):
    """4-state teacher<->classroom preference. Same semantics as
    ClassroomSubjectPreference but on the (teacher, classroom) pair."""
    __tablename__ = "teacher_classroom_preferences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    classroom_id: Mapped[int] = mapped_column(
        ForeignKey("classrooms.id", ondelete="CASCADE"), index=True
    )
    state: Mapped[str] = mapped_column(
        String(16), default="allowed",
        comment="allowed | preferred | forbidden | enforced"
    )
    weight: Mapped[float] = mapped_column(Float, default=10.0)
    teacher: Mapped["Teacher"] = relationship()
    classroom: Mapped["Classroom"] = relationship()
    __table_args__ = (
        UniqueConstraint("teacher_id", "classroom_id", name="uq_teacher_room"),
    )


class ClassroomClassPreference(Base):
    """Soft preference: this class prefers this classroom (its 'home')."""
    __tablename__ = "classroom_class_preferences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classroom_id: Mapped[int] = mapped_column(
        ForeignKey("classrooms.id", ondelete="CASCADE"), index=True
    )
    class_name: Mapped[str] = mapped_column(String(40))
    weight: Mapped[float] = mapped_column(Float, default=20.0)
    is_home: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="true if this is the home (default) classroom for the class"
    )
    classroom: Mapped["Classroom"] = relationship(back_populates="class_prefs")
    __table_args__ = (
        UniqueConstraint("classroom_id", "class_name", name="uq_room_cls"),
    )


class ClassroomUnavailability(Base):
    """3-state availability for a classroom on a (day, hour) cell.
    state in {hard, soft}; missing cells are 'free' (green)."""
    __tablename__ = "classroom_unavailability"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classroom_id: Mapped[int] = mapped_column(
        ForeignKey("classrooms.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[int] = mapped_column(Integer)
    hour: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(8), default="hard")
    soft_penalty: Mapped[int] = mapped_column(Integer, default=100)
    reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    classroom: Mapped["Classroom"] = relationship(back_populates="unavailability")
    __table_args__ = (
        UniqueConstraint("classroom_id", "day", "hour", name="uq_room_dh"),
    )


class ClassUnavailability(Base):
    """3-state availability for a class on a (day, hour) cell.
    state in {hard, soft}; missing cells are 'free' (green).
    HARD prevents the solver from scheduling that class in that slot;
    SOFT is a penalty in the soft objective."""
    __tablename__ = "class_unavailability"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("school_classes.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[int] = mapped_column(Integer)
    hour: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(8), default="hard")
    soft_penalty: Mapped[int] = mapped_column(Integer, default=100)
    reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    school_class: Mapped["SchoolClass"] = relationship()
    __table_args__ = (
        UniqueConstraint("class_id", "day", "hour", name="uq_class_unavail_dh"),
    )


# ---------- Co-teaching (compresenze) ----------


class LogicalUnavailability(Base):
    """Disjunctive availability constraint expressed as a logical
    expression (parsed into DNF) over (day, hour) slots.

    Same shape for teachers / classes / classrooms — the `entity_type`
    discriminator picks which target the rule applies to.

    `kind` discriminates the four constraint types:
       hard      - DNF must be satisfied (busy/unavailable side)
       soft      - violation costs +soft_penalty
       preferred - satisfaction grants -|soft_penalty| (objective bonus)
       enforced  - DNF must be satisfied AND interpreted as 'the entity
                   MUST have a lesson in at least one of the slot blocks'
    is_hard is kept for backwards-compat (kind='hard' iff is_hard=True);
    the sign of soft_penalty (when not hard) still distinguishes soft
    from preferred.
    """
    __tablename__ = "logical_unavailabilities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(
        String(16), index=True,
        comment="teacher | class | classroom"
    )
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    expression: Mapped[str] = mapped_column(Text)
    parsed_dnf_json: Mapped[str] = mapped_column(Text, default="[]")
    is_hard: Mapped[bool] = mapped_column(Boolean, default=True)
    soft_penalty: Mapped[int] = mapped_column(Integer, default=100)
    kind: Mapped[str] = mapped_column(
        String(16), default="hard",
        comment="hard | soft | preferred | enforced"
    )


class CoteachGroup(Base):
    """Task C1: a group of Assignments that teach the same
    (class, subject) jointly for `n_hours` hours per week. Each
    member carries the back-FK `Assignment.coteach_group_id`.

    Semantics:
    - `n_hours` of the cattedra's hours are co-taught (typically a
      lab or pratico subset of the weekly hours). The remaining
      hours are taught by the principal teacher alone; the engine
      reads `n_hours` from this row and the total from the
      principal's `Assignment.hours`.
    - `required=True`: HARD constraint (the n_hours overlap must
      hold). False: SOFT, weight applied when violated.
    """
    __tablename__ = "coteach_groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_id: Mapped[int | None] = mapped_column(
        ForeignKey("school_classes.id", ondelete="CASCADE"),
        nullable=True, index=True,
        comment="non-NULL when coteaching applies to a class. "
                "XOR with group_id."
    )
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("study_groups.id", ondelete="CASCADE"),
        nullable=True, index=True,
        comment="Task C3: non-NULL when coteaching applies to a "
                "StudyGroup. XOR with class_id."
    )
    subject: Mapped[str] = mapped_column(String(64))
    n_hours: Mapped[int] = mapped_column(
        Integer, default=1,
        comment="number of hours that must be co-taught"
    )
    kind: Mapped[str] = mapped_column(
        String(16), default="shared",
        comment="reserved for future variants; only 'shared' supported"
    )
    required: Mapped[bool] = mapped_column(
        Boolean, default=True,
        comment="HARD if true; SOFT otherwise"
    )
    weight: Mapped[float] = mapped_column(
        Float, default=100.0,
        comment="SOFT penalty when the n_hours overlap is broken"
    )
    school_class: Mapped["SchoolClass | None"] = relationship()
    study_group: Mapped["StudyGroup | None"] = relationship()
    assignments: Mapped[list["Assignment"]] = relationship(
        back_populates="coteach_group"
    )
    __table_args__ = (
        UniqueConstraint("class_id", "subject",
                         name="uq_coteach_group_cl_subj"),
        UniqueConstraint("group_id", "subject",
                         name="uq_coteach_group_g_subj"),
    )


class CoTeachingRule(Base):
    """LEGACY (Task C1): superseded by `CoteachGroup` + the per-row
    `Assignment.coteach_group_id` FK. Kept temporarily for backward
    compatibility with import/export pipelines that may still emit
    rows of this shape; the data migration in alembic moves the
    payload into CoteachGroup at upgrade time.

    Originally: a rule that says `for class X, subject S, the lesson
    must (or preferably) be co-taught by N teachers`. The teacher
    list was kept as `teacher_csv`."""
    __tablename__ = "coteaching_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_id: Mapped[int] = mapped_column(
        ForeignKey("school_classes.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(String(64))
    required: Mapped[bool] = mapped_column(
        Boolean, default=True,
        comment="HARD if true; SOFT preference otherwise"
    )
    weight: Mapped[float] = mapped_column(
        Float, default=100.0,
        comment="penalty when SOFT and rule is broken"
    )
    n_teachers: Mapped[int] = mapped_column(Integer, default=2)
    teacher_csv: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="optional comma-separated explicit list of co-teachers"
    )
    school_class: Mapped["SchoolClass"] = relationship()
    __table_args__ = (
        UniqueConstraint("class_id", "subject", name="uq_coteach_cl_subj"),
    )


# ---------- Curricula (indirizzi di studio) ----------


class Curriculum(TenantMixin, TimestampMixin, Base):
    """An indirizzo di studio (e.g. Scientifico, Linguistico, ITIS) with its
    own monte-ore per anno and curriculum-level logical constraints."""
    __tablename__ = "curricula"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True,
                                      comment="machine name e.g. 'Scientifico'")
    name: Mapped[str] = mapped_column(String(120),
                                      comment="display name")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[int] = mapped_column(
        Integer, default=1,
        comment="curriculum_score used by the engine (mock_classes2 jargon)"
    )
    hours: Mapped[list["CurriculumSubjectHours"]] = relationship(
        back_populates="curriculum", cascade="all, delete-orphan"
    )
    constraints: Mapped[list["CurriculumLogicalConstraint"]] = relationship(
        back_populates="curriculum", cascade="all, delete-orphan"
    )


class CurriculumSubjectHours(Base):
    """Monte ore for (curriculum, year, subject). Together they form the
    weekly grid an indirizzo expects for each year of course."""
    __tablename__ = "curriculum_subject_hours"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    curriculum_id: Mapped[int] = mapped_column(
        ForeignKey("curricula.id", ondelete="CASCADE"), index=True
    )
    year: Mapped[int] = mapped_column(Integer, index=True)
    subject: Mapped[str] = mapped_column(String(64), index=True)
    hours_per_week: Mapped[int] = mapped_column(Integer, default=0)
    curriculum: Mapped["Curriculum"] = relationship(back_populates="hours")
    __table_args__ = (
        UniqueConstraint("curriculum_id", "year", "subject",
                         name="uq_curr_year_subj"),
    )


class CurriculumLogicalConstraint(Base):
    """Curriculum-level logical (DNF) constraint. Optionally restricted to
    a specific year_filter (NULL means it applies to every year).

    Same DNF shape as LogicalUnavailability, but stored separately because
    it carries an extra `year_filter` column and resolves to many entities
    (every class with this curriculum) at solver time, not a single one."""
    __tablename__ = "curriculum_logical_constraints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    curriculum_id: Mapped[int] = mapped_column(
        ForeignKey("curricula.id", ondelete="CASCADE"), index=True
    )
    year_filter: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="NULL = applies to all years of this curriculum"
    )
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expression: Mapped[str] = mapped_column(Text)
    parsed_dnf_json: Mapped[str] = mapped_column(Text, default="[]")
    is_hard: Mapped[bool] = mapped_column(Boolean, default=True)
    soft_penalty: Mapped[int] = mapped_column(Integer, default=100)
    kind: Mapped[str] = mapped_column(
        String(16), default="hard",
        comment="hard | soft | preferred | enforced"
    )
    curriculum: Mapped["Curriculum"] = relationship(back_populates="constraints")


# ---------- Students ----------


class Student(TenantMixin, TimestampMixin, Base):
    """A student record. Optionally associated to a single home class.
    Students can also belong to one or more StudyGroup via GroupMembership
    (e.g. a language group cutting across two classes)."""
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_name: Mapped[str] = mapped_column(String(80), index=True)
    first_name: Mapped[str] = mapped_column(String(80), index=True)
    nickname: Mapped[str | None] = mapped_column(
        String(80), nullable=True,
        comment="abbreviation shown in the timetable; defaults to "
                "'<last_name> <first_name>' when displayed."
    )
    birth_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(8), nullable=True,
                                               comment="M | F | other")
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    student_code: Mapped[str | None] = mapped_column(
        String(40), nullable=True, index=True,
        comment="external id (matricola/codice studente)"
    )
    class_id: Mapped[int | None] = mapped_column(
        ForeignKey("school_classes.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    school_class: Mapped["SchoolClass | None"] = relationship()
    memberships: Mapped[list["GroupMembership"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    tag_assignments: Mapped[list["StudentTagAssignment"]] = relationship(
        back_populates="student", cascade="all, delete-orphan",
        passive_deletes=True,
    )
    __table_args__ = (
        UniqueConstraint("last_name", "first_name", "birth_date",
                         name="uq_student_identity"),
    )


class StudentTag(Base):
    """Lightweight label attachable to students (many-to-many).

    Examples used in production:
      - 'BES', 'DSA' (special needs)
      - 'debito_matematica_4' (subject debt by year)
      - 'pcto_ditta_X' (work-study placement at company X)
      - 'studente_atleta' (athletic-student flexibility)

    Tags are passive metadata for filtering / grouping; they do NOT
    replace StudyGroup. They can be queried with
      `forall s in students where "BES" in s.tags: ...`
    in the general DSL, or `has_tag(BES)` in the students list.
    """
    __tablename__ = "student_tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignments: Mapped[list["StudentTagAssignment"]] = relationship(
        back_populates="tag", cascade="all, delete-orphan",
        passive_deletes=True,
    )


class StudentTagAssignment(Base):
    """Join row: student <-> tag."""
    __tablename__ = "student_tag_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("student_tags.id", ondelete="CASCADE"), index=True
    )
    student: Mapped["Student"] = relationship(
        back_populates="tag_assignments"
    )
    tag: Mapped["StudentTag"] = relationship(
        back_populates="assignments"
    )
    __table_args__ = (
        UniqueConstraint("student_id", "tag_id", name="uq_student_tag"),
    )


class RunTelemetry(Base):
    """Time-series telemetry of a Run.

    One row per (run_id, step) sample. The solver/metaheuristic
    modules push samples via `utils.telemetry.collect()` at a
    sane sampling cadence (~100ms or per iteration).

    Stored fields:
      - run_id:   FK Runs.id
      - step:     monotonic counter inside the producer
      - timestamp_s:  seconds since the run started (float)
      - phase:    'phase_a' | 'phase_b_decomp' | 'stage_lns' |
                   'stage_alns' | 'stage_sa' | 'stage_ts' |
                   'stage_vns' | 'stage_ils' | 'stage_lagrangian' |
                   'stage_cg' | 'rooms' | ...
      - payload_json:  small JSON blob with stage-specific metrics
                        (objective_value, hard_violations_count,
                         placed_events_pct, accepted_moves, ...).

    Indexed on (run_id, step) for fast paginated reads.
    """
    __tablename__ = "run_telemetry"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    step: Mapped[int] = mapped_column(Integer, default=0)
    timestamp_s: Mapped[float] = mapped_column(Float, default=0.0)
    phase: Mapped[str] = mapped_column(String(32), index=True,
                                         default="")
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        UniqueConstraint("run_id", "step", "phase",
                          name="uq_run_telemetry_step"),
    )


class SavedView(TimestampMixin, Base):
    """A named filter+sort combination saved by the user for an
    entity list (teachers, classes, classrooms, ...).

    The frontend stores `dsl_query` (string, fed back into `?q=`)
    and `sort_levels_json` (JSON-encoded list of {column, direction}
    objects, fed back into `?sort=`). The (entity, name) pair is
    UNIQUE.
    """
    __tablename__ = "saved_views"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(40), index=True,
                                         comment="teachers|classes|...")
    name: Mapped[str] = mapped_column(String(120))
    dsl_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_levels_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON list of {column, direction:'asc'|'desc'}",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        UniqueConstraint("entity", "name", name="uq_saved_view"),
    )


# ---------- Study groups (gruppi articolati / classi frazionate) ----------


class StudyGroup(TenantMixin, TimestampMixin, Base):
    """A study group cutting across one or more classes (type C semantics).

    Examples: 'IRC vs Alternativa', 'Spagnolo vs Tedesco', 'Recupero
    matematica 1A+1B'. Members are listed in GroupMembership; ore per
    materia in GroupSubjectHours.

    `kind` is a free-text discriminator (e.g. language, religion,
    splitting, support). The solver treats a group as a virtual class
    that meets for the listed subjects and whose members must not be
    scheduled in their home class for the same slot."""
    __tablename__ = "study_groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    nickname: Mapped[str | None] = mapped_column(
        String(80), nullable=True,
        comment="abbreviation shown in the timetable; defaults to name"
    )
    kind: Mapped[str] = mapped_column(
        String(32), default="splitting",
        comment="splitting | language | religion | support | other"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    members: Mapped[list["GroupMembership"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    subject_hours: Mapped[list["GroupSubjectHours"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupMembership(Base):
    """A student belongs to a study group."""
    __tablename__ = "group_memberships"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("study_groups.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    group: Mapped["StudyGroup"] = relationship(back_populates="members")
    student: Mapped["Student"] = relationship(back_populates="memberships")
    __table_args__ = (
        UniqueConstraint("group_id", "student_id", name="uq_group_student"),
    )


class Absence(Base):
    """A single-day absence of a teacher (illness, off-site duty, ...).
    The substitution UI uses these together with the active timetable
    solution to compute per-slot coverage status."""
    __tablename__ = "absences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    teacher: Mapped["Teacher"] = relationship()
    __table_args__ = (
        UniqueConstraint("teacher_id", "date", name="uq_absence_teacher_date"),
    )


class SubstituteAssignment(Base):
    """A substitute teacher assigned to cover a specific (date, day, hour,
    class) slot left uncovered by a teacher absence. The assignment is
    keyed on the slot tuple so we can have at most one substitute per
    uncovered lesson."""
    __tablename__ = "substitute_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    day: Mapped[int] = mapped_column(Integer)
    hour: Mapped[int] = mapped_column(Integer)
    class_name: Mapped[str] = mapped_column(String(40))
    subject: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_teacher_name: Mapped[str] = mapped_column(String(120),
                                                       index=True)
    substitute_teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    substitute: Mapped["Teacher | None"] = relationship()
    __table_args__ = (
        UniqueConstraint("date", "day", "hour", "class_name",
                         name="uq_sub_slot"),
    )


class GroupSubjectHours(Base):
    """The hours-per-week the group meets for a given subject. The same
    group can have several subjects (e.g. IRC + religion teacher)."""
    __tablename__ = "group_subject_hours"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("study_groups.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(String(64), index=True)
    hours_per_week: Mapped[int] = mapped_column(Integer, default=1)
    group: Mapped["StudyGroup"] = relationship(back_populates="subject_hours")
    __table_args__ = (
        UniqueConstraint("group_id", "subject", name="uq_group_subj"),
    )


class ConstraintIntervention(Base):
    """Audit trail for the interventions applied via the
    FeasibilityPanel "Applica suggerimento" / "Modifica" buttons.

    Each row records: who/what was modified, the action taken
    (remove / soften / disable / restore), the value before and
    after, and a timestamp. This lets the user revert a wrong
    intervention without losing the original constraint, and lets
    the system show an "audit history" panel.
    """
    __tablename__ = "constraint_interventions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, index=True)
    action: Mapped[str] = mapped_column(
        String(24), index=True,
        comment="remove | soften | disable | enable | edit | restore")
    target_kind: Mapped[str] = mapped_column(
        String(48),
        comment=("logical_teacher | logical_class | logical_classroom |"
                 " logical_curriculum | teacher_cell | class_cell |"
                 " room_cell | coteach"))
    target_id: Mapped[int] = mapped_column(Integer, index=True)
    target_owner_label: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
        comment="human-readable owner label captured at intervention time")
    before_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON-serialised before-state (level, expression, weight)")
    after_json: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON-serialised after-state; null for hard removals")
    reverted: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True,
        comment="True after a successful 'restore' action")
    reverted_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("constraint_interventions.id"),
        nullable=True,
        comment="when this intervention has been reverted, the id of "
                "the restore intervention that did it")
    note: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="optional free-form note (e.g. 'applied from "
                "FeasibilityPanel suggestion')")
