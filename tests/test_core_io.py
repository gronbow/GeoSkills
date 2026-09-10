import hashlib
import sys
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from geoskills_core.errors import InputValidationError


@pytest.mark.parametrize("extension", ["csv", "txt", "xlsx"])
@pytest.mark.parametrize("transpose", [True, False])
def test_duplicate_source_headers_fail_before_silent_renaming(tmp_path, extension, transpose):
    path = tmp_path / f"input.{extension}"
    rows = [["Sample", "private_label", "private_label"], ["S1", 10, 20]]
    if extension == "xlsx":
        pd.DataFrame(rows).to_excel(path, index=False, header=False)
    else:
        separator = "\t" if extension == "txt" else ","
        path.write_text("\n".join(separator.join(map(str, row)) for row in rows), encoding="utf-8")
    options = {} if transpose else {"transposer": None}
    with pytest.raises(InputValidationError) as caught:
        read_table(path, **options)
    assert caught.value.code == "E110"
    assert caught.value.details == {"duplicate_header_count": 1}
    assert "private_label" not in str(caught.value)

from geoskills_core import (  # noqa: E402
    ColumnMapping,
    FileSizeError,
    Severity,
    TextEncodingError,
    UnsupportedFormatError,
    WorksheetError,
    automatic_column_mappings,
    inspect_column_mappings,
    issue,
    match_analyte,
    read_table,
    sniff_text_format,
    status_from_issues,
    validate_column_mappings,
    validate_table_structure,
)


def test_text_sniffer_does_not_allocate_the_whole_file(tmp_path, monkeypatch):
    path = tmp_path / "large.csv"
    path.write_text("Sample,La_ppm\n" + "S1,1\n" * 20000, encoding="utf-8")
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("unbounded file read"))
    assert sniff_text_format(path) == ("utf-8-sig", ",")


def test_csv_metadata_is_share_safe_and_content_addressed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "private-study.csv"
    content = b"Sample,La_ppm,Ce_ppm,Pr_ppm\nS1,1,2,3\n"
    path.write_bytes(content)

    frame, source = read_table(path)

    assert frame is not None
    assert source["filename"] == path.name
    assert source["file_sha256"] == hashlib.sha256(content).hexdigest()
    assert source["size_bytes"] == len(content)
    assert source["format"] == ".csv"
    assert source["encoding"] == "utf-8-sig"
    assert source["delimiter"] == ","
    assert source["layout"] == "row_per_sample"
    assert "path" not in source
    assert str(tmp_path) not in repr(source)


def test_gb18030_tab_text_is_detected_and_read(tmp_path: Path) -> None:
    path = tmp_path / "published-table.txt"
    path.write_bytes(
        "样品\tLa_ppm\tCe_ppm\tPr_ppm\n样品一\t1\t2\t3\n".encode("gb18030")
    )

    encoding, delimiter = sniff_text_format(path)
    frame, source = read_table(path)

    assert encoding == "gb18030"
    assert delimiter == "\t"
    assert frame is not None
    assert frame.iloc[0, 0] == "样品一"
    assert source["delimiter"] == "TAB"


def test_unsupported_encoding_and_format_are_expected_errors(
    tmp_path: Path,
) -> None:
    bad_text = tmp_path / "bad.csv"
    bad_text.write_bytes(b"\xff\xff\xff")
    with pytest.raises(TextEncodingError):
        read_table(bad_text)

    unsupported = tmp_path / "table.xls"
    unsupported.write_bytes(b"legacy")
    with pytest.raises(UnsupportedFormatError) as captured:
        read_table(unsupported)
    assert "path" not in captured.value.details
    assert captured.value.details["filename"] == "table.xls"


def test_file_size_limit_is_checked_before_parsing(tmp_path: Path) -> None:
    path = tmp_path / "large.csv"
    path.write_bytes(b"a,b\n1,2\n")

    with pytest.raises(FileSizeError) as captured:
        read_table(path, max_file_size_bytes=2)

    assert captured.value.details["size_bytes"] == path.stat().st_size


def test_excel_requires_explicit_sheet_when_several_exist(
    tmp_path: Path,
) -> None:
    path = tmp_path / "workbook.xlsx"
    frame = pd.DataFrame({"Sample": ["S1"], "SiO2_wt%": [50.0]})
    with pd.ExcelWriter(path) as writer:
        frame.to_excel(writer, sheet_name="Data", index=False)
        frame.to_excel(writer, sheet_name="Backup", index=False)

    pending, source = read_table(path)
    selected, selected_source = read_table(path, "Data")
    indexed, indexed_source = read_table(path, 1)

    assert pending is None
    assert source["sheet_names"] == ["Data", "Backup"]
    assert selected is not None
    assert selected_source["sheet"] == "Data"
    assert indexed is not None
    assert indexed_source["sheet"] == "Backup"
    with pytest.raises(WorksheetError):
        read_table(path, "Missing")


def test_conservative_transpose_tracks_sections_and_group(
    tmp_path: Path,
) -> None:
    path = tmp_path / "transposed.xlsx"
    pd.DataFrame(
        [
            ["Rock type", "Suite A", None],
            ["Sample No.", "S1", "S2"],
            ["Major element (wt.%)", None, None],
            ["SiO2", 50.0, 52.0],
            ["MgO", 6.0, 4.5],
            ["Trace element (ppm)", None, None],
            ["Rb", 35, 48],
            ["Zr", 120, 145],
        ]
    ).to_excel(path, index=False, header=False)

    frame, source = read_table(path)

    assert frame is not None
    assert source["layout"] == "column_per_sample_transposed"
    assert source["transformation"]["sample_header_row"] == 2
    assert source["transformation"]["group_header_row"] == 1
    assert list(frame["Sample"]) == ["S1", "S2"]
    assert list(frame["Group"]) == ["Suite A", "Suite A"]
    assert {"SiO2_wt%", "MgO_wt%", "Rb_ppm", "Zr_ppm"}.issubset(
        frame.columns
    )


@pytest.mark.parametrize(
    ("header", "canonical", "unit"),
    [
        ("silica (wt.%)", "SiO2", "wt%"),
        ("TFe2O3_wt%", "Fe2O3T", "wt%"),
        ("Rb mg/kg", "Rb", "ppm"),
        ("La_ppm", "La", "ppm"),
        ("H2O+", "H2O+", "unknown"),
        ("H2O-", "H2O-", "unknown"),
    ],
)
def test_analyte_and_unit_aliases_are_exact(
    header: str,
    canonical: str,
    unit: str,
) -> None:
    matched = match_analyte(header)

    assert matched is not None
    assert matched.canonical == canonical
    assert matched.explicit_unit == unit
    assert match_analyte(f"prefix-{header}-suffix") is None


def test_automatic_mapping_requires_explicit_units() -> None:
    mappings = automatic_column_mappings(
        ["Sample", "SiO2_wt%", "La_ppm", "Ce"]
    )
    by_analyte = {item.canonical_analyte: item for item in mappings}

    assert by_analyte["SiO2"].unit == "wt%"
    assert by_analyte["La"].unit == "ppm"
    assert by_analyte["Ce"].unit == "unknown"
    selected, issues = inspect_column_mappings(
        ["Sample", "SiO2_wt%", "La_ppm", "Ce"]
    )
    assert selected == mappings
    assert {item.code for item in issues} == {"E224"}
    assert status_from_issues(issues) == "needs_review"


def test_explicit_mapping_blocks_ambiguity_and_wrong_units() -> None:
    mappings = [
        ColumnMapping("La result A", "La", "ppm"),
        ColumnMapping("La result B", "La", "ppm"),
        ColumnMapping("La result A", "Ce", "unknown"),
        ColumnMapping("Silica", "SiO2", "ppm"),
        ColumnMapping("Mystery", "NotRegistered", "ppm"),
        ColumnMapping("Missing", "Nd", "ppm"),
    ]

    issues = validate_column_mappings(
        mappings,
        available_columns=[
            "La result A",
            "La result B",
            "Silica",
            "Mystery",
        ],
    )
    codes = {item.code for item in issues}

    assert {"E220", "E221", "E222", "E223", "E224", "E225"}.issubset(
        codes
    )
    assert all(item.blocks for item in issues)


def test_issue_and_table_structure_are_json_ready() -> None:
    notice = issue("W001", Severity.WARNING, "Review this value.", row=3)
    frame = pd.DataFrame([[1, 2]], columns=["La_ppm", "La_ppm"])

    structural = validate_table_structure(frame)

    assert notice.to_dict() == {
        "code": "W001",
        "severity": "warning",
        "message": "Review this value.",
        "details": {"row": 3},
    }
    assert notice.blocks is False
    assert structural[0].code == "E202"
