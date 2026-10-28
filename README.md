# piTantum

<p align="center">
  <img src="branding/logo/logo_light.svg" alt="piTantum" width="280">
</p>

Weekly timetable for an **Italian high school**: classes × teachers × rooms, generated with Google OR-Tools **CP-SAT**, then edited in the browser (drag-and-drop, absences, substitutions).

Built for a *liceo* — co-teaching, special-needs support, multiple buildings, Saturday, *potenziamento* (Law 107/2015) — not a generic university sectioning tool.

[Italiano](README.it.md) · **English** (this file)

[![CI](https://github.com/gborghi/timetable/actions/workflows/ci.yml/badge.svg)](https://github.com/gborghi/timetable/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Svelte 5](https://img.shields.io/badge/svelte-5-orange)](https://svelte.dev/)
[![License](https://img.shields.io/badge/license-proprietary-red)](LICENSE)

```bash
git clone https://github.com/gborghi/timetable.git
cd timetable
./webui/start.sh          # macOS / Linux → http://localhost:5173
# Windows: webui\start.bat
```

Python ≥ 3.11 and Node ≥ 20. The first run creates the Python venv and `node_modules` (a few minutes). After that, the same command starts the stack.

Then open **http://localhost:5173**. On the Dashboard, import a ready-made profile (`small` is the fastest) to get a school and a solved timetable to click around.

OS-by-OS notes: [installation guide](docs/installation.md). Stop the stack with `./webui/stop.sh`.

---

**piTantum** (also **Tempus Tantum**) takes the anagrafe of a school — teachers, classes, subjects, rooms, curricula, co-teaching, support hours — and produces a weekly grid. You can lock lessons, drag them, cover absences, and run the solver again.

The name plays on the Greek letter **π**: the two vertical strokes of lowercase pi are the two **T**s of **T**empus **T**antum.

> *Omnia, Lucili, aliena sunt, tempus tantum nostrum est.*
> — Seneca, *Epistulae morales ad Lucilium*, I, 1
>
> “All, Lucilius, comes to us from others; only time is our own.”

Built with AI assistance (Anthropic Claude) on the CP-SAT engine, the FastAPI backend, and the SvelteKit frontend.

## What it does

- **Generate** a weekly timetable with a CP-SAT solver (OR-Tools), including spectral decomposition on large schools and optional metaheuristics (LNS, SA, tabu, ILS, ALNS, VNS, …) on top of the CP-SAT seed.
- **Edit** the grid in the browser: drag-and-drop with a live feasibility check, conflict modal if the slot is taken, unscheduled pool on the side.
- **Cover absences**: mark teachers off, assign substitutes, see uncovered hours.
- **Import** Excel/CSV with downloadable templates, or seed a demo school (`small` … `mega`).
- **Italian-school rules** that generic timetablers skip: *compresenza*, *sostegno*, *potenziamento*, religion vs alternative at the same hour, cross-class language groups, Saturday, two buildings with travel time.

A locked lesson is a hard constraint in the solver, not a post-hoc patch. Impossible locks fail immediately, before a long run.

## After the first launch

1. Open http://localhost:5173.
2. Dashboard → import profile `small` (tick curricula, classrooms, students if you want the full demo).
3. Open **Orario** and drag a lesson; open **Assenze e supplenze** and cover a day.

Backend listens on port 8000, frontend on 5173. Logs: `webui/logs/`.

## Three layers, one repository

| Path | Role |
| --- | --- |
| `engine/` | Solver: CP-SAT, decomposition, metaheuristics |
| `webui/` | FastAPI + SQLite backend, SvelteKit UI, `start.sh` / `start.bat` |
| `schedule/` | Original single-file prototypes (reference only) |

## Tests

```bash
cd webui
export PYTHONPATH="$PWD:$PWD/../engine:$PWD/../schedule"
backend/.venv/bin/pytest backend/tests -m "not slow" -q
```

End-to-end (Cypress) needs a running stack; the supported way is `docker compose -f docker-compose.test.yml`. Details: [`webui/frontend/E2E_README.md`](webui/frontend/E2E_README.md).

## Documentation

- [Installation](docs/installation.md) — Windows, Linux, macOS
- [Manual (PDF, Italian)](docs/manual.pdf) · [English PDF](docs/manual_en.pdf) (the English volume is partly a summary)
- Markdown reference in [`docs/`](docs/): [architecture](docs/architecture.md), [constraints](docs/constraints.md), [workflow](docs/workflow.md), [UI](docs/ui_guide.md), [API](docs/api.md)
- Short how-tos linked from the UI: [`webui/docs/`](webui/docs/)
- Changelog: [`CHANGELOG.md`](CHANGELOG.md)

## Origins

piTantum grew out of ideas by **Fernando Gargiulo**, **Giovanni Borghi**, **Matteo Mariani** and **Stefano Bertozzi**: which constraints actually matter in an Italian school, and the shape of the method. The code in this repository implements those ideas.

## License

Private project; no public license.
