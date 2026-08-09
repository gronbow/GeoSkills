from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from geoskills_core.quality import (  # noqa: E402
    QUALITY_SCHEMA_VERSION,
    assess_data_quality,
    coerce_geochemical_numeric,
)


def test_numeric_coercion_preserves_missing_bdl_and_invalid_states() -> None:
    source = pd.Series([1, "2.5", "<0.1", "BDL", "", None, "bad", "inf", 0, -1])

    result = coerce_geochemical_numeric(source)

    assert result.values.notna().sum() == 4
    assert result.values.iloc[0] == 1
    assert result.values.iloc[1] == 2.5
    assert result.missing.sum() == 2
    assert result.below_detection.sum() == 2
    assert result.non_numeric.sum() == 1
    assert result.non_finite.sum() == 1


def test_quality_summary_is_count_only_and_privacy_safe() -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["SYN-SECRET-1", "syn-secret-1", ""],
            "SiO2_wt%": [50.0, "bad", 48.0],
            "Na2O_wt%": [4.0, "<0.1", -1.0],
        }
    )

    summary = assess_data_quality(
        frame,
        sample_column="Sample",
        analyte_columns={"SiO2": "SiO2_wt%", "Na2O": "Na2O_wt%"},
        analyte_units={"SiO2": "wt%", "Na2O": "wt%"},
        policy={
            "duplicate_sample_ids": "review",
            "non_numeric_values": "error",
            "major_oxide_total": None,
        },
    )

    encoded = json.dumps(summary, ensure_ascii=False, allow_nan=False)
    assert summary["schema_version"] == QUALITY_SCHEMA_VERSION
    assert summary["status"] == "error"
    assert summary["blank_sample_id_count"] == 1
    assert summary["duplicate_identifier_count"] == 1
    assert summary["duplicate_row_count"] == 2
    assert summary["cell_counts"] == {
        "missing": 0,
        "below_detection": 1,
        "non_numeric": 1,
        "non_finite": 0,
        "nonpositive": 1,
    }
    assert {item["code"] for item in summary["issues"]} == {
        "Q001",
        "Q002",
        "Q003",
        "Q005",
        "Q006",
    }
    assert "SYN-SECRET" not in encoded
    assert "50.0" not in encoded


def test_explicit_major_oxide_total_reports_counts_not_row_values() -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["A", "B", "C", "D"],
            "SiO2_wt%": [60.0, 70.0, 40.0, None],
            "Na2O_wt%": [40.0, 40.0, 40.0, 1.0],
        }
    )

    summary = assess_data_quality(
        frame,
        sample_column="Sample",
        analyte_columns={"SiO2": "SiO2_wt%", "Na2O": "Na2O_wt%"},
        analyte_units={"SiO2": "wt%", "Na2O": "wt%"},
        policy={
            "duplicate_sample_ids": "review",
            "non_numeric_values": "error",
            "major_oxide_total": {
                "analytes": ["SiO2", "Na2O"],
                "lower": 95.0,
                "upper": 105.0,
                "composition_basis": "as-reported",
                "severity": "review",
            },
        },
    )

    total = summary["major_oxide_total"]
    assert total["evaluated_row_count"] == 3
    assert total["in_range_count"] == 1
    assert total["below_range_count"] == 1
    assert total["above_range_count"] == 1
    assert total["incomplete_row_count"] == 1
    assert {item["code"] for item in summary["issues"]} >= {"Q004", "Q007", "Q008"}
    encoded = json.dumps(summary, ensure_ascii=False, allow_nan=False)
    assert '"110.0"' not in encoded
    assert '"80.0"' not in encoded


def test_quality_rejects_missing_source_columns() -> None:
    with pytest.raises(ValueError, match="analyte columns are missing"):
        assess_data_quality(
            pd.DataFrame({"Sample": ["A"]}),
            sample_column="Sample",
            analyte_columns={"Nb": "Nb_ppm"},
            analyte_units={"Nb": "ppm"},
            policy={},
        )
