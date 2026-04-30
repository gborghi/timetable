"""Service layer: pure data-shaping functions reusable across routers,
background tasks, and tests.

Design:
- Functions take a `Session` and primitive args, return Pydantic models
  or plain dicts. NO side effects (no commit, no logging). Routers
  remain thin shims that route + serialize.
- Each module corresponds to a domain (dataset, monitor, coverage,
  ...). When a router's pure-data helper grows beyond ~30 LoC, move
  it here.

Currently exposes:
- dataset_state.compute_state(db)      -- 9-COUNT scan + active solution
- monitor_events.build_events(db)      -- summary for /api/monitor/events
- monitor_events.summary_counts(rows)  -- counters for /api/monitor/summary

Future extraction targets (Section 2.1 P2 of improvements.md):
- monitor.constraints  -> services/monitor_constraints.py
- monitor.conflicts    -> services/monitor_conflicts.py
- imports.<entity>     -> services/imports/<entity>.py (one per entity)
"""
