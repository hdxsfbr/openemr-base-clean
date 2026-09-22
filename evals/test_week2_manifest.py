"""The approved Week 2 corpus allocation is executable, not prose-only."""

from __future__ import annotations

from pathlib import Path

from week2_manifest import validate_manifest_file


def test_week2_manifest_counts_real_case_files_and_exceeds_required_floors() -> None:
    result = validate_manifest_file(Path(__file__).with_name("week2_manifest.yaml"))

    assert result.errors == []
    assert result.retained_cases == 48
    assert result.new_golden_cases >= 35
    assert result.golden_cases >= 50
    assert result.total_cases >= 83
    assert result.total_cases == 85
    assert result.pending_cases > 0
    assert result.executable_cases + result.pending_cases == 37


def test_week2_manifest_rejects_a_declared_case_without_a_case_file(tmp_path: Path) -> None:
    source = Path(__file__).with_name("week2_manifest.yaml")
    manifest = tmp_path / "week2_manifest.yaml"
    cases = tmp_path / "cases"
    cases.symlink_to(source.with_name("cases"), target_is_directory=True)
    manifest.write_text(source.read_text().replace("  - OBS-CORRELATION-CHAIN-W2-001\n", ""))

    result = validate_manifest_file(manifest)

    assert any("Week 2 case files not declared" in error for error in result.errors)


def test_week2_manifest_rejects_missing_applicable_rubrics(tmp_path: Path) -> None:
    source = Path(__file__).with_name("week2_manifest.yaml")
    manifest = tmp_path / "week2_manifest.yaml"
    cases = tmp_path / "cases"
    cases.mkdir()
    for case_path in source.with_name("cases").glob("*.yaml"):
        target = cases / case_path.name
        text = case_path.read_text()
        if case_path.name == "RET-NO-RESULT-001.yaml":
            text = text.replace("rubrics: [safe_refusal]", "rubrics: []")
        target.write_text(text)
    manifest.write_text(source.read_text())

    result = validate_manifest_file(manifest)

    assert "RET-NO-RESULT-001: applicable rubrics are missing" in result.errors
