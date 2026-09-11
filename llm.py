"""
Model access and run logging shared by every BRIEF agent.

- call_model: one chat completion, optionally in JSON mode.
- call_json: a chat completion that must return a JSON object with given keys;
  retries once with a correction, then raises so the caller records a real
  failure instead of passing partial data downstream.
- Run logging: each analysis gets a folder under RUN_LOG_DIR with one JSON
  file per agent, so any score can be traced to what the agent saw and said.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Iterable

from openai import OpenAI

import config

log = logging.getLogger("brief.llm")

client = OpenAI(
    api_key=config.OPENAI_API_KEY or "missing-development-key",
    base_url=config.OPENAI_BASE_URL,
    timeout=config.OPENAI_TIMEOUT_SECONDS,
    max_retries=config.OPENAI_MAX_RETRIES,
)

# A run folder per thread, so concurrent analyses do not write into each other's logs.
_run_state = threading.local()


# ---------------------------------------------------------------------------
# Run logging
# ---------------------------------------------------------------------------

def start_run_log() -> str | None:
    """Create a raw trace folder only when explicitly enabled."""
    if not config.LOG_RAW_PAYLOADS:
        _run_state.run_dir = None
        return None
    try:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        run_dir = os.path.join(config.RUN_LOG_DIR, f"{stamp}-{threading.get_ident() % 10000:04d}")
        os.makedirs(run_dir, exist_ok=True)
    except OSError as exc:
        log.warning("Could not create run folder: %s", exc)
        run_dir = None
    _run_state.run_dir = run_dir
    return run_dir


def current_run_dir() -> str | None:
    return getattr(_run_state, "run_dir", None)


def log_step(name: str, payload: Any) -> None:
    """Write one agent's input/output to the current run folder."""
    run_dir = current_run_dir()
    if not run_dir:
        log.info("step=%s completed payload_logging=disabled", name)
        return
    try:
        with open(os.path.join(run_dir, f"{name}.json"), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
    except (OSError, TypeError) as exc:
        log.warning("Could not write %s: %s", name, exc)


# ---------------------------------------------------------------------------
# Model calls
# ---------------------------------------------------------------------------

def call_model(
    system_prompt: str,
    user_message: str,
    *,
    temperature: float = 0.3,
    json_mode: bool = False,
    model: str | None = None,
) -> str:
    """One chat completion. GPT-5 family models reject a temperature, so it is omitted for them."""
    use_model = model or config.MODEL
    kwargs: dict[str, Any] = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if not use_model.startswith("gpt-5"):
        kwargs["temperature"] = temperature
    response = client.chat.completions.create(
        model=use_model,
        messages=[
            {"role": "system", "content": system_prompt + config.STYLE_NOTE},
            {"role": "user", "content": user_message},
        ],
        store=False,
        **kwargs,
    )
    log.info(
        "model_call model=%s request_id=%s input_tokens=%s output_tokens=%s",
        use_model,
        getattr(response, "_request_id", None),
        getattr(getattr(response, "usage", None), "prompt_tokens", None),
        getattr(getattr(response, "usage", None), "completion_tokens", None),
    )
    return response.choices[0].message.content or ""


def parse_json(raw: str) -> dict[str, Any]:
    """Parse a model reply as JSON, tolerating fences and surrounding prose."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            pass
    return {"raw": cleaned}


class MissingKeysError(ValueError):
    """The model did not return the JSON keys the next agent needs."""


def call_json(
    step_name: str,
    system_prompt: str,
    user_message: str,
    *,
    required_keys: Iterable[str] = (),
    temperature: float = 0.3,
) -> dict[str, Any]:
    """
    Call the model in JSON mode and check the reply has every required key.
    Retry once with a correction. Raise MissingKeysError if it still fails.
    """
    required = tuple(required_keys)
    attempts: list[dict[str, Any]] = []
    message = user_message
    missing: list[str] = []
    for attempt in range(2):
        raw = call_model(system_prompt, message, temperature=temperature, json_mode=True)
        result = parse_json(raw)
        missing = [key for key in required if key not in result]
        attempts.append({"attempt": attempt + 1, "raw": raw, "missing_keys": missing})
        if not missing and "raw" not in result:
            log_step(step_name, {"attempts": attempts, "result": result})
            return result
        message = (
            f"{user_message}\n\nYour previous reply was not valid. It was missing these keys: {missing}. "
            "Return ONLY the JSON object with every required key."
        )
    log_step(step_name, {"attempts": attempts, "result": None})
    raise MissingKeysError(f"{step_name}: model did not return the required JSON keys {missing}")
