from ourboro_pipeline.spss import iter_spss_statements, parse_variable_label


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