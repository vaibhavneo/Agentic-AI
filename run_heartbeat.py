#!/usr/bin/env python3
"""
Daily heartbeat runner — the cron entry point.

    python3 run_heartbeat.py --tickers AAPL,MSFT,NVDA
    python3 run_heartbeat.py --file watchlist.txt
    python3 run_heartbeat.py --tickers AAPL --status-only

Exit codes: 0 = every ticker frozen, 1 = some failed, 2 = nothing ran.
A non-zero exit is what makes a silent cron failure visible.

Suggested crontab — after the US close, weekdays only:
    30 17 * * 1-5  cd /path/to/stock_agent && /usr/bin/python3 run_heartbeat.py \
                     --file watchlist.txt >> logs/heartbeat.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_REPO = os.path.dirname(os.path.abspath(__file__))


def prepare_env(env_path: str = None) -> None:
    """Make the run's settings explicit instead of a side effect of an import.

    Two things used to happen only because the first ticker imported web.app:
    .env was loaded (so SELFIMPROVE_APPLY=1 reached the loop), and the web
    app's background maintenance scheduler started INSIDE this process — so
    the self-improvement cycle, filing watch and screener ran on a thread
    concurrently with the day's calls. A promotion landing mid-run meant some
    of the day's calls were scored under the old weights and the rest under
    the new, and the filing watch and screener competed with the run for the
    same data vendors. Now the scheduler is off here and its jobs run at fixed
    points (pre_forecast_jobs / post_forecast_jobs). Existing environment
    variables win over .env.
    """
    os.environ.setdefault("MAINTENANCE_SCHEDULER", "0")
    path = env_path or os.path.join(_REPO, ".env")
    if not os.path.exists(path):
        return
    try:
        from dotenv import load_dotenv          # same parser web/app.py uses
        load_dotenv(path, override=False)
        return
    except ImportError:
        pass
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def pre_forecast_jobs() -> list:
    """After grading, before anything is fitted or scored: everything that
    learns from outcomes. Global grading also covers tickers outside the
    watchlist (ad-hoc analyses), which the per-ticker pass does not."""
    from data import maintenance as M
    out = [M.run_job(job, min_interval_sec=0.0)
           for job in (M.GRADE_OUTCOMES, M.GRADE_OPTIONS, M.SELF_IMPROVE)]
    # Challenger scores for any call that lacks them (ad-hoc analyses, or a
    # day the freeze could not write them) — point-in-time, see challengers.py.
    try:
        from evaluation.challengers import reconstruct
        r = reconstruct()
        print(f"[challengers] reconstructed {r['scores_written']} score(s) for "
              f"{r['snapshots_considered']} call(s)"
              + (f"; errors: {r['errors'][:3]}" if r["errors"] else ""), flush=True)
        out.append({"job": "challenger_reconstruct", **r})
    except Exception as e:
        out.append({"job": "challenger_reconstruct", "error": f"{type(e).__name__}: {e}"})
    return out


def post_forecast_jobs() -> list:
    """After the day's calls are frozen: the slow, unrelated upkeep, at its
    usual cadence (a job not yet due reports so and does nothing)."""
    from data import maintenance as M
    return [M.run_job(job, min_interval_sec=M.JOB_INTERVALS.get(job, M.DEFAULT_INTERVAL_SEC))
            for job in (M.FILING_WATCH, M.SCREENER_REFRESH)]


def _load_tickers(args) -> list:
    """Symbols from --file or --tickers, de-duplicated, order preserved.

    Comments are stripped BEFORE splitting on commas. The original order was
    the other way round, which meant a comment containing a comma — e.g.
    "(p50 3.4s, p90 19.8s, max 42.0s)" — was split into fragments where only
    the first still began with '#'. The rest were treated as ticker symbols
    and produced five bogus lookup errors on the first real cron run.
    """
    if args.file:
        tokens = []
        with open(args.file) as f:
            for line in f:
                line = line.split("#", 1)[0]          # comments first
                tokens.extend(line.replace(",", " ").split())
    else:
        tokens = (args.tickers or "").replace(",", " ").split()

    seen, out = set(), []
    for t in tokens:
        t = t.strip().upper()
        # A real symbol is letters, digits, dot or dash. Anything else is
        # almost certainly prose that leaked in, and is better dropped loudly
        # at parse time than sent to a data provider as a lookup.
        if not t or t in seen:
            continue
        if not all(c.isalnum() or c in ".-" for c in t):
            print(f"  skipping unparseable symbol: {t!r}", file=sys.stderr)
            continue
        seen.add(t)
        out.append(t)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily prediction heartbeat")
    ap.add_argument("--tickers", help="comma-separated symbols")
    ap.add_argument("--file", help="file with one symbol per line (# comments ok)")
    ap.add_argument("--as-of", help="date to stamp predictions with (default: now)")
    ap.add_argument("--no-grade", action="store_true", help="skip outcome refresh")
    ap.add_argument("--no-refit", action="store_true", help="skip calibration refit")
    ap.add_argument("--force", action="store_true",
                    help="re-predict even if this ticker already has a call today")
    ap.add_argument("--status-only", action="store_true",
                    help="print the independence report and exit, changing nothing")
    ap.add_argument("--json", action="store_true", help="emit the full result as JSON")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip the verified ledger backup after the run")
    ap.add_argument("--health-only", action="store_true",
                    help="print the flywheel health report and exit, changing nothing")
    ap.add_argument("--scorecard-only", action="store_true",
                    help="print the prediction scorecard and exit, changing nothing")
    ap.add_argument("--no-maintenance", action="store_true",
                    help="skip the self-improvement cycle, options grading, filing watch and screener")
    ap.add_argument("--retry-pause", type=float, default=30.0,
                    help="seconds to wait before retrying failed tickers (default 30)")
    args = ap.parse_args()
    prepare_env()

    from agents.heartbeat import independence_report, run_daily

    if args.scorecard_only:
        from evaluation.report import build, format_text
        print(format_text(build(use_cache=False)))
        return 0

    if args.health_only:
        from agents.flywheel_health import format_report, health_report
        print(format_report(health_report()))
        return 0

    if args.status_only:
        rep = independence_report()
        print("Independent evidence per horizon (what actually gates calibration):")
        for h, r in sorted(rep.items()):
            mark = "OK " if r.get("gate_met") else "-- "
            print(f"  {mark} h={h:>3}d  rows={r.get('rows', 0):<6} "
                  f"effective_n={r.get('effective_n', 0):<6} "
                  f"needed={r.get('needed', '?')}  shortfall={r.get('shortfall', '?')}")
        return 0

    tickers = _load_tickers(args)
    if not tickers:
        print("No tickers given. Use --tickers or --file.", file=sys.stderr)
        return 2

    def progress(r):
        tag = " (retry)" if r.get("retry") else ""
        if r["status"] == "done":
            p1 = (r.get("p_up") or {}).get(1)
            print(f"  {r['ticker']:<6} {str(r.get('action')):<10} "
                  f"composite={r.get('composite')}  p_up(1d)={p1}  {r.get('elapsed_s')}s{tag}")
        else:
            print(f"  {r['ticker']:<6} {r['status'].upper()}: {r.get('reason', '')}"
                  f"  {r.get('elapsed_s')}s{tag}")

    res = run_daily(tickers, grade=not args.no_grade, refit=not args.no_refit,
                    as_of=args.as_of, force=args.force, progress_cb=progress,
                    after_grade=None if args.no_maintenance else pre_forecast_jobs,
                    retry_pause_s=args.retry_pause)

    if args.json:
        print(json.dumps(res, indent=2, default=str))
    else:
        print(f"\nfrozen={res['frozen']} skipped={res['skipped']} "
              f"errors={res['errors']} in {res['elapsed_s']}s")
        if res.get("retried"):
            print(f"retried {res['retried']} failed ticker(s); recovered {res['recovered']}")
        if (res.get("asleep_s") or 0) >= 60:
            print(f"WARNING: the machine slept for {res['asleep_s'] / 60:.0f} min during this run "
                  f"— the elapsed time above is mostly sleep, not work")
        timed = sorted((r for r in res.get("results", []) if r.get("elapsed_s") is not None),
                       key=lambda r: -r["elapsed_s"])[:3]
        if timed:
            print("slowest: " + ", ".join(f"{r['ticker']} {r['elapsed_s']}s" for r in timed))
        if res.get("graded"):
            print(f"graded: {res['graded']['matured']} matured outcomes")
        active = res.get("calibration_active_horizons")
        if active is not None:
            print(f"calibration active at: {active or 'no horizon yet (gate not met)'}")
        beat = res.get("outperform_active_horizons")
        if beat is not None:
            print(f"P(beat SPY) stated at: {beat or 'no horizon yet (gate not met)'}")

    # Back up the ledger AFTER the run, so the snapshot includes what was just
    # frozen. Canonical only: a secondary deployment's rows are not evidence,
    # so backing them up would imply they were.
    if not args.no_backup:
        try:
            from data import prediction_ledger as pl
            if pl.is_canonical_ledger():
                from data.backup import backup_ledger
                b = backup_ledger()
                if b.get("ok"):
                    print(f"backup: verified {b['path']} "
                          f"({b.get('bytes', 0) // 1024} KB)")
                else:
                    print(f"backup: FAILED — {b.get('error')}", file=sys.stderr)
            else:
                print("backup: skipped (secondary ledger is not evidence)")
        except Exception as e:
            print(f"backup: FAILED — {e}", file=sys.stderr)

    # Health report: monitoring only, never influences scoring or calibration.
    try:
        from agents.flywheel_health import format_report, health_report
        print()
        print(format_report(health_report()))
    except Exception as e:
        print(f"health report unavailable: {e}", file=sys.stderr)

    # Scorecard: predictions against outcomes, recorded daily so the trend is
    # answerable. Reporting only, like the health report.
    try:
        from evaluation.history import record
        from evaluation.report import build, format_text
        report = build(use_cache=False)
        print()
        print(format_text(report))
        rec = record(report)
        print(f"  history: {rec.get('recorded', 0)} metrics recorded"
              + (f" ({rec['skipped']})" if rec.get("skipped") else ""))
    except Exception as e:
        print(f"scorecard unavailable: {e}", file=sys.stderr)

    # Publish today's calls for the hosted desk (data/desk_views.py) — the only
    # way OptionsPilot sees fresh desk views. Optional: needs DESK_VIEWS_REPO.
    repo = os.environ.get("DESK_VIEWS_REPO", "").strip()
    if repo:
        try:
            from data.desk_views import publish
            r = publish(repo)
            print(f"desk views: published {r.get('published', 0)} ticker(s) to {repo}"
                  + (f" ({r['skipped']})" if r.get("skipped") else ""))
        except Exception as e:
            print(f"desk views: publish FAILED — {type(e).__name__}: {str(e)[:160]}", file=sys.stderr)

    if not args.no_maintenance:
        print()
        for j in post_forecast_jobs():
            if not j.get("ran"):
                print(f"[maintenance] {j['job']}: {j.get('reason')}")

    # A run where every ticker was already predicted today is a SUCCESS - that
    # is the idempotency guard working, not a failed cron.
    ok = res["errors"] == 0 and (res["frozen"] > 0 or res["skipped"] == len(tickers))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
