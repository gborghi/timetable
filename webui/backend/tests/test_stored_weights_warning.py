"""_stored_objective_weights: solo un errore di DB ricade sul default,
con un warning; gli altri errori non vengono nascosti."""
from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError


def test_db_error_warns_and_returns_none(monkeypatch):
    from backend import optimization as opt

    def boom():
        raise OperationalError("SELECT", {}, Exception("db assente"))
    monkeypatch.setattr(opt, "SessionLocal", boom)
    with pytest.warns(RuntimeWarning, match="Pesi dell'obiettivo"):
        assert opt._stored_objective_weights() is None


def test_other_errors_are_not_swallowed(monkeypatch):
    from backend import optimization as opt

    def boom():
        raise KeyError("bug")
    monkeypatch.setattr(opt, "SessionLocal", boom)
    with pytest.raises(KeyError):
        opt._stored_objective_weights()
