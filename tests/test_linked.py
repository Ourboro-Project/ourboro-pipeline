from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pyreadstat

from ourboro_pipeline.linked import build_linked_master, deduplicate_followup, read_crosswalk


def _write_crosswalk(path: Path) -> None:
    values = [
        ["ID March 2026", "HIDBrokerPanelId", "ORIGINAL ID"],
        ["current-1", "hid-1", "original-1"],
    ]
    rows = []
    for row_number, row in enumerate(values, start=1):
        cells = []
        for column_number, value in enumerate(row):
            reference = f"{chr(ord('A') + column_number)}{row_number}"
            cells.append(
                f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'
            )
        rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(rows)}</sheetData></worksheet>'
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)


def _write_shared_string_crosswalk(path: Path) -> None:
    shared_values = [
        "ID March 2026",
        "HIDBrokerPanelId",
        "ORIGINAL ID",
        "current-1",
        "hid-1",
        "original-1",
    ]
    rows = []
    value_index = 0
    for row_number in range(1, 3):
        cells = []
        for column_number in range(3):
            reference = f"{chr(ord('A') + column_number)}{row_number}"
            cells.append(f'<c r="{reference}" t="s"><v>{value_index}</v></c>')
            value_index += 1
        rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(rows)}</sheetData></worksheet>'
    )
    shared_strings = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{value}</t></si>" for value in shared_values)
        + "</sst>"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared_strings)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)


def test_read_crosswalk_supports_shared_strings(tmp_path: Path) -> None:
    crosswalk = tmp_path / "crosswalk.xlsx"
    _write_shared_string_crosswalk(crosswalk)

    dataframe = read_crosswalk(crosswalk)

    assert dataframe.to_dict("records") == [{
        "ID March 2026": "current-1",
        "HIDBrokerPanelId": "hid-1",
        "ORIGINAL ID": "original-1",
    }]


def test_deduplicate_followup_prefers_finished_then_progress() -> None:
    dataframe = pd.DataFrame({
        "BrokerPanelId": ["A", "A"],
        "Finished": [0, 1],
        "Progress": [90, 100],
        "RecordedDate": [1, 2],
        "ResponseId": ["old", "kept"],
    })

    selected, decisions = deduplicate_followup(dataframe)

    assert selected["ResponseId"].tolist() == ["kept"]
    assert decisions == [{
        "broker_panel_id": "A",
        "kept_response_id": "kept",
        "dropped_response_id": "old",
        "rule": "highest Finished, Progress, RecordedDate, then ResponseId",
    }]


def test_build_linked_master_links_and_appends(tmp_path: Path) -> None:
    master_sav = tmp_path / "master.sav"
    pyreadstat.write_sav(pd.DataFrame({
        "PSIDBrokerID": ["original-1", "original-2"],
        "Base": [10.0, 20.0],
    }), master_sav)
    followup_sav = tmp_path / "followup.sav"
    pyreadstat.write_sav(pd.DataFrame({
        "BrokerPanelId": ["current-1", "current-1", "current-2"],
        "Finished": [0.0, 1.0, 1.0],
        "Progress": [50.0, 100.0, 100.0],
        "RecordedDate": [1.0, 2.0, 3.0],
        "ResponseId": ["drop", "linked", "new"],
        "Q1": [1.0, 2.0, 3.0],
    }), followup_sav)
    crosswalk = tmp_path / "crosswalk.xlsx"
    _write_crosswalk(crosswalk)

    report = build_linked_master(
        master_sav=master_sav,
        followup_sav=followup_sav,
        crosswalk_xlsx=crosswalk,
        output_csv=tmp_path / "linked.csv",
        output_sav=tmp_path / "linked.sav",
        report_json=tmp_path / "linked.json",
        enforce_expected=False,
    )

    assert report["counts"]["linked_to_existing_master"] == 1
    assert report["counts"]["no_crosswalk"] == 1
    assert report["counts"]["new_rows_appended"] == 1
    assert report["counts"]["output_rows"] == 3
    linked, _ = pyreadstat.read_sav(tmp_path / "linked.sav")
    assert linked.loc[0, "Y2_ResponseId"] == "linked"
    assert linked.loc[0, "Y2_Q1"] == 2.0
    assert linked.loc[2, "Y2_ResponseId"] == "new"
