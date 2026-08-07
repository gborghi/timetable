# Performance Budgets

Thresholds enforced by `test_perf_budgets.py` (audit T4).

## Current budgets (August 2026)

| Test | Metric | Budget | Rationale |
|---|---|---|---|
| `test_dataset_state_under_5ms` | Wall-clock | < 5 ms | 9 COUNT queries on indexed tables |
| `test_teachers_list_under_25_queries` | SQL queries | < 25 | For 25 teachers; was 200+ before N+1 fix |
| `test_smoke_import_small` | Wall-clock | < 3 s | Import small profile from SQLite |

## Running

```
pytest webui/backend/tests/test_perf_budgets.py -v
```

## Flaky test policy

If a budget test fails in CI:
1. Check if the failure is consistent (re-run)
2. If consistent, investigate the regression
3. If flaky, adjust budget upward by 20% and document reason

## Configuration

Set `PITANTUM_PERF_STRICT=0` to warn instead of fail on budget violations
(useful in CI on shared runners with noisy neighbours).
