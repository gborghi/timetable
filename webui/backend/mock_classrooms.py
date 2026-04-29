"""Deterministic recipe to auto-generate classrooms for a school.

The recipe is **proportional to the number of classes** in the DB.
Defaults are computed by `compute_default_counts(n_classes)`; the user
can override any individual count from the UI before clicking "Genera".

Layout (school-style):
    - 1 'standard' room per class, named exactly like the class
      (the class' "home")
    - N labs of each kind (fisica/chimica/informatica/lingue),
      proportional to n_classes
    - N palestre, proportional
    - >=1 biblioteca
    - N aule speciali (multi-use / disegno / arte / musica)

Rules of thumb -- all are documented in `webui/docs/classroom_generation.md`:
    lab_fisica       ~ 1 every 10 classes
    lab_chimica      ~ 1 every 10 classes
    lab_informatica  ~ 1 every  8 classes (more demand)
    lab_linguistico  ~ 1 every 12 classes
    palestra         ~ 1 every 18 classes
    biblioteca         1 fixed (rarely scaled)
    aula_speciale    ~ 1 every 20 classes
All have a hard floor of 1.
"""
from __future__ import annotations

from typing import Any


# Divisor "1 every K classes" per kind. Tweak here if you want a different
# baseline; UI exposes the resulting count for further override.
DEFAULT_DIVISORS: dict[str, int] = {
    "lab_fisica":      10,
    "lab_chimica":     10,
    "lab_informatica":  8,
    "lab_linguistico": 12,
    "palestra":        18,
    "biblioteca":     999,   # de facto fixed at 1 unless huge
    "aula_speciale":   20,
}

# Lower bound (number always >= floor)
DEFAULT_FLOOR: dict[str, int] = {k: 1 for k in DEFAULT_DIVISORS}


KIND_TO_SUBJECTS_REQUIRED: dict[str, list[str]] = {
    "lab_chimica": ["Chimica", "Scienze"],
    "lab_fisica": ["Fisica"],
    "lab_informatica": ["Informatica"],
    "lab_linguistico": ["Inglese", "Francese", "Tedesco", "Spagnolo"],
    "palestra": ["Scienzemotorie", "Educazionefisica"],
    "biblioteca": [],
    "aula_speciale": [],
}

KIND_DEFAULTS: dict[str, dict[str, Any]] = {
    "standard": dict(capacity=30, multi_class=False, multi_class_max=1,
                     multi_class_pref=1),
    "lab_chimica": dict(capacity=24, multi_class=False, multi_class_max=1,
                        multi_class_pref=1),
    "lab_fisica": dict(capacity=24, multi_class=False, multi_class_max=1,
                       multi_class_pref=1),
    "lab_informatica": dict(capacity=22, multi_class=False, multi_class_max=1,
                            multi_class_pref=1),
    "lab_linguistico": dict(capacity=22, multi_class=False, multi_class_max=1,
                            multi_class_pref=1),
    "palestra": dict(capacity=60, multi_class=True, multi_class_max=2,
                     multi_class_pref=1),
    "biblioteca": dict(capacity=40, multi_class=True, multi_class_max=2,
                       multi_class_pref=1),
    "aula_speciale": dict(capacity=30, multi_class=False, multi_class_max=1,
                          multi_class_pref=1),
}


def compute_default_counts(n_classes: int) -> dict[str, int]:
    """Compute the proportional defaults for classroom counts given the
    current number of classes in the school.

    Returns a dict keyed by the same names used in DEFAULT_DIVISORS.
    Each value is an integer >= 1.
    """
    n = max(0, int(n_classes))
    out: dict[str, int] = {}
    for kind, k in DEFAULT_DIVISORS.items():
        floor = DEFAULT_FLOOR.get(kind, 1)
        # round half-up; biblioteca's huge divisor effectively keeps it at 1
        if n == 0:
            count = floor
        else:
            count = max(floor, round(n / k))
        out[kind] = count
    # biblioteca: keep at 1 unless n_classes >= 60 (then add one per 60)
    out["biblioteca"] = max(1, n // 60 if n >= 60 else 1)
    return out


def build_recipe_for_classes(class_names: list[str], n_classes: int | None = None,
                             overrides: dict[str, int | None] | None = None
                             ) -> list[dict]:
    """Returns a list of classroom dicts to create. Each dict has:
        name, kind, capacity, multi_class, multi_class_max,
        multi_class_pref, subject_required, is_home_for_class.

    `n_classes` is the school size used to compute proportional defaults;
    it defaults to len(class_names). `overrides` is a partial dict of
    explicit counts (any None falls back to the proportional default).
    """
    if n_classes is None:
        n_classes = len(class_names)
    counts = compute_default_counts(n_classes)
    if overrides:
        for k, v in overrides.items():
            if v is not None and k in counts:
                counts[k] = max(0, int(v))

    out: list[dict] = []
    # 1 standard per class
    for cl_name in class_names:
        defaults = KIND_DEFAULTS["standard"]
        out.append({
            "name": cl_name,
            "kind": "standard",
            "capacity": defaults["capacity"],
            "multi_class": defaults["multi_class"],
            "multi_class_max": defaults["multi_class_max"],
            "multi_class_pref": defaults["multi_class_pref"],
            "subject_required": [],
            "is_home_for_class": cl_name,
        })
    # Labs / palestre / biblioteche / aule speciali
    for kind, n in counts.items():
        defaults = KIND_DEFAULTS.get(kind, {})
        subj_req = KIND_TO_SUBJECTS_REQUIRED.get(kind, [])
        for i in range(1, int(n) + 1):
            label = (kind.replace("lab_", "Lab ")
                         .replace("aula_speciale", "Aula speciale")
                         .replace("_", " ")
                         .title())
            name = f"{label} {i}"
            out.append({
                "name": name,
                "kind": kind,
                "capacity": defaults.get("capacity", 30),
                "multi_class": defaults.get("multi_class", False),
                "multi_class_max": defaults.get("multi_class_max", 1),
                "multi_class_pref": defaults.get("multi_class_pref", 1),
                "subject_required": subj_req,
                "is_home_for_class": None,
            })
    return out
