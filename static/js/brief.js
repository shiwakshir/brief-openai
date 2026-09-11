/*
 * BRIEF front end.
 *
 * Sections, in order:
 *   1. Theme and startup (light/dark, tool and mode switches)
 *   2. Input: upload, hypothesis review, running an analysis or an audit
 *   3. Rendering the analysis report (one render* function per panel)
 *   4. Rendering the guide audit
 *   5. Export to Markdown
 *
 * All state lives in the module-level variables at the top of each section.
 * There is no build step: this file is served as-is.
 */
try {
  const savedTheme = localStorage.getItem('brief-theme');
  if (savedTheme === 'light' || savedTheme === 'dark') document.documentElement.setAttribute('data-theme', savedTheme);
} catch (e) {}

function applyThemeLabel() {
  const t = document.documentElement.getAttribute('data-theme');
  const b = document.getElementById('theme-toggle');
  if (b) b.textContent = t === 'light' ? 'Dark mode' : 'Light mode';
}
function toggleTheme() {
  const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('brief-theme', next); } catch (e) {}
  applyThemeLabel();
}
document.addEventListener('DOMContentLoaded', applyThemeLabel);

let allData = null;
let currentSessionId = null;
let currentEventSource = null;
const STEP_LABELS = [
  "Reading your brief",
  "Working out how people ask about this",
  "Asking AI the same question 10 ways",
  "Finding patterns in what AI says",
  "Comparing AI to your actual audience",
  "Scoring the client's assumptions",
  "Tracing where assumptions come from",
  "Checking how much is out of date",
  "Identifying which brands AI mentions",
  "Working out how to research this",
  "Scoring overall design confidence",
  "Drafting note, probes and screener"
];

function scoreCls(label) {
  if (!label) return 's-neutral';
  const l = label.toLowerCase();
  if (l.includes('insufficient') || l.includes('unassessed') || l.includes('unknown')) return 's-neutral';
  if (l === 'critical') return 's-critical';
  if (l === 'high')     return 's-high';
  if (l === 'medium')   return 's-medium';
  return 's-low';
}

function infCls(level) {
  if (!level) return 'inf-marginal';
  const l = level.toLowerCase();
  if (l === 'dominant')    return 'inf-dominant';
  if (l === 'significant') return 'inf-significant';
  if (l === 'marginal')    return 'inf-marginal';
  return 'inf-absent';
}

function safeUrl(value) {
  try {
    const raw = String(value || '').trim();
    if (!/^https?:\/\//i.test(raw)) return '';
    const url = new URL(raw);
    return (url.protocol === 'http:' || url.protocol === 'https:') ? url.href : '';
  } catch (e) {
    return '';
  }
}

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function showPanel(name, el) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const panel = document.getElementById('panel-' + name);
  if (!panel) return;
  panel.classList.add('active');
  if (el) el.classList.add('active');
}

function newAnalysis() {
  if (currentEventSource) currentEventSource.close();
  currentEventSource = null;
  currentSessionId = null;
  allData = null;
  auditData = null;
  document.getElementById('results-view').style.display = 'none';
  document.getElementById('audit-view').style.display = 'none';
  document.getElementById('audit-btn').disabled = false;
  document.getElementById('landing').style.display = 'block';
  document.getElementById('brief-input').value = '';
  document.getElementById('run-btn').disabled = false;
  document.getElementById('confirm-btn').disabled = false;
  document.getElementById('review-section').style.display = 'none';
  reviewedParsed = null;
  document.getElementById('progress-section').style.display = 'none';
  document.getElementById('steps-grid').innerHTML = '';
  document.getElementById('progress-fill').style.width = '0%';
}

let researchMode = 'market';
let reviewedParsed = null;
document.addEventListener('DOMContentLoaded', () => setMode('market'));

let currentTool = 'brief';
let auditData = null;

function setMode(m) {
  researchMode = m;
  ['mode-market', 'gmode-market'].forEach(id => {
    document.getElementById(id).classList.toggle('active', m === 'market');
    document.getElementById(id).setAttribute('aria-pressed', String(m === 'market'));
  });
  ['mode-ux', 'gmode-ux'].forEach(id => {
    document.getElementById(id).classList.toggle('active', m === 'ux');
    document.getElementById(id).setAttribute('aria-pressed', String(m === 'ux'));
  });
  document.getElementById('rv-product-wrap').style.display = m === 'ux' ? 'block' : 'none';
}

function clearInputs(which) {
  if (which === 'brief') {
    document.getElementById('brief-input').value = '';
    document.getElementById('review-section').style.display = 'none';
    document.getElementById('rv-hypotheses').innerHTML = '';
    reviewedParsed = null;
    document.getElementById('input-hint').textContent = '12 reasoning steps · 5-7 minutes';
    document.getElementById('brief-input').focus();
  } else {
    document.getElementById('guide-input').value = '';
    document.getElementById('guide-brief-input').value = '';
    document.getElementById('guide-hint').textContent = '4 steps · about 1-2 minutes';
    document.getElementById('guide-input').focus();
  }
  hideError();
}

function setTool(t) {
  currentTool = t;
  document.getElementById('tool-brief').classList.toggle('active', t === 'brief');
  document.getElementById('tool-guide').classList.toggle('active', t === 'guide');
  document.getElementById('tool-brief').setAttribute('aria-selected', String(t === 'brief'));
  document.getElementById('tool-guide').setAttribute('aria-selected', String(t === 'guide'));
  document.getElementById('brief-section').style.display = t === 'brief' ? 'block' : 'none';
  document.getElementById('guide-section').style.display = t === 'guide' ? 'block' : 'none';
  document.getElementById('review-section').style.display = 'none';
  hideError();
}

function showAuditPanel(name, el) {
  document.querySelectorAll('#audit-view .panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('#audit-view .nav-item').forEach(n => n.classList.remove('active'));
  const panel = document.getElementById('panel-' + name);
  if (!panel) return;
  panel.classList.add('active');
  if (el) el.classList.add('active');
}

async function uploadFile(input, targetId) {
  const file = input.files && input.files[0];
  if (!file) return;
  hideError();
  targetId = targetId || 'brief-input';
  const hint = document.getElementById(targetId === 'guide-input' ? 'guide-hint' : 'input-hint');
  hint.textContent = 'Reading ' + file.name + '...';
  const form = new FormData();
  form.append('file', file);
  try {
    const resp = await fetch('/extract', { method: 'POST', body: form });
    const data = await resp.json();
    if (data.error) { showError(data.error); hint.textContent = targetId === 'guide-input' ? '4 steps · about 1-2 minutes' : '12 reasoning steps · 4-6 minutes'; return; }
    document.getElementById(targetId).value = data.text;
    hint.textContent = (data.truncated ? 'Loaded the first ' + data.text.length + ' of ' + data.chars + ' characters from ' : 'Loaded ') + file.name + '.';
  } catch (e) {
    showError('Upload failed: ' + e.message);
  }
  input.value = '';
}

function addHypothesis(text) {
  const wrap = document.getElementById('rv-hypotheses');
  const row = document.createElement('div');
  row.className = 'hyp-row';
  row.innerHTML = `<input class="review-input" value="${esc(text)}" placeholder="A belief the client holds, in their words"><button type="button" class="hyp-del" title="Remove" data-action="remove-hypothesis">x</button>`;
  wrap.appendChild(row);
}

async function reviewBrief() {
  const brief = document.getElementById('brief-input').value.trim();
  if (!brief || brief.length < 50) {
    showError('Please paste a research brief of at least 50 characters.');
    return;
  }
  hideError();
  const btn = document.getElementById('run-btn');
  btn.disabled = true; btn.textContent = 'Reading the brief...';
  try {
    const resp = await fetch('/parse', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ brief, mode: researchMode }) });
    const data = await resp.json();
    if (data.error) { showError(data.error); return; }
    const p = data.parsed || {};
    document.getElementById('rv-category').value = p.category || '';
    document.getElementById('rv-topic').value = p.topic || p.product_or_service || p.category || '';
    document.getElementById('rv-audience').value = p.target_audience || '';
    document.getElementById('rv-geography').value = p.geography || '';
    document.getElementById('rv-product').value = p.product_or_service || '';
    document.getElementById('rv-sample').value = p.sample_definition || '';
    document.getElementById('rv-fieldwork').value = p.fieldwork_locations || '';
    document.getElementById('rv-hypotheses').innerHTML = '';
    (p.client_hypotheses || []).forEach(h => addHypothesis(h));
    if (!(p.client_hypotheses || []).length) addHypothesis('');
    reviewedParsed = p;
    document.getElementById('review-section').style.display = 'block';
    document.getElementById('review-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    showError('Could not read the brief: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Review hypotheses \u00a0\u25b6';
  }
}

function collectParsed() {
  const p = Object.assign({}, reviewedParsed || {});
  p.category = document.getElementById('rv-category').value.trim() || p.category;
  p.topic = document.getElementById('rv-topic').value.trim() || p.product_or_service || p.category;
  p.target_audience = document.getElementById('rv-audience').value.trim() || p.target_audience;
  p.geography = document.getElementById('rv-geography').value.trim() || p.geography;
  p.product_or_service = document.getElementById('rv-product').value.trim();
  p.sample_definition = document.getElementById('rv-sample').value.trim() || 'Not specified';
  p.fieldwork_locations = document.getElementById('rv-fieldwork').value.trim() || 'Not specified';
  p.client_hypotheses = Array.from(document.querySelectorAll('#rv-hypotheses .review-input')).map(i => i.value.trim()).filter(Boolean);
  p.research_mode = researchMode;
  return p;
}

async function runAnalysis() {
  const brief = document.getElementById('brief-input').value.trim();
  if (!brief || brief.length < 50) {
    showError('Please paste a research brief of at least 50 characters.');
    return;
  }
  hideError();
  const parsed = reviewedParsed ? collectParsed() : null;
  const quick = document.getElementById('quick-mode').checked;
  document.getElementById('run-btn').disabled = true;
  document.getElementById('confirm-btn').disabled = true;
  document.getElementById('review-section').style.display = 'none';
  document.getElementById('progress-section').style.display = 'block';

  // Pre-populate step grid
  const grid = document.getElementById('steps-grid');
  grid.innerHTML = '';
  STEP_LABELS.forEach((label, i) => {
    const cell = document.createElement('div');
    cell.className = 'step-cell';
    cell.id = 'step-cell-' + (i+1);
    cell.innerHTML = `<div class="step-num">${String(i+1).padStart(2,'0')}</div>${label}`;
    grid.appendChild(cell);
  });

  let resp;
  try {
    resp = await fetch('/analyse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ brief, mode: researchMode, parsed, quick })
    });
  } catch (e) {
    showError('Could not start the analysis: ' + e.message);
    return;
  }
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok || payload.error) { showError(payload.error || 'Could not start the analysis.'); return; }

  currentSessionId = payload.session_id;
  const es = new EventSource('/progress/' + currentSessionId);
  currentEventSource = es;

  es.onmessage = (e) => {
    const msg = JSON.parse(e.data);

    if (msg.type === 'progress') {
      document.getElementById('progress-status').textContent = msg.step + '...';
      document.getElementById('progress-pct').textContent = msg.pct + '%';
      document.getElementById('progress-fill').style.width = msg.pct + '%';

      // Mark current active, prev done
      const cur = document.getElementById('step-cell-' + msg.number);
      if (cur) { cur.classList.add('active'); cur.classList.remove('done'); }
      if (msg.number > 1) {
        const prev = document.getElementById('step-cell-' + (msg.number - 1));
        if (prev) { prev.classList.remove('active'); prev.classList.add('done'); }
      }
    }

    if (msg.type === 'result') {
      es.close();
      currentEventSource = null;
      document.getElementById('progress-fill').style.width = '100%';
      document.getElementById('progress-status').textContent = 'Done. Here\'s what BRIEF found.';
      document.getElementById('progress-pct').textContent = '100%';
      document.querySelectorAll('.step-cell').forEach(c => { c.classList.remove('active'); c.classList.add('done'); });

      if (msg.status !== 'done') {
        showError(msg.status === 'cancelled' ? 'Analysis cancelled.' : 'Analysis failed: ' + msg.message);
        document.getElementById('run-btn').disabled = false;
        document.getElementById('confirm-btn').disabled = false;
        return;
      }

      allData = msg.data;
      renderAll(allData);
      document.getElementById('landing').style.display = 'none';
      document.getElementById('results-view').style.display = 'block';
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };
  es.onerror = () => {
    es.close(); currentEventSource = null;
    showError('The live progress connection was interrupted. Start the analysis again.');
    document.getElementById('confirm-btn').disabled = false;
  };
}

async function runAudit() {
  const instrument = document.getElementById('guide-input').value.trim();
  const brief = document.getElementById('guide-brief-input').value.trim();
  if (instrument.length < 80) { showError('Paste a guide or questionnaire with at least a few questions.'); return; }
  hideError();
  document.getElementById('audit-btn').disabled = true;
  document.getElementById('progress-section').style.display = 'block';
  const grid = document.getElementById('steps-grid');
  grid.innerHTML = '';
  ['Reading the guide', 'Reading the brief', 'Auditing every question', 'Checking coverage'].forEach((label, i) => {
    const cell = document.createElement('div');
    cell.className = 'step-cell'; cell.id = 'step-cell-' + (i + 1);
    cell.innerHTML = `<div class="step-num">${String(i + 1).padStart(2, '0')}</div>${label}`;
    grid.appendChild(cell);
  });
  let resp;
  try {
    resp = await fetch('/audit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ instrument, brief, mode: researchMode }) });
  } catch (e) {
    showError('Could not start the audit: ' + e.message);
    document.getElementById('audit-btn').disabled = false;
    return;
  }
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok || payload.error) { showError(payload.error || 'Could not start the audit.'); document.getElementById('audit-btn').disabled = false; return; }
  currentSessionId = payload.session_id;
  const es = new EventSource('/progress/' + currentSessionId);
  currentEventSource = es;
  es.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'progress') {
      document.getElementById('progress-status').textContent = msg.step + '...';
      document.getElementById('progress-pct').textContent = msg.pct + '%';
      document.getElementById('progress-fill').style.width = msg.pct + '%';
      const cur = document.getElementById('step-cell-' + msg.number);
      if (cur) cur.classList.add('active');
      const prev = document.getElementById('step-cell-' + (msg.number - 1));
      if (prev) { prev.classList.remove('active'); prev.classList.add('done'); }
    }
    if (msg.type === 'result') {
      es.close();
      currentEventSource = null;
      document.querySelectorAll('.step-cell').forEach(c => { c.classList.remove('active'); c.classList.add('done'); });
      if (msg.status !== 'done') { showError(msg.status === 'cancelled' ? 'Audit cancelled.' : 'Audit failed: ' + msg.message); document.getElementById('audit-btn').disabled = false; return; }
      auditData = msg.data;
      renderAudit(auditData);
      document.getElementById('landing').style.display = 'none';
      document.getElementById('audit-view').style.display = 'block';
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };
  es.onerror = () => {
    es.close(); currentEventSource = null;
    showError('The live progress connection was interrupted. Start the audit again.');
    document.getElementById('audit-btn').disabled = false;
  };
}

async function cancelRun() {
  if (!currentSessionId) return;
  const button = document.getElementById('cancel-btn');
  button.disabled = true;
  try {
    const resp = await fetch('/cancel/' + encodeURIComponent(currentSessionId), { method: 'POST' });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) showError(payload.error || 'Cancellation could not be requested.');
    else document.getElementById('progress-status').textContent = 'Cancelling...';
  } catch (e) {
    showError('Cancellation could not be requested: ' + e.message);
  } finally {
    button.disabled = false;
  }
}

const SEV_CLS = { high: 's-high', medium: 's-medium', low: 's-low' };

function renderAudit(a) {
  const sm = a.summary || {};
  const color = sm.score >= 80 ? 'var(--ok)' : sm.score >= 60 ? 'var(--amber)' : 'var(--danger)';
  const circumference = 2 * Math.PI * 56;
  const flaggedItems = (a.items || []).filter(i => (i.issues || []).length);
  const worst = flaggedItems.filter(i => i.issues.some(x => x.severity === 'high')).slice(0, 3);
  document.getElementById('panel-asummary-content').innerHTML = `
    <div class="section-title">
      <div class="section-eyebrow">Instrument audit</div>
      <h2>Will this ${esc(a.instrument_type || 'instrument')} test the client's beliefs, or confirm them?</h2>
    </div>
    ${renderInternalRecommendation(a.internal_recommendation)}
    ${renderAssurance(a.assurance, a.human_review)}
    <div class="confidence-hero">
      <div class="gauge">
        <svg width="132" height="132" viewBox="0 0 132 132">
          <circle class="gauge-track" cx="66" cy="66" r="56"></circle>
          <circle class="gauge-fill" cx="66" cy="66" r="56" stroke="${color}" stroke-dasharray="${circumference}" stroke-dashoffset="${circumference * (1 - (sm.score || 0) / 100)}"></circle>
        </svg>
        <div class="gauge-center"><div class="gauge-num" style="color:${color}">${sm.score}</div><div class="gauge-unit">/ 100</div></div>
      </div>
      <div class="confidence-detail">
        <span class="confidence-label-tag" style="background:var(--surface2);color:${color}">${esc(sm.label || '')}</span>
        <div class="confidence-headline">${sm.items_flagged} of ${sm.items_total} items flagged. ${sm.high} high, ${sm.medium} medium, ${sm.low} low. ${sm.items_confirming} item${sm.items_confirming === 1 ? '' : 's'} restate a client hypothesis and ask for agreement.</div>
        <div class="confidence-rationale">Score starts at 100 and loses 12 per high, 5 per medium and 1 per low issue, scaled for short instruments. It measures wording, not whether the study is well designed.</div>
      </div>
    </div>
    ${worst.length ? `<div class="card card-mb-4"><div class="card-label">Fix these first</div>${worst.map(i => `<div class="risk-item"><span class="risk-num">${esc(i.id)}</span><span class="risk-text">${esc(i.text)}<br><span class="assumption-quote">${esc(i.issues[0].explanation)}</span></span></div>`).join('')}</div>` : ''}
    ${(sm.untested_hypotheses || []).length || (sm.confirmed_only_hypotheses || []).length ? `<div class="card">
      ${(sm.untested_hypotheses || []).length ? `<div class="card-label">Client hypotheses this instrument never tests</div><div class="tag-row">${sm.untested_hypotheses.map(h => `<span class="tag absent">${esc(h)}</span>`).join('')}</div>` : ''}
      ${(sm.confirmed_only_hypotheses || []).length ? `<div class="card-label" style="margin-top:var(--sp-3)">Hypotheses it can only confirm</div><div class="tag-row">${sm.confirmed_only_hypotheses.map(h => `<span class="tag">${esc(h)}</span>`).join('')}</div>` : ''}
    </div>` : ''}`;

  const itemHtml = (a.items || []).map(i => `
    <div class="audit-item ${i.issues.length ? '' : 'clean'}" data-sev="${i.issues.length ? (i.issues.some(x => x.severity === 'high') ? 'high' : i.issues.some(x => x.severity === 'medium') ? 'medium' : 'low') : 'none'}">
      <div class="audit-q"><span class="audit-id">${esc(i.id)}</span>${esc(i.text)}${i.tests_or_confirms === 'confirms' ? ' <span class="badge-score s-high">confirms</span>' : ''}</div>
      ${i.issues.map(x => `<div class="audit-issue"><span class="badge-score ${SEV_CLS[x.severity] || ''}">${esc(x.severity)} · ${esc(String(x.type).replace(/_/g, ' '))}</span><span>${esc(x.explanation)}</span></div>`).join('')}
      ${i.rewrite ? `<div class="audit-rewrite"><div class="review-key">Neutral version</div>${esc(i.rewrite)}</div>` : ''}
    </div>`).join('');
  document.getElementById('panel-aitems-content').innerHTML = `
    <div class="audit-filter">
      <button class="tool-tab active" data-action="filter-audit" data-filter="all">All ${a.items.length}</button>
      <button class="tool-tab" data-action="filter-audit" data-filter="flagged">Flagged ${flaggedItems.length}</button>
      <button class="tool-tab" data-action="filter-audit" data-filter="high">High only ${sm.high}</button>
    </div>${itemHtml}`;

  const cov = a.coverage || {};
  const covCls = c => c === 'tested' ? 's-low' : c === 'confirmed_only' ? 's-medium' : 's-high';
  document.getElementById('panel-acoverage-content').innerHTML = (cov.hypotheses || []).length ? `
    ${cov.hypotheses.map(h => `<div class="hyp-item"><div class="hyp-top"><div class="hyp-text">${esc(h.hypothesis)}</div><span class="badge-score ${covCls(h.coverage)}">${esc(String(h.coverage).replace('_', ' '))}</span></div><div class="assumption-freq">${(h.item_ids || []).map(esc).join(', ') || 'no items'}</div><div class="hyp-explanation">${esc(h.note)}</div></div>`).join('')}
    ${(cov.missing_questions || []).length ? `<div class="card-label mb-3" style="margin-top:var(--sp-5)">Questions to add</div>${cov.missing_questions.map(q => `<div class="method-item"><div class="method-rec">${esc(q.question)}</div><div class="method-rationale">Serves: ${esc(q.serves)} · Place after: ${esc(q.place_after)}</div></div>`).join('')}` : ''}`
    : `<div class="card"><p>${esc(cov.note || 'Paste the brief alongside the guide to check coverage of the client hypotheses.')}</p></div>`;

  const clean = (a.items || []).map(i => (i.section ? '' : '') + i.id + '. ' + (i.rewrite || i.text)).join('\n\n');
  document.getElementById('panel-arewrite-content').innerHTML = `
    <div class="card"><button class="btn-copy" id="clean-copy-btn" data-action="copy" data-copy-target="clean-copy">Copy</button><div class="card-label">Clean copy</div><div class="deliv-text" id="clean-copy">${esc(clean)}</div></div>`;
  renderReview(a, 'panel-areview-content', 'audit');
}

function filterAudit(which, el) {
  document.querySelectorAll('#panel-aitems-content .tool-tab').forEach(b => b.classList.remove('active'));
  if (el) el.classList.add('active');
  document.querySelectorAll('#panel-aitems-content .audit-item').forEach(it => {
    const sev = it.getAttribute('data-sev');
    it.style.display = which === 'all' ? '' : which === 'flagged' ? (sev === 'none' ? 'none' : '') : (sev === 'high' ? '' : 'none');
  });
}

function buildAuditMarkdown() {
  const a = auditData; if (!a) return '';
  const sm = a.summary || {};
  let md = '# BRIEF - Guide and questionnaire audit\n\n';
  if (a.internal_recommendation) {
    md += '## Internal workflow recommendation: ' + a.internal_recommendation.label + '\n\n';
    md += a.internal_recommendation.recommended_action + '\n\n';
    (a.internal_recommendation.reasons || []).forEach(reason => { md += '- ' + reason + '\n'; });
    md += '\n_' + a.internal_recommendation.notice + '_\n\n';
  }
  md += '## Score: ' + sm.score + '/100 (' + sm.label + ')\n\n' + sm.items_flagged + ' of ' + sm.items_total + ' items flagged: ' + sm.high + ' high, ' + sm.medium + ' medium, ' + sm.low + ' low. ' + sm.items_confirming + ' items restate a client hypothesis.\n\n';
  md += '## Question by question\n\n';
  (a.items || []).forEach(i => {
    md += '**' + i.id + '.** ' + i.text + '\n';
    (i.issues || []).forEach(x => { md += '- ' + x.severity.toUpperCase() + ' ' + String(x.type).replace(/_/g, ' ') + ': ' + x.explanation + '\n'; });
    if (i.rewrite) md += '- Neutral version: ' + i.rewrite + '\n';
    md += '\n';
  });
  const cov = a.coverage || {};
  if ((cov.hypotheses || []).length) {
    md += '## Hypothesis coverage\n\n';
    cov.hypotheses.forEach(h => { md += '- **' + h.hypothesis + '**: ' + String(h.coverage).replace('_', ' ') + ' (' + (h.item_ids || []).join(', ') + '). ' + (h.note || '') + '\n'; });
    md += '\n';
    if ((cov.missing_questions || []).length) { md += '### Questions to add\n\n'; cov.missing_questions.forEach(q => { md += '- ' + q.question + ' (serves: ' + q.serves + '; place after ' + q.place_after + ')\n'; }); md += '\n'; }
  }
  md += '## Clean copy\n\n' + (a.items || []).map(i => i.id + '. ' + (i.rewrite || i.text)).join('\n\n') + '\n';
  return md;
}

function renderAll(d) {
  renderSummary(d);
  renderBrief(d.parsed);
  renderAssumptions(d.clusters);
  renderGaps(d.gaps);
  renderContamination(d.contamination);
  renderDrift(d.temporal_drift);
  renderCompetitors(d.competitor_intel);
  renderArchaeology(d.archaeology);
  renderMethodology(d.methodology);
  renderEvidence(d.query_data, d.prompts);
  renderDeliverables(d.deliverables);
  renderReview(d, 'panel-review-content', 'report');
}

function renderReview(data, targetId, kind) {
  const target = document.getElementById(targetId);
  if (!target) return;
  const findings = data.findings || [];
  const existing = new Map((((data.human_review || {}).decisions) || []).map(item => [String(item.finding_id), item]));
  const requirements = ((data.assurance || {}).required_reviewer_decisions || []).map(item => `<li>${esc(item)}</li>`).join('');
  const cards = findings.map(item => {
    const decision = existing.get(String(item.id)) || {};
    return `<div class="card review-finding" data-finding-id="${esc(item.id)}">
      <div class="badge-row"><div class="card-label no-margin">${esc(String(item.category || 'finding').replace(/_/g, ' '))}</div><span class="assumption-freq">${esc(item.id)}</span></div>
      <p class="rec-heading">${esc(item.statement)}</p>
      ${item.explanation ? `<div class="assumption-quote">${esc(item.explanation)}</div>` : ''}
      ${item.indicator != null ? `<div class="assumption-freq">Indicator: ${esc(item.indicator)}</div>` : ''}
      <div class="review-grid review-decision-grid">
        <label><span class="review-key">Decision</span><select class="review-input review-decision">
          <option value="">Choose…</option>
          ${['accepted', 'rejected', 'amended'].map(value => `<option value="${value}"${decision.decision === value ? ' selected' : ''}>${value[0].toUpperCase() + value.slice(1)}</option>`).join('')}
        </select></label>
        <label><span class="review-key">Reason (at least 10 characters)</span><textarea class="review-input review-rationale" rows="2">${esc(decision.rationale || '')}</textarea></label>
      </div>
      <label><span class="review-key">Amended wording (required when amended)</span><textarea class="review-input review-amendment" rows="2">${esc(decision.amendment || '')}</textarea></label>
    </div>`;
  }).join('');
  const completed = data.human_review && data.human_review.complete;
  target.innerHTML = `
    ${renderAssurance(data.assurance, data.human_review)}
    ${requirements ? `<div class="card"><div class="card-label">Reviewer checks</div><ul class="deliv-text">${requirements}</ul></div>` : ''}
    ${cards || '<div class="card"><p>No material findings require a recorded decision on this run.</p></div>'}
    ${findings.length ? `<div class="review-submit"><div class="assumption-freq review-message">${completed ? 'All findings have a recorded decision.' : `${findings.length} finding(s) require a decision.`}</div><button class="btn-run" data-action="submit-review" data-kind="${kind}">${completed ? 'Update sign-off' : 'Save reviewer sign-off'}</button></div>` : ''}`;
}

async function submitReview(kind) {
  if (!currentSessionId) { showError('This result no longer has an active review session. Run it again to record sign-off.'); return; }
  const targetId = kind === 'audit' ? 'panel-areview-content' : 'panel-review-content';
  const target = document.getElementById(targetId);
  const decisions = Array.from(target.querySelectorAll('.review-finding')).map(card => ({
    finding_id: card.dataset.findingId,
    decision: card.querySelector('.review-decision').value,
    rationale: card.querySelector('.review-rationale').value.trim(),
    amendment: card.querySelector('.review-amendment').value.trim()
  }));
  const invalid = decisions.find(item => !item.decision || item.rationale.length < 10 || (item.decision === 'amended' && !item.amendment));
  const message = target.querySelector('.review-message');
  if (invalid) { message.textContent = 'Complete every decision, give a meaningful reason, and add wording for amended findings.'; return; }
  const button = target.querySelector('[data-action="submit-review"]');
  button.disabled = true; button.textContent = 'Saving…';
  try {
    const resp = await fetch('/review/' + encodeURIComponent(currentSessionId), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decisions })
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) { message.textContent = payload.error || 'The review could not be saved.'; return; }
    if (kind === 'audit') { auditData = payload.data; renderAudit(auditData); }
    else { allData = payload.data; renderAll(allData); }
  } catch (e) {
    message.textContent = 'The review could not be saved: ' + e.message;
  } finally {
    if (button.isConnected) { button.disabled = false; button.textContent = 'Save reviewer sign-off'; }
  }
}

function copyText(id) {
  const el = document.getElementById(id);
  if (!el) return;
  navigator.clipboard.writeText(el.innerText).then(() => {
    const b = document.getElementById(id + '-btn');
    if (b) { const t = b.textContent; b.textContent = 'Copied'; setTimeout(() => b.textContent = t, 1500); }
  });
}

function renderDeliverables(dl) {
  dl = dl || {};
  const note = dl.challenge_note || {};
  const noteText = [note.opening, note.what_we_found, note.what_we_recommend, note.closing].filter(Boolean).join('\n\n');
  const probes = (dl.discussion_guide_probes || []).map((g, i) => `
    <div class="method-item">
      <div class="method-dim">Tests: ${esc(g.hypothesis)}</div>
      <div class="method-rec">Warm-up: ${esc(g.warm_up)}</div>
      <ul class="deliv-text">${(g.probes || []).map(pr => `<li>${esc(pr)}</li>`).join('')}</ul>
      ${g.avoid ? `<div class="method-risk">Do not ask: ${esc(String(g.avoid).replace(/^(do not ask|don't ask|avoid( asking)?)[:\s]*/i, ''))}</div>` : ''}
    </div>`).join('');
  const probesPlain = (dl.discussion_guide_probes || []).map(g => 'Tests: ' + g.hypothesis + '\nWarm-up: ' + g.warm_up + '\n' + (g.probes || []).map(p => '- ' + p).join('\n') + (g.avoid ? '\nDo not ask: ' + g.avoid : '')).join('\n\n');
  const screener = (dl.screener_criteria || []).map(c => `
    <div class="method-item">
      <div class="method-dim">${esc(c.criterion)}</div>
      <div class="method-rationale">${esc(c.why)}</div>
      ${c.quota_note ? `<div class="method-rec">${esc(c.quota_note)}</div>` : ''}
    </div>`).join('');
  const screenerPlain = (dl.screener_criteria || []).map(c => '- ' + c.criterion + (c.quota_note ? ' (' + c.quota_note + ')' : '') + '\n  Why: ' + c.why).join('\n');
  const tasks = (dl.task_scenarios || []).filter(t => t.task).map(t => `
    <div class="method-item">
      <div class="method-dim">${esc(t.task)}</div>
      <div class="method-rec">Success: ${esc(t.success_measure)}</div>
      <div class="method-rationale">Tests: ${esc(t.hypothesis_tested)}</div>
    </div>`).join('');

  document.getElementById('panel-deliverables-content').innerHTML = `
    <div class="card card-mb-4">
      <button class="btn-copy" id="deliv-note-btn" data-action="copy" data-copy-target="deliv-note">Copy</button>
      <div class="card-label">Challenge note for the client${note.title ? ': ' + esc(note.title) : ''}</div>
      <div class="deliv-text" id="deliv-note">${esc(noteText) || 'Not generated on this run.'}</div>
    </div>
    <div class="card card-mb-4">
      <button class="btn-copy" id="deliv-probes-btn" data-action="copy" data-copy-target="deliv-probes">Copy</button>
      <div class="card-label">Discussion guide probes</div>
      <div id="deliv-probes" style="display:none">${esc(probesPlain)}</div>
      ${probes || '<p>Not generated on this run.</p>'}
    </div>
    ${tasks ? `<div class="card card-mb-4"><div class="card-label">Usability task scenarios</div>${tasks}</div>` : ''}
    <div class="card">
      <button class="btn-copy" id="deliv-screener-btn" data-action="copy" data-copy-target="deliv-screener">Copy</button>
      <div class="card-label">Screener criteria</div>
      <div id="deliv-screener" style="display:none">${esc(screenerPlain)}</div>
      ${screener || '<p>Not generated on this run.</p>'}
    </div>`;
}

function renderEvidence(q, prompts) {
  q = q || {};
  const base = (q.base_responses || []).map((r, i) => `
    <details class="evidence-item">
      <summary><span class="evidence-tag">Q${i + 1} ${esc(r.model || '')}</span>${esc(r.prompt)}</summary>
      <div class="evidence-body">${esc(r.response)}</div>
    </details>`).join('');
  const personas = (q.persona_responses || []).map((r, i) => `
    <details class="evidence-item">
      <summary><span class="evidence-tag">P${i + 1} ${esc(r.persona)} · ${esc(r.model || '')}</span>${esc(r.prompt)}</summary>
      <div class="evidence-body">${esc(r.response)}</div>
    </details>`).join('');
  const empty = !base && !personas ? '<div class="card"><p>No AI answers were captured on this run.</p></div>' : '';
  document.getElementById('panel-evidence-content').innerHTML = `
    ${empty}
    ${base ? `<div class="card-label mb-3">Consumer-style questions</div>${base}` : ''}
    ${personas ? `<div class="card-label mb-3" style="margin-top:var(--sp-5)">Persona variants</div>${personas}` : ''}`;
}

function renderBrief(p) {
  p = p || {};
  const hyps = (p.client_hypotheses || []).map(h => `<span class="tag">${esc(h)}</span>`).join('');
  document.getElementById('panel-brief-content').innerHTML = `
    <div class="meta-row">
      <div class="meta-pill"><span class="meta-key">Category</span><span class="meta-val">${esc(p.category)}</span></div>
      ${p.topic ? `<div class="meta-pill"><span class="meta-key">Topic</span><span class="meta-val">${esc(p.topic)}</span></div>` : ''}
      <div class="meta-pill"><span class="meta-key">Geography</span><span class="meta-val">${esc(p.geography)}</span></div>
      <div class="meta-pill"><span class="meta-key">Method</span><span class="meta-val">${esc(p.methodology_hints)}</span></div>
      <div class="meta-pill"><span class="meta-key">Mode</span><span class="meta-val">${p.research_mode === 'ux' ? 'UX research' : 'Market research'}</span></div>
      ${p.sample_definition && p.sample_definition !== 'Not specified' ? `<div class="meta-pill"><span class="meta-key">Recruits</span><span class="meta-val">${esc(p.sample_definition)}</span></div>` : ''}
      ${p.fieldwork_locations && p.fieldwork_locations !== 'Not specified' ? `<div class="meta-pill"><span class="meta-key">Fieldwork</span><span class="meta-val">${esc(p.fieldwork_locations)}</span></div>` : ''}
      ${p.product_or_service ? `<div class="meta-pill"><span class="meta-key">Product</span><span class="meta-val">${esc(p.product_or_service)}</span></div>` : ''}
    </div>
    <div class="card">
      <div class="card-label">Core question</div>
      <p>${esc(p.core_question)}</p>
      <div class="card-divider"></div>
      <div class="card-label">Target audience</div>
      <p>${esc(p.target_audience)}</p>
      <div class="card-divider"></div>
      <div class="card-label">Research objective</div>
      <p>${esc(p.research_objective)}</p>
      ${hyps ? `<div class="card-divider"></div><div class="card-label">Client hypotheses</div><div class="tag-row">${hyps}</div>` : ''}
    </div>`;
}

function renderAssumptions(c) {
  const list = (c.dominant_assumptions || []).map(a => `
    <div class="assumption-item">
      <div class="assumption-theme">${esc(a.theme)}</div>
      <div class="assumption-freq">${esc(a.frequency)}</div>
      <div class="assumption-desc">${esc(a.description)}</div>
      ${a.example_quote ? `<div class="assumption-quote">"${esc(a.example_quote)}"</div>` : ''}
    </div>`).join('');

  document.getElementById('panel-assumptions-content').innerHTML = `
    <div class="grid-2">
      <div class="card">
        <div class="card-label">Dominant perspective</div>
        <p>${esc(c.dominant_perspective)}</p>
        <div class="card-divider"></div>
        <div class="card-label">Geographic bias</div>
        <p>${esc(c.geographic_bias)}</p>
      </div>
      <div class="card">
        <div class="card-label">Assumed reader</div>
        <p>${esc(c.language_register)}</p>
        <div class="card-divider"></div>
        <div class="card-label">Persona divergence</div>
        <p>${esc(c.persona_divergence)}</p>
      </div>
    </div>
    ${list}`;
}

function renderGaps(g) {
  const over = (g.overrepresented || []).map(o => `
    <div class="gap-item">
      <div class="gap-perspective" class="text-amber">${esc(o.perspective)}</div>
      <div class="gap-explanation">${esc(o.explanation)}</div>
    </div>`).join('');

  const under = (g.underrepresented || []).map(o => `
    <div class="gap-item">
      <div class="gap-perspective" class="text-danger">${esc(o.perspective)}</div>
      <div class="gap-explanation">${esc(o.explanation)}</div>
    </div>`).join('');

  const unknowns = (g.unknown_unknowns || []).map(q => `
    <div class="unknown-item">
      <span class="unknown-q">?</span>
      <span class="unknown-text">${esc(q)}</span>
    </div>`).join('');

  document.getElementById('panel-gaps-content').innerHTML = `
    <div class="grid-2">
      <div>
        <div class="card-label mb-3">Over-represented by AI</div>
        ${over}
      </div>
      <div>
        <div class="card-label mb-3">Under-represented by AI</div>
        ${under}
      </div>
    </div>
    <div class="card">
      <div class="card-label">Audience mismatch</div>
      <p>${esc(g.audience_mismatch)}</p>
      <div class="card-divider"></div>
      <div class="card-label">Risk to research</div>
      <p>${esc(g.risk_to_research)}</p>
    </div>
    <div class="card-label mb-3">Questions nobody is asking</div>
    ${unknowns}`;
}

function renderContamination(c) {
  c = c || {};
  const cls = scoreCls(c.overall_contamination_level);
  const hyps = (c.hypotheses_assessed || []).map(h => {
    const hcls = scoreCls(h.score_label);
    const hasScore = Number.isInteger(h.contamination_score);
    const score = hasScore ? h.contamination_score : null;
    const scoreText = hasScore ? `${score}/100 · ${esc(h.score_label)}` : esc(h.score_label || 'Insufficient data');
    return `
      <div class="hyp-item">
        <div class="hyp-top">
          <div class="hyp-text">${esc(h.hypothesis)}</div>
          <span class="badge-score ${hcls}">${scoreText}</span>
        </div>
        <div class="score-track"><div class="score-fill ${hcls.replace('s-','')}" style="width:${hasScore ? score : 0}%"></div></div>
        <div class="hyp-explanation">${esc(h.explanation)}</div>
        ${h.responses_matching ? `<div class="assumption-freq">${h.measured ? 'Measured: ' : ''}${esc(h.responses_matching)}</div>` : ''}
        ${h.per_model ? `<div class="assumption-freq">${Object.entries(h.per_model).map(([m, c]) => esc(m) + ': ' + (c.main||0) + ' main, ' + (c.mentions||0) + ' factor, ' + (c.disputes||0) + ' disputed, ' + (c.absent||0) + ' absent').join(' · ')}</div>` : ''}
        ${h.presence_pct != null ? `<div class="assumption-freq">Raised in ${h.presence_pct}% of answers</div>` : ''}
        ${(h.evidence_quotes || []).length ? `<div class="hyp-evidence"><div class="card-label">Evidence from the AI answers</div>${h.evidence_quotes.map(q => `<div class="assumption-quote">"${esc(q)}"</div>`).join('')}</div>` : `<div class="assumption-quote">${hasScore ? 'No supporting quote returned. Treat this score with caution.' : 'This hypothesis was not scored because complete classification data was unavailable.'}</div>`}
        <div class="hyp-rec">${esc(h.recommendation)}</div>
      </div>`;
  }).join('');

  document.getElementById('panel-contamination-content').innerHTML = `
    <div class="card card-mb-5">
      <div class="badge-row">
        <div class="card-label no-margin">Overall contamination</div>
        <span class="badge-score ${cls}">${esc(c.overall_contamination_level)}</span>
      </div>
      <p>${esc(c.overall_explanation)}</p>
      <div class="assumption-quote">How the indicator is computed: a classifier reads every AI answer in section 09 and marks whether it presents the idea as the main cause (counts 1), as one factor among several (0.6), disputes it (minus 0.5), or omits it (0). Every answer must have exactly one valid classification or the hypothesis shows Insufficient data. Bands: 0-25 Low, 26-50 Medium, 51-75 High, 76-100 Critical. Models: ${esc((((allData || {}).convergence || {}).models || []).join(', ') || 'the probe models')}.</div>
      ${c.most_dangerous_assumption ? `<div class="card-divider"></div><div class="card-label">Most dangerous assumption</div><p class="text-danger">${esc(c.most_dangerous_assumption)}</p>` : ''}
    </div>
    ${hyps}`;
}

function renderDrift(d) {
  const cls = scoreCls(d.overall_drift_risk);
  const items = (d.stale_assumptions || []).map(s => `
    <div class="drift-item">
      <div class="drift-assumption">${esc(s.assumption)}</div>
      <div class="drift-why">${esc(s.why_stale)}</div>
      <div class="drift-impl">${esc(s.research_implication)}</div>
    </div>`).join('');

  const fast = (d.fast_moving_dimensions || []).map(f => `<span class="tag">${esc(f)}</span>`).join('');

  document.getElementById('panel-drift-content').innerHTML = `
    <div class="card card-mb-5">
      <div class="badge-row">
        <div class="card-label no-margin">Drift risk</div>
        <span class="badge-score ${cls}">${esc(d.overall_drift_risk)}</span>
      </div>
      <p>${esc(d.drift_explanation)}</p>
      ${d.recommendation ? `<div class="card-divider"></div><p><strong>${esc(d.recommendation)}</strong></p>` : ''}
    </div>
    ${items}
    ${fast ? `<div class="card"><div class="card-label">Fast-moving dimensions to probe</div><div class="tag-row">${fast}</div></div>` : ''}`;
}

function renderCompetitors(ci) {
  const rows = (ci.brands_mentioned || []).map(b => `
    <tr>
      <td>${esc(b.brand)}</td>
      <td>${esc(b.frequency)}</td>
      <td>${esc(b.framing)}</td>
      <td><span class="badge-score ${scoreCls(b.priming_risk)}">${esc(b.priming_risk)}</span></td>
    </tr>`).join('');

  document.getElementById('panel-competitors-content').innerHTML = `
    <div class="card card-mb-4">
      <div class="card-label">AI category leader</div>
      <p>${esc(ci.category_leader_in_ai)}</p>
      <div class="card-divider"></div>
      <div class="card-label">Invisible competitors</div>
      <p>${esc(ci.invisible_competitors)}</p>
    </div>
    ${rows ? `<div class="card"><div class="card-label">Brands in AI responses</div>
      <table class="brand-table">
        <thead><tr><th>Brand</th><th>Frequency</th><th>Framing</th><th>Priming risk</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>` : ''}
    ${ci.discussion_guide_implication ? `<div class="card"><div class="card-label">Discussion guide implication</div><p>${esc(ci.discussion_guide_implication)}</p></div>` : ''}`;
}

function renderArchaeology(a) {
  const sources = (a.source_landscape || []).map(s => `
    <div class="source-item">
      <span class="inf-pill ${infCls(s.influence_level)}">${esc(s.influence_level)}</span>
      <div>
        <div class="source-type">${esc(s.source_type)}</div>
        <div class="source-contrib">${esc(s.what_it_contributes)}</div>
        <div class="source-voice">${esc(s.whose_voice)}</div>
      </div>
    </div>`).join('');

  const absent = (a.absent_voices || []).map(v => `<span class="tag absent">${esc(v)}</span>`).join('');

  const grounded = a.grounded === true;
  const banner = grounded
    ? `<div class="iq-banner"><span class="iq-banner-dot"></span><span class="iq-banner-text">Retrieved sources are available · every consequential claim still requires human verification</span></div>`
    : '';

  const citations = (a.sources || []).filter(c => safeUrl(c.url) && !/follow us|facebook|@\w+|download\?|cookie|sign in|log in/i.test(c.title || '')).map(c => `
    <a class="citation" href="${esc(safeUrl(c.url))}" target="_blank" rel="noopener noreferrer">
      <div class="citation-title">${esc(c.title)}</div>
      ${c.url ? `<div class="citation-url">${esc(c.url)}</div>` : ''}
      ${c.snippet ? `<div class="citation-snippet">${esc(c.snippet)}</div>` : ''}
    </a>`).join('');

  const verdictCls = v => { v = (v || '').toLowerCase(); return v.startsWith('not') ? 's-high' : v.startsWith('partly') ? 's-medium' : v.startsWith('supported') ? 's-low' : ''; };
  const findingRow = (f, kind) => `
    <div class="ev-row ${kind}">
      <span class="ev-kind">${kind === 'for' ? 'FOR' : 'AGAINST'}</span>
      <div>
        <div>${esc(f.finding)}</div>
        <div class="citation-url">${f.source_retrieved === true && safeUrl(f.url) ? `<a href="${esc(safeUrl(f.url))}" target="_blank" rel="noopener noreferrer">${esc(f.source || f.url)}</a>` : 'No matching retrieved source'}${f.year ? ' · ' + esc(f.year) : ''} · ${esc(f.verification_status || 'unverified')}</div>
      </div>
    </div>`;
  const hypEvidence = (a.hypothesis_evidence || []).map(he => `
    <div class="card card-mb-4">
      <div class="badge-row">
        <div class="card-label no-margin">Evidence on: ${esc(he.hypothesis)}</div>
        ${he.verdict ? `<span class="badge-score ${verdictCls(he.verdict)}">${esc(he.verdict)}</span>` : ''}
      </div>
      ${he.grounded ? `<p>${esc(he.summary)}</p>` : `<p class="text-amber">${he.summary ? esc(he.summary) : 'No grounded evidence returned for this hypothesis.'}</p>`}
      ${(he.countries || []).map(c => `
        <div class="card-divider"></div>
        <div class="badge-row"><div class="card-label no-margin">${esc(c.country)}</div>${c.verdict ? `<span class="badge-score ${verdictCls(c.verdict)}">${esc(c.verdict)}</span>` : ''}</div>
        ${(c.for || []).map(f => findingRow(f, 'for')).join('')}
        ${(c.against || []).map(f => findingRow(f, 'against')).join('')}`).join('')}
    </div>`).join('');

  document.getElementById('panel-archaeology-content').innerHTML = `
    ${banner}
    ${hypEvidence ? `<div class="card-label mb-3">Published evidence for and against each client hypothesis</div>${hypEvidence}` : ''}
    <div class="card card-mb-4">
      <div class="card-label">Dominant narrative origin</div>
      <p>${esc(a.dominant_narrative_origin)}</p>
      <div class="card-divider"></div>
      <div class="card-label">Implication for research design</div>
      <p>${esc(a.implication_for_research)}</p>
      ${a.decolonisation_note ? `<div class="card-divider"></div><div class="card-label">Anglo-centrism note</div><p class="text-amber">${esc(a.decolonisation_note)}</p>` : ''}
    </div>
    <div class="card-label mb-3">Source landscape</div>
    ${sources}
    ${citations ? `<div class="card-label" style="margin-bottom:var(--sp-3);margin-top:var(--sp-5)">Cited web sources (OpenAI web search)</div>${citations}` : ''}
    ${absent ? `<div class="card"><div class="card-label">Absent voices</div><div class="tag-row">${absent}</div></div>` : ''}`;
}

function renderMethodology(m) {
  const items = (m.methodology_breakdown || []).map(mb => `
    <div class="method-item">
      <div class="method-dim">${esc(mb.dimension)}</div>
      <div class="method-rec">${esc(mb.recommended_method)}</div>
      <div class="method-rationale">${esc(mb.rationale)}</div>
      ${mb.ai_bias_risk ? `<div class="method-risk">Risk: ${esc(mb.ai_bias_risk)}</div>` : ''}
    </div>`).join('');

  const qual_dims = (m.critical_qual_dimensions || []).map(q => `<span class="tag">${esc(q)}</span>`).join('');

  const fit = m.method_fit || {};
  const fitCls = (fit.decision || '').toLowerCase() === 'keep' ? 's-low' : (fit.decision || '').toLowerCase() === 'adjust' ? 's-medium' : 's-high';
  document.getElementById('panel-methodology-content').innerHTML = `
    ${fit.decision ? `<div class="card card-mb-4">
      <div class="badge-row">
        <div class="card-label no-margin">Fit with the method in your brief${fit.stated_method ? ': ' + esc(fit.stated_method) : ''}</div>
        <span class="badge-score ${fitCls}">${esc(fit.decision)}</span>
      </div>
      <p>${esc(fit.reason || '')}</p>
      ${fit.scope_and_cost_note ? `<div class="assumption-quote">${esc(fit.scope_and_cost_note)}</div>` : ''}
    </div>` : ''}
    <div class="card card-mb-4">
      <div class="card-label">Recommended approach</div>
      <p class="rec-heading">${esc(m.recommended_approach)}</p>
      ${m.sample_design_notes ? `<div class="card-divider"></div><div class="card-label">Sample design notes</div><p>${esc(m.sample_design_notes)}</p>` : ''}
      ${m.stimulus_material_warning ? `<div class="card-divider"></div><div class="card-label" class="text-amber">Stimulus material warning</div><p class="text-amber">${esc(m.stimulus_material_warning)}</p>` : ''}
    </div>
    ${m.projective_techniques_needed ? `<div class="card" class="accent-card"><div class="card-label" class="text-accent">Projective techniques needed</div><p>${esc(m.projective_rationale)}</p></div>` : ''}
    ${items}
    ${(m.hypothesis_tests || []).length ? `<div class="card-label mb-3" style="margin-top:var(--sp-5)">How to test each client hypothesis</div>` + m.hypothesis_tests.map(t => `
      <div class="method-item">
        <div class="method-dim">${esc(t.hypothesis)}</div>
        <div class="method-rec">${esc(t.how_to_test_it)}</div>
        <div class="method-risk">Drop it if: ${esc(t.what_would_refute_it)}</div>
      </div>`).join('') : ''}
    ${qual_dims ? `<div class="card"><div class="card-label">Must be qual - cannot survey</div><div class="tag-row">${qual_dims}</div></div>` : ''}
    ${(m.rejected_as_generic || []).length ? `<div class="card"><div class="card-label">Rejected as generic</div><div class="tag-row">${m.rejected_as_generic.map(r => `<span class="tag">${esc(r)}</span>`).join('')}</div></div>` : ''}`;
}

function gaugeColor(score) {
  if (score >= 70) return 'var(--ok)';
  if (score >= 50) return 'var(--amber)';
  if (score >= 30) return 'var(--danger)';
  return 'var(--danger-light)';
}

function confTagStyle(label) {
  const l = (label || '').toLowerCase();
  if (l === 'strong')      return 'background:var(--ok-dim);color:var(--ok)';
  if (l === 'adequate')    return 'background:var(--amber-dim);color:var(--amber)';
  if (l === 'fragile')     return 'background:var(--danger-dim);color:var(--danger)';
  return 'background:var(--danger-dim);color:var(--danger-light)';
}

function renderAssurance(assurance, review) {
  assurance = assurance || {};
  const level = assurance.assurance_level || 'limited';
  const limitations = assurance.limitations || [];
  const reviewText = review && review.complete
    ? `Review complete · ${esc(review.reviewer || 'researcher')} · ${esc(review.reviewed_at || '')}`
    : 'Researcher review required before an internal project or fieldwork decision';
  return `<div class="card card-mb-4 assurance-card">
    <div class="badge-row"><div class="card-label no-margin">Decision assurance</div><span class="badge-score ${scoreCls(level)}">${esc(level)}</span></div>
    <p>${esc(assurance.metric_notice || 'These outputs are advisory indicators and require researcher review.')}</p>
    <div class="assumption-quote">${reviewText}</div>
    ${limitations.map(item => `<div class="assumption-freq">· ${esc(item)}</div>`).join('')}
  </div>`;
}

function renderInternalRecommendation(recommendation) {
  if (!recommendation) return '';
  const tone = recommendation.decision === 'proceed' ? 's-low' : recommendation.decision === 'hold' ? 's-high' : 's-medium';
  const state = recommendation.decision === 'proceed' ? 'proceed' : recommendation.decision === 'hold' ? 'hold' : 'change';
  const reasons = (recommendation.reasons || []).map(reason => `<li>${esc(reason)}</li>`).join('');
  return `<div class="card card-mb-4 internal-decision-card decision-${state}">
    <div class="decision-header">
      <div><div class="card-label no-margin">Internal workflow recommendation</div><p class="rec-heading">${esc(recommendation.recommended_action)}</p></div>
      <span class="badge-score ${tone}">${esc(recommendation.label)}</span>
    </div>
    ${reasons ? `<div class="decision-reasons"><div class="decision-reasons-label">Why</div><ul>${reasons}</ul></div>` : ''}
    <div class="decision-notice">${esc(recommendation.notice)} <span>Status: ${esc(recommendation.review_status)}.</span></div>
  </div>`;
}

function renderHealth(h) {
  if (!h) return '';
  const errs = h.step_errors || [];
  const warn = [];
  if (h.quick_mode) warn.push('Quick mode: one AI model and no web evidence. Scores are indicative only.');
  if (!h.answers_collected) warn.push('No AI answers were collected, so contamination could not be measured.');
  if (!h.quick_mode && !h.grounded) warn.push('Web grounding returned nothing, so the evidence sections are model-only.');
  if (h.classification_failures) warn.push(h.classification_failures + ' hypothesis indicator(s) have insufficient classification data and were not scored.');
  if (h.unassessed_hypotheses) warn.push(h.unassessed_hypotheses + ' additional hypothesis/hypotheses were preserved but not measured beyond the five-hypothesis limit.');
  if ((h.explanation_contract_errors || []).length) warn.push(h.explanation_contract_errors.length + ' explanation result(s) failed the hypothesis-ID completeness check.');
  (h.contract_errors || []).forEach(e => warn.push('Result contract: ' + e));
  errs.forEach(e => warn.push('Step "' + e.step + '" failed and used a fallback: ' + e.error));
  if (!warn.length) return '';
  return `<div class="card card-mb-4" style="border-color:var(--amber)">
    <div class="card-label">Run health</div>
    ${warn.map(w => `<div class="assumption-quote">${esc(w)}</div>`).join('')}
    <div class="assumption-freq">${h.answers_collected} AI answers from ${(h.probe_models || []).join(', ')}${h.run_log_dir ? ' · log: ' + esc(h.run_log_dir) : ''}</div>
  </div>`;
}

function renderSummary(d) {
  const c = d.confidence || {};
  const score = c.confidence_score != null ? c.confidence_score : 50;
  const color = gaugeColor(score);
  const circumference = 2 * Math.PI * 56;
  const offset = circumference * (1 - score / 100);

  const risks = (c.top_three_risks || []).map((r, i) => `
    <div class="risk-item">
      <span class="risk-num">${String(i+1).padStart(2,'0')}</span>
      <span class="risk-text">${esc(r)}</span>
    </div>`).join('');

  // At-a-glance tiles pulling the headline finding from each layer
  const tiles = [
    { label: 'Hypotheses', finding: (d.contamination||{}).overall_contamination_level ? 'Contamination: ' + esc(d.contamination.overall_contamination_level) : 'n/a', panel: 'contamination' },
    { label: 'Temporal drift', finding: (d.temporal_drift||{}).overall_drift_risk ? 'Risk: ' + esc(d.temporal_drift.overall_drift_risk) : 'n/a', panel: 'drift' },
    { label: 'Blind spots', finding: ((d.gaps||{}).underrepresented||[]).length + ' under-represented perspectives', panel: 'gaps' },
    { label: 'Brand priming', finding: ((d.competitor_intel||{}).brands_mentioned||[]).length + ' brands appear unprompted', panel: 'competitors' },
    { label: 'Open questions', finding: ((d.gaps||{}).unknown_unknowns||[]).length + ' questions nobody is asking', panel: 'gaps' },
    { label: 'Method', finding: esc(((d.methodology||{}).recommended_approach||'n/a').split(' - ')[0].split(' with ')[0]), panel: 'methodology' }
  ].map(t => `
    <div class="summary-tile" role="button" tabindex="0" data-action="jump-to" data-panel="${t.panel}">
      <div class="summary-tile-head">
        <span class="summary-tile-label">${t.label}</span>
      </div>
      <div class="summary-tile-finding">${t.finding}</div>
    </div>`).join('');

  document.getElementById('panel-summary-content').innerHTML = `
    <div class="section-title">
      <div class="section-eyebrow">Research design confidence</div>
      <h2>Is this research set up to tell you anything new?</h2>
      <p>One read on whether this brief is set up to tell you something new, or just confirm what AI would have told the client anyway.</p>
    </div>

    ${renderInternalRecommendation(d.internal_recommendation)}
    ${renderAssurance(d.assurance, d.human_review)}

    <div class="confidence-hero">
      <div class="gauge">
        <svg width="132" height="132" viewBox="0 0 132 132">
          <circle class="gauge-track" cx="66" cy="66" r="56"></circle>
          <circle class="gauge-fill" cx="66" cy="66" r="56"
            stroke="${color}"
            stroke-dasharray="${circumference}"
            stroke-dashoffset="${circumference}"
            id="gauge-fill-circle"></circle>
        </svg>
        <div class="gauge-center">
          <div class="gauge-num" style="color:${color}">${score}</div>
          <div class="gauge-unit">/ 100</div>
        </div>
      </div>
      <div class="confidence-detail">
        <span class="confidence-label-tag" style="${confTagStyle(c.confidence_label)}">${esc(c.confidence_label || 'Adequate')}</span>
        <div class="confidence-headline">${esc(c.headline || '')}</div>
        <div class="confidence-rationale">${esc(c.score_rationale || '')}</div>
      </div>
    </div>

    ${((d.gaps || {}).sample_cannot_test || []).length ? `<div class="card card-mb-4" style="border-color:var(--danger)">
      <div class="card-label">The stated sample cannot test these hypotheses</div>
      ${d.gaps.sample_cannot_test.map(x => `<div class="risk-item"><span class="risk-num">!</span><span class="risk-text">${esc(x.hypothesis)}<br><span class="assumption-quote">${esc(x.why)}</span></span></div>`).join('')}
      ${c.score_capped ? `<div class="assumption-freq">${esc(c.score_capped)}</div>` : ''}
    </div>` : ''}
    ${c.key_finding && c.key_finding.statement ? `<div class="card card-mb-4 key-finding">
      <div class="card-label">Key finding</div>
      <p class="rec-heading">${esc(c.key_finding.statement)}</p>
      <div class="assumption-freq">Basis: ${esc(c.key_finding.basis || '')}${(c.key_finding.sources || []).length ? ' · ' + c.key_finding.sources.map(esc).join('; ') : ''}</div>
    </div>` : ''}
    ${renderHealth(d.run_health)}
    ${risks ? `<div class="card">
      <div class="card-label">Fix these before fieldwork</div>
      <div class="risk-list">${risks}</div>
      ${c.what_would_raise_it ? `<div class="card-divider"></div><div class="card-label">Biggest single improvement</div><p class="text-accent">${esc(c.what_would_raise_it)}</p>` : ''}
    </div>` : ''}

    <div class="card-label" style="margin-bottom:var(--sp-3)">At a glance</div>
    <div class="summary-grid">${tiles}</div>
  `;

  // Animate the gauge after a tick
  setTimeout(() => {
    const circle = document.getElementById('gauge-fill-circle');
    if (circle) circle.style.strokeDashoffset = offset;
  }, 200);
}

function jumpTo(panel) {
  const target = document.querySelector(`#results-view .nav-item[data-panel="${panel}"]`);
  showPanel(panel, target);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function buildReportMarkdown() {
  if (!allData) return;
  const d = allData;
  const c = d.confidence || {};
  const p = d.parsed || {};
  let md = '';
  md += '# BRIEF - AI Contamination Report\n\n';
  if (d.internal_recommendation) {
    md += '## Internal workflow recommendation: ' + d.internal_recommendation.label + '\n\n';
    md += d.internal_recommendation.recommended_action + '\n\n';
    (d.internal_recommendation.reasons || []).forEach(reason => { md += '- ' + reason + '\n'; });
    md += '\n_' + d.internal_recommendation.notice + '_\n\n';
  }
  md += '## Research Design Confidence: ' + (c.confidence_score != null ? c.confidence_score : 'n/a') + '/100 (' + (c.confidence_label || '') + ')\n\n';
  md += '> ' + (c.headline || '') + '\n\n';
  md += (c.score_rationale || '') + '\n\n';
  if (((d.gaps || {}).sample_cannot_test || []).length) {
    md += '### The stated sample cannot test these hypotheses\n\n';
    d.gaps.sample_cannot_test.forEach(x => { md += '- **' + x.hypothesis + '**: ' + x.why + '\n'; });
    if (c.score_capped) md += '\n_' + c.score_capped + '_\n';
    md += '\n';
  }
  if (c.key_finding && c.key_finding.statement) {
    md += '### Key finding\n\n' + c.key_finding.statement + '\n\n';
    if ((c.key_finding.sources || []).length) md += '_Sources: ' + c.key_finding.sources.join('; ') + '_\n\n';
  }

  if ((c.top_three_risks || []).length) {
    md += '### Fix before fieldwork\n';
    c.top_three_risks.forEach((r, i) => { md += (i+1) + '. ' + r + '\n'; });
    md += '\n';
  }

  md += '---\n\n## Brief\n\n';
  md += '- **Category:** ' + (p.category || '') + '\n';
  md += '- **Specific topic:** ' + (p.topic || p.product_or_service || p.category || '') + '\n';
  md += '- **Geography:** ' + (p.geography || '') + '\n';
  md += '- **Audience:** ' + (p.target_audience || '') + '\n';
  md += '- **Objective:** ' + (p.research_objective || '') + '\n\n';

  const cont = d.contamination || {};
  const g = d.gaps || {};
  md += '## Blind spots\n\n';
  if (g.audience_mismatch) md += g.audience_mismatch + '\n\n';
  if ((g.overrepresented || []).length) { md += '**Over-represented in AI:** ' + g.overrepresented.map(x => x.perspective || x).join('; ') + '\n\n'; }
  if ((g.underrepresented || []).length) { md += '**Under-represented in AI:** ' + g.underrepresented.map(x => x.perspective || x).join('; ') + '\n\n'; }
  if ((g.unknown_unknowns || []).length) { md += '**Unknown unknowns to explore:**\n'; g.unknown_unknowns.forEach(u => { md += '- ' + (typeof u === 'string' ? u : (u.question || u.text || JSON.stringify(u))) + '\n'; }); md += '\n'; }
  const ci = d.competitor_intel || {};
  if ((ci.brands_mentioned || []).length) { md += '**Brands AI mentions unprompted:** ' + ci.brands_mentioned.map(b => b.brand || b.name || b).join(', ') + '\n\n'; }
  const rh = d.run_health || {};
  if (rh.quick_mode || (rh.step_errors || []).length) {
    md += '_Run health: ' + (rh.quick_mode ? 'quick mode (one model, no web evidence). ' : '') + ((rh.step_errors || []).length ? (rh.step_errors.length + ' step(s) used a fallback: ' + rh.step_errors.map(e => e.step).join(', ') + '.') : '') + '_\n\n';
  }
  md += '## Hypothesis Contamination: ' + (cont.overall_contamination_level || '') + '\n\n';
  md += (cont.overall_explanation || '') + '\n\n';
  (cont.hypotheses_assessed || []).forEach(h => {
    const indicator = Number.isInteger(h.contamination_score) ? h.contamination_score + '/100 ' + (h.score_label || '') : (h.score_label || 'Insufficient data');
    md += '- **[' + indicator + ']** ' + (h.hypothesis||'') + '\n';
    if (h.responses_matching) md += '  - ' + h.responses_matching + '\n';
    (h.evidence_quotes || []).forEach(q => { md += '  - Evidence: "' + q + '"\n'; });
    md += '  - ' + (h.recommendation||'') + '\n';
  });
  md += '\n';

  const dr = d.temporal_drift || {};
  md += '## Temporal Drift: ' + (dr.overall_drift_risk || '') + '\n\n' + (dr.drift_explanation || '') + '\n\n';

  const m = d.methodology || {};
  md += '## Recommended Methodology\n\n';
  if (m.method_fit && m.method_fit.decision) {
    md += '**Fit with the method in the brief (' + (m.method_fit.stated_method || 'not specified') + '):** ' + m.method_fit.decision + '. ' + (m.method_fit.reason || '') + ' ' + (m.method_fit.scope_and_cost_note || '') + '\n\n';
  }
  md += (m.recommended_approach || '') + '\n\n';
  md += (m.sample_design_notes || '') + '\n\n';
  (m.hypothesis_tests || []).forEach(t => {
    md += '- **Test:** ' + (t.hypothesis || '') + '\n  - How: ' + (t.how_to_test_it || '') + '\n  - Drop it if: ' + (t.what_would_refute_it || '') + '\n';
  });
  if ((m.hypothesis_tests || []).length) md += '\n';
  if ((m.rejected_as_generic || []).length) md += '_Rejected as generic: ' + m.rejected_as_generic.join('; ') + '_\n\n';

  const arch = d.archaeology || {};
  if ((arch.sources || []).length || (arch.hypothesis_evidence || []).some(h => h.grounded)) {
    (arch.hypothesis_evidence || []).forEach(he => {
      if (!he.grounded) return;
      md += '## Evidence on: ' + he.hypothesis + '\n\n**Verdict: ' + (he.verdict || '') + '.** ' + (he.summary || '') + '\n\n';
      (he.countries || []).forEach(ct => {
        md += '### ' + ct.country + (ct.verdict ? ' (' + ct.verdict + ')' : '') + '\n';
        (ct.for || []).forEach(f => { md += '- FOR: ' + f.finding + (f.url ? ' ([' + (f.source || 'source') + '](' + f.url + ')' : ' (' + (f.source || '')) + (f.year ? ', ' + f.year : '') + ')\n'; });
        (ct.against || []).forEach(f => { md += '- AGAINST: ' + f.finding + (f.url ? ' ([' + (f.source || 'source') + '](' + f.url + ')' : ' (' + (f.source || '')) + (f.year ? ', ' + f.year : '') + ')\n'; });
        md += '\n';
      });
    });
    md += '## Where these assumptions come from (retrieved sources; human verification required)\n\n';
    md += (arch.dominant_narrative_origin || '') + '\n\n';
    md += '### Cited sources\n';
    arch.sources.forEach(s => {
      md += '- [' + (s.title || 'Source') + '](' + (s.url || '') + ')\n';
    });
    md += '\n';
  }

  const dl = d.deliverables || {};
  if (dl.challenge_note && dl.challenge_note.what_we_found) {
    const n = dl.challenge_note;
    md += '## Challenge note for the client' + (n.title ? ': ' + n.title : '') + '\n\n' + [n.opening, n.what_we_found, n.what_we_recommend, n.closing].filter(Boolean).join('\n\n') + '\n\n';
  }
  if ((dl.discussion_guide_probes || []).length) {
    md += '## Discussion guide probes\n\n';
    dl.discussion_guide_probes.forEach(g => {
      md += '### Tests: ' + g.hypothesis + '\n\nWarm-up: ' + g.warm_up + '\n\n';
      (g.probes || []).forEach(p => { md += '- ' + p + '\n'; });
      if (g.avoid) md += '\n_Do not ask: ' + g.avoid + '_\n';
      md += '\n';
    });
  }
  if ((dl.task_scenarios || []).filter(t => t.task).length) {
    md += '## Usability task scenarios\n\n';
    const tidy = x => String(x || '').trim().replace(/\.+$/, '');
    dl.task_scenarios.filter(t => t.task).forEach(t => { md += '- **' + tidy(t.task) + '.** Success: ' + tidy(t.success_measure) + '. Tests: ' + tidy(t.hypothesis_tested) + '.\n'; });
    md += '\n';
  }
  if ((dl.screener_criteria || []).length) {
    md += '## Screener criteria\n\n';
    dl.screener_criteria.forEach(c => { md += '- ' + c.criterion + (c.quota_note ? ' (' + c.quota_note + ')' : '') + '. Why: ' + c.why + '\n'; });
    md += '\n';
  }

  const q = d.query_data || {};
  const allResp = (q.base_responses || []).concat(q.persona_responses || []);
  if (allResp.length) {
    md += '## Appendix: what AI actually said\n\n_' + allResp.length + ' answers, each cut to 700 characters. Full text is in the runs folder (03_query.json)._\n\n';
    allResp.forEach((r, i) => {
      const body = (r.response || '');
      md += '### ' + (i + 1) + '. ' + (r.model ? '[' + r.model + '] ' : '') + (r.persona ? '[' + r.persona + '] ' : '') + (r.prompt || '') + '\n\n' + body.slice(0, 700) + (body.length > 700 ? ' [...]' : '') + '\n\n';
    });
  }

  md += '---\n_Generated by BRIEF - Bias & Research Intelligence Evaluation Framework. Advisory model-assisted output; human review and citation verification required._\n';

  return md;
}

function showError(msg) {
  const el = document.getElementById('error-box');
  el.textContent = msg;
  el.style.display = 'block';
  document.getElementById('run-btn').disabled = false;
  document.getElementById('confirm-btn').disabled = false;
  document.getElementById('audit-btn').disabled = false;
}

function hideError() {
  document.getElementById('error-box').style.display = 'none';
}

// ---------------------------------------------------------------------------
// Download in Markdown, Word or PDF
// ---------------------------------------------------------------------------

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = filename; link.click();
  URL.revokeObjectURL(url);
}

function exportBaseName(kind, data) {
  // e.g. BRIEF-report-pet-food-2026-09-11-1432
  const slugSource = kind === 'audit'
    ? ((data.brief || {}).category || data.instrument_type || 'guide')
    : (((data.parsed || {}).category) || 'report');
  const slug = String(slugSource).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'report';
  const d = new Date();
  const pad = n => String(n).padStart(2, '0');
  const stamp = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
  return `${kind === 'audit' ? 'BRIEF-guide-audit' : 'BRIEF-report'}-${slug}-${stamp}`;
}

async function downloadAs(kind, format) {
  const data = kind === 'audit' ? auditData : allData;
  if (!data) return;
  const base = exportBaseName(kind, data);
  if (format === 'md') {
    const md = kind === 'audit' ? buildAuditMarkdown() : buildReportMarkdown();
    saveBlob(new Blob([md], { type: 'text/markdown' }), base + '.md');
    return;
  }
  const btns = document.querySelectorAll('.export-menu button');
  btns.forEach(b => b.disabled = true);
  try {
    const resp = await fetch('/export', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, data, format, filename: base }) });
    if (!resp.ok) { const err = await resp.json().catch(() => ({})); showError(err.error || 'Export failed.'); return; }
    saveBlob(await resp.blob(), base + '.' + format);
  } catch (e) {
    showError('Export failed: ' + e.message);
  } finally {
    btns.forEach(b => b.disabled = false);
  }
}

function toggleExportMenu(id) {
  const menu = document.getElementById(id);
  const open = menu.style.display === 'block';
  document.querySelectorAll('.export-menu').forEach(m => m.style.display = 'none');
  menu.style.display = open ? 'none' : 'block';
}

document.addEventListener('click', (e) => {
  const control = e.target.closest('[data-action]');
  if (control) {
    const action = control.dataset.action;
    if (action === 'toggle-theme') toggleTheme();
    else if (action === 'set-tool') setTool(control.dataset.tool);
    else if (action === 'set-mode') setMode(control.dataset.mode);
    else if (action === 'clear-inputs') clearInputs(control.dataset.target);
    else if (action === 'review-brief') reviewBrief();
    else if (action === 'add-hypothesis') addHypothesis('');
    else if (action === 'remove-hypothesis') control.closest('.hyp-row').remove();
    else if (action === 'run-analysis') runAnalysis();
    else if (action === 'run-audit') runAudit();
    else if (action === 'cancel-run') cancelRun();
    else if (action === 'show-panel') showPanel(control.dataset.panel, control);
    else if (action === 'show-audit-panel') showAuditPanel(control.dataset.panel, control);
    else if (action === 'jump-to') jumpTo(control.dataset.panel);
    else if (action === 'filter-audit') filterAudit(control.dataset.filter, control);
    else if (action === 'copy') copyText(control.dataset.copyTarget);
    else if (action === 'toggle-export') toggleExportMenu(control.dataset.menu);
    else if (action === 'download') downloadAs(control.dataset.kind, control.dataset.format);
    else if (action === 'new-analysis') newAnalysis();
    else if (action === 'submit-review') submitReview(control.dataset.kind);
  }
  if (!e.target.closest('.export-wrap')) document.querySelectorAll('.export-menu').forEach(m => m.style.display = 'none');
});

document.addEventListener('change', (e) => {
  const input = e.target.closest('[data-upload-target]');
  if (input) uploadFile(input, input.dataset.uploadTarget);
});

document.addEventListener('keydown', (e) => {
  if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('[data-action="jump-to"]')) {
    e.preventDefault(); jumpTo(e.target.dataset.panel);
  }
});
