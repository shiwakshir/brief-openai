"""
Guide and questionnaire audit for BRIEF.

Takes a discussion guide, interview script, survey or usability test plan and
flags the questions that would confirm rather than test: leading wording,
presuppositions, double-barrelled items, loaded terms, priming order effects,
jargon, and questions that restate a client hypothesis. Optionally checks
coverage against the client hypotheses and blind spots from a brief.

Three model calls: parse the instrument, audit the items, assess coverage.
Under two minutes on a normal guide.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import config
from credibility import audit_assurance
from agent import UX_MODE_NOTE, parse_brief
from llm import call_json, log_step, start_run_log

log = logging.getLogger("brief.audit")

MAX_ITEMS_PER_CALL = 40


# Step A: parse the instrument
def parse_instrument(text, mode="market"):
    system = """You are a senior research methodologist reading a discussion guide, interview
script, survey questionnaire or usability test plan.
Extract every question, probe, task instruction or rating item, in document order.
Keep the researcher's exact wording. Ignore moderator notes, timings, logistics and
consent text unless they contain a question that will be asked.
Return ONLY valid JSON with this exact structure:
{
  "instrument_type": "discussion guide | interview script | survey | usability test plan | mixed",
  "sections": ["section names in order, or ['Main'] if none"],
  "items": [
    {
      "id": "Q1",
      "section": "section name",
      "text": "the question or task exactly as written",
      "kind": "open | closed | scale | task | probe | screener",
      "answer_options": ["for closed or scale items, the options as written; otherwise []"]
    }
  ]
}
Number ids Q1, Q2 ... in document order."""
    if str(mode).lower() == "ux":
        system += UX_MODE_NOTE
    return call_json("A_parse_instrument", system, f"Extract the items from this instrument:\n\n{text[:30000]}",
                     required_keys=("instrument_type", "items"))


# Step B: audit the items
AUDIT_SYSTEM = """You are a senior research methodologist auditing questions before fieldwork.
For each item, decide whether it will test or merely confirm. Flag only real problems.
A neutral, well-formed question gets an empty issues list. Do not invent issues to fill space.

Issue types, with the test for each:
- leading: the wording signals the expected answer ("How much do you value...", "Don't you think...")
- presupposition: the question assumes something not yet established ("Why do you struggle to save?")
- hypothesis_confirming: the item restates a client hypothesis and asks for agreement
- double_barrelled: two questions in one, or two concepts in one scale item. Any "and" that joins two things to rate or answer ("how helpful and easy to use", "how often ... and how ...") is double_barrelled
- loaded_terms: emotive, judgemental or brand-supplied words ("natural", "struggle", "premium", "hassle")
- priming: an earlier item, an intro line or answer options plant the frame this item then measures
- jargon_or_literacy: words the stated audience may not use or understand
- closed_too_early: a closed or scale item where the topic has not yet been explored openly
- unbalanced_scale: options or scale anchors that are not symmetric or omit "don't know / not applicable"
- social_desirability: invites the respectable answer rather than the real one
- task_leading: for usability tasks, the instruction names the feature or the path, so it cannot test findability

Severity:
- high: the answer will be unusable or will confirm the client's belief by construction
- medium: the answer will be biased in a known direction
- low: a wording improvement

Rewrites must keep the researcher's intent and register, be neutral, and be something a
moderator would actually say. For tasks, rewrite as a goal without naming the feature.
Return ONLY valid JSON with this exact structure:
{
  "items": [
    {
      "id": "Q1",
      "issues": [
        {"type": "leading", "severity": "high", "explanation": "one sentence naming the exact words that cause the problem"}
      ],
      "rewrite": "the neutral version, or '' if no issues",
      "tests_or_confirms": "tests | confirms | neutral | not applicable"
    }
  ]
}
Include every item id exactly once."""


def audit_items(items, context, mode="market"):
    system = AUDIT_SYSTEM + (UX_MODE_NOTE if str(mode).lower() == "ux" else "")
    chunks = [items[i:i + MAX_ITEMS_PER_CALL] for i in range(0, len(items), MAX_ITEMS_PER_CALL)] or [[]]

    def run(chunk):
        listing = "\n".join(
            f"{it['id']} [{it.get('section','')}] ({it.get('kind','')}): {it['text']}"
            + (f"  Options: {' / '.join(it['answer_options'])}" if it.get("answer_options") else "")
            for it in chunk
        )
        user = f"""{context}

Items to audit (in order, so you can judge priming):
{listing}"""
        return call_json("B_audit_items", system, user, required_keys=("items",), temperature=0).get("items", [])

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = [r for chunk in pool.map(run, chunks) for r in chunk]
    by_id = {str(r.get("id")): r for r in results if isinstance(r, dict)}
    return by_id


# Step C: coverage against the brief
def assess_coverage(items, parsed, audited, mode="market"):
    hypotheses = [h for h in (parsed or {}).get("client_hypotheses", []) if str(h).strip()]
    if not hypotheses:
        return {"hypotheses": [], "missing_questions": [], "note": "No brief or hypotheses supplied, so coverage was not assessed."}

    system = """You are a senior research methodologist checking whether an instrument can
actually test the client's hypotheses rather than confirm them.
For each hypothesis, list the item ids that bear on it and judge the coverage:
- tested: at least one item marked neutral or tests lets the respondent contradict it
- confirmed_only: items touch it but every one is marked confirms (leading, presupposing or hypothesis-confirming)
- untested: nothing in the instrument addresses it
An item marked confirms can never count towards "tested". Warm-up items that do not address the hypothesis do not count either.
Then propose the missing questions. Each must be neutral, in moderator language, and say
which hypothesis or blind spot it serves.
Return ONLY valid JSON with this exact structure:
{
  "hypotheses": [
    {"hypothesis": "...", "coverage": "tested | confirmed_only | untested", "item_ids": ["Q3", "Q7"], "note": "one sentence"}
  ],
  "missing_questions": [
    {"question": "...", "serves": "which hypothesis or audience gap", "place_after": "item id or 'start' or 'end'"}
  ]
}"""
    system += UX_MODE_NOTE if str(mode).lower() == "ux" else ""
    def verdict_for(it):
        a = audited.get(it["id"], {})
        types = [str(i.get("type", "")).lower() for i in a.get("issues", []) if isinstance(i, dict)]
        if any(t in types for t in ("hypothesis_confirming", "leading", "presupposition", "task_leading")):
            return "confirms (flagged: " + ", ".join(types) + ")"
        return a.get("tests_or_confirms", "") or "neutral"

    listing = "\n".join(f"{it['id']}: {it['text']}  -> {verdict_for(it)}" for it in items)
    user = f"""Client hypotheses: {json.dumps(hypotheses)}
Audience: {parsed.get('target_audience', '')}
Geography: {parsed.get('geography', '')}
Product or service: {parsed.get('product_or_service', '')}

Instrument items with the audit verdict for each:
{listing}"""
    return call_json("C_coverage", system, user, required_keys=("hypotheses", "missing_questions"))


# Orchestrator
def run_audit(instrument_text: str, brief_text: str = "", mode: str = "market", progress_callback=None) -> dict[str, Any]:
    total = 4

    def progress(name, n):
        if progress_callback:
            progress_callback(name, n, total)

    start_run_log()

    progress("Reading the guide or questionnaire", 1)
    parsed_instrument = parse_instrument(instrument_text, mode)
    items = []
    for i, it in enumerate(parsed_instrument.get("items", []), 1):
        if not isinstance(it, dict) or not str(it.get("text", "")).strip():
            continue
        it["id"] = str(it.get("id") or f"Q{i}")
        it["answer_options"] = [str(o) for o in (it.get("answer_options") or [])]
        items.append(it)

    progress("Reading the brief for hypotheses", 2)
    parsed_brief = {}
    if brief_text and len(brief_text.strip()) >= 50:
        try:
            parsed_brief = parse_brief(brief_text, mode)
        except Exception as e:
            log.warning("brief parse failed: %s", e)
            parsed_brief = {}

    context = f"RESEARCH MODE: {'UX' if str(mode).lower() == 'ux' else 'Market research'}."
    if parsed_brief:
        context += (
            f"\nClient hypotheses (an item that restates one of these and asks for agreement is hypothesis_confirming): "
            f"{json.dumps(parsed_brief.get('client_hypotheses', []))}"
            f"\nAudience: {parsed_brief.get('target_audience', '')}"
            f"\nGeography: {parsed_brief.get('geography', '')}"
        )
    else:
        context += "\nNo brief supplied. Judge the wording on its own."

    progress("Auditing every question", 3)
    audited = audit_items(items, context, mode) if items else {}

    progress("Checking coverage of the client hypotheses", 4)
    coverage = assess_coverage(items, parsed_brief, audited, mode) if items else {"hypotheses": [], "missing_questions": []}

    # Merge and score
    merged = []
    counts = {"high": 0, "medium": 0, "low": 0}
    confirms = 0
    for it in items:
        a = audited.get(it["id"], {})
        issues = [i for i in a.get("issues", []) if isinstance(i, dict) and i.get("type")]
        for i in issues:
            sev = str(i.get("severity", "low")).lower()
            counts[sev if sev in counts else "low"] += 1
        verdict = str(a.get("tests_or_confirms", "")).lower()
        if any(str(i.get("type", "")).lower() == "hypothesis_confirming" for i in issues):
            verdict = "confirms"
        if verdict == "confirms":
            confirms += 1
        merged.append({**it, "issues": issues, "rewrite": a.get("rewrite", "") or "", "tests_or_confirms": verdict})

    n = len(merged) or 1
    flagged = sum(1 for m in merged if m["issues"])
    # Score: start at 100, lose 12 per high, 5 per medium, 1 per low, scaled to instrument length
    penalty = (12 * counts["high"] + 5 * counts["medium"] + 1 * counts["low"]) * (10 / n if n < 10 else 1)
    score = int(max(0, min(100, round(100 - penalty))))
    label = "Sound" if score >= 80 else "Needs edits" if score >= 60 else "Rework before fieldwork"

    result = {
        "status": "complete",
        "prompt_version": config.PROMPT_VERSION,
        "instrument_type": parsed_instrument.get("instrument_type", ""),
        "sections": parsed_instrument.get("sections", []),
        "items": merged,
        "coverage": coverage,
        "brief": parsed_brief,
        "summary": {
            "score": score,
            "label": label,
            "items_total": len(merged),
            "items_flagged": flagged,
            "items_confirming": confirms,
            "high": counts["high"], "medium": counts["medium"], "low": counts["low"],
            "untested_hypotheses": [h.get("hypothesis") for h in coverage.get("hypotheses", []) if h.get("coverage") == "untested"],
            "confirmed_only_hypotheses": [h.get("hypothesis") for h in coverage.get("hypotheses", []) if h.get("coverage") == "confirmed_only"],
        },
    }
    result["assurance"] = audit_assurance(result, config.PROMPT_VERSION)
    log_step("D_audit_result", result)
    return result
