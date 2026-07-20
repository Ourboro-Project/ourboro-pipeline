import json
from pathlib import Path

import pandas as pd
import pyreadstat
import pytest

from ourboro_pipeline.transform import (
    apply_transform_config,
    load_transform_config,
    transform_wave,
    validate_transformation,
)


def test_apply_transform_config_preserves_strict_missing_and_rule_order() -> None:
    dataframe = pd.DataFrame({
        "A": [1.0, 2.0, None],
        "B": [2.0, None, 4.0],
    })
    config = {
        "transformations": [
            {"operation": "recode", "source": "A", "target": "R", "values": {"1": 1, "2": -1}},
            {"operation": "multiply_many", "pairs": [["B", "M"]], "factor": -1},
            {"operation": "strict_average", "sources": ["R", "M"], "target": "AVG"},
            {
                "operation": "conditional_assign",
                "target": "ROUTED",
                "default": "missing",
                "rules": [
                    {"when": [{"column": "A", "equals": 1}], "value": 0},
                    {"when": [{"column": "A", "equals": 2}], "copy": "B"},
                ],
            },
        ]
    }

    result, _ = apply_transform_config(dataframe, config)

    assert result["R"].tolist()[:2] == [1.0, -1.0]
    assert result.loc[0, "AVG"] == -0.5
    assert pd.isna(result.loc[1, "AVG"])
    assert result.loc[0, "ROUTED"] == 0
    assert pd.isna(result.loc[1, "ROUTED"])
    assert pd.isna(result.loc[2, "ROUTED"])


def test_load_transform_config_rejects_duplicate_targets(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "schema_version": 1,
        "transformations": [
            {"operation": "recode", "source": "A", "target": "X", "values": {"1": 1}},
            {"operation": "strict_average", "sources": ["A"], "target": "X"},
        ],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicated"):
        load_transform_config(config_path)


def test_transform_wave_writes_csv_sav_and_passes_oracle_validation(tmp_path: Path) -> None:
    input_csv = tmp_path / "followup.csv"
    input_csv.write_text(
        "ResponseId,A,B\n"
        "Response ID,Question A,Question B\n"
        '"{\""ImportId\"":\""ResponseId\""}",ImportId,ImportId\n'
        "R1,1,2\n"
        "R2,2,4\n",
        encoding="utf-8",
    )
    master_sav = tmp_path / "master.sav"
    pyreadstat.write_sav(pd.DataFrame({
        "ResponseId": ["M1"],
        "A": [1.0],
        "B": [2.0],
    }), master_sav)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "schema_version": 1,
        "expected": {
            "input_rows": 2,
            "input_columns": 3,
            "derived_columns": 3,
            "output_columns": 6,
            "id_column": "ResponseId",
        },
        "sav_alignment": {"date_columns": [], "empty_numeric_columns": []},
        "transformations": [
            {"operation": "recode", "source": "A", "target": "R", "values": {"1": 1, "2": -1}},
            {"operation": "multiply_many", "pairs": [["B", "M"]], "factor": -1},
            {"operation": "strict_average", "sources": ["R", "M"], "target": "AVG"},
        ],
    }), encoding="utf-8")
    output_csv = tmp_path / "transformed.csv"
    output_sav = tmp_path / "transformed.sav"

    report = transform_wave(
        input_csv=input_csv,
        master_sav=master_sav,
        config_path=config_path,
        output_csv=output_csv,
        output_sav=output_sav,
        report_json=tmp_path / "transform.json",
    )

    assert report["output_rows"] == 2
    assert report["output_columns"] == 6
    assert output_csv.exists()
    assert output_sav.exists()
    validation = validate_transformation(
        candidate_sav=output_sav,
        oracle_sav=output_sav,
        report_json=tmp_path / "validation.json",
    )
    assert validation["passed"] is True


def test_validate_transformation_reports_value_mismatch(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.sav"
    oracle = tmp_path / "oracle.sav"
    pyreadstat.write_sav(pd.DataFrame({"ResponseId": ["R1"], "X": [1.0]}), candidate)
    pyreadstat.write_sav(pd.DataFrame({"ResponseId": ["R1"], "X": [2.0]}), oracle)
    report_path = tmp_path / "validation.json"

    with pytest.raises(ValueError, match="differs"):
        validate_transformation(
            candidate_sav=candidate,
            oracle_sav=oracle,
            report_json=report_path,
        )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert report["issues"][0]["code"] == "VALUE_MISMATCH"
