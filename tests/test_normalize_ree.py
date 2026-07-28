import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "geoskills"
SCRIPT = SKILL / "scripts" / "normalize_ree.py"
REFERENCE = SKILL / "assets" / "normalization" / "chondrite-sm89.json"

EXPECTED_SM89 = {
    "La": "0.237",
    "Ce": "0.612",
    "Pr": "0.095",
    "Nd": "0.467",
    "Sm": "0.153",
    "Eu": "0.058",
    "Gd": "0.2055",
    "Tb": "0.0374",
    "Dy": "0.2540",
    "Ho": "0.0566",
    "Er": "0.1655",
    "Tm": "0.0255",
    "Yb": "0.170",
    "Lu": "0.0254",
}


def run_normalizer(*arguments: object) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *(str(argument) for argument in arguments)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result, json.loads(result.stdout)


def test_sm89_reference_matches_source_fixture() -> None:
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))

    assert reference["id"] == "Chondrite_SM89"
    assert reference["unit"] == "ppm"
    assert reference["source"]["table"] == "Table 1, C1 chondrite column"
    assert reference["source"]["doi"] == "10.1144/GSL.SP.1989.042.01.19"
    assert reference["element_order"] == list(EXPECTED_SM89)
    assert reference["values"] == EXPECTED_SM89
    assert reference["verification"]["domain_numeric_review"]["status"] == "confirmed"


def test_ten_times_reference_normalizes_to_ten(tmp_path: Path) -> None:
    input_path = tmp_path / "ten_times.csv"
    output_path = tmp_path / "normalized.csv"
    row = {"Sample": "SYN-10X", "Group": "A"}
    row.update(
        {
            f"{element}_ppm": str(Decimal(value) * Decimal("10"))
            for element, value in EXPECTED_SM89.items()
        }
    )
    pd.DataFrame([row]).to_csv(input_path, index=False)

    result, report = run_normalizer(input_path, "--output", output_path)
    normalized = pd.read_csv(output_path)

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["reference"]["id"] == "Chondrite_SM89"
    assert len(report["output"]["normalized_columns"]) == 14
    for element in EXPECTED_SM89:
        assert normalized.at[0, f"{element}_N"] == pytest.approx(10.0)


def test_missing_value_remains_a_gap(tmp_path: Path) -> None:
    input_path = tmp_path / "missing.csv"
    output_path = tmp_path / "normalized.csv"
    input_path.write_text(
        "Sample,La_ppm,Ce_ppm,Pr_ppm\nA,0.237,,0.095\n",
        encoding="utf-8",
    )

    result, report = run_normalizer(input_path, "--output", output_path)
    normalized = pd.read_csv(output_path)

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert normalized.at[0, "La_N"] == pytest.approx(1.0)
    assert pd.isna(normalized.at[0, "Ce_N"])
    assert normalized.at[0, "Pr_N"] == pytest.approx(1.0)
    assert "W211" in {item["code"] for item in report["issues"]}


def test_non_positive_value_blocks_normalization(tmp_path: Path) -> None:
    input_path = tmp_path / "zero.csv"
    output_path = tmp_path / "must_not_exist.csv"
    input_path.write_text(
        "Sample,La_ppm,Ce_ppm,Pr_ppm\nA,0,0.612,0.095\n",
        encoding="utf-8",
    )

    result, report = run_normalizer(input_path, "--output", output_path)
    inspection_codes = {
        item["code"] for item in report["input_inspection"]["issues"]
    }

    assert result.returncode == 2
    assert report["status"] == "blocked"
    assert "E301" in inspection_codes
    assert not output_path.exists()


def test_existing_output_is_not_silently_replaced(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "existing.csv"
    input_path.write_text(
        "Sample,La_ppm,Ce_ppm,Pr_ppm\nA,0.237,0.612,0.095\n",
        encoding="utf-8",
    )
    output_path.write_text("keep me\n", encoding="utf-8")

    result, report = run_normalizer(input_path, "--output", output_path)

    assert result.returncode == 1
    assert report["status"] == "error"
    assert output_path.read_text(encoding="utf-8") == "keep me\n"
