# Optimization techniques: what they do, when to use them

When piTantum builds a schedule it does not do so in a single
shot. The program has a small toolbox of strategies: some build
the first solution from scratch, others improve it later, others
still are diagnostic checks run before launching the solver to
verify the problem is solvable in principle. This page walks
through each tool with a concrete analogy, and tells you when to
turn it on.

You are in the right place if you are a school timetable
coordinator or system administrator wondering: "what is this
'ALNS' I see in the Workflow tab? Should I leave it on? What is
the 'Hall pre-check' for?"

All techniques described here are available from the **Workflow**
tab (`/optimize`) of the web app under the "Advanced techniques"
card. The same options appear in the integrated pipeline where
you decide which stages to execute and in which order.

> **For developers**: the modules live in `engine/` and are
> exposed via REST in `webui/backend/routers/optimize.py`.

## 1. ALNS — the LNS that learns what works

**Analogy**: imagine sculpting a statue. Classic LNS gives you a
single chisel and a fixed rule: "every time, take a big chunk
out of a random area and rebuild it." **ALNS** is the same
process but with six different chisels (one cuts horizontal
lines, another vertical, another clusters of nearby classes...)
and three repair styles. After a few iterations the sculptor
learns: "when I use the horizontal-line chisel, ten times out of
ten the statue gets worse; when I use the cluster chisel, seven
out of ten it gets better." From then on it favours the good
chisels.

**When to use it**: as soon as you have an initial solution
(after Phase B) and you have 1–2 minutes to improve it.
Replaces or follows classic LNS. ON by default.

### Technical detail

`engine/alns.py`. Six destroy operators: `random_window`,
`day_cluster`, `worst_fit_day`, `teacher_day`,
`classroom_day`, `single_class_week`. Three repair operators:
`cp_sat_window`, `greedy_by_soft`, `bfs_fill_back`. Adaptive
roulette-wheel selection over exponentially-decayed scores;
SA-like acceptance with geometric cooling.

API: `POST /api/optimize/meta/alns` with `budget_s`,
`alns_T0`, `alns_alpha`.

## 2. VNS — the polish that drives you to a local optimum

**Analogy**: after roughly sculpting the statue with LNS/ALNS
you want to polish it. VNS picks up a series of finer and
finer files: first try swapping two nearby lessons; if that
doesn't help, swap two pairs; then chain three; then four or
five. When a full pass with no improvement is recorded, the
search stops — you have reached a local optimum.

**When to use it**: at the end of the metaheuristic chain,
after TS or ILS. It does not replace LNS/SA/TS; it is a final
polish. OFF by default (turn it on when you want maximum
quality at the cost of more time).

API: `POST /api/optimize/meta/vns` with `budget_s` and
optional `vns_neighbourhoods[]`.

## 3. Hall pre-check — find out IMMEDIATELY whether the problem is solvable

**Analogy**: before a long drive you check the fuel gauge. If
the tank is empty you don't leave — you avoid getting stuck
halfway. The **Hall pre-check** is the equivalent for piTantum:
in milliseconds it verifies that the available teachers have
*enough total hours* to cover all class hours requested. If
they don't, it tells you immediately rather than letting you
wait 10 minutes to discover the model is infeasible.

It is a structural check, not a solve: it just saves you time
when the model is hopeless from the start.

**When to use it**: always before Phase A, especially mid-year
when you have edited cattedre or added constraints that may
have made the problem impossible. ON by default in the
pipeline.

API: `POST /api/diagnostics/hall-check` with `n_samples`,
`teacher_max_hours`. Returns synchronously
`{ok, n_classes, n_teachers, violations[], stats, warnings}`.

## 4. Column Generation — for very large schools

**Analogy**: instead of planning the whole school's timetable
in one go, you build a "catalogue of weekly templates" for each
teacher (e.g. three or four variants of how teacher Rossi's
week could look). Then a second program picks which template
to use for each teacher so that everything fits together. If
the combination is not enough, you generate new templates and
repeat.

It's like picking an apartment from a rental agency catalogue:
instead of inspecting every existing house, you only look at
the ones in the catalogue, and if none fits you ask the agent
to bring out more listings.

**When to use it**: only for very large schools (>200 classes).
For ordinary instances the standard pipeline is faster. OFF by
default.

### Technical detail

`engine/column_generation.py`. Master LP via
`scipy.linprog` (HiGHS); 9 dedicated CP-SAT pricers at distinct
granularities. The `iterative-diversified` mode (default) is a
primal-heuristic seeder of the pattern pool;
`branch-and-price` is the textbook BP loop with all four
scalability techniques (Ryan-Foster recursive tree, box-step
dual stabilization, column management with EWMA RC, parallel
pricing via `ProcessPoolExecutor`).

#### Two master LPs

- **Variant 1** (`_solve_master`): per-teacher equality
  `sum_p x[t,p] = 1` for every teacher. Used for the
  4 teacher-based granularities (`teacher`, `teacher-day`,
  `teacher-class`, `teacher-class-subject`,
  `teacher-subject`). The pricer emits a complete weekly
  pattern for the teacher; only the granularity slice (e.g.
  the class for `teacher-class`) is CP-SAT-optimised, the
  rest is greedy-placed as context.

- **Variant 2** (`_solve_master_dw`): pure Dantzig-Wolfe.
  Used for the 4 multi-teacher granularities (`class`,
  `class-day`, `day`, `curriculum`):
  - **cover** `sum_col x*placed_col(t,cl,s,d) >= demand(t,cl,s,d)`
  - **class no-overlap** `sum_col x*occupies(cl,d,h) <= 1`
  - **teacher no-overlap** `sum_col x*occupies(t,d,h) <= 1`
  Phase-1 LP with artificial slacks (Big-M = 10^6) is always
  feasible at seed entry, producing valid duals for pricing.

#### Granularity at a glance

| Granularity | CP-SAT variables | What the pricer optimises |
|---|---|---|
| `teacher-class` | slot[(s,d,h)] for s in subjects(t,cl) | all (t, cl, *, *, *) slots |
| `teacher-class-subject` | slot[(d,h)] per (t,cl,s) | one cattedra |
| `teacher-subject` | slot[(cl,d,h)] per cl in classes(t,s) | (t, *, subj, *, *) |
| `teacher-day` | slot[(cl,s,h)] per (cl,s) in catt(t,day) | one teacher-day |
| `teacher` | slot[(cl,s,d,h)] per (cl,s) in catt(t) | full teacher week |
| `class` | slot[(t,s,d,h)] per (t,s) in catt(cl) | full class week |
| `class-day` | slot[(t,s,h)] per (t,s) in catt(cl,day) | one class-day |
| `day` | slot[(t,cl,s,h)] all (t,cl,s) of the day | one global day (multi-class) |
| `curriculum` | slot[(t,cl,s,d,h)] for cl in curriculum_id | full curriculum week |

#### CP-SAT-as-fundamental contract

For every granularity, the CP-SAT sub-problem is the
**fundamental** minimisation; greedy serves only as a
`model.add_hint` warm-start. If CP-SAT cannot find a feasible
solution within the time limit the pricer returns
`(None, 0.0)`: the greedy is **never** promoted to a column.

### Step 4 (textbook BP): pricing-in-nodes + PhaseBDaySolver

Step 4 of the multi-day plan brings the Branch-and-Price loop
to its complete textbook form:

1. **Pricing-in-nodes**. Before Step 4, the Ryan-Foster tree
   only re-solved the master on the existing pool at each node
   — the CP-SAT pricer was invoked only at the root. Now every
   RF tree node re-invokes the pricer with the branch
   decisions (`together`/`apart`) already applied to the
   sub-problem CP-SAT model. Effect: the improving columns
   that emerge under the branched constraints are specific to
   that node and not available at the root; tree exploration
   becomes much more effective on MEGA-size instances where
   the root produces stable duals but the branched
   sub-problem restricts the space in ways the original pool
   cannot represent.

2. **PhaseBDaySolver**. OO wrapper around the legacy
   `solve_phase_b_for_day` function. Preserves the legacy
   model byte-for-byte (100+ regression tests pass by
   construction) and accepts a `via_dsl=True` flag that adds,
   on top of the legacy model, every DSL constraint relevant
   to the day. Its existence is the key to migrating
   progressively from the hardcoded path to the DSL path: the
   hardcoded path stays active, the DSL adds further
   restrictions, and once the outputs coincide on 100% of
   scenarios the hardcoded path is deprecated.

3. **Smoke benchmark**.
   `tests/benchmarks/test_bp_step4_smoke.py` runs the full
   loop on `small` (10 classes) and `medium` (28 classes)
   scenarios, checking: HARD-feasibility, soft cost not worse
   than the iterative-diversified baseline, RF tree explored.
   The test is in CI so any regression of the BP path is
   caught immediately.

The `mode="branch-and-price"` flag in the POST to
`/api/optimize/column-generation` activates the full path.
`iterative-diversified` remains the default and acts as the
initial pool seeder.

### References

- Dantzig & Wolfe 1960, *Decomposition principle for linear
  programs*. The paper that introduces Dantzig-Wolfe
  decomposition.
- Desrosiers & Lubbecke 2005, *A Primer in Column Generation*.
  Modern and accessible reference.
- Ryan & Foster 1981, *An integer programming approach to
  scheduling*. The branching scheme bearing their names.
- Vanderbeck & Wolsey 2010, *Reformulation and decomposition
  of integer programs*. Systematic treatment of block-angular
  decomposition behind the curriculum granularity.

OFF by default in the pipeline (only useful for large
instances).

## 5. Lagrangian relaxation — divide and pack

**Analogy**: the school is split into small clusters of classes
that share few teachers (the clusters produced by spectral
decomposition). Most teachers work inside a single cluster and
their schedule can be planned without looking at the rest of
the school. The "bridge" teachers (those who teach across
clusters) introduce a coordination problem: they cannot be in
two clusters at the same slot. The **Lagrangian** approach
addresses this: it adds a "fictitious" cost to the bridges,
adjusts it iteratively to push the model towards naturally
satisfying the constraint, and as long as the bridges remain
consistent the parallel cluster planning works.

**When to use it**: medium-large schools with many
well-separated clusters. OFF by default (advanced; for most
cases LNS+ALNS+SA+TS are sufficient).

API: `POST /api/optimize/meta/lagrangian` with `budget_s`,
`lagrangian_max_iter`, `lagrangian_tolerance`,
`lagrangian_alpha_0`.

## Other metaheuristics (classic LNS, SA, TS, ILS)

The four "historical" metaheuristics of the solver are always
available, ON by default in the pipeline and combine well.

- **LNS** (Large Neighborhood Search). The parent of ALNS:
  destroys a portion of the solution and rebuilds it with
  CP-SAT. More "rigid" than ALNS because it doesn't choose
  by itself which area to attack.

- **SA** (Simulated Annealing). Analogy: a molten steel ball
  cooling down. When hot it moves a lot and accepts
  worsening moves (to escape local minima); as it cools it
  becomes more selective and finally settles in the deepest
  pit it found.

- **TS** (Tabu Search). Analogy: an explorer who keeps a
  notebook of recent moves and forbids himself from
  repeating them. This breaks out of A→B→A→B loops.

- **ILS** (Iterated Local Search). Alternates "quiet local
  search" phases with periodic perturbations to explore
  different regions of the search space.

## Decomposition: split the problem into parts

Three new decomposition methods join the existing spectral
decomposition. They are orthogonal: they can combine in
multi-stage pipelines (spectral + temporal, METIS + temporal,
etc.) for maximum speedup.

### Temporal decomposition (per-day)

Splits the problem along the time axis instead of along
entities. Each of the six weekdays becomes a separate
sub-problem solvable in parallel. A small pre-distribution
phase decides how many hours of each cattedra go to each day
(respecting weekly constraints like the math double-pair and
the per-class daily cap), then six CP-SAT instances work one
per day on the pre-distributed hours. The main advantage is
that the method is *always applicable*: it does not require a
community structure in the class-teacher graph and parallelises
naturally on six cores. Best for dense schools where spectral
decomposition struggles. Module:
`engine/decomposition_temporal.py`.

### METIS decomposition (k-way multilevel partitioning)

METIS is a classic graph partitioning library that produces
$k$-balanced partitions minimising the cut. Works well on
dense graphs without obvious community structure, where
spectral decomposition returns artificial clusters.
Configurable with the number of partitions $K$
(default $K = \sqrt{n_{\text{classes}}}$) and the imbalance
tolerance (default 5%). Module:
`engine/decomposition_metis.py`.

### Curriculum decomposition

Exploits the `curriculum_id` field on classes: each
curriculum (Liceo Scientifico, ITIS Informatica, ...) becomes
a cluster, and teachers spanning multiple curricula become
bridges. Most predictable and interpretable decomposition.
Module: `engine/decomposition_curriculum.py`.

### Auto-detect of the best strategy

`engine/decomposition_auto.py` exposes
`auto_detect_decomposition_strategy(profs)` which computes two
descriptive metrics of the bipartite class-teacher graph
(Newman-Girvan modularity and density) and recommends the
best strategy. The REST endpoint
`GET /api/optimize/decomposition/recommend` exposes this
function to the frontend.

## Integrated pipeline: recommended order

```
hall_check  (ON, diagnostic)
phase_a     (ON, cattedra assignment)
phase_b     (ON, main scheduling)
cg          (OFF, alternative for large instances)
lns         (ON, classic LNS)
alns        (ON, adaptive LNS)
sa          (ON, simulated annealing)
ts          (ON, tabu search)
vns         (OFF, polish)
lagrangian  (OFF, advanced)
ils         (ON, iterated local search)
rooms       (OFF, independent)
```

All steps are draggable and tickable in the "9) Full pipeline"
card of the `/optimize` tab.

---

> **Note**: this is the English-language summary. The Italian
> version lives in `optimization_strategies.md`.
