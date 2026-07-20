from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ourboro_pipeline.transform import file_sha256


def load_analysis_ready_config(path: Path) -> dict[str, Any]:
    """Load and validate analysis-ready export configuration."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Analysis-ready export config schema_version must be 1.")

    _validate_respondent_id_sources(payload)
    _require_string(
        payload,
        "cluster_join_column",
        "Analysis-ready export config requires cluster_join_column.",
    )
    _require_string(
        payload,
        "cluster_label_column",
        "Analysis-ready export config requires cluster_label_column.",
    )
    _require_string(payload, "wave_column", "Analysis-ready export config requires wave_column.")
    _validate_waves(payload)
    _validate_exclude_stems(payload)
    return payload


def _is_nonempty_string(value: object) -> bool:
    """Return true when a config value is a non-empty string."""
    return isinstance(value, str) and bool(value)


def _require_string(payload: dict[str, Any], key: str, message: str) -> None:
    """Require a named config value to be a non-empty string."""
    if not _is_nonempty_string(payload.get(key)):
        raise ValueError(message)


def _validate_string_list(value: object, message: str) -> None:
    """Require a config value to be a non-empty list of non-empty strings."""
    if not isinstance(value, list) or not value:
        raise ValueError(message)
    for item in value:
        if not _is_nonempty_string(item):
            raise ValueError(message)


def _validate_respondent_id_sources(payload: dict[str, Any]) -> None:
    """Validate old single-column and new multi-column respondent ID config."""
    respondent_id_source = payload.get("respondent_id_source_column")
    respondent_id_sources = payload.get("respondent_id_source_columns")
    if respondent_id_sources is not None:
        _validate_string_list(
            respondent_id_sources,
            "respondent_id_source_columns must be a non-empty list of column names.",
        )
        return

    if not _is_nonempty_string(respondent_id_source):
        raise ValueError(
            "Analysis-ready export config requires respondent_id_source_column or respondent_id_source_columns."
        )


def _validate_waves(payload: dict[str, Any]) -> None:
    """Validate wave labels and their source-column prefixes."""
    waves = payload.get("waves")
    if not isinstance(waves, dict) or not waves:
        raise ValueError("Analysis-ready export config requires a non-empty waves mapping.")

    prefixes: set[str] = set()
    for wave, spec in waves.items():
        if not _is_nonempty_string(wave):
            raise ValueError("Wave labels must be non-empty strings.")
        if not isinstance(spec, dict):
            raise ValueError(f"Wave {wave} must be configured as an object.")

        prefix = spec.get("prefix")
        if not _is_nonempty_string(prefix):
            raise ValueError(f"Wave {wave} requires a non-empty prefix.")
        if prefix in prefixes:
            raise ValueError(f"Wave prefix is duplicated: {prefix}")
        prefixes.add(prefix)


def _validate_exclude_stems(payload: dict[str, Any]) -> None:
    """Validate optional non-DV stem exclusions."""
    exclude_stems = payload.get("exclude_stems", [])
    if not isinstance(exclude_stems, list):
        raise ValueError("exclude_stems must be a list of non-empty strings.")
    for stem in exclude_stems:
        if not _is_nonempty_string(stem):
            raise ValueError("exclude_stems must be a list of non-empty strings.")


def _normalize_id(value: object) -> str:
    """Normalize respondent IDs while preserving original case."""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _coalesce_id_columns(dataframe: pd.DataFrame, columns: list[str]) -> pd.Series:
    """Choose the first non-empty respondent ID from configured source columns."""
    result = pd.Series("", index=dataframe.index, dtype="object")
    for column in columns:
        values = dataframe[column].map(_normalize_id)
        result = result.mask(result.eq(""), values)
    return result


def _nonempty_text(series: pd.Series) -> pd.Series:
    """Return stripped text with null values treated as empty strings."""
    return series.fillna("").astype(str).str.strip()


def read_cluster_assignments(
    clusters_csv: Path,
    *,
    join_column: str,
    label_column: str,
) -> pd.DataFrame:
    """Read and validate respondent cluster assignments."""
    clusters = pd.read_csv(
        clusters_csv,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    _require_cluster_columns(clusters, join_column, label_column)

    result = clusters[[join_column, label_column]].copy()
    result[join_column] = result[join_column].map(_normalize_id)
    result[label_column] = _nonempty_text(result[label_column])
    _validate_cluster_rows(result, join_column, label_column)
    return result


def _require_cluster_columns(
    clusters: pd.DataFrame,
    join_column: str,
    label_column: str,
) -> None:
    """Ensure cluster CSV has required join and label columns."""
    missing = {join_column, label_column} - set(clusters.columns)
    if missing:
        raise ValueError(
            f"Cluster assignments CSV is missing required columns: {', '.join(sorted(missing))}"
        )


def _validate_cluster_rows(
    clusters: pd.DataFrame,
    join_column: str,
    label_column: str,
) -> None:
    """Reject blank or duplicated cluster assignment keys."""
    if clusters[join_column].eq("").any():
        raise ValueError("Cluster assignments contain blank respondent_id values.")
    if clusters[label_column].eq("").any():
        raise ValueError("Cluster assignments contain blank cluster_label values.")
    if clusters[join_column].duplicated().any():
        duplicates = sorted(clusters.loc[clusters[join_column].duplicated(), join_column].unique())
        raise ValueError(
            "Cluster assignments contain duplicate respondent_id values: "
            + ", ".join(duplicates[:10])
        )


def _detect_wave_columns(
    dataframe: pd.DataFrame,
    *,
    waves: dict[str, dict[str, str]],
    exclude_stems: set[str],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Find numeric DV columns that are available under configured wave prefixes."""
    wave_columns: dict[str, dict[str, str]] = {}
    stem_candidates: dict[str, list[str]] = {}

    for wave, spec in waves.items():
        wave_map = _wave_column_map(dataframe, spec["prefix"], exclude_stems)
        wave_columns[wave] = wave_map
        _add_stem_candidates(stem_candidates, wave_map)

    selected_stems, excluded_non_numeric = _classify_numeric_stems(dataframe, stem_candidates)
    if not selected_stems:
        raise ValueError("No numeric wave-prefixed columns were eligible for analysis export.")

    return _filter_wave_columns(wave_columns, selected_stems), excluded_non_numeric


def _wave_column_map(
    dataframe: pd.DataFrame,
    prefix: str,
    exclude_stems: set[str],
) -> dict[str, str]:
    """Map DV stems to source columns for one wave prefix."""
    wave_map: dict[str, str] = {}
    for column in dataframe.columns:
        if not column.startswith(prefix):
            continue
        stem = column[len(prefix):]
        if not stem or stem in exclude_stems:
            continue
        wave_map[stem] = column
    return wave_map


def _add_stem_candidates(
    stem_candidates: dict[str, list[str]],
    wave_map: dict[str, str],
) -> None:
    """Track every source column seen for each DV stem."""
    for stem, column in wave_map.items():
        stem_candidates.setdefault(stem, []).append(column)


def _classify_numeric_stems(
    dataframe: pd.DataFrame,
    stem_candidates: dict[str, list[str]],
) -> tuple[list[str], list[str]]:
    """Split candidate DV stems into numeric and non-numeric groups."""
    selected_stems: list[str] = []
    excluded_non_numeric: list[str] = []
    for stem, source_columns in sorted(stem_candidates.items()):
        if _all_sources_numeric(dataframe, source_columns):
            selected_stems.append(stem)
        else:
            excluded_non_numeric.append(stem)
    return selected_stems, excluded_non_numeric


def _all_sources_numeric(dataframe: pd.DataFrame, source_columns: list[str]) -> bool:
    """Return true if every non-empty value in source columns is numeric."""
    for source_column in source_columns:
        raw = _nonempty_text(dataframe[source_column])
        nonempty = raw[raw.ne("")]
        if nonempty.empty:
            continue
        converted = pd.to_numeric(nonempty, errors="coerce")
        if converted.isna().any():
            return False
    return True


def _filter_wave_columns(
    wave_columns: dict[str, dict[str, str]],
    selected_stems: list[str],
) -> dict[str, dict[str, str]]:
    """Keep only selected numeric DV stems in each wave map."""
    selected = set(selected_stems)
    filtered: dict[str, dict[str, str]] = {}
    for wave, mapping in wave_columns.items():
        filtered_mapping: dict[str, str] = {}
        for stem, column in mapping.items():
            if stem in selected:
                filtered_mapping[stem] = column
        filtered[wave] = filtered_mapping
    return filtered


def export_analysis_ready_long(
    *,
    linked_master_csv: Path,
    clusters_csv: Path,
    config_path: Path,
    output_csv: Path,
    report_json: Path | None = None,
) -> dict[str, Any]:
    """Export linked master data as long-format analysis-ready rows."""
    config = load_analysis_ready_config(config_path)
    dataframe = _read_linked_master_csv(linked_master_csv)
    respondent_id_sources = _respondent_id_source_columns(config)
    _require_respondent_id_columns(dataframe, respondent_id_sources)
    dataframe["respondent_id"] = _coalesce_id_columns(dataframe, respondent_id_sources)

    cluster_join_column = config["cluster_join_column"]
    cluster_label_column = config["cluster_label_column"]
    wave_column = config["wave_column"]
    clusters = read_cluster_assignments(
        clusters_csv,
        join_column=cluster_join_column,
        label_column=cluster_label_column,
    )

    wave_columns, excluded_non_numeric = _detect_wave_columns(
        dataframe,
        waves=config["waves"],
        exclude_stems=set(config.get("exclude_stems", [])),
    )
    dv_columns = _dv_columns(wave_columns)
    combined = _build_long_wave_panel(dataframe, wave_columns, dv_columns, wave_column)
    if config.get("drop_all_missing_rows", True):
        combined = _drop_all_missing_dv_rows(combined, dv_columns)

    _validate_respondent_ids_present(combined)
    combined = _merge_cluster_labels(combined, clusters, cluster_join_column)
    _validate_cluster_labels_present(combined, cluster_label_column)
    combined[cluster_label_column] = _nonempty_text(combined[cluster_label_column])

    output = _analysis_output(combined, cluster_label_column, wave_column, dv_columns)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_csv, index=False, encoding="utf-8-sig")

    report = _analysis_ready_report(
        linked_master_csv=linked_master_csv,
        clusters_csv=clusters_csv,
        config_path=config_path,
        output_csv=output_csv,
        dataframe=dataframe,
        output=output,
        respondent_id_sources=respondent_id_sources,
        cluster_label_column=cluster_label_column,
        wave_column=wave_column,
        waves=config["waves"],
        dv_columns=dv_columns,
        excluded_non_numeric=excluded_non_numeric,
    )

    if report_json is not None:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _read_linked_master_csv(linked_master_csv: Path) -> pd.DataFrame:
    """Read linked master CSV with survey values preserved as strings."""
    return pd.read_csv(
        linked_master_csv,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
        low_memory=False,
    )


def _respondent_id_source_columns(config: dict[str, Any]) -> list[str]:
    """Return configured respondent ID source columns in priority order."""
    respondent_id_sources = config.get("respondent_id_source_columns")
    if respondent_id_sources is not None:
        return list(respondent_id_sources)
    return [config["respondent_id_source_column"]]


def _require_respondent_id_columns(dataframe: pd.DataFrame, columns: list[str]) -> None:
    """Ensure all configured respondent ID source columns exist."""
    missing_id_sources = []
    for column in columns:
        if column not in dataframe.columns:
            missing_id_sources.append(column)
    if missing_id_sources:
        raise ValueError(
            "Linked master is missing respondent ID source columns: "
            + ", ".join(missing_id_sources)
        )


def _dv_columns(wave_columns: dict[str, dict[str, str]]) -> list[str]:
    """Return sorted DV stems found across all configured waves."""
    stems: set[str] = set()
    for mapping in wave_columns.values():
        for stem in mapping:
            stems.add(stem)
    return sorted(stems)


def _build_long_wave_panel(
    dataframe: pd.DataFrame,
    wave_columns: dict[str, dict[str, str]],
    dv_columns: list[str],
    wave_column: str,
) -> pd.DataFrame:
    """Build long-format wave rows before cluster labels are attached."""
    long_frames: list[pd.DataFrame] = []
    for wave, mapping in wave_columns.items():
        long_frames.append(_wave_frame(dataframe, wave, mapping, dv_columns, wave_column))
    return pd.concat(long_frames, ignore_index=True)


def _wave_frame(
    dataframe: pd.DataFrame,
    wave: str,
    mapping: dict[str, str],
    dv_columns: list[str],
    wave_column: str,
) -> pd.DataFrame:
    """Build long rows for one wave label."""
    frame = pd.DataFrame(
        {
            "respondent_id": dataframe["respondent_id"],
            wave_column: wave,
        }
    )
    for dv in dv_columns:
        source_column = mapping.get(dv)
        if source_column is None:
            frame[dv] = pd.Series(float("nan"), index=dataframe.index, dtype="float64")
            continue

        raw = _nonempty_text(dataframe[source_column])
        frame[dv] = pd.to_numeric(raw.replace("", pd.NA), errors="coerce").astype(float)
    return frame


def _drop_all_missing_dv_rows(dataframe: pd.DataFrame, dv_columns: list[str]) -> pd.DataFrame:
    """Remove respondent-wave rows where every DV is missing."""
    return dataframe.loc[dataframe[dv_columns].notna().any(axis=1)].reset_index(drop=True)


def _validate_respondent_ids_present(dataframe: pd.DataFrame) -> None:
    """Reject output rows that have no respondent ID."""
    if dataframe["respondent_id"].eq("").any():
        raise ValueError("Analysis-ready export produced rows with blank respondent_id values.")


def _merge_cluster_labels(
    dataframe: pd.DataFrame,
    clusters: pd.DataFrame,
    cluster_join_column: str,
) -> pd.DataFrame:
    """Attach cluster labels by respondent ID."""
    return dataframe.merge(
        clusters.rename(columns={cluster_join_column: "respondent_id"}),
        on="respondent_id",
        how="left",
        validate="many_to_one",
    )


def _validate_cluster_labels_present(dataframe: pd.DataFrame, cluster_label_column: str) -> None:
    """Reject respondent-wave rows without a cluster label."""
    missing = dataframe[cluster_label_column].isna()
    missing = missing | _nonempty_text(dataframe[cluster_label_column]).eq("")
    if missing.any():
        missing_ids = dataframe.loc[missing, "respondent_id"].astype(str).tolist()
        raise ValueError(
            "Analysis-ready export is missing cluster labels for respondent_id values: "
            + ", ".join(missing_ids[:10])
        )


def _analysis_output(
    dataframe: pd.DataFrame,
    cluster_label_column: str,
    wave_column: str,
    dv_columns: list[str],
) -> pd.DataFrame:
    """Select final output columns and validate respondent-wave uniqueness."""
    output_columns = ["respondent_id", cluster_label_column, wave_column]
    output_columns.extend(dv_columns)
    output = dataframe[output_columns].copy()
    output = output.drop_duplicates(ignore_index=True)
    _validate_no_duplicate_respondent_wave(output, wave_column)
    return output


def _validate_no_duplicate_respondent_wave(dataframe: pd.DataFrame, wave_column: str) -> None:
    """Reject duplicate respondent-wave rows after final de-duplication."""
    duplicates = dataframe.duplicated(["respondent_id", wave_column])
    if not duplicates.any():
        return

    duplicate_rows = dataframe.loc[duplicates, ["respondent_id", wave_column]]
    formatted = []
    renamed = duplicate_rows.rename(columns={wave_column: "wave"})
    for row in renamed.itertuples(index=False):
        formatted.append(f"{row.respondent_id}:{row.wave}")
    raise ValueError(
        "Analysis-ready export produced duplicate respondent_id/wave rows: "
        + ", ".join(formatted[:10])
    )


def _wave_counts(output: pd.DataFrame, wave_column: str) -> dict[str, int]:
    """Count output rows by wave, preserving output wave order."""
    counts: dict[str, int] = {}
    for wave, count in output[wave_column].value_counts(sort=False).to_dict().items():
        counts[wave] = int(count)
    return counts


def _analysis_ready_report(
    *,
    linked_master_csv: Path,
    clusters_csv: Path,
    config_path: Path,
    output_csv: Path,
    dataframe: pd.DataFrame,
    output: pd.DataFrame,
    respondent_id_sources: list[str],
    cluster_label_column: str,
    wave_column: str,
    waves: dict[str, dict[str, str]],
    dv_columns: list[str],
    excluded_non_numeric: list[str],
) -> dict[str, Any]:
    """Build JSON report payload for analysis-ready export."""
    return {
        "method": "long analysis-ready export from linked master",
        "inputs": {
            str(linked_master_csv): file_sha256(linked_master_csv),
            str(clusters_csv): file_sha256(clusters_csv),
            str(config_path): file_sha256(config_path),
        },
        "config": {
            "respondent_id_source_columns": respondent_id_sources,
            "cluster_label_column": cluster_label_column,
            "wave_column": wave_column,
            "waves": list(waves.keys()),
        },
        "counts": {
            "linked_master_rows": int(len(dataframe)),
            "analysis_ready_rows": int(len(output)),
            "distinct_respondent_id": int(output["respondent_id"].nunique()),
            "wave_counts": _wave_counts(output, wave_column),
            "dv_columns": len(dv_columns),
            "missing_cluster_label_rows": 0,
            "duplicate_respondent_wave_rows": 0,
        },
        "dv_columns": dv_columns,
        "excluded_non_numeric_stems": excluded_non_numeric,
        "output_csv": str(output_csv),
        "output_csv_sha256": file_sha256(output_csv),
    }
