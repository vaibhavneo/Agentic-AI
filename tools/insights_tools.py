from __future__ import annotations

from insights.pattern_engine import analyze_health_patterns as _analyze_health_patterns


def analyze_health_patterns(profile_id: str) -> dict:
    return _analyze_health_patterns(profile_id)
