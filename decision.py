"""Deterministic internal workflow recommendations for BRIEF reports."""

from __future__ import annotations

from typing import Any


def internal_recommendation(report: dict[str, Any]) -> dict[str, Any]:
    """Return an internal next-step recommendation without claiming external approval."""
    if "items" in report and "summary" in report:
        return _audit_recommendation(report)
    return _brief_recommendation(report)


def _result(decision: str, reasons: list[str], reviewed: bool) -> dict[str, Any]:
    labels = {
        "proceed": "Proceed to research planning",
        "proceed_with_changes": "Proceed after changes",
        "hold": "Hold before fieldwork",
    }
    actions = {
        "proceed": "Use the findings to plan the next research stage and continue normal internal review.",
        "proceed_with_changes": "Address the listed design or instrument changes before fieldwork starts.",
        "hold": "Do not start fieldwork until the blocking evidence or design gaps are resolved.",
    }
    return {
        "decision": decision,
        "label": labels[decision],
        "review_status": "reviewed" if reviewed else "provisional",
        "scope": "internal_research_workflow",
        "recommended_action": actions[decision],
        "reasons": reasons,
        "notice": (
            "This is an automatically generated internal workflow recommendation, not client advice, "
            "organisational approval, or a validated statement of truth."
        ),
    }


def _brief_recommendation(report: dict[str, Any]) -> dict[str, Any]:
    health = report.get("run_health") or {}
    confidence = report.get("confidence") or {}
    contamination = report.get("contamination") or {}
    assurance = report.get("assurance") or {}
    gaps = report.get("gaps") or {}
    reasons: list[str] = []

    if health.get("status") == "invalid":
        reasons.append("The result contract is invalid.")
    if not int(health.get("answers_collected") or 0):
        reasons.append("No probe answers were collected.")
    if int(health.get("classification_failures") or 0):
        reasons.append("At least one hypothesis has insufficient classification data.")
    if health.get("step_errors"):
        reasons.append("One or more analysis stages failed.")
    if gaps.get("sample_cannot_test"):
        reasons.append("The stated sample or fieldwork cannot test at least one hypothesis.")

    score = confidence.get("confidence_score")
    if reasons or (isinstance(score, int) and score < 40):
        if not reasons:
            reasons.append("The research-design review indicator is below 40.")
        decision = "hold"
    else:
        level = str(contamination.get("overall_contamination_level") or "").lower()
        if (
            not isinstance(score, int)
            or score < 75
            or assurance.get("assurance_level") == "limited"
            or level in {"high", "critical"}
        ):
            decision = "proceed_with_changes"
            if not isinstance(score, int):
                reasons.append("No valid research-design review indicator is available.")
            elif score < 75:
                reasons.append(f"The research-design review indicator is {score}, below the proceed threshold of 75.")
            if assurance.get("assurance_level") == "limited":
                reasons.append("This run has limited assurance.")
            if level in {"high", "critical"}:
                reasons.append(f"Overall model convergence is {level}.")
        else:
            decision = "proceed"
            reasons.append("No automated blocking condition was found and the review indicator is at least 75.")

    reviewed = bool((report.get("human_review") or {}).get("complete"))
    return _result(decision, reasons, reviewed)


def _audit_recommendation(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary") or {}
    reasons: list[str] = []
    high = int(summary.get("high") or 0)
    untested = summary.get("untested_hypotheses") or []
    confirmed_only = summary.get("confirmed_only_hypotheses") or []
    score = summary.get("score")

    if high:
        reasons.append(f"The instrument contains {high} high-severity wording issue(s).")
    if untested:
        reasons.append("At least one client hypothesis is not tested by the instrument.")
    if high or untested:
        decision = "hold"
    elif confirmed_only or not isinstance(score, int) or score < 80:
        decision = "proceed_with_changes"
        if confirmed_only:
            reasons.append("At least one hypothesis can only be confirmed, not tested.")
        if isinstance(score, int) and score < 80:
            reasons.append(f"The wording-review indicator is {score}, below the proceed threshold of 80.")
        elif not isinstance(score, int):
            reasons.append("No valid wording-review indicator is available.")
    else:
        decision = "proceed"
        reasons.append("No high-severity or hypothesis-coverage blocker was found.")

    reviewed = bool((report.get("human_review") or {}).get("complete"))
    return _result(decision, reasons, reviewed)
