from app.metrics import Metrics


def test_document_metrics_keep_type_and_preview_outcome_bounded() -> None:
    metrics = Metrics()
    metrics.extraction("intake_form", "partial", 12.5, "medium")
    metrics.extraction("not-a-document", "leaked-status", 1.0, "unbounded")

    rendered = metrics.prometheus()

    assert 'copilot_document_extractions_total{document_type="intake_form",status="partial",confidence="medium"} 1' in rendered
    assert 'copilot_document_extractions_total{document_type="other",status="other",confidence="other"} 1' in rendered


def test_guideline_metrics_keep_intent_topic_and_limitations_bounded() -> None:
    metrics = Metrics()
    metrics.evidence_retrieval("guideline_evidence", "aaa", "completed", "none", 12.5)
    metrics.evidence_retrieval("leaked", "Jane-Doe", "surprise", "raw query text", 1.0)

    rendered = metrics.prometheus()

    assert 'copilot_guideline_retrievals_total{intent="guideline_evidence",topic="aaa",status="completed",limitation="none"} 1' in rendered
    assert 'copilot_guideline_retrievals_total{intent="other",topic="other",status="other",limitation="other"} 1' in rendered
