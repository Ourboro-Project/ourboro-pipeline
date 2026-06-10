from pathlib import Path

from ourboro_pipeline.spss import (
    iter_spss_statements,
    parse_spss_metadata_file,
    parse_spss_metadata_file_with_diagnostics,
    parse_spss_metadata_text,
    parse_spss_metadata_text_with_diagnostics,
    parse_value_labels,
    parse_variable_label,
)


def test_keeps_multiline_value_labels_together() -> None:
    text = """VALUE LABELS Y1_Q1
    1 'Urban'
    2 'Suburban'
    3 'Rural'.

VARIABLE LABELS Y1_Q2 'Question two.'.
"""

    assert list(iter_spss_statements(text)) == [
        (
            1,
            "VALUE LABELS Y1_Q1\n"
            "    1 'Urban'\n"
            "    2 'Suburban'\n"
            "    3 'Rural'.",
        ),
        (6, "VARIABLE LABELS Y1_Q2 'Question two.'."),
    ]


def test_ignores_blank_lines_before_next_statement() -> None:
    text = "VALUE LABELS Q1 1 'Yes'.\n\n\nVARIABLE LABELS Q2 'Second question'."

    assert list(iter_spss_statements(text)) == [
        (1, "VALUE LABELS Q1 1 'Yes'."),
        (4, "VARIABLE LABELS Q2 'Second question'."),
    ]


def test_does_not_split_on_period_inside_label() -> None:
    text = "VARIABLE LABELS Q1 'This sentence has a period. It continues.'."

    assert list(iter_spss_statements(text)) == [
        (1, "VARIABLE LABELS Q1 'This sentence has a period. It continues.'."),
    ]


def test_handles_escaped_quote_inside_label() -> None:
    text = "VARIABLE LABELS Q1 'Respondent''s answer.'."

    assert list(iter_spss_statements(text)) == [
        (1, "VARIABLE LABELS Q1 'Respondent''s answer.'."),
    ]


def test_preserves_incomplete_trailing_statement_for_diagnostics() -> None:
    text = "\n\nVALUE LABELS Q1 1 'Yes'"

    assert list(iter_spss_statements(text)) == [
        (3, "VALUE LABELS Q1 1 'Yes'"),
    ]


def test_parse_variable_label_parses_normal_variable_labels_statement() -> None:
    statement = "VARIABLE LABELS Y1_Q1 'Which place do you live in?'."

    assert parse_variable_label(statement) == {
        "variable": "Y1_Q1",
        "variable_label": "Which place do you live in?",
    }


def test_parse_variable_label_is_case_insensitive() -> None:
    statement = "Variable Labels Y1_Q2 'Sense of belonging'."

    assert parse_variable_label(statement) == {
        "variable": "Y1_Q2",
        "variable_label": "Sense of belonging",
    }


def test_parse_variable_label_handles_empty_label() -> None:
    statement = "VARIABLE LABELS Y1_Q39_7_TEXT ''."

    assert parse_variable_label(statement) == {
        "variable": "Y1_Q39_7_TEXT",
        "variable_label": "",
    }


def test_parse_variable_label_handles_escaped_quote() -> None:
    statement = "VARIABLE LABELS Q1 'Respondent''s answer'."

    assert parse_variable_label(statement) == {
        "variable": "Q1",
        "variable_label": "Respondent's answer",
    }


def test_parse_variable_label_returns_none_for_unrelated_statement() -> None:
    statement = "VALUE LABELS Q1 1 'Yes' 2 'No'."

    assert parse_variable_label(statement) is None


def test_parse_value_labels_parses_multiline_value_labels() -> None:
    statement = """VALUE LABELS Y1_Q1
    1 'Urban'
    2 'Suburban'
    3 'Rural'."""

    assert parse_value_labels(statement) == [
        {"variable": "Y1_Q1", "value": "1", "value_label": "Urban"},
        {"variable": "Y1_Q1", "value": "2", "value_label": "Suburban"},
        {"variable": "Y1_Q1", "value": "3", "value_label": "Rural"},
    ]


def test_parse_value_labels_parses_single_line_value_labels() -> None:
    statement = "Value Labels Q24 1 'Purchase a home' 2 'Stay where you are'."

    assert parse_value_labels(statement) == [
        {"variable": "Q24", "value": "1", "value_label": "Purchase a home"},
        {"variable": "Q24", "value": "2", "value_label": "Stay where you are"},
    ]


def test_parse_value_labels_supports_observed_labesl_typo() -> None:
    statement = (
        "Value labesl buynextyear "
        "1 'Plan to purchase' "
        "0 'Plan to stay or rent'."
    )

    assert parse_value_labels(statement) == [
        {
            "variable": "buynextyear",
            "value": "1",
            "value_label": "Plan to purchase",
        },
        {
            "variable": "buynextyear",
            "value": "0",
            "value_label": "Plan to stay or rent",
        },
    ]


def test_parse_value_labels_handles_negative_and_decimal_values() -> None:
    statement = (
        "VALUE LABELS Q32order "
        "1 'Better shape' "
        "-1 'Worse shape' "
        "0.5 'Partial match'."
    )

    assert parse_value_labels(statement) == [
        {"variable": "Q32order", "value": "1", "value_label": "Better shape"},
        {"variable": "Q32order", "value": "-1", "value_label": "Worse shape"},
        {"variable": "Q32order", "value": "0.5", "value_label": "Partial match"},
    ]


def test_parse_value_labels_returns_none_for_unrelated_statement() -> None:
    statement = "VARIABLE LABELS Q1 'Question text'."

    assert parse_value_labels(statement) is None


def test_parse_spss_metadata_text_returns_flat_rows_with_source_lines() -> None:
    text = """VARIABLE LABELS Q1 'Question one'.

VALUE LABELS Q1
    1 'Yes'
    0 'No'.
"""

    assert parse_spss_metadata_text(text, source_file="survey.sps") == [
        {
            "source_file": "survey.sps",
            "source_line": "1",
            "label_type": "variable_label",
            "variable": "Q1",
            "value": "",
            "label": "Question one",
        },
        {
            "source_file": "survey.sps",
            "source_line": "3",
            "label_type": "value_label",
            "variable": "Q1",
            "value": "1",
            "label": "Yes",
        },
        {
            "source_file": "survey.sps",
            "source_line": "3",
            "label_type": "value_label",
            "variable": "Q1",
            "value": "0",
            "label": "No",
        },
    ]


def test_parse_spss_metadata_text_ignores_unrelated_statements() -> None:
    text = """COMPUTE Q1_copy = Q1.
VARIABLE LABELS Q1 'Question one'.
FREQUENCIES VARIABLES=Q1.
"""

    assert parse_spss_metadata_text(text) == [
        {
            "source_file": "",
            "source_line": "2",
            "label_type": "variable_label",
            "variable": "Q1",
            "value": "",
            "label": "Question one",
        },
    ]


def test_parse_spss_metadata_file_reads_path(tmp_path: Path) -> None:
    syntax_file = tmp_path / "labels.sps"
    syntax_file.write_text(
        "VALUE LABELS Q1 1 'Yes' 0 'No'.",
        encoding="utf-8",
    )

    assert parse_spss_metadata_file(syntax_file) == [
        {
            "source_file": str(syntax_file),
            "source_line": "1",
            "label_type": "value_label",
            "variable": "Q1",
            "value": "1",
            "label": "Yes",
        },
        {
            "source_file": str(syntax_file),
            "source_line": "1",
            "label_type": "value_label",
            "variable": "Q1",
            "value": "0",
            "label": "No",
        },
    ]


def test_parse_spss_metadata_text_with_diagnostics_returns_valid_rows_without_diagnostics() -> None:
    text = """VARIABLE LABELS Q1 'Question one'.

VALUE LABELS Q1
    1 'Yes'
    0 'No'.
"""

    result = parse_spss_metadata_text_with_diagnostics(
        text,
        source_file="survey.sps",
    )

    assert result["metadata_rows"] == [
        {
            "source_file": "survey.sps",
            "source_line": "1",
            "label_type": "variable_label",
            "variable": "Q1",
            "value": "",
            "label": "Question one",
        },
        {
            "source_file": "survey.sps",
            "source_line": "3",
            "label_type": "value_label",
            "variable": "Q1",
            "value": "1",
            "label": "Yes",
        },
        {
            "source_file": "survey.sps",
            "source_line": "3",
            "label_type": "value_label",
            "variable": "Q1",
            "value": "0",
            "label": "No",
        },
    ]
    assert result["diagnostics"] == []


def test_parse_spss_metadata_text_with_diagnostics_returns_rows_and_diagnostics() -> None:
    text = """VARIABLE LABELS Q1 'Question one'.
COMPUTE Q1_copy = Q1.
"""

    result = parse_spss_metadata_text_with_diagnostics(
        text,
        source_file="survey.sps",
    )

    assert result["metadata_rows"] == [
        {
            "source_file": "survey.sps",
            "source_line": "1",
            "label_type": "variable_label",
            "variable": "Q1",
            "value": "",
            "label": "Question one",
        },
    ]
    assert result["diagnostics"] == [
        {
            "source_file": "survey.sps",
            "source_line": "2",
            "severity": "info",
            "code": "UNSUPPORTED_STATEMENT",
            "message": "Statement is outside the current SPSS metadata parser scope.",
            "statement": "COMPUTE Q1_copy = Q1.",
        },
    ]


def test_parse_spss_metadata_text_with_diagnostics_reports_malformed_variable_labels() -> None:
    text = "VARIABLE LABELS Q1 Missing quoted label."

    result = parse_spss_metadata_text_with_diagnostics(text)

    assert result["metadata_rows"] == []
    assert result["diagnostics"] == [
        {
            "source_file": "",
            "source_line": "1",
            "severity": "warning",
            "code": "MALFORMED_VARIABLE_LABELS",
            "message": "VARIABLE LABELS statement could not be parsed.",
            "statement": "VARIABLE LABELS Q1 Missing quoted label.",
        },
    ]


def test_parse_spss_metadata_text_with_diagnostics_reports_malformed_value_labels() -> None:
    text = "VALUE LABELS Q1 1 Yes."

    result = parse_spss_metadata_text_with_diagnostics(text)

    assert result["metadata_rows"] == []
    assert result["diagnostics"] == [
        {
            "source_file": "",
            "source_line": "1",
            "severity": "warning",
            "code": "MALFORMED_VALUE_LABELS",
            "message": "VALUE LABELS statement could not be parsed.",
            "statement": "VALUE LABELS Q1 1 Yes.",
        },
    ]


def test_parse_spss_metadata_text_with_diagnostics_reports_incomplete_statement() -> None:
    text = "COMPUTE Q1_copy = Q1"

    result = parse_spss_metadata_text_with_diagnostics(text)

    assert result["metadata_rows"] == []
    assert result["diagnostics"] == [
        {
            "source_file": "",
            "source_line": "1",
            "severity": "warning",
            "code": "INCOMPLETE_STATEMENT",
            "message": "SPSS statement does not end with a period.",
            "statement": "COMPUTE Q1_copy = Q1",
        },
    ]


def test_parse_spss_metadata_file_with_diagnostics_reads_path(tmp_path: Path) -> None:
    syntax_file = tmp_path / "labels.sps"
    syntax_file.write_text(
        "FREQUENCIES VARIABLES=Q1.",
        encoding="utf-8",
    )

    result = parse_spss_metadata_file_with_diagnostics(syntax_file)

    assert result["metadata_rows"] == []
    assert result["diagnostics"] == [
        {
            "source_file": str(syntax_file),
            "source_line": "1",
            "severity": "info",
            "code": "UNSUPPORTED_STATEMENT",
            "message": "Statement is outside the current SPSS metadata parser scope.",
            "statement": "FREQUENCIES VARIABLES=Q1.",
        },
    ]
