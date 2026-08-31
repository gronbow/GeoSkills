import json
import subprocess
import sys
from pathlib import Path

import matplotlib.image as mpimg
import numpy as np
import pandas as pd
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "geoskills"
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


def test_exports_publication_bundle_and_report(tmp_path: Path) -> None:
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
    tiff_path = output_dir / "ree_test.tiff"
    source_data_path = output_dir / "ree_test.source_data.csv"
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
    assert {item["format"] for item in report["outputs"]} == {
        "png",
        "svg",
        "pdf",
        "tiff",
    }
    assert png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert tiff_path.read_bytes()[:4] in {b"II*\x00", b"MM\x00*"}
    with Image.open(tiff_path) as tiff_image:
        assert tiff_image.mode == "RGB"
        assert tiff_image.tag_v2.get(259) == 5
        assert tiff_image.info["dpi"] == (100.0, 100.0)
    svg = svg_path.read_text(encoding="utf-8")
    assert "<text" in svg
    assert "C1 chondrite" in svg
    assert "Sun &amp; McDonough (1989)" in svg
    assert report["submission_qa"]["svg_text_editable"] is True
    assert report["submission_qa"]["colourblind_support"]
    assert report["source_data"]["path"] == str(source_data_path.resolve())
    source_data = pd.read_csv(source_data_path)
    assert source_data.columns.tolist()[:2] == ["Sample", "Group"]
    assert "La_N" in source_data.columns
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
        "--y-margin",
        "0.05",
    )

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["configuration"]["sample_column"] == "Code"
    assert report["configuration"]["group_column"] == "RockUnit"
    assert report["configuration"]["elements"] == ["La", "Ce", "Pr"]
    assert report["configuration"]["png_dpi"] == 600
    assert report["configuration"]["tiff_dpi"] == 600
    assert report["configuration"]["y_margin_fraction"] == 0.05
    assert report["configuration"]["y_limit_policy"] == (
        "adaptive_log10_clean_bounds"
    )
    assert report["plot"]["legend_strategy"] == (
        "separate group colour/line-style and sample-symbol keys"
    )
    assert report["configuration"]["axes_frame"] == "open"
    assert report["configuration"]["legend_layout"] == "outside"
    assert report["configuration"]["grid_style"] == "none"


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
        figure, plot_info = build_figure(
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
        assert (
            figure.axes[0].lines[1].get_marker()
            != figure.axes[0].lines[2].get_marker()
        )
        assert plot_info["unity_line_visible"] is True
        assert len(figure.legends) == 1
    finally:
        if "plot_ree" in sys.modules:
            sys.modules["plot_ree"].plt.close("all")
        sys.path.remove(scripts)


def test_adaptive_log_limits_remove_empty_unity_decade() -> None:
    scripts = str(SKILL / "scripts")
    sys.path.insert(0, scripts)
    try:
        from plot_ree import build_figure

        normalized = pd.DataFrame(
            {
                "Sample": ["A", "B"],
                "La_N": [11.3, 20.0],
                "Ce_N": [100.0, 200.0],
                "Pr_N": [1004.2, 800.0],
            }
        )
        figure, plot_info = build_figure(
            normalized,
            "Sample",
            None,
            ["La", "Ce", "Pr"],
            "Chondrite_SM89",
            width_mm=100,
            height_mm=70,
        )
        lower, upper = figure.axes[0].get_ylim()

        assert plot_info["unity_line_visible"] is False
        assert plot_info["y_limits"]["policy"] == (
            "adaptive_log10_clean_bounds"
        )
        assert lower == 10.0
        assert upper == 1500.0
        assert plot_info["y_limits"]["adaptive_lower"] < lower < 11.3
        assert upper > plot_info["y_limits"]["adaptive_upper"]
        assert plot_info["y_limits"]["rounding"] == {
            "policy": "clean_log_bounds",
            "lower_step": 10.0,
            "upper_step": 100.0,
        }
        assert len(figure.axes[0].lines) == 2
    finally:
        if "plot_ree" in sys.modules:
            sys.modules["plot_ree"].plt.close("all")
        sys.path.remove(scripts)


def test_full_frame_inside_auto_legend_avoids_data() -> None:
    scripts = str(SKILL / "scripts")
    sys.path.insert(0, scripts)
    try:
        from plot_ree import build_figure

        normalized = pd.DataFrame(
            {
                "Sample": ["S1", "S2", "S3", "S4", "S5", "S6"],
                "Group": ["A", "A", "B", "B", "C", "C"],
                "La_N": [850.0, 720.0, 550.0, 470.0, 390.0, 320.0],
                "Ce_N": [600.0, 520.0, 380.0, 330.0, 280.0, 230.0],
                "Pr_N": [360.0, 320.0, 240.0, 210.0, 180.0, 150.0],
                "Nd_N": [220.0, 190.0, 145.0, 125.0, 105.0, 88.0],
                "Sm_N": [105.0, 90.0, 70.0, 60.0, 50.0, 42.0],
                "Eu_N": [80.0, 70.0, 55.0, 48.0, 40.0, 34.0],
                "Gd_N": [66.0, 58.0, 45.0, 40.0, 32.0, 28.0],
                "Tb_N": [55.0, 48.0, 38.0, 33.0, 27.0, 23.0],
                "Dy_N": [46.0, 40.0, 31.0, 27.0, 22.0, 19.0],
                "Ho_N": [38.0, 33.0, 26.0, 23.0, 19.0, 16.0],
                "Er_N": [32.0, 28.0, 22.0, 19.0, 16.0, 14.0],
                "Tm_N": [28.0, 24.0, 19.0, 17.0, 14.0, 12.0],
                "Yb_N": [24.0, 21.0, 17.0, 15.0, 13.0, 11.0],
                "Lu_N": [21.0, 18.0, 15.0, 13.0, 11.5, 10.5],
            }
        )
        figure, plot_info = build_figure(
            normalized,
            "Sample",
            "Group",
            ["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu"],
            "Chondrite_SM89",
            width_mm=183,
            height_mm=120,
            axes_frame="full",
            legend_layout="inside-auto",
        )
        axes = figure.axes[0]

        assert axes.spines["top"].get_visible() is True
        assert axes.spines["right"].get_visible() is True
        assert plot_info["axes_frame"] == "full"
        assert plot_info["legend_layout_requested"] == "inside-auto"
        assert plot_info["legend_position"] == "inside_upper_right"
        assert plot_info["legend_fallback"] is False
        assert plot_info["legend_collision_free"] is True
        assert plot_info["inside_legend_collision_free"] is True
        assert all(not line.get_visible() for line in axes.yaxis.get_gridlines())
        assert axes.yaxis.label.get_fontsize() <= 7
    finally:
        if "plot_ree" in sys.modules:
            sys.modules["plot_ree"].plt.close("all")
        sys.path.remove(scripts)


def test_inside_auto_compacts_long_group_and_sample_legends() -> None:
    scripts = str(SKILL / "scripts")
    sys.path.insert(0, scripts)
    try:
        from plot_ree import build_figure

        elements = [
            "Rb",
            "Ba",
            "Th",
            "U",
            "Nb",
            "Ta",
            "K",
            "La",
            "Ce",
            "Pb",
            "Pr",
            "Sr",
            "P",
            "Nd",
            "Sm",
            "Zr",
            "Hf",
            "Eu",
            "Ti",
            "Gd",
            "Tb",
            "Dy",
            "Y",
            "Ho",
            "Er",
            "Tm",
            "Yb",
            "Lu",
        ]
        sample_count = 11
        normalized = pd.DataFrame(
            {
                "Sample": [
                    f"SYN-{index + 1:02d}" for index in range(sample_count)
                ],
                "Group": [
                    f"Long synthetic group {index % 4 + 1} "
                    + "X" * 32
                    for index in range(sample_count)
                ],
                **{
                    f"{element}_N": [
                        300.0
                        * np.exp(-0.10 * element_index)
                        * (1.0 + 0.10 * sample_index)
                        * (
                            1.0
                            + 0.30
                            * np.sin(
                                (element_index + sample_index) / 2.5
                            )
                        )
                        for sample_index in range(sample_count)
                    ]
                    for element_index, element in enumerate(elements)
                },
            }
        )

        figure, plot_info = build_figure(
            normalized,
            "Sample",
            "Group",
            elements,
            "PM_synthetic",
            width_mm=183,
            height_mm=120,
            axes_frame="full",
            legend_layout="inside-auto",
            reference_note="Synthetic normalization for layout testing",
        )

        assert plot_info["legend_position"] == "inside_upper_right"
        assert plot_info["legend_fallback"] is False
        assert plot_info["inside_legend_strategy"] in {
            "compact-two-column",
            "compact-wide",
        }
        assert plot_info["inside_legend_collision_free"] is True
        axes = figure.axes[0]
        assert axes.get_legend() is not None
        assert len(axes.artists) == 1
    finally:
        if "plot_ree" in sys.modules:
            sys.modules["plot_ree"].plt.close("all")
        sys.path.remove(scripts)


def test_subunity_to_enriched_pattern_exports_successfully(tmp_path: Path) -> None:
    input_path = tmp_path / "cross_unity.csv"
    output_dir = tmp_path / "figures"
    input_path.write_text(
        "Sample,Group,La_ppm,Ce_ppm,Pr_ppm\n"
        "A,Test,0.05925,0.612,9.5\n",
        encoding="utf-8",
    )

    result, report = run_plotter(
        input_path,
        "--output-dir",
        output_dir,
        "--stem",
        "cross_unity",
        "--axes-frame",
        "full",
        "--legend-layout",
        "inside-auto",
        "--dpi",
        "72",
    )

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["configuration"]["y_limits"]["data_min"] == 0.25
    assert report["configuration"]["y_limits"]["lower"] == 0.2
    assert report["configuration"]["y_limits"]["upper"] >= 100.0
    assert report["configuration"]["unity_line"] is True
    assert len(report["outputs"]) == 4


def test_skipped_sample_is_not_listed_in_legend() -> None:
    scripts = str(SKILL / "scripts")
    sys.path.insert(0, scripts)
    try:
        from plot_ree import build_figure

        normalized = pd.DataFrame(
            {
                "Sample": ["EMPTY", "PLOTTED"],
                "La_N": [np.nan, 2.0],
                "Ce_N": [np.nan, 3.0],
                "Pr_N": [np.nan, 4.0],
            }
        )
        figure, plot_info = build_figure(
            normalized,
            "Sample",
            None,
            ["La", "Ce", "Pr"],
            "Chondrite_SM89",
            width_mm=100,
            height_mm=70,
        )
        legend_labels = [text.get_text() for text in figure.legends[0].get_texts()]

        assert plot_info["sample_count"] == 2
        assert plot_info["plotted_sample_count"] == 1
        assert plot_info["legend_sample_count"] == 1
        assert plot_info["skipped_samples"] == ["EMPTY"]
        assert legend_labels == ["PLOTTED"]
    finally:
        if "plot_ree" in sys.modules:
            sys.modules["plot_ree"].plt.close("all")
        sys.path.remove(scripts)


def test_sample_ids_can_be_suppressed_while_group_key_is_preserved() -> None:
    scripts = str(SKILL / "scripts")
    sys.path.insert(0, scripts)
    try:
        from plot_ree import build_figure

        normalized = pd.DataFrame(
            {
                "Sample": ["PRIVATE-001", "PRIVATE-002"],
                "Group": ["Suite A", "Suite B"],
                "La_N": [12.0, 18.0],
                "Ce_N": [10.0, 15.0],
                "Pr_N": [8.0, 12.0],
            }
        )
        figure, plot_info = build_figure(
            normalized,
            "Sample",
            "Group",
            ["La", "Ce", "Pr"],
            "Chondrite_SM89",
            width_mm=100,
            height_mm=70,
            show_sample_ids=False,
        )

        assert len(figure.legends) == 1
        legend = figure.legends[0]
        assert legend.get_title().get_text() == "Group"
        legend_text = " ".join(text.get_text() for text in legend.get_texts())
        assert "Suite A" in legend_text
        assert "Suite B" in legend_text
        assert "PRIVATE-001" not in legend_text
        assert "PRIVATE-002" not in legend_text
        assert plot_info["sample_ids_rendered"] is False
        assert plot_info["legend_sample_count"] == 0
    finally:
        if "plot_ree" in sys.modules:
            sys.modules["plot_ree"].plt.close("all")
        sys.path.remove(scripts)


def test_group_legend_title_is_explicit_not_inferred_from_column_name() -> None:
    scripts = str(SKILL / "scripts")
    sys.path.insert(0, scripts)
    try:
        from plot_ree import build_figure

        normalized = pd.DataFrame(
            {
                "Sample": ["A"],
                "Group": ["Suite A"],
                "La_N": [12.0],
                "Ce_N": [10.0],
                "Pr_N": [8.0],
            }
        )
        default_figure, _ = build_figure(
            normalized,
            "Sample",
            "Group",
            ["La", "Ce", "Pr"],
            "Chondrite_SM89",
            width_mm=100,
            height_mm=70,
            show_sample_ids=False,
        )
        explicit_figure, _ = build_figure(
            normalized,
            "Sample",
            "Group",
            ["La", "Ce", "Pr"],
            "Chondrite_SM89",
            width_mm=100,
            height_mm=70,
            show_sample_ids=False,
            group_legend_title="Lithology",
        )

        assert default_figure.legends[0].get_title().get_text() == "Group"
        assert explicit_figure.legends[0].get_title().get_text() == "Lithology"
    finally:
        if "plot_ree" in sys.modules:
            sys.modules["plot_ree"].plt.close("all")
        sys.path.remove(scripts)


def test_repeated_sample_symbols_are_reported(tmp_path: Path) -> None:
    input_path = tmp_path / "many_samples.csv"
    output_dir = tmp_path / "figures"
    frame = pd.DataFrame(
        {
            "Sample": [f"S{index:02d}" for index in range(13)],
            "Group": ["A"] * 13,
            "La_ppm": np.linspace(0.237, 2.37, 13),
            "Ce_ppm": np.linspace(0.612, 6.12, 13),
            "Pr_ppm": np.linspace(0.095, 0.95, 13),
        }
    )
    frame.to_csv(input_path, index=False)

    result, report = run_plotter(
        input_path,
        "--output-dir",
        output_dir,
        "--dpi",
        "72",
    )
    issue_codes = {item["code"] for item in report["issues"]}

    assert result.returncode == 0
    assert report["plot"]["plotted_sample_count"] == 13
    assert report["plot"]["marker_repeated"] is True
    assert report["plot"]["sample_encoding"] == "symbols repeat after 12 plotted samples"
    assert "W506" in issue_codes
    assert "unique sample symbol" not in report["submission_qa"]["colourblind_support"]


def test_inside_auto_legend_falls_back_when_data_fill_the_axes() -> None:
    scripts = str(SKILL / "scripts")
    sys.path.insert(0, scripts)
    try:
        from plot_ree import build_figure

        elements = ["La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd"]
        values = np.geomspace(1.0, 1000.0, 8)
        normalized = pd.DataFrame(
            {
                "Sample": [f"S{index + 1}" for index in range(8)],
                "Group": [f"G{index % 4 + 1}" for index in range(8)],
                **{
                    f"{element}_N": np.roll(values, index)
                    for index, element in enumerate(elements)
                },
            }
        )
        figure, plot_info = build_figure(
            normalized,
            "Sample",
            "Group",
            elements,
            "Chondrite_SM89",
            width_mm=183,
            height_mm=120,
            axes_frame="full",
            legend_layout="inside-auto",
        )

        assert plot_info["legend_position"] == "outside_right_fallback"
        assert plot_info["legend_fallback"] is True
        assert plot_info["legend_collision_free"] is True
        assert plot_info["inside_legend_collision_free"] is False
        assert len(figure.legends) == 2
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
    assert len(report["outputs"]) == 4
    assert Path(report["source_data"]["path"]).exists()


def test_single_column_can_move_reference_note_out_of_canvas() -> None:
    scripts = str(SKILL / "scripts")
    sys.path.insert(0, scripts)
    try:
        from plot_ree import build_figure

        normalized = pd.DataFrame(
            {
                "Sample": ["S1", "S2"],
                "Group": ["A", "B"],
                "La_N": [100.0, 80.0],
                "Ce_N": [90.0, 70.0],
                "Pr_N": [70.0, 55.0],
            }
        )
        figure, plot_info = build_figure(
            normalized,
            "Sample",
            "Group",
            ["La", "Ce", "Pr"],
            "Chondrite_SM89",
            width_mm=89,
            height_mm=75,
            axes_frame="full",
            legend_layout="inside-auto",
            show_sample_ids=False,
            show_reference_note=False,
            style_preset="publication-single-column",
        )

        assert plot_info["reference_note_on_canvas"] is False
        assert not any("Normalization:" in text.get_text() for text in figure.texts)
        assert np.isclose(figure.get_size_inches()[0], 89 / 25.4)
        figure.canvas.draw()
        label_box = figure.axes[0].yaxis.label.get_window_extent(
            figure.canvas.get_renderer()
        )
        assert label_box.x0 >= 0
        assert label_box.x1 <= figure.bbox.width
    finally:
        if "plot_ree" in sys.modules:
            sys.modules["plot_ree"].plt.close("all")
        sys.path.remove(scripts)
