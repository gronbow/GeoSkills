#!/usr/bin/env python3
"""Normalize validated trace elements for spider-diagram workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from inspect_data import InspectionError, issue
from inspect_spider_data import (
    inspect_spider_frame,
    prepare_elemental_ppm_frame,
    read_spider_table,
)
from normalize_ree import NormalizationError, load_reference


SKILL_DIR = Path(__file__).resolve().parents[1]
REFERENCE_PATHS = {
    "pm-sm89": (
        SKILL_DIR
        / "assets"
        / "normalization"
        / "primitive-mantle-sm89.json"
    ),
    "pm-sm89-modified": (
        SKILL_DIR
        / "assets"
        / "normalization"
        / "primitive-mantle-modified-sm89.json"
    ),
    "nmorb-sm89": (
        SKILL_DIR / "assets" / "normalization" / "nmorb-sm89.json"
    ),
}
DEFAULT_REFERENCE_KEY = "pm-sm89-modified"


def resolve_reference(reference_key: str) -> Path:
    """Resolve a supported reference name to its versioned local asset."""
    try:
        return REFERENCE_PATHS[reference_key]
    except KeyError as exc:
        raise NormalizationError(
            "未知标准化方案；可选值为：" + ", ".join(REFERENCE_PATHS) + "。"
        ) from exc


def load_spider_reference(
    path: Path,
) -> tuple[dict[str, Any], dict[str, float]]:
    """Load and validate one spider-diagram reference composition."""
    reference, values = load_reference(path)
    if reference.get("diagram_type") != "trace_element_spider":
        raise NormalizationError("该标准化文件不属于微量元素蛛网图。")
    default_order = reference.get("default_plot_order")
    if not isinstance(default_order, list) or len(default_order) < 5:
        raise NormalizationError("蛛网图标准化文件缺少有效 default_plot_order。")
    unknown = [element for element in default_order if element not in values]
    if unknown:
        raise NormalizationError(
            "default_plot_order 包含未定义元素：" + ", ".join(unknown) + "。"
        )
    return reference, values


def spider_reference_summary(
    path: Path,
    reference: dict[str, Any],
) -> dict[str, Any]:
    """Return a provenance block safe to include in a shareable report."""
    return {
        "id": reference["id"],
        "display_name": reference["display_name"],
        "unit": reference["unit"],
        "doi": reference["source"]["doi"],
        "table": reference["source"]["table"],
        "source_note": reference["source"].get("note"),
        "asset": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "crosscheck": reference.get("crosscheck"),
        "verification": reference.get("verification"),
    }


def normalize_spider_frame(
    frame: pd.DataFrame,
    inspection: dict[str, Any],
    reference_values: dict[str, float],
    reference_order: list[str],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Return identifiers plus dimensionless sample/reference ratios."""
    elemental, conversions = prepare_elemental_ppm_frame(frame, inspection)
    sample_column = inspection["sample_id_candidates"][0]
    output_columns = [sample_column]
    if len(inspection["group_candidates"]) == 1:
        output_columns.append(inspection["group_candidates"][0])
    normalized = elemental[output_columns].copy()
    for element in reference_order:
        if element not in elemental:
            continue
        normalized[f"{element}_N"] = (
            pd.to_numeric(elemental[element], errors="coerce")
            / reference_values[element]
        )
    return normalized, conversions


def normalization_error(path: Path, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "operation": "trace_element_spider_normalization",
        "source": {"format": path.suffix.lower()},
        "issues": [issue("E440", "error", message)],
    }


def normalize_spider_path(
    input_path: Path,
    output_path: Path,
    reference_key: str = DEFAULT_REFERENCE_KEY,
    requested_sheet: str | None = None,
    overwrite: bool = False,
    requested_sample_column: str | None = None,
    requested_group_column: str | None = None,
) -> dict[str, Any]:
    """Inspect, normalize, and write a new CSV without changing the input."""
    try:
        if input_path.resolve() == output_path.resolve():
            raise NormalizationError("输出文件不能与输入文件相同。")
        if output_path.suffix.lower() != ".csv":
            raise NormalizationError("标准化结果只支持输出为 .csv。")
        if output_path.exists() and not overwrite:
            raise NormalizationError(
                "输出文件已经存在；如需替换，请显式使用 --overwrite。"
            )

        reference_path = resolve_reference(reference_key)
        reference, reference_values = load_spider_reference(reference_path)
        frame, source = read_spider_table(input_path, requested_sheet)
        if frame is None:
            return {
                "status": "needs_sheet",
                "operation": "trace_element_spider_normalization",
                "source": source,
                "reference": spider_reference_summary(
                    reference_path, reference
                ),
                "issues": [
                    issue(
                        "E111",
                        "review",
                        "Excel 文件包含多个工作表，请使用 --sheet 指定一个工作表。",
                        sheet_names=source["sheet_names"],
                    )
                ],
            }

        inspection = inspect_spider_frame(
            frame,
            source,
            requested_sample_column,
            requested_group_column,
        )
        if inspection["status"] != "ready":
            return {
                "status": "blocked",
                "operation": "trace_element_spider_normalization",
                "reference": spider_reference_summary(
                    reference_path, reference
                ),
                "input_inspection": inspection,
                "issues": [
                    issue(
                        "E441",
                        "review",
                        "输入数据未通过安全检查，因此没有生成标准化结果。",
                    )
                ],
            }

        normalized, conversions = normalize_spider_frame(
            frame,
            inspection,
            reference_values,
            reference["element_order"],
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        normalized.to_csv(
            output_path,
            index=False,
            encoding="utf-8",
            float_format="%.10g",
        )
        normalized_columns = [
            column for column in normalized.columns if column.endswith("_N")
        ]
        return {
            "status": "ready",
            "operation": "trace_element_spider_normalization",
            "formula": "sample_element_ppm / reference_element_ppm",
            "source": source,
            "reference": spider_reference_summary(reference_path, reference),
            "oxide_conversions": conversions,
            "output": {
                "filename": output_path.name,
                "format": ".csv",
                "rows": int(normalized.shape[0]),
                "columns": [str(column) for column in normalized.columns],
                "normalized_columns": normalized_columns,
            },
            "issues": inspection["issues"],
        }
    except (
        InspectionError,
        NormalizationError,
        OSError,
        ValueError,
    ) as exc:
        return normalization_error(input_path, str(exc))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "使用 Sun & McDonough (1989) 原始地幔或 N-MORB 值"
            "标准化微量元素。"
        )
    )
    parser.add_argument("input", type=Path, help="已满足数据规则的输入表格")
    parser.add_argument("--output", type=Path, required=True, help="新建的 CSV 文件")
    parser.add_argument(
        "--reference",
        choices=tuple(REFERENCE_PATHS),
        default=DEFAULT_REFERENCE_KEY,
        help=(
            "标准化方案：pm-sm89-modified（默认）、pm-sm89 "
            "或 nmorb-sm89"
        ),
    )
    parser.add_argument("--sheet", help="Excel 工作表名称，或从 0 开始的编号")
    parser.add_argument("--sample-column", help="明确指定样品编号列")
    parser.add_argument("--group-column", help="明确指定可选分组列")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="明确允许替换已存在的输出文件",
    )
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    report = normalize_spider_path(
        args.input,
        args.output,
        args.reference,
        args.sheet,
        args.overwrite,
        args.sample_column,
        args.group_column,
    )
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    print(f"蛛网图标准化完成：{report['status']}", file=sys.stderr)
    if report["status"] == "ready":
        return 0
    if report["status"] == "error":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
