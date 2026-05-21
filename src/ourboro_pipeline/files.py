from pathlib import Path
import csv


def read_headers(csv_path: Path) -> list[str]:
    """
    Read only the header row from a CSV file.

    This gives us the file schema without loading the full dataset.
    """
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        return next(reader)


def write_dicts_csv(
    path: Path,
    rows: list[dict[str, object]],
    fieldnames: list[str],
) -> None:
    """
    Write a list of dictionaries to a CSV file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
