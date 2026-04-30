"""Unit tests for the Phase-A objective DSL parser + validator."""
from __future__ import annotations

import pytest

from backend.utils.objective_dsl import (
    parse,
    validate,
    PRESETS,
    get_preset,
)


# ============================================================
# Parser
# ============================================================


def test_parse_minimal():
    ast = parse("minimize 5")
    assert ast["direction"] == "minimize"
    assert ast["expr"]["node"] == "num"


def test_parse_arithmetic():
    ast = parse("minimize 2 * total_unused_capacity + 100")
    assert ast["direction"] == "minimize"
    assert ast["expr"]["node"] == "binop"


def test_parse_call():
    ast = parse("minimize sum(under_min_hours(18))")
    assert ast["direction"] == "minimize"
    e = ast["expr"]
    assert e["node"] == "call"
    assert e["name"] == "sum"
    assert e["args"][0]["node"] == "call"
    assert e["args"][0]["name"] == "under_min_hours"


def test_parse_missing_direction():
    with pytest.raises(SyntaxError):
        parse("5 + 3")


def test_parse_unbalanced_paren():
    with pytest.raises(SyntaxError):
        parse("minimize (5 + 3")


# ============================================================
# Validator
# ============================================================


def test_validate_preset_balance():
    expr = (
        "minimize 50 * total_unused_capacity + 100 * total_n_classes "
        "- 5 * total_n_curricula + 5000 * n_under_18"
    )
    res = validate(expr)
    assert res.ok, res.errors
    assert res.direction == "minimize"


def test_validate_per_teacher_outside_aggregate():
    res = validate("minimize teacher_hours")
    assert not res.ok
    assert any("per-docente" in e or "aggregato" in e for e in res.errors)


def test_validate_predicate_outside_aggregate():
    res = validate("minimize cross_curricula()")
    assert not res.ok
    assert any("aggregato" in e for e in res.errors)


def test_validate_unknown_identifier():
    res = validate("minimize foo_bar")
    assert not res.ok
    assert any("sconosciuto" in e.lower() for e in res.errors)


def test_validate_unknown_function():
    res = validate("minimize ciao(5)")
    assert not res.ok


def test_validate_non_linear_function():
    res = validate("minimize stddev(teacher_weight)")
    assert not res.ok
    assert any("non lineare" in e.lower() for e in res.errors)


def test_validate_var_times_var():
    res = validate("minimize total_unused_capacity * total_n_classes")
    assert not res.ok
    assert any("non lineare" in e.lower() for e in res.errors)


def test_validate_division_by_constant():
    res = validate("minimize total_n_classes / 2")
    assert res.ok, res.errors


def test_validate_division_by_var_rejected():
    res = validate("minimize 2 / total_n_classes")
    assert not res.ok


def test_validate_arity_predicate():
    # under_min_hours wants 1 arg
    res = validate("minimize sum(under_min_hours())")
    assert not res.ok
    assert any("argomenti" in e for e in res.errors)


def test_validate_aggregate_arity():
    res = validate("minimize sum(teacher_hours, teacher_weight)")
    assert not res.ok


# ============================================================
# Presets
# ============================================================


def test_all_presets_validate_ok():
    """Every shipped preset must be a valid DSL expression."""
    for key, label, summary, expr in PRESETS:
        res = validate(expr)
        assert res.ok, f"preset {key!r} is invalid: {res.errors}"


def test_get_preset_lookup():
    p = get_preset("balance_curricula")
    assert p is not None
    assert p[0] == "balance_curricula"
    assert get_preset("does_not_exist") is None
