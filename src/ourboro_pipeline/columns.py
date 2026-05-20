from __future__ import annotations


def compare_column_sets(
    followup_headers: list[str],
    master_headers: list[str],
) -> dict[str, list[dict[str, object]]]:
    """
    Compare two CSV schemas while preserving human-readable column order.

    Returns:
        - columns_in_both
        - columns_only_in_followup
        - columns_only_in_master
    """
    followup_set = set(followup_headers)
    master_set = set(master_headers)

    columns_in_both = [
        {
            "column": column,
            "followup_index": followup_headers.index(column) + 1,
            "master_index": master_headers.index(column) + 1,
        }
        for column in followup_headers
        if column in master_set
    ]

    columns_only_in_followup = [
        {
            "column": column,
            "followup_index": index,
        }
        for index, column in enumerate(followup_headers, start=1)
        if column not in master_set
    ]

    columns_only_in_master = [
        {
            "column": column,
            "master_index": index,
        }
        for index, column in enumerate(master_headers, start=1)
        if column not in followup_set
    ]

    return {
        "columns_in_both": columns_in_both,
        "columns_only_in_followup": columns_only_in_followup,
        "columns_only_in_master": columns_only_in_master,
    }
