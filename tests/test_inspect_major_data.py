import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "geoskills"
SCRIPT = SKILL / "scripts" / "inspect_major_data.py"
EXAMPLE = SKILL / "examples" / "synthetic_major_element_data.csv"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

from inspect_major_data import (  # noqa: E402
    inspect_major_frame,
    prepare_geochem_frame,
    read_major_table,
)


def run_inspector(
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


def test_valid_flat_major_csv_is_ready_and_private() -> None:
    result, report = run_inspector(EXAMPLE)

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["shape"] == {"rows": 10, "columns": 15}
    assert report["sample_id_candidates"] == ["Sample"]
    assert report["group_candidates"] == ["Group"]
    recognized = {
        item["analyte"]: item
        for item in report["analytes"]["recognized"]
    }
    assert recognized["SiO2"]["unit"] == "wt%"
    assert recognized["Rb"]["unit"] == "ppm"
    assert "filename" not in report["source"]
    assert "path" not in report["source"]


def test_transposed_table_tracks_major_and_trace_sections(
    tmp_path: Path,
) -> None:
    path = tmp_path / "supplement.xlsx"
    pd.DataFrame(
        [
            ["Rock type", "Suite A", None],
            ["Sample No.", "S1", "S2"],
            ["Major element (wt.%)", None, None],
            ["SiO2", 50.0, 52.0],
            ["MgO", 6.0, 4.5],
            ["Na2O", 3.0, 3.4],
            ["K2O", 1.0, 1.4],
            ["Trace element (ppm)", None, None],
            ["Rb", 35, 48],
            ["Zr", 120, 145],
        ]
    ).to_excel(path, index=False, header=False)

    frame, source = read_major_table(path, None)
    assert frame is not None
    report = inspect_major_frame(frame, source)

    assert report["status"] == "ready"
    assert source["layout"] == "column_per_sample_transposed"
    assert list(frame["Group"]) == ["Suite A", "Suite A"]
    units = {
        item["analyte"]: item["unit"]
        for item in report["analytes"]["recognized"]
    }
    assert units["SiO2"] == "wt%"
    assert units["Rb"] == "ppm"


def test_unknown_major_unit_requires_review() -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S1", "S2"],
            "SiO2": [50, 52],
            "MgO": [5, 4],
        }
    )
    report = inspect_major_frame(frame, {"format": ".csv"})

    assert report["status"] == "needs_review"
    assert sum(item["code"] == "E621" for item in report["issues"]) == 2


def test_negative_concentration_requires_review() -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S1", "S2"],
            "SiO2_wt%": [50, 52],
            "MgO_wt%": [5, -0.1],
        }
    )
    report = inspect_major_frame(frame, {"format": ".csv"})

    assert report["status"] == "needs_review"
    assert any(item["code"] == "E632" for item in report["issues"])


def test_bdl_trace_value_is_preserved_as_missing() -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S1", "S2"],
            "SiO2_wt%": [50, 52],
            "MgO_wt%": [5, 4],
            "Rb_ppm": ["bdl", 20],
        }
    )
    report = inspect_major_frame(frame, {"format": ".csv"})
    canonical = prepare_geochem_frame(frame, report)

    assert report["status"] == "ready"
    assert any(item["code"] == "W631" for item in report["issues"])
    assert np.isnan(canonical.at[0, "Rb"])


def test_duplicate_canonical_analyte_requires_review() -> None:
    frame = pd.DataFrame(
        {
            "Sample": ["S1", "S2"],
            "SiO2_wt%": [50, 52],
            "silica_wt%": [50, 52],
            "MgO_wt%": [5, 4],
        }
    )
    report = inspect_major_frame(frame, {"format": ".csv"})

    assert report["status"] == "needs_review"
    assert any(item["code"] == "E611" for item in report["issues"])
