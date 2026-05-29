from pathlib import Path

from ourboro_pipeline.files import read_headers


def test_read_headers_reads_first_csv_row() -> None:
    fixture = Path("tests/fixtures/followup_small.csv")

    headers = read_headers(fixture)

    assert headers == ["StartDate", "EndDate", "Q1", "Q2", "Q9_6_TEXT"]
