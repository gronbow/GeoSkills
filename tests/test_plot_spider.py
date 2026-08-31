import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "geoskills"
SCRIPT = SKILL / "scripts" / "plot_spider.py"
EXAMPLE = SKILL / "examples" / "synthetic_spider_data.csv"


def run_plotter(*arguments: object) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *(str(argument) for argument in arguments)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result, json.loads(result.stdout)


def test_exports_spider_publication_bundle(tmp_path: Path) -> None:
    output_dir = tmp_path / "figure"
    result, report = run_plotter(
        EXAMPLE,
        "--output-dir",
        output_dir,
        "--stem",
        "spider_test",
        "--width-mm",
        "100",
        "--height-mm",
        "70",
        "--dpi",
        "100",
    )
    paths = {
        extension: output_dir / f"spider_test.{extension}"
        for extension in ("svg", "pdf", "tiff", "png")
    }
    source_path = output_dir / "spider_test.source_data.csv"
    report_path = output_dir / "spider_test.report.json"

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["reference"]["id"] == "PrimitiveMantleModified_SM89"
    assert report["configuration"]["axes_frame"] == "full"
    assert report["configuration"]["legend_layout"] == "inside-auto"
    assert report["configuration"]["grid_style"] == "none"
    assert report["configuration"]["elements"][:6] == [
        "Rb",
        "Ba",
        "Th",
        "U",
        "Nb",
        "Ta",
    ]
    assert report["source"]["format"] == ".csv"
    assert report["source"]["size_bytes"] == EXAMPLE.stat().st_size
    assert len(report["source"]["file_sha256"]) == 64
    assert "filename" not in report["source"]
    assert report["source"]["layout"] == "row_per_sample"
    assert all(path.exists() and path.stat().st_size > 0 for path in paths.values())
    assert source_path.exists()
    assert report_path.exists()
    assert paths["pdf"].read_bytes().startswith(b"%PDF")
    svg = paths["svg"].read_text(encoding="utf-8")
    assert "<text" in svg
    assert "Table 1 footnote b" in svg
    with Image.open(paths["png"]) as image:
        assert image.size[0] in range(392, 395)
        assert image.size[1] in range(274, 277)
        assert image.info["dpi"][0] == pytest.approx(100, abs=0.1)
    with Image.open(paths["tiff"]) as image:
        assert image.tag_v2.get(259) == 5
        assert image.info["dpi"] == (100.0, 100.0)
        assert image.mode == "RGB"
    assert len(report["oxide_conversions"]) == 3
    assert not any(item["code"] == "W557" for item in report["issues"])
    assert report["plot"]["x_tick_label_strategy"] == "staggered"


def test_spider_figure_can_hide_sample_ids_without_losing_group_legend(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "private-safe"
    result, report = run_plotter(
        EXAMPLE,
        "--output-dir",
        output_dir,
        "--stem",
        "private_safe",
        "--hide-sample-ids",
        "--group-legend-title",
        "Sample suite",
        "--dpi",
        "90",
    )

    svg = (output_dir / "private_safe.svg").read_text(encoding="utf-8")
    assert result.returncode == 0
    assert report["configuration"]["show_sample_ids"] is False
    assert report["configuration"]["group_legend_title"] == "Sample suite"
    assert report["plot"]["sample_ids_rendered"] is False
    assert "SYN-A" not in svg
    assert "SYN-B" not in svg
    assert "SYN-C" not in svg
    assert "Suite A" in svg
    assert "Suite B" in svg
    assert "Sample suite" in svg


def test_custom_elements_follow_reference_order(tmp_path: Path) -> None:
    output_dir = tmp_path / "custom"
    result, report = run_plotter(
        EXAMPLE,
        "--output-dir",
        output_dir,
        "--stem",
        "custom",
        "--elements",
        "Lu,Rb,Nb,La,Ti,Y",
        "--dpi",
        "90",
    )

    assert result.returncode == 0
    assert report["configuration"]["elements"] == [
        "Rb",
        "Nb",
        "La",
        "Ti",
        "Y",
        "Lu",
    ]


def test_nmorb_reference_is_selectable(tmp_path: Path) -> None:
    output_dir = tmp_path / "nmorb"
    result, report = run_plotter(
        EXAMPLE,
        "--output-dir",
        output_dir,
        "--stem",
        "nmorb",
        "--reference",
        "nmorb-sm89",
        "--dpi",
        "90",
    )

    assert result.returncode == 0
    assert report["reference"]["id"] == "NMORB_SM89"
    assert report["configuration"]["reference_key"] == "nmorb-sm89"
    assert not any(item["code"] == "W557" for item in report["issues"])


def test_printed_primitive_mantle_warns_about_alternate_values(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "printed"
    result, report = run_plotter(
        EXAMPLE,
        "--output-dir",
        output_dir,
        "--stem",
        "printed",
        "--reference",
        "pm-sm89",
        "--dpi",
        "90",
    )

    assert result.returncode == 0
    assert report["reference"]["id"] == "PrimitiveMantle_SM89"
    assert any(item["code"] == "W557" for item in report["issues"])


def test_bdl_value_creates_source_data_gap(tmp_path: Path) -> None:
    input_path = tmp_path / "bdl.csv"
    output_dir = tmp_path / "bdl"
    pd.DataFrame(
        {
            "Sample": ["S1", "S2"],
            "Rb_ppm": ["bdl", 2.0],
            "Ba_ppm": [2.0, 3.0],
            "Th_ppm": [1.0, 1.2],
            "U_ppm": [0.5, 0.6],
            "Nb_ppm": [4.0, 5.0],
            "Ta_ppm": [0.3, 0.4],
        }
    ).to_csv(input_path, index=False)

    result, report = run_plotter(
        input_path,
        "--output-dir",
        output_dir,
        "--stem",
        "bdl",
        "--dpi",
        "90",
    )
    source = pd.read_csv(output_dir / "bdl.source_data.csv")

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert any(item["code"] == "W431" for item in report["issues"])
    assert pd.isna(source.at[0, "Rb_N"])


def test_nonpositive_value_blocks_outputs(tmp_path: Path) -> None:
    input_path = tmp_path / "invalid.csv"
    output_dir = tmp_path / "invalid"
    pd.DataFrame(
        {
            "Sample": ["S1"],
            "Rb_ppm": [0],
            "Ba_ppm": [2],
            "Th_ppm": [1],
            "U_ppm": [0.5],
            "Nb_ppm": [4],
        }
    ).to_csv(input_path, index=False)

    result, report = run_plotter(
        input_path,
        "--output-dir",
        output_dir,
        "--stem",
        "invalid",
    )

    assert result.returncode == 2
    assert report["status"] == "blocked"
    assert not output_dir.exists()


def test_existing_bundle_requires_overwrite(tmp_path: Path) -> None:
    output_dir = tmp_path / "existing"
    first, _ = run_plotter(
        EXAMPLE,
        "--output-dir",
        output_dir,
        "--stem",
        "same",
        "--dpi",
        "90",
    )
    second, report = run_plotter(
        EXAMPLE,
        "--output-dir",
        output_dir,
        "--stem",
        "same",
        "--dpi",
        "90",
    )

    assert first.returncode == 0
    assert second.returncode == 1
    assert report["status"] == "error"
