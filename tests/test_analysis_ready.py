import json
from pathlib import Path

import pandas as pd
import pytest
from click.testing import CliRunner

from ourboro_pipeline.analysis_ready import (
    build_cluster_assignments,
    export_analysis_ready_long,
    load_analysis_ready_config,
)
from ourboro_pipeline.cli import main


def write_analysis_ready_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "respondent_id_source_columns": ["PSIDBrokerID", "ResponseId"],
                "cluster_join_column": "respondent_id",
                "cluster_source_column": "TSC_RentOtherCategories_Ourboro",
                "cluster_code_column": "cluster_code",
                "cluster_label_column": "cluster_label",
                "cluster_labels": {
                    "1": "Looked in the past but no longer planning",
                    "2": "Looking and planning",
                    "3": "Planning to buy not yet seriously looking",
                    "6": "Ourboro clients",
                },
                "included_cluster_codes": ["1", "2", "3"],
                "missing_cluster_policy": "exclude",
                "wave_column": "wave",
                "waves": {
                    "Y0": {"prefix": "Y0_"},
                    "Y1": {"prefix": "Y1_"},
                    "Y2": {"prefix": "Y2_"},
                },
                "exclude_stems": ["ResponseId", "BrokerPanelId"],
                "drop_all_missing_rows": True,
            }
        ),
        encoding="utf-8",
    )


def test_build_cluster_assignments_labels_codes_and_uses_fallback_id(tmp_path: Path) -> None:
    linked_master_csv = tmp_path / "linked_master.csv"
    pd.DataFrame(
        {
            "PSIDBrokerID": ["P1", "", "P3", "P4", ""],
            "ResponseId": ["R1", "R2", "R3", "R4", ""],
            "TSC_RentOtherCategories_Ourboro": ["1.0", "2", "6.0", "", "1"],
        }
    ).to_csv(linked_master_csv, index=False, encoding="utf-8-sig")
    config_path = tmp_path / "config.json"
    write_analysis_ready_config(config_path)

    output_csv = tmp_path / "clusters.csv"
    report_json = tmp_path / "clusters_report.json"
    report = build_cluster_assignments(
        linked_master_csv=linked_master_csv,
        config_path=config_path,
        output_csv=output_csv,
        report_json=report_json,
    )

    assignments = pd.read_csv(output_csv, dtype=str, encoding="utf-8-sig")
    assert assignments.to_dict("records") == [
        {
            "respondent_id": "P1",
            "cluster_code": "1",
            "cluster_label": "Looked in the past but no longer planning",
        },
        {
            "respondent_id": "R2",
            "cluster_code": "2",
            "cluster_label": "Looking and planning",
        },
    ]
    assert report["counts"]["included_cluster_assignments"] == 2
    assert report["counts"]["included_rows_missing_respondent_id"] == 1
    assert report["counts"]["included_respondent_id_source_counts"] == {
        "PSIDBrokerID": 1,
        "ResponseId": 1,
    }
    assert report["counts"]["blank_cluster_code_rows"] == 1
    assert report["counts"]["excluded_cluster_code_counts"] == {"6": 1}
    assert report_json.exists()


def test_build_cluster_assignments_rejects_conflicting_codes_for_fallback_id(
    tmp_path: Path,
) -> None:
    linked_master_csv = tmp_path / "linked_master.csv"
    pd.DataFrame(
        {
            "PSIDBrokerID": ["", ""],
            "ResponseId": ["R1", "R1"],
            "TSC_RentOtherCategories_Ourboro": ["1", "6"],
        }
    ).to_csv(linked_master_csv, index=False, encoding="utf-8-sig")
    config_path = tmp_path / "config.json"
    write_analysis_ready_config(config_path)

    with pytest.raises(ValueError, match="conflicting cluster codes"):
        build_cluster_assignments(
            linked_master_csv=linked_master_csv,
            config_path=config_path,
            output_csv=tmp_path / "clusters.csv",
        )


def test_build_cluster_assignments_command_writes_outputs(tmp_path: Path) -> None:
    linked_master_csv = tmp_path / "linked_master.csv"
    pd.DataFrame(
        {
            "PSIDBrokerID": ["P1"],
            "ResponseId": ["R1"],
            "TSC_RentOtherCategories_Ourboro": ["1.0"],
        }
    ).to_csv(linked_master_csv, index=False, encoding="utf-8-sig")
    config_path = tmp_path / "config.json"
    write_analysis_ready_config(config_path)
    output_csv = tmp_path / "clusters.csv"
    report_json = tmp_path / "clusters_report.json"

    result = CliRunner().invoke(
        main,
        [
            "build-cluster-assignments",
            "--linked-master-csv",
            str(linked_master_csv),
            "--config",
            str(config_path),
            "--output-csv",
            str(output_csv),
            "--report-json",
            str(report_json),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Assignments: 1" in result.output
    assert output_csv.exists()
    assert report_json.exists()


def test_analysis_ready_config_rejects_metadata_column_collision(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    write_analysis_ready_config(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["cluster_label_column"] = "cluster_code"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="column names must be distinct"):
        load_analysis_ready_config(config_path)


def test_analysis_ready_config_rejects_reserved_metadata_column(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    write_analysis_ready_config(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["cluster_code_column"] = "_source_cluster_code"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="cannot use reserved name"):
        load_analysis_ready_config(config_path)


def test_analysis_ready_config_rejects_whitespace_cluster_label(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    write_analysis_ready_config(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["cluster_labels"]["1"] = "   "
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty string codes to labels"):
        load_analysis_ready_config(config_path)


def test_analysis_ready_config_rejects_padded_cluster_label(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    write_analysis_ready_config(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["cluster_labels"]["1"] = " Padded label "
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="surrounding whitespace"):
        load_analysis_ready_config(config_path)


def test_export_analysis_ready_long_writes_long_panel(tmp_path: Path) -> None:
    linked_master_csv = tmp_path / "linked_master.csv"
    pd.DataFrame(
        {
            "PSIDBrokerID": ["P1", "P2", "P3"],
            "ResponseId": ["R1", "R2", "R3"],
            "TSC_RentOtherCategories_Ourboro": ["1", "2", "3"],
            "Y0_housing_score": ["1.2345678901234567", "2.0", ""],
            "Y1_housing_score": ["1.5", "2.5", ""],
            "Y2_housing_score": ["2.0", "3.0", "4.0"],
            "Y0_notes": ["alpha", "beta", ""],
            "Y1_notes": ["gamma", "delta", ""],
            "Y2_notes": ["epsilon", "zeta", ""],
        }
    ).to_csv(linked_master_csv, index=False, encoding="utf-8-sig")

    clusters_csv = tmp_path / "clusters.csv"
    pd.DataFrame(
        {
            "respondent_id": ["P1", "P2", "P3"],
            "cluster_code": ["1", "2", "3"],
            "cluster_label": [
                "Looked in the past but no longer planning",
                "Looking and planning",
                "Planning to buy not yet seriously looking",
            ],
        }
    ).to_csv(clusters_csv, index=False, encoding="utf-8-sig")

    config_path = tmp_path / "config.json"
    write_analysis_ready_config(config_path)

    output_csv = tmp_path / "analysis_ready.csv"
    report_json = tmp_path / "report.json"
    report = export_analysis_ready_long(
        linked_master_csv=linked_master_csv,
        clusters_csv=clusters_csv,
        config_path=config_path,
        output_csv=output_csv,
        report_json=report_json,
    )

    assert report["counts"]["analysis_ready_rows"] == 7
    assert report["counts"]["analysis_eligible_respondents_before_cluster_filter"] == 3
    assert report["counts"]["excluded_unclustered_respondents"] == 0
    assert report["counts"]["wave_counts"] == {"Y0": 2, "Y1": 2, "Y2": 3}
    assert report["dv_columns"] == ["housing_score"]
    assert report["excluded_non_numeric_stems"] == ["notes"]

    exported = pd.read_csv(output_csv)
    assert list(exported.columns) == [
        "respondent_id",
        "cluster_code",
        "cluster_label",
        "wave",
        "housing_score",
    ]
    assert set(exported["respondent_id"]) == {"P1", "P2", "P3"}
    assert sorted(exported["wave"].unique().tolist()) == ["Y0", "Y1", "Y2"]
    assert "1.2345678901235" in output_csv.read_text(encoding="utf-8-sig")
    assert exported.loc[
        (exported["respondent_id"] == "P3") & (exported["wave"] == "Y2"),
        "housing_score",
    ].iloc[0] == 4.0


def test_export_analysis_ready_long_excludes_unclustered_respondents(tmp_path: Path) -> None:
    linked_master_csv = tmp_path / "linked_master.csv"
    pd.DataFrame(
        {
            "PSIDBrokerID": ["P1", "P2", "P3", "P4"],
            "ResponseId": ["R1", "R2", "R3", "R4"],
            "TSC_RentOtherCategories_Ourboro": ["1", "2", "6", ""],
            "Y0_housing_score": ["1.0", "2.0", "3.0", "4.0"],
            "Y1_housing_score": ["1.5", "2.5", "3.5", "4.5"],
            "Y2_housing_score": ["2.0", "3.0", "4.0", "5.0"],
        }
    ).to_csv(linked_master_csv, index=False, encoding="utf-8-sig")
    clusters_csv = tmp_path / "clusters.csv"
    pd.DataFrame(
        {
            "respondent_id": ["P1"],
            "cluster_code": ["1"],
            "cluster_label": ["Looked in the past but no longer planning"],
        }
    ).to_csv(clusters_csv, index=False, encoding="utf-8-sig")
    config_path = tmp_path / "config.json"
    write_analysis_ready_config(config_path)

    output_csv = tmp_path / "analysis_ready.csv"
    report = export_analysis_ready_long(
        linked_master_csv=linked_master_csv,
        clusters_csv=clusters_csv,
        config_path=config_path,
        output_csv=output_csv,
    )

    exported = pd.read_csv(output_csv)
    assert set(exported["respondent_id"]) == {"P1"}
    assert report["counts"]["analysis_eligible_respondents_before_cluster_filter"] == 4
    assert report["counts"]["distinct_respondent_id"] == 1
    assert report["counts"]["excluded_unclustered_rows"] == 9
    assert report["counts"]["excluded_unclustered_respondents"] == 3
    assert report["counts"]["excluded_blank_cluster_rows"] == 3
    assert report["counts"]["excluded_blank_cluster_respondents"] == 1
    assert report["counts"]["excluded_cluster_code_rows"] == 3
    assert report["counts"]["excluded_cluster_code_respondents"] == 1
    assert report["counts"]["excluded_cluster_code_row_counts"] == {"6": 3}
    assert report["counts"]["excluded_cluster_code_respondent_counts"] == {"6": 1}
    assert report["counts"]["excluded_missing_cluster_assignment_rows"] == 3
    assert report["counts"]["excluded_missing_cluster_assignment_respondents"] == 1


def test_export_analysis_ready_long_rejects_unapproved_cluster_label(tmp_path: Path) -> None:
    linked_master_csv = tmp_path / "linked_master.csv"
    pd.DataFrame(
        {
            "PSIDBrokerID": ["P1"],
            "ResponseId": ["R1"],
            "TSC_RentOtherCategories_Ourboro": ["1"],
            "Y0_housing_score": ["1.0"],
            "Y1_housing_score": ["1.5"],
            "Y2_housing_score": ["2.0"],
        }
    ).to_csv(linked_master_csv, index=False, encoding="utf-8-sig")
    clusters_csv = tmp_path / "clusters.csv"
    pd.DataFrame(
        {
            "respondent_id": ["P1"],
            "cluster_code": ["1"],
            "cluster_label": ["Cluster A"],
        }
    ).to_csv(clusters_csv, index=False, encoding="utf-8-sig")
    config_path = tmp_path / "config.json"
    write_analysis_ready_config(config_path)

    with pytest.raises(ValueError, match="labels that do not match config"):
        export_analysis_ready_long(
            linked_master_csv=linked_master_csv,
            clusters_csv=clusters_csv,
            config_path=config_path,
            output_csv=tmp_path / "analysis_ready.csv",
        )


def test_export_analysis_ready_long_rejects_assignment_that_differs_from_source(
    tmp_path: Path,
) -> None:
    linked_master_csv = tmp_path / "linked_master.csv"
    pd.DataFrame(
        {
            "PSIDBrokerID": ["P1"],
            "ResponseId": ["R1"],
            "TSC_RentOtherCategories_Ourboro": ["6"],
            "Y0_housing_score": ["1.0"],
            "Y1_housing_score": ["1.5"],
            "Y2_housing_score": ["2.0"],
        }
    ).to_csv(linked_master_csv, index=False, encoding="utf-8-sig")
    clusters_csv = tmp_path / "clusters.csv"
    pd.DataFrame(
        {
            "respondent_id": ["P1"],
            "cluster_code": ["1"],
            "cluster_label": ["Looked in the past but no longer planning"],
        }
    ).to_csv(clusters_csv, index=False, encoding="utf-8-sig")
    config_path = tmp_path / "config.json"
    write_analysis_ready_config(config_path)

    with pytest.raises(ValueError, match="do not match linked-master cluster source"):
        export_analysis_ready_long(
            linked_master_csv=linked_master_csv,
            clusters_csv=clusters_csv,
            config_path=config_path,
            output_csv=tmp_path / "analysis_ready.csv",
        )


def test_export_analysis_ready_long_rejects_duplicate_cluster_assignments(tmp_path: Path) -> None:
    linked_master_csv = tmp_path / "linked_master.csv"
    pd.DataFrame(
        {
            "PSIDBrokerID": ["P1"],
            "ResponseId": ["R1"],
            "TSC_RentOtherCategories_Ourboro": ["1"],
            "Y0_housing_score": ["1.0"],
            "Y1_housing_score": ["1.5"],
            "Y2_housing_score": ["2.0"],
        }
    ).to_csv(linked_master_csv, index=False, encoding="utf-8-sig")

    clusters_csv = tmp_path / "clusters.csv"
    pd.DataFrame(
        {
            "respondent_id": ["P1", "P1"],
            "cluster_code": ["1", "2"],
            "cluster_label": [
                "Looked in the past but no longer planning",
                "Looking and planning",
            ],
        }
    ).to_csv(clusters_csv, index=False, encoding="utf-8-sig")

    config_path = tmp_path / "config.json"
    write_analysis_ready_config(config_path)

    with pytest.raises(ValueError, match="duplicate respondent_id"):
        export_analysis_ready_long(
            linked_master_csv=linked_master_csv,
            clusters_csv=clusters_csv,
            config_path=config_path,
            output_csv=tmp_path / "analysis_ready.csv",
            report_json=tmp_path / "report.json",
        )


def test_export_analysis_ready_command_writes_outputs(tmp_path: Path) -> None:
    linked_master_csv = tmp_path / "linked_master.csv"
    pd.DataFrame(
        {
            "PSIDBrokerID": ["P1", ""],
            "ResponseId": ["R1", "R2"],
            "TSC_RentOtherCategories_Ourboro": ["1", "2"],
            "Y0_housing_score": ["1.0", "2.0"],
            "Y1_housing_score": ["1.5", "2.5"],
            "Y2_housing_score": ["2.0", "3.0"],
        }
    ).to_csv(linked_master_csv, index=False, encoding="utf-8-sig")

    clusters_csv = tmp_path / "clusters.csv"
    pd.DataFrame(
        {
            "respondent_id": ["P1", "R2"],
            "cluster_code": ["1", "2"],
            "cluster_label": [
                "Looked in the past but no longer planning",
                "Looking and planning",
            ],
        }
    ).to_csv(clusters_csv, index=False, encoding="utf-8-sig")

    config_path = tmp_path / "config.json"
    write_analysis_ready_config(config_path)

    runner = CliRunner()
    output_csv = tmp_path / "analysis_ready.csv"
    report_json = tmp_path / "report.json"
    result = runner.invoke(
        main,
        [
            "export-analysis-ready",
            "--linked-master-csv",
            str(linked_master_csv),
            "--clusters-csv",
            str(clusters_csv),
            "--config",
            str(config_path),
            "--output-csv",
            str(output_csv),
            "--report-json",
            str(report_json),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Analysis-ready export complete." in result.output
    assert output_csv.exists()
    assert report_json.exists()
