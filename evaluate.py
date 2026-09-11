"""Run BRIEF against labelled synthetic cases and enforce quality thresholds."""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

CASES_PATH = os.path.join("evals", "labelled_cases.json")
RESULTS_DIR = os.path.join("evals", "results")


def explicit_findings(result: dict[str, Any]) -> list[dict[str, str]]:
    """Extract analysis outputs only; never search parsed brief or client hypotheses."""
    findings: list[dict[str, str]] = []

    def add(category: str, value: Any) -> None:
        if isinstance(value, dict):
            text = " ".join(str(v) for k, v in value.items() if k not in {"hypothesis", "hypothesis_id"})
        elif isinstance(value, list):
            text = " ".join(str(v) for v in value)
        else:
            text = str(value or "")
        if text.strip():
            findings.append({"category": category, "text": text.lower()})

    confidence = result.get("confidence") or {}
    add("key_finding", confidence.get("key_finding"))
    for risk in confidence.get("top_three_risks") or []:
        add("risk_to_fieldwork", risk)
    gaps = result.get("gaps") or {}
    for gap in gaps.get("sample_cannot_test") or []:
        add("sample_fit", gap.get("why") if isinstance(gap, dict) else gap)
    for item in (result.get("contamination") or {}).get("hypotheses_assessed") or []:
        add("convergence_analysis", {
            "explanation": item.get("explanation"),
            "recommendation": item.get("recommendation"),
            "responses_matching": item.get("responses_matching"),
        })
    archaeology = result.get("archaeology") or {}
    add("source_landscape", archaeology.get("dominant_narrative_origin"))
    add("source_landscape", archaeology.get("implication_for_research"))
    methodology = result.get("methodology") or {}
    add("methodology", methodology.get("recommended_approach"))
    add("methodology", methodology.get("sample_design_notes"))
    return findings


def _matches(expectation: dict[str, Any], findings: list[dict[str, str]]) -> str | None:
    phrases = [str(p).lower() for p in expectation.get("phrases", [])]
    category = str(expectation.get("category") or "")
    for finding in findings:
        if finding["category"] == category:
            if "*" in phrases:
                return "*"
            hit = next((phrase for phrase in phrases if phrase in finding["text"]), None)
            if hit:
                return hit
    return None


def check(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    findings = explicit_findings(result)
    expected = []
    forbidden = []
    for label in case.get("expected_findings", []):
        hit = _matches(label, findings)
        expected.append({**label, "hit": hit, "passed": hit is not None})
    for label in case.get("forbidden_findings", []):
        hit = _matches(label, findings)
        forbidden.append({**label, "hit": hit, "passed": hit is None})
    assessed = (result.get("contamination") or {}).get("hypotheses_assessed") or []
    contamination = []
    for label in case.get("expected_high_convergence", []):
        match = next((item for item in assessed if label.lower() in str(item.get("hypothesis", "")).lower()), None)
        score = match.get("contamination_score") if match else None
        contamination.append({"label": label, "score": score,
                              "passed": isinstance(score, int) and not isinstance(score, bool) and score > 50})
    return {"id": case["id"], "expected": expected, "forbidden": forbidden,
            "contamination": contamination, "step_errors": (result.get("run_health") or {}).get("step_errors", [])}


def metrics(cards: list[dict[str, Any]]) -> dict[str, float | int]:
    tp = sum(item["passed"] for card in cards for item in card["expected"])
    fn = sum(not item["passed"] for card in cards for item in card["expected"])
    fp = sum(not item["passed"] for card in cards for item in card["forbidden"])
    cont_pass = sum(item["passed"] for card in cards for item in card["contamination"])
    cont_total = sum(len(card["contamination"]) for card in cards)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {"true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": precision, "recall": recall,
            "convergence_passed": cont_pass, "convergence_total": cont_total,
            "step_errors": sum(len(card["step_errors"]) for card in cards)}


def thresholds_pass(summary: dict[str, Any], min_precision: float, min_recall: float) -> bool:
    return (summary["precision"] >= min_precision and summary["recall"] >= min_recall
            and summary["convergence_passed"] == summary["convergence_total"]
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
    with open(CASES_PATH, encoding="utf-8") as handle:
        cases = json.load(handle)
    if not isinstance(cases, list) or not cases:
        raise SystemExit("Evaluation dataset must contain cases")
    if not any(case.get("expected_findings") for case in cases):
        raise SystemExit("Evaluation dataset needs positive labelled expectations")
    if not any(case.get("forbidden_findings") for case in cases):
        raise SystemExit("Evaluation dataset needs clean/negative labelled expectations")
    for case in cases:
        if not case.get("id") or not case.get("brief"):
            raise SystemExit("Every evaluation case needs an id and brief")
        for label in case.get("expected_findings", []) + case.get("forbidden_findings", []):
            if not label.get("category") or not label.get("phrases"):
                raise SystemExit(f"Case {case['id']} has an incomplete expectation")
    if args.ids:
        cases = [case for case in cases if case["id"] in args.ids]
    if not cases:
        raise SystemExit("No matching evaluation cases")
    if args.dry or args.validate_dataset:
        print(f"Validated {len(cases)} labelled cases, including {sum(bool(c.get('forbidden_findings')) for c in cases)} clean/negative cases.")
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
