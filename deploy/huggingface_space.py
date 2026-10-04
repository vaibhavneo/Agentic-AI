#!/usr/bin/env python3
"""
Deploy this app to a Hugging Face Space — the free replacement for Railway.

Free "CPU basic" hardware is 2 vCPU / 16 GB RAM (Render's free tier is 512 MB /
0.1 CPU, and a full stock analysis peaks at ~320 MB with one worker). A free
Space sleeps after 48 h without visitors and has no persistent disk, so the
ledger and caches rebuild after a restart; LEDGER_ROLE=secondary says so.

Once, by you:  a free account at https://huggingface.co, then
    hf auth login            # paste a token with "write" access
Then:
    python3 deploy/huggingface_space.py                 # creates/updates <you>/stock-agent
    python3 deploy/huggingface_space.py --dry-run       # shows what would happen, changes nothing

What it does:
  - uploads exactly the files git tracks at HEAD (git archive), so .env files,
    OAuth tokens and local databases can't ship;
  - adds the Space's README front matter (Docker SDK, port 7860);
  - sets secrets/variables, taking each value from the environment, then .env,
    then `railway variables` — only NAMES are ever printed;
  - leaves the Robinhood connection OFF (ROBINHOOD_CLIENT_ID unset): the broker
    routes have no login yet, and a public Space must not expose holdings;
  - waits for the build and checks /api/status.
"""
from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECRET_NAMES = ["DEEPSEEK_API_KEY", "ALPHAVANTAGE_API_KEY", "FINNHUB_API_KEY", "FMP_API_KEY",
                "TIINGO_API_KEY", "SEC_USER_AGENT", "MCP_TOKEN", "OPTIONSPILOT_ACCESS_CODE"]
VARIABLE_NAMES = ["SELFIMPROVE_APPLY", "OPTIONSPILOT_BASE_URL"]
FIXED_VARIABLES = {"LEDGER_ROLE": "secondary"}
# Deliberately not carried over: ROBINHOOD_CLIENT_ID (see above), and Railway's
# volume paths (BROKER_TOKEN_DIR, FIL_CACHE_DIR, STOCK_AGENT_DB_PATH), which point
# at a disk a free Space doesn't have.

FRONT_MATTER = """---
title: Stock Agent AI
emoji: 📈
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: Multi-agent stock research desk
---

"""


def _dotenv() -> dict:
    out = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _railway() -> dict:
    """Production values from Railway, if its CLI is linked here. Read even
    while the trial is expired; never printed."""
    if not shutil.which("railway"):
        return {}
    try:
        out = subprocess.run(["railway", "variables", "--service", "Agentic-AI", "--kv"], cwd=ROOT,
                             capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return {}
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def resolve(names: list[str]) -> dict[str, tuple[str, str]]:
    """{name: (value, source)} for the names that have a value somewhere."""
    sources = [("environment", dict(os.environ)), (".env", _dotenv()), ("railway", _railway())]
    found = {}
    for name in names:
        for label, values in sources:
            if values.get(name):
                found[name] = (values[name], label)
                break
    return found


def stage_files(dest: Path) -> tuple[int, int]:
    """git-tracked files at HEAD into dest, plus the Space README. (files, bytes)."""
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "Dockerfile", ".dockerignore", "requirements.txt",
                            "web", "agents", "deploy"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty:
        print("note: uncommitted changes are NOT deployed (only HEAD is):\n" + dirty)
    archive = dest.parent / "head.tar"
    subprocess.run(["git", "archive", "--format=tar", "-o", str(archive), "HEAD"], cwd=ROOT, check=True)
    with tarfile.open(archive) as t:
        t.extractall(dest)
    archive.unlink()
    readme = dest / "README.md"
    body = readme.read_text() if readme.exists() else (
        "# Stock Agent AI\n\nMulti-agent stock research desk. Source: "
        "https://github.com/vaibhavneo/Stock-Analysis-Multi-Agent-Desk\n")
    readme.write_text(FRONT_MATTER + body)
    files = [p for p in dest.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space", default="stock-agent", help="Space name (default: stock-agent)")
    ap.add_argument("--private", action="store_true", help="private Space (only you can open it)")
    ap.add_argument("--dry-run", action="store_true", help="show the plan; create and upload nothing")
    ap.add_argument("--no-wait", action="store_true", help="don't wait for the build")
    args = ap.parse_args()

    from huggingface_hub import HfApi
    api = HfApi()
    try:
        user = api.whoami()["name"]
    except Exception:
        if not args.dry_run:
            print("Not logged in to Hugging Face. Run:  hf auth login   (paste a token with write access)")
            return 2
        user = "<your-hf-username>"
    repo_id = f"{user}/{args.space}"

    secret_vals = resolve(SECRET_NAMES)
    var_vals = resolve(VARIABLE_NAMES)
    print(f"Space: {repo_id} ({'private' if args.private else 'public'}, Docker, free CPU basic)")
    for name in SECRET_NAMES:
        print(f"  secret   {name:26s} {'from ' + secret_vals[name][1] if name in secret_vals else '— not set anywhere, skipped'}")
    print(f"  secret   {'FLASK_SECRET_KEY':26s} newly generated")
    for name in VARIABLE_NAMES:
        print(f"  variable {name:26s} {'from ' + var_vals[name][1] if name in var_vals else '— not set, skipped'}")
    for name, v in FIXED_VARIABLES.items():
        print(f"  variable {name:26s} = {v}")
    print(f"  off      {'ROBINHOOD_CLIENT_ID':26s} broker routes have no login yet")

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "space"
        stage.mkdir()
        n, size = stage_files(stage)
        leaked = [p.name for p in stage.rglob("*") if p.name in ("broker_tokens.json", ".env")
                  or p.suffix in (".db", ".sqlite") or (p.name.startswith(".env.") and not p.name.endswith(".example"))]
        if leaked:
            print(f"refusing to deploy: sensitive files in the upload set: {leaked}")
            return 3
        print(f"  upload   {n} git-tracked files, {size / 1e6:.0f} MB (HEAD)")
        if args.dry_run:
            print("dry run — nothing created or uploaded.")
            return 0

        api.create_repo(repo_id, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True)
        for name, (value, _src) in secret_vals.items():
            api.add_space_secret(repo_id, name, value)
        api.add_space_secret(repo_id, "FLASK_SECRET_KEY", secrets.token_hex(32))
        for name, (value, _src) in var_vals.items():
            api.add_space_variable(repo_id, name, value)
        for name, value in FIXED_VARIABLES.items():
            api.add_space_variable(repo_id, name, value)
        print("uploading…")
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        api.upload_folder(folder_path=str(stage), repo_id=repo_id, repo_type="space",
                          commit_message=f"Deploy {head}", delete_patterns=["*"])

    host = getattr(api.space_info(repo_id), "host", None) or f"https://{repo_id.replace('/', '-').lower()}.hf.space"
    print(f"Space page: https://huggingface.co/spaces/{repo_id}\nApp URL:    {host}")
    if args.no_wait:
        return 0
    last, deadline = None, time.time() + 40 * 60
    while time.time() < deadline:
        stage_now = api.get_space_runtime(repo_id).stage
        if stage_now != last:
            print(f"  {time.strftime('%H:%M:%S')} {stage_now}")
            last = stage_now
        if stage_now == "RUNNING":
            break
        if stage_now in ("BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE"):
            print("Build failed — see the Logs tab on the Space page.")
            return 4
        time.sleep(20)
    else:
        print("Still building after 40 minutes — check the Space page.")
        return 5
    import httpx
    for _ in range(30):
        try:
            r = httpx.get(f"{host}/api/status", timeout=30)
            if r.status_code == 200:
                print(f"Live: {host}  (/api/status 200)")
                return 0
        except Exception:
            pass
        time.sleep(10)
    print(f"Space is RUNNING but {host}/api/status didn't answer yet — give it a minute.")
    return 6


if __name__ == "__main__":
    sys.exit(main())
