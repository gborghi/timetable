"""Procedural generator for stress-constraint datasets.

Hand-written profiles small/ and medium/ already exist with curated
conflicts. For the bigger profiles (big/huge/superhuge/mega) the goal
is volume, not uniqueness: each profile has ~N records spread across
the three categories with a fixed proportion of intentional
conflicts (~10% by default).

The generator emits the same JSON shape as the curated files
(profile/category/schema_version/description/constraints) so
`load_stress_constraints.py` consumes them transparently.

USE
    cd engine/scripts
    python generate_stress_constraints.py --profile big
    python generate_stress_constraints.py --profile huge
    python generate_stress_constraints.py --all

Sizes per profile (approx, see PROFILE_SIZES):
    small       ~ 18 records   3 conflict pairs   (curated)
    medium      ~ 29 records   4 conflict pairs   (curated)
    big         ~ 60 records   6 conflict pairs   (generated)
    huge        ~ 120 records  10 conflict pairs  (generated)
    superhuge   ~ 240 records  18 conflict pairs  (generated)
    mega        ~ 500 records  40 conflict pairs  (generated)
"""
from __future__ import annotations

import argparse
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))

# Per-category target counts.  (teacher, classroom, relational)
PROFILE_SIZES = {
    "big":       (28, 16, 16),
    "huge":      (60, 30, 30),
    "superhuge": (120, 60, 60),
    "mega":      (260, 120, 120),
}

# Approximate fraction of records that are intentionally conflicting.
CONFLICT_FRAC = 0.10

DAYS = ["lun", "mar", "mer", "gio", "ven", "sab"]
SLOTS_MORN = [8, 9, 10]            # 1-3rd hour
SLOTS_MID  = [11, 12]              # 4-5th hour
SLOTS_AFT  = [13]                  # 6th hour
ALL_SLOTS  = SLOTS_MORN + SLOTS_MID + SLOTS_AFT

SUBJECTS = ["Matematica", "Italiano", "Storia", "Filosofia",
            "Fisica", "Chimica", "Inglese", "Religione",
            "Latino", "Greco", "Scienze", "Disegno"]

CURRICULA = ["Scientifico", "ScienzeApplicate", "ScienzeUmane",
             "LinguisticoFRA_TED", "EconomicoSociale"]

ORDINALS_T = ["first", "second", "third", "fourth", "fifth",
              "sixth", "seventh", "eighth", "ninth", "tenth",
              "eleventh", "twelfth"]
ORDINALS_C = ["first", "second", "third", "fourth", "fifth",
              "sixth"]


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _slot(day: str, hour: int) -> str:
    return f"{day}{hour}"


def _level_with_weight(rng: random.Random, allow_enforced: bool = True):
    """Return (level, weight_or_none) with a brand-typical mix."""
    r = rng.random()
    if r < 0.35:
        return ("hard", None)
    if r < 0.55 and allow_enforced:
        return ("enforced", None)
    if r < 0.78:
        return ("preferred", rng.randrange(50, 100))
    return ("soft", rng.randrange(40, 90))


# ---------------------------------------------------------------------
# Per-category generators
# ---------------------------------------------------------------------

def _gen_teacher(rng, n_total, n_conflicts, profile):
    out = []
    used_owner_pattern = []
    for i in range(n_total):
        rid = f"{profile}_t_{i+1:03d}"
        owner_idx = i % len(ORDINALS_T)
        owner = f"{ORDINALS_T[owner_idx]}_teacher"
        used_owner_pattern.append(owner)
        # Pick an expression style
        kind_choice = rng.random()
        if kind_choice < 0.35:
            day = rng.choice(DAYS)
            hours = rng.sample(ALL_SLOTS, k=2)
            expr = " AND ".join([f"mai {_slot(day, h)}"
                                  for h in sorted(hours)])
            descr = (f"Docente: non puo' insegnare {day} alle ore "
                     + ", ".join(str(h) for h in sorted(hours)) + ".")
        elif kind_choice < 0.55:
            d = rng.choice(DAYS)
            expr = f"mai {d}"
            descr = (f"Docente: indisponibile interamente il {d}.")
        elif kind_choice < 0.75:
            d1, d2 = rng.sample(DAYS, k=2)
            h = rng.choice(SLOTS_MORN)
            expr = (f"({_slot(d1, h)} AND {_slot(d1, h+1)}) "
                    f"OR ({_slot(d2, h)} AND {_slot(d2, h+1)})")
            descr = ("Docente: lezione doppia in mattinata in "
                     f"{d1} o {d2}.")
        elif kind_choice < 0.9:
            subj = rng.choice(SUBJECTS)
            d = rng.choice(DAYS)
            expr = f"mai materia:{subj}@{d}"
            descr = (f"Docente: non insegna {subj} il {d}.")
        else:
            d1, d2 = rng.sample(DAYS, k=2)
            expr = f"{d1} OR {d2}"
            descr = (f"Docente: preferenza positiva per {d1}/{d2}.")
        level, weight = _level_with_weight(rng)
        rec = {
            "id": rid,
            "kind": "logical_teacher",
            "scope": "teacher",
            "owner_pattern": owner,
            "level": level,
            "expression": expr,
            "intentionally_conflicting": False,
            "conflict_with": None,
            "description": descr,
        }
        if weight is not None:
            rec["weight"] = weight
        out.append(rec)
    # Add explicit conflict pairs: take some HARD "mai X" and add an
    # ENFORCED "X" on the same owner.
    pairs_added = 0
    for rec in list(out):
        if pairs_added >= n_conflicts:
            break
        if rec["level"] != "hard":
            continue
        # Try to extract a slot from "mai SLOT" patterns
        expr = rec["expression"]
        if "mai " not in expr or "@" in expr or "materia:" in expr:
            continue
        # Find first slot
        toks = [t.replace("mai", "").strip() for t in
                expr.split(" AND ")]
        slot = next((t for t in toks if t and "OR" not in t), None)
        if slot is None:
            continue
        rid2 = f"{profile}_t_{n_total + pairs_added + 1:03d}"
        rec_conflict = {
            "id": rid2,
            "kind": "logical_teacher",
            "scope": "teacher",
            "owner_pattern": rec["owner_pattern"],
            "level": "enforced",
            "expression": slot,
            "intentionally_conflicting": True,
            "conflict_with": [rec["id"]],
            "description": ("[CONFLITTO INTENZIONALE] enforce "
                             f"{slot} contro mai {slot} ({rec['id']})."),
        }
        out.append(rec_conflict)
        pairs_added += 1
    return out


def _gen_classroom(rng, n_total, n_conflicts, profile):
    out = []
    room_keys = ["first_lab", "second_lab", "third_lab", "fourth_lab",
                 "gym", "main_room"]
    for i in range(n_total):
        rid = f"{profile}_r_{i+1:03d}"
        owner = room_keys[i % len(room_keys)]
        kind_choice = rng.random()
        if kind_choice < 0.35:
            d = rng.choice(DAYS)
            hours = sorted(rng.sample(SLOTS_MORN + SLOTS_MID, k=2))
            expr = " AND ".join(f"mai {_slot(d, h)}" for h in hours)
            descr = ("Aula: chiusa "
                     f"{d} ore "
                     + ", ".join(str(h) for h in hours) + ".")
        elif kind_choice < 0.55:
            d = rng.choice(DAYS)
            expr = f"mai {d}"
            descr = f"Aula: indisponibile {d} (corso esterno)."
        elif kind_choice < 0.75:
            d1, d2 = rng.sample(DAYS, k=2)
            expr = f"(lun8 AND lun9) OR ({d1}8 AND {d2}9)"
            descr = ("Aula: preferenza per coppie mattutine.")
        else:
            d = rng.choice(DAYS)
            expr = f"mai sab AND mai {d}13"
            descr = ("Aula: chiusa sabato e ultima ora di "
                     f"{d}.")
        level, weight = _level_with_weight(rng)
        rec = {
            "id": rid,
            "kind": "logical_classroom",
            "scope": "classroom",
            "owner_pattern": owner,
            "level": level,
            "expression": expr,
            "intentionally_conflicting": False,
            "conflict_with": None,
            "description": descr,
        }
        if weight is not None:
            rec["weight"] = weight
        out.append(rec)
    pairs_added = 0
    for rec in list(out):
        if pairs_added >= n_conflicts:
            break
        if rec["level"] != "hard":
            continue
        expr = rec["expression"]
        if "mai " not in expr:
            continue
        toks = [t.replace("mai", "").strip() for t in
                expr.split(" AND ")]
        slot = next((t for t in toks if t and "OR" not in t), None)
        if slot is None:
            continue
        rid2 = f"{profile}_r_{n_total + pairs_added + 1:03d}"
        rec_conflict = {
            "id": rid2,
            "kind": "logical_classroom",
            "scope": "classroom",
            "owner_pattern": rec["owner_pattern"],
            "level": "enforced",
            "expression": slot,
            "intentionally_conflicting": True,
            "conflict_with": [rec["id"]],
            "description": ("[CONFLITTO INTENZIONALE] enforce "
                             f"{slot} contro mai {slot} ({rec['id']})."),
        }
        out.append(rec_conflict)
        pairs_added += 1
    return out


def _gen_relational(rng, n_total, n_conflicts, profile):
    out = []
    for i in range(n_total):
        rid = f"{profile}_x_{i+1:03d}"
        choice = rng.random()
        if choice < 0.4:
            # class scope
            year = rng.randint(1, 5)
            ord_idx = rng.randint(0, 2)
            owner = f"{ORDINALS_C[ord_idx]}_class_year_{year}"
            scope = "class"
            kind = "logical_class"
            subj = rng.choice(SUBJECTS)
            h = rng.choice(SLOTS_AFT + SLOTS_MID)
            expr = f"mai materia:{subj}@{h}"
            descr = (f"Classe: {subj} mai alla {h}a ora.")
        elif choice < 0.75:
            # curriculum scope
            curr = rng.choice(CURRICULA)
            owner = curr
            scope = "curriculum"
            kind = "logical_curriculum"
            d1, d2, d3 = rng.sample(DAYS, k=3)
            expr = (f"({d1}8 OR {d2}8 OR {d3}8)")
            descr = (f"Curriculum {curr}: preferenza per inizio mattina "
                     "in giorni intermedi.")
        else:
            # classroom scope (relational, e.g. forced subject in lab)
            owner = rng.choice(["first_lab", "second_lab", "third_lab",
                                "main_room", "gym"])
            scope = "classroom"
            kind = "logical_classroom"
            subj = rng.choice(["Fisica", "Chimica", "Disegno"])
            d = rng.choice(DAYS)
            h = rng.choice(SLOTS_MORN)
            expr = f"materia:{subj}@{_slot(d, h)}"
            descr = (f"Aula: ospita {subj} {d} ora {h}.")
        level, weight = _level_with_weight(rng,
                                             allow_enforced=(choice >= 0.75))
        rec = {
            "id": rid,
            "kind": kind,
            "scope": scope,
            "owner_pattern": owner,
            "level": level,
            "expression": expr,
            "intentionally_conflicting": False,
            "conflict_with": None,
            "description": descr,
        }
        if weight is not None:
            rec["weight"] = weight
        out.append(rec)
    pairs_added = 0
    for rec in list(out):
        if pairs_added >= n_conflicts:
            break
        if rec["scope"] != "classroom" or rec["level"] != "enforced":
            continue
        # Pick a hard "mai" classroom-side rule that contradicts this
        # forced slot. We'll just emit a sibling "mai SLOT" record on
        # the same owner.
        if "@" not in rec["expression"]:
            continue
        slot = rec["expression"].split("@")[-1].strip()
        rid2 = f"{profile}_x_{n_total + pairs_added + 1:03d}"
        rec_conflict = {
            "id": rid2,
            "kind": "logical_classroom",
            "scope": "classroom",
            "owner_pattern": rec["owner_pattern"],
            "level": "hard",
            "expression": f"mai {slot}",
            "intentionally_conflicting": True,
            "conflict_with": [rec["id"]],
            "description": ("[CONFLITTO INTENZIONALE] mai " + slot
                             + " contro enforce stesso slot ("
                             + rec["id"] + ")."),
        }
        out.append(rec_conflict)
        pairs_added += 1
    return out


# ---------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------

def _emit(profile: str, category: str, recs: list[dict]):
    out_dir = os.path.join(HERE, "stress_constraints", profile)
    os.makedirs(out_dir, exist_ok=True)
    fn = os.path.join(out_dir, f"{category}_constraints.json")
    payload = {
        "profile": profile,
        "category": category,
        "schema_version": 1,
        "description": (f"Stress dataset {category} per {profile}, "
                         "generato proceduralmente."),
        "constraints": recs,
    }
    with open(fn, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    n_conf = sum(1 for r in recs if r.get("intentionally_conflicting"))
    print(f"  [{profile}/{category}] {len(recs)} record "
          f"({n_conf} intenzionali)")


def generate_profile(profile: str, seed: int = 42):
    if profile not in PROFILE_SIZES:
        raise SystemExit(f"profile {profile!r} not in PROFILE_SIZES")
    nt, nr, nx = PROFILE_SIZES[profile]
    nt_conf = max(2, int(nt * CONFLICT_FRAC))
    nr_conf = max(1, int(nr * CONFLICT_FRAC))
    nx_conf = max(1, int(nx * CONFLICT_FRAC))
    rng = random.Random(seed)
    print(f"[gen] profile={profile} sizes=({nt}, {nr}, {nx}) "
          f"conflicts=({nt_conf}, {nr_conf}, {nx_conf})")
    teacher = _gen_teacher(rng, nt, nt_conf, profile)
    rooms   = _gen_classroom(rng, nr, nr_conf, profile)
    rel     = _gen_relational(rng, nx, nx_conf, profile)
    _emit(profile, "teacher", teacher)
    _emit(profile, "classroom", rooms)
    _emit(profile, "relational", rel)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile",
                    choices=list(PROFILE_SIZES.keys()) + ["all"])
    ap.add_argument("--all", action="store_true",
                    help="generate every profile")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    if args.all or args.profile == "all":
        for p in PROFILE_SIZES:
            generate_profile(p, seed=args.seed)
    elif args.profile:
        generate_profile(args.profile, seed=args.seed)
    else:
        ap.error("specify --profile or --all")


if __name__ == "__main__":
    main()
