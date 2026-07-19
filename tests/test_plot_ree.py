import json
import subprocess
import sys
from pathlib import Path

import matplotlib.image as mpimg
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "plot-ree-patterns"
SCRIPT = SKILL / "scripts" / "plot_ree.py"
EXAMPLE = SKILL / "examples" / "synthetic_ree_data.csv"


def run_plotter(*arguments: object) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *(str(argument) for argument in arguments)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result, json.loads(result.stdout)


def test_exports_png_svg_pdf_and_report(tmp_path: Path) -> None:
    output_dir = tmp_path / "figures"
    result, report = run_plotter(
        EXAMPLE,
        "--output-dir",
        output_dir,
        "--stem",
        "ree_test",
        "--width-mm",
        "100",
        "--height-mm",
        "70",
        "--dpi",
        "100",
    )

    png_path = output_dir / "ree_test.png"
    svg_path = output_dir / "ree_test.svg"
    pdf_path = output_dir / "ree_test.pdf"
    report_path = output_dir / "ree_test.report.json"

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["reference"]["id"] == "Chondrite_SM89"
    assert report["configuration"]["elements"] == [
        "La",
        "Ce",
        "Pr",
        "Nd",
        "Sm",
        "Eu",
        "Gd",
        "Tb",
        "Dy",
        "Ho",
        "Er",
        "Tm",
        "Yb",
        "Lu",
    ]
    assert {item["format"] for item in report["outputs"]} == {"png", "svg", "pdf"}
    assert png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert pdf_path.read_bytes().startswith(b"%PDF")
    svg = svg_path.read_text(encoding="utf-8")
    assert "<text" in svg
    assert "Chondrite_SM89" in svg
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "ready"

    image = mpimg.imread(png_path)
    expected_width = round(100 / 25.4 * 100)
    expected_height = round(70 / 25.4 * 100)
    assert abs(image.shape[1] - expected_width) <= 1
    assert abs(image.shape[0] - expected_height) <= 1


def test_custom_columns_and_element_subset(tmp_path: Path) -> None:
    input_path = tmp_path / "custom.csv"
    output_dir = tmp_path / "figures"
    input_path.write_text(
        "Code,RockUnit,La_ppm,Ce_ppm,Pr_ppm,Nd_ppm\n"
        "A-1,Granite,0.237,0.612,0.095,0.467\n",
        encoding="utf-8",
    )

    result, report = run_plotter(
        input_path,
        "--output-dir",
        output_dir,
        "--sample-column",
        "Code",
        "--group-column",
        "RockUnit",
        "--elements",
        "La,Ce,Pr",
    )

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["configuration"]["sample_column"] == "Code"
    assert report["configuration"]["group_column"] == "RockUnit"
    assert report["configuration"]["elements"] == ["La", "Ce", "Pr"]


def test_missing_value_is_preserved_in_line_data() -> None:
    scripts = str(SKILL / "scripts")
    sys.path.insert(0, scripts)
    try:
        from plot_ree import build_figure

        normalized = pd.DataFrame(
            {
                "Sample": ["A", "B"],
                "La_N": [1.0, 1.2],
                "Ce_N": [np.nan, 1.4],
                "Pr_N": [2.0, 1.6],
            }
        )
        figure, _ = build_figure(
            normalized,
            "Sample",
            None,
            ["La", "Ce", "Pr"],
            "Chondrite_SM89",
            width_mm=100,
            height_mm=70,
        )
        sample_line = figure.axes[0].lines[1]

        assert figure.axes[0].get_yscale() == "log"
        assert np.isnan(sample_line.get_ydata()[1])
        assert figure.axes[0].lines[1].get_marker() != figure.axes[0].lines[2].get_marker()
    finally:
        if "plot_ree" in sys.modules:
            sys.modules["plot_ree"].plt.close("all")
        sys.path.remove(scripts)


def test_non_positive_input_blocks_all_exports(tmp_path: Path) -> None:
    input_path = tmp_path / "zero.csv"
    output_dir = tmp_path / "figures"
    input_path.write_text(
        "Sample,La_ppm,Ce_ppm,Pr_ppm\nA,0,0.612,0.095\n",
        encoding="utf-8",
    )

    result, report = run_plotter(input_path, "--output-dir", output_dir)

    assert result.returncode == 2
    assert report["status"] == "blocked"
    assert not output_dir.exists()


def test_transposed_published_layout_exports_figure(tmp_path: Path) -> None:
    input_path = tmp_path / "published_layout.xlsx"
    output_dir = tmp_path / "figures"
    raw = pd.DataFrame(
        [
            ["Published supplementary table", None, None, None],
            ["Rock type", "Group A", None, "Group B"],
            ["Sample No.", "S-1", "S-2", "S-3"],
            ["Trace element (ppm)", None, None, None],
            ["La", 0.237, 0.474, 0.711],
            ["Ce", 0.612, 1.224, 1.836],
            ["Pr", 0.095, 0.190, 0.285],
            ["Nd", 0.467, 0.934, 1.401],
        ]
    )
    raw.to_excel(input_path, index=False, header=False)

    result, report = run_plotter(input_path, "--output-dir", output_dir)

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["source"]["layout"] == "column_per_sample_transposed"
    assert report["plot"]["sample_count"] == 3
    assert report["plot"]["group_count"] == 2
    assert len(report["outputs"]) == 3
