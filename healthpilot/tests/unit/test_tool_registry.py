from app.profile import create_profile
from agents.tool_registry import TOOL_REGISTRY, execute_tool
from agents.specialists import SPECIALISTS
from agents.tool_specs import build_tool_specs


def _profile():
    return create_profile(
        {
            "name": "Registry Test", "age": 29, "sex": "female", "height_cm": 170,
            "current_weight_kg": 68, "activity_level": "light", "diet_preference": "veg",
        }
    )


def test_execute_tool_dispatches_to_real_data():
    p = _profile()
    result = execute_tool("get_user_profile", p["id"], {})
    assert result["name"] == "Registry Test"


def test_execute_tool_unknown_tool_returns_error_dict():
    p = _profile()
    result = execute_tool("delete_everything", p["id"], {})
    assert "error" in result


def test_execute_tool_strips_model_supplied_profile_id():
    """A malicious/confused model passing a different profile_id in args
    must never be able to read another profile's data — the injected
    session profile_id always wins."""
    a = _profile()
    b = _profile()
    result = execute_tool("get_user_profile", a["id"], {"profile_id": b["id"]})
    assert result["id"] == a["id"]
    assert result["name"] == "Registry Test"  # both share a name, but id must match a


def test_execute_tool_catches_exceptions_as_error_dict():
    p = _profile()
    result = execute_tool("search_food", p["id"], {})  # missing required 'query'
    assert "error" in result


def test_every_specialist_tool_exists_in_registry():
    for spec in SPECIALISTS.values():
        for tool_name in spec["tools"]:
            assert tool_name in TOOL_REGISTRY, f"{tool_name} referenced by a specialist but not registered"


def test_build_tool_specs_produces_valid_function_schema():
    specs = build_tool_specs(["get_today_nutrition", "search_food"])
    assert len(specs) == 2
    assert specs[0]["type"] == "function"
    assert "name" in specs[0]["function"]
    search_spec = next(s for s in specs if s["function"]["name"] == "search_food")
    assert "query" in search_spec["function"]["parameters"]["required"]


def test_build_tool_specs_skips_unknown_tool_silently():
    specs = build_tool_specs(["get_today_nutrition", "not_a_real_tool"])
    assert len(specs) == 1
