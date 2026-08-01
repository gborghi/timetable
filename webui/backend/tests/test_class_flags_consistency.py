"""Finding 08b consistency: the per-class HARD-invariant flags are honoured
identically across the engine — the DSL seed (OO/week solver), the
feasibility checker (metaheuristics), and the shared resolver — and default
to the historical global behaviour (zero-drift) when unset."""
import cpsat_v2_timetable as cv2
import dsl_translator as dt
import metaheuristics as mh


PROFS = {"T": {"classi": {"1A": {"Matematica": {"ore": 3}}}}}
_D = cv2.DAYS[0]
# A day for 1A with a HOLE at hour 10 (8, 9, _, 11): violates no-holes but
# starts at 8 and is present at 11, and 8-9 is a Matematica pair.
SOL = {
    ("T", "1A", "Matematica", _D, 8): 1,
    ("T", "1A", "Matematica", _D, 9): 1,
    ("T", "1A", "Matematica", _D, 11): 1,
}


def test_resolver_defaults_and_overrides():
    assert cv2.class_enforces(None, "1A", "no_holes", True) is True
    assert cv2.class_enforces({}, "1A", "no_holes", True) is True
    assert cv2.class_enforces({"1A": {"no_holes": False}},
                              "1A", "no_holes", True) is False
    assert cv2.class_enforces({"1B": {"no_holes": False}},
                              "1A", "no_holes", True) is True


def test_is_hard_feasible_respects_no_holes_flag():
    # Strict (default): the hole makes it infeasible.
    assert mh.is_hard_feasible(SOL, PROFS) is False
    # Turn no_holes OFF for 1A: the same solution is now accepted.
    cf = {"1A": {"no_holes": False}}
    assert mh.is_hard_feasible(SOL, PROFS, class_flags=cf) is True
    # A DIFFERENT class's override must not relax 1A.
    cf_other = {"1B": {"no_holes": False}}
    assert mh.is_hard_feasible(SOL, PROFS, class_flags=cf_other) is False


def test_seed_zero_drift_and_per_class_gating():
    base = dt.seed_implicit_hardcoded(PROFS)
    assert dt.seed_implicit_hardcoded(PROFS, class_flags=None) == base
    got = dt.seed_implicit_hardcoded(
        PROFS, class_flags={"1A": {"no_holes": False}})
    assert [c for c in base if "no_holes_class" in c and "1A" in c]
    assert not [c for c in got if "no_holes_class" in c and "1A" in c]


def test_monolithic_config_carries_class_flags():
    import cp_sat_constraint_model as csm
    cfg = csm.ConstraintConfig(class_flags={"1A": {"no_holes": False}})
    assert cfg.class_flags == {"1A": {"no_holes": False}}
    # A model built with it must expose the per-class resolver.
    solver = csm.MonolithicSolver(PROFS, dc_value=None, config=cfg, scope=None)
    assert solver._class_enforces("1A", "no_holes") is False
    assert solver._class_enforces("1A", "motorie_pairs") is True
