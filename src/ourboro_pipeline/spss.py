from __future__ import annotations

from typing import Iterable


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
        if char == "." and not in_quote:
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
