"""Evidence provenance attached to every report section."""

from __future__ import annotations
from typing import Any

SECTION_PROVENANCE = {
    "parsed": ("model_judgement", "Model extraction from user-provided material."),
    "prompts": ("model_generated", "Synthetic prompts generated from the extracted brief."),
    "query_data": ("model_observation", "Outputs returned by configured probe models."),
    "convergence": ("computed_from_model_outputs", "Formula and classifier labels applied to probe outputs."),
    "clusters": ("model_judgement", "Model synthesis of probe outputs."),
    "gaps": ("model_judgement", "Model interpretation of brief and synthesis."),
    "temporal_drift": ("mixed_inference", "Model inference informed by published evidence when available."),
    "contamination": ("heuristic_indicator", "Computed convergence indicator plus model explanation."),
    "competitor_intel": ("model_judgement", "Model extraction from probe outputs."),
    "archaeology": ("published_evidence_and_model_synthesis", "Web citations plus model synthesis; citations require human verification."),
    "methodology": ("model_recommendation", "Advisory recommendation requiring researcher approval."),
    "confidence": ("heuristic_indicator", "Model score constrained by deterministic product rules."),
    "deliverables": ("model_recommendation", "Draft material requiring researcher editing and approval."),
}


def report_provenance(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: {"evidence_class": evidence_class, "description": description}
        for key, (evidence_class, description) in SECTION_PROVENANCE.items()
        if key in result
    }
