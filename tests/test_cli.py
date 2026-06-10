import json
from pathlib import Path

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
