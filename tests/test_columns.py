from ourboro_pipeline.columns import compare_column_sets


def test_compare_column_sets_finds_exact_overlap() -> None:
    result = compare_column_sets(
        followup_headers=["StartDate", "Q1", "Q2"],
        master_headers=["Case", "StartDate", "Q1", "Y0_Q1", "Y1_Q1"],
    )

    assert result["columns_in_both"] == [
        {
            "column": "StartDate",
            "followup_index": 1,
            "master_index": 2,
        },
        {
            "column": "Q1",
            "followup_index": 2,
            "master_index": 3,
        },
    ]


def test_compare_column_sets_finds_followup_only_columns() -> None:
    result = compare_column_sets(
        followup_headers=["StartDate", "Q1", "Q2"],
        master_headers=["StartDate", "Q1"],
    )

    assert result["columns_only_in_followup"] == [
        {
            "column": "Q2",
            "followup_index": 3,
        },
    ]


def test_compare_column_sets_finds_master_only_columns() -> None:
    result = compare_column_sets(
        followup_headers=["StartDate", "Q1"],
        master_headers=["Case", "StartDate", "Q1", "Y0_Q1"],
    )

    assert result["columns_only_in_master"] == [
        {
            "column": "Case",
            "master_index": 1,
        },
        {
            "column": "Y0_Q1",
            "master_index": 4,
        },
    ]
