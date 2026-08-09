"""Privacy-safe, deterministic quality summaries for geochemical tables."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


QUALITY_SCHEMA_VERSION = "geoskills.quality/v1"

_MISSING_TEXT = frozenset({"", "-", "—", "na", "n/a", "nan", "null", "none"})
_BDL_PATTERN = re.compile(
    r"^\s*(?:"
    r"<\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    r"|bdl|n\.?d\.?|below\s+detection(?:\s+limit)?"
    r")\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NumericCoercion:
    """Numeric values plus non-serialised source-state masks."""

    values: pd.Series
    missing: pd.Series
    below_detection: pd.Series
    non_numeric: pd.Series
    non_finite: pd.Series


def coerce_geochemical_numeric(series: pd.Series) -> NumericCoercion:
    """Coerce values without substituting censored or invalid source cells."""

    text = series.astype("string").str.strip()
    folded = text.str.casefold()
    missing = series.isna() | folded.fillna("").isin(_MISSING_TEXT)
    below_detection = (~missing) & text.fillna("").str.match(_BDL_PATTERN)
    numeric = pd.to_numeric(
        series.where(~missing & ~below_detection), errors="coerce"
    ).astype("float64")
    finite = pd.Series(
        np.isfinite(numeric.to_numpy(dtype=float, na_value=np.nan)),
        index=series.index,
    )
    non_numeric = (~missing) & (~below_detection) & numeric.isna()
    non_finite = numeric.notna() & (~finite)
    return NumericCoercion(
        values=numeric.where(finite),
        missing=missing.astype(bool),
        below_detection=below_detection.astype(bool),
        non_numeric=non_numeric.astype(bool),
        non_finite=non_finite.astype(bool),
    )


def _issue(
    code: str,
    severity: str,
    message: str,
    *,
    suggested_action: str,
) -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "suggested_action": suggested_action,
    }


def _status(issues: Sequence[Mapping[str, Any]]) -> str:
    if any(str(item.get("severity")) == "error" for item in issues):
        return "error"
    if any(str(item.get("severity")) == "review" for item in issues):
        return "review"
    return "ready"


def assess_data_quality(
    frame: pd.DataFrame,
    *,
    sample_column: str,
    analyte_columns: Mapping[str, str],
    analyte_units: Mapping[str, str],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a JSON-ready count summary without source values or identifiers."""

    if sample_column not in frame.columns:
        raise ValueError("sample column is missing")
    missing_columns = sorted(
        column for column in analyte_columns.values() if column not in frame.columns
    )
    if missing_columns:
        raise ValueError("one or more analyte columns are missing")

    issues: list[dict[str, str]] = []
    sample_text = frame[sample_column].astype("string").str.strip()
    blank_sample = frame[sample_column].isna() | sample_text.fillna("").eq("")
    nonblank = sample_text.where(~blank_sample).str.casefold()
    duplicate_rows = nonblank.notna() & nonblank.duplicated(keep=False)
    duplicate_identifier_count = int(nonblank[duplicate_rows].nunique())

    if int(blank_sample.sum()):
        issues.append(
            _issue(
                "Q001",
                "error",
                "样品编号列包含空白项。",
                suggested_action="补全唯一的样品编号后重新生成计划。",
            )
        )
    duplicate_severity = str(policy.get("duplicate_sample_ids", "error"))
    if duplicate_identifier_count and duplicate_severity != "ignore":
        issues.append(
            _issue(
                "Q002",
                duplicate_severity,
                "样品编号列包含重复编号。",
                suggested_action="确认重复记录是否为平行样、重复分析或录入错误。",
            )
        )

    analyte_records: list[dict[str, Any]] = []
    parsed: dict[str, NumericCoercion] = {}
    total_missing = 0
    total_bdl = 0
    total_non_numeric = 0
    total_non_finite = 0
    total_nonpositive = 0
    for analyte in sorted(analyte_columns):
        column = analyte_columns[analyte]
        result = coerce_geochemical_numeric(frame[column])
        parsed[analyte] = result
        valid = result.values.notna()
        zero = valid & result.values.eq(0)
        negative = valid & result.values.lt(0)
        record = {
            "analyte": analyte,
            "unit": str(analyte_units[analyte]),
            "valid_count": int(valid.sum()),
            "missing_count": int(result.missing.sum()),
            "below_detection_count": int(result.below_detection.sum()),
            "non_numeric_count": int(result.non_numeric.sum()),
            "non_finite_count": int(result.non_finite.sum()),
            "zero_count": int(zero.sum()),
            "negative_count": int(negative.sum()),
        }
        analyte_records.append(record)
        total_missing += record["missing_count"]
        total_bdl += record["below_detection_count"]
        total_non_numeric += record["non_numeric_count"]
        total_non_finite += record["non_finite_count"]
        total_nonpositive += record["zero_count"] + record["negative_count"]

    invalid_severity = str(policy.get("non_numeric_values", "error"))
    if total_non_numeric or total_non_finite:
        issues.append(
            _issue(
                "Q003",
                invalid_severity,
                "一个或多个分析物列包含非数字或非有限内容。",
                suggested_action="核对原表中的文本、无穷值和列映射，不要用零静默替代。",
            )
        )
    if total_missing:
        issues.append(
            _issue(
                "Q004",
                "warning",
                "一个或多个分析物列包含缺失项。",
                suggested_action="确认缺失数据的原因，并检查目标图件是否仍有足够完整记录。",
            )
        )
    if total_bdl:
        issues.append(
            _issue(
                "Q005",
                "warning",
                "检测到低于检出限标记；GeoSkills 将其保留为缺失状态。",
                suggested_action="如需替代值，先制定并记录独立的数据处理方案。",
            )
        )
    if total_nonpositive:
        issues.append(
            _issue(
                "Q006",
                "warning",
                "一个或多个分析物列包含零或负数。",
                suggested_action="对数图和比值计算前核对这些记录，GeoSkills 不会自动改值。",
            )
        )

    major_total_record: dict[str, Any] | None = None
    major_total = policy.get("major_oxide_total")
    if isinstance(major_total, Mapping):
        selected = [str(item) for item in major_total["analytes"]]
        matrices = [parsed[item].values for item in selected]
        complete = pd.concat(matrices, axis=1).notna().all(axis=1)
        sums = pd.concat(matrices, axis=1).sum(axis=1, min_count=len(selected))
        lower = float(major_total["lower"])
        upper = float(major_total["upper"])
        below = complete & sums.lt(lower)
        above = complete & sums.gt(upper)
        in_range = complete & sums.ge(lower) & sums.le(upper)
        major_total_record = {
            "analytes": selected,
            "unit": "wt%",
            "composition_basis": str(major_total["composition_basis"]),
            "range_lower": lower,
            "range_upper": upper,
            "evaluated_row_count": int(complete.sum()),
            "in_range_count": int(in_range.sum()),
            "below_range_count": int(below.sum()),
            "above_range_count": int(above.sum()),
            "incomplete_row_count": int((~complete).sum()),
        }
        if int(below.sum()) or int(above.sum()):
            issues.append(
                _issue(
                    "Q007",
                    str(major_total["severity"]),
                    "部分完整主量元素记录的显式求和结果超出配方设定范围。",
                    suggested_action="核对分析总量、挥发分处理和 composition_basis，再确认是否继续。",
                )
            )
        if int((~complete).sum()):
            issues.append(
                _issue(
                    "Q008",
                    "warning",
                    "部分记录无法完成配方指定的主量元素求和。",
                    suggested_action="检查所选氧化物的缺失、检出限和非数字状态。",
                )
            )

    summary = {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "status": _status(issues),
        "row_count": int(frame.shape[0]),
        "mapped_analyte_count": len(analyte_records),
        "blank_sample_id_count": int(blank_sample.sum()),
        "duplicate_identifier_count": duplicate_identifier_count,
        "duplicate_row_count": int(duplicate_rows.sum()),
        "cell_counts": {
            "missing": int(total_missing),
            "below_detection": int(total_bdl),
            "non_numeric": int(total_non_numeric),
            "non_finite": int(total_non_finite),
            "nonpositive": int(total_nonpositive),
        },
        "analytes": analyte_records,
        "major_oxide_total": major_total_record,
        "issues": issues,
    }
    json.dumps(summary, ensure_ascii=False, allow_nan=False)
    return summary


__all__ = [
    "NumericCoercion",
    "QUALITY_SCHEMA_VERSION",
    "assess_data_quality",
    "coerce_geochemical_numeric",
]
