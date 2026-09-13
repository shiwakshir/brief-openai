import json

import agent
import web_grounding
from evaluate import check, metrics, thresholds_pass
import pytest


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


def test_low_overall_answer_coverage_withholds_every_score(monkeypatch):
    query_data = {
        "base_responses": [{"model": "m1", "response": "Cost matters."}],
        "persona_responses": [],
        "models": ["m1"],
        "expected_answers": 10,
        "expected_per_model": {"m1": 10},
    }
    monkeypatch.setattr(agent, "call_json", lambda *args, **kwargs: pytest.fail("classifier should not run"))
    item = agent.step_convergence({"client_hypotheses": ["Cost is the barrier"]}, query_data)["hypotheses"][0]
    assert item["classification_status"] == "insufficient_coverage"
    assert item["measured_score"] is None
    assert "1/10" in item["classification_errors"][0]


def test_silent_model_withholds_scores_even_when_overall_coverage_passes(monkeypatch):
    responses = [
        {"model": "m1", "response": f"Answer {number}"}
        for number in range(9)
    ] + [
        {"model": "m2", "response": f"Answer {number}"}
        for number in range(7)
    ]
    query_data = {
        "base_responses": responses,
        "persona_responses": [],
        "models": ["m1", "m2"],
        "expected_answers": 20,
        "expected_per_model": {"m1": 10, "m2": 10},
    }
    monkeypatch.setattr(agent, "call_json", lambda *args, **kwargs: pytest.fail("classifier should not run"))
    result = agent.step_convergence({"client_hypotheses": ["Cost is the barrier"]}, query_data)
    assert result["answer_coverage"]["ratio"] == 0.8
    assert result["answer_coverage"]["per_model"]["m2"]["ratio"] == 0.7
    assert result["hypotheses"][0]["classification_status"] == "insufficient_coverage"


def test_run_stops_when_every_probe_call_fails(monkeypatch):
    parsed = {
        "category": "banking", "topic": "bank applications", "core_question": "Why do people stop?",
        "target_audience": "Adults", "geography": "UK", "client_hypotheses": ["It takes too long"],
    }
    monkeypatch.setattr(agent, "step_generate", lambda *_: ["Why do applications fail?"])
    monkeypatch.setattr(agent, "step_query", lambda *_: {
        "base_responses": [], "persona_responses": [], "models": ["m"],
        "expected_answers": 5, "expected_per_model": {"m": 5},
    })
    with pytest.raises(agent.NoModelAnswersError, match="stopped without creating a report"):
        agent.run_brief("A sufficiently detailed brief for an offline test.", parsed_override=parsed)


def test_reduced_prompt_set_is_measured_against_the_designed_prompt_count(monkeypatch):
    monkeypatch.setattr(agent, "call_model", lambda *args, **kwargs: "A probe answer")
    query_data = agent.step_query(
        ["Only one generated prompt"],
        {"topic": "banking", "core_question": "Why do people stop?"},
        ["m"],
    )
    coverage = agent.answer_coverage(query_data)
    assert query_data["expected_per_model"] == {"m": 10}
    assert coverage["collected"] == 5
    assert coverage["ratio"] == 0.5
    assert coverage["ok"] is False


def test_failed_prompt_generation_is_recorded_and_scores_are_withheld(monkeypatch):
    parsed = {
        "category": "banking", "topic": "bank applications", "core_question": "Why do people stop?",
        "target_audience": "Adults", "geography": "UK", "client_hypotheses": ["It takes too long"],
    }

    def fail_generate(*_):
        raise RuntimeError("prompt generation failed")

    responses = [{"model": "m", "response": f"Answer {number}"} for number in range(5)]
    monkeypatch.setattr(agent, "step_generate", fail_generate)
    monkeypatch.setattr(agent, "step_query", lambda *_: {
        "base_responses": responses, "persona_responses": [], "models": ["m"],
        "expected_answers": 10, "expected_per_model": {"m": 10},
    })
    monkeypatch.setattr(agent, "step_cluster", lambda *_: {})
    monkeypatch.setattr(agent, "step_gap_analysis", lambda *_: {})
    monkeypatch.setattr(agent, "step_hypothesis_contamination", lambda *args: agent._contamination_fallback(args[0], args[-1]))
    monkeypatch.setattr(agent, "step_assumption_archaeology", lambda *_: {})
    monkeypatch.setattr(agent, "step_temporal_drift", lambda *_: {})
    monkeypatch.setattr(agent, "step_competitor_intelligence", lambda *_: {})
    monkeypatch.setattr(agent, "step_qual_quant_routing", lambda *_: {})
    monkeypatch.setattr(agent, "step_confidence", lambda *_: {
        "confidence_score": 40, "confidence_label": "Fragile", "headline": "Review", "top_three_risks": []
    })
    monkeypatch.setattr(agent, "step_deliverables", lambda *_: {})
    result = agent.run_brief("A sufficiently detailed brief for testing.", parsed_override=parsed)
    assert result["convergence"]["hypotheses"][0]["measured_score"] is None
    assert result["run_health"]["status"] in {"degraded", "invalid"}
    assert any(error["step"] == "generate" for error in result["run_health"]["step_errors"])
    assert result["run_health"]["prompt_generation"] == {
        "designed": 6, "used": 1, "error": "prompt generation failed"
    }


def test_failed_contamination_explanation_preserves_ids_and_valid_measured_scores():
    parsed = {"client_hypotheses": ["Cost is the main barrier", "A sixth claim"]}
    records = agent._hypothesis_records(parsed)
    convergence = {"hypotheses": [{
        **records[0],
        "classification_status": "valid", "measured_score": 70, "main": 7, "mentions": 1,
        "n_answers": 10, "presence_pct": 80, "per_model": {"m": {"main": 7}},
        "quotes": [{"model": "m", "quote": "Cost is the main issue."}],
    }, {
        **records[1],
        "classification_status": "unassessed", "measured_score": None,
    }]}
    fallback = agent._contamination_fallback(parsed, convergence)
    by_id = {item["hypothesis_id"]: item for item in fallback["hypotheses_assessed"]}
    assert set(by_id) == {record["hypothesis_id"] for record in records}
    assert by_id[records[0]["hypothesis_id"]]["contamination_score"] == 70
    assert by_id[records[0]["hypothesis_id"]]["evidence_quotes"] == ["Cost is the main issue."]
    assert by_id[records[1]["hypothesis_id"]]["contamination_score"] is None


def test_failed_confidence_step_never_invents_a_midpoint_score(monkeypatch):
    parsed = {
        "category": "banking", "topic": "bank applications", "core_question": "Why do people stop?",
        "target_audience": "Adults", "geography": "UK", "client_hypotheses": [],
    }
    monkeypatch.setattr(agent, "step_generate", lambda *_: [f"Prompt {number}" for number in range(6)])
    monkeypatch.setattr(agent, "step_query", lambda *_: {
        "base_responses": [{"model": "m", "response": "Answer"}], "persona_responses": [],
        "models": ["m"], "expected_answers": 1, "expected_per_model": {"m": 1},
    })
    monkeypatch.setattr(agent, "step_convergence", lambda *_: {"hypotheses": [], "answer_coverage": {"ok": True}})
    for name in ("step_cluster", "step_gap_analysis", "step_hypothesis_contamination",
                 "step_assumption_archaeology", "step_temporal_drift", "step_competitor_intelligence",
                 "step_qual_quant_routing", "step_deliverables"):
        monkeypatch.setattr(agent, name, lambda *_: {})
    monkeypatch.setattr(agent, "step_confidence", lambda *_: (_ for _ in ()).throw(RuntimeError("failed")))
    result = agent.run_brief("A sufficiently detailed brief for testing.", parsed_override=parsed)
    assert result["confidence"]["confidence_score"] is None
    assert result["confidence"]["confidence_label"] == "Insufficient data"
    assert result["run_health"]["status"] == "invalid"
    assert result["internal_recommendation"]["decision"] == "hold"


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


def test_evaluator_ignores_unlisted_fields_and_wildcard_detects_real_findings():
    case = {"id": "clean", "forbidden_findings": [{
        "category": "risk_to_fieldwork", "phrases": ["*"]
    }]}
    ignored = check(case, {"parsed": {"core_question": "price"}, "debug": {"risk": "price"}})
    assert ignored["forbidden"][0]["passed"] is True
    detected = check(case, {"confidence": {"top_three_risks": ["The sample excludes older people."]}})
    assert detected["forbidden"][0]["passed"] is False


def test_evaluator_checks_unassessed_hypotheses_structurally():
    case = {"id": "six", "expect_unassessed": 1, "expect_hypotheses_preserved": 6}
    assessed = [{"hypothesis": f"H{number}"} for number in range(6)]
    passed = check(case, {"run_health": {"unassessed_hypotheses": 1},
                          "contamination": {"hypotheses_assessed": assessed}})
    failed = check(case, {"run_health": {"unassessed_hypotheses": 0},
                          "contamination": {"hypotheses_assessed": assessed[:5]}})
    assert passed["structural"][0]["passed"] is True
    assert all(item["passed"] for item in passed["structural"])
    assert not any(item["passed"] for item in failed["structural"])
    assert thresholds_pass(metrics([failed]), 0, 0) is False


def test_contamination_fallback_preserves_parsed_hypotheses_missing_from_convergence():
    parsed = {"client_hypotheses": ["First", "Second"]}
    first = agent._hypothesis_records(parsed)[0]
    fallback = agent._contamination_fallback(parsed, {"hypotheses": [{
        **first, "classification_status": "valid", "measured_score": 60,
        "main": 1, "mentions": 1, "n_answers": 2,
    }]})
    assert [item["hypothesis"] for item in fallback["hypotheses_assessed"]] == ["First", "Second"]
    assert fallback["hypotheses_assessed"][0]["contamination_score"] == 60
    assert fallback["hypotheses_assessed"][1]["contamination_score"] is None


def test_evaluator_does_not_score_repeated_screener_criteria():
    case = {"id": "echo", "expected_findings": [{
        "category": "deliverables", "phrases": ["existing customers aged 25 to 40"]
    }]}
    card = check(case, {"deliverables": {"screener_criteria": [{
        "criterion": "Existing customers aged 25 to 40", "why": ""
    }]}})
    assert card["expected"][0]["passed"] is False


def test_checked_in_negative_expectations_do_not_use_wildcards():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "evals" / "labelled_cases.json").read_text(encoding="utf-8"))
    cases += json.loads((root / "evals" / "synthetic_research_cases.json").read_text(encoding="utf-8"))
    for case in cases:
        for label in case.get("forbidden_findings", []):
            assert "*" not in label.get("phrases", []), case["id"]
