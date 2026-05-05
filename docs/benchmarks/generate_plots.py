"""Read the benchmark CSV files in tests/benchmarks/results/ and
emit publication-quality plots into docs/benchmarks/figures/.

Plots produced (each as PNG + SVG):
  - boxplot_time_by_combo.png      box of t_total per combination,
                                    grouped by scenario.
  - bar_softcost_by_combo.png      mean obj_value per combination,
                                    grouped by scenario.
  - scatter_time_vs_softcost.png   Pareto frontier.
  - stacked_breakdown.png          mean (Phase A + Phase B + post)
                                    breakdown.
  - heatmap_combo_x_scenario.png   tile of mean t_total.
  - tightness_vs_time.png          line per combo, x=tightness_score
  - tightness_vs_softcost.png
  - tightness_vs_feasibility.png   % rows with hard_feasible=True

Usage:
  python docs/benchmarks/generate_plots.py

Reads ALL `bench_*.csv` files in tests/benchmarks/results/ that
have valid headers (excluding `bench_latest.csv`); concatenates
them; emits figures.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402
import numpy as np                 # noqa: E402
import pandas as pd                # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
RESULTS_DIR = os.path.join(REPO_ROOT, "tests", "benchmarks",
                            "results")
FIG_DIR = os.path.join(HERE, "figures")
os.makedirs(FIG_DIR, exist_ok=True)


def _load() -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(RESULTS_DIR, "bench_*.csv")))
    if not files:
        raise SystemExit(f"no CSVs in {RESULTS_DIR}")
    dfs = []
    for f in files:
        if "latest" in os.path.basename(f):
            continue
        try:
            df = pd.read_csv(f)
        except Exception as e:
            print(f"[plots] skip {f}: {e}")
            continue
        if "scenario" not in df.columns:
            print(f"[plots] skip {f}: no `scenario` column")
            continue
        dfs.append(df)
    if not dfs:
        raise SystemExit("no usable CSV (all empty/invalid)")
    df = pd.concat(dfs, ignore_index=True)
    # Backfill columns added later
    for col, default in [("tightness_in", 0.5),
                          ("tightness_score", 0.5),
                          ("n_assignments", 0),
                          ("n_classes", 0),
                          ("n_teachers", 0)]:
        if col not in df.columns:
            df[col] = default
    return df


def _save(fig, name):
    for ext in ("png", "svg"):
        path = os.path.join(FIG_DIR, f"{name}.{ext}")
        fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[plots] -> {name}.png + .svg")


def boxplot_time_by_combo(df):
    """Box plot of t_total per combination, grouped by scenario."""
    df = df[df.status == "ok"].copy()
    if df.empty:
        return
    scenarios = sorted(df.scenario.unique())
    combos = sorted(df.combination.unique())
    fig, ax = plt.subplots(figsize=(11, 6))
    width = 0.8 / max(1, len(scenarios))
    x = np.arange(len(combos))
    for i, sc in enumerate(scenarios):
        data = [df[(df.scenario == sc) & (df.combination == c)]
                  .t_total.values for c in combos]
        positions = x + i * width - 0.4 + width / 2
        bp = ax.boxplot(data, positions=positions, widths=width * 0.9,
                         patch_artist=True, showfliers=True)
        color = plt.cm.tab10(i % 10)
        for box in bp["boxes"]:
            box.set_facecolor(color)
            box.set_alpha(0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(combos, rotation=30, ha="right")
    ax.set_ylabel("Tempo totale (s)")
    ax.set_title("Tempo solver per combinazione, per scenario")
    legend_handles = [plt.Rectangle((0, 0), 1, 1,
                                       facecolor=plt.cm.tab10(i % 10),
                                       alpha=0.6, label=sc)
                       for i, sc in enumerate(scenarios)]
    ax.legend(handles=legend_handles, loc="upper left")
    fig.tight_layout()
    _save(fig, "boxplot_time_by_combo")


def bar_softcost_by_combo(df):
    df = df[df.status == "ok"].copy()
    if df.empty or "obj_value" not in df.columns:
        return
    df = df.dropna(subset=["obj_value"])
    if df.empty:
        return
    grp = df.groupby(["scenario", "combination"])\
        .obj_value.mean().reset_index()
    scenarios = sorted(grp.scenario.unique())
    combos = sorted(grp.combination.unique())
    fig, ax = plt.subplots(figsize=(11, 5))
    width = 0.8 / max(1, len(scenarios))
    x = np.arange(len(combos))
    for i, sc in enumerate(scenarios):
        means = [grp[(grp.scenario == sc) & (grp.combination == c)]
                  .obj_value.values for c in combos]
        means = [m[0] if len(m) else 0 for m in means]
        ax.bar(x + i * width - 0.4 + width / 2, means,
               width=width * 0.9, label=sc,
               color=plt.cm.tab10(i % 10), alpha=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(combos, rotation=30, ha="right")
    ax.set_ylabel("Soft cost medio")
    ax.set_title("Soft cost medio per combinazione, per scenario")
    ax.legend()
    fig.tight_layout()
    _save(fig, "bar_softcost_by_combo")


def scatter_time_vs_softcost(df):
    df = df[df.status == "ok"].copy()
    df = df.dropna(subset=["obj_value", "t_total"])
    if df.empty:
        return
    scenarios = sorted(df.scenario.unique())
    combos = sorted(df.combination.unique())
    fig, ax = plt.subplots(figsize=(9, 6))
    for i, sc in enumerate(scenarios):
        for j, c in enumerate(combos):
            sub = df[(df.scenario == sc) & (df.combination == c)]
            if sub.empty:
                continue
            ax.scatter(sub.t_total, sub.obj_value,
                        color=plt.cm.tab10(i % 10),
                        marker=("o", "s", "^", "v", "D", "*", "P")
                                [j % 7],
                        s=80, alpha=0.7,
                        label=f"{sc}/{c}" if len(scenarios) <= 2
                              else None)
    ax.set_xlabel("Tempo totale (s)")
    ax.set_ylabel("Soft cost")
    ax.set_title("Pareto frontier: tempo vs soft cost")
    if len(scenarios) <= 2:
        ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    _save(fig, "scatter_time_vs_softcost")


def stacked_breakdown(df):
    df = df[df.status == "ok"].copy()
    if df.empty:
        return
    grp = df.groupby(["scenario", "combination"])[
        ["t_phase_a", "t_phase_b", "t_post"]].mean().reset_index()
    scenarios = sorted(grp.scenario.unique())
    fig, axes = plt.subplots(1, len(scenarios),
                              figsize=(5 * len(scenarios), 5),
                              sharey=True)
    if len(scenarios) == 1:
        axes = [axes]
    for ax, sc in zip(axes, scenarios):
        sub = grp[grp.scenario == sc].set_index("combination")
        sub = sub.sort_index()
        sub.plot(kind="bar", stacked=True, ax=ax,
                  color=["#5b9bd5", "#ed7d31", "#a5a5a5"])
        ax.set_title(sc)
        ax.set_xlabel("")
        ax.tick_params(axis="x", rotation=30)
    axes[0].set_ylabel("Tempo medio (s)")
    fig.suptitle("Breakdown tempo: Phase A / Phase B / post-pass")
    fig.tight_layout()
    _save(fig, "stacked_breakdown")


def heatmap_combo_x_scenario(df):
    df = df[df.status == "ok"].copy()
    if df.empty:
        return
    pivot = df.pivot_table(index="combination",
                            columns="scenario",
                            values="t_total",
                            aggfunc="mean")
    fig, ax = plt.subplots(figsize=(7, 5))
    im = ax.imshow(pivot.values, cmap="YlOrRd", aspect="auto")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.values[i, j]
            ax.text(j, i, f"{v:.0f}s" if not np.isnan(v) else "-",
                    ha="center", va="center",
                    color="black" if v < pivot.values.mean() else "white")
    fig.colorbar(im, ax=ax, label="t_total (s)")
    ax.set_title("Tempo medio: combinazione x scenario")
    fig.tight_layout()
    _save(fig, "heatmap_combo_x_scenario")


def tightness_plots(df):
    df = df[df.status == "ok"].copy()
    if df.empty or df.tightness_score.nunique() < 2:
        print("[plots] not enough tightness variation; "
              "skipping tightness_vs_*")
        return
    combos = sorted(df.combination.unique())
    # tightness_vs_time
    fig, ax = plt.subplots(figsize=(9, 5))
    for i, c in enumerate(combos):
        sub = df[df.combination == c]\
            .groupby("tightness_score").t_total.mean().reset_index()
        sub = sub.sort_values("tightness_score")
        ax.plot(sub.tightness_score, sub.t_total,
                marker="o", label=c, color=plt.cm.tab10(i % 10))
    ax.set_xlabel("Tightness score")
    ax.set_ylabel("Tempo totale medio (s)")
    ax.set_title("Tightness vs tempo, per combinazione")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    _save(fig, "tightness_vs_time")

    # tightness_vs_softcost
    fig, ax = plt.subplots(figsize=(9, 5))
    df_obj = df.dropna(subset=["obj_value"])
    for i, c in enumerate(combos):
        sub = df_obj[df_obj.combination == c]\
            .groupby("tightness_score").obj_value.mean().reset_index()
        sub = sub.sort_values("tightness_score")
        if not sub.empty:
            ax.plot(sub.tightness_score, sub.obj_value,
                    marker="o", label=c, color=plt.cm.tab10(i % 10))
    ax.set_xlabel("Tightness score")
    ax.set_ylabel("Soft cost medio")
    ax.set_title("Tightness vs soft cost, per combinazione")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    _save(fig, "tightness_vs_softcost")

    # tightness_vs_feasibility
    fig, ax = plt.subplots(figsize=(9, 5))
    rate = df.groupby(["combination", "tightness_score"])\
        .agg(rate=("hard_feasible",
                    lambda s: float(s.fillna(False).sum()) / max(1, len(s))))\
        .reset_index()
    for i, c in enumerate(combos):
        sub = rate[rate.combination == c].sort_values("tightness_score")
        ax.plot(sub.tightness_score, sub.rate,
                marker="o", label=c, color=plt.cm.tab10(i % 10))
    ax.set_xlabel("Tightness score")
    ax.set_ylabel("HARD-feasibility rate")
    ax.set_ylim(-0.05, 1.05)
    ax.set_title("Tightness vs feasibility, per combinazione")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    _save(fig, "tightness_vs_feasibility")


def main():
    df = _load()
    print(f"[plots] {len(df)} rows from "
          f"{df.scenario.unique().tolist()}")
    boxplot_time_by_combo(df)
    bar_softcost_by_combo(df)
    scatter_time_vs_softcost(df)
    stacked_breakdown(df)
    heatmap_combo_x_scenario(df)
    tightness_plots(df)
    print(f"[plots] DONE -> {FIG_DIR}")


if __name__ == "__main__":
    main()
