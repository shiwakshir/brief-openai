"""Typed, environment-driven runtime configuration for BRIEF."""

from __future__ import annotations

import os
from dotenv import load_dotenv

from policy import enforce as enforce_policy, get_policy

load_dotenv()


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value


ENVIRONMENT = os.getenv("BRIEF_ENVIRONMENT", "development").strip().lower()
POLICY_PROFILE = os.getenv("BRIEF_POLICY_PROFILE", "internal_confidential").strip()
PROMPT_VERSION = os.getenv("BRIEF_PROMPT_VERSION", "2026-09-11")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or None
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
PROBE_MODELS = _csv(os.getenv("OPENAI_PROBE_MODELS", "gpt-4.1-mini,gpt-5.4-mini"))
GROUNDING_MODEL = os.getenv("OPENAI_GROUNDING_MODEL", "gpt-5.4-mini")
GROUNDING_EFFORT = os.getenv("OPENAI_GROUNDING_EFFORT", "low")
GROUNDING_TIMEOUT_SECONDS = _int("OPENAI_GROUNDING_TIMEOUT", 240)
OPENAI_TIMEOUT_SECONDS = _int("OPENAI_TIMEOUT_SECONDS", 120)
OPENAI_MAX_RETRIES = _int("OPENAI_MAX_RETRIES", 2, minimum=0)
ENABLE_WEB_GROUNDING = _bool("BRIEF_ENABLE_WEB_GROUNDING", False)

# Data handling
RUN_LOG_DIR = os.getenv("BRIEF_RUN_LOG_DIR", "runs")
LOG_RAW_PAYLOADS = _bool("BRIEF_LOG_RAW_PAYLOADS", False)
SESSION_TTL_SECONDS = _int("BRIEF_SESSION_TTL_SECONDS", 1800)
RUN_TIMEOUT_SECONDS = _int("BRIEF_RUN_TIMEOUT_SECONDS", 900)
MAX_CONTENT_LENGTH = _int("BRIEF_MAX_CONTENT_LENGTH", 2 * 1024 * 1024)
MAX_UPLOAD_BYTES = _int("BRIEF_MAX_UPLOAD_BYTES", 2 * 1024 * 1024)
MAX_DOCX_EXPANDED_BYTES = _int("BRIEF_MAX_DOCX_EXPANDED_BYTES", 10 * 1024 * 1024)
MAX_PDF_PAGES = _int("BRIEF_MAX_PDF_PAGES", 100)

# Capacity
MAX_CONCURRENT_JOBS = _int("BRIEF_MAX_CONCURRENT_JOBS", 2)
MAX_SESSIONS = _int("BRIEF_MAX_SESSIONS", 100)
MAX_HYPOTHESES_GROUNDED = 3
MAX_HYPOTHESES_MEASURED = 5
PROBE_WORKERS = _int("BRIEF_PROBE_WORKERS", 8)

# Authentication
BRIEF_PASSWORD = os.getenv("BRIEF_PASSWORD", "")
TRUST_AUTH_PROXY = _bool("BRIEF_TRUST_AUTH_PROXY", False)
AUTH_USER_HEADER = os.getenv("BRIEF_AUTH_USER_HEADER", "X-Forwarded-User")
ALLOW_INSECURE_DEVELOPMENT = _bool("BRIEF_ALLOW_INSECURE_DEVELOPMENT", False)

MIN_BRIEF_LENGTH = 50
MAX_BRIEF_LENGTH = 24000
MIN_INSTRUMENT_LENGTH = 80
MAX_INSTRUMENT_LENGTH = 40000
STYLE_NOTE = "\n\nUse British English spelling."
ACTIVE_POLICY = get_policy(POLICY_PROFILE)


def validate_startup() -> None:
    enforce_policy(
        ACTIVE_POLICY,
        web_grounding=ENABLE_WEB_GROUNDING,
        raw_payload_logging=LOG_RAW_PAYLOADS,
    )
    if ENVIRONMENT not in {"development", "test"}:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is required outside development/test")
        if not TRUST_AUTH_PROXY and not BRIEF_PASSWORD:
            raise RuntimeError("Configure BRIEF_TRUST_AUTH_PROXY or BRIEF_PASSWORD")
        if ALLOW_INSECURE_DEVELOPMENT:
            raise RuntimeError("BRIEF_ALLOW_INSECURE_DEVELOPMENT is forbidden outside development/test")
