# NOTE (MJ):
# This is a local prototype.
# Input/output paths are hard-coded and will be parameterized later.

import re
import csv
import pandas as pd
from pathlib import Path


def read_sps_file(file_path):
    """
    Read an SPSS syntax file and return all text.
    """
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def parse_recodes(text, file_name):
    """
    Find RECODE statements.

    Example:
    Recode Q25_3 (...) into Q25_3di.

    Output:
    variable = Q25_3di
    case_type = recode
    source_variables = Q25_3
    """

    rows = []

    pattern = re.compile(
        r"Recode\s+([A-Za-z0-9_$]+).*?\s+into\s+([A-Za-z0-9_$]+)",
        re.IGNORECASE,
    )

    for source, target in pattern.findall(text):
        rows.append(
            {
                "file": file_name,
                "variable": target,
                "case_type": "recode",
                "source_variables": source,
            }
        )

    return rows


def parse_computes(text, file_name):
    """
    Find COMPUTE statements.

    Example:
    Compute PlanBuyDEX = (Q12bal + Q25_1bal)/2.

    Output:
    variable = PlanBuyDEX
    case_type = compute
    source_variables = Q12bal,Q25_1bal
    """

    rows = []

    pattern = re.compile(
        r"Compute\s+([A-Za-z0-9_$]+)\s*=\s*(.*?)\.",
        re.IGNORECASE | re.DOTALL,
    )

    for target, expression in pattern.findall(text):
        vars_found = sorted(
            set(
                re.findall(
                    r"\b[A-Za-z][A-Za-z0-9_$]*\b",
                    expression,
                )
            )
        )

        rows.append(
            {
                "file": file_name,
                "variable": target,
                "case_type": "compute",
                "source_variables": ",".join(vars_found),
            }
        )

    return rows


def parse_filters(text, file_name):
    """
    Find filter variables.

    Example:
    COMPUTE filter_$=(Province = 6).

    Output:
    variable = filter_$
    case_type = filter
    source_variables = Province
    """

    rows = []

    pattern = re.compile(
        r"COMPUTE\s+(filter_\$)\s*=\s*\((.*?)\)\.",
        re.IGNORECASE | re.DOTALL,
    )

    for target, expression in pattern.findall(text):
        vars_found = sorted(
            set(
                re.findall(
                    r"\b[A-Za-z][A-Za-z0-9_$]*\b",
                    expression,
                )
            )
        )

        rows.append(
            {
                "file": file_name,
                "variable": target,
                "case_type": "filter",
                "source_variables": ",".join(vars_found),
            }
        )

    return rows


def parse_weights(text, file_name):
    """
    Find WEIGHT BY statements.

    Example:
    WEIGHT BY Weights2024.

    Output:
    variable = Weights2024
    case_type = weight
    """

    rows = []

    pattern = re.compile(
        r"WEIGHT\s+BY\s+([A-Za-z0-9_$]+)",
        re.IGNORECASE,
    )

    for weight_var in pattern.findall(text):
        rows.append(
            {
                "file": file_name,
                "variable": weight_var,
                "case_type": "weight",
                "source_variables": weight_var,
            }
        )

    return rows


def save_csv(rows, output_file):
    """
    Save parsed metadata to CSV.
    """

    fieldnames = [
        "file",
        "variable",
        "case_type",
        "source_variables",
    ]

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for row in rows:
            writer.writerow(row)


def save_duplicate_variables(rows, output_file):
    """
    Save duplicate variable report.
    """
    df = pd.DataFrame(rows)

    dupes = df[df.duplicated(subset=["variable"], keep=False)]

    dupes = dupes.sort_values("variable")

    dupes.to_csv(output_file, index=False)


def main():
    """
    Main program.
    """

    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    DERIVED_DIR = PROJECT_ROOT / "data" / "derived"
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)

    sps_file = PROJECT_ROOT / "OIS - SyntaxWorkingFile Jan 15 25 V7ap.sps"

    text = read_sps_file(sps_file)

    rows = []
    rows.extend(parse_recodes(text, sps_file.name))
    rows.extend(parse_computes(text, sps_file.name))
    rows.extend(parse_filters(text, sps_file.name))
    rows.extend(parse_weights(text, sps_file.name))

    output_file = DERIVED_DIR / "sps_variable_reference.csv"
    duplicate_file = DERIVED_DIR / "duplicate_variables_report.csv"

    save_csv(rows, output_file)
    save_duplicate_variables(rows, duplicate_file)

    print(f"Saved {len(rows)} rows")
    print(output_file)


if __name__ == "__main__":
    main()
