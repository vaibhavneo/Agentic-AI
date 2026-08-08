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

function numOrUndefined(v) {
  return v === "" || v === null ? undefined : Number(v);
}

const bpForm = document.getElementById("bp-form");
if (bpForm) {
  bpForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(bpForm);
    const resultEl = document.getElementById("bp-result");
    resultEl.innerHTML = "Recording...";
    const symptoms = fd.getAll("symptoms");
    try {
      const reading = await callApi(`/api/profiles/${PROFILE_ID}/vitals/bp`, "POST", {
        systolic_1: Number(fd.get("systolic_1")),
        diastolic_1: Number(fd.get("diastolic_1")),
        pulse_1: numOrUndefined(fd.get("pulse_1")),
        systolic_2: numOrUndefined(fd.get("systolic_2")),
        diastolic_2: numOrUndefined(fd.get("diastolic_2")),
        pulse_2: numOrUndefined(fd.get("pulse_2")),
        symptoms,
        notes: fd.get("notes") || undefined,
      });
      const cls = reading.emergency ? "bp-alert-emergency" : reading.urgency === "urgent" ? "bp-alert-urgent" : reading.urgency === "warning" ? "bp-alert-warning" : "bp-alert-info";
      resultEl.innerHTML = `<div class="${cls}"><strong>${reading.category.toUpperCase()}</strong>: ${reading.message}</div>`;
      setTimeout(() => window.location.reload(), reading.emergency ? 4000 : 1500);
    } catch (err) {
      resultEl.innerHTML = `<p class="error">${err.message}</p>`;
    }
  });
}

const weightForm = document.getElementById("weight-form");
if (weightForm) {
  weightForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(weightForm);
    await callApi(`/api/profiles/${PROFILE_ID}/vitals/weight`, "POST", { weight_kg: Number(fd.get("weight_kg")) });
    window.location.reload();
  });
}

const sleepForm = document.getElementById("sleep-form");
if (sleepForm) {
  sleepForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(sleepForm);
    await callApi(`/api/profiles/${PROFILE_ID}/vitals/sleep`, "POST", {
      hours: Number(fd.get("hours")),
      quality: numOrUndefined(fd.get("quality")),
    });
    window.location.reload();
  });
}
