function toListField(value) {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function toNullableString(value) {
  return value.trim() === "" ? null : value;
}

async function submitJson(url, method, body) {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `request failed (${res.status})`);
  }
  return data;
}

document.querySelectorAll(".select-form").forEach((form) => {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    await submitJson(form.action, "POST", {});
    window.location.reload();
  });
});

document.querySelectorAll(".delete-form").forEach((form) => {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!confirm("Delete this profile and all its data? This cannot be undone.")) return;
    await submitJson(form.action, "DELETE", {});
    window.location.reload();
  });
});

// --- Unit toggle (metric <-> US customary). Height/weight are always sent
// to the server as cm/kg regardless of which unit the user is viewing —
// conversion happens here, in one place, right before submit.
const CM_PER_IN = 2.54;
const KG_PER_LB = 0.453592;

function cmToFtIn(cm) {
  const totalIn = cm / CM_PER_IN;
  const ft = Math.floor(totalIn / 12);
  const inch = Math.round((totalIn - ft * 12) * 10) / 10;
  return { ft, inch };
}
function ftInToCm(ft, inch) {
  return Math.round(((Number(ft) || 0) * 12 + (Number(inch) || 0)) * CM_PER_IN * 10) / 10;
}
function kgToLb(kg) {
  return Math.round((kg / KG_PER_LB) * 10) / 10;
}
function lbToKg(lb) {
  return Math.round((lb * KG_PER_LB) * 10) / 10;
}

const unitSelect = document.getElementById("unit-system");
if (unitSelect) {
  unitSelect.addEventListener("change", () => {
    const isUS = unitSelect.value === "us";
    document.querySelectorAll(".metric-field").forEach((el) => (el.hidden = isUS));
    document.querySelectorAll(".us-field").forEach((el) => (el.hidden = !isUS));

    const heightCm = Number(profileForm.querySelector('[name="height_cm"]').value);
    const weightKg = Number(profileForm.querySelector('[name="current_weight_kg"]').value);
    const goalKg = profileForm.querySelector('[name="goal_weight_kg"]').value;

    if (isUS) {
      if (heightCm) {
        const { ft, inch } = cmToFtIn(heightCm);
        profileForm.querySelector('[name="height_ft"]').value = ft;
        profileForm.querySelector('[name="height_in"]').value = inch;
      }
      if (weightKg) profileForm.querySelector('[name="current_weight_lb"]').value = kgToLb(weightKg);
      if (goalKg) profileForm.querySelector('[name="goal_weight_lb"]').value = kgToLb(Number(goalKg));
    } else {
      const ft = profileForm.querySelector('[name="height_ft"]').value;
      const inch = profileForm.querySelector('[name="height_in"]').value;
      const weightLb = profileForm.querySelector('[name="current_weight_lb"]').value;
      const goalLb = profileForm.querySelector('[name="goal_weight_lb"]').value;
      if (ft || inch) profileForm.querySelector('[name="height_cm"]').value = ftInToCm(ft, inch);
      if (weightLb) profileForm.querySelector('[name="current_weight_kg"]').value = lbToKg(Number(weightLb));
      if (goalLb) profileForm.querySelector('[name="goal_weight_kg"]').value = lbToKg(Number(goalLb));
    }
  });
}

// Maps a fragment of the server's "; "-joined error string to the section
// it belongs to, so validation errors show up next to the relevant fields
// instead of only in one generic banner at the bottom.
const FIELD_ERROR_GROUPS = [
  { keys: ["name", "age", "sex", "height", "weight"], target: "basics" },
  { keys: ["activity_level", "diet_preference", "meals_per_day", "allergies", "intolerances", "cuisine", "disliked", "primary_health_goals"], target: "goals" },
  { keys: ["kidney_disease", "egfr", "potassium", "clinician_sodium", "clinician_protein", "clinician_calorie", "exercise_limitations"], target: "health" },
];

function showProfileErrors(message) {
  document.querySelectorAll(".field-error").forEach((el) => (el.textContent = ""));
  const generalEl = document.getElementById("profile-form-error");
  generalEl.textContent = "";
  const leftovers = [];
  message.split(";").map((s) => s.trim()).filter(Boolean).forEach((fragment) => {
    const group = FIELD_ERROR_GROUPS.find((g) => g.keys.some((k) => fragment.toLowerCase().includes(k)));
    if (group) {
      const el = document.querySelector(`[data-field-error="${group.target}"]`);
      el.textContent = el.textContent ? `${el.textContent}; ${fragment}` : fragment;
    } else {
      leftovers.push(fragment);
    }
  });
  if (leftovers.length) generalEl.textContent = leftovers.join("; ");
}

const profileForm = document.getElementById("profile-form");
if (profileForm) {
  if (sessionStorage.getItem("profileSaved") === "1") {
    sessionStorage.removeItem("profileSaved");
    const banner = document.getElementById("profile-saved-banner");
    if (banner) {
      banner.hidden = false;
      setTimeout(() => (banner.hidden = true), 4000);
    }
  }

  profileForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    document.querySelectorAll(".field-error").forEach((el) => (el.textContent = ""));
    document.getElementById("profile-form-error").textContent = "";
    const fd = new FormData(profileForm);

    let heightCm, weightKg, goalWeightKg;
    if (unitSelect && unitSelect.value === "us") {
      heightCm = ftInToCm(fd.get("height_ft"), fd.get("height_in"));
      weightKg = lbToKg(Number(fd.get("current_weight_lb")) || 0);
      const goalLb = fd.get("goal_weight_lb");
      goalWeightKg = goalLb ? lbToKg(Number(goalLb)) : null;
    } else {
      heightCm = Number(fd.get("height_cm"));
      weightKg = Number(fd.get("current_weight_kg"));
      goalWeightKg = toNullableString(fd.get("goal_weight_kg") || "");
    }

    const body = {
      name: fd.get("name"),
      age: Number(fd.get("age")),
      sex: fd.get("sex"),
      height_cm: heightCm,
      current_weight_kg: weightKg,
      goal_weight_kg: goalWeightKg,
      activity_level: fd.get("activity_level"),
      diet_preference: fd.get("diet_preference"),
      meals_per_day: Number(fd.get("meals_per_day")),
      kidney_disease: fd.get("kidney_disease"),
      wake_time: toNullableString(fd.get("wake_time") || ""),
      bed_time: toNullableString(fd.get("bed_time") || ""),
      egfr: toNullableString(fd.get("egfr") || ""),
      potassium_mmol_l: toNullableString(fd.get("potassium_mmol_l") || ""),
      clinician_sodium_target_mg: toNullableString(fd.get("clinician_sodium_target_mg") || ""),
      clinician_protein_target_g: toNullableString(fd.get("clinician_protein_target_g") || ""),
      clinician_calorie_target: toNullableString(fd.get("clinician_calorie_target") || ""),
      primary_health_goals: toNullableString(fd.get("primary_health_goals") || ""),
      exercise_limitations: toNullableString(fd.get("exercise_limitations") || ""),
      allergies: toListField(fd.get("allergies") || ""),
      intolerances: toListField(fd.get("intolerances") || ""),
      cuisine_preferences: toListField(fd.get("cuisine_preferences") || ""),
      disliked_foods: toListField(fd.get("disliked_foods") || ""),
    };
    const profileId = profileForm.dataset.profileId;
    try {
      if (profileId) {
        await submitJson(`/api/profiles/${profileId}`, "PUT", body);
      } else {
        await submitJson("/api/profiles", "POST", body);
      }
      sessionStorage.setItem("profileSaved", "1");
      window.location.reload();
    } catch (err) {
      showProfileErrors(err.message);
    }
  });
}

const cancelEditBtn = document.getElementById("cancel-edit-btn");
if (cancelEditBtn) {
  cancelEditBtn.addEventListener("click", () => window.location.reload());
}

const medForm = document.getElementById("med-form");
if (medForm) {
  medForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errEl = document.getElementById("med-form-error");
    errEl.textContent = "";
    const fd = new FormData(medForm);
    const body = {
      name: fd.get("name"),
      dose: fd.get("dose"),
      frequency: fd.get("frequency"),
      scheduled_time: fd.get("scheduled_time"),
      notes: fd.get("notes"),
      potassium_risk_manual: fd.get("potassium_risk_manual") ? true : null,
    };
    const profileId = document.getElementById("profile-form").dataset.profileId;
    try {
      await submitJson(`/api/profiles/${profileId}/medications`, "POST", body);
      window.location.reload();
    } catch (err) {
      errEl.textContent = err.message;
    }
  });
}

document.querySelectorAll(".log-taken-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const profileId = document.getElementById("profile-form").dataset.profileId;
    const medId = btn.dataset.medId;
    const taken = btn.dataset.taken === "1";
    await submitJson(`/api/profiles/${profileId}/medications/${medId}/log`, "POST", { taken });
    window.location.reload();
  });
});

document.querySelectorAll(".delete-med-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (!confirm("Delete this medication?")) return;
    const profileId = document.getElementById("profile-form").dataset.profileId;
    const medId = btn.dataset.medId;
    await submitJson(`/api/profiles/${profileId}/medications/${medId}`, "DELETE", {});
    window.location.reload();
  });
});

document.querySelectorAll(".csv-import-form").forEach((form) => {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const profileId = document.getElementById("profile-form").dataset.profileId;
    const kind = form.dataset.kind;
    const resultEl = document.querySelector(`.csv-import-result[data-kind="${kind}"]`);
    const fileInput = form.querySelector('input[type="file"]');
    if (!fileInput.files.length) return;

    const fd = new FormData();
    fd.append("file", fileInput.files[0]);
    resultEl.textContent = "Importing...";
    try {
      const res = await fetch(`/api/profiles/${profileId}/import/${kind}`, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "import failed");
      resultEl.textContent = `Imported ${data.imported}/${data.total_rows} rows.` +
        (data.errors.length ? ` ${data.errors.length} row(s) rejected — see console for details.` : "");
      if (data.errors.length) console.warn("CSV import errors:", data.errors);
    } catch (err) {
      resultEl.textContent = `Error: ${err.message}`;
    }
  });
});
