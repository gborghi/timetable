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
