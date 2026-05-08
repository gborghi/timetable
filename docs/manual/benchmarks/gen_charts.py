"""Generate pgfplots-friendly tables and TikZ snippets from
results.csv produced by tests/benchmarks/run_full_sweep.py.

Output: `charts_generated.tex` next to this script. The
benchmarks chapter \\input{}'s it.

Usage:
  python docs/manual/benchmarks/gen_charts.py
  python docs/manual/benchmarks/gen_charts.py --csv path/to/other.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from statistics import median, pstdev

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(HERE, "results.csv")
OUT = os.path.join(HERE, "charts_generated.tex")

PROFILES = ["small", "medium", "big", "huge", "superhuge", "mega"]
FAMILIES = ["greedy", "cpsat", "decomp", "cg", "bp", "meta"]


def load(csv_path: str) -> list[dict]:
    rows = []
    if not os.path.exists(csv_path):
        return rows
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def _f(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except ValueError:
        return None


def _fmt(v, nd=1):
    if v is None:
        return "--"
    return f"{v:.{nd}f}"


def emit_summary_table(rows, fh):
    """Per-profile summary: best technique by cost, best by time,
    count of unwired/timeout/exception."""
    fh.write("\\subsection*{Tabella riassuntiva per profilo}\n\n")
    fh.write("\\begin{table}[h]\n\\centering\\sffamily\\small\n")
    fh.write("\\begin{tabular}{lrrrrrr}\n\\toprule\n")
    fh.write("Profilo & best-cost & best-cost (s) & "
             "best-time & best-time (cost) & ok & not-ok \\\\\n")
    fh.write("\\midrule\n")
    by_prof = defaultdict(list)
    for r in rows:
        by_prof[r["profile"]].append(r)
    for prof in PROFILES:
        rs = by_prof.get(prof, [])
        oks = [r for r in rs if r["status"] == "ok"]
        if not oks:
            fh.write(f"{prof} & -- & -- & -- & -- & 0 & "
                     f"{len(rs)} \\\\\n")
            continue
        # best by cost
        bc = min(oks, key=lambda r: _f(r["cost"]) or float("inf"))
        # best by time
        bt = min(oks, key=lambda r: _f(r["t_total"]) or float("inf"))
        notok = len(rs) - len(oks)
        fh.write(
            f"{prof} & "
            f"\\texttt{{{bc['technique'].replace('_', '\\_')}}} & "
            f"{_fmt(_f(bc['t_total']))} & "
            f"\\texttt{{{bt['technique'].replace('_', '\\_')}}} & "
            f"{_fmt(_f(bt['cost']), 0)} & "
            f"{len(oks)} & {notok} \\\\\n")
    fh.write("\\bottomrule\n\\end{tabular}\n")
    fh.write("\\caption{Per ciascun profilo: tecnica con il "
             "minor costo soft, tempo totale di quella tecnica; "
             "tecnica con il minor tempo, costo soft di quella "
             "tecnica; numero di celle riuscite vs. non-riuscite "
             "(unwired+timeout+infeasible+exception).}\n")
    fh.write("\\label{tab:bench-best-per-profile}\n\\end{table}\n\n")


def emit_family_avg_table(rows, fh):
    """Average wall-clock per family per profile."""
    fh.write("\\subsection*{Tempo medio per famiglia di tecnica e profilo}\n\n")
    fh.write("\\begin{table}[h]\n\\centering\\sffamily\\small\n")
    fh.write("\\begin{tabular}{l" + "r" * len(FAMILIES) + "}\n")
    fh.write("\\toprule\n")
    fh.write("Profilo & " + " & ".join(FAMILIES) + " \\\\\n")
    fh.write("\\midrule\n")
    by_pf = defaultdict(list)
    for r in rows:
        if r["status"] != "ok":
            continue
        v = _f(r["t_total"])
        if v is None:
            continue
        by_pf[(r["profile"], r["family"])].append(v)
    for prof in PROFILES:
        line = [prof]
        for fam in FAMILIES:
            vals = by_pf.get((prof, fam), [])
            if vals:
                line.append(_fmt(sum(vals) / len(vals)))
            else:
                line.append("--")
        fh.write(" & ".join(line) + " \\\\\n")
    fh.write("\\bottomrule\n\\end{tabular}\n")
    fh.write("\\caption{Tempo medio (s) di celle riuscite per "
             "famiglia $\\times$ profilo. Una famiglia senza celle "
             "riuscite per quel profilo \\`e marcata \\texttt{--}.}\n")
    fh.write("\\label{tab:bench-family-avg}\n\\end{table}\n\n")


def emit_pgfplot_time_per_profile(rows, fh):
    fh.write("\\subsection*{Tempo per profilo: bar chart per famiglia}\n\n")
    by_pf = defaultdict(list)
    for r in rows:
        if r["status"] != "ok":
            continue
        v = _f(r["t_total"])
        if v is None:
            continue
        by_pf[(r["profile"], r["family"])].append(v)
    fh.write("\\begin{figure}[h]\n\\centering\n")
    fh.write("\\begin{tikzpicture}\n\\begin{axis}[\n")
    fh.write("  ybar=2pt, bar width=4pt, width=14cm, height=8cm,\n")
    fh.write("  ymin=0, xlabel={Profilo}, ylabel={Tempo medio (s)},\n")
    fh.write("  symbolic x coords={" + ",".join(PROFILES) + "},\n")
    fh.write("  xtick=data,\n  enlarge x limits=0.12,\n")
    fh.write("  legend style={font=\\footnotesize, at={(1.02,1)}, "
             "anchor=north west, draw=none},\n")
    fh.write("  ymajorgrids=true, grid style=dashed,\n")
    fh.write("  every axis plot/.append style={fill opacity=0.7},\n")
    fh.write("]\n")
    palette = {
        "greedy": "gray",
        "cpsat": "cIndaco",
        "decomp": "cSiena",
        "cg": "cOro",
        "bp": "cEnf",
        "meta": "cSoft",
    }
    for fam in FAMILIES:
        coords = []
        for prof in PROFILES:
            vals = by_pf.get((prof, fam), [])
            if vals:
                coords.append(f"({prof},{sum(vals) / len(vals):.1f})")
        if not coords:
            continue
        fh.write(f"\\addplot+[fill={palette[fam]}, draw={palette[fam]}!50!black] coordinates ")
        fh.write("{" + " ".join(coords) + "};\n")
        fh.write(f"\\addlegendentry{{{fam}}}\n")
    fh.write("\\end{axis}\n\\end{tikzpicture}\n")
    fh.write("\\caption{Tempo medio in secondi per famiglia di "
             "tecnica e profilo. Le celle in stato non-OK "
             "(unwired, timeout, exception) sono escluse dal "
             "calcolo. Il bar chart resta vuoto per le combinazioni "
             "famiglia-profilo prive di celle riuscite.}\n")
    fh.write("\\label{fig:bench-time-bar}\n\\end{figure}\n\n")


def emit_full_results_table(rows, fh):
    fh.write("\\subsection*{Matrice completa dei risultati}\n\n")
    fh.write("\\begin{longtable}{llllrrrll}\n")
    fh.write("\\caption{Risultati riga-per-riga del full sweep. "
             "\\texttt{cost} \\`e la somma pesata delle violazioni soft "
             "(scala specifica del modello, lower-is-better). "
             "\\texttt{hard} \\`e True se la soluzione \\`e fattibile "
             "rispetto a tutti i vincoli hard. "
             "\\texttt{dataset=pickle} indica caricamento da pickle "
             "anagrafico (zero vincoli stratificati); "
             "\\texttt{dataset=sqlite} indica caricamento dal profilo "
             "SQLite con le 14 tabelle di vincolo popolate.}\\\\\n")
    fh.write("\\toprule\n")
    fh.write("Profilo & DS & Tecnica & Famiglia & "
             "$t$\\,total (s) & cost & hard & status & note \\\\\n")
    fh.write("\\midrule\n\\endfirsthead\n")
    fh.write("\\toprule\n")
    fh.write("Profilo & DS & Tecnica & Famiglia & "
             "$t$\\,total (s) & cost & hard & status & note \\\\\n")
    fh.write("\\midrule\n\\endhead\n\\bottomrule\n\\endfoot\n")
    for r in rows:
        prof = r["profile"]
        ds = r.get("dataset", "pickle")
        tech = r["technique"].replace("_", "\\_")
        fam = r["family"]
        tt = _fmt(_f(r["t_total"]))
        cost = _fmt(_f(r["cost"]), 0)
        hard = r.get("hard_feasible", "")
        status = r["status"].replace("_", "\\_")
        note = (r.get("note", "") or r.get("error_msg", ""))[:40]
        note = note.replace("_", "\\_").replace("&", "\\&")
        fh.write(f"\\texttt{{{prof}}} & \\texttt{{{ds}}} & "
                 f"\\texttt{{{tech}}} & "
                 f"{fam} & {tt} & {cost} & {hard} & "
                 f"\\texttt{{{status}}} & {note} \\\\\n")
    fh.write("\\end{longtable}\n\n")


def emit_pickle_vs_sqlite_delta(rows, fh):
    """Compare cost on the same (profile, technique) cell between
    pickle and sqlite datasets. Shows where the constraint
    stratification matters most."""
    by_cell = defaultdict(dict)
    for r in rows:
        if r["status"] != "ok":
            continue
        c = _f(r["cost"])
        if c is None:
            continue
        by_cell[(r["profile"], r["technique"])][r.get("dataset", "pickle")] = c
    pairs = [(k, v["pickle"], v["sqlite"]) for k, v in by_cell.items()
             if "pickle" in v and "sqlite" in v]
    if not pairs:
        fh.write("\\subsection*{Delta pickle vs.\\ sqlite}\n\n"
                 "\\emph{Nessuna cella in cui entrambi i dataset "
                 "abbiano prodotto una soluzione OK; impossibile "
                 "calcolare il delta.}\n\n")
        return
    fh.write("\\subsection*{Delta costo pickle vs.\\ sqlite "
             "(stesse celle, entrambe OK)}\n\n")
    fh.write("\\begin{table}[h]\n\\centering\\sffamily\\small\n")
    fh.write("\\begin{tabular}{llrrr}\n\\toprule\n")
    fh.write("Profilo & Tecnica & cost (pickle) & "
             "cost (sqlite) & $\\Delta$\\,\\% \\\\\n\\midrule\n")
    # Sort by absolute delta-% descending so the most-impactful cells
    # come first. Ties broken by (profile, technique) alphabetic.
    def _delta_key(p):
        (_pt, cp, cs) = p
        d = (cs - cp) / cp * 100.0 if cp > 0 else 0.0
        return (-abs(d), p[0][0], p[0][1])
    pairs.sort(key=_delta_key)
    for (prof, tech), cp, cs in pairs:
        delta = (cs - cp) / cp * 100.0 if cp > 0 else float("inf")
        fh.write(f"\\texttt{{{prof}}} & "
                 f"\\texttt{{{tech.replace('_','\\_')}}} & "
                 f"{cp:.0f} & {cs:.0f} & "
                 f"{delta:+.1f}\\% \\\\\n")
    fh.write("\\bottomrule\n\\end{tabular}\n")
    fh.write("\\caption{Delta percentuale del costo soft fra il "
             "dataset \\texttt{pickle} (zero vincoli stratificati) e "
             "il dataset \\texttt{sqlite} (14 tabelle di vincolo "
             "popolate). Valori positivi indicano che lo SQLite paga "
             "il costo dei vincoli aggiuntivi; valori negativi (rari) "
             "indicano che la stratificazione ha guidato il solver "
             "verso una soluzione complessivamente migliore.}\n")
    fh.write("\\label{tab:bench-delta-pickle-sqlite}\n\\end{table}\n\n")


def emit_top_bottom(rows, fh):
    oks = [r for r in rows if r["status"] == "ok"
           and _f(r["cost"]) is not None]
    if not oks:
        return
    fh.write("\\subsection*{Top-5 per costo (lower is better)}\n\n")
    sorted_by_cost = sorted(oks, key=lambda r: _f(r["cost"]) or float("inf"))
    fh.write("\\begin{tabular}{rlllrr}\n\\toprule\n")
    fh.write("\\# & Profilo & Tecnica & Famiglia & cost & "
             "$t$\\,total (s) \\\\\n\\midrule\n")
    for i, r in enumerate(sorted_by_cost[:5], 1):
        fh.write(f"{i} & \\texttt{{{r['profile']}}} & "
                 f"\\texttt{{{r['technique'].replace('_','\\_')}}} & "
                 f"{r['family']} & {_fmt(_f(r['cost']),0)} & "
                 f"{_fmt(_f(r['t_total']))} \\\\\n")
    fh.write("\\bottomrule\n\\end{tabular}\n\n\\medskip\n\n")
    fh.write("\\subsection*{Bottom-5 per costo (highest cost)}\n\n")
    fh.write("\\begin{tabular}{rlllrr}\n\\toprule\n")
    fh.write("\\# & Profilo & Tecnica & Famiglia & cost & "
             "$t$\\,total (s) \\\\\n\\midrule\n")
    for i, r in enumerate(sorted_by_cost[::-1][:5], 1):
        fh.write(f"{i} & \\texttt{{{r['profile']}}} & "
                 f"\\texttt{{{r['technique'].replace('_','\\_')}}} & "
                 f"{r['family']} & {_fmt(_f(r['cost']),0)} & "
                 f"{_fmt(_f(r['t_total']))} \\\\\n")
    fh.write("\\bottomrule\n\\end{tabular}\n\n")


def emit_speedup_vs_baseline(rows, fh):
    """Speedup of each technique vs cpsat_day baseline, per profile."""
    by_prof_tech = {}
    for r in rows:
        if r["status"] != "ok":
            continue
        t = _f(r["t_total"])
        c = _f(r["cost"])
        if t is None:
            continue
        by_prof_tech[(r["profile"], r["technique"])] = (t, c)

    fh.write("\\subsection*{Speedup vs.\\ baseline \\texttt{cpsat\\_day}}\n\n")
    fh.write("\\begin{table}[h]\n\\centering\\sffamily\\small\n")
    fh.write("\\begin{tabular}{lrrr}\n\\toprule\n")
    fh.write("Profilo & baseline (s) & best speedup & cost gap \\\\\n")
    fh.write("\\midrule\n")
    for prof in PROFILES:
        base = by_prof_tech.get((prof, "cpsat_day"))
        if not base:
            fh.write(f"{prof} & -- & -- & -- \\\\\n")
            continue
        bt, bc = base
        # Find the technique with t_total min for this profile
        best_speed = None
        best_tech = None
        best_cost = None
        for (p, t), (tt, cc) in by_prof_tech.items():
            if p != prof:
                continue
            if t == "cpsat_day":
                continue
            ratio = bt / tt if tt > 0 else None
            if ratio is None:
                continue
            if best_speed is None or ratio > best_speed:
                best_speed = ratio
                best_tech = t
                best_cost = cc
        if best_tech and bc and best_cost is not None:
            gap = (best_cost - bc) / bc * 100.0
            fh.write(f"{prof} & {bt:.1f} & "
                     f"{best_speed:.2f}\\,$\\times$ "
                     f"(\\texttt{{{best_tech.replace('_','\\_')}}}) & "
                     f"{gap:+.1f}\\% \\\\\n")
        else:
            fh.write(f"{prof} & {bt:.1f} & -- & -- \\\\\n")
    fh.write("\\bottomrule\n\\end{tabular}\n")
    fh.write("\\caption{Per ciascun profilo: tempo della pipeline "
             "baseline \\texttt{cpsat\\_day} (Phase A + Phase B per "
             "giorno), tecnica con il maggiore speedup rispetto al "
             "baseline e gap percentuale del suo costo soft. Valori "
             "positivi del gap indicano un costo peggiore della "
             "baseline; negativi un costo migliore.}\n")
    fh.write("\\label{tab:bench-speedup}\n\\end{table}\n\n")


def emit_bp_columns_iters(rows, fh):
    """Average columns generated and iterations for BP per granularity."""
    fh.write("\\subsection*{Branch-and-Price: colonne e iterazioni "
             "per granularit\\`a}\n\n")
    by_tech = defaultdict(lambda: ([], []))
    for r in rows:
        if r["family"] != "bp" or r["status"] != "ok":
            continue
        nc = _f(r["n_columns"])
        ni = _f(r["n_iterations"])
        if nc is not None:
            by_tech[r["technique"]][0].append(nc)
        if ni is not None:
            by_tech[r["technique"]][1].append(ni)
    if not by_tech:
        fh.write("\\emph{Nessuna cella BP riuscita "
                 "nel run corrente.}\n\n")
        return
    fh.write("\\begin{table}[h]\n\\centering\\sffamily\\small\n")
    fh.write("\\begin{tabular}{lrrr}\n\\toprule\n")
    fh.write("Granularit\\`a & celle ok & col.~medie & iter medie \\\\\n")
    fh.write("\\midrule\n")
    for tech in sorted(by_tech):
        cols, iters = by_tech[tech]
        col_avg = (sum(cols) / len(cols)) if cols else None
        it_avg = (sum(iters) / len(iters)) if iters else None
        fh.write(f"\\texttt{{{tech.replace('_','\\_')}}} & "
                 f"{len(cols)} & "
                 f"{_fmt(col_avg, 1) if col_avg is not None else '--'} & "
                 f"{_fmt(it_avg, 1) if it_avg is not None else '--'} \\\\\n")
    fh.write("\\bottomrule\n\\end{tabular}\n")
    fh.write("\\caption{Per ciascuna granularit\\`a di pricing: "
             "numero medio di colonne generate e di iterazioni "
             "del loop BP, calcolati sulle celle riuscite del "
             "presente run.}\n")
    fh.write("\\label{tab:bench-bp-stats}\n\\end{table}\n\n")


def emit_pgfplot_cost_vs_iter(rows, fh):
    """Line chart: cost vs iterazione per CG/BP. Synthesized from
    aggregated final cost; we don't have per-iteration data in CSV,
    so this falls back to a bar chart of final cost per technique
    for the small profile."""
    fh.write("\\subsection*{Costo finale per tecnica (profilo \\texttt{small})}\n\n")
    small = [r for r in rows
             if r["profile"] == "small" and r["status"] == "ok"
             and _f(r["cost"]) is not None]
    if not small:
        fh.write("\\emph{Nessuna cella OK su small.}\n\n")
        return
    fh.write("\\begin{figure}[h]\n\\centering\n")
    # pgfplots interprets underscores inside `axis` as math-mode
    # subscripts; we replace `_` with `-` for both symbolic coord
    # values and labels so the bar chart renders cleanly.
    safe_names = [r["technique"].replace("_", "-") for r in small]
    fh.write("\\begin{tikzpicture}\n\\begin{axis}[\n")
    fh.write("  xbar, bar width=4pt, width=12cm, "
             f"height={max(4, 0.45 * len(small))}cm,\n")
    fh.write("  xmin=0, xlabel={Costo soft (lower-is-better)},\n")
    fh.write("  symbolic y coords={" + ",".join(safe_names) + "},\n")
    fh.write("  ytick=data,\n  every axis plot/.append style="
             "{fill=cIndaco!70, draw=cIndaco},\n")
    fh.write("  xmajorgrids=true, grid style=dashed,\n")
    fh.write("  ylabel style={font=\\footnotesize}, "
             "yticklabel style={font=\\footnotesize\\ttfamily},\n")
    fh.write("]\n\\addplot coordinates {")
    for r, sn in zip(small, safe_names):
        fh.write(f"({_f(r['cost']):.0f},{sn}) ")
    fh.write("};\n\\end{axis}\n\\end{tikzpicture}\n")
    fh.write("\\caption{Costo finale (soft objective) per tecnica "
             "sul profilo \\texttt{small}. Le tecniche sono in "
             "ordine di apparizione nel CSV: leggile dall'alto al "
             "basso per il cluster cpsat--decomp--cg--bp--meta.}\n")
    fh.write("\\label{fig:bench-cost-small}\n\\end{figure}\n\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="append", default=None,
                     help="results CSV (repeat for multiple files; rows "
                          "are unioned). Default: results.csv next to "
                          "this script.")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--profiles", type=str, default=None,
                     help="comma-separated subset of profiles to keep "
                          "in the output (e.g. small,medium,big)")
    ap.add_argument("--dataset", type=str, default=None,
                     choices=("pickle", "sqlite"),
                     help="if set, restrict the per-profile/per-family "
                          "tables to this dataset only. The pickle-vs-"
                          "sqlite delta block always uses both.")
    args = ap.parse_args()
    csv_paths = args.csv or [DEFAULT_CSV]
    rows: list[dict] = []
    for p in csv_paths:
        sub = load(p)
        print(f"[gen-charts] read {len(sub)} rows from {p}")
        rows.extend(sub)
    # De-dupe on (profile, dataset, technique, seed) so that a row
    # present in multiple CSVs doesn't get double-counted; later CSVs
    # win on conflict (caller's responsibility to order them).
    keyed = {}
    for r in rows:
        k = (r.get("profile"), r.get("dataset", "pickle"),
             r.get("technique"), r.get("seed", "42"))
        keyed[k] = r
    rows = list(keyed.values())
    profiles_filter = (set(p.strip() for p in args.profiles.split(","))
                       if args.profiles else None)
    if profiles_filter:
        rows = [r for r in rows if r.get("profile") in profiles_filter]
    # The dataset filter applies to *most* tables -- but the
    # pickle-vs-sqlite delta block needs both, so we keep the full
    # `rows` and pass a filtered view to single-dataset emitters.
    if args.dataset:
        rows_focus = [r for r in rows
                      if r.get("dataset", "pickle") == args.dataset]
    else:
        rows_focus = rows
    print(f"[gen-charts] {len(rows)} rows after merge/filter "
          f"({len(rows_focus)} in focus dataset)")
    if not rows:
        print("[gen-charts] no data; writing placeholder .tex")
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("% Auto-generated by docs/manual/benchmarks/gen_charts.py.\n")
        fh.write("% Do not edit by hand. Re-run gen_charts.py after\n")
        fh.write("% updating results.csv.\n")
        fh.write(f"% Inputs: {csv_paths}\n")
        if args.dataset:
            fh.write(f"% Dataset focus: {args.dataset}\n")
        if profiles_filter:
            fh.write(f"% Profile filter: {sorted(profiles_filter)}\n")
        fh.write("\n")
        if not rows:
            fh.write("\\emph{Nessun dato di benchmark disponibile. "
                     "Esegui \\texttt{tests/benchmarks/run\\_full\\_sweep.py} "
                     "e poi \\texttt{docs/manual/benchmarks/gen\\_charts.py}.}\n")
            return
        # Note: we sort rows for stable output
        for arr in (rows, rows_focus):
            arr.sort(key=lambda r: (PROFILES.index(r["profile"])
                                      if r["profile"] in PROFILES else 99,
                                      r.get("dataset", "pickle"),
                                      r["family"], r["technique"]))
        emit_summary_table(rows_focus, fh)
        emit_family_avg_table(rows_focus, fh)
        emit_speedup_vs_baseline(rows_focus, fh)
        emit_pgfplot_time_per_profile(rows_focus, fh)
        emit_pgfplot_cost_vs_iter(rows_focus, fh)
        emit_bp_columns_iters(rows_focus, fh)
        # Delta block always uses the full union (needs both datasets).
        emit_pickle_vs_sqlite_delta(rows, fh)
        emit_top_bottom(rows_focus, fh)
        emit_full_results_table(rows_focus, fh)
    print(f"[gen-charts] wrote {args.out}")


if __name__ == "__main__":
    main()
