import json
from pathlib import Path

from ourboro_pipeline.review import (
    build_y2_mapping_review,
    generate_review_json,
    summarize_mappings,
)


def sample_mapping_rows() -> list[dict[str, object]]:
    return [
        {
            "followup_column_index": 1,
            "followup_column": "Q1",
            "column_family": "raw_survey_question",
            "exists_exact_in_master": True,
            "y0_exists_in_master": True,
            "y1_exists_in_master": True,
            "y2_exists_in_master": False,
            "proposed_target_column": "Y2_Q1",
            "confidence": "high",
            "reason": "Master has both Y0_ and Y1_ versions.",
        },
        {
            "followup_column_index": 2,
            "followup_column": "Duration (in seconds)",
            "column_family": "survey_metadata",
            "exists_exact_in_master": False,
            "y0_exists_in_master": False,
            "y1_exists_in_master": False,
            "y2_exists_in_master": False,
            "proposed_target_column": "Durationinseconds",
            "confidence": "loose_name_match",
            "reason": "Normalized name matches a master column.",
        },
        {
            "followup_column_index": 3,
            "followup_column": "BrokerPanelId",
            "column_family": "survey_metadata",
            "exists_exact_in_master": False,
            "y0_exists_in_master": False,
            "y1_exists_in_master": False,
            "y2_exists_in_master": False,
            "proposed_target_column": "",
            "confidence": "unknown",
            "reason": "No mapping signal found.",
        },
    ]


def test_summarize_mappings_counts_total_confidence_and_family() -> None:
    summary = summarize_mappings(sample_mapping_rows())

    assert summary == {
        "total": 3,
        "by_confidence": {
            "high": 1,
            "loose_name_match": 1,
            "unknown": 1,
        },
        "by_column_family": {
            "raw_survey_question": 1,
            "survey_metadata": 2,
        },
    }


def test_build_y2_mapping_review_includes_summary_and_sections() -> None:
    report = build_y2_mapping_review(sample_mapping_rows())

    assert "# Y2 Mapping Review" in report
    assert "- Total follow-up columns reviewed: 3" in report
    assert "- High-confidence Y2 targets: 1" in report
    assert "- Loose name matches: 1" in report
    assert "- Unknown mappings: 1" in report
    assert "## High Confidence Y2 Targets" in report
    assert "## Loose Name Matches" in report
    assert "## Unknown Mappings" in report
    assert "Y2_Q1" in report
    assert "Durationinseconds" in report
    assert "BrokerPanelId" in report
    assert "_blank_" in report


def test_build_y2_mapping_review_escapes_markdown_table_cells() -> None:
    rows = [
        {
            "followup_column_index": 1,
            "followup_column": "Q1|bad",
            "column_family": "raw_survey_question",
            "exists_exact_in_master": True,
            "y0_exists_in_master": False,
            "y1_exists_in_master": True,
            "y2_exists_in_master": False,
            "proposed_target_column": "Y2_Q1",
            "confidence": "medium",
            "reason": "line one\nline two",
        },
    ]

    report = build_y2_mapping_review(rows)

    assert "Q1\\|bad" in report
    assert "line one line two" in report


def test_generate_review_json_writes_versioned_contract(tmp_path: Path) -> None:
    output_path = tmp_path / "y2_mappings.json"

    generate_review_json(
        rows=sample_mapping_rows(),
        output_path=output_path,
        source_file=Path("possible_y2_mappings.csv"),
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["version"] == "1"
    assert payload["source_file"] == "possible_y2_mappings.csv"
    assert payload["summary"]["total"] == 3
    assert payload["summary"]["by_confidence"]["high"] == 1
    assert len(payload["mappings"]) == 3
    assert payload["mappings"][0]["followup_column"] == "Q1"
    assert payload["mappings"][0]["proposed_target_column"] == "Y2_Q1"
    assert payload["mappings"][0]["approved"] is None
