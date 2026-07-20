import json
from pathlib import Path

import pandas as pd
import pytest
from click.testing import CliRunner

from ourboro_pipeline.analysis_ready import export_analysis_ready_long
from ourboro_pipeline.cli import main


def write_analysis_ready_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "respondent_id_source_columns": ["PSIDBrokerID", "ResponseId"],
                "cluster_join_column": "respondent_id",
                "cluster_label_column": "cluster_label",
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


def test_export_analysis_ready_long_writes_long_panel(tmp_path: Path) -> None:
    linked_master_csv = tmp_path / "linked_master.csv"
    pd.DataFrame(
        {
            "PSIDBrokerID": ["P1", "P2", "P3"],
            "ResponseId": ["R1", "R2", "R3"],
            "Y0_housing_score": ["1.0", "2.0", ""],
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
            "cluster_label": ["Cluster A", "Cluster B", "Cluster C"],
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
    assert report["counts"]["wave_counts"] == {"Y0": 2, "Y1": 2, "Y2": 3}
    assert report["dv_columns"] == ["housing_score"]
    assert report["excluded_non_numeric_stems"] == ["notes"]

    exported = pd.read_csv(output_csv)
    assert list(exported.columns) == ["respondent_id", "cluster_label", "wave", "housing_score"]
    assert set(exported["respondent_id"]) == {"P1", "P2", "P3"}
    assert sorted(exported["wave"].unique().tolist()) == ["Y0", "Y1", "Y2"]
    assert exported.loc[
        (exported["respondent_id"] == "P3") & (exported["wave"] == "Y2"),
        "housing_score",
    ].iloc[0] == 4.0


def test_export_analysis_ready_long_rejects_duplicate_cluster_assignments(tmp_path: Path) -> None:
    linked_master_csv = tmp_path / "linked_master.csv"
    pd.DataFrame(
        {
            "PSIDBrokerID": ["P1"],
            "ResponseId": ["R1"],
            "Y0_housing_score": ["1.0"],
            "Y1_housing_score": ["1.5"],
            "Y2_housing_score": ["2.0"],
        }
    ).to_csv(linked_master_csv, index=False, encoding="utf-8-sig")

    clusters_csv = tmp_path / "clusters.csv"
    pd.DataFrame(
        {
            "respondent_id": ["P1", "P1"],
            "cluster_label": ["Cluster A", "Cluster B"],
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
            "Y0_housing_score": ["1.0", "2.0"],
            "Y1_housing_score": ["1.5", "2.5"],
            "Y2_housing_score": ["2.0", "3.0"],
        }
    ).to_csv(linked_master_csv, index=False, encoding="utf-8-sig")

    clusters_csv = tmp_path / "clusters.csv"
    pd.DataFrame(
        {
            "respondent_id": ["P1", "R2"],
            "cluster_label": ["Cluster A", "Cluster B"],
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
