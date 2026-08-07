"""Loader for the stress-constraint datasets in
engine/stress_constraints/.

For a chosen profile, walks the three category files
(teacher_, classroom_, relational_) and POSTs each constraint
to the running webapp's /api/constraints endpoint. Resolves
`owner_pattern` against the live DB (e.g. 'first_teacher' -> the
teacher with the smallest id).

Tracks the mapping `dataset_id -> db_id` in
`engine/stress_constraints/<profile>/loaded_<timestamp>.json`
so that later runs of the feasibility-check can verify which
DB constraint corresponds to which dataset record (by id), and
in particular which DB rows are part of `intentionally_conflicting`
pairs.

USE
    cd engine/scripts
    python load_stress_constraints.py --profile small
    python load_stress_constraints.py --profile medium --backend http://127.0.0.1:8000
    python load_stress_constraints.py --profile small --dry-run
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import urllib.request
import urllib.error
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BACKEND = "http://127.0.0.1:8000"


# ---------------------------------------------------------------------
# HTTP helpers (no external deps; stdlib urllib only)
# ---------------------------------------------------------------------

def _http_get(backend: str, path: str) -> Any:
    url = backend.rstrip("/") + path
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_post(backend: str, path: str, body: dict) -> Any:
    url = backend.rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------------------------------------------------------------
# Owner resolution
# ---------------------------------------------------------------------

def _resolve_teacher(backend: str, pattern: str,
                     teachers: list[dict]) -> int | None:
    """Map an `owner_pattern` like 'first_teacher', 'second_teacher',
    or a literal name to a teacher id."""
    ordered = sorted(teachers, key=lambda t: t.get("id", 0))
    nth_map = {f"{n}_teacher": i for i, n in enumerate(
        ["first", "second", "third", "fourth", "fifth",
         "sixth", "seventh", "eighth", "ninth", "tenth",
         "eleventh", "twelfth"], start=0)}
    if pattern in nth_map:
        idx = nth_map[pattern]
        if idx < len(ordered):
            return ordered[idx]["id"]
        return None
    # Literal match by name / nickname / display
    for t in teachers:
        if pattern in (t.get("name", ""), t.get("nickname", ""),
                       t.get("display_name", "")):
            return t["id"]
        ln = t.get("last_name") or ""
        fn = t.get("first_name") or ""
        if pattern == f"{ln} {fn}".strip():
            return t["id"]
        if pattern == f"{ln} {fn[:1] + '.'}".strip(" ."):
            return t["id"]
    return None


def _resolve_classroom(pattern: str, rooms: list[dict]) -> int | None:
    """Map a pattern to a classroom id. Special tokens:
    'first_lab' / 'second_lab' / 'third_lab' / 'gym' / 'main_room'.
    """
    labs = sorted([r for r in rooms
                   if (r.get("kind") or "").lower().startswith("lab")],
                  key=lambda r: r["id"])
    nth_lab = {"first_lab": 0, "second_lab": 1, "third_lab": 2,
               "fourth_lab": 3}
    if pattern in nth_lab:
        idx = nth_lab[pattern]
        if idx < len(labs):
            return labs[idx]["id"]
        return None
    if pattern == "gym":
        for r in rooms:
            if "palest" in (r.get("kind") or "").lower() \
                    or "palest" in (r.get("name") or "").lower():
                return r["id"]
    if pattern == "main_room":
        for r in rooms:
            if "magna" in (r.get("name") or "").lower() \
                    or (r.get("kind") or "").lower() == "aula_magna":
                return r["id"]
    # Literal name match
    for r in rooms:
        if pattern == r.get("name"):
            return r["id"]
    return None


def _resolve_class(pattern: str, classes: list[dict]) -> int | None:
    """Map patterns like 'first_class_year_1' (1st class of year 1) or
    a literal class name to a class id."""
    if pattern.startswith(("first_class_year_", "second_class_year_",
                            "third_class_year_", "fourth_class_year_",
                            "fifth_class_year_", "sixth_class_year_")):
        _order_token, _, year_str = pattern.rsplit("_", 2)[0], None, pattern.split("_")[-1]
        ord_map = {"first": 0, "second": 1, "third": 2,
                   "fourth": 3, "fifth": 4, "sixth": 5}
        try:
            year = int(year_str)
        except ValueError:
            return None
        token = pattern.split("_")[0]   # 'first', 'second', ...
        idx = ord_map.get(token, 0)
        in_year = sorted([c for c in classes if c.get("year") == year],
                         key=lambda c: c["id"])
        if idx < len(in_year):
            return in_year[idx]["id"]
        return None
    for c in classes:
        if pattern == c.get("name"):
            return c["id"]
    return None


def _resolve_curriculum(pattern: str, curricula: list[dict]) -> int | None:
    for c in curricula:
        if pattern == c.get("name"):
            return c["id"]
    return None


# ---------------------------------------------------------------------
# Constraint posting
# ---------------------------------------------------------------------

def _post_one(backend: str, rec: dict, owners: dict) -> dict:
    """Resolve owner + post one constraint via /api/constraints
    (the unified dispatcher). Returns {dataset_id, db_id, ok, error}.
    """
    out = {"dataset_id": rec["id"], "db_id": None, "ok": False,
           "error": None}
    scope = rec["scope"]
    if scope == "teacher":
        owner_id = _resolve_teacher(backend, rec["owner_pattern"],
                                     owners["teachers"])
    elif scope == "classroom":
        owner_id = _resolve_classroom(rec["owner_pattern"],
                                       owners["classrooms"])
    elif scope == "class":
        owner_id = _resolve_class(rec["owner_pattern"],
                                   owners["classes"])
    elif scope == "curriculum":
        owner_id = _resolve_curriculum(rec["owner_pattern"],
                                        owners["curricula"])
    else:
        out["error"] = f"unknown scope {scope!r}"
        return out

    if owner_id is None:
        out["error"] = (f"owner '{rec['owner_pattern']}' (scope "
                        f"{scope}) not found in DB")
        return out

    body = {
        "scope": scope,
        "kind": "logical",
        "level": rec["level"],
        "owner_id": owner_id,
        "expression": rec["expression"],
    }
    if rec.get("weight") is not None:
        body["weight"] = rec["weight"]
    if rec.get("description"):
        body["description"] = rec["description"]
    try:
        resp = _http_post(backend, "/api/constraints", body)
        out["ok"] = True
        out["db_id"] = resp.get("id") or resp.get("db_id")
    except urllib.error.HTTPError as e:
        out["error"] = f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}"
    except Exception as e:
        out["error"] = str(e)
    return out


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def _load_dataset(profile: str) -> list[dict]:
    base = os.path.join(HERE, "stress_constraints", profile)
    files = ["teacher_constraints.json",
             "classroom_constraints.json",
             "relational_constraints.json"]
    out: list[dict] = []
    for fn in files:
        p = os.path.join(base, fn)
        if not os.path.exists(p):
            print(f"[stress-loader] missing {p}, skipping")
            continue
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        for c in data.get("constraints", []):
            out.append(c)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True,
                    choices=["small", "medium", "big", "huge",
                              "superhuge", "mega"])
    ap.add_argument("--backend", default=DEFAULT_BACKEND)
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve owners and validate but don't POST")
    args = ap.parse_args()

    print(f"[stress-loader] profile={args.profile}, "
          f"backend={args.backend}")
    dataset = _load_dataset(args.profile)
    print(f"[stress-loader] loaded {len(dataset)} constraint records "
          f"from JSON")
    if not dataset:
        return

    print("[stress-loader] fetching DB owners...")
    try:
        teachers = _http_get(args.backend, "/api/teachers?limit=1000")
        classes = _http_get(args.backend, "/api/classes?limit=1000")
        rooms = _http_get(args.backend, "/api/classrooms?limit=1000")
        curricula = _http_get(args.backend, "/api/curricula?limit=1000")
    except Exception as e:
        print(f"[stress-loader] backend probe failed: {e}")
        sys.exit(2)
    # The list endpoints might return either a list or an envelope
    # `{items, total}`; normalise.
    def _items(x):
        if isinstance(x, dict) and "items" in x:
            return x["items"]
        return x

    owners = {
        "teachers": _items(teachers),
        "classes": _items(classes),
        "classrooms": _items(rooms),
        "curricula": _items(curricula),
    }
    print(f"[stress-loader] DB has {len(owners['teachers'])} teachers, "
          f"{len(owners['classes'])} classes, "
          f"{len(owners['classrooms'])} rooms, "
          f"{len(owners['curricula'])} curricula")

    results = []
    n_ok = 0
    n_err = 0
    for rec in dataset:
        if args.dry_run:
            scope = rec["scope"]
            if scope == "teacher":
                owner_id = _resolve_teacher(args.backend,
                                             rec["owner_pattern"],
                                             owners["teachers"])
            elif scope == "classroom":
                owner_id = _resolve_classroom(rec["owner_pattern"],
                                               owners["classrooms"])
            elif scope == "class":
                owner_id = _resolve_class(rec["owner_pattern"],
                                           owners["classes"])
            elif scope == "curriculum":
                owner_id = _resolve_curriculum(rec["owner_pattern"],
                                                owners["curricula"])
            else:
                owner_id = None
            ok = owner_id is not None
            print(f"  {rec['id']:14s} -> {scope}/{owner_id}  "
                  f"{'ok' if ok else 'OWNER NOT RESOLVED'}")
            results.append({"dataset_id": rec["id"],
                            "db_id": owner_id, "ok": ok,
                            "error": None if ok else
                                     "owner not resolved"})
            if ok: n_ok += 1
            else: n_err += 1
            continue

        out = _post_one(args.backend, rec, owners)
        results.append(out)
        flag = "ok" if out["ok"] else "ERR"
        suffix = (f"db_id={out['db_id']}" if out["ok"]
                   else f"err={out['error']}")
        print(f"  {rec['id']:14s} {flag:3s}  {suffix}")
        if out["ok"]:
            n_ok += 1
        else:
            n_err += 1

    # Persist mapping
    ts = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_dir = os.path.join(HERE, "stress_constraints", args.profile)
    out_fn = os.path.join(
        out_dir, f"loaded_{ts}{'_dryrun' if args.dry_run else ''}.json")
    with open(out_fn, "w", encoding="utf-8") as f:
        json.dump({"profile": args.profile,
                   "backend": args.backend,
                   "timestamp_utc": ts,
                   "dry_run": bool(args.dry_run),
                   "n_total": len(dataset),
                   "n_ok": n_ok, "n_err": n_err,
                   "results": results},
                  f, indent=2, ensure_ascii=False)
    print(f"\n[stress-loader] {n_ok} ok, {n_err} err. Mapping saved "
          f"to {out_fn}")


if __name__ == "__main__":
    main()
