from ourboro_pipeline.spss import iter_spss_statements


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
