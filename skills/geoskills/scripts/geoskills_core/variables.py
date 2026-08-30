"""Safe, privacy-preserving variable evaluation for generic x-y plots.

Only two structured references are supported:

* ``direct`` reads one already-mapped analyte column;
* ``derived`` reads one ratio column previously produced by :mod:`derived`.

This module never accepts or evaluates formula text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .derived import DERIVED_SCHEMA_VERSION, derived_column_name
from .quality import coerce_geochemical_numeric


VARIABLE_EVALUATION_SCHEMA_VERSION = "geoskills.variable-evaluation/v1"
_REFERENCE_FIELDS = frozenset({"kind", "id", "scale", "label"})
_KINDS = frozenset({"direct", "derived"})
_SCALES = frozenset({"linear", "log10"})
_MAX_ID_LENGTH = 128
_MAX_LABEL_LENGTH = 256


class VariableEvaluationError(ValueError):
    """A variable reference cannot be evaluated under the safe contract."""


@dataclass(frozen=True)
class AxisVariableReference:
    """One exact variable lookup and its independent display scale."""

    kind: str
    id: str
    scale: str
    label: str | None = None


@dataclass(frozen=True)
class AxisVariableResult:
    """Evaluated values plus a privacy-safe, count-only explanation."""

    values: pd.Series
    valid_mask: pd.Series
    kind: str
    id: str
    scale: str
    output_unit: str
    label: str
    counts: dict[str, int]

    def to_summary(self) -> dict[str, Any]:
        result = {
            "schema_version": VARIABLE_EVALUATION_SCHEMA_VERSION,
            "kind": self.kind,
            "id": self.id,
            "scale": self.scale,
            "output_unit": self.output_unit,
            "label": self.label,
            "counts": dict(self.counts),
        }
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        return result


@dataclass(frozen=True)
class XYVariableResult:
    """Two independent axis results and their shared coordinate mask."""

    x: AxisVariableResult
    y: AxisVariableResult
    joint_valid_mask: pd.Series
    counts: dict[str, int]

    def to_summary(self) -> dict[str, Any]:
        result = {
            "schema_version": VARIABLE_EVALUATION_SCHEMA_VERSION,
            "x": self.x.to_summary(),
            "y": self.y.to_summary(),
            "coordinate_counts": dict(self.counts),
        }
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        return result


def _safe_text(
    value: Any,
    field: str,
    *,
    maximum_length: int,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VariableEvaluationError(f"{field} must be non-empty text")
    result = value.strip()
    if len(result) > maximum_length or any(ord(character) < 32 for character in result):
        raise VariableEvaluationError(f"{field} contains unsafe text")
    return result


def parse_axis_variable_reference(value: Any) -> AxisVariableReference:
    """Validate a strict reference without accepting formula-like fields."""

    if not isinstance(value, Mapping):
        raise VariableEvaluationError("axis variable reference must be a mapping")
    raw = {str(key): item for key, item in value.items()}
    if set(raw) - _REFERENCE_FIELDS:
        raise VariableEvaluationError("axis variable reference has unsupported fields")
    missing = {"kind", "id", "scale"} - set(raw)
    if missing:
        raise VariableEvaluationError("axis variable reference is incomplete")
    kind = _safe_text(raw["kind"], "kind", maximum_length=16)
    if kind not in _KINDS:
        raise VariableEvaluationError("kind must be direct or derived")
    scale = _safe_text(raw["scale"], "scale", maximum_length=16)
    if scale not in _SCALES:
        raise VariableEvaluationError("scale must be linear or log10")
    label = raw.get("label")
    return AxisVariableReference(
        kind=kind,
        id=_safe_text(raw["id"], "id", maximum_length=_MAX_ID_LENGTH),
        scale=scale,
        label=(
            None
            if label is None
            else _safe_text(label, "label", maximum_length=_MAX_LABEL_LENGTH)
        ),
    )


def _validated_reference(
    value: AxisVariableReference | Mapping[str, Any],
) -> AxisVariableReference:
    if isinstance(value, AxisVariableReference):
        return parse_axis_variable_reference(
            {
                "kind": value.kind,
                "id": value.id,
                "scale": value.scale,
                **({"label": value.label} if value.label is not None else {}),
            }
        )
    return parse_axis_variable_reference(value)


def _derived_record(
    variable_id: str,
    summary: Mapping[str, Any] | None,
    *,
    row_count: int,
) -> dict[str, Any]:
    if not isinstance(summary, Mapping):
        raise VariableEvaluationError("derived summary is required")
    if summary.get("schema_version") != DERIVED_SCHEMA_VERSION:
        raise VariableEvaluationError("derived summary schema is unsupported")
    variables = summary.get("variables")
    if not isinstance(variables, list):
        raise VariableEvaluationError("derived summary variables are invalid")
    matches = [
        item
        for item in variables
        if isinstance(item, Mapping) and item.get("id") == variable_id
    ]
    if len(matches) != 1:
        raise VariableEvaluationError("derived summary must contain one exact variable")
    record = {str(key): value for key, value in matches[0].items()}
    expected_column = derived_column_name(variable_id)
    if (
        record.get("operation") != "ratio"
        or record.get("output_column") != expected_column
        or record.get("output_unit") != "dimensionless"
    ):
        raise VariableEvaluationError("derived summary ratio provenance is invalid")
    numerator = record.get("numerator")
    denominator = record.get("denominator")
    input_unit = record.get("input_unit")
    if (
        not isinstance(numerator, str)
        or not numerator
        or not isinstance(denominator, str)
        or not denominator
        or numerator == denominator
        or not isinstance(input_unit, str)
        or not input_unit
        or record.get("formula") != f"{numerator}/{denominator}"
    ):
        raise VariableEvaluationError("derived summary ratio provenance is invalid")
    for field in (
        "valid_count",
        "missing_or_bdl_count",
        "non_numeric_count",
        "non_finite_count",
        "nonpositive_count",
    ):
        count = record.get(field)
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= row_count:
            raise VariableEvaluationError("derived summary counts are invalid")
    return record


def _default_label(identifier: str, unit: str) -> str:
    return identifier if unit == "dimensionless" else f"{identifier} ({unit})"


def evaluate_axis_variable(
    frame: pd.DataFrame,
    reference: AxisVariableReference | Mapping[str, Any],
    *,
    analyte_columns: Mapping[str, str],
    analyte_units: Mapping[str, str],
    derived_summary: Mapping[str, Any] | None = None,
) -> AxisVariableResult:
    """Evaluate one direct or previously approved derived variable.

    Linear axes retain every finite numeric value, including zero and negative
    values. Log axes keep the original magnitude but mask non-positive values.
    """

    ref = _validated_reference(reference)
    row_count = int(frame.shape[0])
    if ref.kind == "direct":
        column = analyte_columns.get(ref.id)
        unit = analyte_units.get(ref.id)
        if column is None or column not in frame.columns:
            raise VariableEvaluationError("direct variable source is missing")
        if not isinstance(unit, str) or not unit.strip():
            raise VariableEvaluationError("direct variable unit is missing")
        parsed = coerce_geochemical_numeric(frame[column])
        raw_values = parsed.values.astype("float64")
        missing_or_bdl_count = int(
            (parsed.missing | parsed.below_detection).sum()
        )
        non_numeric_count = int(parsed.non_numeric.sum())
        non_finite_count = int(parsed.non_finite.sum())
        source_nonpositive_count = 0
        formula_label = ref.id
    else:
        record = _derived_record(ref.id, derived_summary, row_count=row_count)
        column = derived_column_name(ref.id)
        if column not in frame.columns:
            raise VariableEvaluationError("derived output column is missing")
        parsed = coerce_geochemical_numeric(frame[column])
        raw_values = parsed.values.astype("float64")
        if int(raw_values.notna().sum()) != int(record["valid_count"]):
            raise VariableEvaluationError("derived output no longer matches its summary")
        unit = str(record["output_unit"])
        missing_or_bdl_count = int(record["missing_or_bdl_count"])
        non_numeric_count = int(record["non_numeric_count"])
        non_finite_count = int(record["non_finite_count"])
        source_nonpositive_count = int(record["nonpositive_count"])
        formula_label = str(record["formula"])

    finite = pd.Series(
        np.isfinite(raw_values.to_numpy(dtype=float, na_value=np.nan)),
        index=frame.index,
        dtype=bool,
    ) & raw_values.notna()
    log_nonpositive = finite & raw_values.le(0) if ref.scale == "log10" else pd.Series(
        False, index=frame.index, dtype=bool
    )
    valid = finite & (~log_nonpositive)
    values = raw_values.where(valid).astype("float64")
    counts = {
        "row_count": row_count,
        "valid_count": int(valid.sum()),
        "unavailable_count": int((~valid).sum()),
        "missing_or_bdl_count": missing_or_bdl_count,
        "non_numeric_count": non_numeric_count,
        "non_finite_count": non_finite_count,
        "source_nonpositive_count": source_nonpositive_count,
        "log_nonpositive_count": int(log_nonpositive.sum()),
    }
    result = AxisVariableResult(
        values=values,
        valid_mask=valid.astype(bool),
        kind=ref.kind,
        id=ref.id,
        scale=ref.scale,
        output_unit=unit,
        label=ref.label or (
            formula_label
            if ref.kind == "derived"
            else _default_label(formula_label, unit)
        ),
        counts=counts,
    )
    result.to_summary()
    return result


def evaluate_xy_variables(
    frame: pd.DataFrame,
    *,
    x_reference: AxisVariableReference | Mapping[str, Any],
    y_reference: AxisVariableReference | Mapping[str, Any],
    analyte_columns: Mapping[str, str],
    analyte_units: Mapping[str, str],
    derived_summary: Mapping[str, Any] | None = None,
) -> XYVariableResult:
    """Evaluate X and Y independently, then compute a joint plotting mask."""

    x_result = evaluate_axis_variable(
        frame,
        x_reference,
        analyte_columns=analyte_columns,
        analyte_units=analyte_units,
        derived_summary=derived_summary,
    )
    y_result = evaluate_axis_variable(
        frame,
        y_reference,
        analyte_columns=analyte_columns,
        analyte_units=analyte_units,
        derived_summary=derived_summary,
    )
    joint = (x_result.valid_mask & y_result.valid_mask).astype(bool)
    result = XYVariableResult(
        x=x_result,
        y=y_result,
        joint_valid_mask=joint,
        counts={
            "row_count": int(frame.shape[0]),
            "valid_coordinate_count": int(joint.sum()),
            "invalid_coordinate_count": int((~joint).sum()),
        },
    )
    result.to_summary()
    return result


__all__ = [
    "VARIABLE_EVALUATION_SCHEMA_VERSION",
    "AxisVariableReference",
    "AxisVariableResult",
    "VariableEvaluationError",
    "XYVariableResult",
    "evaluate_axis_variable",
    "evaluate_xy_variables",
    "parse_axis_variable_reference",
]
