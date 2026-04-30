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
| `total_unused_capacity`    | sum over teachers of `(max_hours - actual_hours)`           |
| `total_n_classes`          | sum over teachers of "distinct classes assigned"            |
| `total_n_curricula`        | sum over teachers of "distinct curriculum-tops assigned"    |
| `total_weight`             | sum over teachers of `teacher_weight[t]`                    |
| `n_under_18`               | count of teachers with `actual_hours < 18`                  |
| `n_under_10`               | count of teachers with `actual_hours < 10`                  |

### Per-teacher variables (only inside `sum(...)` / `count(...)`)

| Name                  | Meaning                                                          |
| --------------------- | ---------------------------------------------------------------- |
| `teacher_hours`       | actual hours assigned to this teacher                            |
| `teacher_max_hours`   | max contractual hours for this teacher                           |
| `teacher_unused`      | `max_hours - actual_hours`                                       |
| `teacher_n_classes`   | distinct classes assigned                                        |
| `teacher_n_curricula` | distinct curriculum-tops touched                                 |
| `teacher_weight`      | sum of `(year + curriculum_score)` over assigned classes; a proxy for "load weight" |

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

The presets are stored in `objective_dsl.PRESETS` and surfaced by
`GET /api/optimize/phase-a/presets`. Each tuple is
`(key, label, summary, dsl_expression)`.

### `balance_curricula` (default)

```text
minimize 50 * total_unused_capacity
       + 100 * total_n_classes
       - 5 * total_n_curricula
       + 5000 * n_under_18
       + 50000 * n_under_10
```

Distributes load across teachers without strongly preferring single-
curriculum concentration. Heavy penalties on under-18h and under-10h
keep cattedre piene.

### `concentrate_curriculum`

```text
minimize 50 * total_unused_capacity
       + 100 * total_n_classes
       + 200 * sum(cross_curricula())
       + 5000 * n_under_18
```

Each teacher works on as few curriculum-tops as possible. Pushes the
bipartite teacher-class graph toward natural clusters which makes the
spectral decomposition (Phase B Stage A bridges) more effective.

### `balance_year`

```text
minimize 50 * total_unused_capacity
       + 100 * total_n_classes
       + sum(teacher_weight)
       + 5000 * n_under_18
```

Uses `teacher_weight = sum(year + curriculum_score)` as a proxy for
"how heavy is this teacher's load" and minimises the sum, indirectly
balancing biennio vs triennio.

### `max_full_cattedre`

```text
minimize sum(under_min_hours(18)) * 5000
       + sum(under_min_hours(10)) * 50000
       + 50 * total_unused_capacity
```

Aggressively penalises any teacher under 18h, near-hard penalty
under 10h. Ideal when filling cattedre is the priority and a bit of
fragmentation is acceptable.

### `minimize_fragmentation`

```text
minimize 200 * total_n_classes
       + 50 * total_unused_capacity
       + 5000 * n_under_18
```

Focused on reducing the number of distinct classes per teacher
(continuita' didattica). Good for student experience.

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
