"""Export JSON Schema for every contract to contracts/schema/ (repository root).

    python -m app.contracts.export [--check]

--check exits non-zero if the files on disk differ from the models (CI gate).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import (
    CONTRACT_VERSION,
    ErrorEnvelope,
    LabsParams,
    NotesParams,
    ToolRequest,
    ToolResponse,
    TurnClaims,
    TurnRequest,
    TurnResponse,
    WindowParams,
)
from .week2 import (
    Citation,
    FactReview,
    FinalClaim,
    IntakeExtractionEnvelope,
    LabExtractionEnvelope,
    PromoteReviewedDocumentCommand,
    PromoteReviewedDocumentResponse,
    ReleaseReport,
    ResolvedSource,
    ReviseReviewedRecordCommand,
    ReviseReviewedRecordResponse,
    ReviewFactCommand,
    ReviewedIntakeResponse,
    ReviewedLabReport,
    Week2Limitation,
    WorkerHandoffRequest,
    WorkerHandoffResult,
)

EXPORTS = {
    "tool_request.schema.json": ToolRequest,
    "tool_response.schema.json": ToolResponse,
    "window_params.schema.json": WindowParams,
    "notes_params.schema.json": NotesParams,
    "labs_params.schema.json": LabsParams,
    "turn_request.schema.json": TurnRequest,
    "turn_claims.schema.json": TurnClaims,
    "turn_response.schema.json": TurnResponse,
    "error_envelope.schema.json": ErrorEnvelope,
    "lab_extraction.schema.json": LabExtractionEnvelope,
    "intake_extraction.schema.json": IntakeExtractionEnvelope,
    "review_fact_command.schema.json": ReviewFactCommand,
    "fact_review.schema.json": FactReview,
    "promote_reviewed_document_command.schema.json": PromoteReviewedDocumentCommand,
    "promote_reviewed_document_response.schema.json": PromoteReviewedDocumentResponse,
    "revise_reviewed_record_command.schema.json": ReviseReviewedRecordCommand,
    "revise_reviewed_record_response.schema.json": ReviseReviewedRecordResponse,
    "reviewed_lab_report.schema.json": ReviewedLabReport,
    "reviewed_intake_response.schema.json": ReviewedIntakeResponse,
    "worker_handoff_request.schema.json": WorkerHandoffRequest,
    "worker_handoff_result.schema.json": WorkerHandoffResult,
    "resolved_source.schema.json": ResolvedSource,
    "citation.schema.json": Citation,
    "final_claim.schema.json": FinalClaim,
    "week2_limitation.schema.json": Week2Limitation,
    "release_report.schema.json": ReleaseReport,
}

WEEK2_EXPORTS = {
    name
    for name in EXPORTS
    if name
    not in {
        "tool_request.schema.json",
        "tool_response.schema.json",
        "window_params.schema.json",
        "notes_params.schema.json",
        "labs_params.schema.json",
        "turn_request.schema.json",
        "turn_claims.schema.json",
        "turn_response.schema.json",
        "error_envelope.schema.json",
    }
}


def render(model, contract_version: str = CONTRACT_VERSION) -> str:
    schema = model.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["x-contract-version"] = contract_version
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    out_dir = Path(__file__).resolve().parents[3] / "contracts" / "schema"
    check = "--check" in argv
    out_dir.mkdir(parents=True, exist_ok=True)
    drift = []
    for name, model in EXPORTS.items():
        path = out_dir / name
        content = render(model, "2.0.0" if name in WEEK2_EXPORTS else CONTRACT_VERSION)
        if check:
            if not path.exists() or path.read_text() != content:
                drift.append(name)
        else:
            path.write_text(content)
    if check and drift:
        print("schema drift (run `python -m app.contracts.export`): " + ", ".join(drift), file=sys.stderr)
        return 1
    print(("checked" if check else "wrote") + f" {len(EXPORTS)} schemas in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
