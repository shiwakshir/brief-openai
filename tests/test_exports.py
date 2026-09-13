from export import export_document


def reviewed_report():
    return {
        "parsed": {"core_question": "How should the service be researched?", "research_mode": "market"},
        "confidence": {"confidence_score": 50, "confidence_label": "Fragile", "top_three_risks": ["Sample mismatch"]},
        "assurance": {
            "assurance_level": "limited",
            "metric_notice": "Heuristic output requiring review.",
            "limitations": ["Synthetic test"],
            "required_reviewer_decisions": ["Confirm the finding."],
        },
        "human_review": {
            "complete": True, "reviewer": "researcher", "reviewed_at": "2026-09-11T00:00:00Z",
            "decisions": [{"finding_id": "risk-1", "decision": "accepted",
                           "rationale": "Checked against the sampling specification.", "amendment": ""}],
        },
        "run_health": {"probe_models": ["test-model"], "step_errors": []},
    }


def reviewed_audit():
    return {
        "instrument_type": "survey",
        "summary": {"score": 80, "label": "Sound", "items_total": 1, "items_flagged": 0,
                    "high": 0, "medium": 0, "low": 0, "items_confirming": 0},
        "items": [{"id": "Q1", "text": "Tell me about your experience.", "issues": []}],
        "assurance": {"metric_notice": "Requires review.", "required_reviewer_decisions": ["Confirm."]},
        "human_review": {
            "complete": True, "reviewer": "researcher", "reviewed_at": "2026-09-11T00:00:00Z",
            "decisions": [],
        },
    }


def test_reviewed_report_exports_to_pdf_and_word():
    pdf, pdf_type, pdf_ext = export_document("report", reviewed_report(), "pdf")
    docx, docx_type, docx_ext = export_document("report", reviewed_report(), "docx")
    assert pdf.startswith(b"%PDF") and pdf_ext == "pdf" and pdf_type == "application/pdf"
    assert docx.startswith(b"PK") and docx_ext == "docx"


def test_reviewed_audit_exports_to_pdf_and_word():
    pdf, _, _ = export_document("audit", reviewed_audit(), "pdf")
    docx, _, _ = export_document("audit", reviewed_audit(), "docx")
    assert pdf.startswith(b"%PDF")
    assert docx.startswith(b"PK")


def test_pdf_preserves_accented_research_text():
    from io import BytesIO

    from pypdf import PdfReader

    report = reviewed_report()
    report["parsed"]["core_question"] = "Cum cercetăm gospodăriile din România și España?"
    pdf, _, _ = export_document("report", report, "pdf")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    assert "România" in text
    assert "España" in text


def test_pdf_preserves_latin_greek_cyrillic_and_cjk_text():
    from io import BytesIO

    from pypdf import PdfReader

    report = reviewed_report()
    report["parsed"]["core_question"] = "Zürich Müller Ελλάδα Кириллица 日本語 中文 Łódź Zoë Résumé"
    pdf, _, _ = export_document("report", report, "pdf")
    reader = PdfReader(BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    fonts = " ".join(
        str(font)
        for page in reader.pages
        for font in ((page.get("/Resources") or {}).get("/Font") or {}).values()
    )

    for value in ("Zürich", "Müller", "Ελλάδα", "Кириллица", "日本語", "中文", "Łódź", "Zoë", "Résumé"):
        assert value in text
    assert "DroidSansFallback" in fonts


def test_missing_confidence_score_exports_as_na_not_none_or_fifty():
    from io import BytesIO

    from pypdf import PdfReader

    report = reviewed_report()
    report["confidence"] = {
        "confidence_score": None,
        "confidence_label": "Insufficient data",
        "headline": "The research-design review could not be produced.",
        "top_three_risks": [],
    }
    pdf, _, _ = export_document("report", report, "pdf")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
    assert "n/a" in text
    assert "Insufficient data" in text
    assert "None" not in text

    docx_bytes, _, _ = export_document("report", report, "docx")
    import docx
    document = docx.Document(BytesIO(docx_bytes))
    score_cells = [cell.text.strip() for cell in document.tables[0].rows[0].cells]
    assert score_cells[0] == "n/a"
    assert "Insufficient data" in score_cells[1]
