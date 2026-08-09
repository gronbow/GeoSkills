"""Explicit, privacy-safe composition-basis transformations."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .quality import coerce_geochemical_numeric


DATA_BASIS_SCHEMA_VERSION = "geoskills.data-basis/v1"
ANHYDROUS_TARGET_TOTAL = 100.0


class DataBasisError(ValueError):
    """A declared composition-basis transformation cannot be applied safely."""


def apply_data_basis(
    frame: pd.DataFrame,
    *,
    specification: Mapping[str, Any] | None,
    analyte_columns: Mapping[str, str],
    analyte_units: Mapping[str, str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return a separate basis-specific table and a count-only audit summary.

    The input frame is never mutated.  For ``normalize-to-100``, every selected
    oxide must be finite and non-negative and the selected total must be
    positive.  Invalid rows retain missing transformed values rather than being
    filled, clipped, or silently repaired.
    """

    if specification is None:
        summary = {
            "schema_version": DATA_BASIS_SCHEMA_VERSION,
            "configured": False,
            "issues": [],
        }
        json.dumps(summary, ensure_ascii=False, allow_nan=False)
        return frame.copy(), summary

    operation = str(specification.get("operation"))
    basis = str(specification.get("basis"))
    selected = [str(value) for value in specification.get("analytes", ())]
    if operation not in {"normalize-to-100", "use-as-declared"}:
        raise DataBasisError("unsupported data-basis operation")
    if basis != "anhydrous-100":
        raise DataBasisError("unsupported composition basis")
    if len(selected) < 2 or len(selected) != len(set(selected)):
        raise DataBasisError("data-basis analytes are invalid")
    if any(value not in analyte_columns for value in selected):
        raise DataBasisError("data-basis analyte is not mapped")
    if any(analyte_units.get(value) != "wt%" for value in selected):
        raise DataBasisError("data-basis analytes must use wt%")

    parsed = {
        analyte: coerce_geochemical_numeric(frame[analyte_columns[analyte]])
        for analyte in selected
    }
    values = pd.concat(
        [parsed[analyte].values.rename(analyte) for analyte in selected],
        axis=1,
    )
    missing_or_bdl = pd.concat(
        [
            (parsed[analyte].missing | parsed[analyte].below_detection).rename(
                analyte
            )
            for analyte in selected
        ],
        axis=1,
    ).any(axis=1)
    non_numeric = pd.concat(
        [parsed[analyte].non_numeric.rename(analyte) for analyte in selected],
        axis=1,
    ).any(axis=1)
    non_finite = pd.concat(
        [parsed[analyte].non_finite.rename(analyte) for analyte in selected],
        axis=1,
    ).any(axis=1)
    incomplete = values.isna().any(axis=1)
    negative = values.lt(0).any(axis=1)
    totals = values.sum(axis=1, min_count=len(selected))
    nonpositive_total = totals.notna() & totals.le(0)
    valid = (~incomplete) & (~negative) & (~nonpositive_total)

    output = frame.copy()
    if operation == "normalize-to-100":
        normalized = values.div(totals.where(valid), axis=0) * ANHYDROUS_TARGET_TOTAL
        normalized = normalized.where(np.isfinite(normalized), np.nan)
        for analyte in selected:
            output[analyte_columns[analyte]] = normalized[analyte]
    else:
        for analyte in selected:
            numeric = parsed[analyte].values.where(valid)
            output[analyte_columns[analyte]] = numeric

    issues: list[dict[str, str]] = []
    valid_count = int(valid.sum())
    invalid_count = int((~valid).sum())
    if valid_count == 0:
        issues.append(
            {
                "code": "B101",
                "severity": "error",
                "message": "无水基准处理没有任何完整、非负且总量为正的记录。",
                "suggested_action": "核对所选氧化物、列映射、单位和缺失值后重新生成计划。",
            }
        )
    elif invalid_count:
        issues.append(
            {
                "code": "B102",
                "severity": "warning",
                "message": "部分记录不能安全转换到无水100%基准；对应转换值保持缺失。",
                "suggested_action": "根据计数摘要在本地源表中核对缺失、非数字、负值和无效总量。",
            }
        )

    summary = {
        "schema_version": DATA_BASIS_SCHEMA_VERSION,
        "configured": True,
        "operation": operation,
        "basis": basis,
        "target_total": ANHYDROUS_TARGET_TOTAL,
        "unit": "wt%",
        "analytes": selected,
        "row_count": int(frame.shape[0]),
        "valid_row_count": valid_count,
        "invalid_row_count": invalid_count,
        "invalid_reason_counts": {
            "missing_or_bdl": int(missing_or_bdl.sum()),
            "non_numeric": int(non_numeric.sum()),
            "non_finite": int(non_finite.sum()),
            "negative": int(negative.sum()),
            "nonpositive_total": int(nonpositive_total.sum()),
        },
        "source_columns_overwritten": False,
        "issues": issues,
    }
    json.dumps(summary, ensure_ascii=False, allow_nan=False)
    return output, summary


__all__ = [
    "ANHYDROUS_TARGET_TOTAL",
    "DATA_BASIS_SCHEMA_VERSION",
    "DataBasisError",
    "apply_data_basis",
]
