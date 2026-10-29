"""Limite richieste: 429 vero e memoria con tetto."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main as app_main  # noqa: E402


def test_rate_limit_returns_wait_and_bounds_keys():
    app_main._rate_limit_state.clear()
    app_main._RATE_LIMIT_MAX_KEYS = 3
    try:
        assert app_main.rate_limit_decision("a", 0.0, 1) is None
        wait = app_main.rate_limit_decision("a", 0.1, 1)
        assert wait is not None and wait > 0
        app_main.rate_limit_decision("b", 1.0, 1)
        app_main.rate_limit_decision("c", 2.0, 1)
        app_main.rate_limit_decision("d", 3.0, 1)
        assert len(app_main._rate_limit_state) <= 3
    finally:
        app_main._rate_limit_state.clear()
        app_main._RATE_LIMIT_MAX_KEYS = 4096
