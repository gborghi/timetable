"""Generate English stub chapters for the manual.

Each stub is a brief English summary + pointer to the Italian
chapter for the full text. High-priority chapters get fuller
translations in separate edits.
"""
from __future__ import annotations

import os

CHAPTERS: dict[str, tuple[str, str | None]] = {
    "prologo": ("Introduction", None),
    "problema_timetabling": (
        "The timetabling problem",
        "Formal statement of the school timetabling problem: "
        "cattedre as (teacher, class, subject) triples; weekly "
        "hour distribution across days and time slots; HARD "
        "constraints (no class/teacher overlap, hour coverage, "
        "consecutive hours starting at 8 with presence at h=11) "
        "and SOFT objectives (daily uniformity, free-day "
        "preferences). NP-hardness and the rationale for "
        "decomposition + metaheuristics."),
    "panoramica_pitantum": (
        "piTantum overview",
        "Three-tier architecture: engine (CP-SAT solver core), "
        "backend (FastAPI + SQLite), frontend (SvelteKit). "
        "Pipelines exposed as async runs via /api/optimize/*. "
        "The 16 UI tabs covering registry, constraints, "
        "generation, manual editing, daily operations."),
    "orario_oggetto_strutturale": (
        "The timetable as a structural object",
        "The Lesson dict {(teacher, class, subject, day, hour): 1} "
        "as the canonical representation; round-trip with the "
        "Solution table; the role of dc_value in encoding "
        "Phase A's day-count distribution."),
    "installazione": (
        "Installation",
        "Python 3.13 + ortools + scipy + matplotlib + FastAPI + "
        "SQLAlchemy + Alembic; SvelteKit for the frontend. "
        "Cypress + Playwright for E2E. docker-compose.test.yml "
        "orchestrates the test stack."),
    "vincoli": (
        "Constraints (HARD + SOFT)",
        "HARD: no overlap (teacher in one class at a time, class "
        "with one teacher per slot), hour coverage of all "
        "cattedre, daily start at h=8, consecutive hours, "
        "presence at h=11 (the H1/H2/H3 trio). Native locks. "
        "C1 (compresenza/coteach), C2 (sostegno DVA), C3 "
        "(potenziamento, parallel intra-class, group "
        "inter-class). SOFT: daily uniformity, free-day "
        "preferences, sixth-hour penalties, five/one day load."),
    "workflow_di_ottimizzazione": (
        "Optimization workflow",
        "The pipeline orchestrator: Hall pre-check, Phase A "
        "(assignment + day-count), Phase B (per-day slot "
        "placement), optional metaheuristic post-processing "
        "(LNS / ALNS / SA / TS / ILS / VNS), classroom "
        "assignment."),
    "guida_ui": (
        "UI guide",
        "Tour of the 16 SvelteKit tabs: dashboard, anagrafica "
        "(teachers/classes/students/classrooms), assignments, "
        "monitor, optimize (with iterative-diversified and "
        "branch-and-price modes), diagnostics, runs."),
    "launcher": (
        "Launcher",
        "Single-binary launcher script that bootstraps the venv, "
        "runs the alembic migrations, starts uvicorn + the "
        "SvelteKit dev server."),
    "metodo_cpsat": (
        "CP-SAT method",
        "Model formulation in OR-tools cp_model: BoolVar "
        "slot[(t, cl, s, d, h)], hour coverage equalities, "
        "no-overlap constraints, soft penalties as objective "
        "coefficients. Integer scaling for the fractional duals "
        "in BP."),
    "metodo_spettrale": (
        "Spectral decomposition",
        "Bipartite class-teacher graph; normalised Laplacian "
        "eigendecomposition; spectral clustering into K balanced "
        "clusters; per-cluster CP-SAT + ricucitura with the "
        "bridge teachers."),
    "metodo_metaeuristiche": (
        "Metaheuristics",
        "LNS (random_window, day_cluster, worst_fit_day, "
        "teacher_day, classroom_day, single_class_week destroy "
        "ops + cp_sat_window repair), Adaptive LNS, Simulated "
        "Annealing, Tabu Search, Iterated Local Search, Variable "
        "Neighborhood Search."),
    "metodo_hall": (
        "Hall pre-check",
        "Hall's marriage theorem applied to the bipartite (class, "
        "subject) -> qualified-teachers graph as a fast pre-check "
        "(1-100 ms) before launching Phase A."),
    "metodo_lagrangian": (
        "Lagrangian relaxation and Column Generation",
        "Dualisation of the bridge constraints between clusters; "
        "subgradient ascent on the Lagrangian multipliers; "
        "SA-based per-iteration refinement. Column Generation: "
        "master LP + per-teacher CP-SAT pricing; Branch-and-Price "
        "extension with all 9 granularities (see "
        "ch.~\\ref{ch:tecniche_avanzate})."),
    "metodo_montecarlo": (
        "Monte Carlo sensitivity",
        "Random subset sampling to estimate the Hall violation "
        "probability under perturbations; useful as a pre-check "
        "robustness indicator."),
    "metodo_grafo": (
        "Graph-based diagnostics",
        "Bipartite class-teacher graph: density, modularity "
        "(Newman-Girvan), betweenness centrality. Identifies "
        "bridge teachers and structural bottlenecks."),
    "metodo_statistica": (
        "Statistical diagnostics",
        "Three regressions on lesson-level data with statsmodels "
        "(p-values, effect sizes); five distribution fits with "
        "KS / chi-square tests."),
    "metodo_dsl": (
        "Constraint DSL method",
        "The objective_dsl and general_dsl languages for "
        "expressing soft objectives and HARD constraints in a "
        "compact symbolic form, parsed at runtime and translated "
        "to CP-SAT constraints."),
    "architettura": (
        "Architecture",
        "Three tiers (engine, backend, frontend) with the data "
        "flow: registry -> assignment -> dc_value -> Phase B -> "
        "integer recovery -> persistence -> UI. Async runs "
        "orchestrated via the /api/optimize/* endpoints and the "
        "SQLAlchemy `runs` table."),
    "modello_dati": (
        "Data model",
        "Tables: schools, school_classes, teachers, subjects, "
        "classrooms, assignments, lessons, runs, study_groups, "
        "coteach_groups, parallel_groups, support_assignments, "
        "locks. SQLAlchemy 2.0 ORM. Alembic migrations + "
        "lightweight in-code migrations in db.py."),
    "dsl_generico_per_i_vincoli": (
        "Generic constraint DSL",
        "The general_dsl subset for HARD constraint authoring: "
        "predicates over (teacher, class, subject, day, hour), "
        "boolean combinators, compilation to CP-SAT constraints."),
    "tecniche_di_ottimizzazione_avanzate": (
        "Advanced optimization techniques",
        "ALNS, VNS, Hall pre-check, Column Generation + full "
        "Branch-and-Price with 9 granularities (teacher, "
        "teacher-day, teacher-class, teacher-class-subject, "
        "teacher-subject, class, class-day, day, curriculum). "
        "Four scalability techniques: Ryan-Foster recursive tree, "
        "box-step dual stabilization, column management with "
        "RC-age purge, parallel pricing via ProcessPoolExecutor. "
        "Lagrangian relaxation."),
    "diagnostica_statistica": (
        "Statistical diagnostics tab",
        "The Diagnostics tab in the UI: Monte Carlo sensitivity, "
        "bipartite graph metrics, statsmodels regressions, "
        "distribution fits."),
    "api_rest": (
        "REST API",
        "The /api/* endpoints: /api/optimize/* (Phase A, Phase B, "
        "decompositions, Column Generation with all 9 BP "
        "granularities), /api/diagnostics/*, /api/dashboard/*, "
        "/api/monitor/*. See docs/api.md for the full list."),
    "estendere_il_sistema": (
        "Extending the system",
        "Adding a new constraint, a new metaheuristic "
        "destroy/repair op, a new decomposition strategy, a new "
        "UI tab. The hooks the test suite exercises."),
    "repository_github": (
        "Repository on GitHub",
        "Layout: engine/, webui/backend/, webui/frontend/, docs/, "
        "schedule/, scripts/, tests/. CI workflows, PR "
        "conventions, issue tracker."),
    "benchmarks": (
        "Benchmarks",
        "The six profiles: small / medium / big / huge / "
        "superhuge / mega. End-to-end pipeline times. SOFT "
        "objective components per profile. Hall pre-check times "
        "(negligible). Spectral speedup. Branch-and-Price "
        "scalability on HUGE / MEGA (synthetic): HUGE 2.57s, "
        "MEGA 5.95s, both HARD-feasible. When BP is worth "
        "activating."),
    "lessons_learned": (
        "Lessons learned",
        "Engineering anecdotes from building piTantum: what "
        "worked, what didn't, why CP-SAT was chosen over MILP, "
        "why we layered decomposition + metaheuristics, why the "
        "Italian-specific HARD constraints (H1/H2/H3) deserve "
        "special treatment."),
    "glossario_discorsivo": (
        "Glossary (narrative form)",
        "Discursive definitions of all the terminology used in "
        "the manual: cattedra, sostegno, potenziamento, "
        "compresenza, indirizzo, plesso (when introduced), "
        "dc_value, master LP variant 1 / variant 2, Achterberg "
        "score, EWMA, ProcessPoolExecutor."),
    "reference": (
        "Reference",
        "Reference tables: HARD constraint codes, SOFT weights, "
        "mode/granularity values, file locations, API endpoints, "
        "configuration keys."),
    "introduzione": (
        "Introduction (alternative)",
        "Alternative entry point chapter; the canonical "
        "introduction is in `prologo`."),
}

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(
    os.path.join(HERE, "..", "docs", "manual", "chapters_en"))
os.makedirs(OUT, exist_ok=True)

for name, (en_title, summary) in CHAPTERS.items():
    if name == "prologo":
        continue
    path = os.path.join(OUT, f"{name}.tex")
    if os.path.exists(path):
        continue
    label = "ch:" + name + "_en"
    body = (
        f"\\chapter{{{en_title}}}\n"
        f"\\label{{{label}}}\n\n"
        f"{summary or '(English summary pending.)'}\n\n"
        f"\\medskip\n\\noindent\n"
        f"\\textit{{This chapter is an English summary of the "
        f"corresponding Italian chapter. The full text remains "
        f"in the Italian edition "
        f"(\\texttt{{docs/manual/chapters/{name}.tex}}). "
        f"For the implementation references see the engine "
        f"modules in \\texttt{{engine/}} and the API "
        f"documentation at \\texttt{{docs/api.md}}.}}\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"wrote {path}")

print("done.")
