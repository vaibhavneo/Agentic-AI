"""
A failed LLM call, said in one sentence a person can act on.

_call() reports a provider failure as "[Agent error: <exception text>]".
That prefix is a contract — run_prediction_agent retries on it, the
orchestrator produces it for a crashed agent, the eval cases feed it in as
degraded input — so it stays. What changes is what the page shows: the
exception text is a raw SDK dump ("Error code: 402 - {'error': {'message':
'Insufficient Balance', ...}}") that the UI used to print verbatim in the
prediction card and every agent tab. describe() turns it into one short line
and keeps the original, credential-redacted, as `detail` for a tooltip and
the server log.
"""
from __future__ import annotations

import re
from typing import Optional

AGENT_ERROR_PREFIX = "[Agent error:"

# The openai SDK renders an HTTP failure as "Error code: 402 - {...body...}".
_STATUS = re.compile(r"Error code:\s*(\d{3})\b")

_BY_STATUS = {
    401: "auth",
    402: "insufficient_balance",
    429: "rate_limit",
}

# For failures with no status line (timeouts, DNS, a body without the prefix).
_BY_TEXT = (
    ("insufficient_balance", re.compile(r"insufficient[ _]balance", re.I)),
    ("auth",                 re.compile(r"authentication|invalid api key|incorrect api key", re.I)),
    ("rate_limit",           re.compile(r"rate[ _]limit|too many requests", re.I)),
    ("timeout",              re.compile(r"timed? ?out", re.I)),
    ("connection",           re.compile(r"connection error|could not resolve|name resolution", re.I)),
)

_REASONS = {
    "insufficient_balance": "the DeepSeek account has insufficient balance",
    "auth":                 "the DeepSeek API key was rejected",
    "rate_limit":           "DeepSeek is rate-limiting requests; try again shortly",
    "timeout":              "the DeepSeek request timed out",
    "connection":           "DeepSeek could not be reached",
    "server_error":         "DeepSeek returned a server error",
    "unknown":              "the language-model call failed",
}

# DeepSeek's 401 body names the key it rejected ("Your api key: ****abcd is
# invalid"). It arrives masked, but no part of a key belongs on a page.
_KEY_ECHO = re.compile(r"(api[ _-]?key\s*[:=]\s*)\S+", re.I)

_DETAIL_MAX = 300


def redact(text: str) -> str:
    """The research traces' redaction rule, plus the provider's key echo."""
    from mas.research.execute import redact as _redact
    return _KEY_ECHO.sub(r"\1[redacted]", _redact(text))


def agent_error(exc: BaseException) -> str:
    """The "[Agent error: ...]" string for a failed call, credentials removed
    at the source so the raw field is as safe as the message built from it."""
    return f"{AGENT_ERROR_PREFIX} {redact(str(exc))}]"


def is_agent_error(text) -> bool:
    return isinstance(text, str) and text.startswith(AGENT_ERROR_PREFIX)


def describe(text, what: str = "AI analysis") -> Optional[dict]:
    """{kind, status, message, detail} for an "[Agent error: ...]" string;
    None for anything else (including a real answer that merely mentions an
    error). `message` is for the page; `detail` is for a tooltip and logs."""
    if not is_agent_error(text):
        return None
    raw = text[len(AGENT_ERROR_PREFIX):].strip()
    if raw.endswith("]"):
        raw = raw[:-1].rstrip()

    m = _STATUS.search(raw)
    status = int(m.group(1)) if m else None
    kind = _BY_STATUS.get(status)
    if kind is None and status is not None and 500 <= status <= 599:
        kind = "server_error"
    if kind is None:
        kind = next((k for k, rx in _BY_TEXT if rx.search(raw)), "unknown")

    detail = " ".join(redact(raw).split())
    if len(detail) > _DETAIL_MAX:
        detail = detail[:_DETAIL_MAX - 1] + "…"
    return {
        "kind": kind,
        "status": status,
        "message": f"{what} unavailable: {_REASONS[kind]}",
        "detail": detail,
    }
