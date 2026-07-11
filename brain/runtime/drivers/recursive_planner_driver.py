"""DEPRECATED SHIM — the runtime moved to aios_core/runtime (see aios_core/MIGRATION.md). Re-exports preserved so legacy imports and `runtime.drivers.*` entrypoints keep working. New code: import from aios_core / aios_core.sdk."""
import sys as _sys
from pathlib import Path as _P
_root = str(_P(__file__).resolve().parents[2])
if _root not in _sys.path: _sys.path.insert(0, _root)
from aios_core.runtime.drivers.recursive_planner_driver import *  # noqa
import aios_core.runtime.drivers.recursive_planner_driver as _canonical
import sys as _s; _s.modules[__name__] = _canonical
