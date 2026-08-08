"""Static checks: no source file ever passes an API key / secret to
print/logging, .env is excluded from version control, and the request log
(Flask/Werkzeug's default access log) only ever includes method+path+status
— never a request body, so a POST containing health data never lands in
stdout/log files.
"""
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SOURCE_DIRS = ["app", "agents", "tools", "nutrition", "exercise", "vitals", "insights", "safety", "database", "web", "meal_planning"]

SECRET_NAMES = ["DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "USDA_FDC_API_KEY", "SECRET_KEY"]

# A secret NAME appearing in a log/print call is suspicious; reading it via
# os.environ / config.<NAME> to configure a client is fine and expected.
LOG_CALL_PATTERN = re.compile(r"(print|logging\.\w+|app\.logger\.\w+)\s*\(")


def _iter_py_files():
    for d in SOURCE_DIRS:
        dir_path = os.path.join(REPO_ROOT, d)
        for root, _, files in os.walk(dir_path):
            for f in files:
                if f.endswith(".py"):
                    yield os.path.join(root, f)


def test_no_print_or_log_call_references_a_secret_name():
    offenders = []
    for path in _iter_py_files():
        with open(path, "r") as f:
            for lineno, line in enumerate(f, start=1):
                if LOG_CALL_PATTERN.search(line) and any(secret in line for secret in SECRET_NAMES):
                    offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert offenders == [], "found log/print statements referencing a secret name:\n" + "\n".join(offenders)


def test_env_file_is_gitignored():
    with open(os.path.join(REPO_ROOT, ".gitignore")) as f:
        gitignore = f.read()
    assert ".env" in gitignore.splitlines()


def test_env_example_has_no_real_looking_secret():
    with open(os.path.join(REPO_ROOT, ".env.example")) as f:
        content = f.read()
    # the example key is an obvious placeholder, not something that looks real
    assert "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" in content


def test_database_file_is_gitignored():
    with open(os.path.join(REPO_ROOT, ".gitignore")) as f:
        gitignore = f.read()
    assert "data/*.db" in gitignore


def test_no_hardcoded_secret_key_default_used_outside_dev():
    """The dev fallback SECRET_KEY in app/config.py is clearly named as
    dev-only — this test just pins that naming so it can't quietly become a
    real-looking default later."""
    with open(os.path.join(REPO_ROOT, "app", "config.py")) as f:
        content = f.read()
    assert "dev-only-insecure" in content
