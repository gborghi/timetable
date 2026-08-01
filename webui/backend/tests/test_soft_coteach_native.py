"""Finding 38 (native path): a SOFT coteach group must bias the per-day
solver toward co-location on the NATIVE path (not only the DSL/week path),
without forcing it like a hard group. We solve a tiny day and check the
codoc's hours land inside the principal's (mismatch minimized)."""
import cpsat_v2_timetable as cv2


def _solve(required, weight=1000):
    # 1A: principal T1 teaches Mat 4h, codoc T2 teaches Mat 2h. No-holes
    # off so the placement is free enough for the soft term to matter.
    profs = {
        "T1": {"classi": {"1A": {"Mat": {"ore": 4}}}, "max_hours": 18},
        "T2": {"classi": {"1A": {"Mat": {"ore": 2}}}, "max_hours": 18},
    }
    classes, triples, class_profs = cv2.build_indices(profs)
    day = cv2.DAYS[0]
    dc_value = {
        ("T1", "1A", "Mat", day): 4,
        ("T2", "1A", "Mat", day): 2,
        ("__coday__", 1, day): 2,   # group's coincident hours (hard path)
    }
    coteach = [{
        "group_id": 1, "class_name": "1A", "subject": "Mat",
        "teachers": ["T1", "T2"], "n_hours": 2,
        "required": required, "weight": weight,
    }]
    out, status = cv2.solve_phase_b_for_day(
        day, profs, classes, triples, class_profs, dc_value,
        time_limit=5, workers=1, enforce_no_holes=False,
        coteach_groups=coteach,
    )
    assert out is not None, f"infeasible ({status})"
    t1 = {h for (p, cl, s, d, h), v in out.items()
          if v and p == "T1"}
    t2 = {h for (p, cl, s, d, h), v in out.items()
          if v and p == "T2"}
    return t1, t2


def test_soft_coteach_places_codoc_inside_principal():
    t1, t2 = _solve(required=False)
    assert len(t1) == 4 and len(t2) == 2
    # SOFT coteach honored: the codoc's 2 hours coincide with the
    # principal's (mismatch minimized), i.e. T2 ⊆ T1.
    assert t2 <= t1, f"codoc hours {t2} not inside principal {t1}"


def test_hard_coteach_still_forces_coincidence():
    t1, t2 = _solve(required=True)
    assert len(t2) == 2 and t2 <= t1
