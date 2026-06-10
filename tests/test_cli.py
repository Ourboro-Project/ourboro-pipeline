import json
from pathlib import Path
import csv

from click.testing import CliRunner

from ourboro_pipeline.cli import main


def test_mapping_review_command_writes_markdown_and_json(tmp_path: Path) -> None:
    mappings_csv = tmp_path / "possible_y2_mappings.csv"
    output_dir = tmp_path / "outputs"

    mappings_csv.write_text(
        "\n".join([
            "followup_column_index,followup_column,column_family,exists_exact_in_master,y0_exists_in_master,y1_exists_in_master,y2_exists_in_master,proposed_target_column,confidence,reason",
            "1,Q1,raw_survey_question,True,True,True,False,Y2_Q1,high,Master has both Y0_ and Y1_ versions.",
            "2,BrokerPanelId,survey_metadata,False,False,False,False,,unknown,No mapping signal found.",
        ]),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "mapping-review",
            "--mappings-csv",
            str(mappings_csv),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Y2 Mapping Review" in result.output
    assert "Total mappings: 2" in result.output

    markdown_path = output_dir / "y2_mapping_review.md"
    json_path = output_dir / "y2_mappings.json"

    assert markdown_path.exists()
    assert json_path.exists()

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "## High Confidence Y2 Targets" in markdown
    assert "## Unknown Mappings" in markdown
    assert "Y2_Q1" in markdown
    assert "BrokerPanelId" in markdown

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["version"] == "1"
    assert payload["summary"]["total"] == 2
    assert payload["mappings"][0]["approved"] is None


def test_mapping_review_command_rejects_missing_required_columns(tmp_path: Path) -> None:
    mappings_csv = tmp_path / "bad_mappings.csv"
    output_dir = tmp_path / "outputs"

    mappings_csv.write_text(
        "\n".join([
            "followup_column,confidence",
            "Q1,high",
        ]),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "mapping-review",
            "--mappings-csv",
            str(mappings_csv),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code != 0
    assert "missing required columns" in result.output


def test_extract_spss_metadata_writes_artifacts(tmp_path: Path) -> None:
    syntax_file = tmp_path / "labels.sps"
    output_dir = tmp_path / "outputs"

    syntax_file.write_text(
        "\n".join([
            "VARIABLE LABELS Q1 'Question one'.",
            "VALUE LABELS Q1 1 'Yes' 0 'No'.",
            "VALUE LABELS Q2 1 Yes.",
        ]),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "extract-spss-metadata",
            "--syntax-file",
            str(syntax_file),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "SPSS Metadata Extraction Summary" in result.output
    assert "Metadata rows:   3" in result.output
    assert "Diagnostics:     1" in result.output

    metadata_path = output_dir / "spss_metadata_rows.csv"
    diagnostics_path = output_dir / "spss_metadata_diagnostics.csv"
    summary_path = output_dir / "spss_metadata_summary.txt"

    assert metadata_path.exists()
    assert diagnostics_path.exists()
    assert summary_path.exists()

    with metadata_path.open("r", encoding="utf-8", newline="") as f:
        metadata_rows = list(csv.DictReader(f))

    assert metadata_rows == [
        {
            "source_file": str(syntax_file),
            "source_line": "1",
            "label_type": "variable_label",
            "variable": "Q1",
            "value": "",
            "label": "Question one",
        },
        {
            "source_file": str(syntax_file),
            "source_line": "2",
            "label_type": "value_label",
            "variable": "Q1",
            "value": "1",
            "label": "Yes",
        },
        {
            "source_file": str(syntax_file),
            "source_line": "2",
            "label_type": "value_label",
            "variable": "Q1",
            "value": "0",
            "label": "No",
        },
    ]

    with diagnostics_path.open("r", encoding="utf-8", newline="") as f:
        diagnostics = list(csv.DictReader(f))

    assert diagnostics == [
        {
            "source_file": str(syntax_file),
            "source_line": "3",
            "severity": "warning",
            "code": "MALFORMED_VALUE_LABELS",
            "message": "VALUE LABELS statement could not be parsed.",
            "statement": "VALUE LABELS Q2 1 Yes.",
        },
    ]

    summary = summary_path.read_text(encoding="utf-8")
    assert str(syntax_file) in summary
    assert str(metadata_path) in summary
    assert str(diagnostics_path) in summary


def test_extract_spss_metadata_accepts_multiple_syntax_files(tmp_path: Path) -> None:
    syntax_file_1 = tmp_path / "labels_1.sps"
    syntax_file_2 = tmp_path / "labels_2.sps"
    output_dir = tmp_path / "outputs"

    syntax_file_1.write_text(
        "VARIABLE LABELS Q1 'Question one'.",
        encoding="utf-8",
    )
    syntax_file_2.write_text(
        "VARIABLE LABELS Q2 'Question two'.",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "extract-spss-metadata",
            "--syntax-file",
            str(syntax_file_1),
            "--syntax-file",
            str(syntax_file_2),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Metadata rows:   2" in result.output
    assert "Diagnostics:     0" in result.output

    with (output_dir / "spss_metadata_rows.csv").open(
        "r",
        encoding="utf-8",
        newline="",
    ) as f:
        rows = list(csv.DictReader(f))

    assert [row["variable"] for row in rows] == ["Q1", "Q2"]
    assert {row["source_file"] for row in rows} == {
        str(syntax_file_1),
        str(syntax_file_2),
    }


def test_extract_spss_metadata_rejects_missing_syntax_file(tmp_path: Path) -> None:
    missing_file = tmp_path / "missing.sps"
    output_dir = tmp_path / "outputs"

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "extract-spss-metadata",
            "--syntax-file",
            str(missing_file),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code != 0
    assert "does not exist" in result.output
