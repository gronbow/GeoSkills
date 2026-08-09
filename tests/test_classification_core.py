from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from geoskills_core.classification import (  # noqa: E402
    CLASSIFICATION_MODEL_SCHEMA_VERSION,
    ClassificationModelError,
    add_classification_background,
    classify_coordinates,
    evaluate_model_axes,
    evaluate_variable,
    load_classification_model,
    summarize_classifications,
    validate_classification_model,
)


def synthetic_model() -> dict:
    return {
        "schema_version": CLASSIFICATION_MODEL_SCHEMA_VERSION,
        "id": "synthetic-test-only",
        "display_name": "Synthetic test model",
        "version": "1.0.0",
        "source": {
            "citation": "Synthetic geometry for software tests only.",
            "geometry_reference": "Coordinates are not scientific boundaries.",
        },
        "scientific_review": {
            "status": "approved",
            "reviewed_on": "2026-08-08",
            "notes": "Approval applies only to software test behavior.",
        },
        "variables": [
            {
                "id": "x_ratio",
                "operation": "ratio",
                "numerator": "Nb",
                "denominator": "Y",
                "numerator_unit": "ppm",
                "denominator_unit": "ppm",
                "scale": 1.0,
                "output_unit": "dimensionless",
                "formula": "Nb/Y",
            },
            {
                "id": "y_direct",
                "operation": "direct",
                "source": "SiO2",
                "source_unit": "wt%",
                "scale": 1.0,
                "output_unit": "wt%",
                "formula": "SiO2",
            },
        ],
        "axes": {
            "x": {
                "variable": "x_ratio",
                "label": "Synthetic X",
                "scale": "log10",
                "limits": [0.1, 100.0],
            },
            "y": {
                "variable": "y_direct",
                "label": "Synthetic Y",
                "scale": "linear",
                "limits": [0.0, 100.0],
            },
        },
        "fields": [
            {
                "id": "field-a",
                "label": "A",
                "vertices": [[1.0, 10.0], [10.0, 10.0], [10.0, 50.0], [1.0, 50.0]],
                "label_position": [3.0, 30.0],
            }
        ],
        "boundary": {
            "tolerance": 1e-9,
            "on_boundary": "review",
            "overlap": "review",
            "outside": "outside",
        },
    }


def test_strict_model_validation_and_round_trip() -> None:
    model = validate_classification_model(synthetic_model())

    assert model.id == "synthetic-test-only"
    assert model.x_axis.scale == "log10"
    assert model.to_dict() == synthetic_model()
    json.dumps(model.to_dict(), ensure_ascii=False, allow_nan=False)


def test_pending_unknown_and_invalid_log_models_are_rejected() -> None:
    pending = synthetic_model()
    pending["scientific_review"]["status"] = "pending"
    with pytest.raises(ClassificationModelError, match="not approved"):
        validate_classification_model(pending)
    assert validate_classification_model(pending, require_approved=False)

    unknown = synthetic_model()
    unknown["expression"] = "unsafe"
    with pytest.raises(ClassificationModelError, match="unsupported fields"):
        validate_classification_model(unknown)

    invalid_log = synthetic_model()
    invalid_log["fields"][0]["vertices"][0][0] = 0.0
    with pytest.raises(ClassificationModelError, match="positive"):
        validate_classification_model(invalid_log)

    invalid_formula = synthetic_model()
    invalid_formula["variables"][0]["formula"] = "Y/Nb"
    with pytest.raises(ClassificationModelError, match="structured operations"):
        validate_classification_model(invalid_formula)

    invalid_date = synthetic_model()
    invalid_date["scientific_review"]["reviewed_on"] = "2026-02-31"
    with pytest.raises(ClassificationModelError, match="YYYY-MM-DD"):
        validate_classification_model(invalid_date)

    self_intersection = synthetic_model()
    self_intersection["fields"][0]["vertices"] = [
        [1.0, 10.0],
        [10.0, 50.0],
        [10.0, 10.0],
        [1.0, 50.0],
    ]
    with pytest.raises(ClassificationModelError, match="self-intersects"):
        validate_classification_model(self_intersection)


def test_model_file_hash_is_pinned(tmp_path: Path) -> None:
    model_path = tmp_path / "model.json"
    payload = json.dumps(synthetic_model(), ensure_ascii=False).encode("utf-8")
    model_path.write_bytes(payload)

    digest = hashlib.sha256(payload).hexdigest()
    assert load_classification_model(model_path, expected_sha256=digest).id
    with pytest.raises(ClassificationModelError, match="hash changed"):
        load_classification_model(model_path, expected_sha256="0" * 64)

    duplicate_payload = payload.decode("utf-8").replace(
        '"id": "synthetic-test-only"',
        '"id": "first", "id": "second"',
        1,
    )
    model_path.write_text(duplicate_payload, encoding="utf-8")
    with pytest.raises(ClassificationModelError, match="duplicate JSON keys"):
        load_classification_model(model_path)


def test_axes_are_evaluated_without_expression_parsing() -> None:
    model = validate_classification_model(synthetic_model())
    frame = pd.DataFrame(
        {
            "Nb_ppm": [20.0, 10.0, 1.0],
            "Y_ppm": [10.0, 0.0, 2.0],
            "SiO2_wt%": [40.0, 50.0, "bad"],
        }
    )

    x_values, y_values, summary = evaluate_model_axes(
        frame,
        model,
        analyte_columns={"Nb": "Nb_ppm", "Y": "Y_ppm", "SiO2": "SiO2_wt%"},
        analyte_units={"Nb": "ppm", "Y": "ppm", "SiO2": "wt%"},
    )

    assert x_values.iloc[0] == 2.0
    assert y_values.iloc[0] == 40.0
    assert x_values.iloc[1:].isna().all()
    assert y_values.iloc[1:].isna().all()
    assert summary == {
        "row_count": 3,
        "valid_coordinate_count": 1,
        "invalid_coordinate_count": 2,
    }

    with pytest.raises(ClassificationModelError, match="unit mismatch"):
        evaluate_model_axes(
            frame,
            model,
            analyte_columns={"Nb": "Nb_ppm", "Y": "Y_ppm", "SiO2": "SiO2_wt%"},
            analyte_units={"Nb": "ppm", "Y": "wt%", "SiO2": "wt%"},
        )


def test_winchester_floyd_coordinate_formula_is_supported_without_boundaries() -> None:
    document = synthetic_model()
    document["variables"][0] = {
        "id": "zr_tio2_scaled",
        "operation": "ratio",
        "numerator": "Zr",
        "denominator": "TiO2",
        "numerator_unit": "ppm",
        "denominator_unit": "wt%",
        "scale": 0.0001,
        "output_unit": "scaled ratio",
        "formula": "(Zr/TiO2) * 0.0001",
    }
    document["axes"]["x"]["variable"] = "zr_tio2_scaled"
    model = validate_classification_model(document)
    frame = pd.DataFrame(
        {
            "Zr_ppm": [100.0, 250.0, 100.0],
            "TiO2_wt%": [1.0, 0.5, 0.0],
        }
    )

    values = evaluate_variable(
        frame,
        model.variables[0],
        analyte_columns={"Zr": "Zr_ppm", "TiO2": "TiO2_wt%"},
        analyte_units={"Zr": "ppm", "TiO2": "wt%"},
    )

    assert values.iloc[0] == pytest.approx(0.01)
    assert values.iloc[1] == pytest.approx(0.05)
    assert pd.isna(values.iloc[2])


def test_classification_handles_inside_boundary_outside_invalid_and_overlap() -> None:
    model = validate_classification_model(synthetic_model())
    records = classify_coordinates(
        [2.0, 1.0, 20.0, np.nan],
        [20.0, 20.0, 20.0, 20.0],
        model,
    )

    assert records == [
        {"status": "classified", "field_id": "field-a"},
        {"status": "review_boundary", "field_id": None},
        {"status": "outside", "field_id": None},
        {"status": "invalid", "field_id": None},
    ]
    assert summarize_classifications(records) == {
        "status_counts": {
            "classified": 1,
            "invalid": 1,
            "outside": 1,
            "review_boundary": 1,
        },
        "field_counts": {"field-a": 1},
    }

    overlap = copy.deepcopy(synthetic_model())
    overlap["fields"].append(
        {
            "id": "field-b",
            "label": "B",
            "vertices": [[1.5, 15.0], [8.0, 15.0], [8.0, 45.0], [1.5, 45.0]],
        }
    )
    overlap_model = validate_classification_model(overlap)
    assert classify_coordinates([2.0], [20.0], overlap_model) == [
        {"status": "review_overlap", "field_id": None}
    ]


def test_background_uses_reviewed_axes_and_geometry() -> None:
    model = validate_classification_model(synthetic_model())
    figure, axes = plt.subplots()
    try:
        returned = add_classification_background(axes, model)
        assert returned is axes
        assert axes.get_xscale() == "log"
        assert axes.get_yscale() == "linear"
        assert axes.get_xlabel() == "Synthetic X"
        assert axes.get_ylabel() == "Synthetic Y"
        assert len(axes.lines) == 1
        assert len(axes.texts) == 1
    finally:
        plt.close(figure)
