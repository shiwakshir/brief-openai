import base64
import io
import os
import pytest

os.environ.setdefault("BRIEF_ENVIRONMENT", "test")
os.environ.setdefault("BRIEF_PASSWORD", "test-password")
os.environ.setdefault("BRIEF_LOG_RAW_PAYLOADS", "false")

import app as app_module
from documents import UnsupportedFileType, extract_text


def auth(user="researcher"):
    token = base64.b64encode(f"{user}:test-password".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_liveness_is_available_without_authentication():
    client = app_module.app.test_client()
    response = client.get("/health/live")
    assert response.status_code == 200


def test_application_routes_require_authentication():
    client = app_module.app.test_client()
    assert client.get("/").status_code == 401
    assert client.get("/", headers=auth()).status_code == 200


def test_insecure_development_mode_is_loopback_only(monkeypatch):
    monkeypatch.setattr(app_module.config, "BRIEF_PASSWORD", "")
    monkeypatch.setattr(app_module.config, "TRUST_AUTH_PROXY", False)
    monkeypatch.setattr(app_module.config, "ALLOW_INSECURE_DEVELOPMENT", True)
    monkeypatch.setattr(app_module.config, "ENVIRONMENT", "development")
    client = app_module.app.test_client()
    assert client.get("/", environ_base={"REMOTE_ADDR": "127.0.0.1"}).status_code == 200
    assert client.get("/", environ_base={"REMOTE_ADDR": "192.0.2.10"}).status_code == 403


def test_insecure_development_mode_rejects_forwarded_loopback_requests(monkeypatch):
    monkeypatch.setattr(app_module.config, "BRIEF_PASSWORD", "")
    monkeypatch.setattr(app_module.config, "TRUST_AUTH_PROXY", False)
    monkeypatch.setattr(app_module.config, "ALLOW_INSECURE_DEVELOPMENT", True)
    monkeypatch.setattr(app_module.config, "ENVIRONMENT", "development")
    client = app_module.app.test_client()
    for header in ("Forwarded", "X-Forwarded-For", "X-Real-IP"):
        response = client.get(
            "/", headers={header: "203.0.113.9"}, environ_base={"REMOTE_ADDR": "127.0.0.1"}
        )
        assert response.status_code == 403


def test_debugger_is_disabled_by_default():
    assert app_module.config.DEBUG is False


def test_debugger_is_forbidden_outside_development(monkeypatch):
    monkeypatch.setattr(app_module.config, "ENVIRONMENT", "production")
    monkeypatch.setattr(app_module.config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(app_module.config, "BRIEF_PASSWORD", "test-password")
    monkeypatch.setattr(app_module.config, "ALLOW_INSECURE_DEVELOPMENT", False)
    monkeypatch.setattr(app_module.config, "DEBUG", True)
    with pytest.raises(RuntimeError, match="BRIEF_DEBUG"):
        app_module.config.validate_startup()


def test_security_headers_are_present():
    response = app_module.app.test_client().get("/health/live")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_sessions_are_bound_to_owner():
    store = app_module.SessionStore(60)
    session_id = store.create("alice")
    assert store.get(session_id, "alice") is not None
    assert store.get(session_id, "bob") is None
    assert len(session_id) == 32


def test_rejects_mismatched_file_signature():
    try:
        extract_text("brief.pdf", b"not a pdf")
    except UnsupportedFileType:
        pass
    else:
        raise AssertionError("Expected an invalid PDF to be rejected")


def test_small_text_upload_is_processed_without_persistence():
    client = app_module.app.test_client()
    response = client.post(
        "/extract",
        headers=auth(),
        data={"file": (io.BytesIO(b"A sufficiently detailed research brief for safe extraction and review."), "brief.txt")},
    )
    assert response.status_code == 200
    assert "text" in response.get_json()
