from __future__ import annotations

from collections import Counter

import json
from datetime import datetime, timezone
from pathlib import Path

def build_y2_mapping_review(rows: list[dict[str, object]]) -> str:
    """
    Build a human-readable Markdown review from possible Y2 mapping rows.

    Expected row keys come from propose_y2_mappings():

    - followup_column_index
    - followup_column
    - column_family
    - exists_exact_in_master
    - y0_exists_in_master
    - y1_exists_in_master
    - y2_exists_in_master
    - proposed_target_column
    - confidence
    - reason
    """

    def cell(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "yes" if value else "no"

        text = str(value)
        text = text.replace("|", "\\|")
        text = text.replace("\n", " ")
        return text

    def get(row: dict[str, object], key: str) -> str:
        return cell(row.get(key, ""))

    def section_rows(
        *,
        confidence: str | None = None,
        column_family: str | None = None,
    ) -> list[dict[str, object]]:
        result = rows

        if confidence is not None:
            result = [
                row for row in result
                if row.get("confidence") == confidence
            ]

        if column_family is not None:
            result = [
                row for row in result
                if row.get("column_family") == column_family
            ]

        return result

    def yes_no(row: dict[str, object], key: str) -> str:
        return "yes" if row.get(key) is True else "no"

    def master_signals(row: dict[str, object]) -> str:
        return ", ".join([
            f"exact:{yes_no(row, 'exists_exact_in_master')}",
            f"Y0:{yes_no(row, 'y0_exists_in_master')}",
            f"Y1:{yes_no(row, 'y1_exists_in_master')}",
            f"Y2:{yes_no(row, 'y2_exists_in_master')}",
        ])

    def markdown_table(section: list[dict[str, object]]) -> list[str]:
        if not section:
            return ["_None._"]

        lines = [
            "| # | Follow-up column | Family | Proposed target | Master signals | Reason |",
            "|---:|---|---|---|---|---|",
        ]

        for row in section:
            proposed_target = get(row, "proposed_target_column") or "_blank_"
            lines.append(
                "| "
                + " | ".join([
                    get(row, "followup_column_index"),
                    get(row, "followup_column"),
                    get(row, "column_family"),
                    proposed_target,
                    cell(master_signals(row)),
                    get(row, "reason"),
                ])
                + " |"
            )

        return lines

    def count_list(counter: Counter[str]) -> list[str]:
        if not counter:
            return ["- none"]

        return [
            f"- {cell(name)}: {count}"
            for name, count in sorted(counter.items())
        ]

    confidence_counts = Counter(str(row.get("confidence", "")) for row in rows)
    family_counts = Counter(str(row.get("column_family", "")) for row in rows)

    high_rows = section_rows(confidence="high")
    medium_rows = section_rows(confidence="medium")
    exact_rows = section_rows(confidence="exact_match")
    loose_match_rows = section_rows(confidence="loose_name_match")
    already_exists_rows = section_rows(confidence="already_exists")
    unknown_rows = section_rows(confidence="unknown")
    metadata_rows = section_rows(column_family="survey_metadata")
    free_text_rows = section_rows(column_family="free_text_response")

    lines: list[str] = [
        "# Y2 Mapping Review",
        "",
        "Generated from `possible_y2_mappings.csv`.",
        "This is a review artifact only; it does not modify source data.",
        "",
        "## Summary",
        "",
        f"- Total follow-up columns reviewed: {len(rows)}",
        f"- High-confidence Y2 targets: {confidence_counts.get('high', 0)}",
        f"- Medium-confidence Y2 targets: {confidence_counts.get('medium', 0)}",
        f"- Exact master matches: {confidence_counts.get('exact_match', 0)}",
        f"- Loose name matches: {confidence_counts.get('loose_name_match', 0)}",
        f"- Already-existing Y2 targets: {confidence_counts.get('already_exists', 0)}",
        f"- Unknown mappings: {confidence_counts.get('unknown', 0)}",
        "",
        "## Counts By Confidence",
        "",
        *count_list(confidence_counts),
        "",
        "## Counts By Column Family",
        "",
        *count_list(family_counts),
        "",
        "## High Confidence Y2 Targets",
        "",
        *markdown_table(high_rows),
        "",
        "## Medium Confidence Y2 Targets",
        "",
        *markdown_table(medium_rows),
        "",
        "## Exact Master Matches",
        "",
        *markdown_table(exact_rows),
        "",
        "## Loose Name Matches",
        "",
        *markdown_table(loose_match_rows),
        "",
        "## Already Existing Y2 Targets",
        "",
        *markdown_table(already_exists_rows),
        "",
        "## Unknown Mappings",
        "",
        *markdown_table(unknown_rows),
        "",
        "## Survey Metadata Columns",
        "",
        *markdown_table(metadata_rows),
        "",
        "## Free Text Columns",
        "",
        *markdown_table(free_text_rows),
        "",
    ]

    return "\n".join(lines)


def summarize_mappings(rows: list[dict[str, object]]) -> dict[str, object]:
    confidence_counts = Counter(str(row.get("confidence", "")) for row in rows)
    family_counts = Counter(str(row.get("column_family", "")) for row in rows)

    return {
        "total": len(rows),
        "by_confidence": dict(sorted(confidence_counts.items())),
        "by_column_family": dict(sorted(family_counts.items())),
    }


def generate_review_json(
    rows: list[dict[str, object]],
    output_path: Path,
    source_file: Path,
) -> None:
    """
    Write a machine-readable Y2 mapping review contract.

    The approved field is intentionally null at generation time. A later
    human review step can set it to true or false without changing the 
    mapping shape.
    """
    mappings = []

    for row in rows:
        mapping = dict(row)
        mapping["approved"] = None
        mappings.append(mapping)

    payload = {
        "version": "1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(source_file),
        "summary": summarize_mappings(rows),
        "mappings": mappings,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
