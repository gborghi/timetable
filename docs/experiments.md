# Experiments & Benchmarks — two 90-class schools

This document records the experiments run on **two single-site, 90-class
high-school models** (same six *indirizzi*, 187 teachers, 6-day week Mon–Sat
with a base of 5 hours 8:00–13:00 extensible to a 6th hour to 14:00). It
reports, for each, what was **predicted** and what was **obtained**, with the
statistics measured. All runs are hard-feasible unless noted.

> Built with AI (Anthropic's Claude), like the rest of piTantum.

## Model A — `liceo90` (room-of-the-class)

The traditional Italian model: **the class keeps a home room, teachers move.**
Goal: prove that with a **biennio free-day rotation** (each first-two-year class
is off one day/week, the day chosen by the solver, HARD) plus **gym-sharing**
(a class at PE frees its ordinary room) and **sostegno as compresenza** (the
support teacher rides the class room), a school can run **fewer rooms than
classes**.

| metric | predicted | obtained |
|---|---|---|
| ordinary rooms for 90 classes | < 90 possible via rotation | **84 standard + 3 gyms = 87 < 90** |
| lessons unplaced | 0 | **0** |
| biennio classes with a free day | 36/36 | **36/36** |
| 1st-choice free-day satisfied | ≥ 80% target | **98–99%** |
| PE concurrency (3 gyms × 2) | ≤ 6/slot | **6/slot** (spread forced) |

### Soft `room_pool` — minimise rooms per class
Adding a soft term that minimises the DISTINCT rooms each class occupies over
the week (a class should change room as little as possible):

| | mean rooms/class | max | distinct (class,room) pairs | unplaced |
|---|---|---|---|---|
| without pool | **25.31** | 30 | 2278 | 0 |
| with pool | **~2.4–2.6** | 9 | 233 | 0 |

A ~10× reduction: each class settles into its ordinary room + the gym.

## Decomposition experiments (room step, fixed timetable)

Rooms are a **week-level** resource. We compared assigning them globally vs
decomposing the room step by day (temporal), on the same fixed placement:

| approach | mean rooms/class | max | pairs | unplaced | time |
|---|---|---|---|---|---|
| **Global** (all-at-once) | **2.59** | 9 | 233 | 0 | 122 s |
| Temporal, naive (per-day independent) | 6.83 | 10 | 615 | 0 | 182 s |
| Temporal, consensus (per-day + shared home) | 5.26 | 13 | 473 | 0 | 183 s |

**Finding.** Decomposing rooms by day **inflates the pool 2.6×** (2.59 → 6.83):
each day independently picks rooms, losing the cross-day coupling. A consensus
pass recovers only part of it. The global room step is both cheap and
near-optimal, so it is kept global.

## Joint monolithic week (rooms + timetable together, no decomposition)

Folding room variables into a single monolithic week model for 90 classes:

- **2,803,896 room variables**, ~10 GB RAM.
- After ~16 min: **`best: inf`** — not a single feasible solution found.

**Finding.** Confirms the code's own warning ("goes UNKNOWN around 90 classes"):
the fully-joint monolithic model does not scale to 90 classes. The
temporal/spectral decomposition + a separate global room step solves the same
school in ~2–3 min at 0 unplaced.

## Curriculum decomposition — from broken to feasible

Decomposing by *indirizzo* (curriculum) initially **produced no solution**: the
per-day solves failed instantly (0.4 s) on 3–5 of the 6 days. Root causes and
fixes (all committed):

1. **Phase A ignored per-slot special-room capacity** → it over-allocated a
   required-kind subject (PE) to a day the gyms could not host → per-day
   INFEASIBLE. Fix: a HARD per-(kind, day) cap in Phase A (constraint-driven,
   no hardcoded names).
2. **Biennio free-day rotation was not passed** to the curriculum/metis Phase A
   → all 90 classes present every day → rooms overfull. Fix: thread
   `class_free_days`.
3. **No recovery** when a day failed. Fix: a bounded retry that lowers the
   failed day's total load cap, forcing redistribution.

| | before | after |
|---|---|---|
| days solved | 3/6 → 5/6 → **6/6** | **6/6** |
| coverage | none | **2763 lessons, full** |
| biennio free | — | **36/36** |
| hard-feasible | no | **yes** |

## Model B — `liceo90doc` (room-of-the-teacher)

The reverse paradigm: **the teacher stays in (few rooms of) their subject AREA,
the students move.** Rooms are partitioned into 7 subject-area pools (via
`required_kind`); a soft `teacher_room_pool` term minimises the distinct rooms
each teacher uses; classes are `room_policy = libera`; sostegno = compresenza.

### Predicted vs obtained (room count)

| | value |
|---|---|
| theoretical floor (area hours / 30 base slots) | **85** area rooms |
| theoretical floor (/ 36 slots) | 70 |
| **obtained at FULL coverage** | **106** area rooms + 2 labs + 3 gyms |

### Attempts to go below 106 — all lose coverage

| approach | area rooms | coverage |
|---|---|---|
| Separate (place → re-room into area pools) | **106** | **100%** ✅ |
| Joint hard-cap (spectral) | 92 | 87% ❌ |
| Joint hard-cap (monolithic per-day) | 96 | 88% ❌ |
| Joint + **soft area-balance**, loose caps | (156) | 88% ❌ |

**Finding.** Re-solving the timetable under per-area room constraints drops
~12% coverage in **every** variant — the bottleneck is coverage, not spreading
(the balance term barely moved the peak: 106 → 105). The cause is the very
strong **cross-area coupling**: **162 of 187 teachers teach across several
areas**, plus the biennio rotation and paired subjects, leaving too little
freedom to both spread each area and cover everything. So **106 area rooms is
the practical floor at full coverage** — the structural price of "every teacher
always in their own area". The theoretical 85 is unreachable.

### Metrics at 106 (final model)

| metric | obtained |
|---|---|
| coverage | **full (2763 lessons)**, 0 unplaced, hard-feasible |
| **rooms per TEACHER** | **mean 1.95, max 9** — 89/187 in a single room, 60 in two |
| teachers assigned outside their area | **0** |
| rooms per CLASS | mean **13.37** (students move continuously) |
| gyms | **3** suffice (PE ≤ 6/slot) |

## Summary — predicted vs obtained

| claim | predicted | obtained |
|---|---|---|
| rooms < classes (class model) | yes, via rotation | **87 rooms / 90 classes, 0 unplaced** |
| per-class room minimisation | large | **25.3 → ~2.5 rooms/class** |
| rooms decompose by day | worse (week coupling) | **2.59 → 6.83 (2.6× worse)** |
| joint monolithic @ 90 classes | intractable | **2.8 M vars, best: inf** |
| curriculum decomposition | fixable | **6/6 days, full coverage** |
| teacher model room floor | 85 theoretical | **106 at full coverage** |
| teacher stays put | few rooms | **1.95 rooms/teacher, 0 out-of-area** |

Both solved models are shippable in the app (*Importa modelli risolti* →
`liceo90`, `liceo90doc`).
