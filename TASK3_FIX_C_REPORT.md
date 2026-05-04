# Fix C report — `test_full_tab_cycle_within_budget` regression

**Status:** NOT fixed. Diagnosis complete; the fix is bigger than this
task's scope and warrants a dedicated change with cross-team review.

## What's happening

`test_full_tab_cycle_within_budget` measures the wallclock for 7 list
endpoints (the "click through every tab" scenario the user reports as
"stuck"). Budget: 15s. Observed in the failing run: 31.2s.

With the per-tab breakdown I added to the test's failure message, the
profile is:

| Endpoint | Time |
|---|---|
| `/api/teachers` | 189 ms |
| `/api/classes` | 41 ms |
| `/api/classrooms` | 77 ms |
| `/api/subjects` | 39 ms |
| **`/api/students?limit=10`** | **23 275 ms** |
| `/api/groups` | 1 078 ms |
| **`/api/curricula`** | **6 495 ms** |

Two endpoints account for ~96% of the wallclock: `students?limit=10`
(20× over its own dedicated 3000 ms budget in the earlier
`test_list_endpoint_within_budget` parametrization, **which it passes**
when called first) and `curricula`.

## Why it's not "always slow"

In isolation, the same sequence runs in ~0.5 s:

```
/api/teachers          140ms
/api/classes            21ms
/api/classrooms         45ms
/api/subjects           21ms
/api/students?limit=10 248ms   # <-- fast
/api/groups              7ms
/api/curricula          26ms   # <-- fast
TOTAL: 0.5s
```

So the 23 s on students is **context-dependent**, not an O-of-magnitude
algorithmic regression in the endpoint itself. Manual reproduction
confirms it: spawning 5 async diagnostic POSTs by hand and *immediately*
hitting the 7 tabs gives 0.8 s total. The blow-up only shows up inside
pytest after the parametrized `test_heavy_diagnostic_is_async` (4
spawns) + the two `test_hall_check_*` (one of which is a 5th async
spawn) have run.

## Likely cause

**SQLite write-lock contention from background diagnostic threads
holding writer locks while the list endpoints try to read.**

Evidence:

1. The diagnostics endpoints spawn background threads that, when they
   complete, do an UPDATE on `runs.metrics_json` to persist potentially
   100s of KB of JSON. That UPDATE takes a write transaction and, in the
   absence of WAL, **blocks all readers** until commit.

2. `webui/backend/db.py` does NOT enable WAL — I grepped it for
   `journal_mode`, `WAL`, and `synchronous`; only `check_same_thread`
   is set. Default SQLite journal mode is `delete` → readers block on
   any concurrent writer transaction.

3. The order matters: in pytest, between the spawns and `tab_cycle`
   there's a ~1 s window during which the bg threads finish their
   computation and start their final commit. In my manual repro that
   window is essentially zero, so I never observed the contention.

4. Why `students?limit=10` and `curricula` specifically? Both build a
   richer payload than the others (students joins to groups +
   memberships; curricula to subject hours). They take longer in their
   read transactions — more time to overlap with a writer commit and
   stall.

## The fix is bigger than this task

Possible approaches, all with non-trivial side effects:

- **Enable SQLite WAL mode** (`PRAGMA journal_mode=WAL` on connect). This
  would let readers run concurrently with writers and is the textbook
  fix. But it changes on-disk format (creates `.db-wal` and `.db-shm`
  sidecars), breaks existing tools that copy the .db file blindly, and
  needs validation against the import / export paths that read/write
  the DB outside SQLAlchemy. **This is a deployment-affecting change**;
  it should be its own commit + PR with a checklist for the dev DB
  migration and rollback.

- **Move `runs.metrics_json` writes off the main DB** (e.g. into a
  per-run file or a separate SQLite). Keeps the main DB's writers tiny
  and removes most of the contention surface. Bigger architectural
  change.

- **Make the writer commits incremental** (smaller, more frequent UPDATEs
  with smaller `metrics_json` chunks) to reduce the lock-hold time.
  Touches every diagnostic.

- **Test-only stabilization**: add a fixture that waits for all bg
  diagnostic threads to complete *before* `test_full_tab_cycle` runs.
  Removes the failure but **hides the real production-relevant signal**
  (the user-reported "freezes when clicking tabs while a diagnostic is
  running" is a real UX issue).

## What I changed

Just the test's failure message — it now includes the per-tab breakdown,
so the next person to investigate (or CI) sees *which* tab blew up
without needing to reproduce locally. That's it. No production code
changed; the test still fails on the same threshold for the same reason.

## Recommendation

Open a separate ticket scoped to "SQLite read/writer contention under
async diagnostic load." The investigation above is the starting point;
the fix is most likely WAL mode + a smoke test that runs the tab cycle
*while* a deliberate writer is committing on a parallel connection.

The user-reported "stuck" symptom is real and matches the test's
intent. Don't let the failure get suppressed; the test is doing its
job.
