"""Version-to-version comparison for BRIEF reports."""

from __future__ import annotations
from typing import Any


def _findings(report: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for index, risk in enumerate((report.get("confidence") or {}).get("top_three_risks") or []):
        out[f"risk-{index + 1}"] = str(risk)
    for index, item in enumerate((report.get("contamination") or {}).get("hypotheses_assessed") or []):
        out[f"hypothesis-{index + 1}"] = f"{item.get('hypothesis', '')}: {item.get('contamination_score', '')}"
    return out


def compare_reports(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    a, b = _findings(left), _findings(right)
    added = [{"id": key, "value": b[key]} for key in b.keys() - a.keys()]
    removed = [{"id": key, "value": a[key]} for key in a.keys() - b.keys()]
    changed = [{"id": key, "before": a[key], "after": b[key]}
               for key in a.keys() & b.keys() if a[key] != b[key]]
    return {
        "added": sorted(added, key=lambda x: x["id"]),
        "removed": sorted(removed, key=lambda x: x["id"]),
        "changed": sorted(changed, key=lambda x: x["id"]),
        "comparable": (
            (left.get("run_health") or {}).get("prompt_version")
            == (right.get("run_health") or {}).get("prompt_version")
        ),
        "notice": "Different prompt/model versions must not be interpreted as longitudinal change."
                  if (left.get("run_health") or {}).get("prompt_version")
                  != (right.get("run_health") or {}).get("prompt_version") else "",
    }
