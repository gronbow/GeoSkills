import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "geoskills"
SCRIPT = SKILL / "scripts" / "plot_harker.py"
EXAMPLE = SKILL / "examples" / "synthetic_major_element_data.csv"


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


def test_exports_harker_publication_bundle(tmp_path: Path) -> None:
    output = tmp_path / "harker"
    result, report = run_plotter(
        EXAMPLE,
        "--output-dir",
        output,
        "--stem",
        "harker_test",
        "--y",
        "MgO,CaO,K2O",
        "--width-mm",
        "100",
        "--height-mm",
        "70",
        "--dpi",
        "100",
    )
    paths = {
        suffix: output / f"harker_test.{suffix}"
        for suffix in ("svg", "pdf", "tiff", "png")
    }

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["configuration"]["x"] == "SiO2"
    assert report["configuration"]["y"] == ["MgO", "CaO", "K2O"]
    assert report["plot"]["legend_position"] == "shared_figure_top"
    assert report["plot"]["legend_within_figure"] is True
    assert report["plot"]["shared_x_label"] is True
    assert report["plot"]["axes_frame"] == "full"
    assert all(path.exists() and path.stat().st_size > 0 for path in paths.values())
    assert "<text" in paths["svg"].read_text(encoding="utf-8")
    assert "filename" not in report["source"]
    assert "path" not in report["source"]
    with Image.open(paths["png"]) as image:
        assert image.size[0] in range(392, 395)
        assert image.size[1] in range(274, 277)
        assert image.info["dpi"][0] == pytest.approx(100, abs=0.1)
    with Image.open(paths["tiff"]) as image:
        assert image.mode == "RGB"
        assert image.tag_v2.get(259) == 5
        assert image.info["dpi"] == (100.0, 100.0)


def test_custom_trace_y_and_group_filter(tmp_path: Path) -> None:
    output = tmp_path / "custom"
    result, report = run_plotter(
        EXAMPLE,
        "--output-dir",
        output,
        "--stem",
        "custom",
        "--x",
        "MgO",
        "--y",
        "Rb,Zr",
        "--groups",
        "Series A,Series B",
        "--dpi",
        "90",
    )

    assert result.returncode == 0
    assert report["configuration"]["x"] == "MgO"
    assert report["configuration"]["y"] == ["Rb", "Zr"]
    assert report["configuration"]["groups"] == ["Series A", "Series B"]
    assert report["plot"]["sample_count"] == 6


def test_harker_limits_are_clean_and_do_not_clip() -> None:
    sys.path.insert(0, str(SKILL / "scripts"))
    from plot_geochem_common import clean_linear_limits
    from plot_harker import (
        automatic_columns,
        potentially_mixed_harker_groups,
    )

    limits = clean_linear_limits(pd.Series([7.89, 1437.96]))

    assert limits["lower"] <= 7.89
    assert limits["upper"] >= 1437.96
    assert float(limits["lower"]).is_integer()
    assert float(limits["upper"]).is_integer()
    assert automatic_columns(8) == 4
    assert automatic_columns(6) == 3
    assert automatic_columns(4) == 2
    assert automatic_columns(3) == 3
    assert automatic_columns(9) == 3
    assert potentially_mixed_harker_groups(
        ["Syenite", "Carbonatite suite"]
    ) == ["Carbonatite suite"]
    assert potentially_mixed_harker_groups(["Carbonatite A"]) == []


def test_missing_pair_is_reported_not_imputed(tmp_path: Path) -> None:
    input_path = tmp_path / "missing.csv"
    output = tmp_path / "missing"
    frame = pd.read_csv(EXAMPLE)
    frame.loc[0, "MgO_wt%"] = None
    frame.to_csv(input_path, index=False)

    result, report = run_plotter(
        input_path,
        "--output-dir",
        output,
        "--stem",
        "missing",
        "--y",
        "MgO,CaO",
        "--dpi",
        "90",
    )

    assert result.returncode == 0
    assert report["plot"]["missing_pairs"]["MgO"] == 1
    assert any(item["code"] == "W651" for item in report["issues"])


def test_panel_limits_use_only_complete_xy_pairs(tmp_path: Path) -> None:
    input_path = tmp_path / "unpaired_outlier.csv"
    output = tmp_path / "unpaired_outlier"
    frame = pd.read_csv(EXAMPLE)
    frame.loc[0, "SiO2_wt%"] = None
    frame.loc[0, "MgO_wt%"] = 1000.0
    frame.to_csv(input_path, index=False)

    result, report = run_plotter(
        input_path,
        "--output-dir",
        output,
        "--stem",
        "unpaired_outlier",
        "--y",
        "MgO,CaO",
        "--dpi",
        "90",
    )

    mg_panel = next(
        panel
        for panel in report["plot"]["panels"]
        if panel["y"] == "MgO"
    )
    assert result.returncode == 0
    assert mg_panel["complete_pairs"] == len(frame) - 1
    assert mg_panel["y_limits"]["upper"] < 20


def test_existing_bundle_requires_explicit_overwrite(
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing"
    first, _ = run_plotter(
        EXAMPLE,
        "--output-dir",
        output,
        "--stem",
        "same",
        "--y",
        "MgO,CaO",
        "--dpi",
        "90",
    )
    second, report = run_plotter(
        EXAMPLE,
        "--output-dir",
        output,
        "--stem",
        "same",
        "--y",
        "MgO,CaO",
        "--dpi",
        "90",
    )

    assert first.returncode == 0
    assert second.returncode == 1
    assert report["status"] == "error"


def test_long_group_legend_reflows_inside_figure(tmp_path: Path) -> None:
    input_path = tmp_path / "long_groups.csv"
    output = tmp_path / "long_groups"
    frame = pd.read_csv(EXAMPLE)
    frame["Group"] = [
        "Long alkali feldspar suite",
        "Long alkali feldspar suite",
        "Long nepheline-bearing suite",
        "Long nepheline-bearing suite",
        "Long evolved syenitic suite",
        "Long evolved syenitic suite",
        "Long mixed-lithology review suite",
        "Long mixed-lithology review suite",
        "Long mixed-lithology review suite",
        "Long mixed-lithology review suite",
    ]
    frame.to_csv(input_path, index=False)

    result, report = run_plotter(
        input_path,
        "--output-dir",
        output,
        "--stem",
        "long_groups",
        "--y",
        "MgO,CaO,K2O,P2O5",
        "--dpi",
        "90",
    )

    assert result.returncode == 0
    assert report["plot"]["legend_columns"] == 2
    assert report["plot"]["legend_rows"] == 2
    assert report["plot"]["legend_within_figure"] is True
