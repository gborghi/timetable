"""CLI: report (and optionally refuse) integrity-CHECK violators.

Usage, from ``webui/``::

    PYTHONPATH=. python -m backend.scripts.audit_integrity
    PYTHONPATH=. python -m backend.scripts.audit_integrity --fix-required

Exit codes:
    0  clean (or only derived-required rows, after ``--fix-required``)
    1  XOR violators remain
    2  usage / connection error
"""
from __future__ import annotations

import argparse
import json
import sys

from backend.db import engine
from backend.integrity_checks import (
    audit_integrity,
    fix_derived_required,
    format_audit_error,
    summarize,
    xor_violations,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--fix-required",
        action="store_true",
        help="rewrite classroom_subject_preferences.required from state",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print the report as JSON",
    )
    args = p.parse_args(argv)

    with engine.begin() as conn:
        n_fixed = 0
        if args.fix_required:
            n_fixed = fix_derived_required(conn)
        report = audit_integrity(conn)

    summary = summarize(report, fixed_required=n_fixed)
    if args.as_json:
        print(json.dumps(summary, indent=2))
    else:
        if n_fixed:
            print(f"rewrote required on {n_fixed} row(s)")
        if xor_violations(report):
            print(format_audit_error(report), file=sys.stderr)
        elif report["csp_required"]:
            print(
                "derived required still drifted on ids: "
                + ", ".join(str(i) for i in report["csp_required"]),
                file=sys.stderr,
            )
        else:
            print("integrity: clean")
    return 1 if xor_violations(report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
