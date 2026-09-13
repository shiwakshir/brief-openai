import agent


EV_BRIEF = (
    "Research for a European car maker into electric vehicle adoption barriers among rural "
    "households in France, Spain and Romania. The client assumes range anxiety is the main "
    "barrier and that better public charging will unlock demand. Method: 30 in-depth "
    "interviews in each market."
)


def test_local_fallback_extracts_fields_and_hypotheses_from_prose(monkeypatch):
    monkeypatch.setattr(agent.config, "OPENAI_API_KEY", "")

    parsed = agent.parse_brief(EV_BRIEF)

    assert parsed["parse_status"] == "local_fallback"
    assert parsed["category"] == "electric vehicle adoption barriers"
    assert parsed["topic"] == "electric vehicle adoption barriers"
    assert parsed["target_audience"] == "rural households"
    assert parsed["geography"] == "France, Spain, Romania"
    assert parsed["client_hypotheses"] == [
        "range anxiety is the main barrier",
        "better public charging will unlock demand",
    ]
    assert "30 in-depth interviews" in parsed["sample_definition"]
    assert parsed["parse_warnings"]


def test_local_fallback_reads_labelled_brief_fields(monkeypatch):
    monkeypatch.setattr(agent.config, "OPENAI_API_KEY", "")
    brief = """Category: Retail banking
Specific topic: Opening a first current account
Audience: Students aged 18 to 21
Geography: UK
Objective: Understand how students choose an account
Sample: 24 students recruited through universities
Fieldwork: Manchester and Birmingham
Client hypotheses:
- Students choose primarily on the sign-up incentive
- Branch access does not matter
"""

    parsed = agent.parse_brief(brief)

    assert parsed["category"] == "Retail banking"
    assert parsed["topic"] == "Opening a first current account"
    assert parsed["target_audience"] == "Students aged 18 to 21"
    assert parsed["fieldwork_locations"] == "Manchester and Birmingham"
    assert len(parsed["client_hypotheses"]) == 2


def test_model_failure_uses_local_extraction_instead_of_unknown(monkeypatch):
    monkeypatch.setattr(agent.config, "OPENAI_API_KEY", "sk-test")

    def fail_parse(*_args, **_kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(agent, "step_parse", fail_parse)
    parsed = agent.parse_brief(EV_BRIEF)

    assert parsed["parse_status"] == "local_fallback"
    assert parsed["category"] != "Unknown"
    assert parsed["target_audience"] != "Unknown"
    assert parsed["client_hypotheses"]


def test_local_fallback_reads_inline_labelled_hypotheses(monkeypatch):
    monkeypatch.setattr(agent.config, "OPENAI_API_KEY", "")
    brief = (
        "Research into electric vehicle adoption barriers among rural households in France. "
        "Client hypotheses: range anxiety is the main barrier; better public charging will unlock demand."
    )

    parsed = agent.parse_brief(brief)

    assert parsed["client_hypotheses"] == [
        "range anxiety is the main barrier",
        "better public charging will unlock demand",
    ]
