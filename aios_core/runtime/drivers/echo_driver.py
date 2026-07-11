"""Built-in test skill: echoes its input. Used by runtime + composition tests."""
def run(inputs: dict, context: dict) -> dict:
    return {"echoed": inputs["message"]}


_FLAKY_STATE = {"failures_left": 0}

def arm_flaky(n_failures: int):
    _FLAKY_STATE["failures_left"] = n_failures

def run_flaky(inputs: dict, context: dict) -> dict:
    """Test fixture: fails N times (armed via arm_flaky), then succeeds."""
    if _FLAKY_STATE["failures_left"] > 0:
        _FLAKY_STATE["failures_left"] -= 1
        raise RuntimeError("transient failure (armed)")
    return {"echoed": inputs.get("message", "")}
