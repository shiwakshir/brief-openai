"""Centrally selected data-handling policy profiles."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Policy:
    name: str
    max_classification: str
    web_grounding: bool
    raw_payload_logging: bool
    allowed_uploads: tuple[str, ...]
    description: str


PROFILES = {
    "public_synthetic": Policy("public_synthetic", "public", True, False,
                               (".pdf", ".docx", ".txt", ".md"),
                               "Public or synthetic material only; web grounding permitted."),
    "internal_confidential": Policy("internal_confidential", "confidential", False, False,
                                    (".pdf", ".docx", ".txt", ".md"),
                                    "Internal confidential material; no web grounding or raw traces."),
    "regulated_zdr": Policy("regulated_zdr", "restricted", False, False,
                            (".txt", ".md"),
                            "Restricted profile; text-only, no web grounding, no raw traces. Requires approved ZDR configuration."),
}


def get_policy(name: str) -> Policy:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise RuntimeError(f"Unknown BRIEF_POLICY_PROFILE: {name}") from exc


def enforce(policy: Policy, *, web_grounding: bool, raw_payload_logging: bool) -> None:
    if web_grounding and not policy.web_grounding:
        raise RuntimeError(f"Policy {policy.name} forbids web grounding")
    if raw_payload_logging and not policy.raw_payload_logging:
        raise RuntimeError(f"Policy {policy.name} forbids raw payload logging")
