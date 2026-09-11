"""
Evaluate BRIEF against a test set of briefs with planted biases.

Usage:
    python evaluate.py                # run all briefs in tests/briefs.json
    python evaluate.py bank-budgeting # run one brief by id
    python evaluate.py --dry          # list the briefs and expectations, no API calls
    python evaluate.py --quick        # one probe model, no web grounding (cheap smoke test)

For each brief the script:
  1. runs the full pipeline,
  2. flattens the report to text,
  3. checks each expected flag group (a group passes if ANY of its phrases appears),
  4. checks that each expected high-contamination hypothesis scored over 50,
  5. writes a scorecard to tests/results/<timestamp>.json and prints a summary.

A change to the tool is an improvement only if this score goes up.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

TESTS_PATH = os.path.join("tests", "briefs.json")
RESULTS_DIR = os.path.join("tests", "results")


def flatten(obj: Any) -> str:
    """Turn the nested result dict into one lowercase string for phrase checks."""
    parts = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("query_data",):
                    continue  # the raw AI answers are not the tool's findings
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif x is not None:
            parts.append(str(x))

    walk(obj)
    return "\n".join(parts).lower()


def check(brief_case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    text = flatten(result)
    flag_results = []
    for group in brief_case.get("expect_any", []):
        hit = next((p for p in group if p.lower() in text), None)
        flag_results.append({"group": group, "hit": hit, "passed": hit is not None})

    contamination_results = []
    assessed = result.get("contamination", {}).get("hypotheses_assessed", [])
    for phrase in brief_case.get("expect_high_contamination", []):
        match = next((h for h in assessed if phrase.lower() in str(h.get("hypothesis", "")).lower()), None)
        score = match.get("contamination_score") if match else None
        contamination_results.append({
            "phrase": phrase,
            "found_hypothesis": bool(match),
            "score": score,
            "passed": bool(match) and isinstance(score, int) and score > 50,
        })

    errors = [k for k, v in result.items() if isinstance(v, dict) and v.get("_error")]
    return {
        "id": brief_case["id"],
        "flags": flag_results,
        "contamination": contamination_results,
        "step_errors": errors,
        "confidence_score": result.get("confidence", {}).get("confidence_score"),
        "grounded": result.get("archaeology", {}).get("grounded", False),
        "generic_rejected": len(result.get("methodology", {}).get("rejected_as_generic", [])),
    }


def main() -> None:
    with open(TESTS_PATH, encoding="utf-8") as f:
        cases = json.load(f)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    quick = "--quick" in sys.argv
    if args:
        cases = [c for c in cases if c["id"] in args]

    if dry:
        for c in cases:
            print(f"{c['id']}: {len(c['expect_any'])} flag groups, "
                  f"{len(c.get('expect_high_contamination', []))} contamination checks")
        return

    from agent import run_brief  # imported here so --dry needs no API key

    os.makedirs(RESULTS_DIR, exist_ok=True)
    scorecards = []
    for c in cases:
        print(f"\n=== {c['id']} ===")
        start = time.time()
        result = run_brief(c["brief"], progress_callback=lambda n, i, t: print(f"  {i}/{t} {n}"),
                           mode=c.get("mode", "market"), quick=quick)
        card = check(c, result)
        card["seconds"] = round(time.time() - start)
        scorecards.append(card)
        for fr in card["flags"]:
            mark = "PASS" if fr["passed"] else "MISS"
            print(f"  [{mark}] {fr['group'][0]} ... -> {fr['hit']}")
        for cr in card["contamination"]:
            mark = "PASS" if cr["passed"] else "MISS"
            print(f"  [{mark}] contamination '{cr['phrase']}' scored {cr['score']}")
        if card["step_errors"]:
            print(f"  step errors: {card['step_errors']}")

    total_flags = sum(len(s["flags"]) for s in scorecards)
    passed_flags = sum(1 for s in scorecards for f in s["flags"] if f["passed"])
    total_cont = sum(len(s["contamination"]) for s in scorecards)
    passed_cont = sum(1 for s in scorecards for f in s["contamination"] if f["passed"])

    summary = {
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "quick": quick,
        "briefs": len(scorecards),
        "flags_passed": f"{passed_flags}/{total_flags}",
        "contamination_passed": f"{passed_cont}/{total_cont}",
        "step_errors": sum(len(s["step_errors"]) for s in scorecards),
        "cards": scorecards,
    }
    out_path = os.path.join(RESULTS_DIR, time.strftime("%Y%m%d-%H%M%S") + ".json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\nFlags caught: {summary['flags_passed']}   "
          f"High-contamination hypotheses caught: {summary['contamination_passed']}   "
          f"Step errors: {summary['step_errors']}")
    print(f"Scorecard written to {out_path}")


if __name__ == "__main__":
    main()
