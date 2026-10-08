"""
The desk-views feed: the canonical ledger's latest call per ticker, published
by the daily heartbeat (on the Mac) and merged into the hosted desk's
/api/predictions.

Why it exists: the hosted desk runs LEDGER_ROLE=secondary and never runs the
heartbeat, so its own ledger only holds whatever people happened to analyse on
the website. OptionsPilot reads /api/predictions for direction, found no fresh
view for 29 of its 31 names, and produced no ideas at all. The heartbeat's 75+
daily calls lived only on the Mac.

    publish(repo)      heartbeat → private HF dataset  <repo>/views/latest.json
    fetch(repo)        hosted desk ← the same file, cached 15 minutes
    merge(local, feed) per ticker, the NEWER call wins; nothing is dropped

The feed is optional: with DESK_VIEWS_REPO or a token missing, /api/predictions
serves its local rows exactly as before and says why the feed is absent.
Views are calls (action, confidence labels, price, sector, regime), never
outcomes: those stay with the ledger that graded them.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

FEED_PATH = "views/latest.json"
CACHE_TTL_S = 900
MAX_AGE_DAYS = 10
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def build_views(max_age_days: int = MAX_AGE_DAYS) -> Dict[str, Any]:
    """Latest genuine live call per ticker from this (canonical) ledger."""
    from data import prediction_ledger as pl
    since = (datetime.now() - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
    conn = pl._conn()
    try:
        rows = [dict(r) for r in conn.execute(
            f"""SELECT s.* FROM prediction_snapshots s
                 WHERE s.created_at >= ? {pl._source_where('live')}
                 ORDER BY s.created_at DESC""", (since,)).fetchall()]
    finally:
        conn.close()
    latest: Dict[str, Dict[str, Any]] = {}
    for s in rows:
        if s["ticker"] not in latest:
            latest[s["ticker"]] = _row(s)
    return {"generated_at": datetime.now().isoformat(timespec="seconds"),
            "ledger_role": pl.ledger_role(), "count": len(latest),
            "views": sorted(latest.values(), key=lambda r: r["ticker"])}


def _row(s: Dict[str, Any]) -> Dict[str, Any]:
    """The /api/predictions row shape, so a consumer cannot tell a feed row
    from a local one except by `source`."""
    return {"snapshot_id": s["snapshot_id"], "ticker": s["ticker"], "created_at": s["created_at"],
            "action": s["action"], "price_at_call": s["price_at_call"],
            "confidence": {"thesis": s["conf_thesis"], "data": s["conf_data"],
                           "statistical_edge": s["conf_statistical_edge"],
                           "allocation": s["conf_allocation"]},
            "sector": s["sector"], "regime": s["regime"],
            "strategy_version": s["strategy_version"],
            "decision_fingerprint": s["decision_fingerprint"],
            "outcomes": {}, "fully_matured": False, "source": "heartbeat-feed"}


def publish(repo: str, token: Optional[str] = None, api=None) -> Dict[str, Any]:
    """Upload the views. Canonical ledger only — a secondary deployment's
    rows are not evidence and must not overwrite the feed."""
    from data import prediction_ledger as pl
    if not pl.is_canonical_ledger():
        return {"published": 0, "skipped": "secondary ledger"}
    payload = build_views()
    if api is None:
        from huggingface_hub import HfApi
        api = HfApi(token=token)
    api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
    api.upload_file(path_or_fileobj=json.dumps(payload, default=str).encode(), path_in_repo=FEED_PATH,
                    repo_id=repo, repo_type="dataset",
                    commit_message=f"views {payload['generated_at']} ({payload['count']} tickers)")
    return {"published": payload["count"], "repo": repo}


def fetch(repo: Optional[str] = None, token: Optional[str] = None,
          download=None) -> Dict[str, Any]:
    """{available, views, generated_at, reason}. Never raises."""
    repo = repo if repo is not None else os.environ.get("DESK_VIEWS_REPO", "").strip()
    token = token if token is not None else os.environ.get("HF_TOKEN", "").strip()
    if not repo:
        return {"available": False, "views": [], "reason": "DESK_VIEWS_REPO not set"}
    hit = _cache.get(repo)
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]
    try:
        if download is None:
            from huggingface_hub import hf_hub_download

            def download(r, t):
                return open(hf_hub_download(r, FEED_PATH, repo_type="dataset", token=t or None)).read()
        payload = json.loads(download(repo, token))
        out = {"available": True, "views": payload.get("views") or [],
               "generated_at": payload.get("generated_at"), "reason": None}
    except Exception as e:
        out = {"available": False, "views": [], "reason": f"feed unavailable ({type(e).__name__})"}
    _cache[repo] = (time.time(), out)
    return out


def merge(local: List[Dict[str, Any]], feed: List[Dict[str, Any]],
          ticker: Optional[str] = None) -> List[Dict[str, Any]]:
    """Local rows stay; a feed row is added when it is NEWER than every local
    call for its ticker. Newest first, like the ledger listing."""
    newest: Dict[str, str] = {}
    for r in local:
        t = r.get("ticker")
        if t and str(r.get("created_at") or "") > newest.get(t, ""):
            newest[t] = str(r.get("created_at") or "")
    added = [f for f in feed
             if (ticker is None or f.get("ticker") == ticker)
             and str(f.get("created_at") or "") > newest.get(f.get("ticker"), "")]
    return sorted(local + added, key=lambda r: str(r.get("created_at") or ""), reverse=True)


def clear_cache() -> None:
    _cache.clear()
