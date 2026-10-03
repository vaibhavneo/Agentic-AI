"""
Verification that a failed LLM call reaches the page as one readable line,
not a provider dump and not "$NaN".

Run: python3 tests/test_llm_error_display.py

Why this file exists: production's DeepSeek account ran out of balance and
every call returned HTTP 402. The prediction fallback copied the raw
"[Agent error: Error code: 402 - {'error': ...}]" text into `summary`, the
four agent tabs printed the same dump, and the Grounded Analysis panel ran
Number() over the fallback's "$123.45" / "N/A" placeholders and showed
"$NaN" for entry, target and stop.

Offline/deterministic - the provider failure is a real openai.APIStatusError
raised by a stubbed client; no network, no API key, no DB writes.

What must hold:
  1. A 402 becomes "AI prediction unavailable: the DeepSeek account has
     insufficient balance"; the dump survives only as `detail`.
  2. Other failures get their own reason; ordinary analysis text is never
     mistaken for an error.
  3. No credential reaches the error string, the message, or the detail.
  4. The prediction fallback carries `llm_error` and a clean summary, and
     still satisfies the prediction schema.
  5. Grounding does not invent entry/target/stop for a failed call: with no
     direction there is no strategy agreement, so the levels stay
     uncomputed (the page shows "—" and the reason).
  6. analyze_stock() reports each failed agent in `agent_errors` while the
     *_analysis fields keep their "[Agent error:" contract.
"""
import contextlib
import io
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import openai
import pandas as pd

from agents.llm_errors import describe
from agents.prediction_schema import validate_prediction
from agents.stock_agents import _call, run_prediction_agent

FAILURES = []

BODY_402 = {"error": {"message": "Insufficient Balance", "type": "unknown_error",
                      "param": None, "code": "invalid_request_error"}}
# Exactly what production showed on the page.
RAW_402 = f"[Agent error: Error code: 402 - {BODY_402}]"
MSG_402 = "AI prediction unavailable: the DeepSeek account has insufficient balance"


def check(name, cond, detail=""):
    print(f"  {name:66s} {'OK' if cond else 'FAIL'}  {detail}")
    if not cond:
        FAILURES.append(name)
    # Fails the process, not just the transcript: a check that only prints
    # leaves a pytest run green regardless of what it found.
    assert cond, name


def _status_error(code: int, body) -> openai.APIStatusError:
    """The exception the openai SDK raises for an HTTP failure, built the
    way the SDK builds it (message = "Error code: <code> - <body>")."""
    req = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    return openai.APIStatusError(f"Error code: {code} - {body}",
                                 response=httpx.Response(code, request=req), body=body)


def _failing_client(exc):
    client = MagicMock()
    client.chat.completions.create.side_effect = exc
    return client


def test_402_is_said_in_one_line_with_the_dump_kept_as_detail():
    err = describe(RAW_402, "AI prediction")
    check("402 is recognised as an agent error", err is not None)
    check("402 message is the one-line human sentence", err["message"] == MSG_402, err["message"])
    check("402 status and kind are kept", err["status"] == 402 and err["kind"] == "insufficient_balance")
    check("the provider's wording survives in detail", "Insufficient Balance" in err["detail"], err["detail"])
    check("no SDK dump in the message", "Error code" not in err["message"] and "{" not in err["message"])


def test_other_failures_get_their_own_reason():
    cases = {
        "[Agent error: Error code: 401 - {'error': {'message': 'Authentication Fails'}}]": "auth",
        "[Agent error: Error code: 429 - {'error': {'message': 'Rate limit reached'}}]": "rate_limit",
        "[Agent error: Error code: 503 - {'error': {'message': 'Service Unavailable'}}]": "server_error",
        "[Agent error: Request timed out.]": "timeout",
        "[Agent error: DeepSeek timeout after 180s]": "timeout",
        "[Agent error: Connection error.]": "connection",
        "[Agent error: something nobody planned for]": "unknown",
    }
    for raw, kind in cases.items():
        err = describe(raw)
        check(f"{kind:>13} <- {raw[14:50]}", err is not None and err["kind"] == kind,
              err and err["kind"])
    check("an analysis agent says 'AI analysis unavailable'",
          describe("[Agent error: Request timed out.]")["message"].startswith("AI analysis unavailable: "))
    check("real analysis text that mentions an error is not an error",
          describe("Margins fell; an accounting error was restated in Q2.") is None)
    check("None / non-string is not an error", describe(None) is None and describe({"a": 1}) is None)


def test_no_key_reaches_the_message_the_detail_or_the_raw_field():
    canary = "sk-CANARY-llmerr-5e1f2a9b7c3d4e"
    saved = os.environ.get("DEEPSEEK_API_KEY")
    os.environ["DEEPSEEK_API_KEY"] = canary
    try:
        # An SDK/adapter that echoes the key it was given, plus DeepSeek's own
        # masked echo of the rejected key.
        body = {"error": {"message": "Authentication Fails, Your api key: ****4e1f is invalid"}}
        exc = _status_error(401, body)
        exc.args = (f"{exc} (sent Authorization: Bearer {canary})",)
        raw = _call(_failing_client(exc), "sys", "user")
        err = describe(raw)
        check("raw '[Agent error:' contract is kept", raw.startswith("[Agent error:"), raw[:40])
        check("the live key is not in the raw field", canary not in raw, raw)
        check("the live key is not in message or detail",
              canary not in err["message"] and canary not in err["detail"])
        check("the provider's masked key echo is redacted too", "****4e1f" not in err["detail"], err["detail"])
        check("a 401 reads as a rejected key", err["kind"] == "auth", err["kind"])
    finally:
        if saved is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = saved


def _fallback_on_402():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        pred = run_prediction_agent(
            _failing_client(_status_error(402, BODY_402)), "TEST", "Test Co", 123.45,
            "f", "t", {"score": 50, "direction": "NEUTRAL"}, "s", "a")
    return pred, out.getvalue()


def test_prediction_fallback_on_402_carries_a_clean_summary_and_llm_error():
    pred, log = _fallback_on_402()
    check("a failed call falls back to HOLD/LOW", pred["action"] == "HOLD" and pred["conviction"] == "LOW")
    check("summary is the one-line message", pred["summary"] == MSG_402, pred["summary"])
    check("llm_error is attached for the page", (pred.get("llm_error") or {}).get("kind") == "insufficient_balance")
    check("the dump is kept in llm_error.detail", "Insufficient Balance" in pred["llm_error"]["detail"])
    check("the dump is logged for the server", "Insufficient Balance" in log and MSG_402 in log, log[:120])
    check("the fallback still satisfies the prediction schema",
          validate_prediction(pred).valid, str(validate_prediction(pred).errors))


def test_unparseable_prose_is_not_reported_as_a_provider_failure():
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="I think it's a hold."))])
    pred = run_prediction_agent(client, "TEST", "Test Co", 10.0, "f", "t",
                                {"score": 50, "direction": "NEUTRAL"})
    check("a model that answered in prose is not an llm_error", "llm_error" not in pred)
    check("its own words stay the summary", pred["summary"] == "I think it's a hold.", pred["summary"])


def test_grounding_does_not_invent_levels_for_a_failed_call():
    """The intent check behind showing "—": synthesis.py prices entry/target/
    stop only when a backtested strategy agrees with the call's DIRECTION. A
    failed call has none (HOLD), so even though entry = current price would
    be trivial to fill in, grounding leaves the levels uncomputed."""
    from agents.synthesis import ground_prediction
    pred, _ = _fallback_on_402()
    df = pd.DataFrame(
        {"Open": 100.0, "High": 102.0, "Low": 98.0,
         "Close": [100.0 + (i % 7) for i in range(300)], "Volume": 1e6},
        index=pd.bdate_range("2023-01-02", periods=300))
    with patch("agents.synthesis._record_live_trial"):           # no ledger writes
        grounded = ground_prediction("TEST", 123.45, pred, df, {})
    check("no strategy grounds a call that never happened", grounded["grounding"] == "none")
    check("ATR is still computed from price data", isinstance(grounded["grounding_atr"], float))
    for k in ("entry_price", "target_price", "stop_loss"):
        check(f"{k} is not turned into a computed number",
              not isinstance(grounded[k], (int, float)), repr(grounded[k]))
    check("llm_error survives grounding for the page", grounded.get("llm_error", {}).get("message") == MSG_402)


def test_analyze_stock_reports_each_failed_agent():
    df = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1e6},
                      index=pd.bdate_range("2023-01-02", periods=300))
    raw_401 = "[Agent error: Error code: 401 - {'error': {'message': 'Authentication Fails'}}]"
    analysis = {"fundamentals_analysis": RAW_402, "technical_analysis": RAW_402,
                "social_analysis": "Retail chatter is quiet.", "algo_analysis": raw_401}
    stubs = {
        "agents.orchestrator._get_client": object(),
        "agents.orchestrator.fetch_price_history": df,
        "agents.orchestrator.fetch_fundamentals": {},
        "agents.orchestrator.fetch_earnings": {},
        "agents.orchestrator.fetch_analyst_ratings": {},
        "agents.orchestrator.compute_indicators": {"current_price": 100.0},
        "agents.orchestrator.compute_signal_summary": {"score": 50, "direction": "NEUTRAL"},
        "agents.orchestrator.compute_algo_signals": {},
        "agents.orchestrator.fetch_reddit_sentiment": {},
        "agents.orchestrator.fetch_stocktwits_sentiment": {},
        "agents.orchestrator.fetch_web_forum_sentiment": {},
        "agents.orchestrator.compute_pillar_scores": {"pillars": {}},
        "agents.orchestrator._run_analysis_agents": analysis,
        "agents.orchestrator.run_prediction_agent": {"action": "HOLD", "summary": MSG_402},
        "agents.orchestrator.log_recommendation": None,
        "agents.fundamentals_pit.analyze_fundamentals_pit": None,
    }
    with contextlib.ExitStack() as stack:
        for target, value in stubs.items():
            stack.enter_context(patch(target, return_value=value))
        stack.enter_context(patch("agents.orchestrator.ground_prediction", side_effect=lambda t, p, pred, *a: pred))
        stack.enter_context(patch("intelligence.regime.compute_market_regime", side_effect=RuntimeError("offline")))
        stack.enter_context(patch("agents.recommendation.build_recommendation", side_effect=RuntimeError("offline")))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        from agents.orchestrator import analyze_stock
        result = analyze_stock("TEST", api_key="fake-key", verbose=False)

    errs = result.get("agent_errors", {})
    check("failed agents are listed, the healthy one is not",
          set(errs) == {"fundamentals", "technical", "algo"}, str(sorted(errs)))
    check("a 402 agent tab reads as an out-of-balance account",
          errs["fundamentals"]["message"] == "AI analysis unavailable: the DeepSeek account has insufficient balance",
          errs["fundamentals"]["message"])
    check("a 401 agent tab reads as a rejected key", errs["algo"]["kind"] == "auth")
    check("the raw *_analysis fields keep the '[Agent error:' contract",
          result["fundamentals_analysis"].startswith("[Agent error:"))


if __name__ == "__main__":
    test_402_is_said_in_one_line_with_the_dump_kept_as_detail()
    test_other_failures_get_their_own_reason()
    test_no_key_reaches_the_message_the_detail_or_the_raw_field()
    test_prediction_fallback_on_402_carries_a_clean_summary_and_llm_error()
    test_unparseable_prose_is_not_reported_as_a_provider_failure()
    test_grounding_does_not_invent_levels_for_a_failed_call()
    test_analyze_stock_reports_each_failed_agent()
    print(f"\n{'ALL PASS' if not FAILURES else f'{len(FAILURES)} FAILED'}")
    sys.exit(1 if FAILURES else 0)
