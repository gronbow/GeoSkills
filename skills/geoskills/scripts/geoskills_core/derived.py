"""Safe derived-variable calculations without expression evaluation."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .quality import coerce_geochemical_numeric


DERIVED_SCHEMA_VERSION = "geoskills.derived/v1"


class DerivedVariableError(ValueError):
    """A validated derived-variable contract cannot be executed safely."""


def derived_column_name(variable_id: str) -> str:
    return f"Derived__{variable_id}"


def apply_derived_variables(
    frame: pd.DataFrame,
    *,
    specifications: Sequence[Mapping[str, Any]],
    analyte_columns: Mapping[str, str],
    analyte_units: Mapping[str, str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Apply only fixed ratio operations and return count-only provenance."""

    output = frame.copy()
    records: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    for raw in specifications:
        spec = dict(raw)
        variable_id = str(spec["id"])
        if str(spec.get("operation")) != "ratio":
            raise DerivedVariableError("unsupported derived operation")
        numerator = str(spec["numerator"])
        denominator = str(spec["denominator"])
        if numerator not in analyte_columns or denominator not in analyte_columns:
            raise DerivedVariableError("derived input is not mapped")
        numerator_unit = str(analyte_units[numerator])
        denominator_unit = str(analyte_units[denominator])
        expected_unit = str(spec.get("input_unit", numerator_unit))
        if (
            numerator_unit != denominator_unit
            or numerator_unit != expected_unit
        ):
            raise DerivedVariableError("public ratios require identical units")

        numerator_result = coerce_geochemical_numeric(
            output[analyte_columns[numerator]]
        )
        denominator_result = coerce_geochemical_numeric(
            output[analyte_columns[denominator]]
        )
        missing_or_bdl = (
            numerator_result.missing
            | denominator_result.missing
            | numerator_result.below_detection
            | denominator_result.below_detection
        )
        non_numeric = (
            numerator_result.non_numeric | denominator_result.non_numeric
        )
        non_finite = (
            numerator_result.non_finite | denominator_result.non_finite
        )
        positive = (
            numerator_result.values.gt(0)
            & denominator_result.values.gt(0)
        )
        finite_inputs = (
            numerator_result.values.notna()
            & denominator_result.values.notna()
        )
        nonpositive = finite_inputs & (~positive)
        valid = finite_inputs & positive
        result = pd.Series(np.nan, index=output.index, dtype="float64")
        result.loc[valid] = (
            numerator_result.values.loc[valid]
            / denominator_result.values.loc[valid]
        )
        result = result.where(np.isfinite(result), np.nan)
        output_column = derived_column_name(variable_id)
        if output_column in output.columns:
            raise DerivedVariableError("derived output column collision")
        output[output_column] = result

        record = {
            "id": variable_id,
            "operation": "ratio",
            "formula": f"{numerator}/{denominator}",
            "numerator": numerator,
            "denominator": denominator,
            "input_unit": expected_unit,
            "output_unit": "dimensionless",
            "output_column": output_column,
            "valid_count": int(result.notna().sum()),
            "missing_or_bdl_count": int(missing_or_bdl.sum()),
            "non_numeric_count": int(non_numeric.sum()),
            "non_finite_count": int(non_finite.sum()),
            "nonpositive_count": int(nonpositive.sum()),
        }
        records.append(record)
        if record["valid_count"] == 0:
            issues.append(
                {
                    "code": "D101",
                    "severity": "review",
                    "message": "一个派生比值没有任何可计算的正有限记录。",
                    "suggested_action": "核对分子、分母、单位、缺失值和非正值。",
                }
            )
        elif (
            record["missing_or_bdl_count"]
            or record["non_numeric_count"]
            or record["non_finite_count"]
            or record["nonpositive_count"]
        ):
            issues.append(
                {
                    "code": "D102",
                    "severity": "warning",
                    "message": "一个派生比值仅对部分记录有效；无效记录保持缺失。",
                    "suggested_action": "在使用该比值前检查派生变量计数摘要。",
                }
            )

    summary = {
        "schema_version": DERIVED_SCHEMA_VERSION,
        "variable_count": len(records),
        "variables": records,
        "issues": issues,
    }
    json.dumps(summary, ensure_ascii=False, allow_nan=False)
    return output, summary


__all__ = [
    "DERIVED_SCHEMA_VERSION",
    "DerivedVariableError",
    "apply_derived_variables",
    "derived_column_name",
]
