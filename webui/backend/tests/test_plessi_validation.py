"""Pre-flight validation tests for the PLESSI feature (P2).

Verifies that ``optimization.validate_plessi_rules`` rejects every
inconsistent configuration described in the spec and accepts every
well-formed one.
"""
from __future__ import annotations


def _populate_minimal(db, models):
    """A tiny dataset useful as a baseline for the validation
    tests: 2 plessi, 1 teacher, 1 class, 1 group."""
    p1 = models.Plesso(name="Sede Centrale", code="C")
    p2 = models.Plesso(name="Succursale", code="S")
    db.add_all([p1, p2])
    db.commit()
    t = models.Teacher(name="Rossi")
    c = models.SchoolClass(name="1A")
    db.add_all([t, c])
    db.commit()
    db.refresh(p1)
    db.refresh(p2)
    db.refresh(t)
    db.refresh(c)
    g = models.StudyGroup(name="GruppoA")
    db.add(g)
    db.commit()
    db.refresh(g)
    return p1, p2, t, c, g


def test_validate_plessi_rules_accepts_no_plessi(app_with_temp_db):
    """An empty PLESSI configuration is valid."""
    from backend import optimization
    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        v = optimization.validate_plessi_rules(db)
    assert v == []


def test_validate_plessi_rules_accepts_well_formed(app_with_temp_db):
    """Two plessi, two well-formed rules: no violations."""
    from backend import optimization, models
    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        p1, p2, t, c, _g = _populate_minimal(db, models)
        rule = models.PlessoCommutingRule(
            from_plesso_id=p1.id, to_plesso_id=p2.id,
            entity_kind="teacher", entity_id=None,
            min_gap_hours=1)
        rule_per = models.PlessoCommutingRule(
            from_plesso_id=p1.id, to_plesso_id=p2.id,
            entity_kind="teacher", entity_id=t.id,
            min_gap_hours=2)
        pol = models.PlessoEntityPolicy(
            entity_kind="teacher", entity_id=t.id,
            policy="single_plesso_per_day")
        db.add_all([rule, rule_per, pol])
        db.commit()
        v = optimization.validate_plessi_rules(db)
    assert v == [], v


def test_validate_plessi_rules_invalid_from_plesso(app_with_temp_db):
    """Rule with non-existent from_plesso_id is reported."""
    from backend import optimization, models
    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        p1, p2, _t, _c, _g = _populate_minimal(db, models)
        rule = models.PlessoCommutingRule(
            from_plesso_id=999, to_plesso_id=p2.id,
            entity_kind="teacher", entity_id=None,
            min_gap_hours=0)
        db.add(rule)
        db.commit()
        v = optimization.validate_plessi_rules(db)
    assert any("from_plesso_id=999 non esiste" in m for m in v), v


def test_validate_plessi_rules_invalid_entity_kind(app_with_temp_db):
    from backend import optimization, models
    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        p1, p2, _t, _c, _g = _populate_minimal(db, models)
        rule = models.PlessoCommutingRule(
            from_plesso_id=p1.id, to_plesso_id=p2.id,
            entity_kind="zzz", entity_id=None,
            min_gap_hours=0)
        db.add(rule)
        db.commit()
        v = optimization.validate_plessi_rules(db)
    assert any("entity_kind='zzz'" in m for m in v), v


def test_validate_plessi_rules_invalid_entity_id_for_kind(app_with_temp_db):
    """entity_id=999 with entity_kind='teacher' but no such teacher."""
    from backend import optimization, models
    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        p1, p2, _t, _c, _g = _populate_minimal(db, models)
        rule = models.PlessoCommutingRule(
            from_plesso_id=p1.id, to_plesso_id=p2.id,
            entity_kind="teacher", entity_id=999,
            min_gap_hours=0)
        db.add(rule)
        db.commit()
        v = optimization.validate_plessi_rules(db)
    assert any("entity_id=999" in m for m in v), v


def test_validate_plessi_rules_negative_min_gap(app_with_temp_db):
    from backend import optimization, models
    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        p1, p2, _t, _c, _g = _populate_minimal(db, models)
        rule = models.PlessoCommutingRule(
            from_plesso_id=p1.id, to_plesso_id=p2.id,
            entity_kind="teacher", entity_id=None,
            min_gap_hours=-1)
        db.add(rule)
        db.commit()
        v = optimization.validate_plessi_rules(db)
    assert any("min_gap_hours" in m for m in v), v


def test_validate_plessi_rules_break_only_missing_hours(app_with_temp_db):
    from backend import optimization, models
    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        p1, p2, _t, _c, _g = _populate_minimal(db, models)
        rule = models.PlessoCommutingRule(
            from_plesso_id=p1.id, to_plesso_id=p2.id,
            entity_kind="teacher", entity_id=None,
            min_gap_hours=0,
            allowed_break_only=True,
            break_start_hour=None, break_end_hour=None)
        db.add(rule)
        db.commit()
        v = optimization.validate_plessi_rules(db)
    assert any("allowed_break_only" in m for m in v), v


def test_validate_plessi_rules_duplicate_kindwide(app_with_temp_db):
    """Two kind-wide rules for the same (from, to, kind) -- the
    DB UNIQUE doesn't catch this (NULL is distinct in SQL); the
    application validator does."""
    from backend import optimization, models
    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        p1, p2, _t, _c, _g = _populate_minimal(db, models)
        r1 = models.PlessoCommutingRule(
            from_plesso_id=p1.id, to_plesso_id=p2.id,
            entity_kind="teacher", entity_id=None,
            min_gap_hours=0)
        r2 = models.PlessoCommutingRule(
            from_plesso_id=p1.id, to_plesso_id=p2.id,
            entity_kind="teacher", entity_id=None,
            min_gap_hours=2)
        db.add_all([r1, r2])
        db.commit()
        v = optimization.validate_plessi_rules(db)
    assert any("regola kind-wide" in m for m in v), v


def test_validate_entity_policy_invalid_policy_value(app_with_temp_db):
    from backend import optimization, models
    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        p1, _p2, _t, _c, _g = _populate_minimal(db, models)
        pol = models.PlessoEntityPolicy(
            entity_kind="teacher", entity_id=None,
            policy="invalid_policy")
        db.add(pol)
        db.commit()
        v = optimization.validate_plessi_rules(db)
    assert any("policy='invalid_policy'" in m for m in v), v


def test_validate_entity_policy_plesso_id_only_on_single_total(
        app_with_temp_db):
    """plesso_id makes sense only with policy=single_plesso_total."""
    from backend import optimization, models
    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        p1, _p2, t, _c, _g = _populate_minimal(db, models)
        pol = models.PlessoEntityPolicy(
            entity_kind="teacher", entity_id=t.id,
            policy="single_plesso_per_day",
            plesso_id=p1.id)  # spurious
        db.add(pol)
        db.commit()
        v = optimization.validate_plessi_rules(db)
    assert any("plesso_id" in m and "single_plesso_per_day" in m
               for m in v), v


def test_validate_entity_policy_total_with_invalid_plesso(app_with_temp_db):
    from backend import optimization, models
    _app, TestSession = app_with_temp_db
    with TestSession() as db:
        _p1, _p2, t, _c, _g = _populate_minimal(db, models)
        pol = models.PlessoEntityPolicy(
            entity_kind="teacher", entity_id=t.id,
            policy="single_plesso_total",
            plesso_id=999)  # nonexistent
        db.add(pol)
        db.commit()
        v = optimization.validate_plessi_rules(db)
    assert any("plesso_id=999 non esiste" in m for m in v), v
