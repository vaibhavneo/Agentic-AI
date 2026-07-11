"""
Evaluation suite for the health monitoring agent.
Run: python -m evals.test_scenarios
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import uuid
from agents.orchestrator import build_health_agent, HealthAgentState
from models.alerts import AlertSeverity

SCENARIOS = [
    {
        "name": "Normal vitals — no alerts expected",
        "data": {"patient_id": "EVAL-001", "heart_rate": 70, "systolic_bp": 115,
                 "diastolic_bp": 75, "spo2": 98, "temperature": 36.6,
                 "respiratory_rate": 15, "glucose": 90},
        "expect_severities": [],
        "expect_no_alerts": True,
    },
    {
        "name": "High BP (warning)",
        "data": {"patient_id": "EVAL-002", "heart_rate": 80, "systolic_bp": 155,
                 "diastolic_bp": 95, "spo2": 97, "temperature": 36.8,
                 "respiratory_rate": 16, "glucose": 100},
        "expect_severities": [AlertSeverity.WARNING],
        "expect_no_alerts": False,
    },
    {
        "name": "Critical — low SpO2 + tachycardia",
        "data": {"patient_id": "EVAL-003", "heart_rate": 130, "systolic_bp": 100,
                 "diastolic_bp": 65, "spo2": 87, "temperature": 38.5,
                 "respiratory_rate": 28, "glucose": 110},
        "expect_severities": [AlertSeverity.CRITICAL],
        "expect_no_alerts": False,
    },
    {
        "name": "Hypoglycemia (critical glucose)",
        "data": {"patient_id": "EVAL-004", "heart_rate": 105, "systolic_bp": 110,
                 "diastolic_bp": 70, "spo2": 97, "temperature": 36.5,
                 "respiratory_rate": 18, "glucose": 45},
        "expect_severities": [AlertSeverity.CRITICAL],
        "expect_no_alerts": False,
    },
    {
        "name": "Manual text feed parsing",
        "raw_text": "HR=92 BP=148/94 SpO2=95 Temp=37.9 patient=EVAL-005",
        "expect_severities": [AlertSeverity.WARNING],
        "expect_no_alerts": False,
        "use_manual_parser": True,
    },
]


def run_evals():
    from dotenv import load_dotenv
    load_dotenv()

    agent = build_health_agent()
    passed = 0
    failed = 0

    print("\n" + "="*60)
    print("HEALTH AGENT EVALUATION SUITE")
    print("="*60)

    for i, scenario in enumerate(SCENARIOS, 1):
        print(f"\n[{i}/{len(SCENARIOS)}] {scenario['name']}")

        if scenario.get("use_manual_parser"):
            from extractors.manual_feed import parse_manual_input
            data = parse_manual_input(scenario["raw_text"])
        else:
            data = scenario["data"]

        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        state = HealthAgentState(raw_input=data, input_source="manual")
        result = agent.invoke(state, config)

        alerts = result.get("all_alerts", [])
        severities = {a.severity for a in alerts}

        if scenario["expect_no_alerts"]:
            ok = len(alerts) == 0
        else:
            expected = set(scenario["expect_severities"])
            ok = bool(expected & severities)  # at least one expected severity present

        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"   {status} | Alerts: {len(alerts)} | Severities: {[a.severity for a in alerts]}")
        if not ok:
            print(f"   Expected: {scenario.get('expect_severities')} | Got: {list(severities)}")
            failed += 1
        else:
            passed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed}/{len(SCENARIOS)} passed | {failed} failed")
    print("="*60 + "\n")
    return failed == 0


if __name__ == "__main__":
    success = run_evals()
    sys.exit(0 if success else 1)
