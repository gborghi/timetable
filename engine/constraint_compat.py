"""Solver-compatibility warnings (pure, frontend-agnostic).

The CP-SAT compilers (mono-week / per-day / decomposition) skip DSL
constructs they cannot model and append a free-text diagnostic to a local
list; the metaheuristic post-hoc evaluator accepts more. Today those
diagnostics are printed and discarded. This module turns them into
structured ``ConstraintWarning`` records naming the *constraint*, the
*pipeline* that dropped it, the *reason*, and a *suggestion* (typically:
run a metaheuristic post-pass, which evaluates every DSL constraint on the
finished timetable).

NO webui/backend imports -- the engine owns the classifier; the
orchestration (webui) maps it to RunLog and the frontend renders it.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class ConstraintWarning:
    constraint: str       # label / best-effort identifier
    pipeline: str         # e.g. "per_day_cpsat", "week_cpsat", "metaheuristic"
    reason: str           # human-readable why it wasn't honored
    suggestion: str       # what the user can do
    severity: str = "warning"   # info | warning | error
    raw: str = ""         # the original diagnostic string

    def to_dict(self):
        return asdict(self)


# Trailing reason markers whose *label* field is a full DSL expression that
# may itself contain colons (CG/BP and week-refinement diagnostics). These
# are stripped from the right so the colon-bearing expression survives intact.
_COMPILE_FAILED_SUFFIXES = (
    ":bp:not_modeled_in_pricer",
    ":refinement:exhausted",
)


# category detection from the existing diagnostic string forms
def classify_diagnostic(diag: str) -> tuple[str, str, str]:
    """Return (category, constraint_label, reason)."""
    d = diag.strip()
    # The per-day 'extra' form carries no constraint label:
    #   compile_failed_extra:<ExcType>:<excmsg>
    if d.startswith("compile_failed_extra:"):
        rest = d[len("compile_failed_extra:"):]
        return "compile_failed", "(construct)", f"compile error: {rest}"
    if d.startswith("compile_failed:"):
        rest = d[len("compile_failed:"):]
        # CG/BP + refinement: <expr>:<fixed-suffix>. The expression may carry
        # colons, so peel the known suffix from the right, not by maxsplit.
        for suf in _COMPILE_FAILED_SUFFIXES:
            if rest.endswith(suf):
                label = rest[: -len(suf)]
                reason = suf.lstrip(":")
                return "compile_failed", label, f"compile error: {reason}"
        # Per-day form: <label>:<ExcType>:<excmsg>. label is the first field;
        # keep the (possibly colon-bearing) message tail intact via maxsplit=2.
        parts = rest.split(":", 2)
        label = parts[0] if parts[0] else "(unknown)"
        reason = parts[2] if len(parts) > 2 else rest
        return "compile_failed", label, f"compile error: {reason}"
    if d.startswith("compile_failed"):  # bare/no-colon fallback
        return "compile_failed", "(unknown)", f"compile error: {d}"
    if d.startswith("db_load_failed") or d.startswith(
            "dsl_augmentation_failed"):
        return "load_failed", "(rule set)", d
    if "dynamic" in d and "skipped" in d:
        return "dynamic_unsupported", "(dynamic constraint)", d
    if d.startswith("pragma ") and "skipped" in d:
        return ("pragma_level_mismatch",
                d.split()[1] if len(d.split()) > 1 else "(pragma)", d)
    if "not yet supported" in d:
        return "unsupported_construct", "(construct)", d
    if "loaded" in d and "DSL rules" in d:
        return "info", "(loader)", d
    return "other", "(constraint)", d


_SUGGEST = {
    "compile_failed": "The {pipeline} solver could not build this constraint. "
        "Check the rule's syntax/entities, or run a metaheuristic post-pass "
        "(it evaluates all DSL constraints on the finished timetable).",
    "dynamic_unsupported": "This constraint is too dynamic for the {pipeline} "
        "CP solver to model directly. A metaheuristic post-pass enforces it "
        "post-hoc, or simplify it to a per-slot / static form.",
    "unsupported_construct": "The {pipeline} compiler does not model this "
        "construct yet. Try a metaheuristic post-pass, or rephrase the rule.",
    "pragma_level_mismatch": "This rule applies to a different solve phase than "
        "{pipeline}; it is enforced where its phase runs. No action needed if "
        "another phase covers it.",
    "load_failed": "The rule set failed to load for {pipeline}. Check the DB "
        "rules; re-run after fixing.",
    "other": "This rule was not fully honored by {pipeline}. Review it or try "
        "a different method.",
}


def suggest(category: str, pipeline: str) -> str:
    return _SUGGEST.get(category, _SUGGEST["other"]).format(pipeline=pipeline)


def summarize(diagnostics, *, pipeline: str) -> list[ConstraintWarning]:
    out, seen = [], set()
    for diag in diagnostics or []:
        cat, label, reason = classify_diagnostic(str(diag))
        if cat == "info":
            continue   # informational loader lines are not warnings
        key = (cat, label, reason)
        if key in seen:
            continue
        seen.add(key)
        sev = "error" if cat in ("compile_failed", "load_failed") else "warning"
        out.append(ConstraintWarning(
            constraint=label, pipeline=pipeline, reason=reason,
            suggestion=suggest(cat, pipeline), severity=sev, raw=str(diag)))
    return out
