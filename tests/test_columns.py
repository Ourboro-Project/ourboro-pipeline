from ourboro_pipeline.columns import (
    classify_column,
    compare_column_sets,
    normalize_name,
    propose_y2_mappings,
)


def test_normalize_name_removes_spaces_punctuation_and_case() -> None:
    assert normalize_name("Duration (in seconds)") == "durationinseconds"
    assert normalize_name("Durationinseconds") == "durationinseconds"


def test_classify_column_identifies_raw_survey_question() -> None:
    assert classify_column("Q1") == "raw_survey_question"
    assert classify_column("Q23_1") == "raw_survey_question"


def test_classify_column_identifies_free_text_response() -> None:
    assert classify_column("Q9_6_TEXT") == "free_text_response"


def test_classify_column_identifies_survey_metadata() -> None:
    assert classify_column("StartDate") == "survey_metadata"
    assert classify_column("ResponseId") == "survey_metadata"


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
            "column_family": "survey_metadata",
        },
        {
            "column": "Q1",
            "followup_index": 2,
            "master_index": 3,
            "column_family": "raw_survey_question",
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
            "column_family": "raw_survey_question",
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
            "column_family": "survey_metadata",
        },
        {
            "column": "Y0_Q1",
            "master_index": 4,
            "column_family": "wave_column",
        },
    ]


def test_high_confidence_y2_mapping_when_y0_and_y1_exist() -> None:
    rows = propose_y2_mappings(
        followup_headers=["Q1"],
        master_headers=["Y0_Q1", "Y1_Q1"],
    )

    assert rows[0]["proposed_target_column"] == "Y2_Q1"
    assert rows[0]["confidence"] == "high"


def test_medium_confidence_y2_mapping_when_only_y1_exists() -> None:
    rows = propose_y2_mappings(
        followup_headers=["IPAddress"],
        master_headers=["Y1_IPAddress"],
    )

    assert rows[0]["proposed_target_column"] == "Y2_IPAddress"
    assert rows[0]["confidence"] == "medium"


def test_exact_match_when_column_exists_without_wave_prefix() -> None:
    rows = propose_y2_mappings(
        followup_headers=["RecipientEmail"],
        master_headers=["RecipientEmail"],
    )

    assert rows[0]["proposed_target_column"] == "RecipientEmail"
    assert rows[0]["confidence"] == "exact_match"


def test_loose_match_when_normalized_names_match() -> None:
    rows = propose_y2_mappings(
        followup_headers=["Duration (in seconds)"],
        master_headers=["Durationinseconds"],
    )

    assert rows[0]["proposed_target_column"] == "Durationinseconds"
    assert rows[0]["confidence"] == "loose_name_match"


def test_unknown_when_no_mapping_signal_exists() -> None:
    rows = propose_y2_mappings(
        followup_headers=["BrokerPanelId"],
        master_headers=["PSIDBrokerID"],
    )

    assert rows[0]["proposed_target_column"] == ""
    assert rows[0]["confidence"] == "unknown"
