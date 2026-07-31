"""sostegno associato all'alunno, non alla classe

Revision ID: f31a7c9d2b48
Revises: e10c3fb9a4d1
Create Date: 2026-07-30 22:10:00

Two changes, both additive for existing data:

- `assignments.student_id` (FK -> students.id, ON DELETE SET NULL).
  This is the sostegno target: a support teacher is assigned to a
  *pupil*. `class_id` stays populated (it is the pupil's class) so
  every existing reader keeps working; nothing about existing rows
  changes, they simply have student_id NULL, which now means
  "class-level sostegno, pupil unknown".

- Replace the UNIQUE (teacher_id, class_id, subject, is_support) with
  a functional UNIQUE index that appends COALESCE(student_id, 0).
  Widening it with a bare `student_id` column would have *weakened*
  it: SQL counts NULLs as distinct, so every ordinary cattedra (which
  has student_id NULL) would have become trivially unique and
  duplicate cattedre would slip in. COALESCE pins them all to 0, so
  ordinary rows keep exactly the old rule while one teacher can now
  support two different pupils of the same class.

No data migration: is_support rows keep their subject ('sostegno')
and their class. Filling in student_id for them is a manual/UI step,
and the preflight check reports the ones still missing it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f31a7c9d2b48"
down_revision: Union[str, Sequence[str], None] = "e10c3fb9a4d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp, table: str, column: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("assignments"):
        return

    if not _has_column(insp, "assignments", "student_id"):
        with op.batch_alter_table("assignments") as batch:
            batch.add_column(sa.Column(
                "student_id", sa.Integer(),
                sa.ForeignKey("students.id", ondelete="SET NULL"),
                nullable=True))
        with op.batch_alter_table("assignments") as batch:
            batch.create_index("ix_assignments_student_id",
                               ["student_id"])

    # The old constraint may or may not exist depending on how far
    # this DB got through history; dropping it is best-effort so a
    # partially-migrated dev DB doesn't dead-end here.
    existing = {u["name"] for u in insp.get_unique_constraints(
        "assignments")}
    if "uq_assign_t_cl_subj_sup" in existing:
        with op.batch_alter_table("assignments") as batch:
            batch.drop_constraint("uq_assign_t_cl_subj_sup",
                                  type_="unique")

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_assign_t_cl_subj_sup_stu ON assignments "
        "(teacher_id, class_id, subject, is_support, "
        "COALESCE(student_id, 0))"
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("assignments"):
        return
    op.execute("DROP INDEX IF EXISTS uq_assign_t_cl_subj_sup_stu")
    with op.batch_alter_table("assignments") as batch:
        batch.create_unique_constraint(
            "uq_assign_t_cl_subj_sup",
            ["teacher_id", "class_id", "subject", "is_support"])
    if _has_column(insp, "assignments", "student_id"):
        with op.batch_alter_table("assignments") as batch:
            batch.drop_index("ix_assignments_student_id")
            batch.drop_column("student_id")
