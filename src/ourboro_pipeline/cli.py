from pathlib import Path

import click

from ourboro_pipeline.columns import compare_column_sets, propose_y2_mappings
from ourboro_pipeline.files import read_headers, write_dicts_csv


@click.group()
def main() -> None:
    """
    Ourboro/OIS survey data pipeline tools.
    """


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
