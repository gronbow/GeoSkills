from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from geoskills_core.basis import (  # noqa: E402
    DATA_BASIS_SCHEMA_VERSION,
    DataBasisError,
    apply_data_basis,
)


COLUMNS = {
    "SiO2": "SiO2_wt%",
    "Na2O": "Na2O_wt%",
    "K2O": "K2O_wt%",
}
UNITS = {name: "wt%" for name in COLUMNS}
SPECIFICATION = {
    "operation": "normalize-to-100",
    "basis": "anhydrous-100",
    "analytes": ["SiO2", "Na2O", "K2O"],
}


def test_normalize_to_100_uses_a_copy_and_records_counts_only() -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["PRIVATE-A", "PRIVATE-B"],
            "SiO2_wt%": [50.0, 40.0],
            "Na2O_wt%": [45.0, 36.0],
            "K2O_wt%": [5.0, 4.0],
        }
    )
    original = frame.copy(deep=True)

    output, summary = apply_data_basis(
        frame,
        specification=SPECIFICATION,
        analyte_columns=COLUMNS,
        analyte_units=UNITS,
    )

    pd.testing.assert_frame_equal(frame, original)
    assert output.loc[0, [*COLUMNS.values()]].sum() == pytest.approx(100.0)
    assert output.loc[1, "SiO2_wt%"] == pytest.approx(50.0)
    assert output.loc[1, "Na2O_wt%"] == pytest.approx(45.0)
    assert output.loc[1, "K2O_wt%"] == pytest.approx(5.0)
    assert summary == {
        "schema_version": DATA_BASIS_SCHEMA_VERSION,
        "configured": True,
        "operation": "normalize-to-100",
        "basis": "anhydrous-100",
        "target_total": 100.0,
        "unit": "wt%",
        "analytes": ["SiO2", "Na2O", "K2O"],
        "row_count": 2,
        "valid_row_count": 2,
        "invalid_row_count": 0,
        "invalid_reason_counts": {
            "missing_or_bdl": 0,
            "non_numeric": 0,
            "non_finite": 0,
            "negative": 0,
            "nonpositive_total": 0,
        },
        "source_columns_overwritten": False,
        "issues": [],
    }
    assert "PRIVATE" not in str(summary)


def test_invalid_rows_stay_missing_and_reasons_are_counted() -> None:
    frame = pd.DataFrame(
        {
            "SiO2_wt%": [50.0, None, 50.0, 0.0, "bad", np.inf],
            "Na2O_wt%": [45.0, 45.0, 45.0, 0.0, 45.0, 45.0],
            "K2O_wt%": [5.0, 5.0, -1.0, 0.0, 5.0, 5.0],
        }
    )

    output, summary = apply_data_basis(
        frame,
        specification=SPECIFICATION,
        analyte_columns=COLUMNS,
        analyte_units=UNITS,
    )

    assert output.loc[0, [*COLUMNS.values()]].notna().all()
    assert output.loc[1:, [*COLUMNS.values()]].isna().all(axis=1).all()
    assert summary["valid_row_count"] == 1
    assert summary["invalid_row_count"] == 5
    assert summary["invalid_reason_counts"] == {
        "missing_or_bdl": 1,
        "non_numeric": 1,
        "non_finite": 1,
        "negative": 1,
        "nonpositive_total": 1,
    }
    assert [item["code"] for item in summary["issues"]] == ["B102"]


def test_no_valid_rows_is_an_error_and_declared_mode_does_not_recalculate() -> None:
    invalid = pd.DataFrame(
        {"SiO2_wt%": [None], "Na2O_wt%": [0.0], "K2O_wt%": [0.0]}
    )
    _, invalid_summary = apply_data_basis(
        invalid,
        specification=SPECIFICATION,
        analyte_columns=COLUMNS,
        analyte_units=UNITS,
    )
    assert invalid_summary["issues"][0]["code"] == "B101"
    assert invalid_summary["issues"][0]["severity"] == "error"

    declared = pd.DataFrame(
        {"SiO2_wt%": [49.5], "Na2O_wt%": [3.0], "K2O_wt%": [1.5]}
    )
    output, summary = apply_data_basis(
        declared,
        specification={**SPECIFICATION, "operation": "use-as-declared"},
        analyte_columns=COLUMNS,
        analyte_units=UNITS,
    )
    pd.testing.assert_frame_equal(output, declared)
    assert summary["operation"] == "use-as-declared"


@pytest.mark.parametrize(
    ("specification", "units"),
    [
        ({**SPECIFICATION, "operation": "expression"}, UNITS),
        ({**SPECIFICATION, "basis": "unknown"}, UNITS),
        ({**SPECIFICATION, "analytes": ["SiO2"]}, UNITS),
        (SPECIFICATION, {**UNITS, "K2O": "ppm"}),
    ],
)
def test_invalid_basis_contract_is_rejected(
    specification: dict,
    units: dict[str, str],
) -> None:
    frame = pd.DataFrame(
        {"SiO2_wt%": [50.0], "Na2O_wt%": [45.0], "K2O_wt%": [5.0]}
    )
    with pytest.raises(DataBasisError):
        apply_data_basis(
            frame,
            specification=specification,
            analyte_columns=COLUMNS,
            analyte_units=units,
        )
