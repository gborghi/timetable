"""Audit and apply the three integrity CHECKs declared on models.py.

Fresh DBs get the CHECKs from ``Base.metadata.create_all``. Existing
DBs never did: ``create_all`` does not add CHECKs to tables that
already exist, and no Alembic revision shipped them.

This module is the single implementation used by:

* alembic revision ``c8d9e0f1a2b3`` (adds the CHECKs after a data audit)
* ``db._apply_lightweight_migrations`` (audit + derived-column fix;
  SQLite cannot ADD CHECK without a table rebuild, so the lightweight
  path does not try)
* ``backend/scripts/audit_integrity.py`` (CLI)
* tests

The three invariants:

* ``ck_assign_class_group_xor`` — Assignment is class-bound XOR
  group-bound, or both-NULL only when ``is_potenziamento``.
* ``ck_coteach_class_group_xor`` — CoteachGroup targets exactly one
  of class / group.
* ``ck_csp_required_matches_state`` — ``ClassroomSubjectPreference.required``
  is derived from ``state = 'enforced'``.

XOR violators are reported, never auto-deleted. The derived
``required`` flag is auto-fixed (it is not independent data).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

ASSIGN_XOR_SQL = (
    "(class_id IS NOT NULL AND group_id IS NULL) "
    "OR (class_id IS NULL AND group_id IS NOT NULL) "
    "OR (class_id IS NULL AND group_id IS NULL "
    "AND is_potenziamento = 1)"
)

COTEACH_XOR_SQL = "(class_id IS NOT NULL) <> (group_id IS NOT NULL)"

CSP_REQUIRED_SQL = "required = (state = 'enforced')"

ASSIGN_XOR_NAME = "ck_assign_class_group_xor"
COTEACH_XOR_NAME = "ck_coteach_class_group_xor"
CSP_REQUIRED_NAME = "ck_csp_required_matches_state"


def _table_exists(conn: Connection, table: str) -> bool:
    dialect = conn.dialect.name
    if dialect == "sqlite":
        row = conn.execute(
            text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name=:t"
            ),
            {"t": table},
        ).fetchone()
        return row is not None
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :t"
        ),
        {"t": table},
    ).fetchone()
    return row is not None


def has_check(conn: Connection, table: str, name: str) -> bool:
    """True when *table* already carries a CHECK named *name*."""
    dialect = conn.dialect.name
    if dialect == "sqlite":
        row = conn.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name=:t"
            ),
            {"t": table},
        ).fetchone()
        sql = (row[0] or "") if row else ""
        return name in sql
    row = conn.execute(
        text(
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = :n"
        ),
        {"n": name},
    ).fetchone()
    return row is not None


def _ids(conn: Connection, sql: str) -> list[int]:
    return [int(r[0]) for r in conn.execute(text(sql)).fetchall()]


def audit_integrity(conn: Connection) -> dict[str, list[int]]:
    """Return violating primary keys, grouped by invariant.

    Missing tables yield empty lists (a mid-upgrade DB is not a
    violation).
    """
    out: dict[str, list[int]] = {
        "assignment_xor": [],
        "coteach_xor": [],
        "csp_required": [],
    }
    if _table_exists(conn, "assignments"):
        out["assignment_xor"] = _ids(
            conn,
            "SELECT id FROM assignments WHERE NOT ("
            + ASSIGN_XOR_SQL
            + ")",
        )
    if _table_exists(conn, "coteach_groups"):
        out["coteach_xor"] = _ids(
            conn,
            "SELECT id FROM coteach_groups WHERE NOT ("
            + COTEACH_XOR_SQL
            + ")",
        )
    if _table_exists(conn, "classroom_subject_preferences"):
        out["csp_required"] = _ids(
            conn,
            "SELECT id FROM classroom_subject_preferences "
            "WHERE NOT (" + CSP_REQUIRED_SQL + ")",
        )
    return out


def fix_derived_required(conn: Connection) -> int:
    """Force ``required`` to match ``state = 'enforced'``.

    Returns the number of rows rewritten. No-op when the table is
    missing. Safe: ``required`` is a derived column, not independent
    data.
    """
    if not _table_exists(conn, "classroom_subject_preferences"):
        return 0
    result = conn.execute(
        text(
            "UPDATE classroom_subject_preferences "
            "SET required = (state = 'enforced') "
            "WHERE NOT (" + CSP_REQUIRED_SQL + ")"
        )
    )
    return int(result.rowcount or 0)


def format_audit_error(report: dict[str, list[int]]) -> str:
    """Human-readable refusal used when XOR rows block a CHECK add."""
    lines = [
        "Integrity CHECKs cannot be added: XOR-violating rows "
        "are still in the database. Inspect / delete / repair "
        "them, then re-run `alembic upgrade head`.",
    ]
    if report["assignment_xor"]:
        ids = ", ".join(str(i) for i in report["assignment_xor"][:20])
        extra = (
            f" (+{len(report['assignment_xor']) - 20} more)"
            if len(report["assignment_xor"]) > 20
            else ""
        )
        lines.append(
            f"  assignments (ck_assign_class_group_xor) ids: {ids}{extra}"
        )
    if report["coteach_xor"]:
        ids = ", ".join(str(i) for i in report["coteach_xor"][:20])
        extra = (
            f" (+{len(report['coteach_xor']) - 20} more)"
            if len(report["coteach_xor"]) > 20
            else ""
        )
        lines.append(
            f"  coteach_groups (ck_coteach_class_group_xor) ids: {ids}{extra}"
        )
    return "\n".join(lines)


def xor_violations(report: dict[str, list[int]]) -> list[int]:
    return list(report["assignment_xor"]) + list(report["coteach_xor"])


def raise_if_xor_dirty(report: dict[str, list[int]]) -> None:
    if xor_violations(report):
        raise RuntimeError(format_audit_error(report))


def summarize(report: dict[str, list[int]], *, fixed_required: int = 0) -> dict[str, Any]:
    return {
        "assignment_xor": list(report["assignment_xor"]),
        "coteach_xor": list(report["coteach_xor"]),
        "csp_required": list(report["csp_required"]),
        "fixed_required": int(fixed_required),
        "clean": not xor_violations(report) and not report["csp_required"],
    }
