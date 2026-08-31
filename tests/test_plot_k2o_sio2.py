from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
EXAMPLES = ROOT / "skills" / "geoskills" / "examples"
MODEL = (
    ROOT
    / "skills"
    / "geoskills"
    / "assets"
    / "classification"
    / "k2o-sio2-pt76-r89-original.json"
)
sys.path.insert(0, str(SCRIPTS))

from geoskills_core.classification import (  # noqa: E402
    classify_coordinates,
    load_classification_model,
)
from plot_k2o_sio2 import plot_k2o_sio2_path  # noqa: E402


def test_reviewed_asset_preserves_corrected_original_boundaries() -> None:
    model = load_classification_model(MODEL)

    assert model.id == "k2o-sio2-pt76-r89-original"
    assert model.scientific_review["status"] == "approved"
    assert model.source["doi"] == "10.1007/BF00384745"
    assert model.source["geometry_doi"] == "10.1016/0024-4937(89)90028-5"
    middle = next(
        item
        for item in model.display_boundaries
        if item.id == "calc-alkaline-high-k"
    )
    assert (52.0, 1.5) in middle.vertices
    assert (52.0, 1.3) not in middle.vertices
    assert middle.vertices[-1] == (70.0, 3.0)
    upper = next(
        item
        for item in model.display_boundaries
        if item.id == "high-k-shoshonitic"
    )
    assert upper.vertices[-1] == (63.0, 4.0)


def test_conservative_classification_handles_four_fields_and_domain() -> None:
    model = load_classification_model(MODEL)
    records = classify_coordinates(
        [55.0, 55.0, 55.0, 55.0, 52.0, 70.0],
        [0.3, 1.2, 2.4, 4.5, 1.5, 2.0],
        model,
    )

    assert records == [
        {"status": "classified", "field_id": "tholeiitic-series"},
        {"status": "classified", "field_id": "calc-alkaline-series"},
        {"status": "classified", "field_id": "high-k-calc-alkaline-series"},
        {"status": "classified", "field_id": "shoshonitic-series"},
        {"status": "review_boundary", "field_id": None},
        {"status": "outside", "field_id": None},
    ]


def test_plotter_exports_submission_bundle_and_requires_scientific_gates(
    tmp_path: Path,
) -> None:
    blocked = plot_k2o_sio2_path(
        EXAMPLES / "synthetic_major_element_data.csv",
        tmp_path / "blocked",
        requested_sample_column="Sample",
        requested_group_column="Group",
        composition_basis="anhydrous-normalized",
        dpi=90,
    )
    assert blocked["status"] == "blocked"
    assert not (tmp_path / "blocked").exists()

    output = tmp_path / "ready"
    report = plot_k2o_sio2_path(
        EXAMPLES / "synthetic_major_element_data.csv",
        output,
        stem="figure-k2o",
        requested_sample_column="Sample",
        requested_group_column="Group",
        confirm_volcanic=True,
        composition_basis="anhydrous-normalized",
        width_mm=100.0,
        height_mm=80.0,
        dpi=100,
    )

    assert report["status"] == "ready"
    assert report["model"]["boundary_policy"]["extrapolated"] is False
    assert report["plot"]["complete_domain_x"] == [48.0, 63.0]
    assert report["plot"]["classification_status_counts"]["outside"] == 2
    assert {item["code"] for item in report["issues"]} == {"W812"}
    expected = {
        "figure-k2o.svg",
        "figure-k2o.pdf",
        "figure-k2o.tiff",
        "figure-k2o.png",
        "figure-k2o.source_data.csv",
        "figure-k2o.report.json",
    }
    assert {path.name for path in output.iterdir()} == expected
    exported = pd.read_csv(output / "figure-k2o.source_data.csv")
    assert set(exported["K2O_SiO2_status"]) == {"classified", "outside"}
    svg = (output / "figure-k2o.svg").read_text(encoding="utf-8")
    assert "Peccerillo" in svg
    assert "complete four-field domain" in svg
    assert "<text" in svg
    with Image.open(output / "figure-k2o.png") as image:
        assert image.size[0] in range(392, 396)
        assert image.size[1] in range(313, 317)
        assert image.info["dpi"][0] == pytest.approx(100, abs=0.1)
    with Image.open(output / "figure-k2o.tiff") as image:
        assert image.mode == "RGB"
        assert image.tag_v2.get(259) == 5
        assert image.info["dpi"] == (100.0, 100.0)
    persisted = json.loads(
        (output / "figure-k2o.report.json").read_text(encoding="utf-8")
    )
    assert persisted["model"]["sha256"] == report["model"]["sha256"]
