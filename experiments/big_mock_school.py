r"""Generatore di mock "scuola grande" basato sulle funzioni gia\` presenti
in schedule/mock_classes2.py, SENZA modificarlo.

Riusa le funzioni pure-dati del mock generator e produce un dump
serializzabile (school_big.pkl) con:
  - classes: list di dict {name, year, curriculum, subjects (dict subj->ore)}
  - teachers: list di dict {name, group, max_hours, free_day, weights}
  - cconcorsopersubject: dict subj -> {classe_concorso -> peso}

Questo dump viene poi consumato da cpsat_v2_assignment.py
(senza dipendenze su mock_classes2 a runtime).

Uso:
    cd experiments
    python big_mock_school.py [--small | --medium | --big]
"""
import os
import sys
import argparse
import math
import pickle
from collections import defaultdict

# Permettiamo l'import di mock_classes2 senza modificarlo
SCHEDULE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "schedule")
)
sys.path.insert(0, SCHEDULE_DIR)

# Nota: mock_classes2.py ha effetti collaterali a livello modulo
# (Faker.seed, random.seed, creazione di un cp_model.CpModel global).
# Sono innocui per noi: useremo solo le funzioni pure-dati.
import mock_classes2 as mc  # noqa: E402


PROFILES = {
    # ~10 classi (2 sezioni x 5 anni)
    "small": {
        "Scientifico": 1, "ScienzeApplicate": 1, "ScienzeUmane": 0,
        "EconomicoSociale_FRA": 0, "EconomicoSociale_SPA": 0,
        "EconomicoSociale_TED": 0,
        "Linguistico_FRA_TED": 0, "Linguistico_FRA_SPA": 0,
    },
    # ~25 classi (5 sezioni x 5 anni)
    "medium": {
        "Scientifico": 2, "ScienzeApplicate": 1, "ScienzeUmane": 1,
        "EconomicoSociale_FRA": 0, "EconomicoSociale_SPA": 0,
        "EconomicoSociale_TED": 0,
        "Linguistico_FRA_TED": 1, "Linguistico_FRA_SPA": 0,
    },
    # ~35 classi (7 sezioni * 5 anni). Target: scuola grande tipica.
    "big": {
        "Scientifico": 2, "ScienzeApplicate": 1, "ScienzeUmane": 1,
        "EconomicoSociale_FRA": 1, "EconomicoSociale_SPA": 0,
        "EconomicoSociale_TED": 0,
        "Linguistico_FRA_TED": 1, "Linguistico_FRA_SPA": 1,
    },
    # ~50 classi -- stress test taglia "molto grande"
    "huge": {
        "Scientifico": 3, "ScienzeApplicate": 2, "ScienzeUmane": 2,
        "EconomicoSociale_FRA": 1, "EconomicoSociale_SPA": 0,
        "EconomicoSociale_TED": 0,
        "Linguistico_FRA_TED": 1, "Linguistico_FRA_SPA": 1,
    },
    # 80 classi (16 sezioni x 5 anni), per ~2000 studenti.
    # Mix realistico per un istituto superiore italiano molto grande.
    "superhuge": {
        "Scientifico": 3, "ScienzeApplicate": 3, "ScienzeUmane": 3,
        "EconomicoSociale_FRA": 1, "EconomicoSociale_SPA": 1,
        "EconomicoSociale_TED": 1,
        "Linguistico_FRA_TED": 2, "Linguistico_FRA_SPA": 2,
    },
}


def generate_aggregated_teachers(hours_needed_per_subject, day_weights,
                                 cconcorsopersubject, cconcorso_list,
                                 margin=0.05, base_max_hours=18,
                                 min_part_time=10, max_hours_cap=22):
    r"""Genera un pool di docenti aggregato per CLASSE-DI-CONCORSO
    (gruppo), in modo che la maggior parte dei docenti abbia ~18
    ore (cattedra completa). Per ogni gruppo:
      1. Calcola la sua "fetta" di domanda: D_g = somma per ogni
         materia s del peso (s, g) / sum_g'(weight(s, g')) * D_s.
      2. n_full = floor(D_g * (1+margin) / base_max_hours)
      3. leftover = (D_g * (1+margin)) - n_full * base_max_hours
      4. Crea n_full docenti a `base_max_hours` + 1 part-time per
         leftover (se leftover >= min_part_time, altrimenti
         distribuisci sull'ultimo docente; con max_hours_cap come
         tetto contrattuale).

    Pensata per soddisfare i vincoli A-B (massimo 10% docenti con
    cattedra < 18, massimo 3% con < 10) -- non garantito a livello
    micro per gruppi piccoli, ma la distribuzione globale tende
    naturalmente a 90%+ a 18 ore.
    """
    teachers = []
    allnames = set()
    # 1. demand-per-gruppo: alloca tutto al gruppo PRIMARIO (con
    # peso massimo) di ciascuna materia. I gruppi "secondari" non
    # ricevono docenti dedicati, evitando docenti idle a 0 ore.
    primary_gruppo = {}
    for subj in hours_needed_per_subject:
        weights = cconcorsopersubject.get(subj, {})
        if not weights:
            continue
        primary_gruppo[subj] = max(weights.items(), key=lambda x: x[1])[0]
    demand_per_gruppo = defaultdict(int)
    for subj, demand in hours_needed_per_subject.items():
        g = primary_gruppo.get(subj)
        if g:
            demand_per_gruppo[g] += demand
    # 2. per-gruppo allocation
    for g_name, D in demand_per_gruppo.items():
        target = max(1, int(math.ceil(D * (1 + margin))))
        n_full = target // base_max_hours
        leftover = target - n_full * base_max_hours
        sizes = [base_max_hours] * n_full
        if leftover > 0:
            if leftover < min_part_time and sizes:
                # absorb sull'ultimo, eventualmente sopra base
                if sizes[-1] + leftover <= max_hours_cap:
                    sizes[-1] += leftover
                else:
                    sizes.append(leftover)
            else:
                sizes.append(leftover)
        gruppo = next(g for g in cconcorso_list if g.name == g_name)
        for sz in sizes:
            while True:
                tname = mc.fake.name()
                if tname not in allnames:
                    allnames.add(tname)
                    break
            free_day = mc.choose_random_free_day(day_weights)
            birth = mc.fake.date_of_birth(minimum_age=25, maximum_age=67)
            t = mc.Teacher(tname, gruppo, sz, free_day, birth=birth)
            teachers.append(t)
    return teachers


def generate_tight_teachers(hours_needed_per_subject, day_weights,
                            cconcorsopersubject, cconcorso_list,
                            margin=0.15, base_max_hours=18,
                            min_part_time=4):
    r"""Crea un pool di docenti con somma ore-disponibilita\` =
    fabbisogno x (1+margin), dove "fabbisogno" e\` il monte ore della
    materia. L'ultimo docente di ogni materia puo\` essere part-time
    (max_hours < base_max_hours) per fine-tunare il totale.

    A differenza di mc.generate_required_teachers (che mette sempre
    18h e genera sovradimensionamento dipendente dal numero di
    materie), qui la dimensione totale del pool e\` esplicitamente
    controllata da `margin`.

    Nota sul double counting di gruppi multi-materia: per soggetti
    che possono essere coperti da N gruppi di concorso (es. Matematica
    da A026 e A027), la scelta del gruppo per ciascun docente segue
    i pesi `cconcorsopersubject[subj]`, come nel mock originale.
    Questo introduce variabilita\` ma non incide sull'ordine di
    grandezza del pool: il bilanciamento bipartito in fase di
    assegnazione resta governato da `margin`.
    """
    teachers = []
    allnames = set()
    for subject, demand in hours_needed_per_subject.items():
        target = max(1, int(math.ceil(demand * (1.0 + margin))))
        n_full = target // base_max_hours
        leftover = target - n_full * base_max_hours
        sizes = [base_max_hours] * n_full
        if leftover > 0:
            if leftover < min_part_time and sizes:
                # spalmiamo sull'ultimo docente per evitare
                # part-time microscopici
                sizes[-1] += leftover
            else:
                sizes.append(leftover)
        weights = cconcorsopersubject[subject]
        groups_keys = list(weights.keys())
        groups_vals = list(weights.values())
        for size in sizes:
            mychoice = mc.random.choices(groups_keys, groups_vals)[0]
            free_day = mc.choose_random_free_day(day_weights)
            while True:
                tname = mc.fake.name()
                if tname not in allnames:
                    allnames.add(tname)
                    break
            birth = mc.fake.date_of_birth(minimum_age=25, maximum_age=67)
            group = next(g for g in cconcorso_list if g.name == mychoice)
            t = mc.Teacher(tname, group, size, free_day, birth=birth)
            teachers.append(t)
    return teachers


def build_dataset(profile_name: str, tight: bool = True,
                  margin: float = 0.15, mode: str = "tight"):
    profile = PROFILES[profile_name]
    print(f"[big_mock] profilo: {profile_name} -> {profile}")

    # Riusa le funzioni pure-dati di mock_classes2
    curricula, _curr_subjects, curriculum_subject_hours = mc.generate_curriculum_subjects()
    cconcorsodict, cconcorso_list, cconcorsopersubject = mc.generate_subject_groups()

    school_classes = mc.create_school_classes_with_curriculum(
        curricula, curriculaclasses=profile
    )
    print(f"[big_mock] classi: {len(school_classes)}")

    hours_needed = mc.calculate_teachers_needed(school_classes)
    if mode == "aggregated":
        teachers = generate_aggregated_teachers(
            hours_needed, mc.day_weights,
            cconcorsopersubject, cconcorso_list,
            margin=margin,
        )
        print(
            f"[big_mock] docenti (aggregated pool, margin={margin:.2f}): "
            f"{len(teachers)}"
        )
    elif mode == "tight":
        teachers = generate_tight_teachers(
            hours_needed, mc.day_weights,
            cconcorsopersubject, cconcorso_list,
            margin=margin,
        )
        print(
            f"[big_mock] docenti (tight pool, margin={margin:.2f}): "
            f"{len(teachers)}"
        )
    else:
        teachers = mc.generate_required_teachers(
            hours_needed, mc.day_weights, cconcorsopersubject, cconcorso_list
        )
        print(f"[big_mock] docenti (legacy pool): {len(teachers)}")

    # Serializzazione "leggera" -- niente oggetti CP-SAT
    classes_dump = []
    for cl in school_classes:
        classes_dump.append({
            "name": cl.name,
            "year": cl.year,
            "section": cl.section,
            "curriculum": cl.curriculum,
            "subjects": dict(cl.subjects),  # subj -> ore
        })
    teachers_dump = []
    for t in teachers:
        teachers_dump.append({
            "name": t.name,
            "group": t.subject_group.name,
            "max_hours": t.max_hours,
            "free_day": t.free_day,
            "weights": dict(t.weights),  # subj -> peso (intero)
        })

    # cconcorsopersubject: subj -> {classe_concorso -> peso}, tutti dati
    # serializzabili nativi.
    out = {
        "profile": profile_name,
        "classes": classes_dump,
        "teachers": teachers_dump,
        "cconcorsopersubject": dict(
            (k, dict(v)) for k, v in cconcorsopersubject.items()
        ),
        "curriculum_scores": dict(mc.curriculum_scores),
    }
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile", choices=list(PROFILES.keys()), default="big"
    )
    parser.add_argument(
        "--out",
        default=None,
        help="path di output, default ./school_<profile>.pkl",
    )
    parser.add_argument(
        "--legacy-pool", action="store_true",
        help="usa il generatore originale di mock_classes2 (pool "
             "sovradimensionato dipendente dal numero di materie)"
    )
    parser.add_argument(
        "--mode", choices=["aggregated", "tight", "legacy"],
        default="aggregated",
        help="aggregated = per-gruppo full-time + 1 part-time "
             "(default, soddisfa A-B); tight = per-materia; "
             "legacy = mock_classes2.generate_required_teachers"
    )
    parser.add_argument(
        "--margin", type=float, default=0.05,
        help="margine di sovradimensionamento del pool docenti "
             "(default 0.05 = +5%% sul fabbisogno per modo "
             "aggregated)"
    )
    args = parser.parse_args()

    mode = "legacy" if args.legacy_pool else args.mode
    data = build_dataset(
        args.profile,
        tight=(mode == "tight"),
        margin=args.margin,
        mode=mode,
    )
    out = args.out or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"school_{args.profile}.pkl",
    )
    with open(out, "wb") as f:
        pickle.dump(data, f)
    print(f"[big_mock] scritto {out}")
    # piccolo summary
    n_subj = sum(len(c["subjects"]) for c in data["classes"])
    tot_hours = sum(h for c in data["classes"] for h in c["subjects"].values())
    pool_hours = sum(t["max_hours"] for t in data["teachers"])
    print(
        f"[big_mock] summary: {len(data['classes'])} classi, "
        f"{len(data['teachers'])} docenti, "
        f"{n_subj} (classe,materia) coppie, "
        f"fabbisogno={tot_hours} ore/sett, "
        f"pool docenti={pool_hours} ore/sett "
        f"(slack={pool_hours - tot_hours} ore = "
        f"{100.0 * (pool_hours - tot_hours) / tot_hours:.1f}%)"
    )


if __name__ == "__main__":
    main()
