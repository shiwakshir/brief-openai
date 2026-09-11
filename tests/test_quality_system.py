import base64

import app as app_module
from comparison import compare_reports
from contracts import validate_report, validate_review_decisions
from policy import enforce, get_policy
from rules import audit_instrument, check_item
from limits import SlidingWindowLimiter


def auth(user):
    token = base64.b64encode(f"{user}:test-password".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def test_deterministic_scale_rules_are_explainable():
    issues = check_item({
        "id": "Q1", "kind": "scale", "text": "How helpful and easy was it?",
        "answer_options": ["Strongly agree", "Agree", "Neutral"],
    })
    ids = {issue["rule_id"] for issue in issues}
    assert "wording.conjunction" in ids
    assert "scale.balance.agreement" in ids
    assert all(issue["source"] == "deterministic_rule" for issue in issues)


def test_clean_open_question_has_no_rule_findings():
    assert audit_instrument([{"id": "Q1", "kind": "open", "text": "Tell me about the last time you chose a bank."}]) == {"Q1": []}


def test_report_contract_rejects_overstated_assurance():
    result = {
        "run_health": {}, "parsed": {}, "confidence": {"confidence_score": 50},
        "contamination": {}, "methodology": {},
        "assurance": {"assurance_level": "high", "human_review_required": False},
    }
    errors = validate_report(result)
    assert any("assurance_level" in error for error in errors)
    assert any("human_review_required" in error for error in errors)


def test_review_contract_requires_reasoned_decisions():
    try:
        validate_review_decisions([{"finding_id": "risk-1", "decision": "accepted", "rationale": "ok"}], {"risk-1"})
    except ValueError as exc:
        assert "rationale" in str(exc)
    else:
        raise AssertionError("Short unreasoned decision was accepted")


def test_comparison_warns_across_prompt_versions():
    left = {"run_health": {"prompt_version": "v1"}, "confidence": {"top_three_risks": ["A"]}}
    right = {"run_health": {"prompt_version": "v2"}, "confidence": {"top_three_risks": ["B"]}}
    result = compare_reports(left, right)
    assert result["comparable"] is False
    assert result["notice"]
    assert result["changed"][0]["id"] == "risk-1"


def test_confidential_policy_forbids_web_and_raw_logging():
    policy = get_policy("internal_confidential")
    for web, raw in ((True, False), (False, True)):
        try:
            enforce(policy, web_grounding=web, raw_payload_logging=raw)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Unsafe policy override was accepted")


def test_review_is_owned_and_attributed():
    session_id = app_module.sessions.create("alice")
    session = app_module.sessions.get(session_id, "alice")
    session.result = {"status": "done", "data": {
        "findings": [{"id": "risk-1", "statement": "Risk"}]
    }}
    client = app_module.app.test_client()
    denied = client.post(f"/review/{session_id}", headers=auth("bob"), json={"decisions": []})
    assert denied.status_code == 404
    accepted = client.post(f"/review/{session_id}", headers=auth("alice"), json={"decisions": [{
        "finding_id": "risk-1", "decision": "accepted",
        "rationale": "Confirmed against the approved sampling specification.",
        "amendment": "",
    }]})
    assert accepted.status_code == 200
    review = accepted.get_json()["review"]
    assert review["complete"] is True
    assert review["reviewer"] == "alice"


def test_policy_endpoint_exposes_non_secret_controls():
    response = app_module.app.test_client().get("/policy", headers=auth("alice"))
    assert response.status_code == 200
    assert response.get_json()["name"] == "internal_confidential"


def test_per_user_rate_limit_isolated_by_identity():
    limiter = SlidingWindowLimiter(2, 3600)
    assert limiter.allow("alice", now=100)
    assert limiter.allow("alice", now=101)
    assert not limiter.allow("alice", now=102)
    assert limiter.allow("bob", now=102)
    assert limiter.allow("alice", now=4001)
