r"""Assegnazione prof->classe (cattedre) v2 -- proof of concept.

Risolve in un'unica passata CP-SAT con tre obiettivi linearizzati e
sommati con pesi gerarchici: completare le cattedre, ridurre il numero
di classi distinte per docente, massimizzare il numero di indirizzi
distinti per docente. Il bilanciamento equita\` (la "phase 4" del
mock_classes2 originale) e\` rimosso dal CP-SAT e tenuto come
post-processing locale opzionale a colpi di swap (vedi --balance).

PERCHE\` E\` PIU\` VELOCE:
- niente AddMultiplicationEquality (la phase 4 del mock attuale faceva
  due moltiplicazioni di IntVar enormi -- vedi proposals/analysis.md);
- una sola risoluzione invece di 4;
- penalita\` come somma di valori assoluti (non quadrati).

PERCHE\` PRODUCE QUALITA\` SIMILE:
- i pesi sono "lessicografici" (1e9, 1e3, 1) cosi\` la fase 1 domina,
  poi la fase 2, ecc. -- equivalente a 3 risoluzioni in cascata se
  la prima trova l'ottimo. Aggiusta i pesi se nelle tue istanze i
  domini sono molto piu\` grandi.
- l'equita\` finale, se attivata, viene ottenuta con dev. assolute.

USO:
    cd engine
    python big_mock_school.py --profile big   # produce school_big.pkl
    python cpsat_v2_assignment.py --school school_big.pkl --time 60
"""
import argparse
import os
import pickle
import time

from ortools.sat.python import cp_model


def load_school(path):
    with open(path, "rb") as f:
        return pickle.load(f)


def solve_assignment(data, time_limit_s=60, workers=8, log=True):
    classes = data["classes"]                  # list of dict
    teachers = data["teachers"]                # list of dict
    cconcorso = data["cconcorsopersubject"]    # subj -> {gruppo -> peso}

    model = cp_model.CpModel()

    # Variabili: per ogni (cl_idx, subj, t_idx) compatibile -> Bool
    assign = {}                                # (cl_idx, subj, t_idx) -> Bool
    for ci, cl in enumerate(classes):
        for subj in cl["subjects"]:
            for ti, t in enumerate(teachers):
                if t["group"] in cconcorso.get(subj, {}):
                    assign[(ci, subj, ti)] = model.NewBoolVar(
                        f"a_{ci}_{subj}_{ti}"
                    )

    # Vincolo hard: ogni (classe, materia) ha esattamente 1 docente.
    for ci, cl in enumerate(classes):
        for subj in cl["subjects"]:
            keys = [
                assign[(ci, subj, ti)]
                for ti, t in enumerate(teachers)
                if (ci, subj, ti) in assign
            ]
            if not keys:
                raise RuntimeError(
                    f"Nessun docente compatibile per "
                    f"classe={cl['name']} materia={subj}"
                )
            model.Add(sum(keys) == 1)

    # actual_hours[ti] = sum di ore-cattedra assegnate al docente ti.
    actual_hours = []
    for ti, t in enumerate(teachers):
        terms = []
        for (ci, subj, tj), var in assign.items():
            if tj != ti:
                continue
            ore = classes[ci]["subjects"][subj]
            terms.append(ore * var)
        ah = model.NewIntVar(0, t["max_hours"], f"ah_{ti}")
        model.Add(ah == sum(terms))
        actual_hours.append(ah)

    # Soft 1: minimizza l'ORE-DOCENTE NON UTILIZZATE.
    # Notazione: tutte le ore di tutte le materie di tutte le classi
    # sono coperte HARD (vedi vincolo "sum(keys) == 1" sopra). Il
    # valore qui sotto e\` solo lo "spreco" lato docente (capacita\`
    # contrattuale max_hours non assegnata). E\` accettabile che
    # singoli docenti finiscano con cattedra parziale; minimizziamo
    # solo per non lasciare in piedi docenti totalmente vuoti.
    unused_capacity = model.NewIntVar(0, 100000, "unused_capacity")
    model.Add(
        unused_capacity
        == sum(
            t["max_hours"] - actual_hours[ti]
            for ti, t in enumerate(teachers)
        )
    )

    # Soft 2: numero classi distinte per docente.
    has_class = {}                             # (ti, ci) -> Bool
    for ti, _ in enumerate(teachers):
        for ci, cl in enumerate(classes):
            keys = [
                assign[(ci, subj, ti)]
                for subj in cl["subjects"]
                if (ci, subj, ti) in assign
            ]
            if not keys:
                continue
            b = model.NewBoolVar(f"hc_{ti}_{ci}")
            model.AddMaxEquality(b, keys)      # b == OR(keys)
            has_class[(ti, ci)] = b

    n_classes_per_teacher = []
    for ti in range(len(teachers)):
        rel = [b for (tt, ci), b in has_class.items() if tt == ti]
        n = model.NewIntVar(0, len(classes), f"nclass_{ti}")
        if rel:
            model.Add(n == sum(rel))
        else:
            model.Add(n == 0)
        n_classes_per_teacher.append(n)

    fewclasses = model.NewIntVar(0, 100000, "fewclasses")
    model.Add(fewclasses == sum(n_classes_per_teacher))

    # Soft 3: numero indirizzi (curriculum top-level) distinti per docente.
    curricula_top = sorted({cl["curriculum"].split("_")[0] for cl in classes})
    cur_idx = {c: i for i, c in enumerate(curricula_top)}
    has_curr = {}
    for ti, _ in enumerate(teachers):
        for ci, cl in enumerate(classes):
            top = cl["curriculum"].split("_")[0]
            keys = [
                assign[(ci, subj, ti)]
                for subj in cl["subjects"]
                if (ci, subj, ti) in assign
            ]
            if not keys:
                continue
            # Aggrega sul curriculum top: definiamo solo dopo
            has_curr.setdefault((ti, top), [])
            has_curr[(ti, top)].extend(keys)

    n_curr_per_teacher = []
    for ti in range(len(teachers)):
        rel_bools = []
        for top in curricula_top:
            keys = has_curr.get((ti, top), [])
            if not keys:
                continue
            b = model.NewBoolVar(f"hcurr_{ti}_{cur_idx[top]}")
            model.AddMaxEquality(b, keys)
            rel_bools.append(b)
        n = model.NewIntVar(0, len(curricula_top), f"ncurr_{ti}")
        if rel_bools:
            model.Add(n == sum(rel_bools))
        else:
            model.Add(n == 0)
        n_curr_per_teacher.append(n)

    manycurricula = model.NewIntVar(0, 100000, "manycurricula")
    model.Add(manycurricula == sum(n_curr_per_teacher))

    # SOFT (workload balance, A-B): minimizza n_under_18 e n_under_10.
    # Vincoli A: massimo 10% docenti con cattedra < 18 ore.
    # Vincoli B: massimo 3% docenti con cattedra < 10 ore.
    n_under_18_terms = []
    n_under_10_terms = []
    for ti, t in enumerate(teachers):
        ah = actual_hours[ti]
        is_under_18 = model.NewBoolVar(f"u18_{ti}")
        model.Add(ah < 18).OnlyEnforceIf(is_under_18)
        model.Add(ah >= 18).OnlyEnforceIf(is_under_18.Not())
        n_under_18_terms.append(is_under_18)
        is_under_10 = model.NewBoolVar(f"u10_{ti}")
        model.Add(ah < 10).OnlyEnforceIf(is_under_10)
        model.Add(ah >= 10).OnlyEnforceIf(is_under_10.Not())
        n_under_10_terms.append(is_under_10)
    n_under_18 = model.NewIntVar(0, len(teachers), "n_under_18")
    n_under_10 = model.NewIntVar(0, len(teachers), "n_under_10")
    if n_under_18_terms:
        model.Add(n_under_18 == sum(n_under_18_terms))
        model.Add(n_under_10 == sum(n_under_10_terms))
    else:
        model.Add(n_under_18 == 0)
        model.Add(n_under_10 == 0)

    # Objective: spezzettamento + varieta\` indirizzi + workload
    # balance. Pesi tarati empiricamente.
    W_UNUSED = 50
    W_FEW = 100
    W_MANY = 5
    W_UNDER18 = 5_000           # alto ma non hard
    W_UNDER10 = 50_000          # molto alto: quasi-hard
    objective = (
        W_UNUSED * unused_capacity
        + W_FEW * fewclasses
        - W_MANY * manycurricula
        + W_UNDER18 * n_under_18
        + W_UNDER10 * n_under_10
    )
    model.Minimize(objective)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = workers
    solver.parameters.log_search_progress = log
    solver.parameters.linearization_level = 2
    solver.parameters.cp_model_probing_level = 2

    t0 = time.time()
    status = solver.Solve(model)
    elapsed = time.time() - t0
    print(f"\n[assignment] status={solver.StatusName(status)} elapsed={elapsed:.1f}s")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("Nessuna soluzione trovata.")
    print(
        f"[assignment] objective={solver.ObjectiveValue():.0f} "
        f"unused_capacity={solver.Value(unused_capacity)} "
        f"fewclasses={solver.Value(fewclasses)} "
        f"manycurricula={solver.Value(manycurricula)} "
        f"under18={solver.Value(n_under_18)} "
        f"under10={solver.Value(n_under_10)}"
    )

    # Estrai la soluzione
    cattedre = {}        # teacher_name -> {class_name -> {subj -> ore}}
    for (ci, subj, ti), var in assign.items():
        if solver.Value(var) == 1:
            tname = teachers[ti]["name"]
            cname = classes[ci]["name"]
            ore = classes[ci]["subjects"][subj]
            cattedre.setdefault(tname, {}).setdefault(cname, {})[subj] = ore

    # Sanity check HARD: tutte le coppie (cl, subj) coperte.
    expected_pairs = sum(len(cl["subjects"]) for cl in classes)
    assigned_pairs = sum(
        len(sm) for c in cattedre.values() for sm in c.values()
    )
    expected_hours = sum(
        h for cl in classes for h in cl["subjects"].values()
    )
    assigned_hours = sum(
        h for c in cattedre.values() for sm in c.values()
        for h in sm.values()
    )
    print(
        f"[assignment] HARD coverage check: "
        f"{assigned_pairs}/{expected_pairs} (cl,subj) coperte, "
        f"{assigned_hours}/{expected_hours} ore-classe coperte "
        f"-> {'OK' if assigned_pairs == expected_pairs else 'FAIL'}"
    )
    if assigned_pairs != expected_pairs or assigned_hours != expected_hours:
        raise RuntimeError(
            "Hard constraint violato: alcune cattedre non coperte"
        )

    # Statistica soft: distribuzione "ore docente non utilizzate"
    pool_total = sum(t["max_hours"] for t in teachers)
    used = sum(
        sum(sm.values()) for c in cattedre.values() for sm in c.values()
    )
    unused = pool_total - used
    n_active = len([t for t in teachers if t["name"] in cattedre])
    n_idle = len(teachers) - n_active
    print(
        f"[assignment] pool docenti: {pool_total} ore disponibili, "
        f"{used} utilizzate, {unused} non utilizzate "
        f"({100.0 * unused / pool_total:.1f}% spreco) | "
        f"docenti attivi: {n_active}/{len(teachers)} "
        f"(idle={n_idle})"
    )
    # Distribuzione cattedra per docente (vincoli A-B)
    distrib = {"<10": 0, "10-17": 0, ">=18": 0}
    n_total = len(teachers)
    for ti, t in enumerate(teachers):
        ah = solver.Value(actual_hours[ti])
        if ah < 10:
            distrib["<10"] += 1
        elif ah < 18:
            distrib["10-17"] += 1
        else:
            distrib[">=18"] += 1
    pct = {k: 100.0 * v / n_total for k, v in distrib.items()}
    print(
        f"[assignment] cattedra distribution: "
        f"<10h: {distrib['<10']} ({pct['<10']:.1f}%), "
        f"10-17h: {distrib['10-17']} ({pct['10-17']:.1f}%), "
        f">=18h: {distrib['>=18']} ({pct['>=18']:.1f}%) "
        f"-- vincolo A (>=90% >= 18): "
        f"{'OK' if pct['>=18'] >= 90 else 'VIOL ' + str(round(100 - pct['>=18'], 1)) + '%'}, "
        f"B (<= 3% < 10): "
        f"{'OK' if pct['<10'] <= 3 else 'VIOL ' + str(round(pct['<10'], 1)) + '%'}"
    )
    return cattedre, solver, status


def to_profs_pkl(cattedre, teachers, day_map):
    """Converte nel formato di profs.pkl atteso da prog4.py / cpsat_v2_timetable.

    profs[name] = {'classi': {cl: {subj: {'ore': N}}}, 'glibero': [d1,d2,d3]}
    """
    import random
    rng = random.Random(123)
    days_indices = list(range(1, 7))
    out = {}
    for t in teachers:
        n = t["name"]
        if n not in cattedre:
            continue                  # docente "scartato" senza cattedre
        first = day_map.get(t["free_day"], 1)
        candidates = [d for d in days_indices if d != first]
        rng.shuffle(candidates)
        glibero = [first, candidates[0], candidates[1]]
        classi = {}
        for cname, subjmap in cattedre[n].items():
            classi[cname] = {s: {"ore": ore} for s, ore in subjmap.items()}
        out[n] = {"classi": classi, "glibero": glibero}
    return out


DAY_MAP = {
    "Monday": 1, "Tuesday": 2, "Wednesday": 3,
    "Thursday": 4, "Friday": 5, "Saturday": 6,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--school", default="school_big.pkl")
    parser.add_argument("--time", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", default=None,
                        help="output profs_<profile>.pkl, "
                        "default in cwd dello script")
    parser.add_argument("--no-log", action="store_true")
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    school_path = (
        args.school if os.path.isabs(args.school)
        else os.path.join(here, args.school)
    )
    print(f"[assignment] loading {school_path}")
    data = load_school(school_path)
    print(
        f"[assignment] {len(data['classes'])} classi, "
        f"{len(data['teachers'])} docenti"
    )

    cattedre, solver, status = solve_assignment(
        data,
        time_limit_s=args.time,
        workers=args.workers,
        log=not args.no_log,
    )

    profs = to_profs_pkl(cattedre, data["teachers"], DAY_MAP)
    out = args.out or os.path.join(
        here, f"profs_{data.get('profile', 'mock')}.pkl"
    )
    with open(out, "wb") as f:
        pickle.dump(profs, f)
    print(f"[assignment] scritto {out} ({len(profs)} docenti effettivi)")

    # Statistiche di sanita\`
    n_pairs = sum(len(p["classi"]) for p in profs.values())
    print(f"[assignment] coppie (prof,classe) = {n_pairs}")
    print(
        f"[assignment] coppie (prof,cl,subj) = "
        f"{sum(len(s) for p in profs.values() for s in p['classi'].values())}"
    )


if __name__ == "__main__":
    main()
