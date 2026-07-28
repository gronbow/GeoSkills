#!/usr/bin/env python3
"""Inspect a geochemical table without changing the source file."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd


REE_ORDER = [
    "La",
    "Ce",
    "Pr",
    "Nd",
    "Sm",
    "Eu",
    "Gd",
    "Tb",
    "Dy",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
]
REE_BY_LOWER = {element.lower(): element for element in REE_ORDER}
SUPPORTED_SUFFIXES = {".csv", ".txt", ".xlsx"}
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

SAMPLE_NAMES = {
    "id",
    "sample",
    "samplecode",
    "sampleid",
    "samplename",
    "sampleno",
    "samplenumber",
    "specimen",
    "specimenid",
}
GROUP_NAMES = {
    "area",
    "group",
    "lithology",
    "lithologicalgroup",
    "locality",
    "location",
    "region",
    "rocktype",
    "samplegroup",
    "suite",
}

UNIT_PATTERN = r"ppm|ppb|wt\s*\.?\s*%|wt\s*pct|wt\s*percent"
REE_HEADER_PATTERN = re.compile(
    rf"^\s*({'|'.join(element.lower() for element in REE_ORDER)})"
    rf"(?:[\s_\-\(\[]*({UNIT_PATTERN})[\s\)\]]*)?\s*$",
    re.IGNORECASE,
)
BDL_PATTERN = re.compile(
    r"^\s*(?:"
    r"<\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    r"|bdl|n\.?d\.?|below\s+detection(?:\s+limit)?"
    r")\s*$",
    re.IGNORECASE,
)


class InspectionError(Exception):
    """An expected input problem that should be returned as JSON."""


def clean_name(value: object) -> str:
    """Convert a column name to a compact comparison form."""
    normalized = unicodedata.normalize("NFKC", str(value)).lower()
    return re.sub(r"[^a-z0-9]+", "", normalized)


def infer_unit(column: object) -> str:
    """Infer only units that are explicitly written in a column name."""
    normalized = unicodedata.normalize("NFKC", str(column)).lower()
    if "ppm" in normalized:
        return "ppm"
    if "ppb" in normalized:
        return "ppb"
    if re.search(r"wt\s*\.?\s*(?:%|pct|percent)", normalized):
        return "wt%"
    return "unknown"


def match_ree_column(column: object) -> str | None:
    """Return the canonical REE name when the header is unambiguous."""
    normalized = unicodedata.normalize("NFKC", str(column))
    match = REE_HEADER_PATTERN.fullmatch(normalized)
    if not match:
        return None
    return REE_BY_LOWER[match.group(1).lower()]


def sniff_text_format(path: Path) -> tuple[str, str]:
    """Detect UTF-8/GB18030 text and comma/tab delimiters."""
    raw = path.read_bytes()[:65536]
    decoded: str | None = None
    encoding: str | None = None
    for candidate in ("utf-8-sig", "gb18030"):
        try:
            decoded = raw.decode(candidate)
            encoding = candidate
            break
        except UnicodeDecodeError:
            continue
    if decoded is None or encoding is None:
        raise InspectionError("文本编码无法识别；目前支持 UTF-8 和 GB18030。")

    try:
        delimiter = csv.Sniffer().sniff(decoded, delimiters=",\t").delimiter
    except csv.Error:
        first_line = decoded.splitlines()[0] if decoded.splitlines() else ""
        delimiter = "\t" if first_line.count("\t") > first_line.count(",") else ","
    return encoding, delimiter


def resolve_sheet(sheet_names: list[str], requested: str | None) -> str | None:
    """Resolve an Excel sheet name without silently choosing among many sheets."""
    if requested is None:
        return sheet_names[0] if len(sheet_names) == 1 else None
    if requested in sheet_names:
        return requested
    if requested.isdigit():
        index = int(requested)
        if 0 <= index < len(sheet_names):
            return sheet_names[index]
    raise InspectionError(
        f"工作表 {requested!r} 不存在；可选工作表为：{', '.join(sheet_names)}。"
    )


def adapt_transposed_table(
    raw: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]] | None:
    """Convert a common paper-supplement layout into one row per sample."""
    if raw.empty or raw.shape[0] < 4 or raw.shape[1] < 3:
        return None

    best_label_column: int | None = None
    best_element_rows: dict[str, int] = {}
    for column_index in range(raw.shape[1]):
        element_rows: dict[str, int] = {}
        duplicate = False
        for row_index, value in raw.iloc[:, column_index].items():
            element = match_ree_column(value)
            if element is None:
                continue
            if element in element_rows:
                duplicate = True
                break
            element_rows[element] = int(row_index)
        if not duplicate and len(element_rows) > len(best_element_rows):
            best_label_column = column_index
            best_element_rows = element_rows

    if best_label_column is None or len(best_element_rows) < 3:
        return None

    sample_rows = [
        int(row_index)
        for row_index, value in raw.iloc[:, best_label_column].items()
        if clean_name(value) in SAMPLE_NAMES
        and int(raw.iloc[int(row_index)].notna().sum()) >= 3
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
    if len(sample_columns) < 2:
        return None

    group_row: int | None = None
    for row_index in range(sample_row):
        if clean_name(raw.iat[row_index, best_label_column]) in GROUP_NAMES:
            group_row = row_index

    first_element_row = min(best_element_rows.values())
    section_unit = "unknown"
    unit_source_row: int | None = None
    for row_index in range(sample_row + 1, first_element_row + 1):
        candidate_unit = infer_unit(raw.iat[row_index, best_label_column])
        if candidate_unit != "unknown":
            section_unit = candidate_unit
            unit_source_row = row_index

    samples = [str(raw.iat[sample_row, column]).strip() for column in sample_columns]
    converted: dict[str, list[Any]] = {"Sample": samples}
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

    for element in REE_ORDER:
        if element not in best_element_rows:
            continue
        original_label = raw.iat[best_element_rows[element], best_label_column]
        explicit_unit = infer_unit(original_label)
        unit = explicit_unit if explicit_unit != "unknown" else section_unit
        output_name = f"{element}_{unit}" if unit != "unknown" else element
        converted[output_name] = [
            raw.iat[best_element_rows[element], column] for column in sample_columns
        ]

    metadata = {
        "method": "auto_transpose_elements_by_row",
        "sample_header_row": sample_row + 1,
        "sample_identifier_label": str(raw.iat[sample_row, best_label_column]),
        "sample_count": len(sample_columns),
        "element_label_column": best_label_column + 1,
        "recognized_elements": [
            element for element in REE_ORDER if element in best_element_rows
        ],
        "group_header_row": None if group_row is None else group_row + 1,
        "group_label": (
            None if group_row is None else str(raw.iat[group_row, best_label_column])
        ),
        "inferred_unit": section_unit,
        "unit_source_row": None if unit_source_row is None else unit_source_row + 1,
    }
    return pd.DataFrame(converted), metadata


def read_table(
    path: Path, requested_sheet: str | None
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    """Read one supported table and return its source metadata."""
    if not path.exists() or not path.is_file():
        raise InspectionError(f"找不到输入文件：{path}")
    if path.stat().st_size > MAX_FILE_SIZE_BYTES:
        raise InspectionError("文件超过 20 MB；首个版本暂不处理更大的文件。")

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise InspectionError("不支持该文件格式；请使用 .csv、.txt 或 .xlsx。")

    source: dict[str, Any] = {
        "path": str(path.resolve()),
        "format": suffix,
        "sheet": None,
        "sheet_names": [],
        "encoding": None,
        "delimiter": None,
        "layout": None,
        "transformation": None,
    }

    try:
        if suffix in {".csv", ".txt"}:
            encoding, delimiter = sniff_text_format(path)
            source["encoding"] = encoding
            source["delimiter"] = "TAB" if delimiter == "\t" else delimiter
            raw = pd.read_csv(path, sep=delimiter, encoding=encoding, header=None)
            adapted = adapt_transposed_table(raw)
            if adapted is not None:
                frame, transformation = adapted
                source["layout"] = "column_per_sample_transposed"
                source["transformation"] = transformation
                return frame, source
            frame = pd.read_csv(path, sep=delimiter, encoding=encoding)
            source["layout"] = "row_per_sample"
            return frame, source

        workbook = pd.ExcelFile(path)
        source["sheet_names"] = workbook.sheet_names
        selected_sheet = resolve_sheet(workbook.sheet_names, requested_sheet)
        if selected_sheet is None:
            return None, source
        source["sheet"] = selected_sheet
        raw = pd.read_excel(workbook, sheet_name=selected_sheet, header=None)
        adapted = adapt_transposed_table(raw)
        if adapted is not None:
            frame, transformation = adapted
            source["layout"] = "column_per_sample_transposed"
            source["transformation"] = transformation
            return frame, source
        source["layout"] = "row_per_sample"
        return pd.read_excel(workbook, sheet_name=selected_sheet), source
    except InspectionError:
        raise
    except Exception as exc:
        raise InspectionError(f"无法读取表格：{exc}") from exc


def issue(code: str, severity: str, message: str, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if details:
        result["details"] = details
    return result


def problem_examples(
    frame: pd.DataFrame,
    mask: pd.Series,
    column: object,
    sample_column: object | None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return short, human-readable examples of problematic cells."""
    examples: list[dict[str, Any]] = []
    for index in frame.index[mask][:limit]:
        sample_value = frame.at[index, sample_column] if sample_column is not None else None
        value = frame.at[index, column]
        examples.append(
            {
                "spreadsheet_row": int(index) + 2 if isinstance(index, int) else str(index),
                "sample": None if pd.isna(sample_value) else str(sample_value),
                "value": None if pd.isna(value) else str(value),
            }
        )
    return examples


def inspect_frame(
    frame: pd.DataFrame,
    source: dict[str, Any],
    requested_sample_column: str | None = None,
    requested_group_column: str | None = None,
) -> dict[str, Any]:
    """Inspect identifiers, REE mappings, units, and invalid cell states."""
    columns = [str(column) for column in frame.columns]
    automatic_sample_candidates = [
        column for column in frame.columns if clean_name(column) in SAMPLE_NAMES
    ]
    automatic_group_candidates = [
        column for column in frame.columns if clean_name(column) in GROUP_NAMES
    ]
    requested_sample_matches = [
        column for column in frame.columns if str(column) == requested_sample_column
    ]
    requested_group_matches = [
        column for column in frame.columns if str(column) == requested_group_column
    ]
    sample_candidates = (
        requested_sample_matches
        if requested_sample_column is not None
        else automatic_sample_candidates
    )
    group_candidates = (
        requested_group_matches
        if requested_group_column is not None
        else automatic_group_candidates
    )
    sample_column = sample_candidates[0] if len(sample_candidates) == 1 else None
    issues: list[dict[str, Any]] = []

    if frame.empty:
        issues.append(issue("E101", "error", "表格没有数据行。"))
    if requested_sample_column is not None and len(requested_sample_matches) != 1:
        issues.append(
            issue(
                "E206",
                "error",
                "指定的样品编号列不存在或不唯一。",
                requested=requested_sample_column,
            )
        )
    elif not sample_candidates:
        issues.append(issue("E201", "review", "未自动识别样品编号列，请明确指定。"))
    elif len(sample_candidates) > 1:
        issues.append(
            issue(
                "E201",
                "review",
                "识别到多个可能的样品编号列，请确认使用哪一列。",
                columns=[str(column) for column in sample_candidates],
            )
        )

    if requested_group_column is not None and len(requested_group_matches) != 1:
        issues.append(
            issue(
                "E207",
                "error",
                "指定的分组列不存在或不唯一。",
                requested=requested_group_column,
            )
        )

    if sample_column is not None:
        sample_series = frame[sample_column]
        sample_text = sample_series.astype("string").str.strip()
        missing_sample_mask = sample_series.isna() | sample_text.eq("")
        duplicate_sample_mask = ~missing_sample_mask & sample_text.duplicated(keep=False)
        if int(missing_sample_mask.sum()):
            issues.append(
                issue(
                    "E204",
                    "review",
                    "样品编号列包含空白值；每个数据行都需要样品编号。",
                    column=str(sample_column),
                    rows=[
                        int(index) + 2 if isinstance(index, int) else str(index)
                        for index in frame.index[missing_sample_mask][:10]
                    ],
                )
            )
        if int(duplicate_sample_mask.sum()):
            issues.append(
                issue(
                    "E205",
                    "review",
                    "样品编号存在重复值，请确认这些行是否代表同一样品。",
                    column=str(sample_column),
                    values=sorted(sample_text[duplicate_sample_mask].dropna().unique().tolist())[:10],
                )
            )

    recognized: list[dict[str, Any]] = []
    by_element: dict[str, list[str]] = {}
    for column in frame.columns:
        element = match_ree_column(column)
        if element is None:
            continue

        by_element.setdefault(element, []).append(str(column))
        series = frame[column]
        text_values = series.astype("string").str.strip()
        missing_mask = series.isna() | text_values.eq("")
        bdl_mask = text_values.str.match(BDL_PATTERN, na=False) & ~missing_mask
        numeric = pd.to_numeric(series.where(~missing_mask & ~bdl_mask), errors="coerce")
        nonnumeric_mask = ~missing_mask & ~bdl_mask & numeric.isna()
        nonpositive_mask = numeric.notna() & numeric.le(0)
        unit = infer_unit(column)

        column_report = {
            "element": element,
            "column": str(column),
            "unit": unit,
            "missing": int(missing_mask.sum()),
            "below_detection_limit": int(bdl_mask.sum()),
            "non_numeric": int(nonnumeric_mask.sum()),
            "non_positive": int(nonpositive_mask.sum()),
        }
        recognized.append(column_report)

        if unit != "ppm":
            message = (
                "列名没有明确写出单位 ppm。"
                if unit == "unknown"
                else f"首个版本只接受 ppm，但该列标记为 {unit}。"
            )
            issues.append(issue("E221", "review", message, element=element, column=str(column)))
        if int(bdl_mask.sum()):
            issues.append(
                issue(
                    "W231",
                    "review",
                    "检测到低于检出限的值；程序没有把它们改成零。",
                    element=element,
                    column=str(column),
                    examples=problem_examples(frame, bdl_mask, column, sample_column),
                )
            )
        if int(nonnumeric_mask.sum()):
            issues.append(
                issue(
                    "E231",
                    "review",
                    "检测到无法转换为数字的单元格。",
                    element=element,
                    column=str(column),
                    examples=problem_examples(frame, nonnumeric_mask, column, sample_column),
                )
            )
        if int(nonpositive_mask.sum()):
            issues.append(
                issue(
                    "E301",
                    "review",
                    "检测到零或负数，不能直接用于对数坐标。",
                    element=element,
                    column=str(column),
                    examples=problem_examples(frame, nonpositive_mask, column, sample_column),
                )
            )
        if int(missing_mask.sum()):
            issues.append(
                issue(
                    "W211",
                    "warning",
                    "检测到缺失值；后续绘图应保留为曲线空缺。",
                    element=element,
                    column=str(column),
                    count=int(missing_mask.sum()),
                )
            )

    recognized_elements = {item["element"] for item in recognized}
    if not recognized:
        issues.append(issue("E202", "error", "没有识别到 REE 数据列。"))
    elif len(recognized_elements) < 3:
        issues.append(issue("E203", "error", "至少需要识别到 3 个不同的 REE 元素列。"))

    duplicates = {element: names for element, names in by_element.items() if len(names) > 1}
    if duplicates:
        issues.append(
            issue("E211", "review", "同一 REE 对应多个列，请确认列映射。", columns=duplicates)
        )

    missing_elements = [element for element in REE_ORDER if element not in recognized_elements]
    if missing_elements and recognized:
        issues.append(
            issue(
                "W201",
                "warning",
                "部分 REE 元素列未出现；后续曲线会在相应位置留空。",
                elements=missing_elements,
            )
        )

    severities = {item["severity"] for item in issues}
    if "error" in severities:
        status = "error"
    elif "review" in severities:
        status = "needs_review"
    else:
        status = "ready"

    return {
        "status": status,
        "source": source,
        "shape": {"rows": int(frame.shape[0]), "columns": int(frame.shape[1])},
        "columns": columns,
        "sample_id_candidates": [str(column) for column in sample_candidates],
        "group_candidates": [str(column) for column in group_candidates],
        "ree": {
            "expected_order": REE_ORDER,
            "recognized": recognized,
            "missing_elements": missing_elements,
        },
        "issues": issues,
    }


def error_report(path: Path, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "source": {"path": str(path.resolve())},
        "issues": [issue("E100", "error", message)],
    }


def inspect_path(
    path: Path,
    requested_sheet: str | None = None,
    requested_sample_column: str | None = None,
    requested_group_column: str | None = None,
) -> dict[str, Any]:
    """Public function used by the CLI and automated tests."""
    try:
        frame, source = read_table(path, requested_sheet)
        if frame is None:
            return {
                "status": "needs_sheet",
                "source": source,
                "issues": [
                    issue(
                        "E111",
                        "review",
                        "Excel 文件包含多个工作表，请使用 --sheet 指定一个工作表。",
                        sheet_names=source["sheet_names"],
                    )
                ],
            }
        return inspect_frame(
            frame,
            source,
            requested_sample_column,
            requested_group_column,
        )
    except InspectionError as exc:
        return error_report(path, str(exc))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读检查地球化学 REE 数据表，并输出 JSON 报告。")
    parser.add_argument("input", type=Path, help=".csv、.txt 或 .xlsx 输入文件")
    parser.add_argument("--sheet", help="Excel 工作表名称，或从 0 开始的编号")
    parser.add_argument("--sample-column", help="明确指定样品编号列")
    parser.add_argument("--group-column", help="明确指定可选的分组列")
    return parser.parse_args()


def main() -> int:
    # Keep machine-readable JSON stable across Windows, macOS, and Linux.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    report = inspect_path(
        args.input,
        args.sheet,
        args.sample_column,
        args.group_column,
    )
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    print(f"数据检查完成：{report['status']}", file=sys.stderr)
    if report["status"] == "ready":
        return 0
    if report["status"] == "error":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
