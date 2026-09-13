"""Run BRIEF against labelled synthetic cases and enforce quality thresholds."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from typing import Any

CASES_PATH = os.path.join("evals", "labelled_cases.json")
SYNTHETIC_CASES_PATH = os.path.join("evals", "synthetic_research_cases.json")
RESULTS_DIR = os.path.join("evals", "results")

# Only these model-produced analytical fields are scored. Submitted brief text,
# parsed fields, hypothesis wording, IDs and raw probe answers are excluded by construction.
ANALYTICAL_FIELDS = (
    ("key_finding", "confidence.headline"),
    ("key_finding", "confidence.score_rationale"),
    ("key_finding", "confidence.key_finding.statement"),
    ("risk_to_fieldwork", "confidence.top_three_risks[]"),
    ("risk_to_fieldwork", "confidence.what_would_raise_it"),
    ("sample_fit", "gaps.audience_mismatch"),
    ("sample_fit", "gaps.overrepresented[].explanation"),
    ("sample_fit", "gaps.underrepresented[].explanation"),
    ("sample_fit", "gaps.unknown_unknowns[]"),
    ("sample_fit", "gaps.sample_cannot_test[].why"),
    ("convergence_analysis", "contamination.overall_explanation"),
    ("convergence_analysis", "contamination.hypotheses_assessed[].explanation"),
    ("convergence_analysis", "contamination.hypotheses_assessed[].recommendation"),
    ("source_landscape", "archaeology.hypothesis_evidence[].summary"),
    ("source_landscape", "archaeology.hypothesis_evidence[].countries[].for[].finding"),
    ("source_landscape", "archaeology.hypothesis_evidence[].countries[].against[].finding"),
    ("source_landscape", "archaeology.dominant_narrative_origin"),
    ("source_landscape", "archaeology.implication_for_research"),
    ("temporal_drift", "temporal_drift.drift_explanation"),
    ("temporal_drift", "temporal_drift.stale_assumptions[].why_stale"),
    ("temporal_drift", "temporal_drift.stale_assumptions[].research_implication"),
    ("competitor_intel", "competitor_intel.discussion_guide_implication"),
    ("methodology", "methodology.method_fit.reason"),
    ("methodology", "methodology.method_fit.scope_and_cost_note"),
    ("methodology", "methodology.recommended_approach"),
    ("methodology", "methodology.sample_design_notes"),
    ("methodology", "methodology.hypothesis_tests[].how_to_test_it"),
    ("methodology", "methodology.hypothesis_tests[].what_would_refute_it"),
    ("deliverables", "deliverables.challenge_note.opening"),
    ("deliverables", "deliverables.challenge_note.what_we_found"),
    ("deliverables", "deliverables.challenge_note.what_we_recommend"),
    ("deliverables", "deliverables.screener_criteria[].why"),
)


def _walk(obj: Any, segments: list[str]) -> list[str]:
    if not segments:
        return [obj] if isinstance(obj, str) else []
    head, rest = segments[0], segments[1:]
    if head.endswith("[]"):
        values = obj.get(head[:-2]) if isinstance(obj, dict) else None
        if not isinstance(values, list):
            return []
        return [text for value in values for text in _walk(value, rest)]
    if not isinstance(obj, dict):
        return []
    return _walk(obj.get(head), rest)


def _normalise(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.lower(), flags=re.UNICODE)


def explicit_findings(result: dict[str, Any]) -> list[dict[str, str]]:
    """Extract analysis outputs only; never search parsed brief or client hypotheses."""
    return [
        {"category": category, "text": _normalise(text)}
        for category, path in ANALYTICAL_FIELDS
        for text in _walk(result, path.split("."))
        if text.strip()
    ]


def _matches(expectation: dict[str, Any], findings: list[dict[str, str]]) -> str | None:
    raw_phrases = [str(p) for p in expectation.get("phrases", [])]
    wildcard = "*" in raw_phrases
    phrases = [_normalise(phrase).strip() for phrase in raw_phrases if phrase != "*"]
    phrases = [phrase for phrase in phrases if phrase]
    category = str(expectation.get("category") or "")
    for finding in findings:
        if category == "any_analysis" or finding["category"] == category:
            if wildcard:
                return "*"
            hit = next((phrase for phrase in phrases if phrase in finding["text"]), None)
            if hit:
                return hit
    return None


def check(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    findings = explicit_findings(result)
    expected = []
    forbidden = []
    expected_labels = case.get("expected_findings") or [
        {"category": "any_analysis", "phrases": group} for group in case.get("expect_any", [])
    ]
    forbidden_labels = case.get("forbidden_findings") or [
        {"category": "any_analysis", "phrases": [phrase]} for phrase in case.get("expect_none", [])
    ]
    for label in expected_labels:
        hit = _matches(label, findings)
        expected.append({**label, "hit": hit, "passed": hit is not None})
    for label in forbidden_labels:
        hit = _matches(label, findings)
        forbidden.append({**label, "hit": hit, "passed": hit is None})
    assessed = (result.get("contamination") or {}).get("hypotheses_assessed") or []
    contamination = []
    for label in case.get("expected_high_convergence", case.get("expect_high_contamination", [])):
        match = next((item for item in assessed if label.lower() in str(item.get("hypothesis", "")).lower()), None)
        score = match.get("contamination_score") if match else None
        contamination.append({"label": label, "score": score,
                              "passed": isinstance(score, int) and not isinstance(score, bool) and score > 50})
    structural = []
    if "expect_unassessed" in case:
        expected_count = int(case["expect_unassessed"])
        actual_count = int((result.get("run_health") or {}).get("unassessed_hypotheses") or 0)
        structural.append({"check": "unassessed_hypotheses", "expected": expected_count,
                           "actual": actual_count, "passed": actual_count == expected_count})
    return {"id": case["id"], "expected": expected, "forbidden": forbidden,
            "contamination": contamination, "structural": structural,
            "step_errors": (result.get("run_health") or {}).get("step_errors", [])}


def metrics(cards: list[dict[str, Any]]) -> dict[str, float | int]:
    tp = sum(item["passed"] for card in cards for item in card["expected"])
    fn = sum(not item["passed"] for card in cards for item in card["expected"])
    fp = sum(not item["passed"] for card in cards for item in card["forbidden"])
    cont_pass = sum(item["passed"] for card in cards for item in card["contamination"])
    cont_total = sum(len(card["contamination"]) for card in cards)
    structural_pass = sum(item["passed"] for card in cards for item in card.get("structural", []))
    structural_total = sum(len(card.get("structural", [])) for card in cards)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {"true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": precision, "recall": recall,
            "convergence_passed": cont_pass, "convergence_total": cont_total,
            "structural_passed": structural_pass, "structural_total": structural_total,
            "step_errors": sum(len(card["step_errors"]) for card in cards)}


def thresholds_pass(summary: dict[str, Any], min_precision: float, min_recall: float) -> bool:
    return (summary["precision"] >= min_precision and summary["recall"] >= min_recall
            and summary["convergence_passed"] == summary["convergence_total"]
            and summary.get("structural_passed", 0) == summary.get("structural_total", 0)
            and summary["step_errors"] == 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--validate-dataset", action="store_true")
    parser.add_argument("--min-precision", type=float, default=.80)
    parser.add_argument("--min-recall", type=float, default=.80)
    args = parser.parse_args()
    cases = []
    for path in (CASES_PATH, SYNTHETIC_CASES_PATH):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                cases.extend(json.load(handle))
    if not isinstance(cases, list) or not cases:
        raise SystemExit("Evaluation dataset must contain cases")
    if not any(case.get("expected_findings") or case.get("expect_any") for case in cases):
        raise SystemExit("Evaluation dataset needs positive labelled expectations")
    if not any(case.get("forbidden_findings") or case.get("expect_none") for case in cases):
        raise SystemExit("Evaluation dataset needs clean/negative labelled expectations")
    for case in cases:
        if not case.get("id") or not case.get("brief"):
            raise SystemExit("Every evaluation case needs an id and brief")
        labels = case.get("expected_findings", []) + case.get("forbidden_findings", [])
        for label in labels:
            if not label.get("category") or not label.get("phrases"):
                raise SystemExit(f"Case {case['id']} has an incomplete expectation")
        for group in case.get("expect_any", []):
            if not isinstance(group, list) or not group:
                raise SystemExit(f"Case {case['id']} has an incomplete expectation")
        if "expect_unassessed" in case and (
            not isinstance(case["expect_unassessed"], int) or case["expect_unassessed"] < 0
        ):
            raise SystemExit(f"Case {case['id']} has an invalid structural expectation")
    if args.ids:
        cases = [case for case in cases if case["id"] in args.ids]
    if not cases:
        raise SystemExit("No matching evaluation cases")
    if args.dry or args.validate_dataset:
        clean_count = sum(bool(c.get("forbidden_findings") or c.get("expect_none")) for c in cases)
        print(f"Validated {len(cases)} labelled cases, including {clean_count} clean/negative cases.")
        return 0

    from agent import run_brief
    cards = []
    for case in cases:
        result = run_brief(case["brief"], mode=case.get("mode", "market"), quick=args.quick)
        cards.append(check(case, result))
    summary = metrics(cards)
    summary["cards"] = cards
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, time.strftime("%Y%m%d-%H%M%S") + ".json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)
    passed = thresholds_pass(summary, args.min_precision, args.min_recall)
    print(f"Precision {summary['precision']:.1%}; recall {summary['recall']:.1%}; threshold {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
