"""Deterministic assurance metadata for model-assisted research reviews."""

from __future__ import annotations
from typing import Any


def brief_assurance(
    *,
    run_health: dict[str, Any],
    convergence: dict[str, Any],
    archaeology: dict[str, Any],
    confidence: dict[str, Any],
) -> dict[str, Any]:
    limitations: list[str] = []
    if run_health.get("quick_mode"):
        limitations.append("Quick mode used one probe model and no public-web evidence.")
    if run_health.get("step_errors"):
        limitations.append("One or more analysis stages failed; downstream findings may be incomplete.")
    answers = int(run_health.get("answers_collected") or 0)
    if answers < 10:
        limitations.append("Fewer than ten probe answers were available.")
    if not run_health.get("grounded"):
        limitations.append("Published evidence was not retrieved; source-landscape claims are model-only.")
    if int(run_health.get("classification_failures") or 0):
        limitations.append("One or more model-convergence indicators have insufficient classification data.")
    if int(run_health.get("unassessed_hypotheses") or 0):
        limitations.append("Additional hypotheses were preserved but not measured beyond the five-hypothesis limit.")

    assurance = "limited" if limitations else "moderate"
    source_count = len(archaeology.get("sources") or [])
    hypothesis_sources = sum(
        sum(1 for finding in (country.get("for") or []) + (country.get("against") or [])
            if finding.get("source_retrieved") is True)
        for item in archaeology.get("hypothesis_evidence") or []
        for country in item.get("countries") or []
        if isinstance(country, dict)
    )
    return {
        "decision_use": "advisory_research_qa",
        "assurance_level": assurance,
        "human_review_required": True,
        "metric_notice": (
            "Scores are heuristic review indicators, not validated measures of bias, "
            "contamination, research quality or truth."
        ),
        "evidence_basis": {
            "probe_answers": answers,
            "probe_models": list(run_health.get("probe_models") or []),
            "published_sources": source_count + hypothesis_sources,
            "web_grounded": bool(run_health.get("grounded")),
            "classification_failures": int(run_health.get("classification_failures") or 0),
            "unassessed_hypotheses": int(run_health.get("unassessed_hypotheses") or 0),
            "prompt_version": run_health.get("prompt_version"),
        },
        "limitations": limitations or [
            "Model judgements are correlated and are not independent expert assessments.",
            "Published citations support individual claims but do not validate the overall score.",
        ],
        "required_reviewer_decisions": [
            "Confirm that the extracted client hypotheses accurately represent the brief.",
            "Accept, reject or amend each material risk and record the reason.",
            "Check every consequential citation against the source.",
            "Approve any sample, methodology or instrument change before fieldwork.",
        ],
        "review_indicator": {
            "name": "Research design review indicator",
            "value": confidence.get("confidence_score"),
            "label": confidence.get("confidence_label"),
        },
    }


def audit_assurance(result: dict[str, Any], prompt_version: str) -> dict[str, Any]:
    item_count = len(result.get("items") or [])
    return {
        "decision_use": "advisory_instrument_qa",
        "assurance_level": "moderate" if item_count else "limited",
        "human_review_required": True,
        "metric_notice": (
            "The wording score is a deterministic summary of model-labelled issues; "
            "it is not a validated measure of instrument quality."
        ),
        "evidence_basis": {
            "items_reviewed": item_count,
            "prompt_version": prompt_version,
            "published_sources": 0,
        },
        "limitations": [
            "Issue labels and rewrites are model judgements.",
            "Coverage checks do not establish construct validity or predict fieldwork quality.",
        ],
        "required_reviewer_decisions": [
            "Confirm every high-severity flag against the intended research objective.",
            "Accept, reject or amend each rewrite.",
            "Confirm scales, routing, consent and safeguarding outside this wording review.",
        ],
    }
