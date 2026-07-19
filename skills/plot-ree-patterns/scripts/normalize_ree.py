#!/usr/bin/env python3
"""Normalize validated REE concentrations to a versioned reference table."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

from inspect_data import InspectionError, inspect_frame, issue, read_table


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE_PATH = (
    SKILL_DIR / "assets" / "normalization" / "chondrite-sm89.json"
)


class NormalizationError(Exception):
    """An expected problem that makes normalization unsafe."""


def load_reference(path: Path = DEFAULT_REFERENCE_PATH) -> tuple[dict[str, Any], dict[str, float]]:
    """Load and validate one versioned normalization table."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise NormalizationError(f"找不到标准化值文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise NormalizationError(f"标准化值文件不是有效 JSON：{exc}") from exc

    required_metadata = {
        "schema_version",
        "id",
        "display_name",
        "unit",
        "element_order",
        "values",
        "source",
        "verification",
    }
    missing_metadata = sorted(required_metadata - set(raw))
    if missing_metadata:
        raise NormalizationError(
            f"标准化值文件缺少元数据：{', '.join(missing_metadata)}。"
        )
    if raw["unit"] != "ppm":
        raise NormalizationError("首个版本只允许单位为 ppm 的标准化值。")
    if list(raw["values"]) != raw["element_order"]:
        raise NormalizationError("标准化值顺序与 element_order 不一致。")

    numeric_values: dict[str, float] = {}
    for element in raw["element_order"]:
        try:
            decimal_value = Decimal(str(raw["values"][element]))
        except (InvalidOperation, KeyError) as exc:
            raise NormalizationError(f"{element} 的标准化值无效。") from exc
        if not decimal_value.is_finite() or decimal_value <= 0:
            raise NormalizationError(f"{element} 的标准化值必须是有限正数。")
        numeric_values[element] = float(decimal_value)

    if not raw["source"].get("doi") or not raw["source"].get("table"):
        raise NormalizationError("标准化值文件必须记录 DOI 和原始表格位置。")
    return raw, numeric_values


def reference_summary(path: Path, reference: dict[str, Any]) -> dict[str, Any]:
    """Create the provenance block included in every run report."""
    return {
        "id": reference["id"],
        "display_name": reference["display_name"],
        "unit": reference["unit"],
        "doi": reference["source"]["doi"],
        "table": reference["source"]["table"],
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def normalize_frame(
    frame: pd.DataFrame,
    inspection: dict[str, Any],
    reference_values: dict[str, float],
    reference_order: list[str],
) -> pd.DataFrame:
    """Return a new table containing identifiers and dimensionless REE ratios."""
    if inspection["status"] != "ready":
        raise NormalizationError(
            f"输入检查状态为 {inspection['status']}，不能安全执行标准化。"
        )

    sample_candidates = inspection["sample_id_candidates"]
    if len(sample_candidates) != 1:
        raise NormalizationError("必须明确识别一个样品编号列。")

    output_columns = [sample_candidates[0]]
    if len(inspection["group_candidates"]) == 1:
        output_columns.append(inspection["group_candidates"][0])
    normalized = frame[output_columns].copy()

    mapping = {item["element"]: item["column"] for item in inspection["ree"]["recognized"]}
    for element in reference_order:
        if element not in mapping:
            continue
        numeric = pd.to_numeric(frame[mapping[element]], errors="coerce")
        normalized[f"{element}_N"] = numeric / reference_values[element]
    return normalized


def normalization_error(path: Path, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "operation": "ree_normalization",
        "source": {"path": str(path.resolve())},
        "issues": [issue("E400", "error", message)],
    }


def normalize_path(
    input_path: Path,
    output_path: Path,
    requested_sheet: str | None = None,
    overwrite: bool = False,
    reference_path: Path = DEFAULT_REFERENCE_PATH,
) -> dict[str, Any]:
    """Inspect, normalize, and write a new CSV without changing the source."""
    try:
        if input_path.resolve() == output_path.resolve():
            raise NormalizationError("输出文件不能与输入文件相同。")
        if output_path.suffix.lower() != ".csv":
            raise NormalizationError("当前标准化结果只支持输出为 .csv。")
        if output_path.exists() and not overwrite:
            raise NormalizationError("输出文件已经存在；如需替换，请显式使用 --overwrite。")

        reference, reference_values = load_reference(reference_path)
        frame, source = read_table(input_path, requested_sheet)
        if frame is None:
            return {
                "status": "needs_sheet",
                "operation": "ree_normalization",
                "source": source,
                "reference": reference_summary(reference_path, reference),
                "issues": [
                    issue(
                        "E111",
                        "review",
                        "Excel 文件包含多个工作表，请使用 --sheet 指定一个工作表。",
                        sheet_names=source["sheet_names"],
                    )
                ],
            }

        inspection = inspect_frame(frame, source)
        if inspection["status"] != "ready":
            return {
                "status": "blocked",
                "operation": "ree_normalization",
                "reference": reference_summary(reference_path, reference),
                "input_inspection": inspection,
                "issues": [
                    issue(
                        "E401",
                        "review",
                        "输入数据未通过安全检查，因此没有生成标准化结果。",
                    )
                ],
            }

        normalized = normalize_frame(
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
        normalized_columns = [column for column in normalized.columns if column.endswith("_N")]
        return {
            "status": "ready",
            "operation": "ree_normalization",
            "formula": "sample_ppm / reference_ppm",
            "source": source,
            "reference": reference_summary(reference_path, reference),
            "output": {
                "path": str(output_path.resolve()),
                "format": ".csv",
                "rows": int(normalized.shape[0]),
                "columns": [str(column) for column in normalized.columns],
                "normalized_columns": normalized_columns,
            },
            "issues": inspection["issues"],
        }
    except (InspectionError, NormalizationError, OSError) as exc:
        return normalization_error(input_path, str(exc))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用 Sun & McDonough (1989) C1 球粒陨石值标准化 REE 数据。"
    )
    parser.add_argument("input", type=Path, help="已满足数据规则的输入表格")
    parser.add_argument("--output", type=Path, required=True, help="新建的标准化 CSV 文件")
    parser.add_argument("--sheet", help="Excel 工作表名称，或从 0 开始的编号")
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
    report = normalize_path(args.input, args.output, args.sheet, args.overwrite)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    print(f"REE 标准化完成：{report['status']}", file=sys.stderr)
    if report["status"] == "ready":
        return 0
    if report["status"] == "error":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

