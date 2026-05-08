# scripts/

Repo-level helper scripts (not part of the runtime).

## `rebuild_profiles.ps1` — rebuild mock-school profile pickles

The Dashboard card **"Importa un profilo gia\` calcolato"** lists every
profile for which `engine/scripts/data/<profile>/school_<profile>.pkl`
exists. Only `mega` is checked into git; the other profiles
(`small`, `medium`, `big`, `huge`, `superhuge`) are gitignored and must
be regenerated locally.

Without this step the dropdown shows only `mega` and the **Importa**
button cannot be used for the smaller profiles.

### Run

From the repo root, in PowerShell:

```powershell
powershell -File scripts/rebuild_profiles.ps1
```

This rebuilds all five profiles in sequence and prints the resulting
file sizes. Each profile produces two pickles under
`engine/scripts/data/<profile>/`:

| File                    | Producer                           |
|-------------------------|------------------------------------|
| `school_<profile>.pkl`  | `engine/big_mock_school.py`        |
| `profs_<profile>.pkl`   | `engine/cpsat_v2_assignment.py`    |

### Common flags

```powershell
# Only rebuild some profiles
powershell -File scripts/rebuild_profiles.ps1 -Profiles small,medium

# Skip a profile if both its pickles already exist
powershell -File scripts/rebuild_profiles.ps1 -SkipExisting

# Bump the assignment-step CP-SAT budget for the bigger profiles
powershell -File scripts/rebuild_profiles.ps1 -AssignmentTime 180

# Use a specific Python interpreter (e.g. a venv)
powershell -File scripts/rebuild_profiles.ps1 -Python .venv\Scripts\python.exe
```

### Solution pickles (`solution_*.pkl`)

`rebuild_profiles.ps1` does **not** run the full optimisation
pipeline — it only emits `school_*.pkl` + `profs_*.pkl`, which is what
the Dashboard import flow needs to populate classes / teachers /
assignments.

When the import endpoint cannot find a `solution_*` pickle for a
profile, it falls back to parsing
`engine/scripts/output/<profile>/orario_classi_<profile>.xlsx` (the
human-readable schedule output) and reconstructs the lessons from
there. The `mega` profile relies on this path: its xlsx output is
checked into git but the matching pickle is not.

To produce a fresh solution pickle for a profile, run the relevant
pipeline driver in `engine/scripts/`:

```powershell
python engine/scripts/run_full_pipeline.py --profile big
python engine/scripts/run_mega_pipeline.py
```

These can take minutes (small) to tens of minutes (mega), so they
are intentionally **not** invoked by `rebuild_profiles.ps1`.

## `gen_en_stubs.py`, `check_refs.sh`

Doc-tooling helpers; unrelated to the dashboard.
