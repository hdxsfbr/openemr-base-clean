from app.metrics import Metrics


def test_document_metrics_keep_type_and_preview_outcome_bounded() -> None:
    metrics = Metrics()
    metrics.extraction("intake_form", "partial", 12.5, "medium")
    metrics.extraction("not-a-document", "leaked-status", 1.0, "unbounded")

    rendered = metrics.prometheus()

    assert 'copilot_document_extractions_total{document_type="intake_form",status="partial",confidence="medium"} 1' in rendered
    assert 'copilot_document_extractions_total{document_type="other",status="other",confidence="other"} 1' in rendered
