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

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

import config
from agent import parse_brief, run_brief
from audit import run_audit
from documents import UnsupportedFileType, extract_text
from export import export_document

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("brief.app")

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@dataclass
class Session:
    created: float = field(default_factory=time.time)
    progress: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None


class SessionStore:
    """In-memory sessions with time-based expiry. One process only."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        self.expire()
        session_id = os.urandom(8).hex()
        with self._lock:
            self._sessions[session_id] = Session()
        return session_id

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def expire(self) -> None:
        now = time.time()
        with self._lock:
            stale = [sid for sid, s in self._sessions.items() if now - s.created > self._ttl]
            for sid in stale:
                self._sessions.pop(sid, None)


sessions = SessionStore(config.SESSION_TTL_SECONDS)


def _start_background(session_id: str, work) -> None:
    """Run `work(on_progress)` in a thread and store its result on the session."""
    session = sessions.get(session_id)

    def on_progress(step_name: str, step_number: int, total_steps: int) -> None:
        session.progress.append({
            "step": step_name, "number": step_number, "total": total_steps,
            "pct": int(step_number / total_steps * 100),
        })

    def run() -> None:
        try:
            session.result = {"status": "done", "data": work(on_progress)}
        except Exception as exc:  # any agent failure must reach the user
            log.exception("background run failed")
            session.result = {"status": "error", "message": str(exc)}

    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

@app.before_request
def require_password():
    """Optional shared password for hosted testing. Unset BRIEF_PASSWORD to run open."""
    if not config.BRIEF_PASSWORD:
        return None
    auth = request.authorization
    if auth and auth.password == config.BRIEF_PASSWORD:
        return None
    return Response("Password required", 401, {"WWW-Authenticate": 'Basic realm="BRIEF"'})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/extract", methods=["POST"])
def extract():
    upload = request.files.get("file")
    if not upload:
        return jsonify({"error": "No file received."}), 400
    try:
        text = extract_text(upload.filename or "", upload.read())
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

    session_id = sessions.create()
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

    session_id = sessions.create()
    _start_background(session_id, lambda on_progress: run_audit(
        instrument, brief, mode, progress_callback=on_progress,
    ))
    return jsonify({"session_id": session_id})


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
    except Exception as exc:
        log.exception("export failed")
        return jsonify({"error": f"Export failed: {exc}"}), 500
    return Response(body, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{filename}.{ext}"'})


@app.route("/progress/<session_id>")
def progress(session_id: str):
    """Server-sent events: each progress step as it happens, then the result or a timeout."""
    session = sessions.get(session_id)
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
                yield f"data: {json.dumps({'type': 'result', 'status': 'error', 'message': 'Analysis timed out. Please try again with a shorter brief.'})}\n\n"
                return
            time.sleep(0.5)

    return Response(stream_with_context(stream()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
