#!/usr/bin/env python3
"""Inspect trace-element spider-diagram input without modifying the source."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

from inspect_data import (
    BDL_PATTERN,
    GROUP_NAMES,
    MAX_FILE_SIZE_BYTES,
    SAMPLE_NAMES,
    SUPPORTED_SUFFIXES,
    InspectionError,
    clean_name,
    issue,
    problem_examples,
    resolve_sheet,
    sniff_text_format,
)


SPIDER_ELEMENT_ORDER = [
    "Cs",
    "Tl",
    "Rb",
    "Ba",
    "W",
    "Th",
    "U",
    "Nb",
    "Ta",
    "K",
    "La",
    "Ce",
    "Pb",
    "Pr",
    "Mo",
    "Sr",
    "P",
    "Nd",
    "F",
    "Sm",
    "Zr",
    "Hf",
    "Eu",
    "Sn",
    "Sb",
    "Ti",
    "Gd",
    "Tb",
    "Dy",
    "Li",
    "Y",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
]
DEFAULT_SPIDER_PLOT_ORDER = [
    "Rb",
    "Ba",
    "Th",
    "U",
    "Nb",
    "Ta",
    "K",
    "La",
    "Ce",
    "Pb",
    "Pr",
    "Sr",
    "P",
    "Nd",
    "Zr",
    "Hf",
    "Sm",
    "Eu",
    "Ti",
    "Gd",
    "Tb",
    "Dy",
    "Y",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
]
ELEMENT_BY_KEY = {clean_name(element): element for element in SPIDER_ELEMENT_ORDER}
OXIDE_TO_ELEMENT = {"k2o": "K", "p2o5": "P", "tio2": "Ti"}

# CIAAW/IUPAC standard atomic weights. Oxygen uses the conventional abridged
# value because its natural standard atomic weight is an interval.
ATOMIC_WEIGHTS = {
    "O": 15.999,
    "P": 30.973761998,
    "K": 39.0983,
    "Ti": 47.867,
}
OXIDE_ELEMENT_PPM_PER_WT_PERCENT = {
    "K2O": (
        2 * ATOMIC_WEIGHTS["K"]
        / (2 * ATOMIC_WEIGHTS["K"] + ATOMIC_WEIGHTS["O"])
        * 10000
    ),
    "P2O5": (
        2 * ATOMIC_WEIGHTS["P"]
        / (2 * ATOMIC_WEIGHTS["P"] + 5 * ATOMIC_WEIGHTS["O"])
        * 10000
    ),
    "TiO2": (
        ATOMIC_WEIGHTS["Ti"]
        / (ATOMIC_WEIGHTS["Ti"] + 2 * ATOMIC_WEIGHTS["O"])
        * 10000
    ),
}
UNIT_SUFFIX_PATTERN = re.compile(
    r"[\s_\-\(\[]*(?:ppm|ppb|wt\s*\.?\s*(?:%|pct|percent))"
    r"[\s\)\]]*\s*$",
    re.IGNORECASE,
)


def infer_spider_unit(value: object) -> str:
    """Infer a unit only when it is explicitly present in a label or section."""
    normalized = unicodedata.normalize("NFKC", str(value)).lower()
    if re.search(r"(?:^|[^a-z])ppm(?:$|[^a-z])", normalized):
        return "ppm"
    if re.search(r"(?:^|[^a-z])ppb(?:$|[^a-z])", normalized):
        return "ppb"
    if re.search(r"(?:^|[^a-z])wt\s*\.?\s*(?:%|pct|percent)", normalized):
        return "wt%"
    return "unknown"


def match_spider_analyte(value: object) -> dict[str, str] | None:
    """Map an exact elemental or supported oxide label to a canonical element."""
    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    base = UNIT_SUFFIX_PATTERN.sub("", normalized)
    key = clean_name(base)
    if key in ELEMENT_BY_KEY:
        element = ELEMENT_BY_KEY[key]
        return {
            "element": element,
            "species": element,
            "required_unit": "ppm",
            "conversion": "none",
        }
    if key in OXIDE_TO_ELEMENT:
        species = {
            "k2o": "K2O",
            "p2o5": "P2O5",
            "tio2": "TiO2",
        }[key]
        return {
            "element": OXIDE_TO_ELEMENT[key],
            "species": species,
            "required_unit": "wt%",
            "conversion": "oxide_wt_percent_to_element_ppm",
        }
    return None


def adapt_transposed_spider_table(
    raw: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]] | None:
    """Convert a common elements-by-row supplement into one row per sample."""
    if raw.empty or raw.shape[0] < 7 or raw.shape[1] < 3:
        return None

    best_label_column: int | None = None
    best_rows: list[tuple[int, dict[str, str]]] = []
    for column_index in range(raw.shape[1]):
        matches: list[tuple[int, dict[str, str]]] = []
        seen_species: set[str] = set()
        duplicate = False
        for row_index, value in raw.iloc[:, column_index].items():
            analyte = match_spider_analyte(value)
            if analyte is None:
                continue
            if analyte["species"] in seen_species:
                duplicate = True
                break
            seen_species.add(analyte["species"])
            matches.append((int(row_index), analyte))
        if not duplicate and len(matches) > len(best_rows):
            best_label_column = column_index
            best_rows = matches

    if best_label_column is None or len(best_rows) < 5:
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

    unit_by_row: dict[int, str] = {}
    current_unit = "unknown"
    matched_rows = {row_index for row_index, _ in best_rows}
    for row_index in range(sample_row + 1, raw.shape[0]):
        label = raw.iat[row_index, best_label_column]
        explicit_unit = infer_spider_unit(label)
        if explicit_unit != "unknown" and row_index not in matched_rows:
            current_unit = explicit_unit
        if row_index in matched_rows:
            unit_by_row[row_index] = (
                explicit_unit if explicit_unit != "unknown" else current_unit
            )

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

    recognized: list[dict[str, Any]] = []
    output_names: set[str] = set(converted)
    for row_index, analyte in best_rows:
        unit = unit_by_row.get(row_index, "unknown")
        output_name = (
            f"{analyte['species']}_{unit}"
            if unit != "unknown"
            else analyte["species"]
        )
        if output_name in output_names:
            return None
        output_names.add(output_name)
        converted[output_name] = [
            raw.iat[row_index, column] for column in sample_columns
        ]
        recognized.append(
            {
                **analyte,
                "source_row": row_index + 1,
                "source_label": str(raw.iat[row_index, best_label_column]),
                "inferred_unit": unit,
                "output_column": output_name,
            }
        )

    return pd.DataFrame(converted), {
        "method": "auto_transpose_trace_elements_by_row",
        "sample_header_row": sample_row + 1,
        "sample_identifier_label": str(raw.iat[sample_row, best_label_column]),
        "sample_count": len(sample_columns),
        "element_label_column": best_label_column + 1,
        "group_header_row": None if group_row is None else group_row + 1,
        "group_label": (
            None if group_row is None else str(raw.iat[group_row, best_label_column])
        ),
        "recognized_analytes": recognized,
    }


def read_spider_table(
    path: Path, requested_sheet: str | None
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    """Read one supported table with spider-aware transposed-layout handling."""
    if not path.exists() or not path.is_file():
        raise InspectionError("找不到输入文件。")
    if path.stat().st_size > MAX_FILE_SIZE_BYTES:
        raise InspectionError("文件超过 20 MB；当前版本暂不处理更大的文件。")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise InspectionError("不支持该文件格式；请使用 .csv、.txt 或 .xlsx。")

    source: dict[str, Any] = {
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
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
            adapted = adapt_transposed_spider_table(raw)
            if adapted is not None:
                frame, transformation = adapted
                source["layout"] = "column_per_sample_transposed"
                source["transformation"] = transformation
                return frame, source
            source["layout"] = "row_per_sample"
            return pd.read_csv(path, sep=delimiter, encoding=encoding), source

        workbook = pd.ExcelFile(path)
        source["sheet_names"] = workbook.sheet_names
        selected_sheet = resolve_sheet(workbook.sheet_names, requested_sheet)
        if selected_sheet is None:
            return None, source
        source["sheet"] = selected_sheet
        raw = pd.read_excel(workbook, sheet_name=selected_sheet, header=None)
        adapted = adapt_transposed_spider_table(raw)
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


def inspect_spider_frame(
    frame: pd.DataFrame,
    source: dict[str, Any],
    requested_sample_column: str | None = None,
    requested_group_column: str | None = None,
) -> dict[str, Any]:
    """Inspect identifiers, analyte mappings, units, and invalid cell states."""
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
                    "样品编号列包含空白值；每行都需要样品编号。",
                    column=str(sample_column),
                )
            )
        if int(duplicate_sample_mask.sum()):
            issues.append(
                issue(
                    "E205",
                    "review",
                    "样品编号存在重复值，请确认这些行是否代表同一样品。",
                    column=str(sample_column),
                    values=sorted(
                        sample_text[duplicate_sample_mask].dropna().unique().tolist()
                    )[:10],
                )
            )

    recognized: list[dict[str, Any]] = []
    by_element: dict[str, list[str]] = {}
    for column in frame.columns:
        analyte = match_spider_analyte(column)
        if analyte is None:
            continue
        element = analyte["element"]
        by_element.setdefault(element, []).append(str(column))
        series = frame[column]
        text_values = series.astype("string").str.strip()
        missing_mask = series.isna() | text_values.eq("")
        bdl_mask = text_values.str.match(BDL_PATTERN, na=False) & ~missing_mask
        numeric = pd.to_numeric(
            series.where(~missing_mask & ~bdl_mask),
            errors="coerce",
        )
        nonnumeric_mask = ~missing_mask & ~bdl_mask & numeric.isna()
        nonpositive_mask = numeric.notna() & numeric.le(0)
        unit = infer_spider_unit(column)
        factor = (
            OXIDE_ELEMENT_PPM_PER_WT_PERCENT[analyte["species"]]
            if analyte["conversion"] != "none"
            else 1.0
        )
        recognized.append(
            {
                **analyte,
                "column": str(column),
                "unit": unit,
                "element_ppm_factor": factor,
                "missing": int(missing_mask.sum()),
                "below_detection_limit": int(bdl_mask.sum()),
                "non_numeric": int(nonnumeric_mask.sum()),
                "non_positive": int(nonpositive_mask.sum()),
            }
        )

        if unit != analyte["required_unit"]:
            message = (
                f"{analyte['species']} 列名或所在分区没有明确单位"
                f" {analyte['required_unit']}。"
                if unit == "unknown"
                else (
                    f"{analyte['species']} 必须使用 {analyte['required_unit']}，"
                    f"但当前标记为 {unit}。"
                )
            )
            issues.append(
                issue(
                    "E421",
                    "review",
                    message,
                    element=element,
                    species=analyte["species"],
                    column=str(column),
                )
            )
        if int(bdl_mask.sum()):
            issues.append(
                issue(
                    "W431",
                    "warning",
                    "检测到低于检出限的值；程序保留为曲线空缺，没有替换成零或检出限数值。",
                    element=element,
                    column=str(column),
                    examples=problem_examples(
                        frame, bdl_mask, column, sample_column
                    ),
                )
            )
        if int(nonnumeric_mask.sum()):
            issues.append(
                issue(
                    "E431",
                    "review",
                    "检测到无法转换为数字的单元格。",
                    element=element,
                    column=str(column),
                    examples=problem_examples(
                        frame, nonnumeric_mask, column, sample_column
                    ),
                )
            )
        if int(nonpositive_mask.sum()):
            issues.append(
                issue(
                    "E432",
                    "review",
                    "检测到零或负数，不能用于对数坐标。",
                    element=element,
                    column=str(column),
                    examples=problem_examples(
                        frame, nonpositive_mask, column, sample_column
                    ),
                )
            )
        if int(missing_mask.sum()):
            issues.append(
                issue(
                    "W411",
                    "warning",
                    "检测到缺失值；绘图时保留为曲线空缺。",
                    element=element,
                    column=str(column),
                    count=int(missing_mask.sum()),
                )
            )

    recognized_elements = {item["element"] for item in recognized}
    if not recognized:
        issues.append(issue("E402", "error", "没有识别到可用于蛛网图的元素列。"))
    elif len(recognized_elements) < 5:
        issues.append(
            issue("E403", "error", "微量元素蛛网图至少需要 5 个不同元素。")
        )
    duplicates = {
        element: names for element, names in by_element.items() if len(names) > 1
    }
    if duplicates:
        issues.append(
            issue(
                "E411",
                "review",
                "同一元素对应多个输入列，请明确选择直接元素值或氧化物换算值。",
                columns=duplicates,
            )
        )
    missing_default = [
        element
        for element in DEFAULT_SPIDER_PLOT_ORDER
        if element not in recognized_elements
    ]
    if missing_default and recognized:
        issues.append(
            issue(
                "W401",
                "warning",
                "部分常用蛛网图元素未出现；程序只绘制已验证元素。",
                elements=missing_default,
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
        "trace_elements": {
            "reference_order": SPIDER_ELEMENT_ORDER,
            "default_plot_order": DEFAULT_SPIDER_PLOT_ORDER,
            "recognized": recognized,
            "missing_default_elements": missing_default,
        },
        "oxide_conversion": {
            "atomic_weights": ATOMIC_WEIGHTS,
            "source": "CIAAW/IUPAC standard atomic weights",
            "formula": "oxide_wt_percent * element_mass_fraction * 10000",
            "factors": OXIDE_ELEMENT_PPM_PER_WT_PERCENT,
        },
        "issues": issues,
    }


def prepare_elemental_ppm_frame(
    frame: pd.DataFrame,
    inspection: dict[str, Any],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Create canonical elemental ppm columns from a ready inspection."""
    if inspection["status"] != "ready":
        raise InspectionError(
            f"输入检查状态为 {inspection['status']}，不能安全换算元素浓度。"
        )
    sample_candidates = inspection["sample_id_candidates"]
    if len(sample_candidates) != 1:
        raise InspectionError("必须明确识别一个样品编号列。")
    output_columns = [sample_candidates[0]]
    if len(inspection["group_candidates"]) == 1:
        output_columns.append(inspection["group_candidates"][0])
    elemental = frame[output_columns].copy()
    conversions: list[dict[str, Any]] = []
    for item in inspection["trace_elements"]["recognized"]:
        numeric = pd.to_numeric(frame[item["column"]], errors="coerce")
        elemental[item["element"]] = numeric * item["element_ppm_factor"]
        if item["conversion"] != "none":
            conversions.append(
                {
                    "element": item["element"],
                    "source_column": item["column"],
                    "source_species": item["species"],
                    "source_unit": item["unit"],
                    "target_unit": "ppm",
                    "factor": item["element_ppm_factor"],
                    "formula": (
                        "oxide_wt_percent * element_mass_fraction * 10000"
                    ),
                }
            )
    return elemental, conversions


def spider_error_report(path: Path, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "operation": "trace_element_spider_inspection",
        "source": {"format": path.suffix.lower()},
        "issues": [issue("E400", "error", message)],
    }


def inspect_spider_path(
    path: Path,
    requested_sheet: str | None = None,
    requested_sample_column: str | None = None,
    requested_group_column: str | None = None,
) -> dict[str, Any]:
    """Inspect one spider-diagram input path and return a JSON-ready report."""
    try:
        frame, source = read_spider_table(path, requested_sheet)
        if frame is None:
            return {
                "status": "needs_sheet",
                "operation": "trace_element_spider_inspection",
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
        report = inspect_spider_frame(
            frame,
            source,
            requested_sample_column,
            requested_group_column,
        )
        report["operation"] = "trace_element_spider_inspection"
        return report
    except (InspectionError, OSError) as exc:
        return spider_error_report(path, str(exc))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="只读检查微量元素蛛网图输入，并输出 JSON 报告。"
    )
    parser.add_argument("input", type=Path, help=".csv、.txt 或 .xlsx 输入文件")
    parser.add_argument("--sheet", help="Excel 工作表名称，或从 0 开始的编号")
    parser.add_argument("--sample-column", help="明确指定样品编号列")
    parser.add_argument("--group-column", help="明确指定可选的分组列")
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    report = inspect_spider_path(
        args.input,
        args.sheet,
        args.sample_column,
        args.group_column,
    )
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    print(f"蛛网图数据检查完成：{report['status']}", file=sys.stderr)
    if report["status"] == "ready":
        return 0
    if report["status"] == "error":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
