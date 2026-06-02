from __future__ import annotations

from typing import Iterable

def iter_spss_statements(text: str) -> Iterable[tuple[int, str]]:
    """
    Yield SPSS statements with their starting line numbers.

    A statement ends at a period outside quoted text.
    """

    current: list[str] = []
    start_line: int | None = None
    line = 1
    in_quote = False
    i = 0

    while i < len(text):
        char = text[i]

        # Ignore whitespace between statements. This ensures
        # start_line points to the first meaningful character of
        # next statement.
        if not current and char.isspace():
            if char == "\n":
                line += 1
            i += 1
            continue

        if not current:
            start_line = line

        current.append(char)
        
        # Two quotes inside a quoted text represent an escaped quote.
        if char == "'":
            if in_quote and i + 1 < len(text) and text[i + 1] == "'":
                current.append(text[i + 1])
                i += 1
            else:
                in_quote = not in_quote
            
        # Split only on periods outside quoted labels.
        if char == "." and not in_quote:
            yield start_line or line, "".join(current).strip()
            current = []
            start_line = None
        
        if char == "\n":
            line += 1

        i += 1

    # Preserve incomplete trailing content for later diagnostics.
    tail = "".join(current).strip()
    if tail:
        yield start_line or line, tail


def parse_variable_label(statement: str) -> dict[str, str] | None:
    """
    Extract one VARIABLE LABELS definition from an SPSS statement.
    
    Return None for unrelated or malformed statements. Empty labels are valid 
    because the real syntax file contains definitions such as:
        
        VARIABLE LABELS Y1_Q39_7_TEXT ''.
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


def tokenize_spss_label_body(body: str) -> list[str]:
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
