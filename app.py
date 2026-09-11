"""
Flask front end for BRIEF.

Routes:
  GET  /                  the single-page UI
  POST /extract           uploaded document -> plain text
  POST /parse             step 1 only, so the user can review the hypotheses
  POST /analyse           start a full brief analysis in the background
  POST /audit             start a guide/questionnaire audit in the background
  GET  /progress/<id>     server-sent events with progress, then the result
  POST /export            report or audit data -> designed .docx or .pdf download
  GET  /health            liveness check for the host

Long-running work runs in a background thread per session. Sessions live in
process memory, so the app must run as a single worker process.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from flask import Flask, Response, g, jsonify, render_template, request, stream_with_context

import config
from agent import parse_brief, run_brief
from audit import run_audit
from documents import UnsupportedFileType, extract_text
from export import export_document
from comparison import compare_reports
from contracts import validate_review_decisions
from review import build_findings
from telemetry import metrics
from limits import SlidingWindowLimiter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("brief.app")

config.validate_startup()
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@dataclass
class Session:
    owner: str
    created: float = field(default_factory=time.time)
    progress: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    cancelled: threading.Event = field(default_factory=threading.Event)


class SessionStore:
    """In-memory sessions with time-based expiry. One process only."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, owner: str) -> str:
        self.expire()
        session_id = os.urandom(16).hex()
        with self._lock:
            if len(self._sessions) >= config.MAX_SESSIONS:
                raise RuntimeError("The service is at capacity; try again later.")
            self._sessions[session_id] = Session(owner=owner)
        return session_id

    def get(self, session_id: str, owner: str) -> Session | None:
        self.expire()
        with self._lock:
            session = self._sessions.get(session_id)
            return session if session and hmac.compare_digest(session.owner, owner) else None

    def expire(self) -> None:
        now = time.time()
        with self._lock:
            stale = [
                sid for sid, s in self._sessions.items()
                if s.result is not None and now - s.created > self._ttl
            ]
            for sid in stale:
                self._sessions.pop(sid, None)


sessions = SessionStore(config.SESSION_TTL_SECONDS)
job_slots = threading.BoundedSemaphore(config.MAX_CONCURRENT_JOBS)
user_limiter = SlidingWindowLimiter(config.MAX_JOBS_PER_USER_HOUR, 3600)


def _start_background(session_id: str, work) -> None:
    """Run `work(on_progress)` in a thread and store its result on the session."""
    session = sessions.get(session_id, g.identity)

    def on_progress(step_name: str, step_number: int, total_steps: int) -> None:
        if session.cancelled.is_set():
            raise RuntimeError("Job cancelled")
        session.progress.append({
            "step": step_name, "number": step_number, "total": total_steps,
            "pct": int(step_number / total_steps * 100),
        })

    def run() -> None:
        started = time.monotonic()
        metrics.increment("jobs_started")
        try:
            report = work(on_progress)
            report["findings"] = build_findings(report)
            session.result = {"status": "done", "data": report}
            metrics.observe_job(started, "completed")
        except Exception:
            if session.cancelled.is_set():
                session.result = {"status": "cancelled", "message": "The analysis was cancelled."}
                metrics.observe_job(started, "cancelled")
            else:
                log.exception("background run failed")
                session.result = {"status": "error", "message": "The analysis failed. Quote the job ID to support."}
                metrics.observe_job(started, "failed")
        finally:
            job_slots.release()

    threading.Thread(target=run, daemon=True, name=f"brief-{session_id[:8]}").start()


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

@app.before_request
def authenticate():
    """Require an upstream identity or an explicitly configured development login."""
    if request.path == "/health/live":
        return None
    if config.TRUST_AUTH_PROXY:
        identity = request.headers.get(config.AUTH_USER_HEADER, "").strip()
        if not identity:
            return jsonify({"error": "Authentication required."}), 401
        g.identity = identity
        return None
    if config.BRIEF_PASSWORD:
        auth = request.authorization
        if auth and hmac.compare_digest(auth.password or "", config.BRIEF_PASSWORD):
            g.identity = auth.username or "shared-pilot-user"
            return None
        return Response("Password required", 401, {"WWW-Authenticate": 'Basic realm="BRIEF"'})
    if config.ENVIRONMENT in {"development", "test"} and config.ALLOW_INSECURE_DEVELOPMENT:
        g.identity = "local-development"
        return None
    return jsonify({"error": "Authentication is not configured."}), 503


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health/live")
def health_live():
    return jsonify({"status": "ok"})


@app.route("/health/ready")
def health_ready():
    if not config.OPENAI_API_KEY:
        return jsonify({"status": "not_ready", "reason": "OpenAI is not configured"}), 503
    return jsonify({"status": "ready"})


@app.route("/extract", methods=["POST"])
def extract():
    upload = request.files.get("file")
    if not upload:
        return jsonify({"error": "No file received."}), 400
    suffix = os.path.splitext(upload.filename or "")[1].lower()
    if suffix not in config.ACTIVE_POLICY.allowed_uploads:
        return jsonify({"error": "This file type is not permitted by the active data policy."}), 400
    try:
        data = upload.read(config.MAX_UPLOAD_BYTES + 1)
        if len(data) > config.MAX_UPLOAD_BYTES:
            return jsonify({"error": "The uploaded file is too large."}), 413
        text = extract_text(upload.filename or "", data)
    except UnsupportedFileType as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Could not read that file: {exc}"}), 400
    if len(text) < config.MIN_BRIEF_LENGTH:
        return jsonify({"error": "That file has almost no readable text. If it is a scanned PDF, paste the text instead."}), 400
    return jsonify({
        "text": text[:config.MAX_BRIEF_LENGTH],
        "truncated": len(text) > config.MAX_BRIEF_LENGTH,
        "chars": len(text),
    })


@app.route("/parse", methods=["POST"])
def parse():
    data = request.get_json(silent=True) or {}
    brief = (data.get("brief") or "").strip()
    mode = (data.get("mode") or "market").lower()
    if len(brief) < config.MIN_BRIEF_LENGTH:
        return jsonify({"error": "That brief is too short. Add more detail about the audience, objective, and any client hypotheses."}), 400
    try:
        parsed = parse_brief(brief[:config.MAX_BRIEF_LENGTH], mode)
    except Exception as exc:
        log.exception("parse failed")
        return jsonify({"error": f"Could not read the brief: {exc}"}), 500
    return jsonify({"parsed": parsed})


@app.route("/analyse", methods=["POST"])
def analyse():
    data = request.get_json(silent=True) or {}
    brief = (data.get("brief") or "").strip()
    if len(brief) < config.MIN_BRIEF_LENGTH:
        return jsonify({"error": "That brief is too short. Add more detail about the audience, objective, and any client hypotheses."}), 400
    brief = brief[:config.MAX_BRIEF_LENGTH]
    mode = (data.get("mode") or "market").lower()
    parsed_override = data.get("parsed") if isinstance(data.get("parsed"), dict) else None
    quick = bool(data.get("quick"))

    if not user_limiter.allow(g.identity):
        metrics.increment("jobs_rate_limited")
        return jsonify({"error": "Your hourly analysis limit has been reached."}), 429
    if not job_slots.acquire(blocking=False):
        metrics.increment("jobs_capacity_rejected")
        return jsonify({"error": "The service is at capacity; try again later."}), 429
    try:
        session_id = sessions.create(g.identity)
    except RuntimeError as exc:
        job_slots.release()
        return jsonify({"error": str(exc)}), 429
    _start_background(session_id, lambda on_progress: run_brief(
        brief, progress_callback=on_progress, parsed_override=parsed_override, mode=mode, quick=quick,
    ))
    return jsonify({"session_id": session_id})


@app.route("/audit", methods=["POST"])
def audit():
    data = request.get_json(silent=True) or {}
    instrument = (data.get("instrument") or "").strip()
    if len(instrument) < config.MIN_INSTRUMENT_LENGTH:
        return jsonify({"error": "Paste or upload a guide or questionnaire with at least a few questions."}), 400
    instrument = instrument[:config.MAX_INSTRUMENT_LENGTH]
    brief = (data.get("brief") or "").strip()[:config.MAX_BRIEF_LENGTH]
    mode = (data.get("mode") or "market").lower()

    if not user_limiter.allow(g.identity):
        metrics.increment("jobs_rate_limited")
        return jsonify({"error": "Your hourly analysis limit has been reached."}), 429
    if not job_slots.acquire(blocking=False):
        metrics.increment("jobs_capacity_rejected")
        return jsonify({"error": "The service is at capacity; try again later."}), 429
    try:
        session_id = sessions.create(g.identity)
    except RuntimeError as exc:
        job_slots.release()
        return jsonify({"error": str(exc)}), 429
    _start_background(session_id, lambda on_progress: run_audit(
        instrument, brief, mode, progress_callback=on_progress,
    ))
    return jsonify({"session_id": session_id})


@app.route("/cancel/<session_id>", methods=["POST"])
def cancel_session(session_id: str):
    session = sessions.get(session_id, g.identity)
    if session is None:
        return jsonify({"error": "Unknown session."}), 404
    if session.result is not None:
        return jsonify({"error": "The job has already finished."}), 409
    session.cancelled.set()
    metrics.increment("jobs_cancel_requested")
    return jsonify({"status": "cancelling"})


@app.route("/review/<session_id>", methods=["POST"])
def review_session(session_id: str):
    session = sessions.get(session_id, g.identity)
    if session is None:
        return jsonify({"error": "Unknown session."}), 404
    if not session.result or session.result.get("status") != "done":
        return jsonify({"error": "The analysis is not complete."}), 409
    report = session.result["data"]
    allowed = {str(item.get("id")) for item in report.get("findings") or []}
    try:
        decisions = validate_review_decisions((request.get_json(silent=True) or {}).get("decisions"), allowed)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    review = {
        "reviewer": g.identity,
        "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "complete": len(decisions) == len(allowed) and bool(allowed),
        "decisions": decisions,
    }
    session.review = review
    report["human_review"] = review
    return jsonify({"review": review, "data": report})


@app.route("/compare", methods=["POST"])
def compare():
    data = request.get_json(silent=True) or {}
    left, right = data.get("left"), data.get("right")
    if not isinstance(left, dict) or not isinstance(right, dict):
        return jsonify({"error": "Two report objects are required."}), 400
    return jsonify({"comparison": compare_reports(left, right)})


@app.route("/metrics")
def metric_status():
    return jsonify(metrics.snapshot())


@app.route("/policy")
def policy_status():
    policy = config.ACTIVE_POLICY
    return jsonify({
        "name": policy.name,
        "max_classification": policy.max_classification,
        "web_grounding": policy.web_grounding,
        "raw_payload_logging": policy.raw_payload_logging,
        "allowed_uploads": policy.allowed_uploads,
        "description": policy.description,
    })


@app.route("/export", methods=["POST"])
def export():
    """Render the report or audit data into a designed Word or PDF download."""
    data = request.get_json(silent=True) or {}
    kind = "audit" if data.get("kind") == "audit" else "report"
    fmt = (data.get("format") or "docx").lower()
    payload = data.get("data")
    if not isinstance(payload, dict) or not payload:
        return jsonify({"error": "Nothing to export."}), 400
    filename = re.sub(r"[^A-Za-z0-9._-]+", "-", data.get("filename") or f"BRIEF-{kind}").strip("-") or f"BRIEF-{kind}"
    try:
        body, mime, ext = export_document(kind, payload, fmt)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        log.exception("export failed")
        return jsonify({"error": "The export could not be generated."}), 500
    return Response(body, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{filename}.{ext}"'})


@app.route("/progress/<session_id>")
def progress(session_id: str):
    """Server-sent events: each progress step as it happens, then the result or a timeout."""
    session = sessions.get(session_id, g.identity)
    if session is None:
        return jsonify({"error": "Unknown session. It may have expired; start the analysis again."}), 404

    def stream():
        sent = 0
        started = time.time()
        while True:
            while sent < len(session.progress):
                yield f"data: {json.dumps({'type': 'progress', **session.progress[sent]})}\n\n"
                sent += 1
            if session.result is not None:
                yield f"data: {json.dumps({'type': 'result', **session.result})}\n\n"
                return
            if time.time() - started > config.RUN_TIMEOUT_SECONDS:
                session.cancelled.set()
                yield f"data: {json.dumps({'type': 'result', 'status': 'error', 'message': 'Analysis timed out and cancellation was requested.'})}\n\n"
                return
            time.sleep(0.5)

    return Response(stream_with_context(stream()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    app.run(debug=config.ENVIRONMENT == "development", port=5000, threaded=True)
