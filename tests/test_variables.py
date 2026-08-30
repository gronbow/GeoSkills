from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from geoskills_core.derived import apply_derived_variables  # noqa: E402
from geoskills_core.variables import (  # noqa: E402
    AxisVariableReference,
    VariableEvaluationError,
    evaluate_axis_variable,
    evaluate_xy_variables,
    parse_axis_variable_reference,
)


def test_axis_reference_is_structured_and_rejects_expression_fields() -> None:
    assert parse_axis_variable_reference(
        {"kind": "direct", "id": "SiO2", "scale": "linear"}
    ) == AxisVariableReference(
        kind="direct", id="SiO2", scale="linear", label=None
    )
    assert parse_axis_variable_reference(
        {
            "kind": "derived",
            "id": "Nb_Y",
            "scale": "log10",
            "label": "Nb/Y",
        }
    ) == AxisVariableReference(
        kind="derived", id="Nb_Y", scale="log10", label="Nb/Y"
    )

    with pytest.raises(VariableEvaluationError, match="unsupported fields"):
        parse_axis_variable_reference(
            {
                "kind": "direct",
                "id": "SiO2",
                "scale": "linear",
                "expression": "__import__('os')",
            }
        )
    with pytest.raises(VariableEvaluationError, match="kind"):
        parse_axis_variable_reference(
            {"kind": "expression", "id": "unsafe", "scale": "linear"}
        )
    with pytest.raises(VariableEvaluationError, match="scale"):
        parse_axis_variable_reference(
            {"kind": "direct", "id": "SiO2", "scale": "sqrt"}
        )


def test_direct_linear_keeps_finite_zero_and_negative_values() -> None:
    frame = pd.DataFrame(
        {
            "Sample": [
                "PRIVATE-A",
                "PRIVATE-B",
                "PRIVATE-C",
                "PRIVATE-D",
                "PRIVATE-E",
                "PRIVATE-F",
                "PRIVATE-G",
            ],
            "X": [-2.0, 0.0, 3.0, None, "<0.1", "bad", np.inf],
        }
    )

    result = evaluate_axis_variable(
        frame,
        AxisVariableReference(kind="direct", id="X", scale="linear"),
        analyte_columns={"X": "X"},
        analyte_units={"X": "ppm"},
    )

    assert result.values.iloc[:3].tolist() == [-2.0, 0.0, 3.0]
    assert result.values.iloc[3:].isna().all()
    assert result.valid_mask.tolist() == [True, True, True, False, False, False, False]
    assert result.output_unit == "ppm"
    assert result.label == "X (ppm)"
    assert result.scale == "linear"
    assert result.counts == {
        "row_count": 7,
        "valid_count": 3,
        "unavailable_count": 4,
        "missing_or_bdl_count": 2,
        "non_numeric_count": 1,
        "non_finite_count": 1,
        "source_nonpositive_count": 0,
        "log_nonpositive_count": 0,
    }
    encoded = json.dumps(result.to_summary(), ensure_ascii=False, allow_nan=False)
    assert "PRIVATE-A" not in encoded
    assert "-2.0" not in encoded


def test_direct_log_masks_nonpositive_values_with_count_only_reason() -> None:
    frame = pd.DataFrame({"X": [-2.0, 0.0, 3.0, np.nan]})

    result = evaluate_axis_variable(
        frame,
        AxisVariableReference(
            kind="direct", id="X", scale="log10", label="Custom X"
        ),
        analyte_columns={"X": "X"},
        analyte_units={"X": "wt%"},
    )

    assert result.values.iloc[:2].isna().all()
    assert result.values.iloc[2] == 3.0
    assert pd.isna(result.values.iloc[3])
    assert result.valid_mask.tolist() == [False, False, True, False]
    assert result.label == "Custom X"
    assert result.counts["log_nonpositive_count"] == 2
    assert result.counts["valid_count"] == 1


def test_derived_reference_reuses_approved_ratio_output_and_provenance() -> None:
    source = pd.DataFrame(
        {
            "Nb_ppm": [10.0, 5.0, "bad", 2.0],
            "Y_ppm": [20.0, 0.0, 10.0, None],
        }
    )
    frame, derived_summary = apply_derived_variables(
        source,
        specifications=[
            {
                "id": "Nb_Y",
                "operation": "ratio",
                "numerator": "Nb",
                "denominator": "Y",
                "input_unit": "ppm",
            }
        ],
        analyte_columns={"Nb": "Nb_ppm", "Y": "Y_ppm"},
        analyte_units={"Nb": "ppm", "Y": "ppm"},
    )

    result = evaluate_axis_variable(
        frame,
        AxisVariableReference(kind="derived", id="Nb_Y", scale="log10"),
        analyte_columns={},
        analyte_units={},
        derived_summary=derived_summary,
    )

    assert result.values.iloc[0] == 0.5
    assert result.values.iloc[1:].isna().all()
    assert result.output_unit == "dimensionless"
    assert result.label == "Nb/Y"
    assert result.counts == {
        "row_count": 4,
        "valid_count": 1,
        "unavailable_count": 3,
        "missing_or_bdl_count": 1,
        "non_numeric_count": 1,
        "non_finite_count": 0,
        "source_nonpositive_count": 1,
        "log_nonpositive_count": 0,
    }


def test_derived_reference_cannot_recompute_or_trust_unapproved_metadata() -> None:
    frame = pd.DataFrame(
        {"Nb_ppm": [10.0], "Y_ppm": [20.0], "Derived__Nb_Y": [0.5]}
    )
    reference = AxisVariableReference(
        kind="derived", id="Nb_Y", scale="linear"
    )

    with pytest.raises(VariableEvaluationError, match="summary"):
        evaluate_axis_variable(
            frame,
            reference,
            analyte_columns={"Nb": "Nb_ppm", "Y": "Y_ppm"},
            analyte_units={"Nb": "ppm", "Y": "ppm"},
        )

    unsafe_summary = {
        "schema_version": "unsafe/v1",
        "variables": [
            {
                "id": "Nb_Y",
                "operation": "expression",
                "output_column": "Derived__Nb_Y",
                "output_unit": "dimensionless",
            }
        ],
    }
    with pytest.raises(VariableEvaluationError, match="summary"):
        evaluate_axis_variable(
            frame,
            reference,
            analyte_columns={},
            analyte_units={},
            derived_summary=unsafe_summary,
        )


def test_xy_axes_keep_independent_scales_and_masks() -> None:
    frame = pd.DataFrame(
        {
            "X": [-1.0, 0.0, 2.0, 3.0],
            "Y": [10.0, 0.0, -5.0, 100.0],
        }
    )

    result = evaluate_xy_variables(
        frame,
        x_reference=AxisVariableReference(
            kind="direct", id="X", scale="linear"
        ),
        y_reference=AxisVariableReference(
            kind="direct", id="Y", scale="log10"
        ),
        analyte_columns={"X": "X", "Y": "Y"},
        analyte_units={"X": "ppm", "Y": "ppm"},
    )

    assert result.x.values.tolist() == [-1.0, 0.0, 2.0, 3.0]
    assert result.x.valid_mask.tolist() == [True, True, True, True]
    assert result.y.valid_mask.tolist() == [True, False, False, True]
    assert result.joint_valid_mask.tolist() == [True, False, False, True]
    assert result.counts == {
        "row_count": 4,
        "valid_coordinate_count": 2,
        "invalid_coordinate_count": 2,
    }
    encoded = json.dumps(result.to_summary(), ensure_ascii=False, allow_nan=False)
    assert "values" not in encoded
