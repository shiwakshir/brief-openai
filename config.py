"""
Runtime configuration for BRIEF.

Every tunable lives here and is read from the environment once, so the rest of
the code never calls os.getenv directly. See .env.example for the documented
settings.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


# OpenAI
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL: str | None = os.getenv("OPENAI_BASE_URL") or None  # set to route through an internal gateway
MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
PROBE_MODELS: list[str] = _csv(os.getenv("OPENAI_PROBE_MODELS", "gpt-4.1-mini,gpt-5.4-mini"))
GROUNDING_MODEL: str = os.getenv("OPENAI_GROUNDING_MODEL", "gpt-5.4-mini")
GROUNDING_EFFORT: str = os.getenv("OPENAI_GROUNDING_EFFORT", "low")
GROUNDING_TIMEOUT_SECONDS: int = int(os.getenv("OPENAI_GROUNDING_TIMEOUT", "240"))

# Pipeline
RUN_LOG_DIR: str = os.getenv("BRIEF_RUN_LOG_DIR", "runs")
MAX_HYPOTHESES_GROUNDED: int = 3
MAX_HYPOTHESES_MEASURED: int = 5
PROBE_WORKERS: int = 8

# Web app
BRIEF_PASSWORD: str = os.getenv("BRIEF_PASSWORD", "")
SESSION_TTL_SECONDS: int = 1800
RUN_TIMEOUT_SECONDS: int = 900
MIN_BRIEF_LENGTH: int = 50
MAX_BRIEF_LENGTH: int = 24000
MIN_INSTRUMENT_LENGTH: int = 80
MAX_INSTRUMENT_LENGTH: int = 40000

# Prose style asked of every agent
STYLE_NOTE: str = "\n\nUse British English spelling."
