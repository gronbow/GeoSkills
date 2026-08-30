"""Resource-budget regression tests for untrusted tabular inputs."""

from __future__ import annotations

import struct
import sys
import warnings
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from geoskills_core.errors import InputValidationError  # noqa: E402
from geoskills_core.io import (  # noqa: E402
    TableBudget,
    XlsxArchiveBudget,
    read_table,
)
import geoskills_core.io as io_module  # noqa: E402


CONTENT_TYPES = b"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>
"""
ROOT_RELS = b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""
WORKBOOK = b"""<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets>
</workbook>
"""
WORKBOOK_RELS = b"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
"""
VALID_SHEET = b"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:B2"/>
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>Sample</t></is></c><c r="B1" t="inlineStr"><is><t>La_ppm</t></is></c></row>
    <row r="2"><c r="A2" t="inlineStr"><is><t>S1</t></is></c><c r="B2"><v>1</v></c></row>
  </sheetData>
</worksheet>
"""


def _write_minimal_xlsx(
    path: Path,
    *,
    sheet_xml: bytes = VALID_SHEET,
    extra_entries: list[tuple[str, bytes]] | None = None,
    compression: int = ZIP_STORED,
) -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:")
        with ZipFile(path, "w", compression=compression) as archive:
            archive.writestr("[Content_Types].xml", CONTENT_TYPES)
            archive.writestr("_rels/.rels", ROOT_RELS)
            archive.writestr("xl/workbook.xml", WORKBOOK)
            archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
            archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
            for name, content in extra_entries or []:
                archive.writestr(name, content)


def _mark_first_zip_entry_encrypted(path: Path) -> None:
    payload = bytearray(path.read_bytes())
    local = payload.find(b"PK\x03\x04")
    central = payload.find(b"PK\x01\x02")
    assert local >= 0 and central >= 0
    local_flags = struct.unpack_from("<H", payload, local + 6)[0] | 0x1
    central_flags = struct.unpack_from("<H", payload, central + 8)[0] | 0x1
    struct.pack_into("<H", payload, local + 6, local_flags)
    struct.pack_into("<H", payload, central + 8, central_flags)
    path.write_bytes(payload)


@pytest.mark.parametrize(
    ("content", "budget", "limit_name"),
    [
        (
            "a,b\n1,2\n3,4\n",
            TableBudget(max_rows=2, max_columns=10, max_cells=100, max_field_chars=100),
            "max_rows",
        ),
        (
            "a,b,c\n1,2,3\n",
            TableBudget(max_rows=10, max_columns=2, max_cells=100, max_field_chars=100),
            "max_columns",
        ),
        (
            "a,b\n1,2\n",
            TableBudget(max_rows=10, max_columns=10, max_cells=3, max_field_chars=100),
            "max_cells",
        ),
        (
            "header\n12345\n",
            TableBudget(max_rows=10, max_columns=10, max_cells=100, max_field_chars=4),
            "max_field_chars",
        ),
    ],
)
def test_text_table_budget_blocks_before_pandas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    budget: TableBudget,
    limit_name: str,
) -> None:
    path = tmp_path / "oversized.csv"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(
        io_module.pd,
        "read_csv",
        lambda *args, **kwargs: pytest.fail("pandas must not see rejected input"),
    )

    with pytest.raises(InputValidationError) as captured:
        read_table(path, table_budget=budget)

    assert captured.value.code == "E107"
    assert captured.value.details["limit"] == limit_name
    assert captured.value.details["observed"] > captured.value.details["maximum"]


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (lambda path: _mark_first_zip_entry_encrypted(path), "encrypted_entry"),
        (
            lambda path: _write_minimal_xlsx(
                path,
                extra_entries=[("../outside.xml", b"unsafe")],
            ),
            "unsafe_entry_name",
        ),
        (
            lambda path: _write_minimal_xlsx(
                path,
                extra_entries=[("xl/workbook.xml", WORKBOOK)],
            ),
            "duplicate_entry_name",
        ),
    ],
)
def test_xlsx_rejects_encrypted_or_anomalous_entries_before_openpyxl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutator,
    reason: str,
) -> None:
    path = tmp_path / "unsafe.xlsx"
    _write_minimal_xlsx(path)
    mutator(path)
    monkeypatch.setattr(
        io_module.pd,
        "ExcelFile",
        lambda *args, **kwargs: pytest.fail("openpyxl must not see rejected input"),
    )

    with pytest.raises(InputValidationError) as captured:
        read_table(path)

    assert captured.value.code == "E108"
    assert captured.value.details["reason"] == reason


def test_xlsx_archive_budgets_block_before_openpyxl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "many-parts.xlsx"
    _write_minimal_xlsx(path, extra_entries=[("docProps/a.xml", b"x")])
    monkeypatch.setattr(
        io_module.pd,
        "ExcelFile",
        lambda *args, **kwargs: pytest.fail("openpyxl must not see rejected input"),
    )

    with pytest.raises(InputValidationError) as captured:
        read_table(
            path,
            xlsx_budget=XlsxArchiveBudget(
                max_entries=5,
                max_total_uncompressed_bytes=10_000_000,
                max_single_uncompressed_bytes=10_000_000,
                max_compression_ratio=100.0,
                max_xml_depth=128,
            ),
        )

    assert captured.value.code == "E108"
    assert captured.value.details["reason"] == "entry_count_limit"


def test_xlsx_compression_ratio_is_limited_before_openpyxl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "compressed.xlsx"
    _write_minimal_xlsx(
        path,
        extra_entries=[("docProps/repeated.bin", b"0" * 100_000)],
        compression=ZIP_DEFLATED,
    )
    monkeypatch.setattr(
        io_module.pd,
        "ExcelFile",
        lambda *args, **kwargs: pytest.fail("openpyxl must not see rejected input"),
    )

    with pytest.raises(InputValidationError) as captured:
        read_table(
            path,
            xlsx_budget=XlsxArchiveBudget(
                max_entries=100,
                max_total_uncompressed_bytes=10_000_000,
                max_single_uncompressed_bytes=10_000_000,
                max_compression_ratio=10.0,
                max_xml_depth=128,
            ),
        )

    assert captured.value.code == "E108"
    assert captured.value.details["reason"] == "compression_ratio_limit"


def test_xlsx_table_budget_is_checked_before_openpyxl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "wide.xlsx"
    _write_minimal_xlsx(path)
    monkeypatch.setattr(
        io_module.pd,
        "ExcelFile",
        lambda *args, **kwargs: pytest.fail("openpyxl must not see rejected input"),
    )

    with pytest.raises(InputValidationError) as captured:
        read_table(
            path,
            table_budget=TableBudget(
                max_rows=100,
                max_columns=1,
                max_cells=100,
                max_field_chars=100,
            ),
        )

    assert captured.value.code == "E107"
    assert captured.value.details["limit"] == "max_columns"


def test_xlsx_forbids_xml_entities_before_openpyxl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "entity.xlsx"
    sheet = b"""<?xml version="1.0"?>
<!DOCTYPE worksheet [<!ENTITY payload "unsafe">]>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&payload;</t></is></c></row></sheetData>
</worksheet>
"""
    _write_minimal_xlsx(path, sheet_xml=sheet)
    monkeypatch.setattr(
        io_module.pd,
        "ExcelFile",
        lambda *args, **kwargs: pytest.fail("openpyxl must not see rejected input"),
    )

    with pytest.raises(InputValidationError) as captured:
        read_table(path)

    assert captured.value.code == "E109"
    assert captured.value.details["reason"] == "unsafe_xml"
