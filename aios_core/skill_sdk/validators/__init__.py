"""Validator entry points (the '/skill_runtime/validators/' deliverable —
homed inside aios_core per D14; see SKILL_VALIDATION.md §Location note).
Each stage is a labeled subset of validate_skill's checks."""
from ..validator import validate_skill, print_report        # noqa: F401
from ..quality import score_skill                            # noqa: F401

STAGES = ["V1 structure", "V2 manifest", "V3 contracts", "V4 schemas",
          "V5 documentation", "V6 examples", "V7 test execution",
          "V8 compatibility", "V9 versioning"]
