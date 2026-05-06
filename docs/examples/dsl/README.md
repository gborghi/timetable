# DSL examples / Esempi DSL

This directory holds bilingual (Italian + English) walked-through
examples of the generic DSL. Each file picks one realistic
school-timetable scenario and shows it in five forms:

1. **Narrative** — what the coordinator wants and why.
2. **UI path** — where in the SvelteKit app the rule is created.
3. **DSL canonical** — the shortest valid pragma (when one
   exists).
4. **DSL verbose** — the equivalent expressed with raw
   `forall`/`exists`/`count` so the reader can map syntax to
   semantics.
5. **CP-SAT output** — what the compiler emits onto the model.

Questa cartella raccoglie esempi bilingui (italiano + inglese)
sul DSL generico. Ogni file prende uno scenario realistico di
orario scolastico e lo mostra in cinque forme: narrativa, path
UI, forma canonica, forma verbosa, output CP-SAT.

## Files

- [`dsl_no_holes.md`](./dsl_no_holes.md) — no buchi nella classe
  / no class gaps.
- [`dsl_consecutive_hours.md`](./dsl_consecutive_hours.md) — N
  ore consecutive di una materia / N consecutive hours of a
  subject.
- [`dsl_plesso_commuting.md`](./dsl_plesso_commuting.md) —
  spostamento fra plessi / inter-campus travel gap.
- [`dsl_coteach_sostegno.md`](./dsl_coteach_sostegno.md) —
  compresenza chimica + sostegno DVA / chemistry coteach + DVA
  support.
- [`dsl_soft_constraints.md`](./dsl_soft_constraints.md) — SOFT
  in DSL e stato attuale dell'enforcement / SOFT in DSL and
  current enforcement status.

## Conventions

- The numeric weekday encoding is 1 = Monday … 6 = Saturday.
- Hours run 8 to 13 inclusive (six slots per day).
- Class names ("3B"), teacher names ("Rossi"), subject names
  ("Matematica") match the strings stored on `Lesson` rows; if
  a name contains spaces, double-quote it
  (`"Lab Fisica 1"`).
