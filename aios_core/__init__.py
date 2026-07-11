"""
AIOS Core — reusable AI operating-system infrastructure.

Public SDK (stable): the six APIs an application builds on. Import these; do
NOT reach into aios_core.runtime.* (internal). See aios_core/aios_core.md.

    from aios_core import skill, workflow, agent, memory, retrieval, mission
"""
__version__ = "1.0.0"

from .sdk import skill, workflow, agent, memory, retrieval, mission

__all__ = ["skill", "workflow", "agent", "memory", "retrieval", "mission",
           "__version__"]
