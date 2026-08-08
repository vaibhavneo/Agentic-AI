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

const generateBtn = document.getElementById("generate-plan-btn");
if (generateBtn) {
  generateBtn.addEventListener("click", async () => {
    const errEl = document.getElementById("generate-plan-error");
    errEl.textContent = "";
    try {
      await callApi(`/api/profiles/${PROFILE_ID}/weekly-plan`, "POST", { week_start: generateBtn.dataset.weekStart });
      window.location.reload();
    } catch (err) {
      errEl.textContent = err.message;
    }
  });
}

document.querySelectorAll(".swap-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    try {
      await callApi(`/api/profiles/${PROFILE_ID}/plan-meals/${btn.dataset.planMealId}/swap`, "POST", {});
      window.location.reload();
    } catch (err) {
      alert(err.message);
    }
  });
});

document.querySelectorAll(".lock-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const locked = btn.dataset.locked === "1";
    await callApi(`/api/profiles/${PROFILE_ID}/plan-meals/${btn.dataset.planMealId}/lock`, "POST", { locked });
    window.location.reload();
  });
});

document.querySelectorAll(".restaurant-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    await callApi(`/api/profiles/${PROFILE_ID}/plan-meals/${btn.dataset.planMealId}/source`, "POST", { source: "restaurant" });
    window.location.reload();
  });
});

document.querySelectorAll(".leftovers-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    await callApi(`/api/profiles/${PROFILE_ID}/plan-meals/${btn.dataset.planMealId}/source`, "POST", { source: "leftovers" });
    window.location.reload();
  });
});

document.querySelectorAll(".regenerate-day-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    await callApi(`/api/profiles/${PROFILE_ID}/plan-days/${btn.dataset.dayId}/regenerate`, "POST", {});
    window.location.reload();
  });
});
