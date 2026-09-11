"use strict";

const byId = id => document.getElementById(id);
let currentSession = null;
let currentReport = null;
let parsedOverride = null;

function showStatus(message, error=false) {
  const box = byId("status");
  box.hidden = false;
  box.textContent = message;
  box.classList.toggle("error", error);
}
function setBusy(busy) {
  ["parse", "analyse", "audit", "submit-review", "export-docx", "export-pdf"].forEach(id => {
    byId(id).disabled = busy;
  });
}
async function requestJson(url, options={}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({error: "Unexpected server response."}));
  if (!response.ok) throw new Error(data.error || "Request failed.");
  return data;
}
async function parseBrief() {
  setBusy(true);
  try {
    const data = await requestJson("/parse", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({brief: byId("brief").value, mode: byId("mode").value})
    });
    parsedOverride = data.parsed;
    byId("category").value = parsedOverride.category || "";
    byId("audience").value = parsedOverride.target_audience || "";
    byId("geography").value = parsedOverride.geography || "";
    byId("sample").value = parsedOverride.sample_definition || "";
    byId("fieldwork").value = parsedOverride.fieldwork_locations || "";
    byId("hypotheses").value = (parsedOverride.client_hypotheses || []).join("\n");
    byId("hypothesis-review").hidden = false;
    showStatus("Check and correct the extraction before running the review.");
  } catch (error) { showStatus(error.message, true); }
  finally { setBusy(false); }
}
function reviewedParse() {
  if (!parsedOverride) return null;
  return {
    ...parsedOverride,
    category: byId("category").value.trim(),
    target_audience: byId("audience").value.trim(),
    geography: byId("geography").value.trim(),
    sample_definition: byId("sample").value.trim(),
    fieldwork_locations: byId("fieldwork").value.trim(),
    client_hypotheses: byId("hypotheses").value.split("\n").map(x => x.trim()).filter(Boolean),
    research_mode: byId("mode").value
  };
}
async function follow(sessionId) {
  return new Promise((resolve, reject) => {
    const source = new EventSource("/progress/" + encodeURIComponent(sessionId));
    source.onmessage = event => {
      const data = JSON.parse(event.data);
      if (data.type === "progress") showStatus(data.step + " (" + data.pct + "%)");
      if (data.type === "result") {
        source.close();
        if (data.status !== "done") return reject(new Error(data.message || "Analysis failed."));
        resolve(data.data);
      }
    };
    source.onerror = () => { source.close(); reject(new Error("Progress connection was interrupted.")); };
  });
}
async function start(path, payload) {
  setBusy(true);
  byId("output").hidden = true;
  showStatus("Starting…");
  try {
    const data = await requestJson(path, {
      method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload)
    });
    currentSession = data.session_id;
    currentReport = await follow(currentSession);
    renderReport(currentReport);
    showStatus("Analysis complete. Review every material finding before use.");
  } catch (error) { showStatus(error.message, true); }
  finally { setBusy(false); }
}
function renderReport(report) {
  const assurance = report.assurance || {};
  const basis = assurance.evidence_basis || {};
  byId("assurance").textContent = [
    "Assurance: " + String(assurance.assurance_level || "limited").toUpperCase(),
    assurance.metric_notice || "This output requires human review.",
    "Evidence basis: " + (basis.probe_answers || 0) + " probe answers · " +
      (basis.published_sources || 0) + " published sources · prompt " + (basis.prompt_version || "unknown"),
    "Limitations: " + (assurance.limitations || []).join(" ")
  ].join("\n");

  const host = byId("findings");
  host.replaceChildren();
  const findings = report.findings || [];
  if (!findings.length) {
    const p = document.createElement("p"); p.textContent = "No material findings were produced."; host.append(p);
  }
  findings.forEach(finding => {
    const card = document.createElement("article");
    card.className = "finding";
    card.dataset.findingId = finding.id;
    const title = document.createElement("h3"); title.textContent = finding.category.replaceAll("_", " ");
    const statement = document.createElement("p"); statement.textContent = finding.statement;
    const basisText = document.createElement("p"); basisText.className = "hint";
    basisText.textContent = "Basis: " + finding.basis + (finding.indicator === undefined ? "" : " · indicator " + finding.indicator);
    const label = document.createElement("label"); label.textContent = "Decision";
    const select = document.createElement("select"); select.className = "decision";
    ["", "accepted", "rejected", "amended"].forEach(value => {
      const option = document.createElement("option"); option.value = value;
      option.textContent = value ? value[0].toUpperCase() + value.slice(1) : "Choose…"; select.append(option);
    });
    const rationaleLabel = document.createElement("label"); rationaleLabel.textContent = "Rationale";
    const rationale = document.createElement("textarea"); rationale.className = "rationale"; rationale.rows = 3;
    const amendmentLabel = document.createElement("label"); amendmentLabel.textContent = "Amendment (required when amended)";
    const amendment = document.createElement("textarea"); amendment.className = "amendment"; amendment.rows = 3;
    card.append(title, statement, basisText, label, select, rationaleLabel, rationale, amendmentLabel, amendment);
    host.append(card);
  });
  byId("result").textContent = JSON.stringify(report, null, 2);
  byId("review-state").textContent = "Not yet reviewed.";
  byId("output").hidden = false;
}
async function submitReview() {
  if (!currentSession) return;
  const decisions = [...document.querySelectorAll(".finding")].map(card => ({
    finding_id: card.dataset.findingId,
    decision: card.querySelector(".decision").value,
    rationale: card.querySelector(".rationale").value.trim(),
    amendment: card.querySelector(".amendment").value.trim()
  }));
  setBusy(true);
  try {
    const data = await requestJson("/review/" + encodeURIComponent(currentSession), {
      method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({decisions})
    });
    currentReport = data.data;
    byId("result").textContent = JSON.stringify(currentReport, null, 2);
    byId("review-state").textContent = data.review.complete
      ? "Review complete and attributed to the authenticated researcher."
      : "Review saved but incomplete.";
  } catch (error) { showStatus(error.message, true); }
  finally { setBusy(false); }
}
async function exportReport(format) {
  if (!currentReport) return;
  setBusy(true);
  try {
    const response = await fetch("/export", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({kind: currentReport.items ? "audit" : "report", format, data:currentReport})
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({})); throw new Error(data.error || "Export failed.");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a"); link.href = url; link.download = "BRIEF-reviewed." + format; link.click();
    URL.revokeObjectURL(url);
  } catch (error) { showStatus(error.message, true); }
  finally { setBusy(false); }
}
function downloadJson() {
  if (!currentReport) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(currentReport, null, 2)], {type:"application/json"}));
  const link = document.createElement("a"); link.href = url; link.download = "BRIEF-reviewed.json"; link.click();
  URL.revokeObjectURL(url);
}

byId("parse").addEventListener("click", parseBrief);
byId("analyse").addEventListener("click", () => start("/analyse", {
  brief: byId("brief").value, mode: byId("mode").value,
  quick: byId("quick").checked, parsed: reviewedParse()
}));
byId("audit").addEventListener("click", () => start("/audit", {
  instrument: byId("instrument").value, brief: byId("brief").value, mode: byId("mode").value
}));
byId("submit-review").addEventListener("click", submitReview);
byId("export-docx").addEventListener("click", () => exportReport("docx"));
byId("export-pdf").addEventListener("click", () => exportReport("pdf"));
byId("download-json").addEventListener("click", downloadJson);
byId("file").addEventListener("change", async event => {
  const file = event.target.files[0]; if (!file) return;
  const body = new FormData(); body.append("file", file); showStatus("Reading document…");
  try {
    const data = await requestJson("/extract", {method:"POST", body});
    byId("brief").value = data.text;
    showStatus(data.truncated ? "Document loaded and truncated." : "Document loaded.");
  } catch (error) { showStatus(error.message, true); }
});
