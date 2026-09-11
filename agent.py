"""
The BRIEF pipeline: twelve agents that audit a research brief for AI contamination.

Each step_* function is one agent. run_brief() orchestrates them with per-step
error recovery, so one failed agent degrades the report instead of killing it.
Every agent writes its raw input and output to the run log (see llm.log_step),
which is how any score in the report can be traced back to evidence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import config
import web_grounding
from credibility import brief_assurance
from contracts import validate_report
from provenance import report_provenance
from llm import call_json, call_model, current_run_dir, log_step, start_run_log

log = logging.getLogger("brief.agent")

Parsed = dict[str, Any]
ProgressCallback = Callable[[str, int, int], None]

# Kept as a module attribute so tests and evaluate.py can override it.
PROBE_MODELS = config.PROBE_MODELS
MODEL = config.MODEL


UX_MODE_NOTE = """
RESEARCH MODE: UX research. The subject is a product, service or interface and how people use it.
Treat 'audience' as the user group, 'category' as the product or task domain, and hypotheses as
claims about user behaviour, needs, usability or comprehension (e.g. 'users cannot find X',
'onboarding is too long', 'older users prefer Y'). Think in terms of tasks, contexts of use,
devices, accessibility and mental models, not brand or market share."""


def _lines(items) -> str:
    """Join an iterable of strings with newlines, for prompt building."""
    return "\n".join(items)


def _hypothesis_records(parsed: Parsed) -> list[dict[str, str]]:
    """Return unique hypotheses with deterministic IDs that survive model reordering."""
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in parsed.get("client_hypotheses", []) or []:
        text = str((value.get("hypothesis") or value.get("text") or "") if isinstance(value, dict) else value).strip()
        canonical = " ".join(text.casefold().split())
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        records.append({
            "hypothesis_id": f"hyp-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:12]}",
            "hypothesis": text,
        })
    return records


def _attach_hypothesis_ids(parsed: Parsed) -> Parsed:
    records = _hypothesis_records(parsed)
    parsed["client_hypotheses"] = [item["hypothesis"] for item in records]
    parsed["hypothesis_records"] = records
    return parsed


def mode_note(parsed: Parsed | None) -> str:
    return UX_MODE_NOTE if str((parsed or {}).get("research_mode", "")).lower() == "ux" else ""


# Step 1: parse the brief
def step_parse(brief, mode="market"):
    system = """You are a senior research methodology expert.
Extract structured information from a research brief.
The text may be a short brief or a long document such as an RFP, a client email thread, a
kick-off deck or a previous report. Find the brief inside it. Ignore boilerplate, legal text
and formatting noise. List every hypothesis, assumption or belief the client states or clearly
implies, in the client's own terms, one per item, even when it is phrased as a fact.
Return ONLY valid JSON with exactly these fields:
{
  "core_question": "the main research question in one sentence",
  "category": "the market or topic category (e.g. health drinks, financial services)",
  "target_audience": "who the research is about, including demographics",
  "geography": "markets or regions mentioned, or 'Global' if not specified",
  "research_objective": "what the researcher wants to discover or validate",
  "client_hypotheses": ["list", "of", "stated", "assumptions", "or", "hypotheses"],
  "methodology_hints": "any methodology mentioned (qual/quant/survey/usability test/etc) or 'Not specified'",
  "sample_definition": "who will actually be recruited or surveyed, as the brief states it (e.g. 'existing customers aged 25 to 40'), or 'Not specified'",
  "fieldwork_locations": "where fieldwork will happen, as stated (e.g. 'London only'), or 'Not specified'",
  "product_or_service": "for UX briefs: the product, service or interface under study; otherwise ''",
  "user_task": "for UX briefs: the task or journey users are trying to complete; otherwise ''"
}"""
    if str(mode).lower() == "ux":
        system += UX_MODE_NOTE

    result = call_json("01_parse", system, f"Parse this research brief:\n\n{brief}",
                       required_keys=("core_question", "category", "target_audience", "geography", "client_hypotheses"))
    result["research_mode"] = "ux" if str(mode).lower() == "ux" else "market"
    result.setdefault("sample_definition", "Not specified")
    result.setdefault("fieldwork_locations", "Not specified")
    return result


# Step 2: generate consumer prompts
def step_generate(parsed):
    system = """You are an expert in consumer search behaviour and information-seeking patterns.
Generate exactly 6 varied prompts that real people - not researchers - would type or ask
about this topic. Make them natural, conversational, and semantically diverse.
Vary the framing: some curious, some sceptical, some seeking validation, some practical.
Return ONLY valid JSON with this exact structure:
{"prompts": ["six", "natural", "consumer", "questions", "go", "here"]}"""

    user = f"""Generate 6 natural consumer-style prompts for:{mode_note(parsed)}
Client hypotheses (at least one prompt must give AI a natural opening to raise EACH of these, without naming it; the rest cover the category broadly): {json.dumps(parsed.get('client_hypotheses', []))}
Product or service: {parsed.get('product_or_service', '')}
Category: {parsed.get('category', '')}
Core question: {parsed.get('core_question', '')}
Target audience: {parsed.get('target_audience', '')}
Geography: {parsed.get('geography', '')}"""

    result = call_json("02_generate", system, user, required_keys=("prompts",))
    return result.get("prompts", [])


# Step 3: query the probe models
def step_query(prompts, parsed, probe_models=None):
    """
    Ask every probe model each consumer prompt AND four persona variants.
    Calls run in parallel. Each response records which model produced it.
    """
    base_system = """You are a helpful assistant. Answer the question naturally and informatively."""

    category = parsed.get('category', 'this topic')
    core_q = parsed.get('core_question', '')

    if mode_note(parsed):
        product = parsed.get('product_or_service') or category
        personas = [
            {"label": "Mobile-only user", "framing": f"I only use my phone, never a laptop. {core_q}"},
            {"label": "Screen reader user", "framing": f"I use a screen reader. What is it like to use {product}, and what usually goes wrong?"},
            {"label": "First-time user", "framing": f"I have never used {product} before. What will confuse me and what should I expect?"},
            {"label": "Frustrated power user", "framing": f"I use {product} every day and it annoys me. What do people like me usually complain about?"}
        ]
    else:
        personas = [
            {"label": "Western English-speaker", "framing": f"As someone in the US or UK, {core_q}"},
            {"label": "Global South perspective", "framing": f"As someone in a developing economy, what should I know about {category}?"},
            {"label": "Sceptical consumer", "framing": f"I don't trust what brands say about {category}. What's the real story?"},
            {"label": "First-time researcher", "framing": f"I'm new to {category} and want to understand it properly. Where do I start?"}
        ]

    models = probe_models or PROBE_MODELS
    jobs = []
    for model in models:
        for prompt in prompts:
            jobs.append(("base", model, None, prompt))
        for p in personas:
            jobs.append(("persona", model, p["label"], p["framing"]))

    def run(job):
        kind, model, persona, prompt = job
        try:
            text = call_model(base_system, prompt, temperature=0.5, model=model)
        except Exception as e:
            log.warning("%s failed on a probe prompt: %s: %s", model, type(e).__name__, e)
            text = ""
        return kind, {"model": model, "persona": persona, "prompt": prompt, "response": text}

    responses, persona_responses = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for kind, rec in pool.map(run, jobs):
            if not rec["response"]:
                continue
            if kind == "base":
                rec.pop("persona")
                responses.append(rec)
            else:
                persona_responses.append(rec)

    return {"base_responses": responses, "persona_responses": persona_responses,
            "models": models}


# Step 3b: measured convergence
def step_convergence(parsed, query_data):
    """
    Measure, rather than ask, how often the AI answers contain each client
    hypothesis. A judge model classifies every answer as main, mentions, disputes
    or absent for each hypothesis. Counts are computed only for complete responses.
    """
    hypothesis_records = _hypothesis_records(parsed)
    measured_records = hypothesis_records[:5]
    unassessed_records = hypothesis_records[5:]
    answers = query_data.get("base_responses", []) + query_data.get("persona_responses", [])
    if not hypothesis_records:
        return {"hypotheses": [], "n_answers": len(answers), "models": query_data.get("models", [])}
    if not answers:
        insufficient = [{
            **record, "n_answers": 0, "classification_status": "insufficient_data",
            "classification_errors": ["no probe answers were available"],
            "main": None, "mentions": None, "disputes": None, "absent": None,
            "presence_pct": None, "measured_score": None, "per_model": {}, "quotes": [],
        } for record in measured_records]
        unassessed = [{
            **record, "n_answers": 0, "classification_status": "unassessed",
            "classification_errors": ["outside the five-hypothesis measurement limit"],
            "main": None, "mentions": None, "disputes": None, "absent": None,
            "presence_pct": None, "measured_score": None, "per_model": {}, "quotes": [],
        } for record in unassessed_records]
        return {"hypotheses": insufficient + unassessed, "n_answers": 0,
                "models": query_data.get("models", []), "measurement_limit": 5}

    system = """You are a strict content classifier.
For each numbered AI answer, decide how it treats the given hypothesis:
  "main"     = the answer presents the idea as THE main cause, the top barrier, the key driver, or as settled fact
  "mentions" = the answer includes the idea as one factor among several, without ranking it first
  "disputes" = the answer questions, downplays or contradicts the idea
  "absent"   = the idea does not appear
Judge the idea, not the exact words. Return ONLY valid JSON:
{"verdicts": [{"answer": 1, "verdict": "main|mentions|disputes|absent", "quote": "short verbatim phrase or empty"}]}
Include every answer number exactly once."""

    numbered = ""
    for i, r in enumerate(answers, 1):
        numbered += f"\n[Answer {i}] ({r.get('model','')})\n{(r.get('response') or '')[:1800]}\n"

    def judge(record):
        hypothesis_id = record["hypothesis_id"]
        h = record["hypothesis"]
        user = f"Hypothesis ID: {hypothesis_id}\nHypothesis: {h}\n\nAI answers:{numbered}"
        result = call_json("03b_convergence_judge", system, user, required_keys=("verdicts",), temperature=0)
        verdicts = {}
        errors = []
        rows = result.get("verdicts", [])
        if not isinstance(rows, list):
            rows = []
            errors.append("verdicts was not a list")
        for v in rows:
            if not isinstance(v, dict):
                errors.append("classification row was not an object")
                continue
            try:
                answer_number = int(v.get("answer"))
            except (TypeError, ValueError):
                errors.append("classification had an invalid answer number")
                continue
            verdict = str(v.get("verdict", "")).lower()
            if answer_number < 1 or answer_number > len(answers):
                errors.append(f"classification referenced answer {answer_number} out of range")
            elif answer_number in verdicts:
                errors.append(f"answer {answer_number} was classified more than once")
            elif verdict not in {"main", "mentions", "disputes", "absent"}:
                errors.append(f"answer {answer_number} had invalid verdict {verdict!r}")
            else:
                verdicts[answer_number] = v
        missing = sorted(set(range(1, len(answers) + 1)) - set(verdicts))
        if missing:
            errors.append(f"missing classifications for answers {missing}")
        if len(rows) != len(answers):
            errors.append(f"expected {len(answers)} classification rows, received {len(rows)}")
        if errors:
            return {
                "hypothesis_id": hypothesis_id,
                "hypothesis": h,
                "n_answers": len(answers),
                "classification_status": "insufficient_data",
                "classification_errors": errors,
                "main": None, "mentions": None, "disputes": None, "absent": None,
                "presence_pct": None, "measured_score": None,
                "per_model": {}, "quotes": [],
            }
        per_model = {}
        quotes = []
        counts = {"main": 0, "mentions": 0, "disputes": 0, "absent": 0}
        for i, r in enumerate(answers, 1):
            v = verdicts[i]
            verdict = str(v["verdict"]).lower()
            m = r.get("model", "unknown")
            per_model.setdefault(m, {"main": 0, "mentions": 0, "disputes": 0, "absent": 0, "n": 0})
            per_model[m]["n"] += 1
            per_model[m][verdict] += 1
            counts[verdict] += 1
            q = str(v.get("quote") or "").strip().strip('"').strip("\u201c\u201d")[:200]
            if q and verdict != "absent" and len(quotes) < 4 and q not in [x["quote"] for x in quotes]:
                quotes.append({"model": m, "quote": q})
        n = len(answers)
        # Presence: how often AI raises the idea at all. Framing: how often it ranks it first.
        # Score rewards "main" fully, "mentions" partly, and subtracts for "disputes".
        raw_score = (counts["main"] + 0.6 * counts["mentions"] - 0.5 * counts["disputes"]) / n if n else 0
        score = int(round(100 * max(0.0, min(1.0, raw_score))))
        presence = int(round(100 * (counts["main"] + counts["mentions"] + counts["disputes"]) / n)) if n else 0
        return {
            "hypothesis_id": hypothesis_id,
            "hypothesis": h,
            "classification_status": "valid",
            "classification_errors": [],
            "n_answers": n,
            "main": counts["main"],
            "mentions": counts["mentions"],
            "disputes": counts["disputes"],
            "absent": counts["absent"],
            "presence_pct": presence,
            "measured_score": score,
            "per_model": per_model,
            "quotes": quotes,
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(judge, measured_records))
    results.extend({
        **record, "n_answers": len(answers), "classification_status": "unassessed",
        "classification_errors": ["outside the five-hypothesis measurement limit"],
        "main": None, "mentions": None, "disputes": None, "absent": None,
        "presence_pct": None, "measured_score": None, "per_model": {}, "quotes": [],
    } for record in unassessed_records)
    out = {"hypotheses": results, "n_answers": len(answers),
           "models": query_data.get("models", []), "measurement_limit": 5}
    log_step("03b_convergence", out)
    return out


# Step 4: cluster the answers
def step_cluster(query_data):
    system = """You are an expert in discourse analysis, AI bias detection, and semiotics.
Analyse these AI responses across base queries and persona variants.
Identify dominant assumption themes across ALL responses.
Return ONLY valid JSON with this exact structure:
{
  "dominant_assumptions": [
    {
      "theme": "short name for assumption",
      "frequency": "X/N, where X is how many of the N responses reflect this (e.g. 14/20)",
      "frequency_count": 0,
      "description": "what AI assumes here in one sentence",
      "example_quote": "a short illustrative phrase from the responses"
    }
  ],
  "dominant_perspective": "one sentence: whose worldview dominates these responses",
  "geographic_bias": "one sentence: any geographic or cultural slant detected",
  "language_register": "one sentence: what level of literacy/expertise does AI assume in the reader",
  "persona_divergence": "one sentence: how much do responses change across personas - high/medium/low with explanation"
}"""

    all_responses = ""
    for r in query_data["base_responses"]:
        all_responses += f"\nPROMPT: {r['prompt']}\nRESPONSE: {r['response']}\n---"
    for r in query_data["persona_responses"]:
        all_responses += f"\nPERSONA: {r['persona']}\nPROMPT: {r['prompt']}\nRESPONSE: {r['response']}\n---"

    n_responses = len(query_data.get("base_responses", [])) + len(query_data.get("persona_responses", []))
    result = call_json("04_cluster", system.replace("X/N", f"X/{n_responses}"),
                       f"Analyse these {n_responses} AI responses:\n{all_responses}",
                       required_keys=("dominant_assumptions", "dominant_perspective"))
    for item in result.get("dominant_assumptions", []) or []:
        freq = str(item.get("frequency", ""))
        item["frequency"] = freq.split(",")[0].split(" where")[0].strip() or freq
    return result


# Step 5: gap analysis and sample fit
def step_gap_analysis(parsed, clusters):
    system = """You are a senior market research strategist with deep expertise in research design.
Compare what AI assumes about a topic versus what the actual research audience needs.
Also check sample fit: compare who will actually be recruited, and where, against each
client hypothesis and the stated geography. List a hypothesis in sample_cannot_test ONLY
when the sample excludes the people it is about by definition (hypothesis about older users,
sample aged 25 to 40; hypothesis about drop-off, sample of existing customers) or when the
fieldwork for the relevant method covers only part of the stated geography (interviews in
the UK only for a UK and Italy study). A sample that is merely skewed or likely biased
("may over-represent premium buyers") belongs in audience_mismatch, not here. Leave the
list empty if the sample fits.
Return ONLY valid JSON with this exact structure:
{
  "overrepresented": [
    {"perspective": "name", "explanation": "why this is over-emphasised by AI"}
  ],
  "underrepresented": [
    {"perspective": "name", "explanation": "what AI misses or ignores"}
  ],
  "audience_mismatch": "one paragraph on how AI worldview differs from the target audience reality",
  "sample_cannot_test": [
    {"hypothesis": "a client hypothesis the stated sample or fieldwork location cannot speak to", "why": "one sentence, e.g. the sample excludes the people the hypothesis is about, or fieldwork is in one country of two"}
  ],
  "risk_to_research": "one paragraph on what bad research design decisions could follow from accepting AI assumptions",
  "unknown_unknowns": [
    "Question AI and the brief both missed but that likely matters to the target audience",
    "Another such question",
    "A third such question"
  ]
}"""

    ux_gap_note = ""
    if mode_note(parsed):
        ux_gap_note = ("\nFor this UX brief, check specifically for blind spots on: device and connectivity, "
                       "accessibility and assistive technology, context of use (where, when, interrupted), "
                       "digital confidence, language and literacy, and existing mental models from rival products.")
    user = f"""{mode_note(parsed)}{ux_gap_note}
Product or service: {parsed.get('product_or_service', '')}
User task: {parsed.get('user_task', '')}
Research target audience: {parsed.get('target_audience', '')}
Who will actually be recruited: {parsed.get('sample_definition', 'Not specified')}
Where fieldwork happens: {parsed.get('fieldwork_locations', 'Not specified')}
Client hypotheses: {json.dumps(parsed.get('client_hypotheses', []))}
Research geography: {parsed.get('geography', '')}
Research objective: {parsed.get('research_objective', '')}

AI dominant assumptions: {json.dumps(clusters.get('dominant_assumptions', []))}
AI dominant perspective: {clusters.get('dominant_perspective', '')}
AI geographic bias: {clusters.get('geographic_bias', '')}
AI persona divergence: {clusters.get('persona_divergence', '')}

What are the critical gaps between AI worldview and research reality?"""

    return call_json("05_gaps", system, user, required_keys=('overrepresented', 'underrepresented', 'audience_mismatch', 'sample_cannot_test'))


# Step 8: temporal drift
def step_temporal_drift(parsed, clusters, archaeology=None):
    system = """You are an expert in AI training data analysis and market trend forecasting.
Assess how likely the AI's assumptions about this topic are to be temporally stale,
i.e. reflecting the world as it was 2-3 years ago rather than today.
You are given today's date and dated published sources where available. Use them.
Name specific events, regulations, market data or dates. Do not write generic sentences
about "rapid change" or "evolving markets". If you cannot name what changed, say the
risk is unknown rather than inventing it.
Return ONLY valid JSON with this exact structure:
{
  "overall_drift_risk": "Low / Medium / High",
  "drift_explanation": "one paragraph explaining why this topic is or isn't prone to AI temporal drift",
  "stale_assumptions": [
    {
      "assumption": "the AI assumption that may be outdated",
      "why_stale": "what has likely changed since AI training",
      "research_implication": "what to probe in fieldwork to get current reality"
    }
  ],
  "fast_moving_dimensions": ["list of sub-topics within this category that change fastest"],
  "recommendation": "one actionable sentence for the researcher"
}"""

    user = f"""
Category: {parsed.get('category', '')}
Geography: {parsed.get('geography', '')}
AI dominant assumptions: {json.dumps(clusters.get('dominant_assumptions', []))}
AI dominant perspective: {clusters.get('dominant_perspective', '')}
Today's date: {time.strftime('%d %B %Y')}
Dated published evidence found for this brief:{_evidence_digest(archaeology)}

Assess temporal drift risk for these AI assumptions."""

    return call_json("06_drift", system, user, required_keys=('overall_drift_risk', 'drift_explanation'))


# Step 6: hypothesis contamination
def step_hypothesis_contamination(parsed, clusters, query_data=None, convergence=None):
    system = """You are an expert in research epistemology and AI-generated content analysis.
Assess whether the client's stated hypotheses are genuinely original insights
or whether they are simply reflecting AI consensus - i.e. things the client
learned from AI-generated content rather than real market intelligence.

Scoring rubric. Use it and cite it:
  0-25  Low: AI rarely raises this idea, or disputes it. Say the client may have brought something
        new, but check the prompts first: if none of them gave AI a reason to raise the topic, say
        that absence is weak evidence of originality rather than proof of it.
 26-50  Medium: AI mentions the idea as one factor among several but does not rank it first.
 51-75  High: AI often presents the idea as the main cause or key driver.
 76-100 Critical: AI presents the idea as the main cause or settled fact in most answers.

A measured count is supplied for each hypothesis: how many of the AI answers state
it, hedge it, or omit it, and a score computed from that count. Use the measured score
as the contamination_score. Your job is to explain it, quote the answers, and advise.
If a hypothesis is marked INSUFFICIENT DATA, do not invent or infer a score.
Assess the hypotheses in the order given. overall_contamination_level is the band of the
HIGHEST measured score (0-25 Low, 26-50 Medium, 51-75 High, 76-100 Critical), and
overall_explanation must not name a different level.
Return ONLY valid JSON with this exact structure:
{
  "hypotheses_assessed": [
    {
      "hypothesis": "the client's stated hypothesis",
      "hypothesis_id": "copy the supplied stable hypothesis_id exactly",
      "contamination_score": 0,
      "score_label": "Low / Medium / High / Critical",
      "explanation": "why this hypothesis does or doesn't match AI consensus, naming the rubric band",
      "evidence_quotes": ["two to four short verbatim phrases from the AI responses that support the score"],
      "responses_matching": "X/10 responses state this idea",
      "recommendation": "how to treat this hypothesis in research design"
    }
  ],
  "overall_contamination_level": "Low / Medium / High / Critical",
  "overall_explanation": "one paragraph summarising the contamination picture",
  "genuinely_original_hypotheses": ["any hypotheses that appear NOT to be AI-derived"],
  "most_dangerous_assumption": "the single hypothesis most likely to corrupt research findings if left unchallenged"
}"""

    hypothesis_records = _hypothesis_records(parsed)
    if not hypothesis_records:
        hypothesis_records = _hypothesis_records({
            "client_hypotheses": ["No explicit hypotheses stated - inferred from brief language"]
        })

    evidence = ""
    if query_data:
        n = 0
        for r in query_data.get("base_responses", []) + query_data.get("persona_responses", []):
            n += 1
            evidence += f"\n[Response {n}] PROMPT: {r.get('prompt','')}\nANSWER: {r.get('response','')[:1500]}\n"

    measured_block = ""
    conv_list = (convergence or {}).get("hypotheses", [])
    for c in conv_list:
        if c.get("classification_status") == "unassessed":
            measured_block += f"\n- {c['hypothesis_id']} {c['hypothesis']}: UNASSESSED; outside the five-hypothesis measurement limit"
            continue
        if c.get("classification_status") != "valid":
            measured_block += f"\n- {c['hypothesis_id']} {c['hypothesis']}: INSUFFICIENT DATA; classification contract failed"
            continue
        measured_block += (
            f"\n- {c['hypothesis_id']} {c['hypothesis']}: presented as main cause in {c['main']}/{c['n_answers']} answers, "
            f"mentioned as one factor in {c['mentions']}/{c['n_answers']}, disputed in {c['disputes']}/{c['n_answers']}, "
            f"absent in {c['absent']}/{c['n_answers']}; measured score {c['measured_score']}/100; "
            f"by model: {json.dumps(c['per_model'])}"
        )

    user = f"""
Client hypotheses (return every hypothesis_id exactly once): {json.dumps(hypothesis_records)}
Research category: {parsed.get('category', '')}
Measured convergence across {len(conv_list) and conv_list[0]['n_answers']} AI answers from models {json.dumps((convergence or {}).get('models', []))}:{measured_block or ' none measured'}
AI dominant assumptions for this category: {json.dumps(clusters.get('dominant_assumptions', []))}
AI dominant perspective: {clusters.get('dominant_perspective', '')}

The AI responses (these are your only evidence):
{evidence}

Score each hypothesis for AI contamination using the rubric (0=completely original, 100=pure AI consensus)."""

    result = call_json("07_contamination", system, user, required_keys=('hypotheses_assessed', 'overall_contamination_level'))

    def band(score):
        if score <= 25: return "Low"
        if score <= 50: return "Medium"
        if score <= 75: return "High"
        return "Critical"

    # Join explanations to measurements only by stable ID. Never attach by list position.
    raw_assessed = result.get("hypotheses_assessed", [])
    expected_ids = {item["hypothesis_id"] for item in hypothesis_records}
    explanation_by_id = {}
    explanation_errors = []
    for item in raw_assessed if isinstance(raw_assessed, list) else []:
        hypothesis_id = str(item.get("hypothesis_id") or "") if isinstance(item, dict) else ""
        if hypothesis_id not in expected_ids:
            explanation_errors.append(f"unknown hypothesis_id {hypothesis_id!r}")
        elif hypothesis_id in explanation_by_id:
            explanation_errors.append(f"duplicate hypothesis_id {hypothesis_id}")
        else:
            explanation_by_id[hypothesis_id] = item
    convergence_by_id = {item.get("hypothesis_id"): item for item in conv_list}
    assessed = []
    for record in hypothesis_records:
        hypothesis_id = record["hypothesis_id"]
        measured = convergence_by_id.get(hypothesis_id)
        h = explanation_by_id.get(hypothesis_id, {
            "hypothesis_id": hypothesis_id,
            "hypothesis": record["hypothesis"],
            "explanation": "Explanation unavailable; human review is required.",
            "evidence_quotes": [],
            "recommendation": "Do not use this indicator until the missing analysis is rerun.",
        })
        if hypothesis_id not in explanation_by_id:
            explanation_errors.append(f"missing explanation for {hypothesis_id}")
        h["hypothesis_id"] = hypothesis_id
        h["hypothesis"] = record["hypothesis"]
        if measured and measured.get("classification_status") == "valid":
            h["contamination_score"] = measured["measured_score"]
            h["measured"] = True
            h["classification_status"] = "valid"
            h["responses_matching"] = (
                f"Main cause in {measured['main']} of {measured['n_answers']} answers, "
                f"one factor in {measured['mentions']}, disputed in {measured['disputes']}, "
                f"absent in {measured['absent']}"
            )
            h["presence_pct"] = measured["presence_pct"]
            h["per_model"] = measured["per_model"]
            if not h.get("evidence_quotes") and measured.get("quotes"):
                h["evidence_quotes"] = [q["quote"] for q in measured["quotes"]]
        else:
            h["contamination_score"] = None
            h["measured"] = False
            if measured and measured.get("classification_status") == "unassessed":
                h["classification_status"] = "unassessed"
                h["responses_matching"] = "Unassessed: outside the five-hypothesis measurement limit."
            else:
                h["classification_status"] = "insufficient_data"
                h["responses_matching"] = "Insufficient data: not every answer received exactly one valid classification."
        h["evidence_quotes"] = [str(q).strip().strip('"').strip("\u201c\u201d") for q in h.get("evidence_quotes", [])]
        if h["contamination_score"] is not None:
            h["score_label"] = band(h["contamination_score"])
        elif h["classification_status"] == "unassessed":
            h["score_label"] = "Unassessed"
        else:
            h["score_label"] = "Insufficient data"
        assessed.append(h)
    valid_scores = [h["contamination_score"] for h in assessed if h["contamination_score"] is not None]
    result["hypotheses_assessed"] = assessed
    result["explanation_contract_errors"] = explanation_errors
    result["overall_contamination_level"] = band(max(valid_scores)) if valid_scores else "Insufficient data"
    return result


# Step 9: competitor intelligence
def step_competitor_intelligence(query_data, parsed):
    system = """You are an expert in brand intelligence and competitive analysis.
Analyse these AI responses and identify which brands, products, companies,
or solutions appear organically - without being prompted.
These are the brands that dominate AI's answers about this category,
which means participants have likely already been exposed to them
before they reach your focus group or survey.
Return ONLY valid JSON with this exact structure:
{
  "brands_mentioned": [
    {
      "brand": "brand or product name",
      "frequency": "how many responses mention it",
      "framing": "how AI frames this brand (positive/neutral/negative/as default)",
      "priming_risk": "Low / Medium / High - risk that respondents are pre-primed"
    }
  ],
  "category_leader_in_ai": "which brand or type of solution AI positions as default/best",
  "invisible_competitors": "one sentence on what types of solutions AI never mentions",
  "discussion_guide_implication": "one actionable paragraph on how to handle competitive priming in fieldwork"
}"""

    all_text = "\n---\n".join([
        f"PROMPT: {r['prompt']}\nRESPONSE: {r['response']}"
        for r in query_data["base_responses"] + query_data["persona_responses"]
    ])

    user = f"""Category: {parsed.get('category', '')}
Geography: {parsed.get('geography', '')}

Analyse these AI responses for organic brand/competitor mentions:
{all_text}"""

    return call_json("08_competitors", system, user, required_keys=('brands_mentioned',))


# Step 7: assumption archaeology (web grounded)
def _evidence_text(he, limit=1600):
    """Flatten one hypothesis-evidence record into prompt text."""
    lines = []
    for c in he.get("countries", []):
        lines.append(f"{c.get('country','')}: {c.get('verdict','')}")
        for f in c.get("for", []):
            lines.append(f"  FOR: {f.get('finding','')} ({f.get('source','')}, {f.get('year','')})")
        for f in c.get("against", []):
            lines.append(f"  AGAINST: {f.get('finding','')} ({f.get('source','')}, {f.get('year','')})")
    return "\n".join(lines)[:limit]


def _evidence_digest(archaeology):
    out = ""
    for he in (archaeology or {}).get("hypothesis_evidence", []):
        if he.get("grounded"):
            out += f"\n\nHYPOTHESIS: {he['hypothesis']}\nVERDICT: {he.get('verdict','')}\n{he.get('summary','')}\n{_evidence_text(he, 1200)}"
    return out or "\nNo grounded evidence available."


def step_assumption_archaeology(parsed, clusters, gaps, quick=False):
    # First, ground the analysis in real cited web sources via OpenAI web search.
    category = parsed.get('category', 'this topic')
    geography = parsed.get('geography', 'Global')
    retrieval_query = (
        f"What types of sources, reports, publications and institutional voices "
        f"shape how the topic of '{category}' is discussed and understood, "
        f"particularly in {geography}? Identify dominant industry, media and "
        f"academic sources and whose perspective they represent."
    )

    # Ground each client hypothesis separately: evidence for and against, per country.
    hypotheses = [h for h in parsed.get("client_hypotheses", []) if str(h).strip()][:3]
    audience = parsed.get("target_audience", "the target audience")

    def ground_hypothesis(h):
        return web_grounding.retrieve_hypothesis_evidence(h, audience, geography)

    # Run the category search and every hypothesis search at the same time.
    hypothesis_evidence = []
    iq = {"grounded": False, "answer": "", "citations": []}
    if not quick:
        with ThreadPoolExecutor(max_workers=4) as pool:
            category_future = pool.submit(web_grounding.retrieve, retrieval_query)
            if hypotheses:
                hypothesis_evidence = list(pool.map(ground_hypothesis, hypotheses))
            try:
                iq = category_future.result()
            except Exception as e:
                log.warning("category grounding failed: %s", e)
    log_step("09a_hypothesis_grounding", hypothesis_evidence)

    grounding_block = ""
    for he in hypothesis_evidence:
        if he["grounded"]:
            grounding_block += f"\n\nEVIDENCE ON HYPOTHESIS: {he['hypothesis']} (verdict: {he['verdict']})\n{he['summary']}\n"
            grounding_block += _evidence_text(he)
    if iq.get("grounded"):
        cite_lines = []
        for c in iq.get("citations", [])[:8]:
            cite_lines.append(f"- {c.get('title','Source')} ({c.get('url','')}): {c.get('snippet','')}")
        grounding_block = (
            "\n\nGROUNDED EVIDENCE FROM WEB SEARCH (real web sources, use these to "
            "anchor your analysis and reference the source types you actually see):\n"
            + (iq.get("answer", "") or "")
            + "\n\nCited sources:\n" + "\n".join(cite_lines)
        )

    system = """You are an expert in the sociology of knowledge, media studies, and source analysis.
Work out which kinds of sources shaped how AI and the wider information landscape
understand this topic. Where grounded evidence from real web sources is provided,
base your source landscape on what those sources actually show.
Return ONLY valid JSON with this exact structure:
{
  "source_landscape": [
    {
      "source_type": "type of source (e.g. Western industry reports, mainstream news, academic papers)",
      "influence_level": "Dominant / Significant / Marginal / Absent",
      "what_it_contributes": "what assumptions or framings this source type introduces",
      "whose_voice": "whose perspective or interest this source type typically represents"
    }
  ],
  "absent_voices": [
    "type of source or perspective absent from the dominant understanding of this topic"
  ],
  "dominant_narrative_origin": "one paragraph: the single most influential source type and why it dominates",
  "implication_for_research": "one paragraph: what this means for how you design and interpret your research",
  "decolonisation_note": "one sentence: if applicable, how Western or Anglo-centric the framing of this topic is",
  "grounded": false,
  "sources": []
}"""

    user = f"""
Category: {parsed.get('category', '')}
Geography: {parsed.get('geography', '')}
Target audience: {parsed.get('target_audience', '')}
AI dominant assumptions: {json.dumps(clusters.get('dominant_assumptions', []))}
AI dominant perspective: {clusters.get('dominant_perspective', '')}
Underrepresented perspectives: {json.dumps(gaps.get('underrepresented', []))}
{grounding_block}

Trace where the assumptions about this topic come from."""

    result = call_json("09_archaeology", system, user, required_keys=('source_landscape', 'dominant_narrative_origin'))

    # Attach the real web-search provenance so the UI can show citations.
    result["grounded"] = bool(iq.get("grounded")) or any(h["grounded"] for h in hypothesis_evidence)
    result["sources"] = iq.get("citations", []) if iq.get("grounded") else []
    result["hypothesis_evidence"] = hypothesis_evidence
    return result




# Step 10: methodology routing
def step_qual_quant_routing(parsed, gaps, temporal_drift, archaeology=None, contamination=None):
    system = """You are a senior research methodology director with 20 years of experience
in both qualitative and quantitative research design.
Based on the nature of the gaps identified, recommend the optimal methodology mix.

Specificity rule. A recommendation that would fit an unrelated brief is worthless here.
Every method, sample note and rationale must name at least one of: a specific country in the
geography, a specific trait of the stated audience, or a specific client hypothesis. Use the
grounded country evidence you are given. Do not write "mixed methods", "stratify by age and
country" or similar unless you say exactly why for THIS brief. Before you answer, list the
generic recommendations you considered and rejected in "rejected_as_generic".

For UX briefs, route to UX methods: moderated or unmoderated usability testing, diary studies,
contextual inquiry, card sorting or tree testing, accessibility audits with assistive technology
users, task-based surveys, analytics review. Name the task and the device.
Respect the brief. Start from the method the brief stated. Keep it unless the gaps or the
published evidence give a concrete reason to adjust or change it, and if you do, say what it
costs the client in scope, time or money.
Return ONLY valid JSON with this exact structure:
{
  "method_fit": {
    "stated_method": "the method the brief specified, or 'Not specified'",
    "decision": "keep | adjust | change",
    "reason": "two sentences: why the stated method does or does not fit what the evidence and gaps show",
    "scope_and_cost_note": "one sentence on how the decision changes scope, timing or cost compared with the brief"
  },
  "recommended_approach": "one sentence naming the approach for THIS brief and the reason. Do not start with 'Mixed Methods'.",
  "methodology_breakdown": [
    {
      "dimension": "the research dimension or question",
      "recommended_method": "specific method (e.g. in-depth interviews, laddering, projective techniques, conjoint, segmentation survey)",
      "rationale": "why this method for this dimension",
      "ai_bias_risk": "how AI assumptions could corrupt this dimension if wrong method chosen"
    }
  ],
  "critical_qual_dimensions": ["dimensions that CANNOT be captured by survey - require qual"],
  "projective_techniques_needed": true,
  "projective_rationale": "why or why not projective techniques are needed",
  "sample_design_notes": "one paragraph on sample composition to counteract AI perspective bias, naming countries and audience traits",
  "stimulus_material_warning": "one sentence on any stimulus materials that may carry AI-contaminated framing",
  "hypothesis_tests": [
    {
      "hypothesis": "a client hypothesis",
      "how_to_test_it": "the specific method and question design that would confirm or refute it",
      "what_would_refute_it": "the finding that should make the client drop it"
    }
  ],
  "rejected_as_generic": ["recommendations you considered and rejected because they fit any brief"]
}"""

    evidence_block = _evidence_digest(archaeology)
    scores_block = ""
    for h in (contamination or {}).get("hypotheses_assessed", []):
        scores_block += f"\n- {h.get('hypothesis','')}: contamination {h.get('contamination_score','?')}/100 ({h.get('score_label','')})"

    user = f"""{mode_note(parsed)}
Product or service: {parsed.get('product_or_service', '')}
User task: {parsed.get('user_task', '')}
Client hypotheses: {json.dumps(parsed.get('client_hypotheses', []))}
Who the brief recruits: {parsed.get('sample_definition', 'Not specified')}. Where: {parsed.get('fieldwork_locations', 'Not specified')}.
Hypotheses the stated sample cannot test: {json.dumps((gaps or {}).get('sample_cannot_test', []))}
Contamination scores:{scores_block or ' none'}
Grounded evidence per hypothesis:{evidence_block or ' none available'}

Research objective: {parsed.get('research_objective', '')}
Target audience: {parsed.get('target_audience', '')}
Geography: {parsed.get('geography', '')}
Methodology hints from brief: {parsed.get('methodology_hints', 'Not specified')}

Underrepresented perspectives: {json.dumps(gaps.get('underrepresented', []))}
Unknown unknowns: {json.dumps(gaps.get('unknown_unknowns', []))}
Audience mismatch: {gaps.get('audience_mismatch', '')}
Temporal drift risk: {temporal_drift.get('overall_drift_risk', 'Unknown')}

Recommend the methodology mix most likely to surface findings AI would not have predicted."""

    return call_json("10_methodology", system, user, required_keys=('recommended_approach', 'method_fit'))


# Step 11: confidence synthesis
def step_confidence(parsed, clusters, gaps, temporal_drift, contamination, methodology, archaeology=None):
    """Final synthesis: a single research-design confidence score with reasoning."""
    system = """You are the lead reviewer signing off on a research design.
Based on all the analysis, produce a single Research Design Confidence Score (0-100):
how likely is this research, as currently framed, to tell the client something new
rather than confirm what AI would already have said?
Score the design AS THE BRIEF STATES IT: its stated method, sample and fieldwork locations.
Do not credit the client for methods that BRIEF recommended in the methodology step; those are
proposals, not the design. If the stated sample or fieldwork location cannot test a client
hypothesis (see sample_cannot_test), that is a top risk and caps the score at 50.
You have the measured AI consensus and the published evidence for each hypothesis. The
report's front page shows what you write here, so put the most important evidence-based
finding in key_finding and make every risk specific to this brief. Generic risks such as
"temporal drift" or "insufficient nuance" are not acceptable unless you name what changed
or what nuance is missing. Never mention internal field names such as sample_cannot_test;
write for a researcher who has not seen this system.
Lower scores mean the brief is heavily contaminated and needs rework before fieldwork.
Higher scores mean the design is well-positioned to discover real insight.
Return ONLY valid JSON with this exact structure:
{
  "confidence_score": 0,
  "confidence_label": "Strong (75+) / Adequate (55-74) / Fragile (40-54) / Compromised (below 40); must match the score",
  "headline": "one plain, direct sentence a researcher could say to their client",
  "key_finding": {
    "statement": "the single most important evidence-based finding for this client, one or two sentences. It must contain a specific figure, a named source, or a concrete country contrast. Phrases like 'vary notably' or 'nuanced' without a specific are not acceptable",
    "basis": "measured AI consensus | published evidence | both",
    "sources": ["publisher and title of up to three sources that support it"]
  },
  "score_rationale": "one short paragraph explaining the score",
  "top_three_risks": [
    "the single most important thing to fix before fieldwork, citing a measured count or a published source where one exists",
    "the second",
    "the third"
  ],
  "what_would_raise_it": "one sentence on what change would most improve the score"
}"""

    user = f"""
Research objective: {parsed.get('research_objective', '')}
Target audience: {parsed.get('target_audience', '')}

Overall hypothesis contamination: {contamination.get('overall_contamination_level', 'Unknown')}
Most dangerous assumption: {contamination.get('most_dangerous_assumption', 'None identified')}
Temporal drift risk: {temporal_drift.get('overall_drift_risk', 'Unknown')}
Audience mismatch: {gaps.get('audience_mismatch', '')}
Number of blind spots found: {len(gaps.get('underrepresented', []))}
The design as the brief states it. Method: {parsed.get('methodology_hints', 'Not specified')}. Sample: {parsed.get('sample_definition', 'Not specified')}. Fieldwork: {parsed.get('fieldwork_locations', 'Not specified')}.
Sample cannot test: {json.dumps(gaps.get('sample_cannot_test', []))}
BRIEF's own recommendation (do not credit the client for this): {methodology.get('recommended_approach', '')}
Method fit with the brief: {json.dumps(methodology.get('method_fit', {}))}

Measured AI consensus per hypothesis:{_lines(f"- {h.get('hypothesis','')}: {h.get('contamination_score','?')}/100, {h.get('responses_matching','')}" for h in contamination.get('hypotheses_assessed', [])) or ' none'}

Published evidence per hypothesis:{_evidence_digest(archaeology)}

Score this research design's confidence (0=will only confirm what AI assumes, 100=well-positioned to find something new)."""

    result = call_json("11_confidence", system, user, required_keys=('confidence_score', 'confidence_label', 'headline', 'top_three_risks'))
    try:
        result["confidence_score"] = int(result.get("confidence_score", 50))
    except (TypeError, ValueError):
        result["confidence_score"] = 50
    if gaps.get("sample_cannot_test") and result["confidence_score"] > 50:
        result["confidence_score"] = 50
        result["score_capped"] = "Capped at 50: the stated sample or fieldwork cannot test at least one client hypothesis."
    result["confidence_label"] = confidence_label(result["confidence_score"])
    return result


def confidence_label(score: int) -> str:
    """One rule for the label, so the number and the word never disagree."""
    if score >= 75:
        return "Strong"
    if score >= 55:
        return "Adequate"
    if score >= 40:
        return "Fragile"
    return "Compromised"


# Step 12: paste-ready deliverables
def step_deliverables(parsed, confidence, contamination, gaps, archaeology, methodology):
    """
    Turn the diagnosis into three things a researcher can paste into real work:
    a client-facing challenge note, discussion guide probes per hypothesis, and
    screener criteria that counter the audience mismatch.
    """
    is_ux = bool(mode_note(parsed))
    system = """You are a senior research director writing material a researcher will paste
straight into a proposal, a discussion guide and a screener. Write in plain British English.
No headings inside the text fields. No first person. No praise for the client. Every sentence
must be specific to this brief: name the countries, the audience, the hypotheses and the
evidence. Anything that would fit an unrelated brief must be cut.
Return ONLY valid JSON with this exact structure:
{
  "challenge_note": {
    "title": "short title for a one-page note to the client. Sentence case: capital letter on the first word and on proper nouns (UK, Italy, Mexico), lower case elsewhere",
    "opening": "two sentences a researcher could say to the client about what the brief assumes",
    "what_we_found": "one paragraph, four to six sentences, stating the key finding and the measured AI consensus, citing the published sources by name",
    "what_we_recommend": "one paragraph on how the research should change before fieldwork, tied to the method decision",
    "closing": "one sentence that frames this as protecting the client's investment"
  },
  "discussion_guide_probes": [
    {
      "hypothesis": "the client hypothesis this tests",
      "warm_up": "one open question that lets the respondent raise the topic unprompted",
      "probes": ["four to six follow-up probes written to test the hypothesis, not confirm it, in the words a moderator would say"],
      "avoid": "the leading question itself, in quotes, without 'do not ask' or 'avoid' in front of it"
    }
  ],
  "screener_criteria": [
    {"criterion": "a recruitment criterion", "why": "which blind spot or mismatch it counters", "quota_note": "suggested split or minimum, if any"}
  ],
  "task_scenarios": [
    {"task": "for UX briefs only: a realistic task for a usability session", "success_measure": "how you know it worked", "hypothesis_tested": "which client belief it tests"}
  ]
}"""
    if is_ux:
        system += UX_MODE_NOTE + ("\nFill task_scenarios with three to five tasks. Each task is a goal in the participant's own "
                                  "terms and must NOT name the feature, button or path (write 'sign in the fastest way you can', "
                                  "not 'set up biometric login'). A task is something the participant does, not a question you ask. "
                                  "Probes should be usability probes asked during or after a task.")
    else:
        system += "\nLeave task_scenarios as an empty list."

    key = (confidence or {}).get("key_finding", {}) or {}
    user = f"""
Category: {parsed.get('category', '')}
Product or service: {parsed.get('product_or_service', '')}
Audience: {parsed.get('target_audience', '')}
Geography: {parsed.get('geography', '')}
Stated method: {parsed.get('methodology_hints', '')}
Client hypotheses: {json.dumps(parsed.get('client_hypotheses', []))}

Key finding: {key.get('statement', '')} (sources: {'; '.join(key.get('sources', []) or [])})
Top risks: {json.dumps((confidence or {}).get('top_three_risks', []))}
Measured AI consensus:{_lines(f"- {h.get('hypothesis','')}: {h.get('contamination_score','?')}/100, {h.get('responses_matching','')}" for h in (contamination or {}).get('hypotheses_assessed', [])) or ' none'}
Audience mismatch: {(gaps or {}).get('audience_mismatch', '')}
Who the brief recruits: {parsed.get('sample_definition', 'Not specified')}. Where: {parsed.get('fieldwork_locations', 'Not specified')}.
Hypotheses the stated sample cannot test (the screener must fix this): {json.dumps((gaps or {}).get('sample_cannot_test', []))}
Under-represented perspectives: {json.dumps([g.get('perspective','') for g in (gaps or {}).get('underrepresented', [])])}
Unknown unknowns: {json.dumps((gaps or {}).get('unknown_unknowns', []))}
Method decision: {json.dumps((methodology or {}).get('method_fit', {}))}
Recommended approach: {(methodology or {}).get('recommended_approach', '')}
Published evidence:{_evidence_digest(archaeology)}

Write the three deliverables."""
    result = call_json("12_deliverables", system, user,
                       required_keys=("challenge_note", "discussion_guide_probes", "screener_criteria"))
    note = result.get("challenge_note") or {}
    title = str(note.get("title", "")).strip()
    if title:
        note["title"] = title[0].upper() + title[1:]
    return result


# Pipeline
def _safe_step(fn: Callable[..., Any], fallback: Any, *args: Any, **kwargs: Any) -> Any:
    """Run one agent; on failure log it, record it in the fallback, and carry on."""
    try:
        result = fn(*args, **kwargs)
        if result is None:
            return fallback
        return result
    except Exception as e:
        name = getattr(fn, "__name__", repr(fn))
        log.warning("%s failed: %s: %s", name, type(e).__name__, e)
        log_step(f"error_{name}", {"error": f"{type(e).__name__}: {e}"})
        fb = dict(fallback) if isinstance(fallback, dict) else fallback
        if isinstance(fb, dict):
            fb["_error"] = str(e)
        return fb


def parse_brief(brief: str, mode: str = "market") -> Parsed:
    """Step 1 on its own, so the UI can show the extracted hypotheses for review."""
    start_run_log()
    return _safe_step(step_parse, {
        "core_question": "Could not parse", "category": "Unknown",
        "target_audience": "Unknown", "geography": "Global",
        "research_objective": "Unknown", "client_hypotheses": [],
        "methodology_hints": "Not specified", "product_or_service": "", "user_task": "",
        "research_mode": "ux" if str(mode).lower() == "ux" else "market"
    }, brief, mode)


def run_brief(
    brief: str,
    progress_callback: ProgressCallback | None = None,
    parsed_override: Parsed | None = None,
    mode: str = "market",
    quick: bool = False,
) -> dict[str, Any]:
    """
    Run the full BRIEF pipeline with per-step error recovery.
    progress_callback(step_name, step_number, total_steps) called at each step.
    parsed_override: a parsed brief the user has reviewed and edited; skips step 1.
    quick: one probe model and no web grounding. One to two minutes instead of five to seven.
    Returns a dict of all results plus a confidence synthesis.
    """
    total = 12
    start_run_log()
    probe_models = PROBE_MODELS[:1] if quick else PROBE_MODELS

    def progress(name, n):
        if progress_callback:
            progress_callback(name, n, total)

    progress("Reading your brief", 1)
    if isinstance(parsed_override, dict) and parsed_override.get("category"):
        parsed = dict(parsed_override)
        parsed["client_hypotheses"] = [str(h).strip() for h in parsed.get("client_hypotheses", []) if str(h).strip()]
        parsed["research_mode"] = "ux" if str(parsed.get("research_mode", mode)).lower() == "ux" else "market"
        log_step("01_parse", {"result": parsed, "source": "user-reviewed"})
    else:
        parsed = parse_brief(brief, mode)
    parsed = _attach_hypothesis_ids(parsed)

    progress("Working out how people actually ask about this", 2)
    prompts = _safe_step(step_generate, [], parsed)
    if not isinstance(prompts, list):
        prompts = []
    prompts = [str(p).strip() for p in prompts if str(p).strip()][:6]
    if not prompts:
        prompts = [parsed.get("core_question", "Tell me about this topic")]

    progress("Asking AI the same question 10 different ways", 3)
    query_data = _safe_step(step_query, {"base_responses": [], "persona_responses": []}, prompts, parsed, probe_models)
    log_step("03_query", query_data)
    convergence = _safe_step(step_convergence, {"hypotheses": [], "n_answers": 0, "models": []}, parsed, query_data)

    progress("Finding the patterns in what AI says", 4)
    clusters = _safe_step(step_cluster, {
        "dominant_assumptions": [], "dominant_perspective": "Analysis unavailable",
        "geographic_bias": "Unknown", "language_register": "Unknown",
        "persona_divergence": "Unknown"
    }, query_data)

    progress("Comparing AI's picture to your actual audience", 5)
    gaps = _safe_step(step_gap_analysis, {
        "overrepresented": [], "underrepresented": [],
        "audience_mismatch": "Analysis unavailable", "risk_to_research": "",
        "unknown_unknowns": []
    }, parsed, clusters)

    progress("Scoring the client's assumptions against AI consensus", 6)
    contamination = _safe_step(step_hypothesis_contamination, {
        "hypotheses_assessed": [], "overall_contamination_level": "Unknown",
        "overall_explanation": "Analysis unavailable",
        "genuinely_original_hypotheses": [], "most_dangerous_assumption": ""
    }, parsed, clusters, query_data, convergence)

    progress("Tracing where AI's assumptions come from", 7)
    archaeology = _safe_step(step_assumption_archaeology, {
        "source_landscape": [], "absent_voices": [],
        "dominant_narrative_origin": "Analysis unavailable",
        "implication_for_research": "", "decolonisation_note": "",
        "grounded": False, "sources": []
    }, parsed, clusters, gaps, quick)

    progress("Checking how much of this is already out of date", 8)
    temporal_drift = _safe_step(step_temporal_drift, {
        "overall_drift_risk": "Unknown", "drift_explanation": "Analysis unavailable",
        "stale_assumptions": [], "fast_moving_dimensions": [], "recommendation": ""
    }, parsed, clusters, archaeology)

    progress("Identifying which brands AI puts in the room", 9)
    competitor_intel = _safe_step(step_competitor_intelligence, {
        "brands_mentioned": [], "category_leader_in_ai": "Analysis unavailable",
        "invisible_competitors": "", "discussion_guide_implication": ""
    }, query_data, parsed)

    progress("Working out how to actually research this properly", 10)
    methodology = _safe_step(step_qual_quant_routing, {
        "recommended_approach": "Analysis unavailable", "methodology_breakdown": [],
        "critical_qual_dimensions": [], "projective_techniques_needed": False,
        "projective_rationale": "", "sample_design_notes": "",
        "stimulus_material_warning": ""
    }, parsed, gaps, temporal_drift, archaeology, contamination)

    progress("Scoring overall research design confidence", 11)
    confidence = _safe_step(step_confidence, {
        "confidence_score": 50, "confidence_label": "Adequate",
        "headline": "Analysis complete.", "score_rationale": "",
        "top_three_risks": [], "what_would_raise_it": ""
    }, parsed, clusters, gaps, temporal_drift, contamination, methodology, archaeology)

    progress("Drafting the challenge note, probes and screener", 12)
    deliverables = _safe_step(step_deliverables, {
        "challenge_note": {}, "discussion_guide_probes": [], "screener_criteria": [], "task_scenarios": []
    }, parsed, confidence, contamination, gaps, archaeology, methodology)

    step_errors = []
    for name, obj in [("parse", parsed), ("query", query_data), ("convergence", convergence), ("clusters", clusters),
                      ("gaps", gaps), ("drift", temporal_drift), ("contamination", contamination),
                      ("competitors", competitor_intel), ("archaeology", archaeology), ("methodology", methodology),
                      ("confidence", confidence), ("deliverables", deliverables)]:
        if isinstance(obj, dict) and obj.get("_error"):
            step_errors.append({"step": name, "error": str(obj["_error"])[:300]})
    classification_failures = sum(
        1 for item in convergence.get("hypotheses", [])
        if item.get("classification_status") == "insufficient_data"
    )
    unassessed_hypotheses = sum(
        1 for item in convergence.get("hypotheses", [])
        if item.get("classification_status") == "unassessed"
    )
    explanation_contract_errors = contamination.get("explanation_contract_errors", [])
    run_health = {
        "status": "degraded" if step_errors or classification_failures or explanation_contract_errors else "complete",
        "prompt_version": config.PROMPT_VERSION,
        "quick_mode": bool(quick),
        "probe_models": probe_models,
        "answers_collected": len(query_data.get("base_responses", [])) + len(query_data.get("persona_responses", [])),
        "grounded": bool(archaeology.get("grounded")),
        "classification_failures": classification_failures,
        "unassessed_hypotheses": unassessed_hypotheses,
        "explanation_contract_errors": explanation_contract_errors,
        "step_errors": step_errors,
        "run_log_dir": current_run_dir(),
    }

    assurance = brief_assurance(
        run_health=run_health,
        convergence=convergence,
        archaeology=archaeology,
        confidence=confidence,
    )

    result = {
        "assurance": assurance,
        "run_health": run_health,
        "parsed": parsed,
        "prompts": prompts,
        "query_data": query_data,
        "convergence": convergence,
        "clusters": clusters,
        "gaps": gaps,
        "temporal_drift": temporal_drift,
        "contamination": contamination,
        "competitor_intel": competitor_intel,
        "archaeology": archaeology,
        "methodology": methodology,
        "confidence": confidence,
        "deliverables": deliverables,
    }
    contract_errors = validate_report(result)
    if contract_errors:
        run_health["status"] = "invalid"
        run_health["contract_errors"] = contract_errors
        assurance = brief_assurance(
            run_health=run_health,
            convergence=convergence,
            archaeology=archaeology,
            confidence=confidence,
        )
        assurance["assurance_level"] = "limited"
        result["assurance"] = assurance
    result["provenance"] = report_provenance(result)
    return result
