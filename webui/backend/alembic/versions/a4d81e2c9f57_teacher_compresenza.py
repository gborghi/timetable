"""teacher compresenza policy + per-hour cells

Aggiunge ``teachers.compresenza`` ('mai' | 'sempre' | 'oraria') e la
tabella ``teacher_compresenza_hours`` con le celle (giorno, ora) in cui
la compresenza e` ammessa quando il modo e` 'oraria'.

Perche` serve: una compresenza e` per definizione due docenti nella
STESSA aula sulla stessa classe e la stessa ora. Senza un modo di
dichiararla, lo step aule contava ogni ora di compresenza come una
richiesta d'aula separata e diventava insoddisfacibile (in una scuola
con 60 classi e 387 ore di sostegno: 2115 richieste contro 1728 celle
reali). Non si puo` dedurre la regola da "stessa classe, stessa ora",
perche` gli sdoppiamenti veri (Religione / Attivita` alternativa,
gruppi di lingua) mettono davvero la classe in due aule.

Il default 'mai' e` scelto per non cambiare la forma di un DB
esistente: prima di questa revisione ogni lezione prenotava un'aula
propria, e continua a farlo finche` la scuola non dichiara chi sta in
compresenza.

UNICA eccezione, ed e` il "preset sostegno": i docenti che hanno gia`
almeno una cattedra con ``is_support=1`` passano a 'sempre'. Non e` una
scelta di politica scolastica travestita da migrazione -- per loro il
comportamento storico non era semplicemente "diverso", era
insoddisfacibile (il docente di sostegno seguiva il proprio alunno in
un'aula fisica diversa da quella della sua classe, cosa che non
esiste). Resta comunque modificabile per docente dalla UI.


Revision ID: a4d81e2c9f57
Revises: f31a7c9d2b48
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4d81e2c9f57"
down_revision: Union[str, Sequence[str], None] = "f31a7c9d2b48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp, table: str, column: str) -> bool:
    if not insp.has_table(table):
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    if not _has_column(insp, "teachers", "compresenza"):
        with op.batch_alter_table("teachers") as batch:
            batch.add_column(sa.Column(
                "compresenza", sa.String(16),
                nullable=False, server_default="mai",
            ))
        # Preset sostegno -- vedi il docstring.
        if _has_column(insp, "assignments", "is_support"):
            op.execute(
                "UPDATE teachers SET compresenza = 'sempre' "
                "WHERE id IN (SELECT teacher_id FROM assignments "
                "             WHERE is_support = 1)"
            )

    if not insp.has_table("teacher_compresenza_hours"):
        op.create_table(
            "teacher_compresenza_hours",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("teacher_id", sa.Integer(), nullable=False),
            sa.Column("day", sa.Integer(), nullable=False),
            sa.Column("hour", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["teacher_id"], ["teachers.id"], ondelete="CASCADE",
            ),
            sa.UniqueConstraint("teacher_id", "day", "hour",
                                name="uq_teacher_compresenza_hour"),
        )
        op.create_index("ix_teacher_compresenza_hours_teacher_id",
                        "teacher_compresenza_hours", ["teacher_id"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table("teacher_compresenza_hours"):
        op.drop_index("ix_teacher_compresenza_hours_teacher_id",
                      table_name="teacher_compresenza_hours")
        op.drop_table("teacher_compresenza_hours")
    if _has_column(insp, "teachers", "compresenza"):
        with op.batch_alter_table("teachers") as batch:
            batch.drop_column("compresenza")
