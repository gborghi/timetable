"""Keep the `very_slow` benchmarks out of an ordinary test run.

Both benchmark modules document themselves as "NOT run by default", but
nothing enforced it: `very_slow` is a different marker from `slow`, so
the usual `-m "not slow"` selects them anyway and a plain
`pytest tests/` sat for 20+ minutes solving real CP-SAT models. The
documented workaround was to remember `--ignore=tests/benchmarks` on
every invocation; this makes the default match the docstrings instead.

Opting in is unchanged: `pytest tests/benchmarks -m very_slow`.
"""
from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config, items):
    if "very_slow" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(
        reason="very_slow benchmark; opt in with -m very_slow")
    for item in items:
        if "very_slow" in item.keywords:
            item.add_marker(skip)
