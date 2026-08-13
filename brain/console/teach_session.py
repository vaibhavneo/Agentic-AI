"""
Console-owned bookkeeping for the conversational teaching UI (/api/ask).

Two independent, pure/deterministic pieces, unit-testable in isolation:
  - resolve_turn()  turns a free-text chat message into {topic, mode, depth}
                     using keyword heuristics — no model call, so a follow-up
                     like "simpler please" never silently invents a new topic.
  - to_speech()      strips markdown/LaTeX into something speechSynthesis can
                     read aloud without narrating symbols.

Session/mastery state is a single JSON file under memory/ (P1 files-are-
memory) — the same pattern app.py already uses for memory/uploads and
memory/console_runs. Not a new store: no DB, no new subsystem, just another
file in the existing memory root, read back through the memory SDK.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── conversation threading ──────────────────────────────────────────────────

_FOLLOWUP_REF = re.compile(r"\b(that|this|it|the topic|the concept|again|please)\b", re.I)

_ADJUSTMENTS = [
    (re.compile(r"\b(simpler|simplify|simply|simple|eli5|dumb it down|basic|easier|beginner)\b", re.I), {"depth": "intro"}),
    (re.compile(r"\b(math|formula|equation|derive|derivation|advanced|deeper|"
                r"in-?depth|rigorous)\b", re.I), {"depth": "advanced"}),
    (re.compile(r"\b(quiz|exercise|practice|test me)\b", re.I), {"mode": "exercise"}),
    (re.compile(r"\b(socratic|guide me|ask me questions)\b", re.I), {"mode": "socratic"}),
    (re.compile(r"\b(compare|vs\.?|versus|difference between)\b", re.I), {"mode": "compare"}),
]

# Filler words that don't introduce a new SUBJECT, so a message made only of
# these (plus adjustment/reference keywords) is a pure refinement of the current
# topic rather than a new question.
_FOLLOWUP_STOPWORDS = set(
    "a an the to of for on in is are do does can could would should will me my "
    "mine you your i we us now show tell give explain teach make help want "
    "please again some what how why with about more less bit little lot really "
    "just also and or but so then this that it its".split())


def _is_pure_refinement(message: str, matched: list) -> bool:
    """True when the message, after removing adjustment keywords, reference
    words, and filler, has essentially no new subject of its own (≤1 content
    word) — i.e. it refines the CURRENT topic ("simpler", "now the math",
    "quiz me on that") rather than asking about something new. A long question
    that merely happens to contain "that"/"it" therefore is NOT a follow-up."""
    text = message.lower()
    for pat, _u in _ADJUSTMENTS:
        text = pat.sub(" ", text)
    text = _FOLLOWUP_REF.sub(" ", text)
    residual = [w for w in re.findall(r"[a-z][a-z-]{2,}", text)
                if w not in _FOLLOWUP_STOPWORDS]
    return len(residual) <= 1


def resolve_turn(session: dict, message: str, explicit_topic=None,
                  explicit_mode=None, explicit_depth=None) -> dict:
    """Deterministically resolve one chat message into teacher-skill inputs.

    A message is treated as a follow-up (reusing the session's last topic) only
    when there IS a last topic AND the message is a SHORT pure refinement of it
    (a reference like "that"/"again" or an adjustment like "simpler"/"the math",
    with no substantive new subject of its own). A longer question, or one that
    names its own topic, is always a fresh topic — even if it happens to contain
    a word like "that" — so we never silently answer the previous question.
    """
    message = (message or "").strip()
    last_topic = (session or {}).get("last_topic")
    matched = [u for pat, u in _ADJUSTMENTS if pat.search(message)]
    short = len(message.split()) <= 8
    has_ref = bool(matched or _FOLLOWUP_REF.search(message))
    is_followup = bool(last_topic and explicit_topic is None
                        and short and has_ref
                        and _is_pure_refinement(message, matched))

    topic = explicit_topic or (last_topic if is_followup else message)

    # Keyword-derived hints from THIS message. They make "auto" (dropdown left
    # unset) intelligent — "compare X vs Y" picks compare mode, "explain simply"
    # picks intro depth — on EVERY turn, not just follow-ups (the old behavior
    # ignored them on a fresh question, so auto always fell back to
    # explain/intermediate). An EXPLICIT dropdown selection always wins over a
    # keyword; a keyword wins over the session default.
    kw_mode = next((u["mode"] for u in matched if "mode" in u), None)
    kw_depth = next((u["depth"] for u in matched if "depth" in u), None)

    if explicit_mode is not None:
        mode = explicit_mode
    elif kw_mode is not None:
        mode = kw_mode
    elif is_followup:
        mode = (session or {}).get("last_mode", "explain")
    else:
        mode = "explain"

    if explicit_depth is not None:
        depth = explicit_depth
    elif kw_depth is not None:
        depth = kw_depth
    elif is_followup:
        depth = (session or {}).get("last_depth", "intermediate")
    else:
        depth = "intermediate"

    return {"topic": topic, "mode": mode, "depth": depth, "is_followup": is_followup}


# ── session / mastery store (memory/teacher_sessions.json) ─────────────────

def new_session_id() -> str:
    return uuid.uuid4().hex[:16]


def load_store(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"sessions": {}, "mastery": {}}


def save_store(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))


def get_session(store: dict, session_id: str) -> dict:
    return store.setdefault("sessions", {}).setdefault(session_id, {"turns": []})


def record_turn(store: dict, session_id: str, topic: str, mode: str, depth: str,
                 concept_name: str) -> None:
    session = get_session(store, session_id)
    session["last_topic"] = topic
    session["last_mode"] = mode
    session["last_depth"] = depth
    session["last_concept"] = concept_name
    turns = session.setdefault("turns", [])
    turns.append({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "topic": topic, "mode": mode, "depth": depth, "concept": concept_name})
    session["turns"] = turns[-20:]


def bump_mastery(store: dict, concept_name: str) -> None:
    m = store.setdefault("mastery", {}).setdefault(concept_name, {"prior_activity": 0})
    m["prior_activity"] = m.get("prior_activity", 0) + 1


def _concept_confidence(concept_name: str):
    """Best-effort read of the critic-assigned confidence for this concept
    from the existing concept store (memory/concepts.json) — the same field
    the teacher skill's mastery.confidence documents as its source."""
    try:
        from second_brain import concept_store
        c = concept_store.load()["concepts"].get(concept_name)
        return c.get("confidence") if c else None
    except Exception:
        return None


def build_mastery_input(store: dict, concept_name: str):
    """mastery input for the NEXT turn about `concept_name`, or None when
    there is nothing yet to report (schema: absent ⇒ unknown mastery)."""
    if not concept_name:
        return None
    m = store.get("mastery", {}).get(concept_name, {})
    prior_activity = m.get("prior_activity", 0)
    confidence = _concept_confidence(concept_name)
    if prior_activity == 0 and confidence is None:
        return None
    out = {"concept": concept_name, "prior_activity": prior_activity}
    if confidence is not None:
        out["confidence"] = confidence
    return out


# ── text-to-speech normalization ────────────────────────────────────────────

_LATEX_BLOCK = re.compile(r"\$\$(.+?)\$\$", re.S)
_LATEX_INLINE = re.compile(r"\$(.+?)\$")
_MD_CODE_BLOCK = re.compile(r"```.*?```", re.S)
_MD_INLINE_CODE = re.compile(r"`([^`]+)`")
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_MD_HEADER = re.compile(r"^#{1,6}\s*", re.M)
_MD_BULLET = re.compile(r"^\s*[-*+]\s+", re.M)
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_MD_ITALIC = re.compile(r"\*(.+?)\*|_(.+?)_")

_LATEX_SUBSTITUTIONS = [
    (re.compile(r"\\frac\{(.+?)\}\{(.+?)\}"), r"\1 over \2"),
    (re.compile(r"\\sqrt\{(.+?)\}"), r"square root of \1"),
    (re.compile(r"\\sum"), " sum "),
    (re.compile(r"\\int"), " integral "),
    (re.compile(r"\\infty"), " infinity "),
    (re.compile(r"\\alpha"), " alpha "), (re.compile(r"\\beta"), " beta "),
    (re.compile(r"\\theta"), " theta "), (re.compile(r"\\pi"), " pi "),
    (re.compile(r"\\times"), " times "), (re.compile(r"\\cdot"), " times "),
    (re.compile(r"\\leq"), " less than or equal to "),
    (re.compile(r"\\geq"), " greater than or equal to "),
    (re.compile(r"\\neq"), " not equal to "),
    (re.compile(r"\^\{?(-?[a-zA-Z0-9]+)\}?"), r" to the power of \1 "),
    (re.compile(r"_\{?([a-zA-Z0-9]+)\}?"), r" sub \1 "),
    (re.compile(r"\\left|\\right"), ""),
    (re.compile(r"[{}]"), ""),
    (re.compile(r"\\"), ""),
    (re.compile(r"="), " equals "),
]


def _delatex(expr: str) -> str:
    out = expr
    for pat, repl in _LATEX_SUBSTITUTIONS:
        out = pat.sub(repl, out)
    return re.sub(r"\s+", " ", out).strip()


def to_speech(text: str) -> str:
    """Deterministically flatten markdown + LaTeX into plain speakable text.
    Pure function — no model call, no I/O — so it is fully unit-testable."""
    if not text:
        return ""
    t = text
    t = _LATEX_BLOCK.sub(lambda m: " " + _delatex(m.group(1)) + " ", t)
    t = _LATEX_INLINE.sub(lambda m: " " + _delatex(m.group(1)) + " ", t)
    t = _MD_CODE_BLOCK.sub(" code block omitted ", t)
    t = _MD_INLINE_CODE.sub(lambda m: m.group(1), t)
    t = _MD_LINK.sub(lambda m: m.group(1), t)
    t = _MD_HEADER.sub("", t)
    t = _MD_BULLET.sub("", t)
    t = _MD_BOLD.sub(lambda m: m.group(1) or m.group(2) or "", t)
    t = _MD_ITALIC.sub(lambda m: m.group(1) or m.group(2) or "", t)
    t = re.sub(r"[#*_`>~]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t
