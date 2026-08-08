const PROFILE_ID = document.body.dataset.profileId;
const chatLog = document.getElementById("chat-log");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");

const history = [];

function appendMessage(role, text) {
  const div = document.createElement("div");
  div.className = `chat-msg chat-${role}`;
  div.innerHTML = `<strong>${role === "user" ? "You" : "Coach"}:</strong> <span></span>`;
  div.querySelector("span").textContent = text;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
  return div;
}

function appendDataUsed(dataUsed) {
  if (!dataUsed || !dataUsed.length) return;
  const details = document.createElement("details");
  details.className = "data-used";
  const summary = document.createElement("summary");
  summary.textContent = `Data used (${dataUsed.length} tool call${dataUsed.length > 1 ? "s" : ""})`;
  details.appendChild(summary);
  const pre = document.createElement("pre");
  pre.textContent = dataUsed.map((d) => `${d.tool}(${JSON.stringify(d.arguments)}) -> ${JSON.stringify(d.result)}`).join("\n\n");
  details.appendChild(pre);
  chatLog.appendChild(details);
  chatLog.scrollTop = chatLog.scrollHeight;
}

// A profile can go stale without a page reload (e.g. it's deleted or the
// database is reset in another tab/process while this page stays open) —
// PROFILE_ID is baked into the DOM at page-load time and isn't re-checked
// until the user actually sends a message. When that happens, the backend
// correctly returns a 404, but the raw "no such profile" string must never
// reach the chat transcript verbatim (see tests/integration/test_coach_and_insights_api.py).
function appendNoProfileMessage() {
  const div = document.createElement("div");
  div.className = "chat-msg chat-assistant chat-error";
  div.innerHTML = 'Your active profile could not be found — it may have been removed or reset. ' +
    '<a href="/profile">Go to Profile &amp; Targets</a> to create or select one.';
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;

  if (!PROFILE_ID) {
    appendMessage("user", message);
    chatInput.value = "";
    appendNoProfileMessage();
    return;
  }

  appendMessage("user", message);
  chatInput.value = "";
  chatInput.disabled = true;

  try {
    const res = await fetch(`/api/profiles/${PROFILE_ID}/coach/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history }),
    });

    if (res.status === 404) {
      appendNoProfileMessage();
      return;
    }

    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "request failed");

    appendMessage("assistant", data.answer);
    appendDataUsed(data.data_used);

    history.push({ role: "user", content: message });
    history.push({ role: "assistant", content: data.answer });
  } catch (err) {
    appendMessage("assistant", "Something went wrong answering that — please try again.");
  } finally {
    chatInput.disabled = false;
    chatInput.focus();
  }
});
