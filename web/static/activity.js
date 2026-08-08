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

const typeSelect = document.getElementById("workout-type-select");
const cardioFields = document.getElementById("cardio-fields");
const strengthFields = document.getElementById("strength-fields");
const setsContainer = document.getElementById("strength-sets-container");

function toggleFields() {
  const isCardio = typeSelect.value === "cardio";
  cardioFields.style.display = isCardio ? "" : "none";
  strengthFields.style.display = isCardio ? "none" : "";
}
if (typeSelect) {
  typeSelect.addEventListener("change", toggleFields);
  toggleFields();
}

function addSetRow() {
  const row = document.createElement("div");
  row.className = "grid-2 set-row";
  row.innerHTML = `
    <label>Exercise <input class="set-exercise" required></label>
    <label>Reps <input class="set-reps" type="number" required></label>
    <label>Weight (kg) <input class="set-weight" type="number" step="0.5"></label>
    <label>RPE <input class="set-rpe" type="number" min="1" max="10"></label>
  `;
  setsContainer.appendChild(row);
}
const addSetBtn = document.getElementById("add-set-btn");
if (addSetBtn) {
  addSetBtn.addEventListener("click", addSetRow);
  addSetRow();
}

const workoutForm = document.getElementById("workout-form");
if (workoutForm) {
  workoutForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errEl = document.getElementById("workout-form-error");
    errEl.textContent = "";
    const fd = new FormData(workoutForm);
    const workoutType = fd.get("workout_type");

    const body = {
      workout_type: workoutType,
      activity: fd.get("activity"),
      duration_min: fd.get("duration_min") || undefined,
      rpe: fd.get("rpe") || undefined,
      notes: fd.get("notes") || undefined,
    };

    if (workoutType === "cardio") {
      body.distance_km = fd.get("distance_km") || undefined;
      body.steps = fd.get("steps") || undefined;
      body.avg_hr = fd.get("avg_hr") || undefined;
      body.max_hr = fd.get("max_hr") || undefined;
      body.intensity = fd.get("intensity");
      body.wearable_calories = fd.get("wearable_calories") || undefined;
    } else {
      body.strength_sets = Array.from(setsContainer.querySelectorAll(".set-row")).map((row, i) => ({
        exercise_name: row.querySelector(".set-exercise").value,
        set_number: i + 1,
        reps: Number(row.querySelector(".set-reps").value),
        weight_kg: row.querySelector(".set-weight").value ? Number(row.querySelector(".set-weight").value) : undefined,
        rpe: row.querySelector(".set-rpe").value ? Number(row.querySelector(".set-rpe").value) : undefined,
      })).filter((s) => s.exercise_name && s.reps);
    }

    try {
      await callApi(`/api/profiles/${PROFILE_ID}/workouts`, "POST", body);
      window.location.reload();
    } catch (err) {
      errEl.textContent = err.message;
    }
  });
}

document.querySelectorAll(".delete-workout-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (!confirm("Delete this workout?")) return;
    await callApi(`/api/profiles/${PROFILE_ID}/workouts/${btn.dataset.workoutId}`, "DELETE");
    window.location.reload();
  });
});
