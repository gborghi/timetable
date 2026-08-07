# Independent Audit — `superhuge_bespoke` (90-class Italian liceo stress test)

**Auditor:** independent (read-only) review of the end-to-end run built + solved by two prior agents.
**Date:** 2026-08-04.
**Isolated DB:** `sqlite:////Users/g.borghi/ICT/timetable/webui/data/superhuge_bespoke.db` (dev DB untouched).
**Active solution audited:** `Solution id=3` ("Phase B run 12", day-scope), `is_active=1`, 2767 lessons, 2463 roomed.
**Method:** every number below was **recomputed first-hand** from the DB + engine (scripts in
`scratchpad/superhuge_bespoke/verify*.py`, `verify_rooms.py`); the prior agents' `count_viol.py` was re-run
but also cross-checked against the engine's *own* constraint definitions (`cpsat_v2_timetable`, `general_dsl`),
which turned up a semantic subtlety the prior script got lucky on (see Finding F6).

---

## 1. Scenario

A deliberately hard, tight-room, free-day-heavy single-plesso liceo:

| dimension | value |
|---|---|
| Classes | **90** across 6 indirizzi (Scientifico 25, Sc.Applicate 15, Linguistico 15, LES 15, Sc.Umane 10, Classico 10) |
| Curricula | 9 (8 seeded + Classico injected at runtime with Greco/A013) |
| Week | 6 days (Lun–Sab) × 6 slots (08:00–14:00) = 36 slots |
| Rooms | **80** (64 standard, 4 palestra mm=2, 3+3+3+3 labs) → **0.89 room/class, intentionally tight** |
| Teachers | 187 (178 subject + 9 sostegno/ADSS); demand 2671 h/wk vs supply ~3242 h |
| `required_kind` | Scienzemotorie→palestra, Informatica→lab_informatica only (other labs eligible but not forced) |
| Free-day prefs (SOFT, ranked) | priority 1 = 118, priority 2 = 72, priority 3 = 28 (penalty 40−10·prio) |
| Mandatory free days (HARD) | 18 teachers |
| `min_free_days` floor (HARD) | 1→119, 2→46, **0→22** (incl. the 9 sostegno) |
| Biennio rotation | 36 biennio classes each pinned to a HARD free day (`preferred_free_days_json` is_hard + `required_free_days_count=1` + `max_hours_per_day=6`), rotated 3 sections/day across Mon–Sat |
| Sostegno | 9 disabled pupils (L.104) → 9 `is_support` cattedre (5×12h + 4×9h) shadowing the pupil |

Intent: exercise every real Italian-liceo constraint simultaneously at a scale (90 classes) and room ratio
(0.9) that most timetablers cannot handle.

---

## 2. What was run (engines, failures, relaxations)

### As-specified attempts — both failed
- **run1 — day-scope + decomposition (`scope=day`, `phase_a_mode=always`):** `PhaseAInfeasible` in **0.1 s** on
  the day-**count** model — proven infeasible by the solver, not a timeout.
- **run2 — week / soft_hint (360 s):** the monolithic week solve *found* a complete timetable (~86.8 %) but
  **failed at the DSL no-good gate** — the 18 `teacher_unavailable_day(...)` HARD rules (mandatory free days)
  are not natively compiled by the week solver, fall to the gate, and `max_iters` cannot converge at 90-class
  scale ("370 vincoli HARD DSL non soddisfatti", confirmed in `results.json`).

### Root cause (bisection, reproduced in reasoning): the `min_free_days` HARD floor
The prior agents' bisection showed the day-count model is infeasible **solely** because of the `min_free_days`
floor, and specifically because the **9 sostegno teachers** (DB value 0) were being forced to ≥1. I confirmed
the mechanism **in source** (Finding F2): `engine_io.py:319` bumps a legitimate 0 to 1.

### Relaxations actually applied (what deviates from the original spec)
1. **`min_free_days` driver correction** (no DB/source edit): the driver overrides each teacher's
   `min_free_days` with the *true* DB value so 0 stays 0. This is a **correction of an engine bug**, not a
   weakening of the instance — all 165 real floors stay HARD. *(F2 remediation applied as a workaround.)*
2. **Mandatory free days → native cells** (instance change): the 18 `TeacherMandatoryFreeDay` rows were
   **deleted** and replaced by **108 `TeacherUnavailability` hard cells** (18 days × 6 hours). Verified in DB:
   `teacher_mandatory_free_days` now has **0** rows; `teacher_unavailability` has **108** cells, all state
   `hard`, over exactly 18 teacher-days. This is a genuine instance change: it routes the constraint through a
   natively-compiled path instead of the no-good gate.
3. **`PITANTUM_DSL_GATE_STRICT=0`** as a gate safety net (supported env var), with activation still gated by
   the direct feasibility check.

The final chosen solution is **run12 (day-scope + decomposition, corrected profs, 240 s/day, STRICT=0) = sol3**,
100 % coverage, buchi 96. A separate rooms pass (run14) placed 2463/2767. LNS (run13) was a **no-op** (F1).

---

## 3. Results (verified first-hand)

### 3.1 Coverage — **100 %, exact** ✔
Per (teacher,class,subject) lesson-hours vs `Assignment` hours (1014 non-support cattedre, 2671 h expected):
**0 short, 0 over.** 2767 total lessons = 2671 ordinary + 96 sostegno. The 9 keys not matching a non-support
assignment are exactly the 9 sostegno cattedre. Coverage is genuinely complete.

### 3.2 HARD feasibility — **genuinely feasible** (the `is_hard_feasible=False` is a false negative) ✔
`metaheuristics.is_hard_feasible(sol3, …)` returns **False** — I reproduced it. It is a **false negative**
(Finding F1): `general_dsl.evaluate_safe("teacher_unavailable_day(...)")` returns an error
`"funzione sconosciuta: 'teacher_unavailable_day'"`, and the H6 policy fail-closes. Direct recomputation of the
real constraints on sol3:

| HARD check | violations | how verified |
|---|---|---|
| Teacher double-booking | **0** | own `verify.py` |
| Class double-booking (ordinary) | **0** | `verify.py` — the 96 "overlaps" are exactly the 96 sostegno co-presence hours |
| Coverage | **0** | §3.1 |
| Holes (`hard_no_holes`, 90 cls) | **0** | `verify2/3` |
| Entry@8 (`hard_entry_at_8`, 90) | **0** | `verify2` |
| Exit≥12 (`hard_exit_after_12`, 90) | **0** | `verify3` — engine rule = "hour-11 slot present" (11∈hrs); corrected from a naive reading |
| Teacher max consecutive (all 187 = 5) | **0** | `verify3` |
| **`min_free_days` floor** (true DB values) | **0** | `verify3` |
| **18 mandatory free days** (108 cells) | **0** | `verify3` — all 18 teachers have **zero** lessons on their blocked day |
| Mat/Ita consecutive pair (native semantics) | **0** | `verify4` (see F6) |
| Scienze-motorie pair (`must_pair`) | **0** | `verify4` |

**sol3 satisfies every real HARD timetable constraint.** buchi (soft holes) = **96**, independently recomputed
(matches the stored metric exactly). Comparison solution sol1 (week-scope) has buchi 155 **plus** 62 Mat/Ita +
162 motorie pair violations — the week path structurally cannot model the pairs, so the day-scope sol3 is
correctly the better choice.

### 3.3 Free-day PREFERENCES (soft, ranked) — **poorly satisfied** ⚠
For each `TeacherFreeDayPreference`, is that day actually free in sol3?

| priority | honored / total | rate | unmet penalty (40−10·p) |
|---|---|---|---|
| 1 | 25 / 118 | 21.2 % | 30 × 93 = 2790 |
| 2 | 12 / 72 | 16.7 % | 20 × 60 = 1200 |
| 3 | 7 / 28 | 25.0 % | 10 × 21 = 210 |
| **total penalty** | | | **4200** |

Per-teacher: only **41 / 118 (34.7 %)** teachers got **any** of their ranked days free. This is low. It is not
a HARD violation, but it is a real quality gap — largely because the metaheuristic post-pass that would push
soft costs down was a no-op (F1), and the tight instance leaves little slack. (Finding F5.)

### 3.4 Biennio rotating free day — **UNENFORCED: 35 / 36 classes violated** ✗
For each biennio class, is its HARD-pinned day actually empty?

- **1 / 36** biennio classes has its pinned day free; **35 / 36 do not.**
- Free-day-count distribution across the 36 biennio classes: **33 have 0 free days**, 3 have 1. The intended
  "exactly one free day" (`required_free_days_count=1`) is also unmet for 33 of them.

Root cause confirmed **in source** (Finding F3): `SchoolClass.preferred_free_days_json` and
`required_free_days_count` are referenced **only** in `models.py`, `db.py`, `schemas.py` — **no engine module
consumes them.** The biennio 5-of-6-day rotation is dead data; every biennio class simply attends all 6 days.

### 3.5 Sostegno — **perfect** ✔
All 9 support cattedre: placed hours = assigned hours (5×12 + 4×9 = 96, all placed), `pupil_class == assign_class`
in every case, and **100 %** of each support teacher's lessons land in a slot where the pupil's class has an
ordinary lesson — **0 off-pupil placements**. The sostegno shadow is exactly correct.

### 3.6 Rooms — **304 unplaced, structural (not a bug)** ⚠ (expected-by-design)
2463 placed / 304 unplaced (2767 total).

- **No room is double-booked** beyond `multi_class_max`: **0** over-occupied room-slots. The room step is sound.
- Unplaced lessons span **all 20 subjects** (Italiano 35, Matematica 29, Inglese 27, Filosofia 23, …), i.e. it
  is **not** a lab/Informatica-specific failure — it is aggregate room starvation.
- **Structural cause:** in **24 of 36 slots all 90 classes are in session** (peak 90) against **80 rooms**
  (79 distinct rooms used, +1 palestra double = ~80 effective). ≥10 classes/slot therefore cannot be roomed;
  unplaced concentrate in the mid-morning peaks (16 at slot (Tue,09:00), 15 at (Mon,09:00)…). This matches the
  intentional 0.9 ratio exactly.
- The `NO_ELIGIBLE ×5` for Informatica is a secondary ordering artifact: the 3 informatica labs get consumed by
  ordinary lessons (peak concurrent Informatica is only 2, so labs are not the binding limit), leaving a few
  Informatica lessons with no eligible room once all rooms are full.
- The room-aware **joint** model that would couple placement to room supply **auto-disables above 75 classes**
  (`optimization.py:879`, `PITANTUM_JOINT_MAX_CLASSES=75`); at 90 it degrades to schedule-then-room. Combined
  with a scheduler that does not cap per-slot class concurrency at the room count, the room step is handed a
  physically unroomable 90-into-80 problem. (Finding F4.)

---

## 4. Findings (severity-ranked)

### F1 — `general_dsl` evaluator gap → `is_hard_feasible` false negative + neutered metaheuristics — **HIGH** — [engine modeling gap]
`engine/general_dsl.py` `_eval_call` (ends at **line 1292**, `raise DSLError("funzione sconosciuta")`) implements
no branch for `teacher_unavailable_day`, `teacher_unavailability`, `teacher_at_least_n_free_days`, or
`teacher_day_capacity` (grep: 0 hits for each). Reproduced directly: `evaluate_safe` on
`teacher_unavailable_day("Jessica Hendricks", 1)` returns an error string; `is_hard_feasible(sol3)=False`.
**Impact:** (a) the H6 fail-closed policy makes `is_hard_feasible=True` **structurally unreachable** for *any*
solution of *any* instance carrying a mandatory free day (a very common real constraint) — the audit verdict is
a false negative; (b) worse, LNS/SA/TS call `is_hard_feasible` on the starting solution, fail-closed, and reject
**every** move — the metaheuristic post-pass is a silent no-op (confirmed: run13 LNS produced buchi 96 = the CP
value, no improvement). This silently disables soft-cost optimization (incl. the free-day prefs of F5) on a
whole class of realistic instances. **This is the most consequential finding.**
**Remediation:** implement post-hoc evaluators for `teacher_unavailable_day` / `teacher_unavailability` /
`teacher_at_least_n_free_days` / `teacher_day_capacity` in `general_dsl` (the lesson `world` already carries
teacher/day/hour, so all four are cheaply decidable), mirroring the existing pragma evaluators.

### F2 — `engine_io.profs_dict_from_db` `min_free_days or 1` falsy-zero bug — **HIGH** — [engine bug]
`webui/backend/engine_io.py:319–320`:
```python
info["min_free_days"] = int(getattr(t, "min_free_days", 1) or 1)
```
`or 1` treats a legitimate DB `0` as falsy and bumps it to `1`. It hit exactly the 22 DB-zeros (the 9 sostegno
ADSS + 13 part-time/external). Because a sostegno shadow must follow its pupil **every** working day, forcing
them to ≥1 free day makes the day-count Phase A **provably INFEASIBLE** — this is the sole cause of the run1
`PhaseAInfeasible` and the whole as-specified pipeline failure. **Impact:** any instance with a
legitimately-zero `min_free_days` teacher is over-constrained into infeasibility on the day-scope path.
**Remediation:** `int(t.min_free_days if t.min_free_days is not None else 1)` — distinguish "unset"
(default 1) from an explicit 0. (The prior agents worked around this in the driver rather than patching source.)

### F3 — Biennio class free-day pins unreadable by any Phase-B engine — **HIGH** — [engine modeling gap]
`SchoolClass.preferred_free_days_json` and `required_free_days_count` are consumed by **no** engine module
(refs only in `models.py` / `db.py` / `schemas.py`). Verified outcome (§3.4): **35/36** biennio classes attend
their supposedly-free day; 33/36 have zero free days. The entire biennio 5-of-6-day rotation — a core part of
the scenario — was silently unenforced regardless of engine or relaxation. **Remediation:** translate the class
free-day pin to a per-class `class_day_load_in(class, 0)`-style HARD rule for the pinned day (the day-count
model already has `class_day_load_allowed`, so the plumbing exists), and wire `required_free_days_count` into
the class day-count constraint the way `min_free_days` feeds the teacher day-count.

### F4 — Room over-subscription: scheduler does not cap per-slot concurrency at room supply — **MEDIUM** — [instance over-constraint + scaling gap]
304 unplaced (§3.6). The 0.9 room ratio is **intentional** and makes full rooming physically impossible when 90
classes sit in the same slot, so the *deficit* is expected-by-design. The **engine-side** contribution is that
the scheduler places all 90 classes concurrently (24/36 slots at peak 90) with no per-slot occupancy cap, and
the room-aware joint model that would couple the two auto-disables >75 classes (`optimization.py:879`). The room
step itself is correct (0 double-books). **Remediation:** either raise the ratio to ≥1.0 (instance fix), or add
a `subjects_max_concurrent_classes`-style per-slot occupancy ceiling = room supply to the scheduler so it
spreads load into the underused late slots (hour-13 concurrency is only 9–14), and/or make the joint room model
scale past 75.

### F5 — Free-day soft-preference satisfaction very low (21 % of top choices) — **MEDIUM** — [downstream of F1 + tight instance]
Only 25/118 priority-1 prefs honored, 41/118 teachers with any preferred day free, total penalty 4200 (§3.3).
Partly the price of an intentionally tight instance, but materially worsened by F1 (the metaheuristic pass that
would trade slack into free-day satisfaction is a no-op). **Remediation:** fixing F1 unblocks LNS/SA to reduce
this penalty; independently worth confirming the day-scope objective even *includes* the ranked free-day term at
90-class scale.

### F6 — `general_dsl._eval_subject_pair` semantics differ from the native compiler — **LOW** — [engine modeling inconsistency]
The native day-scope pair constraint (`cpsat_v2_timetable.py:236–299`) enforces pairing on the **teacher's
combined presence across all their subjects** in the class, per day, gated on the teacher's day-count. The
post-hoc evaluator `general_dsl.py:1528 _eval_subject_pair` instead checks **subject-specific** adjacency.
On sol3 the native reading gives **0** Mat/Ita violations (verified `verify4.py`, the constraint the solver
actually enforced), while a naive subject-only reading flags 1 Matematica + 8 Italiano "splits". The prior
agents' `count_viol.py` reported 0 for a *third* reason (it checked only that *some* day in the week has a pair —
too lenient) and happened to agree. **Consequence:** two Italiano hours can be non-adjacent as long as the
Italiano teacher has an adjacent lesson of another subject — arguably not what "abbina le due ore di Italiano"
means pedagogically. **Remediation:** align the two definitions (decide whether pairing is prof-adjacency or
subject-adjacency) and make the post-hoc evaluator match the compiler so audits are consistent.

### F7 — Mandatory free days not natively compiled in the week solver — **MEDIUM** — [engine modeling gap]
Confirmed via run2's `results.json` failure ("370 HARD DSL non soddisfatti … teacher_unavailable_day(...)").
The week path routes `teacher_unavailable_day` to the no-good gate, which cannot converge at 90 classes. The
prior agents sidestepped it by pre-expanding the 18 free days into 108 native `TeacherUnavailability` cells.
**Remediation:** compile `teacher_unavailable_day` natively (it is a pure per-slot forbiddance identical to a
full column of unavailability cells) so the instance change is unnecessary.

---

## 5. Verdict

**Did the solver handle a realistic tough Italian-liceo scenario? — Yes on the timetable core, with real caveats.**

What genuinely works (verified first-hand): **100 % coverage**, **zero real HARD violations** (double-booking,
holes, entry/exit, teacher max-consecutive, `min_free_days`, the 18 mandatory free days, and the Mat/Ita +
motorie pairs the day-scope engine actually models), and **flawless sostegno** shadowing. The chosen day-scope
sol3 (buchi 96) is correctly better than the week alternative. Against a 90-class, 0.9-room, free-day-heavy
instance, producing a fully-covering, hard-clean weekly timetable is a real result.

What must be fixed before this instance class is production-ready:
- **F1 (general_dsl gap)** and **F2 (`or 1` bug)** are genuine engine defects, not instance artifacts. F1 makes
  the automated feasibility verdict lie (false negative) and silently disables metaheuristic optimization on any
  school with mandatory free days; F2 pushes any school with a zero-free-day teacher into false infeasibility.
  Both are common real configurations. These two are the priority fixes.
- **F3 (biennio pins unenforced)** means a headline feature of the scenario never took effect — 35/36 biennio
  classes did not get their free day. This is an engine modeling gap, independent of the relaxations.

Genuine defects vs. the price of an over-tight instance:
- **Real engine defects:** F1, F2, F3, F6, F7 (and the scaling half of F4).
- **Price of an intentionally hard instance:** the 304 unplaced rooms (0.9 ratio is deliberate — the deficit is
  arithmetic, and the room step made no error) and much of the low free-day-preference satisfaction (tight slack,
  amplified by F1).

Net: the scheduling engine is fundamentally sound and scales to 90 classes on the hard constraints it compiles
natively, but three real gaps — the DSL evaluator (F1), the `min_free_days` zero bug (F2), and the unwired class
free-day pins (F3) — meant the run only succeeded after a source-level driver correction and an instance change,
and left two of the scenario's declared features (biennio rotation; ranked free-day preferences) largely
unmet. The `is_hard_feasible=False` badge on sol3 is **not** a real infeasibility.
