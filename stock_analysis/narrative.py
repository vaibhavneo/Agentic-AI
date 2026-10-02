"""
The one LLM step: a summary of a filing's MD&A, held to the filing.

The model is asked for bullets, each paired with a sentence it copied from the
MD&A. Two checks, either of which withholds the whole summary:
  - every quoted sentence must appear in the MD&A, word for word (whitespace
    and quote marks normalized);
  - every number in the bullets must appear in the MD&A text — the desk's own
    decision/narrative.validate_narrative, with the MD&A as the allowlist.
A withheld summary says why. The deterministic findings never depend on it.
Results are cached per filing: a filed document never changes.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict

_MAX_CHARS = 60000
_MODEL = "deepseek-v4-pro"


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def validate(summary: Dict[str, Any], mdna: str) -> Dict[str, Any]:
    from decision.narrative import validate_narrative
    text = _norm(mdna.replace(" | ", " "))
    bad_quotes = []
    for b in summary.get("bullets", []):
        q = _norm(b.get("quote") or "")
        if not q or q.strip('"') not in text:
            bad_quotes.append(b.get("quote") or "(missing)")
    prose = "\n".join(b.get("point", "") for b in summary.get("bullets", []))
    nums = validate_narrative(prose, {"mdna": mdna})
    ok = not bad_quotes and not nums["unsupported_numbers"] and bool(summary.get("bullets"))
    return {"ok": ok, "quotes_not_in_filing": bad_quotes[:5], "numbers_not_in_filing": nums["unsupported_numbers"],
            "banned_phrases": nums["banned_phrases"]}


def summarize_mdna(mdna: str, filing: Dict[str, Any], client: Any = None) -> Dict[str, Any]:
    from financial_data import cache
    from financial_data.keys import has_key, get_key
    if len(mdna) < 2000:
        return {"status": "UNAVAILABLE", "reason": "MD&A section not found in the annual report"}
    key = f"mdna_{filing['accession']}"
    cached = cache.get("stock-analysis", "mdna", key)
    if cached is not None:
        return cached
    if client is None:
        if not has_key("DEEPSEEK_API_KEY"):
            return {"status": "UNAVAILABLE", "reason": "DEEPSEEK_API_KEY is not set"}
        from openai import OpenAI
        client = OpenAI(api_key=get_key("DEEPSEEK_API_KEY", "stock_analysis MD&A summary"),
                        base_url="https://api.deepseek.com", timeout=180.0, max_retries=1)
    body = mdna[:_MAX_CHARS]
    system = ("You summarize the Management's Discussion and Analysis section of an SEC filing for an investor. "
              "Use ONLY the text provided. Return JSON: {\"bullets\": [{\"topic\": one of "
              "\"drivers\"|\"outlook\"|\"risks\"|\"capital\", \"point\": one sentence in plain English, "
              "\"quote\": one sentence copied EXACTLY, word for word, from the text that supports the point}]}. "
              "5 to 8 bullets. Do not state any number that is not written in the text. No advice, no predictions "
              "of your own.")
    try:
        resp = client.chat.completions.create(
            model=_MODEL, max_tokens=6000, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": body}])
        raw = resp.choices[0].message.content or ""
        summary = json.loads(raw)
    except Exception as e:
        code = getattr(e, "status_code", None)
        why = {402: "the DeepSeek account has insufficient balance (HTTP 402)",
               401: "the DeepSeek key was rejected (HTTP 401)"}.get(code, f"{type(e).__name__}"
                                                                         + (f" (HTTP {code})" if code else ""))
        return {"status": "UNAVAILABLE", "reason": f"LLM call failed: {why}"}
    check = validate(summary, body)
    result = ({"status": "OK", "bullets": summary.get("bullets", []), "validation": check,
               "source": {"accession": filing["accession"], "url": filing.get("url"), "filed": filing.get("filed")},
               "model": _MODEL, "chars_read": len(body), "truncated": len(mdna) > _MAX_CHARS}
              if check["ok"] else
              {"status": "WITHHELD", "reason": "the summary did not hold to the filing", "validation": check,
               "source": {"accession": filing["accession"], "url": filing.get("url")}})
    cache.put("stock-analysis", "mdna", key, result)
    return result
