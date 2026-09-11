import json

import agent
import web_grounding
from evaluate import check, metrics, thresholds_pass


def _query_data():
    return {
        "base_responses": [
            {"model": "m", "response": "Cost is the main barrier."},
            {"model": "m", "response": "Cost matters among other factors."},
        ],
        "persona_responses": [],
        "models": ["m"],
    }


def test_missing_classifier_rows_produce_insufficient_data(monkeypatch):
    monkeypatch.setattr(agent, "call_json", lambda *args, **kwargs: {"verdicts": []})
    result = agent.step_convergence({"client_hypotheses": ["Cost is the barrier"]}, _query_data())
    measured = result["hypotheses"][0]
    assert measured["classification_status"] == "insufficient_data"
    assert measured["measured_score"] is None
    assert measured["absent"] is None


def test_duplicate_or_invalid_classifier_rows_do_not_create_a_score(monkeypatch):
    monkeypatch.setattr(agent, "call_json", lambda *args, **kwargs: {"verdicts": [
        {"answer": 1, "verdict": "main"},
        {"answer": 1, "verdict": "not-sure"},
    ]})
    measured = agent.step_convergence(
        {"client_hypotheses": ["Cost is the barrier"]}, _query_data()
    )["hypotheses"][0]
    assert measured["classification_status"] == "insufficient_data"
    assert measured["measured_score"] is None


def test_sixth_hypothesis_is_preserved_and_marked_unassessed(monkeypatch):
    hypotheses = [f"Hypothesis {number}" for number in range(1, 7)]
    monkeypatch.setattr(agent, "call_json", lambda *args, **kwargs: {"verdicts": [
        {"answer": 1, "verdict": "absent"},
        {"answer": 2, "verdict": "absent"},
    ]})
    parsed = agent._attach_hypothesis_ids({"client_hypotheses": hypotheses})
    assert parsed["client_hypotheses"] == hypotheses
    assert len(parsed["hypothesis_records"]) == 6
    result = agent.step_convergence(parsed, _query_data())
    assert len(result["hypotheses"]) == 6
    assert result["hypotheses"][5]["hypothesis"] == "Hypothesis 6"
    assert result["hypotheses"][5]["classification_status"] == "unassessed"
    assert result["hypotheses"][5]["measured_score"] is None
    explanations = [{**record, "explanation": "Reviewed", "evidence_quotes": []}
                    for record in parsed["hypothesis_records"]]
    monkeypatch.setattr(agent, "call_json", lambda *args, **kwargs: {
        "hypotheses_assessed": explanations, "overall_contamination_level": "Low"
    })
    contamination = agent.step_hypothesis_contamination(parsed, {}, _query_data(), result)
    assert len(contamination["hypotheses_assessed"]) == 6
    assert contamination["hypotheses_assessed"][5]["score_label"] == "Unassessed"
    assert contamination["hypotheses_assessed"][5]["contamination_score"] is None


def test_explanations_are_joined_by_hypothesis_id_not_position(monkeypatch):
    parsed = {"client_hypotheses": ["First claim", "Second claim"]}
    records = agent._hypothesis_records(parsed)
    convergence = {"models": ["m"], "hypotheses": [
        {**records[0], "classification_status": "valid", "measured_score": 90,
         "main": 2, "mentions": 0, "disputes": 0, "absent": 0, "n_answers": 2,
         "presence_pct": 100, "per_model": {}, "quotes": []},
        {**records[1], "classification_status": "valid", "measured_score": 10,
         "main": 0, "mentions": 0, "disputes": 0, "absent": 2, "n_answers": 2,
         "presence_pct": 0, "per_model": {}, "quotes": []},
    ]}
    reversed_explanations = {"hypotheses_assessed": [
        {**records[1], "explanation": "second", "evidence_quotes": []},
        {**records[0], "explanation": "first", "evidence_quotes": []},
    ], "overall_contamination_level": "Low"}
    monkeypatch.setattr(agent, "call_json", lambda *args, **kwargs: reversed_explanations)
    result = agent.step_hypothesis_contamination(parsed, {}, _query_data(), convergence)
    by_id = {item["hypothesis_id"]: item for item in result["hypotheses_assessed"]}
    assert by_id[records[0]["hypothesis_id"]]["contamination_score"] == 90
    assert by_id[records[1]["hypothesis_id"]]["contamination_score"] == 10


def test_missing_explanation_is_completed_without_inventing_a_score(monkeypatch):
    parsed = {"client_hypotheses": ["Cost is the barrier"]}
    record = agent._hypothesis_records(parsed)[0]
    convergence = {"models": ["m"], "hypotheses": [{
        **record, "classification_status": "insufficient_data", "measured_score": None,
        "main": None, "mentions": None, "disputes": None, "absent": None,
        "n_answers": 2, "presence_pct": None, "per_model": {}, "quotes": [],
    }]}
    monkeypatch.setattr(agent, "call_json", lambda *args, **kwargs: {
        "hypotheses_assessed": [], "overall_contamination_level": "Low"
    })
    result = agent.step_hypothesis_contamination(parsed, {}, _query_data(), convergence)
    item = result["hypotheses_assessed"][0]
    assert item["contamination_score"] is None
    assert item["score_label"] == "Insufficient data"
    assert result["overall_contamination_level"] == "Insufficient data"
    assert result["explanation_contract_errors"]


def test_hypothesis_grounding_requires_each_finding_url_to_be_retrieved(monkeypatch):
    answer = json.dumps({"verdict": "supported", "summary": "Evidence exists.", "countries": [{
        "country": "UK", "verdict": "supported",
        "for": [{"finding": "A study supports it.", "source": "Study", "url": "https://example.test/study", "year": "2025"}],
        "against": [],
    }]})
    monkeypatch.setattr(web_grounding, "retrieve", lambda *args, **kwargs: {
        "answer": answer, "citations": []
    })
    result = web_grounding.retrieve_hypothesis_evidence("Claim", "Adults", "UK")
    assert result["grounded"] is False
    assert result["countries"][0]["for"][0]["source_retrieved"] is False
    assert result["human_verified"] is False

    monkeypatch.setattr(web_grounding, "retrieve", lambda *args, **kwargs: {
        "answer": answer,
        "citations": [{"title": "Study", "url": "https://example.test/study", "snippet": "Evidence"}],
    })
    retrieved = web_grounding.retrieve_hypothesis_evidence("Claim", "Adults", "UK")
    assert retrieved["grounded"] is True
    assert retrieved["countries"][0]["for"][0]["source_retrieved"] is True
    assert retrieved["verification_status"] == "unverified"
    assert retrieved["human_verified"] is False


def test_citation_urls_are_limited_to_http_and_https():
    assert web_grounding._clean_url("javascript:alert(1)") == ""
    assert web_grounding._clean_url("/relative/source") == ""
    assert web_grounding._clean_url("https://example.test/study?utm_source=x&year=2025") == \
        "https://example.test/study?year=2025"


def test_specific_topic_is_preserved_and_used_for_probe_generation(monkeypatch):
    calls = []

    def fake_json(step, system, user, **kwargs):
        calls.append((step, system, user))
        if step == "01_parse":
            return {
                "core_question": "Why do people choose fresh fish?",
                "category": "supermarket grocery shopping",
                "topic": "buying fresh fish at the supermarket",
                "target_audience": "UK shoppers",
                "geography": "UK",
                "client_hypotheses": ["Freshness drives choice"],
            }
        return {"prompts": ["How do I choose fresh fish?"] * 6}

    monkeypatch.setattr(agent, "call_json", fake_json)
    parsed = agent.step_parse("A detailed research brief " * 4)
    agent.step_generate(parsed)
    assert parsed["topic"] == "buying fresh fish at the supermarket"
    assert "Specific topic (use this, not the broad category): buying fresh fish at the supermarket" in calls[-1][2]


def test_topic_falls_back_and_reference_prompt_refinements_are_present(monkeypatch):
    captured = {}

    def fake_json(step, system, user, **kwargs):
        captured[step] = system
        if step == "01_parse":
            return {
                "core_question": "Question", "category": "payments", "target_audience": "Adults",
                "geography": "UK", "client_hypotheses": [], "product_or_service": "",
            }
        if step == "05_gaps":
            return {"overrepresented": [], "underrepresented": [], "audience_mismatch": "",
                    "sample_cannot_test": []}
        return {"confidence_score": 50, "confidence_label": "Fragile", "headline": "Review",
                "top_three_risks": []}

    monkeypatch.setattr(agent, "call_json", fake_json)
    parsed = agent.step_parse("A detailed research brief " * 4)
    assert parsed["topic"] == "payments"
    agent.step_gap_analysis(parsed, {})
    agent.step_confidence(parsed, {}, {}, {}, {}, {}, {})
    assert "lapsed people" in captured["05_gaps"]
    assert "Check the direction" in captured["11_confidence"]


def test_deliverable_titles_preserve_known_acronyms(monkeypatch):
    monkeypatch.setattr(agent, "call_json", lambda *args, **kwargs: {
        "challenge_note": {"title": "improving uk ux with ai"},
        "discussion_guide_probes": [], "screener_criteria": [],
    })
    result = agent.step_deliverables({}, {}, {}, {}, {}, {})
    assert result["challenge_note"]["title"] == "Improving UK UX with AI"


def test_evaluator_does_not_reward_repeating_the_input_and_enforces_thresholds():
    case = {"id": "echo", "expected_findings": [{
        "category": "risk_to_fieldwork", "phrases": ["lack financial literacy"]
    }], "forbidden_findings": []}
    card = check(case, {"parsed": {"client_hypotheses": ["Customers lack financial literacy"]}})
    assert card["expected"][0]["passed"] is False
    summary = metrics([card])
    assert thresholds_pass(summary, .8, .8) is False
