from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pandas as pd
import pyreadstat

from ourboro_pipeline.transform import file_sha256


SPREADSHEET_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
}
CROSSWALK_COLUMNS = ["ID March 2026", "HIDBrokerPanelId", "ORIGINAL ID"]
FOLLOWUP_REQUIRED_COLUMNS = {
    "BrokerPanelId",
    "Finished",
    "Progress",
    "RecordedDate",
    "ResponseId",
}
FOLLOWUP_RANK_COLUMNS = ["_rank_finished", "_rank_progress", "_rank_recorded", "_rank_response"]


def normalize_id(value: object) -> str:
    """Return a normalized respondent ID for matching."""
    if pd.isna(value):
        return ""
    return str(value).strip().casefold()


def _node_text(nodes: list[ET.Element]) -> str:
    """Join XML text nodes into one string."""
    parts = []
    for node in nodes:
        parts.append(node.text or "")
    return "".join(parts)


def _read_shared_strings(archive: ZipFile) -> list[str]:
    """Read shared string values from an XLSX archive."""
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    shared_strings = []
    for string_item in root.findall("m:si", SPREADSHEET_NS):
        text_nodes = string_item.findall(".//m:t", SPREADSHEET_NS)
        shared_strings.append(_node_text(text_nodes))
    return shared_strings


def _spreadsheet_column_index(reference: str) -> int:
    """Convert an Excel cell reference into a zero-based column index."""
    letters = "".join(character for character in reference if character.isalpha())
    column_index = 0
    for letter in letters:
        column_index = column_index * 26 + ord(letter.upper()) - ord("A") + 1
    return column_index - 1


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    """Extract a string value from an XLSX cell."""
    if cell.get("t") == "inlineStr":
        text_nodes = cell.findall(".//m:t", SPREADSHEET_NS)
        return _node_text(text_nodes).strip()

    node = cell.find("m:v", SPREADSHEET_NS)
    value = "" if node is None or node.text is None else node.text
    if cell.get("t") == "s" and value:
        value = shared_strings[int(value)]
    return value.strip()


def _read_first_worksheet_rows(archive: ZipFile, shared_strings: list[str]) -> list[list[str]]:
    """Read rows from the first worksheet in an XLSX archive."""
    worksheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows: list[list[str]] = []
    for row in worksheet.findall("m:sheetData/m:row", SPREADSHEET_NS):
        values: list[str] = []
        for cell in row.findall("m:c", SPREADSHEET_NS):
            reference = cell.get("r", "A1")
            column_index = _spreadsheet_column_index(reference)
            while len(values) <= column_index:
                values.append("")
            values[column_index] = _cell_value(cell, shared_strings)
        rows.append(values)
    return rows


def _crosswalk_dataframe(rows: list[list[str]]) -> pd.DataFrame:
    """Convert raw worksheet rows into a crosswalk dataframe."""
    if not rows:
        raise ValueError("Crosswalk workbook contains no rows.")

    headers = rows[0]
    records = []
    for row in rows[1:]:
        padded_row = row + [""] * (len(headers) - len(row))
        records.append(padded_row)
    return pd.DataFrame(records, columns=headers)


def _validate_crosswalk(dataframe: pd.DataFrame) -> None:
    """Validate crosswalk columns and identifier uniqueness."""
    if list(dataframe.columns) != CROSSWALK_COLUMNS:
        raise ValueError(f"Unexpected crosswalk columns: {list(dataframe.columns)}")
    for column in CROSSWALK_COLUMNS:
        if dataframe[column].eq("").any() or dataframe[column].duplicated().any():
            raise ValueError(f"Crosswalk column is blank or duplicated: {column}")


def read_crosswalk(path: Path) -> pd.DataFrame:
    """Read and validate the respondent crosswalk workbook."""
    with ZipFile(path) as archive:
        shared_strings = _read_shared_strings(archive)
        rows = _read_first_worksheet_rows(archive, shared_strings)

    result = _crosswalk_dataframe(rows)
    _validate_crosswalk(result)
    return result


def _require_followup_columns(dataframe: pd.DataFrame) -> None:
    """Ensure follow-up data has columns required for deduplication."""
    missing = FOLLOWUP_REQUIRED_COLUMNS - set(dataframe.columns)
    if missing:
        raise ValueError(f"Follow-up SAV is missing columns: {', '.join(sorted(missing))}")


def _rank_followup_rows(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Add sort keys that identify the best follow-up response per ID."""
    working = dataframe.copy()
    working["_current_id"] = working["BrokerPanelId"].map(normalize_id)
    if working["_current_id"].eq("").any():
        raise ValueError("Follow-up contains blank BrokerPanelId values.")

    working["_rank_finished"] = pd.to_numeric(working["Finished"], errors="coerce").fillna(-1)
    working["_rank_progress"] = pd.to_numeric(working["Progress"], errors="coerce").fillna(-1)
    working["_rank_recorded"] = pd.to_numeric(working["RecordedDate"], errors="coerce").fillna(-1)
    working["_rank_response"] = working["ResponseId"].fillna("").astype(str)
    return working.sort_values(
        ["_current_id", "_rank_finished", "_rank_progress", "_rank_recorded", "_rank_response"],
        kind="stable",
    )


def _duplicate_decisions(working: pd.DataFrame) -> list[dict[str, str]]:
    """Record which duplicate follow-up rows were dropped."""
    duplicate_keys = set(working.loc[working["_current_id"].duplicated(keep=False), "_current_id"])
    decisions: list[dict[str, str]] = []
    for current_id in sorted(duplicate_keys):
        candidates = working.loc[working["_current_id"] == current_id]
        winner = candidates.iloc[-1]
        for _, candidate in candidates.iloc[:-1].iterrows():
            decisions.append({
                "broker_panel_id": str(winner["BrokerPanelId"]),
                "kept_response_id": str(winner["ResponseId"]),
                "dropped_response_id": str(candidate["ResponseId"]),
                "rule": "highest Finished, Progress, RecordedDate, then ResponseId",
            })
    return decisions


def deduplicate_followup(
    dataframe: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """Keep one best follow-up response per BrokerPanelId."""
    _require_followup_columns(dataframe)
    working = _rank_followup_rows(dataframe)
    selected = working.drop_duplicates("_current_id", keep="last").copy()
    decisions = _duplicate_decisions(working)
    return selected.drop(columns=FOLLOWUP_RANK_COLUMNS), decisions


def _prefixed_metadata(
    metadata: object,
    prefix: str,
) -> tuple[dict[str, str], dict[str, dict[object, str]]]:
    """Prefix SAV variable labels and value labels for Y2 columns."""
    labels = {
        f"{prefix}{name}": f"[Y2 2026] {label or name}"[:255]
        for name, label in zip(metadata.column_names, metadata.column_labels)
    }
    value_labels = {
        f"{prefix}{name}": values
        for name, values in metadata.variable_value_labels.items()
    }
    return labels, value_labels


def _check_expected_input_counts(
    master: pd.DataFrame,
    followup: pd.DataFrame,
    enforce_expected: bool,
) -> None:
    """Validate expected raw master and follow-up row counts."""
    if enforce_expected and len(master) != 9523:
        raise ValueError(f"Expected 9,523 master rows, found {len(master):,}.")
    if enforce_expected and len(followup) != 1635:
        raise ValueError(f"Expected 1,635 follow-up rows, found {len(followup):,}.")


def _check_expected_deduplicated_count(followup: pd.DataFrame, enforce_expected: bool) -> None:
    """Validate expected follow-up row count after deduplication."""
    if enforce_expected and len(followup) != 1627:
        raise ValueError(f"Expected 1,627 deduplicated follow-up rows, found {len(followup):,}.")


def _prepare_crosswalk(crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Add normalized current and original IDs to the crosswalk."""
    return crosswalk.assign(
        _current_id=crosswalk["ID March 2026"].map(normalize_id),
        _original_id=crosswalk["ORIGINAL ID"].map(normalize_id),
    )


def _merge_followup_crosswalk(followup: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Attach crosswalk IDs to deduplicated follow-up rows."""
    return followup.merge(crosswalk, on="_current_id", how="left", validate="one_to_one")


def _add_master_original_ids(master: pd.DataFrame, followup: pd.DataFrame) -> pd.DataFrame:
    """Add normalized original IDs to master and reject duplicate link keys."""
    if "PSIDBrokerID" not in master:
        raise ValueError("Master SAV is missing PSIDBrokerID.")

    master = master.copy()
    master["_original_id"] = master["PSIDBrokerID"].map(normalize_id)
    linked_originals = set(followup["_original_id"]) - {""}
    duplicate_master_keys = master.loc[
        master["_original_id"].isin(linked_originals)
        & master["_original_id"].duplicated(keep=False),
        "_original_id",
    ]
    if not duplicate_master_keys.empty:
        raise ValueError(
            "Crosswalk maps to duplicated master IDs: "
            + ", ".join(sorted(set(duplicate_master_keys))[:10])
        )
    return master


def _assign_master_links(master: pd.DataFrame, followup: pd.DataFrame) -> pd.DataFrame:
    """Assign master row indexes and link status to follow-up rows."""
    master_lookup = {}
    for index, value in master["_original_id"].items():
        if value:
            master_lookup[value] = index

    followup = followup.copy()
    followup["_master_index"] = followup["_original_id"].map(master_lookup)
    followup["_crosswalk_status"] = "no_crosswalk"
    has_crosswalk = followup["_original_id"].notna() & followup["_original_id"].ne("")
    linked = followup["_master_index"].notna()
    followup.loc[has_crosswalk & ~linked, "_crosswalk_status"] = (
        "crosswalk_original_missing_master"
    )
    followup.loc[linked, "_crosswalk_status"] = "linked_existing_master"
    return followup


def _target_columns(source_columns: list[str], master: pd.DataFrame) -> dict[str, str]:
    """Map follow-up columns to Y2-prefixed output columns."""
    target_columns = {}
    for source in source_columns:
        target_columns[source] = f"Y2_{source}"
    if any(len(target) > 64 for target in target_columns.values()):
        raise ValueError("A Y2-prefixed variable name exceeds the SPSS 64-character limit.")
    collisions = set(target_columns.values()) & set(master.columns)
    if collisions:
        raise ValueError(f"Y2 target columns already exist: {sorted(collisions)[:10]}")
    return target_columns


def _add_empty_y2_columns(
    master: pd.DataFrame,
    followup: pd.DataFrame,
    target_columns: dict[str, str],
) -> pd.DataFrame:
    """Append empty Y2 columns to the master dataframe."""
    new_columns: dict[str, pd.Series] = {}
    for source, target in target_columns.items():
        if pd.api.types.is_numeric_dtype(followup[source]):
            new_columns[target] = pd.Series(float("nan"), index=master.index, dtype="float64")
        else:
            new_columns[target] = pd.Series(None, index=master.index, dtype="object")
    new_columns.update({
        "Y2_HIDBrokerPanelId": pd.Series(None, index=master.index, dtype="object"),
        "Y2_crosswalk_original_id": pd.Series(None, index=master.index, dtype="object"),
        "Y2_crosswalk_status": pd.Series(None, index=master.index, dtype="object"),
        "linked_merge_record_source": pd.Series("existing_master", index=master.index, dtype="object"),
    })
    return pd.concat([master, pd.DataFrame(new_columns)], axis=1)


def _copy_matched_followup(
    master: pd.DataFrame,
    matched: pd.DataFrame,
    target_columns: dict[str, str],
) -> None:
    """Copy matched follow-up values into existing master rows."""
    matched_indices = matched["_master_index"].astype(int).tolist()
    for source, target in target_columns.items():
        master.loc[matched_indices, target] = matched[source].to_numpy()
    master.loc[matched_indices, "Y2_HIDBrokerPanelId"] = matched["HIDBrokerPanelId"].to_numpy()
    master.loc[matched_indices, "Y2_crosswalk_original_id"] = matched["ORIGINAL ID"].to_numpy()
    master.loc[matched_indices, "Y2_crosswalk_status"] = matched["_crosswalk_status"].to_numpy()


def _appended_followup_rows(
    master: pd.DataFrame,
    unmatched: pd.DataFrame,
    target_columns: dict[str, str],
) -> pd.DataFrame:
    """Build new master-shaped rows for unmatched follow-up respondents."""
    appended = master.iloc[:0].reindex(range(len(unmatched))).copy()
    for source, target in target_columns.items():
        appended[target] = unmatched[source].to_numpy()
    appended["Y2_HIDBrokerPanelId"] = unmatched["HIDBrokerPanelId"].replace("", None).to_numpy()
    appended["Y2_crosswalk_original_id"] = unmatched["ORIGINAL ID"].replace("", None).to_numpy()
    appended["Y2_crosswalk_status"] = unmatched["_crosswalk_status"].to_numpy()
    appended["linked_merge_record_source"] = "y2_only_appended"
    appended["PSIDBrokerID"] = unmatched["ORIGINAL ID"].replace("", None).to_numpy()
    return appended


def _assert_master_preserved(combined: pd.DataFrame, master_original: pd.DataFrame) -> None:
    """Ensure original master rows and columns remain unchanged."""
    pd.testing.assert_frame_equal(
        combined.iloc[: len(master_original)][master_original.columns].reset_index(drop=True),
        master_original.reset_index(drop=True),
        check_dtype=False,
        check_exact=True,
    )


def _validate_y2_ids(combined: pd.DataFrame, followup: pd.DataFrame) -> None:
    """Ensure each deduplicated follow-up ID appears exactly once in output."""
    y2_ids = combined["Y2_BrokerPanelId"].dropna().astype(str).str.strip()
    if len(y2_ids) != len(followup) or y2_ids.duplicated().any():
        raise ValueError("Y2 output IDs are missing or duplicated after merge.")


def _master_column_labels(metadata: object) -> dict[str, str]:
    """Build column labels for existing master variables."""
    labels = {}
    for name, label in zip(metadata.column_names, metadata.column_labels):
        if label:
            labels[name] = label
    return labels


def _linked_column_labels(master_metadata: object, followup_metadata: object) -> dict[str, str]:
    """Build SAV column labels for linked master output."""
    master_labels = _master_column_labels(master_metadata)
    y2_labels, _ = _prefixed_metadata(followup_metadata, "Y2_")
    return {
        **master_labels,
        **y2_labels,
        "Y2_HIDBrokerPanelId": "[Y2 2026] Crosswalk HIDBrokerPanelId",
        "Y2_crosswalk_original_id": "[Y2 2026] Original ID supplied by crosswalk",
        "Y2_crosswalk_status": "Y2 respondent crosswalk/link status",
        "linked_merge_record_source": "Record source in linked Y2 merge",
    }


def _linked_value_labels(
    master_metadata: object,
    followup_metadata: object,
) -> dict[str, dict[object, str]]:
    """Build SAV value labels for linked master output."""
    _, y2_value_labels = _prefixed_metadata(followup_metadata, "Y2_")
    return {
        **master_metadata.variable_value_labels,
        **y2_value_labels,
        "Y2_crosswalk_status": {
            "linked_existing_master": "Linked to an existing master respondent",
            "crosswalk_original_missing_master": "Crosswalk supplied ID absent from master",
            "no_crosswalk": "No crosswalk row supplied",
        },
        "linked_merge_record_source": {
            "existing_master": "Existing master record",
            "y2_only_appended": "New Y2-only respondent",
        },
    }


def _build_report(
    *,
    master_sav: Path,
    followup_sav: Path,
    crosswalk_xlsx: Path,
    output_csv: Path,
    output_sav: Path,
    master_original: pd.DataFrame,
    raw_followup_rows: int,
    duplicate_decisions: list[dict[str, str]],
    followup: pd.DataFrame,
    unmatched: pd.DataFrame,
    combined: pd.DataFrame,
    source_columns: list[str],
) -> dict[str, Any]:
    """Build JSON report payload for linked master output."""
    status_counts = Counter(followup["_crosswalk_status"])
    return {
        "method": "wide linked merge using respondent crosswalk",
        "inputs": {
            str(master_sav): file_sha256(master_sav),
            str(followup_sav): file_sha256(followup_sav),
            str(crosswalk_xlsx): file_sha256(crosswalk_xlsx),
        },
        "counts": {
            "master_rows": len(master_original),
            "raw_followup_rows": raw_followup_rows,
            "duplicate_followup_rows_removed": len(duplicate_decisions),
            "deduplicated_followup_rows": len(followup),
            "linked_to_existing_master": status_counts["linked_existing_master"],
            "crosswalk_original_missing_master": status_counts["crosswalk_original_missing_master"],
            "no_crosswalk": status_counts["no_crosswalk"],
            "new_rows_appended": len(unmatched),
            "output_rows": len(combined),
            "master_columns": len(master_original.columns),
            "y2_columns_added": len(source_columns),
            "output_columns": len(combined.columns),
        },
        "deduplication_decisions": duplicate_decisions,
        "outputs": [str(output_csv), str(output_sav)],
        "output_csv_sha256": file_sha256(output_csv),
        "output_sav_sha256": file_sha256(output_sav),
    }


def build_linked_master(
    *,
    master_sav: Path,
    followup_sav: Path,
    crosswalk_xlsx: Path,
    output_csv: Path,
    output_sav: Path,
    report_json: Path,
    enforce_expected: bool = True,
) -> dict[str, Any]:
    """Build CSV/SAV master dataset linked with transformed Y2 follow-up."""
    master, master_metadata = pyreadstat.read_sav(master_sav)
    followup, followup_metadata = pyreadstat.read_sav(followup_sav)
    crosswalk = read_crosswalk(crosswalk_xlsx)

    _check_expected_input_counts(master, followup, enforce_expected)

    raw_followup_rows = len(followup)
    followup, duplicate_decisions = deduplicate_followup(followup)
    _check_expected_deduplicated_count(followup, enforce_expected)

    crosswalk = _prepare_crosswalk(crosswalk)
    followup = _merge_followup_crosswalk(followup, crosswalk)

    master_original = master.copy(deep=True)
    master = _add_master_original_ids(master, followup)
    followup = _assign_master_links(master, followup)
    linked = followup["_master_index"].notna()

    source_columns = list(followup_metadata.column_names)
    target_columns = _target_columns(source_columns, master)
    master = _add_empty_y2_columns(master, followup, target_columns)

    matched = followup.loc[linked].copy()
    _copy_matched_followup(master, matched, target_columns)

    unmatched = followup.loc[~linked].copy()
    appended = _appended_followup_rows(master, unmatched, target_columns)

    master = master.drop(columns=["_original_id"])
    appended = appended.drop(columns=["_original_id"])
    combined = pd.concat([master, appended], ignore_index=True)

    _assert_master_preserved(combined, master_original)
    _validate_y2_ids(combined, followup)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_sav.parent.mkdir(parents=True, exist_ok=True)
    report_json.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_csv, index=False, encoding="utf-8-sig")
    pyreadstat.write_sav(
        combined,
        output_sav,
        file_label="Ourboro master linked with transformed Y2 follow-up, June 2026",
        column_labels=_linked_column_labels(master_metadata, followup_metadata),
        variable_value_labels=_linked_value_labels(master_metadata, followup_metadata),
        compress=True,
    )

    report = _build_report(
        master_sav=master_sav,
        followup_sav=followup_sav,
        crosswalk_xlsx=crosswalk_xlsx,
        output_csv=output_csv,
        output_sav=output_sav,
        master_original=master_original,
        raw_followup_rows=raw_followup_rows,
        duplicate_decisions=duplicate_decisions,
        followup=followup,
        unmatched=unmatched,
        combined=combined,
        source_columns=source_columns,
    )
    report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
