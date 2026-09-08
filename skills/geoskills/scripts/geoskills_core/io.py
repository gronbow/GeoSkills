"""Privacy-safe table input shared by GeoSkills workflows."""

from __future__ import annotations

import csv
import codecs
import hashlib
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

import pandas as pd
from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException

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

# These defaults accept tables far larger than normal whole-rock geochemistry
# datasets while placing a predictable ceiling on memory use. Limits apply to
# the complete table; GeoSkills never samples or silently truncates input.
MAX_TABLE_ROWS = 100_000
MAX_TABLE_COLUMNS = 2_048
MAX_TABLE_CELLS = 2_000_000
MAX_FIELD_CHARS = 65_536

# XLSX is a ZIP container. Its compressed size alone is not a safe resource
# bound, so archive contents are checked before pandas/openpyxl sees the file.
MAX_XLSX_ENTRIES = 1_024
MAX_XLSX_TOTAL_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_XLSX_SINGLE_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_XLSX_COMPRESSION_RATIO = 100.0
MAX_XLSX_XML_DEPTH = 128
MAX_XLSX_ENTRY_NAME_CHARS = 1_024

_CELL_REFERENCE = re.compile(r"^\$?([A-Za-z]+)\$?([1-9][0-9]*)$")
_ALLOWED_XLSX_COMPRESSION = frozenset({ZIP_STORED, ZIP_DEFLATED})

TransposeResult: TypeAlias = tuple[pd.DataFrame, dict[str, Any]]
Transposer: TypeAlias = Callable[[pd.DataFrame], TransposeResult | None]
AnalyteMatcher: TypeAlias = Callable[[object], AnalyteMatch | None]


@dataclass(frozen=True)
class TableBudget:
    """Hard limits for one parsed table, including its header row."""

    max_rows: int = MAX_TABLE_ROWS
    max_columns: int = MAX_TABLE_COLUMNS
    max_cells: int = MAX_TABLE_CELLS
    max_field_chars: int = MAX_FIELD_CHARS

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")


@dataclass(frozen=True)
class XlsxArchiveBudget:
    """Hard limits for the ZIP/XML resources inside one XLSX workbook."""

    max_entries: int = MAX_XLSX_ENTRIES
    max_total_uncompressed_bytes: int = MAX_XLSX_TOTAL_UNCOMPRESSED_BYTES
    max_single_uncompressed_bytes: int = MAX_XLSX_SINGLE_UNCOMPRESSED_BYTES
    max_compression_ratio: float = MAX_XLSX_COMPRESSION_RATIO
    max_xml_depth: int = MAX_XLSX_XML_DEPTH

    def __post_init__(self) -> None:
        integer_fields = (
            "max_entries",
            "max_total_uncompressed_bytes",
            "max_single_uncompressed_bytes",
            "max_xml_depth",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if (
            isinstance(self.max_compression_ratio, bool)
            or not isinstance(self.max_compression_ratio, (int, float))
            or self.max_compression_ratio <= 0
        ):
            raise ValueError("max_compression_ratio must be positive.")


DEFAULT_TABLE_BUDGET = TableBudget()
DEFAULT_XLSX_ARCHIVE_BUDGET = XlsxArchiveBudget()


def _raise_table_budget(
    limit: str,
    observed: int,
    maximum: int,
) -> None:
    raise InputValidationError(
        (
            f"Input table exceeds the {limit} safety limit "
            f"({observed} > {maximum}); no rows were sampled or truncated."
        ),
        code="E107",
        details={
            "limit": limit,
            "observed": observed,
            "maximum": maximum,
        },
        suggested_action=(
            "Split the table into smaller complete datasets, then create a "
            "separate reviewed recipe for each dataset."
        ),
    )


def _raise_xlsx_archive(reason: str, **safe_details: int | float) -> None:
    raise InputValidationError(
        "Excel workbook failed the XLSX archive safety preflight.",
        code="E108",
        details={"reason": reason, **safe_details},
        suggested_action=(
            "Open the workbook in a trusted spreadsheet application and save "
            "a clean .xlsx copy containing only the required data sheets."
        ),
    )


def _raise_xlsx_xml(reason: str) -> None:
    raise InputValidationError(
        "Excel workbook contains XML that is unsafe or too complex to parse.",
        code="E109",
        details={"reason": reason},
        suggested_action=(
            "Open the workbook in a trusted spreadsheet application and save "
            "a clean .xlsx copy, or export the required sheet as UTF-8 CSV."
        ),
    )


def _column_number(reference: str) -> tuple[int, int] | None:
    match = _CELL_REFERENCE.fullmatch(reference)
    if match is None:
        return None
    letters, row_text = match.groups()
    column = 0
    for character in letters.upper():
        column = column * 26 + ord(character) - ord("A") + 1
    return column, int(row_text)


def _check_coordinate(
    reference: str,
    budget: TableBudget,
) -> None:
    coordinate = _column_number(reference)
    if coordinate is None:
        _raise_xlsx_xml("invalid_cell_reference")
    column, row = coordinate
    if column > budget.max_columns:
        _raise_table_budget("max_columns", column, budget.max_columns)
    if row > budget.max_rows:
        _raise_table_budget("max_rows", row, budget.max_rows)


def _check_dimension(reference: str, budget: TableBudget) -> None:
    endpoints = reference.split(":")
    if len(endpoints) not in {1, 2}:
        _raise_xlsx_xml("invalid_dimension_reference")
    for endpoint in endpoints:
        _check_coordinate(endpoint, budget)


def _local_name(tag: object) -> str:
    text = str(tag)
    return text.rsplit("}", 1)[-1]


def _preflight_xml_part(
    stream: Any,
    *,
    part_kind: str,
    table_budget: TableBudget,
    archive_budget: XlsxArchiveBudget,
) -> None:
    depth = 0
    row_count = 0
    cell_count = 0
    cells_in_row = 0
    in_cell = False
    cell_chars = 0
    in_shared_string = False
    shared_string_chars = 0
    try:
        parser = SafeElementTree.iterparse(
            stream,
            events=("start", "end"),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
        for event, element in parser:
            name = _local_name(element.tag)
            if event == "start":
                depth += 1
                if depth > archive_budget.max_xml_depth:
                    _raise_xlsx_xml("xml_depth_limit")
                if part_kind == "worksheet":
                    if name == "dimension" and element.get("ref"):
                        _check_dimension(str(element.get("ref")), table_budget)
                    elif name == "row":
                        row_count += 1
                        if row_count > table_budget.max_rows:
                            _raise_table_budget(
                                "max_rows", row_count, table_budget.max_rows
                            )
                        row_reference = element.get("r")
                        if row_reference:
                            try:
                                row_number = int(row_reference)
                            except ValueError:
                                _raise_xlsx_xml("invalid_row_reference")
                            if row_number > table_budget.max_rows:
                                _raise_table_budget(
                                    "max_rows", row_number, table_budget.max_rows
                                )
                        cells_in_row = 0
                    elif name == "c":
                        cell_count += 1
                        cells_in_row += 1
                        if cell_count > table_budget.max_cells:
                            _raise_table_budget(
                                "max_cells", cell_count, table_budget.max_cells
                            )
                        if cells_in_row > table_budget.max_columns:
                            _raise_table_budget(
                                "max_columns",
                                cells_in_row,
                                table_budget.max_columns,
                            )
                        reference = element.get("r")
                        if reference:
                            _check_coordinate(str(reference), table_budget)
                        in_cell = True
                        cell_chars = 0
                elif part_kind == "shared_strings" and name == "si":
                    in_shared_string = True
                    shared_string_chars = 0
                continue

            text_length = len(element.text or "")
            if text_length > table_budget.max_field_chars:
                _raise_table_budget(
                    "max_field_chars",
                    text_length,
                    table_budget.max_field_chars,
                )
            if part_kind == "worksheet" and in_cell and name in {"v", "t", "f"}:
                cell_chars += text_length
                if cell_chars > table_budget.max_field_chars:
                    _raise_table_budget(
                        "max_field_chars",
                        cell_chars,
                        table_budget.max_field_chars,
                    )
            if part_kind == "worksheet" and name == "c":
                in_cell = False
                cell_chars = 0
            if part_kind == "shared_strings" and in_shared_string and name == "t":
                shared_string_chars += text_length
                if shared_string_chars > table_budget.max_field_chars:
                    _raise_table_budget(
                        "max_field_chars",
                        shared_string_chars,
                        table_budget.max_field_chars,
                    )
            if part_kind == "shared_strings" and name == "si":
                in_shared_string = False
                shared_string_chars = 0
            element.clear()
            depth -= 1
    except InputValidationError:
        raise
    except (DefusedXmlException, ParseError, ValueError, OverflowError):
        _raise_xlsx_xml("unsafe_xml")


def _xlsx_part_kind(name: str) -> str:
    normalized = name.casefold()
    if normalized.startswith("xl/worksheets/") and normalized.endswith(".xml"):
        return "worksheet"
    if normalized == "xl/sharedstrings.xml":
        return "shared_strings"
    return "xml"


def _entry_name_is_safe(name: str) -> bool:
    if not name or len(name) > MAX_XLSX_ENTRY_NAME_CHARS:
        return False
    if "\x00" in name or "\\" in name or name.startswith("/"):
        return False
    parts = name.split("/")
    if any(part == ".." for part in parts):
        return False
    if parts and parts[0].endswith(":"):
        return False
    return True


def _preflight_xlsx(
    path: Path,
    table_budget: TableBudget,
    archive_budget: XlsxArchiveBudget,
) -> None:
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > archive_budget.max_entries:
                _raise_xlsx_archive(
                    "entry_count_limit",
                    observed=len(entries),
                    maximum=archive_budget.max_entries,
                )
            names: set[str] = set()
            total_uncompressed = 0
            total_compressed = 0
            for entry in entries:
                if not _entry_name_is_safe(entry.filename):
                    _raise_xlsx_archive("unsafe_entry_name")
                if entry.filename in names:
                    _raise_xlsx_archive("duplicate_entry_name")
                names.add(entry.filename)
                if entry.flag_bits & 0x1:
                    _raise_xlsx_archive("encrypted_entry")
                if entry.compress_type not in _ALLOWED_XLSX_COMPRESSION:
                    _raise_xlsx_archive("unsupported_compression")
                mode = (entry.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    _raise_xlsx_archive("symbolic_link_entry")
                if entry.file_size > archive_budget.max_single_uncompressed_bytes:
                    _raise_xlsx_archive(
                        "single_entry_size_limit",
                        observed=entry.file_size,
                        maximum=archive_budget.max_single_uncompressed_bytes,
                    )
                if entry.file_size and not entry.compress_size:
                    _raise_xlsx_archive("invalid_entry_size")
                if entry.compress_size:
                    ratio = entry.file_size / entry.compress_size
                    if ratio > archive_budget.max_compression_ratio:
                        _raise_xlsx_archive(
                            "compression_ratio_limit",
                            observed=round(ratio, 2),
                            maximum=archive_budget.max_compression_ratio,
                        )
                total_uncompressed += entry.file_size
                total_compressed += entry.compress_size
            if total_uncompressed > archive_budget.max_total_uncompressed_bytes:
                _raise_xlsx_archive(
                    "total_uncompressed_size_limit",
                    observed=total_uncompressed,
                    maximum=archive_budget.max_total_uncompressed_bytes,
                )
            if total_compressed:
                ratio = total_uncompressed / total_compressed
                if ratio > archive_budget.max_compression_ratio:
                    _raise_xlsx_archive(
                        "compression_ratio_limit",
                        observed=round(ratio, 2),
                        maximum=archive_budget.max_compression_ratio,
                    )
            corrupt_member = archive.testzip()
            if corrupt_member is not None:
                _raise_xlsx_archive("crc_mismatch")
            for entry in entries:
                lower_name = entry.filename.casefold()
                if not lower_name.endswith((".xml", ".rels")):
                    continue
                with archive.open(entry) as stream:
                    _preflight_xml_part(
                        stream,
                        part_kind=_xlsx_part_kind(entry.filename),
                        table_budget=table_budget,
                        archive_budget=archive_budget,
                    )
    except InputValidationError:
        raise
    except (BadZipFile, OSError, RuntimeError):
        _raise_xlsx_archive("malformed_archive")


def _preflight_text_table(
    path: Path,
    *,
    encoding: str,
    delimiter: str,
    budget: TableBudget,
) -> None:
    previous_limit = csv.field_size_limit()
    csv.field_size_limit(budget.max_field_chars + 1)
    row_count = 0
    cell_count = 0
    try:
        with path.open("r", encoding=encoding, errors="strict", newline="") as stream:
            for row in csv.reader(stream, delimiter=delimiter):
                row_count += 1
                if row_count > budget.max_rows:
                    _raise_table_budget("max_rows", row_count, budget.max_rows)
                column_count = len(row)
                if column_count > budget.max_columns:
                    _raise_table_budget(
                        "max_columns", column_count, budget.max_columns
                    )
                cell_count += column_count
                if cell_count > budget.max_cells:
                    _raise_table_budget("max_cells", cell_count, budget.max_cells)
                for field in row:
                    field_chars = len(field)
                    if field_chars > budget.max_field_chars:
                        _raise_table_budget(
                            "max_field_chars",
                            field_chars,
                            budget.max_field_chars,
                        )
    except csv.Error as exc:
        if "field larger than field limit" in str(exc).casefold():
            _raise_table_budget(
                "max_field_chars",
                budget.max_field_chars + 1,
                budget.max_field_chars,
            )
        raise
    finally:
        csv.field_size_limit(previous_limit)


def _enforce_frame_budget(frame: pd.DataFrame, budget: TableBudget) -> None:
    rows, columns = frame.shape
    if rows > budget.max_rows:
        _raise_table_budget("max_rows", rows, budget.max_rows)
    if columns > budget.max_columns:
        _raise_table_budget("max_columns", columns, budget.max_columns)
    cells = rows * columns
    if cells > budget.max_cells:
        _raise_table_budget("max_cells", cells, budget.max_cells)


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
    with input_path.open("rb") as stream:
        raw = stream.read(65536)
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


def _validate_raw_headers(raw: pd.DataFrame) -> None:
    """Reject ambiguous labels before pandas silently adds .1 suffixes."""
    if raw.empty:
        return
    labels = [str(value).strip() for value in raw.iloc[0] if pd.notna(value) and str(value).strip()]
    duplicates = len(labels) - len(set(labels))
    if duplicates:
        raise InputValidationError(
            "表头存在重复列名，无法可靠选择数据列。",
            code="E110",
            details={"duplicate_header_count": duplicates},
            suggested_action="在本地副本中为重复列命名，确认列的含义后重新生成计划。",
        )


def _read_text(
    path: Path,
    metadata: dict[str, Any],
    transposer: Transposer | None,
    table_budget: TableBudget,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    encoding, delimiter = sniff_text_format(path)
    _preflight_text_table(
        path,
        encoding=encoding,
        delimiter=delimiter,
        budget=table_budget,
    )
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
            _enforce_frame_budget(frame, table_budget)
            metadata["layout"] = "column_per_sample_transposed"
            metadata["transformation"] = transformation
            return frame, metadata
    else:
        raw = pd.read_csv(path, sep=delimiter, encoding=encoding, header=None, nrows=1)
    _validate_raw_headers(raw)
    metadata["layout"] = "row_per_sample"
    frame = pd.read_csv(path, sep=delimiter, encoding=encoding)
    _enforce_frame_budget(frame, table_budget)
    return frame, metadata


def _read_excel(
    path: Path,
    metadata: dict[str, Any],
    requested_sheet: str | int | None,
    transposer: Transposer | None,
    table_budget: TableBudget,
    xlsx_budget: XlsxArchiveBudget,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    _preflight_xlsx(path, table_budget, xlsx_budget)
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
                _enforce_frame_budget(frame, table_budget)
                metadata["layout"] = "column_per_sample_transposed"
                metadata["transformation"] = transformation
                return frame, metadata
        else:
            raw = pd.read_excel(workbook, sheet_name=selected_sheet, header=None, nrows=1)
        _validate_raw_headers(raw)
        metadata["layout"] = "row_per_sample"
        frame = pd.read_excel(workbook, sheet_name=selected_sheet)
        _enforce_frame_budget(frame, table_budget)
        return frame, metadata


def read_table(
    path: str | Path,
    requested_sheet: str | int | None = None,
    *,
    transposer: Transposer | None = adapt_transposed_table,
    max_file_size_bytes: int = MAX_FILE_SIZE_BYTES,
    table_budget: TableBudget = DEFAULT_TABLE_BUDGET,
    xlsx_budget: XlsxArchiveBudget = DEFAULT_XLSX_ARCHIVE_BUDGET,
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
            return _read_text(
                input_path,
                metadata,
                transposer,
                table_budget,
            )
        return _read_excel(
            input_path,
            metadata,
            requested_sheet,
            transposer,
            table_budget,
            xlsx_budget,
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
