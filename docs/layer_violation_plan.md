# Engine → WebUI Layer Violation — Fix Plan (audit A5)

## Status: closed (2026-08-23)

The two remaining engine→ORM holes named by AUDIT.md are closed.

1. `engine/dsl_translator.py` no longer imports `webui.backend.models`.
   `load_all_dsl_constraints` and `special_room_capacity_to_dsl` require
   `_models` from the caller and raise `TypeError` if it is omitted.
   Production webui already passed `_models=models`; engine callers
   (`solve_phase_b_for_day`, `is_hard_feasible`,
   `add_all_dsl_constraints_from_db`, `PhaseBDaySolver`) now accept and
   forward `_models`.
2. `engine/general_dsl.py` already had `build_world()` in
   `webui/backend/engine_io.py` and no longer imports the ORM.
3. `engine/cpsat_assignment_dsl.py` no longer injects `webui/` onto
   `sys.path`. The Phase-A compiler lives in `engine/objective_dsl.py`;
   `webui/backend/utils/objective_dsl.py` is a re-export shim.

Callers that still hold a live Session and want DB-driven DSL must pass
the models module. Engine-only paths should keep using pre-built
`dsl_hard_expressions` / `extra_dsl_expressions` instead of a Session.
