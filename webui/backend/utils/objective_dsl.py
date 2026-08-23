"""Compatibility shim — ``objective_dsl`` now lives in ``engine/objective_dsl.py``.

The Phase-A objective compiler was relocated into the engine so
``cpsat_assignment_dsl`` can import a sibling instead of injecting
``webui/`` onto ``sys.path``. This shim aliases the legacy module
name to the single engine module object so every import path --
``objective_dsl`` (engine-flat), ``backend.utils.objective_dsl`` and
``webui.backend.utils.objective_dsl`` -- resolves to ONE module.

New code should ``import objective_dsl`` from the engine.
"""
import sys

try:
    import objective_dsl as _od
except ImportError:  # engine/ not yet on sys.path -- add it and retry
    import os as _os
    _eng = _os.path.normpath(
        _os.path.join(_os.path.dirname(__file__), "..", "..", "..", "engine"))
    if _eng not in sys.path:
        sys.path.insert(0, _eng)
    import objective_dsl as _od

# Replace this shim module with the real engine module under THIS name, so
# `from backend.utils import objective_dsl` (and the webui-prefixed variant)
# both return the same object as the engine-flat `import objective_dsl`.
sys.modules[__name__] = _od
