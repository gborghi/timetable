"""Single source of truth for CP-SAT SOFT-cost encodings.

Pure free functions over a CP model + slot view. No coupling to the
solver classes: both ``ConstraintModel.compute_soft_cost_expr`` and the
``DSLConstraintCompiler`` soft pragmas call these, so the encoding exists
exactly once. Each returns ``(obj_terms, aux_vars)``; callers pass the
weights (this module owns no policy).
"""
from __future__ import annotations


def sixth_slot_pairs(model, slot, *, weight, sixth_hour=13):
    """Per-slot sixth-hour penalty (mode='default'): one ``(weight, var)``
    pair per slot var at ``hour == sixth_hour``. Returning pairs (not
    ``weight*var`` products) matches the shape ``soft_cost_terms`` stores,
    so the pragma layer can extend directly; the ConstraintModel caller
    adapts with ``[w*v for w, v in pairs]``. Mirrors
    compute_soft_cost_expr mode='default' sixth block (:1004-1006)."""
    pairs = []
    for (_t, _cl, _s, _d, h), v in slot.items():
        if h == sixth_hour:
            pairs.append((weight, v))
    return pairs, []


def sixth_class_busy_terms(model, busy_indicator_fn, classes, days, *,
                            weight, sixth_hour=13, name_prefix="sx"):
    """Per-day sixth-hour penalty (mode='phase_b_per_day'): one
    ``weight * indicator`` term per (class, day) class-busy occupation
    at ``hour == sixth_hour``.

    Unlike :func:`sixth_slot_pairs` (per-slot), this aggregates the slot
    vars of a class at the sixth hour into a SINGLE busy indicator using
    the caller's ``busy_indicator_fn`` -- so a coteach pair / parallel
    intra group counts ONCE and sostegno is excluded (those exclusion +
    aggregation rules live entirely inside ``busy_indicator_fn``, the
    ConstraintModel's ``_build_class_busy_indicators``).

    ``busy_indicator_fn(cl, d, sixth_hour)`` must return the list of
    class-busy indicators at that cell (already de-duplicated per busy
    key by the caller). When the list has 0 entries the (cl, d) pair is
    skipped; with exactly 1 the lone indicator is used directly; with
    >1 a fresh ``NewBoolVar`` is OR'd over them via ``AddMaxEquality``
    (and recorded in ``aux_vars``).

    Returns ``(obj_terms, aux_vars)`` where ``obj_terms`` is a list of
    ``weight * var`` products (the ConstraintModel caller builds the
    objective directly, so this returns finished products, not pairs).
    Mirrors compute_soft_cost_expr mode='phase_b_per_day' sixth block.
    """
    obj_terms = []
    aux_vars = []
    for cl in classes:
        for d in days:
            busy = busy_indicator_fn(cl, d, sixth_hour)
            if not busy:
                continue
            if len(busy) == 1:
                ind = busy[0]
            else:
                ind = model.NewBoolVar(f"{name_prefix}_{cl}_{d}")
                model.AddMaxEquality(ind, busy)
                aux_vars.append(ind)
            obj_terms.append(weight * ind)
    return obj_terms, aux_vars


def buchi_and_daydist_terms(model, slot, teachers, days, hours, *,
                             buchi_weight, five_weight, one_weight,
                             include_five_one, fixed_load=None):
    """Per-(teacher, day) gap (buchi) penalty plus the optional weekly
    day-distribution five/one penalties.

    Single source of truth for the buchi + five/one block of
    ``ConstraintModel.compute_soft_cost_expr``. For each (teacher, day)
    in scope it builds:

    * ``any_at_h`` -- a per-hour occupation indicator. A cell with
      ``fixed_load >= 1`` is a constant ``1``; an empty CP-SAT cell is a
      constant ``0``; otherwise a fresh BoolVar OR'd over the cell's slot
      vars (``b >= v`` for each ``v`` and ``b <= sum``).
    * ``count_d`` -- an IntVar equal to ``base_count + sum(cpsat_all)``
      where ``base_count`` is the fixed-load contribution and
      ``cpsat_all`` the CP-SAT slot vars for the day.
    * ``first_h`` / ``last_h`` -- the earliest / latest occupied hour via
      ``AddMinEquality`` / ``AddMaxEquality`` over per-hour auxiliaries
      that take the hour index when occupied and a sentinel
      (``h_max + 1`` / ``h_min - 1``) otherwise.
    * ``buchi`` -- ``>= last_h - first_h + 1 - count_d`` (the number of
      idle interior hours), contributed as ``buchi_weight * buchi``.

    When ``include_five_one`` is true (mode='default') the reified
    ``is_five`` (``count_d == 5``) and ``is_one`` (``count_d == 1``)
    day-distribution indicators are added with ``five_weight`` /
    ``one_weight``. They are SKIPPED in the per-day mode, which cannot
    observe the rest of the week.

    Slot access uses an inline comprehension over ``slot`` -- the exact
    equivalent of ``ConstraintModel.slots_for_teacher_day_hour``.
    ``fixed_load`` (defaulting to an empty dict) maps
    ``(teacher, day, hour) -> int`` greedy-base load that is out of
    CP-SAT scope; it contributes a constant to the per-cell count.

    Returns ``(obj_terms, aux_vars)`` -- finished ``weight * var``
    products (the caller builds the objective directly) and the
    auxiliary BoolVars/IntVars introduced.
    Mirrors compute_soft_cost_expr buchi + five/one block.
    """
    if fixed_load is None:
        fixed_load = {}
    obj_terms = []
    aux_vars = []
    if not hours:
        return obj_terms, aux_vars
    h_min, h_max = min(hours), max(hours)
    for t in teachers:
        for d in days:
            cpsat_at_h: dict = {}
            base_at_h: dict = {}
            for h in hours:
                cpsat_at_h[h] = [
                    v for (tt, _c, _s, dd, hh), v in slot.items()
                    if tt == t and dd == d and hh == h]
                base_at_h[h] = int(fixed_load.get((t, d, h), 0))
            base_count = sum(base_at_h.values())
            cpsat_all = [v for h in hours for v in cpsat_at_h[h]]
            if not cpsat_all and base_count == 0:
                continue
            # any_at_h indicators
            any_at_h: dict = {}
            for h in hours:
                if base_at_h[h] >= 1:
                    any_at_h[h] = model.NewConstant(1)
                elif not cpsat_at_h[h]:
                    any_at_h[h] = model.NewConstant(0)
                else:
                    b = model.NewBoolVar(f"any_{t}_{d}_{h}")
                    for v in cpsat_at_h[h]:
                        model.Add(b >= v)
                    model.Add(b <= sum(cpsat_at_h[h]))
                    aux_vars.append(b)
                    any_at_h[h] = b
            # day_count
            count_d = model.NewIntVar(
                base_count, base_count + len(cpsat_all),
                f"cnt_{t}_{d}")
            aux_vars.append(count_d)
            if cpsat_all:
                model.Add(count_d == base_count + sum(cpsat_all))
            else:
                model.Add(count_d == base_count)
            # first_h, last_h via min/max over auxiliaries
            first_h = model.NewIntVar(
                h_min, h_max + 1, f"fh_{t}_{d}")
            last_h = model.NewIntVar(
                h_min - 1, h_max, f"lh_{t}_{d}")
            aux_vars.extend([first_h, last_h])
            hf_aux: list = []
            hl_aux: list = []
            for h in hours:
                hf = model.NewIntVar(
                    h_min, h_max + 1, f"hf_{t}_{d}_{h}")
                hl = model.NewIntVar(
                    h_min - 1, h_max, f"hl_{t}_{d}_{h}")
                model.Add(hf == h).OnlyEnforceIf(any_at_h[h])
                model.Add(hf == h_max + 1).OnlyEnforceIf(
                    any_at_h[h].Not())
                model.Add(hl == h).OnlyEnforceIf(any_at_h[h])
                model.Add(hl == h_min - 1).OnlyEnforceIf(
                    any_at_h[h].Not())
                hf_aux.append(hf)
                hl_aux.append(hl)
            model.AddMinEquality(first_h, hf_aux)
            model.AddMaxEquality(last_h, hl_aux)
            # buchi
            max_buchi = h_max - h_min
            buchi = model.NewIntVar(0, max_buchi, f"bch_{t}_{d}")
            aux_vars.append(buchi)
            model.Add(buchi >= last_h - first_h + 1 - count_d)
            obj_terms.append(buchi_weight * buchi)
            if include_five_one:
                # is_five, is_one reified -- weekly day-distribution
                # penalties; not emitted in the per-day mode since
                # the per-day model cannot see the rest of the week.
                is_five = model.NewBoolVar(f"5_{t}_{d}")
                model.Add(count_d == 5).OnlyEnforceIf(is_five)
                model.Add(count_d != 5).OnlyEnforceIf(is_five.Not())
                is_one = model.NewBoolVar(f"1_{t}_{d}")
                model.Add(count_d == 1).OnlyEnforceIf(is_one)
                model.Add(count_d != 1).OnlyEnforceIf(is_one.Not())
                aux_vars.extend([is_five, is_one])
                obj_terms.append(five_weight * is_five)
                obj_terms.append(one_weight * is_one)
    return obj_terms, aux_vars
