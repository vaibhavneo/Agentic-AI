from __future__ import annotations
"""
Health Vitals Monitoring Agent
================================
Production-ready agentic AI system that:
  - Accepts inputs from: screenshot, PDF, DOCX, manual data feed
  - Extracts structured vitals using Claude vision/text
  - Runs rule-based threshold checks + LLM trend analysis
  - Dispatches prioritized alerts in real-time

Usage:
  python main.py --demo
  python main.py --input manual --data "HR=88 BP=145/92 SpO2=94 patient=P001"
  python main.py --input manual --data '{"heart_rate":88,"spo2":94,"patient_id":"P001"}'
  python main.py --input screenshot --path /path/to/monitor.png
  python main.py --input pdf --path /path/to/report.pdf
  python main.py --input docx --path /path/to/notes.docx
  python main.py --watch --input manual --data "HR=88 BP=140/90" --interval 30
"""

import argparse
import logging
import sys
import time
import uuid

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/health_agent.log"),
    ],
)
logger = logging.getLogger("health_agent")
console = Console()


def run_analysis(input_source: str, data: dict, session_id: str = None) -> dict:
    """Run the full health monitoring pipeline for one reading."""
    from agents.orchestrator import build_health_agent, HealthAgentState
    agent = build_health_agent()
    sid = session_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": sid}}
    state = HealthAgentState(raw_input=data, input_source=input_source)
    return agent.invoke(state, config)


def extract_input(args) -> tuple:
    if args.input == "screenshot":
        from extractors.screenshot import extract_from_screenshot
        console.print("[cyan]Extracting vitals from screenshot: " + args.path + "[/cyan]")
        return args.input, extract_from_screenshot(args.path)

    elif args.input == "pdf":
        from extractors.pdf_extractor import extract_from_pdf
        console.print("[cyan]Extracting vitals from PDF: " + args.path + "[/cyan]")
        return args.input, extract_from_pdf(args.path)

    elif args.input == "docx":
        from extractors.docx_extractor import extract_from_docx
        console.print("[cyan]Extracting vitals from DOCX: " + args.path + "[/cyan]")
        return args.input, extract_from_docx(args.path)

    elif args.input == "manual":
        from extractors.manual_feed import parse_manual_input
        data = parse_manual_input(args.data)
        console.print("[cyan]Manual input: " + str(data) + "[/cyan]")
        return args.input, data

    raise ValueError("Unknown input type: " + args.input)


def print_results(state: dict) -> None:
    """Pretty-print analysis results to console."""
    alerts = state.get("all_alerts", [])
    summary = state.get("llm_summary", "")
    reading = state.get("reading")

    if reading:
        body = "[bold]" + reading.summary() + "[/bold]"
        if summary:
            body = body + "\n\n" + summary
        console.print(Panel(body, title="[green]Health Analysis Report[/green]", border_style="green"))

    if not alerts:
        console.print("[bold green]All vitals within normal range. No alerts.[/bold green]\n")
        return

    table = Table(title="Alerts", box=box.ROUNDED, show_lines=True)
    table.add_column("Severity", style="bold", width=10)
    table.add_column("Vital", width=18)
    table.add_column("Value", width=10)
    table.add_column("Source", width=12)
    table.add_column("Message", max_width=40)
    table.add_column("Recommendation", max_width=40)

    color_map = {"CRITICAL": "red", "WARNING": "yellow", "INFO": "blue"}
    for alert in alerts:
        color = color_map.get(alert.severity, "white")
        table.add_row(
            "[" + color + "]" + alert.severity + "[/" + color + "]",
            alert.vital_name,
            str(alert.vital_value),
            alert.triggered_by,
            alert.message,
            alert.recommendation,
        )

    console.print(table)
    n_dispatched = len(state.get("dispatched_alerts", []))
    console.print("\n[bold]Total: " + str(len(alerts)) + " alerts | Dispatched: " + str(n_dispatched) + "[/bold]\n")


def watch_mode(args, interval: int) -> None:
    console.print("[bold cyan]Watch mode: checking every " + str(interval) + "s. Ctrl+C to stop.[/bold cyan]\n")
    session_id = str(uuid.uuid4())
    cycle = 0
    while True:
        cycle += 1
        console.rule("[dim]Cycle " + str(cycle) + " - " + time.strftime("%Y-%m-%d %H:%M:%S") + "[/dim]")
        try:
            source, data = extract_input(args)
            result = run_analysis(source, data, session_id=session_id)
            print_results(result)
        except KeyboardInterrupt:
            console.print("\n[yellow]Watch mode stopped.[/yellow]")
            break
        except Exception as e:
            logger.error("Cycle %d error: %s", cycle, e)
            console.print("[red]Error in cycle " + str(cycle) + ": " + str(e) + "[/red]")
        time.sleep(interval)


def run_demo() -> None:
    """Run 3 built-in demo scenarios."""
    from agents.orchestrator import build_health_agent, HealthAgentState

    scenarios = [
        {
            "name": "NORMAL VITALS",
            "data": {"patient_id": "DEMO-001", "heart_rate": 72, "systolic_bp": 118,
                     "diastolic_bp": 76, "spo2": 98, "temperature": 36.6,
                     "respiratory_rate": 16, "glucose": 95},
        },
        {
            "name": "WARNING - Elevated BP + Borderline SpO2",
            "data": {"patient_id": "DEMO-001", "heart_rate": 95, "systolic_bp": 152,
                     "diastolic_bp": 96, "spo2": 94, "temperature": 37.8,
                     "respiratory_rate": 22, "glucose": 155},
        },
        {
            "name": "CRITICAL - Multiple Vitals at Risk",
            "data": {"patient_id": "DEMO-001", "heart_rate": 38, "systolic_bp": 85,
                     "diastolic_bp": 52, "spo2": 88, "temperature": 39.8,
                     "respiratory_rate": 32, "glucose": 48},
        },
    ]

    agent = build_health_agent()
    for i, scenario in enumerate(scenarios, 1):
        console.rule("[bold]Demo " + str(i) + ": " + scenario["name"] + "[/bold]")
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        state = HealthAgentState(raw_input=scenario["data"], input_source="manual")
        result = agent.invoke(state, config)
        print_results(result)
        time.sleep(0.3)


def main():
    parser = argparse.ArgumentParser(description="Health Vitals Monitoring Agent")
    parser.add_argument("--input", choices=["screenshot", "pdf", "docx", "manual"], default="manual")
    parser.add_argument("--path", help="File path (screenshot/pdf/docx)")
    parser.add_argument("--data", help="Manual vitals (JSON or key=value string)")
    parser.add_argument("--watch", action="store_true", help="Continuous monitoring mode")
    parser.add_argument("--interval", type=int, default=30, help="Watch interval in seconds")
    parser.add_argument("--demo", action="store_true", help="Run built-in demo scenarios")
    args = parser.parse_args()

    if args.demo:
        run_demo()
        return
    if args.watch:
        watch_mode(args, args.interval)
        return

    source, data = extract_input(args)
    result = run_analysis(source, data)
    print_results(result)


if __name__ == "__main__":
    main()
