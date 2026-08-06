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
    cd engine
    python cpsat_v2_timetable.py --profs profs_big.pkl \
        --time-a 30 --time-b 30
"""
import argparse
import os
import pickle
import time
from collections import defaultdict

from ortools.sat.python import cp_model

try:
    from . import solver_config as _solvercfg  # type: ignore
except ImportError:  # direct script import (no package context)
    import solver_config as _solvercfg  # type: ignore

# Tab Ore (working hours config) plumbing
# ---------------------------------------
# DAYS / HOURS / SLOTS_PER_DAY are now driven by
# ``engine.working_hours_config`` instead of being hardcoded literals,
# so the user's customisation in the Tab Ore UI propagates through to
# every solver in the pipeline. The lists are MUTATED IN PLACE on
# refresh (``_apply_working_hours_config``) so downstream modules that
# bind ``DAYS = cv2.DAYS`` keep the same list reference and see the
# new values transparently. The legacy-fallback defaults (lun..sab,
# 8..13) are bit-identical to the old hardcoded literals so existing
# tests run unchanged when the working_hours DB is empty / absent.
try:
    from . import working_hours_config as _whc  # type: ignore
except ImportError:  # direct script import (no package context)
    import working_hours_config as _whc  # type: ignore


class PhaseAError(RuntimeError):
    """Base for the two ways ``solve_phase_a`` can fail to return a
    day-count. Subclasses ``RuntimeError`` so pre-existing
    ``except RuntimeError`` handlers keep catching it."""


class PhaseAInfeasible(PhaseAError):
    """CP-SAT *proved* no day distribution exists. A caller that only
    wants the day-count as a HINT (``phase_a_mode="soft_hint"``) can
    catch this and carry on without one; a caller that needs it as
    input (``"always"``, the per-day pipeline) cannot."""


class PhaseAUnsolved(PhaseAError):
    """The solve hit the wall clock (UNKNOWN / MODEL_INVALID) without a
    solution. NOT a proof of infeasibility -- more time may suffice."""


DAYS: list[int] = list(_whc.get_days())        # default 1..6
HOURS: list[int] = list(_whc.get_hours())      # default 8..13 (6 ore)
SLOTS_PER_DAY: dict[int, int] = dict(
    _whc.get_slots_per_day_map())              # default {1:6,..,6:6}


def _apply_working_hours_config() -> None:
    """Refresh DAYS / HOURS / SLOTS_PER_DAY from
    ``working_hours_config`` (which re-reads the DB after ``reload()``).

    Lists/dicts are mutated IN PLACE so downstream module-level
    aliases (``metaheuristics.DAYS = cv2.DAYS`` etc.) keep the same
    reference and pick up the new values without a re-import.
    """
    _whc.reload()
    DAYS[:] = list(_whc.get_days())
    HOURS[:] = list(_whc.get_hours())
    SLOTS_PER_DAY.clear()
    SLOTS_PER_DAY.update(_whc.get_slots_per_day_map())


def slots_for_day(day: int) -> int:
    """Number of active slots for ``day`` (legacy day number).
    Falls back to ``len(HOURS)`` for unknown days so existing
    callers that pass a raw day number always get a sensible cap."""
    return SLOTS_PER_DAY.get(int(day), len(HOURS))


MAX_PER_DAY_TRIPLE = 2                         # max 2 ore al giorno per cattedra
MAX_PER_DAY_PROF_CL = 3                        # max 3 ore al giorno (prof, classe)
DAY_HOURS_MIN = 4                              # almeno 4 ore al giorno per classe
DAY_HOURS_MAX = 6                              # max 6 (= len HOURS)
MAX_PROF_HOURS_PER_DAY = 5                     # HARD (C): max 5 ore prof/giorno

# The seven per-class HARD invariants (finding 08b). Canonical keys, shared
# by every solver via ``class_enforces`` so the class-card toggles behave
# identically on the per-day, week (MonolithicSolver), decomposition,
# column-generation and metaheuristic paths.
CLASS_FLAG_KEYS = (
    "no_holes", "entry_at_8", "exit_after_12",
    "dual_math", "dual_italian", "motorie_pairs", "max_6_per_day",
)


def class_enforces(class_flags, cl, key, default=True) -> bool:
    """Whether a per-class HARD invariant is active for ``cl`` (08b).

    ``class_flags`` is ``{class_name -> {flag_key -> bool}}`` (from
    ``engine_io.class_flags_from_db``). A missing map, class or key falls
    back to ``default`` (the global behaviour), so every solver stays
    byte-identical for classes the school never touched.
    """
    if not class_flags:
        return default
    entry = class_flags.get(cl)
    if not entry:
        return default
    return bool(entry.get(key, default))


def _ensure_dsl_imports_available() -> None:
    """Bootstrap sys.path so ``dsl_to_cpsat`` can ``import general_dsl``
    (the engine-flat name) regardless of how the caller set up the import
    roots. ``general_dsl`` now lives in ``engine/`` next to this module; if
    the engine dir is not on sys.path the import fails. We add it here so any
    caller of ``solve_phase_a`` works without needing to set sys.path in
    tests or scripts.

    Safe and idempotent: skips when already importable.
    """
    import importlib
    import os
    import sys
    try:
        importlib.import_module("general_dsl")
        return
    except ImportError:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)


def subject_key(name) -> str:
    r"""Chiave canonica per confrontare i nomi delle materie.

    Le regole Mat/Ita/Motorie qui sotto sono scritte su letterali
    ("Scienzemotorie"), ma ogni scuola nomina le proprie materie come
    vuole: "Scienze motorie", "Scienze Motorie" e "Scienzemotorie"
    sono la stessa materia e finora erano tre materie diverse -- con
    il mancato match che falliva IN SILENZIO (find_prof_subject
    tornava None, la pragma non veniva emessa e per quella scuola la
    regola semplicemente non esisteva). Minuscole + via i caratteri
    non alfanumerici: le tre grafie collassano su una chiave sola.
    """
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def find_prof_subject_named(profs, cl, subject):
    r"""Come `find_prof_subject`, ma ritorna anche la materia con la
    grafia usata da `profs`. Chi emette una pragma DSL deve usare la
    grafia della scuola, non il letterale che ha cercato."""
    want = subject_key(subject)
    for p, info in profs.items():
        if cl not in info["classi"]:
            continue
        for s in info["classi"][cl]:
            if subject_key(s) == want:
                return p, s
    return None, None


def find_prof_subject(profs, cl, subject):
    r"""Ritorna il nome del docente che insegna `subject` in `cl`,
    o None se non esiste in questa classe. Il confronto e\` sulla
    chiave canonica (vedi `subject_key`)."""
    return find_prof_subject_named(profs, cl, subject)[0]


def add_consecutive_constraints_phase_b(model, slot, day, profs, dc_value,
                                        class_flags=None):
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
    # Per-class HARD-invariant gates (finding 08b): dual_math / dual_italian
    # / motorie_pairs. class_flags=None keeps every pair (global default).
    _pair_flag = {"Matematica": "dual_math", "Italiano": "dual_italian",
                  "Scienzemotorie": "motorie_pairs"}
    for cl in classes_in_day:
        for subject, mode in [
            ("Matematica", "pair_exists"),
            ("Italiano", "pair_exists"),
            ("Scienzemotorie", "must_pair"),
        ]:
            if not class_enforces(class_flags, cl, _pair_flag[subject], True):
                continue
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


def build_phase_a_pragmas(
    profs,
    classes,
    *,
    cl_day_load_classes,
    triples_by_prof,
    day_count_keys,
    class_flags=None,
):
    """Emit the canonical list of Phase A DSL pragmas for the given
    Phase A state. Mirrors the HARD/SOFT surface of the legacy
    ``solve_phase_a``:

      * ``class_day_load_in_day_count(cl, 0, 4, 5, 6)`` per real class
        (subset of ``classes`` with a ``cl_day_load`` IntVar after
        codoc / support / parallel-secondary / group exclusions).
      * ``hall_bound_prof_day(prof)`` for every prof with at least one
        triple in a real class -- profs whose only classes are virtual
        groups are skipped, mirroring the legacy ``only_group_classes``
        bypass.
      * ``subject_day_count_pair(t, cl, subj, 2)`` per (teacher, class,
        subject) cattedra where ``subj`` is "Matematica" or "Italiano"
        and the cattedra has at least 2 hours. Per-teacher per-subject:
        each such cattedra independently needs >=1 day with >=2 hours
        of that specific (teacher, class, subject). Replaces the
        legacy per-prof cross-subject Mat/Ita HARD block.
      * ``subject_day_count_in(cl, "Scienzemotorie", 0, 2)`` per class
        with a Scienzemotorie cattedra in ``day_count``.
      * ``teacher_day_capacity(prof, day, n)`` -- or its ``n == 0``
        form ``teacher_unavailable_day(prof, day)`` -- per restricted
        (prof, day) in ``profs[prof]["day_capacity"]``, so the HARD
        availability tables bound the day distribution.

    The returned list is a list of pragma strings ready for
    ``DSLConstraintCompiler.compile``.

    Parameters
    ----------
    profs : dict
        the same ``profs`` dict ``solve_phase_a`` consumes.
    classes : list[str]
        all classes (including ones with no real-cattedra triples).
    cl_day_load_classes : Iterable[str]
        the subset of ``classes`` that have a ``cl_day_load`` IntVar
        (after codoc / support / parallel-secondary / group
        exclusions).
    triples_by_prof : dict[str, list[tuple[str, str]]]
        prof -> list of ``(class, subject)`` (after the augmentation
        with group_assignments). Used to gate ``hall_bound_prof_day``.
    day_count_keys : Iterable[tuple[str, str, str, int]]
        the keys of the ``day_count`` IntVar dict; used to gate
        ``subject_day_count_in`` (Motorie cattedra present).
    """
    pragmas: list[str] = []
    cl_day_load_classes = set(cl_day_load_classes)
    day_count_keys = set(day_count_keys)
    # 1. cl_day_load -- one pragma per class with a cl_day_load entry.
    #    Per-class gate on max_6_per_day (finding 08b): the day-load band
    #    {0,4,5,6} caps the day at 6, so the toggle governs this pragma.
    for cl in sorted(cl_day_load_classes):
        if not class_enforces(class_flags, cl, "max_6_per_day", True):
            continue
        pragmas.append(
            f'class_day_load_in_day_count({cl!r}, 0, 4, 5, 6)'
        )
    # 2. hall_bound_prof_day -- emit per prof unless the legacy
    # ``only_group_classes`` bypass applies, which fires only when
    # ``cl_day_load_classes`` is non-empty AND none of the prof's
    # classes are in it (a prof whose only classes are virtual
    # groups). When ``cl_day_load_classes`` is empty, the legacy
    # still emits Hall (the bound becomes prof_day_load <= 0, which
    # is the desired infeasibility signal for all-sostegno classes
    # etc.).
    for p in sorted(triples_by_prof):
        classes_of_p = {cl for (cl, _s) in triples_by_prof[p]}
        if cl_day_load_classes and not (
                classes_of_p & cl_day_load_classes):
            continue
        pragmas.append(f'hall_bound_prof_day({p!r})')
    # 3. Free-day pragmas (HARD floor + SOFT priority) are now
    # emitted by ``dsl_translator.load_all_dsl_constraints`` from the
    # DB rows (Teacher.min_free_days for the HARD floor,
    # TeacherFreeDayPreference rows for the SOFT priority weights).
    # The legacy ``free_day_choice_3way`` Phase-A-only pragma was
    # bypassed by the cpsat_week / cpsat_day_skip_phase_a /
    # cpsat_day_soft_hint techniques and is no longer emitted here;
    # the new pragmas (level=both) are honored uniformly.
    # 4. Mat/Ita ">=1 day with >=2 hours" -- per-teacher per-subject.
    # Emit one pragma per cattedra (t, cl, subj) where subj is
    # Matematica or Italiano and ore >= 2 (the per-cattedra
    # feasibility gate). Profs teaching the subject with < 2 hours
    # are skipped (the rule is infeasible for them and the legacy
    # cross-subject form is no longer the contract -- the user
    # explicit rule is "stesso prof stessa materia devono avere la
    # coppia di ore").
    _pa_pair_flag = {"Matematica": "dual_math", "Italiano": "dual_italian"}
    for cl in sorted(classes):
        for subject in ("Matematica", "Italiano"):
            if not class_enforces(class_flags, cl,
                                  _pa_pair_flag[subject], True):
                continue
            want = subject_key(subject)
            for p in sorted(profs):
                cmap = profs[p].get("classi", {}) or {}
                if cl not in cmap:
                    continue
                # Match on the canonical key, emit the school's own
                # spelling: see ``subject_key``.
                subj = next((s for s in cmap[cl]
                             if subject_key(s) == want), None)
                if subj is None:
                    continue
                ore = int(cmap[cl][subj].get("ore", 0))
                if ore < 2:
                    continue
                pragmas.append(
                    f'subject_day_count_pair({p!r}, {cl!r}, '
                    f'{subj!r}, 2)'
                )
    # 5. subject_day_count_in -- per class with a Scienzemotorie
    # cattedra in day_count, restrict daily count to {0, 2}.
    for cl in sorted(classes):
        if not class_enforces(class_flags, cl, "motorie_pairs", True):
            continue
        p, subj = find_prof_subject_named(profs, cl, "Scienzemotorie")
        if p is None:
            continue
        if not any(k[0] == p and k[1] == cl and k[2] == subj
                    for k in day_count_keys):
            continue
        pragmas.append(
            f'subject_day_count_in({cl!r}, {subj!r}, 0, 2)'
        )
    # 6. Per-(prof, day) hour ceiling from the HARD availability
    # tables: capacity = the day's configured hours minus the prof's
    # HARD unavailable ones (0 for a mandatory free day). Carried on
    # profs by ``engine_io.day_capacity_by_teacher``.
    #
    # This is the only route by which per-cell unavailability reaches
    # Phase A. The cells name an hour and Phase A has no hour
    # dimension -- but their count bounds prof_day_load, which it does
    # have. Without the bound Phase A can hand the per-day Phase B a
    # day_count no arrangement of hours can satisfy: a prof blocked
    # for 4 of 6 slots on Tuesday still got up to 6 Tuesday hours.
    for p in sorted(profs):
        caps = profs[p].get("day_capacity") or {}
        for d in sorted(caps, key=int):
            n = int(caps[d])
            if n <= 0:
                pragmas.append(f'teacher_unavailable_day({p!r}, {int(d)})')
            else:
                pragmas.append(
                    f'teacher_day_capacity({p!r}, {int(d)}, {n})')
    return pragmas


# -----------------------------
# PHASE A: assegnazione GIORNO
# -----------------------------
def solve_phase_a(profs, classes, triples, class_profs,
                  time_limit=30, workers=8, log=True,
                  locked_day_count=None,
                  coteach_groups=None,
                  support_assignments=None,
                  potenziamento_assignments=None,
                  parallel_groups=None,
                  group_assignments=None,
                  class_flags=None,
                  class_day_load_allowed=None,
                  class_free_days=None):
    """Risolve Phase A. Se `locked_day_count` e\` valorizzato, e\` un
    dict (prof, class, subject, day) -> int che impone un FLOOR sul
    numero di ore di quella cattedra nel giorno indicato. Le ore non
    coperte dai lock restano libere (il vincolo settimanale
    sum_d day_count == ore resta intatto).

    Se `coteach_groups` e\` valorizzato, e\` una lista di dict
    {class_name, subject, n_hours, teachers, required} (formato di
    engine_io.coteach_groups_for_solver). Per ogni gruppo HARD viene
    introdotta una IntVar `coday_count[g, d]` in [0, n_hours] tale
    che sum_d == n_hours, e per ogni teacher Ti del gruppo
    `day_count[(Ti, X, Y, d)] >= coday_count[g, d]`. Il valore di
    `coday_count` viene incluso nell'output dc_value cosi\` che
    Phase B sappia quante ore sono in compresenza in ciascun giorno.
    """
    model = cp_model.CpModel()
    locked_day_count = locked_day_count or {}
    coteach_groups = list(coteach_groups or [])
    support_assignments = list(support_assignments or [])
    # Support triples: (prof, class, subject) of every sostegno
    # Assignment. Used below to exclude them from cl_day_load /
    # ore_per_classe (the support hours follow the class' other
    # lessons, they don't add a fresh class-hour demand).
    support_triples_set: set[tuple[str, str, str]] = {
        (sa["teacher_name"], sa["class_name"], sa["subject"])
        for sa in support_assignments
    }
    potenziamento_assignments = list(potenziamento_assignments or [])
    parallel_groups = list(parallel_groups or [])
    # Task C3: group assignments are scheduled like normal triples
    # but with class_name = group_name (a virtual class label that
    # is NOT in `classes`). Their day_count vars get created by the
    # standard loop below; the home_class busy propagation happens
    # in Phase B via the class-busy aggregator.
    group_assignments = list(group_assignments or [])
    # Build group-augmented triples list. We keep the input `triples`
    # untouched and add the group ones at the end so downstream
    # consumers (decomposed pipelines) can pass triples without
    # group rows and have C3 still work end-to-end.
    group_triples_set: set[tuple[str, str, str]] = set()
    augmented_triples = list(triples)
    for ga in group_assignments:
        gtri = (ga["teacher_name"], ga["group_name"],
                ga["subject"], int(ga["n_hours"]))
        key = (gtri[0], gtri[1], gtri[2])
        if key in group_triples_set:
            continue
        group_triples_set.add(key)
        augmented_triples.append(gtri)
    triples = augmented_triples
    # group_triples_active: (teacher, group_name, subject) tuples used
    # below to wire home-class busy propagation.
    # parallel_subj_to_busy_key: (class_name, subject) -> stable key
    # used by Phase B's class-busy aggregator. Each parallel group's
    # members share the same key, so they count as ONE class
    # occupation. Defaults to the subject string for non-parallel.
    parallel_subj_to_busy_key: dict[tuple[str, str], str] = {}
    # parallel_secondary_triples: (teacher, class, subject) of every
    # parallel group member EXCEPT the first one; excluded from
    # cl_day_load + ore_per_classe so the class hours are counted
    # once per parallel slot (the first member contributes; the
    # others "ride along" with day_count tied via the constraint
    # below).
    parallel_secondary_triples: set[tuple[str, str, str]] = set()
    for pg in parallel_groups:
        key = f"__par__{pg['group_id']}"
        members = pg.get("members", [])
        for m in members:
            parallel_subj_to_busy_key[(pg["class_name"], m["subject"])] = key
        for m in members[1:]:
            parallel_secondary_triples.add(
                (m["teacher_name"], pg["class_name"], m["subject"]))

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

    # Lock floors: every (p, c, s, d) with locked Lessons must place
    # at least n_locked hours in that day. The solver is free to add
    # the remaining (ore - sum_d n_locked) hours where it wants.
    for (p, cl, subj, d), n_lock in locked_day_count.items():
        if n_lock <= 0:
            continue
        if (p, cl, subj, d) not in day_count:
            # Triple unknown to Phase A: skip rather than crash; the
            # caller is expected to keep the triple list consistent
            # with the lock set.
            continue
        model.Add(day_count[(p, cl, subj, d)] >= int(n_lock))

    # Shared coteaching: for each HARD group, introduce coday_count
    # IntVars and tie them to each member's day_count. Convention:
    #   members[0] is the PRINCIPAL teacher (full cattedra hours).
    #     -> day_count[principal, d] >= coday[g, d]   (the n_hours of
    #     overlap are a subset of the principal's hours).
    #   members[1:] are CO-TEACHERS (their cattedra hours are exactly
    #     the compresenza hours).
    #     -> day_count[codoc, d] == coday[g, d]
    # `coteach_codoc_triples` collects the (codoc, class, subj) keys
    # so the cl_day_load + ore_per_classe constraints below can
    # exclude them (their hours are already counted via the principal).
    coday_count_vars: dict[tuple[int, int], Any] = {}
    coteach_codoc_triples: set[tuple[str, str, str]] = set()
    for g in coteach_groups:
        if not g.get("required"):
            continue                  # SOFT not yet enforced
        gid = g["group_id"]
        gcl = g["class_name"]
        gsub = g["subject"]
        gn = int(g["n_hours"])
        gteachers = list(g["teachers"])
        # Skip groups whose triples are not in dc_value (e.g. a member
        # has zero hours scheduled). Defensive: malformed inputs.
        usable = [t for t in gteachers
                  if (t, gcl, gsub, DAYS[0]) in day_count]
        if len(usable) < 2:
            continue
        principal = usable[0]
        codocs = usable[1:]
        for d in DAYS:
            cdv = model.NewIntVar(0, gn, f"coday_{gid}_{d}")
            coday_count_vars[(gid, d)] = cdv
            model.Add(day_count[(principal, gcl, gsub, d)] >= cdv)
            for t in codocs:
                model.Add(day_count[(t, gcl, gsub, d)] == cdv)
        model.Add(sum(coday_count_vars[(gid, d)] for d in DAYS) == gn)
        for t in codocs:
            coteach_codoc_triples.add((t, gcl, gsub))

    # Parallel groups (intra-class): the n parallel Assignments
    # marciano insieme, both in number-of-hours-per-day and in
    # actual slot. Phase A: tie day_count vars; Phase B will tie
    # the slot vars and aggregate the class-busy correctly.
    for pg in parallel_groups:
        cl_name = pg["class_name"]
        members = pg.get("members", [])
        if len(members) < 2:
            continue
        m_keys = [(m["teacher_name"], cl_name, m["subject"])
                  for m in members]
        for d in DAYS:
            usable = [(t, c, s) for (t, c, s) in m_keys
                      if (t, c, s, d) in day_count]
            if len(usable) < 2:
                continue
            ref = day_count[(*usable[0], d)]
            for k in usable[1:]:
                model.Add(day_count[(*k, d)] == ref)

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
                <= slots_for_day(d)
            )

    # min_free_days HARD floor -- cross-day coordination for the per-day
    # decomposition. Each teacher must keep at least
    # ``profs[p]["min_free_days"]`` weekdays entirely free (zero day_count on
    # every cattedra that day). The monolithic/week path enforces this via
    # the DB-driven DSL free-day pragmas, but the NATIVE Phase A used by the
    # decomposition (``pre_distribute_hours`` -> ``solve_phase_a``, no DB)
    # dropped it, so a per-day-assembled week could be full-coverage yet
    # ``is_hard_feasible``-rejected because a teacher got no free day (pure
    # per-day solves cannot coordinate a cross-day count). Enforcing it HERE,
    # at the day-count stage and from the SAME ``profs["min_free_days"]`` the
    # validator reads, makes the counts reserve the free days so every
    # downstream per-day solve inherits them and the assembled week is
    # feasible. If locks/hours make it impossible, Phase A returns infeasible
    # -- an honest, coverage-visible failure rather than a silent violation.
    for p, lst in triples_by_prof.items():
        mfd = int((profs.get(p, {}) or {}).get("min_free_days", 0) or 0)
        if mfd <= 0:
            continue
        busy_days = []
        for d in DAYS:
            terms = [day_count[(p, cl, s, d)] for cl, s in lst
                     if (p, cl, s, d) in day_count]
            if not terms:
                continue
            b = model.NewBoolVar(f"busy_{p}_{d}")
            model.Add(sum(terms) >= 1).OnlyEnforceIf(b)
            model.Add(sum(terms) == 0).OnlyEnforceIf(b.Not())
            busy_days.append(b)
        if busy_days:
            model.Add(sum(busy_days) <= max(0, len(DAYS) - mfd))

    # Per (cl, day): vincoli HARD aggiornati (richiesta Giovanni).
    # cl_day_load[cl, d] e\` il numero di ore di lezione della classe
    # cl nel giorno d. Vincoli imposti:
    #   (HARD-2) "uscita non prima delle 12:00" => sotto no-holes,
    #            ogni giornata con lezione ha >= 4 ore. Quindi
    #            cl_day_load >= 4 oppure == 0.
    #   (HARD-1) "se classe > 24 ore settimanali, no day = 3" =>
    #            ridondante con (HARD-2): {0, [4, max]} esclude 3.
    #   Equivalenza pratica: cl_day_load in {0, 4, 5, 6}.
    # Codoc, SUPPORT and PARALLEL-SECONDARY triples are excluded from
    # cl_day_load: codoc hours are already counted via the principal;
    # sostegno hours follow the class' other lessons; parallel
    # members ride along with the first member.
    triples_by_cl = defaultdict(list)
    for (p, cl, subj, ore) in triples:
        if (p, cl, subj) in coteach_codoc_triples:
            continue
        if (p, cl, subj) in support_triples_set:
            continue
        if (p, cl, subj) in parallel_secondary_triples:
            continue
        if (p, cl, subj) in group_triples_set:
            continue                  # group hours not on a real class
        triples_by_cl[cl].append((p, subj))
    cl_day_load = {}
    for cl, lst in triples_by_cl.items():
        for d in DAYS:
            load = model.NewIntVar(
                0, slots_for_day(d), f"load_{cl}_{d}")
            model.Add(
                load == sum(day_count[(p, cl, s, d)] for p, s in lst)
            )
            cl_day_load[(cl, d)] = load
            # HARD ``cl_day_load in {0, 4, 5, 6}`` is added below by
            # the ``class_day_load_in_day_count`` DSL pragma; the
            # compiler's cl_day_load cache is pre-populated with this
            # IntVar so the pragma uses the same (excluded-set) load.
            # User-authored ``class_day_load_in(cl, ...)`` GeneralConstraints
            # (e.g. the year-1/2 free-day rotation: per-day load in {0,6})
            # are HARD too, but they never reached Phase A -- only the
            # monolithic week gate enforced them, so every decomposition
            # engine silently produced free-day-violating timetables. Apply
            # them directly on this IntVar's domain here, so Phase A (and
            # thus ALL decomposition schedulers that share it) honour them.
            _allow = (class_day_load_allowed or {}).get(cl)
            if _allow:
                model.AddAllowedAssignments(
                    [load], [[int(v)] for v in sorted(_allow)])

    # Class free-day FLOOR (audit F3): each class keeps at least
    # ``class_free_days[cl]`` weekdays entirely empty (load == 0). Unlike a
    # PINNED free day, WHICH day stays a solver decision -- this reserves the
    # count in the day distribution so every downstream per-day solve
    # inherits the empty day(s), and the solver optimizes which day(s) (e.g.
    # to align a biennio class' free day with its teachers' free-day
    # preferences). It is the class-level twin of the ``min_free_days``
    # teacher floor above, imposed on the same ``cl_day_load`` IntVars, so
    # every decomposition scheduler that shares this Phase A honours it. If
    # the class' total weekly hours cannot fit into the remaining days at
    # <= 6h/day, Phase A returns infeasible -- an honest, visible failure.
    for cl in classes:
        rfd = int((class_free_days or {}).get(cl, 0) or 0)
        if rfd <= 0:
            continue
        empty_days = []
        for d in DAYS:
            if (cl, d) not in cl_day_load:
                continue
            e = model.NewBoolVar(f"clfree_{cl}_{d}")
            model.Add(cl_day_load[(cl, d)] == 0).OnlyEnforceIf(e)
            model.Add(cl_day_load[(cl, d)] >= 1).OnlyEnforceIf(e.Not())
            empty_days.append(e)
        if empty_days:
            model.Add(sum(empty_days) >= rfd)

    # SOFT (4): minimizziamo il totale degli slot di 6^a ora occupati
    # nella scuola, cioe\` il numero di (cl, d) con load == 6.
    sixth_hour_inds = []
    for cl in classes:
        for d in DAYS:
            if (cl, d) not in cl_day_load:
                continue          # class has no non-support triples
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
    # Codoc + sostegno + parallel-secondary triples excluded.
    ore_per_classe = defaultdict(int)
    for (p, cl, subj, ore) in triples:
        if (p, cl, subj) in coteach_codoc_triples:
            continue
        if (p, cl, subj) in support_triples_set:
            continue
        if (p, cl, subj) in parallel_secondary_triples:
            continue
        if (p, cl, subj) in group_triples_set:
            continue                  # group hours have their own sum
        ore_per_classe[cl] += ore
    # Support triples follow the class load: per day, support hours
    # cannot exceed cl_day_load (the support teacher cannot be in
    # class on a day where the class has no lessons).
    # Task C3: a sostegno can target a StudyGroup (is_group_target);
    # in that case the bound is "<= sum of day_count of non-support
    # group triples for that group on day d" -- the prof follows the
    # student into the group lessons.
    for sa in support_assignments:
        sp = sa["teacher_name"]
        sc = sa["class_name"]
        ss = sa["subject"]
        if sa.get("is_group_target"):
            for d in DAYS:
                key = (sp, sc, ss, d)
                if key not in day_count:
                    continue
                group_day_terms = [
                    day_count[(pp, cc, ss2, d)]
                    for (pp, cc, ss2, _) in triples
                    if cc == sc
                       and (pp, cc, ss2) in group_triples_set
                       and (pp, cc, ss2) not in support_triples_set
                ]
                if not group_day_terms:
                    model.Add(day_count[key] == 0)
                else:
                    model.Add(day_count[key] <= sum(group_day_terms))
            continue
        if (sc, 1) not in cl_day_load:
            continue
        for d in DAYS:
            key = (sp, sc, ss, d)
            if key not in day_count:
                continue
            model.Add(day_count[key] <= cl_day_load[(sc, d)])
    for cl in classes:
        if (cl, 1) not in cl_day_load:
            continue           # class with no triples (degenerate)
        model.Add(
            sum(cl_day_load[(cl, d)] for d in DAYS) == ore_per_classe[cl]
        )

    # Task C3: per-day capacity for each home class. The class hours
    # (cl_day_load) plus the hours of every group touching the class
    # cannot exceed len(HOURS) on any day -- otherwise Phase B would
    # be infeasible (no room to schedule both regular lessons and
    # group lessons in the 6 available slots, and the group prevents
    # the home class from running another lesson at the group slot).
    # Sostegno on group is excluded: it shadows a non-support group
    # lesson, doesn't add a new occupied slot.
    for cl in classes:
        if (cl, 1) not in cl_day_load:
            continue
        home_group_keys = [
            (ga["teacher_name"], ga["group_name"], ga["subject"])
            for ga in group_assignments
            if cl in ga.get("home_class_names", [])
            and (ga["teacher_name"], ga["group_name"],
                  ga["subject"]) not in support_triples_set
        ]
        if not home_group_keys:
            continue
        for d in DAYS:
            group_terms = [
                day_count[(p, gcl, gs, d)]
                for (p, gcl, gs) in home_group_keys
                if (p, gcl, gs, d) in day_count
            ]
            if not group_terms:
                continue
            model.Add(
                cl_day_load[(cl, d)] + sum(group_terms)
                <= slots_for_day(d)
            )

    # Giorno libero del prof: HARD floor + SOFT priority preferences
    # are now driven by the DSL translator (load_all_dsl_constraints
    # emits teacher_at_least_n_free_days + teacher_preferred_free_day_penalty
    # pragmas that work in both Phase A and Phase B). The legacy
    # 1/2-candidate fallback that injected per-prof BoolVars directly
    # is no longer needed -- the new pragmas handle any number of
    # preferences uniformly.

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
    # Potenziamento: pot_day_count[prof, d] in [0, MAX]; the prof's
    # cattedra hours + potenziamento hours per day must not exceed
    # MAX_PROF_HOURS_PER_DAY. Stored in dc_value with key
    # ("__pot__", prof, d) for downstream consumers.
    pot_day_count_vars: dict[tuple[str, int], Any] = {}
    pot_by_prof: dict[str, int] = {}
    for pa in potenziamento_assignments:
        pot_by_prof[pa["teacher_name"]] = (
            pot_by_prof.get(pa["teacher_name"], 0) + int(pa["n_hours"]))
    for p, lst in triples_by_prof.items():
        ore_tot = sum(o for (pp, cl, subj, o) in triples if pp == p)
        for d in DAYS:
            ld = model.NewIntVar(0, MAX_PROF_HOURS_PER_DAY,
                                 f"pld_{p}_{d}")
            model.Add(
                ld == sum(day_count[(p, cl, s, d)] for cl, s in lst)
            )
            prof_day_load[(p, d)] = ld
            diff = model.NewIntVar(-30, 30, f"pdif_{p}_{d}")
            model.Add(diff == ld * 6 - ore_tot)
            ad = model.NewIntVar(0, 30, f"padif_{p}_{d}")
            model.AddAbsEquality(ad, diff)
            abs_prof_terms.append(ad)
        # Potenziamento for this prof: distribute over the 6 days.
        # cattedra ld + pot must stay within the per-day cap.
        pot_total = pot_by_prof.get(p, 0)
        if pot_total > 0:
            for d in DAYS:
                pdc = model.NewIntVar(0, MAX_PROF_HOURS_PER_DAY,
                                       f"pot_{p}_{d}")
                pot_day_count_vars[(p, d)] = pdc
                model.Add(pdc + prof_day_load[(p, d)]
                          <= MAX_PROF_HOURS_PER_DAY)
            model.Add(
                sum(pot_day_count_vars[(p, d)] for d in DAYS)
                == pot_total
            )
    # Profs that ONLY have potenziamento (no cattedra) need their
    # own pot_day_count vars without the prof_day_load coupling.
    for p, pot_total in pot_by_prof.items():
        if p in triples_by_prof:
            continue
        for d in DAYS:
            pdc = model.NewIntVar(0, MAX_PROF_HOURS_PER_DAY,
                                   f"pot_{p}_{d}")
            pot_day_count_vars[(p, d)] = pdc
        model.Add(
            sum(pot_day_count_vars[(p, d)] for d in DAYS) == pot_total
        )

    # HARD (A) Mat/Ita "≥1 day with ≥2 hours" -- compiled below by
    # the ``subject_day_count_pair`` DSL pragma. Per-teacher
    # per-subject: each (t, cl, subj) cattedra with subj in
    # {Matematica, Italiano} and ore >= 2 gets the rule independently.
    # HARD (B) Motorie {0, 2} -- compiled below by the
    # ``subject_day_count_in`` DSL pragma.

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

    # SOFT (F5) -- ranked free-day PREFERENCE at the day-count level. The
    # per-day Phase B penalty could never move a day the distribution had
    # already fixed, so first-choice satisfaction sat near chance. Here,
    # WHICH day a teacher is free is exactly what Phase A decides, so paying
    # ``weight`` when the teacher works on a preferred day steers the
    # distribution to free the top choice (weights come from
    # ``engine_io._FREE_DAY_PREF_WEIGHT`` on the profs dict; priority 1 is set
    # above the sixth-hour term so it wins unless coverage forbids it).
    freeday_pref_terms = []
    for p in triples_by_prof:
        for pref in ((profs.get(p, {}) or {}).get("free_day_prefs") or []):
            try:
                pref_day, weight = int(pref[0]), int(pref[1])
            except (TypeError, ValueError, IndexError):
                continue
            if weight <= 0 or (p, pref_day) not in prof_day_load:
                continue
            works = model.NewBoolVar(f"fdpref_{p}_{pref_day}")
            model.Add(prof_day_load[(p, pref_day)] >= 1).OnlyEnforceIf(works)
            model.Add(prof_day_load[(p, pref_day)] == 0).OnlyEnforceIf(
                works.Not())
            freeday_pref_terms.append(weight * works)
    freeday_pref_pen = model.NewIntVar(0, 100_000_000, "fdpref_pen")
    if freeday_pref_terms:
        model.Add(freeday_pref_pen == sum(freeday_pref_terms))
    else:
        model.Add(freeday_pref_pen == 0)

    # HARD Hall-like (per (prof, day): prof_day_load <= max_c
    # cl_day_load) is compiled below by the ``hall_bound_prof_day``
    # DSL pragma. The compiler's prof_day_load and cl_day_load
    # caches are pre-populated with the IntVars built above so the
    # pragma uses the same exclusion-aware loads.

    # ============================================================
    # DSL Phase A pragmas: cl_day_load {0,4,5,6}, hall_bound,
    # free_day_choice (HARD pick + soft weights), Mat/Ita pair,
    # Motorie {0, 2}. The compiler's load caches are pre-populated
    # with the IntVars built above so codoc / support /
    # parallel-secondary / group exclusions and the
    # only_group_classes Hall bypass are preserved transparently.
    # ============================================================
    _ensure_dsl_imports_available()
    try:
        from . import dsl_to_cpsat as _d2c  # type: ignore
    except ImportError:
        import dsl_to_cpsat as _d2c  # type: ignore
    _compiler = _d2c.DSLConstraintCompiler(
        model, slot={}, day_count=day_count, level="phase_a")
    # Pre-populate cl_day_load cache with the (excluded-set) IntVars.
    for (cl, d), v in cl_day_load.items():
        _compiler._cl_day_load_cache[(cl, d)] = v
    # For classes touched by day_count but excluded from cl_day_load
    # (e.g. a class with only sostegno / codoc / parallel-secondary
    # entries), force the cache entry to a constant 0. The legacy
    # Hall block treats those classes' load as 0 even when the prof
    # has lessons there; without this seed the pragma would call
    # ``_cl_day_load_intvar`` which falls back to summing raw
    # day_count, breaking the infeasibility signal for all-sostegno
    # classes.
    _zero_const = model.NewConstant(0)
    _classes_touched = {k[1] for k in day_count}
    for cl in _classes_touched:
        for d in DAYS:
            if (cl, d) not in _compiler._cl_day_load_cache:
                _compiler._cl_day_load_cache[(cl, d)] = _zero_const
    # Pre-populate prof_day_load cache so the Hall pragma re-uses the
    # IntVars above (built with the same sum-over-triples_by_prof[p]).
    for (p, d), v in prof_day_load.items():
        _compiler._prof_day_load_cache[(p, d)] = v
    cl_day_load_classes = {cl for (cl, _d) in cl_day_load.keys()}
    _pragmas = build_phase_a_pragmas(
        profs, classes,
        cl_day_load_classes=cl_day_load_classes,
        triples_by_prof={p: list(lst)
                          for p, lst in triples_by_prof.items()},
        day_count_keys=day_count.keys(),
        class_flags=class_flags,
    )
    for _src in _pragmas:
        _compiler.compile(_src)

    uniform_prof_pen = model.NewIntVar(0, 100000, "uppen")
    if abs_prof_terms:
        model.Add(uniform_prof_pen == sum(abs_prof_terms))
    else:
        model.Add(uniform_prof_pen == 0)

    # Free-day handling here: the RANKED PREFERENCE is scored above as
    # ``freeday_pref_pen`` (audit F5) -- it must live at this day-count stage
    # because that is where "which day is free" is decided; a Phase-B-only
    # penalty cannot move an already-distributed day. Phase A's pragma stream
    # (``build_phase_a_pragmas``) stays HARD-only, so
    # ``_compiler.soft_cost_terms`` is empty here. The DSL-loader twin
    # (``teacher_preferred_free_day_penalty``) still also applies at Phase B
    # (per-day via ``solve_phase_b_for_day(via_dsl=True)`` and week via
    # ``MonolithicSolver``) as a tie-breaker within the fixed distribution.

    # Objective unico. Pesi:
    #   - uniform_class_pen / uniform_prof_pen: spalmatura ore.
    #   - n_sixth_hour: penalita\` sulle 6e ore (richiesta Giovanni,
    #     SOFT (4)). Peso scelto per essere in scala con uniform_class
    #     (somma fra 0 e ~5000 per dataset reali).
    W_SIXTH = 50
    W_FIVE = 30                                # SOFT (D)
    W_ONE = 80                                 # SOFT (E) -- piu\` pesante
    model.Minimize(
        4 * uniform_class_pen
        + 3 * uniform_prof_pen
        + W_SIXTH * n_sixth_hour
        + W_FIVE * n_five
        + W_ONE * n_one
        + freeday_pref_pen          # SOFT (F5): ranked free-day preference
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
    _solvercfg.configure_solver(solver)
    status = solver.Solve(model)
    elapsed = time.time() - t0
    print(f"\n[phaseA] status={solver.StatusName(status)} elapsed={elapsed:.1f}s")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Distinguish PROVEN infeasibility from "ran out of time". CP-SAT
        # returns INFEASIBLE only when it has proved no solution exists;
        # UNKNOWN (and MODEL_INVALID) mean the solve hit the wall-clock
        # limit without finding one. Conflating the two -- the old
        # "nessuna soluzione" for every non-solved status -- made a big
        # school that merely needs more time look permanently infeasible.
        if status == cp_model.INFEASIBLE:
            if locked_day_count:
                raise PhaseAInfeasible(
                    "Phase A INFEASIBLE: i lock attivi sono incompatibili "
                    "con i vincoli correnti. Rimuovi o adatta i lock "
                    "(es. sblocca eventi nel monitor) e ritenta. "
                    f"Lock attivi: {len(locked_day_count)} cattedra-giorno."
                )
            raise PhaseAInfeasible(
                "Phase A INFEASIBLE: il modello dei conteggi-giorno non "
                "ammette soluzione con i vincoli correnti (dimostrato dal "
                "solver, non un timeout)."
            )
        # UNKNOWN / MODEL_INVALID / timeout: NOT infeasibility.
        lock_note = (
            f" ({len(locked_day_count)} lock cattedra-giorno attivi)"
            if locked_day_count else ""
        )
        raise PhaseAUnsolved(
            f"Phase A non risolta entro il tempo limite "
            f"({time_limit:.0f}s, status={solver.StatusName(status)}){lock_note}: "
            "nessuna soluzione trovata in tempo. Aumenta il time limit o "
            "riduci dimensione/tightness. NB: questo NON significa che il "
            "problema sia infeasible."
        )
    print(
        f"[phaseA] obj={solver.ObjectiveValue():.0f} "
        f"uniform_class={solver.Value(uniform_class_pen)} "
        f"uniform_prof={solver.Value(uniform_prof_pen)} "
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

    # Estrai assegnazione giornaliera. The coday_count IntVars (one
    # per shared coteaching group * day) are merged into dc_value
    # using the namespaced key ("__coday__", group_id, day) so Phase B
    # can read them without breaking the (p, cl, subj, day) -> int
    # contract for cattedra-bound entries.
    dc_value = {
        k: solver.Value(v) for k, v in day_count.items()
    }
    for (gid, d), var in coday_count_vars.items():
        dc_value[("__coday__", gid, d)] = solver.Value(var)
    for (p, d), var in pot_day_count_vars.items():
        dc_value[("__pot__", p, d)] = solver.Value(var)
    return dc_value


# -----------------------------
# PHASE B: piazzamento ORE
# -----------------------------
def build_plessi_ctx(db):
    """``(PlessiData, class_to_plesso)`` per il solver di giornata.

    Da costruire UNA volta e passare a tutte le chiamate di
    :func:`solve_phase_b_for_day`: ricostruirlo per ogni giorno vuol
    dire rileggere aule, docenti, classi e regole sei volte per niente.
    Ritorna ``None`` quando la scuola non ha plessi configurati, cosi\`
    il chiamante puo\` saltare il blocco senza casi speciali.
    """
    try:
        from . import plessi_constraints as _pc  # type: ignore
    except ImportError:
        import plessi_constraints as _pc  # type: ignore
    try:
        pl = _pc.load_plessi_data(db)
    except Exception:
        return None
    if not pl.commuting_rules and not pl.entity_policies:
        return None
    pins = _pc.class_plesso_pins(pl)
    if not pins:
        return None
    return (pl, pins)


def build_class_flags(db):
    """``{class_name -> {flag_key -> bool}}`` from SchoolClass (finding 08b),
    mirroring engine_io.class_flags_from_db so a caller that only has a db
    session (decomposition, column generation, the day fallback) can obtain
    the per-class overrides without the backend threading them. Returns
    None on any error so the solver keeps the global behaviour."""
    try:
        from backend import models  # type: ignore
    except ImportError:
        return None
    try:
        out: dict[str, dict[str, bool]] = {}
        for c in db.query(models.SchoolClass).all():
            out[c.name] = {
                "no_holes": bool(getattr(c, "hard_no_holes", True)),
                "entry_at_8": bool(getattr(c, "hard_entry_at_8", True)),
                "exit_after_12": bool(getattr(c, "hard_exit_after_12", True)),
                "dual_math": bool(getattr(c, "hard_dual_math", True)),
                "dual_italian": bool(getattr(c, "hard_dual_italian", True)),
                "motorie_pairs": bool(getattr(c, "hard_motorie_pairs", True)),
                "max_6_per_day": bool(getattr(c, "hard_max_6_per_day", True)),
            }
        return out or None
    except Exception:
        return None


def build_special_room_ctx(db):
    """``(subject_required_kind, kind_capacity)`` per il solver di giornata.

    Phase B decide l'orario prima che le aule esistano, e finora ignorava
    quante aule speciali ci sono: metteva sette classi in palestra alla
    stessa ora pur avendone due (finding 34). Nessuna assegnazione di
    aule puo' poi rimediare -- le ore sono congelate.

    `subject_required_kind`: {materia -> kind} per le sole materie con
    `required_kind` valorizzato. `kind_capacity`: {kind -> classi
    contemporanee massime} = somma di `multi_class_max` sulle aule di quel
    kind. Includiamo solo i kind con capienza >= 1 e con almeno una
    materia che li richiede: un kind senza aule e' un problema di dati che
    il preflight segnala, non qualcosa che deve rendere INFEASIBLE la
    Phase B. Ritorna ``None`` quando non c'e' nulla da vincolare, cosi' il
    chiamante salta il blocco senza casi speciali.
    """
    try:
        from backend import models  # type: ignore
    except ImportError:
        return None
    try:
        subj_kind = {
            s.name: s.required_kind
            for s in db.query(models.Subject).all()
            if getattr(s, "required_kind", None)
        }
        if not subj_kind:
            return None
        needed_kinds = set(subj_kind.values())
        kind_cap: dict[str, int] = {}
        for r in db.query(models.Classroom).all():
            k = getattr(r, "kind", None)
            if k not in needed_kinds:
                continue
            kind_cap[k] = kind_cap.get(k, 0) + int(
                getattr(r, "multi_class_max", 1) or 1)
    except Exception:
        return None
    kind_cap = {k: c for k, c in kind_cap.items() if c >= 1}
    subj_kind = {s: k for s, k in subj_kind.items() if k in kind_cap}
    if not subj_kind or not kind_cap:
        return None
    return (subj_kind, kind_cap)


def add_special_room_capacity_phase_b(model, slot, ctx, *, day=None) -> int:
    """HARD: al piu' ``kind_capacity[R]`` classi possono avere una materia
    che richiede il kind ``R`` nella stessa cella oraria (finding 34).

    ``slot`` e' la vista 5-tuple ``(teacher, class, subject, day, hour) ->
    BoolVar``. Passa ``day`` per il solver di giornata (filtra su quel
    giorno); ``day=None`` (solver settimanale monolitico) considera tutti
    i giorni, raggruppando comunque per (kind, giorno, ora).

    Contiamo l'occupazione **per (classe, cella)**, non per (docente,
    cella): una compresenza o una codocenza mette due docenti nella stessa
    cella della stessa classe, e la palestra la occupa una volta sola. Per
    ogni classe con piu' var concorrenti creiamo un indicatore OR (``occ
    >= var``); per il caso comune (una var sola) usiamo direttamente la
    var. Il vincolo si emette solo quando le classi candidate superano la
    capienza. Ritorna il numero di vincoli emessi.
    """
    subj_kind, kind_cap = ctx
    if not subj_kind or not kind_cap:
        return 0
    from collections import defaultdict
    buckets: dict[tuple[str, int, int], dict[str, list]] = defaultdict(
        lambda: defaultdict(list))
    for (p, cl, s, d, h), var in slot.items():
        if day is not None and d != day:
            continue
        r_kind = subj_kind.get(s)
        if r_kind is None or r_kind not in kind_cap:
            continue
        buckets[(r_kind, d, h)][cl].append(var)
    n = 0
    for (r_kind, d, h), per_class in buckets.items():
        cap = kind_cap[r_kind]
        if len(per_class) <= cap:
            continue  # can never exceed capacity -> no constraint needed
        occ_terms = []
        for cl, vars_ in per_class.items():
            if len(vars_) == 1:
                occ_terms.append(vars_[0])
            else:
                occ = model.NewBoolVar(f"specroom_{r_kind}_{cl}_d{d}_h{h}")
                for v in vars_:
                    model.Add(occ >= v)
                occ_terms.append(occ)
        model.Add(sum(occ_terms) <= cap)
        n += 1
    return n


def add_general_room_capacity_phase_b(model, slot, n_rooms, *,
                                      day=None, subj_kind=None) -> int:
    """HARD: at most ``n_rooms`` distinct classes may be in session in the
    same (day, hour) cell -- a school cannot seat more concurrent classes
    than it has rooms. The general-room twin of
    ``add_special_room_capacity_phase_b`` (which caps a specific ROOM KIND):
    it makes the SCHEDULE itself room-feasible per slot, so the room step can
    seat everyone instead of leaving lessons unplaced when the scheduler
    crammed more classes into a slot than there are rooms.

    ``subj_kind`` (optional, the ``{subject: required_kind}`` map): when given,
    lessons whose subject requires a special kind are EXCLUDED from the count
    -- they sit in a lab/gym, not an ordinary room, so ``n_rooms`` should be
    the STANDARD-room count and this cap then bounds only the ordinary
    (standard-seeking) load. This is what lets a class in the gym free its
    ordinary room for another class: the PE cell simply doesn't consume a
    standard seat. The special kinds keep their own per-slot caps.

    Counts per (class, cell) like the special cap, so co-teaching / codocenza
    on one class occupy one room, not two. Emitted only where the candidate
    classes exceed the cap. ``n_rooms <= 0`` disables it. Returns the number
    of constraints emitted.
    """
    if not n_rooms or int(n_rooms) <= 0:
        return 0
    cap = int(n_rooms)
    from collections import defaultdict
    buckets: dict[tuple[int, int], dict[str, list]] = defaultdict(
        lambda: defaultdict(list))
    for (p, cl, s, d, h), var in slot.items():
        if day is not None and d != day:
            continue
        if subj_kind and s in subj_kind:
            continue   # required-kind lesson -> special room, not a standard
                       # seat; don't count it against ``n_rooms``
        buckets[(d, h)][cl].append(var)
    n = 0
    for (d, h), per_class in buckets.items():
        if len(per_class) <= cap:
            continue  # can never exceed capacity -> no constraint needed
        occ_terms = []
        for cl, vars_ in per_class.items():
            if len(vars_) == 1:
                occ_terms.append(vars_[0])
            else:
                occ = model.NewBoolVar(f"genroom_{cl}_d{d}_h{h}")
                for v in vars_:
                    model.Add(occ >= v)
                occ_terms.append(occ)
        model.Add(sum(occ_terms) <= cap)
        n += 1
    return n


def solve_phase_b_for_day(day, profs, classes, triples, class_profs,
                          dc_value, time_limit=10, workers=4, log=False,
                          enforce_no_holes=True,
                          locked_slots_for_day=None,
                          coteach_groups=None,
                          support_assignments=None,
                          parallel_groups=None,
                          group_assignments=None,
                          db=None,
                          via_dsl=False,
                          extra_dsl_expressions=None,
                          dsl_hard_expressions=None,
                          return_objective=False,
                          plessi_ctx=None,
                          special_room_ctx=None,
                          class_flags=None,
                          total_room_capacity=None,
                          *,
                          lagrangian_penalties=None,
                          diagnostics_sink=None):
    r"""Risolve il sotto-problema di un singolo giorno.

    Se enforce_no_holes=True (default) impone ai profili di classe la
    contiguita\` dalle 8. Se phase A ha distribuito troppo tight i
    giorni puo\` rendersi necessario rilassare questo vincolo per
    quel giorno (vedi main: fallback automatico).

    Se `locked_slots_for_day` e\` valorizzato, e\` un iterable di
    tuple (prof, class, subject, hour) che devono valere 1 (cioe\`
    occupati). Sono i lock nativi: il solver li tratta come
    constraint e li sfrutta per potare lo spazio di ricerca.

    Se `coteach_groups` e\` valorizzato, e\` la stessa lista di dict
    passata a solve_phase_a (uno per gruppo di compresenza). Per
    ogni gruppo la cui `coday_count` per questo giorno e\` > 0 (letta
    da dc_value tramite la chiave ("__coday__", group_id, day)),
    introdurre `coslot[(g, h)]` BoolVar con somma == coday e
    legare `slot[(Ti, X, Y, h)] >= coslot[(g, h)]` per ogni teacher
    del gruppo. Il vincolo class-busy aggrega per (class, subject)
    cosi\` che gli k slot di compresenza contino UNA sola volta
    come occupazione classe.
    """
    model = cp_model.CpModel()
    slot = {}                                  # (p, cl, subj, h) -> Bool
    triples_active = []
    locked_slots_for_day = list(locked_slots_for_day or [])
    support_assignments = list(support_assignments or [])
    support_triples_set: set[tuple[str, str, str]] = {
        (sa["teacher_name"], sa["class_name"], sa["subject"])
        for sa in support_assignments
    }
    parallel_groups = list(parallel_groups or [])
    parallel_subj_to_busy_key: dict[tuple[str, str], str] = {}
    for pg in parallel_groups:
        key = f"__par__{pg['group_id']}"
        for m in pg.get("members", []):
            parallel_subj_to_busy_key[(pg["class_name"],
                                        m["subject"])] = key
    # Task C3: augment triples with group assignments (class=group_name).
    group_assignments = list(group_assignments or [])
    group_triples_set: set[tuple[str, str, str]] = set()
    augmented_triples = list(triples)
    for ga in group_assignments:
        key = (ga["teacher_name"], ga["group_name"], ga["subject"])
        if key in group_triples_set:
            continue
        group_triples_set.add(key)
        augmented_triples.append(
            (ga["teacher_name"], ga["group_name"],
             ga["subject"], int(ga["n_hours"])))
    triples = augmented_triples
    # group_home_classes: (teacher, group_name, subject) -> [home_class, ...]
    group_home_classes: dict[tuple[str, str, str], list[str]] = {}
    for ga in group_assignments:
        gkey = (ga["teacher_name"], ga["group_name"], ga["subject"])
        group_home_classes[gkey] = list(ga.get("home_class_names", []))
    for (p, cl, subj, ore) in triples:
        # Phase A output is dense (one entry per (p,cl,subj,day) over the
        # 6 days), but partial / column-generation pipelines may pass a
        # sparse dc_value that only carries non-zero hours. Treat a
        # missing key as "0 ore quel giorno" so the day-solver can
        # gracefully skip that triple instead of crashing with KeyError.
        cnt = dc_value.get((p, cl, subj, day), 0)
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
        # Tab Ore -- variable slots per day: when this day has fewer
        # active slots than ``len(HOURS)`` (e.g., SAT only has 4
        # afternoon slots while lun..ven have 6), force the surplus
        # slot vars to 0 so no lesson lands on a non-existent hour.
        n_slots = slots_for_day(day)
        if n_slots < len(HOURS):
            for h_idx in range(n_slots, len(HOURS)):
                model.Add(slot[(p, cl, subj, HOURS[h_idx])] == 0)

    # Native lock constraints: force the matching slot var to 1.
    # If the lock points at a triple Phase A produced 0 hours for, the
    # slot var doesn't exist -- skip with a warning rather than crash;
    # the caller is responsible for keeping the lock set consistent
    # with the dc_value.
    for (p, cl, subj, h) in locked_slots_for_day:
        key = (p, cl, subj, h)
        if key not in slot:
            print(f"[phaseB.day{day}] WARN locked slot {key} not in "
                  f"model (triple inactive that day); ignoring lock.")
            continue
        model.Add(slot[key] == 1)

    # Shared coteaching: introduce coslot vars and tie member slots.
    # Build a dict (class_name, subject) -> set(teacher_names)
    # to drive the class-busy aggregation later.
    coteach_groups = list(coteach_groups or [])
    coslot: dict[tuple[int, int], Any] = {}    # (group_id, hour) -> Bool
    coteach_members_by_cl_subj: dict[
        tuple[str, str], list[str]] = {}
    coteach_n_by_day: dict[int, int] = {}        # group_id -> n_hours_today
    # SOFT coteach penalty terms (finding 38): (weight, mismatch_var) pairs
    # folded into the soft objective below.
    _soft_coteach_terms: list = []
    for g in coteach_groups:
        gid = g["group_id"]
        gcl = g["class_name"]
        gsub = g["subject"]
        gteachers = list(g["teachers"])
        # Active members today: must have a slot var (i.e. dc_value > 0)
        usable = [t for t in gteachers
                  if (t, gcl, gsub, HOURS[0]) in slot]
        if len(usable) < 2:
            continue
        if not g.get("required"):
            # SOFT compresenza: don't FORCE coincidence -- pay a penalty for
            # each hour where the principal and a codoc differ on this
            # (class, subject). The DSL/week path already models this as a
            # weighted rule; this brings the native per-day path in line so a
            # 'preferibile' compresenza actually biases the solver instead of
            # being silently dropped.
            weight = int(g.get("weight", 100) or 100)
            principal = usable[0]
            for t in usable[1:]:
                for h in HOURS:
                    pk = slot[(principal, gcl, gsub, h)]
                    ck = slot[(t, gcl, gsub, h)]
                    mism = model.NewBoolVar(f"cosoft_{gid}_{t}_{day}_{h}")
                    model.Add(mism >= pk - ck)     # mism >= |pk - ck|
                    model.Add(mism >= ck - pk)
                    _soft_coteach_terms.append((weight, mism))
            continue
        n_today = int(dc_value.get(("__coday__", gid, day), 0))
        coteach_n_by_day[gid] = n_today
        if n_today == 0:
            continue
        coteach_members_by_cl_subj[(gcl, gsub)] = usable
        for h in HOURS:
            cv = model.NewBoolVar(f"co_{gid}_{day}_{h}")
            coslot[(gid, h)] = cv
            for t in usable:
                model.Add(slot[(t, gcl, gsub, h)] >= cv)
        model.Add(sum(coslot[(gid, h)] for h in HOURS) == n_today)

    # Parallel groups (intra-class): tie member slots so the n
    # parallel Assignments occupy the same hour exactly.
    for pg in parallel_groups:
        cl_name = pg["class_name"]
        members = pg.get("members", [])
        if len(members) < 2:
            continue
        m_keys = [(m["teacher_name"], cl_name, m["subject"])
                  for m in members]
        for h in HOURS:
            usable = [k for k in m_keys
                      if (k[0], k[1], k[2], h) in slot]
            if len(usable) < 2:
                continue
            ref = slot[(usable[0][0], usable[0][1], usable[0][2], h)]
            for k in usable[1:]:
                model.Add(slot[(k[0], k[1], k[2], h)] == ref)

    # No overlap prof
    for p in {pp for (pp, _, _, _) in triples_active}:
        for h in HOURS:
            model.Add(
                sum(slot[(p, cl, s, h)]
                    for (pp, cl, s, _) in triples_active if pp == p)
                <= 1
            )

    # Classe occupata: per ogni (class, subject, h), aggregare i k
    # slot dei k coteachers in un OR -- conta UNA sola occupazione
    # classe anche quando i co-docenti sono entrambi presenti
    # (compresenza). Senza compresenza, k=1 e il vincolo degenera
    # all'usuale sum<=1. Le triple di SOSTEGNO sono escluse: il
    # sostegno segue la classe (vincolo shadow sotto), non aggiunge
    # un'occupazione classe.
    # Task C3: separate "real classes" (subject to HARD-2 etc.) from
    # "virtual group classes" (no HARD-2). Real classes include any
    # home_class touched by a group active today, so the home class
    # gets the busy propagation but NOT the no-holes/HARD-2 logic
    # if it has only group hours that day.
    cls_with_direct_triples = {
        cl for (p, cl, ss, _) in triples_active
        if (p, cl, ss) not in group_triples_set
    }
    home_classes_today: set[str] = set()
    for (p, cl, ss, _) in triples_active:
        if (p, cl, ss) in group_triples_set:
            home_classes_today.update(
                group_home_classes.get((p, cl, ss), []))
    cls_in_day = cls_with_direct_triples | home_classes_today
    # Per-class overrides of the ex-officio HARD invariants (finding 08b).
    # If not passed, build from db when available (covers decomposition /
    # column-generation callers that only thread the session). A class
    # absent from the map keeps the global default, so every untouched
    # class behaves exactly as before; only a class whose toggle was turned
    # off on its card differs.
    if class_flags is None and db is not None:
        class_flags = build_class_flags(db)
    _cflags = class_flags or {}

    def _cf(cl_name: str, key: str, default: bool) -> bool:
        return bool(_cflags.get(cl_name, {}).get(key, default))

    present_per_class = {}
    pr_per_cl_h: dict[tuple[str, int], Any] = {}
    for cl in cls_in_day:
        present = []
        for h in HOURS:
            # Group slots by busy_key: parallel-group members share
            # the same key (so they count as ONE class occupation),
            # while regular subjects use the subject string itself.
            # Group hours touching this class as a home class are
            # added under a __grp__ busy_key per group.
            keys_by_busy: dict[str, list] = {}
            for (p, cc, ss, _) in triples_active:
                if cc != cl:
                    continue
                if (p, cl, ss) in support_triples_set:
                    continue
                if (p, cc, ss) in group_triples_set:
                    continue            # handled in the group loop
                bk = parallel_subj_to_busy_key.get((cl, ss), ss)
                keys_by_busy.setdefault(bk, []).append(
                    slot[(p, cl, ss, h)])
            # Add group slots for groups whose home_classes include cl.
            # Sostegno triples on a group are EXCLUDED here: the
            # support follows the lesson, doesn't add a fresh
            # class-busy slot. Same exclusion as class-target sostegno.
            for (gp, gcl, gss, _) in triples_active:
                if (gp, gcl, gss) not in group_triples_set:
                    continue
                if (gp, gcl, gss) in support_triples_set:
                    continue
                if cl not in group_home_classes.get((gp, gcl, gss), []):
                    continue
                gbk = f"__grp__{gcl}__{gss}"
                keys_by_busy.setdefault(gbk, []).append(
                    slot[(gp, gcl, gss, h)])
            subj_busy_vars = []
            for bk, keys_s in keys_by_busy.items():
                if not keys_s:
                    continue
                if len(keys_s) == 1:
                    subj_busy_vars.append(keys_s[0])
                else:
                    sb = model.NewBoolVar(
                        f"sb_{cl}_{bk}_{day}_{h}")
                    model.AddMaxEquality(sb, keys_s)
                    subj_busy_vars.append(sb)
            pr = model.NewBoolVar(f"pr_{cl}_{day}_{h}")
            if subj_busy_vars:
                model.AddMaxEquality(pr, subj_busy_vars)
                model.Add(sum(subj_busy_vars) == pr)
            else:
                model.Add(pr == 0)
            pr_per_cl_h[(cl, h)] = pr
            present.append(pr)
        present_per_class[cl] = present
        # Task C3: skip HARD-2 / no-holes for classes that ONLY have
        # group hours today (no direct triples). The group hours are
        # extras that float on top of the home class' regular slots,
        # not subject to the curriculum no-holes / 4-hours-min logic.
        if cl not in cls_with_direct_triples:
            continue
        # Per-class gates (finding 08b): `no_holes` (non-increasing
        # presence) and `entry_at_8` (first hour occupied when the class
        # has any lesson) default to the global `enforce_no_holes` so
        # untouched classes are unchanged.
        _enf_no_holes = _cf(cl, "no_holes", enforce_no_holes)
        _enf_entry8 = _cf(cl, "entry_at_8", enforce_no_holes)
        if _enf_no_holes or _enf_entry8:
            any_present = model.NewBoolVar(f"ap_{cl}_{day}")
            model.AddMaxEquality(any_present, present)
            if _enf_entry8:
                # se la classe ha lezione, parte alle 8
                model.Add(present[0] >= any_present)
            if _enf_no_holes:
                # non crescente
                for i in range(len(present) - 1):
                    model.Add(present[i + 1] <= present[i])

        # HARD (2) "uscita non prima delle 12:00":
        # se la classe ha lezione (= cl in cls_in_day), allora la 4^a
        # ora deve essere occupata (h=11). Sotto no-holes questo e\`
        # gia\` implicato da Phase A (cl_day_load >= 4); qui lo
        # imponiamo esplicitamente per coprire anche il fallback
        # no-holes rilassato. Gated per-class su `exit_after_12` (08b).
        if 11 in HOURS and _cf(cl, "exit_after_12", True):
            h11_idx = HOURS.index(11)
            model.Add(present[h11_idx] == 1)

    # Shadow (sostegno): for every support triple, the support
    # slot at h must imply the target is busy with a non-support
    # subject/lesson at h. Two flavors:
    #   - class-target: slot[sost, X, sost, h] <= pr_per_cl_h[X, h]
    #     (existing behavior; X is a real class).
    #   - group-target (Task C3): slot[sost, G, sost, h] <=
    #     OR(slot[*, G, *, h] for non-support members of G). The
    #     prof follows the student into the group lessons.
    for sa in support_assignments:
        sp = sa["teacher_name"]
        sc = sa["class_name"]
        ss = sa["subject"]
        is_group = sa.get("is_group_target", False)
        for h in HOURS:
            sk = slot.get((sp, sc, ss, h))
            if sk is None:
                continue
            if is_group:
                grp_busy_keys = [
                    slot[(p, c2, s2, h)]
                    for (p, c2, s2, _) in triples_active
                    if c2 == sc
                       and (p, c2, s2) in group_triples_set
                       and (p, c2, s2) not in support_triples_set
                ]
                if not grp_busy_keys:
                    model.Add(sk == 0)
                elif len(grp_busy_keys) == 1:
                    model.Add(sk <= grp_busy_keys[0])
                else:
                    gb = model.NewBoolVar(
                        f"grpbusy_{sc}_{day}_{h}")
                    model.AddMaxEquality(gb, grp_busy_keys)
                    model.Add(sk <= gb)
                continue
            cp = pr_per_cl_h.get((sc, h))
            if cp is None:
                model.Add(sk == 0)
            else:
                model.Add(sk <= cp)

    # HARD (A)+(B): Mat/Ita doppia consecutiva (se >=2 ore quel
    # giorno) e Scienzemotorie sempre a coppie consecutive.
    add_consecutive_constraints_phase_b(
        model, slot, day, profs, dc_value, class_flags=class_flags
    )

    # SOFT objective (B1): the structural soft cost -- SOFT (4) "sixth
    # hour at h13 (per class busy)" + SOFT (6) "teacher intra-day gaps
    # (buchi)" -- is now sourced from the DSL pragma stream instead of
    # being hand-built inline. ``dsl_translator.build_soft_pragmas(...,
    # scale_mode="phase_b_per_day")`` emits
    #   class_sixth_penalty(5, "class_busy")   (PENALTY_SIXTH_PD)
    #   teacher_buchi_penalty(10)              (PENALTY_BUCHI_PD)
    # and a per-day ``DSLConstraintCompiler`` over the 5-tuple slot view
    # compiles them into ``soft_cost_terms`` (weight, var) pairs. The
    # objective is ``sum(w*v)`` over those pairs -- value-identical to the
    # legacy ``W_SIXTH_B=5`` / ``W_GAP=10`` block it replaces. When
    # ``via_dsl=True`` the loader below adds table SOFT (free-day prefs,
    # soft unavailability, soft general/logical/coteach) onto the SAME
    # compiler with ``include_soft=True`` and re-minimizes the accumulated
    # ``soft_cost_terms`` -- the loader is the single owner of free-day
    # soft on the per-day path (sub-project B2).
    try:
        from . import dsl_to_cpsat as _d2c  # type: ignore
        from . import cp_sat_constraint_model as _csm  # type: ignore
        from . import dsl_translator as _dt  # type: ignore
    except ImportError:
        import dsl_to_cpsat as _d2c  # type: ignore
        import cp_sat_constraint_model as _csm  # type: ignore
        import dsl_translator as _dt  # type: ignore

    # 5-tuple slot view the DSL compiler expects (the 4-tuple ``slot``
    # dict is not mutated). Built unconditionally now -- the same
    # compiler is reused by the opt-in ``via_dsl`` hard-rule block below.
    slot_5 = {
        (p, cl, s, day, h): v
        for (p, cl, s, h), v in slot.items()
    }
    cfg5 = _csm.ConstraintConfig()
    compiler = _d2c.DSLConstraintCompiler(
        model, slot_5, config=cfg5,
        classroom_for_slot=None,
        plessi_data=None,
    )
    # SOFT coteach penalties (finding 38) join the soft accumulator so both
    # the initial Minimize and the via_dsl re-minimize below include them.
    if _soft_coteach_terms:
        compiler.soft_cost_terms.extend(_soft_coteach_terms)

    # ---- Lagrangian dual penalties (opt-in) ----
    # The subgradient solver (``lagrangian.run_lagrangian``) dualizes the
    # cross-cluster bridge-teacher no-overlap coupling: a bridge teacher may
    # be used by at most ONE cluster in a given (day, hour), but each cluster
    # is solved independently, so that coupling is relaxed and PRICED. For
    # every slot of a bridge teacher ``t`` at hour ``h`` we add a soft term
    # ``lambda[(t, h)] * slot`` so this cluster PAYS to occupy a contended
    # hour and the CP objective steers ``t``'s (dc_value-fixed) hours toward
    # the cheapest -- i.e. collision-free -- slots. Folding into
    # ``soft_cost_terms`` means BOTH the initial ``Minimize`` and the
    # ``via_dsl`` re-minimize price them. ``None`` (every non-Lagrangian
    # caller) leaves the objective byte-identical.
    if lagrangian_penalties:
        for (_p, _cl, _s, _h), _var in slot.items():
            _w = lagrangian_penalties.get((_p, _h))
            if _w:
                compiler.soft_cost_terms.append((int(round(_w)), _var))

    # ---- Plessi: dove sta il docente, ora per ora ----
    # `plessi_data=None` qui sopra non e\` una svista: il compiler DSL
    # ricava il plesso dall'aula, e in Phase B le aule non esistono
    # ancora. Il plesso lo sa la CLASSE (sta nella sua aula base tutta
    # la settimana), e da li\` si ricava quello del docente ora per ora.
    # Senza questo blocco il tempo di trasferimento fra plessi non
    # vincola nulla: quando la fase aule interviene le ore sono
    # congelate, e un docente messo nei due plessi a ore contigue non
    # ha piu\` nessuna assegnazione di aula che possa salvarlo.
    if plessi_ctx is None and db is not None:
        plessi_ctx = build_plessi_ctx(db)
    if plessi_ctx:
        _pl, _pins = plessi_ctx
        try:
            from . import plessi_constraints as _pc  # type: ignore
        except ImportError:
            import plessi_constraints as _pc  # type: ignore
        n_pl = _pc.add_plesso_constraints_phase_b(
            model, slot_5, _pl, day=day, hours=HOURS,
            class_to_plesso=_pins,
        )
        if log and n_pl:
            print(f"[phaseB.day{day}] plessi: {n_pl} vincoli")

    # ---- Aule speciali: quante palestre/laboratori esistono ----
    # Senza questo, la fase oraria puo' mettere piu' classi in palestra di
    # quante palestre esistano nello stesso slot; la fase aule non puo'
    # rimediare a ore congelate (finding 34). No-op se nessuna materia ha
    # `required_kind` o mancano le aule speciali.
    if special_room_ctx is None and db is not None:
        special_room_ctx = build_special_room_ctx(db)
    if special_room_ctx:
        n_sr = add_special_room_capacity_phase_b(
            model, slot_5, special_room_ctx, day=day)
        if log and n_sr:
            print(f"[phaseB.day{day}] aule speciali: {n_sr} vincoli capienza")

    # General room capacity (F4): cap the distinct classes in session per
    # slot at the total room count, so the per-day schedule the temporal
    # decomposition produces is room-feasible and the room step can seat
    # everyone. Opt-in (``total_room_capacity`` None/0 -> off, byte-identical
    # to before). If the day genuinely has more concurrent classes than rooms
    # the per-day solve returns infeasible -- an honest "add rooms / relax"
    # signal rather than a silently over-booked timetable.
    if total_room_capacity:
        # Cap the ORDINARY (standard-seeking) load only: a required-kind
        # lesson sits in its lab/gym, freeing its ordinary seat for another
        # class (the gym-sharing that lets rooms < classes). ``subj_kind``
        # comes from the special-room ctx so PE / lab hours are excluded and
        # ``total_room_capacity`` is read as the STANDARD-room count.
        _sk = special_room_ctx[0] if special_room_ctx else None
        n_gr = add_general_room_capacity_phase_b(
            model, slot_5, total_room_capacity, day=day, subj_kind=_sk)
        if log and n_gr:
            print(f"[phaseB.day{day}] capienza aule standard "
                  f"({total_room_capacity}): {n_gr} vincoli per-slot")

    _soft_classes = sorted({k[1] for k in slot})
    for _src in _dt.build_soft_pragmas(
            profs, _soft_classes, scale_mode="phase_b_per_day"):
        compiler.compile(_src)
    soft_obj = [int(w) * v for (w, v) in compiler.soft_cost_terms]
    if soft_obj:
        model.Minimize(sum(soft_obj))

    # ---- Step 4a: DSL augmentation (opt-in via via_dsl=True) ----
    # When the caller passes ``via_dsl=True`` together with a database
    # session (``db``) and/or a list of extra DSL expressions
    # (``extra_dsl_expressions``), every applicable rule is compiled
    # onto the existing model BEFORE the solver runs. The legacy
    # hardcoded path (cattedra demand, no-overlap, no-holes, motorie/
    # mat/ita pairs, locks, coteach, parallel, support, groups) is
    # untouched -- DSL rules are added on top. Slot vars used by the
    # compiler are wrapped to match its 5-tuple key convention
    # (``t, cl, s, day, h``); the existing 4-tuple ``slot`` dict is
    # not mutated.
    dsl_diagnostics: list[str] = []
    # HARD DSL expressions the CP compiler could NOT emit natively (audit
    # H6/H12). Populated by the compile pass below; drives the post-solve
    # verify + no-good refinement gate. Empty => the model already enforces
    # every hard rule (or there are none) => the byte-identical single-shot
    # solve runs unchanged.
    _noncompilable_hard: list[str] = []
    if via_dsl and (db is not None
                     or extra_dsl_expressions
                     or dsl_hard_expressions):
        try:
            # Reuse the SAME ``compiler`` (and ``slot_5``) built above for
            # the structural soft objective. HARD DSL rules add constraints
            # only; SOFT rules append weighted terms to
            # ``compiler.soft_cost_terms`` and the objective is re-minimized
            # over the full accumulator after the loop (see below).
            # Pull DB-side rules through the unified loader.
            if db is not None:
                try:
                    # B2: load SOFT rows too (free-day prefs, soft
                    # unavailability, soft general/logical/coteach). The
                    # loader is now the single owner of the free-day soft
                    # on the per-day path. Each rule carries its own
                    # ``is_hard``/``weight``; we toggle the shared
                    # compiler's mode per rule so SOFT rows compile to
                    # weighted ``soft_cost_terms`` (summed by the objective
                    # set above) instead of being promoted to HARD.
                    rules = _dt.load_all_dsl_constraints(
                        db, include_soft=True)
                    _saved_hard = compiler.is_hard
                    _saved_w = compiler.soft_weight
                    try:
                        for r in rules:
                            compiler.is_hard = bool(r.get("is_hard", True))
                            compiler.soft_weight = int(
                                r.get("weight", 0) or 0)
                            try:
                                compiler.compile(r["expression"])
                            except Exception as exc:  # noqa: BLE001
                                dsl_diagnostics.append(
                                    f"compile_failed:{r.get('label', '')}:"
                                    f"{type(exc).__name__}:{exc}")
                    finally:
                        compiler.is_hard = _saved_hard
                        compiler.soft_weight = _saved_w
                except Exception as exc:  # noqa: BLE001
                    dsl_diagnostics.append(
                        f"db_load_failed:{type(exc).__name__}:{exc}")

            # In-memory extras (e.g. seed pragmas the caller pre-built).
            for expr in (extra_dsl_expressions or []):
                try:
                    compiler.compile(expr)
                except Exception as exc:  # noqa: BLE001
                    dsl_diagnostics.append(
                        f"compile_failed_extra:{type(exc).__name__}:{exc}")

            # HARD DSL rules to ENFORCE via the post-solve gate (audit
            # H6/H12). Compile each onto the model (compilable fragment ->
            # native constraints) AND detect which ones the compiler could
            # not fully emit, by watching the compiler diagnostics grow. A
            # rule that raises or adds a diagnostic is non-compilable: the
            # model does NOT enforce it, so it must be verified + no-good
            # refined after the solve. Compilable hard rules are already
            # native constraints -> no gate round is ever spent on them
            # (this keeps the single-shot path byte-identical when every
            # hard rule compiles). Dedup against ``extra_dsl_expressions``
            # so a caller passing the same list twice does not double-add
            # the constraints; the shared rule is still probed for
            # compilability on a throwaway model so it is gated if needed.
            _already = set(extra_dsl_expressions or [])

            def _is_noncompilable(_expr: str) -> bool:
                """True if the compiler cannot fully emit ``_expr``.

                Compiles onto a THROWAWAY model over the current slot keys
                (never touches the real model) and reports whether any
                diagnostic was produced or an exception raised.
                """
                try:
                    _pm = cp_model.CpModel()
                    _ps = {k: _pm.NewBoolVar(f"probe_{i}")
                           for i, k in enumerate(slot_5.keys())}
                    _pc = _d2c.DSLConstraintCompiler(
                        _pm, _ps, config=_csm.ConstraintConfig(),
                        classroom_for_slot=None, plessi_data=None)
                    _pc.compile(_expr)
                    return len(_pc.diagnostics) > 0
                except Exception:  # noqa: BLE001 - unparseable => non-compilable
                    return True

            for expr in (dsl_hard_expressions or []):
                if expr not in _already:
                    _before = len(compiler.diagnostics)
                    _sh, _sw = compiler.is_hard, compiler.soft_weight
                    compiler.is_hard, compiler.soft_weight = True, 0
                    try:
                        compiler.compile(expr)
                        if len(compiler.diagnostics) > _before:
                            _noncompilable_hard.append(expr)
                    except Exception as exc:  # noqa: BLE001
                        _noncompilable_hard.append(expr)
                        dsl_diagnostics.append(
                            f"compile_failed_hard:{type(exc).__name__}:{exc}")
                    finally:
                        compiler.is_hard, compiler.soft_weight = _sh, _sw
                elif _is_noncompilable(expr):
                    _noncompilable_hard.append(expr)

            # B2: SOFT DSL rows (and any soft extras) may have appended new
            # (weight, var) pairs to ``compiler.soft_cost_terms`` after the
            # structural-soft objective was set above. CP-SAT's
            # ``Minimize`` replaces the objective, and the term list is a
            # superset of the structural terms, so re-minimizing the full
            # accumulator folds the new SOFT contributions in without
            # double-counting the structural ones.
            _soft_now = [int(w) * v
                         for (w, v) in compiler.soft_cost_terms]
            if _soft_now:
                model.Minimize(sum(_soft_now))

            dsl_diagnostics.extend(compiler.diagnostics)
            if log and dsl_diagnostics:
                print(f"[phaseB.day{day}] DSL diagnostics: "
                      f"{len(dsl_diagnostics)} note(s)")
        except Exception as exc:  # noqa: BLE001
            # The DSL pipeline is opt-in; never let its failures
            # break the proven legacy path.
            dsl_diagnostics.append(
                f"dsl_augmentation_failed:{type(exc).__name__}:{exc}")
            if log:
                print(f"[phaseB.day{day}] WARN dsl_augmentation_failed: "
                      f"{exc}")

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    solver.parameters.log_search_progress = log
    solver.parameters.linearization_level = 1

    _solvercfg.configure_solver(solver)

    # ---- DSL HARD-rule refinement gate (audit H6/H12) ----
    # When at least one hard DSL rule could NOT be compiled natively, the
    # model does not enforce it. Mirror the proven week path
    # (dsl_cp_gate.solve_with_dsl_refinement): solve -> verify the
    # non-compilable hard rules on the produced day -> if any violated and
    # budget remains, forbid the exact assignment (no-good) and re-solve.
    # Only the non-compilable rules are verified: compilable ones are
    # already native constraints, so re-checking them is redundant AND a
    # day-projected re-check of a compiled rule could disagree with the
    # compiler and spend a wasted round. Adding no-goods to THIS model and
    # re-solving is sound: unlike MonolithicSolver.build() the model here
    # is built once and only grown between solves.
    _gate_active = bool(via_dsl and _noncompilable_hard)
    if _gate_active:
        try:
            from . import dsl_cp_gate as _gate  # type: ignore
        except ImportError:
            import dsl_cp_gate as _gate  # type: ignore
        _max_iters = 8
        _unsatisfied: list[str] = []
        _uncertifiable = False
        status = None
        for _it in range(_max_iters):
            status = solver.Solve(model)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                _unsatisfied = []              # no solution: handled below
                break                          # infeasible: give up
            _produced = {
                (p, cl, subj, day, h): solver.Value(slot[(p, cl, subj, h)])
                for (p, cl, subj, _) in triples_active
                for h in HOURS
            }
            _violated, _unverifiable = _gate.screen_dsl_hard(
                _produced, profs, _noncompilable_hard, day=day)
            if _unverifiable:
                # HARD rule neither compiled natively nor certifiable by the
                # evaluator (unparseable / eval raised): a no-good cannot fix
                # it. Stop and fail closed (audit H6 residual) instead of
                # silently shipping it.
                _unsatisfied = _unverifiable + _violated
                _uncertifiable = True
                break
            _unsatisfied = _violated
            if not _unsatisfied:
                break                                  # fully compliant
            _gate.add_nogood(model, slot_5, _produced)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) and _unsatisfied:
            # Either budget exhausted with violations still standing, or an
            # uncertifiable HARD rule. Respect PITANTUM_DSL_GATE_STRICT
            # (same semantics as the week gate): strict (default) fails
            # closed -- a day whose HARD DSL cannot be satisfied returns no
            # solution, so the run degrades exactly like a genuine
            # infeasibility (coverage drops, not activated). STRICT=0 keeps
            # the last (violating) solution for inspection; is_hard_feasible
            # still refuses to activate it.
            _reason = "uncertifiable" if _uncertifiable else "exhausted"
            dsl_diagnostics.extend(
                "compile_failed:" + e + ":refinement:" + _reason
                for e in _unsatisfied)
            _strict = os.environ.get(
                "PITANTUM_DSL_GATE_STRICT", "1"
            ).strip().lower() not in ("0", "false", "no", "off")
            if log:
                _why = ("regola/e HARD non certificabile/i"
                        if _uncertifiable else "budget esaurito,")
                print(f"[phaseB.day{day}] DSL gate: {_why} "
                      f"{len(_unsatisfied)} regola/e HARD non soddisfatta/e"
                      + (" -> fail-closed" if _strict else
                         " -> keep-partial"))
            if _strict:
                if diagnostics_sink is not None:
                    diagnostics_sink.extend(dsl_diagnostics)
                if return_objective:
                    return None, status, None
                return None, status
    else:
        status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Se infeasible per via dei "no holes" stretti, segnaliamo
        # (in produzione qui andrebbe un repair che muove un'ora
        # ad altro giorno usando dc_value modificabile).
        if diagnostics_sink is not None:
            diagnostics_sink.extend(dsl_diagnostics)
        if return_objective:
            return None, status, None
        return None, status

    out = {
        (p, cl, subj, day, h): solver.Value(slot[(p, cl, subj, h)])
        for (p, cl, subj, _) in triples_active
        for h in HOURS
    }
    if diagnostics_sink is not None:
        diagnostics_sink.extend(dsl_diagnostics)
    if return_objective:
        # Only meaningful when the model has an objective (soft_obj
        # non-empty). When the model is a pure feasibility problem
        # ObjectiveValue() is 0.0; expose it as an int for the caller.
        return out, status, int(round(solver.ObjectiveValue()))
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
