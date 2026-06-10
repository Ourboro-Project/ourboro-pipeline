from __future__ import annotations

from pathlib import Path
from typing import Iterable


def parse_spss_metadata_file(path: Path) -> list[dict[str, str]]:
    """
    Parse SPSS label metadata from one syntax file.

    This reads syntax text only. It does not touch SAV data or respondent rows.
    """
    text = path.read_text(encoding="utf-8-sig")
    return parse_spss_metadata_text(text, source_file=str(path))


def parse_spss_metadata_file_with_diagnostics(
    path: Path,
) -> dict[str, list[dict[str, str]]]:
    """
    Parse one syntax file and return both metadata rows and diagnostics.

    This is the safer API for real files because it does not silently discard
    statements that the metadata parser does not understand.
    """
    text = path.read_text(encoding="utf-8-sig")
    return parse_spss_metadata_text_with_diagnostics(
        text,
        source_file=str(path),
    )


def parse_spss_metadata_text(
    text: str,
    *,
    source_file: str = "",
) -> list[dict[str, str]]:
    """
    Parse VARIABLE LABELS and VALUE LABELS statements into flat metadata rows.

    The row shape is intentionally CSV-friendly because the next slice will
    write these rows as an artifact for review.
    """
    rows: list[dict[str, str]] = []

    for source_line, statement in iter_spss_statements(text):
        variable_label = parse_variable_label(statement)
        if variable_label is not None:
            rows.append({
                "source_file": source_file,
                "source_line": str(source_line),
                "label_type": "variable_label",
                "variable": variable_label["variable"],
                "value": "",
                "label": variable_label["variable_label"],
            })
            continue

        value_labels = parse_value_labels(statement)
        if value_labels is None:
            continue

        for value_label in value_labels:
            rows.append({
                "source_file": source_file,
                "source_line": str(source_line),
                "label_type": "value_label",
                "variable": value_label["variable"],
                "value": value_label["value"],
                "label": value_label["value_label"],
            })

    return rows


def parse_spss_metadata_text_with_diagnostics(
    text: str,
    *,
    source_file: str = "",
) -> dict[str, list[dict[str, str]]]:
    """
    Parse SPSS metadata rows and collect machine-readable diagnostics.

    The existing parse_spss_metadata_text() stays quiet and returns only rows.
    This function is for real-file review, where ignored statements should be
    visible instead of disappearing.
    """
    rows: list[dict[str, str]] = []
    diagnostics: list[dict[str, str]] = []

    for source_line, statement in iter_spss_statements(text):
        variable_label = parse_variable_label(statement)
        if variable_label is not None:
            rows.append({
                "source_file": source_file,
                "source_line": str(source_line),
                "label_type": "variable_label",
                "variable": variable_label["variable"],
                "value": "",
                "label": variable_label["variable_label"],
            })
            continue

        value_labels = parse_value_labels(statement)
        if value_labels is not None:
            for value_label in value_labels:
                rows.append({
                    "source_file": source_file,
                    "source_line": str(source_line),
                    "label_type": "value_label",
                    "variable": value_label["variable"],
                    "value": value_label["value"],
                    "label": value_label["value_label"],
                })

            if not value_labels:
                diagnostics.append(build_spss_diagnostic(
                    source_file=source_file,
                    source_line=source_line,
                    severity="warning",
                    code="MALFORMED_VALUE_LABELS",
                    message="VALUE LABELS statement could not be parsed.",
                    statement=statement,
                ))

            continue

        if is_incomplete_statement(statement):
            diagnostics.append(build_spss_diagnostic(
                source_file=source_file,
                source_line=source_line,
                severity="warning",
                code="INCOMPLETE_STATEMENT",
                message="SPSS statement does not end with a period.",
                statement=statement,
            ))
            continue

        if looks_like_variable_labels(statement):
            diagnostics.append(build_spss_diagnostic(
                source_file=source_file,
                source_line=source_line,
                severity="warning",
                code="MALFORMED_VARIABLE_LABELS",
                message="VARIABLE LABELS statement could not be parsed.",
                statement=statement,
            ))
            continue

        if looks_like_value_labels(statement):
            diagnostics.append(build_spss_diagnostic(
                source_file=source_file,
                source_line=source_line,
                severity="warning",
                code="MALFORMED_VALUE_LABELS",
                message="VALUE LABELS statement could not be parsed.",
                statement=statement,
            ))
            continue

        # This parser extracts metadata only. Other valid SPSS syntax such as
        # RECODE, COMPUTE, FILTER, comments, and analysis commands belongs to a
        # separate lineage/analysis extractor, so it is ignored here instead of
        # flooding diagnostics.
        continue

    return {
        "metadata_rows": rows,
        "diagnostics": diagnostics,
    }


def iter_spss_statements(text: str) -> Iterable[tuple[int, str]]:
    """
    Yield complete SPSS statements with their starting line numbers.

    SPSS statements end with periods, but quoted label text may contain periods.
    Only split when a period appears outside quoted text.
    """
    current: list[str] = []
    start_line: int | None = None
    line = 1
    in_quote = False
    i = 0

    while i < len(text):
        char = text[i]

        # Ignore whitespace between statements so start_line points to the
        # first meaningful character of the next statement.
        if not current and char.isspace():
            if char == "\n":
                line += 1
            i += 1
            continue

        if not current:
            start_line = line

        current.append(char)

        # Two consecutive quotes inside quoted text represent an escaped quote.
        if char == "'":
            if in_quote and i + 1 < len(text) and text[i + 1] == "'":
                current.append(text[i + 1])
                i += 1
            else:
                in_quote = not in_quote

        # A period ends the statement only when it is outside quoted text.
        # Decimal values such as 0.5 and -.5 appear often in recodes and must
        # not split the statement.
        if char == "." and not in_quote and not is_decimal_point(text, i):
            yield start_line or line, "".join(current).strip()
            current = []
            start_line = None

        if char == "\n":
            line += 1

        i += 1

    # Preserve incomplete trailing content so callers can diagnose it later.
    tail = "".join(current).strip()
    if tail:
        yield start_line or line, tail


def parse_variable_label(statement: str) -> dict[str, str] | None:
    """
    Extract one VARIABLE LABELS definition from an SPSS statement.
    """
    words = statement.strip().split(None, 2)
    if len(words) < 3:
        return None

    if words[0].lower() != "variable" or words[1].lower() != "labels":
        return None

    tokens = tokenize_spss_label_body(words[2])
    if len(tokens) != 2:
        return None

    variable, label = tokens
    if not is_quoted(label):
        return None

    return {
        "variable": clean_token(variable),
        "variable_label": unquote(label),
    }


def parse_value_labels(statement: str) -> list[dict[str, str]] | None:
    """
    Extract VALUE LABELS definitions from an SPSS statement.

    Supports the observed typo "Value labesl" from the working syntax file.
    Returns None for unrelated statements.
    """
    words = statement.strip().split(None, 2)
    if len(words) < 3:
        return None

    if words[0].lower() != "value":
        return None

    command_word = words[1].lower()
    if command_word not in {"labels", "labesl"}:
        return None

    tokens = tokenize_spss_label_body(words[2])
    if not tokens:
        return []

    variable = clean_token(tokens[0])
    labels: list[dict[str, str]] = []
    i = 1

    while i + 1 < len(tokens):
        value = clean_token(tokens[i])
        label = tokens[i + 1]

        # SPSS also permits switching variables inside one VALUE LABELS command
        # with /OtherVariable. The current files do not depend on this heavily,
        # but supporting it costs little and keeps the parser honest.
        if value.startswith("/"):
            variable = clean_token(value[1:])
            i += 1
            continue

        if not is_quoted(label):
            i += 1
            continue

        labels.append({
            "variable": variable,
            "value": unquote(value),
            "value_label": unquote(label),
        })
        i += 2

    return labels


def tokenize_spss_label_body(body: str) -> list[str]:
    """
    Split a label command body into tokens while preserving quoted labels.
    """
    tokens: list[str] = []
    current: list[str] = []
    in_quote = False
    i = 0

    while i < len(body):
        char = body[i]

        if char.isspace() and not in_quote:
            if current:
                tokens.append("".join(current))
                current = []
            i += 1
            continue

        current.append(char)

        if char == "'":
            if in_quote and i + 1 < len(body) and body[i + 1] == "'":
                current.append(body[i + 1])
                i += 1
            else:
                in_quote = not in_quote

        i += 1

    if current:
        tokens.append("".join(current))

    return tokens


def clean_token(token: str) -> str:
    token = token.strip()
    if token.endswith("."):
        token = token[:-1]
    return token


def is_quoted(token: str) -> bool:
    token = clean_token(token)
    return len(token) >= 2 and token[0] == "'" and token[-1] == "'"


def unquote(token: str) -> str:
    token = clean_token(token)
    if is_quoted(token):
        return token[1:-1].replace("''", "'")
    return token


def is_decimal_point(text: str, index: int) -> bool:
    """
    Return True when text[index] is part of a numeric decimal literal.
    """
    if text[index] != ".":
        return False

    next_char = text[index + 1] if index + 1 < len(text) else ""
    if not next_char.isdigit():
        return False

    previous_char = text[index - 1] if index > 0 else ""
    return (
        previous_char.isdigit()
        or previous_char in {"-", "+"}
        or previous_char.isspace()
        or previous_char in {"(", "="}
    )


def build_spss_diagnostic(
    *,
    source_file: str,
    source_line: int,
    severity: str,
    code: str,
    message: str,
    statement: str,
) -> dict[str, str]:
    """
    Build one CSV-friendly diagnostic row.
    """
    return {
        "source_file": source_file,
        "source_line": str(source_line),
        "severity": severity,
        "code": code,
        "message": message,
        "statement": statement,
    }


def is_incomplete_statement(statement: str) -> bool:
    return not statement.rstrip().endswith(".")


def looks_like_variable_labels(statement: str) -> bool:
    words = statement.strip().split(None, 2)
    return (
        len(words) >= 2
        and words[0].lower() == "variable"
        and words[1].lower() == "labels"
    )


def looks_like_value_labels(statement: str) -> bool:
    words = statement.strip().split(None, 2)
    return (
        len(words) >= 2
        and words[0].lower() == "value"
        and words[1].lower() in {"labels", "labesl"}
    )
