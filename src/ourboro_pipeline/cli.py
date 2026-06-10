from pathlib import Path
import csv

import click

from ourboro_pipeline.columns import compare_column_sets, propose_y2_mappings
from ourboro_pipeline.files import read_headers, write_dicts_csv
from ourboro_pipeline.review import build_y2_mapping_review, generate_review_json, summarize_mappings
from ourboro_pipeline.spss import parse_spss_metadata_file_with_diagnostics


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


@click.group()
def main() -> None:
    """
    Ourboro/OIS survey data pipeline tools.
    """


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
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata_rows: list[dict[str, str]] = []
    diagnostics: list[dict[str, str]] = []

    for syntax_file in syntax_files:
        result = parse_spss_metadata_file_with_diagnostics(syntax_file)
        metadata_rows.extend(result["metadata_rows"])
        diagnostics.extend(result["diagnostics"])

    metadata_path = output_dir / "spss_metadata_rows.csv"
    diagnostics_path = output_dir / "spss_metadata_diagnostics.csv"
    summary_path = output_dir / "spss_metadata_summary.txt"

    write_dicts_csv(metadata_path, metadata_rows, SPSS_METADATA_FIELDS)
    write_dicts_csv(diagnostics_path, diagnostics, SPSS_DIAGNOSTIC_FIELDS)

    variable_label_count = sum(
        1 for row in metadata_rows
        if row["label_type"] == "variable_label"
    )
    value_label_count = sum(
        1 for row in metadata_rows
        if row["label_type"] == "value_label"
    )

    summary = "\n".join([
        "SPSS Metadata Extraction Summary",
        "=" * 80,
        "Syntax files:",
        *[f"- {path}" for path in syntax_files],
        "",
        f"Metadata rows:   {len(metadata_rows)}",
        f"Variable labels: {variable_label_count}",
        f"Value labels:    {value_label_count}",
        f"Diagnostics:     {len(diagnostics)}",
        "",
        "Generated files:",
        f"- {metadata_path}",
        f"- {diagnostics_path}",
        f"- {summary_path}",
    ])

    summary_path.write_text(summary, encoding="utf-8")

    click.echo(summary)


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
