"use strict";
const byId = id => document.getElementById(id);
const statusBox = byId("status");
const output = byId("output");
const result = byId("result");

function showStatus(message, error=false) {
  statusBox.hidden = false;
  statusBox.textContent = message;
  statusBox.classList.toggle("error", error);
}
function setBusy(busy) {
  byId("analyse").disabled = busy;
  byId("audit").disabled = busy;
}
async function jsonRequest(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({error: "Unexpected server response."}));
  if (!response.ok) throw new Error(data.error || "Request failed.");
  return data;
}
async function follow(sessionId) {
  await new Promise((resolve, reject) => {
    const source = new EventSource("/progress/" + encodeURIComponent(sessionId));
    source.onmessage = event => {
      const data = JSON.parse(event.data);
      if (data.type === "progress") {
        showStatus(data.step + " (" + data.pct + "%)");
      } else if (data.type === "result") {
        source.close();
        if (data.status !== "done") return reject(new Error(data.message || "Analysis failed."));
        const assurance = data.data.assurance || {};
        const basis = assurance.evidence_basis || {};
        byId("assurance").textContent = [
          "Assurance: " + (assurance.assurance_level || "limited"),
          assurance.metric_notice || "This output requires human review.",
          "Evidence: " + (basis.probe_answers || 0) + " probe answers; " +
            (basis.published_sources || 0) + " published sources."
        ].join("\n");
        byId("reviewed").checked = false;
        result.textContent = JSON.stringify(data.data, null, 2);
        output.hidden = false;
        showStatus("Complete.");
        resolve();
      }
    };
    source.onerror = () => { source.close(); reject(new Error("Progress connection was interrupted.")); };
  });
}
async function start(path, payload) {
  setBusy(true); output.hidden = true; showStatus("Starting…");
  try {
    const data = await jsonRequest(path, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });
    await follow(data.session_id);
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    setBusy(false);
  }
}
byId("analyse").addEventListener("click", () => start("/analyse", {
  brief: byId("brief").value,
  mode: byId("mode").value,
  quick: byId("quick").checked
}));
byId("audit").addEventListener("click", () => start("/audit", {
  instrument: byId("instrument").value,
  brief: byId("brief").value,
  mode: byId("mode").value
}));
byId("file").addEventListener("change", async event => {
  const file = event.target.files[0]; if (!file) return;
  const body = new FormData(); body.append("file", file);
  showStatus("Reading document…");
  try {
    const data = await jsonRequest("/extract", {method:"POST", body});
    byId("brief").value = data.text;
    showStatus(data.truncated ? "Document loaded and truncated to the analysis limit." : "Document loaded.");
  } catch (error) { showStatus(error.message, true); }
});
