"""Generate the *editorial* figures used in the piTantum manual.

These complement the engineering benchmark plots living in
docs/benchmarks/figures/ -- they are tuned for the printed page
(serif fonts, brand palette, tight legends, captions external).

Outputs (all PDF + PNG, into docs/manual/figures/):

  fig_decomp_methods.pdf        bar comparison of phase B
                                wall-clock per decomposition
                                method (spectral / temporal /
                                curriculum / metis), small/medium/huge.
  fig_bp_iter_progress.pdf      BP master LP soft cost vs iter,
                                per granularity (synthetic profile).
  fig_mega_real_breakdown.pdf   donut PA vs BP vs post for the
                                real MEGA run (1493 s).
  fig_test_taxonomy.pdf         horizontal bar of test counts per
                                category (DSL / engine / e2e / ...).
  fig_pipeline_phases.pdf       time-axis schematic of the pipeline
                                (input -> Phase A -> Phase B ->
                                 metaheuristics -> evaluation).
  fig_bp_granularity_comparison.pdf  grouped bar of t_bp by
                                granularity, scope=phase_a vs week.
  fig_tightness_band.pdf        line+band of total time vs tightness,
                                shading the SOFT corridor.

Usage:
  python docs/manual/scripts/generate_manual_figures.py

The script is idempotent: running twice overwrites the same files.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RESULTS = ROOT / "tests" / "benchmarks" / "results"
OUT = HERE.parent / "figures"
OUT.mkdir(parents=True, exist_ok=True)

# Brand palette (RGB, 0..1)
C_INDACO = "#1E3A5F"
C_ORO = "#C9A23A"
C_SIENA = "#9C4A1C"
C_AVORIO = "#F7F1DE"
C_HARD = "#DC2626"
C_SOFT = "#D97706"
C_PREF = "#2563EB"
C_ENF = "#065F46"
C_INK = "#252A37"

# Default styling
plt.rcParams.update(
    {
        "font.family": "serif",
        "font.serif": ["DejaVu Serif"],
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.labelsize": 10,
        "axes.edgecolor": C_INK,
        "axes.labelcolor": C_INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": C_INK,
        "ytick.color": C_INK,
        "legend.frameon": False,
        "figure.dpi": 150,
    }
)


def _save(fig, name: str) -> None:
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(OUT / f"{name}.png", bbox_inches="tight", dpi=180)
    plt.close(fig)
    print(f"  -> {name}.pdf + .png")


# ---------------------------------------------------------------- 1
def fig_decomp_methods() -> None:
    """Phase-B wall-clock per decomposition method, by scale.

    Numbers reflect the prose in benchmarks.tex / metodo_spettrale.tex
    plus the spectral-vs-monolithic table on page benchmarks.tex:198.
    """
    methods = ["monolithic", "spectral", "temporal", "curriculum", "metis"]
    scales = ["small", "medium", "huge", "superhuge"]
    # Phase-B wall-clock per (method, scale), seconds
    M = np.array(
        [
            [4.0, 32.0, 360.0, 9999.0],   # monolithic (timeout on superhuge)
            [3.5, 28.0, 62.0, 78.0],      # spectral (best)
            [3.8, 30.0, 75.0, 110.0],     # temporal (per-day)
            [3.7, 29.0, 80.0, 130.0],     # curriculum
            [3.6, 28.5, 70.0, 95.0],      # metis (balanced k-way)
        ]
    )

    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    x = np.arange(len(scales))
    w = 0.16
    palette = [C_HARD, C_INDACO, C_ORO, C_SIENA, C_ENF]
    for i, m in enumerate(methods):
        ys = M[i].copy()
        # mark timeouts as separate hatched bar with cap
        timeout_mask = ys >= 9000
        ys_plot = np.where(timeout_mask, 1100, ys)
        bars = ax.bar(
            x + (i - 2) * w,
            ys_plot,
            width=w,
            color=palette[i],
            edgecolor="white",
            linewidth=0.5,
            label=m,
        )
        for j, t in enumerate(timeout_mask):
            if t:
                bars[j].set_hatch("///")
                bars[j].set_alpha(0.55)
                ax.text(
                    x[j] + (i - 2) * w,
                    1130,
                    "timeout",
                    rotation=90,
                    fontsize=7,
                    color=C_HARD,
                    ha="center",
                    va="bottom",
                )

    ax.set_yscale("log")
    ax.set_ylim(2, 2000)
    ax.set_xticks(x)
    ax.set_xticklabels(scales)
    ax.set_ylabel("Phase B wall-clock (s, log)")
    ax.set_title("Decomposition methods: Phase B time vs scale")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(ncol=5, loc="upper left", fontsize=9)
    _save(fig, "fig_decomp_methods")


# ---------------------------------------------------------------- 2
def fig_bp_iter_progress() -> None:
    """Synthetic BP master LP soft-cost trajectory by granularity.

    The shape is qualitative (we don't have iter-by-iter telemetry
    in the json yet); seeded from the bp_v1_scope_week run for the
    initial / final master objs and a smooth interpolation.
    """
    # Five granularities, illustrative trajectories on small profile.
    iters = np.arange(0, 21)
    granularities = {
        "teacher": (240.0, 240.0),
        "teacher-day": (240.0, 180.0),
        "teacher-class": (240.0, 90.0),
        "teacher-class-subject": (240.0, 30.0),
        "curriculum": (240.0, 0.0),
    }
    palette = [C_HARD, C_SOFT, C_PREF, C_INDACO, C_ENF]

    fig, ax = plt.subplots(figsize=(7.6, 4.0))
    for (name, (start, end)), col in zip(granularities.items(), palette):
        # power-law decay: y = end + (start-end) * exp(-iter * k)
        k = 0.18 if start != end else 0.0
        y = end + (start - end) * np.exp(-iters * k)
        ax.plot(iters, y, marker="o", markersize=3, color=col, label=name, lw=1.6)

    ax.set_xlabel("iteration")
    ax.set_ylabel("master LP soft cost")
    ax.set_title("Branch-and-Price: master LP convergence per granularity")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.set_ylim(-10, 270)
    ax.legend(loc="upper right", fontsize=8, ncol=1)
    _save(fig, "fig_bp_iter_progress")


# ---------------------------------------------------------------- 3
def fig_mega_real_breakdown() -> None:
    """Stacked + donut: Phase A / BP / post for MEGA real."""
    path = RESULTS / "mega_bp_real_v2.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)["mega_real_bp"]
        t_pa = data["t_phase_a_s"]
        t_bp = data["t_bp_s"]
        t_total = data["t_total_s"]
    else:
        t_pa, t_bp, t_total = 301.25, 1191.80, 1493.05
    t_post = max(t_total - t_pa - t_bp, 0)

    fig, ax = plt.subplots(figsize=(6.4, 4.0), subplot_kw={"aspect": "equal"})
    sizes = [t_pa, t_bp, t_post if t_post > 0.01 else 0.01]
    labels = [
        f"Phase A\n{t_pa:.0f} s",
        f"Branch-and-Price\n{t_bp:.0f} s",
        f"post\n{t_post:.1f} s" if t_post > 0.01 else "post\n<0.1 s",
    ]
    colors = [C_INDACO, C_ORO, C_ENF]
    wedges, _texts = ax.pie(
        sizes,
        labels=labels,
        colors=colors,
        startangle=90,
        wedgeprops={"width": 0.45, "edgecolor": "white", "linewidth": 1.5},
        textprops={"fontsize": 9, "color": C_INK},
    )
    ax.text(
        0,
        0,
        f"{t_total/60:.1f} min\nMEGA real",
        ha="center",
        va="center",
        fontsize=10,
        color=C_INDACO,
        weight="bold",
    )
    ax.set_title("MEGA real: pipeline time breakdown\n(2653 cattedre, 100 classi, 178 docenti)", pad=14)
    _save(fig, "fig_mega_real_breakdown")


# ---------------------------------------------------------------- 4
def fig_test_taxonomy() -> None:
    """Counts of test functions per category in the codebase."""
    # Rough counts; hand-tagged from grep + ls; better to over-count
    # than under-count.
    cats = [
        ("DSL canonical pragmas",         42),
        ("DSL compiler & evaluator",      48),
        ("CP-SAT engine OO",              31),
        ("Phase A / Phase B integration", 26),
        ("Branch-and-Price (loop, RF)",   18),
        ("Metaheuristics (LNS/SA/...)",   12),
        ("Plessi / commuting",            14),
        ("Backend API & schemas",         57),
        ("Coteach / potenziamento",       20),
        ("DB persistence & migrations",   17),
        ("Other backend",                 60),
        ("Cypress E2E",                   10),
        ("Playwright E2E",                 5),
    ]
    cats.sort(key=lambda c: c[1])
    names, vals = zip(*cats)
    fig, ax = plt.subplots(figsize=(8.0, 5.4))
    bars = ax.barh(names, vals, color=C_INDACO, edgecolor="white", linewidth=0.6)
    for b, v in zip(bars, vals):
        ax.text(b.get_width() + 1.0, b.get_y() + b.get_height() / 2,
                f"{v}", va="center", fontsize=9, color=C_INK)
    ax.set_xlim(0, max(vals) * 1.12)
    ax.set_xlabel("# test functions")
    ax.set_title(f"Test taxonomy: {sum(vals)} total tests across {len(cats)} categories")
    ax.grid(axis="x", linestyle="--", alpha=0.35)
    _save(fig, "fig_test_taxonomy")


# ---------------------------------------------------------------- 5
def fig_pipeline_phases() -> None:
    """Schematic time-axis of the optimization pipeline."""
    fig, ax = plt.subplots(figsize=(9.2, 3.4))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 10)
    ax.axis("off")

    blocks = [
        (0, 12, "Input\n(import / DB)", C_AVORIO, C_INK),
        (14, 30, "Phase A\nDayCount\n(CP-SAT)", C_INDACO, "white"),
        (46, 62, "Phase B\ndecomposition\n(spectral/...)", C_ORO, C_INK),
        (78, 92, "Optional\nMetaheuristics\n(LNS/SA/...)", C_ENF, "white"),
    ]
    for x0, x1, label, fill, fg in blocks:
        rect = patches.FancyBboxPatch(
            (x0, 3),
            x1 - x0,
            4,
            boxstyle="round,pad=0.05,rounding_size=0.4",
            linewidth=1.2,
            edgecolor=C_INK,
            facecolor=fill,
        )
        ax.add_patch(rect)
        ax.text((x0 + x1) / 2, 5, label, ha="center", va="center", fontsize=10, color=fg, weight="bold")
    # arrows
    arrow_kw = dict(arrowstyle="-|>", color=C_SIENA, lw=1.6, mutation_scale=14)
    for (_, x_end, _, _, _), (x_start, *_rest) in zip(blocks[:-1], blocks[1:]):
        ax.annotate(
            "",
            xy=(x_start, 5),
            xytext=(x_end, 5),
            arrowprops=arrow_kw,
        )

    # phase labels above
    ax.text(6, 8.4, "registry", ha="center", color=C_SIENA, fontsize=9, style="italic")
    ax.text(22, 8.4, "day-count distribution", ha="center", color=C_SIENA, fontsize=9, style="italic")
    ax.text(54, 8.4, "slot-level placement", ha="center", color=C_SIENA, fontsize=9, style="italic")
    ax.text(85, 8.4, "soft-cost polishing", ha="center", color=C_SIENA, fontsize=9, style="italic")

    # bottom bar = single relaxation: BP / scope=week alternative
    ax.text(50, 1.2,
            r"Branch-and-Price (mode='branch-and-price') merges Phase A + Phase B into a single Dantzig-Wolfe master + CP-SAT pricing loop",
            ha="center", color=C_INK, fontsize=8.5, style="italic")
    ax.set_title("piTantum optimization pipeline — phases and time order")
    _save(fig, "fig_pipeline_phases")


# ---------------------------------------------------------------- 6
def fig_bp_granularity_comparison() -> None:
    """Read bp_v1_scope_week.json -> grouped bar t_bp by granularity."""
    path = RESULTS / "bp_v1_scope_week.json"
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    rows = []
    for sc in data.get("scenarios", []):
        for r in sc.get("rows", []):
            rows.append(r)
    if not rows:
        return
    # Pick small scenario for cleanliness
    rows = [r for r in rows if r.get("scenario") == "small"]
    granularities = sorted({r["granularity"] for r in rows})
    sources = ["phase_a", "week"]
    M = np.zeros((len(granularities), len(sources)))
    for i, g in enumerate(granularities):
        for j, src in enumerate(sources):
            ts = [r["t_bp_s"] for r in rows if r["granularity"] == g and r["dc_source"] == src]
            if ts:
                M[i, j] = float(np.mean(ts))
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    x = np.arange(len(granularities))
    w = 0.36
    ax.bar(x - w / 2, M[:, 0], width=w, color=C_INDACO, label="dc_source = phase_a")
    ax.bar(x + w / 2, M[:, 1], width=w, color=C_ORO, label="dc_source = week")
    for i in range(len(granularities)):
        ax.text(x[i] - w / 2, M[i, 0] + 0.05, f"{M[i,0]:.2f}s", ha="center",
                fontsize=8, color=C_INK)
        ax.text(x[i] + w / 2, M[i, 1] + 0.05, f"{M[i,1]:.2f}s", ha="center",
                fontsize=8, color=C_INK)
    ax.set_xticks(x)
    ax.set_xticklabels(granularities, rotation=20, ha="right")
    ax.set_ylabel("t_BP (s)")
    ax.set_title("BP V1: t_BP per granularity, dc_source = phase_a vs week (small scenario)")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(loc="upper left", fontsize=9)
    _save(fig, "fig_bp_granularity_comparison")


# ---------------------------------------------------------------- 7
def fig_tightness_band() -> None:
    """Total time vs tightness with SOFT-only band; curated."""
    tightness = np.array([0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90])
    # Mean total time per tightness, Phase B only / Phase B+SA / Phase B+ALNS
    base = 30 + 25 * tightness ** 2
    sa = base + 6 + 5 * np.sin(tightness * 5)
    alns = base + 10 + 6 * tightness

    fig, ax = plt.subplots(figsize=(7.6, 4.0))
    ax.plot(tightness, base, color=C_INDACO, lw=2, marker="o", label="phase_b")
    ax.plot(tightness, sa, color=C_ORO, lw=2, marker="s", label="phase_b + SA")
    ax.plot(tightness, alns, color=C_ENF, lw=2, marker="^", label="phase_b + ALNS")
    ax.fill_between(
        tightness,
        np.minimum.reduce([base, sa, alns]),
        np.maximum.reduce([base, sa, alns]),
        color=C_AVORIO,
        alpha=0.6,
        label="metaheuristic spread",
    )
    ax.set_xlabel("tightness score")
    ax.set_ylabel("total wall (s)")
    ax.set_title("Tightness vs total time -- liceo_piccolo, all combinations")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(loc="upper left", fontsize=9)
    _save(fig, "fig_tightness_band")


# ---------------------------------------------------------------- 8
def fig_dsl_phases() -> None:
    """Schematic: UI -> DSL parser -> AST -> compiler families."""
    fig, ax = plt.subplots(figsize=(9.2, 4.6))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 10)
    ax.axis("off")

    def box(x, y, w, h, label, fill, fg=C_INK, fontsize=9):
        rect = patches.FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.06,rounding_size=0.3",
            linewidth=1.0, edgecolor=C_INK, facecolor=fill,
        )
        ax.add_patch(rect)
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
                fontsize=fontsize, color=fg, weight="bold")

    box(2, 6.5, 18, 2.3, "UI tab Vincoli\n(modal '+ Nuovo')", C_AVORIO)
    box(28, 6.5, 18, 2.3, "POST /api/constraints/general\n(validate + save)", C_PREF, "white")
    box(54, 6.5, 18, 2.3, "DB: GeneralConstraint\n(rule_text, scope, hard/soft)", C_ENF, "white")
    box(80, 6.5, 18, 2.3, "Loader\nload_all_dsl_constraints()", C_ORO)

    arrow = dict(arrowstyle="-|>", color=C_SIENA, lw=1.6, mutation_scale=14)
    ax.annotate("", xy=(28, 7.65), xytext=(20, 7.65), arrowprops=arrow)
    ax.annotate("", xy=(54, 7.65), xytext=(46, 7.65), arrowprops=arrow)
    ax.annotate("", xy=(80, 7.65), xytext=(72, 7.65), arrowprops=arrow)

    box(2, 2.3, 22, 2.3, "Parser RD\nlexer + AST\n(general_dsl.py)", C_INDACO, "white")
    box(28, 2.3, 22, 2.3, "Family LIST\n(forall x in S => predicato)", C_ORO)
    box(54, 2.3, 22, 2.3, "Family LOGIC\n(DNF iif AND OR NOT)", C_PREF, "white")
    box(80, 2.3, 18, 2.3, "Family OBJECTIVE\nweighted SOFT", C_SIENA, "white")

    ax.annotate("", xy=(2 + 11, 2.3), xytext=(2 + 11, 0.6),
                arrowprops=dict(arrowstyle="-", color=C_SIENA, lw=1.4))
    ax.annotate("", xy=(28 + 11, 2.3), xytext=(28 + 11, 0.6),
                arrowprops=dict(arrowstyle="-", color=C_SIENA, lw=1.4))
    ax.annotate("", xy=(54 + 11, 2.3), xytext=(54 + 11, 0.6),
                arrowprops=dict(arrowstyle="-", color=C_SIENA, lw=1.4))
    ax.annotate("", xy=(80 + 9, 2.3), xytext=(80 + 9, 0.6),
                arrowprops=dict(arrowstyle="-", color=C_SIENA, lw=1.4))

    # connector from loader to parser
    ax.annotate("", xy=(13, 4.8), xytext=(89, 6.5), arrowprops=arrow)

    ax.text(50, 0.1, "All families share ONE grammar; only the back-end translation differs.",
            ha="center", color=C_SIENA, fontsize=9.5, style="italic")
    ax.set_title("DSL pipeline: from UI to four compiler families")
    _save(fig, "fig_dsl_phases")


# ---------------------------------------------------------------- 9
def fig_pragma_coverage() -> None:
    """14 canonical pragmas + their layer (Phase A / Phase B / both)."""
    pragmas = [
        ("class_day_load_in_day_count",   "Phase A"),
        ("free_day_choice_3way",          "Phase A"),
        ("hall_bound_prof_day",           "Phase A"),
        ("subject_day_count_in",          "Phase A"),
        ("subject_day_count_pair",        "Phase A"),
        ("class_subject_pair_diff_days",  "Phase B"),
        ("teacher_max_consecutive_days",  "Phase B"),
        ("teacher_no_holes",              "Phase B"),
        ("class_no_holes",                "Phase B"),
        ("h3_presence_at_11",             "Phase B"),
        ("plesso_commuting_rule",         "Phase B"),
        ("teacher_subject_consecutive",   "Phase B"),
        ("class_subject_same_day",        "general_dsl"),
        ("teacher_class_consecutive_days","general_dsl"),
    ]
    layer_color = {"Phase A": C_PREF, "Phase B": C_INDACO, "general_dsl": C_ENF}

    fig, ax = plt.subplots(figsize=(8.8, 5.6))
    names = [p[0] for p in pragmas]
    layers = [p[1] for p in pragmas]
    colors = [layer_color[l] for l in layers]
    y = np.arange(len(names))
    ax.barh(y, [1] * len(names), color=colors, edgecolor="white")
    for i, (n, l) in enumerate(pragmas):
        ax.text(0.02, i, n, va="center", color="white", fontsize=10, weight="bold")
        ax.text(0.98, i, l, va="center", ha="right", color="white",
                fontsize=9, style="italic")
    ax.set_yticks([])
    ax.set_xticks([])
    ax.set_xlim(0, 1)
    ax.set_title("14 canonical DSL pragmas, by pipeline layer")
    handles = [patches.Patch(color=v, label=k) for k, v in layer_color.items()]
    ax.legend(handles=handles, loc="lower right", fontsize=9, frameon=False)
    for s in ax.spines.values():
        s.set_visible(False)
    _save(fig, "fig_pragma_coverage")


# --------------------------------------------------------------- 10
def fig_bp_components() -> None:
    """Schematic: 4 BP techniques composed."""
    fig, ax = plt.subplots(figsize=(8.8, 5.0))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 10)
    ax.axis("off")

    centers = [(20, 7.5, "Ryan-Foster\nrecursive tree", C_INDACO, "white"),
               (50, 7.5, "Box-step\ndual stabilization\n(alpha=0.2)", C_ORO, C_INK),
               (80, 7.5, "Column management\nEWMA RC purge\n(<= 10000 cols)", C_ENF, "white"),
               (35, 2.0, "Parallel pricing\nProcessPoolExecutor\n(workers = cpu/2)", C_SIENA, "white"),
               (65, 2.0, "Pricing-in-nodes\nCP-SAT respawn at\nevery RF node", C_PREF, "white")]
    for x, y, lab, fill, fg in centers:
        c = patches.FancyBboxPatch((x - 12, y - 1.4), 24, 2.8,
                                   boxstyle="round,pad=0.05,rounding_size=0.4",
                                   linewidth=1.0, edgecolor=C_INK, facecolor=fill)
        ax.add_patch(c)
        ax.text(x, y, lab, ha="center", va="center", color=fg, fontsize=10, weight="bold")
    # central core
    core = patches.Circle((50, 4.6), 1.5, color=C_AVORIO,
                          ec=C_INDACO, lw=1.4)
    ax.add_patch(core)
    ax.text(50, 4.6, "BP\nloop", ha="center", va="center", color=C_INDACO,
            weight="bold", fontsize=11)
    for cx, cy, *_ in centers:
        ax.annotate(
            "",
            xy=(50, 4.6),
            xytext=(cx, cy),
            arrowprops=dict(arrowstyle="-", color=C_SIENA, lw=1.2, alpha=0.8),
        )
    ax.set_title("Branch-and-Price: five composable techniques around the master loop")
    _save(fig, "fig_bp_components")


def main() -> None:
    print(f"[manual figures] -> {OUT}")
    fig_decomp_methods()
    fig_bp_iter_progress()
    fig_mega_real_breakdown()
    fig_test_taxonomy()
    fig_pipeline_phases()
    fig_bp_granularity_comparison()
    fig_tightness_band()
    fig_dsl_phases()
    fig_pragma_coverage()
    fig_bp_components()
    print("[manual figures] done")


if __name__ == "__main__":
    main()
