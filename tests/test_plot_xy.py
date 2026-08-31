from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from plot_xy import inspect_xy_path, plot_xy_path  # noqa: E402
from geoskills_core.derived import DERIVED_SCHEMA_VERSION  # noqa: E402


def _input(path: Path) -> Path:
    pd.DataFrame(
        {
            "Sample": ["PRIVATE-ID-1", "PRIVATE-ID-2", "PRIVATE-ID-3", "PRIVATE-ID-4"],
            "Group": ["A", "A", "B", "B"],
            "SiO2_wt%": [48.0, 52.0, 60.0, 70.0],
            "Derived__Nb_Y": [0.4, 0.8, 1.2, 2.0],
        }
    ).to_csv(path, index=False)
    return path


def _derived_summary() -> dict:
    return {
        "schema_version": DERIVED_SCHEMA_VERSION,
        "variables": [
            {
                "id": "Nb_Y",
                "operation": "ratio",
                "formula": "Nb/Y",
                "output_column": "Derived__Nb_Y",
                "output_unit": "dimensionless",
                "numerator": "Nb",
                "denominator": "Y",
                "input_unit": "ppm",
                "valid_count": 4,
                "missing_or_bdl_count": 0,
                "non_numeric_count": 0,
                "non_finite_count": 0,
                "nonpositive_count": 0,
            }
        ]
    }


def test_xy_inspector_returns_only_count_safe_coordinate_summary(tmp_path: Path) -> None:
    report = inspect_xy_path(
        _input(tmp_path / "input.csv"),
        x_reference={"kind": "direct", "id": "SiO2", "scale": "linear"},
        y_reference={"kind": "derived", "id": "Nb_Y", "scale": "log10"},
        analyte_columns={"SiO2": "SiO2_wt%"},
        analyte_units={"SiO2": "wt%"},
        derived_summary=_derived_summary(),
    )

    assert report["status"] == "ready"
    assert report["coordinates"]["joint_valid_count"] == 4
    serialized = json.dumps(report, ensure_ascii=False)
    assert "PRIVATE-ID" not in serialized
    assert "48.0" not in serialized


def test_xy_plot_exports_complete_grouped_bundle_without_sample_ids(tmp_path: Path) -> None:
    output = tmp_path / "output"
    report = plot_xy_path(
        input_path=_input(tmp_path / "input.csv"),
        output_dir=output,
        stem="figure-xy",
        requested_sample_column="Sample",
        requested_group_column="Group",
        x_reference={"kind": "direct", "id": "SiO2", "scale": "linear"},
        y_reference={"kind": "derived", "id": "Nb_Y", "scale": "log10"},
        analyte_columns={"SiO2": "SiO2_wt%"},
        analyte_units={"SiO2": "wt%"},
        derived_summary=_derived_summary(),
        width_mm=100,
        height_mm=80,
        dpi=100,
    )

    assert report["status"] == "ready"
    assert report["plot"]["joint_valid_count"] == 4
    for extension in ("svg", "pdf", "tiff", "png"):
        assert (output / f"figure-xy.{extension}").is_file()
    svg = (output / "figure-xy.svg").read_text(encoding="utf-8")
    assert "PRIVATE-ID" not in svg
    assert "SiO" in svg
    assert "Nb/Y" in svg
    with Image.open(output / "figure-xy.tiff") as image:
        assert image.mode == "RGB"
        assert image.info.get("compression") == "tiff_lzw"


def test_xy_linear_axes_keep_finite_zero_and_negative_values(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    pd.DataFrame(
        {
            "Sample": ["S1", "S2", "S3"],
            "X_ppm": [-2.0, 0.0, 2.0],
            "Y_ppm": [1.0, 2.0, 3.0],
        }
    ).to_csv(path, index=False)

    report = inspect_xy_path(
        path,
        x_reference={"kind": "direct", "id": "X", "scale": "linear"},
        y_reference={"kind": "direct", "id": "Y", "scale": "linear"},
        analyte_columns={"X": "X_ppm", "Y": "Y_ppm"},
        analyte_units={"X": "ppm", "Y": "ppm"},
        derived_summary={"variables": []},
    )

    assert report["status"] == "ready"
    assert report["coordinates"]["joint_valid_count"] == 3


def test_xy_log_axis_masks_nonpositive_values_count_only(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    pd.DataFrame(
        {
            "Sample": ["S1", "S2", "S3", "S4"],
            "X_ppm": [1.0, 2.0, 3.0, 4.0],
            "Y_ppm": [-1.0, 0.0, 1.0, np.inf],
        }
    ).to_csv(path, index=False)

    report = inspect_xy_path(
        path,
        x_reference={"kind": "direct", "id": "X", "scale": "linear"},
        y_reference={"kind": "direct", "id": "Y", "scale": "log10"},
        analyte_columns={"X": "X_ppm", "Y": "Y_ppm"},
        analyte_units={"X": "ppm", "Y": "ppm"},
        derived_summary={"variables": []},
    )

    assert report["coordinates"]["joint_valid_count"] == 1
    assert report["coordinates"]["y"]["log_nonpositive_count"] == 2
    assert report["coordinates"]["y"]["non_finite_count"] == 1
