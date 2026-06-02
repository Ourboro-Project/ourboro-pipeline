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