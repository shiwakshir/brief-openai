from decision import internal_recommendation


def brief_report(score=80, **health_overrides):
    health = {
        "status": "complete", "answers_collected": 20, "classification_failures": 0,
        "step_errors": [],
    }
    health.update(health_overrides)
    return {
        "run_health": health,
        "confidence": {"confidence_score": score},
        "contamination": {"overall_contamination_level": "Low"},
        "assurance": {"assurance_level": "moderate"},
        "gaps": {"sample_cannot_test": []},
    }


def test_clean_internal_brief_can_proceed_to_planning():
    recommendation = internal_recommendation(brief_report())
    assert recommendation["decision"] == "proceed"
    assert recommendation["review_status"] == "provisional"
    assert recommendation["scope"] == "internal_research_workflow"


def test_incomplete_classification_holds_fieldwork():
    recommendation = internal_recommendation(brief_report(classification_failures=1))
    assert recommendation["decision"] == "hold"
    assert any("insufficient classification" in reason for reason in recommendation["reasons"])


def test_middle_score_recommends_changes_without_calling_it_truth():
    recommendation = internal_recommendation(brief_report(score=62))
    assert recommendation["decision"] == "proceed_with_changes"
    assert "not client advice" in recommendation["notice"]
    assert "validated statement of truth" in recommendation["notice"]


def test_researcher_review_changes_status_not_the_computed_recommendation():
    report = brief_report()
    report["human_review"] = {"complete": True}
    recommendation = internal_recommendation(report)
    assert recommendation["decision"] == "proceed"
    assert recommendation["review_status"] == "reviewed"


def test_guide_with_high_severity_issue_is_held():
    report = {"items": [{}], "summary": {
        "score": 85, "high": 1, "untested_hypotheses": [], "confirmed_only_hypotheses": [],
    }}
    assert internal_recommendation(report)["decision"] == "hold"


def test_clean_guide_can_proceed():
    report = {"items": [{}], "summary": {
        "score": 90, "high": 0, "untested_hypotheses": [], "confirmed_only_hypotheses": [],
    }}
    assert internal_recommendation(report)["decision"] == "proceed"
