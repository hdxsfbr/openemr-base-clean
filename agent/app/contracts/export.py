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
}


def render(model) -> str:
    schema = model.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["x-contract-version"] = CONTRACT_VERSION
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    out_dir = Path(__file__).resolve().parents[3] / "contracts" / "schema"
    check = "--check" in argv
    out_dir.mkdir(parents=True, exist_ok=True)
    drift = []
    for name, model in EXPORTS.items():
        path = out_dir / name
        content = render(model)
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
