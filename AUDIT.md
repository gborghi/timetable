# piTantum — Audit 2026-08-23

Independent code-reading pass of `~/ICT/timetable` at HEAD
`8a914f3` (plus a dirty `optimization.py`). Line-precise where it
matters. Previous audits were read first and then checked against
the tree; several of them are stale.

This file replaces the English stub that only pointed at the LaTeX
manual. Historical audits stay under `docs/` and
`AUDIT_2026-08-15.md` as primary sources; do not treat them as
current.

---

## Verdict

A serious research product, not a prototype. The solver (two-phase
CP-SAT + decompositions + metaheuristics + a single DSL compiler)
is the strongest piece. The backend has been hardened across several
audit rounds (API key, CORS, pickle gate, tenant firewall, truthful
cancel, coverage gate). The frontend covers the whole Italian-school
domain.

The problem is not missing features. It is **growth debt**: three
files of 2.5–6k lines hold the product together, on-tree audits
contradict the code, and Cypress E2E has rotted (13 failed-screenshot
directories).

| Area | Score | Notes |
|---|---|---|
| Solver architecture | 9/10 | One DSL grammar, fail-closed, zero-drift tests |
| Code quality | 6.5/10 | `optimization.py` is a 5977-line god-file |
| Backend tests | 8/10 | 136 pytest files, not “5 integration tests” |
| Frontend / E2E tests | 4.5/10 | Unit tests ok; Cypress in rot |
| Documentation | 8.5/10 | Manual + DSL matrix excellent; old audits lie |
| Security | 7.5/10 | API-key (not JWT); pickle still present, gated |
| UX | 7/10 | Import / Button / empty-states done; DSL editor is a textarea |
| Maintainability | 6/10 | Too much knowledge in 3 files; engine still imports ORM |

**Overall: 7.4/10** — shippable as a single-user localhost tool,
not as school-network SaaS.

---

## Previous audits — what still holds

Read: `AUDIT.md` (old stub), `AUDIT_2026-08-15.md`,
`docs/audit_2026-05-03.md`, `docs/frontend_audit_2026-06-09.md`,
`docs/workflow_audit_2026-05-03.md`,
`docs/migration_cpsat_v2_audit.md`, `docs/layer_violation_plan.md`,
`docs/improvements.md`, `log.md`.

### Stale or wrong

`AUDIT_2026-08-15.md` is the most dangerous: it looks recent and
rehearses June findings without reopening the files.

1. **`/import` is a “non-functional shell”** — false.
   Picker, drop, template, dry-run, report are all there.
   `log.md` (2026-06-09) already called this a misread.
2. **No shared `Button.svelte`** — it exists, with variants and
   `button_variants.test.mjs`.
3. **JWT + bcrypt** — does not exist. Auth is optional
   `APIKeyMiddleware` (`X-API-Key` / Bearer). Unset key = open
   API. Production boot fails closed if the key is missing.
4. **Groups “solver-side wiring” TODO** — the comment is gone.
   C3 groups are modelled; README still admits
   spectral / curriculum / metis / CG ignore `group_assignments`.
5. **“Only 5 engine tests, no E2E”** — 136 backend tests + 37
   Cypress specs + Playwright + 5 root tests. CI runs ruff,
   pytest (fast), svelte-check, vite build, docker buildx.

`docs/improvements.md` still claims “zero test files” and ~4.5k
frontend LoC. Ignore the numbers.

`docs/workflow_audit_2026-05-03.md` still points at `experiments/`.
Those modules live in `engine/` now; branch-and-price has since
been wired (9 pricers, Ryan-Foster).

### Still valid

- **CP-SAT v2 migration audit**: Phase A is IntVar `day_count`;
  Phase B / DSL are slot-Bool. Not drop-in interchangeable.
- **Frontend 2026-06-09 leftovers**: DSL highlight and calendar
  virtualization and pipeline persist are done; no swap / batch
  move.
- **Layer-violation plan**: closed. `build_world()` lives in
  `engine_io.py`; `dsl_translator` requires `_models` from the
  caller and no longer imports the ORM; `objective_dsl` lives in
  `engine/` and `cpsat_assignment_dsl` no longer injects `webui/`.
- **Doc audit 2026-05-03**: `/docs` in-app tab still missing;
  recovery wizard still not a dedicated flow.

---

## Architecture (as of this pass)

```
engine/          CP-SAT + decompositions + meta + DSL compiler
webui/backend/   FastAPI + SQLAlchemy + Alembic + run_manager
webui/frontend/  SvelteKit 5 + Tailwind + TanStack Query
```

DSL path (the cleanest design in the repo):

```
UI / ORM tables
    → dsl_translator → canonical strings
        → general_dsl.parse (AST)
            → DSLConstraintCompiler
                → Mono | PhaseB | 9 BP pricers | RF nodes | post-hoc evaluator
```

Hard rules compile or become no-goods. Soft rules score post-hoc.
Incompatibilities are **not silent** (`constraint_compat`).
Metaheuristics are the universal enforcer.

Italian-school constraints that are actually modelled: shared and
shadow co-teaching, potenziamento (L. 107), intra-class parallel
groups, inter-class StudyGroup, native locks, plessi / commuting,
special-room capacity already in Phase A.

---

## Findings (this pass)

### P0 — fix before any real production use

**1. Auth is a switch, not a user model.**
Without `PITANTUM_API_KEY` every route is open: clear dataset,
import-db, optimize, delete. Fine on `127.0.0.1`. Not fine on a
school LAN. `/docs` stays exempt even with a key. No RBAC, no
per-user audit trail.

**2. Pickle is still RCE, only gated.**
`POST /api/dataset/upload-pickle` does `pickle.loads` when
`PITANTUM_ALLOW_PICKLE_UPLOAD=1` **and** an API key is set.
Tests cover the gate. Production boot *warns* but does not
refuse. The SQLite snapshot path is the safe one; the pickle
endpoint should be removed, not merely switched off.

**3. XOR / derived CHECKs exist only on fresh DBs.**
`ck_assign_class_group_xor`, `ck_coteach_class_group_xor`,
`ck_csp_required_matches_state` live on `models.py`. **No Alembic
revision applies them.** `create_all` does not add CHECKs to
existing tables. A May `timetable.db` can still hold an
Assignment with both `class_id` and `group_id` set;
`engine_io` skips those rows silently. Known since 2026-07-28
(`log.md`).

**4. Cypress E2E is in rot.**
13 spec directories under `webui/frontend/cypress/screenshots/`
with failed PNGs. Opened
`critical_workflows.cy.ts`: the teacher-edit modal is up, the
assert on `.weekly-calendar` fails (calendar not visible —
below the fold or not mounted). E2E runs on PR, **not** on the
default push CI. Green unit tests hide UI regressions.

### P1 — debt that will eat the next months

**5. Three god-files.**

| File | Lines | Role |
|---|---|---|
| `webui/backend/optimization.py` | 5977 | Every pipeline, preflight, move preview, rooms, diagnostics |
| `engine/column_generation.py` | 4549 | BP + 9 pricers + Ryan-Foster |
| `engine/cp_sat_constraint_model.py` | 2630 | OO constraint catalogue |
| `engine/dsl_to_cpsat.py` | 2447 | Compiler |
| `engine/cpsat_v2_timetable.py` | 2424 | Phase A + Phase B legacy |

`optimization.py` has 64 `def`/`class`. It is the only place that
knows how to launch a run. Ruff carves it out of `F841`.

**6. Engine → webui layer still broken in two places.**
See layer-violation note above.

**7. Calendar: 1305 lines, no virtualization.**
`WeeklyCalendarView.svelte` has no virtualize / pagination /
swap / undo. On 60–90 classes the DOM explodes (flagged July:
“3000 nodes / full reload per drag”). Optimistic drag is still
deferred.

**8. Optimize pipeline is not persisted.**
`pipelineList` is in-memory in `optimize/+page.svelte`. Reload
loses order and toggles.

**9. DSL editor is a textarea + 500 ms validate.**
Live `POST /api/constraints/general/validate` and a cookbook of
examples exist. Minimal token colouring is now overlaid on the
textarea (`DslEditor` + `dsl_highlight.mjs`). Still no
autocomplete or squiggle.

**10. Multi-tenant is bait.**
`SingleTenantGuardMiddleware` correctly rejects a spoofed
`X-Tenant-Id` while multi-tenant is off. `PITANTUM_MULTI_TENANT=1`
honours the header **without** scoping queries.
Solution / Lesson / Assignment have no `tenant_id`. Turning the
flag on today is a data leak.

### P2 — honest incompletes, not bugs

- C3 groups: monolithic + temporal only.
- Some native soft families still “TODO d’obiettivo”.
- Phase A cannot migrate 1:1 onto slot-Bool DSL.
- `run_manager` is in-process: gunicorn `-w 1` is mandatory
  (documented in the Dockerfile).
- In-app `/docs` tab: absent.
- Alembic dual-head: **closed** (`d10b2ea8d390`). The July
  “stuck migrations” note is obsolete; the CHECKs are not.

### Security, short

Good: CORS fail-fast in prod, rate-limit on optimize/clear when
keyed, profile path-traversal whitelist + tests, import-db size
and zip-bomb caps, IntegrityError 409 does not leak schema,
parameterized SQLAlchemy. CSP is permissive (`unsafe-inline` +
`unsafe-eval`) and acceptable for a Vite SPA.

Bad / single-user only: default zero auth, pickle still in the
tree, no users / roles, in-memory rate-limit (useless behind a
proxy without a trusted `X-Forwarded-For`).

---

## Tests

- Backend: **136** files under `webui/backend/tests/` (DSL, locks,
  coteach, plessi, import, security, run_manager, coverage gate,
  90-class schools).
- Root `tests/`: 5 files + benchmarks. The engine is exercised
  from the backend suite via flat `PYTHONPATH` imports.
- Frontend unit: `node:test` on `src/**/*.test.mjs`.
- Real hole: unreliable E2E + slow/E2E suites off the default CI.

CI (`.github/workflows/ci.yml`): ruff `webui/` → pytest
`-m "not slow"` → svelte-check + npm test + vite build →
buildx both Dockerfiles. E2E is a separate workflow on PR.

---

## Opinion

The repo was written with AI under human direction, and both
sides show.

Best: fail-closed instead of “return done”, structured warnings
instead of silent drops, HARD-set regression tests, July P0
tranche (truthful cancel, orphan sweep, tenant firewall,
coverage gate, deterministic seeds). Hostile audits were read
and the P0s were closed. That is not theatre.

Worst: files that grow by accretion, markdown audits nobody
invalidates, Cypress screenshots committed as fossils,
`docs/improvements.md` describing a project with zero tests.
User documentation is excellent. Code-status documentation is a
graveyard of expired truths.

Do **not** follow `AUDIT_2026-08-15.md`’s P1 (“finish `/import`”,
“create `Button.svelte`”). Both have been done since June.

---

## Fix order (this file is the queue)

Work through these in order. Do not start the next item until
the current one is in the tree and its tests pass.

1. **P0 CHECK + data audit** — Alembic revision that (a) reports
   XOR / derived-column violators, (b) auto-fixes the derived
   `required` flag, (c) refuses to add CHECKs if XOR rows remain,
   (d) adds the three CHECKs on existing DBs.
2. **P1 split `optimization.py`** — extract cohesive modules
   (preflight, diagnostics, decompositions, rooms, moves);
   leave `optimization.py` as a compatibility facade.
3. **P1 Cypress** — triage the 13 failed specs; fix the real UI
   bugs (teacher-modal calendar first); delete fossil
   screenshots; make the rest skip or pass.
4. **P1 calendar virtualization** — virtualize
   `WeeklyCalendarView` so a 90-class grid does not mount every
   cell.
5. **P1 persist optimize pipeline** — localStorage (or
   `AppState`) for order + per-step toggles.
6. **P1 remove pickle upload** — delete the endpoint; keep
   SQLite snapshot import; keep reading checked-in engine
   pickles as a fallback.
7. **P1 close engine → ORM imports** — pass pre-built dicts
   into `dsl_translator`; stop `cpsat_assignment_dsl` from
   injecting `webui/`.
8. **P2 DSL highlight** — minimal token colouring in the
   general-DSL textarea. Not Monaco.

Out of scope for this pass: multi-tenant, in-app `/docs` tab,
unifying Phase A onto slot-Bool, a dedicated recovery wizard.

---

## References

- `docs/manual/chapters/lessons_learned.tex`
- `docs/manual/chapters/benchmarks.tex`
- `docs/dsl_compliance.md`
- `docs/migration_cpsat_v2_audit.md`
- `docs/frontend_audit_2026-06-09.md`
- `log.md` (June–August implementation diary)
- `tests/benchmarks/results/bp_scalability.json`
