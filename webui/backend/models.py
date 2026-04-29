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
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


# ---------- value-object helpers ----------


class JSONColumn(Text):
    """Text column carrying JSON strings."""


def utcnow() -> dt.datetime:
    return dt.datetime.utcnow()


# ---------- Subjects ----------


class Subject(Base):
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


class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    matricola: Mapped[str | None] = mapped_column(String(40), nullable=True)
    group: Mapped[str | None] = mapped_column(String(40), nullable=True,
                                              comment="classe di concorso")
    max_hours: Mapped[int] = mapped_column(Integer, default=18)
    completion_hours: Mapped[int] = mapped_column(Integer, default=0)
    exemption_hours: Mapped[int] = mapped_column(Integer, default=0)
    free_day: Mapped[str | None] = mapped_column(String(16), nullable=True,
                                                 comment="day name (Italian)")
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


# ---------- Classes ----------


class SchoolClass(Base):
    __tablename__ = "school_classes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    year: Mapped[int] = mapped_column(Integer, default=1)
    section: Mapped[str | None] = mapped_column(String(8), nullable=True)
    curriculum: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    targeted manual overrides."""
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    class_id: Mapped[int] = mapped_column(
        ForeignKey("school_classes.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(String(64))
    hours: Mapped[int] = mapped_column(Integer, default=0)
    locked: Mapped[bool] = mapped_column(Boolean, default=False,
                                         comment="true => cannot be changed "
                                         "by the optimizer")
    teacher: Mapped["Teacher"] = relationship()
    school_class: Mapped["SchoolClass"] = relationship()
    __table_args__ = (
        UniqueConstraint("class_id", "subject", name="uq_assign_cl_subj"),
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


class AppState(Base):
    __tablename__ = "app_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")


# ---------- Classrooms (aule) ----------


class Classroom(Base):
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


class ClassroomSubjectPreference(Base):
    """Soft preference: this subject prefers being held in this classroom."""
    __tablename__ = "classroom_subject_preferences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    classroom_id: Mapped[int] = mapped_column(
        ForeignKey("classrooms.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(String(64))
    weight: Mapped[float] = mapped_column(Float, default=10.0)
    required: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="HARD: subject can only be in this kind of room if true"
    )
    classroom: Mapped["Classroom"] = relationship(back_populates="subject_prefs")
    __table_args__ = (
        UniqueConstraint("classroom_id", "subject", name="uq_room_subj"),
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

    The DNF is `[clause1, clause2, ...]` where each clause is a list of
    `{day, hour, negate}` literals. The constraint is satisfied iff at
    least one clause is fully active (i.e. all its literals hold) on the
    timetable.
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


class CoTeachingRule(Base):
    """A rule that says: for class X, subject S, the lesson must (or
    preferably) be co-taught by N teachers. The ASSIGNMENT step honors
    this by linking N teachers to (class, subject); during scheduling the
    lessons MUST share the same slot."""
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
