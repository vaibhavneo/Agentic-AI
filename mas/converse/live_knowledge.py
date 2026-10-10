"""
live_knowledge — a small, fast retrieval layer with a live fallback.

Vendored into each app (keep the copies identical; this file in
agent-hosting/shared/ is the source). Standard library only.

    store = KnowledgeStore("storage/knowledge.db")
    pipe = Pipeline(store, fetchers=[FredFetcher(...), WikipediaFetcher(), GoogleNewsFetcher()])
    out = pipe.answer("what is the 10-year treasury yield now?")

How a question is answered:

  1. LOCAL    full-text search (SQLite FTS5, BM25) over the app's own documents
              and everything fetched before that has not expired.
  2. ENOUGH?  local hits cover the question's key terms, AND the question does
              not ask for something only live data can say ("now", "today",
              "latest", a price, a rate, news). If so, stop here.
  3. LIVE     the fetchers that apply to this question run in parallel, each
              with a timeout; what they return is cached in the store with a
              time-to-live (a quote for minutes, an encyclopedia entry for weeks)
              so the next identical question is answered locally.
  4. ANSWER   extractive: the sentences that best match the question, each
              carrying a numbered citation (source, title, URL, fetched-at).
              Nothing is generated, so nothing can be invented. An LLM, when
              one is available, may reword this answer — never add to it.

Free, keyless sources only (Wikipedia, Google News RSS, FRED CSV, SEC EDGAR
full-text search with the app's own contact string, Yahoo quotes). A fetcher
that fails is recorded in the trace and costs the answer nothing else.
"""
from __future__ import annotations

import concurrent.futures as cf
import csv
import hashlib
import html
import io
import json
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

VERSION = "1.0.0"
UA = "live-knowledge/1.0 (personal research app)"
STOP = set("""a an and are as at be by can do does for from has have how i in is it its me my of on or our
should so than that the their them then there these this to us was we what when where which who why will with
would you your tell about please give show explain define meaning mean get much many any some current currently
now today latest recent what's how's it's where's who's that's there's today's""".split())
LIVE_WORDS = re.compile(r"\b(now|today|tonight|current(ly)?|latest|recent|this (week|month|morning)|"
                        r"news|headlines?|price|quote|trading at|yield|rate|rates)\b", re.I)


def terms(text: str) -> List[str]:
    # Inner dots and hyphens stay ("u.s.", "10-year"); a sentence's final
    # period does not ("yoga." is "yoga").
    words = (w.strip(".-'") for w in re.findall(r"[a-z0-9][a-z0-9.\-']*", text.lower()))
    return [w for w in words if w not in STOP and len(w) > 1]


def needs_live(question: str) -> bool:
    return bool(LIVE_WORDS.search(question or ""))


DEFINITION = re.compile(r"^\s*(what('s| is| are)( an?| the)?|define|definition of|explain|meaning of|what does .+ mean)\b",
                        re.I)


def is_definition(question: str) -> bool:
    """'what is a calendar spread', 'define theta': an encyclopedia question.
    App docs that merely mention the words are not a definition."""
    return bool(DEFINITION.search(question or ""))


@dataclass
class Doc:
    source: str                 # "wikipedia", "fred", "news", "local:docs", …
    title: str
    text: str
    url: str = ""
    kind: str = "reference"     # reference | fact | news | local (a knowledge corpus) | appdoc (the app's own docs)
    ttl_s: float = 30 * 86400   # how long a fetched doc stays usable
    fetched_at: float = field(default_factory=time.time)
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.source}|{self.url or self.title}".encode()).hexdigest()[:20]


class KnowledgeStore:
    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS docs (
        id TEXT PRIMARY KEY, source TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
        url TEXT, text TEXT NOT NULL, fetched_at REAL NOT NULL, expires_at REAL NOT NULL, meta TEXT);
    CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(title, text, content='docs', content_rowid='rowid',
        tokenize='porter unicode61');
    CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
        INSERT INTO docs_fts(rowid, title, text) VALUES (new.rowid, new.title, new.text); END;
    CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON docs BEGIN
        INSERT INTO docs_fts(docs_fts, rowid, title, text) VALUES ('delete', old.rowid, old.title, old.text); END;
    CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON docs BEGIN
        INSERT INTO docs_fts(docs_fts, rowid, title, text) VALUES ('delete', old.rowid, old.title, old.text);
        INSERT INTO docs_fts(rowid, title, text) VALUES (new.rowid, new.title, new.text); END;
    """

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)     # a fresh container has no data/ yet
        with self._conn() as c:
            c.executescript(self._SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def add(self, docs: Sequence[Doc]) -> int:
        with self._lock, self._conn() as c:
            for d in docs:
                c.execute("""INSERT INTO docs (id, source, kind, title, url, text, fetched_at, expires_at, meta)
                             VALUES (?,?,?,?,?,?,?,?,?)
                             ON CONFLICT(id) DO UPDATE SET text=excluded.text, title=excluded.title,
                               kind=excluded.kind, fetched_at=excluded.fetched_at, expires_at=excluded.expires_at,
                               meta=excluded.meta""",
                          (d.id, d.source, d.kind, d.title, d.url, d.text, d.fetched_at,
                           d.fetched_at + d.ttl_s, json.dumps(d.meta, default=str)))
        return len(docs)

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM docs").fetchone()[0]

    def prune(self) -> int:
        with self._lock, self._conn() as c:
            return c.execute("DELETE FROM docs WHERE expires_at < ?", (time.time(),)).rowcount

    def get(self, ids: Sequence[str]) -> List[Dict[str, Any]]:
        if not ids:
            return []
        with self._conn() as c:
            rows = {r["id"]: dict(r) for r in c.execute(
                f"SELECT * FROM docs WHERE id IN ({','.join('?' * len(ids))})", list(ids)).fetchall()}
        return [rows[i] for i in ids if i in rows]

    def search(self, query: str, k: int = 6, kinds: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        q = terms(query)
        if not q:
            return []
        match = " OR ".join(f'"{t}"' for t in q)
        sql = """SELECT d.*, bm25(docs_fts, 3.0, 1.0) AS rank FROM docs_fts JOIN docs d ON d.rowid = docs_fts.rowid
                 WHERE docs_fts MATCH ? AND d.expires_at >= ?"""
        args: List[Any] = [match, time.time()]
        if kinds:
            sql += f" AND d.kind IN ({','.join('?' * len(kinds))})"
            args += list(kinds)
        sql += " ORDER BY rank LIMIT ?"
        args.append(k)
        try:
            with self._conn() as c:
                rows = [dict(r) for r in c.execute(sql, args).fetchall()]
        except sqlite3.OperationalError:
            return []
        for r in rows:
            body = f"{r['title']} {r['text']}".lower()
            r["coverage"] = round(sum(1 for t in set(q) if t in body) / len(set(q)), 3)
        return rows


# ── Fetchers ──────────────────────────────────────────────────────────────

def http_get(url: str, timeout: float = 8.0, headers: Optional[Dict[str, str]] = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class Fetcher:
    name = "fetcher"
    kinds: Sequence[str] = ("reference",)
    timeout = 8.0

    def applies(self, question: str, ctx: Dict[str, Any]) -> bool:
        return True

    def fetch(self, question: str, ctx: Dict[str, Any]) -> List[Doc]:
        raise NotImplementedError

    def cache_ids(self, question: str, ctx: Dict[str, Any]) -> List[str]:
        """Ids of the docs this fetcher WOULD return, when they are knowable
        without fetching (a FRED series, a ticker's quote). A fresh cached copy
        of all of them answers the question with no network call, whatever
        words the question used."""
        return []


class WikipediaFetcher(Fetcher):
    """Encyclopedia summaries for concepts: search, then the top pages' leads."""
    name, kinds = "wikipedia", ("reference",)

    def __init__(self, suffix: str = "", top: int = 2, http: Callable = http_get):
        self.suffix, self.top, self.http = suffix, top, http

    def applies(self, question, ctx):
        return not ctx.get("only_live_facts")

    def _summary(self, title: str) -> Optional[Doc]:
        try:
            s = json.loads(self.http("https://en.wikipedia.org/api/rest_v1/page/summary/"
                                     + urllib.parse.quote(title.replace(" ", "_"))))
        except Exception:
            return None
        if not s.get("extract") or s.get("type") == "disambiguation":
            return None
        return Doc("wikipedia", s.get("title") or title, s["extract"],
                   (s.get("content_urls") or {}).get("desktop", {}).get("page", ""), "reference", ttl_s=30 * 86400)

    def fetch(self, question, ctx):
        key = terms(question)
        out: List[Doc] = []
        # "what is a nakshatra" -> the article "Nakshatra" itself, before search
        # (which ranks specific pages like "Revati (nakshatra)" above the general one).
        if 1 <= len(key) <= 4:
            d = self._summary(" ".join(key).capitalize())
            if d:
                out.append(d)
        q = " ".join(key) + (f" {self.suffix}" if self.suffix else "")
        data = json.loads(self.http("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "query", "list": "search", "srsearch": q, "format": "json", "srlimit": self.top})))
        for hit in (data.get("query") or {}).get("search", []):
            if len(out) >= self.top:
                break
            if any(d.title == hit["title"] for d in out):
                continue
            d = self._summary(hit["title"])
            if d:
                out.append(d)
        return out


class GoogleNewsFetcher(Fetcher):
    """Recent headlines for a query (Google News RSS, keyless)."""
    name, kinds = "news", ("news",)

    def __init__(self, query_fn: Optional[Callable[[str, Dict], str]] = None, top: int = 6, http: Callable = http_get):
        self.query_fn, self.top, self.http = query_fn, top, http

    def applies(self, question, ctx):
        return bool(re.search(r"\b(news|headlines?|latest|recent|happening|why (is|did)|announce\w*)\b",
                              question, re.I)) or bool(ctx.get("want_news"))

    def fetch(self, question, ctx):
        q = self.query_fn(question, ctx) if self.query_fn else " ".join(terms(question))
        root = ET.fromstring(self.http("https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})))
        out = []
        for item in root.iter("item"):
            title = html.unescape(item.findtext("title") or "")
            desc = re.sub(r"<[^>]+>", " ", html.unescape(item.findtext("description") or ""))
            pub = item.findtext("pubDate") or ""
            desc = " ".join(desc.split())
            body = f"{title} ({pub[:16]})." if not desc or desc[:40] in title or title[:40] in desc else \
                f"{title} ({pub[:16]}). {desc}"
            if ctx.get("tickers"):     # so the cached headline is found again by its ticker
                body += f" Related: {', '.join(ctx['tickers'][:3])}."
            out.append(Doc("news", title, body, item.findtext("link") or "",
                           "news", ttl_s=1800, meta={"published": pub}))
            if len(out) >= self.top:
                break
        return out


class FredFetcher(Fetcher):
    """The latest value of FRED series the question names (keyless CSV)."""
    name, kinds = "fred", ("fact",)

    def __init__(self, series: Dict[str, tuple], http: Callable = http_get):
        # series: regex -> (series_id, label, unit)
        self.series = {re.compile(k, re.I): v for k, v in series.items()}
        self.http = http

    def _wanted(self, question):
        return [v for rx, v in self.series.items() if rx.search(question)]

    def applies(self, question, ctx):
        return bool(self._wanted(question))

    def cache_ids(self, question, ctx):
        return [Doc("fred", "", "", f"https://fred.stlouisfed.org/series/{spec[0]}").id for spec in self._wanted(question)]

    def fetch(self, question, ctx):
        out = []
        for spec in self._wanted(question):
            sid, label, unit = spec[:3]
            yoy = len(spec) > 3 and spec[3] == "yoy"
            start = time.strftime("%Y-%m-%d", time.gmtime(time.time() - (420 if yoy else 120) * 86400))
            # FRED answers only known client agents (Python-urllib, curl); a custom
            # or browser-like User-Agent hangs until the timeout.
            raw = self.http(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}",
                            headers={"User-Agent": "Python-urllib/3"}).decode()
            rows = [(r[0], float(r[1])) for r in csv.reader(io.StringIO(raw))
                    if len(r) == 2 and r[1] not in ("", ".") and r[0][:1].isdigit()]
            if not rows:
                continue
            day, val = rows[-1]
            if yoy:
                year_ago = [v for d, v in rows if d <= f"{int(day[:4]) - 1}{day[4:]}"]
                if not year_ago:
                    continue
                text = (f"The {label} was {(val / year_ago[-1] - 1) * 100:.1f}{unit} for the month of {day[:7]} "
                        f"(FRED series {sid}; index {val:g} vs {year_ago[-1]:g} a year earlier).")
                value = round((val / year_ago[-1] - 1) * 100, 2)
            else:
                text = f"The {label} was {val:g}{unit} on {day} (FRED series {sid})."
                if len(rows) > 1:
                    text += f" The previous reading was {rows[-2][1]:g}{unit} on {rows[-2][0]}."
                value = val
            out.append(Doc("fred", f"{label} ({sid})", text, f"https://fred.stlouisfed.org/series/{sid}",
                           "fact", ttl_s=6 * 3600, meta={"series": sid, "date": day, "value": value}))
        return out


# Question pattern -> (FRED series, label, unit). Daily or monthly, all keyless.
MARKET_SERIES = {
    r"\b(10.?y(ea)?r|ten.?year)\b.*\b(treasury|yield|note|bond)s?\b|\b(treasury|bond) yields?\b":
        ("DGS10", "10-year Treasury yield", "%"),
    r"\b(2.?y(ea)?r|two.?year)\b.*\b(treasury|yield)": ("DGS2", "2-year Treasury yield", "%"),
    r"\b(3.?month|three.?month|t.?bills?|treasury bills?)\b": ("DTB3", "3-month Treasury bill rate", "%"),
    r"\bfed(eral)?\s*funds\b|\bfed rate\b|\binterest rates? (now|today)\b|\bwhat (are|is) (the )?interest rates?\b":
        ("DFF", "effective federal funds rate", "%"),
    r"\bmortgage rates?\b|\b30.?y(ea)?r (fixed|mortgage)\b": ("MORTGAGE30US", "average 30-year fixed mortgage rate", "%"),
    r"\b(inflation|cpi|consumer prices?)\b": ("CPIAUCSL", "US CPI inflation (CPI-U, year over year)", "%", "yoy"),
    r"\bunemployment\b|\bjobless rate\b": ("UNRATE", "US unemployment rate", "%"),
    r"\bvix\b|\bvolatility index\b": ("VIXCLS", "CBOE VIX volatility index", ""),
    r"\bs&p ?500 (level|index|close)\b|\bwhere is the s&p\b": ("SP500", "S&P 500 index close", ""),
    r"\b(yield curve|10.?2 spread|curve invert\w*)\b": ("T10Y2Y", "10-year minus 2-year Treasury spread", " percentage points"),
}


class QuoteFetcher(Fetcher):
    """Last price for tickers the context names, from a callable the app
    supplies (each app already has its own market-data path)."""
    name, kinds = "quote", ("fact",)

    def __init__(self, quote_fn: Callable[[str], Optional[Dict[str, Any]]]):
        self.quote_fn = quote_fn

    def applies(self, question, ctx):
        return bool(ctx.get("tickers"))

    def cache_ids(self, question, ctx):
        return [Doc("quote", f"{t} price", "", f"https://finance.yahoo.com/quote/{t}").id for t in ctx.get("tickers", [])[:5]]

    def fetch(self, question, ctx):
        out = []
        for t in ctx.get("tickers", [])[:5]:
            q = self.quote_fn(t)
            if not q or q.get("price") is None:
                continue
            chg = f", {q['change_pct']:+.2f}% on the day" if q.get("change_pct") is not None else ""
            out.append(Doc("quote", f"{t} price", f"{t} last traded at ${q['price']:,.2f}{chg} "
                           f"(as of {q.get('as_of', 'the latest available quote')}, source {q.get('source', 'Yahoo')}).",
                           q.get("url", f"https://finance.yahoo.com/quote/{t}"), "fact", ttl_s=300,
                           meta={"ticker": t, **{k: v for k, v in q.items() if k != "url"}}))
        return out


class SecFullTextFetcher(Fetcher):
    """SEC EDGAR full-text search: filings that mention the question's terms.
    SEC requires a contact in the User-Agent — the app passes its own."""
    name, kinds = "sec", ("reference",)

    def __init__(self, user_agent: str, http: Callable = http_get):
        self.ua, self.http = user_agent, http

    def applies(self, question, ctx):
        return bool(self.ua) and bool(re.search(r"\b(filing|10-k|10-q|8-k|sec|disclos\w*|risk factor\w*|guidance)\b",
                                                question, re.I))

    def fetch(self, question, ctx):
        q = " ".join(terms(question)[:6])
        if ctx.get("tickers"):
            q = f"{q} {ctx['tickers'][0]}"
        data = json.loads(self.http("https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode({"q": q}),
                                    headers={"User-Agent": self.ua}))
        out = []
        for h in ((data.get("hits") or {}).get("hits") or [])[:5]:
            s = h.get("_source", {})
            names = ", ".join(s.get("display_names") or [])[:120]
            form, filed = s.get("form") or s.get("file_type") or "filing", s.get("file_date") or ""
            adsh = (h.get("_id") or "").split(":")[0]
            cik = (s.get("ciks") or [""])[0]
            url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh.replace('-', '')}/"
                   if cik and adsh else "https://efts.sec.gov/LATEST/search-index")
            out.append(Doc("sec", f"{form} — {names}", f"{names} filed a {form} on {filed} that matches "
                           f"\"{q}\".", url, "reference", ttl_s=7 * 86400, meta={"form": form, "filed": filed}))
        return out


_BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _page_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav|form)\b.*?</\1>", " ", raw)
    paras = re.findall(r"(?is)<(?:p|li|h2|h3)\b[^>]*>(.*?)</(?:p|li|h2|h3)>", raw)
    out = []
    for p in paras:
        t = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", p)).split())
        if len(t) > 40:
            out.append(t)
    return "\n".join(out)


class WebSearchFetcher(Fetcher):
    """General web research: DuckDuckGo's HTML results (keyless) — titles and
    snippets of the top results — and, for depth, the text of the top pages,
    kept only where it shares the question's terms. Kind "web": cited like any
    source, quoted not invented. Never runs for a personal question (apps pass
    ctx['only'] without it)."""
    name, kinds, timeout = "web", ("web",), 14.0

    def __init__(self, top: int = 5, pages: int = 2, http: Callable = http_get, suffix: str = ""):
        self.top, self.pages, self.http, self.suffix = top, pages, http, suffix

    def applies(self, question, ctx):
        return len(terms(question)) >= 2 and not ctx.get("only_live_facts")

    def search(self, query: str) -> List[Dict[str, str]]:
        raw = self.http("https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query}),
                        headers={"User-Agent": _BROWSER_UA}).decode("utf-8", "ignore")
        out = []
        for m in re.finditer(r'(?s)class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>', raw):
            href, title, snip = m.group(1), m.group(2), m.group(3)
            q = urllib.parse.parse_qs(urllib.parse.urlparse(html.unescape(href)).query)
            url = (q.get("uddg") or [html.unescape(href)])[0]
            if "duckduckgo.com/y.js" in url or not url.startswith("http"):
                continue                                              # ads
            out.append({"url": url, "title": " ".join(html.unescape(re.sub("<[^>]+>", "", title)).split()),
                        "snippet": " ".join(html.unescape(re.sub("<[^>]+>", "", snip)).split())})
            if len(out) >= self.top:
                break
        return out

    def fetch(self, question, ctx):
        q = " ".join(terms(question)) + (f" {self.suffix}" if self.suffix else "")
        results = self.search(q)
        docs = []
        for r in results:
            text = r["snippet"] if r["snippet"].endswith((".", "!", "?")) else r["snippet"] + "."
            docs.append(Doc("web", r["title"], text, r["url"], "web", ttl_s=86400))
        # Depth: the top pages' own paragraphs that share the question's terms.
        qt = set(terms(question))
        with cf.ThreadPoolExecutor(max_workers=max(1, self.pages)) as ex:
            futs = {ex.submit(self._page, r["url"]): r for r in results[: self.pages]}
            for fut, r in futs.items():
                try:
                    body = fut.result(timeout=6)
                except Exception:
                    continue
                keep = [p for p in body.split("\n") if len(qt & set(terms(p))) >= min(2, len(qt))][:6]
                if keep:
                    docs.append(Doc("web", r["title"], " ".join(keep), r["url"] + "#page", "web", ttl_s=86400))
        return docs

    def _page(self, url: str) -> str:
        raw = self.http(url, timeout=6, headers={"User-Agent": _BROWSER_UA})[:800_000]
        return _page_text(raw.decode("utf-8", "ignore"))


# ── Pipeline ──────────────────────────────────────────────────────────────

class Pipeline:
    def __init__(self, store: KnowledgeStore, fetchers: Sequence[Fetcher], min_coverage: float = 0.6,
                 max_workers: int = 4, kinds: Optional[Sequence[str]] = None):
        self.store, self.fetchers = store, list(fetchers)
        self.min_coverage, self.max_workers = min_coverage, max_workers
        # Restrict local search to these doc kinds: two pipelines can share one
        # store and still answer from different shelves (a library vs the sky).
        self.kinds = tuple(kinds) if kinds else None

    def _enough(self, hits: List[Dict[str, Any]], live: bool) -> bool:
        if live:
            # A live question is only answered locally by FRESH facts/news fetched for it.
            return any(h["kind"] in ("fact", "news") and h["coverage"] >= self.min_coverage for h in hits)
        return any(h["coverage"] >= self.min_coverage for h in hits)

    def fetch_live(self, question: str, ctx: Dict[str, Any], fetched: Optional[List[str]] = None
                   ) -> List[Dict[str, Any]]:
        # ctx["only"]: the fetchers allowed for this question. An app passes the
        # ones that send no free text (a FRED series id, a ticker) when the
        # question itself is personal and must not leave the machine.
        only = ctx.get("only")
        todo = [f for f in self.fetchers if (only is None or f.name in only) and f.applies(question, ctx)]
        trace = []
        if not todo:
            return trace
        with cf.ThreadPoolExecutor(max_workers=min(self.max_workers, len(todo))) as ex:
            futs = {ex.submit(f.fetch, question, ctx): (f, time.time()) for f in todo}
            for fut, (f, t0) in futs.items():
                try:
                    docs = fut.result(timeout=f.timeout + 2)
                    self.store.add(docs)
                    if fetched is not None:
                        fetched.extend(d.id for d in docs)
                    trace.append({"fetcher": f.name, "ok": True, "docs": len(docs),
                                  "ms": int((time.time() - t0) * 1000)})
                except Exception as e:
                    trace.append({"fetcher": f.name, "ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}",
                                  "ms": int((time.time() - t0) * 1000)})
        return trace

    def answer(self, question: str, ctx: Optional[Dict[str, Any]] = None, k: int = 6,
               force_live: Optional[bool] = None) -> Dict[str, Any]:
        ctx = dict(ctx or {})
        only = ctx.get("only")
        # A question a fact source can answer (a FRED series, a ticker) is a live
        # question even without "now": "my cash vs T-bills" wants today's rate.
        fact_fetcher = any("fact" in f.kinds and (only is None or f.name in only) and f.applies(question, ctx)
                           for f in self.fetchers)
        live = (needs_live(question) or fact_fetcher) if force_live is None else force_live
        q_for_search = " ".join([question] + list(ctx.get("tickers", [])))
        hits = self.store.search(q_for_search, k, self.kinds)
        trace: List[Dict[str, Any]] = []
        used_live = False
        # Facts a fetcher can name in advance (a FRED series, a quote): fresh
        # cached copies answer whatever words the question used, lead the
        # answer, and spare that fetcher a call.
        applicable = [f for f in self.fetchers if (only is None or f.name in only) and f.applies(question, ctx)]
        known: List[Dict[str, Any]] = []
        cached_ok: set = set()
        for f in applicable:
            if "fact" in f.kinds:
                ids = f.cache_ids(question, ctx)
                got = [h for h in self.store.get(ids) if h["expires_at"] >= time.time()]
                if ids and len(got) == len(ids):
                    cached_ok.add(f.name)
                known += got
        for h in known:
            h["coverage"] = 1.0
        seen_ids = {x["id"] for x in known}
        hits = known + [h for h in hits if h["id"] not in seen_ids]
        fetched: List[str] = [h["id"] for h in known]
        definition = is_definition(question) and not live
        if definition:
            # A definition needs a reference or a knowledge corpus (kind "local",
            # e.g. a library of books). An app's own documentation ("appdoc")
            # that merely uses the words is not a definition.
            enough = any(h["kind"] in ("reference", "local", "web") and h["coverage"] >= self.min_coverage for h in hits)
        elif live:
            want_fact = [f for f in applicable if "fact" in f.kinds]
            want_news = any("news" in f.kinds for f in applicable)
            enough = (all(f.name in cached_ok for f in want_fact)
                      and (not want_news or any(h["kind"] == "news" and h["coverage"] >= self.min_coverage
                                                for h in hits))
                      and (want_fact or want_news or self._enough(hits, live)))
        else:
            enough = self._enough(hits, live)
        if not enough:
            ctx = {**ctx, "only": [f.name for f in applicable if f.name not in cached_ok]}
            trace = self.fetch_live(question, ctx, fetched)
            used_live = any(t["ok"] and t["docs"] for t in trace)
            # What was fetched FOR this question is a candidate even when its words
            # differ from the question's ("T-bills" vs "Treasury bill").
            found = self.store.search(q_for_search, k, self.kinds)
            ids = {h["id"] for h in found}
            extra = [h for h in self.store.get(fetched) if h["id"] not in ids]
            qt = set(terms(q_for_search))
            for h in extra:
                body = f"{h['title']} {h['text']}".lower()
                h["coverage"] = round(sum(1 for t in qt if t in body) / (len(qt) or 1), 3)
            hits = found + extra
        if live:
            # Facts and news cached for OTHER questions must match this one well;
            # the T-bill rate fetched an hour ago is no answer to "mortgage rates".
            # A fact cached for another question must cover every key term of
            # this one ("2-year Treasury yield" is no answer to the 10-year).
            now_ids = set(fetched)
            hits = [h for h in hits if h["id"] in now_ids
                    or (h["kind"] == "fact" and h["coverage"] >= 1.0)
                    or (h["kind"] == "news" and h["coverage"] >= self.min_coverage)
                    or h["kind"] not in ("fact", "news")]
            hits.sort(key=lambda h: ({"fact": 0, "news": 1}.get(h["kind"], 2), -h["coverage"], -h["fetched_at"]))
        if definition and any(h["kind"] in ("reference", "local", "web") for h in hits):
            hits = [h for h in hits if h["kind"] in ("reference", "local", "web")]
        out = compose(question, hits, trace, used_live, live)
        if not out["found"] and not trace:
            # The local text matched words but held no quotable sentence (a table
            # of contents, a fragment): one live attempt before saying "not found".
            trace = self.fetch_live(question, ctx, fetched)
            if any(t["ok"] and t["docs"] for t in trace):
                extra = self.store.get(fetched)
                qt = set(terms(q_for_search))
                for h in extra:
                    body = f"{h['title']} {h['text']}".lower()
                    h["coverage"] = round(sum(1 for t in qt if t in body) / (len(qt) or 1), 3)
                out = compose(question, extra + hits, trace, True, live)
            else:
                out["trace"] = trace
        return out


def _good(s: str, strict: bool = True) -> bool:
    """A sentence worth quoting: not a table-of-contents line, not a fragment
    cut mid-word by a chunker, not a wall of digits or rules. Computed facts
    and headlines are written by code or an editor (dates and figures are the
    point), so only `strict` text — books, articles — gets the content tests."""
    if not (20 < len(s) <= 450):
        return False
    if not strict:
        return True
    if s[0].islower() or s[-1] not in ".!?\"')":
        return False                                     # cut mid-word, or a chunk's dangling tail
    if len(re.findall(r"\b\d+\b", s)) >= 5 and len(re.findall(r"\b\d+\b", s)) / len(s.split()) > 0.2:
        return False                                     # a contents listing: name, page, name, page…
    if re.search(r"_{3,}|\.{4,}|(\d+\s+){6,}", s):
        return False
    return sum(ch.isalpha() for ch in s) / len(s) >= 0.6


def _sentences(text: str, strict: bool = True) -> List[str]:
    out = []
    for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])", text):
        s = s.strip()
        if strict:
            # PDF text: a run of 3+ spaces is a layout gap, and what precedes the
            # last one is a running header ("2012   page ~ 36 ~ Book I (7)   ...").
            tail = re.split(r"\s{3,}", s)[-1]
            s = tail if len(tail) > 20 else s
        s = " ".join(s.split())
        if _good(s, strict):
            out.append(s)
    return out


QUANTITY = re.compile(r"\b(how (much|many|long|high|low|big)|limits?|rates?|price|cost|fees?|yield|percent|"
                      r"amount|threshold|caps?|maximum|minimum|when|what year|how old|age)\b", re.I)
BLURB = re.compile(r"^(learn|discover|find out|find the|explore|read|see|get|check out|track|browse|compare|"
                   r"this (guide|article|page|post)|(a |the )?(complete|ultimate|comprehensive) guide|here'?s|"
                   r"in this|click|sign up|subscribe|below (you will|you'll) find|we (cover|explain|break down))\b", re.I)


def compose(question: str, hits: List[Dict[str, Any]], trace: List[Dict[str, Any]], used_live: bool,
            live: bool = False, max_sentences: int = 4, max_chars: int = 900) -> Dict[str, Any]:
    q = set(terms(question))
    sources: List[Dict[str, Any]] = []
    scored = []
    wants_figure = bool(QUANTITY.search(question))
    q_core = q - {"news", "headline", "headlines", "latest", "update", "updates", "happening", "stories"}
    q_tickers = {w.lower() for w in re.findall(r"\b[A-Z]{2,5}\b", question)}
    doc_terms: Dict[str, set] = {}
    by_doc: Dict[str, List[str]] = {}
    for rank, h in enumerate(hits):
        strict = h["kind"] not in ("fact", "news", "web")
        sents = _sentences(h["text"], strict) or ([h["text"]] if _good(h["text"].strip(), strict) else [])
        by_doc[h["id"]] = sents
        for i, s in enumerate(sents):
            st = set(terms(s))
            hit_terms = len(q & st)
            # Background must share two of the question's key terms (one when it
            # has only one): "covered" alone does not make a sentence about
            # covered calls.
            if h["kind"] not in ("fact", "news") and hit_terms < min(2, len(q)):
                continue
            # A headline must be about the question, not share one word with it:
            # two core terms ("news", "latest" don't count) unless there is only
            # one — or a ticker the question names.
            if h["kind"] == "news":
                doc_t = doc_terms.setdefault(h["id"], set(terms(f"{h['title']} {h['text']}")))
                shared = q_core & doc_t
                if len(shared) < min(2, len(q_core)) and not (shared & q_tickers):
                    continue
            overlap = hit_terms / (len(q) or 1)
            facty = 0.3 if h["kind"] in ("fact", "news") else 0.0
            # A question asking for a quantity is answered by a sentence with a
            # figure in it; a page's own blurb ("Learn how…", "This guide…") is
            # not an answer.
            if wants_figure and re.search(r"\d", s):
                facty += 0.25
            if BLURB.match(s):
                continue                        # a page's blurb is never the answer
            scored.append((overlap + facty - 0.03 * rank, rank, i, s, h))
    scored.sort(key=lambda x: -x[0])
    has_fact = live and any(h["kind"] in ("fact", "news") for h in hits)
    chosen, total, seen, background = [], 0, set(), 0
    # Each fact doc's best sentence goes in first — a quote or a rate IS the
    # answer, and six headlines must not crowd it out — when it shares a term
    # with the question. If no fact sentence does ("my cash vs T-bills" against
    # "The 3-month Treasury bill rate was…"), the top fact doc's best still goes in.
    best: Dict[str, tuple] = {}
    for item in scored:                              # scored is best-first
        h = item[4]
        if h["kind"] == "fact" and h["id"] not in best:
            best[h["id"]] = item
    relevant = [b for b in best.values() if len(q & set(terms(b[3])))]
    lead = relevant or sorted(best.values(), key=lambda b: b[1])[:1]
    for score, rank, i, s, h in sorted(lead, key=lambda b: -b[0])[:max_sentences]:
        seen.add(re.sub(r"\W+", " ", s.lower()).strip()[:80])
        chosen.append((rank, i, s, h))
        total += len(s)
    lead_ids = {b[4]["id"] for b in lead}
    n_sents: Dict[str, int] = {}
    for item in scored:
        n_sents[item[4]["id"]] = n_sents.get(item[4]["id"], 0) + 1
    for score, rank, i, s, h in scored:
        if h["kind"] == "fact" and not len(q & set(terms(s))) \
                and not (h["id"] in lead_ids and n_sents[h["id"]] <= 2):
            continue        # a fact sentence about something else (a 1-2 sentence fact doc stays whole)
        key = re.sub(r"\W+", " ", s.lower()).strip()[:80]
        if score <= 0 or len(chosen) >= max_sentences or total + len(s) > max_chars or key in seen:
            continue
        if has_fact and h["kind"] not in ("fact", "news"):
            # A live answer leads with the live facts; background is one
            # encyclopedia sentence at most — never an app's own docs or a
            # book aside that happens to share the words.
            if background >= 1 or score < 0.5 or h["kind"] not in ("reference", "web"):
                continue
            background += 1
        seen.add(key)
        chosen.append((rank, i, s, h))
        total += len(s)
    # Context: a chosen passage sentence brings the sentence before it when
    # that one shares a term ("Guru in a kendra from the Moon causes this
    # yoga." before "Of what good is that Kesari Yoga…") — what a reader of
    # the page would have seen.
    have = {(h["id"], i) for _, i, _, h in chosen}
    for rank, i, s, h in list(chosen):
        if h["kind"] in ("local", "reference", "web") and i > 0 and (h["id"], i - 1) not in have \
                and len(chosen) < max_sentences:
            prev = by_doc.get(h["id"], [])[i - 1]
            if q & set(terms(prev)) and total + len(prev) <= max_chars:
                chosen.append((rank, i - 1, prev, h))
                have.add((h["id"], i - 1))
                total += len(prev)
    picked, used = [], {}
    for rank, i, s, h in sorted(chosen, key=lambda c: (c[0], c[1])):   # retrieval order, then the source's own
        if h["id"] not in used:
            used[h["id"]] = len(sources) + 1
            sources.append({"n": used[h["id"]], "source": h["source"], "title": h["title"], "url": h["url"],
                            "kind": h["kind"], "fetched_at": time.strftime("%Y-%m-%d %H:%M",
                                                                           time.localtime(h["fetched_at"]))})
        picked.append(f"{s} [{used[h['id']]}]")
    if not picked:
        failed = [t["fetcher"] for t in trace if not t["ok"]]
        text = ("I couldn't find this in the local knowledge base"
                + (", and the live sources returned nothing relevant" if trace else "")
                + (f" ({', '.join(failed)} did not answer)" if failed else "") + ".")
        return {"answer": text, "sources": [], "used_live": used_live, "trace": trace, "found": False}
    text = " ".join(picked)
    failed = [t["fetcher"] for t in trace if not t["ok"]]
    if live and failed and not any(x["kind"] in ("fact", "news") for x in sources):
        text = (f"Live data is unavailable right now ({', '.join(failed)} did not answer), so this is background "
                f"only, not a current figure: {text}")
    return {"answer": text, "sources": sources, "used_live": used_live, "trace": trace, "found": True}
