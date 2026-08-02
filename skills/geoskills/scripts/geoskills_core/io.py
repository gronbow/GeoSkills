"""Privacy-safe table input shared by GeoSkills workflows."""

from __future__ import annotations

import csv
import codecs
import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TypeAlias

import pandas as pd

from .analytes import (
    GROUP_NAME_ALIASES,
    SAMPLE_NAME_ALIASES,
    AnalyteMatch,
    clean_name,
    infer_unit,
    match_analyte,
)
from .errors import (
    FileSizeError,
    InputValidationError,
    TableReadError,
    TextEncodingError,
    UnsupportedFormatError,
    WorksheetError,
)


SUPPORTED_SUFFIXES = frozenset({".csv", ".txt", ".xlsx"})
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024
TEXT_ENCODINGS = ("utf-8-sig", "gb18030")

TransposeResult: TypeAlias = tuple[pd.DataFrame, dict[str, Any]]
Transposer: TypeAlias = Callable[[pd.DataFrame], TransposeResult | None]
AnalyteMatcher: TypeAlias = Callable[[object], AnalyteMatch | None]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_input_file(
    path: str | Path,
    *,
    max_file_size_bytes: int = MAX_FILE_SIZE_BYTES,
) -> Path:
    """Validate a supported local input path without exposing its location."""
    input_path = Path(path)
    display_name = input_path.name or "input"
    if not input_path.exists() or not input_path.is_file():
        raise InputValidationError(
            f"未找到输入文件：{display_name}。",
            code="E106",
            details={"filename": display_name},
            suggested_action=(
                "确认文件位于配方旁边，或修正 input.file 后重新运行 plan。"
            ),
        )
    size_bytes = input_path.stat().st_size
    if size_bytes > max_file_size_bytes:
        raise FileSizeError(
            f"Input file exceeds the {max_file_size_bytes}-byte limit.",
            details={
                "filename": display_name,
                "size_bytes": size_bytes,
                "max_size_bytes": max_file_size_bytes,
            },
        )
    suffix = input_path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedFormatError(
            "Supported formats are .csv, .txt, and .xlsx.",
            details={"filename": display_name, "format": suffix},
        )
    return input_path


def build_source_metadata(path: str | Path) -> dict[str, Any]:
    """Build share-safe provenance: filename, content hash, and file size."""
    input_path = Path(path)
    return {
        "filename": input_path.name,
        "file_sha256": _sha256(input_path),
        "size_bytes": input_path.stat().st_size,
        "format": input_path.suffix.lower(),
        "sheet": None,
        "sheet_names": [],
        "encoding": None,
        "delimiter": None,
        "layout": None,
        "transformation": None,
    }


def sniff_text_format(path: str | Path) -> tuple[str, str]:
    """Detect UTF-8/GB18030 and comma/tab separation."""
    input_path = Path(path)
    raw = input_path.read_bytes()[:65536]
    decoded: str | None = None
    encoding: str | None = None
    for candidate in TEXT_ENCODINGS:
        try:
            decoder = codecs.getincrementaldecoder(candidate)(errors="strict")
            decoded = decoder.decode(raw, final=False)
            encoding = candidate
            break
        except UnicodeDecodeError:
            continue
    if decoded is None or encoding is None:
        raise TextEncodingError(
            "Text encoding is not supported; use UTF-8 or GB18030.",
            details={"filename": input_path.name},
        )

    try:
        delimiter = csv.Sniffer().sniff(decoded, delimiters=",\t").delimiter
    except csv.Error:
        first_line = decoded.splitlines()[0] if decoded.splitlines() else ""
        delimiter = (
            "\t" if first_line.count("\t") > first_line.count(",") else ","
        )
    return encoding, delimiter


def resolve_sheet(
    sheet_names: list[str] | tuple[str, ...],
    requested: str | int | None,
) -> str | None:
    """Resolve one worksheet, without silently choosing among several."""
    names = list(sheet_names)
    if requested is None:
        return names[0] if len(names) == 1 else None
    if isinstance(requested, int):
        index = requested
    else:
        requested_text = str(requested)
        if requested_text in names:
            return requested_text
        index = int(requested_text) if requested_text.isdigit() else -1
    if 0 <= index < len(names):
        return names[index]
    raise WorksheetError(
        f"Worksheet {requested!r} does not exist.",
        details={"requested_sheet": requested, "sheet_names": names},
    )


def _coerce_match(
    value: AnalyteMatch | Mapping[str, Any] | None,
    source_label: object,
) -> AnalyteMatch | None:
    """Accept the public match object and a small mapping compatibility form."""
    if value is None or isinstance(value, AnalyteMatch):
        return value
    canonical = value.get("analyte") or value.get("canonical")
    if not canonical:
        return None
    return AnalyteMatch(
        canonical=str(canonical),
        kind=str(value.get("kind", "analyte")),
        required_unit=str(value.get("required_unit", "unknown")),
        source_label=str(source_label),
        explicit_unit=str(value.get("explicit_unit", infer_unit(source_label))),
    )


def adapt_transposed_table(
    raw: pd.DataFrame,
    *,
    matcher: Callable[
        [object], AnalyteMatch | Mapping[str, Any] | None
    ] = match_analyte,
    min_analytes: int = 3,
    min_samples: int = 2,
) -> TransposeResult | None:
    """Convert a common analytes-by-row table to one row per sample.

    This is deliberately a conservative skeleton. It acts only when there is
    one unambiguous sample-header row and at least ``min_analytes`` exact
    registry matches. Otherwise it leaves the table untouched.
    """
    if (
        raw.empty
        or raw.shape[0] < min_analytes + 1
        or raw.shape[1] < min_samples + 1
    ):
        return None

    best_label_column: int | None = None
    best_rows: list[tuple[int, AnalyteMatch]] = []
    for column_index in range(raw.shape[1]):
        matches: list[tuple[int, AnalyteMatch]] = []
        seen: set[str] = set()
        duplicate = False
        for row_index, label in raw.iloc[:, column_index].items():
            analyte = _coerce_match(matcher(label), label)
            if analyte is None:
                continue
            if analyte.canonical in seen:
                duplicate = True
                break
            seen.add(analyte.canonical)
            matches.append((int(row_index), analyte))
        if not duplicate and len(matches) > len(best_rows):
            best_label_column = column_index
            best_rows = matches

    if best_label_column is None or len(best_rows) < min_analytes:
        return None

    sample_rows = [
        int(row_index)
        for row_index, label in raw.iloc[:, best_label_column].items()
        if clean_name(label) in SAMPLE_NAME_ALIASES
        and int(raw.iloc[int(row_index)].notna().sum()) >= min_samples + 1
    ]
    if len(sample_rows) != 1:
        return None
    sample_row = sample_rows[0]

    sample_columns = [
        column_index
        for column_index in range(raw.shape[1])
        if column_index != best_label_column
        and pd.notna(raw.iat[sample_row, column_index])
        and str(raw.iat[sample_row, column_index]).strip()
    ]
    if len(sample_columns) < min_samples:
        return None

    group_row: int | None = None
    for row_index in range(sample_row):
        if (
            clean_name(raw.iat[row_index, best_label_column])
            in GROUP_NAME_ALIASES
        ):
            group_row = row_index

    matched_row_numbers = {row_index for row_index, _ in best_rows}
    unit_by_row: dict[int, str] = {}
    current_unit = "unknown"
    for row_index in range(sample_row + 1, raw.shape[0]):
        label = raw.iat[row_index, best_label_column]
        explicit_unit = infer_unit(label)
        if explicit_unit != "unknown" and row_index not in matched_row_numbers:
            current_unit = explicit_unit
        if row_index in matched_row_numbers:
            unit_by_row[row_index] = (
                explicit_unit if explicit_unit != "unknown" else current_unit
            )

    converted: dict[str, list[Any]] = {
        "Sample": [
            str(raw.iat[sample_row, column]).strip()
            for column in sample_columns
        ]
    }
    if group_row is not None:
        group_values = pd.Series(
            [raw.iat[group_row, column] for column in sample_columns],
            dtype="object",
        ).ffill()
        if group_values.notna().any():
            converted["Group"] = [
                None if pd.isna(value) else str(value).strip()
                for value in group_values.tolist()
            ]

    recognized: list[dict[str, Any]] = []
    output_names = set(converted)
    for row_index, analyte in best_rows:
        unit = unit_by_row.get(row_index, "unknown")
        output_name = (
            f"{analyte.canonical}_{unit}"
            if unit != "unknown"
            else analyte.canonical
        )
        if output_name in output_names:
            return None
        output_names.add(output_name)
        converted[output_name] = [
            raw.iat[row_index, column] for column in sample_columns
        ]
        recognized.append(
            {
                **analyte.to_dict(),
                "source_row": row_index + 1,
                "inferred_unit": unit,
                "output_column": output_name,
            }
        )

    transformation = {
        "method": "auto_transpose_geochemical_analytes_by_row",
        "sample_header_row": sample_row + 1,
        "sample_identifier_label": str(
            raw.iat[sample_row, best_label_column]
        ),
        "sample_count": len(sample_columns),
        "analyte_label_column": best_label_column + 1,
        "group_header_row": None if group_row is None else group_row + 1,
        "recognized_analytes": recognized,
    }
    return pd.DataFrame(converted), transformation


def _read_text(
    path: Path,
    metadata: dict[str, Any],
    transposer: Transposer | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    encoding, delimiter = sniff_text_format(path)
    metadata["encoding"] = encoding
    metadata["delimiter"] = "TAB" if delimiter == "\t" else delimiter
    if transposer is not None:
        raw = pd.read_csv(
            path,
            sep=delimiter,
            encoding=encoding,
            header=None,
        )
        adapted = transposer(raw)
        if adapted is not None:
            frame, transformation = adapted
            metadata["layout"] = "column_per_sample_transposed"
            metadata["transformation"] = transformation
            return frame, metadata
    metadata["layout"] = "row_per_sample"
    return pd.read_csv(path, sep=delimiter, encoding=encoding), metadata


def _read_excel(
    path: Path,
    metadata: dict[str, Any],
    requested_sheet: str | int | None,
    transposer: Transposer | None,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    with pd.ExcelFile(path) as workbook:
        metadata["sheet_names"] = list(workbook.sheet_names)
        selected_sheet = resolve_sheet(workbook.sheet_names, requested_sheet)
        if selected_sheet is None:
            return None, metadata
        metadata["sheet"] = selected_sheet
        if transposer is not None:
            raw = pd.read_excel(
                workbook,
                sheet_name=selected_sheet,
                header=None,
            )
            adapted = transposer(raw)
            if adapted is not None:
                frame, transformation = adapted
                metadata["layout"] = "column_per_sample_transposed"
                metadata["transformation"] = transformation
                return frame, metadata
        metadata["layout"] = "row_per_sample"
        return pd.read_excel(workbook, sheet_name=selected_sheet), metadata


def read_table(
    path: str | Path,
    requested_sheet: str | int | None = None,
    *,
    transposer: Transposer | None = adapt_transposed_table,
    max_file_size_bytes: int = MAX_FILE_SIZE_BYTES,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    """Read CSV/TXT/XLSX and return a table plus share-safe provenance.

    A multi-sheet workbook returns ``None`` until ``requested_sheet`` is
    provided. Pass ``transposer=None`` to disable conservative auto-transpose.
    """
    input_path = validate_input_file(
        path,
        max_file_size_bytes=max_file_size_bytes,
    )
    metadata = build_source_metadata(input_path)
    try:
        if input_path.suffix.lower() in {".csv", ".txt"}:
            return _read_text(input_path, metadata, transposer)
        return _read_excel(
            input_path,
            metadata,
            requested_sheet,
            transposer,
        )
    except InputValidationError:
        raise
    except Exception as exc:
        raise TableReadError(
            f"Could not read table {input_path.name}.",
            details={
                "filename": input_path.name,
                "reason": type(exc).__name__,
            },
        ) from exc
