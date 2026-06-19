from __future__ import annotations

import csv
from pathlib import Path
from typing import TextIO


MASTER_ENCODINGS = ["latin-1"]


def clean_fieldnames(fieldnames: list[str]) -> list[str]:
    """Normalize header artifacts from fallback decoding."""
    if not fieldnames:
        return fieldnames

    cleaned = list(fieldnames)
    cleaned[0] = cleaned[0].removeprefix("\ufeff").removeprefix("\u00ef\u00bb\u00bf")
    return cleaned


def open_csv_with_fallback(path: Path) -> tuple[TextIO, str]:
    last_error: UnicodeDecodeError | None = None

    for encoding in MASTER_ENCODINGS:
        handle = path.open("r", encoding=encoding, newline="")
        try:
            handle.readline()
            handle.seek(0)
            return handle, encoding
        except UnicodeDecodeError as exc:
            handle.close()
            last_error = exc

    if last_error is not None:
        raise last_error
    
    # Technically unreachable -- latin-1 maps every byte 0x00-0xFF to Unicode, 
    # so it never raises UnicodeDecodeError
    raise UnicodeDecodeError("utf-8", b"", 0, 1, "Unable to decode CSV")


def read_mapping_rows(mappings_csv: Path) -> list[dict[str, str]]:
    with mappings_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"{mappings_csv} is empty or missing a header row.")
        return list(reader)
    

def build_followup_to_master_map(rows: list[dict[str, str]]) -> dict[str, str]:
    result: dict[str, str] = {}

    for row in rows:
        followup_column = row.get("followup_column", "").strip()
        target_column = row.get("proposed_target_column", "").strip()

        if not followup_column:
            continue
        
        # Special case
        if not target_column and followup_column == "BrokerPanelId":
            target_column = "Y2_BrokerPanelId"
        
        if target_column:
            result[followup_column] = target_column

    return result


def is_qualtrics_metadata_row(row: dict[str, str]) -> bool:
    """Return whether a follow-up row contains Qualtrics import metadata."""
    response_id = (row.get("ResponseId") or "").strip()
    return (
        response_id == "Response ID"
        or response_id.startswith('{"ImportId"')
    )


def merge_followup_into_master_csv(
    *,
    master_csv: Path,
    followup_csv: Path,
    mappings_csv: Path,
    output_csv: Path,
) -> dict[str, object]:
    mapping_rows = read_mapping_rows(mappings_csv)
    followup_to_master = build_followup_to_master_map(mapping_rows)

    master_file, master_encoding = open_csv_with_fallback(master_csv)
    with master_file:
        master_reader = csv.DictReader(master_file)
        if master_reader.fieldnames is None:
            raise ValueError(f"{master_csv} is empty or missing a header row.")
        
        master_fields = clean_fieldnames(list(master_reader.fieldnames))
        master_reader.fieldnames = master_fields

        with followup_csv.open("r", encoding="utf-8-sig", newline="") as followup_file:
            followup_reader = csv.DictReader(followup_file)

            if followup_reader.fieldnames is None:
                raise ValueError(f"{followup_csv} is empty or missing a header row.")
            
            mapped_target_fields = [
                target
                for source, target in followup_to_master.items()
                if source in followup_reader.fieldnames
            ]

            new_fields = [
                field
                for field in mapped_target_fields
                if field not in master_fields
            ]

            output_fields = master_fields + new_fields

            output_csv.parent.mkdir(parents=True, exist_ok=True)
            with output_csv.open("w", encoding="utf-8", newline="") as output_file:
                writer = csv.DictWriter(output_file, fieldnames=output_fields)
                writer.writeheader()

                master_rows = 0
                for row in master_reader:
                    writer.writerow({field: row.get(field, "") for field in output_fields})
                    master_rows += 1

                followup_rows = 0
                for row in followup_reader:
                    if is_qualtrics_metadata_row(row):
                        continue

                    output_row = {field: "" for field in output_fields}
                    for source, target in followup_to_master.items():
                        if source in row and target in output_row:
                            output_row[target] = row[source]
                    writer.writerow(output_row)
                    followup_rows += 1

    unmapped_followup_columns = [
        row.get("followup_column", "")
        for row in mapping_rows
        if row.get("followup_column", "") not in followup_to_master
    ]

    return {
        "master_rows": master_rows,
        "followup_rows": followup_rows,
        "output_rows": master_rows + followup_rows,
        "master_columns": len(master_fields),
        "output_columns": len(output_fields),
        "new_columns_added": len(new_fields),
        "new_columns": new_fields,
        "mappings_used": len(followup_to_master),
        "unmapped_followup_columns": unmapped_followup_columns,
        "master_encoding": master_encoding,
        "output_csv": output_csv,
    }


