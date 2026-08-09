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

from geoskills_core.derived import (  # noqa: E402
    DERIVED_SCHEMA_VERSION,
    DerivedVariableError,
    apply_derived_variables,
)


def test_same_unit_ratio_is_deterministic_and_invalid_rows_remain_missing() -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["PRIVATE-A", "PRIVATE-B", "PRIVATE-C", "PRIVATE-D"],
            "Nb_ppm": [10.0, "<0.1", 5.0, 2.0],
            "Y_ppm": [20.0, 10.0, 0.0, "bad"],
        }
    )

    output, summary = apply_derived_variables(
        frame,
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

    assert output["Derived__Nb_Y"].iloc[0] == 0.5
    assert output["Derived__Nb_Y"].iloc[1:].isna().all()
    assert summary["schema_version"] == DERIVED_SCHEMA_VERSION
    assert summary["variable_count"] == 1
    assert summary["variables"][0]["valid_count"] == 1
    assert summary["variables"][0]["missing_or_bdl_count"] == 1
    assert summary["variables"][0]["non_numeric_count"] == 1
    assert summary["variables"][0]["nonpositive_count"] == 1
    assert summary["issues"][0]["code"] == "D102"
    encoded = json.dumps(summary, ensure_ascii=False, allow_nan=False)
    assert "PRIVATE-A" not in encoded
    assert "10.0" not in encoded


def test_ratio_rejects_mixed_units_and_unsupported_operations() -> None:
    frame = pd.DataFrame({"Nb_ppm": [1.0], "TiO2_wt%": [1.0]})
    common = {
        "frame": frame,
        "analyte_columns": {"Nb": "Nb_ppm", "TiO2": "TiO2_wt%"},
        "analyte_units": {"Nb": "ppm", "TiO2": "wt%"},
    }
    with pytest.raises(DerivedVariableError, match="identical units"):
        apply_derived_variables(
            specifications=[
                {
                    "id": "Nb_TiO2",
                    "operation": "ratio",
                    "numerator": "Nb",
                    "denominator": "TiO2",
                }
            ],
            **common,
        )
    with pytest.raises(DerivedVariableError, match="unsupported"):
        apply_derived_variables(
            specifications=[
                {
                    "id": "unsafe",
                    "operation": "expression",
                    "numerator": "Nb",
                    "denominator": "TiO2",
                }
            ],
            **common,
        )


def test_ratio_rejects_output_collision() -> None:
    frame = pd.DataFrame(
        {"Nb_ppm": [1.0], "Y_ppm": [2.0], "Derived__Nb_Y": [np.nan]}
    )
    with pytest.raises(DerivedVariableError, match="collision"):
        apply_derived_variables(
            frame,
            specifications=[
                {
                    "id": "Nb_Y",
                    "operation": "ratio",
                    "numerator": "Nb",
                    "denominator": "Y",
                }
            ],
            analyte_columns={"Nb": "Nb_ppm", "Y": "Y_ppm"},
            analyte_units={"Nb": "ppm", "Y": "ppm"},
        )
