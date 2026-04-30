# Phase-A objective DSL

A small linear-expression language used to describe what the
Phase-A solver (assegnazione docenti -> classi) should optimise.
Lives in `webui/backend/utils/objective_dsl.py`. Compiled to a CP-SAT
`LinearExpr` at solve time by `experiments/cpsat_assignment_dsl.py`.

The five built-in **presets** that ship with piTantum are themselves
expressions in this DSL (see the `PRESETS` constant in the parser
module). Users can pick a preset from the Workflow page or write a
custom expression in the editor.

## Why a DSL?

The original Phase A had hard-coded weights inside
`cpsat_v2_assignment.py`. Adding a new criterion meant patching code
+ re-deploying. With the DSL:

- 5 presets cover the common cases. Picking one is one click.
- "Custom" lets the user combine the same primitives in arbitrary
  proportions for one-off scenarios (e.g. "this year I really want
  cattedre piene at all costs, even if it concentrates classes").
- The same primitives are reused across all presets so the user can
  learn the vocabulary once and read any preset like it was their
  own.

## Grammar (BNF)

```bnf
program       := direction expr
direction     := 'minimize' | 'maximize'
expr          := term (('+' | '-') term)*
term          := factor (('*' | '/') factor)*
factor        := NUMBER
              | call
              | IDENT                ; named scalar variable
              | '-' factor
              | '(' expr ')'
call          := IDENT '(' [arg (',' arg)*] ')'
arg           := expr
```

A program **must** start with `minimize` or `maximize`. Comments are
not (yet) supported.

## Vocabulary

### Scalar variables (already aggregated, usable at top level)

| Name                       | Meaning                                                     |
| -------------------------- | ----------------------------------------------------------- |
| `total_unused_capacity`         | sum over teachers of `(max_hours - actual_hours)`     |
| `total_n_classes`               | sum over teachers of "distinct classes assigned"      |
| `total_n_curricula`             | sum over teachers of "distinct curriculum-tops assigned" |
| `total_weight`                  | sum over teachers of `teacher_weight[t]`              |
| `total_seniority_misalignment`  | sum over teachers of `teacher_seniority_misalignment[t]`. Higher means teachers and classes are badly matched by seniority/curriculum-weight; minimise to align "anziani -> indirizzi pesanti". |
| `weight_balance_penalty`        | linearised variance of `teacher_weight[t]`: `sum_t |n_t * teacher_weight[t] - total_weight|`. Minimise to make every teacher carry roughly the same indirizzo-weight (= no one stuck only on heavy classes, no one only on light). Lineare-equivalente di una varianza. |
| `n_under_18`                    | count of teachers with `actual_hours < 18`            |
| `n_under_10`                    | count of teachers with `actual_hours < 10`            |

### Per-teacher variables (only inside `sum(...)` / `count(...)`)

| Name                              | Meaning                                                          |
| --------------------------------- | ---------------------------------------------------------------- |
| `teacher_hours`                   | actual hours assigned to this teacher                            |
| `teacher_max_hours`               | max contractual hours for this teacher                           |
| `teacher_unused`                  | `max_hours - actual_hours`                                       |
| `teacher_n_classes`               | distinct classes assigned                                        |
| `teacher_n_curricula`             | distinct curriculum-tops touched                                 |
| `teacher_weight`                  | sum of `(year + curriculum_score)` over assigned classes; a proxy for "load weight" |
| `teacher_seniority_misalignment`  | `sum_ci has_class[ti,ci] * |teacher_rank[ti] - class_rank[ci]| * curriculum_score[ci]`. Requires `graduatoria_score` on Teacher; teachers without a score get the median rank. |

### Predicates (boolean per teacher; only inside aggregates)

| Name                       | Args | Meaning                                       |
| -------------------------- | ---- | --------------------------------------------- |
| `over_max_hours()`         | 0    | `teacher_hours > teacher_max_hours` (rare)    |
| `under_min_hours(N)`       | 1    | `teacher_hours < N`                           |
| `over_min_hours(N)`        | 1    | `teacher_hours >= N`                          |
| `cross_curricula()`        | 0    | `teacher_n_curricula > 1`                     |
| `single_curriculum()`      | 0    | `teacher_n_curricula == 1`                    |
| `empty_teacher()`          | 0    | `teacher_hours == 0` (no assignment)          |

### Aggregates

`sum(<expr>)` and `count(<expr>)` (alias for `sum` on a boolean).
Both expand the inner expression once per teacher and sum the
results.

### Operators

`+ - * /` on linear expressions. **At least one side of `*` and the
right side of `/` must be a constant** -- otherwise the expression
is non-linear and rejected by the validator.

### Rejected (non-linear)

`stddev`, `var`, `mean`, `abs`, plus any `var * var` / `var / var`.
The validator gives a clear error pointing at the offending node.

## Built-in presets

Per Giovanni's spec, the **three** shipped presets cover the most
common Phase-A goals; everything else is reachable via `Custom` in
the UI editor. The presets are stored in `objective_dsl.PRESETS`
and surfaced by `GET /api/optimize/phase-a/presets`. Each tuple is
`(key, label, summary, dsl_expression)`.

### `max_clustering`

```text
minimize 50 * total_unused_capacity
       + 200 * total_n_classes
       + 200 * sum(cross_curricula())
       + 5000 * n_under_18
```

Minimises the number of teacher-class connections in the bipartite
graph: each teacher works on as few classes as possible AND on a
single curriculum. Pushes the graph toward natural clusters, making
the subsequent spectral decomposition in Phase B (Stage A bridges)
much more effective. Trade-off: rigidifies the allocation in case of
substitutions / emergencies.

### `balance_weight`

```text
minimize 50 * total_unused_capacity
       + 100 * total_n_classes
       + 20 * weight_balance_penalty
       + 5000 * n_under_18
       + 50000 * n_under_10
```

Distributes the weight of curricula evenly across teachers using a
**linearised variance** of `teacher_weight[t]` — concretely
`weight_balance_penalty = sum_t |n_t * teacher_weight[t] -
total_weight|`, which is zero exactly when every teacher carries
the same total weight. Sensible default if you don't have a
specific requirement.

### `seniority`

```text
minimize 50 * total_unused_capacity
       + 100 * total_n_classes
       + 5000 * n_under_18
       + 10 * total_seniority_misalignment
```

Aligns teacher seniority (`graduatoria_score`) with class
heaviness (`curriculum.score`): the more senior teacher gets the
heavier indirizzo. Teachers without a recorded score are treated as
neutral (median rank). The penalty is `|rank_t - rank_ci| *
curriculum_score[ci]`, summed per-teacher and across teachers.

Requires the `graduatoria_score` field on Teacher (added 2026-04-30
via Alembic migration `a8b1a59a0487`). On a school with NO
graduatoria data, this preset behaves identically to the generic
balance preset (the seniority term degenerates to 0).

## Custom expression examples

### "Bilanciamento + nessun docente vuoto"

```text
minimize 100 * total_unused_capacity
       + 50 * total_n_classes
       + 100000 * sum(empty_teacher())
```

Penalises teachers with 0 hours nearly-hardly.

### "Maximize curriculum coverage diversity"

```text
maximize total_n_curricula
       - 0.1 * total_unused_capacity
```

Useful when the goal is to expose teachers to more curricula
(rotation, pedagogical breadth).

### "Soft floor at 12h, soft ceiling at 16h"

```text
minimize 200 * sum(under_min_hours(12))
       + 50 * sum(over_min_hours(16)) * (-1)
       + 50 * total_unused_capacity
```

(The `* (-1)` is OK because both factors are constants — the
validator is happy.)

## Compile semantics (for engine devs)

- `_lower(expr, ctx, inside_aggregate)` walks the AST and emits an
  ortools `LinearExpr` (or scalar number).
- Scalar variables map to pre-built `IntVar`s on the Phase-A model.
- `sum(per_teacher_expr)` calls `_per_teacher_terms` which expands
  the subtree once per teacher; the returned list of terms is then
  reduced with Python `sum()`.
- Predicates lazily allocate one `BoolVar` per teacher with the
  appropriate `OnlyEnforceIf` reified equality. The boolvars are
  cached by `(name, args_tuple)` so e.g. `under_min_hours(18)` reused
  twice in the same expression doesn't double-allocate.

## Extending the vocabulary

To add a new predicate:

1. Add the name + arity to `PREDICATES` in
   `webui/backend/utils/objective_dsl.py`.
2. Add a branch in `_predicate_per_teacher()` that wires the
   `OnlyEnforceIf` reification using the model variables in the
   `CompileContext`.
3. If new model variables are needed, expose them on
   `CompileContext` (e.g. `teacher_seniority`) and populate them in
   `experiments/cpsat_assignment_dsl.py::solve_assignment_dsl`.

To add a new scalar variable:

1. Add the name to `SCALAR_VARS`.
2. Wire it in `_lower()`.
3. Build the IntVar in `solve_assignment_dsl` and pass it to the
   `CompileContext`.

To add a new preset:

Just append a tuple to `PRESETS`. The frontend picks it up via
`GET /api/optimize/phase-a/presets`.

## Testing

`webui/backend/tests/test_objective_dsl.py` covers parser, validator,
and preset round-trips (each preset must validate).
`webui/backend/tests/test_phase_a_endpoint.py` covers the two HTTP
endpoints (`presets`, `validate-expression`).

Integration with the actual CP-SAT solve is exercised end-to-end by
running Phase A on the small profile after this commit -- not
automated yet, but easy to add with a fixture.
