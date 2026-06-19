from pathlib import Path
import csv
from collections import Counter

import click

from ourboro_pipeline.columns import compare_column_sets, propose_y2_mappings
from ourboro_pipeline.files import read_headers, write_dicts_csv
from ourboro_pipeline.review import build_y2_mapping_review, generate_review_json, summarize_mappings
from ourboro_pipeline.spss import (
    detect_spss_metadata_conflicts,
    parse_spss_metadata_file_with_diagnostics,
)
from ourboro_pipeline.merge import merge_followup_into_master_csv

SPSS_METADATA_FIELDS = [
    "source_file",
    "source_line",
    "label_type",
    "variable",
    "value",
    "label",
]

SPSS_DIAGNOSTIC_FIELDS = [
    "source_file",
    "source_line",
    "severity",
    "code",
    "message",
    "statement",
]

SPSS_CONFLICT_FIELDS = [
    "severity",
    "code",
    "label_type",
    "variable",
    "value",
    "labels",
    "sources",
    "message",
]


@click.group()
def main() -> None:
    """
    Ourboro/OIS survey data pipeline tools.
    """


@main.command("build-review-bundle")
@click.option(
    "--followup-csv",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the new follow-up CSV file.",
)
@click.option(
    "--master-csv",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the existing master CSV file.",
)
@click.option(
    "--syntax-file",
    "syntax_files",
    required=True,
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to an SPSS .sps syntax file. Can be provided more than once.",
)
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory where the review bundle will be written.",
)
def build_review_bundle(
    followup_csv: Path,
    master_csv: Path,
    syntax_files: tuple[Path, ...],
    output_dir: Path,
) -> None:
    """
    Build one review folder with column, mapping, and SPSS metadata artifacts.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    column_dir = output_dir / "column_comparison"
    mapping_dir = output_dir / "mapping_review"
    spss_dir = output_dir / "spss_metadata"
    column_dir.mkdir(parents=True, exist_ok=True)
    mapping_dir.mkdir(parents=True, exist_ok=True)
    spss_dir.mkdir(parents=True, exist_ok=True)

    followup_headers = read_headers(followup_csv)
    master_headers = read_headers(master_csv)
    comparison = compare_column_sets(
        followup_headers=followup_headers,
        master_headers=master_headers,
    )
    possible_y2_mappings = propose_y2_mappings(
        followup_headers=followup_headers,
        master_headers=master_headers,
    )

    write_dicts_csv(
        column_dir / "columns_in_both.csv",
        comparison["columns_in_both"],
        ["column", "followup_index", "master_index", "column_family"],
    )
    write_dicts_csv(
        column_dir / "columns_only_in_followup.csv",
        comparison["columns_only_in_followup"],
        ["column", "followup_index", "column_family"],
    )
    write_dicts_csv(
        column_dir / "columns_only_in_master.csv",
        comparison["columns_only_in_master"],
        ["column", "master_index", "column_family"],
    )
    possible_mappings_path = column_dir / "possible_y2_mappings.csv"
    write_dicts_csv(
        possible_mappings_path,
        possible_y2_mappings,
        [
            "followup_column_index",
            "followup_column",
            "column_family",
            "exists_exact_in_master",
            "y0_exists_in_master",
            "y1_exists_in_master",
            "y2_exists_in_master",
            "proposed_target_column",
            "confidence",
            "reason",
        ],
    )

    column_summary = "\n".join([
        "Column Comparison Summary",
        "=" * 80,
        f"Follow-up CSV: {followup_csv}",
        f"Master CSV:    {master_csv}",
        "",
        f"Follow-up columns: {len(followup_headers)}",
        f"Master columns:    {len(master_headers)}",
        "",
        f"Exact columns in both:       {len(comparison['columns_in_both'])}",
        f"Columns only in follow-up:   {len(comparison['columns_only_in_followup'])}",
        f"Columns only in master:      {len(comparison['columns_only_in_master'])}",
        f"Possible Y2 mappings:        {len(possible_y2_mappings)}",
    ])
    column_summary_path = column_dir / "column_comparison_summary.txt"
    column_summary_path.write_text(column_summary, encoding="utf-8")

    mapping_markdown_path = mapping_dir / "y2_mapping_review.md"
    mapping_json_path = mapping_dir / "y2_mappings.json"
    mapping_markdown_path.write_text(
        build_y2_mapping_review(possible_y2_mappings),
        encoding="utf-8",
    )
    generate_review_json(
        rows=possible_y2_mappings,
        output_path=mapping_json_path,
        source_file=possible_mappings_path,
    )
    mapping_summary = summarize_mappings(possible_y2_mappings)

    spss_summary = write_spss_metadata_artifacts(
        syntax_files=syntax_files,
        output_dir=spss_dir,
    )

    bundle_summary_path = output_dir / "review_bundle_summary.md"
    bundle_summary = "\n".join([
        "# Ourboro Review Bundle",
        "",
        "## Inputs",
        "",
        f"- Follow-up CSV: `{followup_csv}`",
        f"- Master CSV: `{master_csv}`",
        *[f"- SPSS syntax: `{path}`" for path in syntax_files],
        "",
        "## Column Comparison",
        "",
        f"- Follow-up columns: {len(followup_headers)}",
        f"- Master columns: {len(master_headers)}",
        f"- Exact columns in both: {len(comparison['columns_in_both'])}",
        f"- Columns only in follow-up: {len(comparison['columns_only_in_followup'])}",
        f"- Columns only in master: {len(comparison['columns_only_in_master'])}",
        f"- Possible Y2 mappings: {mapping_summary['total']}",
        "",
        "## SPSS Metadata",
        "",
        f"- Metadata rows: {spss_summary['metadata_rows']}",
        f"- Variable labels: {spss_summary['variable_labels']}",
        f"- Value labels: {spss_summary['value_labels']}",
        f"- Diagnostics: {spss_summary['diagnostics']}",
        f"- Conflict rows: {spss_summary['conflicts']}",
        f"- Conflict warnings: {spss_summary['conflict_warnings']}",
        f"- Duplicate info: {spss_summary['duplicate_info']}",
        "",
        "## Review Checklist",
        "",
        "- Review `mapping_review/y2_mapping_review.md` for proposed column mappings.",
        "- Review `spss_metadata/spss_metadata_conflicts.csv` for label conflicts.",
        "- Confirm `spss_metadata/spss_metadata_diagnostics.csv` has no blocking parser warnings.",
        "- Treat all generated files as review artifacts, not final merged data.",
        "",
        "## Generated Folders",
        "",
        "- `column_comparison/`",
        "- `mapping_review/`",
        "- `spss_metadata/`",
    ])
    bundle_summary_path.write_text(bundle_summary, encoding="utf-8")

    click.echo("Ourboro Review Bundle")
    click.echo("=" * 80)
    click.echo(f"Output dir: {output_dir}")
    click.echo(f"Summary: {bundle_summary_path}")
    click.echo("")
    click.echo("Generated folders:")
    click.echo(f"- {column_dir}")
    click.echo(f"- {mapping_dir}")
    click.echo(f"- {spss_dir}")


@main.command("extract-spss-metadata")
@click.option(
    "--syntax-file",
    "syntax_files",
    required=True,
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to an SPSS .sps syntax file. Can be provided more than once.",
)
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory where SPSS metadata artifacts will be written.",
)
def extract_spss_metadata(
    syntax_files: tuple[Path, ...],
    output_dir: Path,
) -> None:
    """
    Extract variable/value label metadata from SPSS syntax files.
    """
    summary = write_spss_metadata_artifacts(
        syntax_files=syntax_files,
        output_dir=output_dir,
    )
    click.echo(summary["summary_text"])


def write_spss_metadata_artifacts(
    *,
    syntax_files: tuple[Path, ...],
    output_dir: Path,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata_rows: list[dict[str, str]] = []
    diagnostics: list[dict[str, str]] = []

    for syntax_file in syntax_files:
        result = parse_spss_metadata_file_with_diagnostics(syntax_file)
        metadata_rows.extend(result["metadata_rows"])
        diagnostics.extend(result["diagnostics"])

    conflicts = detect_spss_metadata_conflicts(metadata_rows)

    metadata_path = output_dir / "spss_metadata_rows.csv"
    diagnostics_path = output_dir / "spss_metadata_diagnostics.csv"
    conflicts_path = output_dir / "spss_metadata_conflicts.csv"
    summary_path = output_dir / "spss_metadata_summary.txt"

    write_dicts_csv(metadata_path, metadata_rows, SPSS_METADATA_FIELDS)
    write_dicts_csv(diagnostics_path, diagnostics, SPSS_DIAGNOSTIC_FIELDS)
    write_dicts_csv(conflicts_path, conflicts, SPSS_CONFLICT_FIELDS)

    variable_label_count = sum(
        1 for row in metadata_rows
        if row["label_type"] == "variable_label"
    )
    value_label_count = sum(
        1 for row in metadata_rows
        if row["label_type"] == "value_label"
    )
    conflict_warning_count = sum(
        1 for row in conflicts
        if row["severity"] == "warning"
    )
    duplicate_info_count = sum(
        1 for row in conflicts
        if row["severity"] == "info"
    )
    conflict_code_counts = Counter(row["code"] for row in conflicts)
    conflict_code_lines = [
        f"- {code}: {count}"
        for code, count in sorted(conflict_code_counts.items())
    ]
    if not conflict_code_lines:
        conflict_code_lines = ["- none"]

    summary_text = "\n".join([
        "SPSS Metadata Extraction Summary",
        "=" * 80,
        "Syntax files:",
        *[f"- {path}" for path in syntax_files],
        "",
        f"Metadata rows:   {len(metadata_rows)}",
        f"Variable labels: {variable_label_count}",
        f"Value labels:    {value_label_count}",
        f"Diagnostics:     {len(diagnostics)}",
        f"Conflict rows:   {len(conflicts)}",
        f"Conflict warnings: {conflict_warning_count}",
        f"Duplicate info:    {duplicate_info_count}",
        "",
        "Conflict codes:",
        *conflict_code_lines,
        "",
        "Generated files:",
        f"- {metadata_path}",
        f"- {diagnostics_path}",
        f"- {conflicts_path}",
        f"- {summary_path}",
    ])

    summary_path.write_text(summary_text, encoding="utf-8")

    return {
        "metadata_rows": len(metadata_rows),
        "variable_labels": variable_label_count,
        "value_labels": value_label_count,
        "diagnostics": len(diagnostics),
        "conflicts": len(conflicts),
        "conflict_warnings": conflict_warning_count,
        "duplicate_info": duplicate_info_count,
        "summary_text": summary_text,
        "metadata_path": metadata_path,
        "diagnostics_path": diagnostics_path,
        "conflicts_path": conflicts_path,
        "summary_path": summary_path,
    }


@main.command("mapping-review")
@click.option(
    "--mappings-csv",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to possible_y2_mappings.csv.",
)
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory where mapping review artifacts will be written.",
)
def mapping_review(mappings_csv: Path, output_dir: Path) -> None:
    """
    Generate human-readable and machine-readable Y2 mapping review artifacts.
    """
    required_fields = {
        "followup_column_index",
        "followup_column",
        "column_family",
        "exists_exact_in_master",
        "y0_exists_in_master",
        "y1_exists_in_master",
        "y2_exists_in_master",
        "proposed_target_column",
        "confidence",
        "reason",
    }

    with mappings_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise click.ClickException(f"{mappings_csv} is empty or missing a header row.")

        missing_fields = required_fields - set(reader.fieldnames)
        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise click.ClickException(
                f"{mappings_csv} is missing required columns: {missing}"
            )

        rows: list[dict[str, object]] = list(reader)

    output_dir.mkdir(parents=True, exist_ok=True)

    markdown_path = output_dir / "y2_mapping_review.md"
    json_path = output_dir / "y2_mappings.json"

    markdown_path.write_text(
        build_y2_mapping_review(rows),
        encoding="utf-8",
    )

    generate_review_json(
        rows=rows,
        output_path=json_path,
        source_file=mappings_csv,
    )

    summary = summarize_mappings(rows)

    click.echo("Y2 Mapping Review")
    click.echo("=" * 80)
    click.echo(f"Mappings CSV: {mappings_csv}")
    click.echo(f"Total mappings: {summary['total']}")
    click.echo("")
    click.echo("Generated files:")
    click.echo(f"- {markdown_path}")
    click.echo(f"- {json_path}")


@main.command("compare-columns")
@click.option(
    "--followup-csv",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the new follow-up CSV file.",
)
@click.option(
    "--master-csv",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the existing master CSV file.",
)
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory where comparison reports will be written.",
)
def compare_columns(followup_csv: Path, master_csv: Path, output_dir: Path) -> None:
    """
    Compare follow-up CSV columns against the master CSV.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    followup_headers = read_headers(followup_csv)
    master_headers = read_headers(master_csv)

    comparison = compare_column_sets(
        followup_headers=followup_headers,
        master_headers=master_headers,
    )

    possible_y2_mappings = propose_y2_mappings(
        followup_headers=followup_headers,
        master_headers=master_headers,
    )

    write_dicts_csv(
        output_dir / "columns_in_both.csv",
        comparison["columns_in_both"],
        ["column", "followup_index", "master_index", "column_family"],
    )

    write_dicts_csv(
        output_dir / "columns_only_in_followup.csv",
        comparison["columns_only_in_followup"],
        ["column", "followup_index", "column_family"],
    )

    write_dicts_csv(
        output_dir / "columns_only_in_master.csv",
        comparison["columns_only_in_master"],
        ["column", "master_index", "column_family"],
    )

    write_dicts_csv(
        output_dir / "possible_y2_mappings.csv",
        possible_y2_mappings,
        [
            "followup_column_index",
            "followup_column",
            "column_family",
            "exists_exact_in_master",
            "y0_exists_in_master",
            "y1_exists_in_master",
            "y2_exists_in_master",
            "proposed_target_column",
            "confidence",
            "reason",
        ],
    )

    summary = "\n".join([
        "Column Comparison Summary",
        "=" * 80,
        f"Follow-up CSV: {followup_csv}",
        f"Master CSV:    {master_csv}",
        "",
        f"Follow-up columns: {len(followup_headers)}",
        f"Master columns:    {len(master_headers)}",
        "",
        f"Exact columns in both:       {len(comparison['columns_in_both'])}",
        f"Columns only in follow-up:   {len(comparison['columns_only_in_followup'])}",
        f"Columns only in master:      {len(comparison['columns_only_in_master'])}",
        "",
        "Generated files:",
        f"- {output_dir / 'columns_in_both.csv'}",
        f"- {output_dir / 'columns_only_in_followup.csv'}",
        f"- {output_dir / 'columns_only_in_master.csv'}",
        f"- {output_dir / 'possible_y2_mappings.csv'}",
    ])

    summary_path = output_dir / "column_comparison_summary.txt"
    summary_path.write_text(summary, encoding="utf-8")

    click.echo(summary)


@main.command("rough-merge-followup")
@click.option(
    "--master-csv",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the existing master CSV.",
)
@click.option(
    "--followup-csv",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the follow-up CSV to append.",
)
@click.option(
    "--mappings-csv",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to possible_y2_mappings.csv.",
)
@click.option(
    "--output-csv",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output path for the rough merged master CSV.",
)
def rough_merge_followup(
    master_csv: Path,
    followup_csv: Path,
    mappings_csv: Path,
    output_csv: Path,
) -> None:
    """
    Roughly append follow-up rows into the master CSV using proposed mappings.
    """
    try:
        summary = merge_followup_into_master_csv(
            master_csv=master_csv,
            followup_csv=followup_csv,
            mappings_csv=mappings_csv,
            output_csv=output_csv,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo("Rough Follow-up Master Merge")
    click.echo("=" * 80)
    click.echo(f"Master CSV:   {master_csv}")
    click.echo(f"Follow-up CSV:{followup_csv}")
    click.echo(f"Mappings CSV: {mappings_csv}")
    click.echo(f"Output CSV:   {summary['output_csv']}")
    click.echo("")
    click.echo(f"Master encoding:     {summary['master_encoding']}")
    click.echo(f"Master rows:         {summary['master_rows']}")
    click.echo(f"Follow-up rows:      {summary['followup_rows']}")
    click.echo(f"Output rows:         {summary['output_rows']}")
    click.echo(f"Master columns:      {summary['master_columns']}")
    click.echo(f"Output columns:      {summary['output_columns']}")
    click.echo(f"New columns added:   {summary['new_columns_added']}")
    click.echo(f"Mappings used:       {summary['mappings_used']}")

    unmapped = summary["unmapped_followup_columns"]
    if unmapped:
        click.echo("")
        click.echo("Unmapped follow-up columns:")
        for column in unmapped:
            click.echo(f"- {column}")
