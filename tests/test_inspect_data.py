import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "geoskills" / "scripts" / "inspect_data.py"
EXAMPLE = ROOT / "skills" / "geoskills" / "examples" / "synthetic_ree_data.csv"


def run_inspector(*arguments: object) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *(str(argument) for argument in arguments)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result, json.loads(result.stdout)


def test_valid_csv_is_ready() -> None:
    result, report = run_inspector(EXAMPLE)

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["shape"] == {"rows": 3, "columns": 16}
    assert report["sample_id_candidates"] == ["Sample"]
    assert report["group_candidates"] == ["Group"]
    assert [item["element"] for item in report["ree"]["recognized"]] == [
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
    assert report["issues"] == []


def test_problem_cells_require_review(tmp_path: Path) -> None:
    input_file = tmp_path / "problem_data.csv"
    input_file.write_text(
        "Sample,La_ppm,Ce_ppm,Pr_ppm\n"
        "A,<0.01,5,1\n"
        "B,2,bad,0\n"
        ",3,7,\n",
        encoding="utf-8",
    )

    result, report = run_inspector(input_file)
    codes = {item["code"] for item in report["issues"]}

    assert result.returncode == 2
    assert report["status"] == "needs_review"
    assert {"E204", "W231", "E231", "E301", "W211"}.issubset(codes)
    assert report["ree"]["recognized"][0]["below_detection_limit"] == 1


def test_tab_delimited_txt_is_detected(tmp_path: Path) -> None:
    input_file = tmp_path / "table.txt"
    input_file.write_text(
        "Sample\tLa_ppm\tCe_ppm\tPr_ppm\nA\t1\t2\t3\n",
        encoding="utf-8",
    )

    result, report = run_inspector(input_file)

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["source"]["delimiter"] == "TAB"


def test_multiple_excel_sheets_need_an_explicit_choice(tmp_path: Path) -> None:
    input_file = tmp_path / "workbook.xlsx"
    frame = pd.DataFrame(
        {"Sample": ["A"], "La_ppm": [1.0], "Ce_ppm": [2.0], "Pr_ppm": [3.0]}
    )
    with pd.ExcelWriter(input_file) as writer:
        frame.to_excel(writer, sheet_name="Data", index=False)
        frame.to_excel(writer, sheet_name="Backup", index=False)

    result, report = run_inspector(input_file)
    selected_result, selected_report = run_inspector(input_file, "--sheet", "Data")

    assert result.returncode == 2
    assert report["status"] == "needs_sheet"
    assert report["source"]["sheet_names"] == ["Data", "Backup"]
    assert selected_result.returncode == 0
    assert selected_report["status"] == "ready"
    assert selected_report["source"]["sheet"] == "Data"


def test_user_can_select_identifier_and_group_columns(tmp_path: Path) -> None:
    input_file = tmp_path / "custom_columns.csv"
    input_file.write_text(
        "Code,RockUnit,La_ppm,Ce_ppm,Pr_ppm\nA-1,Granite,1,2,3\n",
        encoding="utf-8",
    )

    result, report = run_inspector(
        input_file,
        "--sample-column",
        "Code",
        "--group-column",
        "RockUnit",
    )

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["sample_id_candidates"] == ["Code"]
    assert report["group_candidates"] == ["RockUnit"]


def test_transposed_paper_supplement_is_adapted(tmp_path: Path) -> None:
    input_file = tmp_path / "transposed.xlsx"
    raw = pd.DataFrame(
        [
            ["Published supplementary table", None, None, None],
            ["Rock type", "Group A", None, "Group B"],
            ["Sample No.", "S-1", "S-2", "S-3"],
            ["Trace element (ppm)", None, None, None],
            ["La", 0.237, 0.474, 0.711],
            ["Ce", 0.612, 1.224, 1.836],
            ["Pr", 0.095, 0.190, 0.285],
        ]
    )
    raw.to_excel(input_file, index=False, header=False)

    result, report = run_inspector(input_file)

    assert result.returncode == 0
    assert report["status"] == "ready"
    assert report["source"]["layout"] == "column_per_sample_transposed"
    assert report["source"]["transformation"]["sample_header_row"] == 3
    assert report["source"]["transformation"]["group_header_row"] == 2
    assert report["source"]["transformation"]["inferred_unit"] == "ppm"
    assert report["shape"] == {"rows": 3, "columns": 5}
    assert report["sample_id_candidates"] == ["Sample"]
    assert report["group_candidates"] == ["Group"]
    assert [item["element"] for item in report["ree"]["recognized"]] == [
        "La",
        "Ce",
        "Pr",
    ]
