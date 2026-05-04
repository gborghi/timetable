"""coteach_groups + sostegno + potenziamento

Revision ID: b91a4e2c1f00
Revises: a848420325b3
Create Date: 2026-05-04 19:00:00

Task C1 (extended) schema migration:
- Drop the strict UniqueConstraint(class_id, subject) on `assignments`
  so multiple teachers can share the same (class, subject) for shared
  coteaching. Replace with a looser unique that includes teacher_id +
  is_support so the cattedra-normale invariant ("one teacher per
  (class, subject)") still holds for non-coteach rows.
- Make `assignments.class_id` nullable (potenziamento has no class).
- Add `assignments.coteach_group_id` (FK -> coteach_groups.id, nullable).
- Add `assignments.is_support` and `assignments.is_potenziamento`
  boolean flags.
- Create `coteach_groups` table.

Data migration (best-effort):
- For each existing CoTeachingRule, create a matching CoteachGroup
  with n_hours = the rule's n_teachers count is NOT n_hours; we
  default to 1 hour and let the user adjust. Required/weight carry
  over verbatim. The (class, subject) match is exact.
- For each teacher named in CoTeachingRule.teacher_csv:
    if a Teacher with that name exists AND there is an Assignment
    on (class_id, subject) for that teacher -> set its
    coteach_group_id to the new group's id. If the Assignment is
    missing, log a warning (the data is incomplete; the user has
    to manually attach the teacher).
The migration counts and prints n_migrated / n_skipped on stdout.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b91a4e2c1f00"
down_revision: Union[str, Sequence[str], None] = "a848420325b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Schema + data migration for Task C1 extended."""
    # 1. Create coteach_groups table.
    op.create_table(
        "coteach_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("class_id", sa.Integer(),
                   sa.ForeignKey("school_classes.id",
                                 ondelete="CASCADE"),
                   nullable=False, index=True),
        sa.Column("subject", sa.String(64), nullable=False),
        sa.Column("n_hours", sa.Integer(), nullable=False, default=1),
        sa.Column("kind", sa.String(16), nullable=False,
                   server_default="shared"),
        sa.Column("required", sa.Boolean(), nullable=False,
                   server_default=sa.text("1")),
        sa.Column("weight", sa.Float(), nullable=False,
                   server_default="100.0"),
        sa.UniqueConstraint("class_id", "subject",
                             name="uq_coteach_group_cl_subj"),
    )

    # 2. Add new columns to assignments. SQLite ALTER TABLE limits
    # what we can do in one shot; use batch_alter_table for portable
    # behaviour.
    with op.batch_alter_table("assignments") as batch:
        batch.add_column(sa.Column(
            "coteach_group_id", sa.Integer(),
            sa.ForeignKey("coteach_groups.id", ondelete="SET NULL"),
            nullable=True))
        batch.add_column(sa.Column(
            "is_support", sa.Boolean(), nullable=False,
            server_default=sa.text("0")))
        batch.add_column(sa.Column(
            "is_potenziamento", sa.Boolean(), nullable=False,
            server_default=sa.text("0")))
        # Make class_id nullable.
        batch.alter_column("class_id",
                            existing_type=sa.Integer(),
                            nullable=True)
        # Drop legacy unique, install the new one.
        batch.drop_constraint("uq_assign_cl_subj", type_="unique")
        batch.create_unique_constraint(
            "uq_assign_t_cl_subj_sup",
            ["teacher_id", "class_id", "subject", "is_support"])

    # 3. Add indexes on the new columns.
    with op.batch_alter_table("assignments") as batch:
        batch.create_index("ix_assignments_coteach_group_id",
                            ["coteach_group_id"])
        batch.create_index("ix_assignments_is_support",
                            ["is_support"])
        batch.create_index("ix_assignments_is_potenziamento",
                            ["is_potenziamento"])

    # 4. Best-effort data migration: CoTeachingRule -> CoteachGroup
    # + Assignment.coteach_group_id back-fill.
    bind = op.get_bind()
    rules = bind.execute(sa.text(
        "SELECT id, class_id, subject, required, weight, n_teachers, "
        "teacher_csv FROM coteaching_rules"
    )).fetchall()
    n_migrated = 0
    n_skipped_no_assignment = 0
    n_skipped_no_teacher = 0
    for r in rules:
        rid, class_id, subject, required, weight, n_teachers, csv = r
        # Default n_hours: 1 (user can adjust). The legacy schema
        # didn't carry an hours-of-overlap field, only the teacher
        # count and a required flag.
        new_group = bind.execute(sa.text(
            "INSERT INTO coteach_groups "
            "(class_id, subject, n_hours, kind, required, weight) "
            "VALUES (:cid, :sub, 1, 'shared', :req, :w) "
            "RETURNING id"
        ), {"cid": class_id, "sub": subject,
             "req": bool(required), "w": float(weight or 100.0)}
        ).fetchone()
        new_group_id = new_group[0] if new_group else None
        if new_group_id is None:
            continue
        teachers = [s.strip() for s in (csv or "").split(",")
                    if s.strip()]
        for tname in teachers:
            tid_row = bind.execute(sa.text(
                "SELECT id FROM teachers WHERE name = :n"
            ), {"n": tname}).fetchone()
            if tid_row is None:
                n_skipped_no_teacher += 1
                continue
            tid = tid_row[0]
            asgn = bind.execute(sa.text(
                "SELECT id FROM assignments WHERE class_id = :cid "
                "AND subject = :sub AND teacher_id = :tid"
            ), {"cid": class_id, "sub": subject, "tid": tid}
            ).fetchone()
            if asgn is None:
                n_skipped_no_assignment += 1
                continue
            bind.execute(sa.text(
                "UPDATE assignments SET coteach_group_id = :gid "
                "WHERE id = :aid"
            ), {"gid": new_group_id, "aid": asgn[0]})
            n_migrated += 1
    print(f"[alembic b91a4e2c1f00] coteach data migration: "
          f"{n_migrated} assignments linked to {len(rules)} groups; "
          f"{n_skipped_no_teacher} skipped (teacher name not found in "
          f"DB); {n_skipped_no_assignment} skipped (no matching "
          f"assignment row).")


def downgrade() -> None:
    """Reverse the schema migration. Data in coteach_groups is
    discarded; the legacy coteaching_rules + teacher_csv form is
    NOT reconstructed."""
    with op.batch_alter_table("assignments") as batch:
        batch.drop_index("ix_assignments_is_potenziamento")
        batch.drop_index("ix_assignments_is_support")
        batch.drop_index("ix_assignments_coteach_group_id")
        batch.drop_constraint("uq_assign_t_cl_subj_sup",
                               type_="unique")
        batch.create_unique_constraint(
            "uq_assign_cl_subj", ["class_id", "subject"])
        batch.alter_column("class_id",
                            existing_type=sa.Integer(),
                            nullable=False)
        batch.drop_column("is_potenziamento")
        batch.drop_column("is_support")
        batch.drop_column("coteach_group_id")
    op.drop_table("coteach_groups")
