# Engine → WebUI Layer Violation — Fix Plan (audit A5)

## Current violations

1. `engine/dsl_translator.py` imports `webui.backend.models` (lines 274, 764)
2. `engine/general_dsl.py` imports `webui.backend.models` (lines 727, 740)
3. `engine/cpsat_assignment_dsl.py` injects webui path (line 36)

## Root cause

The `build_world()` function needs entity name lookups that currently go through
the ORM. The engine should receive pre-built dictionaries instead.

## Fix plan

1. Move `build_world()` from `engine/general_dsl.py` to `webui/backend/engine_io.py`
   (where all other DB→dict conversions live)
2. `engine_io` pre-resolves all entity names into a `world` dict
3. Pass `world` as a parameter to `general_dsl._eval()` and `dsl_translator.*_to_dsl()`
4. Remove all `webui.backend` imports from engine/

## Estimated effort: 2-3 days
## Risk: Medium (changes the DSL evaluation interface)
