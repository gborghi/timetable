r"""Orario settimanale v2 -- proof of concept con decomposizione in 2 fasi.

INPUT: profs_<profile>.pkl, lo stesso schema di schedule/profs.pkl:
   profs[name] = {
     'classi': {classe: {materia: {'ore': N}}},
     'glibero': [d1, d2, d3]   # giorni 1..6, in ordine di preferenza
   }

USCITA: solution_timetable_v2.pkl con dict
   (prof, classe, materia, day, hour) -> 0/1

DECOMPOSIZIONE
==============
PHASE A (giorno):
    var int day_count[(prof, cl, subj, day)] in [0, max_per_day]
    sum_d = ore-cattedra
    no overlap prof per (prof, day): sum_{cl,subj} day_count <= 6
    no overlap classe per (cl, day): sum_{prof,subj} day_count <= 6
    "no holes" della classe non puo\` essere imposto qui (e\` sui buchi
    intra-giornalieri); ma possiamo gia\` imporre numero di ore al
    giorno della classe = somma_subj day_count[*,cl,*,d] e
    metterlo tra min e max di una "giornata scuola tipica" (4..6).
    Giorno libero del prof: day_count[(prof,*,*,free_day)] == 0,
    con free_day scelto fra 3 candidati (Bool choice).

PHASE B (slot orario):
    Dato day_count fissato, per ogni giorno costruisci slot 8..13.
    var bool slot[(prof, cl, subj, hour)] per ogni triple "presente
    quel giorno", con hour in 8..13.
    sum_h slot == day_count[*,*,*,d] (ora fissato).
    no overlap prof e classe (gia\` per giorno).
    no holes della classe: la presenza per ora e\` non crescente,
    e l'ora 8 e\` occupata.
    consecutive Matematica/Scienzemotorie: in qualche giorno coppia.
    max 2 ore della stessa cattedra in un giorno (gia\` da day_count
    + slot e\` un duplicato; ma utile come bound).

PERCHE\` SCALA MEGLIO
====================
- Phase A ha ~ N_triples * 6 IntVar di range piccolo. Per ~400 triples
  -> ~2400 IntVar. Niente reified pattern, niente quadratiche.
- Phase B si risolve **per giorno**, indipendentemente. Per ogni
  giorno: ~400 / 6 = ~70 triple presenti (in media), con 6 slot
  ciascuna -> ~420 Bool. Banale.

Usa solo la variabile globale "day libero" (3-way choice) e l'objective
delle "buche prof" come penalita\` di ricomposizione fra fasi.

Le penalita\` originali quadratiche di "uniform_class" e "uniform_prof"
sono sostituite con **somma di deviazioni assolute**.

USO:
    cd experiments
    python cpsat_v2_timetable.py --profs profs_big.pkl \
        --time-a 30 --time-b 30
"""
import argparse
import os
import pickle
import time
from collections import defaultdict

from ortools.sat.python import cp_model


DAYS = list(range(1, 7))                       # 1..6
HOURS = list(range(8, 14))                     # 8..13 (6 ore)
MAX_PER_DAY_TRIPLE = 2                         # max 2 ore al giorno per cattedra
MAX_PER_DAY_PROF_CL = 3                        # max 3 ore al giorno (prof, classe)
DAY_HOURS_MIN = 4                              # almeno 4 ore al giorno per classe
DAY_HOURS_MAX = 6                              # max 6 (= len HOURS)
MAX_PROF_HOURS_PER_DAY = 5                     # HARD (C): max 5 ore prof/giorno


def find_prof_subject(profs, cl, subject):
    r"""Ritorna il nome del docente che insegna `subject` in `cl`,
    o None se non esiste in questa classe."""
    for p, info in profs.items():
        if cl in info["classi"] and subject in info["classi"][cl]:
            return p
    return None


def add_consecutive_constraints_phase_b(model, slot, day, profs, dc_value):
    r"""Aggiunge i vincoli HARD su Phase B per quel giorno:
      A) per ogni classe, se il prof di Mat/Ita ha >= 2 ore quel
         giorno (sommate su tutte le materie), almeno una coppia
         di slot consecutivi deve essere occupata da quel prof in
         quella classe.
      B) per ogni classe, se il prof di Scienzemotorie ha 2 ore
         quel giorno (Phase A garantisce {0, 2}), devono essere
         consecutive.
    """
    classes_in_day = {k[1] for k in slot.keys()}
    for cl in classes_in_day:
        for subject, mode in [
            ("Matematica", "pair_exists"),
            ("Italiano", "pair_exists"),
            ("Scienzemotorie", "must_pair"),
        ]:
            p = find_prof_subject(profs, cl, subject)
            if p is None or cl not in profs[p]["classi"]:
                continue
            subjs_of_p = list(profs[p]["classi"][cl].keys())
            # Skip se questo prof non ha slot in questo stage
            # (e\` schedulato altrove). Il vincolo verra\` applicato
            # nello stage in cui il prof e\` modellato.
            has_slots = any(
                (p, cl, s, h) in slot
                for s in subjs_of_p
                for h in HOURS
            )
            if not has_slots:
                continue
            day_count_total = sum(
                dc_value.get((p, cl, s, day), 0) for s in subjs_of_p
            )
            if mode == "must_pair" and day_count_total != 2:
                continue
            if mode == "pair_exists" and day_count_total < 2:
                continue
            # Build presence for prof p in class cl per hour
            presence = []
            for h in HOURS:
                keys = [
                    slot[(p, cl, s, h)]
                    for s in subjs_of_p
                    if (p, cl, s, h) in slot
                ]
                pr = model.NewBoolVar(
                    f"pr_{subject[:3]}_{p}_{cl}_{day}_{h}"
                )
                if keys:
                    model.AddMaxEquality(pr, keys)
                else:
                    model.Add(pr == 0)
                presence.append(pr)
            # Pairs for adjacent hours
            pairs = []
            for hi in range(len(HOURS) - 1):
                pair = model.NewBoolVar(
                    f"pair_{subject[:3]}_{p}_{cl}_{day}_{hi}"
                )
                model.AddBoolAnd(
                    [presence[hi], presence[hi + 1]]
                ).OnlyEnforceIf(pair)
                model.AddBoolOr(
                    [presence[hi].Not(), presence[hi + 1].Not()]
                ).OnlyEnforceIf(pair.Not())
                pairs.append(pair)
            if pairs:
                model.AddBoolOr(pairs)


def load_profs(path):
    with open(path, "rb") as f:
        return pickle.load(f)


def build_indices(profs):
    classes = sorted({c for p in profs for c in profs[p]["classi"]})
    triples = []                               # (prof, cl, subj, ore)
    for p, info in profs.items():
        for cl, subjmap in info["classi"].items():
            for subj, meta in subjmap.items():
                triples.append((p, cl, subj, meta["ore"]))
    class_profs = defaultdict(set)
    for p, info in profs.items():
        for cl in info["classi"]:
            class_profs[cl].add(p)
    return classes, triples, class_profs


# -----------------------------
# PHASE A: assegnazione GIORNO
# -----------------------------
def solve_phase_a(profs, classes, triples, class_profs,
                  time_limit=30, workers=8, log=True):
    model = cp_model.CpModel()

    # Variabili int [0..MAX_PER_DAY_TRIPLE]
    day_count = {}                             # (prof, cl, subj, day) -> IntVar
    for (p, cl, subj, ore) in triples:
        for d in DAYS:
            day_count[(p, cl, subj, d)] = model.NewIntVar(
                0, min(MAX_PER_DAY_TRIPLE, ore),
                f"dc_{p}_{cl}_{subj}_{d}"
            )
        # somma settimanale = ore richieste
        model.Add(
            sum(day_count[(p, cl, subj, d)] for d in DAYS) == ore
        )

    # Per (prof, cl, day): max MAX_PER_DAY_PROF_CL
    triples_by_prof_cl = defaultdict(list)
    for (p, cl, subj, ore) in triples:
        triples_by_prof_cl[(p, cl)].append((subj, ore))
    for (p, cl), lst in triples_by_prof_cl.items():
        for d in DAYS:
            model.Add(
                sum(day_count[(p, cl, s, d)] for s, _ in lst)
                <= MAX_PER_DAY_PROF_CL
            )

    # Per (prof, day): no overlap fra classi.
    # E\` un upper bound: nello stesso slot orario un prof puo\`
    # avere al massimo 1 lezione, ma in un GIORNO puo\` averne
    # fino a len(HOURS).
    triples_by_prof = defaultdict(list)
    for (p, cl, subj, ore) in triples:
        triples_by_prof[p].append((cl, subj))
    for p, lst in triples_by_prof.items():
        for d in DAYS:
            model.Add(
                sum(day_count[(p, cl, s, d)] for cl, s in lst)
                <= len(HOURS)
            )

    # Per (cl, day): vincoli HARD aggiornati (richiesta Giovanni).
    # cl_day_load[cl, d] e\` il numero di ore di lezione della classe
    # cl nel giorno d. Vincoli imposti:
    #   (HARD-2) "uscita non prima delle 12:00" => sotto no-holes,
    #            ogni giornata con lezione ha >= 4 ore. Quindi
    #            cl_day_load >= 4 oppure == 0.
    #   (HARD-1) "se classe > 24 ore settimanali, no day = 3" =>
    #            ridondante con (HARD-2): {0, [4, max]} esclude 3.
    #   Equivalenza pratica: cl_day_load in {0, 4, 5, 6}.
    triples_by_cl = defaultdict(list)
    for (p, cl, subj, ore) in triples:
        triples_by_cl[cl].append((p, subj))
    cl_day_load = {}
    for cl, lst in triples_by_cl.items():
        for d in DAYS:
            load = model.NewIntVar(0, len(HOURS), f"load_{cl}_{d}")
            model.Add(
                load == sum(day_count[(p, cl, s, d)] for p, s in lst)
            )
            cl_day_load[(cl, d)] = load
            # Vincolo HARD: load in {0, 4, 5, 6}. Esclude 1, 2, 3.
            model.AddAllowedAssignments([load], [(0,), (4,), (5,), (6,)])

    # SOFT (4): minimizziamo il totale degli slot di 6^a ora occupati
    # nella scuola, cioe\` il numero di (cl, d) con load == 6.
    sixth_hour_inds = []
    for cl in classes:
        for d in DAYS:
            load = cl_day_load[(cl, d)]
            is6 = model.NewBoolVar(f"is6_{cl}_{d}")
            model.Add(load == 6).OnlyEnforceIf(is6)
            model.Add(load != 6).OnlyEnforceIf(is6.Not())
            sixth_hour_inds.append(is6)
    n_sixth_hour = model.NewIntVar(
        0, len(classes) * len(DAYS), "n_sixth_hour"
    )
    if sixth_hour_inds:
        model.Add(n_sixth_hour == sum(sixth_hour_inds))
    else:
        model.Add(n_sixth_hour == 0)

    # vincolo settimanale: sum_d load = ore curriculum totali della classe
    ore_per_classe = defaultdict(int)
    for (p, cl, subj, ore) in triples:
        ore_per_classe[cl] += ore
    for cl in classes:
        model.Add(
            sum(cl_day_load[(cl, d)] for d in DAYS) == ore_per_classe[cl]
        )

    # Giorno libero del prof: scegli 1 fra 3 candidati (in glibero)
    glib_choice = {}                           # (prof, k=0/1/2) -> Bool
    for p, info in profs.items():
        glibero = info.get("glibero", [])
        if not glibero:
            continue
        choices = [
            model.NewBoolVar(f"glib_{p}_{k}") for k in range(3)
        ]
        model.Add(sum(choices) == 1)
        # symmetry break: il primo candidato e\` premiato (vedi obj)
        glib_choice[p] = (glibero, choices)

        # Per ogni candidato, se scelto, la somma del prof in quel
        # giorno deve essere 0
        for k, day in enumerate(glibero[:3]):
            model.Add(
                sum(day_count[(p, cl, s, day)]
                    for cl, s in triples_by_prof[p]) == 0
            ).OnlyEnforceIf(choices[k])

    # Penalita\` "uniform_class" e "uniform_prof" come dev. assolute.
    # Per ogni triple (prof, cl, subj) con ore "ore", il valore atteso
    # giornaliero e\` ore/6. Ma con interi: 'ore // 6' o 'ceil'.
    # Penalita\` assoluta = sum_d |day_count - ore/6|.
    # Con ore <= 6 spesso il "perfettamente uniforme" non esiste
    # (es. ore=4 -> distribuzione [1,1,1,1,0,0]). Va bene cosi\`.
    abs_terms = []
    for (p, cl, subj, ore) in triples:
        # target diviso per 6 con floor e ceil; minimizziamo dev. da
        # questi due target -- in pratica: dev. assoluta da ore/6
        # arrotondato.
        # Per semplicita\` usiamo la deviazione massima da 1 dello
        # spread: |day_count * 6 - ore| sommato e diviso per 6
        # (intero). Mettiamolo come |day_count - target_i| dove
        # target_i in {0,1,2}. Trick standard:
        for d in DAYS:
            dv = day_count[(p, cl, subj, d)]
            # |dv*6 - ore|
            diff = model.NewIntVar(-12, 12, f"dif_{p}_{cl}_{subj}_{d}")
            model.Add(diff == dv * 6 - ore)
            ad = model.NewIntVar(0, 12, f"adif_{p}_{cl}_{subj}_{d}")
            model.AddAbsEquality(ad, diff)
            abs_terms.append(ad)
    uniform_class_pen = model.NewIntVar(0, 100000, "uclpen")
    if abs_terms:
        model.Add(uniform_class_pen == sum(abs_terms))
    else:
        model.Add(uniform_class_pen == 0)

    # Per il prof: dev assoluta del totale ore giornaliere dal target.
    prof_day_load = {}
    abs_prof_terms = []
    for p, lst in triples_by_prof.items():
        ore_tot = sum(o for (pp, cl, subj, o) in triples if pp == p)
        for d in DAYS:
            ld = model.NewIntVar(0, MAX_PROF_HOURS_PER_DAY,
                                 f"pld_{p}_{d}")
            model.Add(
                ld == sum(day_count[(p, cl, s, d)] for cl, s in lst)
            )
            # HARD (C): max 5 ore consecutive per giorno = max 5 ore
            # totali, dato che un giorno ha solo 6 slot e che la
            # sequenza prof-day non puo\` avere "buchi obbligati"
            # rispetto agli slot della classe.
            prof_day_load[(p, d)] = ld
            diff = model.NewIntVar(-30, 30, f"pdif_{p}_{d}")
            model.Add(diff == ld * 6 - ore_tot)
            ad = model.NewIntVar(0, 30, f"padif_{p}_{d}")
            model.AddAbsEquality(ad, diff)
            abs_prof_terms.append(ad)

    # HARD (A) -- Mat/Ita: per ogni classe, almeno UN giorno deve avere
    # >= 2 ore del docente (qualunque materia, ma stesso prof).
    for cl in classes:
        for subject in ("Matematica", "Italiano"):
            p = find_prof_subject(profs, cl, subject)
            if p is None:
                continue
            subjs_of_p = list(profs[p]["classi"][cl].keys())
            tot_in_cl = sum(
                profs[p]["classi"][cl][s]["ore"] for s in subjs_of_p
            )
            if tot_in_cl < 2:
                continue                # impossibile soddisfare
            # max_d sum_subj day_count[(p, cl, s, d)] >= 2
            day_sums = []
            for d in DAYS:
                ds = model.NewIntVar(
                    0, MAX_PER_DAY_PROF_CL,
                    f"dayHrs_{subject[:3]}_{p}_{cl}_{d}"
                )
                model.Add(
                    ds == sum(
                        day_count[(p, cl, s, d)] for s in subjs_of_p
                    )
                )
                day_sums.append(ds)
            mx = model.NewIntVar(
                0, MAX_PER_DAY_PROF_CL,
                f"maxDay_{subject[:3]}_{p}_{cl}"
            )
            model.AddMaxEquality(mx, day_sums)
            model.Add(mx >= 2)

    # HARD (B) -- Scienzemotorie: tutte le ore in coppie. Quindi
    # day_count[(p_mot, cl, "Scienzemotorie", d)] in {0, 2}.
    for cl in classes:
        p = find_prof_subject(profs, cl, "Scienzemotorie")
        if p is None:
            continue
        for d in DAYS:
            key = (p, cl, "Scienzemotorie", d)
            if key in day_count:
                model.AddAllowedAssignments(
                    [day_count[key]], [(0,), (2,)]
                )

    # SOFT (D) -- penalita\` per prof_day_load == 5
    # SOFT (E) -- penalita\` per prof_day_load == 1
    n_five_terms = []
    n_one_terms = []
    for p in triples_by_prof:
        for d in DAYS:
            ld = prof_day_load[(p, d)]
            is5 = model.NewBoolVar(f"is5_{p}_{d}")
            model.Add(ld == 5).OnlyEnforceIf(is5)
            model.Add(ld != 5).OnlyEnforceIf(is5.Not())
            n_five_terms.append(is5)
            is1 = model.NewBoolVar(f"is1_{p}_{d}")
            model.Add(ld == 1).OnlyEnforceIf(is1)
            model.Add(ld != 1).OnlyEnforceIf(is1.Not())
            n_one_terms.append(is1)
    n_five = model.NewIntVar(0, 100000, "n_five")
    n_one = model.NewIntVar(0, 100000, "n_one")
    if n_five_terms:
        model.Add(n_five == sum(n_five_terms))
    else:
        model.Add(n_five == 0)
    if n_one_terms:
        model.Add(n_one == sum(n_one_terms))
    else:
        model.Add(n_one == 0)

    # HARD aggiuntivo (Hall-like): per ogni (prof, day), il prof non
    # puo\` lavorare piu\` ore di quante una delle sue classi resta
    # aperta quel giorno. Sotto no-holes hard, ogni classe e\` aperta
    # da h=8 a h=8+L-1 dove L = cl_day_load[c, d]. Quindi prof_hours
    # <= max_{c che insegna} L. Senza questo bound, Phase B diventa
    # infeasible (es. prof con 6 ore in un giorno dove tutte le
    # classi che insegna hanno load=5: solo 5 slot disponibili).
    for p, lst in triples_by_prof.items():
        classes_of_p = sorted({c for c, _ in lst})
        for d in DAYS:
            # rl[c] = cl_day_load[c, d] se prof p ha lezione con c in d,
            #        0 altrimenti.
            relevant_loads = []
            for c in classes_of_p:
                subj_list = [s for (cc, s) in lst if cc == c]
                cnt_pcd = sum(
                    day_count[(p, c, s, d)] for s in subj_list
                )
                ind = model.NewBoolVar(f"ind_{p}_{c}_{d}")
                model.Add(cnt_pcd >= 1).OnlyEnforceIf(ind)
                model.Add(cnt_pcd == 0).OnlyEnforceIf(ind.Not())
                rl = model.NewIntVar(0, len(HOURS), f"rl_{p}_{c}_{d}")
                model.Add(rl == cl_day_load[(c, d)]).OnlyEnforceIf(ind)
                model.Add(rl == 0).OnlyEnforceIf(ind.Not())
                relevant_loads.append(rl)
            max_load = model.NewIntVar(0, len(HOURS), f"mlh_{p}_{d}")
            if relevant_loads:
                model.AddMaxEquality(max_load, relevant_loads)
            else:
                model.Add(max_load == 0)
            # Hall: prof_hours[p, d] <= max_load
            model.Add(prof_day_load[(p, d)] <= max_load)

    uniform_prof_pen = model.NewIntVar(0, 100000, "uppen")
    if abs_prof_terms:
        model.Add(uniform_prof_pen == sum(abs_prof_terms))
    else:
        model.Add(uniform_prof_pen == 0)

    # Penalita\` giorno libero non-primo:
    glib_pen_terms = []
    for p, (glibero, choices) in glib_choice.items():
        glib_pen_terms.append(50 * choices[1])
        glib_pen_terms.append(100 * choices[2])
    glib_pen = model.NewIntVar(0, 100000, "glibpen")
    if glib_pen_terms:
        model.Add(glib_pen == sum(glib_pen_terms))
    else:
        model.Add(glib_pen == 0)

    # Objective unico. Pesi:
    #   - uniform_class_pen / uniform_prof_pen: spalmatura ore.
    #   - glib_pen: giorno libero non-primo.
    #   - n_sixth_hour: penalita\` sulle 6e ore (richiesta Giovanni,
    #     SOFT (4)). Peso scelto per essere in scala con uniform_class
    #     (somma fra 0 e ~5000 per dataset reali).
    W_SIXTH = 50
    W_FIVE = 30                                # SOFT (D)
    W_ONE = 80                                 # SOFT (E) -- piu\` pesante
    model.Minimize(
        4 * uniform_class_pen
        + 3 * uniform_prof_pen
        + 1 * glib_pen
        + W_SIXTH * n_sixth_hour
        + W_FIVE * n_five
        + W_ONE * n_one
    )

    # Decision strategy = "lex-leader-lite" simmetria-break: forziamo
    # un ordering canonico fra triple identicamente-tipate (stesso prof,
    # stessa classe, ore uguali) ordinandole per nome. Cosi' due
    # permutazioni equivalenti di (subj1, subj2) per uno stesso (prof,
    # classe) producono lo stesso ordine di esplorazione: il solver
    # converge piu' velocemente a una scelta canonica.
    sorted_dc_vars = [
        day_count[(p, cl, subj, d)]
        for (p, cl, subj, ore) in sorted(triples,
                                         key=lambda t: (t[0], t[1], t[2]))
        for d in DAYS
    ]
    if sorted_dc_vars:
        model.AddDecisionStrategy(
            sorted_dc_vars,
            cp_model.CHOOSE_FIRST,
            cp_model.SELECT_MIN_VALUE,
        )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    solver.parameters.log_search_progress = log
    solver.parameters.linearization_level = 2
    solver.parameters.cp_model_probing_level = 2

    t0 = time.time()
    status = solver.Solve(model)
    elapsed = time.time() - t0
    print(f"\n[phaseA] status={solver.StatusName(status)} elapsed={elapsed:.1f}s")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("Phase A: nessuna soluzione")
    print(
        f"[phaseA] obj={solver.ObjectiveValue():.0f} "
        f"uniform_class={solver.Value(uniform_class_pen)} "
        f"uniform_prof={solver.Value(uniform_prof_pen)} "
        f"glib={solver.Value(glib_pen)} "
        f"n_sixth_hour={solver.Value(n_sixth_hour)} "
        f"n_five={solver.Value(n_five)} "
        f"n_one={solver.Value(n_one)}"
    )

    # Statistica HARD aggiuntive: distribuzione cl_day_load per
    # validare che (HARD-1)+(HARD-2) sono soddisfatti.
    load_distribution = defaultdict(int)
    for (cl, d), v in cl_day_load.items():
        load_distribution[solver.Value(v)] += 1
    print(
        f"[phaseA] cl_day_load distribution (cl,d): "
        + ", ".join(f"{k}={v}" for k, v in sorted(load_distribution.items()))
    )
    if any(k in (1, 2, 3) for k in load_distribution):
        print(
            f"[phaseA] WARNING: vincolo HARD violato (load 1/2/3 trovato)"
        )

    # Estrai assegnazione giornaliera
    dc_value = {
        k: solver.Value(v) for k, v in day_count.items()
    }
    return dc_value


# -----------------------------
# PHASE B: piazzamento ORE
# -----------------------------
def solve_phase_b_for_day(day, profs, classes, triples, class_profs,
                          dc_value, time_limit=10, workers=4, log=False,
                          enforce_no_holes=True):
    r"""Risolve il sotto-problema di un singolo giorno.

    Se enforce_no_holes=True (default) impone ai profili di classe la
    contiguita\` dalle 8. Se phase A ha distribuito troppo tight i
    giorni puo\` rendersi necessario rilassare questo vincolo per
    quel giorno (vedi main: fallback automatico).
    """
    model = cp_model.CpModel()
    slot = {}                                  # (p, cl, subj, h) -> Bool
    triples_active = []
    for (p, cl, subj, ore) in triples:
        cnt = dc_value[(p, cl, subj, day)]
        if cnt == 0:
            continue
        triples_active.append((p, cl, subj, cnt))
        for h in HOURS:
            slot[(p, cl, subj, h)] = model.NewBoolVar(
                f"s_{p}_{cl}_{subj}_{day}_{h}"
            )
        model.Add(
            sum(slot[(p, cl, subj, h)] for h in HOURS) == cnt
        )

    # No overlap prof
    for p in {pp for (pp, _, _, _) in triples_active}:
        for h in HOURS:
            model.Add(
                sum(slot[(p, cl, s, h)]
                    for (pp, cl, s, _) in triples_active if pp == p)
                <= 1
            )

    # No overlap classe + no holes (classe presente in slot 8 e
    # presenza non crescente).
    cls_in_day = {cl for (_, cl, _, _) in triples_active}
    present_per_class = {}
    for cl in cls_in_day:
        # presenza per ora
        present = []
        for h in HOURS:
            slot_keys = [
                slot[(p, cl, s, h)]
                for (p, cc, s, _) in triples_active if cc == cl
            ]
            pr = model.NewBoolVar(f"pr_{cl}_{day}_{h}")
            if slot_keys:
                model.AddMaxEquality(pr, slot_keys)
                model.Add(sum(slot_keys) == pr)        # sostituisce <=1
                                                        # quando pr=1
                # in realta\` "sum<=1" basta; il MaxEq + Add forzano
                # esattamente 1 quando presente.
            else:
                model.Add(pr == 0)
            present.append(pr)
        present_per_class[cl] = present
        if enforce_no_holes:
            # se la classe ha lezione, parte alle 8
            any_present = model.NewBoolVar(f"ap_{cl}_{day}")
            model.AddMaxEquality(any_present, present)
            model.Add(present[0] >= any_present)
            # non crescente
            for i in range(len(present) - 1):
                model.Add(present[i + 1] <= present[i])

        # HARD (2) "uscita non prima delle 12:00":
        # se la classe ha lezione (= cl in cls_in_day), allora la 4^a
        # ora deve essere occupata (h=11). Sotto no-holes questo e\`
        # gia\` implicato da Phase A (cl_day_load >= 4); qui lo
        # imponiamo esplicitamente per coprire anche il fallback
        # no-holes rilassato.
        if 11 in HOURS:
            h11_idx = HOURS.index(11)
            model.Add(present[h11_idx] == 1)

    # HARD (A)+(B): Mat/Ita doppia consecutiva (se >=2 ore quel
    # giorno) e Scienzemotorie sempre a coppie consecutive.
    add_consecutive_constraints_phase_b(
        model, slot, day, profs, dc_value
    )

    # SOFT (4) gia\` minimizzato in Phase A su `cl_day_load == 6`.
    # Sotto no-holes hard, il numero di present[h=13]==1 e\` esattamente
    # determinato da cl_day_load. Aggiungere una penalita\` qui non
    # cambia il valore (ridondante ma robusto).
    sixth_terms = []
    if 13 in HOURS:
        h13_idx = HOURS.index(13)
        sixth_terms = [
            present_per_class[cl][h13_idx] for cl in cls_in_day
        ]

    # SOFT (6) -- buchi del docente nella giornata, da minimizzare.
    # Per ogni prof presente in questo giorno, calcoliamo:
    #   present_p[h] = 1 sse il prof ha lezione nello slot h (qualunque
    #                  classe/materia)
    #   gap_p[h]    = 1 sse h e\` slot vuoto fra due slot occupati del
    #                  prof (= "buco interno" della sua giornata).
    # Sommiamo i gap su tutti i prof attivi e li mettiamo in objective.
    profs_in_day = sorted({p for (p, _, _, _) in triples_active})
    gap_terms = []
    for p in profs_in_day:
        # present_p per ora
        present_p = []
        for h in HOURS:
            keys = [
                slot[(p, cl, s, h)]
                for (pp, cl, s, _) in triples_active if pp == p
            ]
            if not keys:
                pp_var = model.NewConstant(0)
            else:
                pp_var = model.NewBoolVar(f"pp_{p}_{day}_{h}")
                model.AddMaxEquality(pp_var, keys)
            present_p.append(pp_var)
        # gap per slot interno: present_p[h] = 0 AND has_before AND has_after
        for hi in range(1, len(HOURS) - 1):
            earlier = present_p[:hi]
            later = present_p[hi + 1:]
            has_before = model.NewBoolVar(f"hb_{p}_{day}_{hi}")
            model.AddMaxEquality(has_before, earlier)
            has_after = model.NewBoolVar(f"ha_{p}_{day}_{hi}")
            model.AddMaxEquality(has_after, later)
            gap = model.NewBoolVar(f"gap_{p}_{day}_{hi}")
            # gap == NOT present_p[hi] AND has_before AND has_after
            model.AddBoolAnd(
                [present_p[hi].Not(), has_before, has_after]
            ).OnlyEnforceIf(gap)
            model.AddBoolOr(
                [present_p[hi], has_before.Not(), has_after.Not()]
            ).OnlyEnforceIf(gap.Not())
            gap_terms.append(gap)

    # Objective Phase B: combinazione lineare di SOFT (4) e SOFT (6).
    W_SIXTH_B = 5    # coerente con Phase A W_SIXTH=50/scalato
    W_GAP = 10       # buchi del prof: penalizzati di piu\` per slot
    obj_terms = []
    if sixth_terms:
        obj_terms.append(W_SIXTH_B * sum(sixth_terms))
    if gap_terms:
        obj_terms.append(W_GAP * sum(gap_terms))
    if obj_terms:
        model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    solver.parameters.log_search_progress = log
    solver.parameters.linearization_level = 1

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Se infeasible per via dei "no holes" stretti, segnaliamo
        # (in produzione qui andrebbe un repair che muove un'ora
        # ad altro giorno usando dc_value modificabile).
        return None, status

    out = {
        (p, cl, subj, day, h): solver.Value(slot[(p, cl, subj, h)])
        for (p, cl, subj, _) in triples_active
        for h in HOURS
    }
    return out, status


def _diagnose_phaseb_infeasibility(day, profs, triples, dc_value):
    """Stampa diagnostica per Phase B infeasible su `day`.

    Cerca le coppie (prof, day) che violano il vincolo Hall:
    prof_hours[p, d] > max(cl_day_load[c, d] : c classi insegnate
    da p quel giorno). Questo e\` il caso piu\` frequente di
    infeasibility nel modello attuale.
    """
    from collections import defaultdict as _dd
    prof_classes_day = _dd(set)        # (p, d) -> {classes}
    prof_hours_day = _dd(int)
    cl_load_day = _dd(int)
    for (p, cl, subj, ore) in triples:
        cnt = dc_value.get((p, cl, subj, day), 0)
        if cnt > 0:
            prof_classes_day[p].add(cl)
            prof_hours_day[p] += cnt
            cl_load_day[cl] += cnt
    n_violations = 0
    for p, cls in prof_classes_day.items():
        max_load = max(cl_load_day[c] for c in cls) if cls else 0
        if prof_hours_day[p] > max_load:
            n_violations += 1
            if n_violations <= 5:
                print(
                    f"  prof '{p}' day={day}: lavora "
                    f"{prof_hours_day[p]} ore in {len(cls)} classi "
                    f"con max load = {max_load} -> Hall violata"
                )
    if n_violations > 5:
        print(f"  ... e altre {n_violations - 5} violazioni Hall.")
    if n_violations == 0:
        print(f"  Nessuna violazione Hall evidente. Causa diversa "
              f"(probabile: HARD (2) e capacita\\` slot).")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profs", default="profs_big.pkl")
    parser.add_argument("--time-a", type=float, default=30.0)
    parser.add_argument("--time-b", type=float, default=10.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", default=None)
    parser.add_argument("--log", action="store_true")
    parser.add_argument(
        "--save-dc", default=None,
        help="opzionale: pickle dove salvare il dc_value (Phase A "
             "interno, assegnazione giorno) per riuso da esperimenti.",
    )
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    profs_path = (
        args.profs if os.path.isabs(args.profs)
        else os.path.join(here, args.profs)
    )
    print(f"[v2] loading {profs_path}")
    profs = load_profs(profs_path)
    classes, triples, class_profs = build_indices(profs)
    print(
        f"[v2] {len(profs)} profs, {len(classes)} classi, "
        f"{len(triples)} triples (prof,cl,subj)"
    )

    t0 = time.time()
    dc_value = solve_phase_a(
        profs, classes, triples, class_profs,
        time_limit=args.time_a, workers=args.workers, log=args.log,
    )
    elapsed_a = time.time() - t0

    print("\n[phaseB] inizio risoluzione per giorno")
    full_solution = {}
    elapsed_b = 0.0
    failed_days = []
    for d in DAYS:
        tt = time.time()
        out, status = solve_phase_b_for_day(
            d, profs, classes, triples, class_profs, dc_value,
            time_limit=args.time_b, workers=args.workers, log=args.log,
            enforce_no_holes=True,
        )
        dt = time.time() - tt
        elapsed_b += dt
        if out is None:
            # Fallback NON ammesso: il vincolo no-holes per le classi
            # e\` categorico (richiesta Giovanni). Diagnostichiamo e
            # segnaliamo le classi infeasible per quel giorno.
            print(f"[phaseB] day={d}: INFEASIBLE ({status}), no-holes "
                  f"hard non rilassabile. Diagnostica:")
            _diagnose_phaseb_infeasibility(d, profs, triples, dc_value)
            failed_days.append(d)
            continue
        full_solution.update(out)
        # statistica veloce
        nh = sum(1 for v in out.values() if v == 1)
        print(f"[phaseB] day={d}: ok in {dt:.1f}s, {nh} ore-classe occupate")
    if failed_days:
        print(
            f"\n[phaseB] FALLIMENTI ({len(failed_days)} giorni): "
            f"{failed_days}. Soluzione PARZIALE: salvo solo i giorni "
            f"completati."
        )

    elapsed_total = elapsed_a + elapsed_b
    print(
        f"\n[v2] TOTALE phaseA={elapsed_a:.1f}s phaseB={elapsed_b:.1f}s "
        f"=> {elapsed_total:.1f}s"
    )

    out = args.out or os.path.join(here, "solution_timetable_v2.pkl")
    with open(out, "wb") as f:
        pickle.dump(full_solution, f)
    print(f"[v2] scritto {out} ({len(full_solution)} celle)")

    if args.save_dc:
        dc_path = args.save_dc
        if not os.path.isabs(dc_path):
            dc_path = os.path.join(here, dc_path)
        with open(dc_path, "wb") as f:
            pickle.dump(dc_value, f)
        print(f"[v2] scritto dc_value (Phase A interno) in {dc_path}")


if __name__ == "__main__":
    main()
