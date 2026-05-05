"""Read tests/benchmarks/results/bp_scalability.json and emit
plots for the BP scalability section of the manual.

Plots produced (each as PNG + SVG, in docs/benchmarks/figures/):
  - bp_time_by_scale.png        bar chart of t_BP per scale
                                  with horizontal target lines
                                  (5 min for HUGE, 30 min for MEGA).
  - bp_columns_by_scale.png     bar chart of n_columns at the end
                                  of the BP loop.

Usage:
  python docs/benchmarks/generate_bp_plots.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
RESULTS = Path(ROOT) / "tests" / "benchmarks" / "results" / "bp_scalability.json"
FIGS = Path(HERE) / "figures"
FIGS.mkdir(parents=True, exist_ok=True)


def _save(fig, name):
    fig.savefig(FIGS / f"{name}.png", dpi=150, bbox_inches="tight")
    fig.savefig(FIGS / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)


def main():
    if not RESULTS.exists():
        raise SystemExit(
            f"missing {RESULTS} -- run the benchmark first")
    with open(RESULTS, "r", encoding="utf-8") as f:
        data = json.load(f)

    scales = ["huge", "mega"]
    metrics = [data[s] for s in scales if s in data]
    if not metrics:
        raise SystemExit(
            f"no recognised scales in {RESULTS}: {list(data)}")
    labels = [
        f"{m['scale'].upper()}\n"
        f"{m['n_classes']} cl / {m['n_teachers']} prof / "
        f"{m['n_cattedre']} catt"
        for m in metrics
    ]
    times = [m["t_bp_s"] for m in metrics]
    cols = [m["n_columns"] or 0 for m in metrics]

    # Bar: t_BP per scale, with target lines.
    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(labels, times,
                   color=["#4c78a8", "#f58518"], edgecolor="black")
    for bar, t in zip(bars, times):
        ax.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() + 0.05,
                 f"{t:.2f} s", ha="center", va="bottom",
                 fontsize=10)
    # Target lines: HUGE 5 min, MEGA 30 min.
    targets = {"huge": 300.0, "mega": 1800.0}
    for i, m in enumerate(metrics):
        target = targets.get(m["scale"])
        if target is None:
            continue
        ax.axhline(y=target, xmin=i / len(metrics),
                    xmax=(i + 1) / len(metrics),
                    color="red", linestyle="--", alpha=0.5,
                    label="_nolegend_")
    ax.set_ylabel("t_BP (s)")
    ax.set_title("Branch-and-Price tempo a HARD-feasibility "
                  "(scenari sintetici)")
    ax.set_yscale("log")
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, "bp_time_by_scale")

    # Bar: n_columns
    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(labels, cols,
                   color=["#4c78a8", "#f58518"], edgecolor="black")
    for bar, c in zip(bars, cols):
        ax.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() + 5,
                 f"{c}", ha="center", va="bottom", fontsize=10)
    ax.set_ylabel("n_columns (final pool size)")
    ax.set_title("Dimensione finale del pool di colonne")
    ax.grid(True, axis="y", alpha=0.3)
    _save(fig, "bp_columns_by_scale")

    print("emitted: bp_time_by_scale, bp_columns_by_scale "
          "(PNG + SVG) in", FIGS)


if __name__ == "__main__":
    main()
