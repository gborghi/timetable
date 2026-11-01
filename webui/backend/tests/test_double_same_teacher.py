"""H_A del validatore (regola di Giovanni, 31/10): la doppia di Mat/Ita
basta che sia con lo stesso docente, non serve la stessa materia."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
for p in (os.path.join(REPO_ROOT, "webui"), os.path.join(REPO_ROOT, "engine"),
          REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import metaheuristics as meta  # noqa: E402

P = {"I": {"classi": {"1A": {"Italiano": {"ore": 2}, "Storia": {"ore": 2}}}}}
CF = {"1A": {"dual_math": False, "motorie_pairs": False,
             "exit_after_12": False, "entry_at_8": False,
             "no_holes": False}}


def _sol(lessons):
    return {("I", "1A", s, d, h): 1 for s, d, h in lessons}


def _ok(lessons):
    return meta.is_hard_feasible(_sol(lessons), P, verbose=True,
                                 class_flags=CF)


def test_italiano_storia_consecutive_is_valid_double():
    d0, d1, d2 = meta.DAYS[:3]
    h = meta.HOURS
    assert _ok([("Italiano", d0, h[0]), ("Storia", d0, h[1]),
                ("Italiano", d1, h[0]), ("Storia", d2, h[0])])


def test_no_consecutive_hours_of_teacher_is_invalid():
    d0, d1, d2, d3 = meta.DAYS[:4]
    h = meta.HOURS
    assert not _ok([("Italiano", d0, h[0]), ("Storia", d1, h[0]),
                    ("Italiano", d2, h[0]), ("Storia", d3, h[0])])


# --- Fase A e modello settimanale allineati (Giovanni 31/10, «allinea») ---

def test_phase_a_pragma_counts_teacher_across_subjects():
    """Ita 2 + Storia 2 dello stesso docente, al massimo 1 ora di ciascuna
    materia al giorno: la regola per docente e' soddisfatta con Ita + Sto
    nello stesso giorno; la vecchia regola per cattedra sarebbe infeasible."""
    from ortools.sat.python import cp_model
    import dsl_to_cpsat as d2c
    model = cp_model.CpModel()
    days = list(range(1, 7))
    dc = {}
    for s in ("Ita", "Sto"):
        for d in days:
            dc[("I", "1A", s, d)] = model.NewIntVar(0, 1, f"dc_{s}_{d}")
        model.Add(sum(dc[("I", "1A", s, d)] for d in days) == 2)
    comp = d2c.DSLConstraintCompiler(model, slot={}, day_count=dc,
                                     level="phase_a")
    comp.compile('teacher_class_day_count_pair("I", "1A", 2)')
    cs = cp_model.CpSolver()
    cs.parameters.num_search_workers = 1
    assert cs.Solve(model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert max(sum(cs.Value(dc[("I", "1A", s, d)]) for s in ("Ita", "Sto"))
               for d in days) >= 2
    assert d2c.PRAGMA_LEVEL["teacher_class_day_count_pair"] == "phase_a"


def test_phase_a_emits_teacher_rule_once_per_teacher_class():
    import cpsat_v2_timetable as cv2
    profs = {"I": {"classi": {"1A": {"Italiano": {"ore": 4},
                                     "Matematica": {"ore": 3}}}}}
    keys = [("I", "1A", s, d) for s in ("Italiano", "Matematica")
            for d in range(1, 7)]
    prags = cv2.build_phase_a_pragmas(
        profs, ["1A"], cl_day_load_classes=["1A"],
        triples_by_prof={"I": [("1A", "Italiano"), ("1A", "Matematica")]},
        day_count_keys=keys)
    pair = [p for p in prags if "day_count_pair" in p]
    assert pair == ["teacher_class_day_count_pair('I', '1A', 2, 'Italiano', 'Matematica')"], prags


def test_general_dsl_teacher_class_day_count_pair():
    import general_dsl as g
    w = {"lessons": [
        {"teacher": "I", "class": "1A", "subject": "Ita", "day": 1},
        {"teacher": "I", "class": "1A", "subject": "Sto", "day": 1}]}
    assert g._eval_teacher_class_day_count_pair(w, "I", "1A", 2)
    w["lessons"][1]["day"] = 2
    assert not g._eval_teacher_class_day_count_pair(w, "I", "1A", 2)


def test_week_model_accepts_cross_subject_double():
    """Modello settimanale: docente con Ita 2 + Storia 2 e al massimo 1 ora
    di Italiano al giorno. Con la regola per cattedra era infeasible; ora la
    doppia Ita + Sto basta, e il validatore accetta la soluzione."""
    from ortools.sat.python import cp_model
    import cp_sat_constraint_model as csm
    P = {"I": {"classi": {"1A": {"Italiano": {"ore": 2},
                                 "Storia": {"ore": 2}}}}}
    cfg = csm.ConstraintConfig(enforce_no_holes=False,
                               enforce_h3_presence_at_11=False,
                               enforce_motorie_pair=False,
                               enforce_math_italian_pair=True, locks=[])
    s = csm.MonolithicSolver(P, dc_value=None, config=cfg, scope=None)
    s.add_all_hard_constraints()
    for d in meta.DAYS:
        s.model.Add(sum(v for k, v in s.slot.items()
                        if k[2] == "Italiano" and k[3] == d) <= 1)
    cs = cp_model.CpSolver()
    cs.parameters.max_time_in_seconds = 20
    cs.parameters.num_workers = 4
    st = cs.Solve(s.model)
    assert st in (cp_model.OPTIMAL, cp_model.FEASIBLE), cs.StatusName(st)
    sol = {k: 1 for k, v in s.slot.items() if cs.Value(v)}
    assert meta.is_hard_feasible(sol, P, verbose=True, class_flags=CF)


def test_phase_b_pairs_every_math_teacher_in_class():
    """Fase B: due docenti di Matematica nella stessa classe (Kepler, GRAVE
    31/10). Anche il secondo docente, con 2 ore quel giorno, deve averle
    consecutive: forzarle staccate rende il giorno infeasible."""
    from ortools.sat.python import cp_model
    import cpsat_v2_timetable as cv2
    profs = {"A": {"classi": {"1A": {"Matematica": {"ore": 2}}}},
             "B": {"classi": {"1A": {"Matematica": {"ore": 2}}}}}
    day = cv2.DAYS[0]
    H = list(cv2.HOURS)

    def build(force_split):
        m = cp_model.CpModel()
        slot = {(p, "1A", "Matematica", h): m.NewBoolVar(f"{p}{h}")
                for p in profs for h in H}
        for p in profs:
            m.Add(sum(slot[(p, "1A", "Matematica", h)] for h in H) == 2)
        for h in H:
            m.Add(sum(slot[(p, "1A", "Matematica", h)] for p in profs) <= 1)
        dc = {(p, "1A", "Matematica", day): 2 for p in profs}
        cv2.add_consecutive_constraints_phase_b(m, slot, day, profs, dc)
        if force_split:
            for p in ("B",):
                for i in range(len(H) - 1):
                    m.AddBoolOr([slot[(p, "1A", "Matematica", H[i])].Not(),
                                 slot[(p, "1A", "Matematica", H[i + 1])].Not()])
        cs = cp_model.CpSolver()
        cs.parameters.num_workers = 1
        return cs.Solve(m)

    assert build(False) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    # solo B staccato: prima del fix B non era vincolato
    assert build(True) == cp_model.INFEASIBLE


# --- Regola per (docente, classe) su materie di tutta la classe, come
# dato del preset (Giovanni 01/11) ---

import pytest  # noqa: E402
import double_lesson_rule as dlr  # noqa: E402

CF2 = {"1A": {"motorie_pairs": False, "exit_after_12": False,
              "entry_at_8": False, "no_holes": False}}


@pytest.fixture(autouse=True)
def _reset_rule():
    dlr.set_rule(None)
    yield
    dlr.set_rule(None)


def _feas(P, lessons, **kw):
    sol = {(p, "1A", s, d, h): 1 for p, s, d, h in lessons}
    return meta.is_hard_feasible(sol, P, verbose=True, class_flags=CF2, **kw)


def _D(i):
    return meta.DAYS[i]


def _H(i):
    return meta.HOURS[i]


def test_mat_1h_plus_potenziamento_1h_needs_double():
    P = {"M": {"classi": {"1A": {"Matematica": {"ore": 1},
                                 "Potenziamento matematica": {"ore": 1}}}}}
    split = [("M", "Matematica", _D(0), _H(0)),
             ("M", "Potenziamento matematica", _D(1), _H(0))]
    pair = [("M", "Matematica", _D(0), _H(0)),
            ("M", "Potenziamento matematica", _D(0), _H(1))]
    assert not _feas(P, split)
    assert _feas(P, pair)


def test_group_subject_not_counted():
    # Religione e' di gruppo: non entra ne' nella soglia ne' nella doppia.
    P = {"I": {"classi": {"1A": {"Italiano": {"ore": 1},
                                 "Religione": {"ore": 1, "gruppo": True}}}}}
    assert _feas(P, [("I", "Italiano", _D(0), _H(0)),
                     ("I", "Religione", _D(1), _H(0))])  # 1 h: niente doppia
    P2 = {"I": {"classi": {"1A": {"Italiano": {"ore": 2},
                                  "Religione": {"ore": 1, "gruppo": True}}}}}
    # Ita + Religione consecutive non e' una doppia valida.
    assert not _feas(P2, [("I", "Italiano", _D(0), _H(0)),
                          ("I", "Religione", _D(0), _H(1)),
                          ("I", "Italiano", _D(1), _H(0))])
    # Gruppo dichiarato via parallel_groups (senza flag nei profs).
    P3 = {"I": {"classi": {"1A": {"Italiano": {"ore": 2},
                                  "Laboratorio": {"ore": 1}}}}}
    pg = [{"group_id": 1, "class_name": "1A",
           "members": [{"teacher_name": "I", "subject": "Laboratorio"}]}]
    les = [("I", "Italiano", _D(0), _H(0)), ("I", "Laboratorio", _D(0), _H(1)),
           ("I", "Italiano", _D(1), _H(0))]
    assert _feas(P3, les)
    assert not _feas(P3, les, parallel_groups=pg)


def test_config_disabled_and_extra_trigger_change_constraints():
    import cpsat_v2_timetable as cv2
    P = {"F": {"classi": {"1A": {"Fisica": {"ore": 2}}}}}
    split = [("F", "Fisica", _D(0), _H(0)), ("F", "Fisica", _D(1), _H(0))]
    keys = [("F", "1A", "Fisica", d) for d in range(1, 7)]

    def prags():
        return [p for p in cv2.build_phase_a_pragmas(
            P, ["1A"], cl_day_load_classes=["1A"],
            triples_by_prof={"F": [("1A", "Fisica")]}, day_count_keys=keys)
            if "day_count_pair" in p]
    # default: Fisica non e' trigger
    assert _feas(P, split) and prags() == []
    dlr.set_rule({"trigger_subjects": ["Matematica", "Italiano", "Fisica"]})
    assert not _feas(P, split)
    assert prags() == ["teacher_class_day_count_pair('F', '1A', 2, 'Fisica')"]
    # regola spenta: niente vincolo per Ita
    PI = {"I": {"classi": {"1A": {"Italiano": {"ore": 2}}}}}
    spl = [("I", "Italiano", _D(0), _H(0)), ("I", "Italiano", _D(1), _H(0))]
    dlr.set_rule(None)
    assert not _feas(PI, spl)
    dlr.set_rule({"enabled": False})
    assert _feas(PI, spl)
    # soglia alzata a 3: 2 ore non bastano a far scattare la regola
    dlr.set_rule({"min_hours": 3})
    assert _feas(PI, spl)


def test_config_drives_week_model():
    from ortools.sat.python import cp_model
    import cp_sat_constraint_model as csm
    P = {"F": {"classi": {"1A": {"Fisica": {"ore": 2}}}}}

    def status():
        cfg = csm.ConstraintConfig(enforce_no_holes=False,
                                   enforce_h3_presence_at_11=False,
                                   enforce_motorie_pair=False,
                                   enforce_math_italian_pair=True, locks=[])
        s = csm.MonolithicSolver(P, dc_value=None, config=cfg, scope=None)
        s.add_all_hard_constraints()
        for d in meta.DAYS:  # al massimo 1 ora al giorno
            s.model.Add(sum(v for k, v in s.slot.items() if k[3] == d) <= 1)
        cs = cp_model.CpSolver()
        cs.parameters.num_workers = 1
        return cs.Solve(s.model)
    assert status() in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    dlr.set_rule({"trigger_subjects": ["Fisica"]})
    assert status() == cp_model.INFEASIBLE


# --- Revisione Kepler di 91d2d6a: G1, G2, M2 ---

def test_g1_alternativa_only_in_parallel_groups_same_in_all_parts():
    """Esempio di Kepler: Alternativa dichiarata solo in parallel_groups,
    senza flag nei profs. Fase A, Fase B, modello settimanale e validatore
    devono escluderla tutti."""
    import copy
    import cpsat_v2_timetable as cv2
    base = {"I": {"classi": {"1A": {"Italiano": {"ore": 2},
                                    "Alternativa": {"ore": 1}}}}}
    pg = [{"group_id": 1, "class_name": "1A",
           "members": [{"teacher_name": "I", "subject": "Alternativa"}]}]
    dlr.set_rule({"excluded_subjects": []})  # solo il gruppo deve escludere
    P = copy.deepcopy(base)
    dlr.mark_groups(P, pg)
    keys = [("I", "1A", s, d) for s in ("Italiano", "Alternativa")
            for d in range(1, 7)]
    prags = [p for p in cv2.build_phase_a_pragmas(
        P, ["1A"], cl_day_load_classes=["1A"],
        triples_by_prof={"I": [("1A", "Italiano"), ("1A", "Alternativa")]},
        day_count_keys=keys) if "day_count_pair" in p]
    assert prags == ["teacher_class_day_count_pair('I', '1A', 2, 'Italiano')"]
    les = [("I", "Italiano", _D(0), _H(0)), ("I", "Alternativa", _D(0), _H(1)),
           ("I", "Italiano", _D(1), _H(0))]
    # validatore: parallel_groups su profs senza flag -> stesso risultato
    assert not _feas(copy.deepcopy(base), les, parallel_groups=pg)
    # Fase B: Ita 1 + Alternativa 1 nello stesso giorno non fa scattare
    # la coppia (Alternativa non contata).
    from ortools.sat.python import cp_model
    m = cp_model.CpModel()
    H = list(cv2.HOURS)
    slot = {("I", "1A", s, h): m.NewBoolVar(f"{s}{h}")
            for s in ("Italiano", "Alternativa") for h in H}
    dc = {("I", "1A", "Italiano", _D(0)): 1,
          ("I", "1A", "Alternativa", _D(0)): 1}
    m.Add(sum(slot[("I", "1A", "Italiano", h)] for h in H) == 1)
    m.Add(sum(slot[("I", "1A", "Alternativa", h)] for h in H) == 1)
    m.Add(slot[("I", "1A", "Italiano", H[0])] == 1)
    m.Add(slot[("I", "1A", "Alternativa", H[2])] == 1)
    cv2.add_consecutive_constraints_phase_b(m, slot, _D(0),
                                            copy.deepcopy(P), dc)
    cs = cp_model.CpSolver()
    assert cs.Solve(m) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_g1_week_model_uses_config_parallel_groups():
    from ortools.sat.python import cp_model
    import cp_sat_constraint_model as csm
    dlr.set_rule({"excluded_subjects": []})
    P = {"I": {"classi": {"1A": {"Italiano": {"ore": 1},
                                 "Alternativa": {"ore": 1}}}}}
    pg = [{"group_id": 1, "class_name": "1A",
           "members": [{"teacher_name": "I", "subject": "Alternativa"}]}]
    cfg = csm.ConstraintConfig(enforce_no_holes=False,
                               enforce_h3_presence_at_11=False,
                               enforce_motorie_pair=False,
                               enforce_math_italian_pair=True, locks=[])
    cfg.parallel_groups = pg
    s = csm.MonolithicSolver(P, dc_value=None, config=cfg, scope=None)
    s.add_math_italian_pair()
    assert P["I"]["classi"]["1A"]["Alternativa"].get("gruppo") is True


@pytest.mark.parametrize("name", [
    "IRC", "Religione cattolica", "Religione", "Mat. alternativa",
    "Materia alternativa", "Attività alternativa", "Sostegno (AD01)",
    "AD01", "sostegno", "SOSTEGNO"])
def test_g2_excluded_names(name):
    assert dlr.is_excluded_name(name)
    assert not dlr.is_whole_class(name, {"ore": 1})


@pytest.mark.parametrize("name", [
    "Italiano", "Matematica", "Storia", "Elettrotecnica circuiti",
    "Fisica", "Potenziamento matematica"])
def test_g2_whole_class_names_kept(name):
    assert dlr.is_whole_class(name, {"ore": 1})


def test_g2_exclusions_configurable():
    dlr.set_rule({"excluded_subjects": ["Storia"]})
    assert not dlr.is_whole_class("Storia dell'arte", {"ore": 1})
    assert dlr.is_whole_class("IRC", {"ore": 1})


def test_m2_declared_pair_honors_preset():
    """Percorso pairing (subject_pair_exists): soglia min_hours ed
    esclusioni del preset, in Fase A e Fase B."""
    import cpsat_v2_timetable as cv2
    from ortools.sat.python import cp_model
    P = {"F": {"classi": {"1A": {"Fisica": {"ore": 2},
                                 "IRC": {"ore": 1}}}}}
    keys = [("F", "1A", s, d) for s in ("Fisica", "IRC") for d in range(1, 7)]
    pairing = {("1A", "Fisica"): "pair_exists"}

    def prags():
        return [p for p in cv2.build_phase_a_pragmas(
            P, ["1A"], cl_day_load_classes=["1A"],
            triples_by_prof={"F": [("1A", "Fisica"), ("1A", "IRC")]},
            day_count_keys=keys, pairing=pairing) if "day_count_pair" in p]
    assert prags() == ["teacher_class_day_count_pair('F', '1A', 2, 'Fisica')"]

    def phase_b_split_feasible():
        m = cp_model.CpModel()
        H = list(cv2.HOURS)
        slot = {("F", "1A", "Fisica", h): m.NewBoolVar(f"f{h}") for h in H}
        m.Add(sum(slot.values()) == 2)
        for i in range(len(H) - 1):
            m.AddBoolOr([slot[("F", "1A", "Fisica", H[i])].Not(),
                         slot[("F", "1A", "Fisica", H[i + 1])].Not()])
        cv2.add_consecutive_constraints_phase_b(
            m, slot, _D(0), P, {("F", "1A", "Fisica", _D(0)): 2},
            pairing=pairing)
        return cp_model.CpSolver().Solve(m) in (cp_model.OPTIMAL,
                                                cp_model.FEASIBLE)
    assert not phase_b_split_feasible()
    dlr.set_rule({"min_hours": 3})  # Fisica 2 h (IRC escluso) < 3
    assert prags() == []
    assert phase_b_split_feasible()


def test_two_teachers_consecutive_never_a_double_in_all_parts():
    """Giovanni 01/11: «la doppia si conta sul singolo docente non su due
    docenti assieme». Due ore consecutive di due docenti diversi nella
    stessa classe (Mat A + Mat B, o Mat + Ita) non sono mai una doppia."""
    from ortools.sat.python import cp_model
    import cp_sat_constraint_model as csm
    import cpsat_v2_timetable as cv2
    for sb in ("Matematica", "Italiano"):
        P = {"A": {"classi": {"1A": {"Matematica": {"ore": 2}}}},
             "B": {"classi": {"1A": {sb: {"ore": 2}}}}}
        H = list(cv2.HOURS)
        # validatore: A e B alternati, nessuno con ore proprie consecutive
        les = [("A", "Matematica", _D(0), _H(0)), ("B", sb, _D(0), _H(1)),
               ("A", "Matematica", _D(0), _H(2)), ("B", sb, _D(0), _H(3))]
        assert not _feas(P, les)
        # Fase A: un pragma per singolo docente
        keys = [(p, "1A", s, d) for p, s in (("A", "Matematica"), ("B", sb))
                for d in range(1, 7)]
        prags = [p for p in cv2.build_phase_a_pragmas(
            P, ["1A"], cl_day_load_classes=["1A"],
            triples_by_prof={"A": [("1A", "Matematica")], "B": [("1A", sb)]},
            day_count_keys=keys) if "day_count_pair" in p]
        assert sorted(prags) == [
            "teacher_class_day_count_pair('A', '1A', 2, 'Matematica')",
            f"teacher_class_day_count_pair('B', '1A', 2, '{sb}')"]
        # Fase B: alternanza A,B,A,B forzata -> infeasible
        m = cp_model.CpModel()
        slot = {(p, "1A", s, h): m.NewBoolVar(f"{p}{h}")
                for p, s in (("A", "Matematica"), ("B", sb)) for h in H}
        for i, (p, s) in enumerate([("A", "Matematica"), ("B", sb),
                                    ("A", "Matematica"), ("B", sb)]):
            m.Add(slot[(p, "1A", s, H[i])] == 1)
        m.Add(sum(slot[("A", "1A", "Matematica", h)] for h in H) == 2)
        m.Add(sum(slot[("B", "1A", sb, h)] for h in H) == 2)
        dc = {("A", "1A", "Matematica", _D(0)): 2, ("B", "1A", sb, _D(0)): 2}
        cv2.add_consecutive_constraints_phase_b(m, slot, _D(0), P, dc)
        assert cp_model.CpSolver().Solve(m) == cp_model.INFEASIBLE
        # modello settimanale: nessun docente con ore proprie consecutive
        cfg = csm.ConstraintConfig(enforce_no_holes=False,
                                   enforce_h3_presence_at_11=False,
                                   enforce_motorie_pair=False,
                                   enforce_math_italian_pair=True, locks=[])
        s = csm.MonolithicSolver(P, dc_value=None, config=cfg, scope=None)
        s.add_all_hard_constraints()
        for d in meta.DAYS:
            for p in ("A", "B"):
                vs = [v for k, v in sorted(s.slot.items())
                      if k[0] == p and k[3] == d]
                for i in range(len(vs) - 1):
                    s.model.AddBoolOr([vs[i].Not(), vs[i + 1].Not()])
        cs = cp_model.CpSolver()
        cs.parameters.num_workers = 1
        assert cs.Solve(s.model) == cp_model.INFEASIBLE
