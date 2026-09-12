# BRIEF

> **Deployment status:** pilot hardening is in progress. Use only behind organisational access controls, with approved low-sensitivity data. Raw payload logging and web grounding are disabled by default. See [the deployment baseline](docs/DEPLOYMENT.md) and [security policy](SECURITY.md).


### Bias & Research Intelligence Evaluation Framework

**An internal research-intelligence workspace with two tools: one audits what AI already assumes about a research brief before fieldwork begins; the other audits a discussion guide or questionnaire for questions that would confirm rather than test.**

BRIEF was first built for the Microsoft Agents League hackathon (Reasoning Agents track) on Microsoft Foundry, where it won the Hack for Good award. This version runs on the OpenAI API only: one API key, no Azure subscription. It has since been extended well beyond the hackathon build; see "What changed since the hackathon" at the end.

---

## Why it exists

I am a market researcher. A growing part of my job, and my colleagues' jobs, now starts with an AI model: asking it to summarise a category, suggest hypotheses, or sketch an audience before we design a study.

The model's answer is never neutral. It reflects whatever dominated its training data, usually Western, urban, commercial, English-language sources. Two things then go wrong. The research tends to confirm what the model already believed. And respondents have often absorbed the same narratives, so even their answers echo the consensus back. The result is expensive research that validates a starting assumption rather than discovering anything, and the contamination is invisible because nobody mapped it.

BRIEF maps it, before the money is spent.

---

## What it does

### Tool 1: audit a brief

Paste a research brief, or upload the RFP, client email or kick-off deck. BRIEF reads it, shows you the hypotheses it found so you can correct them, then runs twelve analysis stages and produces an advisory report with:

- **A heuristic research-design review indicator** (0 to 100) for the study as the brief states it, with the label computed from the score
- **A key finding** backed by a named published source or a measured count
- **Sample fit**: hypotheses the stated sample or fieldwork location cannot test, which caps the score at 50
- **Hypothesis contamination**: a measured score for each client hypothesis, computed from how two AI models answer twenty consumer-style questions, with the verbatim quotes behind it
- **What AI assumes** about the topic, whose perspective dominates, what it over- and under-represents, and the unknown unknowns
- **Published evidence** for and against each hypothesis, per country, with source and year, found by a reasoning model with web search
- **Temporal drift**: which AI assumptions are stale, against dated sources
- **Brand priming**: brands the model raises unprompted
- **Methodology**: whether to keep, adjust or change the method in the brief and what that costs, plus how to test each hypothesis and what finding should make the client drop it
- **Paste-ready outputs**: a client challenge note, discussion guide probes per hypothesis, screener criteria, and in UX mode, usability task scenarios
- **An appendix** of every AI answer the scores were computed from
- **An internal workflow recommendation**: proceed to research planning, proceed after changes, or hold before fieldwork, with the deterministic reasons shown separately from the score
- **Researcher sign-off**: accept, reject or amend material findings and record the rationale before relying on the result

### Tool 2: audit a guide or questionnaire

Paste or upload a discussion guide, interview script, survey or usability test plan, optionally with the brief. In under two minutes BRIEF extracts every item, flags leading wording, presuppositions, hypothesis-confirming items, double-barrelled questions, loaded terms, priming, jargon, closing too early, unbalanced scales, social desirability and (for usability tasks) instructions that name the feature. Each flag has a severity and a neutral rewrite. With a brief supplied it also marks each client hypothesis as tested, confirmed only or untested, proposes the missing questions, and produces a clean copy of the instrument.

### Two modes

**Market research** (default) and **UX research**. UX mode changes what is extracted (product, user task), the personas probed (mobile-only, screen reader, first-time, frustrated power user), the blind spots checked (device, accessibility, context of use) and the methods routed to (usability testing, diary studies, card sorting, accessibility audits).

### Exports

Word (.docx), PDF and Markdown, for both tools. Word and PDF are designed documents built from the structured results: internal recommendation and score, boxed key finding and sample-fit warnings, tables for hypotheses, evidence, methods, tasks and screener, and an appendix of AI answers. Filenames carry the category and a timestamp.

PDF exports embed DejaVu Sans so accented and multilingual research text is retained without relying on fonts installed on the host machine.

### Interface

The browser interface is designed as a supervised internal workspace rather than a client-facing report portal:

- The landing page states the internal quality-assurance purpose plainly and moves directly into the chosen audit workflow.
- Brief and guide audits share one clearly separated tool switch, while Market research and UX research remain available within each workflow.
- Results lead with the internal workflow recommendation, followed by its reasons, review status, assurance limitations and the underlying research-design indicator.
- The full evidence trail, raw AI answers, paste-ready outputs and researcher sign-off remain available through the results navigation.
- Light and dark themes, visible keyboard focus, labelled controls and responsive layouts support laptop, tablet and mobile use.

The interface deliberately distinguishes **recommendation**, **score**, **evidence** and **human review**. A polished presentation does not make any of them validated truth.

---


An orchestrator (`run_brief` in `agent.py`) passes state through twelve model-assisted analysis stages. These stages are not independent experts: they share upstream outputs and may share training-data patterns. Each stage has a scoped instruction and output contract.

```
Research brief
   |
   v
ORCHESTRATOR (run_brief)
   |
   1   PARSE           category, audience, geography, sample, fieldwork, hypotheses  [user can edit before continuing]
   2   GENERATE        six consumer-style questions, at least one per hypothesis
   3   QUERY           ask each probe model the six questions and four persona variants (20 answers)
   3b  CONVERGENCE     classifier marks every answer per hypothesis: main cause / one factor / disputed / absent
   4   CLUSTER         dominant assumptions across the answers
   5   GAPS            over- and under-represented perspectives, audience mismatch, sample fit
   6   CONTAMINATION   explains the measured score for each hypothesis with quotes
   7   ARCHAEOLOGY     web-grounded evidence for and against each hypothesis, per country; source landscape
   8   DRIFT           stale assumptions against dated evidence
   9   COMPETITORS     brands raised unprompted
  10   METHODOLOGY     method fit with the brief, approach, hypothesis tests
  11   CONFIDENCE      score, label, key finding, top three risks
  12   DELIVERABLES    challenge note, probes, screener, task scenarios
   |
   v
Report, exports, run log
```

Each agent runs inside its own error recovery. If one fails it records the failure, returns a safe fallback and the run continues; the report shows a Run health card naming the step.

---

## Methodological status

BRIEF is an internal research quality-assurance assistant, not an external client deliverable or organisational approval system. It automatically recommends whether an internal project should proceed to research planning, proceed after changes, or pause before fieldwork. The recommendation follows deterministic quality gates; its numerical outputs remain heuristic review indicators, not validated measures of bias, contamination, truth, construct validity or likely project success. Every result includes its evidence basis, limitations and required human decisions. See [Methodological assurance](docs/ASSURANCE.md).

## How the indicators are calculated

**Model-convergence indicators are computed, not asked for.** Every consumer question and persona variant goes to each probe model (default `gpt-4.1-mini` and `gpt-5.4-mini`). A classifier marks how each of the 20 answers treats each client hypothesis: main cause (1), one factor among several (0.6), disputed (minus 0.5), absent (0). The total is divided by the number of answers. Bands: 0 to 25 Low, 26 to 50 Medium, 51 to 75 High, 76 to 100 Critical. The report shows the counts per model and the formula. The explanation agent receives the measured score and must explain it with verbatim quotes; it cannot change it.

**Evidence is grounded per hypothesis.** A reasoning model with web search returns structured findings for and against each hypothesis, per country, with verdict, source and year. These feed the drift, methodology, confidence and deliverables agents, so the front page can cite published sources.

**The research-design review indicator assesses the brief, not the recommendation.** The review stage is told to score the design as stated and not to credit the client for methods BRIEF proposed. If the stated sample cannot test a hypothesis (older users on a 25 to 40 sample; drop-off on existing customers; Italy with UK-only interviews) the score is capped at 50 in code. The label is computed from the score: 75+ Strong, 55 to 74 Adequate, 40 to 54 Fragile, below 40 Compromised.

**The guide audit score** starts at 100 and loses 12 per high, 5 per medium and 1 per low issue, scaled for short instruments. It measures wording, not study design.

---

## Using it

1. Choose the tool tab and the mode (Market or UX).
2. Paste the text, or upload PDF, DOCX, TXT or MD. Clear empties the boxes.
3. Brief audit only: click **Review hypotheses**, check what was read, edit the hypotheses, sample and fieldwork, then **Run the analysis**. Tick **Quick mode** for a one to two minute run with one model and no web evidence; use the full run (five to seven minutes) before making an internal project decision.
4. Start with the internal workflow recommendation and its reasons, then inspect the score, evidence trail, run-health warnings and source status.
5. Complete researcher sign-off for material findings. Read the full report in the browser or export it; the header switches light and dark mode.

The review screen is populated from the pasted brief. BRIEF uses the configured AI model first and fills any missing fields with conservative local extraction. If the model is unavailable, the local extraction still identifies common labelled and prose fields—including explicit client hypotheses—and the screen shows a warning so the researcher can check every field before continuing. A working API key is still required to run the analysis itself.

---

## Trying it

Security, policy, deterministic-rule, contract, export and adversarial regression tests are in `tests/` and run in CI. Synthetic cases live in `evals/`; they are smoke tests, not expert validation.

Run the offline checks with:

```bash
pip install -r requirements-dev.txt
pytest -q
```

A brief to try:

> Research for a European car maker into electric vehicle adoption barriers among rural households in France, Spain and Romania. The client assumes range anxiety is the main barrier and that better public charging will unlock demand. Method: 30 in-depth interviews in each market.

Expected: range anxiety scores above 50 for contamination; the evidence shows purchase price outranks it in France and Romania; Romania is treated separately; home charging undercuts the public-charging hypothesis.

---

## Running it locally

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `OPENAI_API_KEY`. Then:

```bash
python app.py
```

Open `http://brief.localhost:5000`. If that name is not recognised by a managed browser or network policy, `http://localhost:5000` remains the fallback.

| Variable | Default | What it does |
|---|---|---|
| `OPENAI_API_KEY` | required | Key from an organisation-owned OpenAI project |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Model for the agents |
| `OPENAI_PROBE_MODELS` | `gpt-4.1-mini,gpt-5.4-mini` | Models whose answers are measured for consensus |
| `OPENAI_GROUNDING_MODEL` | `gpt-5.4-mini` | Reasoning model for web-grounded evidence |
| `OPENAI_GROUNDING_EFFORT` | `low` | `low`, `medium` or `high`; medium is slower and searches more |
| `OPENAI_BASE_URL` | unset | Route API calls through an internal gateway |
| `BRIEF_PASSWORD` | unset | Shared password for a hosted instance |
| `BRIEF_RUN_LOG_DIR` | `runs` | Where run logs are written |

---

## Testing

**Offline tests** (no API key): `pytest -q`. CI also compiles Python, checks browser JavaScript, audits dependencies, produces an SBOM, builds the container and smoke-tests liveness plus authenticated homepage access.

**Evaluation status:** checked-in synthetic cases verify deterministic and adversarial behaviour. Model quality remains unvalidated until a blinded, independently labelled expert benchmark is completed under `docs/ASSURANCE.md`.

---

## Inspecting a run

Raw trace logging is disabled by default. When explicitly enabled under an approved retention policy, an analysis writes JSON traces under `runs/`. Normal operational logs contain stage completion, model, request ID and token metadata rather than brief or response content.

---

## Code layout

```
config.py          every setting, read once from the environment
llm.py             model client, JSON-with-required-keys helper, run logging
agent.py           the twelve brief-audit agents and run_brief()
web_grounding.py   web search with citations; structured evidence per hypothesis
audit.py           the guide and questionnaire audit
documents.py       PDF, DOCX and text extraction for uploads
export.py          designed Word and PDF documents from the result data
app.py             Flask routes, sessions, server-sent progress
templates/         index.html (markup only)
templates/         minimal server-rendered application shell
static/            css/brief.css and js/brief.js (no build step)
tests/             offline security and access-control regression tests
evaluate.py        runs the brief set and scores what BRIEF caught
Dockerfile         container build; render.yaml and Procfile for PaaS hosts
```

---

## For IT and infrastructure teams

This section is for whoever has to run BRIEF inside an organisation. It covers what the app is, what it needs, what leaves the network, and what is stored.

### What it is

A single-process Python web application. No database, no message queue, no background workers beyond threads inside the one process. State lives in process memory for 30 minutes per session. Raw JSON traces are disabled by default and are written under `runs/` only when explicitly enabled. It can run on a laptop, a small VM, a container platform, or a PaaS such as Render.

### Runtime and dependencies

| Component | Requirement | Purpose |
|---|---|---|
| Python | 3.10 or newer (3.12 tested) | Runtime |
| `flask` | 3.x | Web framework and server-sent events |
| `gunicorn` | 21+ | Production WSGI server (Linux). On Windows use `waitress` or `python app.py` |
| `openai` | 1.66+ (3.x tested) | Chat Completions and Responses API client |
| `python-dotenv` | 1.x | Reads `.env` in development |
| `pypdf`, `python-docx` | 4+, 1.1+ | Text extraction from uploaded PDF and Word files |
| `reportlab` | 4+ | PDF export |

All dependencies are pure Python or ship wheels for Windows, macOS and Linux. No system packages are needed beyond Python itself. Exact versions are in `requirements.txt`; the container build in `Dockerfile` pins Python 3.12.

### External services and network

The only external service is the OpenAI API. Outbound HTTPS to `api.openai.com` on port 443 must be allowed. There are no analytics, telemetry, CDN or external font requests; the interface uses system fonts already installed on the user's device. If the organisation routes AI traffic through a gateway, set `OPENAI_BASE_URL` in the environment and the `openai` client will use it.

Endpoints used:

- `POST /v1/chat/completions` for the twelve agents and the classifier (`gpt-4.1-mini` and `gpt-5.4-mini` by default)
- `POST /v1/responses` with the `web_search` tool for grounding (`gpt-5.4-mini` by default). This is the one call that causes OpenAI to fetch public web pages on the app's behalf.

A full brief analysis makes roughly 45 API calls; a guide audit makes three to five; quick mode skips web search and uses one model.

### Data flow and retention

- **What leaves the network:** the brief or guide text the user pastes or uploads, and the text of the AI answers it generates, are sent to OpenAI inside API requests. OpenAI states that API data is not used for training unless the customer opts in. Abuse-monitoring and application-state retention are separate controls. This application passes `store=False`, but the operator must confirm the project’s current retention, residency and web-search eligibility before use.
- **What is stored locally:** by default, no raw prompt or response payload is written. Enabling `BRIEF_LOG_RAW_PAYLOADS` writes sensitive JSON traces under `runs/` and therefore requires an approved encrypted location, access policy and automatic deletion schedule.
- **What is stored in memory:** session results for 30 minutes (`SESSION_TTL_SECONDS`), then discarded.
- **Uploaded files** are read into memory, converted to text, and discarded. The file itself is not saved.
- **Exports** (Word, PDF, Markdown) are generated on request and streamed to the browser; they are not saved on the server.

### Authentication and access

The application fails closed unless it receives a trusted identity from an organisational proxy, has an explicitly configured pilot password, or is running with the development-only insecure flag. Production should set `BRIEF_TRUST_AUTH_PROXY=true` behind an OIDC/identity-aware proxy that strips inbound copies of the identity header. The Basic password remains a small-pilot fallback, not production identity.

### Researcher review workflow

The researcher corrects extracted hypotheses before analysis. Results then open with an automatically generated internal workflow recommendation and the deterministic reasons behind it. Each material finding records its evidence class and requires an accept, reject or amend decision with a rationale. Human review changes the review status, not the computed recommendation. Consequential citations appear as unverified findings until checked. Word, PDF and Markdown exports include attributed adjudication. Reports from different prompt versions are marked non-comparable.

### Configuration

All settings are environment variables, read once at start by `config.py`. `.env.example` lists them. `BRIEF_POLICY_PROFILE` selects `public_synthetic`, `internal_confidential` or `regulated_zdr`; unsafe web/logging overrides fail startup. The two that matter for adoption:

- `OPENAI_API_KEY`: use a key from an organisation-owned OpenAI account or project, not a personal one, so spend limits, data terms and revocation sit with the organisation.
- `BRIEF_PASSWORD`: set it, or front the app with a proxy.

Optional: `OPENAI_MODEL`, `OPENAI_PROBE_MODELS`, `OPENAI_GROUNDING_MODEL`, `OPENAI_GROUNDING_EFFORT`, `OPENAI_GROUNDING_TIMEOUT`, `BRIEF_RUN_LOG_DIR`.

### Running it

Any host that can run a Python process works. Three tested paths:

**Container**

```bash
docker build -t brief .
docker run -p 8000:8000 -e OPENAI_API_KEY=... -e BRIEF_PASSWORD=... -v brief-runs:/app/runs brief
```

**Render or similar PaaS**: `render.yaml` and `Procfile` are included. The start command is the same as the container's.

**Bare VM or laptop**: `pip install -r requirements.txt` then `gunicorn -w 1 --threads 8 --timeout 1000 app:app` (Linux or macOS) or `python app.py` (any OS, development server).

Constraints to respect:

- **One worker process only.** Sessions are in memory. A second process cannot see them and users will get "unknown session" errors. Scale by giving the one process more threads or more memory, not by adding processes. If more than one instance is ever needed, the session store needs to move to Redis or a database first; it is a small class in `app.py` designed for that.
- **Long requests.** A full analysis streams progress for five to seven minutes over one HTTP connection. Set proxy and load balancer idle timeouts to at least 15 minutes for the `/progress/` path, and disable response buffering for it (the app sends the `X-Accel-Buffering: no` header for nginx).
- **Resources.** Under 300 MB of memory and negligible CPU; the work happens at OpenAI. A 0.5 vCPU, 512 MB instance is enough for a team.

`GET /health/live` provides unauthenticated liveness without dependency details. Authenticated `GET /health/ready` checks required configuration.

### Cost

Usage is billed by OpenAI per token. Observed on real briefs: roughly 30 to 60 pence per full analysis with two probe models and web grounding, about a tenth of that for quick mode or a guide audit. Set a monthly spend limit on the OpenAI project before sharing the link.

### Moving to Azure OpenAI

The tool started life on Microsoft Foundry and the code keeps that door open. All model calls go through one client in `llm.py`; switching to Azure OpenAI is a change to that client's constructor and the model names, roughly ten lines. Web grounding would need an Azure equivalent (Azure AI Search or Bing grounding), which is the larger piece.

### Licence and third parties

The repository has no licence file yet; add one before sharing beyond the organisation (MIT is the usual choice for a tool like this). Dependencies are BSD, MIT and Apache licensed. No proprietary components. Web-grounded evidence quotes and links public sources; the report attributes each finding to its source and links to it.

---

## Deploying for colleagues

The repo includes a `render.yaml` and a `Procfile`. On Render:

1. Create a new Blueprint from this repo, or a Web Service with the start command in the `Procfile`.
2. Set `OPENAI_API_KEY` and `BRIEF_PASSWORD` in the environment settings.
3. Share the URL and the password.

Run one worker only; sessions live in process memory. A free Render instance sleeps after 15 minutes without traffic and takes about a minute to wake; the Starter tier removes that.

---

## What changed since the hackathon

The hackathon build had eleven agents on Foundry, one probe model, a single grounded "archaeology" call, and a browser-only report. Since then:

- Moved from Azure OpenAI and Foundry IQ to the OpenAI API with the Responses web search tool
- Contamination scores measured by a classifier across two models instead of asked of one model
- Evidence grounded per hypothesis, per country, structured with verdict, source and year
- Sample-fit check, honest scoring of the stated design, computed labels
- Editable hypotheses before the run; document upload; quick mode; run health; run logs per agent
- UX research mode
- Paste-ready outputs: challenge note, probes, screener, task scenarios
- The guide and questionnaire audit as a second tool
- Word and PDF exports; a responsive, decision-led browser interface; light and dark themes; improved keyboard accessibility
- Automatic internal workflow recommendations with explicit reasons, assurance limits and separate researcher sign-off status
- Refactor into config, llm, agent, audit, grounding, documents, export and app modules; offline test suite; evaluation set

Still open: running the same brief over time to see how contamination drifts; comparing predicted gaps against real fieldwork results, which is the only true test of whether the tool works.

---

## A note on purpose

BRIEF was built for market research, but the same problem reaches anywhere people use AI to frame a question before investigating it: healthcare, public policy, financial inclusion. Wherever a study's starting assumptions quietly come from a model rather than the world, the findings risk confirming the model instead of the reality. Making those assumptions visible before the work begins is a small contribution to research integrity.


## Assurance and operations

- [Methodological assurance](docs/ASSURANCE.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Deployment baseline](docs/DEPLOYMENT.md)
- [Operational runbook](docs/RUNBOOK.md)
- [Verification and acceptance](docs/VERIFICATION.md)
