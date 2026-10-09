"""
live_feed — scheduled live data streams for an app's agents and its UI.

Vendored beside agent_core.py and live_knowledge.py (source: agent-hosting/
shared/; sync with shared/sync.py). Standard library only.

    hub = FeedHub([QuoteFeed(lambda: ["AAPL", "NVDA"]), FredFeed(["DGS10", "VIXCLS"])],
                  store=knowledge_store, db_path="data/live_events.db")
    hub.start()                       # one daemon thread; idempotent
    hub.latest("quote:NVDA")          # newest event for a key
    hub.snapshot()                    # every key's newest event + per-feed health
    hub.sse(kinds=["quote"])          # generator of Server-Sent Events for a Flask Response

How it behaves:

  - Each Feed has an interval, and a slower one when its market is closed
    (US equities: 09:30-16:00 New York, Mon-Fri; holidays are not modelled —
    a holiday just polls at the open-market rate and sees no change).
  - A failing feed backs off exponentially (x2 per failure, capped at x16) and
    its health is visible in snapshot(); one feed failing never stops another.
  - An event is PUBLISHED only when its value changed (per key), so a quiet
    market does not spam subscribers — but every poll refreshes `seen_at`.
  - Every published event is kept in a ring buffer (for SSE replay by id),
    appended to a SQLite event log (bounded), and — when it carries text and a
    knowledge store is attached — written into the store as a short-TTL fact,
    so the RAG pipeline and every agent read the freshest number without a
    fetch of their own.

The feeds poll public, keyless endpoints at modest rates. Nothing here trades
or writes anywhere but the app's own data folder.
"""
from __future__ import annotations

import collections
import concurrent.futures as cf
import csv
import datetime as dt
import hashlib
import io
import json
import queue
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

try:
    from zoneinfo import ZoneInfo
    _NY = ZoneInfo("America/New_York")
except Exception:                                   # pragma: no cover
    _NY = None

UA = "live-knowledge/1.0"     # Yahoo's chart API answers this; browser and default agents get 429


@dataclass
class Event:
    feed: str
    kind: str                 # quote | rate | headline | sky | …
    key: str                  # stable identity, e.g. "quote:NVDA"
    value: Dict[str, Any]
    text: str = ""            # one plain sentence describing it (what the knowledge store indexes)
    ts: float = field(default_factory=time.time)
    source: str = ""
    url: str = ""
    ttl_s: float = 900
    id: int = 0
    # Identity in the knowledge store. Matching live_knowledge's own fetchers
    # (source "quote" / "fred", same URL) means a streamed value IS the cached
    # answer those fetchers look for, so a question needs no fetch of its own.
    doc_source: str = ""
    doc_title: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "feed": self.feed, "kind": self.kind, "key": self.key, "value": self.value,
                "text": self.text, "ts": self.ts, "at": dt.datetime.fromtimestamp(self.ts).isoformat(timespec="seconds"),
                "source": self.source, "url": self.url}


def us_market_open(now: Optional[dt.datetime] = None) -> bool:
    if _NY is None:
        return True
    n = (now or dt.datetime.now(dt.timezone.utc)).astimezone(_NY)
    if n.weekday() >= 5:
        return False
    return dt.time(9, 30) <= n.time() < dt.time(16, 0)


class Feed:
    name = "feed"
    interval_s = 60.0
    closed_interval_s = 900.0        # when active() is False
    timeout_s = 20.0

    def active(self) -> bool:
        return True

    def poll(self) -> List[Event]:
        raise NotImplementedError


class FnFeed(Feed):
    def __init__(self, name: str, poll: Callable[[], List[Event]], interval_s: float = 60,
                 closed_interval_s: Optional[float] = None, active: Optional[Callable[[], bool]] = None):
        self.name, self._poll, self.interval_s = name, poll, interval_s
        self.closed_interval_s = closed_interval_s if closed_interval_s is not None else interval_s
        self._active = active

    def active(self):
        return self._active() if self._active else True

    def poll(self):
        return self._poll()


# ── Ready-made feeds ──────────────────────────────────────────────────────

def http_get(url: str, timeout: float = 8.0, headers: Optional[Dict[str, str]] = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def yahoo_quote(sym: str, http: Callable = http_get) -> Optional[Dict[str, Any]]:
    """Last price, previous close and the exchange timestamp from Yahoo's
    chart endpoint (keyless). None when the symbol has no quote."""
    raw = http("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sym)
               + "?range=1d&interval=5m")
    res = (json.loads(raw).get("chart") or {}).get("result") or []
    if not res:
        return None
    m = res[0].get("meta") or {}
    price = m.get("regularMarketPrice")
    if not price or price <= 0:
        return None
    prev = m.get("chartPreviousClose") or m.get("previousClose")
    t = m.get("regularMarketTime")
    return {"symbol": sym, "price": float(price), "prev_close": float(prev) if prev else None,
            "change_pct": round((price / prev - 1) * 100, 3) if prev else None,
            "currency": m.get("currency"), "exchange_time": t,
            "as_of": dt.datetime.fromtimestamp(t).isoformat(timespec="minutes") if t else None}


class QuoteFeed(Feed):
    """Quotes for a symbol list the app supplies at each poll (holdings,
    watchlist, today's ideas), fetched in parallel."""
    name = "quotes"
    interval_s = 60.0
    closed_interval_s = 1800.0

    def __init__(self, symbols: Callable[[], Sequence[str]], name: str = "quotes", interval_s: float = 60,
                 closed_interval_s: float = 1800, max_symbols: int = 40, quote: Callable = yahoo_quote,
                 always_open: Sequence[str] = ()):
        self.symbols, self.name, self.interval_s, self.closed_interval_s = symbols, name, interval_s, closed_interval_s
        self.max_symbols, self.quote, self.always_open = max_symbols, quote, set(always_open)

    def active(self):
        return us_market_open()

    def poll(self):
        syms = list(dict.fromkeys(s.upper() for s in (self.symbols() or []) if s))[: self.max_symbols]
        out: List[Event] = []
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            for sym, q in zip(syms, ex.map(self._safe, syms)):
                if not q:
                    continue
                chg = f", {q['change_pct']:+.2f}% vs the previous close" if q.get("change_pct") is not None else ""
                out.append(Event(self.name, "quote", f"quote:{sym}", q,
                                 f"{sym} last traded at ${q['price']:,.2f}{chg} (as of {q.get('as_of') or 'now'}).",
                                 source="Yahoo Finance chart", url=f"https://finance.yahoo.com/quote/{sym}", ttl_s=900,
                                 doc_source="quote", doc_title=f"{sym} price"))
        return out

    def _safe(self, sym):
        try:
            return self.quote(sym)
        except Exception:
            return None


FRED_LABELS = {"DGS10": ("10-year Treasury yield", "%"), "DGS2": ("2-year Treasury yield", "%"),
               "DTB3": ("3-month Treasury bill rate", "%"), "DFF": ("effective federal funds rate", "%"),
               "MORTGAGE30US": ("average 30-year fixed mortgage rate", "%"), "VIXCLS": ("CBOE VIX", ""),
               "T10Y2Y": ("10-year minus 2-year Treasury spread", " pts"), "UNRATE": ("US unemployment rate", "%")}


class FredFeed(Feed):
    """Latest observations of FRED series (keyless CSV). FRED answers only
    known client agents — a custom or browser User-Agent hangs."""
    name = "rates"
    interval_s = 6 * 3600.0
    closed_interval_s = 6 * 3600.0

    def __init__(self, series: Sequence[str], http: Callable = http_get, name: str = "rates"):
        self.series, self.http, self.name = list(series), http, name

    def poll(self):
        out = []
        start = (dt.date.today() - dt.timedelta(days=30)).isoformat()
        for sid in self.series:
            raw = self.http(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}",
                            headers={"User-Agent": "Python-urllib/3"}).decode()
            rows = [r for r in csv.reader(io.StringIO(raw)) if len(r) == 2 and r[1] not in ("", ".") and r[0][:1].isdigit()]
            if not rows:
                continue
            day, val = rows[-1][0], float(rows[-1][1])
            label, unit = FRED_LABELS.get(sid, (sid, ""))
            out.append(Event(self.name, "rate", f"rate:{sid}", {"series": sid, "value": val, "date": day,
                                                                 "label": label, "unit": unit},
                             f"The {label} was {val:g}{unit} on {day} (FRED series {sid}).", source="FRED",
                             url=f"https://fred.stlouisfed.org/series/{sid}", ttl_s=8 * 3600,
                             doc_source="fred", doc_title=f"{label} ({sid})"))
        return out


class HeadlineFeed(Feed):
    """Google News RSS for a few queries the app supplies (e.g. holdings)."""
    name = "headlines"
    interval_s = 1800.0
    closed_interval_s = 3600.0

    def __init__(self, queries: Callable[[], Sequence[str]], http: Callable = http_get, per_query: int = 3,
                 name: str = "headlines", max_queries: int = 8):
        self.queries, self.http, self.per_query, self.name, self.max_queries = queries, http, per_query, name, max_queries

    def poll(self):
        import html
        import re
        import xml.etree.ElementTree as ET
        out = []
        for q in list(self.queries() or [])[: self.max_queries]:
            try:
                root = ET.fromstring(self.http("https://news.google.com/rss/search?" + urllib.parse.urlencode(
                    {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})))
            except Exception:
                continue
            for item in list(root.iter("item"))[: self.per_query]:
                title = html.unescape(item.findtext("title") or "").strip()
                if not title:
                    continue
                pub = item.findtext("pubDate") or ""
                hid = hashlib.sha1(re.sub(r"\W+", " ", title.lower()).encode()).hexdigest()[:12]
                out.append(Event(self.name, "headline", f"headline:{hid}", {"query": q, "title": title, "published": pub},
                                 f"{title} ({pub[:16]}). Related: {q}.", source="Google News",
                                 url=item.findtext("link") or "", ttl_s=6 * 3600))
        return out


# ── Hub ───────────────────────────────────────────────────────────────────

class FeedHub:
    def __init__(self, feeds: Sequence[Feed], store: Any = None, db_path: Optional[str] = None,
                 ring: int = 1000, max_log_rows: int = 20000):
        self.feeds = {f.name: f for f in feeds}
        self.store, self.db_path, self.max_log_rows = store, db_path, max_log_rows
        self._ring: collections.deque = collections.deque(maxlen=ring)
        self._latest: Dict[str, Event] = {}
        self._hash: Dict[str, str] = {}
        self._subs: List[queue.Queue] = []
        self._lock = threading.Lock()
        self._next_id = 1
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.health: Dict[str, Dict[str, Any]] = {
            n: {"last_ok": None, "last_error": None, "error": None, "failures": 0, "next_due": 0.0,
                "polls": 0, "published": 0, "last_ms": None} for n in self.feeds}
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            with self._db() as c:
                c.execute("""CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts REAL, feed TEXT, kind TEXT,
                             key TEXT, value TEXT, text TEXT, source TEXT, url TEXT)""")
                c.execute("CREATE INDEX IF NOT EXISTS events_key ON events(key, id)")
                row = c.execute("SELECT MAX(id) FROM events").fetchone()
                self._next_id = (row[0] or 0) + 1
                # Warm the latest-by-key map from the log so a restart is not blank.
                for r in c.execute("""SELECT e.id, e.ts, e.feed, e.kind, e.key, e.value, e.text, e.source, e.url
                                      FROM events e JOIN (SELECT key, MAX(id) m FROM events GROUP BY key) x
                                      ON e.id = x.m"""):
                    ev = Event(r[2], r[3], r[4], json.loads(r[5] or "{}"), r[6] or "", r[1], r[7] or "", r[8] or "", id=r[0])
                    self._latest[ev.key] = ev
                    self._hash[ev.key] = _vhash(ev.value)

    def _db(self):
        return sqlite3.connect(self.db_path, timeout=10)

    # Lifecycle ----------------------------------------------------------
    def start(self) -> "FeedHub":
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="feed-hub", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = time.time()
            due = [n for n, h in self.health.items() if h["next_due"] <= now]
            for n in due:
                self.poll_now(n)
            nxt = min((h["next_due"] for h in self.health.values()), default=now + 30)
            self._stop.wait(max(1.0, min(30.0, nxt - time.time())))

    # Polling ------------------------------------------------------------
    def poll_now(self, name: str) -> List[Event]:
        """Poll one feed immediately (also what the loop calls). Returns the
        events PUBLISHED (changed values)."""
        f, h = self.feeds[name], self.health[name]
        t0 = time.time()
        published: List[Event] = []
        try:
            active = f.active()
            ex = cf.ThreadPoolExecutor(max_workers=1)
            try:
                events = ex.submit(f.poll).result(timeout=f.timeout_s)
            finally:
                ex.shutdown(wait=False)
            for ev in events or []:
                if self._publish(ev):
                    published.append(ev)
            h.update(last_ok=time.time(), error=None, failures=0)
            base = f.interval_s if active else f.closed_interval_s
        except Exception as e:
            h["failures"] += 1
            h.update(last_error=time.time(), error=f"{type(e).__name__}: {str(e)[:160]}")
            base = f.interval_s * min(16, 2 ** h["failures"])
        h["polls"] += 1
        h["published"] += len(published)
        h["last_ms"] = int((time.time() - t0) * 1000)
        h["next_due"] = time.time() + base
        return published

    def publish(self, ev: Event) -> bool:
        """Publish an event from outside a feed (e.g. an app computing one)."""
        return self._publish(ev)

    def _publish(self, ev: Event) -> bool:
        vh = _vhash(ev.value)
        with self._lock:
            if self._hash.get(ev.key) == vh:
                cur = self._latest.get(ev.key)
                if cur is not None:
                    cur.value.setdefault("_seen", None)
                    cur.value["_seen"] = time.time()
                return False
            ev.id = self._next_id
            self._next_id += 1
            self._hash[ev.key] = vh
            self._latest[ev.key] = ev
            self._ring.append(ev)
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass
        if self.db_path:
            try:
                with self._db() as c:
                    c.execute("INSERT INTO events (id, ts, feed, kind, key, value, text, source, url) VALUES (?,?,?,?,?,?,?,?,?)",
                              (ev.id, ev.ts, ev.feed, ev.kind, ev.key, json.dumps(_clean(ev.value), default=str),
                               ev.text, ev.source, ev.url))
                    if ev.id % 500 == 0:
                        c.execute("DELETE FROM events WHERE id < ?", (ev.id - self.max_log_rows,))
            except sqlite3.Error:
                pass
        if self.store is not None and ev.text:
            try:
                from_doc = _doc_class(self.store)
                if from_doc:
                    self.store.add([from_doc(ev.doc_source or f"feed:{ev.feed}", ev.doc_title or ev.key, ev.text,
                                             ev.url or f"feed://{ev.key}",
                                             "fact" if ev.kind != "headline" else "news", ttl_s=ev.ttl_s,
                                             fetched_at=ev.ts, meta=_clean(ev.value))])
            except Exception:
                pass
        return True

    # Reading ------------------------------------------------------------
    def latest(self, key: str) -> Optional[Event]:
        return self._latest.get(key)

    def latest_value(self, key: str, max_age_s: Optional[float] = None) -> Optional[Dict[str, Any]]:
        ev = self._latest.get(key)
        if ev is None:
            return None
        seen = ev.value.get("_seen") or ev.ts
        if max_age_s is not None and time.time() - seen > max_age_s:
            return None
        return _clean(ev.value)

    def by_kind(self, kind: str) -> List[Event]:
        return sorted((e for e in self._latest.values() if e.kind == kind), key=lambda e: e.key)

    def events(self, since_id: int = 0, kinds: Optional[Sequence[str]] = None, limit: int = 200) -> List[Event]:
        with self._lock:
            evs = [e for e in self._ring if e.id > since_id and (not kinds or e.kind in kinds)]
        return evs[-limit:]

    def snapshot(self, kinds: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        now = time.time()
        return {
            "running": self.running,
            "feeds": {n: {**{k: v for k, v in h.items() if k != "next_due"},
                          "next_in_s": max(0, int(h["next_due"] - now)) if h["next_due"] else None,
                          "active": _safe_active(self.feeds[n])}
                      for n, h in self.health.items()},
            "latest": [_ev_dict(e) for e in sorted(self._latest.values(), key=lambda e: (e.kind, e.key))
                       if not kinds or e.kind in kinds],
            "last_id": self._next_id - 1,
        }

    # Streaming ----------------------------------------------------------
    def subscribe(self, maxsize: int = 500) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def sse(self, kinds: Optional[Sequence[str]] = None, since_id: int = 0, max_s: float = 25.0,
            heartbeat_s: float = 10.0) -> Iterator[str]:
        """Server-Sent Events: replay what the client missed (since_id), then
        live events, then end after max_s so a worker thread is never held
        forever (EventSource reconnects with Last-Event-ID by itself)."""
        q = self.subscribe()
        try:
            yield "retry: 3000\n\n"
            for ev in self.events(since_id, kinds):
                yield _sse(ev)
            end = time.time() + max_s
            last_beat = time.time()
            while time.time() < end:
                try:
                    ev = q.get(timeout=1.0)
                    if not kinds or ev.kind in kinds:
                        yield _sse(ev)
                except queue.Empty:
                    pass
                if time.time() - last_beat >= heartbeat_s:
                    last_beat = time.time()
                    yield ": keep-alive\n\n"
        finally:
            self.unsubscribe(q)


def _sse(ev: Event) -> str:
    return f"id: {ev.id}\nevent: {ev.kind}\ndata: {json.dumps(_ev_dict(ev), default=str)}\n\n"


def _ev_dict(e: Event) -> Dict[str, Any]:
    d = e.to_dict()
    d["value"] = _clean(e.value)
    return d


def _clean(v: Dict[str, Any]) -> Dict[str, Any]:
    return {k: x for k, x in (v or {}).items() if not str(k).startswith("_")}


def _vhash(v: Dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(_clean(v), sort_keys=True, default=str).encode()).hexdigest()


def _safe_active(f: Feed) -> Optional[bool]:
    try:
        return bool(f.active())
    except Exception:
        return None


def _doc_class(store: Any):
    """The Doc class of whichever live_knowledge module built `store`."""
    import sys
    mod = sys.modules.get(type(store).__module__)
    return getattr(mod, "Doc", None)
