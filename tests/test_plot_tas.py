import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "geoskills"
SCRIPT = SKILL / "scripts" / "plot_tas.py"
EXAMPLE = SKILL / "examples" / "synthetic_major_element_data.csv"
MODEL = SKILL / "assets" / "classification" / "tas-lemaitre-2002.json"
sys.path.insert(0, str(SKILL / "scripts"))

from plot_tas import classify_tas_point, load_tas_model  # noqa: E402


def run_plotter(
    *arguments: object,
) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *(str(item) for item in arguments)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result, json.loads(result.stdout)


def test_tas_asset_has_expected_fields_and_vertices() -> None:
    model = load_tas_model(MODEL)
    fields = {field["id"]: field for field in model["fields"]}

    assert model["source"]["boundary_doi"] == "10.1007/BF01160698"
    assert len(fields) == 15
    assert fields["B"]["polygon"] == [
        [45.0, 0.0],
        [45.0, 5.0],
        [52.0, 5.0],
        [52.0, 0.0],
    ]
    assert fields["T"]["name"] == "Trachyte/Trachydacite"
    assert fields["U1"]["name"] == "Tephrite/Basanite"


@pytest.mark.parametrize(
    ("x", "y", "field"),
    [
        (47.0, 3.0, "B"),
        (54.0, 4.0, "O1"),
        (59.5, 4.8, "O2"),
        (66.0, 5.5, "O3"),
        (74.0, 6.2, "R"),
        (50.0, 6.0, "S1"),
        (54.0, 7.2, "S2"),
        (59.0, 9.0, "S3"),
        (49.0, 10.3, "U2"),
        (58.0, 14.0, "Ph"),
    ],
)
def test_representative_points_classify_deterministically(
    x: float,
    y: float,
    field: str,
) -> None:
    result = classify_tas_point(x, y, load_tas_model(MODEL))

    assert result["status"] == "classified"
    assert result["field"] == field


def test_point_on_shared_boundary_requires_review() -> None:
    result = classify_tas_point(52.0, 5.0, load_tas_model(MODEL))

    assert result["status"] == "boundary_review"
    assert result["name"] is None


def test_tas_requires_domain_and_basis_confirmation(
    tmp_path: Path,
) -> None:
    result, report = run_plotter(
        EXAMPLE,
        "--output-dir",
        tmp_path / "blocked",
    )

    assert result.returncode == 2
    assert report["status"] == "blocked"
    assert {item["code"] for item in report["issues"]} == {
        "E711",
        "E712",
    }


def test_exports_tas_classification_bundle(tmp_path: Path) -> None:
    output = tmp_path / "tas"
    result, report = run_plotter(
        EXAMPLE,
        "--output-dir",
        output,
        "--stem",
        "tas_test",
        "--confirm-volcanic",
        "--composition-basis",
        "anhydrous-normalized",
        "--width-mm",
        "100",
        "--height-mm",
        "80",
        "--dpi",
        "100",
    )
    paths = {
        suffix: output / f"tas_test.{suffix}"
        for suffix in ("svg", "pdf", "tiff", "png")
    }

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["model"]["id"] == "TAS_LeMaitre2002_Volcanic_CombinedT"
    assert report["plot"]["classification_status_counts"] == {
        "classified": 10
    }
    assert report["plot"]["axes_frame"] == "full"
    assert report["configuration"]["legend_position"].startswith("inside_")
    assert "filename" not in report["source"]
    assert "path" not in report["source"]
    svg = paths["svg"].read_text(encoding="utf-8")
    assert "<text" in svg
    assert "Foidite" in svg
    with Image.open(paths["png"]) as image:
        assert image.size[0] in range(392, 395)
        assert image.size[1] in range(313, 317)
        assert image.info["dpi"][0] == pytest.approx(100, abs=0.1)
    with Image.open(paths["tiff"]) as image:
        assert image.mode == "RGB"
        assert image.tag_v2.get(259) == 5
        assert image.info["dpi"] == (100.0, 100.0)


def test_as_reported_basis_is_explicitly_provisional(
    tmp_path: Path,
) -> None:
    result, report = run_plotter(
        EXAMPLE,
        "--output-dir",
        tmp_path / "reported",
        "--confirm-volcanic",
        "--composition-basis",
        "as-reported",
        "--dpi",
        "90",
    )

    assert result.returncode == 0
    assert any(item["code"] == "W711" for item in report["issues"])


def test_existing_tas_bundle_requires_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    arguments = (
        EXAMPLE,
        "--output-dir",
        output,
        "--confirm-volcanic",
        "--composition-basis",
        "anhydrous-normalized",
        "--dpi",
        "90",
    )
    first, _ = run_plotter(*arguments)
    second, report = run_plotter(*arguments)

    assert first.returncode == 0
    assert second.returncode == 1
    assert report["status"] == "error"
