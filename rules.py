"""Deterministic, explainable research-instrument checks."""

from __future__ import annotations
import re
from typing import Any

RULE_VERSION = "1.0.0"


def _issue(rule_id: str, issue_type: str, severity: str, explanation: str) -> dict[str, str]:
    return {
        "type": issue_type,
        "severity": severity,
        "explanation": explanation,
        "source": "deterministic_rule",
        "rule_id": rule_id,
        "rule_version": RULE_VERSION,
    }


def check_item(item: dict[str, Any]) -> list[dict[str, str]]:
    text = str(item.get("text") or "").strip()
    low = text.lower()
    options = [str(x).strip().lower() for x in item.get("answer_options") or []]
    kind = str(item.get("kind") or "").lower()
    issues: list[dict[str, str]] = []

    if len(text) > 280:
        issues.append(_issue("wording.length", "excessive_length", "low",
                             "The item exceeds 280 characters and may be difficult to administer consistently."))

    if re.search(r"\b(how|what|which|rate|describe)\b.{0,80}\band\b.{0,80}\?", low):
        issues.append(_issue("wording.conjunction", "possible_double_barrelled", "medium",
                             "The item contains an 'and' construction that may ask about two concepts."))

    if kind in {"scale", "closed"} and options:
        has_na = any(re.search(r"not applicable|don't know|do not know|prefer not", x) for x in options)
        if len(options) >= 4 and not has_na:
            issues.append(_issue("scale.opt_out", "missing_opt_out", "low",
                                 "The response options do not include an explicit opt-out or not-applicable choice."))
        joined = " ".join(options)
        if "agree" in joined and "disagree" not in joined:
            issues.append(_issue("scale.balance.agreement", "unbalanced_scale", "high",
                                 "The options include agreement without a corresponding disagreement option."))
        if "satisfied" in joined and "dissatisfied" not in joined:
            issues.append(_issue("scale.balance.satisfaction", "unbalanced_scale", "high",
                                 "The options include satisfaction without a corresponding dissatisfaction option."))

    if kind == "task" and re.search(r"\b(click|tap|select|open|use)\b", low):
        issues.append(_issue("ux.task.path", "possible_task_leading", "medium",
                             "The task names an interface action; verify that it does not reveal the intended path."))

    return issues


def audit_instrument(items: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    return {str(item.get("id") or ""): check_item(item) for item in items}
