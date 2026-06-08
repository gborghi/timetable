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
