# Pagination Coverage (audit P2)

Routers using `paginated_or_list`: classes, classrooms, curricula, groups,
lessons, monitor, students, subjects, teachers (9/23 routers).

Routers without pagination (acceptable — small datasets or non-list endpoints):
assignments, plessi, constraints, coteaching, coverage, dashboard, dataset,
diagnostics, optimize, schedule, saved_views, bulk, bulk_events, working_hours.

All 9 list routers already have limit/offset + CSV/XLSX export support.
No action needed.
