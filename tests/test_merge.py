from __future__ import annotations

import csv
from pathlib import Path

from ourboro_pipeline.merge import (
    build_followup_to_master_map,
    clean_fieldnames,
    merge_followup_into_master_csv,
    open_csv_with_fallback,
)


def test_clean_fieldnames_removes_latin1_bom_artifact() -> None:
    assert clean_fieldnames(["ï»¿Case", "Q1"]) == ["Case", "Q1"]


def test_open_csv_with_fallback_reads_non_utf8_master(tmp_path: Path) -> None:
    master_csv = tmp_path / "master.csv"
    master_csv.write_bytes(b"Case,Q1\n1,caf\x8f\n")

    handle, encoding = open_csv_with_fallback(master_csv)
    with handle:
        rows = list(csv.reader(handle))

    assert encoding == "latin-1"
    assert rows[0] == ["Case", "Q1"]


def test_build_followup_to_master_map_handles_broker_panel_id_special_case() -> None:
    rows = [
        {"followup_column": "Q1", "proposed_target_column": "Y2_Q1"},
        {"followup_column": "BrokerPanelId", "proposed_target_column": ""},
    ]

    assert build_followup_to_master_map(rows) == {
        "Q1": "Y2_Q1",
        "BrokerPanelId": "Y2_BrokerPanelId",
    }


def test_merge_followup_into_master_csv_appends_mapped_rows(tmp_path: Path) -> None:
    master_csv = tmp_path / "master.csv"
    followup_csv = tmp_path / "followup.csv"
    mappings_csv = tmp_path / "possible_y2_mappings.csv"
    output_csv = tmp_path / "merged.csv"

    master_csv.write_text(
        "Case,Y1_Q1\n1,old\n\n",
        encoding="utf-8",
    )
    followup_csv.write_text(
        "Q1,BrokerPanelId,Ignored\nnew,bp-1,x\n",
        encoding="utf-8",
    )
    mappings_csv.write_text(
        "followup_column,proposed_target_column\n"
        "Q1,Y2_Q1\n"
        "BrokerPanelId,\n"
        "Ignored,\n",
        encoding="utf-8",
    )

    summary = merge_followup_into_master_csv(
        master_csv=master_csv,
        followup_csv=followup_csv,
        mappings_csv=mappings_csv,
        output_csv=output_csv,
    )

    assert summary["master_rows"] == 1
    assert summary["followup_rows"] == 1
    assert summary["output_rows"] == 2
    assert summary["new_columns"] == ["Y2_Q1", "Y2_BrokerPanelId"]
    assert summary["unmapped_followup_columns"] == ["Ignored"]

    with output_csv.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert rows == [
        {
            "Case": "1",
            "Y1_Q1": "old",
            "Y2_Q1": "",
            "Y2_BrokerPanelId": "",
        },
        {
            "Case": "",
            "Y1_Q1": "",
            "Y2_Q1": "new",
            "Y2_BrokerPanelId": "bp-1",
        },
    ]
