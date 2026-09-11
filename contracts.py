"""Deterministic result-contract validation."""

from __future__ import annotations
from typing import Any


def validate_report(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_dicts = ("run_health", "parsed", "confidence", "contamination", "methodology", "assurance")
    for key in required_dicts:
        if not isinstance(result.get(key), dict):
            errors.append(f"{key} must be an object")
    confidence = result.get("confidence") or {}
    score = confidence.get("confidence_score")
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
        errors.append("confidence.confidence_score must be an integer from 0 to 100")
    assurance = result.get("assurance") or {}
    if assurance.get("assurance_level") not in {"limited", "moderate"}:
        errors.append("assurance.assurance_level must be limited or moderate")
    if assurance.get("human_review_required") is not True:
        errors.append("assurance.human_review_required must be true")
    return errors


def validate_review_decisions(value: Any, allowed_ids: set[str]) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("decisions must be a list of at most 100 items")
    clean: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("each decision must be an object")
        finding_id = str(raw.get("finding_id") or "").strip()
        decision = str(raw.get("decision") or "").strip().lower()
        rationale = str(raw.get("rationale") or "").strip()
        amendment = str(raw.get("amendment") or "").strip()
        if finding_id not in allowed_ids or finding_id in seen:
            raise ValueError("decision references an unknown or duplicate finding")
        if decision not in {"accepted", "rejected", "amended"}:
            raise ValueError("decision must be accepted, rejected or amended")
        if len(rationale) < 10 or len(rationale) > 1000:
            raise ValueError("each decision requires a rationale of 10 to 1000 characters")
        if decision == "amended" and not amendment:
            raise ValueError("amended findings require amendment text")
        seen.add(finding_id)
        clean.append({"finding_id": finding_id, "decision": decision,
                      "rationale": rationale, "amendment": amendment[:2000]})
    return clean
