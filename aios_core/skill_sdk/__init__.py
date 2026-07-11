"""AIOS Skill SDK — authoring, validation, quality scoring, capability
descriptors for skills. Docs: SKILL_SDK.md · SKILL_AUTHOR_GUIDE.md ·
SKILL_VALIDATION.md · CAPABILITY_DESCRIPTOR.md · templates/skill/."""
from .validator import validate_skill, print_report
from .quality import score_skill
from . import capability

__all__ = ["validate_skill", "print_report", "score_skill", "capability"]
