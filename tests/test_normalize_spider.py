import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "geoskills"
SCRIPT = SKILL / "scripts" / "normalize_spider.py"
PM_REFERENCE = (
    SKILL / "assets" / "normalization" / "primitive-mantle-sm89.json"
)
PM_MODIFIED_REFERENCE = (
    SKILL
    / "assets"
    / "normalization"
    / "primitive-mantle-modified-sm89.json"
)
NMORB_REFERENCE = SKILL / "assets" / "normalization" / "nmorb-sm89.json"
EXAMPLE = SKILL / "examples" / "synthetic_spider_data.csv"


def run_normalizer(*arguments: object) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *(str(argument) for argument in arguments)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result, json.loads(result.stdout)


def test_sm89_spider_references_match_table_one_values() -> None:
    pm = json.loads(PM_REFERENCE.read_text(encoding="utf-8"))
    modified = json.loads(PM_MODIFIED_REFERENCE.read_text(encoding="utf-8"))
    nmorb = json.loads(NMORB_REFERENCE.read_text(encoding="utf-8"))

    assert pm["id"] == "PrimitiveMantle_SM89"
    assert pm["source"]["table"] == "Table 1, Primitive mantle column"
    assert pm["values"]["Rb"] == 0.635
    assert pm["values"]["Ba"] == 6.989
    assert pm["values"]["Nb"] == 0.713
    assert pm["values"]["Pb"] == 0.185
    assert pm["values"]["Ti"] == 1300
    assert list(pm["values"]) == pm["element_order"]
    assert "Cs=0.0079" in pm["source"]["note"]
    assert pm["crosscheck"]["release"] == "v0.3.7"

    assert modified["id"] == "PrimitiveMantleModified_SM89"
    assert modified["values"]["Cs"] == 0.0079
    assert modified["values"]["Pb"] == 0.071
    changed = [
        element
        for element in pm["element_order"]
        if pm["values"][element] != modified["values"][element]
    ]
    assert changed == ["Cs", "Pb"]

    assert nmorb["id"] == "NMORB_SM89"
    assert nmorb["source"]["table"] == "Table 1, N-type MORB column"
    assert nmorb["values"]["Rb"] == 0.56
    assert nmorb["values"]["Nb"] == 2.33
    assert nmorb["values"]["Ti"] == 7600
    assert list(nmorb["values"]) == nmorb["element_order"]


def test_reference_values_normalize_to_unity(tmp_path: Path) -> None:
    input_path = tmp_path / "unity.csv"
    output_path = tmp_path / "normalized.csv"
    pm = json.loads(PM_REFERENCE.read_text(encoding="utf-8"))
    elements = ["Rb", "Ba", "Th", "U", "Nb", "Ta", "La"]
    frame = {"Sample": ["REF"]}
    for element in elements:
        frame[f"{element}_ppm"] = [pm["values"][element]]
    pd.DataFrame(frame).to_csv(input_path, index=False)

    result, report = run_normalizer(
        input_path,
        "--output",
        output_path,
        "--reference",
        "pm-sm89",
    )
    normalized = pd.read_csv(output_path)

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["reference"]["id"] == "PrimitiveMantle_SM89"
    assert report["output"]["filename"] == "normalized.csv"
    for element in elements:
        assert normalized.at[0, f"{element}_N"] == pytest.approx(1.0)


def test_reference_switch_changes_ratios(tmp_path: Path) -> None:
    pm_output = tmp_path / "pm.csv"
    nmorb_output = tmp_path / "nmorb.csv"

    pm_result, pm_report = run_normalizer(
        EXAMPLE,
        "--output",
        pm_output,
        "--reference",
        "pm-sm89",
    )
    nmorb_result, nmorb_report = run_normalizer(
        EXAMPLE,
        "--output",
        nmorb_output,
        "--reference",
        "nmorb-sm89",
    )
    pm = pd.read_csv(pm_output)
    nmorb = pd.read_csv(nmorb_output)

    assert pm_result.returncode == 0
    assert nmorb_result.returncode == 0
    assert pm_report["reference"]["id"] == "PrimitiveMantle_SM89"
    assert nmorb_report["reference"]["id"] == "NMORB_SM89"
    assert pm.at[0, "Nb_N"] != pytest.approx(nmorb.at[0, "Nb_N"])
    assert pm_report["oxide_conversions"]


def test_modified_primitive_mantle_is_explicitly_selectable(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "modified.csv"

    result, report = run_normalizer(
        EXAMPLE,
        "--output",
        output_path,
        "--reference",
        "pm-sm89-modified",
    )

    assert result.returncode == 0
    assert report["reference"]["id"] == "PrimitiveMantleModified_SM89"
    assert "footnote-b" in report["reference"]["table"]


def test_existing_output_requires_explicit_overwrite(tmp_path: Path) -> None:
    output_path = tmp_path / "normalized.csv"
    output_path.write_text("keep\n", encoding="utf-8")

    result, report = run_normalizer(EXAMPLE, "--output", output_path)

    assert result.returncode == 1
    assert report["status"] == "error"
    assert output_path.read_text(encoding="utf-8") == "keep\n"
