"""End-to-end school scenario tests.

Builds 3 canonical Italian-school scenarios via the framework in
`tests/scenarios/` and validates that Phase A + Phase B (and a
quick post-processing pass) produce a HARD-feasible timetable that
preserves all C1+C2+C3 invariants.

Scenarios are MODULE-SCOPED: each one builds the school once and
shares it across the tests in this file (Phase A on the medium
profile is ~30s; we don't want to pay it per test).

Tests are SLOW; tagged accordingly.
"""
from __future__ import annotations

import os
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
WEBUI_DIR = os.path.dirname(BACKEND_DIR)
REPO_ROOT = os.path.dirname(WEBUI_DIR)
ENGINE_DIR = os.path.join(REPO_ROOT, "engine")
SCHEDULE_DIR = os.path.join(REPO_ROOT, "schedule")
for p in (WEBUI_DIR, ENGINE_DIR, SCHEDULE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


# ----------------------------------------------------------------------
# Module-scoped fixture helpers
# ----------------------------------------------------------------------

def _make_module_db_session(tmp_path_factory, label: str):
    """Create a sqlite test DB + Session at module scope. The
    schema is built via Base.metadata.create_all + lightweight
    migrations (mirroring conftest._apply_migrations_on)."""
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import sessionmaker

    p = tmp_path_factory.mktemp(f"scen_{label}")
    url = f"sqlite:///{p / 'scen.db'}"
    test_engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        future=True,
    )
    TestSession = sessionmaker(
        bind=test_engine, autoflush=False, autocommit=False,
        future=True,
    )
    from backend import db as backend_db
    from backend import models  # noqa: F401  -- registers tables
    backend_db.Base.metadata.create_all(bind=test_engine)
    insp = inspect(test_engine)

    def has_col(tbl, col):
        if not insp.has_table(tbl):
            return False
        return any(c["name"] == col for c in insp.get_columns(tbl))

    with test_engine.begin() as conn:
        if insp.has_table("assignments"):
            for col, ddl in (
                ("coteach_group_id",
                 "ALTER TABLE assignments ADD COLUMN "
                 "coteach_group_id INTEGER"),
                ("is_support",
                 "ALTER TABLE assignments ADD COLUMN "
                 "is_support INTEGER NOT NULL DEFAULT 0"),
                ("is_potenziamento",
                 "ALTER TABLE assignments ADD COLUMN "
                 "is_potenziamento INTEGER NOT NULL DEFAULT 0"),
                ("parallel_group_id",
                 "ALTER TABLE assignments ADD COLUMN "
                 "parallel_group_id INTEGER"),
                ("group_id",
                 "ALTER TABLE assignments ADD COLUMN "
                 "group_id INTEGER"),
            ):
                if not has_col("assignments", col):
                    conn.execute(text(ddl))
        if insp.has_table("coteach_groups"):
            if not has_col("coteach_groups", "group_id"):
                conn.execute(text(
                    "ALTER TABLE coteach_groups ADD COLUMN "
                    "group_id INTEGER"))
        if insp.has_table("lessons"):
            if not has_col("lessons", "group_name"):
                conn.execute(text(
                    "ALTER TABLE lessons ADD COLUMN "
                    "group_name VARCHAR(120)"))
    return test_engine, TestSession


@pytest.fixture(scope="module")
def liceo_piccolo_scenario(tmp_path_factory):
    """Build the liceo_piccolo once per test module."""
    from backend.tests.scenarios import Scenario, liceo_piccolo
    engine, Session = _make_module_db_session(
        tmp_path_factory, "piccolo")
    db = Session()
    try:
        sc = Scenario.build(db, liceo_piccolo())
        yield sc
    finally:
        db.close()
        engine.dispose()


@pytest.fixture(scope="module")
def liceo_medio_scenario(tmp_path_factory):
    """Build the liceo_medio once per test module. Tuned to be
    solvable in ~3min."""
    from backend.tests.scenarios import Scenario, liceo_medio
    engine, Session = _make_module_db_session(
        tmp_path_factory, "medio")
    db = Session()
    try:
        sc = Scenario.build(db, liceo_medio())
        yield sc
    finally:
        db.close()
        engine.dispose()


# ----------------------------------------------------------------------
# Solver helpers
# ----------------------------------------------------------------------

def _solve_phase_b_mono(profs, inputs, *, time_a, time_b):
    import cpsat_v2_timetable as cv2          # type: ignore
    coteach, support, pot, par, grp = inputs
    classes_v, triples, class_profs = cv2.build_indices(profs)
    dc = cv2.solve_phase_a(
        profs, classes_v, triples, class_profs,
        time_limit=time_a, workers=2, log=False,
        coteach_groups=coteach,
        support_assignments=support,
        potenziamento_assignments=pot,
        parallel_groups=par,
        group_assignments=grp,
    )
    full = {}
    for d in cv2.DAYS:
        out, _ = cv2.solve_phase_b_for_day(
            d, profs, classes_v, triples, class_profs, dc,
            time_limit=time_b, workers=2, log=False,
            coteach_groups=coteach,
            support_assignments=support,
            parallel_groups=par,
            group_assignments=grp,
        )
        if out:
            full.update(out)
    return dc, full


def _assert_basic_validity(sol, profs, inputs):
    import metaheuristics as meta             # type: ignore
    coteach, support, pot, par, grp = inputs
    assert sol is not None and len(sol) > 0, (
        "solver returned empty solution")
    assert meta.is_hard_feasible(
        sol, profs, verbose=True,
        group_assignments=grp,
        coteach_groups=coteach,
        parallel_groups=par,
        support_assignments=support), \
        "HARD invariants (incl. C1/C2/C3) violated"


# ----------------------------------------------------------------------
# liceo_piccolo: full pipeline + post-processing
# ----------------------------------------------------------------------

@pytest.mark.slow
def test_piccolo_phase_b_baseline(liceo_piccolo_scenario):
    """Phase B monolithic. Budget: 90s."""
    sc = liceo_piccolo_scenario
    profs, *rest = sc.solver_inputs()
    inputs = tuple(rest)
    t0 = time.time()
    dc, sol = _solve_phase_b_mono(
        profs, inputs, time_a=15, time_b=8)
    elapsed = time.time() - t0
    print(f"\n[piccolo.phase_b] {elapsed:.1f}s -- {sc.meta.notes[0]}")
    assert elapsed < 90.0
    _assert_basic_validity(sol, profs, inputs)


@pytest.mark.slow
def test_piccolo_phase_b_then_lns(liceo_piccolo_scenario):
    """Phase B + 3s LNS pass."""
    import metaheuristics as meta             # type: ignore
    sc = liceo_piccolo_scenario
    profs, *rest = sc.solver_inputs()
    inputs = tuple(rest)
    coteach, support, pot, par, grp = inputs
    dc, sol = _solve_phase_b_mono(
        profs, inputs, time_a=15, time_b=8)
    new_sol, _ = meta.run_lns(
        sol, profs, dc, 3.0, log=False, workers=2,
        coteach_groups=coteach, support_assignments=support,
        parallel_groups=par, group_assignments=grp,
    )
    _assert_basic_validity(new_sol, profs, inputs)


@pytest.mark.slow
def test_piccolo_phase_b_then_alns(liceo_piccolo_scenario):
    """Phase B + 5s ALNS pass."""
    import alns as alns_mod                    # type: ignore
    sc = liceo_piccolo_scenario
    profs, *rest = sc.solver_inputs()
    inputs = tuple(rest)
    coteach, support, pot, par, grp = inputs
    dc, sol = _solve_phase_b_mono(
        profs, inputs, time_a=15, time_b=8)
    new_sol, _ = alns_mod.run_alns(
        sol, profs, dc, 5.0, log=False, workers=2,
        coteach_groups=coteach, support_assignments=support,
        parallel_groups=par, group_assignments=grp,
    )
    _assert_basic_validity(new_sol, profs, inputs)


@pytest.mark.slow
def test_piccolo_phase_b_then_vns(liceo_piccolo_scenario):
    """Phase B + 4s VNS pass."""
    import vns as vns_mod                       # type: ignore
    sc = liceo_piccolo_scenario
    profs, *rest = sc.solver_inputs()
    inputs = tuple(rest)
    coteach, support, pot, par, grp = inputs
    dc, sol = _solve_phase_b_mono(
        profs, inputs, time_a=15, time_b=8)
    new_sol, _ = vns_mod.run_vns(
        sol, profs, dc, 4.0, log=False,
        coteach_groups=coteach, support_assignments=support,
        parallel_groups=par, group_assignments=grp,
    )
    _assert_basic_validity(new_sol, profs, inputs)


# ----------------------------------------------------------------------
# liceo_medio: harder scenario, fewer combos to keep budget under
# 5 minutes per test.
# ----------------------------------------------------------------------

@pytest.mark.slow
def test_medio_phase_b_baseline(liceo_medio_scenario):
    """Liceo medio Phase B mono. Budget: 4min."""
    sc = liceo_medio_scenario
    profs, *rest = sc.solver_inputs()
    inputs = tuple(rest)
    t0 = time.time()
    dc, sol = _solve_phase_b_mono(
        profs, inputs, time_a=45, time_b=15)
    elapsed = time.time() - t0
    print(f"\n[medio.phase_b] {elapsed:.1f}s -- {sc.meta.notes[0]}")
    assert elapsed < 240.0, (
        f"medio phase_b too slow: {elapsed:.1f}s (budget 4min)")
    _assert_basic_validity(sol, profs, inputs)


@pytest.mark.slow
def test_medio_phase_b_then_lns(liceo_medio_scenario):
    """Liceo medio Phase B + 5s LNS post-processing."""
    import metaheuristics as meta             # type: ignore
    sc = liceo_medio_scenario
    profs, *rest = sc.solver_inputs()
    inputs = tuple(rest)
    coteach, support, pot, par, grp = inputs
    dc, sol = _solve_phase_b_mono(
        profs, inputs, time_a=45, time_b=15)
    new_sol, _ = meta.run_lns(
        sol, profs, dc, 5.0, log=False, workers=2,
        coteach_groups=coteach, support_assignments=support,
        parallel_groups=par, group_assignments=grp,
    )
    _assert_basic_validity(new_sol, profs, inputs)


@pytest.mark.slow
def test_medio_meta_summary(liceo_medio_scenario):
    """Sanity: meta counts match config defaults."""
    sc = liceo_medio_scenario
    cfg = sc.config
    m = sc.meta
    assert m.n_classes >= 20, (
        f"medium profile should yield >=20 classes; got {m.n_classes}")
    # The builder may cap coteach_class_n if too few candidate
    # Assignments exist; we accept up to the requested number.
    assert m.n_coteach_groups_class <= cfg.coteach_class_n
    assert m.n_sostegno_class <= cfg.sostegno_n
    assert m.n_potenziamento <= cfg.pot_n
    assert m.n_parallel_intra <= cfg.parallel_intra_n
    assert m.n_study_groups <= cfg.study_groups_n
    assert m.n_classrooms >= (
        cfg.n_lab_chimica + cfg.n_lab_fisica
        + cfg.n_lab_biologia + cfg.n_lab_informatica
        + cfg.n_palestre - 1
    )


# ----------------------------------------------------------------------
# istituto_tecnico (FU-A): big profile (~35 classes, ~74 teachers)
# with denser C1/C2/C3 mix simulating a tecnico/professionale.
# Total budget: ~8min for build + Phase A + Phase B + a quick ALNS
# pass (the user-stated cap was 8min; the test asserts < 480s).
# ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def istituto_tecnico_scenario(tmp_path_factory):
    """Build the istituto_tecnico once per module. Tuned to be
    solvable in ~5-6min, leaving headroom for one post-pass."""
    from backend.tests.scenarios import (
        Scenario, istituto_tecnico,
    )
    engine, Session = _make_module_db_session(
        tmp_path_factory, "itp")
    db = Session()
    try:
        sc = Scenario.build(db, istituto_tecnico())
        yield sc
    finally:
        db.close()
        engine.dispose()


@pytest.mark.slow
def test_itp_phase_b_baseline(istituto_tecnico_scenario):
    """ITP-like Phase B mono. Honest 8-minute budget for the full
    pipeline: Phase A (45s timetabling cap) + 6 Phase B days
    (35s/day cap) + assertion overhead."""
    sc = istituto_tecnico_scenario
    profs, *rest = sc.solver_inputs()
    inputs = tuple(rest)
    t0 = time.time()
    dc, sol = _solve_phase_b_mono(
        profs, inputs, time_a=60, time_b=35)
    elapsed = time.time() - t0
    print(f"\n[itp.phase_b] {elapsed:.1f}s -- {sc.meta.notes[0]}")
    assert elapsed < 480.0, (
        f"ITP phase_b too slow: {elapsed:.1f}s (budget 8min)")
    _assert_basic_validity(sol, profs, inputs)


@pytest.mark.slow
def test_itp_phase_b_then_alns(istituto_tecnico_scenario):
    """ITP Phase B + 10s ALNS. Validates that destroy + repair
    operators preserve the dense C1+C2+C3 mix end-to-end."""
    import alns as alns_mod                       # type: ignore
    sc = istituto_tecnico_scenario
    profs, *rest = sc.solver_inputs()
    inputs = tuple(rest)
    coteach, support, pot, par, grp = inputs
    dc, sol = _solve_phase_b_mono(
        profs, inputs, time_a=60, time_b=35)
    t0 = time.time()
    new_sol, _ = alns_mod.run_alns(
        sol, profs, dc, 10.0, log=False, workers=2,
        coteach_groups=coteach, support_assignments=support,
        parallel_groups=par, group_assignments=grp,
    )
    print(f"\n[itp.alns] {time.time() - t0:.1f}s")
    _assert_basic_validity(new_sol, profs, inputs)


@pytest.mark.slow
def test_itp_meta_summary(istituto_tecnico_scenario):
    """Sanity: ITP yields a ~big school with the configured C1/C2/C3
    counts (capped where necessary by the tight teacher pool).
    """
    sc = istituto_tecnico_scenario
    cfg = sc.config
    m = sc.meta
    # big profile yields ~35 classes
    assert m.n_classes >= 30, (
        f"big profile should yield >=30 classes; got {m.n_classes}")
    assert m.n_teachers >= 60, (
        f"big profile should yield >=60 teachers; got {m.n_teachers}")
    # Densities may be capped if there aren't enough lab Assignments
    # OR enough classes for the requested number of parallels.
    assert m.n_coteach_groups_class <= cfg.coteach_class_n
    assert m.n_sostegno_class <= cfg.sostegno_n
    assert m.n_potenziamento <= cfg.pot_n
    assert m.n_parallel_intra <= cfg.parallel_intra_n
    assert m.n_study_groups <= cfg.study_groups_n
    # Density floor: at least HALF of the requested entities should
    # be created (otherwise the factory is producing degenerate
    # scenarios).
    assert m.n_coteach_groups_class >= cfg.coteach_class_n // 2, (
        f"too few coteach groups: {m.n_coteach_groups_class}/"
        f"{cfg.coteach_class_n}")
    assert m.n_classrooms >= (
        cfg.n_lab_chimica + cfg.n_lab_fisica
        + cfg.n_lab_biologia + cfg.n_lab_informatica
        + cfg.n_palestre - 1
    )
