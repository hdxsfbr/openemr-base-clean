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
    EvidenceQuery,
    EvidenceWorkerResult,
    GuidelineCandidate,
    GuidelineCitation,
    GuidelineEvidenceClaim,
    GuidelineEvidenceRequest,
    GuidelineEvidenceResponse,
    GuidelineExcerpt,
    GuidelineRetrievalLimitation,
    GuidelineSourceRequest,
    GuidelineSourceResponse,
    AnswerReadinessResult,
    DispatchRecord,
    HandoffCompletion,
    RouteDecision,
    SupervisorRequestState,
    IntakeExtraction,
    IntakeExtractionResult,
    LabExtraction,
    LabExtractionResult,
    LabsParams,
    NotesParams,
    ToolRequest,
    ToolResponse,
    TurnClaims,
    TurnRequest,
    TurnResponse,
    WindowParams,
    UploadIntent,
    UploadResult,
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
    "lab_extraction.schema.json": LabExtraction,
    "lab_extraction_result.schema.json": LabExtractionResult,
    "intake_extraction.schema.json": IntakeExtraction,
    "intake_extraction_result.schema.json": IntakeExtractionResult,
    "upload_intent.schema.json": UploadIntent,
    "upload_result.schema.json": UploadResult,
    "evidence_query.schema.json": EvidenceQuery,
    "evidence_worker_result.schema.json": EvidenceWorkerResult,
    "guideline_candidate.schema.json": GuidelineCandidate,
    "guideline_excerpt.schema.json": GuidelineExcerpt,
    "guideline_citation.schema.json": GuidelineCitation,
    "guideline_evidence_claim.schema.json": GuidelineEvidenceClaim,
    "guideline_evidence_request.schema.json": GuidelineEvidenceRequest,
    "guideline_evidence_response.schema.json": GuidelineEvidenceResponse,
    "guideline_source_request.schema.json": GuidelineSourceRequest,
    "guideline_source_response.schema.json": GuidelineSourceResponse,
    "guideline_retrieval_limitation.schema.json": GuidelineRetrievalLimitation,
    "supervisor_request_state.schema.json": SupervisorRequestState,
    "supervisor_route_decision.schema.json": RouteDecision,
    "supervisor_dispatch_record.schema.json": DispatchRecord,
    "supervisor_handoff_completion.schema.json": HandoffCompletion,
    "supervisor_answer_readiness.schema.json": AnswerReadinessResult,
}

EXPORT_VERSIONS = {
    "supervisor_request_state.schema.json": "4.0.0",
    "supervisor_route_decision.schema.json": "4.0.0",
    "supervisor_dispatch_record.schema.json": "4.0.0",
    "supervisor_handoff_completion.schema.json": "4.0.0",
    "supervisor_answer_readiness.schema.json": "4.0.0",
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
        content = render(model, EXPORT_VERSIONS.get(name, CONTRACT_VERSION))
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
