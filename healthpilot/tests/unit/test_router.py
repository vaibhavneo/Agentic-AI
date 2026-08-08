from agents.router import route_question


def test_routes_bp_questions_to_vitals_agent():
    assert route_question("What's my blood pressure trend?") == "vitals_agent"


def test_routes_exercise_questions_to_fitness_agent():
    assert route_question("How was my workout this week?") == "fitness_agent"


def test_routes_sodium_questions_to_heart_health_agent():
    assert route_question("How much sodium have I had today?") == "heart_health_agent"


def test_routes_pattern_questions_to_health_pattern_analyst():
    assert route_question("Is there a pattern between restaurant food and my BP?") == "health_pattern_analyst"


def test_routes_meal_plan_questions_to_nutrition_planner():
    assert route_question("What should I eat tonight?") == "nutrition_planner"


def test_routes_logging_questions_to_food_logging_agent():
    assert route_question("I just had a banana, log it") == "food_logging_agent"


def test_unmatched_question_falls_back_to_general():
    assert route_question("How am I doing overall?") == "general"


def test_routing_is_case_insensitive():
    assert route_question("WHAT IS MY BLOOD PRESSURE") == "vitals_agent"
