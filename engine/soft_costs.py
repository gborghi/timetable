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


def _buchi_daydist_vars(model, slot, teachers, days, hours, *,
                         include_five_one, fixed_load=None):
    """Shared builder for the per-(teacher, day) gap (buchi) and weekly
    day-distribution (five/one) auxiliary variables.

    Single source of truth for the gap/day-count modeling. Both
    :func:`buchi_and_daydist_terms` (which forms ``weight*var`` products
    for ``ConstraintModel.compute_soft_cost_expr``) and the pair-shaped
    wrappers :func:`buchi_pairs` / :func:`five_one_pairs` (which yield
    ``(weight, var)`` tuples for the pragma layer) consume this helper,
    so the encoding -- and the EXACT order in which aux vars are created
    -- exists once.

    For each (teacher, day) with at least one decision variable or a
    non-zero fixed-load contribution it builds:

    * ``any_at_h`` -- a per-hour occupation indicator. A cell with
      ``fixed_load >= 1`` is a constant ``1``; an empty CP-SAT cell is a
      constant ``0``; otherwise a fresh BoolVar OR'd over the cell's slot
      vars (``b >= v`` for each ``v`` and ``b <= sum``).
    * ``count_d`` -- an IntVar equal to ``base_count + sum(cpsat_all)``
      where ``base_count`` is the fixed-load contribution and
      ``cpsat_all`` the CP-SAT slot vars for the day.
    * ``first_h`` / ``last_h`` -- the earliest / latest occupied hour via
      ``AddMinEquality`` / ``AddMaxEquality`` over per-hour auxiliaries.
    * ``buchi`` -- ``>= last_h - first_h + 1 - count_d`` (the number of
      idle interior hours).
    * ``is_five`` / ``is_one`` -- reified ``count_d == 5`` / ``count_d
      == 1`` day-distribution indicators, only when ``include_five_one``.

    Returns ``(records, aux_vars)`` where ``records`` is a list of
    per-(teacher, day) dicts ``{"buchi": IntVar, "is_five": BoolVar |
    None, "is_one": BoolVar | None}`` (in (teacher, day) iteration
    order) and ``aux_vars`` is every auxiliary BoolVar/IntVar created,
    appended in creation order. Callers pick the vars they want and
    attach weights; this module owns no policy.
    """
    if fixed_load is None:
        fixed_load = {}
    records: list = []
    aux_vars: list = []
    if not hours:
        return records, aux_vars
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
            rec = {"buchi": buchi, "is_five": None, "is_one": None}
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
                rec["is_five"] = is_five
                rec["is_one"] = is_one
            records.append(rec)
    return records, aux_vars


def buchi_and_daydist_terms(model, slot, teachers, days, hours, *,
                             buchi_weight, five_weight, one_weight,
                             include_five_one, fixed_load=None):
    """Per-(teacher, day) gap (buchi) penalty plus the optional weekly
    day-distribution five/one penalties.

    Thin policy wrapper over :func:`_buchi_daydist_vars`: it builds the
    per-(teacher, day) buchi / is_five / is_one vars via the shared
    helper and forms ``weight * var`` PRODUCTS (the
    ``ConstraintModel.compute_soft_cost_expr`` caller builds the
    objective directly, so this returns finished products, not pairs).
    The product order is buchi, then is_five, then is_one per record --
    byte-identical to the historical inline implementation.

    When ``include_five_one`` is true (mode='default') the reified
    ``is_five`` (``count_d == 5``) and ``is_one`` (``count_d == 1``)
    day-distribution indicators are added with ``five_weight`` /
    ``one_weight``. They are SKIPPED in the per-day mode, which cannot
    observe the rest of the week.

    ``fixed_load`` (defaulting to an empty dict) maps
    ``(teacher, day, hour) -> int`` greedy-base load that is out of
    CP-SAT scope; it contributes a constant to the per-cell count.

    Returns ``(obj_terms, aux_vars)`` -- finished ``weight * var``
    products and the auxiliary BoolVars/IntVars introduced (in creation
    order). Mirrors compute_soft_cost_expr buchi + five/one block.
    """
    records, aux_vars = _buchi_daydist_vars(
        model, slot, teachers, days, hours,
        include_five_one=include_five_one, fixed_load=fixed_load)
    obj_terms: list = []
    for rec in records:
        obj_terms.append(buchi_weight * rec["buchi"])
        if include_five_one:
            obj_terms.append(five_weight * rec["is_five"])
            obj_terms.append(one_weight * rec["is_one"])
    return obj_terms, aux_vars


def buchi_pairs(model, slot, teachers, days, hours, *,
                weight, fixed_load=None):
    """Per-(teacher, day) gap (buchi) penalty as ``(weight, var)`` PAIRS.

    Pair-shaped twin of :func:`buchi_and_daydist_terms` for the
    ``DSLConstraintCompiler`` soft-pragma layer (which stores
    ``(weight, var)`` tuples in ``soft_cost_terms``). Consumes the SAME
    shared :func:`_buchi_daydist_vars` helper as
    ``buchi_and_daydist_terms`` so the gap modeling exists once;
    ``include_five_one=False`` since buchi alone needs no weekly
    day-distribution vars.

    Returns ``(pairs, aux_vars)`` where ``pairs`` is
    ``[(weight, buchi_var), ...]`` (one per in-scope (teacher, day))
    and ``aux_vars`` is every auxiliary var created (creation order).
    """
    records, aux_vars = _buchi_daydist_vars(
        model, slot, teachers, days, hours,
        include_five_one=False, fixed_load=fixed_load)
    pairs = [(weight, rec["buchi"]) for rec in records]
    return pairs, aux_vars


def five_one_pairs(model, slot, teachers, days, hours, *,
                   five_weight=None, one_weight=None, fixed_load=None):
    """Weekly day-distribution five/one penalties as ``(weight, var)``
    PAIRS.

    Pair-shaped twin of the five/one block of
    :func:`buchi_and_daydist_terms` for the ``DSLConstraintCompiler``
    soft-pragma layer. Consumes the SAME shared
    :func:`_buchi_daydist_vars` helper (with ``include_five_one=True``)
    so the day-count / is_five / is_one modeling is identical to the
    ConstraintModel path. The per-(teacher, day) ``count_d`` is derived
    from slot occupancy (+ ``fixed_load``) exactly as
    ``buchi_and_daydist_terms``'s own ``count_d`` -- the encoding is
    therefore consistent with the ConstraintModel semantics.

    Pass ``five_weight`` and/or ``one_weight`` (``None`` -> that penalty
    is omitted). The pragma layer calls this once for ``is_five`` (with
    only ``five_weight``) and once for ``is_one`` (with only
    ``one_weight``); both still build the full record set but emit only
    the requested pairs.

    Returns ``(pairs, aux_vars)`` -- ``[(weight, var), ...]`` for the
    requested indicator(s) and every auxiliary var created.
    """
    records, aux_vars = _buchi_daydist_vars(
        model, slot, teachers, days, hours,
        include_five_one=True, fixed_load=fixed_load)
    pairs: list = []
    for rec in records:
        if five_weight is not None:
            pairs.append((five_weight, rec["is_five"]))
        if one_weight is not None:
            pairs.append((one_weight, rec["is_one"]))
    return pairs, aux_vars
