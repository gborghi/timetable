"""One-shot migration: add `dataset=pickle` column to the
pre-v2 results.csv produced by the original full sweep. After
this runs, the CSV header matches what bench v2 expects and new
SQLite-source runs can append.

Usage:
  python tests/benchmarks/_migrate_csv_v2.py
"""
import csv
import os

CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "..", "docs", "manual", "benchmarks",
                    "results.csv")
CSV = os.path.abspath(CSV)

NEW_FIELDS = [
    "profile", "dataset", "technique", "family", "seed", "status",
    "t_phase_a", "t_phase_b", "t_post", "t_total", "cost",
    "hard_feasible", "n_lessons", "n_columns", "n_iterations",
    "n_classes", "n_teachers", "note", "error_msg",
]


def main():
    with open(CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if rows and "dataset" in rows[0]:
        print(f"[migrate] CSV already has 'dataset' column "
              f"({len(rows)} rows); no-op")
        return
    with open(CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=NEW_FIELDS)
        w.writeheader()
        for r in rows:
            r["dataset"] = "pickle"
            w.writerow({k: r.get(k, "") for k in NEW_FIELDS})
    print(f"[migrate] transformed {len(rows)} rows, "
          f"added dataset=pickle column -> {CSV}")


if __name__ == "__main__":
    main()
