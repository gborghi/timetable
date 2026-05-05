# piTantum — Audit (English summary)

This audit is based on a code-reading pass with line-precise
evidence (`path:lineno`). Anything not directly measured is
labelled *(non testato / not measured)*. The synthesis maps
realistic Italian-school scenarios onto the codebase as it
stands.

The long-form audit material has been moved to the LaTeX
manual chapters; this Markdown file stays English-only and
terse so it can be linked from code reviews and PR templates.

The full historical text lived under a separator on this file
prior to the bilingual-manual cleanup (commit `401887f`).

---

## Audit data and references

For the comprehensive audit narrative, see:

- `docs/manual/chapters/lessons_learned.tex` — engineering
  decisions and what we learnt from each.
- `docs/manual/chapters/benchmarks.tex` — measured numbers per
  profile and per BP scale.
- `docs/manual/chapters_en/lessons_learned.tex` — English
  summary of the above.
- `tests/benchmarks/results/bp_scalability.json` — reproducible
  HUGE/MEGA BP timings.
