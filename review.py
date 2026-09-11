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
            "id": str(item.get("hypothesis_id") or f"hypothesis-{index}"),
            "category": "model_convergence",
            "statement": str(item.get("hypothesis") or ""),
            "indicator": item.get("contamination_score") if item.get("contamination_score") is not None else "Insufficient data",
            "basis": "computed_from_model_outputs" if item.get("contamination_score") is not None else "classification_incomplete",
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
    citations = list((report.get("archaeology") or {}).get("sources") or [])
    for evidence in (report.get("archaeology") or {}).get("hypothesis_evidence") or []:
        for country in evidence.get("countries") or []:
            citations.extend(country.get("for") or [])
            citations.extend(country.get("against") or [])
    seen_urls: set[str] = set()
    for citation in citations:
        url = str(citation.get("url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        findings.append({
            "id": f"citation-{len(seen_urls)}",
            "category": "citation_verification",
            "statement": str(citation.get("title") or citation.get("source") or url),
            "explanation": url,
            "basis": "published_evidence_unverified",
            "required_action": "Open the source and confirm the claim, population, geography and publication date.",
        })

    for item in report.get("items") or []:
        issues = item.get("issues") or []
        if not issues:
            continue
        finding_id = f"instrument-{item.get('id', len(findings) + 1)}"
        findings.append({
            "id": finding_id,
            "category": "instrument_wording",
            "statement": str(item.get("text") or ""),
            "explanation": "; ".join(str(issue.get("explanation") or "") for issue in issues),
            "basis": "mixed_rules_and_model_judgement",
            "required_action": "Accept, reject or amend the proposed wording change.",
        })
    return findings
