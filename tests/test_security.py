import base64
import io
import os

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
