from __future__ import annotations

import re


def normalize_name(name: str) -> str:
    """
    Normalize a column name for loose comparisons.

    Example:
        "Duration (in seconds)" becomes "durationinseconds"
        "Durationinseconds" becomes "durationinseconds"
    """
    return re.sub(r"[^a-z0-9]", "", name.lower())


def classify_column(name: str) -> str:
    """
    Assign a broad family to a column name.

    This keeps metadata, raw survey questions, free-text fields,
    and wave columns separated during review.
    """
    if name.startswith(("Y0_", "Y1_", "Y2_")):
        return "wave_column"

    if re.fullmatch(r"Q\d+(_\d+)?", name):
        return "raw_survey_question"

    if name.endswith("_TEXT"):
        return "free_text_response"

    if name.startswith((
        "StartDate",
        "EndDate",
        "Status",
        "IPAddress",
        "Progress",
        "Duration",
        "Finished",
        "RecordedDate",
        "ResponseId",
        "Recipient",
        "ExternalReference",
        "LocationLatitude",
        "LocationLongitude",
        "DistributionChannel",
        "UserLanguage",
        "BrokerPanelId",
        "PSIDBrokerID",
        "Case",
    )):
        return "survey_metadata"

    return "other"


def compare_column_sets(
    followup_headers: list[str],
    master_headers: list[str],
) -> dict[str, list[dict[str, object]]]:
    """
    Compare two CSV schemas while preserving human-readable column order.
    """
    followup_set = set(followup_headers)
    master_set = set(master_headers)

    followup_indexes = {
        column: index
        for index, column in enumerate(followup_headers, start=1)
    }

    master_indexes = {
        column: index
        for index, column in enumerate(master_headers, start=1)
    }
    
    columns_in_both = [
        {
            "column": column,
            "followup_index": followup_indexes[column],
            "master_index": master_indexes[column],
            "column_family": classify_column(column),
        }
        for column in followup_headers
        if column in master_set
    ]

    columns_only_in_followup = [
        {
            "column": column,
            "followup_index": index,
            "column_family": classify_column(column),
        }
        for index, column in enumerate(followup_headers, start=1)
        if column not in master_set
    ]

    columns_only_in_master = [
        {
            "column": column,
            "master_index": index,
            "column_family": classify_column(column),
        }
        for index, column in enumerate(master_headers, start=1)
        if column not in followup_set
    ]

    return {
        "columns_in_both": columns_in_both,
        "columns_only_in_followup": columns_only_in_followup,
        "columns_only_in_master": columns_only_in_master,
    }


def propose_y2_mappings(
    followup_headers: list[str],
    master_headers: list[str],
) -> list[dict[str, object]]:
    """
    Propose how follow-up columns may map into the master file.

    This does not modify data. It only creates a review table.
    """
    master_set = set(master_headers)
    master_normalized = {normalize_name(column): column for column in master_headers}

    rows: list[dict[str, object]] = []

    for index, column in enumerate(followup_headers, start=1):
        y0 = f"Y0_{column}"
        y1 = f"Y1_{column}"
        y2 = f"Y2_{column}"

        exact_exists = column in master_set
        y0_exists = y0 in master_set
        y1_exists = y1 in master_set
        y2_exists = y2 in master_set

        loose_match = master_normalized.get(normalize_name(column))

        if y0_exists and y1_exists and not y2_exists:
            proposed_target = y2
            confidence = "high"
            reason = "Master has both Y0_ and Y1_ versions; likely year-2 target."
        elif y1_exists and not y2_exists:
            proposed_target = y2
            confidence = "medium"
            reason = "Master has Y1_ version; likely year-2 target."
        elif y2_exists:
            proposed_target = y2
            confidence = "already_exists"
            reason = "Y2_ version already exists in master."
        elif exact_exists:
            proposed_target = column
            confidence = "exact_match"
            reason = "Column already exists in master without wave prefix."
        elif loose_match:
            proposed_target = loose_match
            confidence = "loose_name_match"
            reason = "No exact match, but normalized name matches a master column."
        else:
            proposed_target = ""
            confidence = "unknown"
            reason = "No exact, Y0/Y1/Y2, or loose normalized match found."

        rows.append({
            "followup_column_index": index,
            "followup_column": column,
            "column_family": classify_column(column),
            "exists_exact_in_master": exact_exists,
            "y0_exists_in_master": y0_exists,
            "y1_exists_in_master": y1_exists,
            "y2_exists_in_master": y2_exists,
            "proposed_target_column": proposed_target,
            "confidence": confidence,
            "reason": reason,
        })

    return rows
