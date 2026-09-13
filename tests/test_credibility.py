from credibility import audit_assurance, brief_assurance


def test_clean_full_run_is_never_presented_as_high_assurance():
    assurance = brief_assurance(
        run_health={
            "quick_mode": False,
            "step_errors": [],
            "answers_collected": 20,
            "grounded": True,
            "probe_models": ["model-a", "model-b"],
            "prompt_version": "v1",
        },
        convergence={},
        archaeology={"sources": [{"url": "https://example.test"}], "hypothesis_evidence": []},
        confidence={"confidence_score": 72, "confidence_label": "Adequate"},
    )
    assert assurance["assurance_level"] == "moderate"
    assert assurance["human_review_required"] is True
    assert assurance["review_indicator"]["name"] == "Research design review indicator"
    assert "not validated" in assurance["metric_notice"]


def test_quick_ungrounded_run_is_limited():
    assurance = brief_assurance(
        run_health={
            "quick_mode": True,
            "step_errors": [],
            "answers_collected": 6,
            "grounded": False,
            "probe_models": ["model-a"],
            "prompt_version": "v1",
        },
        convergence={},
        archaeology={},
        confidence={"confidence_score": 50, "confidence_label": "Fragile"},
    )
    assert assurance["assurance_level"] == "limited"
    assert len(assurance["limitations"]) >= 3


def test_failed_stage_is_explicitly_limited():
    assurance = brief_assurance(
        run_health={
            "quick_mode": False,
            "step_errors": [{"step": "gaps"}],
            "answers_collected": 20,
            "grounded": True,
        },
        convergence={},
        archaeology={},
        confidence={},
    )
    assert assurance["assurance_level"] == "limited"
    assert any("failed" in item for item in assurance["limitations"])


def test_instrument_assurance_requires_human_review():
    assurance = audit_assurance({"items": [{"id": "Q1"}]}, "v1")
    assert assurance["assurance_level"] == "moderate"
    assert assurance["human_review_required"] is True
    assert assurance["evidence_basis"]["items_reviewed"] == 1
