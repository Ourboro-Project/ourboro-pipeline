from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyreadstat


SUPPORTED_OPERATIONS = {
    "recode",
    "recode_many",
    "multiply_many",
    "strict_average",
    "conditional_assign",
}

NUMERIC_METADATA_COLUMNS = {
    "Status",
    "Progress",
    "Duration (in seconds)",
    "Finished",
    "LocationLatitude",
    "LocationLongitude",
}


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        block = handle.read(1024 * 1024)
        while block:
            digest.update(block)
            block = handle.read(1024 * 1024)
    return digest.hexdigest()


def load_transform_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Transformation config schema_version must be 1.")
    transformations = payload.get("transformations")
    if not isinstance(transformations, list):
        raise ValueError("Transformation config must contain a transformations list.")

    seen_targets: set[str] = set()
    for index, spec in enumerate(transformations):
        if not isinstance(spec, dict):
            raise ValueError(f"Transformation {index} must be an object.")
        operation = spec.get("operation")
        if operation not in SUPPORTED_OPERATIONS:
            raise ValueError(f"Transformation {index} has unsupported operation: {operation}")
        targets = _spec_targets(spec, index=index)
        for target in targets:
            if target in seen_targets:
                raise ValueError(f"Transformation target is duplicated: {target}")
            seen_targets.add(target)

    expected = payload.get("expected", {})
    expected_derived = expected.get("derived_columns")
    if expected_derived is not None and expected_derived != len(seen_targets):
        raise ValueError(
            f"Config declares {expected_derived} derived columns but defines "
            f"{len(seen_targets)} targets."
        )
    return payload


def _spec_targets(spec: dict[str, Any], *, index: int) -> list[str]:
    if spec["operation"] in {"recode_many", "multiply_many"}:
        pairs = spec.get("pairs")
        if not isinstance(pairs, list) or not pairs:
            raise ValueError(f"Transformation {index} requires non-empty pairs.")
        targets: list[str] = []
        for pair in pairs:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError(f"Transformation {index} contains an invalid source/target pair.")
            source, target = pair
            if not isinstance(source, str) or not source:
                raise ValueError(f"Transformation {index} contains an invalid source/target pair.")
            if not isinstance(target, str) or not target:
                raise ValueError(f"Transformation {index} contains an invalid source/target pair.")
            targets.append(target)
        return targets

    target = spec.get("target")
    if not isinstance(target, str) or not target:
        raise ValueError(f"Transformation {index} requires a target.")
    return [target]


def _is_metadata_row(dataframe: pd.DataFrame) -> pd.Series:
    if "ResponseId" not in dataframe:
        raise ValueError("Input CSV is missing required column: ResponseId")
    response_id = dataframe["ResponseId"].fillna("").astype(str).str.strip()
    return response_id.eq("Response ID") | response_id.str.startswith('{"ImportId"')


def make_spss_name(name: str, used: set[str]) -> str:
    cleaned = "".join(character for character in name if character.isalnum() or character == "_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"V_{cleaned}"
    cleaned = cleaned[:64]
    candidate = cleaned
    suffix = 2
    while candidate.casefold() in used:
        suffix_text = f"_{suffix}"
        candidate = f"{cleaned[:64 - len(suffix_text)]}{suffix_text}"
        suffix += 1
    used.add(candidate.casefold())
    return candidate


def should_be_numeric(name: str) -> bool:
    if name in NUMERIC_METADATA_COLUMNS or name == "ETHICS":
        return True
    return name.startswith("Q") and not name.endswith("_TEXT") and name != "QClosing"


def coerce_declared_numeric_columns(
    dataframe: pd.DataFrame,
    original_to_spss: dict[str, str],
) -> list[str]:
    rejected: list[str] = []
    for original, column in original_to_spss.items():
        if not should_be_numeric(original):
            continue
        source = dataframe[column].fillna("").astype(str)
        nonempty = source[source.ne("")]
        converted = pd.to_numeric(nonempty, errors="coerce")
        if converted.isna().any():
            rejected.append(column)
            continue
        dataframe[column] = pd.to_numeric(source.replace("", pd.NA), errors="coerce").astype(float)
    return rejected


def _numeric_series(dataframe: pd.DataFrame, column: str) -> pd.Series:
    if column not in dataframe:
        raise ValueError(f"Transformation source column is missing: {column}")
    source = dataframe[column]
    if pd.api.types.is_numeric_dtype(source):
        return pd.to_numeric(source, errors="coerce")
    text = source.fillna("").astype(str).str.strip()
    converted = pd.to_numeric(text.replace("", pd.NA), errors="coerce")
    invalid = text.ne("") & converted.isna()
    if invalid.any():
        row_number = int(invalid[invalid].index[0]) + 2
        raise ValueError(f"Non-numeric value in {column} at CSV row {row_number}.")
    return converted.astype(float)


def _configured_value(value: Any) -> float:
    if value == "missing" or value is None:
        return float("nan")
    if not isinstance(value, (int, float)):
        raise ValueError(f"Configured transformation value must be numeric or missing: {value}")
    return float(value)


def _apply_recode(
    dataframe: pd.DataFrame,
    *,
    source: str,
    target: str,
    spec: dict[str, Any],
) -> None:
    source_values = _numeric_series(dataframe, source)
    result = pd.Series(float("nan"), index=dataframe.index, dtype="float64")
    matched = pd.Series(False, index=dataframe.index)

    for raw_source, raw_target in spec.get("values", {}).items():
        source_value = float(raw_source)
        mask = source_values.eq(source_value)
        result.loc[mask] = _configured_value(raw_target)
        matched |= mask

    for raw_range in spec.get("ranges", []):
        if not isinstance(raw_range, list) or len(raw_range) != 3:
            raise ValueError(f"Invalid range mapping for target {target}.")
        low, high, raw_target = raw_range
        mask = source_values.between(float(low), float(high), inclusive="both")
        result.loc[mask] = _configured_value(raw_target)
        matched |= mask

    if "else" in spec and spec["else"] != "missing":
        result.loc[source_values.notna() & ~matched] = _configured_value(spec["else"])
    dataframe[target] = result


def _condition_mask(dataframe: pd.DataFrame, conditions: list[dict[str, Any]]) -> pd.Series:
    mask = pd.Series(True, index=dataframe.index)
    for condition in conditions:
        column = condition.get("column")
        if not isinstance(column, str):
            raise ValueError("Conditional rule requires a column.")
        source = _numeric_series(dataframe, column)
        if "equals" in condition:
            mask &= source.eq(float(condition["equals"]))
        elif "between" in condition:
            bounds = condition["between"]
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise ValueError(f"Invalid between condition for {column}.")
            mask &= source.between(float(bounds[0]), float(bounds[1]), inclusive="both")
        else:
            raise ValueError(f"Unsupported condition for {column}.")
    return mask


def apply_transform_config(
    dataframe: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, dict[float, str]]]:
    result = dataframe.copy()
    value_labels: dict[str, dict[float, str]] = {}

    for spec in config["transformations"]:
        operation = spec["operation"]
        if operation in {"recode", "recode_many"}:
            if operation == "recode_many":
                pairs = spec["pairs"]
            else:
                pairs = [[spec["source"], spec["target"]]]
            for source, target in pairs:
                _apply_recode(result, source=source, target=target, spec=spec)
        elif operation == "multiply_many":
            factor = float(spec["factor"])
            for source, target in spec["pairs"]:
                result[target] = _numeric_series(result, source) * factor
        elif operation == "strict_average":
            sources = spec.get("sources")
            if not isinstance(sources, list) or not sources:
                raise ValueError(f"strict_average target {spec['target']} requires sources.")
            numeric_sources = []
            for source in sources:
                numeric_sources.append(_numeric_series(result, source))
            numeric = pd.concat(numeric_sources, axis=1)
            result[spec["target"]] = numeric.sum(axis=1, skipna=False) / len(sources)
        elif operation == "conditional_assign":
            target = spec["target"]
            result[target] = _configured_value(spec.get("default", "missing"))
            for rule in spec.get("rules", []):
                mask = _condition_mask(result, rule.get("when", []))
                if "copy" in rule:
                    result.loc[mask, target] = _numeric_series(result, rule["copy"]).loc[mask]
                else:
                    result.loc[mask, target] = _configured_value(rule.get("value"))

        labels = spec.get("value_labels")
        if labels:
            for target in _spec_targets(spec, index=0):
                target_labels = {}
                for value, label in labels.items():
                    target_labels[float(value)] = label
                value_labels[target] = target_labels

    return result, value_labels


def transform_wave(
    *,
    input_csv: Path,
    master_sav: Path,
    config_path: Path,
    output_csv: Path,
    output_sav: Path,
    report_json: Path | None = None,
    enforce_expected: bool = True,
) -> dict[str, Any]:
    config = load_transform_config(config_path)
    dataframe = pd.read_csv(
        input_csv,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    dataframe = dataframe.loc[~_is_metadata_row(dataframe)].reset_index(drop=True)
    original_columns = list(dataframe.columns)
    used_names: set[str] = set()
    renamed = {}
    for original in original_columns:
        renamed[original] = make_spss_name(original, used_names)
    dataframe = dataframe.rename(columns=renamed)
    input_columns = list(dataframe.columns)
    rejected_numeric_columns = coerce_declared_numeric_columns(dataframe, renamed)
    expected = config.get("expected", {})
    if enforce_expected:
        if len(dataframe) != expected.get("input_rows"):
            raise ValueError(
                f"Expected {expected.get('input_rows')} input rows, found {len(dataframe)}."
            )
        if len(input_columns) != expected.get("input_columns"):
            raise ValueError(
                f"Expected {expected.get('input_columns')} input columns, found {len(input_columns)}."
            )

    transformed, value_labels = apply_transform_config(dataframe, config)
    if enforce_expected and len(transformed.columns) != expected.get("output_columns"):
        raise ValueError(
            f"Expected {expected.get('output_columns')} output columns, "
            f"found {len(transformed.columns)}."
        )

    id_column = expected.get("id_column", "ResponseId")
    ids = transformed[id_column].astype(str).str.strip()
    if ids.eq("").any() or ids.duplicated().any():
        raise ValueError(f"{id_column} values must be populated and unique.")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_sav.parent.mkdir(parents=True, exist_ok=True)
    transformed.to_csv(output_csv, index=False, encoding="utf-8-sig")

    sav_data = transformed.copy()
    alignment = config.get("sav_alignment", {})
    excel_epoch = pd.Timestamp("1899-12-30")
    for column in alignment.get("date_columns", []):
        timestamps = pd.to_datetime(
            sav_data[column],
            format="%Y-%m-%d %H:%M:%S",
            errors="raise",
        )
        sav_data[column] = ((timestamps - excel_epoch) / pd.Timedelta(days=1)).astype(float)
    for column in alignment.get("empty_numeric_columns", []):
        if sav_data[column].fillna("").astype(str).str.strip().ne("").any():
            raise ValueError(f"Expected {column} to contain only blank values.")
        sav_data[column] = float("nan")

    _, master_metadata = pyreadstat.read_sav(master_sav, metadataonly=True)
    master_columns = set(master_metadata.column_names)
    if not master_columns:
        raise ValueError("Master SAV contains no columns.")
    variable_formats = {}
    for column in sav_data.columns:
        if pd.api.types.is_numeric_dtype(sav_data[column]):
            variable_formats[column] = "F8.2"
    for column in alignment.get("date_columns", []):
        variable_formats[column] = "F18.12"
    for column in alignment.get("empty_numeric_columns", []):
        variable_formats[column] = "F8.2"

    column_labels = {}
    for original in original_columns:
        column_labels[renamed[original]] = original
    pyreadstat.write_sav(
        sav_data,
        output_sav,
        file_label="Ourboro transformed Y2 follow-up aligned to master types",
        column_labels=column_labels,
        variable_value_labels=value_labels,
        variable_format=variable_formats,
        compress=True,
    )

    report: dict[str, Any] = {
        "input_csv": str(input_csv),
        "master_sav": str(master_sav),
        "config": str(config_path),
        "input_rows": len(dataframe),
        "input_columns": len(input_columns),
        "derived_columns": len(transformed.columns) - len(input_columns),
        "output_rows": len(transformed),
        "output_columns": len(transformed.columns),
        "output_csv": str(output_csv),
        "output_sav": str(output_sav),
        "output_csv_sha256": file_sha256(output_csv),
        "output_sav_sha256": file_sha256(output_sav),
        "rejected_numeric_columns": rejected_numeric_columns,
    }
    if report_json is not None:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def validate_transformation(
    *,
    candidate_sav: Path,
    oracle_sav: Path,
    report_json: Path | None = None,
    id_column: str = "ResponseId",
    tolerance: float = 1e-12,
) -> dict[str, Any]:
    candidate, candidate_metadata = pyreadstat.read_sav(candidate_sav)
    oracle, oracle_metadata = pyreadstat.read_sav(oracle_sav)
    issues: list[dict[str, Any]] = []

    if list(candidate.columns) != list(oracle.columns):
        issues.append({"code": "COLUMN_MISMATCH"})
    if id_column not in candidate or id_column not in oracle:
        issues.append({"code": "MISSING_ID_COLUMN", "column": id_column})
    else:
        for label, dataframe in (("candidate", candidate), ("oracle", oracle)):
            ids = dataframe[id_column].fillna("").astype(str).str.strip()
            if ids.eq("").any() or ids.duplicated().any():
                issues.append({"code": "INVALID_IDS", "dataset": label})

    shared_columns = []
    for column in oracle.columns:
        if column in candidate.columns:
            shared_columns.append(column)
    if id_column in candidate and id_column in oracle:
        candidate = candidate.set_index(id_column, drop=False)
        oracle = oracle.set_index(id_column, drop=False)
        if set(candidate.index) != set(oracle.index):
            issues.append({"code": "ID_SET_MISMATCH"})
        else:
            candidate = candidate.loc[oracle.index]
            for column in shared_columns:
                left = candidate[column]
                right = oracle[column]
                if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
                    mismatch = pd.Series(
                        ~np.isclose(
                            left.astype(float),
                            right.astype(float),
                            rtol=0,
                            atol=tolerance,
                            equal_nan=True,
                        ),
                        index=left.index,
                    )
                else:
                    left_text = left.fillna("").astype(str)
                    right_text = right.fillna("").astype(str)
                    mismatch = ~left_text.eq(right_text)
                mismatch_count = int(mismatch.sum())
                if mismatch_count:
                    examples = []
                    for value in mismatch[mismatch].index[:5]:
                        examples.append(str(value))
                    issues.append({
                        "code": "VALUE_MISMATCH",
                        "column": column,
                        "count": mismatch_count,
                        "response_ids": examples,
                    })

    candidate_labels = dict(zip(candidate_metadata.column_names, candidate_metadata.column_labels))
    oracle_labels = dict(zip(oracle_metadata.column_names, oracle_metadata.column_labels))
    for column in shared_columns:
        if candidate_labels.get(column) != oracle_labels.get(column):
            issues.append({"code": "VARIABLE_LABEL_MISMATCH", "column": column})
        if candidate_metadata.variable_value_labels.get(column, {}) != (
            oracle_metadata.variable_value_labels.get(column, {})
        ):
            issues.append({"code": "VALUE_LABEL_MISMATCH", "column": column})
        candidate_format = candidate_metadata.original_variable_types.get(column, "")
        oracle_format = oracle_metadata.original_variable_types.get(column, "")
        candidate_family = candidate_format[:1]
        oracle_family = oracle_format[:1]
        if candidate_family != oracle_family:
            issues.append({
                "code": "VARIABLE_FORMAT_MISMATCH",
                "column": column,
                "candidate": candidate_format,
                "oracle": oracle_format,
            })

    report: dict[str, Any] = {
        "candidate_sav": str(candidate_sav),
        "oracle_sav": str(oracle_sav),
        "candidate_sha256": file_sha256(candidate_sav),
        "oracle_sha256": file_sha256(oracle_sav),
        "rows": len(oracle),
        "columns": len(oracle.columns),
        "tolerance": tolerance,
        "passed": not issues,
        "issues": issues,
    }
    if report_json is not None:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if issues:
        raise ValueError(
            f"Transformation differs from PSPP oracle: {len(issues)} issue(s). "
            f"See {report_json or 'validation report'} for details."
        )
    return report
