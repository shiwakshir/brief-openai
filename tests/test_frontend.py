from pathlib import Path

import app as app_module
from test_security import auth


ROOT = Path(__file__).resolve().parents[1]


def test_full_research_workflow_is_present_on_homepage():
    response = app_module.app.test_client().get("/", headers=auth())
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    for element_id in (
        "brief-input", "guide-input", "rv-topic", "review-section", "progress-section",
        "review-parse-notice",
        "panel-contamination", "panel-archaeology", "panel-evidence",
        "panel-deliverables", "panel-review", "panel-areview",
    ):
        assert f'id="{element_id}"' in html
    assert "Reviewer sign-off" in html
    assert "Review a brief before fieldwork." in html
    assert "Internal tool" in html
    assert 'role="tab" aria-selected="true" aria-controls="brief-section"' in html
    assert 'role="tabpanel" aria-labelledby="tool-brief"' in html
    assert "onclick=" not in html
    assert "onchange=" not in html


def test_frontend_uses_csp_safe_external_event_wiring():
    javascript = (ROOT / "static" / "js" / "brief.js").read_text(encoding="utf-8")
    assert "onclick=" not in javascript
    assert "data-action" in javascript
    assert "data-upload-target" in javascript
    assert "function cancelRun" in javascript
    assert "function submitReview" in javascript
    assert "function renderDeliverables" in javascript
    assert "function renderEvidence" in javascript
    assert "function renderInternalRecommendation" in javascript
    assert "p.parse_warnings" in javascript
    assert "setAttribute('aria-selected'" in javascript
    assert "setAttribute('aria-pressed'" in javascript
    assert "function safeUrl" in javascript
    assert "p.topic = document.getElementById('rv-topic')" in javascript


def test_incomplete_hypothesis_classification_never_renders_as_zero():
    javascript = (ROOT / "static" / "js" / "brief.js").read_text(encoding="utf-8")
    assert "Number.isInteger(h.contamination_score)" in javascript
    assert "h.contamination_score||0" not in javascript
    assert "This hypothesis was not scored" in javascript


def test_csp_blocks_inline_scripts_but_allows_presentational_inline_styles():
    response = app_module.app.test_client().get("/health/live")
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "script-src 'self' 'unsafe-inline'" not in csp
    assert "style-src 'self' 'unsafe-inline'" in csp


def test_frontend_does_not_load_external_fonts():
    stylesheet = (ROOT / "static" / "css" / "brief.css").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in stylesheet
    assert "fonts.gstatic.com" not in stylesheet
