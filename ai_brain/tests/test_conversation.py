"""Offline regression test for conversation.py's session persistence.

    python3 tests/test_conversation.py

No network: CONVERSATION_PATH is redirected to a scratch temp file for the
whole run so this never touches the real memory/conversation.json.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import conversation

fails = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  — ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)
    return ok


_tmp = tempfile.TemporaryDirectory()
conversation.CONVERSATION_PATH = Path(_tmp.name) / "conversation.json"

print("[empty state]")
check("no conversation yet -> {}", conversation.load_conversation() == {})

print("\n[append_turn]")
messages = conversation.append_turn("What is a gradient?", "It's the vector of partial derivatives.")
check("returns 2 messages after first turn", len(messages) == 2)
check("first message is the user question", messages[0] == {"role": "user", "content": "What is a gradient?"})
check("second message is the assistant answer",
     messages[1] == {"role": "assistant", "content": "It's the vector of partial derivatives."})

print("\n[persistence across loads]")
loaded = conversation.load_conversation()
check("loaded messages match what was appended", loaded.get("messages") == messages)
check("has created_at", bool(loaded.get("created_at")))
check("has updated_at", bool(loaded.get("updated_at")))

print("\n[accumulates across multiple turns]")
conversation.append_turn("Why does it point uphill?", "By definition of the directional derivative.")
after_two = conversation.load_conversation()["messages"]
check("4 messages after two turns", len(after_two) == 4)
check("created_at stable across turns", loaded["created_at"] == conversation.load_conversation()["created_at"])

print("\n[trims to MAX_STORED_TURNS]")
for i in range(conversation.MAX_STORED_TURNS + 5):
    conversation.append_turn(f"q{i}", f"a{i}")
trimmed = conversation.load_conversation()["messages"]
check("trimmed to MAX_STORED_TURNS*2 messages", len(trimmed) == conversation.MAX_STORED_TURNS * 2)
check("oldest turns dropped, newest kept",
     trimmed[-1]["content"] == f"a{conversation.MAX_STORED_TURNS + 4}")

print("\n[reset_conversation]")
conversation.reset_conversation()
check("conversation cleared after reset", conversation.load_conversation() == {})
check("reset is idempotent (no error calling twice)", conversation.reset_conversation() is None)

print()
if fails:
    print(f"{len(fails)} check(s) FAILED")
    sys.exit(1)
print("ALL PASS")
