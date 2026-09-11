"""Build stable, reviewable findings from a BRIEF result."""

from __future__ import annotations
from typing import Any


def build_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for index, risk in enumerate((report.get("confidence") or {}).get("top_three_risks") or [], 1):
        findings.append({
            "id": f"risk-{index}",
            "category": "risk_to_fieldwork",
            "statement": str(risk),
            "basis": "model_judgement",
            "required_action": "Accept, reject or amend before fieldwork.",
        })
    for index, item in enumerate((report.get("contamination") or {}).get("hypotheses_assessed") or [], 1):
        findings.append({
            "id": f"hypothesis-{index}",
            "category": "model_convergence",
            "statement": str(item.get("hypothesis") or ""),
            "indicator": item.get("contamination_score"),
            "basis": "computed_from_model_outputs",
            "required_action": "Decide whether this convergence is relevant to the research design.",
        })
    for index, item in enumerate((report.get("gaps") or {}).get("sample_cannot_test") or [], 1):
        findings.append({
            "id": f"sample-gap-{index}",
            "category": "sample_fit",
            "statement": str(item.get("hypothesis") or item.get("why") or ""),
            "explanation": str(item.get("why") or ""),
            "basis": "model_judgement",
            "required_action": "Confirm against recruitment and fieldwork specifications.",
        })
    return findings
