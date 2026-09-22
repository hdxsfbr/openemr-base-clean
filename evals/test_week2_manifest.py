"""The approved Week 2 corpus allocation is executable, not prose-only."""

from __future__ import annotations

from pathlib import Path

from week2_manifest import validate_manifest_file


def test_week2_manifest_retains_week1_and_exceeds_required_floors() -> None:
    result = validate_manifest_file(Path(__file__).with_name("week2_manifest.yaml"))

    assert result.errors == []
    assert result.retained_cases == 48
    assert result.new_golden_cases >= 35
    assert result.golden_cases >= 50
    assert result.total_cases >= 83
