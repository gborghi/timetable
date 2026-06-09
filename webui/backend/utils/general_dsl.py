"""Compatibility shim — ``general_dsl`` now lives in ``engine/general_dsl.py``.

The DSL parser/evaluator was relocated into the engine (frontend-agnostic)
to kill the engine -> webui import coupling. This shim aliases the legacy
module name to the single engine module object so every import path --
``general_dsl`` (engine-flat), ``backend.utils.general_dsl`` and
``webui.backend.utils.general_dsl`` -- resolves to ONE module with ONE set
of AST node classes. That collapses the old dual-module ``isinstance``
hazard structurally: trees parsed under any name evaluate cleanly anywhere.

New code should ``import general_dsl`` directly.
"""
import sys

try:
    import general_dsl as _gd
except ImportError:  # engine/ not yet on sys.path -- add it and retry
    import os as _os
    _eng = _os.path.normpath(
        _os.path.join(_os.path.dirname(__file__), "..", "..", "..", "engine"))
    if _eng not in sys.path:
        sys.path.insert(0, _eng)
    import general_dsl as _gd

# Replace this shim module with the real engine module under THIS name, so
# `from backend.utils import general_dsl` (and the webui-prefixed variant)
# both return the same object as the engine-flat `import general_dsl`.
sys.modules[__name__] = _gd
