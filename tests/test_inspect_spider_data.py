import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "geoskills"
SCRIPT = SKILL / "scripts" / "inspect_spider_data.py"
EXAMPLE = SKILL / "examples" / "synthetic_spider_data.csv"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

from inspect_spider_data import (  # noqa: E402
    OXIDE_ELEMENT_PPM_PER_WT_PERCENT,
    inspect_spider_frame,
    prepare_elemental_ppm_frame,
    read_spider_table,
)


def run_inspector(*arguments: object) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *(str(argument) for argument in arguments)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result, json.loads(result.stdout)


def test_valid_flat_spider_csv_is_ready() -> None:
    result, report = run_inspector(EXAMPLE)

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["shape"] == {"rows": 3, "columns": 30}
    assert report["sample_id_candidates"] == ["Sample"]
    assert report["group_candidates"] == ["Group"]
    recognized = {
        item["element"]: item for item in report["trace_elements"]["recognized"]
    }
    assert recognized["K"]["species"] == "K2O"
    assert recognized["K"]["unit"] == "wt%"
    assert recognized["P"]["species"] == "P2O5"
    assert recognized["Ti"]["species"] == "TiO2"
    assert report["issues"] == []


def test_transposed_supplement_tracks_major_and_trace_units(tmp_path: Path) -> None:
    path = tmp_path / "transposed.xlsx"
    raw = pd.DataFrame(
        [
            ["Rock type", "Suite A", None],
            ["Sample No.", "S1", "S2"],
            ["Major element (wt.%)", None, None],
            ["TiO2", 1.0, 1.2],
            ["K2O", 2.0, 2.2],
            ["P2O5", 0.2, 0.25],
            ["Trace element (ppm)", None, None],
            ["Rb", 30, 35],
            ["Ba", 300, 340],
            ["Th", 5, 6],
            ["U", 1.2, 1.5],
            ["Nb", 14, 16],
            ["Ta", 0.9, 1.0],
            ["La", 20, 22],
        ]
    )
    raw.to_excel(path, index=False, header=False)

    frame, source = read_spider_table(path, None)
    assert frame is not None
    report = inspect_spider_frame(frame, source)

    assert report["status"] == "ready"
    assert source["layout"] == "column_per_sample_transposed"
    assert source["transformation"]["sample_header_row"] == 2
    assert list(frame["Group"]) == ["Suite A", "Suite A"]
    units = {
        item["species"]: item["unit"]
        for item in report["trace_elements"]["recognized"]
    }
    assert units["TiO2"] == "wt%"
    assert units["K2O"] == "wt%"
    assert units["P2O5"] == "wt%"
    assert units["Rb"] == "ppm"


def test_oxide_conversion_uses_declared_stoichiometric_factors() -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S1"],
            "Rb_ppm": [1.0],
            "Ba_ppm": [1.0],
            "Th_ppm": [1.0],
            "U_ppm": [1.0],
            "Nb_ppm": [1.0],
            "K2O_wt%": [1.0],
            "P2O5_wt%": [1.0],
            "TiO2_wt%": [1.0],
        }
    )
    report = inspect_spider_frame(frame, {"filename": "test.csv"})
    elemental, conversions = prepare_elemental_ppm_frame(frame, report)

    assert report["status"] == "ready"
    assert elemental.at[0, "K"] == pytest.approx(
        OXIDE_ELEMENT_PPM_PER_WT_PERCENT["K2O"]
    )
    assert elemental.at[0, "P"] == pytest.approx(
        OXIDE_ELEMENT_PPM_PER_WT_PERCENT["P2O5"]
    )
    assert elemental.at[0, "Ti"] == pytest.approx(
        OXIDE_ELEMENT_PPM_PER_WT_PERCENT["TiO2"]
    )
    assert {item["source_species"] for item in conversions} == {
        "K2O",
        "P2O5",
        "TiO2",
    }


def test_bdl_is_preserved_as_gap_without_blocking() -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S1", "S2"],
            "Rb_ppm": ["bdl", 2.0],
            "Ba_ppm": [1.0, 2.0],
            "Th_ppm": [1.0, 2.0],
            "U_ppm": [1.0, 2.0],
            "Nb_ppm": [1.0, 2.0],
        }
    )
    report = inspect_spider_frame(frame, {"filename": "bdl.csv"})
    elemental, _ = prepare_elemental_ppm_frame(frame, report)

    assert report["status"] == "ready"
    assert any(item["code"] == "W431" for item in report["issues"])
    assert np.isnan(elemental.at[0, "Rb"])


def test_nonpositive_value_blocks_logarithmic_plotting() -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S1"],
            "Rb_ppm": [0],
            "Ba_ppm": [1],
            "Th_ppm": [1],
            "U_ppm": [1],
            "Nb_ppm": [1],
        }
    )
    report = inspect_spider_frame(frame, {"filename": "zero.csv"})

    assert report["status"] == "needs_review"
    assert any(item["code"] == "E432" for item in report["issues"])


def test_direct_element_and_oxide_duplicate_requires_review() -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S1"],
            "Rb_ppm": [1],
            "Ba_ppm": [1],
            "Th_ppm": [1],
            "U_ppm": [1],
            "K_ppm": [1000],
            "K2O_wt%": [1.0],
        }
    )
    report = inspect_spider_frame(frame, {"filename": "duplicate.csv"})

    assert report["status"] == "needs_review"
    duplicate = next(item for item in report["issues"] if item["code"] == "E411")
    assert duplicate["details"]["columns"]["K"] == ["K_ppm", "K2O_wt%"]
