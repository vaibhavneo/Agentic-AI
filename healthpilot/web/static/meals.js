const PROFILE_ID = document.body.dataset.profileId;

async function callApi(url, method, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
  return data;
}

const recomputeBtn = document.getElementById("recompute-btn");
if (recomputeBtn) {
  recomputeBtn.addEventListener("click", async () => {
    await callApi(`/api/profiles/${PROFILE_ID}/nutrition/targets/recompute`, "POST", {});
    window.location.reload();
  });
}

const generateRemainingBtn = document.getElementById("generate-remaining-btn");
if (generateRemainingBtn) {
  generateRemainingBtn.addEventListener("click", async () => {
    const resultEl = document.getElementById("generate-remaining-result");
    resultEl.textContent = "Generating...";
    try {
      const plan = await callApi(`/api/profiles/${PROFILE_ID}/nutrition/generate-remaining-plan`, "POST", {});
      if (!plan.meals.length) {
        resultEl.textContent = "All of today's meals are already logged.";
        return;
      }
      const lines = plan.meals.map((m) => {
        const time = m.suggested_time ? ` (suggested ${m.suggested_time})` : "";
        return `${m.meal_type}${time}: ${m.items.map((i) => i.food_name).join(", ")}`;
      });
      resultEl.innerHTML = `<p>Proposed (not logged yet):</p><ul>${lines.map((l) => `<li>${l}</li>`).join("")}</ul>` +
        `<p class="muted">Fits within ${plan.remaining_target.calories} kcal / ${plan.remaining_target.sodium_mg}mg sodium remaining today.</p>`;
    } catch (err) {
      resultEl.textContent = `Error: ${err.message}`;
    }
  });
}

const nlForm = document.getElementById("nl-log-form");
if (nlForm) {
  nlForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(nlForm);
    const resultEl = document.getElementById("nl-log-result");
    resultEl.textContent = "Logging...";
    try {
      const result = await callApi(`/api/profiles/${PROFILE_ID}/meals/log_text`, "POST", {
        meal_type: fd.get("meal_type"),
        text: fd.get("text"),
      });
      const loggedNames = result.logged.map((l) => `${l.quantity} x ${l.food_name}`).join(", ");
      const unresolvedNames = result.unresolved.map((u) => u.query).join(", ");
      let msg = loggedNames ? `Logged: ${loggedNames}.` : "Nothing was matched.";
      if (unresolvedNames) msg += ` Could not find a match for: ${unresolvedNames} — add manually below.`;
      resultEl.textContent = msg;
      if (result.logged.length) setTimeout(() => window.location.reload(), 1200);
    } catch (err) {
      resultEl.textContent = `Error: ${err.message}`;
    }
  });
}

const searchForm = document.getElementById("search-form");
if (searchForm) {
  searchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(searchForm);
    const resultsEl = document.getElementById("search-results");
    resultsEl.innerHTML = "Searching...";
    try {
      const foods = await callApi(`/api/foods/search?q=${encodeURIComponent(fd.get("q"))}`, "GET");
      if (!foods.length) {
        resultsEl.innerHTML = "<p class='muted'>No matches. Try a different term.</p>";
        return;
      }
      resultsEl.innerHTML = "";
      foods.forEach((food) => {
        const row = document.createElement("div");
        row.className = "food-result";
        const servingOptions = food.servings
          .map((s) => `<option value="${s.id}">${s.description}</option>`)
          .join("");
        row.innerHTML = `
          <strong>${food.name}</strong> (${food.calories_kcal} kcal / 100g)
          <select class="serving-select">${servingOptions}</select>
          <input class="qty-input" type="number" value="1" min="0.1" step="0.1" style="width:4rem">
          <select class="meal-type-select">
            <option value="breakfast">breakfast</option>
            <option value="lunch">lunch</option>
            <option value="dinner">dinner</option>
            <option value="snack">snack</option>
          </select>
          <button type="button" class="link-btn add-food-btn">Add</button>
        `;
        row.querySelector(".add-food-btn").addEventListener("click", async () => {
          await callApi(`/api/profiles/${PROFILE_ID}/meals/log`, "POST", {
            food_id: food.id,
            serving_id: Number(row.querySelector(".serving-select").value),
            quantity: Number(row.querySelector(".qty-input").value),
            meal_type: row.querySelector(".meal-type-select").value,
          });
          window.location.reload();
        });
        resultsEl.appendChild(row);
      });
    } catch (err) {
      resultsEl.innerHTML = `<p class="error">${err.message}</p>`;
    }
  });
}

document.querySelectorAll(".delete-meal-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (!confirm("Delete this meal?")) return;
    await callApi(`/api/profiles/${PROFILE_ID}/meals/${btn.dataset.mealId}`, "DELETE");
    window.location.reload();
  });
});

document.querySelectorAll(".water-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    await callApi(`/api/profiles/${PROFILE_ID}/water`, "POST", { amount_ml: Number(btn.dataset.ml) });
    window.location.reload();
  });
});
